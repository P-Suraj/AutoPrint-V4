using AutoPrint.Core;
using AutoPrint.Core.Agent;
using AutoPrint.Core.Printing;
using AutoPrint.Core.Shop;

namespace AutoPrint.Core.Tests;

/// <summary>An in-memory server that records calls in order and can be told to misbehave.</summary>
public sealed class FakeShopApi : IShopApi
{
    public List<string> Calls { get; } = [];
    public Claim? NextClaim { get; set; }
    public int ReportUnreachableTimes { get; set; }
    public bool ReportAlwaysUnreachable { get; set; }
    public bool ReportStale { get; set; }
    public bool RefuseCompletedEvidence { get; set; }
    public int MarkSentUnreachableTimes { get; set; }
    public int RenewCount { get; private set; }
    public List<(Outcome Outcome, IDictionary<string, object?> Evidence)> Reports { get; } = [];
    public Action? OnClaim { get; set; }
    public bool RenewStale { get; set; }
    public bool MarkSentRefused { get; set; }
    private int _polls;
    public int PollCount => Volatile.Read(ref _polls);
    /// <summary>What the poll answers (or throws). Default: an empty queue.</summary>
    public Func<int, QueueSnapshot>? OnPoll { get; set; }

    public static QueueSnapshot Queue(params JobSummary[] jobs) => new("TST001", "Test", jobs, DateTimeOffset.UtcNow);
    public static JobSummary Job(JobStatus status, string code = "A91F", string name = "cv.pdf", Guid? id = null, DateTimeOffset? created = null) =>
        new(id ?? Guid.NewGuid(), code, name, 3, 1, false, false, null, 600, status, created ?? DateTimeOffset.UtcNow,
            status == JobStatus.AwaitingApproval ? (created ?? DateTimeOffset.UtcNow).AddHours(1) : null, 0);

    public Task<QueueSnapshot> PollAsync(CancellationToken ct)
    {
        int n = Interlocked.Increment(ref _polls);
        return Task.FromResult(OnPoll?.Invoke(n) ?? Queue());
    }
    public Task ApproveAsync(Guid jobId, CancellationToken ct) { Calls.Add("approve"); return Task.CompletedTask; }
    public Task RejectAsync(Guid jobId, string? reason, CancellationToken ct) { Calls.Add("reject"); return Task.CompletedTask; }
    public Task<JobStatus> ResolveAsync(Guid jobId, Resolution r, string? note, CancellationToken ct) { Calls.Add("resolve"); return Task.FromResult(JobStatus.Approved); }

    public Task<Claim?> ClaimAsync(CancellationToken ct)
    {
        Calls.Add("claim"); OnClaim?.Invoke();
        var c = NextClaim; NextClaim = null; return Task.FromResult(c);
    }

    public Task<DateTimeOffset> RenewAsync(Guid attemptId, string token, int seconds, CancellationToken ct)
    {
        RenewCount++; Calls.Add("renew");
        if (RenewStale) throw new ApiRejectedException("stale_attempt", "stale", System.Net.HttpStatusCode.Conflict);
        return Task.FromResult(DateTimeOffset.UtcNow.AddMinutes(5));
    }

    public Task MarkSentAsync(Guid attemptId, string token, CancellationToken ct)
    {
        Calls.Add("sent");
        if (MarkSentRefused) throw new ApiRejectedException("rate_limited", "slow down", System.Net.HttpStatusCode.TooManyRequests);
        if (MarkSentUnreachableTimes-- > 0) throw new ServerUnreachableException("offline");
        return Task.CompletedTask;
    }

    public Task<DocumentAccess> DocumentAsync(Guid jobId, CancellationToken ct)
    {
        Calls.Add("document");
        return Task.FromResult(new DocumentAccess("https://example.test/f", new string('0', 64), 1, 1));
    }

