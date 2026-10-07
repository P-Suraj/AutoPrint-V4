using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Threading;
using AutoPrint.Core;
using AutoPrint.Core.Agent;
using AutoPrint.Core.Printing;
using AutoPrint.Core.Shop;

namespace AutoPrint.Desktop;

/// <summary>
/// Support tool:  AutoPrint.exe --selftest-ui &lt;output folder&gt; [soak:&lt;seconds&gt; | live]
/// Builds the real windows with made-up data and writes a PNG of each state, at 100%, at 150% and at the smallest
/// window size, so the screens can be checked without a shop, a printer or a customer. It never reads or writes the
/// real settings, credentials or journal, never uses the network, never lists or touches a printer, and makes no sound:
/// everything it needs is in memory, and its log goes under the output folder. "soak" keeps one window open and
/// reports the CPU and memory it used, in four parts: a quiet queue, a job printing, the same with the window minimised,
/// and the quiet queue again.
/// </summary>
internal static partial class SelfTest
{
    private static readonly DateTimeOffset Now = new DateTimeOffset(new DateTime(2026, 10, 6, 10, 30, 0, DateTimeKind.Local));
    private static readonly DeviceCredentials Shop = new(Guid.NewGuid(), "not-a-real-secret", "TST001", "Campus Print Point", "https://example.invalid");
    private const string PrinterName = "HP LaserJet Pro M404";
    private static readonly Health Fine = new(new PrinterHealth(PrinterName, true, false, false, false, null), null, true);
    private const string PdfPrinter = "Microsoft Print to PDF";
    private static readonly Health NoPaper = new(new PrinterHealth(PdfPrinter, true, true, false, false, null, Prompts: true), null, true);
    private static readonly PrinterInfo[] Installed =
    [
        new(PrinterName, false, false), new("Canon G3010 colour", false, false), new("Kyocera TASKalfa 3212i", false, true),
        new("AutoPrint-Spike-PDF", true, false), new("Fax", true, false, Prompts: true), new(PdfPrinter, true, false, Prompts: true),
    ];

    public static async Task RunAsync(App app, string folder, string? option)
    {
        int code = 0;
        string outDir = Path.GetFullPath(folder);
        var log = new StringBuilder();
        try
        {
            var appData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            if (outDir.StartsWith(Path.Combine(appData, "AutoPrint"), StringComparison.OrdinalIgnoreCase)) throw new InvalidOperationException("choose a folder outside the app's own data");
            Directory.CreateDirectory(outDir);
            Settings.Dir = Path.Combine(outDir, "data");                 // before anything else: the log and any temp file stay under the output folder
            if (option is not null && option.StartsWith("soak", StringComparison.OrdinalIgnoreCase))
                await SoakAsync(log, int.TryParse(option.Split(':').ElementAtOrDefault(1), out var s) ? s : 60);
            else if (option == "live") { if (!await LiveAsync(app, outDir, log)) code = 1; }
            else { Motion.Enabled = false; await ShotsAsync(outDir, log); }
        }
        catch (Exception e) { log.AppendLine("FAILED: " + e); code = 1; }
        try { File.WriteAllText(Path.Combine(outDir, "selftest-ui.log"), log.ToString()); } catch (Exception) { code = 1; }
        App.FlushLog();
        app.Shutdown(code);
    }

    // ---------------------------------------------------------------- made-up data
    private static JobSummary Job(string code, string name, int pages, int copies, bool colour, bool duplex, string? range, int paise, JobStatus status, double minutesAgo, int attempts = 0) =>
        new(Guid.NewGuid(), code, name, pages, copies, colour, duplex, range, paise, status, Now.AddMinutes(-minutesAgo),
            status == JobStatus.AwaitingApproval ? Now.AddMinutes(60 - minutesAgo) : null, attempts);

