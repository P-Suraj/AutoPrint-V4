# Timing sheets: the old way, then AutoPrint

The adoption bar is: AutoPrint must take **at least 50% less** than WhatsApp or email, for the student **and** for the shopkeeper. This sheet gives the two "before" numbers. Do Sheet A **before** the sign goes up and before the shopkeeper has used AutoPrint.

## How to time (both sheets)

- Stand where you can see the counter and the screen. Do not help, hurry or explain. Tell the shopkeeper: "Work as you always do; I am only timing."
- Use the phone stopwatch with **laps**. Start it at T0, tap Lap at each later moment, copy the lap times to the row afterwards. Write total seconds from T0.
- Take jobs as they come: about 20, across a quiet time and a busy time. Do not pick the easy ones.
- If you missed a moment, write a dash. A row with a dash is still useful; a guessed number is not.
- If the shopkeeper left the job to serve someone else, tick "Int." (interrupted). Those rows stay out of the shopkeeper median.

---

## Sheet A: the current way (WhatsApp, email, USB)

**Moments to time**

| | Moment | How you know |
|---|---|---|
| **T0** | Student starts | Phone comes out to send the file, or the student asks "can I get a print?", whichever is first. |
| **T1** | File sent | The student has pressed send (WhatsApp or email). For USB: the drive is in the PC. |
| **T2** | Shopkeeper starts on it | He picks up his phone or turns to the PC **for this job**. |
| **T3** | Print pressed | He presses Print for the last time on this job. |
| **T4** | Paper in hand | The student holds all the pages. |
| **T5** | Paid | Money has changed hands. |

**The two numbers**

- **Student, start to paper = T4 - T0.** Also note T1 - T0 (effort to send) and T4 - T1 (waiting).
- **Shopkeeper attention = (T3 - T2) + (T5 - T4).** Hands on this job: finding the message, downloading, opening, asking which pages, setting copies and sides, pressing Print; then handing over and taking money. Queue time between T1 and T2 is **not** his attention.

**Tally page** (print 2; 12 rows each). Ch = W WhatsApp, E email, U USB. Q = questions the two had to ask each other ("which file?", "colour?", "both sides?"). Re = pages printed wrong and done again (Y/N).

Date: __________ Shop: __________ Observer: __________

| # | Clock | Ch | Sides | BW/C | 1s/2s | T1 s | T2 s | T3 s | T4 s | T5 s | Int. | Q | Re | Note |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | | | | | | | | | | | | | | |
| 2 | | | | | | | | | | | | | | |
| 3 | | | | | | | | | | | | | | |
| 4 | | | | | | | | | | | | | | |
| 5 | | | | | | | | | | | | | | |
| 6 | | | | | | | | | | | | | | |
| 7 | | | | | | | | | | | | | | |
| 8 | | | | | | | | | | | | | | |
| 9 | | | | | | | | | | | | | | |
| 10 | | | | | | | | | | | | | | |
| 11 | | | | | | | | | | | | | | |
| 12 | | | | | | | | | | | | | | |

**Baseline result** (median = sort the values, take the middle one)

| | Median | Slowest |
|---|---|---|
| Student: T0 to file sent (T1) | ______ s | ______ s |
| Student: file sent to paper (T4 - T1) | ______ s | ______ s |
| **Student: start to paper (T4)** | ______ s | ______ s |
| **Shopkeeper attention per job** (rows without Int.) | ______ s | ______ s |
| Jobs with a question asked: ____ of ____ | Jobs reprinted: ____ of ____ | |

---

## Sheet B: AutoPrint, watched by hand

`scripts/ap_report.py` gives server times for every job. It **cannot** see four things, so time them here:

1. **The start.** The report's "page opened" clock really starts when the student presses **Continue** after choosing a file. Scanning the sign, the page loading and finding the file are invisible to it.
2. **Paper in hand.** The report stops at "Sent to printer".
3. **Shopkeeper attention.** The report's "Shop: order sent to approve or reject" is how long the job **waited**, not how long he worked on it.
4. **Confusion, questions, help.**

**Moments to time**

