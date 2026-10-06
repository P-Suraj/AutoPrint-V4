using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Media;
using AutoPrint.Core;

namespace AutoPrint.Desktop;

/// <summary>
/// "--selftest-ui &lt;folder&gt; live": runs the real window through a whole day in a minute, against a made-up server that
/// lives inside this process. Pairing, the queue, a double-clicked Approve, a finished job, losing and regaining the
/// internet, Reject, and being disconnected by the shop. Nothing leaves the process: no network, no real credentials
/// (they are kept in memory), data only under the output folder, and the made-up server never hands out a job to
/// print, so no printer is used.
/// </summary>
internal static partial class SelfTest
{
    private sealed class FakeServer : HttpMessageHandler
    {
        public readonly Guid Device = Guid.NewGuid(), J1 = Guid.NewGuid(), J2 = Guid.NewGuid();
        public string S1 = "awaiting_approval", S2 = "awaiting_approval";
        public volatile bool Offline, Revoked;
        public int Starts, PairPolls, Polls, Approves, Rejects, Claims;
        private readonly DateTimeOffset _t0 = DateTimeOffset.UtcNow;

        private string Job(Guid id, string code, string name, string status, int minutesAgo)
        {
            var created = _t0.AddMinutes(-minutesAgo);
            var expires = status == "awaiting_approval" ? $"\"{created.AddHours(1):O}\"" : "null";
            return $$"""{"job_id":"{{id}}","order_short_code":"{{code}}","document_name":"{{name}}","page_count":3,"copies":2,"color":false,"duplex":true,"page_range":null,"amount_paise":720,"status":"{{status}}","created_at":"{{created:O}}","approval_expires_at":{{expires}},"attempt_count":0}""";
        }

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken ct)
        {
            if (Offline) throw new HttpRequestException("made-up network failure");
            var path = request.RequestUri!.AbsolutePath;
            HttpResponseMessage Json(string json, HttpStatusCode status = HttpStatusCode.OK)
            {
                var r = new HttpResponseMessage(status) { Content = new StringContent(json, Encoding.UTF8, "application/json") };
                r.Headers.Date = DateTimeOffset.UtcNow;
                return r;
            }
            if (path.EndsWith("/pair/start")) { Interlocked.Increment(ref Starts); PairPolls = 0; return Json($$"""{"pair_code":"TEST-CODE","expires_at":"{{DateTimeOffset.UtcNow.AddMinutes(15):O}}"}"""); }
            if (path.EndsWith("/pair/poll"))
            {
                if (Interlocked.Increment(ref PairPolls) < 2 || Revoked) return Json("""{"status":"pending","device_id":null,"shop_code":null,"shop_name":null}""");
                return Json($$"""{"status":"approved","device_id":"{{Device}}","shop_code":"TST001","shop_name":"Live Self-Test Shop"}""");
            }
            if (Revoked) return Json("""{"error":{"code":"unauthorized","message":"This device is not authorised."}}""", HttpStatusCode.Unauthorized);
            if (path.EndsWith("/v1/agent/jobs"))
            {
                Interlocked.Increment(ref Polls);
                return Json($$"""{"shop_code":"TST001","shop_name":"Live Self-Test Shop","contract_version":1,"jobs":[{{Job(J1, "LV01", "First made-up file.pdf", S1, 3)}},{{Job(J2, "LV02", "Second made-up file.pdf", S2, 1)}}]}""");
            }
            if (path.EndsWith("/approve")) { await Task.Delay(400, ct); Interlocked.Increment(ref Approves); S1 = "approved"; return Json($$"""{"job_id":"{{J1}}","status":"approved"}"""); }
            if (path.EndsWith("/reject")) { Interlocked.Increment(ref Rejects); S2 = "rejected"; return Json($$"""{"job_id":"{{J2}}","status":"rejected"}"""); }
            if (path.EndsWith("/claim"))
            {
                Interlocked.Increment(ref Claims);                      // never hands out a job: nothing is ever printed by this test
                return Json("""{"status":"no_job","job_id":null,"attempt_id":null,"attempt_token":null,"spooler_job_name":null,"lease_expires_at":null,"document":null,"options":null}""");
            }
            return Json("""{"error":{"code":"job_not_found","message":"Not part of the self-test."}}""", HttpStatusCode.NotFound);
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

    private static async Task<bool> Until(Func<bool> condition, int seconds)
    {
        var until = DateTime.UtcNow.AddSeconds(seconds);
        while (!condition()) { if (DateTime.UtcNow > until) return false; await Task.Delay(100); }
        return true;
    }

    private static async Task<bool> LiveAsync(string outDir, StringBuilder log)
    {
        bool all = true;
        void Check(string what, bool ok) { all &= ok; log.AppendLine((ok ? "PASS  " : "FAIL  ") + what); }
        async Task Shot(Window w, string name) { await Idle(w); Save(w, Path.Combine(outDir, name + ".png"), 96); }

        var server = new FakeServer();
        App.Http = new HttpClient(server) { Timeout = TimeSpan.FromSeconds(30) };
        var store = new MemoryCredentialStore();
        // "Microsoft Print to PDF" is only named so that the printer check finds a printer; nothing is ever sent to it
        var w = new MainWindow(App.Version, new Settings { ApiBaseUrl = "https://selftest.invalid", BlackWhitePrinter = "Microsoft Print to PDF", SoundOn = false }, store)
        { WindowStartupLocation = WindowStartupLocation.Manual, Left = -30000, Top = -30000, ShowInTaskbar = false, ShowActivated = false };
        w.Show();
        w.Start();

        // ---- pairing
        Check("pairing: the code from the server is shown", await Until(() => w.PairView.IsVisible && w.PairCode.Text == "TEST-CODE", 15));
        Check("pairing: the countdown is running", await Until(() => w.PairNote.Text.Contains("It works for"), 5));
        await Shot(w, "live-01-pairing");
        Check("pairing: the queue opens by itself once the code is accepted", await Until(() => w.QueueView.IsVisible, 30));
        Check("pairing: the credentials went to the store it was given", store.Load()?.DeviceId == server.Device);

        // ---- the queue
        Check("queue: both waiting requests are shown", await Until(() => Buttons(w.Cards, "Approve and print").Count == 2, 15));
        Check("queue: shop name and connection state", w.ShopTitle.Text == "Live Self-Test Shop" && w.StatusText.Text == "Connected");
        int pollsBefore = server.Polls;
        await Task.Delay(1200);
        Check("queue: the oldest request is first", Inside<TextBlock>(w.Cards).Select(t => t.Text).Where(t => t is "LV01" or "LV02").FirstOrDefault() == "LV01");
        await Shot(w, "live-02-queue");

        // ---- two fast clicks on Approve
        var approve = Buttons(w.Cards, "Approve and print")[0];
        Click(approve); Click(approve);
        await Idle(w);
        foreach (var again in Buttons(w.Cards, "Approve and print").Take(1)) Click(again);     // the rebuilt, switched-off button too
        Check("approve: the request shows it is being sent, with its buttons off", Says(w.Cards, "Sending your answer") && !Buttons(w.Cards, "Approve and print")[0].IsEnabled);
        await Until(() => server.Approves >= 1, 5); await Task.Delay(1500);
        Check($"approve: three clicks sent exactly one approval (server saw {server.Approves})", server.Approves == 1);
        Check("approve: the request moves to Approved", await Until(() => Says(w.Cards, "Approved. It prints as soon as the printer is free."), 10));
        Check("approve: the app asked the server for the job to print", await Until(() => server.Claims >= 1, 10));
        await Shot(w, "live-03-approved");

        // ---- it finishes: the card leaves, the order can be looked up
        server.S1 = "completed"; w.WakeAgent();
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
        Click(Buttons(w.Cards, "Reject")[0]);
        Check("reject: sent once, and the card leaves", await Until(() => server.Rejects == 1 && !Says(w.Cards, "LV02"), 10));
        Check("empty: the queue says there is nothing to do", await Until(() => w.EmptyState.IsVisible, 5));
        Check($"heartbeat: the server was polled throughout ({server.Polls} polls)", server.Polls > pollsBefore + 3);

        // ---- the shop disconnects this computer on its dashboard
        int startsBefore = server.Starts;
        server.Revoked = true; w.WakeAgent();
        Check("disconnected: back to the connect screen with a new code, and it says why",
            await Until(() => w.PairView.IsVisible && w.PairCode.Text == "TEST-CODE" && server.Starts > startsBefore && w.PairWhy.Text.Contains("disconnected"), 30));
        Check("disconnected: the saved credentials were cleared", store.Load() is null);
        await Shot(w, "live-06-disconnected");

        w.Stop(); w.Hide();
        App.FlushLog();
        var appLog = File.Exists(Path.Combine(Settings.Dir, "app.log")) ? File.ReadAllText(Path.Combine(Settings.Dir, "app.log")) : "";
        Check("no error was logged by the window or the agent", !appLog.Contains("ui error") && !appLog.Contains("unexpected") && !appLog.Contains("failed"));
        Check("no customer document or credential file on disk", !Directory.EnumerateFiles(Settings.Dir, "*", SearchOption.AllDirectories).Any(f => f.EndsWith(".pdf") || f.EndsWith(".part") || f.EndsWith("device.bin")));
        log.AppendLine("files written: " + string.Join(", ", Directory.EnumerateFiles(Settings.Dir, "*", SearchOption.AllDirectories).Select(f => Path.GetRelativePath(Settings.Dir, f))));
        log.AppendLine(all ? "ok" : "FAILED");
        return all;
    }
}
