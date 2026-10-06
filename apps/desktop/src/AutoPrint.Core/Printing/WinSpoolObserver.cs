using System.Runtime.InteropServices;

namespace AutoPrint.Core.Printing;

/// <summary>
/// Reads the Windows print queue with the native spooler API (winspool.drv: OpenPrinter, EnumJobs, SetJob). This is
/// exactly what the Phase 1 spike measured. System.Printing was tried first and rejected: its objects belong to the
/// thread that created them, so the app's async code crashed with "a different thread owns it". The native calls
/// are thread-agnostic and cheap enough to poll every 40 ms.
/// </summary>
public sealed class WinSpoolObserver : ISpoolerObserver
{
    public bool PrinterExists(string printer)
    {
        if (string.IsNullOrWhiteSpace(printer)) return false;
        if (!Native.OpenPrinter(printer, out var h, IntPtr.Zero)) return false;
        Native.ClosePrinter(h);
        return true;
    }

    public IReadOnlyList<SpoolerJobInfo> ListJobs(string printer, string nameContains)
    {
        if (!Native.OpenPrinter(printer, out var h, IntPtr.Zero)) throw new InvalidOperationException("printer_unavailable");
        try
        {
            // With no buffer the call succeeds only when the queue is empty. Any failure other than "buffer too small"
            // is a failed read, never an empty queue: the watcher takes "empty" to mean the job left the queue.
            if (Native.EnumJobs(h, 0, 999, 1, IntPtr.Zero, 0, out uint needed, out _)) return [];
            if (Marshal.GetLastWin32Error() != Native.ERROR_INSUFFICIENT_BUFFER || needed == 0)
                throw new InvalidOperationException("spooler_enum_failed");
            var buf = Marshal.AllocHGlobal((int)needed);
            try
            {
                if (!Native.EnumJobs(h, 0, 999, 1, buf, needed, out _, out uint count))
                    throw new InvalidOperationException("spooler_enum_failed");
                var result = new List<SpoolerJobInfo>();
                int size = Marshal.SizeOf<Native.JOB_INFO_1>();
                for (int i = 0; i < count; i++)
                {
                    var j = Marshal.PtrToStructure<Native.JOB_INFO_1>(buf + i * size);
                    if (j.pDocument is null || !j.pDocument.Contains(nameContains, StringComparison.OrdinalIgnoreCase)) continue;
                    result.Add(new SpoolerJobInfo((int)j.JobId, j.pDocument, FlagNames(j.Status), (int)j.PagesPrinted, (int)j.TotalPages));
                }
                return result;
            }
            finally { Marshal.FreeHGlobal(buf); }
        }
        finally { Native.ClosePrinter(h); }
    }

    public void RemoveJob(string printer, int jobId)
    {
        // A user may always cancel a job they sent themselves with plain "use" access. Asking for "administer" as well
        // fails outright for a standard user on many printers, so that is only the second try.
        foreach (var access in new[] { Native.PRINTER_ACCESS_USE, Native.PRINTER_ACCESS_USE | Native.PRINTER_ACCESS_ADMINISTER })
        {
            if (!Native.OpenPrinter(printer, out var h, new Native.PRINTER_DEFAULTS { DesiredAccess = access })) continue;
            try { if (Native.SetJob(h, (uint)jobId, 0, IntPtr.Zero, Native.JOB_CONTROL_DELETE)) return; }
            finally { Native.ClosePrinter(h); }
        }
        throw new InvalidOperationException("spooler_remove_failed");
    }

    /// <summary>Names match the Win32 JOB_STATUS_* flags used in the spike and in the completion rule.</summary>
    internal static IReadOnlyList<string> FlagNames(uint s)
    {
        var names = new List<string>();
        void Add(uint f, string n) { if ((s & f) != 0) names.Add(n); }
        Add(0x1, "PAUSED"); Add(0x2, "ERROR"); Add(0x4, "DELETING"); Add(0x8, "SPOOLING"); Add(0x10, "PRINTING");
        Add(0x20, "OFFLINE"); Add(0x40, "PAPEROUT"); Add(0x80, "PRINTED"); Add(0x100, "DELETED"); Add(0x200, "BLOCKED_DEVQ");
        Add(0x400, "USER_INTERVENTION"); Add(0x800, "RESTART"); Add(0x1000, "COMPLETE"); Add(0x2000, "RETAINED");
        return names;
    }

    private static class Native
    {
        public const uint PRINTER_ACCESS_ADMINISTER = 0x4, PRINTER_ACCESS_USE = 0x8, JOB_CONTROL_DELETE = 5;
        public const uint PRINTER_ENUM_LOCAL = 0x2, PRINTER_ENUM_CONNECTIONS = 0x4;
        public const int ERROR_INSUFFICIENT_BUFFER = 122;