    private static readonly JobSummary W1 = Job("K7QD", "Thesis final draft.pdf", 48, 2, false, true, null, 9600, JobStatus.AwaitingApproval, 2);
    private static readonly JobSummary W2 = Job("M2XP", "Lab record - Physics practical observations and readings (semester 3) FINAL v2.pdf", 12, 1, true, false, "1-4, 9", 5000, JobStatus.AwaitingApproval, 9);
    private static readonly JobSummary W3 = Job("R8TA", "ID card.pdf", 1, 4, true, false, null, 4000, JobStatus.AwaitingApproval, 53);
    // one order with three files, each with its own settings: the cards share the code and say what the order comes to
    private static readonly JobSummary[] Many =
    [
        Job("G5LT", "Unit 1 notes.pdf", 14, 1, false, true, null, 1400, JobStatus.AwaitingApproval, 1) with { OrderFiles = 3, OrderTotalPaise = 7400 },
        Job("G5LT", "Cover page.pdf", 1, 1, true, false, null, 1000, JobStatus.AwaitingApproval, 1) with { OrderFiles = 3, OrderTotalPaise = 7400 },
        Job("G5LT", "Question bank.pdf", 25, 2, false, false, null, 5000, JobStatus.AwaitingApproval, 1) with { OrderFiles = 3, OrderTotalPaise = 7400 },
    ];
    private static readonly JobSummary P1 =Job("B4HN", "Resume.pdf", 2, 3, false, false, null, 1200, JobStatus.Printing, 4, 1);
    private static readonly JobSummary A1 = Job("C9WL", "Assignment 4.pdf", 6, 1, false, true, null, 600, JobStatus.Approved, 3);
    private static readonly JobSummary N1 = Job("F3ZE", "Project report.pdf", 30, 1, false, true, null, 3000, JobStatus.NeedsAttention, 11, 1);
    private static readonly JobSummary[] Done =
    [
        Job("K7QA", "Hall ticket.pdf", 1, 2, false, false, null, 400, JobStatus.Completed, 25, 1),
        Job("T5MK", "Notes unit 3 and 4 - data structures.pdf", 64, 1, false, true, null, 6400, JobStatus.Completed, 70, 1),
        Job("H2VB", "Poster A4.pdf", 1, 10, true, false, null, 10000, JobStatus.Rejected, 95),
        Job("D6QS", "Bonafide certificate.pdf", 1, 1, false, false, null, 250, JobStatus.Cancelled, 130),
        Job("K7ZR", "Seminar slides.pdf", 22, 1, true, false, null, 22000, JobStatus.Failed, 190, 1),
        Job("W9CA", "Fee receipt.pdf", 2, 1, false, false, null, 400, JobStatus.Expired, 260),
        Job("N4PD", "Internship letter.pdf", 3, 2, false, true, null, 1200, JobStatus.Completed, 60 * 20, 1),
    ];

    private static AgentState State(bool online, params JobSummary[] jobs) =>
        new(online, false, new QueueSnapshot(Shop.ShopCode, Shop.ShopName, jobs, Now, Now), null, online ? null : "No connection to AutoPrint. Retrying…", online ? Now : Now.AddMinutes(-7));

