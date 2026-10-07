using AutoPrint.Core;
using AutoPrint.Core.Agent;
using AutoPrint.Core.Printing;
using AutoPrint.Core.Shop;
using Xunit;

namespace AutoPrint.Core.Tests;

/// <summary>The founder chose "Microsoft Print to PDF"; it opened a Save As window, the job sat for 87 seconds and
/// failed. These tests are about never walking into that again.</summary>
public class PrinterKindTests
{
    [Theory]
    // name, port, driver -> what comes out
    [InlineData("Microsoft Print to PDF", "PORTPROMPT:", "Microsoft Print To PDF", PrinterKind.Prompt)]
    [InlineData("Counter printer", "PORTPROMPT:", "Microsoft Print To PDF", PrinterKind.Prompt)]              // renamed: the port still tells
    [InlineData("Microsoft XPS Document Writer", "PORTPROMPT:", "Microsoft XPS Document Writer v4", PrinterKind.Prompt)]
    [InlineData("Old XPS writer", "XPSPort:", "Microsoft XPS Document Writer", PrinterKind.Prompt)]
    [InlineData("HP LaserJet (print to file)", "FILE:", "HP Universal Printing PCL 6", PrinterKind.Prompt)]    // a real driver on the FILE: port asks for a file name
    [InlineData("HP LaserJet", "LPT1:, FILE:", "HP Universal Printing PCL 6", PrinterKind.Prompt)]
    [InlineData("Fax", "SHRFAX:", "Microsoft Shared Fax Driver", PrinterKind.Prompt)]
    [InlineData("Brother MFC-L2710DW FAX", "USB002", "Brother PC-FAX v.2.2", PrinterKind.Prompt)]
    [InlineData("OneNote (Desktop)", "nul:", "Send to Microsoft OneNote 16 Driver", PrinterKind.Prompt)]
    [InlineData("OneNote for Windows 10", "Microsoft.Office.OneNote_16001.14326.21146.0_x64__8wekyb3d8bbwe_microsoft.onenoteim_S-1-5-21", "Microsoft Software Printer Driver", PrinterKind.Prompt)]
    [InlineData("My office printer", "CPW2:", "CutePDF Writer", PrinterKind.Prompt)]                           // by driver, whatever it is called
    [InlineData("PDF24", "PDF24", "PDF24", PrinterKind.Prompt)]
    [InlineData("Adobe PDF", "Documents\\*.pdf", "Adobe PDF Converter", PrinterKind.File)]
    [InlineData("AutoPrint-Spike-PDF", @"F:\Projects\AutoPrint-V4\spikes\_out\spike_out.pdf", "Microsoft Print To PDF", PrinterKind.File)]   // the test printer: a fixed file, no window
    [InlineData("Null printer", "nul:", "Generic / Text Only", PrinterKind.File)]
    [InlineData("TASKalfa 3212i", "WSD-5549776f-2c43-4d2e-9f2a-0017c8a1b2c3", "Kyocera TASKalfa 3212i XPS", PrinterKind.Paper)]
    [InlineData("HP LaserJet Pro M404", "USB001", "HP Universal Printing PCL 6", PrinterKind.Paper)]
    [InlineData("Canon G3010 series", "192.168.1.40", "Canon G3010 series", PrinterKind.Paper)]
    [InlineData("Epson L3250", "IP_192.168.1.41", "EPSON L3250 Series", PrinterKind.Paper)]
    [InlineData("Front desk", "LPT1:", "Generic / Text Only", PrinterKind.Paper)]
    public void What_comes_out_is_decided_by_port_and_driver_not_only_by_name(string name, string port, string driver, PrinterKind expected)
    {
        Assert.Equal(expected, PrinterCatalog.Classify(name, port, driver));
        var health = PrinterHealth.From(name, port, driver, 0, 0);
        Assert.Equal(expected != PrinterKind.Paper, health.IsVirtual);
        Assert.Equal(expected == PrinterKind.Prompt, health.Prompts);
        Assert.Equal(expected == PrinterKind.Paper, health.Fine);
    }

    [Theory]
    [InlineData("Microsoft Print to PDF", true)]
    [InlineData("Microsoft XPS Document Writer", true)]
    [InlineData("OneNote (Desktop)", true)]
    [InlineData("Fax", true)]
    [InlineData("Send To OneNote 2016", true)]
    [InlineData(@"\\OFFICE-PC\Foxit PDF Printer", true)]
    [InlineData(@"\\OFFICE-PC\HP LaserJet 1020", false)]
    [InlineData("TASKalfa 3212i", false)]
    public void When_only_the_name_is_known_the_usual_document_writers_are_still_recognised(string name, bool noPaper)
    {
        Assert.Equal(noPaper, PrinterCatalog.LooksVirtual(name));
        Assert.Equal(noPaper ? PrinterKind.Prompt : PrinterKind.Paper, PrinterCatalog.Classify(name));
    }

