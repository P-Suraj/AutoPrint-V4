using AutoPrint.Core.Printing;

namespace AutoPrint.Core.Shop;

/// <summary>
/// The words and numbers the shopkeeper reads on a request. Kept here, away from the windows, so they are tested.
/// Wording rule (decision O-8): the software never says a job "printed" as a fact; only a person can say that.
/// </summary>
public static class JobText
{
    public static string Money(int paise) => paise % 100 == 0 ? $"₹{paise / 100}" : $"₹{paise / 100m:0.00}";

    public static string Plural(int n, string one, string many) => $"{n} {(n == 1 ? one : many)}";

    /// <summary>Pages of the document that will be printed (the page range applied), for one copy.</summary>
    public static int SelectedPages(JobSummary j) => PageRange.SelectedCount(j.PageRange, j.PageCount) ?? j.PageCount;

    /// <summary>Printed sides in total: selected pages times copies. This is what the price is counted in.</summary>
    public static int Sides(JobSummary j) => SelectedPages(j) * j.Copies;

    /// <summary>Sheets of paper that should come out: two sides share a sheet when printing on both sides.</summary>
    public static int Sheets(JobSummary j) => (j.Duplex ? (SelectedPages(j) + 1) / 2 : SelectedPages(j)) * j.Copies;

    public static string PaperLine(JobSummary j) =>
        $"{Plural(Sides(j), "side", "sides")} to print on {Plural(Sheets(j), "sheet", "sheets")} of paper";

    public static string Colour(JobSummary j) => j.Color ? "Colour" : "Black and white";
    public static string SidesChoice(JobSummary j) => j.Duplex ? "Both sides" : "One side";
    public static string Pages(JobSummary j) =>
        string.IsNullOrWhiteSpace(j.PageRange) ? Plural(j.PageCount, "page", "pages") : $"Pages {j.PageRange!.Trim()} of {j.PageCount}";

    /// <summary>"2 min", "1 h 05 min". Anything negative (a clock that is wrong) reads as "just now".</summary>
    public static string Span(TimeSpan t)
    {
        if (t < TimeSpan.FromMinutes(1)) return "under a minute";
        if (t < TimeSpan.FromHours(1)) return $"{(int)t.TotalMinutes} min";
        return $"{(int)t.TotalHours} h {t.Minutes:00} min";
    }

    public static string Waiting(JobSummary j, DateTimeOffset now)
    {
        var t = now - j.CreatedAt;
        return t < TimeSpan.FromMinutes(1) ? "Just arrived" : $"Waiting {Span(t)}";
    }

    /// <summary>Null when the request has no approval deadline (it is not waiting any more).</summary>
    public static string? Expiry(JobSummary j, DateTimeOffset now)
    {
        if (j.ApprovalExpiresAt is not { } at) return null;
        var left = at - now;
        return left <= TimeSpan.Zero ? "Out of time. It is being closed." : $"Expires in {Span(left)} if not approved";
    }

    /// <summary>True when little time is left to approve, so the card can show it in a warning colour.</summary>
    public static bool ExpiresSoon(JobSummary j, DateTimeOffset now) =>
        j.ApprovalExpiresAt is { } at && at - now < TimeSpan.FromMinutes(10);

    public static bool IsActive(JobStatus s) => s is JobStatus.AwaitingApproval or JobStatus.Approved or JobStatus.Printing or JobStatus.NeedsAttention;

    /// <summary>The state of a request in plain words. "Completed" is "Sent to printer": the software saw the job leave
    /// the Windows print queue, it did not see paper.</summary>
    public static string State(JobStatus s) => s switch
    {
        JobStatus.AwaitingApproval => "Waiting for you",
        JobStatus.Approved => "Approved, prints next",
        JobStatus.Printing => "Printing now",
        JobStatus.NeedsAttention => "Needs your attention",
        JobStatus.Completed => "Sent to printer",
        JobStatus.Failed => "Did not go through",
        JobStatus.Rejected => "Rejected",
        JobStatus.Cancelled => "Cancelled by customer",
        JobStatus.Expired => "Not approved in time",
        _ => s.ToString(),
    };

    /// <summary>"Today 3:42 PM" / "Yesterday 6:10 PM" in the PC's own time zone.</summary>
    public static string When(DateTimeOffset at, DateTimeOffset now)
    {
        var local = at.ToLocalTime(); var today = now.ToLocalTime().Date;
        var time = local.ToString("h:mm tt", System.Globalization.CultureInfo.InvariantCulture);
        return local.Date == today ? "Today " + time : local.Date == today.AddDays(-1) ? "Yesterday " + time
            : local.ToString("d MMM ", System.Globalization.CultureInfo.InvariantCulture) + time;
    }

    private static string Fold(string s) => new(s.Where(char.IsLetterOrDigit).Select(char.ToUpperInvariant).ToArray());

    /// <summary>Find by order code (spaces, dashes and letter case ignored) or by part of the document name.</summary>
    public static bool Matches(JobSummary j, string? query)
    {
        if (string.IsNullOrWhiteSpace(query)) return true;
        var q = Fold(query);
        if (q.Length == 0) return false;
        return Fold(j.OrderShortCode).Contains(q) || j.DocumentName.Contains(query.Trim(), StringComparison.OrdinalIgnoreCase);
    }
}

public enum AlertKind { None, New, Reminder }

/// <param name="Count">New: how many requests are new. Reminder: how many are still waiting.</param>
public sealed record Alert(AlertKind Kind, int Count, string? FirstDocument)
{
    public static readonly Alert Nothing = new(AlertKind.None, 0, null);
}

/// <summary>
/// Decides when the shop PC should make itself noticed. One alert for any number of requests that arrive together
/// (also for those already waiting when the app starts), then a reminder at a steady interval while something is
/// still waiting for an answer. Never more than one alert per interval, so there is no alert storm.
/// </summary>
public sealed class AlertPolicy(TimeSpan? remindEvery = null)
{
    private readonly TimeSpan _remindEvery = remindEvery ?? TimeSpan.FromMinutes(2);
    private readonly HashSet<Guid> _seen = [];
    private DateTimeOffset _last = DateTimeOffset.MinValue;

    public Alert Next(IReadOnlyList<JobSummary> jobs, DateTimeOffset now)
    {
        var waiting = jobs.Where(j => j.Status == JobStatus.AwaitingApproval).ToList();
        var fresh = waiting.Where(j => !_seen.Contains(j.JobId)).ToList();
        _seen.IntersectWith(waiting.Select(j => j.JobId));           // answered requests are forgotten, so this never grows
        foreach (var j in fresh) _seen.Add(j.JobId);
        if (waiting.Count == 0) return Alert.Nothing;
        if (fresh.Count > 0) { _last = now; return new(AlertKind.New, fresh.Count, fresh[^1].DocumentName); }
        if (now - _last >= _remindEvery || now < _last) { _last = now; return new(AlertKind.Reminder, waiting.Count, null); }
        return Alert.Nothing;
    }
}
