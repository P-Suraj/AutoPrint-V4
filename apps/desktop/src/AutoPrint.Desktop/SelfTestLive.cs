using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Media;
using AutoPrint.Core;
using AutoPrint.Core.Agent;
using AutoPrint.Core.Printing;
using AutoPrint.Core.Shop;

namespace AutoPrint.Desktop;

/// <summary>
/// "--selftest-ui &lt;folder&gt; live": runs the real window through a whole day in about two minutes, against a made-up
/// server that lives inside this process. Pairing, the queue, the alert for new requests, a double-clicked Approve, a
/// finished job, losing and regaining the internet, Reject, a customer cancelling (with the preview open, and in the
/// instant before Approve), a print interrupted by sleep, "Print again" with the old job still in the print queue,
/// opening the app a second time, Quit, and being disconnected by the shop.
///
/// Nothing leaves the process. No network: every request is answered by the made-up server. No real credentials: they
/// are kept in memory. No real printer, print queue or print program: a scripted printer (FakeSpooler) stands in, so
/// nothing can reach paper. No sound and no taskbar flash: both are counted at the last step before Windows would be
/// called. No message box. Its own single-instance name, so a real AutoPrint running on this PC is never signalled.
/// Data only under the output folder.
/// </summary>
internal static partial class SelfTest
{
    private const string LivePrinter = "Self-Test Printer (made up)";

    private sealed class FakeJob
    {
        public Guid Id = Guid.NewGuid();
        public string Code = "", Name = "", Status = "awaiting_approval";
        public int MinutesAgo, Attempts, Handed;
    }

    private sealed class FakeServer : HttpMessageHandler
    {
        public readonly Guid Device = Guid.NewGuid();
        public readonly List<FakeJob> Jobs = [];
        public volatile bool Offline, Revoked, HandOut;
        public int Starts, PairPolls, Polls, OfflinePolls, Requests, Approves, Rejects, Claims, Resolves, StaleAnswers;
        public readonly List<string> Outcomes = [];
        private readonly DateTimeOffset _t0 = DateTimeOffset.UtcNow;
        private readonly object _gate = new();
        private (Guid Attempt, FakeJob Job)? _lease;
        public readonly byte[] Pdf = TestPage.Build("AutoPrint live self-test", "Made-up page. No customer document is used.");

        public FakeJob Add(string code, string name, int minutesAgo)
        {
            var j = new FakeJob { Code = code, Name = name, MinutesAgo = minutesAgo };
            lock (_gate) Jobs.Add(j);
            return j;
        }

        public void Set(FakeJob j, string status) { lock (_gate) j.Status = status; }
        public string StatusOf(FakeJob j) { lock (_gate) return j.Status; }

        /// <summary>What the real server does when a PC stops renewing its lease: the attempt is no longer that PC's
        /// and the job waits for a person.</summary>
        public void ExpireLease() { lock (_gate) { if (_lease is { } l) { l.Job.Status = "needs_attention"; _lease = null; } } }

