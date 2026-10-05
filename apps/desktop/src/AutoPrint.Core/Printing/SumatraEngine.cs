using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;

namespace AutoPrint.Core.Printing;

/// <summary>
/// Prints a PDF with SumatraPDF's command line, exactly as measured in docs/PRINT_SPIKE_REPORT.md.
/// Known hazards handled here: the file named SumatraPDF.exe in V3 was the INSTALLER (identical hash), a
/// nonexistent printer name makes Sumatra hang instead of failing, and a killed Sumatra can leave a stuck spooler job.
/// </summary>
public sealed class SumatraEngine(string exePath) : IPrintEngine
{
    /// <summary>SHA-256 of the official portable SumatraPDF 3.6.1 (64-bit) executable, from sumatrapdfreader.org.</summary>
    public const string PortableSha256 = "719f689b34f47be8ca105ce8484948474dafde0e106bab599e4a89326070c3d0";

    public static bool IsGenuinePortable(string path)
    {
        if (!File.Exists(path)) return false;
        using var s = File.OpenRead(path);
        return Convert.ToHexString(SHA256.HashData(s)).Equals(PortableSha256, StringComparison.OrdinalIgnoreCase);
    }

    public static string SettingsFor(Shop.PrintOptions o)
    {
        var parts = new List<string> { $"{o.Copies}x", o.Color ? "color" : "monochrome", o.Duplex ? "duplexlong" : "simplex", "fit", "paper=a4" };
        if (!string.IsNullOrWhiteSpace(o.PageRange))
        {
            var cleaned = new string(o.PageRange.Where(c => char.IsDigit(c) || c is ',' or '-').ToArray());   // digits, commas, hyphens only
            if (cleaned.Length > 0) parts.Add(cleaned);
        }
        return string.Join(",", parts);
    }

    public async Task<SubmitResult> SubmitAsync(PrintRequest r, CancellationToken ct)
    {
        if (!IsGenuinePortable(exePath)) return new(false, "sumatra_missing_or_not_the_portable_build");
        if (!File.Exists(r.FilePath)) return new(false, "file_missing");

        var psi = new ProcessStartInfo(exePath) { UseShellExecute = false, CreateNoWindow = true, RedirectStandardError = true, RedirectStandardOutput = true };
        foreach (var a in new[] { "-print-to", r.Printer, "-print-settings", SettingsFor(r.Options), r.FilePath }) psi.ArgumentList.Add(a);

        using var p = Process.Start(psi)!;
        var stderr = new StringBuilder();
        p.ErrorDataReceived += (_, e) => { if (e.Data is not null && stderr.Length < 400) stderr.AppendLine(e.Data); };
        p.BeginErrorReadLine(); p.BeginOutputReadLine();

        var limit = TimeSpan.FromSeconds(Math.Max(90, 30 + 2.5 * r.ExpectedPages));
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(ct);
        timeout.CancelAfter(limit);
        try { await p.WaitForExitAsync(timeout.Token); }
        catch (OperationCanceledException)
        {
            try { p.Kill(entireProcessTree: true); } catch (InvalidOperationException) { /* already gone */ }
            if (ct.IsCancellationRequested) throw;                              // the app is shutting down
            return new(false, "engine_timeout");                                // a hung process: the observer will see any orphan
        }
        return p.ExitCode == 0 ? new(true, null) : new(false, $"exit_code_{p.ExitCode}");
    }
}
