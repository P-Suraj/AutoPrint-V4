# Runbook: running AutoPrint at a shop

For the founder. Everything here was done or checked on 5 October 2026 unless marked **not yet verified**. Commands run from the repo root; `PY` means `apps\api\.venv\Scripts\python.exe`.

## 1. Add a shop (about 3 minutes)
The database port is blocked from the founder PC, so these tools go through the deployed API (`scripts/ap_remote.py`, uses the maintenance token from `.env`).
1. Create the shop and its prices in one step: `PY scripts/ap_remote.py create-shop ABC123 "Shop name" --rates rates.json`. Shop codes are three letters and three digits. `rates.json` has the same shape as the demo rate card (`bw` and `color`, each with `simplex` and `duplex` slabs in paise per side). A bad rate card is refused and nothing is created. To change prices later: `set-rates ABC123 --rates rates.json` (publishes a new version; old orders keep the price they were quoted).
2. Create the shopkeeper link: `PY scripts/ap_remote.py shop-link ABC123 --label owner`. It prints a private link once; hand it over in person.
3. The customer link is `https://autoprint-v4.vercel.app/s/ABC123`. Print the counter QR for it. **Not yet built:** a poster generator.

## 2. Install at the shop (target under 15 minutes; not yet timed on a clean PC)
1. Copy `dist\AutoPrintSetup-<version>.exe` to the shop PC. Verify its SHA-256 matches `AutoPrintSetup-<version>.exe.sha256.txt`.
2. Run it. If Windows shows "Windows protected your PC", click **More info**, then **Run anyway** (the file is not signed yet). Keep "Start AutoPrint when I sign in" ticked.
3. The app shows a code. The shopkeeper opens their private link and types it. Within seconds the app shows the queue.
4. Set the shop PC to **never sleep while plugged in** (Settings, System, Power) and keep it plugged in; a sleeping PC stops receiving jobs and the shop shows as offline.
4. In the app choose the printer, press **Print a test page**, and confirm paper came out.
5. Send one real job from a phone and approve it. Done.

## 3. Daily check (30 seconds)
`PY scripts/ap_report.py ABC123` shows the last 24 hours: counts by outcome, jobs that need a look, whether the shop computer is online.
- `needs_attention` or `failed` above zero: phone the shop. The shopkeeper chooses "It printed", "It did not print" or "Print again" in the app.
- Computer not online: see the table below.

## 4. When something goes wrong
| What you see | Likely cause | Fix |
|---|---|---|
| Report shows computer last seen long ago | PC off, asleep, or no internet | Ask the shopkeeper to wake the PC and check the status dot in the tray app (green online, orange offline). It reconnects by itself |
| App shows a new pairing code instead of the queue | Credentials were removed or the computer was disconnected on the dashboard | Shopkeeper types the new code on their dashboard |
| Customer says "not taking orders" | App has been offline for 45+ seconds | As above |
| Job stuck as `needs_attention` | The app could not confirm the print (queue stuck, printer error, app restarted mid-print) | Check the printer and the Windows print queue; shopkeeper resolves it in the app. The system never reprints by itself |
| Job `failed` with printer not found | The chosen printer was renamed or removed | Printers button in the app, choose it again |
| SmartScreen or antivirus blocks the installer | Unsigned file | See `DESKTOP_DISTRIBUTION.md`; report the false positive to Microsoft; click Run anyway |
| Shopkeeper lost their link | | Issue a new one with `shop-link` and revoke the old with `revoke-link --label owner` (it revokes every login with that label, so use a distinct label per person) |

## 5. Retention and deletion on request
- Rules (decision O-5/O-10): drafts 1 hour; submitted orders up to 48 hours; finished orders +24 hours; unapproved jobs expire 1 hour after submit. Documents are deleted from storage with the records.
- The cleanup runs when a shop app polls (at most once a minute) and from the scheduled workflow `.github/workflows/maintenance.yml` every 15 minutes. **One manual step:** add the repository secret `AUTOPRINT_MAINTENANCE_TOKEN` (the workflow fails loudly until you do).
- Deletion proven locally by tests and live for the storage cache issue (a deleted file is not readable through an unauthenticated URL). **Not yet verified live:** that a file past its real window is gone and an old signed URL stops working; this needs waiting out a real window.
- Purge a customer's order on request: **not yet built** as a script. Today: delete the order's documents in the Supabase storage bucket and tell me the order code.

## 6. Reboot and soak
- Reboot test: **not yet run.** The app starts at sign-in with `--background` (tray, no window) when that option is on.
- 24-hour idle soak: **not yet run.**

## 7. Secrets and access
- Local `.env` (git-ignored) holds the Supabase and maintenance values. Never paste them in chat or commit them.
- The maintenance token can run migrations, issue shop logins and read reports. Rotate it by changing the Vercel environment variable and the GitHub secret, then redeploying.
- Vercel only applies environment changes to new deployments: redeploy after every change.
