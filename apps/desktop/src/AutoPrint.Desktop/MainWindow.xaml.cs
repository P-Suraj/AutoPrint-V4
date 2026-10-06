using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Documents;
using System.Windows.Media;
using System.Windows.Threading;
using AutoPrint.Core;
using AutoPrint.Core.Agent;
using AutoPrint.Core.Printing;
using AutoPrint.Core.Shop;

namespace AutoPrint.Desktop;

/// <summary>What Windows says about the chosen printers and whether the print program is intact. Read on a background thread.</summary>
public sealed record Health(PrinterHealth? Bw, PrinterHealth? Colour, bool EngineOk);

/// <summary>
/// The shopkeeper's one window. Nothing here waits on the network, the disk, the spooler or a printer: that work runs
/// on background threads and comes back as a state to show. The lists are updated in place, keyed by job, so a poll
/// that changes nothing touches nothing (no flicker, hover and keyboard focus stay where they are).
/// </summary>
public partial class MainWindow : Window
{
    private readonly string _version;
    private readonly Settings _settings;
    private readonly ICredentialStore _store;
    private readonly bool _live;                                   // false in the UI self-test: no network, no timers, no sound
    private CancellationTokenSource _cts = new();
    private DeviceCredentials? _creds;
    private ShopApi? _api;
    private AgentService? _agent;
    private AgentState _state = new(false, false, null, null, null, null);
    private Health? _health;
    private bool _healthBusy;
    private (long Length, DateTime Written, bool Ok)? _engineSeen;
    private readonly AlertPolicy _alerts = new();
    private readonly Dictionary<Guid, DateTimeOffset?> _busy = new();   // answers on their way: null = being sent, time = sent, waiting for the queue to show it
    private Guid? _confirmRetry;
    private string? _notice;
    private DateTimeOffset _noticeAt, _shiftedAt, _pairExpires;
    private bool _pairing, _pairOffline, _toldAboutTray;
    private string _finishedShown = "";
    private PreviewWindow? _preview;
    private readonly DispatcherTimer _tick = new(), _healthTimer = new() { Interval = TimeSpan.FromSeconds(30) };
    private readonly SolidColorBrush _dot = new(Colors.LightGray);

    private readonly Dictionary<Guid, RunResult> _runs = new();        // how print runs ended on this PC since it started: lets a card say why
    private RunResult? _lastRun, _failedRun;

    /// <summary>Replaced by the self-test so its pictures do not depend on the time of day.</summary>
    internal Func<DateTimeOffset> Clock = () => DateTimeOffset.UtcNow;

    // Replaced only by the self-test, so that it never reads a real printer, never starts the print program and never
    // takes the keyboard: a made-up printer and print queue stand in. The real app uses the defaults.
    internal Func<string, PrinterHealth> ReadPrinter = WinSpoolObserver.Health;
    internal Func<bool>? PrintProgramOk;
    internal Func<IShopApi, Journal, (PrintOrchestrator Orchestrator, ISpoolerObserver Queue)>? MakePrinting;
    internal bool Quiet;
    /// <summary>Whether the shopkeeper is looking at this window (then nothing needs to flash). The self-test, whose window
    /// is off the screen, answers for it.</summary>
    internal Func<bool>? InFront;

    // "Print again" must not put the same document out twice (see WaitingJobs). What the last look in the Windows print
    // queue found for each request that needs attention, and where the "print again" conversation stands.
    private enum RetryStep { Looking, Confirm, Removing, RemoveFailed }
    private WaitingJobs? _waitingJobs;
    private readonly Dictionary<Guid, QueueLook> _queueLook = new();
    private readonly HashSet<Guid> _lookingAt = new(), _leftByItself = new();
    private RetryStep _retryStep;

    public MainWindow(string version, Settings settings, ICredentialStore store, bool live = true)
    {
        _version = version; _settings = settings; _store = store; _live = live;
        InitializeComponent();
        StatusDot.Fill = _dot;
        // a small or scaled-up screen (a 1366 x 768 laptop at 150%) must still show the whole window
        Width = Math.Min(Width, SystemParameters.WorkArea.Width); Height = Math.Min(Height, SystemParameters.WorkArea.Height);
        _tick.Tick += (_, _) => Tick();
        _healthTimer.Tick += (_, _) => _ = RefreshHealthAsync();
        IsVisibleChanged += (_, _) => Timers();
        // messages at the top never push the requests off a small window: past a third of its height they scroll
        SizeChanged += (_, a) => BannerArea.MaxHeight = Math.Max(120, a.NewSize.Height * 0.36);
        Activated += (_, _) => Alerts.Flash(this, on: false);
        PreviewKeyDown += (_, e) => { if (e.Key == System.Windows.Input.Key.F && System.Windows.Input.Keyboard.Modifiers == System.Windows.Input.ModifierKeys.Control && QueueView.IsVisible) { TabFinished.IsChecked = true; SearchBox.Focus(); e.Handled = true; } };
    }

    protected override void OnClosing(System.ComponentModel.CancelEventArgs e)
    {
        e.Cancel = true;                                          // closing the window keeps printing; Quit is in the tray menu
        Hide();
        if (_live && !_toldAboutTray) { _toldAboutTray = true; App.Current.Notify("AutoPrint is still running. New print requests will still arrive. To stop it, right-click this icon and choose Quit."); }
    }

    public void Start() => _ = RunAsync(_cts.Token);
    public void Stop() => _cts.Cancel();
    public bool IsPrinting => _state.Current is not null;
    public void WakeAgent() => _agent?.Wake();

    /// <summary>Timers run only while the window can be seen, so a window sitting in the tray all day costs nothing.</summary>
    private void Timers()
    {
        bool on = _live && IsVisible;
        _tick.Interval = TimeSpan.FromSeconds(_pairing ? 1 : 15);
        _tick.IsEnabled = on; _healthTimer.IsEnabled = on && _agent is not null;
        if (on) { Tick(); if (_agent is not null) _ = RefreshHealthAsync(); }
    }

    // ---------------------------------------------------------------- starting and pairing
    private enum View { Start, Pair, Queue }

    private void ShowView(View v)
    {
        void Set(UIElement e, bool show) { if (show && e.Visibility != Visibility.Visible) Motion.Fade(e); e.Visibility = show ? Visibility.Visible : Visibility.Collapsed; }
        Set(StartView, v == View.Start); Set(PairView, v == View.Pair); Set(QueueView, v == View.Queue);
        SettingsButton.Visibility = v == View.Queue ? Visibility.Visible : Visibility.Collapsed;
        _pairing = v == View.Pair;
        if (v != View.Queue) { SyncList(Banners, _bannerEntries, [], animate: false); SetStatus(null, v == View.Pair ? "Not connected yet" : "Starting…"); }
        Timers();
    }

    /// <summary>Runs until this PC is connected and the agent is started. Every failure on the way is shown in plain
    /// words and tried again by itself: this loop never ends silently, whatever goes wrong.</summary>
    private async Task RunAsync(CancellationToken ct)
    {
        while (!ct.IsCancellationRequested)
        {
            try
            {
                ShowView(View.Start); StartTitle.Text = "Starting…"; StartNote.Text = "";
                await Task.Run(CleanLeftovers, ct);
                var creds = await Task.Run(_store.Load, ct);
                while (creds is null) creds = await PairAsync(ct);
                await StartAgentAsync(creds, ct);
                return;
            }
            catch (OperationCanceledException) when (ct.IsCancellationRequested) { return; }
            catch (Exception e)
            {
                App.Log("start: " + SafeText.Describe(e));
                ShowView(View.Start);
                StartTitle.Text = "AutoPrint could not start yet";
                StartNote.Text = "It cannot read or write its own files on this computer right now. It is trying again by itself. If this message stays, restart the computer.";
                try { await Task.Delay(TimeSpan.FromSeconds(5), ct); } catch (OperationCanceledException) { return; }
            }
        }
    }

