using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading;
using System.Windows;
using AutoPrint.Core.Printing;
using AutoPrint.Core.Shop;

namespace AutoPrint.Desktop;

public partial class SettingsWindow : Window
{
    private const string None = "(none)";
    private readonly Settings _settings;
    private readonly IReadOnlyList<PrinterInfo> _printers = PrinterCatalog.List();

    public SettingsWindow(Settings settings)
    {
        _settings = settings; InitializeComponent();
        foreach (var p in _printers) { BwBox.Items.Add(p.Name); ColorBox.Items.Add(p.Name); }
        ColorBox.Items.Insert(0, None);
        BwBox.SelectedItem = settings.BlackWhitePrinter ?? _printers.FirstOrDefault(p => !p.IsVirtual && !p.IsOffline)?.Name;
        ColorBox.SelectedItem = settings.ColorPrinter ?? None;
        StartupBox.IsChecked = settings.StartWithWindows;
        BwBox.SelectionChanged += (_, _) => Warn();
        Warn();
    }

    private void Warn()
    {
        var p = _printers.FirstOrDefault(x => x.Name == (BwBox.SelectedItem as string));
        BwWarn.Text = p is null ? "" : p.IsVirtual ? "This is a virtual printer. It makes a file, not paper." : p.IsOffline ? "Windows says this printer is offline." : "";
    }

    private async void OnTest(object sender, RoutedEventArgs e)
    {
        var name = BwBox.SelectedItem as string;
        if (name is null) { Result.Text = "Choose a printer first."; return; }
        var sumatra = Path.Combine(AppContext.BaseDirectory, "tools", "SumatraPDF.exe");
        var dir = Path.Combine(Settings.Dir, "work"); Directory.CreateDirectory(dir);
        var jobName = "aptest_" + Guid.NewGuid().ToString("N");
        var file = Path.Combine(dir, jobName + ".pdf");
        await File.WriteAllBytesAsync(file, TestPage.Build("AutoPrint test page", DateTime.Now.ToString("g")));
        try
        {
            Result.Text = "Sending…";
            var r = await new SumatraEngine(sumatra).SubmitAsync(new PrintRequest(file, name, new PrintOptions(1, false, false, null), jobName, 1), CancellationToken.None);
            Result.Text = r.Accepted ? "Sent. Check the printer." : "It did not work: " + r.Error;
        }
        finally { try { File.Delete(file); } catch (IOException) { } }
    }

    private void OnSave(object sender, RoutedEventArgs e)
    {
        _settings.BlackWhitePrinter = BwBox.SelectedItem as string;
        _settings.ColorPrinter = ColorBox.SelectedItem as string is { } c && c != None ? c : null;
        _settings.StartWithWindows = StartupBox.IsChecked == true;
        _settings.Save();
        Settings.ApplyStartup(_settings.StartWithWindows);
        DialogResult = true;
    }
}
