using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace AutoPrint.Core;

public sealed record DeviceCredentials(Guid DeviceId, string DeviceSecret, string ShopCode, string ShopName, string ApiBaseUrl);

public interface ICredentialStore
{
    DeviceCredentials? Load();
    void Save(DeviceCredentials credentials);
    void Clear();
}

/// <summary>
/// Stores the device secret encrypted with Windows DPAPI for the current user. The file is useless on another
/// PC or under another Windows account. Nothing here is ever logged.
/// </summary>
public sealed class DpapiCredentialStore(string path) : ICredentialStore
{
    private static readonly byte[] Entropy = Encoding.UTF8.GetBytes("AutoPrint.V4.device-credentials");

    public static string DefaultPath() =>
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "AutoPrintV4", "device.bin");

    /// <summary>Null when this PC is not connected to a shop, or the saved connection is damaged (connect again).
    /// A file that exists but cannot be READ right now (locked by antivirus or a backup) is different: that throws
    /// after a few tries, so a working connection is never thrown away because of a passing lock.</summary>
    public DeviceCredentials? Load()
    {
        byte[] bytes;
        for (int attempt = 0; ; attempt++)
        {
            if (!File.Exists(path)) return null;
            try { bytes = File.ReadAllBytes(path); break; }
            catch (FileNotFoundException) { return null; }
            catch (Exception e) when (e is IOException or UnauthorizedAccessException)
            {
                if (attempt >= 4) throw new IOException("The saved connection could not be read.", e);
                Thread.Sleep(150);
            }
        }
        try
        {
            var c = JsonSerializer.Deserialize<DeviceCredentials>(ProtectedData.Unprotect(bytes, Entropy, DataProtectionScope.CurrentUser));
            // a file that decrypts but is incomplete is as useless as a corrupt one
            if (c is null || c.DeviceId == Guid.Empty || string.IsNullOrEmpty(c.DeviceSecret) || string.IsNullOrEmpty(c.ShopCode)
                || !Uri.TryCreate(c.ApiBaseUrl, UriKind.Absolute, out _)) return null;
            return c with { ShopName = string.IsNullOrEmpty(c.ShopName) ? c.ShopCode : c.ShopName };
        }
        catch (CryptographicException) { return null; }      // different Windows user or corrupt file: enrol again
        catch (JsonException) { return null; }
    }

    public void Save(DeviceCredentials credentials)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        var protectedBytes = ProtectedData.Protect(JsonSerializer.SerializeToUtf8Bytes(credentials), Entropy, DataProtectionScope.CurrentUser);
        var tmp = path + ".tmp";
        File.WriteAllBytes(tmp, protectedBytes);
        File.Move(tmp, path, overwrite: true);
    }

    public void Clear() { if (File.Exists(path)) File.Delete(path); }
}

public sealed class MemoryCredentialStore : ICredentialStore
{
    private DeviceCredentials? _c;
    public DeviceCredentials? Load() => _c;
    public void Save(DeviceCredentials credentials) => _c = credentials;
    public void Clear() => _c = null;
}
