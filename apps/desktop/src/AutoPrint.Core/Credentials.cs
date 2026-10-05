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

    public DeviceCredentials? Load()
    {
        if (!File.Exists(path)) return null;
        try
        {
            var plain = ProtectedData.Unprotect(File.ReadAllBytes(path), Entropy, DataProtectionScope.CurrentUser);
            return JsonSerializer.Deserialize<DeviceCredentials>(plain);
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
