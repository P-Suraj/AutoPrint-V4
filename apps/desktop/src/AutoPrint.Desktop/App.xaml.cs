using System;
using System.IO;
using System.Net.Http;
using System.Threading;
using System.Windows;
using AutoPrint.Core;
using AutoPrint.Core.Agent;
using AutoPrint.Core.Printing;
using AutoPrint.Core.Shop;

namespace AutoPrint.Desktop;

public partial class App : Application
{
    public const string Version = "4.0.0";
    private Mutex? _single;
    private System.Windows.Forms.NotifyIcon? _tray;
    private MainWindow? _window;
    public static readonly HttpClient Http = new() { Timeout = TimeSpan.FromSeconds(30) };

    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        if (e.Args.Length == 2 && e.Args[0] == "--selftest-preview") { SelfTestPreview(e.Args[1]); return; }
        _single = new Mutex(true, @"Local\AutoPrint.V4.SingleInstance", out bool first);
        if (!first) { Shutdown(); return; }                     // already running: the first copy owns the tray

        DispatcherUnhandledException += (_, a) => { Log("ui error " + a.Exception.GetType().Name); a.Handled = true; };
        _window = new MainWindow(Version);
        _tray = new System.Windows.Forms.NotifyIcon { Icon = new System.Drawing.Icon(GetResourceStream(new Uri("pack://application:,,,/app.ico")).Stream), Text = "AutoPrint", Visible = true };
        _tray.DoubleClick += (_, _) => ShowWindow();
        var menu = new System.Windows.Forms.ContextMenuStrip();
        menu.Items.Add("Open AutoPrint", null, (_, _) => ShowWindow());
        menu.Items.Add("Quit", null, (_, _) => Quit());
        _tray.ContextMenuStrip = menu;
        _window.Start();
        if (!Array.Exists(e.Args, a => a == "--background")) ShowWindow();
    }

    /// <summary>Support tool: renders page 1 of a PDF with the same code the preview uses, writes the result to app.log, exits.</summary>
    private async void SelfTestPreview(string pdfPath)
    {
        int code = 0;
        try
        {
            var r = await PdfRender.OpenAsync(pdfPath);
            var img = await r.PageAsync(0, 800);
            Log($"selftest-preview ok: pages={r.PageCount} first page {img.PixelWidth}x{img.PixelHeight}");
        }
        catch (Exception ex) { Log("selftest-preview FAILED: " + ex.GetType().Name + " " + ex.Message); code = 1; }
        Shutdown(code);
    }

    public void ShowWindow() { _window!.Show(); _window.WindowState = WindowState.Normal; _window.Activate(); }
    public void Notify(string text) => _tray?.ShowBalloonTip(4000, "AutoPrint", text, System.Windows.Forms.ToolTipIcon.Info);

    public void Quit()
    {
        _window?.Stop();
        if (_tray is not null) { _tray.Visible = false; _tray.Dispose(); }
        Shutdown();
    }

    public static void Log(string line)
    {
        try
        {
            Directory.CreateDirectory(Settings.Dir);
            var f = Path.Combine(Settings.Dir, "app.log");
            if (File.Exists(f) && new FileInfo(f).Length > 500_000) File.Move(f, f + ".old", true);
            File.AppendAllText(f, $"{DateTime.Now:s} {line}{Environment.NewLine}");     // never secrets, tokens or file contents
        }
        catch (IOException) { }
    }
}
