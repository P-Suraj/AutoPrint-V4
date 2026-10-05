using System.Net.Http.Json;
using System.Security.Cryptography;
using AutoPrint.Core.Shop;

namespace AutoPrint.Core;

public sealed record PairStartRequest(string DisplayName, string PollToken, string DeviceSecret);
public sealed record PairStartResponse(string PairCode, DateTimeOffset ExpiresAt);
public sealed record PairPollRequest(string PollToken);
public sealed record PairPollResponse(string Status, Guid? DeviceId, string? ShopCode, string? ShopName);

public sealed record PairingSession(string Code, string PollToken, string DeviceSecret, DateTimeOffset ExpiresAt, string ApiBaseUrl);

/// <summary>
/// Device-initiated pairing. The app makes its own secret, shows a short code, and waits for the founder to approve
/// that code for a shop. No secret ever comes back from the server.
/// </summary>
public static class Pairing
{
    private static string Random32() => Convert.ToHexString(RandomNumberGenerator.GetBytes(32)).ToLowerInvariant();

    public static async Task<PairingSession> StartAsync(HttpClient http, string baseUrl, string displayName, CancellationToken ct)
    {
        var poll = Random32();
        var secret = Random32();
        var res = await PostAsync<PairStartRequest, PairStartResponse>(http, baseUrl, "/v1/agent/pair/start", new(displayName, poll, secret), ct);
        return new PairingSession(res.PairCode, poll, secret, res.ExpiresAt, baseUrl);
    }

    public static Task<PairPollResponse> PollOnceAsync(HttpClient http, PairingSession s, CancellationToken ct) =>
        PostAsync<PairPollRequest, PairPollResponse>(http, s.ApiBaseUrl, "/v1/agent/pair/poll", new(s.PollToken), ct);

    /// <summary>Polls every few seconds until the founder approves, the code expires, or the user cancels.</summary>
    public static async Task<DeviceCredentials?> WaitForApprovalAsync(
        HttpClient http, PairingSession s, TimeSpan? every, CancellationToken ct)
    {
        var step = every ?? TimeSpan.FromSeconds(3);
        while (!ct.IsCancellationRequested)
        {
            try
            {
                var r = await PollOnceAsync(http, s, ct);
                if (r.Status == "approved") return new DeviceCredentials(r.DeviceId!.Value, s.DeviceSecret, r.ShopCode!, r.ShopName ?? r.ShopCode!, s.ApiBaseUrl);
                if (r.Status == "expired") return null;
            }
            catch (ServerUnreachableException) { /* offline: keep waiting; the code stays valid for 15 minutes */ }
            await Task.Delay(step, ct);
        }
        return null;
    }

    private static async Task<TRes> PostAsync<TReq, TRes>(HttpClient http, string baseUrl, string path, TReq body, CancellationToken ct)
    {
        try
        {
            using var res = await http.PostAsJsonAsync(baseUrl.TrimEnd('/') + path, body, Wire.Json, ct);
            if (res.IsSuccessStatusCode) return (await res.Content.ReadFromJsonAsync<TRes>(Wire.Json, ct))!;
            if ((int)res.StatusCode >= 500) throw new ServerUnreachableException($"The server had a problem (HTTP {(int)res.StatusCode}).");
            throw new ApiRejectedException("unknown", "The request was refused.", res.StatusCode);
        }
        catch (HttpRequestException e) { throw new ServerUnreachableException("Could not reach AutoPrint.", e); }
    }
}
