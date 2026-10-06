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
        if (!Native.OpenPrinter(printer, out var h, new Native.PRINTER_DEFAULTS { DesiredAccess = Native.PRINTER_ACCESS_USE | Native.PRINTER_ACCESS_ADMINISTER }))
            throw new InvalidOperationException("printer_unavailable");
        try { Native.SetJob(h, (uint)jobId, 0, IntPtr.Zero, Native.JOB_CONTROL_DELETE); }
        finally { Native.ClosePrinter(h); }
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
            Native.GetPrinter(h, 2, IntPtr.Zero, 0, out uint needed);
            if (needed == 0) return new PrinterHealth(printer, true, PrinterCatalog.LooksVirtual(printer), false, false, null);
            var buf = Marshal.AllocHGlobal((int)needed);
            try
            {
                if (!Native.GetPrinter(h, 2, buf, needed, out _)) return new PrinterHealth(printer, true, PrinterCatalog.LooksVirtual(printer), false, false, null);
                var i = Marshal.PtrToStructure<Native.PRINTER_INFO_2>(buf);
                string port = Marshal.PtrToStringUni(i.pPortName) ?? "", driver = Marshal.PtrToStringUni(i.pDriverName) ?? "";
                return PrinterHealth.From(printer, port, driver, i.Attributes, i.Status);
            }
            finally { Marshal.FreeHGlobal(buf); }
        }
        finally { Native.ClosePrinter(h); }
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
            var list = new List<PrinterInfo>();
            int size = Marshal.SizeOf<Native.PRINTER_INFO_4>();
            for (int i = 0; i < count; i++)
            {
                var p = Marshal.PtrToStructure<Native.PRINTER_INFO_4>(buf + i * size);
                if (p.pPrinterName is null) continue;
                bool offline = (p.Attributes & 0x400) != 0;                         // PRINTER_ATTRIBUTE_WORK_OFFLINE
                list.Add(new PrinterInfo(p.pPrinterName, PrinterCatalog.LooksVirtual(p.pPrinterName), offline));
            }
            return list;
        }
        finally { Marshal.FreeHGlobal(buf); }
    }
}

public sealed record PrinterInfo(string Name, bool IsVirtual, bool IsOffline);

/// <summary>The state of one printer as Windows reports it. Drivers are often wrong about "offline", so this is
/// shown as a warning and never used to block a print; only a printer that no longer exists blocks.</summary>
/// <param name="Trouble">A plain-words problem Windows reports (out of paper, paper jam, door open), or null.</param>
public sealed record PrinterHealth(string Name, bool Exists, bool IsVirtual, bool Offline, bool Paused, string? Trouble)
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
        return new(name, true, PrinterCatalog.LooksVirtual(name, port, driver), offline, paused, trouble);
    }
}

public static class PrinterCatalog
{
    private static readonly string[] VirtualMarkers = ["Print to PDF", "XPS Document Writer", "OneNote", "Fax", "Send to", "PDF Creator"];

    public static bool LooksVirtual(string name) => VirtualMarkers.Any(m => name.Contains(m, StringComparison.OrdinalIgnoreCase));

    /// <summary>A printer whose port is a file or a prompt, or whose driver is a document writer, makes a file, not paper,
    /// whatever it has been named.</summary>
    public static bool LooksVirtual(string name, string port, string driver) =>
        LooksVirtual(name) || LooksVirtual(driver)
        || port.Equals("PORTPROMPT:", StringComparison.OrdinalIgnoreCase) || port.Equals("FILE:", StringComparison.OrdinalIgnoreCase)
        || port.Equals("nul:", StringComparison.OrdinalIgnoreCase) || port.StartsWith("XPSPort", StringComparison.OrdinalIgnoreCase)
        || port.Contains(":\\") || port.EndsWith(".pdf", StringComparison.OrdinalIgnoreCase) || port.EndsWith(".xps", StringComparison.OrdinalIgnoreCase);

    /// <summary>Installed printers, real ones first. Virtual ones are flagged so the app can say they produce no paper.</summary>
    public static IReadOnlyList<PrinterInfo> List() =>
        WinSpoolObserver.EnumerateInstalledPrinters().OrderBy(p => p.IsVirtual).ThenBy(p => p.Name).ToList();
}
