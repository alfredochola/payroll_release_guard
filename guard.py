"""The Release Guard: check one payroll before it is posted.

Three checks, each with a plain-English reason:
  1. Amount   - against the person's own past payments, the programme's normal and the rest of the payroll.
  2. People   - shared phones and accounts, and bank details changed since the last payment.
  3. Approval - how the payroll was approved (speed, same person, hour).
An Isolation Forest also looks at each payroll as a whole and adds weight to lines with an unusual mix of details.
Only lines with a clear reason are held; the rest are safe to release.
"""
import json
import math
import time
from datetime import datetime

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

import store

HOLD_AT = 0.60            # a line is held when its combined risk reaches this
OWN_HISTORY_MIN = 1       # past payments needed to use the person's own normal
SWITCH_DAYS = 14          # an account opened this close before payday, replacing an older one, is a switch
OFFICE_HOURS = (7, 19)


# ---------------------------------------------------------------------------- context
_GLOBAL = {}


def global_context(con):
    """Reference data shared by every check. Loaded once, reloaded when the local copy changes."""
    stamp = con.execute("SELECT COALESCE(MAX(value), '') FROM sync_info WHERE key = 'last_sync'").fetchone()[0] + \
        str(con.execute("SELECT COUNT(*) FROM beneficiaries").fetchone()[0])
    if _GLOBAL.get("stamp") == stamp:
        return _GLOBAL
    ben = pd.read_sql_query("SELECT ben, project_id, id_checked, phone, created_on FROM beneficiaries", con)
    acc = pd.read_sql_query("SELECT ben, account, created_on FROM accounts", con).dropna(subset=["account"])
    stats = pd.read_sql_query(
        """SELECT r.payroll_id, r.currency, r.created_on, MAX(p.amount) AS top FROM payments p
            JOIN payrolls r USING (payroll_id) WHERE r.stage = 'paid' GROUP BY r.payroll_id""", con)
    _GLOBAL.clear()
    _GLOBAL.update(stamp=stamp, ben=ben, ben_info=ben.drop_duplicates("ben").set_index("ben"),
                   phone_sizes=ben.dropna(subset=["phone"]).groupby("phone")["ben"].nunique(),
                   account_sizes=acc.groupby("account")["ben"].nunique(),
                   account_opened=pd.read_sql_query(
                       "SELECT account, MIN(created_on) AS opened FROM accounts WHERE account IS NOT NULL "
                       "GROUP BY account", con).set_index("account")["opened"],
                   acc=acc, payroll_stats=stats,
                   norms={})
    return _GLOBAL


def project_norm(sizes, keys, floor):
    """The size of group that is still normal in a programme: larger than 99% of its groups is unusual."""
    s = sizes.reindex(pd.Index(list(keys)).dropna().unique()).dropna()
    return int(max(floor, np.percentile(s, 99))) if len(s) else floor


def build_context(con, project_id, currency, before, exclude_payroll):
    """Everything the checks compare against, using only data from before this payroll."""
    g = global_context(con)
    hist = pd.read_sql_query(
        """SELECT p.ben, p.amount, p.account, r.created_on FROM payments p JOIN payrolls r USING (payroll_id)
            WHERE r.project_id = ? AND r.created_on < ? AND r.payroll_id <> ? AND r.stage = 'paid'""",
        con, params=(project_id, before, exclude_payroll))
    hist = hist.sort_values("created_on")
    own = hist.groupby("ben").agg(n=("amount", "size"), expected=("amount", "median"),
                                  top=("amount", "max"), last_account=("account", "last"), last=("amount", "last"))
    stats = g["payroll_stats"]
    others = stats[stats["payroll_id"] != exclude_payroll]
    earlier = others[(others["currency"] == currency) & (others["created_on"] < before)]
    currency_median = None
    if len(earlier):
        ids = ",".join(str(int(i)) for i in earlier["payroll_id"])
        currency_median = pd.read_sql_query(f"SELECT amount FROM payments WHERE payroll_id IN ({ids}) LIMIT 200000",
                                            con)["amount"].median()
    in_project = g["ben"][g["ben"]["project_id"] == project_id]
    if project_id not in g["norms"]:
        project_accounts = g["acc"][g["acc"]["ben"].isin(in_project["ben"])]["account"]
        g["norms"][project_id] = (project_norm(g["phone_sizes"], in_project["phone"], 3),
                                  project_norm(g["account_sizes"], project_accounts, 1))
    phone_norm, account_norm = g["norms"][project_id]
    return dict(own=own, project_median=float(hist["amount"].median()) if len(hist) else None,
                currency_median=None if currency_median is None or pd.isna(currency_median) else float(currency_median),
                system_max=float(others["top"].max()) if len(others) else 0.0,
                phone_sizes=g["phone_sizes"], phone_norm=phone_norm,
                account_sizes=g["account_sizes"], account_norm=account_norm,
                ben_info=g["ben_info"], account_opened=g["account_opened"])


