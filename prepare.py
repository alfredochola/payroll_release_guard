"""Get everything ready for a demo: live copy (optional), demo programme, checks on every payroll, accuracy test.

    python prepare.py            fresh demo state using the existing live copy
    python prepare.py --live     copy from the live database first
"""
import json
import sys
import time

import evaluate
import extract
import guard
import scenarios
import store

if __name__ == "__main__":
    t0 = time.time()
    store.init()
    if "--live" in sys.argv or not store.DB.exists() or not store.connect().execute(
            "SELECT COUNT(*) FROM payrolls WHERE source='live'").fetchone()[0]:
        extract.run()
    with store.connect() as con:
        for t in ("checks", "held", "decisions", "evaluation"):
            con.execute(f"DELETE FROM {t}")
        con.execute("""DELETE FROM audit_log WHERE event IN ('Released', 'Cancelled', 'Held the whole payroll',
                       'Sent back for re-approval') OR event LIKE 'Released %'""")
    october = scenarios.build()
    print("Demo programme ready")
    with store.connect() as con:
        ids = [r[0] for r in con.execute("SELECT payroll_id FROM payrolls WHERE source='live' ORDER BY payroll_id")]
    for pid in list(october.values()) + ids:
        r = guard.check(pid)
        print(f"  checked {pid}: {r['lines']:,} payments, {r['held']} held, {r['verdict']}, {r['seconds']}s")
    with store.connect() as con:
        con.execute("INSERT OR REPLACE INTO sync_info VALUES ('quality', ?)", (json.dumps(store.quality_stats(con)),))
    r = evaluate.run(progress=lambda m: None)
    print(f"Accuracy test: Guard recall {r['guard']['recall']:.0%}, precision {r['guard']['precision']:.0%}; "
          f"simple rule recall {r['rule']['recall']:.0%}")
    print(f"Ready in {time.time() - t0:.0f}s")