    // ---------------------------------------------------------------- pictures
    private static async Task ShotsAsync(string outDir, StringBuilder log)
    {
        var scenes = new List<(string Name, Func<Window> Make)>
        {
            ("01-pairing", () => MainWith(w => w.DemoPairing("K7QD-M2XP", new TimeSpan(0, 14, 32), offline: false))),
            ("02-pairing-no-internet", () => MainWith(w => w.DemoPairing(null, default, offline: true))),
            ("03-empty-queue", () => MainWith(w => w.Demo(Shop, State(true, Done), Fine))),
            ("04-queue-waiting-and-printing", () => MainWith(w => w.Demo(Shop, State(true, [W1, W2, W3, P1, A1, .. Done]) with { Current = new AutoPrint.Core.Agent.Activity(Stage.Watching, P1.JobId, null) }, Fine))),
            ("05-needs-attention", () => MainWith(w => w.Demo(Shop, State(true, N1, W1), Fine))),
            ("06-needs-attention-print-again", () => MainWith(w => w.Demo(Shop, State(true, N1, W1), Fine, confirm: N1.JobId))),
            ("07-finished", () => MainWith(w => w.Demo(Shop, State(true, [W1, N1, .. Done]), Fine, finishedTab: true))),
            ("08-finished-search", () => MainWith(w => w.Demo(Shop, State(true, [W1, N1, .. Done]), Fine, finishedTab: true, search: "K7"))),
            ("09-finished-search-no-match", () => MainWith(w => w.Demo(Shop, State(true, [W1, N1, .. Done]), Fine, finishedTab: true, search: "ZZ99"))),
            ("10-offline", () => MainWith(w => w.Demo(Shop, State(false, W1, W3), Fine))),
            ("11-printer-offline-warning", () => MainWith(w => w.Demo(Shop, State(true, W1, W2), Fine with { Bw = new PrinterHealth(PrinterName, true, false, true, false, null) }))),
            ("12-printer-missing-blocks-approve", () => MainWith(w => w.Demo(Shop, State(true, W1), Fine with { Bw = PrinterHealth.Missing(PrinterName) }))),
            ("13-no-printer-chosen", () => MainWith(w => w.Demo(Shop, State(true, W1), null), printer: null)),
            ("14-print-program-missing", () => MainWith(w => w.Demo(Shop, State(true, W1, A1), Fine with { EngineOk = false }, notice: "No internet connection, so that did not go through. Nothing was changed. Try again in a moment."))),
            ("15-settings", () => new SettingsWindow(new Settings { BlackWhitePrinter = PrinterName }, Support, Installed)),
            ("17-settings-first-time-default-is-a-real-printer", () => new SettingsWindow(new Settings(), Support, [.. Installed.Reverse()])),
            ("18-settings-no-paper-printer-chosen", () => new SettingsWindow(new Settings { BlackWhitePrinter = PdfPrinter, ColorPrinter = "Canon G3010 colour" }, Support, Installed)),
            ("19-settings-printer-list-lines", PrinterListLines),
            ("26-long-request-alone", () => MainWith(w => w.Demo(Shop, State(true, W2), Fine))),
            ("20-queue-no-paper-printer-chosen", () => MainWith(w => w.Demo(Shop, State(true, W1, W3), NoPaper), printer: PdfPrinter)),
            ("21-failed-run-says-why", () => MainWith(w => w.Demo(Shop, State(true, [W1, .. Done]), NoPaper,
                runs: new RunResult(RunKind.Failed, Done[4].JobId, "engine_failed_nothing_in_spooler", "engine_timeout", PdfPrinter)), printer: PdfPrinter)),
            ("22-finished-failed-says-why", () => MainWith(w => w.Demo(Shop, State(true, [W1, .. Done]), Fine, finishedTab: true,
                runs: new RunResult(RunKind.Failed, Done[4].JobId, "engine_failed_nothing_in_spooler", "exit_code_1", PrinterName)))),
            ("23-needs-attention-still-in-windows-queue", () => MainWith(w => w.Demo(Shop, State(true, N1, W1), Fine, stillQueued: N1.JobId,
                runs: new RunResult(RunKind.Uncertain, N1.JobId, "still_in_queue_when_wait_ended", null, PrinterName)))),
            ("24-print-again-while-still-in-windows-queue", () => MainWith(w => w.Demo(Shop, State(true, N1, W1), Fine, confirm: N1.JobId, stillQueued: N1.JobId))),
            ("25-print-again-remove-failed", () => MainWith(w => w.Demo(Shop, State(true, N1, W1), Fine, confirm: N1.JobId, stillQueued: N1.JobId, removeFailed: true))),
            ("27-requests-search", () => MainWith(w => w.Demo(Shop, State(true, [W1, W2, .. Many, N1, .. Done]), Fine, search: "g5lt"))),
            ("28-requests-search-no-match", () => MainWith(w => w.Demo(Shop, State(true, [W1, W2, .. Many, .. Done]), Fine, search: "K7QA"))),
            ("29-order-with-several-files", () => MainWith(w => w.Demo(Shop, State(true, [W1, .. Many]), Fine))),
            ("16-preview",() => new PreviewWindow(W2, null, null, null, TestPage.Build("AutoPrint preview self-test", "Made-up page. No customer document is used."))),
        };
        foreach (var (name, make) in scenes)
            foreach (var (tag, small, dpi) in new[] { ("100", false, 96.0), ("150", false, 144.0), ("min", true, 96.0) })
            {
                var w = make();
                if (small && w.SizeToContent != SizeToContent.Manual) continue;          // the settings window has one size
                if (small) { w.Width = w.MinWidth; w.Height = w.MinHeight; }
                w.WindowStartupLocation = WindowStartupLocation.Manual; w.Left = -30000; w.Top = -30000;     // off every screen: nothing flashes up on the desktop
                w.ShowInTaskbar = false; w.ShowActivated = false;
                w.Show();
                if (w is PreviewWindow p) { await Idle(w); await p.Ready; }
                await Idle(w); await Idle(w);
                var file = Path.Combine(outDir, $"{name}-{tag}.png");
                var size = Save(w, file, dpi);
                log.AppendLine($"{Path.GetFileName(file)}  {size.Width}x{size.Height} px  (window {w.ActualWidth:0}x{w.ActualHeight:0} at {dpi / 96:P0})");
                w.Hide();
                if (w is not MainWindow) w.Close();
            }
        log.AppendLine("ok");
    }

