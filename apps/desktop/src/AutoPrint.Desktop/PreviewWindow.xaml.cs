using System;
using System.IO;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Input;
using AutoPrint.Core;
using AutoPrint.Core.Agent;
using AutoPrint.Core.Shop;

namespace AutoPrint.Desktop;

public enum PreviewChoice { None, Approve, Reject }

/// <summary>
/// Shows the customer document before the shopkeeper approves it, using the PDF viewer built into Windows 10 and 11.
/// The file is downloaded to a private temp folder, checked against its SHA-256, read into memory and deleted at
/// once: nothing of it is on the disk while the window is open, and nothing is left when it closes. The window only
/// records the shopkeeper's choice; the main window sends it, so there is one place where answers are sent.
/// </summary>
public partial class PreviewWindow : Window
{
    private readonly JobSummary _job;
    private readonly IShopApi? _api;
    private readonly HttpClient? _http;
    private readonly string? _block;
    private readonly byte[]? _demo;
    private readonly CancellationTokenSource _cts = new();
    private readonly string _dir = Path.Combine(Settings.Dir, "preview", Guid.NewGuid().ToString("N"));
    private PdfRender? _pdf;
    private uint _page;
    private bool _gone;

    public Guid JobId => _job.JobId;
    public PreviewChoice Choice { get; private set; }
    /// <summary>Completes when the first page is on screen or loading has failed (used by the self-test).</summary>
    public Task Ready { get; private set; } = Task.CompletedTask;

    /// <param name="block">Why this request cannot be approved right now (no printer chosen, printer gone), or null.</param>
    /// <param name="demo">Self-test only: a PDF to show instead of downloading one.</param>
    public PreviewWindow(JobSummary job, IShopApi? api, HttpClient? http, string? block, byte[]? demo = null)
    {
        _job = job; _api = api; _http = http; _block = block; _demo = demo;
        InitializeComponent();
        Code.Text = job.OrderShortCode;
        Title1.Text = job.DocumentName; Title1.ToolTip = job.DocumentName;
        Detail.Text = $"{JobText.Pages(job)}   ·   {JobText.Plural(job.Copies, "copy", "copies")}   ·   {JobText.Colour(job)}   ·   {JobText.SidesChoice(job)}";
        AmountText.Text = JobText.Money(job.AmountPaise);
        Height = Math.Min(Height, SystemParameters.WorkArea.Height); Width = Math.Min(Width, SystemParameters.WorkArea.Width);
        JobChanged(job);
        Loaded += (_, _) => Ready = LoadAsync();
        PreviewKeyDown += (_, e) => { if (e.Key == Key.Escape) { Close(); e.Handled = true; } };
        Closed += (_, _) =>
        {
            _cts.Cancel();
            PageImage.Source = null; _pdf?.Dispose(); _pdf = null;            // give the page bitmap and the document back at once
            WorkFiles.CleanStale(_dir);
            try { Directory.Delete(_dir, true); } catch (Exception e) when (e is IOException or UnauthorizedAccessException) { /* swept at the next start */ }
        };
    }

    /// <summary>Called by the main window on every refresh of the queue: null or a different state means the request
    /// is not waiting any more (the customer cancelled it, or it ran out of time) and can no longer be answered here.</summary>
    public void JobChanged(JobSummary? now)
    {
        bool waiting = now is { Status: JobStatus.AwaitingApproval };
        if (!waiting && !_gone && IsLoaded)
        {
            _gone = true;
            ShowMessage(now?.Status == JobStatus.Cancelled ? "The customer cancelled this request. There is nothing to approve." : "This request is not waiting for an answer any more.");
        }
        ApproveBtn.IsEnabled = waiting && _block is null;
        RejectBtn.IsEnabled = waiting;
        Why.Text = !waiting ? (IsLoaded ? "No longer waiting for an answer." : "") : _block ?? "";
        if (!waiting || _block is not null) Why.Foreground = Ui.Brush("Err");
    }

    private void ShowMessage(string? text)
    {
        MessageBox1.Visibility = text is null ? Visibility.Collapsed : Visibility.Visible;
        if (text is not null) { Message.Text = text; Motion.Fade(MessageBox1); }
    }

    private async Task LoadAsync()
    {
        try
        {
            byte[] bytes;
            if (_demo is not null) bytes = _demo;
            else
            {
                var doc = await _api!.DocumentAsync(_job.JobId, _cts.Token);
                var path = Path.Combine(_dir, "preview.pdf");
                await new HttpDownloader(_http!, TimeSpan.FromMinutes(3)).DownloadAsync(doc.DownloadUrl, doc.Sha256, doc.ByteSize, path, _cts.Token);
                bytes = await File.ReadAllBytesAsync(path, _cts.Token);
                await WorkFiles.DeleteAsync(path);                      // the copy on disk is gone before the first page shows
            }
            _pdf = await PdfRender.OpenAsync(bytes);
            await ShowAsync(0);
            if (!_gone) ShowMessage(null);
        }
        catch (OperationCanceledException) { }
        catch (Exception e) when (e is ServerUnreachableException or ApiRejectedException or DownloadFailedException)
        {
            if (!_gone) ShowMessage("The file could not be loaded. Check the internet connection, close this window and try again.");
        }
        catch (Exception e)
        {
            // a file Windows' viewer cannot draw is still a file the printer may print: the choice stays with the shopkeeper
            if (!_gone) ShowMessage("Windows could not show this file. You can still approve or reject it.");
            App.Log("preview: " + SafeText.Describe(e));
        }
    }

    private async Task ShowAsync(uint index)
    {
        if (_pdf is not { } pdf || index >= pdf.PageCount) return;
        Prev.IsEnabled = Next.IsEnabled = false;                         // one page at a time; fast clicks cannot pile up renders
        double scale = System.Windows.Media.VisualTreeHelper.GetDpi(this).DpiScaleX;
        double shown = Math.Max(420, Math.Min(900, ActualWidth - 80));
        var image = await pdf.PageAsync(index, (uint)(shown * scale));  // exactly the pixels the screen needs: sharp at 100% and 150%
        if (_pdf is null) return;                                        // closed while it was drawing
        _page = index;
        PageImage.Source = image; PageImage.Width = shown;
        Motion.Fade(PageImage);
        PageText.Text = $"Page {index + 1} of {pdf.PageCount}";
        Prev.IsEnabled = index > 0;
        Next.IsEnabled = index + 1 < pdf.PageCount;
    }

    private async void OnPrev(object sender, RoutedEventArgs e) { try { await ShowAsync(_page - 1); } catch (Exception x) { App.Log("preview page: " + SafeText.Describe(x)); } }
    private async void OnNext(object sender, RoutedEventArgs e) { try { await ShowAsync(_page + 1); } catch (Exception x) { App.Log("preview page: " + SafeText.Describe(x)); } }

    private void OnApprove(object sender, RoutedEventArgs e) { Choice = PreviewChoice.Approve; Close(); }
    private void OnReject(object sender, RoutedEventArgs e) { Choice = PreviewChoice.Reject; Close(); }
}