    [Fact]
    public void A_printer_that_makes_no_paper_is_never_the_default_choice()
    {
        var pdf = new PrinterInfo("Microsoft Print to PDF", true, false, Prompts: true);
        var spike = new PrinterInfo("AutoPrint-Spike-PDF", true, false);
        var off = new PrinterInfo("Kyocera (offline)", false, true);
        var real = new PrinterInfo("HP LaserJet", false, false);

        Assert.Equal("HP LaserJet", PrinterCatalog.DefaultChoice([pdf, spike, off, real]));
        Assert.Equal("Kyocera (offline)", PrinterCatalog.DefaultChoice([pdf, off, spike]));     // "offline" is often wrong; a real printer still beats a file
        Assert.Null(PrinterCatalog.DefaultChoice([pdf, spike]));                                // only file printers: the shopkeeper must choose, with the warning in front of them
        Assert.Null(PrinterCatalog.DefaultChoice([]));
    }

    [Fact]
    public void The_warning_says_no_paper_and_names_the_waiting_window_only_when_there_is_one()
    {
        Assert.Null(PrinterCatalog.Warning("HP LaserJet", false, false));
        var prompt = PrinterCatalog.Warning("Microsoft Print to PDF", true, true)!;
        Assert.Contains("does not print on paper", prompt);
        Assert.Contains("waits for someone to answer", prompt);
        var file = PrinterCatalog.Warning("AutoPrint-Spike-PDF", true, false)!;
        Assert.Contains("does not print on paper", file);
        Assert.DoesNotContain("window", file);
    }

    [Fact]
    public void The_installed_printers_of_this_pc_are_listed_with_their_kind_and_no_paper_ones_come_last()
    {
        var list = PrinterCatalog.List();                    // reads the list only; nothing is sent to any printer
        Assert.Equal(list.OrderBy(p => p.IsVirtual).Select(p => p.Name), list.Select(p => p.Name));
        Assert.All(list.Where(p => p.Prompts), p => Assert.True(p.IsVirtual));
        if (list.FirstOrDefault(p => p.Name == "Microsoft Print to PDF") is { } pdf) Assert.True(pdf.IsVirtual && pdf.Prompts, "Print to PDF asks where to save");
        if (list.FirstOrDefault(p => p.Name == "AutoPrint-Spike-PDF") is { } spike) Assert.True(spike.IsVirtual && !spike.Prompts, "the test printer writes a fixed file and asks nothing");
        if (PrinterCatalog.DefaultChoice(list) is { } first) Assert.False(list.First(p => p.Name == first).IsVirtual);
    }
}

public class FailureWordsTests
{
    public static readonly string[] Reasons =
    [
        "engine_failed_nothing_in_spooler", "engine_failed_but_job_in_spooler", "job_never_seen_in_spooler", "cancelled_at_printer_before_any_page",
        "spooler_error_flag", "still_in_queue_when_wait_ended", "no_printing_progress_observed", "server_refused_completed_evidence",
        "printer_not_found", SumatraEngine.NotReadyReason, PrintOrchestrator.JournalUnavailable, PageRange.InvalidReason,
        "download_timeout", "download_unreachable", "download_sha256_mismatch", "download_size_mismatch", "download_larger_than_expected",
        "download_io_error", "download_http_404", "lease_lost_before_print", "offline_before_print",
        "agent_restarted_before_print", "agent_restarted_after_print_intent", "stale_attempt", "report_undelivered",
    ];

    [Fact]
    public void Every_reason_a_run_can_end_with_has_its_own_plain_words_and_something_to_check()
    {
        var fallback = FailureWords.For("something_new");
        foreach (var reason in Reasons)
        {
            var f = FailureWords.For(reason);
            Assert.True(f.What != fallback.What, reason + " has no words of its own");
            Assert.True(f.What.Length > 20 && f.Check.Length > 10, reason);
            Assert.DoesNotContain("_", f.Both);                                  // no code ever reaches the shopkeeper
            Assert.DoesNotContain("spooler", f.Both, StringComparison.OrdinalIgnoreCase);
        }
        Assert.Equal(Reasons.Length, Reasons.Select(r => FailureWords.For(r).What).Distinct().Count() + 3);   // the two "not the same file" and the two "could not download" reasons share words, as do download_size/larger
    }

    [Fact]
    public void The_words_match_every_reason_the_outcome_rule_can_give()
    {
        var seen = new SpoolEvidence(true, true, true, [], 1, 1, 1);
        var cases = new[]
        {
            OutcomeRules.Decide(new(false, "exit_code_1"), SpoolEvidence.None(1)),
            OutcomeRules.Decide(new(false, "exit_code_1"), seen),
            OutcomeRules.Decide(new(true, null), SpoolEvidence.None(1)),
            OutcomeRules.Decide(new(true, null), seen with { FlagsSeen = ["DELETING"], PrintingSeen = false, MaxPagesPrinted = 0 }),
            OutcomeRules.Decide(new(true, null), seen with { FlagsSeen = ["PAPEROUT"] }),
            OutcomeRules.Decide(new(true, null), seen with { LeftQueue = false }),
            OutcomeRules.Decide(new(true, null), seen with { PrintingSeen = false }),
        };
        Assert.Equal(7, cases.Select(c => c.Reason).Distinct().Count());
        Assert.All(cases, c => Assert.Contains(c.Reason, Reasons));
    }

