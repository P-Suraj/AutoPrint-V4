# Runbook: running AutoPrint at a shop

For the founder. Everything here was done or checked on 5 October 2026 unless marked **not yet verified**. Commands run from the repo root; `PY` means `apps\api\.venv\Scripts\python.exe`.

## 1. Add a shop (about 3 minutes)
The database port is blocked from the founder PC, so these tools go through the deployed API (`scripts/ap_remote.py`, uses the maintenance token from `.env`).
0. Prices file: copy `scripts/rates.example.json` to `rates.json` and change every `paise_per_side` (100 paise = 1 rupee). The example holds Rs 999 placeholders that the tool refuses to publish.
1. Create the shop and its prices in one step: `PY scripts/ap_remote.py create-shop ABC123 "Shop name" --rates rates.json`. Shop codes are three letters and three digits. `rates.json` has the same shape as the demo rate card (`bw` and `color`, each with `simplex` and `duplex` slabs in paise per side). A bad rate card is refused and nothing is created. To change prices later: `set-rates ABC123 --rates rates.json` (publishes a new version; old orders keep the price they were quoted).
2. Create the shopkeeper link: `PY scripts/ap_remote.py shop-link ABC123 --label owner`. It prints a private link once; hand it over in person.
3. The customer link is `https://autoprint-v4.vercel.app/s/ABC123`. Print the counter QR for it. The shopkeeper can print the counter sign from their dashboard ("Print your counter sign"), or open `https://autoprint-v4.vercel.app/poster/ABC123`. **Not yet checked:** scanning the printed sign with a real phone.

## 2. Install at the shop (target under 15 minutes; not yet timed on a clean PC)
1. Copy `dist\AutoPrintSetup-<version>.exe` to the shop PC. Verify its SHA-256 matches `AutoPrintSetup-<version>.exe.sha256.txt`.
2. Run it. If Windows shows "Windows protected your PC", click **More info**, then **Run anyway** (the file is not signed yet). Keep "Start AutoPrint when I sign in" ticked.
3. The app shows a code. The shopkeeper opens their private link and types it. Within seconds the app shows the queue.
4. Set the shop PC to **never sleep while plugged in** (Settings, System, Power) and keep it plugged in; a sleeping PC stops receiving jobs and the shop shows as offline.
4. In the app choose the printer, press **Print a test page**, and confirm paper came out.
5. Send one real job from a phone and approve it. Done.

## 3. Daily check (30 seconds)
`PY scripts/ap_report.py --all` shows every shop on one line each (on or off, computer online, jobs today, needing a look). `PY scripts/ap_report.py ABC123` shows one shop for the last 24 hours (`--days 7` for a week, up to 90): outcomes, success and needs-attention rates, duplicate signs, how long each step took, busiest hours, whether the shop computer is online. It is read-only and shows no document names. Checked live on TST001 on 6 Oct 2026. Time a computer spent offline is recorded only after migration 0011 is applied.
- `needs_attention` or `failed` above zero: phone the shop. The shopkeeper chooses "It printed", "It did not print" or "Print again" in the app.
- Computer not online: see the table below.

