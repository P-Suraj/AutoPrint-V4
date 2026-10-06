using System.Text.Json;
using System.Text.Json.Serialization;

namespace AutoPrint.Core.Shop;

// Wire types for the shop-side API. Names follow contracts/openapi.json (snake_case). A contract test
// (ContractTests) fails if any of these drifts from the API schema, so they cannot silently diverge.

public static class Wire
{
    public static readonly JsonSerializerOptions Json = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        DefaultIgnoreCondition = JsonIgnoreCondition.Never,
        Converters = { new JsonStringEnumConverter(JsonNamingPolicy.SnakeCaseLower) },
    };
}

public enum JobStatus { AwaitingApproval, Approved, Printing, Completed, Failed, NeedsAttention, Rejected, Cancelled, Expired }
public enum Outcome { Completed, Failed, Uncertain }
public enum Resolution { Completed, Failed, Retry }

public sealed record PrintOptions(int Copies, bool Color, bool Duplex, string? PageRange);

public sealed record JobSummary(
    Guid JobId, string OrderShortCode, string DocumentName, int PageCount, int Copies, bool Color, bool Duplex,
    string? PageRange, int AmountPaise, JobStatus Status, DateTimeOffset CreatedAt, DateTimeOffset? ApprovalExpiresAt,
    int AttemptCount);

public sealed record JobListResponse(string ShopCode, string ShopName, IReadOnlyList<JobSummary> Jobs, int ContractVersion);

public sealed record DocumentAccess(string DownloadUrl, string Sha256, long ByteSize, int? PageCount);

public sealed record ClaimResponse(
    string Status, Guid? JobId, Guid? AttemptId, string? AttemptToken, string? SpoolerJobName,
    DateTimeOffset? LeaseExpiresAt, DocumentAccess? Document, PrintOptions? Options);

public sealed record AttemptAuth(string AttemptToken);
public sealed record RenewRequest(string AttemptToken, int LeaseSeconds);
public sealed record OutcomeRequest(string AttemptToken, Outcome Outcome, IDictionary<string, object?> Evidence);
public sealed record OutcomeResponse(JobStatus JobStatus);
public sealed record LeaseResponse(DateTimeOffset LeaseExpiresAt);
public sealed record AckResponse(string Status);
public sealed record JobStatusResponse(Guid JobId, JobStatus Status);
public sealed record RejectRequest(string? Reason);
public sealed record ResolveRequest(Resolution Resolution, string? Note);
public sealed record EnrollRequest(string EnrollmentCode, string DisplayName);
public sealed record EnrollResponse(Guid DeviceId, string DeviceSecret, string ShopCode, string ShopName);

/// <summary>What the rest of the app works with: no wire details.</summary>
public sealed record Claim(
    Guid JobId, Guid AttemptId, string AttemptToken, string SpoolerJobName, DateTimeOffset LeaseExpiresAt,
    string DownloadUrl, string Sha256, long Bytes, int PageCount, PrintOptions Options);

/// <param name="At">When the reply arrived, by this PC's clock.</param>
/// <param name="ServerNow">The server's own clock at that moment (HTTP Date header), so waiting and expiry times
/// stay right on a PC whose clock is wrong.</param>
public sealed record QueueSnapshot(string ShopCode, string ShopName, IReadOnlyList<JobSummary> Jobs, DateTimeOffset At, DateTimeOffset? ServerNow = null);
