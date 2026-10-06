"""Measure accuracy on a scored test set, against a simple rule.

There are no confirmed fraud cases in the test database, so we build test payrolls whose answers we know:
real demo-programme history, a fresh October payroll, and planted problems of different difficulty.
Look-alikes that are NOT problems are planted too (genuine raises, households sharing a phone, caregiver
accounts), so false alarms are measured, not just catches.
"""
import json
import random
import time

import numpy as np
import pandas as pd

import guard
import scenarios
import store

TRIALS, LINES = 30, 600
POSITIVE = {  # case type -> (difficulty, how it is planted)
    "One extra zero (x10)": "easy", "Two extra zeros (x100)": "easy", "Three extra zeros (x1,000)": "easy",
    "Inflated x5": "subtle", "Inflated x3": "subtle", "Doubled (x2)": "hard",
    "Linked identities (one phone)": "subtle", "Shared account (3 people)": "subtle",
    "Account switched before payday": "subtle",
}
DECOY = ["Genuine raise (+KES 2,000)", "Household sharing a phone", "Caregiver account for two"]


def run(progress=print):
    rng = random.Random(7)
    t0 = time.time()
    with store.connect() as con:
        base_ctx = guard.build_context(con, scenarios.PROJECT, "KES", "2026-10-05 09:00:00", -1)
        sept = pd.read_sql_query(
            """SELECT p.ben, p.account, p.amount FROM payments p JOIN payrolls r USING (payroll_id)
                WHERE r.source = 'demo' AND r.stage = 'paid' AND r.payroll_number LIKE 'PN-D6%'
                  AND p.ben NOT IN (SELECT ben FROM payments WHERE planted IS NOT NULL)""", con)
    phone_of = base_ctx["ben_info"]["phone"]
    phone_sizes = base_ctx["phone_sizes"]
    household = [b for b in sept["ben"] if phone_sizes.get(phone_of.get(b), 1) in (2, 3)]
    caregiver = sept.groupby("account")["ben"].transform("nunique")
    caregiver_bens = set(sept.loc[caregiver == 2, "ben"])

    rows = []                                 # one row per test line: truth, guard flag, rule flag, case, excess
    for t in range(TRIALS):
        progress(f"Test payroll {t + 1} of {TRIALS}")
        lines = sept.sample(LINES, random_state=t).reset_index(drop=True)
        lines["payment_id"] = range(len(lines))
        lines["truth"], lines["case"], lines["excess"] = 0, "Normal payment", 0.0
        ctx = dict(base_ctx)
        ctx["phone_sizes"] = phone_sizes.copy()
        ctx["account_sizes"] = base_ctx["account_sizes"].copy()
        ctx["account_opened"] = base_ctx["account_opened"].copy()
        ben_info = base_ctx["ben_info"]
        changed_phone = {}
        free = list(rng.sample(range(LINES), LINES))

        def take(k=1):
            return [free.pop() for _ in range(k)]

        for case, factor in (("One extra zero (x10)", 10), ("Two extra zeros (x100)", 100),
                             ("Three extra zeros (x1,000)", 1000), ("Inflated x5", 5), ("Inflated x3", 3),
                             ("Doubled (x2)", 2)):
            for i in take():
                normal = lines.at[i, "amount"]
                lines.loc[i, ["amount", "truth", "case", "excess"]] = [normal * factor, 1, case, normal * (factor - 1)]
        ring = take(rng.randint(5, 12))
        ring_phone = f"PH-RING{t}"
        ctx["phone_sizes"][ring_phone] = len(ring)
        for i in ring:
            changed_phone[lines.at[i, "ben"]] = ring_phone
            lines.loc[i, ["truth", "case"]] = [1, "Linked identities (one phone)"]
        shared = take(3)
        acc = f"AC-SHARED{t}"
        ctx["account_sizes"][acc] = 3
        for i in shared:
            lines.loc[i, ["account", "truth", "case"]] = [acc, 1, "Shared account (3 people)"]
        i = take()[0]
        new_acc = f"AC-NEW{t}"
        ctx["account_sizes"][new_acc] = 1
        ctx["account_opened"][new_acc] = "2026-10-02 15:00:00"
        lines.loc[i, ["account", "truth", "case"]] = [new_acc, 1, "Account switched before payday"]
        for i in take(4):                                  # genuine raises: look unusual, are fine
            lines.loc[i, ["amount", "case"]] = [lines.at[i, "amount"] + 2000, "Genuine raise (+KES 2,000)"]
        for i in range(LINES):
            b = lines.at[i, "ben"]
            if lines.at[i, "case"] == "Normal payment" and b in household:
                lines.at[i, "case"] = "Household sharing a phone"
            elif lines.at[i, "case"] == "Normal payment" and b in caregiver_bens:
                lines.at[i, "case"] = "Caregiver account for two"
        if changed_phone:
            info = ben_info.loc[ben_info.index.intersection(list(changed_phone))].copy()
            info["phone"] = info.index.map(changed_phone)
            ctx["ben_info"] = pd.concat([ben_info.drop(info.index), info])

        scored = guard.score_lines(lines[["payment_id", "ben", "account", "amount"]], ctx, "KES", "2026-10-05 09:00:00")
        lines["guard"] = (scored["risk"] >= guard.HOLD_AT).astype(int).values
        lines["rule"] = guard.simple_rule(lines).astype(int).values
        rows.append(lines[["truth", "case", "excess", "guard", "rule", "amount"]])

    res = pd.concat(rows, ignore_index=True)

    def metrics(col):
        tp = int(((res[col] == 1) & (res["truth"] == 1)).sum())
        fp = int(((res[col] == 1) & (res["truth"] == 0)).sum())
        fn = int(((res[col] == 0) & (res["truth"] == 1)).sum())
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        excess = res.loc[res["truth"] == 1, "excess"].sum()
        caught = res.loc[(res["truth"] == 1) & (res[col] == 1), "excess"].sum()
        return dict(tp=tp, fp=fp, fn=fn, precision=precision, recall=recall, f1=f1,
                    false_alarms_per_10k=10000 * fp / int((res["truth"] == 0).sum()),
                    money_caught_pct=float(caught / excess) if excess else 0.0)

    by_case = []
    for case, group in res.groupby("case"):
        positive = case in POSITIVE
        by_case.append(dict(case=case, kind="problem" if positive else "look-alike (not a problem)",
                            difficulty=POSITIVE.get(case, "-"), lines=len(group),
                            guard=float(group["guard"].mean()), rule=float(group["rule"].mean())))
    result = dict(trials=TRIALS, lines=len(res), problems=int(res["truth"].sum()),
                  guard=metrics("guard"), rule=metrics("rule"), by_case=by_case,
                  seconds=round(time.time() - t0, 1))
    with store.connect() as con:
        con.execute("INSERT INTO evaluation (run_at, result_json) VALUES (?,?)", (store.now(), json.dumps(result)))
        store.audit(con, "Accuracy test run",
                    f"{TRIALS} test payrolls, {len(res):,} payments, {result['problems']} planted problems. "
                    f"Guard recall {result['guard']['recall']:.0%}, precision {result['guard']['precision']:.0%}; "
                    f"simple rule recall {result['rule']['recall']:.0%}.")
    return result


if __name__ == "__main__":
    r = run(progress=lambda m: None)
    for k in ("guard", "rule"):
        m = r[k]
        print(f"{k:6} precision {m['precision']:.1%} recall {m['recall']:.1%} F1 {m['f1']:.2f} "
              f"false alarms/10k {m['false_alarms_per_10k']:.1f} money caught {m['money_caught_pct']:.1%}  "
              f"(tp {m['tp']}, fp {m['fp']}, fn {m['fn']})")
    for c in r["by_case"]:
        print(f"   {c['case']:34} {c['kind']:27} n={c['lines']:5}  guard {c['guard']:.0%}  rule {c['rule']:.0%}")
    print("seconds", r["seconds"])
