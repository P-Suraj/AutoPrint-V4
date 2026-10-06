using System.Net;
using System.Text;
using AutoPrint.Core;
using AutoPrint.Core.Agent;
using AutoPrint.Core.Printing;
using AutoPrint.Core.Shop;
using Xunit;

namespace AutoPrint.Core.Tests;

/// <summary>A web server in a lambda, for the code that talks HTTP directly.</summary>
internal sealed class Handler(Func<HttpRequestMessage, CancellationToken, Task<HttpResponseMessage>> reply) : HttpMessageHandler
{
    public int Requests;
    protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken ct)
    { Interlocked.Increment(ref Requests); return reply(request, ct); }

    public static HttpResponseMessage Json(string json, HttpStatusCode status = HttpStatusCode.OK) =>
        new(status) { Content = new StringContent(json, Encoding.UTF8, "application/json") };
    public static HttpResponseMessage Html() =>
        new(HttpStatusCode.OK) { Content = new StringContent("<html><body>Sign in to this Wi-Fi</body></html>", Encoding.UTF8, "text/html") };
}

internal static class Wait
{
    public static async Task Until(Func<bool> condition, int timeoutMs = 5000)
    {
        var until = DateTime.UtcNow.AddMilliseconds(timeoutMs);
        while (!condition()) { Assert.True(DateTime.UtcNow < until, "timed out waiting"); await Task.Delay(10); }
    }
}

/// <summary>Pilot-day failures of the loop that keeps the shop PC connected (V3: the agent died or stalled).</summary>
public class AgentLoopTests
{
    private static AgentService Agent(Rig rig, List<string>? log = null, PrintOrchestrator? orchestrator = null) =>
        new(rig.Api, orchestrator ?? rig.Orchestrator, TimeSpan.FromMilliseconds(20), (d, ct) => Task.Delay(TimeSpan.FromMilliseconds(Math.Min(20, d.TotalMilliseconds)), ct),
            m => { if (log is not null) lock (log) log.Add(m); });

    [Fact]
    public async Task A_timeout_or_a_bug_in_one_round_never_stops_the_loop()
    {
        using var rig = new Rig();
        rig.Api.NextClaim = null;
        rig.Api.OnPoll = n => n switch
        {
            1 => throw new TaskCanceledException("a timeout looks like a cancellation nobody asked for"),   // this one used to end the loop for good
            2 => throw new InvalidOperationException("a bug"),
            3 => throw new ServerUnreachableException("offline"),
            _ => FakeShopApi.Queue(),
        };
        var log = new List<string>();
        var agent = Agent(rig, log);
        using var cts = new CancellationTokenSource();
        var run = agent.RunAsync(cts.Token);
        await Wait.Until(() => agent.State.Online && rig.Api.PollCount >= 6);
        Assert.False(run.IsCompleted);                                    // still running
        Assert.Null(agent.State.Problem);
        lock (log) Assert.Contains(log, l => l.Contains("InvalidOperationException") && l.Contains("a bug"));   // enough to diagnose
        cts.Cancel();
        await run;                                                        // and it stops when asked to
    }

    [Fact]
    public async Task A_listener_that_throws_does_not_stop_the_loop()
    {
        using var rig = new Rig();
        rig.Api.NextClaim = null;
        var agent = Agent(rig);
        agent.StateChanged += _ => throw new InvalidOperationException("window code failed");
        using var cts = new CancellationTokenSource();
        var run = agent.RunAsync(cts.Token);
        await Wait.Until(() => rig.Api.PollCount >= 4);
        Assert.False(run.IsCompleted);
        cts.Cancel(); await run;
    }

