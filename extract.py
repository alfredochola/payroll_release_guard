"""Copy the payroll data from the live Oracle database into guard.db, read-only.

Personal numbers (beneficiary ID, phone, account, caregiver ID) are scrambled the moment they are read.
Names, addresses and fingerprint data are never selected. Staff usernames become codes (U-01, U-02 ...).
"""
import os
import time

import oracledb

import store

QUERIES = {
    "projects": "SELECT id, name, currency FROM project",
    "payrolls": """SELECT id, payroll_number, project_id, currency, total_amount, status, cbs_transaction_status,
                          created_on, created_by, first_approved_by, first_approved_on, second_approved_by,
                          second_approved_on FROM payroll""",
    "payments": """SELECT id, payroll_id, beneficiary_id_no, account_number, caregiver_id_no, amount, credited,
                          is_clawback, cbs_transaction_status FROM payroll_transactions""",
    "beneficiaries": """SELECT b.id, b.beneficiary_id_no, b.project_id, b.status, b.government_validation_status,
                               EXTRACT(YEAR FROM b.date_of_birth), b.mobile_no, b.created_on
                          FROM beneficiary b
                         WHERE b.beneficiary_id_no IN (SELECT DISTINCT beneficiary_id_no FROM payroll_transactions)""",
    "accounts": """SELECT a.beneficiary_id, a.account_number, a.created_on FROM beneficiaries_cbs_accounts a
                    WHERE a.beneficiary_id IN (SELECT b.id FROM beneficiary b WHERE b.beneficiary_id_no IN
                                                (SELECT DISTINCT beneficiary_id_no FROM payroll_transactions))""",
}


def ts(v):
    return v.isoformat(sep=" ", timespec="seconds") if v else None


def fetch(cur, sql, progress, label):
    cur.arraysize = 20000
    cur.execute(sql)
    rows = []
    while True:
        batch = cur.fetchmany()
        if not batch:
            return rows
        rows.extend(batch)
        progress(f"Reading {label}: {len(rows):,} rows")


INDEXES = {"ix_pay_payroll": "payments(payroll_id)", "ix_pay_ben": "payments(ben)",
           "ix_ben": "beneficiaries(ben)", "ix_acc": "accounts(ben)"}      # must match store.SCHEMA
LOCK = store.HERE / "refresh.lock"
STALE_AFTER = 15 * 60          # a lock older than this was left by a crash and is ignored


class AlreadyRefreshing(Exception):
    pass


def reachable(timeout=3):
    """True when the live payroll database answers within a few seconds."""
    store.load_env()
    try:
        with oracledb.connect(user=os.environ["PAY_DB_USER"], password=os.environ["PAY_DB_PASSWORD"],
                              dsn=os.environ["PAY_DB_DSN"], tcp_connect_timeout=timeout) as con:
            con.ping()
        return True
    except Exception:
        return False


def run(progress=print):
    """Copy the live data. Only one copy runs at a time, and the local database is busy for seconds, not minutes."""
    if LOCK.exists() and time.time() - LOCK.stat().st_mtime < STALE_AFTER:
        raise AlreadyRefreshing("A refresh is already running")
    LOCK.write_text(store.now())
    try:
        return _copy(progress)
    finally:
        LOCK.unlink(missing_ok=True)


def _copy(progress):
    store.load_env()
    store.init()
    t0 = time.time()
    progress("Connecting to the live payroll database (read-only)")
    con = oracledb.connect(user=os.environ["PAY_DB_USER"], password=os.environ["PAY_DB_PASSWORD"],
                           dsn=os.environ["PAY_DB_DSN"])
    con.autocommit = False
    cur = con.cursor()
    data = {name: fetch(cur, sql, progress, name) for name, sql in QUERIES.items()}
    con.rollback()
    con.close()

    # scramble everything first, so the local database is only busy for the quick inserts
    progress("Scrambling personal numbers")
    staff = sorted({u for r in data["payrolls"] for u in (r[8], r[9], r[11]) if u})
    code = {u: f"U-{i + 1:02d}" for i, u in enumerate(staff)}
    payrolls = [(r[0], r[1], None, r[2], r[3], r[4], r[5], r[6], ts(r[7]), code.get(r[8]), code.get(r[9]), ts(r[10]),
                 code.get(r[11]), ts(r[12]), "live", "paid") for r in data["payrolls"]]
    payments = [(r[0], r[1], store.scramble(r[2], "B"), store.scramble(r[3], "AC"), store.scramble(r[4], "CG"), r[5],
                 r[6], r[7], r[8], None) for r in data["payments"]]
    ben_of_id, beneficiaries = {}, []
    for r in data["beneficiaries"]:
        ben = store.scramble(r[1], "B")
        ben_of_id[r[0]] = ben
        beneficiaries.append((ben, r[2], r[3], 1 if (r[4] or "").upper() == "DONE" else 0, r[5],
                              store.scramble(r[6], "PH"), ts(r[7]), "live"))
    accounts = [(ben_of_id.get(r[0]), store.scramble(r[1], "AC"), ts(r[2]), "live") for r in data["accounts"]]

    progress("Saving the local copy")
    t_write = time.time()
    db = store.connect()
    try:
        db.execute("BEGIN IMMEDIATE")           # take the write lock once, up front
        # rebuilding the indexes once is about 5 times faster than updating them row by row
        for name in INDEXES:
            db.execute(f"DROP INDEX IF EXISTS {name}")
        # replace the previous live copy; demo payrolls (source='demo') are kept
        db.execute("DELETE FROM payments WHERE payroll_id IN (SELECT payroll_id FROM payrolls WHERE source = 'live')")
        db.execute("DELETE FROM payrolls WHERE source = 'live'")
        db.execute("DELETE FROM beneficiaries WHERE source = 'live'")
        db.execute("DELETE FROM accounts WHERE source = 'live'")
        db.executemany("INSERT OR REPLACE INTO projects VALUES (?,?,?)", data["projects"])
        db.executemany("INSERT INTO payrolls VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", payrolls)
        db.executemany("INSERT INTO payments VALUES (?,?,?,?,?,?,?,?,?,?)", payments)
        db.executemany("INSERT INTO beneficiaries VALUES (?,?,?,?,?,?,?,?)", beneficiaries)
        db.executemany("INSERT INTO accounts VALUES (?,?,?,?)", accounts)
        for name, on in INDEXES.items():
            db.execute(f"CREATE INDEX {name} ON {on}")
        info = {"last_sync": store.now(), "payrolls": len(payrolls), "payments": len(payments),
                "beneficiaries": len(beneficiaries), "seconds": round(time.time() - t0, 1)}
        db.executemany("INSERT OR REPLACE INTO sync_info VALUES (?,?)", [(k, str(v)) for k, v in info.items()])
        store.audit(db, "Copied data from the live database",
                    f"{info['payrolls']} payrolls, {info['payments']:,} payments, {info['beneficiaries']:,} "
                    f"beneficiary records in {info['seconds']}s. Personal numbers scrambled.")
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    info["write_seconds"] = round(time.time() - t_write, 1)
    progress(f"Done: {info['payments']:,} payments copied in {info['seconds']}s")
    return info


if __name__ == "__main__":
    run()
