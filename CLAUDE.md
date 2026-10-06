# AutoPrint V4: standing instructions for any AI model working here

Read `docs/HANDOVER.md` first (state, rules, how to work), then `docs/IMPLEMENTATION_STATUS.md` (evidence, what is unverified). `docs/DECISIONS.md` holds what the founder has decided; do not reopen it.

## Documentation is part of the work (founder's standing rule, 6 October 2026)

Model time on this project is expensive. Anything learned and not written into the repository is paid for again later. So, by default and without being asked:

1. **Write findings down when they arrive, not at the end.** A sub-agent's report, a review finding, a measurement, a root cause, a failed approach, a founder decision: each goes into a file in the same work block. A result that exists only in the chat is lost.
2. **Where things go** (keep to this small set; do not create new status files):
   - `docs/IMPLEMENTATION_STATUS.md`: what was built, what was checked and how (command and result), what is **not verified**, what is not done, known defects left open. The only status file.
   - `docs/HANDOVER.md`: current state for a model with no memory of earlier sessions: what is live, what is pending, next steps in order, tooling gotchas. Update it when any of those change.
   - `docs/DECISIONS.md`: every founder decision, dated, in the founder's meaning. Append; never rewrite history.
   - `docs/RUNBOOK.md`, `docs/TEST_THE_WINDOWS_APP.md`, `docs/pilot/`: update in the same commit as the behaviour they describe.
   - Design work for something not yet built gets one file in `docs/` (for example `docs/PAYMENTS_DESIGN.md`).
3. **Record negative results and open risks**, not only successes: what was tried and did not work, what a review found and nobody fixed, what could not be checked and why.
4. **Say how each claim was verified.** "Tests pass" needs the command and the count. Mark anything unverified as unverified. A statement taken on the founder's word is recorded as such.
5. **Commit at the end of every work block**, including documentation, so a stopped session loses nothing. When sub-agents are running, stage only the paths that are finished.
6. **Before stopping for any reason** (done, blocked, out of budget): status and handover are current, the next steps are listed in order, and anything the founder must do himself is listed with the exact command.
7. **Sub-agents:** tell each one which files it owns, and require a final report with what it verified, what it changed, and what is still unverified. Fold that report into the status file yourself; the sub-agent's transcript is not kept.

## Rules that must never be broken

- Never modify, deploy over, or connect to V3 (`F:\Projects\Printer automation`, `F:\AutoPrint`, `%LOCALAPPDATA%\AutoPrint`, the V3 Supabase and Vercel projects).
- Never print, log or commit secrets (`.env`, `dist\SHOP_LINK.txt`, tokens, signed URLs, shop keys).
- A job is never printed twice without a human action. Anything uncertain goes to a human.
- Free resources only unless the founder says otherwise.
- Report honestly: no claim without evidence.
- Migrations already applied to the live database are never edited; add a new numbered file.
- Founder's design bar: no lag, calm and purposeful motion, not a generic AI look, minimal and easy to use.