    [Fact]
    public async Task The_heartbeat_and_the_queue_keep_refreshing_during_a_long_print_and_recovery_waits_for_it()
    {
        using var rig = new Rig(FakeScenario.StuckInQueue, wait: TimeSpan.FromMilliseconds(700));     // "a long print"
        var job = FakeShopApi.Job(JobStatus.Approved);
        rig.Api.OnPoll = _ => rig.Api.NextClaim is null ? FakeShopApi.Queue() : FakeShopApi.Queue(job);
        int pollsAtClaim = -1, pollsAtReport = -1;
        rig.Api.OnClaim = () => { if (pollsAtClaim < 0) pollsAtClaim = rig.Api.PollCount; };
        var agent = Agent(rig);
        agent.StateChanged += s => { if (s.Current?.Stage == Stage.Reporting && pollsAtReport < 0) pollsAtReport = rig.Api.PollCount; };
        using var cts = new CancellationTokenSource();
        var run = agent.RunAsync(cts.Token);
        await Wait.Until(() => rig.Api.Reports.Count == 1 && agent.State.Current is null);
        cts.Cancel(); await run;

        Assert.True(pollsAtReport - pollsAtClaim >= 5, $"only {pollsAtReport - pollsAtClaim} polls while the job was at the printer");
        Assert.Equal(1, rig.Spooler.SubmitCount);
        // the attempt in progress was never "recovered" under the running print: exactly one report, the real one
        Assert.Single(rig.Api.Calls, c => c.StartsWith("report"));
        Assert.Equal("still_in_queue_when_wait_ended", rig.Api.Reports.Single().Evidence["reason"]);
    }

    [Fact]
    public async Task A_broken_print_record_blocks_printing_and_says_so_but_the_heartbeat_goes_on()
    {
        using var rig = new Rig();
        rig.BreakJournal();
        rig.Api.OnPoll = _ => FakeShopApi.Queue(FakeShopApi.Job(JobStatus.Approved));
        var agent = Agent(rig);
        using var cts = new CancellationTokenSource();
        var run = agent.RunAsync(cts.Token);
        await Wait.Until(() => rig.Api.PollCount >= 5);
        Assert.Equal(AgentService.JournalFaultText, agent.State.CannotPrint);
        Assert.True(agent.State.Online);
        Assert.DoesNotContain("claim", rig.Api.Calls);                    // nothing is taken from the queue while it cannot be recorded
        Assert.Equal(0, rig.Spooler.SubmitCount);
        cts.Cancel(); await run;
    }
}

public class OrchestratorRobustnessTests
{
    [Fact]
    public async Task Without_a_working_print_record_the_job_fails_cleanly_and_nothing_is_printed()
    {
        using var rig = new Rig();
        rig.BreakJournal();
        var res = await rig.Orchestrator.RunOnceAsync(default);
        Assert.Equal((RunKind.Failed, PrintOrchestrator.JournalUnavailable), (res.Kind, res.Reason));
        Assert.Equal(["claim", "report:Failed"], rig.Api.Calls);
        Assert.Equal(0, rig.Spooler.SubmitCount);                          // journal before print, so: no journal, no print
    }

    private sealed class MissingEngine : IPrintEngine
    {
        public int Submits;
        public string? NotReady() => SumatraEngine.NotReadyReason;
        public Task<SubmitResult> SubmitAsync(PrintRequest r, CancellationToken ct) { Submits++; return Task.FromResult(new SubmitResult(true, null)); }
    }

    [Fact]
    public async Task A_missing_or_damaged_print_program_fails_the_job_at_once_before_any_download()
    {
        using var rig = new Rig();
        var engine = new MissingEngine();
        rig.Downloader.FailWith = "must_not_be_downloaded";
        var clock = System.Diagnostics.Stopwatch.StartNew();
        var res = await rig.MakeOrchestrator(wait: TimeSpan.FromSeconds(30), engine: engine).RunOnceAsync(default);
        Assert.Equal((RunKind.Failed, SumatraEngine.NotReadyReason), (res.Kind, res.Reason));
        Assert.Equal(0, engine.Submits);
        Assert.True(clock.Elapsed < TimeSpan.FromSeconds(5), "it must not sit out the spooler wait for a print that cannot have started");
    }

