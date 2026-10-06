# Pilot day checklist (founder)

Written from the code and docs as they stood on 6 October 2026 (app 4.0.1). Tick as you go.

**[NV] = not verified on a real printer.** The expected result is what the code is written to do; nobody has recorded it happening on paper. Your own real-printer trial is not recorded anywhere, so every printing step still carries the mark. Write what really happens in `RESULTS_LOG.md`. When the result differs from this sheet, the sheet is wrong, not the printer.

`PY` = `apps\api\.venv\Scripts\python.exe`, run from `F:\Projects\AutoPrint-V4`. `CODE` = the shop code, for example `ABC123`.

---

## 1. The evening before

**Live system**
- [ ] `git status`: nothing waiting to be pushed that the shop needs (a push to `main` deploys the site).
- [ ] Migrations 0010 to 0013: confirm they are applied live. The docs do not say they are. Quick sign: run `PY scripts\ap_report.py TST001`; if the SHOP COMPUTERS part says "Not recorded ... (migration 0011 adds this)", they are not applied. Apply through `/v1/internal/migrate` (HANDOVER.md, next steps, item 0).
- [ ] GitHub secret `AUTOPRINT_MAINTENANCE_TOKEN` is added, so file cleanup also runs when no shop computer is on.
- [ ] From **your own real phone**, on mobile data: open `https://autoprint-v4.vercel.app/s/TST001`, send one PDF, approve it on your PC. A real phone has never been used before; do not let the shop be the first time.

**The shop**
- [ ] Agree the prices with the shopkeeper. Copy `scripts\rates.example.json` to `rates.json`, change every `paise_per_side` (100 paise = 1 rupee).
- [ ] `PY scripts\ap_remote.py create-shop CODE "Shop name" --rates rates.json`
- [ ] `PY scripts\ap_remote.py prices CODE` and read the prices back against what was agreed.
- [ ] `PY scripts\ap_remote.py shop-link CODE --label owner`. It prints the private link **once**. Keep it to hand over in person. Anyone with it can manage the shop.
- [ ] Open `https://autoprint-v4.vercel.app/poster/CODE`, print 2 copies on A4. Scan one with your phone: it must open the shop's page with the right name. (Never checked with a real phone.)

**The installer**
- [ ] Code changed since `dist\AutoPrintSetup-4.0.1.exe` was built (6 Oct, 18:44)? Then bump the version and rebuild: `powershell -ExecutionPolicy Bypass -File apps\desktop\installer\build.ps1 -Version 4.0.x`.
- [ ] Copy the installer **and** its `.sha256.txt` to a USB stick. Write the version and the first 8 characters of the hash here: ____________
- [ ] Install that exact file on your own PC and run one job end to end (TEST_THE_WINDOWS_APP.md).

**Print on paper**
- [ ] This checklist. `SHOPKEEPER_GUIDE.md` x2 (write your phone number in). `CUSTOMER_FAQ.md` x2. `BASELINE_TIMING_SHEET.md` (2 copies of each tally page). `RESULTS_LOG.md` (4 copies of the job table).

**Bring**
- [ ] Laptop with the repo and `.env` (needed for `ap_remote.py` and `ap_report.py`), charger.
- [ ] USB stick with the installer. Two phones if you can (one Android, one iPhone). A mobile hotspot.
- [ ] Test PDFs on the phone: 1 page; 10 pages; 2 pages with colour; one long file (50 pages or more); one password-protected PDF; one file over 25 MB.
- [ ] Stopwatch (phone), 2 pens, tape for the sign, a ream of A4 and some cash: you pay the shop for every test page.

---

## 2. At the shop, in this order

### 2.1 Before anything is installed
- [ ] **Baseline first.** Time about 20 jobs done the current way (`BASELINE_TIMING_SHEET.md`, Sheet A). Once students have seen the sign, the baseline is gone.
- [ ] Write down in `RESULTS_LOG.md`: PC name, Windows version, printer make and model, driver name, how it is connected (USB, network, Wi-Fi), how the shop prints PDFs today.
- [ ] Windows Settings, System, Power: screen and sleep = **Never** while plugged in. PC plugged in. Date and time correct.

