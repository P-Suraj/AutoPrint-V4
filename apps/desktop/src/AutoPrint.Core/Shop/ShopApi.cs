using System.Net;
using System.Net.Http.Json;
using System.Text.Json;

namespace AutoPrint.Core.Shop;

/// <summary>The server answered with an error from the catalog (docs/CONTRACTS.md). Branch on Code, never on Message.</summary>
public sealed class ApiRejectedException(string code, string message, HttpStatusCode status) : Exception(message)
{
    public string Code { get; } = code;
    public HttpStatusCode Status { get; } = status;
    public bool IsAuthFailure => Code == "unauthorized";
    /// <summary>The attempt is no longer ours (lease expired or another outcome recorded). Never retry blindly.</summary>
    public bool IsStaleAttempt => Code == "stale_attempt";
}

/// <summary>Could not reach the server (offline, DNS, timeout, 5xx). Always safe to retry later.</summary>
public sealed class ServerUnreachableException(string message, Exception? inner = null) : Exception(message, inner);

public interface IShopApi
{
    Task<QueueSnapshot> PollAsync(CancellationToken ct);
    Task ApproveAsync(Guid jobId, CancellationToken ct);
    Task RejectAsync(Guid jobId, string? reason, CancellationToken ct);
    Task<JobStatus> ResolveAsync(Guid jobId, Resolution resolution, string? note, CancellationToken ct);
    Task<Claim?> ClaimAsync(CancellationToken ct);
    Task<DateTimeOffset> RenewAsync(Guid attemptId, string token, int seconds, CancellationToken ct);
    Task MarkSentAsync(Guid attemptId, string token, CancellationToken ct);
    Task<JobStatus> ReportOutcomeAsync(Guid attemptId, string token, Outcome outcome, IDictionary<string, object?> evidence, CancellationToken ct);
}

public sealed class ShopApi : IShopApi
{
    private readonly HttpClient _http;
    private readonly DeviceCredentials _cred;
    private readonly string _version;

    public ShopApi(HttpClient http, DeviceCredentials credentials, string agentVersion)
    {
        _http = http;
        _cred = credentials;
        _version = agentVersion;
        _http.BaseAddress ??= new Uri(credentials.ApiBaseUrl.TrimEnd('/') + "/");
    }

    /// <summary>Enrollment happens before credentials exist, so it is static.</summary>
    public static async Task<EnrollResponse> EnrollAsync(HttpClient http, string baseUrl, string code, string displayName, CancellationToken ct)
    {
        using var req = new HttpRequestMessage(HttpMethod.Post, baseUrl.TrimEnd('/') + "/v1/agent/enroll")
        { Content = JsonContent.Create(new EnrollRequest(code, displayName), options: Wire.Json) };
        return await SendAsync<EnrollResponse>(http, req, ct);
    }

    private HttpRequestMessage Req(HttpMethod m, string path, object? body = null)
    {
        var r = new HttpRequestMessage(m, "v1/agent" + path);
        r.Headers.Add("X-Device-Id", _cred.DeviceId.ToString());
        r.Headers.Add("X-Device-Secret", _cred.DeviceSecret);
        r.Headers.Add("X-AutoPrint-Contract-Version", "1");
        if (body is not null) r.Content = JsonContent.Create(body, body.GetType(), options: Wire.Json);
        return r;
    }

    public async Task<QueueSnapshot> PollAsync(CancellationToken ct)
    {
        using var r = Req(HttpMethod.Get, "/jobs");
        r.Headers.Add("X-Agent-Version", _version);
        var res = await SendAsync<JobListResponse>(_http, r, ct);
        return new QueueSnapshot(res.ShopCode, res.ShopName, res.Jobs, DateTimeOffset.UtcNow);
    }

    public async Task ApproveAsync(Guid jobId, CancellationToken ct)
    { using var r = Req(HttpMethod.Post, $"/jobs/{jobId}/approve"); await SendAsync<JobStatusResponse>(_http, r, ct); }

    public async Task RejectAsync(Guid jobId, string? reason, CancellationToken ct)
    { using var r = Req(HttpMethod.Post, $"/jobs/{jobId}/reject", new RejectRequest(reason)); await SendAsync<JobStatusResponse>(_http, r, ct); }

    public async Task<JobStatus> ResolveAsync(Guid jobId, Resolution resolution, string? note, CancellationToken ct)
    { using var r = Req(HttpMethod.Post, $"/jobs/{jobId}/resolve", new ResolveRequest(resolution, note)); return (await SendAsync<JobStatusResponse>(_http, r, ct)).Status; }

    public async Task<Claim?> ClaimAsync(CancellationToken ct)
    {
        using var r = Req(HttpMethod.Post, "/claim");
        var c = await SendAsync<ClaimResponse>(_http, r, ct);
        if (c.Status != "claimed") return null;
        return new Claim(c.JobId!.Value, c.AttemptId!.Value, c.AttemptToken!, c.SpoolerJobName!, c.LeaseExpiresAt!.Value,
                         c.Document!.DownloadUrl, c.Document.Sha256, c.Document.ByteSize, c.Document.PageCount ?? 1, c.Options!);
    }

    public async Task<DateTimeOffset> RenewAsync(Guid attemptId, string token, int seconds, CancellationToken ct)
    { using var r = Req(HttpMethod.Post, $"/attempts/{attemptId}/renew", new RenewRequest(token, seconds)); return (await SendAsync<LeaseResponse>(_http, r, ct)).LeaseExpiresAt; }

    public async Task MarkSentAsync(Guid attemptId, string token, CancellationToken ct)
    { using var r = Req(HttpMethod.Post, $"/attempts/{attemptId}/sent", new AttemptAuth(token)); await SendAsync<AckResponse>(_http, r, ct); }

    public async Task<JobStatus> ReportOutcomeAsync(Guid attemptId, string token, Outcome outcome, IDictionary<string, object?> evidence, CancellationToken ct)
    { using var r = Req(HttpMethod.Post, $"/attempts/{attemptId}/outcome", new OutcomeRequest(token, outcome, evidence)); return (await SendAsync<OutcomeResponse>(_http, r, ct)).JobStatus; }

    private static async Task<T> SendAsync<T>(HttpClient http, HttpRequestMessage req, CancellationToken ct)
    {
        HttpResponseMessage res;
        try { res = await http.SendAsync(req, ct); }
        catch (OperationCanceledException) when (ct.IsCancellationRequested) { throw; }
        catch (Exception e) when (e is HttpRequestException or TaskCanceledException or IOException)
        { throw new ServerUnreachableException("Could not reach AutoPrint.", e); }

        using (res)
        {
            if (res.IsSuccessStatusCode)
            {
                var body = await res.Content.ReadFromJsonAsync<T>(Wire.Json, ct);
                return body ?? throw new ServerUnreachableException("The server sent an empty reply.");
            }
            if ((int)res.StatusCode >= 500)
                throw new ServerUnreachableException($"The server had a problem (HTTP {(int)res.StatusCode}).");
            string code = "unknown", message = "The request was refused.";
            try
            {
                using var doc = JsonDocument.Parse(await res.Content.ReadAsStringAsync(ct));
                var e = doc.RootElement.GetProperty("error");
                code = e.GetProperty("code").GetString() ?? code;
                message = e.GetProperty("message").GetString() ?? message;
            }
            catch (Exception) { /* not our envelope: keep the generic text */ }
            throw new ApiRejectedException(code, message, res.StatusCode);
        }
    }
}
