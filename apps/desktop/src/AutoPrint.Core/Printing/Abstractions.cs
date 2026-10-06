using AutoPrint.Core.Shop;

namespace AutoPrint.Core.Printing;

public sealed record PrintRequest(string FilePath, string Printer, PrintOptions Options, string SpoolerJobName, int ExpectedPages);

/// <summary>Result of handing the file to the print engine. Accepted means the spooler took it, nothing more.</summary>
public sealed record SubmitResult(bool Accepted, string? Error);

public interface IPrintEngine
{
    Task<SubmitResult> SubmitAsync(PrintRequest request, CancellationToken ct);

    /// <summary>A reason code when the engine cannot print at all right now (its program is missing or damaged),
    /// otherwise null. Checked before a document is downloaded, so such a job fails at once and cleanly.</summary>
    string? NotReady() => null;
}

public sealed record SpoolerJobInfo(int JobId, string Document, IReadOnlyList<string> Flags, int PagesPrinted, int TotalPages);

public interface ISpoolerObserver
{
    bool PrinterExists(string printer);
    /// <summary>All jobs in the queue whose document name contains <paramref name="nameContains"/>.</summary>
    IReadOnlyList<SpoolerJobInfo> ListJobs(string printer, string nameContains);
    /// <summary>Remove one job from the queue (used only for a stuck orphan, on a person's request).</summary>
    void RemoveJob(string printer, int jobId);
}

public static class SpoolerFlags
{
    /// <summary>Flags that mean the job did not go through cleanly (docs/PRINT_SPIKE_REPORT.md).</summary>
    public static readonly IReadOnlySet<string> Bad = new HashSet<string>
    { "ERROR", "DELETING", "DELETED", "OFFLINE", "PAPEROUT", "BLOCKED_DEVQ", "USER_INTERVENTION", "RESTART" };
}
