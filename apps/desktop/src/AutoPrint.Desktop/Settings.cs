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

    /// <summary>Play a short sound when a request arrives, and again while one is still waiting for an answer.</summary>
    public bool SoundOn { get; set; } = true;

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
        catch (IOException) { }
    }

    private static string? _dir;
    /// <summary>Where settings, the journal, the log and work files live. The UI self-test points this at a temporary
    /// folder before anything else runs, so it can never touch a real shop's data.</summary>
    public static string Dir
    {
        get => _dir ?? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "AutoPrintV4");
        set => _dir = value;
    }
    private static string FilePath => Path.Combine(Dir, "settings.json");

    /// <summary>Never throws: a settings file that is damaged or cannot be read means "start with the defaults"
    /// (the app then asks for the printer again), not an app that will not open.</summary>
    public static Settings Load()
    {
        try
        {
            if (File.Exists(FilePath)) return JsonSerializer.Deserialize<Settings>(File.ReadAllText(FilePath)) is { ApiBaseUrl.Length: > 0 } s ? s : new();
        }
        catch (Exception e) { App.Log("settings unreadable, using defaults: " + e.GetType().Name); }
        return new();
    }

    /// <summary>Written to a second file and swapped in, so a power cut cannot leave half a settings file. False when it could not be saved.</summary>
    public bool Save()
    {
        try
        {
            Directory.CreateDirectory(Dir);
            var tmp = FilePath + ".tmp";
            File.WriteAllText(tmp, JsonSerializer.Serialize(this, new JsonSerializerOptions { WriteIndented = true }));
            File.Move(tmp, FilePath, overwrite: true);
            return true;
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException) { App.Log("settings not saved: " + e.GetType().Name); return false; }
    }

    /// <summary>Colour jobs go to the colour printer when one is set; everything else to the black-and-white one.</summary>
    public string PrinterFor(AutoPrint.Core.Shop.PrintOptions o) => PrinterFor(o.Color);
    public string PrinterFor(bool colour) => (colour && !string.IsNullOrEmpty(ColorPrinter) ? ColorPrinter : BlackWhitePrinter) ?? "";
}
