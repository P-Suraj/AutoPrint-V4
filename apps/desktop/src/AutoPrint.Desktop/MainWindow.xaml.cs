using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using AutoPrint.Core;
using AutoPrint.Core.Agent;
using AutoPrint.Core.Printing;
using AutoPrint.Core.Shop;

namespace AutoPrint.Desktop;

public partial class MainWindow : Window
{
    private readonly string _version;
    private readonly Settings _settings = Settings.Load();
    private readonly ICredentialStore _store = new DpapiCredentialStore(DpapiCredentialStore.DefaultPath());
    private CancellationTokenSource _cts = new();
    private ShopApi? _api;
    private AgentService? _agent;
    private Journal? _journal;
    private readonly HashSet<Guid> _announced = new();

    public MainWindow(string version) { _version = version; InitializeComponent(); }

    protected override void OnClosing(System.ComponentModel.CancelEventArgs e)
    {
        e.Cancel = true;                                          // closing the window keeps printing; Quit is in the tray menu
        Hide();
    }

    public void Start() => _ = RunAsync();
    public void Stop() { _cts.Cancel(); _journal?.Dispose(); }

    private async Task RunAsync()
    {
        try
        {
            var creds = _store.Load();
            while (creds is null && !_cts.IsCancellationRequested) creds = await PairAsync();
            if (creds is not null) StartAgent(creds);
        }
        catch (OperationCanceledException) { }
    }

    // ---------------------------------------------------------------- pairing
    private async Task<DeviceCredentials?> PairAsync()
    {
        ShowView(pair: true);
        StatusText.Text = "Not connected"; SetDot(Brushes.Gray);
        PairingSession session;
        try
        {
            session = await Pairing.StartAsync(App.Http, _settings.ApiBaseUrl, Environment.MachineName, _cts.Token);
        }
        catch (Exception e) when (e is ServerUnreachableException or ApiRejectedException)
        {
            PairCode.Text = "····-····";
            PairNote.Text = e is ApiRejectedException ? "Too many codes right now. Retrying in a moment…" : "No internet connection. Retrying…";
            await Task.Delay(TimeSpan.FromSeconds(8), _cts.Token);
            return null;
        }
        PairCode.Text = session.Code;
        PairNote.Text = "Waiting for approval. The code works for 15 minutes.";
        var creds = await Pairing.WaitForApprovalAsync(App.Http, session, null, _cts.Token);
        if (creds is not null) _store.Save(creds);
        return creds;                                            // null = expired: the loop shows a fresh code
    }

    private void OnNewCode(object sender, RoutedEventArgs e) => _ = RestartPairing();

    private async Task RestartPairing()
    {
        _cts.Cancel(); _cts = new CancellationTokenSource();
        await RunAsync();
    }

    // ---------------------------------------------------------------- running
    private void StartAgent(DeviceCredentials creds)
    {
        Directory.CreateDirectory(Settings.Dir);
        _api = new ShopApi(App.Http, creds, _version);
        _journal = new Journal(Path.Combine(Settings.Dir, "journal.db"));
        var sumatra = Path.Combine(AppContext.BaseDirectory, "tools", "SumatraPDF.exe");
        var orchestrator = new PrintOrchestrator(_api, new SumatraEngine(sumatra), new WinSpoolObserver(), _journal, new HttpDownloader(App.Http),
            new OrchestratorOptions(Path.Combine(Settings.Dir, "work"), _settings.PrinterFor), App.Log);
        _agent = new AgentService(_api, orchestrator, log: App.Log);
        _agent.StateChanged += s => Dispatcher.BeginInvoke(() => Render(s));
        ShopTitle.Text = creds.ShopName;
        ShowView(pair: false);
        if (string.IsNullOrEmpty(_settings.BlackWhitePrinter)) OnSettings(this, new RoutedEventArgs());
        _ = _agent.RunAsync(_cts.Token);
    }

    private void Render(AgentState s)
    {
        if (s.NeedsPairing) { _store.Clear(); _ = RestartPairing(); return; }
        SetDot(s.Online ? Brushes.SeaGreen : Brushes.OrangeRed);
        StatusText.Text = s.Current is { } c ? ActivityText(c) : s.Online ? "Online" : "Offline: retrying";
        bool noPrinter = string.IsNullOrEmpty(_settings.BlackWhitePrinter);
        ShowBanner(s.Problem ?? (noPrinter ? "Choose a printer under “Printers…” before approving jobs." : null));

        var jobs = (s.Queue?.Jobs ?? Array.Empty<JobSummary>())
            .Where(j => j.Status is JobStatus.AwaitingApproval or JobStatus.Approved or JobStatus.Printing or JobStatus.NeedsAttention).ToList();
        EmptyText.Visibility = jobs.Count == 0 ? Visibility.Visible : Visibility.Collapsed;
        Cards.Children.Clear();
        foreach (var j in jobs) Cards.Children.Add(Card(j, noPrinter));
        foreach (var j in jobs.Where(j => j.Status == JobStatus.AwaitingApproval && _announced.Add(j.JobId)))
            ((App)Application.Current).Notify($"New print request: {j.DocumentName}");
    }

