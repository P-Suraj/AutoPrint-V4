using System;
using System.IO;
using System.Text.Json;

namespace AutoPrint.Desktop;

/// <summary>Non-secret settings, stored per Windows user. Secrets live in the DPAPI credential store.</summary>
public sealed class Settings
{
    public string ApiBaseUrl { get; set; } = "https://autoprint-v4.vercel.app";
    public string? BlackWhitePrinter { get; set; }
    public string? ColorPrinter { get; set; }

    /// <summary>Start AutoPrint (in the tray, no window) when this Windows user signs in. On by default: a shop PC that restarts must keep receiving jobs.</summary>
    public bool StartWithWindows { get; set; } = true;

    private const string RunKey = @"Software\Microsoft\Windows\CurrentVersion\Run";

    /// <summary>Per-user, no administrator rights: one value under HKCU...\Run.</summary>
    public static void ApplyStartup(bool on)
    {
        try
        {
            using var key = Microsoft.Win32.Registry.CurrentUser.CreateSubKey(RunKey);
            if (on) key.SetValue("AutoPrint", $"\"{Environment.ProcessPath}\" --background");
            else key.DeleteValue("AutoPrint", throwOnMissingValue: false);
        }
        catch (System.Security.SecurityException) { /* locked down by policy: the setting just has no effect */ }
        catch (UnauthorizedAccessException) { }
    }

    public static string Dir => Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "AutoPrintV4");
    private static string FilePath => Path.Combine(Dir, "settings.json");

    public static Settings Load()
    {
        try { if (File.Exists(FilePath)) return JsonSerializer.Deserialize<Settings>(File.ReadAllText(FilePath)) ?? new(); }
        catch (Exception e) when (e is IOException or JsonException) { /* start fresh */ }
        return new();
    }

    public void Save()
    {
        Directory.CreateDirectory(Dir);
        File.WriteAllText(FilePath, JsonSerializer.Serialize(this, new JsonSerializerOptions { WriteIndented = true }));
    }

    /// <summary>Colour jobs go to the colour printer when one is set; everything else to the black-and-white one.</summary>
    public string PrinterFor(AutoPrint.Core.Shop.PrintOptions o) =>
        (o.Color && !string.IsNullOrEmpty(ColorPrinter) ? ColorPrinter : BlackWhitePrinter) ?? "";
}