    /// <summary>No customer document survives a restart: whatever a crash or a power cut left in the work folders goes now.</summary>
    private static void CleanLeftovers()
    {
        foreach (var d in new[] { "work", "preview", "testpage" }) WorkFiles.CleanStale(Path.Combine(Settings.Dir, d));
    }

    private async Task<DeviceCredentials?> PairAsync(CancellationToken ct)
    {
        ShowView(View.Pair);
        PairStep3.Text = $"Check the computer name ({Environment.MachineName}) and press “Yes, connect it”.";
        PairCode.Text = "····-····"; PairCode.Opacity = 0.35; _pairExpires = default; _pairOffline = false;
        PairNote.Text = "Getting a code…";
        PairingSession session;
        try { session = await Pairing.StartAsync(App.Http, _settings.ApiBaseUrl, Environment.MachineName, ct); }
        catch (Exception e) when (e is ServerUnreachableException or ApiRejectedException)
        {
            for (int s = 8; s > 0; s--)                              // recovers by itself; the shopkeeper only has to wait
            {
                PairNote.Text = (e is ApiRejectedException ? "AutoPrint is busy right now." : "No internet connection.") + $" Trying again in {s} s…";
                await Task.Delay(1000, ct);
            }
            return null;
        }
        PairCode.Text = session.Code; PairCode.Opacity = 1; Motion.Fade(PairCode);
        // if this PC's clock is wrong the server's expiry time means nothing here: fall back to the 15 minutes a code lasts
        var left = session.ExpiresAt - DateTimeOffset.UtcNow;
        if (left <= TimeSpan.FromSeconds(30) || left > TimeSpan.FromMinutes(20)) left = TimeSpan.FromMinutes(15);
        _pairExpires = DateTimeOffset.UtcNow + left;
        Tick();
        using var life = CancellationTokenSource.CreateLinkedTokenSource(ct);
        life.CancelAfter(left);
        try
        {
            var creds = await Pairing.WaitForApprovalAsync(App.Http, session, null, life.Token, ok => Dispatcher.BeginInvoke(() => { _pairOffline = !ok; Tick(); }));
            if (creds is not null) await Task.Run(() => _store.Save(creds), ct);
            return creds;                                            // null = expired: the loop shows a fresh code
        }
        catch (OperationCanceledException) when (!ct.IsCancellationRequested) { return null; }      // the code ran out: get a new one
        catch (ApiRejectedException) { return null; }
    }

    private void OnNewCode(object sender, RoutedEventArgs e) => RestartPairing(null);

    private void RestartPairing(string? why)
    {
        _cts.Cancel(); _cts = new CancellationTokenSource();
        _agent = null; _api = null; _creds = null; _health = null; _busy.Clear(); _runs.Clear(); _lastRun = _failedRun = null;
        _waitingJobs = null; _queueLook.Clear(); _leftByItself.Clear(); _confirmRetry = null;
        _state = new(false, false, null, null, null, null);
        PairWhy.Text = why ?? "You do this once. It takes about a minute.";
        ShopTitle.Text = "AutoPrint"; ShopSub.Text = "Print requests from your customers";
        _ = RunAsync(_cts.Token);
    }

    // ---------------------------------------------------------------- running
    private async Task StartAgentAsync(DeviceCredentials creds, CancellationToken ct)
    {
        bool fresh = false;
        var journal = await Task.Run(() =>
        {
            Directory.CreateDirectory(Settings.Dir);
            var j = Journal.OpenOrSetAside(Path.Combine(Settings.Dir, "journal.db"), m => { fresh = true; App.Log(m); });
            try { j.Prune(TimeSpan.FromDays(30)); } catch (Exception e) { App.Log("journal prune: " + e.GetType().Name); }
            return j;
        }, ct);
        var api = new ShopApi(App.Http, creds, _version);
        ISpoolerObserver queue = new WinSpoolObserver();
        var orchestrator = MakePrinting is { } make ? make(api, journal).Unpack(out queue)
            : new PrintOrchestrator(api, new SumatraEngine(SumatraPath), queue, journal, new HttpDownloader(App.Http),
                new OrchestratorOptions(Path.Combine(Settings.Dir, "work"), _settings.PrinterFor), App.Log);
        _waitingJobs = new WaitingJobs(journal, queue, App.Log);
        var agent = new AgentService(api, orchestrator, log: App.Log);
        agent.StateChanged += s => Dispatcher.BeginInvoke(() => { if (ReferenceEquals(agent, _agent)) OnState(s); });
        _api = api; _agent = agent; _creds = creds;
        ShowQueue(creds);
        if (fresh) Notice("AutoPrint started a new print record because the old one was damaged. If a request shows “Needs your attention”, look at the printer before you choose.");
        _ = Task.Run(() => agent.RunAsync(ct), ct);                 // the whole agent, the journal and the spooler watch run off the window's thread
        _ = RefreshHealthAsync();
        if (string.IsNullOrEmpty(_settings.BlackWhitePrinter) && IsVisible) _ = Dispatcher.BeginInvoke(() => OnSettings(this, new RoutedEventArgs()));
    }

    internal static string SumatraPath => Path.Combine(AppContext.BaseDirectory, "tools", "SumatraPDF.exe");

    private void ShowQueue(DeviceCredentials creds)
    {
        _creds = creds;
        ShopTitle.Text = creds.ShopName;
        ShowView(View.Queue);
        Render();
    }

    private void OnState(AgentState s)
    {
        if (s.NeedsPairing)
        {
            App.Log("this PC is no longer connected to the shop: showing a new code");
            try { _store.Clear(); } catch (Exception e) { App.Log("credentials not cleared: " + e.GetType().Name); }
            RestartPairing("This computer was disconnected from the shop. To connect it again, use the new code below.");
            return;
        }
        _state = s;
        if (s.LastRun is { JobId: { } ran } run && !ReferenceEquals(run, _lastRun))
        {
            _lastRun = run;
            if (run.Kind == RunKind.Completed) _runs.Remove(ran); else _runs[ran] = run;
            if (run.Kind == RunKind.Failed) _failedRun = run;          // said at the top until the shopkeeper has read it
        }
        if (s.Queue is { } q)
        {
            foreach (var gone in _runs.Keys.Where(id => !q.Jobs.Any(j => j.JobId == id)).ToList()) _runs.Remove(gone);
            foreach (var id in _busy.Where(b => b.Value is { } sent && sent < q.At).Select(b => b.Key).ToList()) _busy.Remove(id);   // the queue now shows the answer
            if (_confirmRetry is { } c && !q.Jobs.Any(j => j.JobId == c && j.Status == JobStatus.NeedsAttention)) _confirmRetry = null;
            // every refresh looks again for requests that need attention: a job that was stuck can print by itself meanwhile
            var attention = q.Jobs.Where(j => j.Status == JobStatus.NeedsAttention).Select(j => j.JobId).ToHashSet();
            foreach (var id in _queueLook.Keys.Where(id => !attention.Contains(id)).ToList()) { _queueLook.Remove(id); _leftByItself.Remove(id); }
            foreach (var id in attention) _ = LookInQueueAsync(id);
            Alert(_alerts.Next(q.Jobs, DateTimeOffset.UtcNow));
            _preview?.JobChanged(q.Jobs.FirstOrDefault(j => j.JobId == _preview.JobId));
        }
        Render();
    }