# ---------------------------------------------------------------------------- scoring helpers
def amount_risk(ratio):
    """1.5x normal is ordinary; 3x is worth a look; 10x and above is almost certainly wrong."""
    return 0.0 if ratio < 1.5 else float(1 - math.exp(-0.7 * (ratio - 1.5)))


def slip_name(ratio):
    for k, words in ((1, "one extra zero"), (2, "two extra zeros"), (3, "three extra zeros"), (4, "four extra zeros")):
        if 0.9 <= ratio / 10 ** k <= 1.1:
            return words
    return None


def money(cur, x):
    return f"{cur} {x:,.0f}" if x >= 10 else f"{cur} {x:,.2f}".rstrip("0").rstrip(".")


def times(r):
    return f"{r:,.0f} times" if r >= 2 else f"{r:.1f} times"


# ---------------------------------------------------------------------------- line checks
def score_lines(lines, ctx, currency, payroll_date):
    """lines: DataFrame(payment_id, ben, account, amount). Returns lines with risk, expected, reasons."""
    df = lines.copy()
    own = ctx["own"]
    df["n_hist"] = df["ben"].map(own["n"]).fillna(0).astype(int)
    df["expected_own"] = df["ben"].map(own["expected"])
    df["last_account"] = df["ben"].map(own["last_account"])
    pay_median = float(df["amount"].median()) if len(df) else 0.0
    norm = ctx["project_median"] or ctx["currency_median"]

    # A programme-wide rate change moves most of the payroll by the same factor. That is one decision to
    # confirm, not thousands of errors, so each payment is then judged against the new rate.
    has_own = (df["n_hist"] >= OWN_HISTORY_MIN) & (df["expected_own"] > 0)
    base = df["expected_own"].where(has_own, norm if norm else np.nan)
    ratios = (df["amount"] / base).replace([np.inf, -np.inf], np.nan).dropna()
    rate, notes = 1.0, []
    if len(ratios) >= 5:
        m = float(ratios.median())
        moved = int(((ratios / m - 1).abs() <= 0.1).sum()) if m > 0 else 0
        if m > 0 and abs(math.log(m)) > math.log(1.2) and moved >= 0.5 * len(ratios):
            rate = m
            example = df.loc[ratios.index[(ratios / m - 1).abs() <= 0.1][0]]
            before = base[example.name]
            notes.append(("warning", f"New rate: {moved:,} of {len(df):,} payments are about {times(m)} the "
                                     f"usual amount (for example {money(currency, before)} to "
                                     f"{money(currency, example['amount'])}). Confirm this rate change was approved."))
    df.attrs["notes"] = notes
    at_rate = "" if rate == 1.0 else " at the new rate"

    out_risk, out_reasons, out_expected = [], [], []
    phone_sizes, account_sizes = ctx["phone_sizes"], ctx["account_sizes"]
    in_payroll_account = df.groupby("account")["ben"].transform("nunique")
    for i, r in enumerate(df.itertuples(index=False)):
        reasons, parts = [], []
        amt = float(r.amount)

        # 1. amount
        if r.n_hist >= OWN_HISTORY_MIN and r.expected_own and r.expected_own > 0:
            expected = float(r.expected_own) * rate
            ratio = amt / expected
            slip = slip_name(ratio)
            confidence = min(1.0, 0.5 + 0.1 * r.n_hist)       # 1 past payment: 0.6, 5 or more: 1.0
            p = max(amount_risk(ratio) * confidence, 0.9 if slip else 0.0)
            if p >= 0.2:
                reasons.append(dict(check="Amount", weight=p, text=(
                    f"Expected about {money(currency, expected)}{at_rate} from {r.n_hist} past "
                    f"payment{'s' if r.n_hist > 1 else ''}. This one is {money(currency, amt)}, {times(ratio)} more"
                    + (f", likely {slip}." if slip else "."))))
                parts.append(p)
        else:
            expected = norm * rate if norm else pay_median
            if norm is None and ctx["system_max"] > 0 and amt > 10 * ctx["system_max"]:
                ratio = amt / ctx["system_max"]
                reasons.append(dict(check="Amount", weight=0.97, text=(
                    f"No payment history for this programme or currency. {money(currency, amt)} is "
                    f"{times(ratio)} the largest payment this system has ever made ({ctx['system_max']:,.0f}).")))
                parts.append(0.97)
                expected = None
            elif expected:
                ratio = amt / expected
                slip = slip_name(ratio)
                p = max(amount_risk(ratio) * 0.85, 0.85 if slip else 0.0)   # less certain without own history
                if p >= 0.2:
                    reasons.append(dict(check="Amount", weight=p, text=(
                        f"First payment to this person. {money(currency, amt)} is {times(ratio)} the programme's "
                        f"usual {money(currency, expected)}{at_rate}" + (f", likely {slip}." if slip else "."))))
                    parts.append(p)
        if pay_median > 0 and amt >= 10 * pay_median and not any(x["check"] == "Amount" for x in reasons):
            reasons.append(dict(check="Amount", weight=0.9, text=(
                f"{times(amt / pay_median)} the typical payment in this payroll ({money(currency, pay_median)}).")))
            parts.append(0.9)

        # 2. people
        info = ctx["ben_info"].loc[r.ben] if r.ben in ctx["ben_info"].index else None
        phone = info["phone"] if info is not None else None
        group = int(phone_sizes.get(phone, 1)) if phone else 1
        if group > ctx["phone_norm"]:
            p = 0.45 if group < 2 * ctx["phone_norm"] else 0.85
            reasons.append(dict(check="People", weight=p, phone=phone, text=(
                f"Shares one phone number with {group - 1} other beneficiaries. In this programme, normally no "
                f"more than {ctx['phone_norm']} people share a phone.")))
            parts.append(p)
        shared = max(int(account_sizes.get(r.account, 1)) if r.account else 1, int(in_payroll_account.iloc[i]))
        if shared > ctx["account_norm"]:
            other = "1 other beneficiary uses" if shared == 2 else f"{shared - 1} other beneficiaries use"
            usual = "person uses" if ctx["account_norm"] == 1 else "people use"
            reasons.append(dict(check="People", weight=0.85, text=(
                f"Paid into a bank account that {other} too. In this programme, normally no more than "
                f"{ctx['account_norm']} {usual} one account.")))
            parts.append(0.85)
        if r.n_hist and isinstance(r.last_account, str) and r.account and r.account != r.last_account:
            opened = ctx["account_opened"].get(r.account)
            if opened:
                days = (datetime.fromisoformat(payroll_date) - datetime.fromisoformat(opened)).days
                if 0 <= days <= SWITCH_DAYS:
                    reasons.append(dict(check="People", weight=0.65, text=(
                        f"Bank account changed {days} day{'s' if days != 1 else ''} before this payroll. "
                        f"Earlier payments went to a different account.")))
                    parts.append(0.65)

        risk = 1 - np.prod([1 - p for p in parts]) if parts else 0.0
        if reasons and info is not None and not int(info["id_checked"] or 0):
            reasons.append(dict(check="Context", weight=0, text="Identity never confirmed with the national ID check."))
        out_risk.append(risk)
        out_reasons.append(reasons)
        out_expected.append(expected)

    df["risk"] = out_risk
    df["reasons"] = out_reasons
    df["expected"] = out_expected
    df = add_model_signal(df)
    return df


