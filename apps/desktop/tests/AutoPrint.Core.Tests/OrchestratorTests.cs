using AutoPrint.Core;
using AutoPrint.Core.Agent;
using AutoPrint.Core.Printing;
using AutoPrint.Core.Shop;
using Xunit;

namespace AutoPrint.Core.Tests;

public class OrchestratorTests
{
    private static Guid AttemptOf(Rig r, Claim c) => c.AttemptId;

    [Fact]
    public async Task Happy_path_reports_completed_with_rule_v1_evidence_and_cleans_up()
    {
        using var rig = new Rig(FakeScenario.Success);
        var claim = rig.Api.NextClaim!;
        var res = await rig.Orchestrator.RunOnceAsync(default);

        Assert.Equal(RunKind.Completed, res.Kind);
        Assert.Equal(["claim", "sent", "report:Completed"], rig.Api.Calls);
        var evidence = rig.Api.Reports.Single().Evidence;
        Assert.Equal(1, evidence["rule_version"]);
        Assert.Equal(true, evidence["spooler_job_seen"]);
        Assert.Equal(true, evidence["left_queue"]);
        Assert.Equal(AttemptState.Reported, rig.Journal.StateOf(claim.AttemptId));
        Assert.Empty(Directory.GetFiles(Path.Combine(rig.Dir, "work")));            // the document is deleted after the job
        Assert.Equal(1, rig.Spooler.SubmitCount);
        Assert.Equal(claim.SpoolerJobName + ".pdf", Path.GetFileName(rig.Spooler.Submitted[0].FilePath));   // printed under the unique name
        Assert.Equal(Stage.Idle, rig.Activities.Last().Stage);
    }

    [Fact]
    public async Task No_job_does_nothing()
    {
        using var rig = new Rig();
        rig.Api.NextClaim = null;
        var res = await rig.Orchestrator.RunOnceAsync(default);
        Assert.Equal(RunKind.NoJob, res.Kind);
        Assert.Equal(["claim"], rig.Api.Calls);
        Assert.Equal(0, rig.Spooler.SubmitCount);
    }

    [Fact]
    public async Task Unknown_printer_fails_cleanly_before_anything_is_sent()
    {
        using var rig = new Rig(printer: "No Such Printer");
        var res = await rig.Orchestrator.RunOnceAsync(default);
        Assert.Equal(RunKind.Failed, res.Kind);
        Assert.Equal("printer_not_found", res.Reason);
        Assert.Equal(0, rig.Spooler.SubmitCount);
        Assert.DoesNotContain("sent", rig.Api.Calls);
    }

    [Theory]
    [InlineData("download_sha256_mismatch")]
    [InlineData("download_unreachable")]
    [InlineData("download_larger_than_expected")]
    public async Task A_bad_download_is_never_printed(string reason)
    {
        using var rig = new Rig();
        rig.Downloader.FailWith = reason;
        var res = await rig.Orchestrator.RunOnceAsync(default);
        Assert.Equal(RunKind.Failed, res.Kind);
        Assert.Equal(reason, res.Reason);
        Assert.Equal(0, rig.Spooler.SubmitCount);
    }

    [Theory]
    [InlineData(FakeScenario.EngineRejects, RunKind.Failed, "engine_failed_nothing_in_spooler")]
    [InlineData(FakeScenario.EngineThrows, RunKind.Failed, "engine_failed_nothing_in_spooler")]
    [InlineData(FakeScenario.NeverAppears, RunKind.Uncertain, "job_never_seen_in_spooler")]
    [InlineData(FakeScenario.CancelledAtPrinter, RunKind.Failed, "cancelled_at_printer_before_any_page")]
    [InlineData(FakeScenario.PaperOut, RunKind.Uncertain, "spooler_error_flag")]
    [InlineData(FakeScenario.RejectsButOrphan, RunKind.Uncertain, "engine_failed_but_job_in_spooler")]
    public async Task Every_failure_mode_ends_in_the_right_outcome(FakeScenario scenario, RunKind kind, string reason)
    {
        using var rig = new Rig(scenario, wait: TimeSpan.FromMilliseconds(400));
        var res = await rig.Orchestrator.RunOnceAsync(default);
        Assert.Equal(kind, res.Kind);
        Assert.Equal(reason, res.Reason);
        Assert.NotEqual(RunKind.Completed, res.Kind);
    }