    // ---------------------------------------------------------------- getting noticed
    private void Alert(Alert a)
    {
        if (!_live || a.Kind == AlertKind.None) return;
        if (_settings.SoundOn) Alerts.Chime();
        if (!(InFront?.Invoke() ?? IsActive))
        {
            if (!IsVisible) { ShowActivated = false; WindowState = WindowState.Minimized; Show(); }     // back on the taskbar, without taking the keyboard
            Alerts.Flash(this);
        }
        if (a.Kind == AlertKind.New)
            App.Current.Notify(a.Count == 1 ? $"New print request: {a.FirstDocument}" : $"{a.Count} print requests are waiting for you");
    }

    // ---------------------------------------------------------------- printer and print program health
    private async Task RefreshHealthAsync()
    {
        if (!_live || _healthBusy || _agent is null) return;
        _healthBusy = true;
        try
        {
            string bw = _settings.BlackWhitePrinter ?? "", colour = _settings.ColorPrinter ?? "";
            var seen = _engineSeen;
            var (read, programOk) = (ReadPrinter, PrintProgramOk);
            var (health, engine) = await Task.Run(() =>
            {
                if (programOk is not null) return (new Health(bw == "" ? null : read(bw), colour == "" ? null : read(colour), programOk()), seen ?? default);
                // hashing the print program is the costly part: only again when the file itself has changed
                var f = new FileInfo(SumatraPath);
                long length = f.Exists ? f.Length : -1; DateTime written = f.Exists ? f.LastWriteTimeUtc : default;
                bool ok = seen is { } s && s.Length == length && s.Written == written ? s.Ok : SumatraEngine.IsGenuinePortable(SumatraPath);
                return (new Health(bw == "" ? null : read(bw), colour == "" ? null : read(colour), ok), (length, written, ok));
            });
            _engineSeen = engine;
            if (health != _health) { _health = health; Render(); }
        }
        catch (Exception e) { App.Log("health check: " + SafeText.Describe(e)); }
        finally { _healthBusy = false; }
    }

    internal void SetHealth(Health h) { _health = h; Render(); }

    // ---------------------------------------------------------------- time
    /// <summary>The server's clock, carried forward: waiting and expiry times stay right when this PC's clock is wrong.</summary>
    private DateTimeOffset ServerNow() => _state.Queue is { ServerNow: { } server } q ? server + (Clock() - q.At) : Clock();

    private void Tick()
    {
        if (_pairing)
        {
            if (_pairExpires == default) return;
            var left = _pairExpires - DateTimeOffset.UtcNow; if (left < TimeSpan.Zero) left = TimeSpan.Zero;
            PairNote.Text = (_pairOffline ? "No internet connection. Trying again by itself. " : "Waiting for you to type the code. ") + $"It works for {(int)left.TotalMinutes}:{left.Seconds:00} more.";
            return;
        }
        var now = ServerNow();
        foreach (var e in _cardEntries.Values) e.Live?.Invoke(now);
        if (_notice is not null && Clock() - _noticeAt > TimeSpan.FromSeconds(20)) { _notice = null; Render(); }
        foreach (var id in _busy.Where(b => b.Value is { } sent && Clock() - sent > TimeSpan.FromSeconds(30)).Select(b => b.Key).ToList()) { _busy.Remove(id); Render(); }
        if (_live && _state.Queue is { } q) Alert(_alerts.Next(q.Jobs, DateTimeOffset.UtcNow));
    }

    // ---------------------------------------------------------------- keyed lists: change only what changed
    private sealed class Entry { public required Border Root; public string Sig = ""; public Action<DateTimeOffset>? Live; public bool Leaving; }
    private sealed record Wanted(string Key, string Sig, Func<(UIElement Content, Action<DateTimeOffset>? Live)> Build);
    private readonly Dictionary<string, Entry> _cardEntries = new(), _bannerEntries = new();

    private void SyncList(Panel panel, Dictionary<string, Entry> map, IReadOnlyList<Wanted> wanted, bool animate)
    {
        var keep = wanted.Select(w => w.Key).ToHashSet();
        foreach (var (key, old) in map.Where(m => !keep.Contains(m.Key) && !m.Value.Leaving).ToList())
        {
            old.Leaving = true; old.Root.Tag = "leaving";
            void Gone() { panel.Children.Remove(old.Root); if (map.TryGetValue(key, out var cur) && ReferenceEquals(cur, old)) map.Remove(key); }
            if (animate) Motion.Leave(old.Root, Gone); else Gone();
        }
        int at = 0; bool moved = false;
        foreach (var w in wanted)
        {
            map.TryGetValue(w.Key, out var e);
            if (e is null || e.Leaving)
            {
                var (content, live) = w.Build();
                e = new Entry { Root = new Border { Child = content }, Sig = w.Sig, Live = live };
                map[w.Key] = e; moved = true;
                if (animate) Motion.Enter(e.Root);
            }
            else if (e.Sig != w.Sig)
            {
                var (content, live) = w.Build();
                e.Root.Child = content; e.Sig = w.Sig; e.Live = live;
            }
            while (at < panel.Children.Count && panel.Children[at] is Border { Tag: "leaving" }) at++;
            if (at >= panel.Children.Count || !ReferenceEquals(panel.Children[at], e.Root))
            {
                if (panel.Children.Contains(e.Root)) { panel.Children.Remove(e.Root); moved = true; }
                panel.Children.Insert(Math.Min(at, panel.Children.Count), e.Root);
            }
            at++;
        }
        if (moved && ReferenceEquals(panel, Cards)) _shiftedAt = Clock();
    }

    // ---------------------------------------------------------------- the screen
    private bool Offline => !_state.Online;

