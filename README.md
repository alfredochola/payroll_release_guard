# AI-Powered Payroll Release Guard

An MVP for the CompuLynx AI Spark Hackathon, 7 October 2026 (Alfred Ochola and Caleb Rubalema).

It checks every payroll **after it is approved and before the money is posted**. Only suspicious payments are held, with a plain-English reason for each. Everyone else is paid on time.

It answers three questions for every payment:
1. **Is the amount right?** It compares the payment with the person's own past payments, the programme's normal amount and the rest of the payroll. Extra zeros (×10, ×100, ×1,000) are named. When most of a payroll moves together, it is treated as one rate change to confirm, not thousands of errors.
2. **Is this a real, separate person?** It looks for phones and bank accounts shared by more people than is normal for the programme, and for a bank account changed just before payday.
3. **Was it properly approved?** It flags the same person approving twice, the creator approving their own payroll, a missing second approval, approvals too fast for the payroll's size, and approvals outside working hours.

## Run it

| When | Do this |
|---|---|
| First time on a computer | Double-click `setup.bat`. It installs the libraries, downloads the AI model, copies the live data (read-only, about 1 minute) and prepares the demo. |
| Before each demo | Double-click `reset_demo.bat`. You get fresh demo payrolls with no decisions made. It uses the local copy, so slow internet does not matter. |
| To show the portal | Double-click `start_demo.bat`. The portal opens at http://localhost:8502. Keep the black window open, minimised. |

The live database login is read from `.env`. That file is never committed.

## How it connects to the database

`extract.py` reads the live Oracle payroll database with SELECT queries only, and saves a local copy (`guard.db`). Beneficiary IDs, phone numbers, account numbers and caregiver IDs are **scrambled as they are read**. Each becomes a code such as `B-1A2B3C4D5E`, which keeps links between records without revealing the number. Names, addresses and fingerprint data are never selected. The portal's **Refresh from live database** button runs the same copy on demand.

## What is in the folder

| File | What it does |
|---|---|
| `extract.py` | Read-only copy from the live database, with personal numbers scrambled |
| `guard.py` | The three checks, the Isolation Forest, the approval review and the verdict |
| `scenarios.py` | A clearly marked demo programme with 6 months of history and 3 October payrolls waiting for release |
| `ai_scan.py` | The AI scan: an Isolation Forest finds unusual combinations in waiting payments, with no rules |
| `evaluate.py` | The accuracy test: 30 test payrolls with known answers, compared with a simple rule |
| `explainer.py` | Optional plain-English sentence from the private AI (Ollama), with a fact check |
| `app.py` | The portal |
| `prepare.py` | Builds the demo state: demo programme, every payroll checked, accuracy test |

## The demo payrolls

| Payroll | Story | What the Guard says |
|---|---|---|
| October 2026 · North | Normal | 🟢 Safe to release |
| October 2026 · South | KES 20,000 instead of 2,000 (one extra zero), KES 200,000 (two extra zeros), a tripled payment, 11 identities on one phone, 3 people paid into one account, an account switched 2 days before payday | 🟡 Release with holds: 18 held, 982 paid on time |
| October 2026 · East top-up | Same person gave both approvals at 02:46, 25 seconds for 800 payments, and one KES 6,000,000 payment (three extra zeros) | 🔴 Hold: approval problem |

The **Found in your test database** section shows what the Guard found in the 109 real payrolls in the live test database: the **SSP 100,000,010 payroll** (paid to 5 people, about 20 million each) and the payrolls with approval problems (same person approved twice, no second approval, or approved by the person who created them).

## Five-minute demo script

The app has four pages: **Release desk**, **AI scan**, **Proof** and **History**.

1. **The problem (30 s).** "Once a payroll is approved, the money goes. Nobody checks each payment for an extra zero, one person hiding behind several identities, or an approval nobody really gave."
2. **Release desk (45 s).** Three October payrolls are waiting. KES 6.3M is held before it leaves; KES 8.4M is safe to release.
3. **South (1.5 min).** Open it. "Release with holds": 18 of 1,000 payments held. Show the KES 200,000 payment ("expected about KES 2,000, likely two extra zeros"), then the **11 people, one phone** card, then **Details** for the payment chart. Press **Release 982 payments**: "Nobody waits because of someone else's error."
4. **East (45 s).** Open it. "The same person approved twice, at 2:46 at night, 25 seconds to check 800 payments." The main button is **Send back for re-approval**.
5. **Their own data (30 s).** Back on the desk, under **Found in your test database**: the SSP 100,000,010 payroll paid to 5 people, and 15 of 109 payrolls with approval problems.
6. **AI scan (1 min).** Open **AI scan** and press **Let AI find anomalies**. "No rules. The AI learns what an ordinary payment looks like and points out what does not fit." It finds 6 payments in South that every check let through: a bank account opened 24 days ago plus 1.8 times the last payment. Neither fact breaks a limit; together they are unusual. Press **Hold** on one. In the practice test it caught 75 of 90 such cases; the checks caught 0, and it flagged no good payments.
7. **Proof (45 s).** 550 anomalies planted in 30 practice payrolls: the Guard caught **512**, the usual "over 10 times the average" check caught **60**, and neither stopped a good payment. Say honestly that this is a practice test.
8. **History (15 s).** Every decision is recorded with who made it. Say: it reads the payroll system and never changes it; names and numbers are scrambled.
9. **Close (15 s).** "The right amount, to the right person, properly approved, before a shilling leaves."

## Honest limits

- The live database is test data, with made-up amounts. Some look-back holds are test artefacts.
- Accuracy is measured on a simulation with known answers. Real-world accuracy will be lower; a pilot on real payrolls is the next step.
- Doubled payments are mostly not held, on purpose: a doubling is often a genuine change.
- The Guard recommends. A person releases or cancels every held payment, and every decision is logged.