    [Fact]
    public async Task A_job_stuck_in_the_queue_is_uncertain_not_completed_and_is_not_reprinted()
    {
        using var rig = new Rig(FakeScenario.StuckInQueue, wait: TimeSpan.FromMilliseconds(300));
        var res = await rig.Orchestrator.RunOnceAsync(default);
        Assert.Equal(RunKind.Uncertain, res.Kind);
        Assert.Equal("still_in_queue_when_wait_ended", res.Reason);
        Assert.Equal(1, rig.Spooler.SubmitCount);
    }

    [Fact]
    public async Task Intent_is_journaled_before_the_engine_is_started()
    {
        using var rig = new Rig();
        var claim = rig.Api.NextClaim!;
        AttemptState? seen = null;
        var engine = new CheckingEngine(rig.Spooler, () => seen = rig.Journal.StateOf(claim.AttemptId));
        var o = new PrintOrchestrator(rig.Api, engine, rig.Spooler, rig.Journal, rig.Downloader,
            new OrchestratorOptions(Path.Combine(rig.Dir, "work"), _ => "Test Printer", _ => TimeSpan.FromSeconds(2), SpoolPoll: TimeSpan.FromMilliseconds(5)));
        await o.RunOnceAsync(default);
        Assert.Equal(AttemptState.Intent, seen);          // the safety property: written first, then printed
    }

    private sealed class CheckingEngine(IPrintEngine inner, Action onSubmit) : IPrintEngine
    {
        public Task<SubmitResult> SubmitAsync(PrintRequest r, CancellationToken ct) { onSubmit(); return inner.SubmitAsync(r, ct); }
    }

    // ------------------------------------------------------------------ the network misbehaves
    [Fact]
    public async Task Report_is_retried_while_the_server_is_unreachable()
    {
        using var rig = new Rig();
        rig.Api.ReportUnreachableTimes = 2;
        var res = await rig.Orchestrator.RunOnceAsync(default);
        Assert.Equal(RunKind.Completed, res.Kind);
        Assert.Equal(3, rig.Api.Calls.Count(c => c == "report:Completed"));
        Assert.Equal(1, rig.Spooler.SubmitCount);                         // retrying the report never reprints
    }

    [Fact]
    public async Task Mark_sent_is_retried()
    {
        using var rig = new Rig();
        rig.Api.MarkSentUnreachableTimes = 2;
        var res = await rig.Orchestrator.RunOnceAsync(default);
        Assert.Equal(RunKind.Completed, res.Kind);
        Assert.Equal(3, rig.Api.Calls.Count(c => c == "sent"));
    }

    [Fact]
    public async Task An_undeliverable_outcome_stays_in_the_journal_and_is_settled_later_as_uncertain_never_reprinted()
    {
        using var rig = new Rig();
        var claim = rig.Api.NextClaim!;
        rig.Api.ReportAlwaysUnreachable = true;
        var res = await rig.Orchestrator.RunOnceAsync(default);
        Assert.Equal("report_undelivered", res.Reason);
        Assert.Equal(AttemptState.Sent, rig.Journal.StateOf(claim.AttemptId));       // not lost

        rig.Api.ReportAlwaysUnreachable = false;                                      // the network comes back; the app restarts
        var settled = await rig.MakeOrchestrator().RecoverAsync(default);
        Assert.Equal(1, settled);
        Assert.Equal(Outcome.Uncertain, rig.Api.Reports.Last().Outcome);              // after a print was started: a person decides
        Assert.Equal(AttemptState.Reported, rig.Journal.StateOf(claim.AttemptId));
        Assert.Equal(1, rig.Spooler.SubmitCount);
    }

    [Fact]
    public async Task A_stale_attempt_is_accepted_as_the_servers_decision()
    {
        using var rig = new Rig();
        var claim = rig.Api.NextClaim!;
        rig.Api.ReportStale = true;
        var res = await rig.Orchestrator.RunOnceAsync(default);
        Assert.Equal("stale_attempt", res.Reason);
        Assert.Equal(AttemptState.Reported, rig.Journal.StateOf(claim.AttemptId));    // no endless retrying
    }