def add_model_signal(df):
    """Isolation Forest over the whole payroll: lines with an unusual mix of details get extra weight.
    It never holds a line on its own; it strengthens lines that already have a reason."""
    if len(df) < 50:
        df["model"] = 0.0
        return df
    ratio = (df["amount"] / df["expected"].replace(0, np.nan).fillna(df["amount"].median())).clip(lower=1e-6)
    feats = np.column_stack([np.log10(ratio), np.log10(df["amount"].clip(lower=1e-6) / max(df["amount"].median(), 1e-6)),
                             df["n_hist"].clip(upper=24), df["reasons"].map(len)])
    model = IsolationForest(n_estimators=150, random_state=7).fit(feats)
    score = -model.score_samples(feats)
    pct = pd.Series(score).rank(pct=True).values
    df["model"] = np.where(pct >= 0.995, 0.35, 0.0)
    boost = (df["model"] > 0) & (df["reasons"].map(len) > 0)
    df.loc[boost, "risk"] = 1 - (1 - df.loc[boost, "risk"]) * (1 - df.loc[boost, "model"])
    return df


# ---------------------------------------------------------------------------- approval check
def approval_review(meta, n_lines):
    """Look at how the payroll was approved. Returns a list of findings (severity, text)."""
    out = []
    fmt = lambda s: datetime.fromisoformat(s) if s else None
    created, first, second = fmt(meta["created_on"]), fmt(meta["first_on"]), fmt(meta["second_on"])
    plausible = 30 + 0.1 * n_lines          # very generous: 30 seconds plus a tenth of a second per payment
    if meta["first_by"] and meta["second_by"] and meta["first_by"] == meta["second_by"]:
        out.append(("critical", f"The same person ({meta['first_by']}) gave both approvals."))
    if meta["created_by"] and meta["created_by"] in (meta["first_by"], meta["second_by"]):
        out.append(("critical", f"The person who created the payroll ({meta['created_by']}) also approved it."))
    if not second:
        out.append(("critical", "There is no second approval."))
    for label, start, end in (("First approval", created, first), ("Second approval", first, second)):
        if start and end:
            secs = (end - start).total_seconds()
            if 0 <= secs < plausible:
                took = f"{secs:,.0f} seconds" if secs < 120 else f"{secs / 60:,.0f} minutes"
                out.append(("warning", f"{label} took only {took} to check {n_lines:,} payments."))
    for label, when in (("First", first), ("Second", second)):
        if when and not (OFFICE_HOURS[0] <= when.hour < OFFICE_HOURS[1]):
            out.append(("warning", f"{label} approval was given at {when:%H:%M} at night."
                        if when.hour < 5 or when.hour >= 21 else
                        f"{label} approval was given at {when:%H:%M}, outside working hours."))
    return out


