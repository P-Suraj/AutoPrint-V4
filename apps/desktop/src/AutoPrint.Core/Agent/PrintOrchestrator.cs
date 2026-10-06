using AutoPrint.Core.Printing;
using AutoPrint.Core.Shop;

namespace AutoPrint.Core.Agent;

public enum RunKind { NoJob, Completed, Failed, Uncertain }
public sealed record RunResult(RunKind Kind, Guid? JobId, string Reason);

public enum Stage { Idle, Claimed, Downloading, Printing, Watching, Reporting }
public sealed record Activity(Stage Stage, Guid? JobId, string? Detail);

public sealed record OrchestratorOptions(
    string WorkDir,
    Func<PrintOptions, string> PrinterFor,
    Func<int, TimeSpan>? WaitLimit = null,
    TimeSpan? LeaseRenewEvery = null,
    TimeSpan? SpoolPoll = null,
    int ReportAttempts = 6,
    TimeSpan? RetryDelay = null);

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
    public event Action<Activity>? ActivityChanged;
    private void Emit(Stage s, Guid? job = null, string? detail = null) => ActivityChanged?.Invoke(new(s, job, detail));
    private void Log(string m) => log?.Invoke(m);

    public async Task<RunResult> RunOnceAsync(CancellationToken ct)
    {
        Claim? claim = await api.ClaimAsync(ct);
        if (claim is null) return new(RunKind.NoJob, null, "no_job");

        Emit(Stage.Claimed, claim.JobId);
        var printer = options.PrinterFor(claim.Options);
        var expected = PageRange.ExpectedPages(claim.Options, claim.PageCount);
        journal.Begin(claim.AttemptId, claim.JobId, claim.SpoolerJobName, claim.AttemptToken, printer, expected);
        var file = Path.Combine(options.WorkDir, claim.SpoolerJobName + ".pdf");
        Log($"claimed job {Short(claim.JobId)}");

        try
        {
            // ---- before anything is sent: any problem here is a clean failure ---------------------------------
            if (string.IsNullOrWhiteSpace(printer) || !observer.PrinterExists(printer))
                return await ReportAsync(claim, Outcome.Failed, "printer_not_found", null, ct);

            Emit(Stage.Downloading, claim.JobId);
            try { await downloader.DownloadAsync(claim.DownloadUrl, claim.Sha256, claim.Bytes, file, ct); }
            catch (DownloadFailedException e) { return await ReportAsync(claim, Outcome.Failed, e.Reason, null, ct); }
            journal.Advance(claim.AttemptId, AttemptState.Downloaded);

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
            return await ReportAsync(claim, decision.Outcome, decision.Reason, evidence, ct);
        }
        finally
        {
            try { if (File.Exists(file)) File.Delete(file); } catch (IOException) { /* best effort; nothing sensitive is kept longer than needed */ }
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
            catch (ApiRejectedException e) when (e.IsStaleAttempt) { return; }     // the lease was lost; the report will say so
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
                journal.MarkReported(claim.AttemptId, outcome.ToString());
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
                journal.MarkReported(claim.AttemptId, "Stale");
                return new(RunKind.Uncertain, claim.JobId, "stale_attempt");
            }
            catch (ServerUnreachableException) { await Task.Delay(Delay(i), ct); }
        }
        _undelivered[claim.AttemptId] = (outcome, wire);
        Log($"job {Short(claim.JobId)}: outcome not delivered; will be settled when the server is reachable");
        return new(RunKind.Uncertain, claim.JobId, "report_undelivered");
    }

    /// <summary>Outcomes this run decided but could not deliver. Kept only in memory: after a restart the journal
    /// alone decides, and that is always uncertain or failed.</summary>
    private readonly Dictionary<Guid, (Outcome Outcome, IDictionary<string, object?> Wire)> _undelivered = [];

    /// <summary>
    /// Call at start-up and before each poll. Settles every attempt whose outcome never reached the server. An
    /// outcome decided in this run is sent as it was, with its evidence. After a restart only the journal is left:
    /// if the print might have started it is "uncertain"; if nothing was ever sent it is "failed". Never reprints.
    /// </summary>
    public async Task<int> RecoverAsync(CancellationToken ct)
    {
        int settled = 0;
        foreach (var e in journal.Unreported())
        {
            Outcome outcome;
            IDictionary<string, object?> wire;
            if (_undelivered.TryGetValue(e.AttemptId, out var kept)) (outcome, wire) = kept;
            else
            {
                var maybeSent = e.State >= AttemptState.Intent;
                outcome = maybeSent ? Outcome.Uncertain : Outcome.Failed;
                var reason = maybeSent ? "agent_restarted_after_print_intent" : "agent_restarted_before_print";
                wire = new Dictionary<string, object?> { ["reason"] = reason, ["journal_state"] = e.State.ToString() };
            }
            try
            {
                await api.ReportOutcomeAsync(e.AttemptId, e.AttemptToken, outcome, wire, ct);
                journal.MarkReported(e.AttemptId, outcome.ToString());
                _undelivered.Remove(e.AttemptId);
                settled++;
            }
            catch (ApiRejectedException) { journal.MarkReported(e.AttemptId, "Stale"); _undelivered.Remove(e.AttemptId); settled++; }   // the server already decided
            catch (ServerUnreachableException) { /* still offline: try again next time */ }
        }
        return settled;
    }

    private static RunKind ToKind(Outcome o) => o switch { Outcome.Completed => RunKind.Completed, Outcome.Failed => RunKind.Failed, _ => RunKind.Uncertain };
    private static string Short(Guid g) => g.ToString("N")[..8];
}