    [Fact]
    public void Nothing_is_claimed_that_the_software_cannot_know()
    {
        foreach (var reason in Reasons)
        {
            var text = FailureWords.For(reason, "engine_timeout", true, true).Both;
            // the software watches the Windows print queue, not the tray: it never states that paper did or did not come out
            Assert.DoesNotContain("it printed", text, StringComparison.OrdinalIgnoreCase);
            Assert.DoesNotContain("has printed", text, StringComparison.OrdinalIgnoreCase);
        }
        Assert.Contains("may or may not have printed", FailureWords.For("agent_restarted_after_print_intent").Both);
        Assert.Contains("may still print", FailureWords.For("still_in_queue_when_wait_ended").Both);
        Assert.Contains("can come out twice", FailureWords.For("still_in_queue_when_wait_ended").Both);
    }

    [Fact]
    public void The_founders_failure_is_explained_a_file_printer_whose_window_nobody_answered()
    {
        var f = FailureWords.For("engine_failed_nothing_in_spooler", "engine_timeout", printerMakesFile: true, printerPrompts: true);
        Assert.Contains("never reached the printer's queue", f.What);
        Assert.Contains("does not print on paper", f.Check);
        Assert.Contains("may have opened a window that nobody answered", f.Check);       // "may": the app did not see the window
        Assert.Contains("Choose your real printer in Settings", f.Check);

        var real = FailureWords.For("engine_failed_nothing_in_spooler", "engine_timeout");
        Assert.Contains("window on this computer that is waiting for an answer", real.Check);
        Assert.Contains("switched on and connected", real.Check);
        Assert.Contains("test page", FailureWords.For("engine_failed_nothing_in_spooler", "exit_code_1").Check);
        Assert.Contains("not installed", FailureWords.For("engine_failed_nothing_in_spooler", "printer_not_found").What);
    }

    [Fact]
    public async Task A_run_carries_what_the_print_program_said_and_which_printer_it_was()
    {
        using var rig = new Rig(FakeScenario.EngineRejects);
        var res = await rig.Orchestrator.RunOnceAsync(default);
        Assert.Equal((RunKind.Failed, "engine_failed_nothing_in_spooler", "exit_code_1", "Test Printer"), (res.Kind, res.Reason, res.Detail, res.Printer));
    }

    [Fact]
    public async Task An_attempt_settled_from_the_journal_after_a_restart_is_announced_with_its_reason()
    {
        using var rig = new Rig();
        var claim = rig.Api.NextClaim!;
        rig.Journal.Begin(claim.AttemptId, claim.JobId, claim.SpoolerJobName, claim.AttemptToken, "Test Printer", 3);
        rig.Journal.Advance(claim.AttemptId, AttemptState.Intent);
        var told = new List<RunResult>();
        Assert.Equal(1, await rig.MakeOrchestrator().RecoverAsync(default, told.Add));     // a fresh orchestrator: as after a restart
        var r = Assert.Single(told);
        Assert.Equal((RunKind.Uncertain, claim.JobId, "agent_restarted_after_print_intent", "Test Printer"), (r.Kind, r.JobId!.Value, r.Reason, r.Printer));
        Assert.Equal(0, rig.Spooler.SubmitCount);                                           // recovery never prints
    }
}

public class AlertStartTests
{
    private static readonly DateTimeOffset Now = new(2026, 10, 6, 10, 0, 0, TimeSpan.Zero);

    [Fact]
    public void Requests_already_waiting_at_start_up_make_no_noise_but_are_reminded_and_new_ones_alert_once()
    {
        var policy = new AlertPolicy(TimeSpan.FromMinutes(2));
        var a = FakeShopApi.Job(JobStatus.AwaitingApproval, "AAAA"); var b = FakeShopApi.Job(JobStatus.AwaitingApproval, "BBBB");
        Assert.Equal(AlertKind.None, policy.Next([a, b], Now).Kind);                              // the app has just started: the shopkeeper is looking at it
        Assert.Equal(AlertKind.None, policy.Next([a, b], Now.AddSeconds(10)).Kind);
        var batch = policy.Next([a, b, FakeShopApi.Job(JobStatus.AwaitingApproval, "CCCC"), FakeShopApi.Job(JobStatus.AwaitingApproval, "DDDD"), FakeShopApi.Job(JobStatus.AwaitingApproval, "EEEE")], Now.AddSeconds(20));
        Assert.Equal((AlertKind.New, 3), (batch.Kind, batch.Count));                              // three together: one alert

        var quiet = new AlertPolicy(TimeSpan.FromMinutes(2));
        Assert.Equal(AlertKind.None, quiet.Next([a], Now).Kind);
        Assert.Equal(AlertKind.None, quiet.Next([a], Now.AddSeconds(119)).Kind);
        Assert.Equal(AlertKind.Reminder, quiet.Next([a], Now.AddSeconds(121)).Kind);              // still unanswered two minutes after start: now it reminds
    }
}

/// <summary>Security review: a page range that is not plain ASCII "1-3,5" must never reach the print program, which
/// ignores what it cannot read and prints every page.</summary>
public class PageRangeGuardTests
{
    [Theory]
    [InlineData(null, null)]
    [InlineData("", null)]
    [InlineData("   ", null)]
    [InlineData("1-3,5", "1-3,5")]
    [InlineData(" 1-4, 9 ", "1-4,9")]
    [InlineData("7", "7")]
    [InlineData("002-010", "2-10")]
    public void A_well_formed_range_is_passed_on_in_one_plain_shape(string? range, string? expected)
    {
        Assert.True(PageRange.TryNormalize(range, out var got));
        Assert.Equal(expected, got);
    }

