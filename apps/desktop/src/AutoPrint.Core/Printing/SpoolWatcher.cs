using System.Diagnostics;

namespace AutoPrint.Core.Printing;

/// <summary>Follows one job through the Windows spooler by its unique name and returns what it saw.</summary>
public static class SpoolWatcher
{
    public static async Task<SpoolEvidence> WatchAsync(
        ISpoolerObserver observer, string printer, string jobName, int expectedPages, TimeSpan maxWait,
        Func<CancellationToken, Task>? onTick, TimeSpan tickEvery, CancellationToken ct, TimeSpan? pollEvery = null)
    {
        var poll = pollEvery ?? TimeSpan.FromMilliseconds(50);
        var clock = Stopwatch.StartNew();
        var flags = new HashSet<string>();
        bool seen = false, printing = false, left = false;
        int maxPages = 0;
        TimeSpan? firstSeen = null, gone = null, lastTick = TimeSpan.Zero;

        while (clock.Elapsed < maxWait)
        {
            ct.ThrowIfCancellationRequested();
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

            if (onTick is not null && clock.Elapsed - lastTick >= tickEvery)
            {
                lastTick = clock.Elapsed;
                await onTick(ct);
            }
            await Task.Delay(poll, ct);
        }

        var inQueue = seen ? ((gone ?? clock.Elapsed) - (firstSeen ?? TimeSpan.Zero)).TotalSeconds : 0;
        return new SpoolEvidence(seen, printing, left, flags.OrderBy(x => x).ToArray(), maxPages, expectedPages, inQueue);
    }
}