### 2.2 Install (start a stopwatch; target under 15 minutes to the first test page; never timed on a clean PC)
- [ ] Check the file: `certutil -hashfile AutoPrintSetup-4.0.1.exe SHA256` matches the `.sha256.txt`.
- [ ] Run it. "Windows protected your PC": **More info**, then **Run anyway** (the file is not signed). Copy down the exact text of any other antivirus warning.
- [ ] Keep "Start AutoPrint when I sign in" ticked. No administrator prompt should appear.

### 2.3 Connect
- [ ] The app shows "Connect this computer to your shop" and a code like `K7QD-M2XP` (works for 15 minutes; "Get a new code" gives another).
- [ ] The **shopkeeper** opens the private link on their own phone, types the code under "Connect a computer", checks the computer name, presses "Yes, connect it to (shop name)".
- [ ] Within a few seconds the app shows the shop name, a green dot and "Connected". The Settings window opens by itself because no printer is chosen.

### 2.4 Choose the real printer
- [ ] "Printer for customer prints": pick the printer the shop really uses. The app pre-selects the first real-looking printer in the list, which may be the wrong one. Ask the shopkeeper which name they pick in Windows today.
- [ ] If the line under the box says **"This one makes a file, not paper."**, it is a virtual printer (Print to PDF, XPS, OneNote, Fax). Choose another.
- [ ] "Colour printer, if it is a different one": set it only if colour goes to a second machine. Otherwise leave "Same printer".
- [ ] Press **Print a test page**. Expected: "Sent to the printer. Check that a page came out." and one page headed "AutoPrint test page" with the date. **[NV]** The test page goes to the first printer only; a separate colour printer is tested by a real colour job.
- [ ] Press **Save**. The top of the window now reads "Shop code CODE · Printer: (name)". Stop the stopwatch; write the install time in `RESULTS_LOG.md`.

### 2.5 First real job from a phone
- [ ] Tape up the sign. Scan it. The page shows "Print at (shop name)" and a green "Open for prints".
- [ ] Choose a PDF, **Continue**, pick settings, **See exact price**, **Send to shop**. The phone shows "Order XXXX · Say this code at the counter".
- [ ] On the PC: a sound, the taskbar button flashes, a card appears under WAITING FOR YOU with the same order code and the same amount. (Sound, flash and tray message have not been seen on a real screen.)
- [ ] **Preview** shows the pages. **Approve and print.**
- [ ] PC: PRINTING NOW, "Getting the file…", "Sending it to the printer…", "The printer is working on it…". Phone: "Approved. Waiting for the printer." then "Sending to the printer." then "Sent to printer. Collect it at the counter." **[NV]**
- [ ] **The one thing to watch:** did the job end as "Sent to printer" by itself, and was the paper out by then? Write both times down. **[NV]** If healthy prints end as "Needs your attention" every time, this printer's driver does not report what the completion rule needs. That is a stop (section 5).
- [ ] Finished tab: the order is there as "Sent to printer". Count the sheets against the card ("N sides to print on N sheets of paper").

### 2.6 Settings on paper (each one a line in `RESULTS_LOG.md`)
- [ ] Black and white, one side. **[NV]**
- [ ] Both sides: pages back to back, flipped on the long edge. **[NV]** (never checked on paper)
- [ ] Colour: comes out in colour, and from the right machine. **[NV]** (never checked on paper)
- [ ] 3 copies. **[NV]**   - [ ] "Some pages" 2-4 of a 10-page file: exactly 3 pages. **[NV]**
- [ ] The long file (150 sides or more, for example 50 pages x 3 copies): must not turn into "Needs your attention" while it is still printing. **[NV]**
- [ ] Password-protected PDF: the phone refuses it ("This PDF is password-protected. Remove the password and try again."). File over 25 MB: "The file is larger than 25 MB."

---

## 3. Fault drills, before real customers

Do each once with your own test file. For every drill write in `RESULTS_LOG.md`: what the PC showed, the exact words on the phone, what came out, and any yellow or red message at the top of the app. All expected results are **[NV]**.

