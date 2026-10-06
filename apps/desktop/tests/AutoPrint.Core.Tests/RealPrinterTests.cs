using AutoPrint.Core.Printing;
using AutoPrint.Core.Shop;
using Xunit;

namespace AutoPrint.Core.Tests;

/// <summary>Runs only when AP_REAL_PRINTER and AP_SUMATRA are set. Uses the real Windows spooler and the real engine.</summary>
public sealed class RealPrinterFactAttribute : FactAttribute
{
    public RealPrinterFactAttribute()
    {
        if (string.IsNullOrEmpty(Environment.GetEnvironmentVariable("AP_REAL_PRINTER")) || string.IsNullOrEmpty(Environment.GetEnvironmentVariable("AP_SUMATRA")))
            Skip = "set AP_REAL_PRINTER (a printer name) and AP_SUMATRA (path to the portable SumatraPDF) to run";
    }
}

public class RealPrinterTests
{
    private static string Printer => Environment.GetEnvironmentVariable("AP_REAL_PRINTER")!;
    private static string Sumatra => Environment.GetEnvironmentVariable("AP_SUMATRA")!;

    private static string NewFile(out string name)
    {
        name = "apjob_" + Guid.NewGuid().ToString("N");
        var dir = Path.Combine(Path.GetTempPath(), "ap_real");
        Directory.CreateDirectory(dir);
        var path = Path.Combine(dir, name + ".pdf");
        File.WriteAllBytes(path, TestPage.Build("AutoPrint test", name));
        return path;
    }

    [RealPrinterFact]
    public async Task The_real_engine_and_observer_produce_evidence_that_satisfies_the_rule()
    {
        var observer = new WinSpoolObserver();
        Assert.True(observer.PrinterExists(Printer));
        Assert.False(observer.PrinterExists("No Such Printer " + Guid.NewGuid()));

        var file = NewFile(out var name);
        var req = new PrintRequest(file, Printer, new PrintOptions(1, false, false, null), name, 1);
        var submit = await new SumatraEngine(Sumatra).SubmitAsync(req, default);
        Assert.True(submit.Accepted, submit.Error);

        var ev = await SpoolWatcher.WatchAsync(observer, Printer, name, 1, TimeSpan.FromSeconds(60), null, TimeSpan.FromSeconds(30), default, TimeSpan.FromMilliseconds(40));
        var decision = OutcomeRules.Decide(submit, ev);
        Assert.True(ev.SpoolerJobSeen, "the job was found by its unique name");
        Assert.True(ev.LeftQueue);
        Assert.False(ev.HasBadFlag, string.Join(",", ev.FlagsSeen));
        Assert.True(decision.Outcome == Outcome.Completed, $"{decision} | seen={ev.SpoolerJobSeen} printing={ev.PrintingSeen} left={ev.LeftQueue} flags=[{string.Join(",", ev.FlagsSeen)}] maxPages={ev.MaxPagesPrinted} secs={ev.SecondsInQueue:F1}");
        Assert.Contains("PRINTING", ev.FlagsSeen);
    }

    [RealPrinterFact]
    public async Task A_job_cancelled_at_the_spooler_is_not_reported_completed()
    {
        var observer = new WinSpoolObserver();
        var file = NewFile(out var name);
        var submitTask = new SumatraEngine(Sumatra).SubmitAsync(new PrintRequest(file, Printer, new PrintOptions(1, false, false, null), name, 1), default);

        // cancel it as soon as it shows up in the queue, like a shopkeeper pressing Cancel in Windows
        var watcher = SpoolWatcher.WatchAsync(observer, Printer, name, 1, TimeSpan.FromSeconds(60), null, TimeSpan.FromSeconds(30), default, TimeSpan.FromMilliseconds(20));
        var deadline = DateTime.UtcNow.AddSeconds(10);
        bool removed = false;
        while (!removed && DateTime.UtcNow < deadline)
        {
            var jobs = observer.ListJobs(Printer, name);
            if (jobs.Count > 0) { try { observer.RemoveJob(Printer, jobs[0].JobId); removed = true; } catch (Exception) { /* race: try again */ } }
            await Task.Delay(10);
        }
        var submit = await submitTask;
        var ev = await watcher;
        Assert.True(removed, "the job never appeared in the queue");
        var decision = OutcomeRules.Decide(submit, ev);
        Assert.True(decision.Outcome != Outcome.Completed, $"{decision} | seen={ev.SpoolerJobSeen} flags=[{string.Join(",", ev.FlagsSeen)}] left={ev.LeftQueue} maxPages={ev.MaxPagesPrinted}");   // the lesson of the spike
    }

    [Fact]
    public void The_v3_installer_copy_is_not_mistaken_for_the_portable_program()
    {
        var v3 = @"F:\Projects\Printer automation\windows-agent\sumatrapdf\SumatraPDF.exe";
        if (!File.Exists(v3)) return;                                                // only meaningful where V3 exists
        Assert.False(SumatraEngine.IsGenuinePortable(v3));
    }

    [Fact]
    public void Print_settings_follow_the_options_and_strip_unsafe_characters()
    {
        Assert.Equal("1x,monochrome,simplex,fit,paper=a4", SumatraEngine.SettingsFor(new PrintOptions(1, false, false, null)));
        Assert.Equal("3x,color,duplexlong,fit,paper=a4,1-3,5", SumatraEngine.SettingsFor(new PrintOptions(3, true, true, "1-3,5")));
        Assert.Equal("2x,monochrome,simplex,fit,paper=a4,1-2,7", SumatraEngine.SettingsFor(new PrintOptions(2, false, false, " 1-2 , 7 ")));
        Assert.Null(SumatraEngine.SettingsFor(new PrintOptions(2, false, false, "1-2; calc.exe")));      // not cleaned up: refused (see PageRangeGuardTests)
    }

    [Fact]
    public void Spooler_flag_names_match_the_completion_rule()
    {
        var f = WinSpoolObserver.FlagNames(0x4 | 0x8 | 0x200);
        Assert.Equal(["DELETING", "SPOOLING", "BLOCKED_DEVQ"], f);
        Assert.All(f.Where(x => x is "DELETING" or "BLOCKED_DEVQ"), x => Assert.Contains(x, SpoolerFlags.Bad));
    }
}
