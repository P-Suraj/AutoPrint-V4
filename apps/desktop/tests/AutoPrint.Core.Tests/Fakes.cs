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

    public Task<QueueSnapshot> PollAsync(CancellationToken ct) => Task.FromResult(new QueueSnapshot("TST001", "Test", [], DateTimeOffset.UtcNow));
    public Task ApproveAsync(Guid jobId, CancellationToken ct) { Calls.Add("approve"); return Task.CompletedTask; }
    public Task RejectAsync(Guid jobId, string? reason, CancellationToken ct) { Calls.Add("reject"); return Task.CompletedTask; }
    public Task<JobStatus> ResolveAsync(Guid jobId, Resolution r, string? note, CancellationToken ct) { Calls.Add("resolve"); return Task.FromResult(JobStatus.Approved); }

    public Task<Claim?> ClaimAsync(CancellationToken ct)
    {
        Calls.Add("claim"); OnClaim?.Invoke();
        var c = NextClaim; NextClaim = null; return Task.FromResult(c);
    }

    public Task<DateTimeOffset> RenewAsync(Guid attemptId, string token, int seconds, CancellationToken ct)
    { RenewCount++; Calls.Add("renew"); return Task.FromResult(DateTimeOffset.UtcNow.AddMinutes(5)); }

    public Task MarkSentAsync(Guid attemptId, string token, CancellationToken ct)
    {
        Calls.Add("sent");
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

    public PrintOrchestrator MakeOrchestrator(TimeSpan? wait = null, TimeSpan? renew = null) => new(
        Api, Spooler, Spooler, Journal, Downloader,
        new OrchestratorOptions(Path.Combine(Dir, "work"), _ => PrinterName, _ => wait ?? TimeSpan.FromSeconds(3),
                                renew ?? TimeSpan.FromMinutes(1), TimeSpan.FromMilliseconds(5), ReportAttempts: 4, RetryDelay: TimeSpan.FromMilliseconds(1)));

    public static Claim NewClaim(int copies = 1, int pages = 3) => new(
        Guid.NewGuid(), Guid.NewGuid(), new string('a', 64), "apjob_" + Guid.NewGuid().ToString("N"), DateTimeOffset.UtcNow.AddMinutes(5),
        "https://example.invalid/doc", new string('b', 64), 1000, pages, new PrintOptions(copies, false, false, null));

    public void Dispose() { try { Directory.Delete(Dir, true); } catch (IOException) { } }
}