    [Theory]
    [InlineData("١-٣")]                 // Arabic-Indic digits: char.IsDigit said yes
    [InlineData("１-３")]               // full-width digits
    [InlineData("1-2; calc.exe")]
    [InlineData("1-2 -print-to-default")]
    [InlineData("1–3")]                 // an en dash, not a hyphen
    [InlineData("1-3,")]
    [InlineData(",1")]
    [InlineData("1--3")]
    [InlineData("1-2-3")]
    [InlineData("3-1")]
    [InlineData("0")]
    [InlineData("0-2")]
    [InlineData("-3")]
    [InlineData("1-3\n")]
    [InlineData("1,\u00A02")]           // a no-break space
    [InlineData("all")]
    [InlineData("1x")]
    [InlineData("123456")]              // longer than any real document: not parsed, not passed on
    public void Anything_else_is_refused_not_cleaned_up(string range)
    {
        Assert.False(PageRange.TryNormalize(range, out var got));
        Assert.Null(got);
        Assert.Null(PageRange.SelectedCount(range, 100));
        Assert.Null(SumatraEngine.SettingsFor(new PrintOptions(1, false, false, range)));
    }

    [Fact]
    public async Task A_job_with_a_malformed_range_fails_unprinted_before_anything_is_fetched_or_sent()
    {
        using var rig = new Rig();
        rig.Api.NextClaim = Rig.NewClaim() with { Options = new PrintOptions(1, false, false, "١-٣") };
        var res = await rig.Orchestrator.RunOnceAsync(default);

        Assert.Equal((RunKind.Failed, PageRange.InvalidReason), (res.Kind, res.Reason));
        Assert.Equal(0, rig.Spooler.SubmitCount);                                          // the print program was never started
        Assert.Equal(["claim", "report:Failed"], rig.Api.Calls);                           // not even downloaded
        Assert.Equal(PageRange.InvalidReason, rig.Api.Reports.Single().Evidence["reason"]);
        Assert.Contains("could not be read as a page range", FailureWords.For(res.Reason).What);
    }

    [Fact]
    public async Task A_valid_range_still_prints_and_reaches_the_engine_unchanged()
    {
        using var rig = new Rig(pages: 12);
        rig.Api.NextClaim = Rig.NewClaim(pages: 12) with { Options = new PrintOptions(1, false, false, "1-4, 9") };
        var res = await rig.Orchestrator.RunOnceAsync(default);
        Assert.Equal(RunKind.Completed, res.Kind);
        Assert.Equal("1x,monochrome,simplex,fit,paper=a4,1-4,9", SumatraEngine.SettingsFor(rig.Spooler.Submitted.Single().Options));
        Assert.Equal(5, rig.Spooler.Submitted.Single().ExpectedPages);
    }

    [RealPrinterFact]
    public async Task The_real_engine_does_not_start_the_print_program_for_a_malformed_range()
    {
        var dir = Path.Combine(Path.GetTempPath(), "ap_real"); Directory.CreateDirectory(dir);
        var name = "apjob_" + Guid.NewGuid().ToString("N");
        var file = Path.Combine(dir, name + ".pdf");
        File.WriteAllBytes(file, TestPage.Build("AutoPrint test", "range guard"));
        try
        {
            var printer = Environment.GetEnvironmentVariable("AP_REAL_PRINTER")!;
            var clock = System.Diagnostics.Stopwatch.StartNew();
            var r = await new SumatraEngine(Environment.GetEnvironmentVariable("AP_SUMATRA")!).SubmitAsync(
                new PrintRequest(file, printer, new PrintOptions(1, false, false, "١-٣"), name, 1), default);
            Assert.Equal((false, PageRange.InvalidReason), (r.Accepted, r.Error));
            Assert.True(clock.Elapsed < TimeSpan.FromSeconds(10));
            await Task.Delay(500);
            Assert.Empty(new WinSpoolObserver().ListJobs(printer, name));                  // nothing reached the queue
        }
        finally { File.Delete(file); }
    }
}

/// <summary>Review finding: after paper-out or printer-off the request becomes "needs attention" while its job can
/// still be sitting in the Windows print queue. "Print again" must not make paper come out twice.</summary>
public class WaitingJobTests
{
    private sealed class BrokenQueue : ISpoolerObserver
    {
        public bool PrinterExists(string printer) => true;
        public IReadOnlyList<SpoolerJobInfo> ListJobs(string printer, string nameContains) => throw new InvalidOperationException("spooler_enum_failed");
        public void RemoveJob(string printer, int jobId) => throw new InvalidOperationException("printer_unavailable");
    }

    /// <summary>One request printed into a queue that never empties (printer off): it ends "uncertain".</summary>
    private static async Task<(Rig Rig, Claim Claim, WaitingJobs Guard)> StuckAsync()
    {
        var rig = new Rig(FakeScenario.StuckInQueue, wait: TimeSpan.FromMilliseconds(250));
        var claim = rig.Api.NextClaim!;
        var res = await rig.Orchestrator.RunOnceAsync(default);
        Assert.Equal((RunKind.Uncertain, "still_in_queue_when_wait_ended"), (res.Kind, res.Reason));
        return (rig, claim, new WaitingJobs(rig.Journal, rig.Spooler));
    }

