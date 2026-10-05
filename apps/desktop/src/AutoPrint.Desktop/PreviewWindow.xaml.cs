using System;
using System.IO;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Media.Imaging;
using AutoPrint.Core.Agent;
using AutoPrint.Core.Shop;

namespace AutoPrint.Desktop;

/// <summary>
/// Shows the customer document before the shopkeeper approves it, using the PDF viewer built into Windows 10 and 11.
/// The file is downloaded to a private temp folder, checked against its SHA-256, and deleted when the window closes.
/// </summary>
public partial class PreviewWindow : Window
{
    private readonly JobSummary _job;
    private readonly IShopApi _api;
    private readonly HttpClient _http;
    private readonly bool _canDecide;
    private readonly CancellationTokenSource _cts = new();
    private readonly string _dir = Path.Combine(Settings.Dir, "preview", Guid.NewGuid().ToString("N"));
    private PdfRender? _pdf;
    private uint _page;

    /// <summary>True when the shopkeeper chose Approve or Reject here, so the caller can refresh straight away.</summary>
    public bool Decided { get; private set; }

    public PreviewWindow(JobSummary job, IShopApi api, HttpClient http, bool canDecide)
    {
        _job = job; _api = api; _http = http; _canDecide = canDecide;
        InitializeComponent();
        Title1.Text = job.DocumentName;
        var d = $"{job.PageCount} pages  ·  {job.Copies} {(job.Copies == 1 ? "copy" : "copies")}  ·  {(job.Color ? "Colour" : "Black & white")}  ·  {(job.Duplex ? "Both sides" : "One side")}";
        if (!string.IsNullOrWhiteSpace(job.PageRange)) d += $"  ·  pages {job.PageRange}";
        Detail.Text = d;
        Actions.Visibility = job.Status == JobStatus.AwaitingApproval ? Visibility.Visible : Visibility.Collapsed;
        ApproveBtn.IsEnabled = canDecide;
        Loaded += async (_, _) => await LoadAsync();
        Closed += (_, _) => { _cts.Cancel(); try { Directory.Delete(_dir, true); } catch (IOException) { } };
    }

    private async Task LoadAsync()
    {
        try
        {
            var doc = await _api.DocumentAsync(_job.JobId, _cts.Token);
            var path = Path.Combine(_dir, "preview.pdf");
            await new HttpDownloader(_http).DownloadAsync(doc.DownloadUrl, doc.Sha256, doc.ByteSize, path, _cts.Token);
            _pdf = await PdfRender.OpenAsync(path);
            Message.Visibility = Visibility.Collapsed;
            await ShowAsync(0);
        }
        catch (OperationCanceledException) { }
        catch (Exception e) when (e is ServerUnreachableException or ApiRejectedException or DownloadFailedException)
        {
            Message.Text = "The file could not be loaded. Check the internet connection and try again.";
        }
        catch (Exception e) when (e is System.Runtime.InteropServices.COMException or IOException)
        {
            Message.Text = "Windows could not display this file. You can still approve or reject it.";
            App.Log("preview: " + e.GetType().Name);
        }
    }

    private async Task ShowAsync(uint index)
    {
        if (_pdf is null || index >= _pdf.PageCount) return;
        _page = index;
        double w = Math.Min(1100, Math.Max(600, ActualWidth * 1.4));           // sharp enough to read, small enough to be quick
        PageImage.Source = await _pdf.PageAsync(index, (uint)w);
        PageText.Text = $"  Page {index + 1} of {_pdf.PageCount}  ";
        Prev.IsEnabled = index > 0;
        Next.IsEnabled = index + 1 < _pdf.PageCount;
    }

    private async void OnPrev(object sender, RoutedEventArgs e) => await ShowAsync(_page - 1);
    private async void OnNext(object sender, RoutedEventArgs e) => await ShowAsync(_page + 1);

    private async void OnApprove(object sender, RoutedEventArgs e) => await Decide(() => _api.ApproveAsync(_job.JobId, CancellationToken.None));
    private async void OnReject(object sender, RoutedEventArgs e) => await Decide(() => _api.RejectAsync(_job.JobId, null, CancellationToken.None));

    private async Task Decide(Func<Task> action)
    {
        ApproveBtn.IsEnabled = RejectBtn.IsEnabled = false;
        try { await action(); Decided = true; Close(); }
        catch (ServerUnreachableException) { Message.Visibility = Visibility.Visible; Message.Text = "No connection. Try again in a moment."; ApproveBtn.IsEnabled = _canDecide; RejectBtn.IsEnabled = true; }
        catch (ApiRejectedException ex) { Message.Visibility = Visibility.Visible; Message.Text = ex.Message; Decided = true; }
    }
}
