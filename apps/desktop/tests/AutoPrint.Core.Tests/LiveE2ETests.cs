using System.Net.Http.Json;
using System.Text.Json;
using AutoPrint.Core.Agent;
using AutoPrint.Core.Printing;
using AutoPrint.Core.Shop;
using Xunit;

namespace AutoPrint.Core.Tests;

public sealed class LiveE2EFactAttribute : FactAttribute
{
    public LiveE2EFactAttribute()
    {
        foreach (var v in new[] { "AP_E2E_BASE", "AP_E2E_SHOP_KEY", "AP_E2E_PRINTER", "AP_SUMATRA", "AP_E2E_OUT" })
            if (string.IsNullOrEmpty(Environment.GetEnvironmentVariable(v))) { Skip = $"live end-to-end run only: set {v}"; return; }
    }
}

/// <summary>
/// The shop side of the whole-chain run, driven by e2e/run_live_e2e.py (which plays the customer). It pairs through the
/// shopkeeper dashboard API, runs the real agent with the real engine and spooler, and "clicks Approve" on the job.
/// </summary>
public class LiveE2ETests
{
    [LiveE2EFact]
    public async Task Shop_side_of_the_whole_chain()
    {
        var baseUrl = Environment.GetEnvironmentVariable("AP_E2E_BASE")!.TrimEnd('/');
        var key = Environment.GetEnvironmentVariable("AP_E2E_SHOP_KEY")!;
        var printer = Environment.GetEnvironmentVariable("AP_E2E_PRINTER")!;
        var sumatra = Environment.GetEnvironmentVariable("AP_SUMATRA")!;
        var outFile = Environment.GetEnvironmentVariable("AP_E2E_OUT")!;
        var t0 = DateTimeOffset.UtcNow;
        var timeline = new List<object>();
        void Mark(string what) { lock (timeline) timeline.Add(new { s = Math.Round((DateTimeOffset.UtcNow - t0).TotalSeconds, 2), what }); }

        using var http = new HttpClient { Timeout = TimeSpan.FromSeconds(30) };
        var dir = Path.Combine(Path.GetTempPath(), "ap_live_" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(dir);
        using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(150));
        Guid? deviceId = null;
        try
        {
            // 1. pair the way a shopkeeper does: the app shows a code, the dashboard approves it
            var session = await Pairing.StartAsync(http, baseUrl, "E2E-TEST-PC", cts.Token);
            Mark("pair code shown");
            using (var req = new HttpRequestMessage(HttpMethod.Post, baseUrl + "/v1/shop/pair/approve") { Content = JsonContent.Create(new { pair_code = session.Code }) })
            {
                req.Headers.Add("X-Shop-Key", key);
                using var res = await http.SendAsync(req, cts.Token);
                Assert.True(res.IsSuccessStatusCode, "dashboard approval failed: " + (int)res.StatusCode);
            }
            var creds = await Pairing.WaitForApprovalAsync(http, session, TimeSpan.FromMilliseconds(500), cts.Token);
            Assert.NotNull(creds);
            deviceId = creds!.DeviceId;
            Mark("paired");

            // 2. the real agent, real engine, real spooler
            var api = new ShopApi(http, creds, "e2e");
            using var journal = new Journal(Path.Combine(dir, "journal.db"));
            var runs = new List<string>();
            var orchestrator = new PrintOrchestrator(api, new SumatraEngine(sumatra), new WinSpoolObserver(), journal, new HttpDownloader(http),
                new OrchestratorOptions(Path.Combine(dir, "work"), _ => printer), m => { if (m.StartsWith("run:")) lock (runs) runs.Add(m); });
            var agent = new AgentService(api, orchestrator, TimeSpan.FromSeconds(2));
            var approved = new HashSet<Guid>();
            agent.StateChanged += s =>
            {
                if (s.Queue is null) return;
                foreach (var j in s.Queue.Jobs.Where(j => j.Status == JobStatus.AwaitingApproval && j.DocumentName.StartsWith("e2e_") && approved.Add(j.JobId)))
                {
                    Mark("job visible to the shop");
                    _ = Task.Run(async () => { await api.ApproveAsync(j.JobId, cts.Token); Mark("approved (the click)"); agent.Wake(); });
                }
                if (s.Current is { } c) Mark("stage " + c.Stage);
            };
            var loop = agent.RunAsync(cts.Token);

            while (!cts.IsCancellationRequested) { lock (runs) if (runs.Count > 0) break; await Task.Delay(200); }
            Mark("agent finished a run: " + string.Join(";", runs));
            cts.Cancel();
            try { await loop; } catch (OperationCanceledException) { }
            Assert.Contains(runs, r => r.StartsWith("run: Completed"));
        }
        finally
        {
            if (deviceId is not null)                                             // leave nothing connected behind
            {
                using var req = new HttpRequestMessage(HttpMethod.Post, $"{baseUrl}/v1/shop/devices/{deviceId}/revoke");
                req.Headers.Add("X-Shop-Key", key);
                try { await http.SendAsync(req); Mark("device disconnected"); } catch (HttpRequestException) { }
            }
            File.WriteAllText(outFile, JsonSerializer.Serialize(timeline));
            try { Directory.Delete(dir, true); } catch (IOException) { }
        }
    }
}