    [Fact]
    public async Task A_job_still_in_the_queue_is_found_by_its_own_name_and_no_other_job_is_looked_at()
    {
        var (rig, claim, guard) = await StuckAsync();
        using var _ = rig;
        Assert.Equal(QueueLook.Waiting, guard.Look(claim.JobId));

        // another request's job sits in the same queue: it is not this request's, so it is neither found nor touched
        var other = Rig.NewClaim();
        var file = Path.Combine(rig.Dir, "other.pdf"); File.WriteAllText(file, "%PDF");
        await rig.Spooler.SubmitAsync(new PrintRequest(file, "Test Printer", other.Options, other.SpoolerJobName, 1), default);
        Assert.Equal(QueueLook.NoRecord, guard.Look(other.JobId));                         // this PC's journal has no attempt for it
        Assert.Equal(RemoveOutcome.NoRecord, await guard.RemoveAsync(other.JobId));
        Assert.Equal(RemoveOutcome.Removed, await guard.RemoveAsync(claim.JobId));
        Assert.Equal(1, rig.Spooler.RemoveCount);
        Assert.Single(rig.Spooler.ListJobs("Test Printer", other.SpoolerJobName));         // the other job is still there
    }

    [Fact]
    public async Task Removed_and_confirmed_gone_then_printed_again_exactly_once()
    {
        var (rig, claim, guard) = await StuckAsync();
        using var _ = rig;
        Assert.Equal(RemoveOutcome.Removed, await guard.RemoveAsync(claim.JobId));
        Assert.Equal(QueueLook.NotThere, guard.Look(claim.JobId));

        // only now does the shopkeeper's "print again" reach the server; the server hands the same request out once more
        rig.Spooler.Scenario = FakeScenario.Success;
        var second = Rig.NewClaim() with { JobId = claim.JobId };
        rig.Api.NextClaim = second;
        var res = await rig.Orchestrator.RunOnceAsync(default);
        Assert.Equal(RunKind.Completed, res.Kind);
        Assert.Equal(2, rig.Spooler.SubmitCount);                                           // the first attempt and exactly one new one
        Assert.Equal(AttemptState.Reported, rig.Journal.StateOf(second.AttemptId));         // journalled like any attempt
        Assert.Equal(2, rig.Journal.AttemptsFor(claim.JobId).Count);
        Assert.Equal(QueueLook.NotThere, guard.Look(claim.JobId));
        Assert.Equal(RunKind.NoJob, (await rig.Orchestrator.RunOnceAsync(default)).Kind);   // and nothing prints by itself afterwards
        Assert.Equal(2, rig.Spooler.SubmitCount);
    }

    [Fact]
    public async Task A_job_that_left_the_queue_by_itself_is_reported_as_such_and_nothing_is_removed()
    {
        var (rig, claim, guard) = await StuckAsync();
        using var _ = rig;
        Assert.Equal(QueueLook.Waiting, guard.Look(claim.JobId));
        rig.Spooler.DrainQueue();                                                           // the printer came back and worked off its queue
        Assert.Equal(QueueLook.NotThere, guard.Look(claim.JobId));
        Assert.Equal(RemoveOutcome.GoneByItself, await guard.RemoveAsync(claim.JobId));     // the caller must not print again on this answer
        Assert.Equal(0, rig.Spooler.RemoveCount);
        Assert.Equal(1, rig.Spooler.SubmitCount);
    }

    [Fact]
    public async Task When_removal_fails_the_job_is_reported_still_there_never_gone()
    {
        var (rig, claim, guard) = await StuckAsync();
        using var _ = rig;
        rig.Spooler.RemoveFails = true;
        var result = await guard.RemoveAsync(claim.JobId, default, TimeSpan.FromMilliseconds(300), TimeSpan.FromMilliseconds(20));
        Assert.Equal(RemoveOutcome.StillThere, result);
        Assert.Equal(1, rig.Spooler.RemoveCount);
        Assert.Equal(QueueLook.Waiting, guard.Look(claim.JobId));
        Assert.Equal(1, rig.Spooler.SubmitCount);

        rig.Spooler.RemoveFails = false;                                                    // a second try, once Windows lets go
        Assert.Equal(RemoveOutcome.Removed, await guard.RemoveAsync(claim.JobId));
    }

    [Fact]
    public async Task A_queue_that_cannot_be_read_is_unknown_not_empty()
    {
        var (rig, claim, _) = await StuckAsync();
        using var __ = rig;
        var blind = new WaitingJobs(rig.Journal, new BrokenQueue());
        Assert.Equal(QueueLook.Unreadable, blind.Look(claim.JobId));
        Assert.Equal(RemoveOutcome.Unreadable, await blind.RemoveAsync(claim.JobId));
        Assert.Equal(QueueLook.NoRecord, blind.Look(Guid.NewGuid()));
    }

