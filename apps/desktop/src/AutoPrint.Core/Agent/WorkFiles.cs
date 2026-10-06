namespace AutoPrint.Core.Agent;

/// <summary>
/// Customer documents exist on this PC only while their job is being handled. These helpers make that true after a
/// crash or a power cut too: whatever is left in a work folder when nothing is running is stale and is removed.
/// </summary>
public static class WorkFiles
{
    /// <summary>Deletes everything inside <paramref name="dir"/> (best effort). Returns how many entries could not be removed.</summary>
    public static int CleanStale(string dir)
    {
        int left = 0;
        try
        {
            if (!Directory.Exists(dir)) return 0;
            foreach (var f in Directory.GetFiles(dir)) if (!TryDelete(() => { File.SetAttributes(f, FileAttributes.Normal); File.Delete(f); })) left++;
            foreach (var d in Directory.GetDirectories(dir)) if (!TryDelete(() => Directory.Delete(d, true))) left++;
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException) { left++; }
        return left;
    }

    /// <summary>Deletes one file, trying again for a moment: a print program that was just stopped can hold it briefly.</summary>
    public static async Task<bool> DeleteAsync(string file, int tries = 5, int waitMs = 200)
    {
        for (int i = 0; i < tries; i++)
        {
            if (TryDelete(() => { if (File.Exists(file)) File.Delete(file); }) && !File.Exists(file)) return true;
            if (i + 1 < tries) await Task.Delay(waitMs);
        }
        return false;
    }

    private static bool TryDelete(Action delete)
    {
        try { delete(); return true; }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException) { return false; }
    }
}
