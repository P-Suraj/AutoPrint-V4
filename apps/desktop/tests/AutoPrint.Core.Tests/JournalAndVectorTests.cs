using System.Text.Json;
using AutoPrint.Core;
using AutoPrint.Core.Printing;
using AutoPrint.Core.Shop;
using Xunit;

namespace AutoPrint.Core.Tests;

public class JournalTests
{
    [Fact]
    public void State_survives_reopening_and_only_moves_forward()
    {
        var path = Path.Combine(Path.GetTempPath(), "apj_" + Guid.NewGuid().ToString("N")[..8], "j.db");
        var a = Guid.NewGuid();
        var j1 = new Journal(path);
        j1.Begin(a, Guid.NewGuid(), "apjob_x", "secret-token", "Printer", 5);
        j1.Advance(a, AttemptState.Intent);
        j1.Advance(a, AttemptState.Downloaded);                       // an older state must not move it backwards
        var j2 = new Journal(path);                                    // "the app restarted"
        Assert.Equal(AttemptState.Intent, j2.StateOf(a));
        var e = Assert.Single(j2.Unreported());
        Assert.Equal("secret-token", e.AttemptToken);
        Assert.Equal(5, e.ExpectedPages);
        j2.MarkReported(a, "Completed");
        Assert.Empty(j2.Unreported());
        Directory.Delete(Path.GetDirectoryName(path)!, true);
    }

    [Fact]
    public void The_token_is_not_stored_in_plain_text()
    {
        var dir = Path.Combine(Path.GetTempPath(), "apj_" + Guid.NewGuid().ToString("N")[..8]);
        var j = new Journal(Path.Combine(dir, "j.db"));
        j.Begin(Guid.NewGuid(), Guid.NewGuid(), "apjob_x", "TOKEN-THAT-MUST-NOT-APPEAR", "P", 1);
        foreach (var f in Directory.GetFiles(dir))
        {
            using var s = new FileStream(f, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
            using var ms = new MemoryStream(); s.CopyTo(ms);
            Assert.DoesNotContain("TOKEN-THAT-MUST-NOT-APPEAR", System.Text.Encoding.UTF8.GetString(ms.ToArray()));
        }
        Directory.Delete(dir, true);
    }
}

public class CredentialTests
{
    [Fact]
    public void Credentials_round_trip_through_dpapi_and_are_not_readable_in_the_file()
    {
        var path = Path.Combine(Path.GetTempPath(), "apc_" + Guid.NewGuid().ToString("N")[..8], "device.bin");
        var store = new DpapiCredentialStore(path);
        Assert.Null(store.Load());
        var cred = new DeviceCredentials(Guid.NewGuid(), "SECRET-VALUE-123", "TST001", "Shop", "https://x.example");
        store.Save(cred);
        Assert.Equal(cred, store.Load());
        Assert.DoesNotContain("SECRET-VALUE-123", System.Text.Encoding.UTF8.GetString(File.ReadAllBytes(path)));
        File.WriteAllBytes(path, [1, 2, 3]);                           // corrupt: must not crash, must ask to enrol again
        Assert.Null(store.Load());
        store.Clear();
        Directory.Delete(Path.GetDirectoryName(path)!, true);
    }
}

/// <summary>Cross-language checks: the same vector files are run by the Python tests, so the C# code cannot drift
/// from the server's pricing page-range rule or from the SQL completion rule.</summary>
public class VectorTests
{
    private static string Contracts()
    {
        var d = new DirectoryInfo(AppContext.BaseDirectory);
        while (d is not null && !Directory.Exists(Path.Combine(d.FullName, "contracts"))) d = d.Parent;
        return Path.Combine(d!.FullName, "contracts");
    }

    [Fact]
    public void Page_range_counting_matches_the_pricing_vectors()
    {
        using var doc = JsonDocument.Parse(File.ReadAllText(Path.Combine(Contracts(), "pricing_vectors.json")));
        int n = 0;
        foreach (var c in doc.RootElement.GetProperty("cases").EnumerateArray())
        {
            int pages = c.GetProperty("page_count").GetInt32();
            string? range = c.GetProperty("page_range").ValueKind == JsonValueKind.Null ? null : c.GetProperty("page_range").GetString();
            var expect = c.GetProperty("expect");
            var got = PageRange.SelectedCount(range, pages);
            if (expect.TryGetProperty("error", out var err))
            {
                if (err.GetString() == "invalid_page_range") Assert.Null(got);
            }
            else Assert.Equal(expect.GetProperty("selected_pages").GetInt32(), got);
            n++;
        }
        Assert.True(n >= 20);
    }

