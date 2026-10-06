# Test the Windows app yourself

Use a test shop (`TST001`). Nothing here touches V3. Allow about 15 minutes.

## What you need
- `dist\AutoPrintSetup-4.0.1.exe` (59 MB). Rebuild with `powershell -ExecutionPolicy Bypass -File apps\desktop\installer\build.ps1`.
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

## What is new in 4.0.1
- Each request shows the order code large (the customer says it at the counter), the amount to collect, sides and sheets, how long it has waited and when it expires.
- A new request plays a short sound, flashes the taskbar button and shows a tray message. The sound can be switched off in Settings.
- **Finished** tab: the last 24 hours, with a box to find an order by its code.
- "Needs attention" explains what to check and what each choice does. "Print again" really prints again and asks you to confirm.
- Banners when no printer is chosen, the chosen printer is gone or offline, the print program is missing, or the internet is down (requests arrive when it is back).
- Settings shows the version, the shop, the connection, and a button that opens the folder with `app.log`. To disconnect this PC, use the shop dashboard.
- Pictures of every screen with made-up data: `AutoPrint.exe --selftest-ui <folder>` (it touches no real data and never prints).

**Not yet tried on a real screen by anyone but you:** the animations, the sound, the taskbar flash, and what happens after the PC sleeps and wakes. Please look at these in particular.

## 4. Things worth trying
- Close the window: the app keeps running in the tray (right-click the tray icon, Quit to exit).
- Turn off Wi-Fi for a minute, turn it on: the status dot goes orange and then green again by itself.
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