    private static string ActivityText(Activity a) => a.Stage switch
    {
        Stage.Downloading => "Getting the file…", Stage.Printing => "Sending to the printer…",
        Stage.Watching => "Printing…", Stage.Reporting => "Finishing…", _ => "Working…"
    };

    private UIElement Card(JobSummary j, bool noPrinter)
    {
        var panel = new StackPanel();
        panel.Children.Add(new TextBlock { Text = j.DocumentName, FontWeight = FontWeights.SemiBold, FontSize = 16, TextTrimming = TextTrimming.CharacterEllipsis });
        var detail = $"{j.OrderShortCode}  ·  {j.PageCount} pages  ·  {j.Copies} {(j.Copies == 1 ? "copy" : "copies")}  ·  {(j.Color ? "Colour" : "Black & white")}  ·  {(j.Duplex ? "Both sides" : "One side")}";
        if (!string.IsNullOrWhiteSpace(j.PageRange)) detail += $"  ·  pages {j.PageRange}";
        panel.Children.Add(new TextBlock { Text = detail, Foreground = Brushes.DimGray, Margin = new Thickness(0, 2, 0, 0) });
        panel.Children.Add(new TextBlock { Text = $"₹{j.AmountPaise / 100m:0.##}", Margin = new Thickness(0, 2, 0, 8) });

        var row = new StackPanel { Orientation = Orientation.Horizontal };
        switch (j.Status)
        {
            case JobStatus.AwaitingApproval:
                row.Children.Add(Btn("Approve and print", () => _api!.ApproveAsync(j.JobId, _cts.Token), primary: true, enabled: !noPrinter));
                row.Children.Add(Btn("Reject", () => _api!.RejectAsync(j.JobId, null, _cts.Token)));
                break;
            case JobStatus.Approved: row.Children.Add(new TextBlock { Text = "Approved. Waiting to print…", Foreground = Brushes.DimGray }); break;
            case JobStatus.Printing: row.Children.Add(new TextBlock { Text = "Printing…", Foreground = Brushes.DimGray }); break;
            case JobStatus.NeedsAttention:
                row.Children.Add(new TextBlock { Text = "Check the printer. We could not confirm this printed.", Foreground = Brushes.Firebrick, Margin = new Thickness(0, 0, 12, 0), VerticalAlignment = VerticalAlignment.Center });
                row.Children.Add(Btn("It printed", () => _api!.ResolveAsync(j.JobId, Resolution.Completed, null, _cts.Token)));
                row.Children.Add(Btn("It did not print", () => _api!.ResolveAsync(j.JobId, Resolution.Failed, null, _cts.Token)));
                row.Children.Add(Btn("Print again", () => _api!.ResolveAsync(j.JobId, Resolution.Retry, null, _cts.Token)));
                break;
        }
        panel.Children.Add(row);
        return new Border { Background = Brushes.White, CornerRadius = new CornerRadius(10), Padding = new Thickness(16), Margin = new Thickness(0, 0, 0, 10), Child = panel };
    }

    private Button Btn(string text, Func<Task> action, bool primary = false, bool enabled = true)
    {
        var b = new Button { Content = text, IsEnabled = enabled };
        if (primary) { b.Background = new SolidColorBrush(Color.FromRgb(29, 78, 216)); b.Foreground = Brushes.White; }
        b.Click += async (_, _) =>
        {
            b.IsEnabled = false;                                  // no double clicks
            try { await action(); _agent?.Wake(); }
            catch (ServerUnreachableException) { ShowBanner("No connection. Try again in a moment."); b.IsEnabled = true; }
            catch (ApiRejectedException ex) { ShowBanner(ex.Message); _agent?.Wake(); }
        };
        return b;
    }

    // ---------------------------------------------------------------- helpers
    private void OnSettings(object sender, RoutedEventArgs e)
    {
        var w = new SettingsWindow(_settings) { Owner = IsVisible ? this : null };
        if (w.ShowDialog() == true) _agent?.Wake();
    }

    private void ShowView(bool pair)
    {
        PairView.Visibility = pair ? Visibility.Visible : Visibility.Collapsed;
        QueueView.Visibility = pair ? Visibility.Collapsed : Visibility.Visible;
        SettingsButton.Visibility = pair ? Visibility.Collapsed : Visibility.Visible;
    }
    private void SetDot(Brush b) => StatusDot.Fill = b;
    private void ShowBanner(string? text) { Banner.Visibility = text is null ? Visibility.Collapsed : Visibility.Visible; BannerText.Text = text; }
}
