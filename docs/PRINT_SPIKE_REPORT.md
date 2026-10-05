# Phase 1 — Print Spike Report

**Date:** 5 October 2026
**Gate status: NOT PASSED.** Every measurement below was taken on a **virtual** printer. The build plan requires a **physical** printer for this gate. The founder allowed a virtual printer for testing; this report treats that as a way to make progress, not as a pass. The completion rule is version 1 and **must be re-validated on a real printer** before Phase 8.

## What was tested

| Item | Value |
|---|---|
| PC | Windows 11 Home Insider Preview, build 10.0.26220 |
| Printer | "AutoPrint-Spike-PDF": driver *Microsoft Print To PDF*, port set to a fixed file path so no Save-As prompt appears. **Virtual.** |
| Engine | SumatraPDF 3.6.1, **portable** build, command line `-print-to <printer> -print-settings <...> <file>` |
| Observation | Windows spooler polled every 25 ms through `EnumJobs` (pywin32) while each job ran |
| Test files | 1, 10 and 50 pages; 6 pages mixed portrait/landscape; 3-page and 6-page image PDFs of 8.7 MB and 21.5 MB |
| Raw data | `spikes/_out/results.json` (not committed; regenerate with `spikes/spike_print.py`) |

Not tested: any physical printer; duplex and colour output (the virtual driver ignores them); printer powered off, cable pulled, paper empty, paper jam, driver-reported errors; PC restart mid-job. A Kyocera TASKalfa 3212i is installed on this PC but was **offline** and was deliberately not used.

## Results

### Normal prints: 30 consecutive jobs

- 30 of 30 exited with code 0.
- 30 of 30 were found in the spooler **by the unique file name** given to Sumatra. This is the correlation key: the agent prints each job under a name like `apjob_<32 hex>.pdf` and looks for that name. It removes V3's "any new job on this printer" guess.
- 30 of 30 produced an output file with the correct page count.
- The job appeared in the spooler 0.3–0.8 s after launch.
- Time from launch until the job left the queue:

| File | Jobs | Sumatra exits after | Job leaves queue after (min / median / max) |
|---|---|---|---|
| 1 page | 5 | 1.0–1.4 s | 2.0 / 2.1 / 2.3 s |
| 6 pages, mixed orientation | 5 | 4.8–6.6 s | 7.9 / 9.6 / 10.1 s |
| 3 pages, image-heavy (8.7 MB) | 5 | 8.9–11.5 s | 11.3 / 13.0 / 14.1 s |
| 10 pages | 5 | 7.5–11.6 s | 12.0 / 15.8 / 17.0 s |
| 6 pages, image-heavy (21.5 MB) | 5 | 16.8–21.1 s | 21.1 / 24.6 / 26.0 s |
| 50 pages | 5 | 49.7–57.2 s | 77.3 / 82.5 / 85.2 s |

**25 of 30 jobs took longer than 6 seconds**, which was V3's fixed observation window. Under V3's rule they would have been recorded wrongly. The wait must scale with the job.

### Status signals

A normal job shows: `SPOOLING` while Sumatra sends pages, then `PRINTING` with a `RETAINED` flag while the page counter climbs, then the job disappears. On this driver the page counter is reported oddly (printed rises while total falls); the code uses only the highest printed value seen.

### Settings the engine honoured (checked by counting pages in the output file)

| Request | Pages in output |
|---|---|
| 10-page file, defaults | 10 |
| 3 copies | 30 |
| page range `2-4` | 3 |
| page range `1,3,5-6` | 4 |
| 2 copies, range `1-2` | 4 |

Copies and page ranges are applied correctly. **Duplex and colour could not be checked**: the output pages did not change, and the virtual driver has no duplex or colour. These must be verified on the physical printer.

### Failure drills

| Drill | What happened | Consequence |
|---|---|---|
| Queue paused, job sent | Job stayed queued with no progress; after resume it left the queue normally | A job that never leaves the queue is *uncertain*, not failed |
| Sumatra killed before spooling (0.3 s) | Exit code 1; **no spooler job ever appeared**; no output | Never seen in the spooler = nothing was sent |
| Sumatra killed mid-spool (3 s into 50 pages) | Exit code 1; an **orphan job stayed in the spooler**, stuck at 0 of N pages, unchanged after 23 s, and later could not be purged (`DELETING`) | After an agent crash, orphans must be found by their `apjob_` name and dealt with. A stuck job blocks that printer queue |
| **Job cancelled at the spooler** | Status `DELETING`, then the job **left the queue** | **"Left the queue" does not prove it printed.** A cancelled job leaves the queue too. V3's rule would have called it done |
| Printer name does not exist | Sumatra **did not exit within 60 s** | Check that the printer exists before printing, always use a timeout, and kill a hung process |
| Page counter | The final increment was not seen in 4 of 37 jobs because the job left the queue between samples | The rule must not require "pages printed = total" |

