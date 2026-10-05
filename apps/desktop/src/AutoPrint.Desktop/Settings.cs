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
