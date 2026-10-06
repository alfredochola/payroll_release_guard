"""Local copy of the payroll data (SQLite) and small shared helpers."""
import hashlib
import hmac
import os
import secrets
import sqlite3
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent
DB = HERE / "guard.db"
KEY_FILE = HERE / ".guard_key"

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (project_id INTEGER PRIMARY KEY, name TEXT, currency TEXT);
CREATE TABLE IF NOT EXISTS payrolls (payroll_id INTEGER PRIMARY KEY, payroll_number TEXT, title TEXT, project_id INTEGER,
    currency TEXT, total_amount REAL, status TEXT, posted_status TEXT, created_on TEXT, created_by TEXT,
    first_by TEXT, first_on TEXT, second_by TEXT, second_on TEXT, source TEXT, stage TEXT);
CREATE TABLE IF NOT EXISTS payments (payment_id INTEGER PRIMARY KEY, payroll_id INTEGER, ben TEXT, account TEXT,
    caregiver TEXT, amount REAL, credited INTEGER, clawback INTEGER, posted_status TEXT, planted TEXT);
CREATE TABLE IF NOT EXISTS beneficiaries (ben TEXT, project_id INTEGER, status TEXT, id_checked INTEGER,
    birth_year INTEGER, phone TEXT, created_on TEXT, source TEXT);
CREATE TABLE IF NOT EXISTS accounts (ben TEXT, account TEXT, created_on TEXT, source TEXT);
CREATE TABLE IF NOT EXISTS sync_info (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS checks (check_id INTEGER PRIMARY KEY, payroll_id INTEGER, run_at TEXT, seconds REAL,
    lines INTEGER, held_lines INTEGER, held_amount REAL, safe_amount REAL, verdict TEXT, approval_json TEXT);
CREATE TABLE IF NOT EXISTS held (check_id INTEGER, payment_id INTEGER, ben TEXT, amount REAL, expected REAL,
    risk INTEGER, reasons_json TEXT, ai_sentence TEXT);
CREATE TABLE IF NOT EXISTS decisions (id INTEGER PRIMARY KEY, payroll_id INTEGER, check_id INTEGER, payment_id INTEGER,
    decision TEXT, reviewer TEXT, ts TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS audit_log (id INTEGER PRIMARY KEY, ts TEXT, event TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS evaluation (id INTEGER PRIMARY KEY, run_at TEXT, result_json TEXT);
CREATE INDEX IF NOT EXISTS ix_pay_payroll ON payments(payroll_id);
CREATE INDEX IF NOT EXISTS ix_pay_ben ON payments(ben);
CREATE INDEX IF NOT EXISTS ix_ben ON beneficiaries(ben);
CREATE INDEX IF NOT EXISTS ix_acc ON accounts(ben);
CREATE INDEX IF NOT EXISTS ix_held ON held(check_id);
"""


def connect():
    con = sqlite3.connect(DB, timeout=120)     # wait up to 2 minutes for another writer, never fail at once
    con.execute("PRAGMA journal_mode=WAL")
    return con


def init():
    with connect() as con:
        con.executescript(SCHEMA)


def now():
    return datetime.now().isoformat(sep=" ", timespec="seconds")


def audit(con, event, detail=""):
    con.execute("INSERT INTO audit_log (ts, event, detail) VALUES (?,?,?)", (now(), event, detail))


def _key():
    if not KEY_FILE.exists():
        KEY_FILE.write_bytes(secrets.token_bytes(32))
    return KEY_FILE.read_bytes()


_KEY = None


def scramble(value, prefix, length=10):
    """Turn an ID, phone or account number into a stable code. The same input always gives the same code,
    so links between records survive, but the original number cannot be read back."""
    global _KEY
    if value is None or str(value).strip() == "":
        return None
    if _KEY is None:
        _KEY = _key()
    digest = hmac.new(_KEY, str(value).strip().encode(), hashlib.sha256).hexdigest()
    return f"{prefix}-{digest[:length].upper()}"


def load_env():
    env = HERE / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def quality_stats(con):
    """Data-quality numbers for the live copy. Slow on 400,000 payments, so prepare.py saves them once."""
    repeat = con.execute("""SELECT COUNT(*) FROM (SELECT ben FROM payments WHERE payroll_id IN
                             (SELECT payroll_id FROM payrolls WHERE source='live') GROUP BY ben
                             HAVING MIN(payroll_id) <> MAX(payroll_id))""").fetchone()[0]
    bens = con.execute("SELECT COUNT(DISTINCT ben) FROM beneficiaries WHERE source='live'").fetchone()[0]
    checked = con.execute("SELECT COUNT(DISTINCT ben) FROM beneficiaries WHERE source='live' AND id_checked=1").fetchone()[0]
    nophone = con.execute("SELECT COUNT(DISTINCT ben) FROM beneficiaries WHERE source='live' AND phone IS NULL").fetchone()[0]
    no2nd = con.execute("SELECT COUNT(*) FROM payrolls WHERE source='live' AND second_on IS NULL").fetchone()[0]
    return [repeat, bens, checked, nophone, no2nd]
