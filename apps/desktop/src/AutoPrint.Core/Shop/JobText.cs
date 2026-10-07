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

    /// <summary>For a request whose order has more than one file: how many, and what the whole order comes to.
    /// Null for the usual one-file order. The total is missing when the server is older than this app.</summary>
    public static (string Files, string? Total)? OrderLine(JobSummary j) => j.OrderFiles <= 1 ? null
        : ($"One of {j.OrderFiles} files in this order", j.OrderTotalPaise is { } paise ? $"Order total {Money(paise)}" : null);

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

/// <param name="What">What happened, as far as the software saw it.</param>
/// <param name="Check">What the shopkeeper should look at or do next.</param>
public sealed record FailureText(string What, string Check)
{
    public string Both => What + " " + Check;
}

/// <summary>
/// Plain words for every reason a print run can end without "sent to printer" (the reason codes of OutcomeRules,
/// PrintOrchestrator, HttpDownloader and SumatraEngine). Each says what the software saw and what to check. It never
/// says paper did or did not come out: the software watches the Windows print queue, not the tray.
/// </summary>
public static class FailureWords
{
    private const string Resend = "The customer is told it failed and can send the file again.";
    private const string TestPage = "Print a test page from Settings to see whether the printer answers.";

    /// <param name="reason">The reason code of the run.</param>
    /// <param name="detail">What the print program itself said (engine_timeout, exit_code_1, ...), when there is one.</param>
    /// <param name="printerMakesFile">The printer used does not print on paper.</param>
    /// <param name="printerPrompts">The printer used opens a window and waits for a person.</param>
    public static FailureText For(string? reason, string? detail = null, bool printerMakesFile = false, bool printerPrompts = false)
    {
        string notPaper = printerPrompts
            ? "The printer chosen in Settings does not print on paper: it makes a file and may have opened a window that nobody answered. Choose your real printer in Settings. "
            : printerMakesFile ? "The printer chosen in Settings makes a file, not paper. Choose your real printer in Settings. " : "";
        if (detail == "page_range_invalid") reason = detail;
        switch (reason)
        {
            case "engine_failed_nothing_in_spooler" when detail == "engine_timeout":
                return new("The document was handed to Windows, but it never reached the printer's queue and AutoPrint stopped waiting.",
                    notPaper.Length > 0 ? notPaper + Resend
                    : "Look for a window on this computer that is waiting for an answer, and check that the printer is switched on and connected. " + Resend);
            case "engine_failed_nothing_in_spooler" when detail == "file_missing":
                return new("The customer's file was gone from this computer before it could be printed. Nothing was sent to the printer.",
                    "Antivirus may have removed it. " + Resend);
            case "engine_failed_nothing_in_spooler" when detail == "printer_not_found":
            case "printer_not_found":
                return new("The printer chosen in Settings is not installed on this computer any more. Nothing was sent to it.",
                    "Choose a printer in Settings. " + Resend);
            case "engine_failed_nothing_in_spooler" when detail == "sumatra_missing_or_not_the_portable_build":
            case "sumatra_missing_or_not_the_portable_build":
                return new("The part of AutoPrint that sends documents to the printer is missing or damaged. Nothing was sent to the printer.",
                    "Antivirus may have removed it. Install AutoPrint again. " + Resend);
            case "engine_failed_nothing_in_spooler":
                return new("Windows did not take the document for printing. Nothing reached the printer's queue.",
                    notPaper + TestPage + " If the test page comes out, this file may be one that cannot be printed. " + Resend);
            case "engine_failed_but_job_in_spooler":
                return new("The print program stopped with an error, but a job for this document is in the printer's queue.",
                    "Look at the printer: pages may still come out. If the job is stuck, cancel it in the Windows print queue before you print again.");
            case "job_never_seen_in_spooler":
                return new("The document was sent, but AutoPrint never saw it in the printer's queue. It may have gone through too fast to be seen, or not at all.",
                    notPaper + "Look in the printer's tray before you choose.");
            case "cancelled_at_printer_before_any_page":
                return new("The job was cancelled in the Windows print queue before any page was printed.",
                    "If nobody here cancelled it, check the printer. " + Resend);
            case "spooler_error_flag":
                return new("Windows reported a problem with the printer while this was printing, such as no paper, a paper jam or the printer going offline.",
                    "Put the printer right, then count the pages in the tray: some may have come out.");
            case "still_in_queue_when_wait_ended":
                return new("The job was still waiting in the printer's queue when AutoPrint stopped watching it.",
                    "It may still print. Check that the printer is switched on, not paused and has paper. If you print it again while the old job is still there, it can come out twice.");
            case "no_printing_progress_observed":
                return new("The job left the printer's queue, but Windows never showed it as printing.",
                    notPaper + "Look in the printer's tray before you choose.");
            case "server_refused_completed_evidence":
                return new("The job left the printer's queue, but what AutoPrint saw was not enough to be sure it was printed.",
                    "Look in the printer's tray before you choose.");
            case "page_range_invalid":
                return new("The pages the customer asked for could not be read as a page range, so nothing was printed: printing every page instead would have been wrong.",
                    "Ask the customer which pages they want and to send the file again. If it happens again, call support.");
            case "journal_unavailable":
                return new("AutoPrint could not write its print record on this computer, so it did not print. Nothing was sent to the printer.",
                    "Restart the computer. If it happens again, call support. " + Resend);
            case "download_timeout" or "download_unreachable":
                return new("The customer's file could not be downloaded to this computer. Nothing was sent to the printer.",
                    "Check the internet connection. " + Resend);
            case "download_sha256_mismatch" or "download_size_mismatch" or "download_larger_than_expected":
                return new("The file that arrived was not the same as the one the customer sent, so it was not printed.",
                    Resend + " If it happens again, call support.");
            case "download_io_error":
                return new("The customer's file could not be saved on this computer. Nothing was sent to the printer.",
                    "Check that the disk is not full. " + Resend);
            case { } r when r.StartsWith("download_http_", StringComparison.Ordinal):
                return new("The customer's file was no longer available to download. Nothing was sent to the printer.", Resend);
            case "lease_lost_before_print":
                return new("Getting the file took so long that the request was taken back before printing started. Nothing was sent to the printer.",
                    "Check the internet connection, then look at the request again: it may be waiting for your attention.");
            case "offline_before_print":
                return new("The internet connection was lost just before printing started. Nothing was sent to the printer.",
                    "Check the internet connection. " + Resend);
            case "agent_restarted_before_print":
                return new("AutoPrint was closed, or this computer was switched off, before this was sent to the printer. Nothing was sent.", Resend);
            case "agent_restarted_after_print_intent":
                return new("AutoPrint was closed, or this computer went to sleep or lost power, while this was being sent to the printer.",
                    "It may or may not have printed. Look in the printer's tray before you choose.");
            case "stale_attempt":
                return new("This computer lost contact with AutoPrint for too long while this was printing, so the result could not be recorded.",
                    "It may or may not have printed. Look in the printer's tray before you choose.");
            case "report_undelivered":
                return new("The internet connection was lost before the result of this print could be recorded. AutoPrint sends it when the connection is back.",
                    "Look in the printer's tray to see whether it came out.");
            default:
                return new("AutoPrint could not confirm what happened to this print.", "Look at the printer and its tray before you choose.");
        }
    }
}