    private void Render()
    {
        if (_creds is null) return;
        var s = _state;
        var jobs = s.Queue?.Jobs ?? Array.Empty<JobSummary>();
        // The list from the server can be up to one poll old. What this PC is doing right now is known at once: the
        // request it is printing is shown as printing, not as "approved, waiting for the printer" for ten more seconds.
        if (s.Current is { JobId: { } working } && jobs.Any(j => j.JobId == working && j.Status == JobStatus.Approved))
            jobs = jobs.Select(j => j.JobId == working && j.Status == JobStatus.Approved ? j with { Status = JobStatus.Printing } : j).ToList();
        var now = ServerNow();

        if (s.Queue is { } q && q.ShopName.Length > 0) ShopTitle.Text = q.ShopName;
        var printer = _settings.BlackWhitePrinter;
        ShopSub.Text = $"Shop code {_creds.ShopCode}" + (string.IsNullOrEmpty(printer) ? "" : $"   ·   Printer: {printer}");
        if (s.Queue is null && !s.Online && s.LastPollAt is null && s.Problem is null) SetStatus(null, "Connecting…");
        else SetStatus(s.Online, s.Online ? "Connected" : "No internet");

        SyncList(Banners, _bannerEntries, WantedBanners(s), animate: true);

        // needs attention first, then what is printing, then what waits for an answer (oldest first, so nothing is forgotten
        // and a new request never pushes the card under the pointer)
        var attention = jobs.Where(j => j.Status == JobStatus.NeedsAttention).OrderBy(j => j.CreatedAt).ToList();
        var printing = jobs.Where(j => j.Status is JobStatus.Printing or JobStatus.Approved).OrderBy(j => j.Status == JobStatus.Printing ? 0 : 1).ThenBy(j => j.CreatedAt).ToList();
        var waiting = jobs.Where(j => j.Status == JobStatus.AwaitingApproval).OrderBy(j => j.CreatedAt).ToList();
        var wanted = new List<Wanted>();
        void Section(string key, string title, string colour, List<JobSummary> list)
        {
            if (list.Count == 0) return;
            wanted.Add(new("h:" + key, title, () => (new TextBlock { Text = title, Style = Ui.Res<Style>("Eyebrow"), Foreground = Ui.Brush(colour), FontSize = 12, Margin = new Thickness(2, 4, 0, 8) }, null)));
            foreach (var j in list)
            {
                bool busy = _busy.ContainsKey(j.JobId);
                string? block = Block(j, s);
                var stage = s.Current is { } c && c.JobId == j.JobId ? c.Stage : Stage.Idle;
                string? caution = j.Status == JobStatus.AwaitingApproval ? Caution(j) : null;
                var why = _runs.GetValueOrDefault(j.JobId);
                var sig = $"{j.Status}|{busy}|{_confirmRetry == j.JobId}|{block}|{Offline}|{stage}|{j.DocumentName}|{j.AmountPaise}|{j.AttemptCount}|{j.ApprovalExpiresAt}|{caution}|{why?.Reason}|{why?.Detail}|{(_queueLook.TryGetValue(j.JobId, out var look) ? look : null)}|{_leftByItself.Contains(j.JobId)}|{(_confirmRetry == j.JobId ? _retryStep : null)}";
                wanted.Add(new(j.JobId.ToString(), sig, () => JobCard(j, busy, block, stage, caution)));
            }
        }
        Section("attention", attention.Count == 1 ? "NEEDS YOUR ATTENTION" : $"NEEDS YOUR ATTENTION  ·  {attention.Count}", "Err", attention);
        Section("printing", printing.Any(j => j.Status == JobStatus.Printing) ? "PRINTING NOW" : "APPROVED", "Brand", printing);
        Section("waiting", waiting.Count == 1 ? "WAITING FOR YOU" : $"WAITING FOR YOU  ·  {waiting.Count}", "Muted", waiting);
        SyncList(Cards, _cardEntries, wanted, animate: true);
        foreach (var e in _cardEntries.Values) e.Live?.Invoke(now);

        bool empty = wanted.Count == 0;
        EmptyState.Visibility = empty ? Visibility.Visible : Visibility.Collapsed;
        if (empty) EmptyNote.Text = s.Queue is null && Offline
            ? "Requests will show here as soon as AutoPrint can connect."
            : $"New ones appear here by themselves{(_settings.SoundOn ? ", with a sound" : "")}.\nYour customers send files to shop code {_creds.ShopCode}.";
        TabRequests.Content = waiting.Count + attention.Count > 0 ? $"Requests  ·  {waiting.Count + attention.Count}" : "Requests";
        if (FinishedPane.IsVisible) RenderFinished();
    }

    private void SetStatus(bool? online, string text)
    {
        StatusText.Text = text;
        StatusText.Foreground = Ui.Brush(online switch { true => "Ok", false => "Warn", _ => "Muted" });
        Motion.Colour(_dot, ((SolidColorBrush)Ui.Brush(online switch { true => "Ok", false => "Warn", _ => "Line" })).Color);
    }

    /// <summary>Why this request cannot be approved right now, or null. Only things that are certain block: no printer
    /// chosen, a printer that is gone, a print program or print record that is unusable. "Offline" according to
    /// Windows never blocks; drivers get that wrong.</summary>
    private string? Block(JobSummary j, AgentState s)
    {
        if (s.CannotPrint is not null || _health is { EngineOk: false }) return "This computer cannot print right now. See the message at the top.";
        if (string.IsNullOrEmpty(_settings.PrinterFor(j.Color))) return "Choose a printer first (Settings).";
        return HealthFor(j) is { Exists: false } ? "The printer for this request is not on this computer any more. Choose a printer in Settings." : null;
    }

    private PrinterHealth? HealthFor(JobSummary j) => j.Color && !string.IsNullOrEmpty(_settings.ColorPrinter) ? _health?.Colour : _health?.Bw;

    /// <summary>A warning that does not stop the shopkeeper: the printer this request would go to makes no paper.</summary>
    private string? Caution(JobSummary j) => HealthFor(j) is { Exists: true, IsVirtual: true } h
        ? "The chosen printer makes a file, not paper. See the message at the top."
        : null;

    /// <summary>Why a print run ended as it did, in plain words, knowing what kind of printer it was sent to.</summary>
    private FailureText Words(RunResult run)
    {
        var h = new[] { _health?.Bw, _health?.Colour }.FirstOrDefault(x => x is not null && x.Name == run.Printer);
        return FailureWords.For(run.Reason, run.Detail, h?.IsVirtual == true, h?.Prompts == true);
    }

    private List<Wanted> WantedBanners(AgentState s)
    {
        var list = new List<Wanted>();
        void Add(string key, string kind, string text, string? button = null, Action? click = null) =>
            list.Add(new(key, kind + text + button, () => (Banner(kind, text, button, click), null)));

        if (Offline && (s.Problem is not null || s.LastPollAt is not null))
            Add("offline", "Warn", "No internet connection. New requests will arrive by themselves when it is back. "
                + (s.LastPollAt is { } at ? $"Last contact: {at.ToLocalTime():h:mm tt}." : "AutoPrint has not been able to connect yet."), "Try now", () => _agent?.Wake());
        else if (s.Online && s.Problem is not null)
            Add("problem", "Warn", "AutoPrint had a problem talking to its server. It is trying again by itself.");

        if (s.CannotPrint is { } cannot) Add("record", "Err", cannot);
        if (_health is { EngineOk: false })
            Add("engine", "Err", "The part of AutoPrint that sends documents to the printer is missing or damaged (antivirus may have removed it). Nothing can be printed until AutoPrint is installed again.");

        if (string.IsNullOrEmpty(_settings.BlackWhitePrinter))
            Add("noprinter", "Warn", "No printer is chosen yet. Choose your printer before you approve requests.", "Choose printer", () => OnSettings(this, new RoutedEventArgs()));
        foreach (var (h, what) in new[] { (_health?.Bw, "printer"), (_health?.Colour, "colour printer") })
        {
            if (h is null || h.Fine) continue;
            if (!h.Exists)
                Add("p:" + what, "Err", $"The {what} “{h.Name}” is not installed on this computer any more. Requests for it cannot be approved until you choose a printer.", "Choose printer", () => OnSettings(this, new RoutedEventArgs()));
            else if (h.IsVirtual)
                Add("p:" + what, "Warn", PrinterCatalog.Warning(h.Name, true, h.Prompts) + " Choose your real printer for customer prints.", "Choose printer", () => OnSettings(this, new RoutedEventArgs()));
            else
                Add("p:" + what, "Warn", $"Windows says the {what} “{h.Name}” " + (h.Paused ? "is paused. Resume it in Windows printer settings."
                    : h.Offline ? "is offline. Check that it is switched on and connected." : h.Trouble + ".") + " You can still approve; check the printer first.");
        }
        if (_failedRun is { JobId: { } failed } run)
        {
            var job = s.Queue?.Jobs.FirstOrDefault(j => j.JobId == failed);
            var f = Words(run);
            Add("run", "Err", (job is null ? "A request was not printed. " : $"Order {job.OrderShortCode} ({job.DocumentName}) was not printed. ") + f.Both,
                "OK", () => { _failedRun = null; Render(); });
        }
        if (_notice is { } n) Add("notice", "Info", n, "OK", () => { _notice = null; Render(); });
        return list;
    }