## 4. When something goes wrong
| What you see | Likely cause | Fix |
|---|---|---|
| Report shows computer last seen long ago | PC off, asleep, or no internet | Ask the shopkeeper to wake the PC and check the status dot at the top of the AutoPrint window (green connected, orange offline). It reconnects by itself |
| App shows a new pairing code instead of the queue | Credentials were removed or the computer was disconnected on the dashboard | Shopkeeper types the new code on their dashboard |
| Customer sees "The shop's printer computer looks offline" | App has been offline for 45+ seconds (the customer can still send; the job waits) | As above |
| Customer sees "This shop is not taking orders right now" | The shop is switched off, or (after migration 0018) it already has 150 jobs waiting for approval: look at the report; the waiting jobs expire by themselves an hour after they were sent | If it is switched off: `PY scripts/ap_remote.py shop-on ABC123` (and `shop-off ABC123` to stop taking orders; nothing is deleted, jobs already sent still print, and the shopkeeper's dashboard link stops working while it is off). **Not yet run live** |
| Shop name or prices are wrong | | `rename ABC123 "New name"`; `prices ABC123` shows the current prices; `set-rates` publishes new ones. **Not yet run live** |
| A request answers "try again" (503) | The database or file storage had a hiccup | It is safe to retry; the apps do. If it lasts, check `https://autoprint-v4.vercel.app/health/ready` |
| Job stuck as `needs_attention` | The app could not confirm the print (queue stuck, printer error, app restarted mid-print) | Check the printer and the Windows print queue; shopkeeper resolves it in the app. The system never reprints by itself |
| Job `failed` with printer not found | The chosen printer was renamed or removed | Printers button in the app, choose it again |
| SmartScreen or antivirus blocks the installer | Unsigned file | See `DESKTOP_DISTRIBUTION.md`; report the false positive to Microsoft; click Run anyway |
| Shopkeeper lost their link | | Issue a new one with `shop-link` and revoke the old with `revoke-link ABC123 --label owner` (it revokes every login of that shop with that label, so use a distinct label per person) |
| A helper with email sign-in has left | | `remove-email helper@example.com`: stops new sign-ins and the keys that address already has (needs migration 0010) |

## 5. Retention and deletion on request
- Rules (decisions O-5, O-10, H-9; migration 0021): an unsent file 1 hour; a file waiting, approved or printing up to 48 hours; a file that was sent to the printer, rejected, cancelled or not approved in time is due at once; a file whose print did not go through is kept 24 hours for "Print again"; unapproved jobs expire 1 hour after submit. "Due" means the next cleanup removes it from storage: about a minute while a shop computer is on. If no shop computer is on and the scheduled workflow is not working (see the next line), due files stay until one of them runs.
- The cleanup runs when a shop app polls (at most once a minute) and from the scheduled workflow `.github/workflows/maintenance.yml` every 15 minutes. **One manual step:** add the repository secret `AUTOPRINT_MAINTENANCE_TOKEN` (the workflow fails loudly until you do).
- Deletion proven locally by tests and live for the storage cache issue (a deleted file is not readable through an unauthenticated URL). **Not yet verified live:** that a file past its real window is gone and an old signed URL stops working; this needs waiting out a real window.
- Purge a customer's order on request: `PY scripts/ap_remote.py purge ABC123 K7QD` (shop code, then the 4-character order code the customer sees). It deletes the uploaded files at once and keeps the order record without any file. It is refused while a job is waiting, approved or printing; reject or cancel it first. Tested locally and run live on a finished test order (1 file deleted, repeat deleted 0). An order code is reused after its order ends, so one shop can have several orders with the same code in 30 days: only the most recent one is purged, and the command lists every match with its time; add `--which 2` for the one before, and so on (tested locally 7 Oct 2026, **not yet run live**). After migration 0015 a deleted file also loses its name and checksum in the database (the name becomes "deleted file").

## 6. Reboot and soak
- Reboot test: **not yet run.** The app starts at sign-in with `--background` (tray, no window) when that option is on.
- 24-hour idle soak: **not yet run.**

## 7. Secrets and access
- Local `.env` (git-ignored) holds the Supabase and maintenance values. Never paste them in chat or commit them.
- The maintenance token can run migrations, issue shop logins and read reports. Rotate it by changing the Vercel environment variable and the GitHub secret, then redeploying.
- Vercel only applies environment changes to new deployments: redeploy after every change.

## 8. After new code goes live: database updates
The site and the database are updated separately. New code is written to work with the old database, so the order is always: **site first, then the database.**
1. `PY scripts/ap_remote.py status` says whether the site is up, whether it can reach the database, which database updates (migrations) are applied and which are still PENDING. It changes nothing.
2. `PY scripts/ap_remote.py migrate` applies the pending ones, in order, each in its own transaction (a failing one changes nothing and stops the run), and lists what it applied. Running it again is safe: it answers "Nothing to apply".
3. Run `status` again: it must say "Nothing pending".
4. Send one PDF from `/s/TST001` and approve it in the Windows app, or run `PY e2e/run_live_e2e.py`.

Both commands are tested locally against a scratch database (7 Oct 2026). **Not yet run live.** If `status` warns that the database has updates the live code does not know, an older version of the site is live: redeploy the current one.

## 9. What the shopkeeper can now do alone, and publishing the installer (7 October 2026, after migration 0020)

- **Name, prices, colour:** on the dashboard, "Prices and shop details". Saving new prices publishes a new price list version, the same as `set-rates`; an order already priced keeps its price. "Black & white only" tells customers the shop has no colour printing and the server refuses colour. The founder tools (`rename`, `set-rates`, `prices`) still work. **Not yet used on the live site.**
- **Installer download:** the dashboard's "Download AutoPrint for Windows" button opens `https://github.com/P-Suraj/AutoPrint-V4/releases/latest/download/AutoPrintSetup.exe`. It works only after a release exists. For every new build:
  1. `powershell -ExecutionPolicy Bypass -File apps\desktop\installer\build.ps1 -Version x.y.z` (writes `dist\AutoPrintSetup-x.y.z.exe` and the same file as `dist\AutoPrintSetup.exe`).
  2. On GitHub: the repository, Releases, "Draft a new release", tag `vx.y.z`, attach `dist\AutoPrintSetup.exe` (this exact name) and the `.sha256.txt` file, Publish.
  3. Open the dashboard and press the button once to see that the download starts.
  The repository is public, so anyone with the link can download the installer; it holds no secrets (a shop is connected afterwards with the code on the dashboard).