public enum AlertKind { None, New, Reminder }

/// <param name="Count">New: how many requests are new. Reminder: how many are still waiting.</param>
public sealed record Alert(AlertKind Kind, int Count, string? FirstDocument)
{
    public static readonly Alert Nothing = new(AlertKind.None, 0, null);
}

/// <summary>
/// Decides when the shop PC should make itself noticed. One alert for any number of requests that arrive together,
/// then a reminder at a steady interval while something is still waiting for an answer. Never more than one alert
/// per interval, so there is no alert storm. Requests that were already waiting when the app started are not "new":
/// the first look is silent (the shopkeeper has just opened the app and sees them), and the reminder follows after
/// one interval if they are still unanswered.
/// The reminder ends by itself. It counts only requests that can still be answered: one whose time to approve has run
/// out is no longer reminded about, and while there is no internet nothing is said at all, because the list on screen is
/// then an old one and no answer can be sent. So a PC left on overnight without a connection stays quiet.
/// </summary>
public sealed class AlertPolicy(TimeSpan? remindEvery = null)
{
    private readonly TimeSpan _remindEvery = remindEvery ?? TimeSpan.FromMinutes(2);
    private readonly HashSet<Guid> _seen = [];
    private DateTimeOffset _last = DateTimeOffset.MinValue;
    private bool _started;
    private int _reminders;          // since the last new request: the first three come one interval apart, later ones five
    private const int QuickReminders = 3;

    /// <param name="now">This PC's clock: used only to space the alerts.</param>
    /// <param name="serverNow">The server's clock carried forward, to tell whether a request can still be approved. Defaults to <paramref name="now"/>.</param>
    /// <param name="online">False while the server cannot be reached: the list is then not current.</param>
    public Alert Next(IReadOnlyList<JobSummary> jobs, DateTimeOffset now, DateTimeOffset? serverNow = null, bool online = true)
    {
        if (!online) return Alert.Nothing;
        var waiting = jobs.Where(j => j.Status == JobStatus.AwaitingApproval).ToList();
        var open = waiting.Where(j => j.ApprovalExpiresAt is not { } ends || ends > (serverNow ?? now)).ToList();
        var fresh = open.Where(j => !_seen.Contains(j.JobId)).ToList();
        _seen.IntersectWith(waiting.Select(j => j.JobId));           // answered requests are forgotten, so this never grows
        foreach (var j in fresh) _seen.Add(j.JobId);
        if (!_started) { _started = true; _last = now; return Alert.Nothing; }
        if (open.Count == 0) { _reminders = 0; return Alert.Nothing; }
        if (fresh.Count > 0) { _last = now; _reminders = 0; return new(AlertKind.New, fresh.Count, fresh[^1].DocumentName); }
        // A shopkeeper who has not answered after three reminders is busy or away: keep reminding, but far less often,
        // so the counter is not filled with a chime every two minutes for the whole hour a request can wait.
        var gap = _reminders < QuickReminders ? _remindEvery : _remindEvery * 5;
        if (now - _last >= gap || now < _last) { _last = now; _reminders++; return new(AlertKind.Reminder, open.Count, null); }
        return Alert.Nothing;
    }
}
