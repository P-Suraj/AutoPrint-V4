using System.Security.Cryptography;

namespace AutoPrint.Core.Agent;

public sealed class DownloadFailedException(string reason, Exception? inner = null) : Exception(reason, inner)
{
    public string Reason { get; } = reason;
}

public interface IDownloader
{
    /// <summary>Downloads to <paramref name="path"/>, verifying size and SHA-256. Throws DownloadFailedException.</summary>
    Task DownloadAsync(string url, string expectedSha256, long expectedBytes, string path, CancellationToken ct);
}

public sealed class HttpDownloader(HttpClient http) : IDownloader
{
    public async Task DownloadAsync(string url, string expectedSha256, long expectedBytes, string path, CancellationToken ct)
    {
        var part = path + ".part";
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        try
        {
            using var res = await http.GetAsync(url, HttpCompletionOption.ResponseHeadersRead, ct);
            if (!res.IsSuccessStatusCode) throw new DownloadFailedException($"download_http_{(int)res.StatusCode}");
            using var sha = SHA256.Create();
            long total = 0;
            await using (var src = await res.Content.ReadAsStreamAsync(ct))
            await using (var dst = new FileStream(part, FileMode.Create, FileAccess.Write, FileShare.None, 81920, useAsync: true))
            {
                var buf = new byte[81920];
                int n;
                while ((n = await src.ReadAsync(buf, ct)) > 0)
                {
                    total += n;
                    if (total > expectedBytes) throw new DownloadFailedException("download_larger_than_expected");
                    sha.TransformBlock(buf, 0, n, null, 0);
                    await dst.WriteAsync(buf.AsMemory(0, n), ct);
                }
                sha.TransformFinalBlock([], 0, 0);
            }
            if (total != expectedBytes) throw new DownloadFailedException("download_size_mismatch");
            if (!string.Equals(Convert.ToHexString(sha.Hash!), expectedSha256, StringComparison.OrdinalIgnoreCase))
                throw new DownloadFailedException("download_sha256_mismatch");   // never print a file that is not the approved one
            File.Move(part, path, overwrite: true);
        }
        catch (HttpRequestException e) { throw new DownloadFailedException("download_unreachable", e); }
        catch (IOException e) when (e is not FileNotFoundException) { throw new DownloadFailedException("download_io_error", e); }
        finally { try { File.Delete(part); } catch (IOException) { /* best effort */ } }
    }
}