    [Fact]
    public async Task If_the_server_refuses_completed_evidence_it_is_downgraded_to_uncertain()
    {
        using var rig = new Rig();
        rig.Api.RefuseCompletedEvidence = true;
        var res = await rig.Orchestrator.RunOnceAsync(default);
        Assert.Equal(RunKind.Uncertain, res.Kind);
        Assert.Equal(["claim", "sent", "report:Completed", "report:Uncertain"], rig.Api.Calls);
    }

    // ------------------------------------------------------------------ the app is killed
    [Fact]
    public async Task Shutting_down_mid_print_reports_nothing_and_the_next_start_reports_uncertain()
    {
        using var rig = new Rig(FakeScenario.StuckInQueue, wait: TimeSpan.FromSeconds(30));
        var claim = rig.Api.NextClaim!;
        using var cts = new CancellationTokenSource(TimeSpan.FromMilliseconds(150));
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => rig.Orchestrator.RunOnceAsync(cts.Token));
        Assert.DoesNotContain(rig.Api.Calls, c => c.StartsWith("report"));            // no guess was reported
        Assert.True(rig.Journal.StateOf(claim.AttemptId) >= AttemptState.Intent);

        var settled = await rig.MakeOrchestrator().RecoverAsync(default);              // "after the restart"
        Assert.Equal(1, settled);
        Assert.Equal(Outcome.Uncertain, rig.Api.Reports.Single().Outcome);
        Assert.Equal(1, rig.Spooler.SubmitCount);                                      // and it did not print again
    }

    [Fact]
    public async Task Recovery_after_a_crash_before_printing_reports_failed()
    {
        using var rig = new Rig();
        var c = rig.Api.NextClaim!;
        rig.Journal.Begin(c.AttemptId, c.JobId, c.SpoolerJobName, c.AttemptToken, "Test Printer", 3);
        rig.Journal.Advance(c.AttemptId, AttemptState.Downloaded);
        Assert.Equal(1, await rig.Orchestrator.RecoverAsync(default));
        Assert.Equal(Outcome.Failed, rig.Api.Reports.Single().Outcome);
        Assert.Equal(0, rig.Spooler.SubmitCount);
    }

    [Fact]
    public async Task Recovery_when_still_offline_keeps_the_entry_for_next_time()
    {
        using var rig = new Rig();
        var c = rig.Api.NextClaim!;
        rig.Journal.Begin(c.AttemptId, c.JobId, c.SpoolerJobName, c.AttemptToken, "Test Printer", 3);
        rig.Journal.Advance(c.AttemptId, AttemptState.Intent);
        rig.Api.ReportAlwaysUnreachable = true;
        Assert.Equal(0, await rig.Orchestrator.RecoverAsync(default));
        Assert.Single(rig.Journal.Unreported());
    }

    // ------------------------------------------------------------------ housekeeping
    [Fact]
    public async Task The_lease_is_renewed_while_a_long_job_is_watched()
    {
        using var rig = new Rig(FakeScenario.StuckInQueue);
        var o = rig.MakeOrchestrator(wait: TimeSpan.FromMilliseconds(400), renew: TimeSpan.FromMilliseconds(80));
        await o.RunOnceAsync(default);
        Assert.True(rig.Api.RenewCount >= 2, $"renewed {rig.Api.RenewCount} times");
    }

    [Fact]
    public async Task Copies_and_page_range_set_the_expected_page_count_and_wait()
    {
        using var rig = new Rig(copies: 3, pages: 10);
        rig.Api.NextClaim = rig.Api.NextClaim! with { Options = new PrintOptions(3, false, false, "1-4") };
        await rig.Orchestrator.RunOnceAsync(default);
        Assert.Equal(12, rig.Spooler.Submitted[0].ExpectedPages);                      // 4 pages x 3 copies
        Assert.Equal(TimeSpan.FromSeconds(60), WaitLimit.For(12));                     // minimum 60 s
        Assert.Equal(TimeSpan.FromSeconds(155), WaitLimit.For(50));                    // 30 s + 2.5 s per page
    }
}
