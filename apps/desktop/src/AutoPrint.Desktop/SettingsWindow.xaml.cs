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
        ColorBox.SelectionChanged += (_, _) => Warn();
        if (demoPrinters is not null) Fill(demoPrinters);
        else Loaded += async (_, _) =>
        {
            BwBox.IsEnabled = ColorBox.IsEnabled = TestBtn.IsEnabled = TestColorBtn.IsEnabled = false; BwWarn.Text = "Looking for printers…"; BwWarn.Visibility = Visibility.Visible;
            try { Fill(await Task.Run(PrinterCatalog.List)); }             // never on the window's thread: a sleeping network printer can take seconds
            catch (Exception e) { App.Log("printer list: " + SafeText.Describe(e)); BwWarn.Text = "Windows could not list the printers. Close this window and try again."; BwWarn.Visibility = Visibility.Visible; }
        };
    }

    private void Fill(IReadOnlyList<PrinterInfo> printers)
    {
        _printers = printers;
        // real printers first (the list comes sorted that way); the ones that make no paper say so in the list itself
        foreach (var p in printers) { BwBox.Items.Add(new PrinterChoice(p.Name, Mark(p))); ColorBox.Items.Add(new PrinterChoice(p.Name, Mark(p))); }
        ColorBox.Items.Insert(0, new PrinterChoice(Same, ""));
        // a printer that was chosen but has since gone stays visible, so the warning can name it
        if (_settings.BlackWhitePrinter is { Length: > 0 } bw && printers.All(p => p.Name != bw)) BwBox.Items.Add(new PrinterChoice(bw, "not installed any more"));
        // nothing chosen yet: offer a real printer, never one that makes a file or opens a window
        BwBox.SelectedValue = _settings.BlackWhitePrinter ?? PrinterCatalog.DefaultChoice(printers);
        ColorBox.SelectedValue = _settings.ColorPrinter is { } c && printers.Any(p => p.Name == c) ? c : Same;
        BwBox.IsEnabled = ColorBox.IsEnabled = TestBtn.IsEnabled = TestColorBtn.IsEnabled = true;
        Warn();
    }

    private static string Mark(PrinterInfo p) => p.Prompts ? "no paper: makes a file, may open a window" : p.IsVirtual ? "no paper: makes a file" : p.IsOffline ? "offline" : "";

    private void Warn()
    {
        var name = BwBox.SelectedValue as string;
        var p = _printers.FirstOrDefault(x => x.Name == name);
        (BwWarn.Text, string colour) = name is null ? ("Choose the printer your customers' documents should come out of.", "Muted")
            : p is null ? ("This printer is not installed on this computer any more. Choose another one.", "Err")
            : p.IsVirtual ? (PrinterCatalog.Warning(p.Name, true, p.Prompts) + " Choose your real printer for customer prints.", "Warn")
            : p.IsOffline ? ("Windows says this printer is offline. Check that it is switched on and connected.", "Warn")
            : ("", "Muted");
        BwWarn.Foreground = Ui.Brush(colour);
        BwWarn.Visibility = BwWarn.Text.Length > 0 ? Visibility.Visible : Visibility.Collapsed;

        var colourPrinter = ColorBox.SelectedValue is string cn && cn != Same ? _printers.FirstOrDefault(x => x.Name == cn) : null;
        ColorWarn.Text = colourPrinter is { IsVirtual: true } v ? PrinterCatalog.Warning(v.Name, true, v.Prompts) + " Colour prints would go there." : "";
        ColorWarn.Visibility = ColorWarn.Text.Length > 0 ? Visibility.Visible : Visibility.Collapsed;
        // a second machine gets its own test: shown only when the colour printer really is a different one
        TestColorBtn.Visibility = TestPrint.ColourTarget(ColorBox.SelectedValue as string, name, Same) is not null ? Visibility.Visible : Visibility.Collapsed;
    }

    private void OnTest(object sender, RoutedEventArgs e) => TestAsync(BwBox.SelectedValue as string, colour: false);

    /// <summary>The colour printer is tested on its own: it is a different machine, and the first button says nothing about it.</summary>
    private void OnTestColour(object sender, RoutedEventArgs e) => TestAsync(TestPrint.ColourTarget(ColorBox.SelectedValue as string, BwBox.SelectedValue as string, Same), colour: true);

    /// <summary>The print program a test page is handed to. Replaced only by the self-test, which must never start the real one.</summary>
    internal Func<IPrintEngine> TestEngine = () => new SumatraEngine(MainWindow.SumatraPath);
    private TestPrint? _test;
    private bool _testing;

    private async void TestAsync(string? name, bool colour)
    {
        if (_testing) return;                                              // one page for one press: a double click, or a press on the other button, sends nothing more
        Result.Visibility = Visibility.Visible;
        if (name is null) { Result.Foreground = Ui.Brush("Muted"); Result.Text = "Choose a printer first."; return; }
        _testing = true;
        bool prompts = _printers.FirstOrDefault(x => x.Name == name) is { Prompts: true };
        TestBtn.IsEnabled = TestColorBtn.IsEnabled = false; Result.Foreground = Ui.Brush("Muted");
        Result.Text = prompts ? "Sending a test page. A window may open on this computer: answer it or close it." : $"Sending a test page to {(colour ? "the colour printer" : "the printer")} “{name}”…";
        try
        {
            var test = _test ??= new TestPrint(() => TestEngine(), Path.Combine(Settings.Dir, "testpage"));
            var r = await Task.Run(() => test.SendAsync(name, colour));      // never on the window's thread: the print program can take a while
            if (r is null) return;                                           // another test page is still on its way
            Result.Foreground = Ui.Brush(r.Accepted ? "Ink" : "Err");
            Result.Text = TestPrint.Words(r, name, colour, prompts);
            if (!r.Accepted) App.Log("test page: " + r.Error);
        }
        catch (Exception x) { App.Log("test page: " + SafeText.Describe(x)); Result.Foreground = Ui.Brush("Err"); Result.Text = TestPrint.Unexpected; }
        finally { _testing = false; TestBtn.IsEnabled = TestColorBtn.IsEnabled = true; }
    }

    private void OnHear(object sender, RoutedEventArgs e) => Alerts.Chime();

    private void OnLogFolder(object sender, RoutedEventArgs e)
    {
        try { Directory.CreateDirectory(Settings.Dir); System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo("explorer.exe", $"\"{Settings.Dir}\"") { UseShellExecute = true }); }
        catch (Exception x) { App.Log("open log folder: " + x.GetType().Name); SaveNote.Text = "The folder could not be opened: " + Settings.Dir; }
    }

    private void OnSave(object sender, RoutedEventArgs e)
    {
        _settings.BlackWhitePrinter = BwBox.SelectedValue as string;
        _settings.ColorPrinter = ColorBox.SelectedValue as string is { } c && c != Same ? c : null;
        _settings.StartWithWindows = StartupBox.IsChecked == true;
        _settings.SoundOn = SoundBox.IsChecked == true;
        if (!_settings.Save()) { SaveNote.Text = "The settings could not be saved on this computer. They are used until AutoPrint closes."; return; }
        Settings.ApplyStartup(_settings.StartWithWindows);
        DialogResult = true;
    }
}

/// <summary>One line of a printer list: the name, and a few quiet words when it is not a printer to rely on.</summary>
public sealed record PrinterChoice(string Name, string Note)
{
    public string Gap => Note.Length > 0 ? "   " : "";
}