        [StructLayout(LayoutKind.Sequential)] public struct PRINTER_DEFAULTS { public IntPtr pDatatype; public IntPtr pDevMode; public uint DesiredAccess; }

        [StructLayout(LayoutKind.Sequential)]
        public struct SYSTEMTIME { public ushort wYear, wMonth, wDayOfWeek, wDay, wHour, wMinute, wSecond, wMilliseconds; }

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        public struct JOB_INFO_1
        {
            public uint JobId; public string pPrinterName; public string pMachineName; public string pUserName;
            public string pDocument; public string pDatatype; public string pStatus;
            public uint Status; public uint Priority; public uint Position; public uint TotalPages; public uint PagesPrinted;
            public SYSTEMTIME Submitted;
        }

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        public struct PRINTER_INFO_4 { public string pPrinterName; public string pServerName; public uint Attributes; }

        [DllImport("winspool.drv", EntryPoint = "OpenPrinterW", CharSet = CharSet.Unicode, SetLastError = true)]
        public static extern bool OpenPrinter(string name, out IntPtr handle, IntPtr defaults);

        [DllImport("winspool.drv", EntryPoint = "OpenPrinterW", CharSet = CharSet.Unicode, SetLastError = true)]
        public static extern bool OpenPrinter(string name, out IntPtr handle, PRINTER_DEFAULTS defaults);

        [DllImport("winspool.drv", SetLastError = true)] public static extern bool ClosePrinter(IntPtr handle);

        [DllImport("winspool.drv", EntryPoint = "EnumJobsW", CharSet = CharSet.Unicode, SetLastError = true)]
        public static extern bool EnumJobs(IntPtr hPrinter, uint first, uint count, uint level, IntPtr pJob, uint cbBuf, out uint needed, out uint returned);

        [DllImport("winspool.drv", EntryPoint = "SetJobW", CharSet = CharSet.Unicode, SetLastError = true)]
        public static extern bool SetJob(IntPtr hPrinter, uint jobId, uint level, IntPtr pJob, uint command);

        [StructLayout(LayoutKind.Sequential)]
        public struct PRINTER_INFO_2
        {
            public IntPtr pServerName, pPrinterName, pShareName, pPortName, pDriverName, pComment, pLocation, pDevMode, pSepFile,
                          pPrintProcessor, pDatatype, pParameters, pSecurityDescriptor;
            public uint Attributes, Priority, DefaultPriority, StartTime, UntilTime, Status, cJobs, AveragePPM;
        }

        [DllImport("winspool.drv", EntryPoint = "GetPrinterW", CharSet = CharSet.Unicode, SetLastError = true)]
        public static extern bool GetPrinter(IntPtr hPrinter, uint level, IntPtr pPrinter, uint cbBuf, out uint needed);

        [DllImport("winspool.drv", EntryPoint = "EnumPrintersW", CharSet = CharSet.Unicode, SetLastError = true)]
        public static extern bool EnumPrinters(uint flags, string? name, uint level, IntPtr pPrinterEnum, uint cbBuf, out uint needed, out uint returned);
    }

    /// <summary>
    /// What Windows says about one printer right now. Can take seconds for a network printer that is switched off,
    /// so never call it on the window's own thread. It only reads; nothing is sent to the printer.
    /// </summary>
    public static PrinterHealth Health(string printer)
    {
        if (string.IsNullOrWhiteSpace(printer) || !Native.OpenPrinter(printer, out var h, IntPtr.Zero)) return PrinterHealth.Missing(printer ?? "");
        try
        {
            var byName = PrinterCatalog.Classify(printer);
            var nameOnly = new PrinterHealth(printer, true, byName != PrinterKind.Paper, false, false, null, byName == PrinterKind.Prompt);
            Native.GetPrinter(h, 2, IntPtr.Zero, 0, out uint needed);
            if (needed == 0) return nameOnly;
            var buf = Marshal.AllocHGlobal((int)needed);
            try
            {
                if (!Native.GetPrinter(h, 2, buf, needed, out _)) return nameOnly;
                var i = Marshal.PtrToStructure<Native.PRINTER_INFO_2>(buf);
                string port = Marshal.PtrToStringUni(i.pPortName) ?? "", driver = Marshal.PtrToStringUni(i.pDriverName) ?? "";
                return PrinterHealth.From(printer, port, driver, i.Attributes, i.Status);
            }
            finally { Marshal.FreeHGlobal(buf); }
        }
        finally { Native.ClosePrinter(h); }
    }

