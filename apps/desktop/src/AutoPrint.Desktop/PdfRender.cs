using System;
using System.Threading.Tasks;
using System.Windows.Media.Imaging;
using Windows.Data.Pdf;
using Windows.Storage;
using Windows.Storage.Streams;

namespace AutoPrint.Desktop;

/// <summary>Draws PDF pages with the viewer built into Windows 10 and 11 (no extra program or library).</summary>
public sealed class PdfRender
{
    private readonly PdfDocument _pdf;
    private PdfRender(PdfDocument pdf) { _pdf = pdf; }

    public uint PageCount => _pdf.PageCount;

    public static async Task<PdfRender> OpenAsync(string path)
    {
        var file = await StorageFile.GetFileFromPathAsync(path);
        return new PdfRender(await PdfDocument.LoadFromFileAsync(file));
    }

    public async Task<BitmapImage> PageAsync(uint index, uint width)
    {
        using var page = _pdf.GetPage(index);
        using var mem = new InMemoryRandomAccessStream();
        await page.RenderToStreamAsync(mem, new PdfPageRenderOptions { DestinationWidth = width });
        mem.Seek(0);
        var bmp = new BitmapImage();
        bmp.BeginInit();
        bmp.CacheOption = BitmapCacheOption.OnLoad;
        bmp.StreamSource = System.IO.WindowsRuntimeStreamExtensions.AsStreamForRead(mem);
        bmp.EndInit();
        bmp.Freeze();
        return bmp;
    }
}
