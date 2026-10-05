using AutoPrint.Core.Shop;

namespace AutoPrint.Core.Agent;

public sealed record AgentState(
    bool Online, bool NeedsPairing, QueueSnapshot? Queue, Activity? Current, string? Problem, DateTimeOffset? LastPollAt);

/// <summary>
/// Keeps the shop PC connected. One request every ~10 s does both heartbeat and queue refresh; approving a job
/// wakes the loop at once, so "approve" feels instant instead of waiting for the next poll. It never exits on a
/// network failure: it backs off and keeps trying (V3's agent died permanently if offline at boot).
/// </summary>
public sealed class AgentService
{
    private readonly IShopApi _api;
    private readonly PrintOrchestrator _orchestrator;
    private readonly TimeSpan _pollEvery;
    private readonly Func<TimeSpan, CancellationToken, Task> _delay;
    private readonly Action<string>? _log;
    private readonly SemaphoreSlim _wake = new(0, 1);
    private readonly Random _rng = new();
    private AgentState _state = new(false, false, null, null, null, null);

    public event Action<AgentState>? StateChanged;
    public AgentState State => _state;

    public AgentService(IShopApi api, PrintOrchestrator orchestrator, TimeSpan? pollEvery = null,
                        Func<TimeSpan, CancellationToken, Task>? delay = null, Action<string>? log = null)
    {
        _api = api; _orchestrator = orchestrator; _log = log;
        _pollEvery = pollEvery ?? TimeSpan.FromSeconds(10);
        _delay = delay ?? Task.Delay;
        orchestrator.ActivityChanged += a => Publish(_state with { Current = a.Stage == Stage.Idle ? null : a });
    }

    private void Publish(AgentState s) { _state = s; StateChanged?.Invoke(s); }

    /// <summary>Ask the loop to poll now (after the shopkeeper approved or resolved something).</summary>
    public void Wake() { try { _wake.Release(); } catch (SemaphoreFullException) { /* already pending */ } }

    public async Task RunAsync(CancellationToken ct)
    {
        int failures = 0;
        bool recovered = false;
        while (!ct.IsCancellationRequested)
        {
            try
            {
                if (!recovered) { await _orchestrator.RecoverAsync(ct); recovered = true; }
                var snap = await _api.PollAsync(ct);
                failures = 0;
                Publish(_state with { Online = true, NeedsPairing = false, Queue = snap, Problem = null, LastPollAt = snap.At });

                // print everything that has been approved, one job at a time, then look again straight away
                while (!ct.IsCancellationRequested && _state.Queue!.Jobs.Any(j => j.Status == JobStatus.Approved))
                {
                    var run = await _orchestrator.RunOnceAsync(ct);
                    _log?.Invoke($"run: {run.Kind} {run.Reason}");
                    snap = await _api.PollAsync(ct);
                    Publish(_state with { Queue = snap, LastPollAt = snap.At });
                    if (run.Kind == RunKind.NoJob) break;
                }
            }
            catch (OperationCanceledException) when (ct.IsCancellationRequested) { break; }
            catch (ApiRejectedException e) when (e.IsAuthFailure)
            {
                Publish(_state with { Online = true, NeedsPairing = true, Problem = "This PC is no longer authorised. Pair it again." });
                failures = Math.Max(failures, 3);                         // check again, but slowly
            }
            catch (ServerUnreachableException)
            {
                failures++;
                Publish(_state with { Online = false, Problem = "No connection to AutoPrint. Retrying…" });
            }
            catch (Exception e) when (e is not OperationCanceledException)
            {
                failures++;                                                // a bug must never stop the shop's PC
                _log?.Invoke($"unexpected {e.GetType().Name}");
                Publish(_state with { Problem = "Something went wrong. Retrying…" });
            }

            await WaitAsync(NextDelay(failures), ct);
        }
    }

    /// <summary>10 s normally; after failures 2, 4, 8, 16, 30, 60 s with a little jitter so shops do not all retry together.</summary>
    internal TimeSpan NextDelay(int failures)
    {
        if (failures <= 0) return _pollEvery;
        var secs = Math.Min(60, 2 * Math.Pow(2, Math.Min(failures - 1, 5)));
        return TimeSpan.FromSeconds(secs * (0.85 + _rng.NextDouble() * 0.3));
    }

    private async Task WaitAsync(TimeSpan d, CancellationToken ct)
    {
        using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        var wake = _wake.WaitAsync(cts.Token);
        var timer = _delay(d, cts.Token);
        await Task.WhenAny(wake, timer);
        cts.Cancel();
        try { await Task.WhenAll(wake, timer); } catch (OperationCanceledException) { /* the loser was cancelled */ }
    }
}
