# Pilot results log

The record that Phase 6 (50 phone-to-paper jobs checked against the paper, every drill recorded, zero duplicates, zero "completed" without paper) and Phase 8 (50 to 100 real customer jobs, every support intervention logged, three working days without help) ask for. Fill it in by hand at the counter; type it up the same evening. An empty cell means "not checked", so write N or a dash when you did check.

## 1. Setup record (once)

| | |
|---|---|
| Shop name and code | |
| Date installed | |
| Shop PC: name, Windows version | |
| Printer: make and model | |
| Printer driver name (Windows, Printer properties, Advanced) | |
| Connection (USB / network cable / Wi-Fi) | |
| Second (colour) printer, if any | |
| AutoPrint version (Settings, "Version") | |
| Installer hash matched the `.sha256.txt` (Y/N) | |
| Windows or antivirus warning: exact text | |
| Minutes from starting the installer to the test page on paper (target under 15) | |
| Test page came out (Y/N) | |
| Sign scanned correctly with a real phone (Y/N, which phone) | |

## 2. Job table (print several copies)

One row for every job that reached the shop, including the ones that went wrong.

- **Settings:** BW or C; 1s or 2s; copies; page range if any. Example: `BW 2s x3 p2-4`.
- **Sheets:** what the card said ("... on N sheets of paper") / what came out.
- **Paper matched:** Y only if the count, the sides, the colour and the content are all right.
- **State shown:** SP sent to printer, NA needs attention, DG did not go through, RJ rejected, CA cancelled by customer, EX not approved in time. For NA, add what was pressed: P it printed, X it did not print, A print again.
- **Who helped:** - nobody, K shopkeeper helped the student, F founder helped.
- **T** = test job by the founder, **R** = real customer.

Date: __________ Page ____ of ____

| # | Time | T/R | Order code | Settings | Sheets card / out | Paper matched Y/N | State on PC | Words on phone at the end | Printed twice? Y/N | Problems | Who helped |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | | | | | / | | | | | | |
| 2 | | | | | / | | | | | | |
| 3 | | | | | / | | | | | | |
| 4 | | | | | / | | | | | | |
| 5 | | | | | / | | | | | | |
| 6 | | | | | / | | | | | | |
| 7 | | | | | / | | | | | | |
| 8 | | | | | / | | | | | | |
| 9 | | | | | / | | | | | | |
| 10 | | | | | / | | | | | | |
| 11 | | | | | / | | | | | | |
| 12 | | | | | / | | | | | | |
| 13 | | | | | / | | | | | | |
| 14 | | | | | / | | | | | | |
| 15 | | | | | / | | | | | | |

Page totals: jobs ____ · paper matched ____ · SP with no paper ____ · printed twice ____ · needed help ____

## 3. Fault drill record

Expected results are in `PILOT_DAY_CHECKLIST.md`, section 3. Write what really happened.

| Drill | Date | State on PC | Exact words on the phone | Message at the top of the app | What came out | Job left in Windows queue? | Duplicate? | As expected Y/N |
|---|---|---|---|---|---|---|---|---|
| 1 Paper out | | | | | | | | |
| 2 Printer off | | | | | | | | |
| 3a Printer cable or Wi-Fi pulled mid-print | | | | | | | | |
| 3b Shop internet pulled mid-print (1 min) | | | | | | | | |
| 3b Shop internet pulled mid-print (7 min) | | | | | | | | |
| 4 PC sleep | | | | | | | | |
| 5a Window closed | | | | | | | | |
| 5b App quit, then opened | | | | | | | | |
| 5c Quit or restart mid-print | | | | | | | | |
| 6 Two jobs at once | | | | | | | | |
| 7 Customer cancels | | | | | | | | |
| 8 Reject | | | | | | | | |
| 9 Cancel at the printer (optional) | | | | | | | | |
| 10 Paper jam (optional) | | | | | | | | |
| Long job, 150 sides or more | | | | | | | | |
| Both sides, on paper | | | | | | | | |
| Colour, on paper | | | | | | | | |

The completion question, answered from the drills:

- On a healthy print, did the job reach "Sent to printer" by itself? Always / Sometimes / Never
- Was the paper already out when it said so? Always / Sometimes / Never. Typical gap: ______ s
- Did any fault end as "Sent to printer" with no paper? N / Y, which: ______________

## 4. Support intervention log

Every time you, the founder, did anything for the shop after the handover: a phone call, a message, a visit, a command you ran. One line each. Phase 8 passes only with three working days in a row with no line here.

| # | Date, time | Who contacted whom, and how | What was wrong (their words) | What fixed it | Minutes | Could the shopkeeper have done it alone with the guide? | Defect, guide gap, or one-off |
|---|---|---|---|---|---|---|---|
| 1 | | | | | | | |
| 2 | | | | | | | |
| 3 | | | | | | | |
| 4 | | | | | | | |
| 5 | | | | | | | |
| 6 | | | | | | | |
| 7 | | | | | | | |
| 8 | | | | | | | |

## 5. Asked for, not built

Feature requests go here and nowhere else until the pilot is judged.

| Date | Who asked | What they asked for | What they were trying to do |
|---|---|---|---|
| | | | |
| | | | |
| | | | |
| | | | |

## 6. Daily line

Copy from `ap_report.py CODE` each evening.

| Date | Jobs sent to shop | Sent to printer | Needs attention (rate) | Failed | Rejected / cancelled / expired | "Second attempts nobody asked for" | Typical customer wait | Founder present? | Shopkeeper needed help? |
|---|---|---|---|---|---|---|---|---|---|
| | | | | | / / | | | | |
| | | | | | / / | | | | |
| | | | | | / / | | | | |
| | | | | | / / | | | | |
| | | | | | / / | | | | |
| | | | | | / / | | | | |
| | | | | | / / | | | | |

## 7. End-of-pilot summary

Pilot ran from __________ to __________ at __________ (code ______). Working days: ____

**Counts** (from `ap_report.py CODE --days N`, checked against section 2)

| | |
|---|---|
| Real customer jobs recorded (target 50 to 100) | |
| Jobs checked against the paper | |
| Success rate ("ended as sent to printer") | |
| First try, nobody had to step in | |
| Needs-attention rate | |
| Jobs printed again by the shopkeeper | |
| Second attempts that nobody asked for (must be 0) | |
| Duplicate prints seen on paper | |
| "Sent to printer" with no paper | |
| Orders started but never sent | |

**Timing medians** (report column "typical")

| | |
|---|---|
| Customer: page opened to order sent (whole) | |
| Shop: order sent to approve or reject (response time) | |
| Printer: handed to Windows to result reported | |
| Customer wait: order sent to "Sent to printer" | |

**Against the old way** (from `BASELINE_TIMING_SHEET.md`)

| | Old way | AutoPrint | Half or less? |
|---|---|---|---|
| Student, start to paper (median, by hand) | | | |
| Shopkeeper attention per job (median, by hand) | | | |

**The rest**

- Privacy incidents (wrong person saw or got a file, a file left on the PC): ____ . What happened:
- Support interventions in total: ____ . Longest run of working days with none: ____ (need 3).
- Did the completion rule hold on this printer? Yes / No / Only with these limits:
- What the printer and driver did that the app could not see:
- The three things students struggled with most:
- The three things the shopkeeper struggled with most:
- What the shopkeeper said when asked "would you keep it?":
- Anything in this log I am not sure about:

**Decision:** Proceed / Fix and repeat / Change direction

Why, in two sentences:

Signed: __________________ Date: __________