| | Moment | How you know |
|---|---|---|
| **T0** | Student starts | Phone comes out to scan the sign or type the shop code. |
| **T1** | Order sent | The phone shows "Order XXXX · Say this code at the counter". |
| **A1** | Shopkeeper turns to the card | He looks at the screen for this request. |
| **A2** | Answer given | He presses "Approve and print" (or Reject). |
| **T4** | Paper in hand | The student holds all the pages. |
| **T5** | Paid | Money has changed hands. |

- **Student, start to paper = T4 - T0.**
- **Shopkeeper attention = (A2 - A1) + (T5 - T4)**, plus any time spent on a "Needs your attention" card for this job.

**Tally page** (print 2). Stuck = where the student hesitated more than about 5 seconds: S scan, F find file, P settings or price, C code or counter, - none. Help = who helped: - nobody, K shopkeeper, F founder, O another student. Prev = shopkeeper opened Preview (Y/N). End = what the PC showed: SP sent to printer, NA needs attention, RJ rejected, CA cancelled, EX expired, DG did not go through.

Date: __________ Shop: __________ Observer: __________

| # | Order code | Sides | T1 s | A1 s | A2 s | T4 s | T5 s | Stuck | Q asked | Help | Prev | End | What they said or did |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | | | | | | | | | | | | | |
| 2 | | | | | | | | | | | | | |
| 3 | | | | | | | | | | | | | |
| 4 | | | | | | | | | | | | | |
| 5 | | | | | | | | | | | | | |
| 6 | | | | | | | | | | | | | |
| 7 | | | | | | | | | | | | | |
| 8 | | | | | | | | | | | | | |
| 9 | | | | | | | | | | | | | |
| 10 | | | | | | | | | | | | | |
| 11 | | | | | | | | | | | | | |
| 12 | | | | | | | | | | | | | |

Write the order code on every row: it is how you match a row to the report's "MOST RECENT JOBS" list.

Also tally, with strokes:

| Students who gave up before sending | Could not find the PDF on the phone | File was not a PDF | Asked "is it done?" although the phone said so | Did not say the order code until asked | Shopkeeper did not notice a request for over 2 min |
|---|---|---|---|---|---|
| | | | | | |

---

## Putting the two side by side

Run `apps\api\.venv\Scripts\python.exe scripts\ap_report.py CODE --days 7` and copy the "typical" column (typical = the median).

| What | Old way (Sheet A) | AutoPrint by hand (Sheet B) | AutoPrint from the report (exact line name) |
|---|---|---|---|
| Student effort to send | T1 - T0: ______ s | T1 - T0: ______ s | "Customer: page opened to order sent (whole)": ______ s. Shorter than the hand time, because it starts at Continue. |
| Student wait after sending | T4 - T1: ______ s | T4 - T1: ______ s | "Customer wait: order sent to 'Sent to printer'": ______ s. Shorter than the hand time, because it ends before the paper is handed over. |
| **Student, start to paper** | **T4 - T0: ______ s** | **T4 - T0: ______ s** | No single line. Use the hand time. |
| **Shopkeeper attention per job** | **______ s** | **______ s** | Not in the report. Use the hand time. |
| How long a request waited for the shopkeeper | T2 - T1: ______ s | A2 - T1: ______ s | "Shop: order sent to approve or reject (response time)": ______ s |
| Jobs where someone had to ask a question | ____ of ____ | ____ of ____ | Not in the report. |
| Jobs that went wrong | reprinted: ____ of ____ | needs attention or did not go through: ____ of ____ | "needs-attention rate" and "first try, nobody had to step in" |

**The bar:** AutoPrint passes for the student if its "start to paper" median is **half or less** of the old way's. It passes for the shopkeeper if its attention median is **half or less** of the old way's. Both must pass.

Student: ______ s is ______ % of ______ s. Pass / Fail.
Shopkeeper: ______ s is ______ % of ______ s. Pass / Fail.

Compare like with like: say so if the AutoPrint jobs were much larger or smaller than the baseline jobs, or measured at a quieter hour. Fewer than about 20 jobs on either side is a first impression, not a result.