    private static UIElement Banner(string kind, string text, string? button, Action? click)
    {
        var (soft, line, ink, glyph) = kind switch { "Err" => ("ErrSoft", "ErrLine", "Err", Ui.Warning), "Warn" => ("WarnSoft", "WarnLine", "Warn", Ui.Warning), _ => ("BrandSoft", "BrandLine", "Brand", Ui.Info) };
        var row = new DockPanel();
        var icon = Ui.Icon(glyph, ink); icon.Margin = new Thickness(0, 2, 10, 0); icon.VerticalAlignment = VerticalAlignment.Top;
        row.Children.Add(icon);
        if (button is not null)
        {
            var b = Ui.B(button); b.Margin = new Thickness(14, 0, 0, 0); b.VerticalAlignment = VerticalAlignment.Center; b.MinHeight = 32;
            b.Click += (_, _) => click?.Invoke();
            DockPanel.SetDock(b, Dock.Right); row.Children.Add(b);
        }
        var t = Ui.T(text); t.VerticalAlignment = VerticalAlignment.Center;
        row.Children.Add(t);
        return new Border { Style = Ui.Res<Style>("BannerBox"), Background = Ui.Brush(soft), BorderBrush = Ui.Brush(line), Child = row };
    }

    private void Notice(string text) { _notice = text; _noticeAt = Clock(); Render(); }

