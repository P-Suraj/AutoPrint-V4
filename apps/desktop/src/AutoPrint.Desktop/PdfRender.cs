using System;
using System.IO;
using System.Runtime.InteropServices.WindowsRuntime;
using System.Threading.Tasks;
using System.Windows.Media.Imaging;
using Windows.Data.Pdf;
using Windows.Storage.Streams;

namespace AutoPrint.Desktop;

/// <summary>
/// Draws PDF pages with the viewer built into Windows 10 and 11 (no extra program or library). The document is held
/// in memory, never as an open file, so the downloaded copy can be deleted the moment it has been read. Rendering and
/// decoding happen off the window's thread.
/// </summary>
public sealed class PdfRender : IDisposable
{
    private readonly PdfDocument _pdf;
    private readonly InMemoryRandomAccessStream _source;
    private PdfRender(PdfDocument pdf, InMemoryRandomAccessStream source) { _pdf = pdf; _source = source; }

    public uint PageCount => _pdf.PageCount;

    public static async Task<PdfRender> OpenAsync(byte[] bytes)
    {
        var mem = new InMemoryRandomAccessStream();
        try
        {
            await mem.WriteAsync(bytes.AsBuffer());
            mem.Seek(0);
            return new PdfRender(await PdfDocument.LoadFromStreamAsync(mem), mem);
        }
        catch { mem.Dispose(); throw; }
    }

    public static async Task<PdfRender> OpenAsync(string path) => await OpenAsync(await File.ReadAllBytesAsync(path));

    public async Task<BitmapSource> PageAsync(uint index, uint width)
    {
        byte[] png;
        using (var page = _pdf.GetPage(index))
        using (var mem = new InMemoryRandomAccessStream())
        {
            await page.RenderToStreamAsync(mem, new PdfPageRenderOptions { DestinationWidth = width });
            png = new byte[mem.Size];
            mem.Seek(0);
            await mem.ReadAsync(png.AsBuffer(), (uint)png.Length, InputStreamOptions.None);
        }
        return await Task.Run(() =>
        {
            var bmp = new BitmapImage();
            bmp.BeginInit();
            bmp.CacheOption = BitmapCacheOption.OnLoad;
            bmp.StreamSource = new MemoryStream(png);
            bmp.EndInit();
            bmp.Freeze();                                              // frozen: can be handed to the window's thread
            return (BitmapSource)bmp;
        });
    }

    public void Dispose() => _source.Dispose();
}
