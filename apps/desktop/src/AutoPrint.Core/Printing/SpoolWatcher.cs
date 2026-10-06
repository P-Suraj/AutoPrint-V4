using System.Diagnostics;

namespace AutoPrint.Core.Printing;

/// <summary>Follows one job through the Windows spooler by its unique name and returns what it saw.</summary>
public static class SpoolWatcher
{
    /// <param name="waitStartsAfter">When given, the watch can begin before the print process has finished: it runs
    /// (and ticks) for as long as that task takes, and <paramref name="maxWait"/> is counted from its end.</param>
    public static async Task<SpoolEvidence> WatchAsync(
        ISpoolerObserver observer, string printer, string jobName, int expectedPages, TimeSpan maxWait,
        Func<CancellationToken, Task>? onTick, TimeSpan tickEvery, CancellationToken ct, TimeSpan? pollEvery = null,
        Task? waitStartsAfter = null)
    {
        var poll = pollEvery ?? TimeSpan.FromMilliseconds(50);
        var clock = Stopwatch.StartNew();
        var flags = new HashSet<string>();
        bool seen = false, printing = false, left = false;
        int maxPages = 0;
        TimeSpan? firstSeen = null, gone = null, lastTick = TimeSpan.Zero;
        TimeSpan? waitFrom = waitStartsAfter is null ? TimeSpan.Zero : null;

        while (true)
        {
            if (waitFrom is null && waitStartsAfter!.IsCompleted) waitFrom = clock.Elapsed;
            if (waitFrom is { } from && clock.Elapsed - from >= maxWait) break;
            ct.ThrowIfCancellationRequested();
            await TickIfDueAsync();
            IReadOnlyList<SpoolerJobInfo> jobs;
            try { jobs = observer.ListJobs(printer, jobName); }
            catch (Exception) when (!ct.IsCancellationRequested) { jobs = []; await Task.Delay(poll, ct); continue; }   // spooler busy: look again

            if (jobs.Count > 0)
            {
                seen = true; firstSeen ??= clock.Elapsed;
                foreach (var j in jobs)
                {
                    foreach (var f in j.Flags) flags.Add(f);
                    if (j.Flags.Contains("PRINTING")) printing = true;
                    maxPages = Math.Max(maxPages, j.PagesPrinted);
                }
            }
            else if (seen)
            {
                left = true; gone = clock.Elapsed;       // it was in the queue and now is not
                break;
            }

            await Task.Delay(poll, ct);
        }

        // the job is gone but the print process has not returned yet: keep ticking (the lease) until it does
        while (waitStartsAfter is { IsCompleted: false })
        {
            ct.ThrowIfCancellationRequested();
            await TickIfDueAsync();
            await Task.Delay(poll, ct);
        }

        async Task TickIfDueAsync()
        {
            if (onTick is null || clock.Elapsed - lastTick < tickEvery) return;
            lastTick = clock.Elapsed;
            await onTick(ct);
        }

        var inQueue = seen ? ((gone ?? clock.Elapsed) - (firstSeen ?? TimeSpan.Zero)).TotalSeconds : 0;
        return new SpoolEvidence(seen, printing, left, flags.OrderBy(x => x).ToArray(), maxPages, expectedPages, inQueue);
    }
}
