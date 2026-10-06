using System;
using System.Collections.Concurrent;
using System.IO;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using AutoPrint.Core;

namespace AutoPrint.Desktop;

public partial class App : Application
{
    public const string Version = "4.0.1";
    private Mutex? _single;
    private EventWaitHandle? _showSignal;
    private System.Windows.Forms.NotifyIcon? _tray;
    private MainWindow? _window;
    public static HttpClient Http { get; internal set; } = new() { Timeout = TimeSpan.FromSeconds(30) };     // replaced only by the self-test, with a made-up server
    public static new App Current => (App)Application.Current;

    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        // Nothing that goes wrong may close the shop's app or pass unseen: it is written to app.log with enough to find it.
        DispatcherUnhandledException += (_, a) => { Log("ui error: " + SafeText.Describe(a.Exception, 12)); a.Handled = true; };
        AppDomain.CurrentDomain.UnhandledException += (_, a) => { Log("fatal: " + (a.ExceptionObject is Exception x ? SafeText.Describe(x, 12) : "unknown")); FlushLog(); };
        TaskScheduler.UnobservedTaskException += (_, a) => { Log("background task: " + SafeText.Describe(a.Exception)); a.SetObserved(); };

        // Support tools. Both use only the folder they are given: never the real settings, credentials, journal or network.
        if (e.Args.Length == 2 && e.Args[0] == "--selftest-preview") { SelfTestPreview(e.Args[1]); return; }
        if (e.Args.Length >= 2 && e.Args[0] == "--selftest-ui") { _ = SelfTest.RunAsync(this, e.Args[1], e.Args.Length > 2 ? e.Args[2] : null); return; }

        _single = new Mutex(true, @"Local\AutoPrint.V4.SingleInstance", out bool first);
        _showSignal = new EventWaitHandle(false, EventResetMode.AutoReset, @"Local\AutoPrint.V4.ShowWindow");
        if (!first)
        {
            // Already running (in the tray). Opening it again must not look like "nothing happens": bring its window up.
            _showSignal.Set();
            Shutdown();
            return;
        }
        var listener = new Thread(() => { while (_showSignal.WaitOne()) Dispatcher.BeginInvoke(ShowWindow); }) { IsBackground = true, Name = "show-window" };
        listener.Start();

        try
        {
            _window = new MainWindow(Version, Settings.Load(), new DpapiCredentialStore(DpapiCredentialStore.DefaultPath()));
            _tray = new System.Windows.Forms.NotifyIcon { Icon = new System.Drawing.Icon(GetResourceStream(new Uri("pack://application:,,,/app.ico")).Stream), Text = "AutoPrint", Visible = true };
            _tray.DoubleClick += (_, _) => ShowWindow();
            _tray.BalloonTipClicked += (_, _) => ShowWindow();
            var menu = new System.Windows.Forms.ContextMenuStrip();
            menu.Items.Add("Open AutoPrint", null, (_, _) => ShowWindow());
            menu.Items.Add("Quit", null, (_, _) => Quit());
            _tray.ContextMenuStrip = menu;
        }
        catch (Exception x)
        {
            // Without a window or a tray icon the app would run unseen and block every later start. Say so and leave.
            Log("startup failed: " + SafeText.Describe(x, 12)); FlushLog();
            MessageBox.Show("AutoPrint could not start. Restart the computer and try again. If it still does not start, install AutoPrint again.", "AutoPrint", MessageBoxButton.OK, MessageBoxImage.Warning);
            Shutdown(1);
            return;
        }
        Log($"started {Version}");
        // the laptop lid opens, or the Wi-Fi comes back: reconnect now, not when the back-off timer gets round to it
        Microsoft.Win32.SystemEvents.PowerModeChanged += (_, a) => { if (a.Mode == Microsoft.Win32.PowerModes.Resume) { Log("woke from sleep"); _window?.WakeAgent(); } };
        System.Net.NetworkInformation.NetworkChange.NetworkAvailabilityChanged += (_, a) => { if (a.IsAvailable) _window?.WakeAgent(); };
        _window.Start();
        if (!Array.Exists(e.Args, a => a == "--background")) ShowWindow();
    }

    /// <summary>Support tool: renders page 1 of a PDF with the same code the preview uses, writes the result to app.log, exits.</summary>
    private async void SelfTestPreview(string pdfPath)
    {
        int code = 0;
        try
        {
            using var r = await PdfRender.OpenAsync(pdfPath);
            var img = await r.PageAsync(0, 800);
            Log($"selftest-preview ok: pages={r.PageCount} first page {img.PixelWidth}x{img.PixelHeight}");
        }
        catch (Exception ex) { Log("selftest-preview FAILED: " + ex.GetType().Name + " " + ex.Message); code = 1; }
        FlushLog();
        Shutdown(code);
    }

    public void ShowWindow()
    {
        if (_window is null) return;
        _window.ShowActivated = true;
        _window.Show();
        if (_window.WindowState == WindowState.Minimized) _window.WindowState = WindowState.Normal;
        _window.Activate();
    }

    public void Notify(string text) { try { _tray?.ShowBalloonTip(5000, "AutoPrint", text, System.Windows.Forms.ToolTipIcon.Info); } catch (Exception e) { Log("notify: " + e.GetType().Name); } }

    public void Quit()
    {
        // quitting stops the shop receiving requests: make sure it is meant, and say what it costs when a job is at the printer
        var text = _window?.IsPrinting == true
            ? "A document is being sent to the printer right now. If you quit, it will show “Needs your attention” next time.\n\nQuit AutoPrint anyway?"
            : "While AutoPrint is closed, new print requests wait and customers see your shop as offline.\n\nQuit AutoPrint?";
        if (MessageBox.Show(text, "AutoPrint", MessageBoxButton.YesNo, MessageBoxImage.Question, MessageBoxResult.No) != MessageBoxResult.Yes) return;
        Log("quit by the user");
        _window?.Stop();
        if (_tray is not null) { _tray.Visible = false; _tray.Dispose(); }
        FlushLog();
        Shutdown();
    }

    protected override void OnExit(ExitEventArgs e) { FlushLog(); base.OnExit(e); }

    // ---------------------------------------------------------------- app.log
    // Lines are queued and written by one background thread, so logging never makes the window wait for the disk and
    // never fails the caller. Never secrets, tokens, links or file contents (see SafeText).
    private static readonly BlockingCollection<string> Lines = new(2000);
    private static readonly Thread Writer = StartWriter();
    private static int _pending;

    public static void Log(string line)
    {
        _ = Writer;
        if (Lines.TryAdd($"{DateTime.Now:s} {line}")) Interlocked.Increment(ref _pending);
    }

    private static Thread StartWriter()
    {
        var t = new Thread(() =>
        {
            foreach (var line in Lines.GetConsumingEnumerable())
            {
                try
                {
                    Directory.CreateDirectory(Settings.Dir);
                    var f = Path.Combine(Settings.Dir, "app.log");
                    if (File.Exists(f) && new FileInfo(f).Length > 500_000) File.Move(f, f + ".old", true);
                    File.AppendAllText(f, line + Environment.NewLine);
                }
                catch (Exception) { /* a log line that cannot be written is dropped; nothing else depends on it */ }
                finally { Interlocked.Decrement(ref _pending); }
            }
        }) { IsBackground = true, Name = "app-log" };
        t.Start();
        return t;
    }

    /// <summary>Waits briefly for queued lines to reach the disk (before exit, and after a fatal error).</summary>
    public static void FlushLog()
    {
        for (int i = 0; i < 100 && Volatile.Read(ref _pending) > 0; i++) Thread.Sleep(10);
    }
}