    [Fact]
    public void The_real_engine_reports_a_missing_program_as_not_ready()
    {
        var missing = Path.Combine(Path.GetTempPath(), "ap_no_such_" + Guid.NewGuid().ToString("N"), "SumatraPDF.exe");
        Assert.Equal(SumatraEngine.NotReadyReason, ((IPrintEngine)new SumatraEngine(missing)).NotReady());
        var wrong = Path.GetTempFileName();                                // present, but not the genuine program
        try { File.WriteAllText(wrong, "MZ not sumatra"); Assert.Equal(SumatraEngine.NotReadyReason, new SumatraEngine(wrong).NotReady()); }
        finally { File.Delete(wrong); }
    }

    [Fact]
    public async Task If_the_lease_was_lost_during_a_slow_download_the_document_is_not_printed()
    {
        using var rig = new Rig();
        rig.Api.RenewStale = true;
        var res = await rig.MakeOrchestrator(renewBeforePrintAfter: TimeSpan.Zero).RunOnceAsync(default);
        Assert.Equal((RunKind.Failed, "lease_lost_before_print"), (res.Kind, res.Reason));
        Assert.Equal(0, rig.Spooler.SubmitCount);
        Assert.Empty(Directory.GetFiles(rig.WorkDir));
    }

    [Fact]
    public async Task A_refusal_of_the_sent_notice_does_not_abandon_the_watch()
    {
        using var rig = new Rig();
        rig.Api.MarkSentRefused = true;
        var res = await rig.Orchestrator.RunOnceAsync(default);
        Assert.Equal(RunKind.Completed, res.Kind);                         // the job was still followed to its end and reported with evidence
        Assert.Equal(true, rig.Api.Reports.Single().Evidence["left_queue"]);
    }

    [Fact]
    public async Task Documents_left_behind_by_a_crash_are_removed_when_the_next_job_starts()
    {
        using var rig = new Rig();
        Directory.CreateDirectory(rig.WorkDir);
        var stale = Path.Combine(rig.WorkDir, "apjob_from_a_crashed_run.pdf");
        File.WriteAllText(stale, "%PDF a customer document");
        File.WriteAllText(stale + ".part", "half a download");
        await rig.Orchestrator.RunOnceAsync(default);
        Assert.Empty(Directory.GetFileSystemEntries(rig.WorkDir));
    }

    [Theory]
    [InlineData(FakeScenario.EngineRejects)]
    [InlineData(FakeScenario.EngineThrows)]
    [InlineData(FakeScenario.StuckInQueue)]
    [InlineData(FakeScenario.PaperOut)]
    public async Task No_document_remains_after_any_outcome(FakeScenario scenario)
    {
        using var rig = new Rig(scenario, wait: TimeSpan.FromMilliseconds(200));
        await rig.Orchestrator.RunOnceAsync(default);
        Assert.Empty(Directory.GetFileSystemEntries(rig.WorkDir));
    }

    [Fact]
    public async Task A_locked_work_file_is_reported_and_then_removed_by_the_sweep()
    {
        var dir = Path.Combine(Path.GetTempPath(), "apw_" + Guid.NewGuid().ToString("N")[..8]);
        Directory.CreateDirectory(Path.Combine(dir, "sub"));
        var file = Path.Combine(dir, "apjob_x.pdf");
        File.WriteAllText(file, "x"); File.WriteAllText(Path.Combine(dir, "sub", "preview.pdf"), "y");
        using (new FileStream(file, FileMode.Open, FileAccess.Read, FileShare.None))
        {
            Assert.False(await WorkFiles.DeleteAsync(file, tries: 2, waitMs: 10));     // "the print program still holds it"
            Assert.Equal(1, WorkFiles.CleanStale(dir));
        }
        Assert.Equal(0, WorkFiles.CleanStale(dir));
        Assert.Empty(Directory.GetFileSystemEntries(dir));
        Assert.Equal(0, WorkFiles.CleanStale(Path.Combine(dir, "does-not-exist")));
        Directory.Delete(dir);
    }
}