**The rule behind every drill:** the app never prints a job twice by itself. When it is not sure, the card moves to NEEDS YOUR ATTENTION and a person chooses "It printed", "It did not print" or "Print again". A job that ends there may **still be sitting in the Windows print queue** and will print when the printer recovers. Before "Print again", open the Windows queue (Settings, Bluetooth & devices, Printers & scanners, the printer, Open print queue) and look for a job named `apjob_...`. If it is there, wait for it or cancel it there first.

| # | Drill | Do this | Expected |
|---|---|---|---|
| 1 | **Paper out** | Empty the tray, send and approve a 5-page job. Wait 2 minutes. Refill. | A yellow line may appear: "Windows says the printer ... is out of paper. You can still approve; check the printer first." (checked every 30 s). The job does **not** end as "Sent to printer"; it goes to NEEDS YOUR ATTENTION (after about a minute, or once the pages finish). Phone: "The shop is checking this print. Please ask at the counter." After the refill the pages come out **without** pressing anything. Then press "It printed". Phone: "Sent to printer. Collect it at the counter." **Fail:** "Sent to printer" while the tray was empty and nothing came out. |
| 2 | **Printer off** | Switch the printer off. Send and approve a 2-page job. Wait 2 minutes. Switch it on. | Maybe "Windows says the printer ... is offline." Approve still works. About a minute later: NEEDS YOUR ATTENTION. When the printer comes on, Windows will probably print the waiting job. If it does: "It printed". If nothing comes and the Windows queue is empty: "Print again", confirm, one copy comes out. **Fail:** two copies. |
| 3a | **Printer cable or printer Wi-Fi pulled mid-print** | Start a 20-page job, pull the printer's cable after about 5 pages, wait 2 minutes, plug it back. | NEEDS YOUR ATTENTION. Some pages are out. See what Windows does when the cable is back (continues, restarts, or nothing) and write it down. Choose by counting pages: complete = "It printed"; unusable = "It did not print" (phone: "The shop could not print this. Please ask at the counter.") and the customer sends again. |
| 3b | **Shop internet pulled mid-print** | Start a 20-page job, turn the PC's Wi-Fi off, turn it on after 1 minute. Repeat with 7 minutes. | Printing carries on (the file is already on the PC). Dot goes orange, "No internet", banner "No internet connection. New requests will arrive by themselves when it is back." with "Try now". Buttons are greyed: "No internet. You can answer when it is back." Short break: the job ends as "Sent to printer" by itself once back. Long break (over about 5 minutes): NEEDS YOUR ATTENTION; the pages are there; "It printed". Never a second print. |
| 4 | **PC sleep** | Start menu, Power, Sleep. Send a job from the phone. Wake the PC after 2 minutes. | While asleep the phone's shop page shows "Shop computer offline" and "You can still send your file; it will wait for the shop." On wake the app reconnects by itself and the card appears with the sound. Never tried, on any PC. A request not approved within 1 hour ends as "The shop did not approve this in time. Please start a new order." |
| 5a | **Window closed** | Click the X. Send a job. | The app stays in the tray; first time a message says so. The sound plays and the window comes back to the taskbar. |
| 5b | **App quit** | Right-click the tray icon, Quit, Yes. Send a job. Start AutoPrint from the Start menu. | Quit asks: "While AutoPrint is closed, new print requests wait and customers see your shop as offline." The job waits and shows up when the app is opened. No new pairing code. |
| 5c | **App quit or PC restarted mid-print** | Start a 20-page job, Quit (or restart Windows) while it prints. Start the app again. | Quit warns: "A document is being sent to the printer right now. If you quit, it will show 'Needs your attention' next time." The printer usually finishes the pages. After the restart: NEEDS YOUR ATTENTION. Count pages, "It printed". After a Windows restart the app should come back in the tray by itself (never tested). |
| 6 | **Two jobs at once** | Send from two phones within seconds. Approve both back to back. | "WAITING FOR YOU · 2", oldest on top. After approving: one under PRINTING NOW, the other "Approved. It prints as soon as the printer is free." They print one after the other. Pages are not mixed; each stack matches its order code. Both end as "Sent to printer". |
| 7 | **Customer cancels** | Send a job; on the phone press "Cancel this print", OK. Repeat with Preview open on the PC. | Phone: "Cancelled." The card leaves Requests; Finished shows "Cancelled by customer". With Preview open: "The customer cancelled this request. There is nothing to approve." A click that lands at the same moment: "That request has changed ... Nothing was changed." Nothing prints. Once printing has started the cancel link is gone. |
| 8 | **Reject** | Send a job, press Reject. | One click, no question, no reason asked. Phone: "The shop declined this print." Finished: "Rejected". Nothing prints. The customer is never told why, so the shopkeeper has to say it. |
| 9 | Optional: **cancel at the printer** | Start a 20-page job, cancel it in the Windows print queue or on the printer panel. | Before any page: Finished shows "Did not go through". After some pages: NEEDS YOUR ATTENTION. Never "Sent to printer". |
| 10 | Optional: **paper jam** | Only if the shopkeeper agrees. | NEEDS YOUR ATTENTION. Record whether Windows showed "has a paper jam" at all. If a jam ends as "Sent to printer", write it down: the rule cannot see jams on this printer. |