    /// <summary>The lines of the printer drop-down, drawn with the Settings window's own template. The drop-down itself is
    /// a separate pop-up window that Windows keeps on a real screen, so it cannot be pictured off-screen.</summary>
    private static Window PrinterListLines()
    {
        var settings = new SettingsWindow(new Settings { BlackWhitePrinter = PrinterName }, Support, Installed);
        var list = new System.Windows.Controls.ItemsControl { ItemTemplate = (DataTemplate)settings.FindResource("PrinterLine"), Margin = new Thickness(16) };
        foreach (var item in settings.BwBox.Items) list.Items.Add(item);
        list.ItemContainerStyle = new Style(typeof(System.Windows.Controls.ContentPresenter)) { Setters = { new Setter(FrameworkElement.MarginProperty, new Thickness(10, 8, 10, 8)) } };
        settings.Close();
        return new Window { Width = 520, SizeToContent = SizeToContent.Height, Background = Brushes.White, Content = list, FontFamily = new FontFamily("Segoe UI"), FontSize = 14, UseLayoutRounding = true };
    }

    private static readonly SupportInfo Support = new(App.Version, "Campus Print Point (TST001)", "Connected. Last contact 10:29:54 AM");

    private static MainWindow MainWith(Action<MainWindow> fill, string? printer = PrinterName)
    {
        var w = new MainWindow(App.Version, new Settings { BlackWhitePrinter = printer }, new MemoryCredentialStore(), live: false) { Clock = () => Now };
        fill(w);
        return w;
    }

    private static async Task Idle(Window w) => await w.Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle);

    private static Size Save(Window w, string file, double dpi)
    {
        w.UpdateLayout();
        var root = (FrameworkElement)VisualTreeHelper.GetChild(w, 0);                  // the client area, with the window's background
        double scale = dpi / 96;
        var bitmap = new RenderTargetBitmap((int)Math.Ceiling(root.ActualWidth * scale), (int)Math.Ceiling(root.ActualHeight * scale), dpi, dpi, PixelFormats.Pbgra32);
        bitmap.Render(root);
        var png = new PngBitmapEncoder();
        png.Frames.Add(BitmapFrame.Create(bitmap));
        using var f = File.Create(file);
        png.Save(f);
        return new Size(bitmap.PixelWidth, bitmap.PixelHeight);
    }

    // ---------------------------------------------------------------- idle cost
    /// <summary>One visible window with made-up requests, refreshed like a poll every 10 s (the same snapshot, as on a
    /// quiet day), first with nothing printing, then with a job printing (the only continuous animation).</summary>
    private static async Task SoakAsync(StringBuilder log, int seconds)
    {
        var me = Process.GetCurrentProcess();
        var w = new MainWindow(App.Version, new Settings { BlackWhitePrinter = PrinterName, SoundOn = false }, new MemoryCredentialStore(), live: false) { ShowActivated = false };
        var quiet = State(true, [W1, W2, W3, .. Done]);
        var busy = State(true, [W1, W2, W3, P1, .. Done]) with { Current = new AutoPrint.Core.Agent.Activity(Stage.Watching, P1.JobId, null) };
        w.Demo(Shop, quiet, Fine);
        w.Show();
        await Task.Delay(3000);
        log.AppendLine($"animations: {(Motion.On ? "on" : "off")}; render tier {RenderCapability.Tier >> 16}; logical processors {Environment.ProcessorCount}");
        foreach (var (label, state, minimised) in new[] { ("queue, 3 waiting, nothing printing", quiet, false), ("one job printing (progress line moving)", busy, false),
            ("one job printing, window minimised (progress line at rest)", busy, true), ("queue again", quiet, false) })
        {
            w.WindowState = minimised ? WindowState.Minimized : WindowState.Normal;
            w.Demo(Shop, state, Fine);
            await Task.Delay(2000);
            GC.Collect(); me.Refresh();
            var cpu0 = me.TotalProcessorTime; long mem0 = me.PrivateMemorySize64, managed0 = GC.GetTotalMemory(false); var clock = Stopwatch.StartNew();
            while (clock.Elapsed < TimeSpan.FromSeconds(seconds)) { await Task.Delay(10000); w.Demo(Shop, state, Fine); }
            GC.Collect(); me.Refresh();
            double cpu = (me.TotalProcessorTime - cpu0).TotalMilliseconds / clock.Elapsed.TotalMilliseconds * 100;
            log.AppendLine($"{label}: {clock.Elapsed.TotalSeconds:0} s, CPU {cpu:0.00}% of one core, private memory {mem0 / 1048576.0:0.0} -> {me.PrivateMemorySize64 / 1048576.0:0.0} MB, managed heap {managed0 / 1048576.0:0.0} -> {GC.GetTotalMemory(false) / 1048576.0:0.0} MB");
        }
        log.AppendLine("ok");
    }
}
