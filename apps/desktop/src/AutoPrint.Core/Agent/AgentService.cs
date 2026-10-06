using AutoPrint.Core.Shop;

namespace AutoPrint.Core.Agent;

/// <param name="LastPollAt">Time of the last successful contact with the server (this PC's clock).</param>
/// <param name="LastRun">How the most recent print run on this PC ended (not "no job"). Kept only in memory; lets the window say why.</param>
/// <param name="CannotPrint">Set when this PC must not print at all (its print record cannot be written). Approving is pointless until it clears.</param>
public sealed record AgentState(
    bool Online, bool NeedsPairing, QueueSnapshot? Queue, Activity? Current, string? Problem, DateTimeOffset? LastPollAt,
    string? CannotPrint = null, RunResult? LastRun = null);

/// <summary>
/// Keeps the shop PC connected. One request every ~10 s does both heartbeat and queue refresh; approving a job
/// wakes the loop at once, so "approve" feels instant instead of waiting for the next poll. It never exits on a
/// network failure or on a bug: it backs off and keeps trying (V3's agent died permanently if offline at boot).
/// Printing runs beside the loop, not inside it, so the heartbeat and the queue keep refreshing during a long
/// print (V3 showed the shop "offline" while it printed). Only one print runs at a time, and recovery of unsettled
/// attempts runs only while nothing is printing.
/// </summary>
public sealed class AgentService
{
    public const string JournalFaultText =
        "AutoPrint cannot write its print record on this computer, so nothing will be printed. Restart the computer. If this message stays, call support.";

    private readonly IShopApi _api;
    private readonly PrintOrchestrator _orchestrator;
    private readonly TimeSpan _pollEvery;
    private readonly Func<TimeSpan, CancellationToken, Task> _delay;
    private readonly Action<string>? _log;
    private readonly SemaphoreSlim _wake = new(0, 1);
    private readonly Random _rng = new();
    private readonly object _gate = new();
    private AgentState _state = new(false, false, null, null, null, null);

    public event Action<AgentState>? StateChanged;
    public AgentState State => _state;

    public AgentService(IShopApi api, PrintOrchestrator orchestrator, TimeSpan? pollEvery = null,
                        Func<TimeSpan, CancellationToken, Task>? delay = null, Action<string>? log = null)
    {
        _api = api; _orchestrator = orchestrator; _log = log;
        _pollEvery = pollEvery ?? TimeSpan.FromSeconds(10);
        _delay = delay ?? Task.Delay;
        orchestrator.ActivityChanged += a => Publish(s => s with { Current = a.Stage == Stage.Idle ? null : a });
    }

    private void Log(string line) { try { _log?.Invoke(line); } catch (Exception) { /* logging must never stop the agent */ } }

    /// <summary>The print worker and the poll loop both publish, so changes are applied one at a time, in order.</summary>
    private void Publish(Func<AgentState, AgentState> change)
    {
        lock (_gate)
        {
            _state = change(_state);
            try { StateChanged?.Invoke(_state); }
            catch (Exception e) { Log("state listener failed: " + SafeText.Describe(e)); }
        }
    }

    /// <summary>Ask the loop to poll now (after the shopkeeper approved or resolved something, or the network came back).</summary>
    public void Wake() { try { _wake.Release(); } catch (SemaphoreFullException) { /* already pending */ } }

    public async Task RunAsync(CancellationToken ct)
    {
        int failures = 0;
        Task? printing = null;
        while (!ct.IsCancellationRequested)
        {
            try
            {
                bool idle = printing is null || printing.IsCompleted;
                // every idle round, not only at start: an outcome that could not be delivered (offline at boot, or the
                // network dropped during the report) is settled as soon as the server answers again. Never while a
                // print is running: the attempt in progress is "unreported" too, and must not be settled under it.
                if (idle) { printing = null; await RecoverAsync(ct); }
                var snap = await _api.PollAsync(ct);
                failures = 0;
                Publish(s => s with { Online = true, NeedsPairing = false, Queue = snap, Problem = null, LastPollAt = snap.At });

                if (idle && _state.CannotPrint is null && snap.Jobs.Any(j => j.Status == JobStatus.Approved))
                    printing = PrintApprovedAsync(ct);
            }
            catch (OperationCanceledException) when (ct.IsCancellationRequested) { break; }
            catch (ApiRejectedException e) when (e.IsAuthFailure)
            {
                Publish(s => s with { Online = true, NeedsPairing = true, Problem = "This PC is no longer authorised. Pair it again." });
                failures = Math.Max(failures, 3);                         // check again, but slowly
            }
            catch (ServerUnreachableException)
            {
                failures++;
                Publish(s => s with { Online = false, Problem = "No connection to AutoPrint. Retrying…" });
            }
            catch (Exception e)
            {
                // A bug, or a timeout surfacing as a cancellation that nobody asked for, must never stop the shop's PC.
                failures++;
                Log("unexpected " + SafeText.Describe(e));
                Publish(s => s with { Problem = "Something went wrong. Retrying…" });
            }

            try { await WaitAsync(NextDelay(failures), ct); }
            catch (OperationCanceledException) when (ct.IsCancellationRequested) { break; }
            catch (Exception e) { Log("wait failed: " + SafeText.Describe(e)); }
        }
        if (printing is not null) { try { await printing; } catch (Exception) { /* it logs its own end */ } }
    }

    /// <summary>Settles attempts whose outcome never reached the server. A fault in the local print record does not
    /// stop the heartbeat: it is shown to the shopkeeper and blocks printing until the record works again.</summary>
    private async Task RecoverAsync(CancellationToken ct)
    {
        try
        {
            await _orchestrator.RecoverAsync(ct, r => Publish(s => s with { LastRun = r }));
            if (_state.CannotPrint is not null) Publish(s => s with { CannotPrint = null });
        }
        catch (Exception e) when (e is not (OperationCanceledException or ApiRejectedException or ServerUnreachableException))
        {
            Log("print record fault: " + SafeText.Describe(e));
            Publish(s => s with { CannotPrint = JournalFaultText });
        }
    }

    /// <summary>Prints everything that has been approved, one job at a time, and refreshes the queue after each.</summary>
    private async Task PrintApprovedAsync(CancellationToken ct)
    {
        bool ran = false;
        try
        {
            while (!ct.IsCancellationRequested)
            {
                var run = await _orchestrator.RunOnceAsync(ct);
                Log($"run: {run.Kind} {run.Reason}");
                if (run.Reason == PrintOrchestrator.JournalUnavailable) { Publish(s => s with { CannotPrint = JournalFaultText }); break; }
                if (run.Kind == RunKind.NoJob) break;
                ran = true;
                Publish(s => s with { LastRun = run });
                Wake();
            }
        }
        catch (OperationCanceledException) when (ct.IsCancellationRequested) { }
        catch (Exception e) { Log("print run stopped: " + SafeText.Describe(e)); }    // the journal keeps the attempt; the next idle round settles it
        // Refresh at once only when a job really ran. An approved job the server will not hand out yet (another PC is
        // printing, or its document is gone) is simply asked for again at the next normal poll, never in a tight loop.
        finally { if (ran) Wake(); }
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
        ct.ThrowIfCancellationRequested();
    }
}
