using System.Security.Cryptography;
using System.Text;
using Microsoft.Data.Sqlite;

namespace AutoPrint.Core;

public enum AttemptState
{
    /// <summary>Claimed from the server. Nothing has been sent to the printer.</summary>
    Claimed = 0,
    /// <summary>The file is downloaded and verified. Still nothing sent.</summary>
    Downloaded = 1,
    /// <summary>Written immediately BEFORE the print process starts. From here the job may have reached the spooler.</summary>
    Intent = 2,
    /// <summary>The print process reported that the spooler accepted the job.</summary>
    Sent = 3,
    /// <summary>The final outcome reached the server. The only terminal state.</summary>
    Reported = 4,
}

public sealed record JournalEntry(
    Guid AttemptId, Guid JobId, string SpoolerJobName, string AttemptToken, string Printer, int ExpectedPages, AttemptState State);

/// <summary>
/// Local record of every print attempt, in SQLite WAL mode with synchronous FULL, so a power cut leaves a true
/// record. Rule (decision F-8): after a crash, an attempt that reached Intent is reported "uncertain" and never
/// reprinted automatically. The attempt token is stored encrypted with DPAPI.
/// </summary>
public sealed class Journal : IDisposable
{
    private static readonly byte[] Entropy = Encoding.UTF8.GetBytes("AutoPrint.V4.journal-token");
    private readonly string _cs;

    public Journal(string path)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(path))!);
        _cs = new SqliteConnectionStringBuilder { DataSource = path, Pooling = false }.ToString();
        using var c = Open();
        Exec(c, "PRAGMA journal_mode=WAL;");
        Exec(c, """
            CREATE TABLE IF NOT EXISTS attempts (
              attempt_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, spooler_job_name TEXT NOT NULL,
              token BLOB NOT NULL, printer TEXT NOT NULL, expected_pages INTEGER NOT NULL,
              state INTEGER NOT NULL, outcome TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            """);
    }

    private SqliteConnection Open()
    {
        var c = new SqliteConnection(_cs);
        c.Open();
        Exec(c, "PRAGMA synchronous=FULL;");
        return c;
    }

    private static void Exec(SqliteConnection c, string sql, params (string, object)[] p)
    {
        using var cmd = c.CreateCommand();
        cmd.CommandText = sql;
        foreach (var (k, v) in p) cmd.Parameters.AddWithValue(k, v);
        cmd.ExecuteNonQuery();
    }

    private static byte[] Protect(string s) => ProtectedData.Protect(Encoding.UTF8.GetBytes(s), Entropy, DataProtectionScope.CurrentUser);
    private static string Unprotect(byte[] b) => Encoding.UTF8.GetString(ProtectedData.Unprotect(b, Entropy, DataProtectionScope.CurrentUser));

    public void Begin(Guid attemptId, Guid jobId, string spoolerJobName, string token, string printer, int expectedPages)
    {
        using var c = Open();
        var now = DateTimeOffset.UtcNow.ToString("O");
        Exec(c, "INSERT INTO attempts VALUES ($a,$j,$n,$t,$p,$e,$s,NULL,$now,$now)",
            ("$a", attemptId.ToString()), ("$j", jobId.ToString()), ("$n", spoolerJobName), ("$t", Protect(token)),
            ("$p", printer), ("$e", expectedPages), ("$s", (int)AttemptState.Claimed), ("$now", now));
    }

    public void Advance(Guid attemptId, AttemptState state)
    {
        using var c = Open();
        Exec(c, "UPDATE attempts SET state=$s, updated_at=$now WHERE attempt_id=$a AND state < $s",
            ("$s", (int)state), ("$now", DateTimeOffset.UtcNow.ToString("O")), ("$a", attemptId.ToString()));
    }

    public void MarkReported(Guid attemptId, string outcome)
    {
        using var c = Open();
        Exec(c, "UPDATE attempts SET state=$s, outcome=$o, updated_at=$now WHERE attempt_id=$a",
            ("$s", (int)AttemptState.Reported), ("$o", outcome), ("$now", DateTimeOffset.UtcNow.ToString("O")), ("$a", attemptId.ToString()));
    }

    /// <summary>Every attempt whose final outcome never reached the server.</summary>
    public IReadOnlyList<JournalEntry> Unreported()
    {
        using var c = Open();
        using var cmd = c.CreateCommand();
        cmd.CommandText = "SELECT attempt_id, job_id, spooler_job_name, token, printer, expected_pages, state FROM attempts WHERE state < $r ORDER BY created_at";
        cmd.Parameters.AddWithValue("$r", (int)AttemptState.Reported);
        var list = new List<JournalEntry>();
        using var r = cmd.ExecuteReader();
        while (r.Read())
        {
            string token;
            try { token = Unprotect((byte[])r["token"]); }
            catch (CryptographicException) { continue; }    // written by another Windows user: cannot be reported from here
            list.Add(new JournalEntry(Guid.Parse(r.GetString(0)), Guid.Parse(r.GetString(1)), r.GetString(2), token,
                                      r.GetString(4), r.GetInt32(5), (AttemptState)r.GetInt32(6)));
        }
        return list;
    }

    public AttemptState? StateOf(Guid attemptId)
    {
        using var c = Open();
        using var cmd = c.CreateCommand();
        cmd.CommandText = "SELECT state FROM attempts WHERE attempt_id=$a";
        cmd.Parameters.AddWithValue("$a", attemptId.ToString());
        var v = cmd.ExecuteScalar();
        return v is null ? null : (AttemptState)Convert.ToInt32(v);
    }

    /// <summary>Housekeeping: keep 30 days of reported attempts, no more.</summary>
    public void Prune(TimeSpan keep)
    {
        using var c = Open();
        Exec(c, "DELETE FROM attempts WHERE state=$r AND updated_at < $cut",
            ("$r", (int)AttemptState.Reported), ("$cut", (DateTimeOffset.UtcNow - keep).ToString("O")));
    }

    public void Dispose() { }
}
