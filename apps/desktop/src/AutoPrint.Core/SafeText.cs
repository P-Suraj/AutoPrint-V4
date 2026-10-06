using System.Text;
using System.Text.RegularExpressions;

namespace AutoPrint.Core;

/// <summary>
/// Turns an exception into one log line that is enough to diagnose a fault from a shop's app.log, without ever
/// writing a secret: web addresses lose their path and query (signed download links live there) and long
/// token-like runs are cut out. Stack frames carry method names only, never data.
/// </summary>
public static class SafeText
{
    private static readonly Regex Url = new(@"(https?://[^/\s""'<>]+)[^\s""'<>]*", RegexOptions.Compiled | RegexOptions.IgnoreCase);
    private static readonly Regex Token = new(@"[A-Za-z0-9_\-+/=]{32,}", RegexOptions.Compiled);

    public static string Scrub(string? text)
    {
        if (string.IsNullOrEmpty(text)) return "";
        var s = Url.Replace(text, "$1/…");
        s = Token.Replace(s, "[hidden]");
        s = s.Replace('\r', ' ').Replace('\n', ' ');
        return s.Length > 300 ? s[..300] + "…" : s;
    }

    public static string Describe(Exception e, int frames = 6)
    {
        var sb = new StringBuilder();
        int depth = 0;
        for (Exception? x = e; x is not null && depth < 3; x = x.InnerException, depth++)
        {
            if (depth > 0) sb.Append(" <- ");
            sb.Append(x.GetType().Name).Append(": ").Append(Scrub(x.Message));
        }
        var lines = (e.StackTrace ?? "").Split('\n', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        foreach (var line in lines.Take(frames))
        {
            int cut = line.IndexOf(" in ", StringComparison.Ordinal);            // drop the source path, keep the line number
            int at = line.LastIndexOf(":line ", StringComparison.Ordinal);
            sb.Append(" | ").Append(cut > 0 ? line[..cut] + (at > cut ? line[at..] : "") : line);
        }
        return sb.ToString();
    }
}