### Findings about V3

1. V3's `windows-agent/sumatrapdf/SumatraPDF.exe` is **byte-identical to the installer** (`SumatraPDF-3.6.1-64-install.exe`, same SHA-256). Launching it starts the installer, not a print. The real portable program is a different 20 MB file. V3's installed agent contains the installer copy too. V4 must ship the portable build and verify the hash.
2. The 6-second window, "left the queue = confirmed", and "any new spooler job" were each wrong in a measurable way above.

## Completion rule, version 1

Implemented in `supabase/migrations/0003_completion_rule.sql` and tested in `supabase/tests/test_completion_rule.py`.

A job is recorded **completed** only when the agent's evidence shows all of:

1. the job was found in the spooler under its unique name;
2. the spooler reported it as printing at some point;
3. the job was seen leaving the queue;
4. none of these flags appeared at any sample: `ERROR`, `DELETING`, `DELETED`, `OFFLINE`, `PAPEROUT`, `BLOCKED_DEVQ`, `USER_INTERVENTION`, `RESTART`;
5. at least one page was reported printed.

Anything else is **never** completed:

| Observation | Agent reports | Job becomes |
|---|---|---|
| Print process failed and the job never appeared in the spooler | `failed` | `failed` |
| Job appeared, then a bad flag (including `DELETING`) | `failed` if the printer stopped it, otherwise `uncertain` | `failed` or `needs_attention` |
| Job still in queue when the wait ends | `uncertain` | `needs_attention` |
| Spooler cannot be read, or agent restarts after sending | `uncertain` | `needs_attention` |
| Lease expires with no report | (system) | `needs_attention` |

A human then chooses: mark completed, mark failed, or retry. A retry is the only way a second attempt is ever created.

**The wait scales with the job.** From the data: allow 30 s plus 2.5 s per page, per copy, with a minimum of 60 s; renew the lease while waiting. The agent stops watching only when the job leaves the queue or that limit passes.

## Measured against V3 and the plan

| Gate item | Status |
|---|---|
| Results table for every test and drill | Done for the virtual printer. Missing for physical-printer drills |
| At least 30 consecutive normal prints | 30 of 30, **virtual printer**. Physical run still required |
| Written completion rule | Done (version 1) |
| Duplex, colour, copies, page range control | Copies and range proven. Duplex and colour **unproven** |
| Engine chosen | SumatraPDF portable **provisional**. A PDFium route through the Windows print API was **not** compared; the .NET SDK was installed only afterwards |
| Stop if the printer reports too little | Not triggered on the virtual printer. The physical printer may report less; check on the first real test |

## What must happen on the real printer

1. Repeat the 30-job run and compare the signals; record the model, driver and connection type.
2. Verify duplex and colour on paper.
3. Run the real drills: printer off, cable out, paper out, jam, cancel at the printer, PC restart mid-job.
4. Record which flags the driver actually raises for each failure. If a jam produces no flag, the rule cannot detect it and F-8 needs the founder's decision.
5. Note: SumatraPDF is licensed GPL-3.0. Shipping it as a separate program is a common arrangement but requires including its license and a source link; confirm before distributing.


## Addendum, 5 October 2026: what the C# desktop app found

Findings from running the real engine (SumatraPDF) and a .NET observer against the same virtual printer. Still **virtual printer only**; the physical-printer gate is not passed.

1. **The pages-printed counter is unreliable, so completion rule v2 no longer requires it** (migration 0006). A job that did print (the output file exists, with the right page count) was reported by Windows with 0 pages printed for its entire time in the queue. Real printer drivers often report no count until the end. Requiring "at least 1 page printed" would have forced a person to resolve jobs that printed correctly. Version 2 keeps every other safeguard: found by unique name, seen printing, seen leaving the queue, and no error or deleting flag. The count is still recorded, as information.
2. **`System.Printing` cannot be used from async code.** Its objects belong to the thread that created them; the app crashed with "the calling thread cannot access this object because a different thread owns it". The app now calls the native spooler API directly (OpenPrinter, EnumJobs, SetJob), exactly what the spike measured.
3. A job cancelled at the spooler is still not judged completed, now confirmed in C# against the real spooler (test `A_job_cancelled_at_the_spooler_is_not_reported_completed`).
4. Sumatra's SHA-256 is checked before every print, because V3 shipped the installer under the name `SumatraPDF.exe`. The expected hash is that of the official portable 3.6.1 (64-bit) build, downloaded from sumatrapdfreader.org and not independently verified against a publisher checksum.

Still open for the physical printer: duplex and colour, real failure flags (jam, paper out, offline), power-off and cable drills, and whether the real driver reports PRINTING at all. If it does not, completion rule v2 would never be satisfied and F-8 needs the founder's decision.