    /// <summary>Port and driver of every printer installed on this PC itself (level 2, local only: the spooler answers
    /// from its own records and no network printer is contacted). Printers shared from another computer are not in it.</summary>
    private static Dictionary<string, (string Port, string Driver)> LocalPortsAndDrivers()
    {
        var map = new Dictionary<string, (string, string)>(StringComparer.OrdinalIgnoreCase);
        Native.EnumPrinters(Native.PRINTER_ENUM_LOCAL, null, 2, IntPtr.Zero, 0, out uint needed, out _);
        if (needed == 0) return map;
        var buf = Marshal.AllocHGlobal((int)needed);
        try
        {
            if (!Native.EnumPrinters(Native.PRINTER_ENUM_LOCAL, null, 2, buf, needed, out _, out uint count)) return map;
            int size = Marshal.SizeOf<Native.PRINTER_INFO_2>();
            for (int i = 0; i < count; i++)
            {
                var p = Marshal.PtrToStructure<Native.PRINTER_INFO_2>(buf + i * size);
                if (Marshal.PtrToStringUni(p.pPrinterName) is { } name)
                    map[name] = (Marshal.PtrToStringUni(p.pPortName) ?? "", Marshal.PtrToStringUni(p.pDriverName) ?? "");
            }
        }
        finally { Marshal.FreeHGlobal(buf); }
        return map;
    }

    internal static IReadOnlyList<PrinterInfo> EnumerateInstalledPrinters()
    {
        const uint flags = Native.PRINTER_ENUM_LOCAL | Native.PRINTER_ENUM_CONNECTIONS;
        Native.EnumPrinters(flags, null, 4, IntPtr.Zero, 0, out uint needed, out _);
        if (needed == 0) return [];
        var buf = Marshal.AllocHGlobal((int)needed);
        try
        {
            if (!Native.EnumPrinters(flags, null, 4, buf, needed, out _, out uint count)) return [];
            Dictionary<string, (string Port, string Driver)> local;
            try { local = LocalPortsAndDrivers(); } catch (Exception) { local = []; }      // the names alone still give a list
            var list = new List<PrinterInfo>();
            int size = Marshal.SizeOf<Native.PRINTER_INFO_4>();
            for (int i = 0; i < count; i++)
            {
                var p = Marshal.PtrToStructure<Native.PRINTER_INFO_4>(buf + i * size);
                if (p.pPrinterName is null) continue;
                bool offline = (p.Attributes & 0x400) != 0;                         // PRINTER_ATTRIBUTE_WORK_OFFLINE
                var kind = local.TryGetValue(p.pPrinterName, out var d) ? PrinterCatalog.Classify(p.pPrinterName, d.Port, d.Driver) : PrinterCatalog.Classify(p.pPrinterName);
                list.Add(new PrinterInfo(p.pPrinterName, kind != PrinterKind.Paper, offline, kind == PrinterKind.Prompt));
            }
            return list;
        }
        finally { Marshal.FreeHGlobal(buf); }
    }
}

/// <summary>What comes out of a printer, as far as its port, driver and name tell.</summary>
public enum PrinterKind
{
    /// <summary>Nothing says otherwise: treated as a real printer.</summary>
    Paper,
    /// <summary>Writes a file to a fixed place without asking anyone (its port is a file path). No paper.</summary>
    File,
    /// <summary>No paper, and it opens a window on this PC (Save As, a fax wizard, a notes app) and waits for a person.</summary>
    Prompt,
}

/// <param name="IsVirtual">It does not print on paper.</param>
/// <param name="Prompts">It also opens a window and waits for a person, so a print sent to it just sits there.</param>
public sealed record PrinterInfo(string Name, bool IsVirtual, bool IsOffline, bool Prompts = false);

/// <summary>The state of one printer as Windows reports it. Drivers are often wrong about "offline", so this is
/// shown as a warning and never used to block a print; only a printer that no longer exists blocks.</summary>
/// <param name="Trouble">A plain-words problem Windows reports (out of paper, paper jam, door open), or null.</param>
/// <param name="Prompts">It makes no paper and opens a window that waits for a person (see <see cref="PrinterKind.Prompt"/>).</param>
public sealed record PrinterHealth(string Name, bool Exists, bool IsVirtual, bool Offline, bool Paused, string? Trouble, bool Prompts = false)
{
    public static PrinterHealth Missing(string name) => new(name, false, false, false, false, null);
    public bool Fine => Exists && !IsVirtual && !Offline && !Paused && Trouble is null;

    /// <summary>From the raw Win32 values (PRINTER_INFO_2). Separate from the system call so it can be tested.</summary>
    public static PrinterHealth From(string name, string port, string driver, uint attributes, uint status)
    {
        bool offline = (attributes & 0x400) != 0 || (status & (0x80 | 0x1000)) != 0;        // WORK_OFFLINE; STATUS_OFFLINE, NOT_AVAILABLE
        bool paused = (status & 0x1) != 0;
        string? trouble =
            (status & 0x10) != 0 ? "is out of paper" : (status & 0x8) != 0 ? "has a paper jam" : (status & 0x400000) != 0 ? "has a door open"
            : (status & 0x40000) != 0 ? "is out of toner or ink" : (status & (0x2 | 0x40 | 0x100000)) != 0 ? "needs someone to look at it" : null;
        var kind = PrinterCatalog.Classify(name, port, driver);
        return new(name, true, kind != PrinterKind.Paper, offline, paused, trouble, kind == PrinterKind.Prompt);
    }
}