    [Fact]
    public void Completion_rule_matches_the_shared_vectors()
    {
        using var doc = JsonDocument.Parse(File.ReadAllText(Path.Combine(Contracts(), "completion_vectors.json")));
        int n = 0;
        foreach (var c in doc.RootElement.GetProperty("cases").EnumerateArray())
        {
            var e = c.GetProperty("evidence");
            if (e.GetProperty("rule_version").GetInt32() != 1) continue;   // the server also rejects unknown versions
            var ev = new SpoolEvidence(
                e.GetProperty("spooler_job_seen").GetBoolean(), e.GetProperty("printing_seen").GetBoolean(), e.GetProperty("left_queue").GetBoolean(),
                e.GetProperty("flags_seen").EnumerateArray().Select(x => x.GetString()!).ToArray(),
                e.GetProperty("max_pages_printed").GetInt32(), 3, 1);
            Assert.True(c.GetProperty("expect_completed").GetBoolean() == ev.SatisfiesRule, c.GetProperty("name").GetString());
            n++;
        }
        Assert.True(n >= 8);
    }
}

/// <summary>The hand-written wire types must match contracts/openapi.json exactly (decision D-13, adapted).</summary>
public class ContractTests
{
    private static readonly JsonElement Schemas = Load();

    private static JsonElement Load()
    {
        var d = new DirectoryInfo(AppContext.BaseDirectory);
        while (d is not null && !File.Exists(Path.Combine(d.FullName, "contracts", "openapi.json"))) d = d.Parent;
        using var doc = JsonDocument.Parse(File.ReadAllText(Path.Combine(d!.FullName, "contracts", "openapi.json")));
        return doc.RootElement.GetProperty("components").GetProperty("schemas").Clone();
    }

    public static IEnumerable<object[]> Types() => new (string, Type)[]
    {
        ("JobSummary", typeof(JobSummary)), ("JobListResponse", typeof(JobListResponse)), ("DocumentAccess", typeof(DocumentAccess)),
        ("ClaimResponse", typeof(ClaimResponse)), ("AttemptAuth", typeof(AttemptAuth)), ("RenewRequest", typeof(RenewRequest)),
        ("OutcomeRequest", typeof(OutcomeRequest)), ("OutcomeResponse", typeof(OutcomeResponse)), ("LeaseResponse", typeof(LeaseResponse)),
        ("AckResponse", typeof(AckResponse)), ("JobStatusResponse", typeof(JobStatusResponse)), ("RejectRequest", typeof(RejectRequest)),
        ("ResolveRequest", typeof(ResolveRequest)), ("EnrollRequest", typeof(EnrollRequest)), ("EnrollResponse", typeof(EnrollResponse)),
        ("PrintOptions", typeof(PrintOptions)),
    }.Select(t => new object[] { t.Item1, t.Item2 });

    [Theory, MemberData(nameof(Types))]
    public void Wire_type_has_exactly_the_fields_of_the_api_schema(string schema, Type type)
    {
        var apiFields = Schemas.GetProperty(schema).GetProperty("properties").EnumerateObject().Select(p => p.Name).OrderBy(x => x).ToArray();
        var ctor = type.GetConstructors().Single();
        var ourFields = ctor.GetParameters().Select(p => JsonNamingPolicy.SnakeCaseLower.ConvertName(p.Name!)).OrderBy(x => x).ToArray();
        Assert.Equal(apiFields, ourFields);
    }

    [Theory]
    [InlineData("JobStatus", typeof(JobStatus))]
    [InlineData("Outcome", typeof(Outcome))]
    [InlineData("Resolution", typeof(Resolution))]
    public void Enums_match_the_api(string schema, Type type)
    {
        var api = Schemas.GetProperty(schema).GetProperty("enum").EnumerateArray().Select(x => x.GetString()!).OrderBy(x => x).ToArray();
        var ours = Enum.GetNames(type).Select(n => JsonNamingPolicy.SnakeCaseLower.ConvertName(n)).OrderBy(x => x).ToArray();
        Assert.Equal(api, ours);
    }

    [Fact]
    public void Wire_serialisation_round_trips_a_realistic_poll_reply()
    {
        var json = """{"shop_code":"TST001","shop_name":"Shop","contract_version":1,"jobs":[{"job_id":"7a6d5f8e-1111-4222-8333-444455556666","order_short_code":"A91F","document_name":"cv.pdf","page_count":3,"copies":2,"color":false,"duplex":true,"page_range":null,"amount_paise":720,"status":"awaiting_approval","created_at":"2026-10-05T12:00:00+00:00","approval_expires_at":"2026-10-05T13:00:00+00:00","attempt_count":0}]}""";
        var r = JsonSerializer.Deserialize<JobListResponse>(json, Wire.Json)!;
        var j = Assert.Single(r.Jobs);
        Assert.Equal((JobStatus.AwaitingApproval, 720, "A91F", true), (j.Status, j.AmountPaise, j.OrderShortCode, j.Duplex));
        Assert.Null(j.PageRange);
        Assert.NotNull(j.ApprovalExpiresAt);
    }
}
