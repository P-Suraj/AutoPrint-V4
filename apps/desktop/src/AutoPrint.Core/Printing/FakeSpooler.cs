using System.Collections.Concurrent;
using System.Diagnostics;

namespace AutoPrint.Core.Printing;

public enum FakeScenario
{
    Success,
    EngineRejects,           // the print process fails and nothing reaches the queue
    EngineThrows,
    NeverAppears,            // accepted, but no job is ever visible in the queue
    StuckInQueue,            // appears, never leaves (printer paused or orphaned job)
    CancelledAtPrinter,      // appears, is deleted before any page prints
    PaperOut,                // appears with a PAPEROUT flag, then leaves
    RejectsButOrphan,        // the engine reports failure but a job is left in the queue
}

/// <summary>
/// A scripted printer for tests and for trying the app without paper. It is both the engine and the spooler
/// observer, and computes the queue state from elapsed time, so behaviour is deterministic.
/// </summary>
public sealed class FakeSpooler(FakeScenario scenario = FakeScenario.Success, int stepMs = 20) : IPrintEngine, ISpoolerObserver
{
    private sealed record Item(int Id, string Name, int Pages, Stopwatch Clock);
    private readonly ConcurrentDictionary<int, Item> _jobs = new();
    private int _next;

    public FakeScenario Scenario { get; set; } = scenario;
    public HashSet<string> Printers { get; } = ["Test Printer"];
    public List<PrintRequest> Submitted { get; } = [];
    public int SubmitCount => Submitted.Count;

    public Task<SubmitResult> SubmitAsync(PrintRequest request, CancellationToken ct)
    {
        Submitted.Add(request);
        if (!File.Exists(request.FilePath)) return Task.FromResult(new SubmitResult(false, "file_missing"));
        switch (Scenario)
        {
            case FakeScenario.EngineThrows: throw new InvalidOperationException("engine crashed");
            case FakeScenario.EngineRejects: return Task.FromResult(new SubmitResult(false, "exit_code_1"));
            case FakeScenario.NeverAppears: return Task.FromResult(new SubmitResult(true, null));
            case FakeScenario.RejectsButOrphan:
                Add(request); return Task.FromResult(new SubmitResult(false, "exit_code_1"));
            default:
                Add(request); return Task.FromResult(new SubmitResult(true, null));
        }
    }

    private void Add(PrintRequest r) { var id = Interlocked.Increment(ref _next); _jobs[id] = new Item(id, r.SpoolerJobName + ".pdf", r.ExpectedPages, Stopwatch.StartNew()); }

    public bool PrinterExists(string printer) => Printers.Contains(printer);

    public IReadOnlyList<SpoolerJobInfo> ListJobs(string printer, string nameContains)
    {
        var list = new List<SpoolerJobInfo>();
        foreach (var j in _jobs.Values.Where(j => j.Name.Contains(nameContains)))
        {
            long t = j.Clock.ElapsedMilliseconds;
            long s = stepMs;
            switch (Scenario)
            {
                case FakeScenario.Success:
                    if (t < s) list.Add(Info(j, ["SPOOLING"], 0));
                    else if (t < 4 * s) list.Add(Info(j, ["SPOOLING", "PRINTING", "RETAINED"], (int)Math.Min(j.Pages, 1 + (t - s) * j.Pages / (3 * s))));
                    break;
                case FakeScenario.StuckInQueue:
                case FakeScenario.RejectsButOrphan:
                    list.Add(Info(j, ["SPOOLING", "PRINTING"], 0));
                    break;
                case FakeScenario.CancelledAtPrinter:
                    if (t < s) list.Add(Info(j, ["SPOOLING"], 0));
                    else if (t < 3 * s) list.Add(Info(j, ["DELETING", "SPOOLING"], 0));
                    break;
                case FakeScenario.PaperOut:
                    if (t < s) list.Add(Info(j, ["SPOOLING"], 0));
                    else if (t < 3 * s) list.Add(Info(j, ["PRINTING", "PAPEROUT"], 1));
                    break;
            }
        }
        return list;
    }

    private static SpoolerJobInfo Info(Item j, string[] flags, int pages) => new(j.Id, j.Name, flags, pages, j.Pages);

    public void RemoveJob(string printer, int jobId) => _jobs.TryRemove(jobId, out _);
}