public class NetworkEdgeTests
{
    private sealed class StallingStream : Stream
    {
        private bool _sent;
        public override bool CanRead => true; public override bool CanSeek => false; public override bool CanWrite => false;
        public override long Length => throw new NotSupportedException();
        public override long Position { get => throw new NotSupportedException(); set => throw new NotSupportedException(); }
        public override void Flush() { }
        public override int Read(byte[] buffer, int offset, int count) => throw new NotSupportedException();
        public override long Seek(long offset, SeekOrigin origin) => throw new NotSupportedException();
        public override void SetLength(long value) => throw new NotSupportedException();
        public override void Write(byte[] buffer, int offset, int count) => throw new NotSupportedException();
        public override async ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken ct = default)
        {
            if (!_sent) { _sent = true; buffer.Span[0] = (byte)'%'; return 1; }
            await Task.Delay(Timeout.Infinite, ct);                                   // the connection goes quiet for ever
            return 0;
        }
        public override Task<int> ReadAsync(byte[] buffer, int offset, int count, CancellationToken ct) => ReadAsync(buffer.AsMemory(offset, count), ct).AsTask();
    }

    [Fact]
    public async Task A_download_that_stalls_is_a_clean_failure_not_a_hang_and_leaves_no_file()
    {
        var dir = Path.Combine(Path.GetTempPath(), "apd_" + Guid.NewGuid().ToString("N")[..8]);
        using var http = new HttpClient(new Handler((_, _) => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { Content = new StreamContent(new StallingStream()) })));
        var path = Path.Combine(dir, "job.pdf");
        var e = await Assert.ThrowsAsync<DownloadFailedException>(() =>
            new HttpDownloader(http, TimeSpan.FromMilliseconds(250)).DownloadAsync("https://example.test/f", new string('0', 64), 1000, path, default));
        Assert.Equal("download_timeout", e.Reason);
        Assert.Empty(Directory.GetFileSystemEntries(dir));
        Directory.Delete(dir);
    }

    [Fact]
    public async Task A_download_that_is_not_the_approved_file_leaves_nothing_on_disk()
    {
        var dir = Path.Combine(Path.GetTempPath(), "apd_" + Guid.NewGuid().ToString("N")[..8]);
        using var http = new HttpClient(new Handler((_, _) => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { Content = new ByteArrayContent("%PDF other"u8.ToArray()) })));
        var e = await Assert.ThrowsAsync<DownloadFailedException>(() =>
            new HttpDownloader(http).DownloadAsync("https://example.test/f", new string('0', 64), 10, Path.Combine(dir, "job.pdf"), default));
        Assert.Equal("download_sha256_mismatch", e.Reason);
        Assert.Empty(Directory.GetFileSystemEntries(dir));
        Directory.Delete(dir);
    }

    [Fact]
    public async Task Closing_the_app_during_a_download_is_a_cancellation_not_a_failed_job()
    {
        var dir = Path.Combine(Path.GetTempPath(), "apd_" + Guid.NewGuid().ToString("N")[..8]);
        using var http = new HttpClient(new Handler((_, _) => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { Content = new StreamContent(new StallingStream()) })));
        using var cts = new CancellationTokenSource(100);
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() =>
            new HttpDownloader(http).DownloadAsync("https://example.test/f", new string('0', 64), 1000, Path.Combine(dir, "job.pdf"), cts.Token));
        Assert.Empty(Directory.GetFileSystemEntries(dir));
        Directory.Delete(dir);
    }

    private const string PollJson = """{"shop_code":"TST001","shop_name":"Shop","contract_version":1,"jobs":[]}""";
    private static readonly DeviceCredentials Cred = new(Guid.NewGuid(), "s", "TST001", "Shop", "https://example.test");

    [Fact]
    public async Task The_poll_carries_the_servers_clock_so_a_wrong_pc_clock_does_not_skew_waiting_times()
    {
        var serverNow = new DateTimeOffset(2026, 10, 6, 9, 30, 0, TimeSpan.Zero);
        using var http = new HttpClient(new Handler((_, _) => { var r = Handler.Json(PollJson); r.Headers.Date = serverNow; return Task.FromResult(r); }));
        var snap = await new ShopApi(http, Cred, "test").PollAsync(default);
        Assert.Equal(serverNow, snap.ServerNow);
    }

    [Fact]
    public async Task A_wifi_sign_in_page_or_a_timeout_is_no_connection_never_a_crash()
    {
        using var html = new HttpClient(new Handler((_, _) => Task.FromResult(Handler.Html())));
        await Assert.ThrowsAsync<ServerUnreachableException>(() => new ShopApi(html, Cred, "test").PollAsync(default));
        await Assert.ThrowsAsync<ServerUnreachableException>(() => new ShopApi(html, Cred, "test").ApproveAsync(Guid.NewGuid(), default));
        using var slow = new HttpClient(new Handler((_, _) => throw new TaskCanceledException("timeout")));
        await Assert.ThrowsAsync<ServerUnreachableException>(() => new ShopApi(slow, Cred, "test").PollAsync(default));
        await Assert.ThrowsAsync<ServerUnreachableException>(() => Pairing.StartAsync(html, "https://example.test", "PC", default));
        await Assert.ThrowsAsync<ServerUnreachableException>(() => Pairing.StartAsync(slow, "https://example.test", "PC", default));
    }

    [Fact]
    public async Task Pairing_keeps_waiting_through_a_timeout_and_connects_when_approved()
    {
        var device = Guid.NewGuid();
        int n = 0;
        using var http = new HttpClient(new Handler((_, _) => (++n) switch
        {
            1 => throw new TaskCanceledException("timeout"),                           // this used to end the pairing screen silently
            2 => Task.FromResult(Handler.Html()),
            3 => Task.FromResult(Handler.Json("""{"status":"pending","device_id":null,"shop_code":null,"shop_name":null}""")),
            _ => Task.FromResult(Handler.Json($$"""{"status":"approved","device_id":"{{device}}","shop_code":"TST001","shop_name":"Shop"}""")),
        }));
        var session = new PairingSession("ABCD-EFGH", "poll", "secret", DateTimeOffset.UtcNow.AddMinutes(15), "https://example.test");
        var cred = await Pairing.WaitForApprovalAsync(http, session, TimeSpan.FromMilliseconds(5), default);
        Assert.Equal((device, "secret", "TST001"), (cred!.DeviceId, cred.DeviceSecret, cred.ShopCode));
    }
}

