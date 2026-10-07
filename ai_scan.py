"""AI scan: an Isolation Forest looks at every waiting payment with no rules and finds the unusual ones.

The checks in guard.py look for problems we described in advance. The AI scan is told nothing about fraud.
It is given nine plain facts about each payment and learns, from the payroll itself, what an ordinary payment
looks like. Payments that are easy to separate from the rest are unusual. The scan reports the unusual payments
the checks did not hold, with the facts that made each one stand out.
"""
import json
import math
import time
from datetime import datetime

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

import guard
import store

TOP_SHARE = 0.01        # at most this share of the payments the checks let through is reported (1 in 100)
MIN_SCORE = 0.60        # model score (0-1) a payment needs before it is reported; ordinary payments score ~0.40
RARE = 0.02             # a fact is "unusual" when no more than 2% of the payroll is as extreme
MIN_AREAS = 2           # one unusual area is the checks' job; the AI scan reports unusual combinations
AREA = {"vs_usual": "amount", "vs_last": "amount", "account_days": "account", "account_new": "account",
        "account_group": "account", "phone_group": "phone", "id_unchecked": "identity", "history": "identity",
        "registered_days": "identity"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_scans (scan_id INTEGER PRIMARY KEY, run_at TEXT, seconds REAL, payrolls INTEGER,
    lines INTEGER, found INTEGER);
CREATE TABLE IF NOT EXISTS ai_findings (scan_id INTEGER, payroll_id INTEGER, payment_id INTEGER, ben TEXT,
    amount REAL, score REAL, top_pct REAL, why_json TEXT);
"""

# fact -> (direction that is suspicious, how to say it). +1: higher is suspicious, -1: lower is suspicious
FACTS = {
    "vs_usual":     (+1, lambda v: f"Paid {v:.1f} times this person's usual amount"),
    "vs_last":      (+1, lambda v: f"{v:.1f} times their last payment"),
    "account_days": (-1, lambda v: f"Bank account opened {v:.0f} days ago"),
    "account_new":  (+1, lambda v: "Paid into a different account than last time"),
    "phone_group":  (+1, lambda v: f"Phone number shared with {v - 1:.0f} other people"),
    "account_group": (+1, lambda v: f"Bank account shared with {v - 1:.0f} other people"),
    "id_unchecked": (+1, lambda v: "ID never verified"),
    "history":      (-1, lambda v: "First payment ever" if v == 0 else f"Only {v:.0f} past payments"),
    "registered_days": (-1, lambda v: f"Registered {v:.0f} days ago"),
}
LOG = {"vs_usual", "vs_last", "account_days", "phone_group", "account_group", "history", "registered_days"}


def facts(scored, ctx, payroll_date):
    """Nine plain facts per payment. scored: the output of guard.score_lines."""
    when = datetime.fromisoformat(payroll_date)
    days = lambda s: s.map(lambda t: (when - datetime.fromisoformat(t)).days if isinstance(t, str) else np.nan)
    own, info = ctx["own"], ctx["ben_info"]
    norm = ctx["project_median"] or ctx["currency_median"] or float(scored["amount"].median())
    usual = scored["expected_own"].where(scored["n_hist"] > 0, norm)
    last = scored["ben"].map(own["last"])
    phone = scored["ben"].map(info["phone"])
    in_payroll = scored.groupby("account")["ben"].transform("nunique")
    f = pd.DataFrame(index=scored.index)
    f["vs_usual"] = (scored["amount"] / usual).replace([np.inf, -np.inf], np.nan).fillna(1.0)
    f["vs_last"] = (scored["amount"] / last).replace([np.inf, -np.inf], np.nan).fillna(1.0)
    f["account_days"] = days(scored["account"].map(ctx["account_opened"]))
    f["account_days"] = f["account_days"].fillna(f["account_days"].median()).fillna(365).clip(lower=0)
    f["account_new"] = ((scored["n_hist"] > 0) & scored["last_account"].map(lambda a: isinstance(a, str))
                        & (scored["account"] != scored["last_account"])).astype(int)
    f["phone_group"] = phone.map(ctx["phone_sizes"]).fillna(1).clip(lower=1)
    f["account_group"] = np.maximum(scored["account"].map(ctx["account_sizes"]).fillna(1), in_payroll.fillna(1))
    f["id_unchecked"] = 1 - scored["ben"].map(info["id_checked"]).fillna(1).astype(int)
    f["history"] = scored["n_hist"].astype(float)
    f["registered_days"] = days(scored["ben"].map(info["created_on"]))
    f["registered_days"] = f["registered_days"].fillna(f["registered_days"].median()).fillna(365).clip(lower=0)
    return f


def suspicious_side(f):
    """Each fact as 'how far past the payroll's ordinary value, in the suspicious direction' (0 = ordinary)."""
    x = pd.DataFrame(index=f.index)
    for k, (direction, _) in FACTS.items():
        v = np.log1p(f[k].astype(float)) if k in LOG else f[k].astype(float)
        x[k] = (direction * (v - v.median())).clip(lower=0)
    return x


def rarity(f):
    """For each payment and fact: the share of the payroll that is at least as extreme in the suspicious direction."""
    r = pd.DataFrame(index=f.index)
    for k, (direction, _) in FACTS.items():
        v = direction * f[k].astype(float)
        r[k] = v.rank(method="max", ascending=False, pct=True)
    return r


def find(scored, ctx, payroll_date):
    """Score every payment; return the unusual ones the checks did not hold, with the reasons they stand out."""
    if len(scored) < 50:
        return scored.iloc[0:0].assign(score=[], top_pct=[], why=[])
    f = facts(scored, ctx, payroll_date)
    x = suspicious_side(f)
    model = IsolationForest(n_estimators=300, max_samples=min(512, len(x)), random_state=7).fit(x.values)
    score = pd.Series(-model.score_samples(x.values), index=x.index)
    released = scored["risk"] < guard.HOLD_AT                # the AI looks for what the checks let through
    top_pct = score[released].rank(ascending=False, pct=True).reindex(score.index)
    rare = rarity(f)
    out = scored.assign(score=score, top_pct=top_pct)
    unusual = [[k for k in rare.loc[i].sort_values().index if rare.at[i, k] <= RARE and x.at[i, k] > 0]
               for i in out.index]
    out["why"] = [[FACTS[k][1](f.at[i, k]) for k in u][:3] for i, u in zip(out.index, unusual)]
    out["areas"] = [len({AREA[k] for k in u}) for u in unusual]
    keep = released & (out["score"] >= MIN_SCORE) & (out["top_pct"] <= TOP_SHARE) & (out["areas"] >= MIN_AREAS)
    return out[keep].sort_values("score", ascending=False)


def run(progress=lambda m: None):
    """Scan every payroll waiting for release and save what the AI found."""
    t0 = time.time()
    store.init()
    with store.connect() as con:
        con.executescript(SCHEMA)
        pending = pd.read_sql_query("SELECT * FROM payrolls WHERE stage = 'pending' ORDER BY created_on", con)
        found, lines = [], 0
        for _, meta in pending.iterrows():
            progress(f"AI scanning {meta['title'] or meta['payroll_number']}")
            rows = pd.read_sql_query("SELECT payment_id, ben, account, amount FROM payments WHERE payroll_id = ?",
                                     con, params=(int(meta["payroll_id"]),))
            ctx = guard.build_context(con, int(meta["project_id"]), meta["currency"], meta["created_on"],
                                      int(meta["payroll_id"]))
            scored = guard.score_lines(rows, ctx, meta["currency"], meta["created_on"])
            lines += len(scored)
            hits = find(scored, ctx, meta["created_on"])
            found += [(int(meta["payroll_id"]), int(h.payment_id), h.ben, float(h.amount), float(h.score),
                       float(h.top_pct), json.dumps(h.why)) for h in hits.itertuples()]
        secs = round(time.time() - t0, 1)
        sid = con.execute("INSERT INTO ai_scans (run_at, seconds, payrolls, lines, found) VALUES (?,?,?,?,?)",
                          (store.now(), secs, len(pending), lines, len(found))).lastrowid
        con.executemany("INSERT INTO ai_findings VALUES (?,?,?,?,?,?,?,?)", [(sid, *r) for r in found])
        store.audit(con, "AI scan", f"{lines:,} payments in {len(pending)} payrolls, {len(found)} unusual found, {secs}s")
    return dict(scan_id=sid, seconds=secs, payrolls=len(pending), lines=lines, found=len(found))


if __name__ == "__main__":
    print(run(print))