def verdict(held_amount, total, approval):
    if any(s == "critical" for s, _ in approval) or (total and held_amount / total >= 0.25):
        return "red"
    if held_amount > 0 or approval:
        return "amber"
    return "green"


# ---------------------------------------------------------------------------- run a check
def check(payroll_id, progress=lambda m: None):
    t0 = time.time()
    with store.connect() as con:
        meta = pd.read_sql_query("SELECT * FROM payrolls WHERE payroll_id = ?", con, params=(payroll_id,)).iloc[0]
        lines = pd.read_sql_query("SELECT payment_id, ben, account, amount FROM payments WHERE payroll_id = ?",
                                  con, params=(payroll_id,))
        progress(f"Learning normal payments for programme {meta['project_id']}")
        ctx = build_context(con, int(meta["project_id"]), meta["currency"], meta["created_on"], payroll_id)
        progress(f"Checking {len(lines):,} payments")
        scored = score_lines(lines, ctx, meta["currency"], meta["created_on"])
        approval = approval_review(meta, len(lines)) + scored.attrs.get("notes", [])
        held = scored[scored["risk"] >= HOLD_AT]
        held_amount, total = float(held["amount"].sum()), float(scored["amount"].sum())
        v = verdict(held_amount, total, approval)
        secs = round(time.time() - t0, 2)
        cid = con.execute("INSERT INTO checks (payroll_id, run_at, seconds, lines, held_lines, held_amount, safe_amount,"
                          " verdict, approval_json) VALUES (?,?,?,?,?,?,?,?,?)",
                          (payroll_id, store.now(), secs, len(scored), len(held), held_amount, total - held_amount, v,
                           json.dumps(approval))).lastrowid
        con.executemany("INSERT INTO held VALUES (?,?,?,?,?,?,?,?)", [
            (cid, int(r.payment_id), r.ben, float(r.amount), None if r.expected is None or pd.isna(r.expected)
             else float(r.expected), int(round(100 * r.risk)), json.dumps(r.reasons), None)
            for r in held.itertuples(index=False)])
        store.audit(con, "Payroll checked",
                    f"Payroll {meta['payroll_number'] or payroll_id}: {len(scored):,} payments, {len(held)} held "
                    f"({meta['currency']} {held_amount:,.0f}), verdict {v}, {secs}s")
    return dict(check_id=cid, seconds=secs, lines=len(scored), held=len(held), held_amount=held_amount, verdict=v)


def simple_rule(lines):
    """The baseline most teams would build: flag any payment above 10 times the payroll average."""
    return lines["amount"] > 10 * lines["amount"].mean()


if __name__ == "__main__":
    import sys
    store.init()
    for pid in (int(a) for a in sys.argv[1:]):
        print(pid, check(pid, progress=print))
