"""Developer helper: print the latest checks and a few held lines for each."""
import json
import sys

import store

with store.connect() as con:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    rows = con.execute("SELECT check_id, payroll_id, verdict, lines, held_lines, held_amount, seconds, approval_json "
                       "FROM checks ORDER BY check_id DESC LIMIT ?", (limit,)).fetchall()
    for cid, pid, v, n, h, amt, secs, a in reversed(rows):
        print(f"\n{pid}: {v}, {h}/{n} held ({amt:,.0f}), {secs}s")
        for sev, text in json.loads(a):
            print(f"   [{sev}] {text}")
        for ben, amount, exp, risk, reasons in con.execute(
                "SELECT ben, amount, expected, risk, reasons_json FROM held WHERE check_id=? ORDER BY risk DESC LIMIT 3",
                (cid,)):
            print(f"   {ben} {amount:,.0f} exp={exp} risk={risk}")
            for r in json.loads(reasons):
                print(f"      - {r['text']}")
