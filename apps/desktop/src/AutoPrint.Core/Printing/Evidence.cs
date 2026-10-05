using System.Text.RegularExpressions;
using AutoPrint.Core.Shop;

namespace AutoPrint.Core.Printing;

/// <summary>
/// What the app observed in the Windows spooler. Mirrors completion rule version 2 (docs/PRINT_SPIKE_REPORT.md,
/// supabase/migrations/0006). The SERVER applies the rule; this type only reports facts and predicts the answer
/// so the app never reports "completed" for something the server would refuse.
/// </summary>
public sealed record SpoolEvidence(
    bool SpoolerJobSeen, bool PrintingSeen, bool LeftQueue, IReadOnlyList<string> FlagsSeen,
    int MaxPagesPrinted, int ExpectedPages, double SecondsInQueue)
{
    public const int RuleVersion = 2;

    public bool HasBadFlag => FlagsSeen.Any(SpoolerFlags.Bad.Contains);
    public bool WasCancelledAtPrinter => FlagsSeen.Contains("DELETING") || FlagsSeen.Contains("DELETED");

    public bool SatisfiesRule =>
        SpoolerJobSeen && PrintingSeen && LeftQueue && !HasBadFlag;     // pages printed is informational (migration 0006)

    public IDictionary<string, object?> ToWire(string? reason = null)
    {
        var d = new Dictionary<string, object?>
        {
            ["rule_version"] = RuleVersion,
            ["spooler_job_seen"] = SpoolerJobSeen,
            ["printing_seen"] = PrintingSeen,
            ["left_queue"] = LeftQueue,
            ["flags_seen"] = FlagsSeen.ToArray(),
            ["max_pages_printed"] = MaxPagesPrinted,
            ["expected_pages"] = ExpectedPages,
            ["seconds_in_queue"] = Math.Round(SecondsInQueue, 1),
        };
        if (reason is not null) d["reason"] = reason;
        return d;
    }

    public static SpoolEvidence None(int expectedPages) => new(false, false, false, [], 0, expectedPages, 0);
}

public sealed record Decision(Outcome Outcome, string Reason);

public static class OutcomeRules
{
    /// <summary>
    /// Turns what happened into the outcome to report. Conservative by design (decision F-8):
    /// anything unclear is Uncertain for a human; nothing is ever retried automatically.
    /// </summary>
    public static Decision Decide(SubmitResult submit, SpoolEvidence ev)
    {
        if (!submit.Accepted && !ev.SpoolerJobSeen)
            return new(Outcome.Failed, "engine_failed_nothing_in_spooler");     // nothing reached the printer queue
        if (!submit.Accepted)
            return new(Outcome.Uncertain, "engine_failed_but_job_in_spooler");  // an orphan may be stuck in the queue
        if (ev.SatisfiesRule) return new(Outcome.Completed, "rule_v2_satisfied");
        if (!ev.SpoolerJobSeen) return new(Outcome.Uncertain, "job_never_seen_in_spooler");
        if (ev.WasCancelledAtPrinter && ev.MaxPagesPrinted == 0) return new(Outcome.Failed, "cancelled_at_printer_before_any_page");
        if (ev.HasBadFlag) return new(Outcome.Uncertain, "spooler_error_flag");
        if (!ev.LeftQueue) return new(Outcome.Uncertain, "still_in_queue_when_wait_ended");
        return new(Outcome.Uncertain, "no_printing_progress_observed");
    }
}

public static class PageRange
{
    private static readonly Regex Shape = new(@"^\d+(-\d+)?(\s*,\s*\d+(-\d+)?)*$", RegexOptions.Compiled);

    /// <summary>Number of unique pages selected, or null when the text is not a valid range for this document.</summary>
    public static int? SelectedCount(string? range, int pageCount)
    {
        if (string.IsNullOrWhiteSpace(range)) return pageCount;
        var text = range.Trim();
        if (!Shape.IsMatch(text)) return null;
        var pages = new HashSet<int>();
        foreach (var part in text.Split(','))
        {
            var bounds = part.Trim().Split('-');
            int start = int.Parse(bounds[0]);
            int end = bounds.Length == 1 ? start : int.Parse(bounds[1]);
            if (start < 1 || end < start || end > pageCount) return null;
            for (int p = start; p <= end; p++) pages.Add(p);
        }
        return pages.Count;
    }

    /// <summary>Sides the printer is expected to produce: selected pages times copies.</summary>
    public static int ExpectedPages(PrintOptions o, int pageCount) => (SelectedCount(o.PageRange, pageCount) ?? pageCount) * o.Copies;
}

/// <summary>How long to keep watching a job. From the spike: 30 s plus 2.5 s per page, never under 60 s.</summary>
public static class WaitLimit
{
    public static TimeSpan For(int expectedPages) => TimeSpan.FromSeconds(Math.Max(60, 30 + 2.5 * expectedPages));
}
