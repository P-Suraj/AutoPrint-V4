# Test the Windows app yourself

Use a test shop (`TST001`). Nothing here touches V3. Allow about 15 minutes.

## What you need
- `dist\AutoPrintSetup-4.0.3.exe` (about 59 MB). Rebuild with `powershell -ExecutionPolicy Bypass -File apps\desktop\installer\build.ps1 -Version 4.0.3`.
- `dist\SHOP_LINK.txt`: your private dashboard link for TST001. Keep it private; anyone with it can manage that shop. Revoke it any time through the founder endpoint (label `founder-test`).
- A printer. The virtual printer `AutoPrint-Spike-PDF` makes a file, not paper. The Kyocera is the real test but is **not certified yet**: use it only for trial pages.

## 1. Install
1. Double-click the installer. Windows may show **"Windows protected your PC"** because the file is not signed. Click **More info**, then **Run anyway**. This is expected until a code-signing certificate is bought (see `DESKTOP_DISTRIBUTION.md`). Defender scanned this file and reported nothing.
2. Keep "Start AutoPrint when I sign in" ticked and finish. It installs for your user only, with no administrator prompt, under `%LOCALAPPDATA%\Programs\AutoPrint`.

## 2. Connect it (the shopkeeper flow)
1. The app opens and shows a code like `ABCD-EFGH`.
2. On your phone or PC, open the link in `dist\SHOP_LINK.txt`. Type the code, check the computer name, press **Yes, connect it**.
3. Within a few seconds the app switches to the queue. A window asks you to choose a printer; pick one and press **Print a test page**.

## 3. Send a document as a customer
1. On your phone open `https://autoprint-v4.vercel.app`, type `TST001` (or scan a QR for `/s/TST001`).
2. Pick a PDF, choose options, submit.
3. In the app a card appears (and a tray notification). Press **Preview** to see the pages, then **Approve and print**.
4. The customer page should move to "printing" and then "Sent to printer".

## What is new in 4.0.3 (7 October)
These are in `AutoPrintSetup-4.0.3.exe`, not in 4.0.2.
- **The list is refreshed at once when you open the window** from the tray icon or bring it to the front, instead of up to 10 seconds later. The app still asks the server every 10 seconds and no more often: the refresh takes the place of the next regular one, and opening the window many times in a row asks only once.
- **The reminder sound ends by itself.** It plays every 2 minutes only for requests that can still be approved. A request whose hour is over is no longer reminded about, and while there is no internet the app stays quiet (before, a computer left on without internet chimed every 2 minutes about an old list for as long as it was on). When the internet is back and something is still waiting, it reminds once and carries on.
- **"Test the colour printer"** has now been pressed by the app's own run with a made-up print program, and by the automatic tests with the real print program on the virtual printer: one page, in colour, to the colour printer and to no other; a double click sends one page; a failure says "It did not work. Check the printer and try again." It has still not been pressed with a real colour printer.
- The moving blue line under a job that is printing now rests while nobody can see it (window in the tray or minimised, or the Finished tab in front), so a long print costs the computer nothing then.
- The warning sign in a message at the top now lines up with its words when the message has a button.

Measured on this PC on 7 October with `AutoPrint.exe --selftest-ui <folder> soak:300` (one window, made-up requests, refreshed every 10 s, 5 minutes each part, 8-processor PC): a quiet queue used 0.2% to 0.8% of one processor; a job printing with the window in view used 8% to 11% of one processor (the moving line); the same with the window minimised used 0.2%. Memory did not grow: 89 MB at the start, 69 MB after 20 minutes. Not measured on a slow shop PC.

## What is new in 4.0.2
- **Printers that make a file instead of paper** ("Microsoft Print to PDF", XPS, Fax, OneNote) are marked "no paper" in Settings, are never chosen by default, and a banner at the top says so if one is chosen. This is what made order BLS3 fail on 6 October: the app was set to Microsoft Print to PDF, which opens a Save window and waits. **First thing to do: open Settings and choose the real printer.**
- A print that fails now says why in plain words (printer off, nothing reached the print queue, the file is gone, and so on): in a red message at the top until you press OK, under the order in the Finished tab, and on the card when the request needs your attention. The words are kept while the order is in the list and the app stays open.
- **"Print again" can no longer print twice by accident.** If the earlier job is still waiting in the Windows print queue (paper ran out, printer was off), the app says so and offers: remove it and print again, keep both, or go back.
- A job this computer is printing shows "Printing now" at once.
- A page range that is not plain digits, commas and hyphens is refused before anything is downloaded.
- Settings has **Test the colour printer** when a colour printer is chosen that is a different machine from the main printer.
- Requests that were already waiting when the app starts make no sound at first. If they are still waiting 2 minutes later the reminder starts, and it repeats every 2 minutes while one is waiting, as for any request. **Tell me if you would rather hear them at once.**

**Not yet tried on a real printer or a real screen:** the "Test the colour printer" button with a real colour printer, the taskbar flash, removing a job that is stuck at a switched-off printer, and the Save window case itself. Checked on 7 October only by the automatic tests (177 with the Windows print queue on the virtual printer) and the app's own 72-step run with made-up data.

## What is new in 4.0.1
- Each request shows the order code large (the customer says it at the counter), the amount to collect, sides and sheets, how long it has waited and when it expires.
- A new request plays a short sound, flashes the taskbar button and shows a tray message. The sound can be switched off in Settings.
- **Finished** tab: the last 24 hours, with a box to find an order by its code.
- "Needs attention" explains what to check and what each choice does. "Print again" really prints again and asks you to confirm.
- Banners when no printer is chosen, the chosen printer is gone or offline, the print program is missing, or the internet is down (requests arrive when it is back).
- Settings shows the version, the shop, the connection, and a button that opens the folder with `app.log`. To disconnect this PC, use the shop dashboard.
- Pictures of every screen with made-up data: `AutoPrint.exe --selftest-ui <folder>` (it touches no real data and never prints). Add `live` for the app's own run through a whole day, or `soak:300` to measure what an open window costs the computer.

**Not yet tried on a real screen by anyone but you:** the animations, the sound, the taskbar flash, and what happens after the PC sleeps and wakes. Please look at these in particular.

## 4. Things worth trying
- Close the window: the app keeps running in the tray (right-click the tray icon, Quit to exit).
- Turn off Wi-Fi for a minute, turn it on: the status dot goes orange and then green again by itself.
- Close the window, send a job from the phone, wait for the sound, then open the window from the tray icon: the request should already be there.
- Leave a request unanswered: the sound should come again every 2 minutes, and the taskbar button should flash until you click the window.
- Send a job, then cancel it on the phone before approving.
- Reject a job. Approve two jobs back to back.
- Restart Windows: the app should start in the tray by itself.
- Uninstall from Settings, Apps. Your settings and the print journal are kept on purpose.

## What to tell me
Anything confusing, slow, or ugly; any wording you would change; any warning from Windows or antivirus (copy its exact text).

## Known limits right now
- Not signed: SmartScreen warning on first run.
- Physical printer behaviour is not certified.
- Colour/duplex are sent to the printer but unverified on paper.
- The preview uses Windows' built-in PDF viewer; unusual PDFs may fail to display (you can still approve or reject).
- Not tested on any PC other than this one.