    // ---------------------------------------------------------------- one request
    private (UIElement, Action<DateTimeOffset>?) JobCard(JobSummary j, bool busy, string? block, Stage stage, string? caution = null)
    {
        var body = new StackPanel();
        Facts? timing = null; TextBlock? waited = null, expiry = null;
        if (j.Status == JobStatus.AwaitingApproval) { timing = new Facts(); waited = timing.Add("", "Soft"); expiry = timing.Add("", "Soft"); }
        body.Children.Add(Head(j, timing));
        Action<DateTimeOffset>? live = null;
        string border = "Line";

        switch (j.Status)
        {
            case JobStatus.AwaitingApproval:
                live = now =>
                {
                    bool soon = JobText.ExpiresSoon(j, now);
                    string wait = JobText.Waiting(j, now); string? ends = JobText.Expiry(j, now);
                    if (waited!.Text != wait) waited.Text = wait;                    // a tick that changes nothing lays out nothing
                    if (expiry!.Text != (ends ?? "")) { expiry.Text = ends ?? ""; expiry.Visibility = ends is null ? Visibility.Collapsed : Visibility.Visible; }
                    var ink = Ui.Brush(soon ? "Warn" : "Muted"); var weight = soon ? FontWeights.SemiBold : FontWeights.Normal;
                    if (!ReferenceEquals(expiry.Foreground, ink)) { waited.Foreground = expiry.Foreground = ink; waited.FontWeight = expiry.FontWeight = weight; timing!.Dot = ink; }
                };
                var buttons = new StackPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Right, Margin = new Thickness(0, 12, 0, 0) };
                bool can = !busy && !Offline;
                buttons.Children.Add(AnswerButton("Reject", "Danger", can, j, guard: true, () => _api!.RejectAsync(j.JobId, null, _cts.Token)));
                var preview = Ui.B("Preview"); preview.Margin = new Thickness(8, 0, 8, 0); preview.IsEnabled = can; preview.Click += (_, _) => OpenPreview(j, block);
                buttons.Children.Add(preview);
                buttons.Children.Add(AnswerButton("Approve and print", "Primary", can && block is null, j, guard: true, () => _api!.ApproveAsync(j.JobId, _cts.Token)));
                // why a button is switched off is said in words, on its own line, right above the buttons
                if ((busy ? "Sending your answer…" : Offline ? "No internet. You can answer when it is back." : block ?? caution) is { } why)
                {
                    var note = Ui.T(why, "Soft", busy || Offline ? null : block is not null ? "Err" : "Warn"); note.TextAlignment = TextAlignment.Right; note.Margin = new Thickness(0, 12, 0, -4);
                    body.Children.Add(note);
                }
                body.Children.Add(buttons);
                break;

            case JobStatus.Printing:
                border = "BrandLine";
                var doing = Ui.T(stage switch { Stage.Claimed or Stage.Downloading => "Getting the file…", Stage.Printing => "Sending it to the printer…", Stage.Reporting => "Finishing…", _ => "The printer is working on it…" }, "Body", "Brand");
                doing.FontWeight = FontWeights.SemiBold; doing.Margin = new Thickness(0, 14, 0, 0);
                body.Children.Add(doing);
                body.Children.Add(Motion.Progress());
                break;

            case JobStatus.Approved:
                var next = Ui.T(block ?? "Approved. It prints as soon as the printer is free.", "Soft", block is null ? null : "Err"); next.Margin = new Thickness(0, 12, 0, 0);
                body.Children.Add(next);
                break;

            case JobStatus.NeedsAttention:
                border = "ErrLine";
                body.Children.Add(new Border { Height = 1, Background = Ui.Brush("Line"), Margin = new Thickness(0, 14, 0, 12) });
                body.Children.Add(_confirmRetry == j.JobId ? ConfirmAgain(j, busy) : Choices(j, busy));
                break;
        }
        var card = new Border { Style = Ui.Res<Style>("CardBox"), BorderBrush = Ui.Brush(border), Child = body };
        return (card, live);
    }

    /// <summary>The order code and the amount carry the card: they are what the customer says and what the shopkeeper collects.</summary>
    private static UIElement Head(JobSummary j, Facts? timing)
    {
        var grid = new Grid();
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        grid.ColumnDefinitions.Add(new ColumnDefinition());
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });

        var code = new StackPanel { Margin = new Thickness(0, 0, 22, 0), MinWidth = 96 };
        code.Children.Add(Ui.T("ORDER CODE", "Eyebrow"));
        code.Children.Add(Ui.T(j.OrderShortCode, "OrderCode"));
        grid.Children.Add(code);

        var mid = new StackPanel { VerticalAlignment = VerticalAlignment.Center };
        var name = Ui.T(j.DocumentName, "H2"); name.TextTrimming = TextTrimming.CharacterEllipsis; name.ToolTip = j.DocumentName;
        mid.Children.Add(name);
        // each fact is one piece; a narrow window moves whole facts to the next line, never half of one, and never a stray dot
        var detail = new Facts { Margin = new Thickness(0, 3, 0, 0) };
        detail.Add(JobText.Pages(j)); detail.Add(JobText.Plural(j.Copies, "copy", "copies"));
        var colour = detail.Add(JobText.Colour(j)); if (j.Color) { colour.Foreground = Ui.Brush("Brand"); colour.FontWeight = FontWeights.SemiBold; }
        detail.Add(JobText.SidesChoice(j));
        mid.Children.Add(detail);
        var paper = Ui.T(JobText.PaperLine(j), "Soft"); paper.Margin = new Thickness(0, 2, 0, 0);
        mid.Children.Add(paper);
        if (timing is not null) { timing.Margin = new Thickness(0, 2, 0, 0); mid.Children.Add(timing); }
        Grid.SetColumn(mid, 1); grid.Children.Add(mid);

        var pay = new StackPanel { Margin = new Thickness(22, 0, 0, 0) };
        var label = Ui.T("TO COLLECT", "Eyebrow"); label.HorizontalAlignment = HorizontalAlignment.Right;
        pay.Children.Add(label);
        pay.Children.Add(Ui.T(JobText.Money(j.AmountPaise), "Amount"));
        Grid.SetColumn(pay, 2); grid.Children.Add(pay);
        return grid;
    }

    private UIElement Choices(JobSummary j, bool busy)
    {
        var box = new StackPanel();
        // when this PC ran the print itself it knows what it saw; after a restart, or for another PC's print, only the general words are true
        var known = _runs.TryGetValue(j.JobId, out var run) ? Words(run) : null;
        var lead = Ui.T(known?.What ?? "AutoPrint could not confirm that this came out of the printer. Look at the printer and its paper tray, then choose one.");
        lead.FontWeight = FontWeights.SemiBold;
        box.Children.Add(lead);
        if (known is not null) { var check = Ui.T(known.Check); check.Margin = new Thickness(0, 4, 0, 0); box.Children.Add(check); }
        if (QueueLine(j.JobId) is { } inQueue)
        {
            var t = Ui.T(inQueue.Text, "Body", inQueue.Waiting ? "Warn" : null); t.FontWeight = FontWeights.SemiBold;
            box.Children.Add(new Border { Background = Ui.Brush(inQueue.Waiting ? "WarnSoft" : "BrandSoft"), BorderBrush = Ui.Brush(inQueue.Waiting ? "WarnLine" : "BrandLine"), BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(10), Padding = new Thickness(12, 9, 12, 9), Margin = new Thickness(0, 10, 0, 0), Child = t });
        }
        if (j.AttemptCount > 1) { var again = Ui.T($"This request has already been sent to the printer {j.AttemptCount} times.", "Soft", "Err"); again.Margin = new Thickness(0, 4, 0, 0); box.Children.Add(again); }
        var three = new UniformGrid { Columns = 3, Margin = new Thickness(-6, 12, -6, 0) };
        bool can = !busy && !Offline;
        void Choice(string text, string caption, Button b)
        {
            var col = new StackPanel { Margin = new Thickness(6, 0, 6, 0) };
            b.HorizontalAlignment = HorizontalAlignment.Stretch; col.Children.Add(b);
            var c = Ui.T(caption, "Soft"); c.Margin = new Thickness(2, 6, 2, 0); col.Children.Add(c);
            three.Children.Add(col);
        }
        Choice("It printed", "The pages are there. The customer collects them and pays.",
            AnswerButton("It printed", null, can, j, guard: true, () => _api!.ResolveAsync(j.JobId, Resolution.Completed, null, _cts.Token)));
        Choice("It did not print", "Nothing usable came out. The request is closed and the customer is told it failed.",
            AnswerButton("It did not print", null, can, j, guard: true, () => _api!.ResolveAsync(j.JobId, Resolution.Failed, null, _cts.Token)));
        var retry = Ui.B("Print again"); retry.IsEnabled = can && Block(j, _state) is null;
        retry.Click += (_, _) => { if (!Shifted()) _ = AskPrintAgainAsync(j.JobId); };
        Choice("Print again", "Sends the whole document to the printer one more time. You are asked to confirm.", retry);
        box.Children.Add(three);
        if (busy || Offline) { var n = Ui.T(busy ? "Sending your answer…" : "No internet. You can answer when it is back.", "Soft"); n.Margin = new Thickness(0, 10, 0, 0); box.Children.Add(n); }
        return box;
    }

    /// <summary>What the Windows print queue shows for a request that needs attention, in the words the card uses.</summary>
    private (string Text, bool Waiting)? QueueLine(Guid jobId) =>
        _queueLook.TryGetValue(jobId, out var look) && look == QueueLook.Waiting
            ? ("This document is still waiting in the Windows print queue. It will print when the printer is ready.", true)
        : _leftByItself.Contains(jobId)
            ? ("This document was waiting in the Windows print queue and has now left it by itself. It has probably printed: look in the tray before you choose.", false)
        : null;

    /// <summary>Looks in the Windows print queue for this request's own job, off the window's thread. A request whose job
    /// was waiting and is now gone, without anyone removing it, is remembered as "left by itself".</summary>
    private async Task LookInQueueAsync(Guid jobId)
    {
        if (_waitingJobs is not { } jobs || !_lookingAt.Add(jobId)) return;
        try
        {
            var found = await Task.Run(() => jobs.Look(jobId));
            if (!ReferenceEquals(jobs, _waitingJobs)) return;
            bool was = _queueLook.TryGetValue(jobId, out var before);
            if (was && before == found) return;
            if (was && before == QueueLook.Waiting && found == QueueLook.NotThere) _leftByItself.Add(jobId);
            if (found == QueueLook.Waiting) _leftByItself.Remove(jobId);
            _queueLook[jobId] = found;
            Render();
        }
        catch (Exception e) { App.Log("queue look: " + SafeText.Describe(e)); }
        finally { _lookingAt.Remove(jobId); }
    }

    /// <summary>"Print again" was pressed: look in the queue now, at the moment of decision, before anything is offered.</summary>
    private async Task AskPrintAgainAsync(Guid jobId)
    {
        _confirmRetry = jobId; _retryStep = RetryStep.Looking;
        Render();
        for (int i = 0; i < 40 && _lookingAt.Contains(jobId); i++) await Task.Delay(50);      // a look already on its way finishes first
        await LookInQueueAsync(jobId);
        if (_confirmRetry == jobId && _retryStep == RetryStep.Looking) { _retryStep = RetryStep.Confirm; Render(); }
    }

    /// <summary>Removes the waiting job and, only once a look has confirmed that it is gone, starts the new attempt.
    /// If it had already left by itself nothing is printed again: it has probably come out, and the shopkeeper is told.</summary>
    private async Task RemoveThenPrintAgainAsync(JobSummary j)
    {
        if (_waitingJobs is not { } jobs || _confirmRetry != j.JobId || _retryStep == RetryStep.Removing) return;
        _retryStep = RetryStep.Removing;
        Render();
        RemoveOutcome result;
        try { result = await Task.Run(() => jobs.RemoveAsync(j.JobId, _cts.Token)); }
        catch (OperationCanceledException) { return; }
        catch (Exception e) { App.Log("remove waiting job: " + SafeText.Describe(e)); result = RemoveOutcome.Unreadable; }
        if (_confirmRetry != j.JobId || !ReferenceEquals(jobs, _waitingJobs)) return;
        switch (result)
        {
            case RemoveOutcome.Removed:
                _queueLook[j.JobId] = QueueLook.NotThere;
                await Answer(j.JobId, () => _api!.ResolveAsync(j.JobId, Resolution.Retry, null, _cts.Token));
                break;
            case RemoveOutcome.GoneByItself:
                _queueLook[j.JobId] = QueueLook.NotThere; _leftByItself.Add(j.JobId); _confirmRetry = null;
                Render();
                break;
            default:
                _retryStep = RetryStep.RemoveFailed;
                Render();
                break;
        }
    }

    private UIElement ConfirmAgain(JobSummary j, bool busy)
    {
        var box = new StackPanel();
        var look = _queueLook.TryGetValue(j.JobId, out var l) ? l : QueueLook.NoRecord;
        bool waiting = look == QueueLook.Waiting, can = !busy && !Offline;
        var (title, text) = _retryStep switch
        {
            RetryStep.Looking => ("Looking in the Windows print queue…", "One moment."),
            RetryStep.Removing => ("Removing the waiting job…", "Nothing new is sent to the printer until it is gone."),
            RetryStep.RemoveFailed => ("Windows could not remove the waiting job",
                "Nothing new was sent to the printer. The old job is still in the Windows print queue and will print when the printer is ready. You can cancel it yourself in the Windows print queue, then try again."),
            _ when waiting => ("This document is still waiting in the Windows print queue",
                "It will print when the printer is ready. If you print it again now, it can come out twice. Remove the waiting job first."),
            _ => ("Print it again?", (_leftByItself.Contains(j.JobId) ? "This document was waiting in the Windows print queue and has now left it by itself, so it has probably printed already. " : "") + $"All {JobText.Plural(JobText.Sides(j), "side", "sides")} will be sent to the printer one more time. First make sure the pages are not already in the tray: this really prints again."
                + (look == QueueLook.Unreadable ? " AutoPrint could not look in the Windows print queue: if this document is still listed there, cancel it first." : "")),
        };
        var q = Ui.T(title); q.FontWeight = FontWeights.SemiBold; q.FontSize = 16;
        box.Children.Add(q);
        var t = Ui.T(text); t.Margin = new Thickness(0, 4, 0, 12);
        box.Children.Add(t);
        var row = new WrapPanel();
        void Put(Button b) { b.Margin = new Thickness(0, 0, 8, 6); row.Children.Add(b); }
        Button Do(string label, string? style, Action act) { var b = Ui.B(label, style); b.IsEnabled = can; b.Click += (_, _) => act(); return b; }
        Func<Task> again = () => _api!.ResolveAsync(j.JobId, Resolution.Retry, null, _cts.Token);
        if (_retryStep is RetryStep.Confirm or RetryStep.RemoveFailed)
        {
            if (_retryStep == RetryStep.RemoveFailed)
            {
                Put(Do("Try to remove it again", "Primary", () => _ = RemoveThenPrintAgainAsync(j)));
                Put(AnswerButton("Print again anyway, both may come out", null, can, j, guard: false, again));
            }
            else if (waiting)
            {
                Put(Do("Remove it, then print again", "Primary", () => _ = RemoveThenPrintAgainAsync(j)));
                Put(AnswerButton("Keep it and print again too", null, can, j, guard: false, again));
            }
            else Put(AnswerButton("Yes, print it again", "Primary", can, j, guard: false, again));
        }
        var no = Ui.B("No, go back"); no.Margin = new Thickness(0, 0, 0, 6); no.IsEnabled = _retryStep != RetryStep.Removing;
        no.Click += (_, _) => { _confirmRetry = null; Render(); };
        row.Children.Add(no);
        box.Children.Add(row);
        return new Border { Background = Ui.Brush("WarnSoft"), BorderBrush = Ui.Brush("WarnLine"), BorderThickness = new Thickness(1), CornerRadius = new CornerRadius(12), Padding = new Thickness(16, 14, 16, 8), Child = box };
    }

    /// <summary>True for a moment after the cards have moved: a click that lands then was aimed at whatever was there before.</summary>
    private bool Shifted() => Clock() - _shiftedAt < TimeSpan.FromMilliseconds(450);

    private Button AnswerButton(string text, string? style, bool enabled, JobSummary j, bool guard, Func<Task> call)
    {
        var b = Ui.B(text, style); b.IsEnabled = enabled;
        b.Click += (_, _) => { if (!(guard && Shifted())) _ = Answer(j.JobId, call); };
        return b;
    }

    /// <summary>Sends one answer for one request. A second click cannot send a second answer: the request stays
    /// "busy" from the first click until the queue shows the result.</summary>
    private async Task Answer(Guid jobId, Func<Task> call)
    {
        if (_api is null || _busy.ContainsKey(jobId)) return;
        _busy[jobId] = null;
        Render();
        try { await call(); _busy[jobId] = DateTimeOffset.UtcNow; }
        catch (Exception e)
        {
            _busy.Remove(jobId);
            if (e is OperationCanceledException) return;
            if (e is not (ServerUnreachableException or ApiRejectedException)) App.Log("answer: " + SafeText.Describe(e));
            Notice(e switch
            {
                ServerUnreachableException => "No internet connection, so that did not go through. Nothing was changed. Try again in a moment.",
                ApiRejectedException { Code: "not_actionable" or "job_not_found" } => "That request has changed: the customer may have cancelled it, or it was already answered. Nothing was changed.",
                ApiRejectedException { Code: "rate_limited" } => "Too many clicks in a short time. Wait a moment and try again.",
                ApiRejectedException { Code: "contract_mismatch" } => "This version of AutoPrint is too old. Install the new version.",
                ApiRejectedException x => x.Message,
                _ => "That did not work. Try again.",
            });
        }
        finally { if (_confirmRetry == jobId) _confirmRetry = null; _agent?.Wake(); Render(); }
    }

    private void OpenPreview(JobSummary j, string? block)
    {
        if (_api is null || _preview is not null) return;
        _preview = new PreviewWindow(j, _api, App.Http, block) { Owner = this };
        if (Quiet) { _preview.ShowActivated = false; _preview.ShowInTaskbar = false; }
        try { _preview.ShowDialog(); }
        finally
        {
            var choice = _preview.Choice; _preview = null;
            if (choice == PreviewChoice.Approve) _ = Answer(j.JobId, () => _api!.ApproveAsync(j.JobId, _cts.Token));
            else if (choice == PreviewChoice.Reject) _ = Answer(j.JobId, () => _api!.RejectAsync(j.JobId, null, _cts.Token));
        }
    }

    // ---------------------------------------------------------------- finished: a lookup list, not a ledger
    private void OnTab(object sender, RoutedEventArgs e)
    {
        if (FinishedPane is null) return;                          // raised once while the window is still being built
        bool finished = TabFinished.IsChecked == true;
        RequestsPane.Visibility = finished ? Visibility.Collapsed : Visibility.Visible;
        FinishedPane.Visibility = finished ? Visibility.Visible : Visibility.Collapsed;
        Motion.Fade(finished ? FinishedPane : RequestsPane);
        if (finished) { _finishedShown = ""; RenderFinished(); }
    }

    private void OnSearch(object sender, TextChangedEventArgs e)
    {
        bool typed = SearchBox.Text.Length > 0;
        SearchHint.Visibility = typed ? Visibility.Collapsed : Visibility.Visible;
        SearchClear.Visibility = typed ? Visibility.Visible : Visibility.Collapsed;
        RenderFinished();
    }

    private void OnSearchClear(object sender, RoutedEventArgs e) { SearchBox.Clear(); SearchBox.Focus(); }

    private void RenderFinished()
    {
        var query = SearchBox.Text.Trim();
        var jobs = _state.Queue?.Jobs ?? Array.Empty<JobSummary>();
        // looking for a code finds it wherever the request is, so "where is my print?" always has an answer
        var rows = jobs.Where(j => query.Length > 0 ? JobText.Matches(j, query) : !JobText.IsActive(j.Status))
                       .OrderByDescending(j => j.CreatedAt).Take(60).ToList();
        var now = ServerNow();
        var sig = query + "|" + now.ToLocalTime().Date.DayOfYear + "|" + string.Join(",", rows.Select(j => $"{j.JobId:N}{(int)j.Status}{_runs.GetValueOrDefault(j.JobId)?.Reason}"));
        if (sig == _finishedShown) return;                         // a poll that changed nothing rebuilds nothing
        _finishedShown = sig;
        FinishedRows.Children.Clear();
        FinishedBox.Visibility = rows.Count == 0 ? Visibility.Collapsed : Visibility.Visible;
        FinishedNote.Text = rows.Count > 0 ? (query.Length > 0 ? $"Orders that match “{query}”." : "Requests that ended in the last 24 hours, newest first. The time is when the customer sent it.")
            : query.Length > 0 ? $"No order matches “{query}” in the last 24 hours. Check the code with the customer."
            : "Nothing has finished in the last 24 hours.";
        for (int i = 0; i < rows.Count; i++)
        {
            var j = rows[i];
            var why = j.Status == JobStatus.Failed && _runs.TryGetValue(j.JobId, out var run) ? Words(run).What : null;
            FinishedRows.Children.Add(FinishedRow(j, now, last: i == rows.Count - 1, why));
        }
    }

    private static UIElement FinishedRow(JobSummary j, DateTimeOffset now, bool last, string? why = null)
    {
        var g = new Grid { Margin = new Thickness(0, 12, 0, 12) };
        g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(92) });
        g.ColumnDefinitions.Add(new ColumnDefinition());
        g.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto, MinWidth = 64 });
        g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(176) });
        var code = Ui.T(j.OrderShortCode, "OrderCode"); code.FontSize = 20; code.VerticalAlignment = VerticalAlignment.Center;
        g.Children.Add(code);

        var mid = new StackPanel { VerticalAlignment = VerticalAlignment.Center };
        var name = Ui.T(j.DocumentName); name.FontWeight = FontWeights.SemiBold; name.TextWrapping = TextWrapping.NoWrap; name.TextTrimming = TextTrimming.CharacterEllipsis; name.ToolTip = j.DocumentName;
        mid.Children.Add(name);
        var when = Ui.T($"{JobText.When(j.CreatedAt, now)}   ·   {JobText.Plural(JobText.Sides(j), "side", "sides")}", "Soft");
        when.TextWrapping = TextWrapping.NoWrap; when.TextTrimming = TextTrimming.CharacterEllipsis;
        mid.Children.Add(when);
        if (why is not null) { var w = Ui.T(why, "Soft"); w.Margin = new Thickness(0, 2, 0, 0); mid.Children.Add(w); }
        Grid.SetColumn(mid, 1); g.Children.Add(mid);

        var amount = Ui.T(JobText.Money(j.AmountPaise)); amount.FontSize = 17; amount.FontWeight = FontWeights.SemiBold; amount.HorizontalAlignment = HorizontalAlignment.Right; amount.VerticalAlignment = VerticalAlignment.Center; amount.Margin = new Thickness(12, 0, 0, 0);
        Grid.SetColumn(amount, 2); g.Children.Add(amount);

        var colour = j.Status switch { JobStatus.Completed => "Ok", JobStatus.Failed or JobStatus.NeedsAttention => "Err", JobStatus.AwaitingApproval or JobStatus.Approved or JobStatus.Printing => "Brand", _ => "Muted" };
        var state = new StackPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Right, VerticalAlignment = VerticalAlignment.Center };
        state.Children.Add(new System.Windows.Shapes.Ellipse { Width = 8, Height = 8, Fill = Ui.Brush(colour), Margin = new Thickness(0, 1, 7, 0), VerticalAlignment = VerticalAlignment.Center });
        state.Children.Add(Ui.T(JobText.State(j.Status), "Body", colour));
        Grid.SetColumn(state, 3); g.Children.Add(state);

        return new Border { BorderBrush = Ui.Brush("Line"), BorderThickness = new Thickness(0, 0, 0, last ? 0 : 1), Child = g };
    }

    // ---------------------------------------------------------------- settings
    private void OnSettings(object sender, RoutedEventArgs e)
    {
        if (OwnedWindows.OfType<SettingsWindow>().Any()) return;
        var w = new SettingsWindow(_settings, SupportInfo()) { Owner = IsVisible ? this : null };
        w.ShowDialog();
        _agent?.Wake(); Render(); _ = RefreshHealthAsync();          // also after Cancel: cheap, and the printer may have changed meanwhile
    }

    internal SupportInfo SupportInfo() => new(_version,
        _creds is null ? "Not connected to a shop yet" : $"{ShopTitle.Text} ({_creds.ShopCode})",
        _creds is null ? "Not connected" : _state.Online ? "Connected" + (_state.LastPollAt is { } at ? $". Last contact {at.ToLocalTime():h:mm:ss tt}" : "")
            : "No internet" + (_state.LastPollAt is { } last ? $". Last contact {last.ToLocalTime():h:mm tt}" : ""));

    // ---------------------------------------------------------------- for the UI self-test (fake data only)
    internal void Demo(DeviceCredentials creds, AgentState state, Health? health, bool finishedTab = false, string search = "", Guid? confirm = null, string? notice = null, Guid? stillQueued = null, bool removeFailed = false, params RunResult[] runs)
    {
        _state = state; _health = health; _confirmRetry = confirm; _notice = notice; _noticeAt = Clock();
        _retryStep = removeFailed ? RetryStep.RemoveFailed : RetryStep.Confirm;
        if (stillQueued is { } queued) _queueLook[queued] = QueueLook.Waiting;
        foreach (var r in runs) { _runs[r.JobId!.Value] = r; if (r.Kind == RunKind.Failed) _failedRun = r; }
        ShowQueue(creds);
        if (finishedTab) { TabFinished.IsChecked = true; SearchBox.Text = search; }
    }

    internal void DemoPairing(string? code, TimeSpan left, bool offline)
    {
        ShowView(View.Pair);
        PairStep3.Text = "Check the computer name (SHOP-PC) and press “Yes, connect it”.";
        PairCode.Text = code ?? "····-····"; PairCode.Opacity = code is null ? 0.35 : 1;
        PairNote.Text = code is null ? "No internet connection. Trying again in 6 s…"
            : (offline ? "No internet connection. Trying again by itself. " : "Waiting for you to type the code. ") + $"It works for {(int)left.TotalMinutes}:{left.Seconds:00} more.";
    }
}

public sealed record SupportInfo(string Version, string Shop, string Connection);

internal static class PrintingParts
{
    /// <summary>Takes the pair the self-test supplies apart in one expression.</summary>
    public static PrintOrchestrator Unpack(this (PrintOrchestrator Orchestrator, ISpoolerObserver Queue) parts, out ISpoolerObserver queue)
    {
        queue = parts.Queue;
        return parts.Orchestrator;
    }
}
