using AutoPrint.Core.Printing;
using AutoPrint.Core.Shop;

namespace AutoPrint.Core.Agent;

public enum RunKind { NoJob, Completed, Failed, Uncertain }
/// <param name="Detail">What the print program itself said when it failed (engine_timeout, exit_code_1, ...), or null.</param>
/// <param name="Printer">The printer the job was meant for, so the shopkeeper can be told which one to check.</param>
public sealed record RunResult(RunKind Kind, Guid? JobId, string Reason, string? Detail = null, string? Printer = null);

public enum Stage { Idle, Claimed, Downloading, Printing, Watching, Reporting }
public sealed record Activity(Stage Stage, Guid? JobId, string? Detail);

public sealed record OrchestratorOptions(
    string WorkDir,
    Func<PrintOptions, string> PrinterFor,
    Func<int, TimeSpan>? WaitLimit = null,
    TimeSpan? LeaseRenewEvery = null,
    TimeSpan? SpoolPoll = null,
    int ReportAttempts = 6,
    TimeSpan? RetryDelay = null,
    TimeSpan? RenewBeforePrintAfter = null);

/// <summary>
/// One print job, start to finish. Order of events is the safety property (decision F-8):
///   claim -> journal(Claimed) -> download+verify -> journal(Downloaded) -> journal(Intent) -> print ->
///   journal(Sent) -> tell server -> watch spooler -> decide -> report -> journal(Reported).
/// Anything unclear is reported "uncertain" for a person. A job is never printed twice by this code.
/// </summary>
public sealed class PrintOrchestrator(
    IShopApi api, IPrintEngine engine, ISpoolerObserver observer, Journal journal, IDownloader downloader,
    OrchestratorOptions options, Action<string>? log = null)
{
    /// <summary>Reason reported when the local print record cannot be written: the job is failed, never printed.</summary>
    public const string JournalUnavailable = "journal_unavailable";

    public event Action<Activity>? ActivityChanged;
    private void Emit(Stage s, Guid? job = null, string? detail = null)
    {
        try { ActivityChanged?.Invoke(new(s, job, detail)); }
        catch (Exception e) { Log("activity listener failed: " + SafeText.Describe(e)); }    // a display problem must not change what happens to a print
    }
    private void Log(string m) { try { log?.Invoke(m); } catch (Exception) { /* logging must never change the outcome of a print */ } }

    public async Task<RunResult> RunOnceAsync(CancellationToken ct)
    {
        Claim? claim = await api.ClaimAsync(ct);
        if (claim is null) return new(RunKind.NoJob, null, "no_job");

        Emit(Stage.Claimed, claim.JobId);
        var sinceClaim = System.Diagnostics.Stopwatch.StartNew();
        var printer = options.PrinterFor(claim.Options);
        var expected = PageRange.ExpectedPages(claim.Options, claim.PageCount);
        var file = Path.Combine(options.WorkDir, claim.SpoolerJobName + ".pdf");
        Log($"claimed job {Short(claim.JobId)}");

        try
        {
            // One job at a time: anything still in the work folder belongs to a job that has ended (a crash, a power
            // cut, a file that was locked when its job finished). No customer document stays on this PC.
            WorkFiles.CleanStale(options.WorkDir);

            // ---- before anything is sent: any problem here is a clean failure ---------------------------------
            // No journal, no print: the record must exist before the irreversible step, so without it the job fails.
            try { journal.Begin(claim.AttemptId, claim.JobId, claim.SpoolerJobName, claim.AttemptToken, printer, expected); }
            catch (Exception e) when (e is not OperationCanceledException)
            {
                Log("print record unavailable: " + SafeText.Describe(e));
                return await ReportAsync(claim, Outcome.Failed, JournalUnavailable, null, ct);
            }

            if (string.IsNullOrWhiteSpace(printer) || !observer.PrinterExists(printer))
                return await ReportAsync(claim, Outcome.Failed, "printer_not_found", null, ct) with { Printer = printer };
            if (engine.NotReady() is { } notReady)
                return await ReportAsync(claim, Outcome.Failed, notReady, null, ct);
            // A page range that is not a plain "1-3,5" is not guessed at: the print program would ignore it and print
            // every page. The job fails here, before the file is even fetched, and a person decides what to do.
            if (!PageRange.TryNormalize(claim.Options.PageRange, out _))
                return await ReportAsync(claim, Outcome.Failed, PageRange.InvalidReason, null, ct);

            Emit(Stage.Downloading, claim.JobId);
            try { await downloader.DownloadAsync(claim.DownloadUrl, claim.Sha256, claim.Bytes, file, ct); }
            catch (DownloadFailedException e) { return await ReportAsync(claim, Outcome.Failed, e.Reason, null, ct); }
            journal.Advance(claim.AttemptId, AttemptState.Downloaded);

            // A slow download can use up most of the lease. Printing on a lease the server has already given up
            // would put paper out for a job it now shows as "needs attention", so check it is still ours first.
            if (sinceClaim.Elapsed >= (options.RenewBeforePrintAfter ?? TimeSpan.FromSeconds(120)))
            {
                try { await api.RenewAsync(claim.AttemptId, claim.AttemptToken, 300, ct); }
                catch (ApiRejectedException) { return await ReportAsync(claim, Outcome.Failed, "lease_lost_before_print", null, ct); }
                catch (ServerUnreachableException) { return await ReportAsync(claim, Outcome.Failed, "offline_before_print", null, ct); }
            }

            // ---- the irreversible step: record intent FIRST, then print ----------------------------------------
            journal.Advance(claim.AttemptId, AttemptState.Intent);
            Emit(Stage.Printing, claim.JobId);

            // ---- watch the spooler, keeping the lease alive ----------------------------------------------------
            // The watch starts together with the print process, not after it: a long job would otherwise outlive its
            // lease before the first renewal, and a short one could leave the queue before anyone looked.
            var wait = (options.WaitLimit ?? WaitLimit.For)(expected);
            var renewEvery = options.LeaseRenewEvery ?? TimeSpan.FromSeconds(60);
            using var watchCts = CancellationTokenSource.CreateLinkedTokenSource(ct);
            var submitting = SubmitQuietlyAsync(new PrintRequest(file, printer, claim.Options, claim.SpoolerJobName, expected), ct);
            var watching = SpoolWatcher.WatchAsync(observer, printer, claim.SpoolerJobName, expected, wait,
                async t => await RenewQuietlyAsync(claim, t), renewEvery, watchCts.Token, options.SpoolPoll, waitStartsAfter: submitting);
            SubmitResult submit;
            SpoolEvidence evidence;
            try
            {
                submit = await submitting;
                if (submit.Accepted)
                {
                    journal.Advance(claim.AttemptId, AttemptState.Sent);
                    await TellServerSentAsync(claim, ct);
                }
                Emit(Stage.Watching, claim.JobId);
                evidence = await watching;
            }
            finally
            {
                watchCts.Cancel();                                                   // never leave the watch running behind us
                try { await watching; } catch (Exception) { /* already finished, or stopped by the line above */ }
            }

            var decision = OutcomeRules.Decide(submit, evidence);
            return await ReportAsync(claim, decision.Outcome, decision.Reason, evidence, ct) with { Detail = submit.Error, Printer = printer };
        }
        finally
        {
            // the print program can hold the file for a moment after it is stopped; whatever survives this is removed
            // before the next job and at the next start (WorkFiles.CleanStale)
            if (!await WorkFiles.DeleteAsync(file)) Log($"job {Short(claim.JobId)}: work file still locked; it is removed before the next job");
            Emit(Stage.Idle);
        }
    }

    private async Task<SubmitResult> SubmitQuietlyAsync(PrintRequest request, CancellationToken ct)
    {
        try { return await engine.SubmitAsync(request, ct); }
        catch (OperationCanceledException) { throw; }
        catch (Exception e) { return new SubmitResult(false, e.GetType().Name); }
    }

    private async Task TellServerSentAsync(Claim claim, CancellationToken ct)
    {
        for (int i = 0; i < 4; i++)
        {
            try { await api.MarkSentAsync(claim.AttemptId, claim.AttemptToken, ct); return; }
            catch (ServerUnreachableException) { await Task.Delay(Delay(i), ct); }
            catch (ApiRejectedException) { return; }     // the lease was lost, or the server refused: keep watching, the report will say so
        }
    }

    private async Task RenewQuietlyAsync(Claim claim, CancellationToken ct)
    {
        try { await api.RenewAsync(claim.AttemptId, claim.AttemptToken, 300, ct); }
        catch (ServerUnreachableException) { /* try again at the next tick */ }
        catch (ApiRejectedException) { /* stale: the report will explain */ }
    }

    private TimeSpan Delay(int attempt) => (options.RetryDelay ?? TimeSpan.FromSeconds(2)) * Math.Min(1 << attempt, 8);

    /// <summary>Reports the outcome, retrying while the server is unreachable. If it never gets through the
    /// attempt stays in the journal as unreported and is settled at the next start (always as uncertain/failed).</summary>
    private async Task<RunResult> ReportAsync(Claim claim, Outcome outcome, string reason, SpoolEvidence? evidence, CancellationToken ct)
    {
        Emit(Stage.Reporting, claim.JobId, reason);
        var wire = evidence?.ToWire(reason) ?? new Dictionary<string, object?> { ["reason"] = reason };
        for (int i = 0; i < options.ReportAttempts; i++)
        {
            try
            {
                var status = await api.ReportOutcomeAsync(claim.AttemptId, claim.AttemptToken, outcome, wire, ct);
                MarkQuietly(claim.AttemptId, outcome.ToString());
                Log($"job {Short(claim.JobId)} reported {outcome} ({reason}); server status {status}");
                return new(ToKind(outcome), claim.JobId, reason);
            }
            catch (ApiRejectedException e) when (e.IsStaleAttempt || e.Code == "evidence_insufficient")
            {
                // The server decides. "Completed" without sufficient evidence is downgraded to uncertain, once.
                if (e.Code == "evidence_insufficient" && outcome == Outcome.Completed)
                {
                    outcome = Outcome.Uncertain; reason = "server_refused_completed_evidence";
                    wire = (evidence ?? SpoolEvidence.None(0)).ToWire(reason);
                    continue;
                }
                MarkQuietly(claim.AttemptId, "Stale");
                return new(RunKind.Uncertain, claim.JobId, "stale_attempt");
            }
            catch (ApiRejectedException)
            {
                _undelivered[claim.AttemptId] = (outcome, wire);            // refused for another reason (busy server, sign-in): keep what was seen
                throw;
            }
            catch (ServerUnreachableException) { await Task.Delay(Delay(i), ct); }
        }
        _undelivered[claim.AttemptId] = (outcome, wire);
        Log($"job {Short(claim.JobId)}: outcome not delivered; will be settled when the server is reachable");
        return new(RunKind.Uncertain, claim.JobId, "report_undelivered");
    }

    /// <summary>The server has the outcome already; a failed local write only means recovery asks it once more.</summary>
    private void MarkQuietly(Guid attemptId, string outcome)
    {
        try { journal.MarkReported(attemptId, outcome); }
        catch (Exception e) { Log("print record not updated: " + SafeText.Describe(e)); }
    }

    /// <summary>Outcomes this run decided but could not deliver. Kept only in memory: after a restart the journal
    /// alone decides, and that is always uncertain or failed.</summary>
    private readonly Dictionary<Guid, (Outcome Outcome, IDictionary<string, object?> Wire)> _undelivered = [];

    /// <summary>
    /// Call at start-up and before each poll. Settles every attempt whose outcome never reached the server. An
    /// outcome decided in this run is sent as it was, with its evidence. After a restart only the journal is left:
    /// if the print might have started it is "uncertain"; if nothing was ever sent it is "failed". Never reprints.
    /// </summary>
    /// <param name="settledOne">Told about each attempt settled from the journal alone, so the shopkeeper can be told why.</param>
    public async Task<int> RecoverAsync(CancellationToken ct, Action<RunResult>? settledOne = null)
    {
        int settled = 0;
        foreach (var e in journal.Unreported())
        {
            Outcome outcome;
            IDictionary<string, object?> wire;
            string? fromJournal = null;
            if (_undelivered.TryGetValue(e.AttemptId, out var kept)) (outcome, wire) = kept;
            else
            {
                var maybeSent = e.State >= AttemptState.Intent;
                outcome = maybeSent ? Outcome.Uncertain : Outcome.Failed;
                var reason = maybeSent ? "agent_restarted_after_print_intent" : "agent_restarted_before_print";
                wire = new Dictionary<string, object?> { ["reason"] = reason, ["journal_state"] = e.State.ToString() };
                fromJournal = reason;
            }
            try
            {
                await api.ReportOutcomeAsync(e.AttemptId, e.AttemptToken, outcome, wire, ct);
                journal.MarkReported(e.AttemptId, outcome.ToString());
                _undelivered.Remove(e.AttemptId);
                settled++;
                if (fromJournal is not null)
                    try { settledOne?.Invoke(new(ToKind(outcome), e.JobId, fromJournal, null, e.Printer)); }
                    catch (Exception x) { Log("recovery listener failed: " + SafeText.Describe(x)); }
            }
            // "Not signed in" and "too many requests" say nothing about this attempt: keep it and let the caller react.
            catch (ApiRejectedException x) when (x.IsAuthFailure || x.Code == "rate_limited") { throw; }
            catch (ApiRejectedException) { journal.MarkReported(e.AttemptId, "Stale"); _undelivered.Remove(e.AttemptId); settled++; }   // the server already decided
            catch (ServerUnreachableException) { /* still offline: try again next time */ }
        }
        return settled;
    }

    private static RunKind ToKind(Outcome o) => o switch { Outcome.Completed => RunKind.Completed, Outcome.Failed => RunKind.Failed, _ => RunKind.Uncertain };
    private static string Short(Guid g) => g.ToString("N")[..8];
}