public class LocalStateTests
{
    [Fact]
    public void A_damaged_journal_is_set_aside_and_a_fresh_one_started_so_the_shop_keeps_working()
    {
        var dir = Path.Combine(Path.GetTempPath(), "apj_" + Guid.NewGuid().ToString("N")[..8]);
        Directory.CreateDirectory(dir);
        var path = Path.Combine(dir, "journal.db");
        File.WriteAllText(path, new string('x', 4096));                    // not a database at all
        var log = new List<string>();
        var j = Journal.OpenOrSetAside(path, log.Add);
        var a = Guid.NewGuid();
        j.Begin(a, Guid.NewGuid(), "apjob_x", "t", "P", 1);
        Assert.Equal(AttemptState.Claimed, j.StateOf(a));                 // the new journal works
        Assert.Single(Directory.GetFiles(dir, "journal.db.damaged-*"));    // the old one is kept for support, not deleted
        Assert.Single(log);

        var again = Journal.OpenOrSetAside(path, log.Add);                 // a healthy journal is opened as it is
        Assert.Equal(AttemptState.Claimed, again.StateOf(a));
        Assert.Single(Directory.GetFiles(dir, "journal.db.damaged-*"));
        Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools();
        Directory.Delete(dir, true);
    }

    [Fact]
    public void An_incomplete_saved_connection_means_connect_again_and_a_locked_one_is_not_thrown_away()
    {
        var path = Path.Combine(Path.GetTempPath(), "apc_" + Guid.NewGuid().ToString("N")[..8], "device.bin");
        var store = new DpapiCredentialStore(path);
        store.Save(new DeviceCredentials(Guid.Empty, "", "", "", ""));     // decrypts, but is useless
        Assert.Null(store.Load());

        var good = new DeviceCredentials(Guid.NewGuid(), "secret", "TST001", "Shop", "https://x.example");
        store.Save(good);
        using (new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.None))
            Assert.Throws<IOException>(() => store.Load());                // locked right now: an error to retry, not "not connected"
        Assert.Equal(good, store.Load());                                  // and the connection is still there afterwards
        Directory.Delete(Path.GetDirectoryName(path)!, true);
    }

    [Fact]
    public void An_error_is_logged_with_enough_to_diagnose_and_without_secrets()
    {
        Exception caught;
        try { throw new InvalidOperationException("GET https://abc.supabase.co/storage/v1/object/sign/docs/cv.pdf?token=eyJhbGciOiJIUzI1NiJ9.SECRETPART failed for device 0123456789abcdef0123456789abcdef0123456789abcdef", new IOException("disk")); }
        catch (Exception e) { caught = e; }
        var line = SafeText.Describe(caught);
        Assert.Contains("InvalidOperationException", line);
        Assert.Contains("IOException: disk", line);
        Assert.Contains("https://abc.supabase.co/…", line);
        Assert.Contains(nameof(An_error_is_logged_with_enough_to_diagnose_and_without_secrets), line);    // where it happened
        Assert.DoesNotContain("token=", line);
        Assert.DoesNotContain("SECRETPART", line);
        Assert.DoesNotContain("cv.pdf", line);
        Assert.DoesNotContain("0123456789abcdef0123", line);
        Assert.DoesNotContain("\n", line);
    }
}