    public Task<JobStatus> ReportOutcomeAsync(Guid attemptId, string token, Outcome outcome, IDictionary<string, object?> evidence, CancellationToken ct)
    {
        Calls.Add("report:" + outcome);
        if (ReportAlwaysUnreachable || ReportUnreachableTimes-- > 0) throw new ServerUnreachableException("offline");
        if (ReportStale) throw new ApiRejectedException("stale_attempt", "stale", System.Net.HttpStatusCode.Conflict);
        if (RefuseCompletedEvidence && outcome == Outcome.Completed) throw new ApiRejectedException("evidence_insufficient", "no", System.Net.HttpStatusCode.Conflict);
        Reports.Add((outcome, evidence));
        return Task.FromResult(outcome == Outcome.Completed ? JobStatus.Completed : outcome == Outcome.Failed ? JobStatus.Failed : JobStatus.NeedsAttention);
    }
}

public sealed class FakeDownloader : IDownloader
{
    public string? FailWith { get; set; }
    public Task DownloadAsync(string url, string expectedSha256, long expectedBytes, string path, CancellationToken ct)
    {
        if (FailWith is not null) throw new DownloadFailedException(FailWith);
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        File.WriteAllBytes(path, "%PDF-1.4 fake"u8.ToArray());
        return Task.CompletedTask;
    }
}

/// <summary>Everything one orchestrator test needs, in a temp folder that is removed afterwards.</summary>
public sealed class Rig : IDisposable
{
    public string Dir { get; } = Path.Combine(Path.GetTempPath(), "ap_test_" + Guid.NewGuid().ToString("N")[..8]);
    public FakeShopApi Api { get; } = new();
    public FakeSpooler Spooler { get; }
    public FakeDownloader Downloader { get; } = new();
    public Journal Journal { get; }
    public PrintOrchestrator Orchestrator { get; }
    public List<Activity> Activities { get; } = [];

    public Rig(FakeScenario scenario = FakeScenario.Success, TimeSpan? wait = null, int copies = 1, int pages = 3, string printer = "Test Printer")
    {
        Spooler = new FakeSpooler(scenario, stepMs: 20);
        Journal = new Journal(Path.Combine(Dir, "journal.db"));
        Orchestrator = MakeOrchestrator(wait);
        Orchestrator.ActivityChanged += Activities.Add;
        Api.NextClaim = NewClaim(copies, pages);
        PrinterName = printer;
    }

    public string PrinterName { get; set; }

    public string WorkDir => Path.Combine(Dir, "work");

    public PrintOrchestrator MakeOrchestrator(TimeSpan? wait = null, TimeSpan? renew = null, IPrintEngine? engine = null, TimeSpan? renewBeforePrintAfter = null) => new(
        Api, engine ?? Spooler, Spooler, Journal, Downloader,
        new OrchestratorOptions(WorkDir, _ => PrinterName, _ => wait ?? TimeSpan.FromSeconds(3),
                                renew ?? TimeSpan.FromMinutes(1), TimeSpan.FromMilliseconds(5), ReportAttempts: 4, RetryDelay: TimeSpan.FromMilliseconds(1),
                                RenewBeforePrintAfter: renewBeforePrintAfter));

    /// <summary>Makes the journal file unreadable, as a failing disk or a power cut can.</summary>
    public void BreakJournal()
    {
        foreach (var f in Directory.GetFiles(Dir, "journal.db*")) File.Delete(f);
        File.WriteAllText(Path.Combine(Dir, "journal.db"), "this is not a database, it is long enough to be read as a header ........................................");
    }

    public static Claim NewClaim(int copies = 1, int pages = 3) => new(
        Guid.NewGuid(), Guid.NewGuid(), new string('a', 64), "apjob_" + Guid.NewGuid().ToString("N"), DateTimeOffset.UtcNow.AddMinutes(5),
        "https://example.invalid/doc", new string('b', 64), 1000, pages, new PrintOptions(copies, false, false, null));

    public void Dispose() { try { Directory.Delete(Dir, true); } catch (IOException) { } }
}