        private string Json(FakeJob j)
        {
            var created = _t0.AddMinutes(-j.MinutesAgo);
            var expires = j.Status == "awaiting_approval" ? $"\"{created.AddHours(1):O}\"" : "null";
            return $$"""{"job_id":"{{j.Id}}","order_short_code":"{{j.Code}}","document_name":"{{j.Name}}","page_count":1,"copies":2,"color":false,"duplex":false,"page_range":null,"amount_paise":720,"status":"{{j.Status}}","created_at":"{{created:O}}","approval_expires_at":{{expires}},"attempt_count":{{j.Attempts}}}""";
        }

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken ct)
        {
            var path = request.RequestUri!.AbsolutePath;
            if (Offline) { if (path.EndsWith("/v1/agent/jobs")) Interlocked.Increment(ref OfflinePolls); throw new HttpRequestException("made-up network failure"); }
            Interlocked.Increment(ref Requests);
            HttpResponseMessage Reply(string json, HttpStatusCode status = HttpStatusCode.OK)
            {
                var r = new HttpResponseMessage(status) { Content = new StringContent(json, Encoding.UTF8, "application/json") };
                r.Headers.Date = DateTimeOffset.UtcNow;
                return r;
            }
            HttpResponseMessage Refuse(string code) => Reply($$$"""{"error":{"code":"{{{code}}}","message":"Refused by the self-test server."}}""", HttpStatusCode.Conflict);
            HttpResponseMessage Stale() { Interlocked.Increment(ref StaleAnswers); return Refuse("stale_attempt"); }
            FakeJob? JobIn() { lock (_gate) return Jobs.FirstOrDefault(j => path.Contains(j.Id.ToString())); }
            bool Mine() { lock (_gate) return _lease is { } l && path.Contains(l.Attempt.ToString()); }

            if (path.EndsWith("/file")) return new HttpResponseMessage(HttpStatusCode.OK) { Content = new ByteArrayContent(Pdf) };
            if (path.EndsWith("/pair/start")) { Interlocked.Increment(ref Starts); PairPolls = 0; return Reply($$"""{"pair_code":"TEST-CODE","expires_at":"{{DateTimeOffset.UtcNow.AddMinutes(15):O}}"}"""); }
            if (path.EndsWith("/pair/poll"))
            {
                if (Interlocked.Increment(ref PairPolls) < 2 || Revoked) return Reply("""{"status":"pending","device_id":null,"shop_code":null,"shop_name":null}""");
                return Reply($$"""{"status":"approved","device_id":"{{Device}}","shop_code":"TST001","shop_name":"Live Self-Test Shop"}""");
            }
            if (Revoked) return Reply("""{"error":{"code":"unauthorized","message":"This device is not authorised."}}""", HttpStatusCode.Unauthorized);
            if (path.EndsWith("/v1/agent/jobs"))
            {
                Interlocked.Increment(ref Polls);
                string jobs; lock (_gate) jobs = string.Join(",", Jobs.Select(Json));
                return Reply($$"""{"shop_code":"TST001","shop_name":"Live Self-Test Shop","contract_version":1,"jobs":[{{jobs}}]}""");
            }
            if (path.EndsWith("/document"))
                return Reply($$"""{"download_url":"https://selftest.invalid/file","sha256":"{{Convert.ToHexString(SHA256.HashData(Pdf)).ToLowerInvariant()}}","byte_size":{{Pdf.Length}},"page_count":1}""");
            if (path.EndsWith("/approve") || path.EndsWith("/reject"))
            {
                bool approve = path.EndsWith("/approve");
                if (approve) await Task.Delay(400, ct);
                var j = JobIn();
                lock (_gate)
                {
                    if (j is null || j.Status != "awaiting_approval") return Refuse("not_actionable");     // the customer cancelled a moment ago
                    j.Status = approve ? "approved" : "rejected";
                }
                Interlocked.Increment(ref approve ? ref Approves : ref Rejects);
                return Reply($$"""{"job_id":"{{j.Id}}","status":"{{j.Status}}"}""");
            }
            if (path.EndsWith("/resolve"))
            {
                var body = await request.Content!.ReadAsStringAsync(ct);
                var j = JobIn();
                lock (_gate)
                {
                    if (j is null || j.Status != "needs_attention") return Refuse("not_actionable");
                    j.Status = body.Contains("\"retry\"") ? "approved" : body.Contains("\"completed\"") ? "completed" : "failed";
                }
                Interlocked.Increment(ref Resolves);
                return Reply($$"""{"job_id":"{{j.Id}}","status":"{{j.Status}}"}""");
            }
            if (path.EndsWith("/claim"))
            {
                Interlocked.Increment(ref Claims);
                lock (_gate)
                {
                    var j = HandOut && _lease is null ? Jobs.FirstOrDefault(x => x.Status == "approved") : null;
                    if (j is null) return Reply("""{"status":"no_job","job_id":null,"attempt_id":null,"attempt_token":null,"spooler_job_name":null,"lease_expires_at":null,"document":null,"options":null}""");
                    var attempt = Guid.NewGuid();
                    j.Status = "printing"; j.Attempts++; j.Handed++; _lease = (attempt, j);
                    return Reply($$$"""{"status":"claimed","job_id":"{{{j.Id}}}","attempt_id":"{{{attempt}}}","attempt_token":"made-up-token","spooler_job_name":"apjob_{{{attempt:N}}}","lease_expires_at":"{{{DateTimeOffset.UtcNow.AddMinutes(5):O}}}","document":{"download_url":"https://selftest.invalid/file","sha256":"{{{Convert.ToHexString(SHA256.HashData(Pdf)).ToLowerInvariant()}}}","byte_size":{{{Pdf.Length}}},"page_count":1},"options":{"copies":2,"color":false,"duplex":false,"page_range":null}}""");
                }
            }
            if (path.EndsWith("/sent")) return Mine() ? Reply("""{"status":"ok"}""") : Stale();
            if (path.EndsWith("/renew")) return Mine() ? Reply($$"""{"lease_expires_at":"{{DateTimeOffset.UtcNow.AddMinutes(5):O}}"}""") : Stale();
            if (path.EndsWith("/outcome"))
            {
                var body = await request.Content!.ReadAsStringAsync(ct);
                lock (_gate)
                {
                    if (_lease is not { } l || !path.Contains(l.Attempt.ToString())) return Stale();
                    string outcome = body.Contains("\"outcome\":\"completed\"") ? "completed" : body.Contains("\"outcome\":\"failed\"") ? "failed" : "uncertain";
                    l.Job.Status = outcome == "uncertain" ? "needs_attention" : outcome;
                    Outcomes.Add($"{l.Job.Code}:{outcome}"); _lease = null;
                    return Reply($$"""{"job_status":"{{l.Job.Status}}"}""");
                }
            }
            return Reply("""{"error":{"code":"job_not_found","message":"Not part of the self-test."}}""", HttpStatusCode.NotFound);
        }
    }

    /// <summary>Stands where the print program would be. It only hands the request to the scripted printer, after
    /// noting whether the journal already held "about to print" for this very attempt.</summary>
    private sealed class WatchedEngine(FakeSpooler printer, Journal journal, Func<Guid> job) : IPrintEngine
    {
        public readonly List<bool> JournalHadIntentFirst = [];
        public Task<SubmitResult> SubmitAsync(PrintRequest request, CancellationToken ct)
        {
            JournalHadIntentFirst.Add(journal.AttemptsFor(job()).Any(a => a.SpoolerJobName == request.SpoolerJobName && a.State == AttemptState.Intent));
            if (printer.SubmitCount >= 1) printer.Scenario = FakeScenario.Success;       // the first print gets stuck (printer off); a later one goes through
            return printer.SubmitAsync(request, ct);
        }
    }

    private sealed class MadeUpDownloader(byte[] pdf) : IDownloader
    {
        public async Task DownloadAsync(string url, string expectedSha256, long expectedBytes, string path, CancellationToken ct)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            await File.WriteAllBytesAsync(path, pdf, ct);
        }
    }

    private static IEnumerable<T> Inside<T>(DependencyObject root) where T : DependencyObject
    {
        for (int i = 0; i < VisualTreeHelper.GetChildrenCount(root); i++)
        {
            var child = VisualTreeHelper.GetChild(root, i);
            if (child is T t) yield return t;
            foreach (var deeper in Inside<T>(child)) yield return deeper;
        }
    }

    private static List<Button> Buttons(DependencyObject root, string text) => Inside<Button>(root).Where(b => b.Content as string == text).ToList();
    private static bool Says(DependencyObject root, string text) => Inside<TextBlock>(root).Any(t => t.IsVisible && t.Text.Contains(text));
    private static void Click(Button b) => b.RaiseEvent(new RoutedEventArgs(ButtonBase.ClickEvent));

    /// <summary>The card of one request, found by its order code.</summary>
    private static DependencyObject Card(MainWindow w, string code) =>
        w.Cards.Children.OfType<Border>().FirstOrDefault(b => b.Tag as string != "leaving" && Inside<TextBlock>(b).Any(t => t.Text == code)) ?? new Border();

    private static async Task<bool> Until(Func<bool> condition, double seconds)
    {
        var until = DateTime.UtcNow.AddSeconds(seconds);
        while (!condition()) { if (DateTime.UtcNow > until) return false; await Task.Delay(100); }
        return true;
    }

    private static async Task<bool> LiveAsync(App app, string outDir, StringBuilder log)
    {
        bool all = true;
        void Check(string what, bool ok) { all &= ok; log.AppendLine((ok ? "PASS  " : "FAIL  ") + what); }
        async Task Shot(Window w, string name) { await Idle(w); Save(w, Path.Combine(outDir, name + ".png"), 96); }

        var server = new FakeServer();
        var j1 = server.Add("LV01", "First made-up file.pdf", 3);
        var j2 = server.Add("LV02", "Second made-up file.pdf", 1);
        App.Http = new HttpClient(server) { Timeout = TimeSpan.FromSeconds(30) };
        var store = new MemoryCredentialStore();

        // the sound and the flash are counted here, one step before Windows would be asked to make them
        int chimes = 0, flashes = 0;
        Alerts.Probe = what => { if (what == "chime") Interlocked.Increment(ref chimes); else if (what == "flash") Interlocked.Increment(ref flashes); };

        // a scripted printer in place of the print program and the Windows print queue: nothing here can reach paper
        var printer = new FakeSpooler(FakeScenario.StuckInQueue, stepMs: 150);
        printer.Printers.Add(LivePrinter);
        FakeJob? printed = null;
        WatchedEngine? engine = null;
        var settings = new Settings { ApiBaseUrl = "https://selftest.invalid", BlackWhitePrinter = LivePrinter, SoundOn = true };
        var w = new MainWindow(App.Version, settings, store)
        {
            WindowStartupLocation = WindowStartupLocation.Manual, Left = -30000, Top = -30000, ShowInTaskbar = false, ShowActivated = false, Quiet = true,
            ReadPrinter = name => new PrinterHealth(name, name == LivePrinter, false, false, false, null),
            PrintProgramOk = () => true,
            InFront = () => false,                                       // the shopkeeper is looking elsewhere: a new request must flash
        };
        w.MakePrinting = (api, journal) =>
        {
            engine = new WatchedEngine(printer, journal, () => printed?.Id ?? Guid.Empty);
            var options = new OrchestratorOptions(Path.Combine(Settings.Dir, "work"), settings.PrinterFor, WaitLimit: _ => TimeSpan.FromSeconds(4),
                LeaseRenewEvery: TimeSpan.FromSeconds(1), SpoolPoll: TimeSpan.FromMilliseconds(25), ReportAttempts: 4, RetryDelay: TimeSpan.FromMilliseconds(250));
            return (new PrintOrchestrator(api, engine, printer, journal, new MadeUpDownloader(server.Pdf), options, App.Log), printer);
        };
        app.Adopt(w); app.ActivateOnShow = false;
        var asked = new List<string>(); bool sayYes = false; int exits = 0;
        app.Confirm = text => { asked.Add(text); return sayYes; };
        app.ExitProcess = () => exits++;
        w.Show();
        w.Start();

        // ---- pairing
        Check("pairing: the code from the server is shown", await Until(() => w.PairView.IsVisible && w.PairCode.Text == "TEST-CODE", 15));
        Check("pairing: the countdown is running", await Until(() => w.PairNote.Text.Contains("It works for"), 5));
        await Shot(w, "live-01-pairing");
        Check("pairing: the queue opens by itself once the code is accepted", await Until(() => w.QueueView.IsVisible, 30));
        Check("pairing: the credentials went to the store it was given", store.Load()?.DeviceId == server.Device);

        // ---- the queue, with two requests that were already waiting
        Check("queue: both waiting requests are shown", await Until(() => Buttons(w.Cards, "Approve and print").Count == 2, 15));
        Check("queue: shop name and connection state", w.ShopTitle.Text == "Live Self-Test Shop" && w.StatusText.Text == "Connected");
        int pollsBefore = server.Polls;
        await Task.Delay(1200);
        Check("queue: the oldest request is first", Inside<TextBlock>(w.Cards).Select(t => t.Text).Where(t => t is "LV01" or "LV02").FirstOrDefault() == "LV01");
        Check($"start-up: requests that were already waiting made no sound and no flash (sounds {chimes}, flashes {flashes})", chimes == 0 && flashes == 0);
        await Shot(w, "live-02-queue");

        // ---- three new requests arrive together: one sound, one flash
        var j3 = server.Add("LV03", "Third made-up file.pdf", 0);
        var j4 = server.Add("LV04", "Fourth made-up file.pdf", 0);
        var j5 = server.Add("LV05", "Fifth made-up file.pdf", 0);
        w.WakeAgent();
        Check("new requests: all five are shown", await Until(() => Buttons(w.Cards, "Approve and print").Count == 5, 10));
        Check($"new requests: three at once made exactly one sound and one taskbar flash (sounds {chimes}, flashes {flashes})", chimes == 1 && flashes == 1);
        w.WakeAgent(); await Task.Delay(1500); w.WakeAgent(); await Task.Delay(1000);
        log.AppendLine($"      (Windows reports the off-screen test window as active: {w.IsActive})");
        Check($"new requests: later polls with nothing new stay quiet (sounds {chimes}, flashes {flashes})", chimes == 1 && flashes == 1);

        // ---- two fast clicks on Approve
        var approve = Buttons(Card(w, "LV01"), "Approve and print")[0];
        Click(approve); Click(approve);
        await Idle(w);
        foreach (var again in Buttons(Card(w, "LV01"), "Approve and print").Take(1)) Click(again);     // the rebuilt, switched-off button too
        Check("approve: the request shows it is being sent, with its buttons off", Says(w.Cards, "Sending your answer") && !Buttons(Card(w, "LV01"), "Approve and print")[0].IsEnabled);
        await Until(() => server.Approves >= 1, 5); await Task.Delay(1500);
        Check($"approve: three clicks sent exactly one approval (server saw {server.Approves})", server.Approves == 1);
        Check("approve: the request moves to Approved", await Until(() => Says(w.Cards, "Approved. It prints as soon as the printer is free."), 10));
        Check("approve: the app asked the server for the job to print", await Until(() => server.Claims >= 1, 10));
        await Shot(w, "live-03-approved");

        // ---- it finishes: the card leaves, the order can be looked up
        server.Set(j1, "completed"); w.WakeAgent();
        Check("finished: the card leaves the queue", await Until(() => !Says(w.Cards, "LV01"), 10));
        w.TabFinished.IsChecked = true; w.SearchBox.Text = "lv01";
        Check("finished: found by its code, worded as sent to printer", await Until(() => Says(w.FinishedRows, "LV01") && Says(w.FinishedRows, "Sent to printer"), 5));
        Check("finished: the other order is not in the result", !Says(w.FinishedRows, "LV02"));
        await Shot(w, "live-04-finished-lookup");
        w.SearchBox.Text = ""; w.TabRequests.IsChecked = true;

        // ---- the internet goes away and comes back
        server.Offline = true; w.WakeAgent();
        Check("offline: the header says so", await Until(() => w.StatusText.Text == "No internet", 20));
        Check("offline: a banner explains, with the time of the last contact", Says(w.Banners, "New requests will arrive by themselves") && Says(w.Banners, "Last contact"));
        Check("offline: answer buttons are off and the card says why", await Until(() => Buttons(w.Cards, "Reject").All(b => !b.IsEnabled) && Says(w.Cards, "You can answer when it is back"), 5));
        await Shot(w, "live-05-offline");
        server.Offline = false; w.WakeAgent();
        Check("online again by itself", await Until(() => w.StatusText.Text == "Connected" && Buttons(w.Cards, "Reject").All(b => b.IsEnabled), 30));
        Check("offline: the banner is gone", await Until(() => !Says(w.Banners, "New requests will arrive by themselves"), 5));

        // ---- reject is one click
        await Task.Delay(700);
        Click(Buttons(Card(w, "LV02"), "Reject")[0]);
        Check("reject: sent once, and the card leaves", await Until(() => server.Rejects == 1 && !Says(w.Cards, "LV02"), 10));

        // ---- the customer cancels while the shopkeeper has the preview open
        await Task.Delay(700);
        int approvesBefore = server.Approves, rejectsBefore = server.Rejects;
        var open = Buttons(Card(w, "LV03"), "Preview")[0];
        _ = w.Dispatcher.BeginInvoke(() => Click(open));                 // the preview is a dialog: the click returns only when it closes
        Check("preview: the window opens", await Until(() => w.OwnedWindows.OfType<PreviewWindow>().Any(), 10));
        var preview = w.OwnedWindows.OfType<PreviewWindow>().FirstOrDefault();
        if (preview is not null)
        {
            Check("preview: the page of the made-up file is shown", await Until(() => preview.PageText.Text == "Page 1 of 1" && preview.PageImage.Source is not null, 20));
            Check("preview: both answers are offered while the request is waiting", preview.ApproveBtn.IsEnabled && preview.RejectBtn.IsEnabled);
            server.Set(j3, "cancelled"); w.WakeAgent();
            Check("preview: it says the customer cancelled, and both answers switch off",
                await Until(() => preview.Message.IsVisible && preview.Message.Text.Contains("customer cancelled") && !preview.ApproveBtn.IsEnabled && !preview.RejectBtn.IsEnabled, 10));
            await Shot(preview, "live-06-preview-customer-cancelled");
            preview.Close();
            Check("preview: closed, and nothing was sent for the cancelled request", await Until(() => !w.OwnedWindows.OfType<PreviewWindow>().Any(), 5)
                && server.Approves == approvesBefore && server.Rejects == rejectsBefore);
        }
        Check("cancelled: the card has left the queue", await Until(() => !Says(w.Cards, "LV03"), 10));

        // ---- the customer cancels in the instant before Approve is clicked (the queue on screen is a few seconds old)
        await Task.Delay(700);
        server.Set(j4, "cancelled");
        Click(Buttons(Card(w, "LV04"), "Approve and print")[0]);
        Check("cancelled just before Approve: the shopkeeper is told nothing was changed", await Until(() => Says(w.Banners, "That request has changed"), 10));
        Check("cancelled just before Approve: no approval went through and the card leaves", await Until(() => !Says(w.Cards, "LV04"), 10) && server.Approves == approvesBefore);

        // ---- a print is under way when the PC goes to sleep
        printed = j5; server.HandOut = true;
        await Task.Delay(700);
        Click(Buttons(Card(w, "LV05"), "Approve and print")[0]);
        Check("print: the request is handed to the (made-up) printer and shown as printing", await Until(() => printer.SubmitCount == 1 && Says(w.Cards, "PRINTING NOW"), 15));
        Check("print: the journal said \"about to print\" before the printer was given anything", engine is { JournalHadIntentFirst: [true] });
        await Shot(w, "live-07-printing");
        app.Quit();                                                      // answered "no" by the test
        Check("quit while printing: asks first, and says the job will need attention", asked.Count == 1 && asked[0].Contains("being sent to the printer right now") && asked[0].Contains("Quit AutoPrint anyway?"));
        Check("quit answered No: nothing stops", exits == 0);

        // Sleep: nothing gets through, the app's waits between tries grow, and meanwhile the server gives up on the
        // lease, as the real one does. (The made-up printer keeps the job in its queue: the printer was off.)
        server.Offline = true; server.ExpireLease();
        Check("sleep: the app notices it has no connection and backs off", await Until(() => server.OfflinePolls >= 4, 40));
        await Task.Delay(1000);
        int pollsAsleep = server.Polls;
        var woke = System.Diagnostics.Stopwatch.StartNew();
        server.Offline = false;
        app.OnResume();                                                  // what Windows' "resumed from sleep" event calls
        bool polledAtOnce = await Until(() => server.Polls > pollsAsleep, 3);
        Check($"wake: the server was polled {woke.ElapsedMilliseconds} ms after waking (the next try by itself was several seconds away)", polledAtOnce && woke.ElapsedMilliseconds < 1500);
        Check("wake: the print that was under way shows as needing attention", await Until(() => Says(w.Cards, "NEEDS YOUR ATTENTION") && Buttons(Card(w, "LV05"), "Print again").Count == 1, 15));
        Check("wake: the card says the document is still in the Windows print queue", await Until(() => Says(Card(w, "LV05"), "still waiting in the Windows print queue"), 15));
        w.WakeAgent(); await Task.Delay(3000); w.WakeAgent(); await Task.Delay(1500);
        Check($"wake: nothing was printed again by itself (handed out {j5.Handed} time, sent to the printer {printer.SubmitCount} time)", j5.Handed == 1 && printer.SubmitCount == 1);
        Check("wake: the server stayed the judge of the interrupted attempt (it kept \"needs attention\")", server.StatusOf(j5) == "needs_attention");
        await Shot(w, "live-08-after-wake-needs-attention");

        // ---- Print again: asks first, removes the job that is still queued, then exactly one new attempt
        Click(Buttons(Card(w, "LV05"), "Print again")[0]);
        Check("print again: it asks first, and offers to remove the job that is still in the queue", await Until(() => Buttons(Card(w, "LV05"), "Remove it, then print again").Count == 1, 10));
        Check("print again: nothing was sent while it asks", server.Resolves == 0 && printer.SubmitCount == 1 && printer.RemoveCount == 0);
        await Shot(w, "live-09-print-again-asks");
        var remove = Buttons(Card(w, "LV05"), "Remove it, then print again")[0];
        Click(remove); Click(remove);
        Check("print again: the new attempt went to the printer and was reported", await Until(() => server.StatusOf(j5) == "completed", 30));
        await Task.Delay(2500); w.WakeAgent(); await Task.Delay(1500);
        Check($"print again: two clicks made exactly one new attempt (answers {server.Resolves}, handed out {j5.Handed} times, sent to the printer {printer.SubmitCount} times)",
            server.Resolves == 1 && j5.Handed == 2 && printer.SubmitCount == 2);
        Check($"print again: the old job was removed from the queue first ({printer.RemoveCount} removal) and the journal came first again", printer.RemoveCount == 1 && engine is { JournalHadIntentFirst: [true, true] });
        Check("print again: the card leaves and the queue says there is nothing to do", await Until(() => !Says(w.Cards, "LV05") && w.EmptyState.IsVisible, 10));
        Check($"heartbeat: the server was polled throughout ({server.Polls} polls)", server.Polls > pollsBefore + 3);

        // ---- AutoPrint is opened a second time while it is already running
        string name = @"Local\AutoPrint.V4.SelfTest." + Guid.NewGuid().ToString("N");     // never the real name: a real AutoPrint on this PC is not signalled
        using (var first = new SingleInstance(name))
        {
            first.Listen(() => w.Dispatcher.BeginInvoke(app.ShowWindow));
            w.Close();                                                   // closing keeps it running, hidden
            Check("close: the window hides and the app keeps running", first.IsFirst && !w.IsVisible && exits == 0);
            using var second = new SingleInstance(name);
            Check("second launch: it sees that AutoPrint is already running", !second.IsFirst);
            second.AskFirstToShow();
            Check("second launch: the window of the running app comes back", await Until(() => w.IsVisible, 5));
            w.WindowState = WindowState.Minimized;
            second.AskFirstToShow();
            Check("second launch: a minimised window is restored", await Until(() => w.WindowState == WindowState.Normal, 5));
        }

        // ---- Quit asks, and No means no
        asked.Clear();
        app.Quit();
        int pollsAfterNo = server.Polls; w.WakeAgent();
        Check("quit: asks first, and says what closing costs", asked.Count == 1 && asked[0].Contains("customers see your shop as offline") && asked[0].Contains("Quit AutoPrint?"));
        Check("quit answered No: the app keeps polling", exits == 0 && await Until(() => server.Polls > pollsAfterNo, 5));

        // ---- the shop disconnects this computer on its dashboard
        int startsBefore = server.Starts;
        server.Revoked = true; w.WakeAgent();
        Check("disconnected: back to the connect screen with a new code, and it says why",
            await Until(() => w.PairView.IsVisible && w.PairCode.Text == "TEST-CODE" && server.Starts > startsBefore && w.PairWhy.Text.Contains("disconnected"), 30));
        Check("disconnected: the saved credentials were cleared", store.Load() is null);
        await Shot(w, "live-10-disconnected");

        // ---- Quit answered Yes
        sayYes = true; asked.Clear();
        app.Quit();
        await Task.Delay(500);
        int requestsAtQuit = server.Requests;
        await Task.Delay(6000);
        Check($"quit answered Yes: asked once, the app stops and nothing more is sent to the server ({server.Requests - requestsAtQuit} requests in 6 s)", asked.Count == 1 && exits == 1 && server.Requests == requestsAtQuit);

        w.Hide();
        Alerts.Probe = null;
        App.FlushLog();
        var appLog = File.Exists(Path.Combine(Settings.Dir, "app.log")) ? File.ReadAllText(Path.Combine(Settings.Dir, "app.log")) : "";
        Check("the log shows the wake and the quit", appLog.Contains("woke from sleep") && appLog.Contains("quit by the user"));
        Check("no error was logged by the window or the agent", !appLog.Contains("ui error") && !appLog.Contains("unexpected") && !appLog.Contains("failed"));
        Check("no customer document or credential file on disk", !Directory.EnumerateFiles(Settings.Dir, "*", SearchOption.AllDirectories).Any(f => f.EndsWith(".pdf") || f.EndsWith(".part") || f.EndsWith("device.bin")));
        log.AppendLine("outcomes the server accepted: " + string.Join(", ", server.Outcomes) + $"; answers it refused as stale: {server.StaleAnswers}");
        log.AppendLine("runs in app.log: " + string.Join(" | ", appLog.Split('\n').Where(l => l.Contains(" run: ")).Select(l => l.Trim()[(l.IndexOf(" run: ", StringComparison.Ordinal) + 1)..])));
        log.AppendLine("files written: " + string.Join(", ", Directory.EnumerateFiles(Settings.Dir, "*", SearchOption.AllDirectories).Select(f => Path.GetRelativePath(Settings.Dir, f))));
        log.AppendLine(all ? "ok" : "FAILED");
        return all;
    }
}