public class ShopkeeperTextTests
{
    private static readonly DateTimeOffset Now = new(2026, 10, 6, 10, 0, 0, TimeSpan.Zero);
    private static JobSummary Job(int pages = 10, int copies = 2, bool duplex = true, string? range = null, int paise = 2400, JobStatus status = JobStatus.AwaitingApproval,
                                  int waitedMin = 3, string code = "K7QD", string name = "Thesis final.pdf") =>
        new(Guid.NewGuid(), code, name, pages, copies, true, duplex, range, paise, status, Now.AddMinutes(-waitedMin), Now.AddMinutes(60 - waitedMin), 0);

    [Fact]
    public void Sides_and_sheets_follow_the_page_range_copies_and_double_sided_choice()
    {
        Assert.Equal((20, 10), (JobText.Sides(Job()), JobText.Sheets(Job())));                           // 10 pages x 2 copies, both sides
        Assert.Equal((20, 20), (JobText.Sides(Job(duplex: false)), JobText.Sheets(Job(duplex: false))));
        Assert.Equal((6, 4), (JobText.Sides(Job(range: "1-3")), JobText.Sheets(Job(range: "1-3"))));       // 3 pages: 2 sheets a copy
        Assert.Equal("1 side to print on 1 sheet of paper", JobText.PaperLine(Job(pages: 1, copies: 1)));
        Assert.Equal("Pages 1-3 of 10", JobText.Pages(Job(range: "1-3")));
        Assert.Equal("10 pages", JobText.Pages(Job()));
    }