After the drills:
- [ ] Windows print queue is empty (no stuck `apjob_` job blocking the shop's own printing).
- [ ] Settings, "Open the log folder": the folders `work`, `preview` and `testpage` hold no PDF. No customer file stays on the PC.
- [ ] `PY scripts\ap_report.py CODE --hours 6`: under DUPLICATE CHECK, "second attempts that nobody asked for" is 0.

Then hand over: give the shopkeeper the guide with your number on it, and watch them do three jobs without you touching anything.

---

## 4. End of the day

- [ ] `PY scripts\ap_report.py CODE`. Copy into `RESULTS_LOG.md`: jobs sent, sent to printer, success rate, needs-attention rate, the five DUPLICATE CHECK lines, the HOW LONG THINGS TOOK table.
- [ ] "NEEDS A LOOK NOW" says "nothing". If not, settle each job with the shopkeeper before you leave.
- [ ] The number of jobs in the report equals the lines in your job table. Every "Sent to printer" in the Finished tab had paper.
- [ ] Money: the app records no payment. Add up TO COLLECT for today's "Sent to printer" orders in the Finished tab and ask the shopkeeper whether the cash agrees.
- [ ] Windows print queue empty; `work` and `preview` folders empty.
- [ ] Ask the shopkeeper: What was confusing? What was slower than WhatsApp? Would you open it tomorrow without me? Write the answers down word for word.
- [ ] Every time you stepped in is a line in the support log. Every "it should also do..." is a line in the backlog. Build none of them.
- [ ] Leave the PC on or tell the shopkeeper it starts by itself at sign-in. Next morning: `PY scripts\ap_report.py --all` (computer online?).

---

## 5. Stop and call it off

Stop the same hour if any one of these happens:

1. **A job printed twice and nobody pressed "Print again"**, or the report shows "second attempts that nobody asked for" above 0.
2. **"Sent to printer" with no paper**, and no paper ever comes, more than once.
3. **Healthy prints end as "Needs your attention" most of the time.** The shopkeeper cannot run that alone; the completion rule needs your decision (F-8) before going on.
4. **A privacy problem:** a customer's file opened by or handed to the wrong person, or a customer PDF found left on the shop PC.
5. **Wrong money:** the amount on the PC differs from the phone, or from the agreed prices.
6. **Real phones cannot upload** (several students, different phones).
7. **The shop's own printing is blocked** by a stuck job, or the app keeps closing, or the shopkeeper asks you to stop.

How to stop, in order:
- [ ] `PY scripts\ap_remote.py shop-off CODE`. Customers see "This shop is not taking orders right now." Jobs already sent still print. The shopkeeper's private link also stops working while the shop is off. (`shop-off` and `shop-on` have not been run on the live system yet; try both on `TST001` the evening before.)
- [ ] Take the sign down. Tell the shopkeeper: back to WhatsApp for now.
- [ ] Settle anything under NEEDS YOUR ATTENTION. Clear the Windows print queue.
- [ ] Right-click the tray icon, Quit. Uninstalling is optional (Windows Settings, Apps); it keeps the print record on purpose.
- [ ] Before leaving: Settings, "Open the log folder", copy `app.log` to your USB stick. Write down what happened while you still remember it.

Not a reason to stop: one job needing attention after a real fault, a slow approval, a SmartScreen warning, a student who needs the steps explained. Log them and carry on.
