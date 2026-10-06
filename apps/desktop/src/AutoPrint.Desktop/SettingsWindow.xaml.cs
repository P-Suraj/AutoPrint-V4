using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using AutoPrint.Core;
using AutoPrint.Core.Agent;
using AutoPrint.Core.Printing;
using AutoPrint.Core.Shop;

namespace AutoPrint.Desktop;

public partial class SettingsWindow : Window
{
    private const string Same = "Same printer";
    private readonly Settings _settings;
    private IReadOnlyList<PrinterInfo> _printers = Array.Empty<PrinterInfo>();

    /// <param name="demoPrinters">Self-test only: a made-up list, so the real printers of this PC are never read.</param>
    public SettingsWindow(Settings settings, SupportInfo info, IReadOnlyList<PrinterInfo>? demoPrinters = null)
    {
        _settings = settings; InitializeComponent();
        MaxHeight = Math.Max(420, SystemParameters.WorkArea.Height - 24);     // taller than a small screen: the middle scrolls, Save stays in view
        StartupBox.IsChecked = settings.StartWithWindows;
        SoundBox.IsChecked = settings.SoundOn;
        ShopText.Text = info.Shop; ConnText.Text = info.Connection; PcText.Text = demoPrinters is null ? Environment.MachineName : "SHOP-PC"; VersionText.Text = "AutoPrint " + info.Version;
        DisconnectText.Text = $"To disconnect this computer from the shop: open your private shop link, find “{PcText.Text}” under “Your computers” and press Disconnect. "
            + "This app then shows a new code. It cannot be done from here, so that only the shop's owner can do it.";
        BwBox.SelectionChanged += (_, _) => Warn();
        if (demoPrinters is not null) Fill(demoPrinters);
        else Loaded += async (_, _) =>
        {
            BwBox.IsEnabled = ColorBox.IsEnabled = TestBtn.IsEnabled = false; BwWarn.Text = "Looking for printers…"; BwWarn.Visibility = Visibility.Visible;
            try { Fill(await Task.Run(PrinterCatalog.List)); }             // never on the window's thread: a sleeping network printer can take seconds
            catch (Exception e) { App.Log("printer list: " + SafeText.Describe(e)); BwWarn.Text = "Windows could not list the printers. Close this window and try again."; BwWarn.Visibility = Visibility.Visible; }
        };
    }

    private void Fill(IReadOnlyList<PrinterInfo> printers)
    {
        _printers = printers;
        foreach (var p in printers) { BwBox.Items.Add(p.Name); ColorBox.Items.Add(p.Name); }
        ColorBox.Items.Insert(0, Same);
        // a printer that was chosen but has since gone stays visible, so the warning can name it
        if (_settings.BlackWhitePrinter is { Length: > 0 } bw && !BwBox.Items.Contains(bw)) BwBox.Items.Add(bw);
        BwBox.SelectedItem = _settings.BlackWhitePrinter ?? printers.FirstOrDefault(p => !p.IsVirtual && !p.IsOffline)?.Name;
        ColorBox.SelectedItem = _settings.ColorPrinter is { } c && ColorBox.Items.Contains(c) ? c : Same;
        BwBox.IsEnabled = ColorBox.IsEnabled = TestBtn.IsEnabled = true;
        Warn();
    }

    private void Warn()
    {
        var name = BwBox.SelectedItem as string;
        var p = _printers.FirstOrDefault(x => x.Name == name);
        (BwWarn.Text, string colour) = name is null ? ("Choose the printer your customers' documents should come out of.", "Muted")
            : p is null ? ("This printer is not installed on this computer any more. Choose another one.", "Err")
            : p.IsVirtual ? ("This one makes a file, not paper.", "Warn")
            : p.IsOffline ? ("Windows says this printer is offline. Check that it is switched on and connected.", "Warn")
            : ("", "Muted");
        BwWarn.Foreground = Ui.Brush(colour);
        BwWarn.Visibility = BwWarn.Text.Length > 0 ? Visibility.Visible : Visibility.Collapsed;
    }

    private async void OnTest(object sender, RoutedEventArgs e)
    {
        var name = BwBox.SelectedItem as string;
        if (name is null) { Result.Text = "Choose a printer first."; return; }
        TestBtn.IsEnabled = false; Result.Foreground = Ui.Brush("Muted"); Result.Text = "Sending a test page…";
        var dir = Path.Combine(Settings.Dir, "testpage");                  // its own folder: a customer job cleaning the work folder never touches it
        var jobName = "aptest_" + Guid.NewGuid().ToString("N");
        var file = Path.Combine(dir, jobName + ".pdf");
        try
        {
            var r = await Task.Run(async () =>
            {
                Directory.CreateDirectory(dir);
                await File.WriteAllBytesAsync(file, TestPage.Build("AutoPrint test page", DateTime.Now.ToString("g")));
                return await new SumatraEngine(MainWindow.SumatraPath).SubmitAsync(new PrintRequest(file, name, new PrintOptions(1, false, false, null), jobName, 1), CancellationToken.None);
            });
            Result.Foreground = Ui.Brush(r.Accepted ? "Ink" : "Err");
            Result.Text = r.Accepted ? "Sent to the printer. Check that a page came out." : r.Error switch
            {
                SumatraEngine.NotReadyReason => "AutoPrint's print program is missing or damaged. Install AutoPrint again.",
                "printer_not_found" => "Windows cannot find this printer any more. Choose another one.",
                "engine_timeout" => "The printer did not take the page. Check that it is switched on and connected.",
                _ => "It did not work. Check the printer and try again.",
            };
            if (!r.Accepted) App.Log("test page: " + r.Error);
        }
        catch (Exception x) { App.Log("test page: " + SafeText.Describe(x)); Result.Foreground = Ui.Brush("Err"); Result.Text = "It did not work. Check the printer and try again."; }
        finally { await WorkFiles.DeleteAsync(file); TestBtn.IsEnabled = true; }
    }

    private void OnHear(object sender, RoutedEventArgs e) => Alerts.Chime();

    private void OnLogFolder(object sender, RoutedEventArgs e)
    {
        try { Directory.CreateDirectory(Settings.Dir); System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo("explorer.exe", $"\"{Settings.Dir}\"") { UseShellExecute = true }); }
        catch (Exception x) { App.Log("open log folder: " + x.GetType().Name); SaveNote.Text = "The folder could not be opened: " + Settings.Dir; }
    }

    private void OnSave(object sender, RoutedEventArgs e)
    {
        _settings.BlackWhitePrinter = BwBox.SelectedItem as string;
        _settings.ColorPrinter = ColorBox.SelectedItem as string is { } c && c != Same ? c : null;
        _settings.StartWithWindows = StartupBox.IsChecked == true;
        _settings.SoundOn = SoundBox.IsChecked == true;
        if (!_settings.Save()) { SaveNote.Text = "The settings could not be saved on this computer. They are used until AutoPrint closes."; return; }
        Settings.ApplyStartup(_settings.StartWithWindows);
        DialogResult = true;
    }
}