    [Fact]
    public void Money_waiting_and_expiry_read_plainly()
    {
        Assert.Equal("₹24", JobText.Money(2400));
        Assert.Equal("₹7.50", JobText.Money(750));
        Assert.Equal("Waiting 3 min", JobText.Waiting(Job(), Now));
        Assert.Equal("Just arrived", JobText.Waiting(Job(waitedMin: 0), Now));
        Assert.Equal("Just arrived", JobText.Waiting(Job(waitedMin: -30), Now));                          // a clock that is wrong never shows nonsense
        Assert.Equal("Expires in 57 min if not approved", JobText.Expiry(Job(), Now));
        Assert.False(JobText.ExpiresSoon(Job(), Now));
        Assert.True(JobText.ExpiresSoon(Job(waitedMin: 55), Now));
        Assert.Equal("Out of time. It is being closed.", JobText.Expiry(Job(waitedMin: 61), Now));
        Assert.Null(JobText.Expiry(Job() with { ApprovalExpiresAt = null }, Now));
        Assert.Equal("1 h 05 min", JobText.Span(TimeSpan.FromMinutes(65)));
    }

    [Fact]
    public void No_state_is_ever_worded_as_printed()
    {
        foreach (var s in Enum.GetValues<JobStatus>())
        {
            var text = JobText.State(s);
            Assert.False(string.IsNullOrWhiteSpace(text));
            Assert.DoesNotContain("printed", text, StringComparison.OrdinalIgnoreCase);                  // decision O-8: only a person can say that
        }
        Assert.Equal("Sent to printer", JobText.State(JobStatus.Completed));
    }

    [Fact]
    public void An_order_is_found_by_its_code_however_it_is_typed_or_by_its_document_name()
    {
        var j = Job();
        Assert.True(JobText.Matches(j, null));
        Assert.True(JobText.Matches(j, "k7qd"));
        Assert.True(JobText.Matches(j, " K7-QD "));
        Assert.True(JobText.Matches(j, "7Q"));
        Assert.True(JobText.Matches(j, "thesis"));
        Assert.False(JobText.Matches(j, "ZZZZ"));
        Assert.False(JobText.Matches(j, "--"));
    }

    [Fact]
    public void Alerts_one_for_requests_that_arrive_together_none_for_old_ones_and_a_steady_reminder_no_storm()
    {
        var policy = new AlertPolicy(TimeSpan.FromMinutes(2));
        var a = Job(code: "AAAA"); var b = Job(code: "BBBB"); var c = Job(code: "CCCC", name: "notes.pdf");
        var done = Job(status: JobStatus.Completed);

        Assert.Equal(AlertKind.None, policy.Next([done], Now).Kind);                                     // nothing waiting: silence
        var first = policy.Next([a, b, done], Now);                                                      // app start with two waiting, or two together
        Assert.Equal((AlertKind.New, 2), (first.Kind, first.Count));                                     // ONE alert, not two
        Assert.Equal(AlertKind.None, policy.Next([a, b], Now.AddSeconds(10)).Kind);                      // every later poll: quiet
        Assert.Equal(AlertKind.None, policy.Next([a, b], Now.AddSeconds(110)).Kind);
        var reminder = policy.Next([a, b], Now.AddSeconds(121));
        Assert.Equal((AlertKind.Reminder, 2), (reminder.Kind, reminder.Count));                          // still unanswered after a while
        Assert.Equal(AlertKind.None, policy.Next([a, b], Now.AddSeconds(131)).Kind);

        var third = policy.Next([a, b, c], Now.AddSeconds(140));
        Assert.Equal((AlertKind.New, 1, "notes.pdf"), (third.Kind, third.Count, third.FirstDocument));
        Assert.Equal(AlertKind.None, policy.Next([a with { Status = JobStatus.Approved }, b with { Status = JobStatus.Rejected }, c with { Status = JobStatus.Printing }], Now.AddMinutes(30)).Kind);   // all answered: no reminder
    }
}