    [Fact]
    public async Task Every_attempt_of_the_request_is_looked_for_also_one_kept_on_purpose()
    {
        var (rig, claim, guard) = await StuckAsync();
        using var _ = rig;
        // the shopkeeper chose to keep the waiting job and print again; that one got stuck too
        rig.Api.NextClaim = Rig.NewClaim() with { JobId = claim.JobId };
        await rig.Orchestrator.RunOnceAsync(default);
        Assert.Equal(2, rig.Spooler.SubmitCount);
        Assert.Equal(QueueLook.Waiting, guard.Look(claim.JobId));
        Assert.Equal(RemoveOutcome.Removed, await guard.RemoveAsync(claim.JobId));
        Assert.Equal(2, rig.Spooler.RemoveCount);                                           // both of its own jobs, nothing else
    }
}

/// <summary>Review of 7 October: the reminder for requests that are still waiting must end by itself. Before this, a
/// shop PC that lost its connection kept an old list on screen and chimed about it every two minutes for as long as
/// it was left on.</summary>
public class AlertEndTests
{
    private static readonly DateTimeOffset Now = new(2026, 10, 7, 10, 0, 0, TimeSpan.Zero);
    private static JobSummary Waiting(string code, double expiresInMinutes = 60) =>
        FakeShopApi.Job(JobStatus.AwaitingApproval, code, created: Now) with { ApprovalExpiresAt = Now.AddMinutes(expiresInMinutes) };

    [Fact]
    public void The_reminder_is_steady_while_a_request_can_be_answered_and_stops_when_its_hour_is_over()
    {
        var policy = new AlertPolicy(TimeSpan.FromMinutes(2));
        var a = Waiting("AAAA");
        var reminders = new List<DateTimeOffset>();
        // three hours of looks, one every 10 s like the poll, with the request never answered and never closed by the server
        for (var t = Now; t <= Now.AddHours(3); t = t.AddSeconds(10))
        {
            var alert = policy.Next([a], t, serverNow: t);
            Assert.NotEqual(AlertKind.New, alert.Kind);                                      // it was there at start-up: never "new"
            if (alert.Kind == AlertKind.Reminder) reminders.Add(t);
        }
        Assert.Equal(Now.AddMinutes(2), reminders[0]);                                       // the first one two minutes after start-up
        // three reminders two minutes apart, then one every ten minutes until its hour is over, then no more
        Assert.Equal(new[] { 2, 4, 6, 16, 26, 36, 46, 56 }, reminders.Select(t => (int)(t - Now).TotalMinutes));
        Assert.All(reminders, t => Assert.True(t < Now.AddHours(1)));
    }

    [Fact]
    public void Without_internet_nothing_is_said_however_long_it_lasts_and_the_reminder_comes_back_with_the_connection()
    {
        var policy = new AlertPolicy(TimeSpan.FromMinutes(2));
        var a = Waiting("AAAA", expiresInMinutes: 24 * 60);
        Assert.Equal(AlertKind.None, policy.Next([a], Now, Now).Kind);
        for (var t = Now.AddSeconds(15); t < Now.AddHours(8); t = t.AddSeconds(15))          // a night with the router off: the list on screen is the old one
            Assert.Equal(AlertKind.None, policy.Next([a], t, t, online: false).Kind);
        var back = Now.AddHours(8);
        Assert.Equal(AlertKind.Reminder, policy.Next([a], back, back).Kind);                 // connected again and it is still waiting: say so once
        Assert.Equal(AlertKind.None, policy.Next([a], back.AddSeconds(10), back.AddSeconds(10)).Kind);
    }

    [Fact]
    public void Whether_a_request_can_still_be_answered_is_judged_by_the_servers_clock_not_this_pcs()
    {
        var a = Waiting("AAAA");
        // this PC's clock is three hours fast; the server says ten minutes have passed: it is still waiting, so it reminds
        var fast = new AlertPolicy(TimeSpan.FromMinutes(2));
        Assert.Equal(AlertKind.None, fast.Next([a], Now.AddHours(3), Now).Kind);
        Assert.Equal(AlertKind.Reminder, fast.Next([a], Now.AddHours(3).AddMinutes(10), Now.AddMinutes(10)).Kind);
        // this PC's clock is right but the server's hour is over: nothing to answer, nothing said
        var over = new AlertPolicy(TimeSpan.FromMinutes(2));
        Assert.Equal(AlertKind.None, over.Next([a], Now, Now).Kind);
        Assert.Equal(AlertKind.None, over.Next([a], Now.AddMinutes(10), Now.AddMinutes(61)).Kind);
        // a new request beside the expired one is still announced, and counted alone
        var b = FakeShopApi.Job(JobStatus.AwaitingApproval, "BBBB", "new.pdf") with { ApprovalExpiresAt = Now.AddHours(2) };
        var alert = over.Next([a, b], Now.AddMinutes(11), Now.AddMinutes(62));
        Assert.Equal((AlertKind.New, 1, "new.pdf"), (alert.Kind, alert.Count, alert.FirstDocument));
    }
}

/// <summary>The shop app asks the server every 10 s, and every request costs money, so the interval stays. What is
/// free is asking at once at the moments that matter. These tests use a 30 s interval: any poll after the first one
/// can only have come from a wake-up.</summary>
public class WakeTests
{
    private static AgentService Slow(Rig rig) => new(rig.Api, rig.Orchestrator, TimeSpan.FromSeconds(30));

