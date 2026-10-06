"""A realistic demo programme added next to the live copy, clearly marked as demo data.

The live test data mostly pays 1 or 10 KES, so it cannot show realistic amounts. This programme has six months
of normal monthly history and three October payrolls waiting for release:
  North  - clean, should be released in full
  South  - planted problems in individual payments, should release with holds
  East   - planted approval problems and one huge payment, should be held
Every planted problem is recorded in payments.planted so the demo can be checked against the right answer.
"""
import random
from datetime import datetime, timedelta

import store

PROJECT = 9001
PROJECT_NAME = "Demo · Older Persons Cash Transfer"
REGIONS = {"North": 1000, "South": 1000, "East": 800}
TIERS = [(2000, 0.6), (4000, 0.3), (6000, 0.1)]       # monthly amount by household size
MONTHS = ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09"]
STAFF = ["U-41", "U-42", "U-43", "U-44", "U-45", "U-46"]
rng = random.Random(2026)


def code(kind, i):
    return store.scramble(f"demo-{kind}-{i}", {"ben": "B", "phone": "PH", "acc": "AC"}[kind])


def tier():
    x, acc = rng.random(), 0
    for amount, p in TIERS:
        acc += p
        if x <= acc:
            return amount
    return TIERS[-1][0]


def build():
    store.init()
    with store.connect() as con:
        old = [r[0] for r in con.execute("SELECT payroll_id FROM payrolls WHERE source = 'demo'")]
        if old:
            ids = ",".join(map(str, old))
            con.execute(f"DELETE FROM payments WHERE payroll_id IN ({ids})")
            con.execute(f"DELETE FROM held WHERE check_id IN (SELECT check_id FROM checks WHERE payroll_id IN ({ids}))")
            con.execute(f"DELETE FROM checks WHERE payroll_id IN ({ids})")
            con.execute(f"DELETE FROM decisions WHERE payroll_id IN ({ids})")
        for t in ("payrolls", "beneficiaries", "accounts"):
            con.execute(f"DELETE FROM {t} WHERE source = 'demo'")
        con.execute("INSERT OR REPLACE INTO projects VALUES (?,?,?)", (PROJECT, PROJECT_NAME, "KES"))

        # people: households share phones (2-3 people), a few caregivers receive for two people
        people, n = [], 0
        for region, size in REGIONS.items():
            for _ in range(size):
                n += 1
                people.append(dict(i=n, region=region, ben=code("ben", n), amount=tier(),
                                   phone=code("phone", n), account=code("acc", n), id_checked=rng.random() < 0.85))
        for k in range(0, len(people) - 3, 9):             # about one in nine shares a phone with family
            for j in range(1, rng.choice([2, 2, 3])):
                people[k + j]["phone"] = people[k]["phone"]
        for k in range(4, len(people) - 1, 23):            # a caregiver account for two people
            people[k + 1]["account"] = people[k]["account"]
        by_region = {r: [p for p in people if p["region"] == r] for r in REGIONS}

        payroll_id = 900001
        payments = []

        def payroll(region, month, stage, created, first, second, first_by, second_by, title, number):
            nonlocal payroll_id
            pid = payroll_id
            payroll_id += 1
            con.execute("INSERT INTO payrolls VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (pid, number, title, PROJECT, "KES", 0, "Active", "Success" if stage == "paid" else "Pending",
                         created, "U-41" if region != "East" else "U-43", first_by, first, second_by, second, "demo", stage))
            return pid

        # six months of normal history
        for m, month in enumerate(MONTHS):
            for r, region in enumerate(REGIONS):
                day = datetime.fromisoformat(f"{month}-05 09:{10 + 7 * r:02d}:00")
                first = day + timedelta(hours=rng.uniform(2, 5))
                second = first + timedelta(hours=rng.uniform(18, 26))
                pid = payroll(region, month, "paid", str(day), str(first), str(second), STAFF[1 + r % 3],
                              STAFF[3 + (r + 1) % 3], f"{datetime.fromisoformat(month + '-01'):%B %Y} · {region}",
                              f"PN-D{m + 1}{r + 1}")
                for p in by_region[region]:
                    amount = p["amount"]
                    if month == "2026-09" and rng.random() < 0.02:     # a few genuine changes, e.g. a larger household
                        p["amount"] = amount = amount + 2000
                    payments.append((pid, p["ben"], p["account"], amount, None))

        # October payrolls waiting for release
        oct_day = "2026-10-05"
        north = payroll("North", "2026-10", "pending", f"{oct_day} 09:10:00", f"{oct_day} 12:41:00", "2026-10-06 10:05:00",
                        "U-42", "U-45", "October 2026 · North", "PN-D71")
        south = payroll("South", "2026-10", "pending", f"{oct_day} 09:17:00", f"{oct_day} 13:02:00", "2026-10-06 09:48:00",
                        "U-43", "U-46", "October 2026 · South", "PN-D72")
        east = payroll("East", "2026-10", "pending", "2026-10-06 02:46:10", "2026-10-06 02:46:35", "2026-10-06 02:47:02",
                       "U-44", "U-44", "October 2026 · East top-up", "PN-D73")
        october = {"North": north, "South": south, "East": east}
        plants = {}
        south_people = by_region["South"]
        for idx, (kind, factor) in enumerate([("one extra zero", 10), ("two extra zeros", 100), ("tripled amount", 3)]):
            plants[south_people[40 + idx * 50]["ben"]] = (kind, factor)
        ring = south_people[300:311]                      # 11 identities behind one phone
        ring_phone = code("phone", "ring-South")
        for p in ring:
            p["phone"] = ring_phone
            plants[p["ben"]] = ("linked identities", 1)
        switched = south_people[520]
        old_account = switched["account"]
        switched["account"] = code("acc", "switched-520")
        plants[switched["ben"]] = ("account switched", 1)
        shared_acc = code("acc", "shared-South")
        for p in south_people[700:703]:
            p["account"] = shared_acc
            plants[p["ben"]] = ("shared account", 1)
        plants[by_region["East"][77]["ben"]] = ("three extra zeros", 1000)

        for region, pid in october.items():
            for p in by_region[region]:
                kind, factor = plants.get(p["ben"], (None, 1))
                payments.append((pid, p["ben"], p["account"], p["amount"] * factor, kind))

        con.executemany("INSERT INTO payments (payroll_id, ben, account, amount, planted) VALUES (?,?,?,?,?)", payments)
        con.execute("UPDATE payrolls SET total_amount = (SELECT SUM(amount) FROM payments p WHERE p.payroll_id = "
                    "payrolls.payroll_id) WHERE source = 'demo'")
        con.executemany("INSERT INTO beneficiaries VALUES (?,?,?,?,?,?,?,?)", [
            (p["ben"], PROJECT, "Active", int(p["id_checked"]), rng.randint(1940, 1962), p["phone"],
             "2026-03-01 10:00:00", "demo") for p in people])
        accounts = [(p["ben"], p["account"], "2026-03-01 10:00:00", "demo") for p in people]
        accounts.append((switched["ben"], old_account, "2026-03-01 10:00:00", "demo"))
        accounts = [a if a[1] != switched["account"] else (a[0], a[1], "2026-10-03 16:20:00", "demo") for a in accounts]
        con.executemany("INSERT INTO accounts VALUES (?,?,?,?)", accounts)
        store.audit(con, "Demo programme created",
                    f"{PROJECT_NAME}: {len(people):,} people, 6 months of history, 3 October payrolls waiting for release")
    return october


if __name__ == "__main__":
    print(build())
