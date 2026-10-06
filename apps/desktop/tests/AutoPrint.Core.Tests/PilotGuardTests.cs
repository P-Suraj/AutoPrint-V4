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