    [Fact]
    public async Task Opening_the_window_refreshes_the_list_only_when_it_is_old_and_many_presses_make_one_request()
    {
        using var rig = new Rig();
        rig.Api.NextClaim = null;
        var agent = Slow(rig);
        using var cts = new CancellationTokenSource();
        var run = agent.RunAsync(cts.Token);
        await Wait.Until(() => rig.Api.PollCount == 1);

        Assert.False(agent.WakeIfStale(TimeSpan.FromMinutes(1)));                             // asked a moment ago: nothing to gain
        await Task.Delay(300);
        Assert.Equal(1, rig.Api.PollCount);

        for (int i = 0; i < 20; i++) agent.WakeIfStale(TimeSpan.FromMilliseconds(200));       // the window is opened and brought forward again and again
        await Wait.Until(() => rig.Api.PollCount == 2);
        await Task.Delay(300);
        Assert.Equal(2, rig.Api.PollCount);                                                   // one request, not twenty
        Assert.False(agent.WakeIfStale(TimeSpan.FromSeconds(30)));                            // and that one counts as fresh

        agent.Wake();                                                                         // an answer was sent, or the network came back: always at once
        await Wait.Until(() => rig.Api.PollCount == 3);
        await Task.Delay(300);
        Assert.Equal(3, rig.Api.PollCount);                                                   // and no faster steady rate afterwards
        cts.Cancel(); await run;
    }

    [Fact]
    public async Task When_a_print_ends_the_queue_is_asked_again_at_once_and_not_in_a_tight_loop()
    {
        using var rig = new Rig();
        var job = FakeShopApi.Job(JobStatus.Approved);
        rig.Api.OnPoll = _ => rig.Api.NextClaim is null ? FakeShopApi.Queue() : FakeShopApi.Queue(job);
        var agent = Slow(rig);
        using var cts = new CancellationTokenSource();
        var run = agent.RunAsync(cts.Token);
        await Wait.Until(() => rig.Api.Reports.Count == 1);
        await Wait.Until(() => rig.Api.PollCount >= 2, 3000);                                 // not 30 s later
        await Task.Delay(500);
        Assert.InRange(rig.Api.PollCount, 2, 4);
        Assert.Equal(1, rig.Spooler.SubmitCount);
        cts.Cancel(); await run;
    }
}

/// <summary>"Print a test page" and "Test the colour printer" in Settings: the colour button had never been pressed.</summary>
public class TestPrintTests
{
    private sealed class ScriptedEngine : IPrintEngine
    {
        public readonly List<PrintRequest> Requests = [];
        public readonly List<bool> FileWasThere = [];
        public TaskCompletionSource? Hold;
        public SubmitResult Answer = new(true, null);
        public Exception? Throw;

        public async Task<SubmitResult> SubmitAsync(PrintRequest request, CancellationToken ct)
        {
            lock (Requests) { Requests.Add(request); FileWasThere.Add(File.Exists(request.FilePath)); }
            if (Hold is { } hold) await hold.Task;
            if (Throw is { } x) throw x;
            return Answer;
        }
    }

    private static string NewDir() => Path.Combine(Path.GetTempPath(), "ap_test_" + Guid.NewGuid().ToString("N")[..8], "testpage");
    private static void Remove(string dir) { try { Directory.Delete(Path.GetDirectoryName(dir)!, true); } catch (IOException) { } }

    [Fact]
    public void The_colour_button_exists_only_for_a_second_machine_and_names_that_machine()
    {
        Assert.Equal("Canon colour", TestPrint.ColourTarget("Canon colour", "HP mono", "Same printer"));
        Assert.Null(TestPrint.ColourTarget("Same printer", "HP mono", "Same printer"));       // no separate colour printer
        Assert.Null(TestPrint.ColourTarget("HP mono", "HP mono", "Same printer"));            // the same machine chosen twice: the first button tests it
        Assert.Null(TestPrint.ColourTarget(null, "HP mono", "Same printer"));
        Assert.Null(TestPrint.ColourTarget("", "HP mono", "Same printer"));
        Assert.Equal("Canon colour", TestPrint.ColourTarget("Canon colour", null, "Same printer"));
    }

    [Fact]
    public async Task One_page_in_colour_goes_to_the_printer_that_was_named_and_its_file_is_gone_afterwards()
    {
        var dir = NewDir();
        try
        {
            var engine = new ScriptedEngine();
            var test = new TestPrint(() => engine, dir);
            var r = await test.SendAsync("Canon colour", colour: true);
            Assert.True(r is { Accepted: true });
            var sent = Assert.Single(engine.Requests);
            Assert.Equal("Canon colour", sent.Printer);
            Assert.Equal(new PrintOptions(1, true, false, null), sent.Options);              // one copy, colour, one side, every page of a one-page file
            Assert.Equal(1, sent.ExpectedPages);
            Assert.StartsWith("aptest_", sent.SpoolerJobName);                               // never the name of a customer's job
            Assert.Equal(dir, Path.GetDirectoryName(sent.FilePath));                         // never in the folder customer documents use
            Assert.True(engine.FileWasThere.Single());
            Assert.False(File.Exists(sent.FilePath));
            Assert.False(test.Running);

            await test.SendAsync("HP mono", colour: false);
            Assert.Equal(("HP mono", false), (engine.Requests[1].Printer, engine.Requests[1].Options.Color));
        }
        finally { Remove(dir); }
    }