public class PrinterHealthTests
{
    [Fact]
    public void Windows_status_values_become_plain_warnings()
    {
        var ok = PrinterHealth.From("Counter printer", "USB001", "Kyocera TASKalfa XPS", 0, 0);
        Assert.True(ok.Fine);
        Assert.True(PrinterHealth.From("P", "USB001", "D", 0x400, 0).Offline);                           // "Use printer offline"
        Assert.True(PrinterHealth.From("P", "WSD-1", "D", 0, 0x80).Offline);
        Assert.True(PrinterHealth.From("P", "USB001", "D", 0, 0x1).Paused);
        Assert.Equal("is out of paper", PrinterHealth.From("P", "USB001", "D", 0, 0x10).Trouble);
        Assert.Equal("has a paper jam", PrinterHealth.From("P", "USB001", "D", 0, 0x8).Trouble);
        Assert.False(PrinterHealth.Missing("gone").Exists);
    }

    [Fact]
    public void A_printer_that_makes_a_file_is_recognised_whatever_it_is_called()
    {
        Assert.True(PrinterHealth.From("Counter printer", "PORTPROMPT:", "Microsoft Print To PDF", 0, 0).IsVirtual);
        Assert.True(PrinterHealth.From("AutoPrint-Spike-PDF", @"F:\out\spike_out.pdf", "Microsoft Print To PDF", 0, 0).IsVirtual);
        Assert.True(PrinterHealth.From("Microsoft XPS Document Writer", "PORTPROMPT:", "Microsoft XPS Document Writer v4", 0, 0).IsVirtual);
        Assert.False(PrinterHealth.From("TASKalfa 3212i", "WSD-5549776f", "Kyocera TASKalfa 3212i XPS", 0, 0).IsVirtual);
        Assert.False(PrinterHealth.From("HP LaserJet", "USB001", "HP Universal Printing PCL 6", 0, 0).IsVirtual);
    }

    [Fact]
    public void A_printer_that_does_not_exist_is_reported_missing()
    {
        Assert.False(WinSpoolObserver.Health("No Such Printer " + Guid.NewGuid()).Exists);
        Assert.False(WinSpoolObserver.Health("").Exists);
    }
}

/// <summary>Real Windows spooler and the real SumatraPDF; run only with AP_REAL_PRINTER and AP_SUMATRA set.</summary>
public class RealPrinterGuardTests
{
    [RealPrinterFact]
    public async Task The_print_program_is_never_started_for_a_printer_that_does_not_exist()
    {
        var dir = Path.Combine(Path.GetTempPath(), "ap_real"); Directory.CreateDirectory(dir);
        var file = Path.Combine(dir, "apjob_" + Guid.NewGuid().ToString("N") + ".pdf");
        File.WriteAllBytes(file, TestPage.Build("AutoPrint test", "guard"));
        try
        {
            var clock = System.Diagnostics.Stopwatch.StartNew();
            var r = await new SumatraEngine(Environment.GetEnvironmentVariable("AP_SUMATRA")!).SubmitAsync(
                new PrintRequest(file, "No Such Printer " + Guid.NewGuid(), new PrintOptions(1, false, false, null), "apjob_guard", 1), default);
            Assert.Equal((false, "printer_not_found"), (r.Accepted, r.Error));
            Assert.True(clock.Elapsed < TimeSpan.FromSeconds(10), "it answered at once instead of hanging until the timeout");
        }
        finally { File.Delete(file); }
    }

    [RealPrinterFact]
    public void The_health_check_reads_a_real_printer_and_the_genuine_program_is_ready()
    {
        var h = WinSpoolObserver.Health(Environment.GetEnvironmentVariable("AP_REAL_PRINTER")!);
        Assert.True(h.Exists);
        if (h.Name == "AutoPrint-Spike-PDF") Assert.True(h.IsVirtual, "a printer whose port is a file makes a file, not paper");
        Assert.Null(((IPrintEngine)new SumatraEngine(Environment.GetEnvironmentVariable("AP_SUMATRA")!)).NotReady());
    }
}