/// <summary>
/// Tells printers that put ink on paper from the "printers" that Windows and other programs install to make a file,
/// send a fax or open a note. The port and the driver decide; the name is only the fallback, because a shopkeeper can
/// rename a printer. It only ever warns: nothing here blocks a print.
/// </summary>
public static class PrinterCatalog
{
    // Document writers, fax and note "printers", by the words in their driver or name.
    private static readonly string[] Markers =
        ["Print to PDF", "XPS Document Writer", "OneNote", "Fax", "Send to", "Journal Note Writer", "Document Image Writer",
         "PDF Creator", "PDFCreator", "PDF24", "CutePDF", "doPDF", "novaPDF", "Bullzip", "Adobe PDF", "Foxit", "Nitro PDF", "PDF-XChange",
         "PDF Writer", "PDF Printer", "PDF Converter", "Print to File", "Snagit", "Evernote", "Document Converter"];

    private static bool Marked(string text) => Markers.Any(m => text.Contains(m, StringComparison.OrdinalIgnoreCase));

    private static bool IsFilePath(string port) =>
        port.Contains(":\\") || new[] { ".pdf", ".xps", ".oxps", ".prn" }.Any(x => port.EndsWith(x, StringComparison.OrdinalIgnoreCase));

    /// <summary>When only the name is known (a printer shared from another computer, or Windows gave no details).
    /// A document writer is assumed to ask where to save, because most do and the app cannot know.</summary>
    public static PrinterKind Classify(string name) => Marked(name) ? PrinterKind.Prompt : PrinterKind.Paper;

    /// <summary>
    /// By port first. PORTPROMPT:, FILE: and the old XPS port ask for a file name every time, and the fax and OneNote
    /// ports open their own window: a print sent there waits for a person. A port that is a file path writes that
    /// file without asking. After the port, the driver and the name: a document writer on a port of its own is
    /// assumed to ask, because most do and the app cannot know.
    /// </summary>
    public static PrinterKind Classify(string name, string port, string driver)
    {
        // several ports can be ticked for one printer ("LPT1:,FILE:"); one that asks is enough to make a print wait
        var ports = port.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        bool Any(Func<string, bool> test) => ports.Any(test);
        if (Any(p => p.Equals("PORTPROMPT:", StringComparison.OrdinalIgnoreCase) || p.Equals("FILE:", StringComparison.OrdinalIgnoreCase)
                  || p.StartsWith("XPSPort", StringComparison.OrdinalIgnoreCase) || p.StartsWith("SHRFAX", StringComparison.OrdinalIgnoreCase)
                  || p.Contains("OneNote", StringComparison.OrdinalIgnoreCase)))
            return PrinterKind.Prompt;
        if (Any(IsFilePath)) return PrinterKind.File;
        if (Marked(driver) || Marked(name)) return PrinterKind.Prompt;
        if (Any(p => p.Equals("nul:", StringComparison.OrdinalIgnoreCase) || p.Equals("nul", StringComparison.OrdinalIgnoreCase))) return PrinterKind.File;
        return PrinterKind.Paper;
    }

    public static bool LooksVirtual(string name) => Classify(name) != PrinterKind.Paper;
    public static bool LooksVirtual(string name, string port, string driver) => Classify(name, port, driver) != PrinterKind.Paper;

    /// <summary>What to tell the shopkeeper about a printer that makes no paper, or null for a real one. One wording
    /// for Settings and for the queue.</summary>
    public static string? Warning(string name, bool isVirtual, bool prompts) =>
        !isVirtual ? null
        : prompts ? $"“{name}” does not print on paper. It makes a file, and may open a window that waits for someone to answer, so a customer's print would just sit there."
        : $"“{name}” does not print on paper. It makes a file on this computer.";

    /// <summary>The printer to offer when none has been chosen yet: the first real one that is not marked offline, else
    /// the first real one, else none. Never one that makes a file or opens a window: that is only ever chosen by hand.</summary>
    public static string? DefaultChoice(IReadOnlyList<PrinterInfo> printers) =>
        (printers.FirstOrDefault(p => !p.IsVirtual && !p.IsOffline) ?? printers.FirstOrDefault(p => !p.IsVirtual))?.Name;

    /// <summary>Installed printers, real ones first. Those that make no paper are flagged so the app can say so.</summary>
    public static IReadOnlyList<PrinterInfo> List() =>
        WinSpoolObserver.EnumerateInstalledPrinters().OrderBy(p => p.IsVirtual).ThenBy(p => p.Name).ToList();
}