    [Fact]
    public async Task A_second_press_while_a_page_is_on_its_way_sends_nothing()
    {
        var dir = NewDir();
        try
        {
            var engine = new ScriptedEngine { Hold = new TaskCompletionSource() };
            var test = new TestPrint(() => engine, dir);
            var first = test.SendAsync("Canon colour", colour: true);
            await Wait.Until(() => { lock (engine.Requests) return engine.Requests.Count == 1; });
            Assert.True(test.Running);
            Assert.Null(await test.SendAsync("Canon colour", colour: true));                 // the double click
            Assert.Null(await test.SendAsync("HP mono", colour: false));                     // or the other button
            Assert.Null(await Task.Run(() => test.SendAsync("Canon colour", colour: true))); // from any thread
            Assert.Single(engine.Requests);
            Assert.True(File.Exists(engine.Requests[0].FilePath));                           // the refused presses did not take the first one's file away
            engine.Hold.SetResult();
            Assert.True((await first) is { Accepted: true });
            Assert.Single(engine.Requests);
            Assert.NotNull(await test.SendAsync("Canon colour", colour: true));              // afterwards the button works again
            Assert.Equal(2, engine.Requests.Count);
        }
        finally { Remove(dir); }
    }

    [Fact]
    public async Task The_page_file_is_removed_and_the_button_freed_also_when_the_print_program_fails_or_breaks()
    {
        var dir = NewDir();
        try
        {
            var engine = new ScriptedEngine { Answer = new(false, "exit_code_1") };
            var test = new TestPrint(() => engine, dir);
            Assert.Equal((false, "exit_code_1"), ((await test.SendAsync("P", true))!.Accepted, (await test.SendAsync("P", true))!.Error));
            engine.Throw = new InvalidOperationException("the print program could not be started");
            await Assert.ThrowsAsync<InvalidOperationException>(() => test.SendAsync("P", true));
            Assert.False(test.Running);
            Assert.Equal(3, engine.Requests.Count);
            Assert.Empty(Directory.GetFiles(dir));
        }
        finally { Remove(dir); }
    }

    [Fact]
    public void Every_result_is_said_in_plain_words_and_never_claims_that_paper_came_out()
    {
        var ok = TestPrint.Words(new(true, null), "Canon colour", colour: true, prompts: false);
        Assert.Contains("the colour printer “Canon colour”", ok);
        Assert.Contains("Check that a page came out", ok);
        Assert.DoesNotContain("printed", ok, StringComparison.OrdinalIgnoreCase);            // the software saw it accepted, not paper
        Assert.Contains("the printer “HP mono”", TestPrint.Words(new(true, null), "HP mono", colour: false, prompts: false));
        Assert.Contains("red, green and blue", ok);                                          // the colour page has something coloured to look at
        Assert.DoesNotContain("squares", TestPrint.Words(new(true, null), "HP mono", colour: false, prompts: false));
        var plain = System.Text.Encoding.ASCII.GetString(TestPage.Build("a", "b"));
        var coloured = System.Text.Encoding.ASCII.GetString(TestPage.Build("a", "b", colour: true));
        Assert.DoesNotContain(" rg ", plain);
        Assert.Contains("1 0 0 rg 72 520 90 90 re f", coloured);

        string?[] errors = [SumatraEngine.NotReadyReason, "printer_not_found", "engine_timeout", "exit_code_1", "file_missing", PageRange.InvalidReason, null, "something_new"];
        foreach (var error in errors)
            foreach (var prompts in new[] { false, true })
            {
                var text = TestPrint.Words(new(false, error), "Canon colour", true, prompts);
                Assert.False(string.IsNullOrWhiteSpace(text));
                Assert.DoesNotContain("_", text);                                            // no reason code reaches the shopkeeper
                Assert.DoesNotContain("exit", text, StringComparison.OrdinalIgnoreCase);
                Assert.DoesNotContain("Sent to", text);
                Assert.EndsWith(".", text);
            }
        Assert.Contains("switched on", TestPrint.Words(new(false, "engine_timeout"), "P", true, prompts: false));
        Assert.Contains("makes a file", TestPrint.Words(new(false, "engine_timeout"), "P", true, prompts: true));
        Assert.Contains("Install AutoPrint again", TestPrint.Words(new(false, SumatraEngine.NotReadyReason), "P", true, false));
    }

    [RealPrinterFact]
    public async Task With_the_real_print_program_the_colour_test_page_is_accepted_by_the_named_printer_and_refused_plainly_for_one_that_is_gone()
    {
        var dir = NewDir();
        try
        {
            var printer = Environment.GetEnvironmentVariable("AP_REAL_PRINTER")!;
            var test = new TestPrint(() => new SumatraEngine(Environment.GetEnvironmentVariable("AP_SUMATRA")!), dir);
            var r = await test.SendAsync(printer, colour: true);
            Assert.True(r is { Accepted: true }, r?.Error);
            Assert.Empty(Directory.GetFiles(dir));

            var gone = await test.SendAsync("No Such Printer " + Guid.NewGuid(), colour: true);
            Assert.Equal((false, "printer_not_found"), (gone!.Accepted, gone.Error));
            Assert.Equal("Windows cannot find this printer any more. Choose another one.", TestPrint.Words(gone, "x", true, false));
            Assert.Empty(Directory.GetFiles(dir));
        }
        finally { Remove(dir); }
    }
}
