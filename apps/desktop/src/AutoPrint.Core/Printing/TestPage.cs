using System.Text;

namespace AutoPrint.Core.Printing;

/// <summary>A one-page PDF with a few lines of text, built in memory. Used by "Print a test page" and by tests.</summary>
public static class TestPage
{
    public static byte[] Build(string line1, string line2)
    {
        static string Esc(string s) => s.Replace("\\", "\\\\").Replace("(", "\\(").Replace(")", "\\)");
        var content = $"BT /F1 28 Tf 72 740 Td ({Esc(line1)}) Tj ET\nBT /F1 14 Tf 72 700 Td ({Esc(line2)}) Tj ET\n" +
                      "BT /F1 12 Tf 72 660 Td (If you can read this, the printer is connected.) Tj ET";
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
