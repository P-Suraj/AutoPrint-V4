using System.Text;
using AutoPrint.Core.Agent;
using AutoPrint.Core.Shop;

namespace AutoPrint.Core.Printing;

/// <summary>A one-page PDF with a few lines of text, built in memory. Used by "Print a test page" and by tests.</summary>
public static class TestPage
{
    /// <param name="colour">Adds a red, a green and a blue square, so a person can see that colour really prints.</param>
    public static byte[] Build(string line1, string line2, bool colour = false)
    {
        static string Esc(string s) => s.Replace("\\", "\\\\").Replace("(", "\\(").Replace(")", "\\)");
        var content = $"BT /F1 28 Tf 72 740 Td ({Esc(line1)}) Tj ET\nBT /F1 14 Tf 72 700 Td ({Esc(line2)}) Tj ET\n" +
                      "BT /F1 12 Tf 72 660 Td (If you can read this, the printer is connected.) Tj ET";
        if (colour)
            content += "\nBT /F1 12 Tf 72 630 Td (The three squares below must be red, green and blue.) Tj ET\n" +
                       "1 0 0 rg 72 520 90 90 re f\n0 0.6 0.2 rg 182 520 90 90 re f\n0 0.2 1 rg 292 520 90 90 re f\n0 g";
        var objects = new[]
        {
            "<</Type/Catalog/Pages 2 0 R>>",
            "<</Type/Pages/Kids[3 0 R]/Count 1>>",
            "<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>",
            $"<</Length {Encoding.ASCII.GetByteCount(content)}>>\nstream\n{content}\nendstream",
            "<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
        };
        var sb = new StringBuilder("%PDF-1.4\n");
        var offsets = new List<int>();
        for (int i = 0; i < objects.Length; i++)
        {
            offsets.Add(sb.Length);
            sb.Append($"{i + 1} 0 obj\n{objects[i]}\nendobj\n");
        }
        int xref = sb.Length;
        sb.Append($"xref\n0 {objects.Length + 1}\n0000000000 65535 f \n");
        foreach (var o in offsets) sb.Append($"{o:D10} 00000 n \n");
        sb.Append($"trailer\n<</Size {objects.Length + 1}/Root 1 0 R>>\nstartxref\n{xref}\n%%EOF\n");
        return Encoding.ASCII.GetBytes(sb.ToString());
    }
}

/// <summary>
/// "Print a test page" and "Test the colour printer" in Settings. Kept here, away from the window, so it is tested:
/// one page goes to exactly the printer that was named and to no other, a second press while one is on its way sends
/// nothing, the page's file is removed whatever happens, and every way it can fail is said in plain words.
/// </summary>
public sealed class TestPrint(Func<IPrintEngine> engine, string dir)
{
    private int _running;

    /// <summary>True while a test page is on its way to a printer.</summary>
    public bool Running => Volatile.Read(ref _running) != 0;

    /// <summary>The printer "Test the colour printer" goes to: the one chosen for colour, and only when that is a
    /// different machine from the main printer (otherwise the first button already tests it). Null means there is no
    /// separate colour printer to test.</summary>
    /// <param name="same">The words the list uses for "no separate colour printer".</param>
    public static string? ColourTarget(string? colourChoice, string? mainChoice, string same) =>
        colourChoice is { Length: > 0 } c && c != same && c != mainChoice ? c : null;

    /// <summary>Sends one test page to <paramref name="printer"/>. Returns null, having sent nothing, when a test page
    /// is already on its way (a double click).</summary>
    public async Task<SubmitResult?> SendAsync(string printer, bool colour, CancellationToken ct = default)
    {
        if (Interlocked.Exchange(ref _running, 1) != 0) return null;
        var jobName = "aptest_" + Guid.NewGuid().ToString("N");
        var file = Path.Combine(dir, jobName + ".pdf");                  // its own folder: a customer job cleaning the work folder never touches it
        try
        {
            Directory.CreateDirectory(dir);
            await File.WriteAllBytesAsync(file, TestPage.Build("AutoPrint test page", DateTime.Now.ToString("g"), colour), ct);
            return await engine().SubmitAsync(new PrintRequest(file, printer, new PrintOptions(1, colour, false, null), jobName, 1), ct);
        }
        finally
        {
            await WorkFiles.DeleteAsync(file);
            Volatile.Write(ref _running, 0);
        }
    }

    /// <summary>What to tell the shopkeeper. "Sent" is all the software knows: only a person can see the page.</summary>
    /// <param name="prompts">The printer makes a file and opens a window that waits for a person.</param>
    public static string Words(SubmitResult result, string printer, bool colour, bool prompts)
    {
        if (result.Accepted) return $"Sent to {(colour ? "the colour printer" : "the printer")} “{printer}”. Check that a page came out there{(colour ? " and that its three squares are red, green and blue" : "")}.";
        return result.Error switch
        {
            SumatraEngine.NotReadyReason => "AutoPrint's print program is missing or damaged. Install AutoPrint again.",
            "printer_not_found" => "Windows cannot find this printer any more. Choose another one.",
            "engine_timeout" => prompts ? "Nothing was printed. This one makes a file and waits for a window to be answered. Choose your real printer."
                : "The printer did not take the page. Check that it is switched on and connected, and that no window on this computer is waiting for an answer.",
            _ => Unexpected,
        };
    }

    /// <summary>For anything else that goes wrong (the print program stopped with an error, the disk, Windows).</summary>
    public const string Unexpected = "It did not work. Check the printer and try again.";
}
