namespace AutoPrint.Core.Printing;

/// <summary>What a look in the Windows print queue found for one request.</summary>
public enum QueueLook
{
    /// <summary>This PC has no record of sending the request to a printer (another PC did, or the record is gone).</summary>
    NoRecord,
    /// <summary>The queue could not be read (printer removed, spooler not answering). Nothing is known.</summary>
    Unreadable,
    /// <summary>None of this request's own print jobs is in the queue.</summary>
    NotThere,
    /// <summary>One of this request's own print jobs is still in the queue: it will print when the printer is ready.</summary>
    Waiting,
}

public enum RemoveOutcome
{
    /// <summary>It was in the queue, was removed, and a later look confirmed that it is gone.</summary>
    Removed,
    /// <summary>It had already left the queue by itself before anything was removed: it has probably printed.</summary>
    GoneByItself,
    /// <summary>It is still in the queue after the removal was asked for. Nothing may be assumed.</summary>
    StillThere,
    Unreadable,
    NoRecord,
}

/// <summary>
/// Guards "Print again" against printing twice. When the printer runs out of paper or is switched off, AutoPrint stops
/// watching after a while and the request becomes "needs attention", but its job can still be sitting in the Windows
/// print queue and will print when the printer recovers. Before a new attempt is started this finds that job, by the
/// spooler job names this PC's journal recorded for this very request (each is unique; no other job is ever looked
/// at or touched), and can remove it. It never prints anything and never starts an attempt: that stays with a person.
/// </summary>
public sealed class WaitingJobs(Journal journal, ISpoolerObserver observer, Action<string>? log = null)
{
    private void Log(string m) { try { log?.Invoke(m); } catch (Exception) { /* logging never changes the answer */ } }

    private IReadOnlyList<JournalAttempt>? Attempts(Guid jobId)
    {
        try { return journal.AttemptsFor(jobId); }
        catch (Exception e) { Log("queue look: print record unreadable: " + e.GetType().Name); return null; }
    }

    /// <summary>The request's own jobs that are in the queue now. Null when a queue could not be read.</summary>
    private List<(string Printer, SpoolerJobInfo Job)>? Find(IReadOnlyList<JournalAttempt> attempts)
    {
        var found = new List<(string, SpoolerJobInfo)>();
        foreach (var a in attempts)
        {
            if (string.IsNullOrWhiteSpace(a.Printer) || string.IsNullOrWhiteSpace(a.SpoolerJobName)) continue;
            try { foreach (var j in observer.ListJobs(a.Printer, a.SpoolerJobName)) found.Add((a.Printer, j)); }
            catch (Exception e) { Log("queue look failed: " + e.GetType().Name); return null; }
        }
        return found;
    }

    public QueueLook Look(Guid jobId)
    {
        var attempts = Attempts(jobId);
        if (attempts is null) return QueueLook.Unreadable;
        if (attempts.Count == 0) return QueueLook.NoRecord;
        var found = Find(attempts);
        return found is null ? QueueLook.Unreadable : found.Count > 0 ? QueueLook.Waiting : QueueLook.NotThere;
    }

    /// <summary>Removes the request's own waiting jobs and then looks again until they are gone or the time is up.
    /// "Removed" is only ever said after a look that found the queue without them.</summary>
    public async Task<RemoveOutcome> RemoveAsync(Guid jobId, CancellationToken ct = default, TimeSpan? confirmWithin = null, TimeSpan? lookEvery = null)
    {
        var attempts = Attempts(jobId);
        if (attempts is null) return RemoveOutcome.Unreadable;
        if (attempts.Count == 0) return RemoveOutcome.NoRecord;
        var found = Find(attempts);
        if (found is null) return RemoveOutcome.Unreadable;
        if (found.Count == 0) return RemoveOutcome.GoneByItself;          // it left while the shopkeeper was reading: nothing to remove, and no reason to print again unasked

        foreach (var (printer, job) in found)
        {
            try { observer.RemoveJob(printer, job.JobId); }
            catch (Exception e) { Log("waiting job not removed: " + e.GetType().Name + " " + e.Message); }
        }
        var clock = System.Diagnostics.Stopwatch.StartNew();
        var limit = confirmWithin ?? TimeSpan.FromSeconds(6);
        while (true)
        {
            var left = Find(attempts);
            if (left is { Count: 0 }) { Log("waiting job removed from the print queue"); return RemoveOutcome.Removed; }
            if (clock.Elapsed >= limit) return left is null ? RemoveOutcome.Unreadable : RemoveOutcome.StillThere;
            await Task.Delay(lookEvery ?? TimeSpan.FromMilliseconds(200), ct);
        }
    }
}
