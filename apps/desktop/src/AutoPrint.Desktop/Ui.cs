using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Interop;
using System.Windows.Media;
using System.Windows.Media.Animation;

namespace AutoPrint.Desktop;

/// <summary>Small builders so the windows read as content, not as property lists. All styling lives in App.xaml.</summary>
internal static class Ui
{
    public static T Res<T>(string key) => (T)Application.Current.FindResource(key);
    public static Brush Brush(string key) => Res<Brush>(key);

    public static TextBlock T(string text, string style = "Body", string? colour = null)
    {
        var t = new TextBlock { Text = text, Style = Res<Style>(style) };
        if (colour is not null) t.Foreground = Brush(colour);
        return t;
    }

    public static TextBlock Icon(string glyph, string colour, double size = 16) =>
        new() { Text = glyph, Style = Res<Style>("Icon"), Foreground = Brush(colour), FontSize = size };

    public static Button B(string text, string? style = null)
    {
        var b = new Button { Content = text };
        if (style is not null) b.Style = Res<Style>(style);
        return b;
    }

    // Segoe MDL2 Assets, present on every Windows 10 and 11
    public const string Printer = "", Warning = "", Info = "", Search = "", Gear = "", Tick = "", Offline = "", Clear = "";
}

/// <summary>
/// A row of short facts with a small dot between neighbours ("48 pages · 2 copies · Both sides"). When the row is too
/// narrow a whole fact moves to the next line, and the dot is drawn only between two facts that share a line, so no
/// line ever ends or begins with a stray dot.
/// </summary>
internal sealed class Facts : Panel
{
    private const double Gap = 26, LineGap = 2;
    private readonly List<Point> _dots = new();

    public static readonly DependencyProperty DotProperty = DependencyProperty.Register(nameof(Dot), typeof(Brush), typeof(Facts),
        new FrameworkPropertyMetadata(null, FrameworkPropertyMetadataOptions.AffectsRender));
    public Brush? Dot { get => (Brush?)GetValue(DotProperty); set => SetValue(DotProperty, value); }

    public TextBlock Add(string text, string style = "Body", string? colour = null)
    {
        var t = Ui.T(text, style, colour); t.TextWrapping = TextWrapping.NoWrap; t.TextTrimming = TextTrimming.CharacterEllipsis;
        Children.Add(t);
        return t;
    }

    private Size Layout(double width, bool arrange)
    {
        double x = 0, y = 0, line = 0, widest = 0;
        if (arrange) _dots.Clear();
        foreach (UIElement c in InternalChildren)
        {
            if (c.Visibility == Visibility.Collapsed) continue;
            var want = c.DesiredSize;
            if (x > 0 && x + Gap + want.Width > width) { y += line + LineGap; x = 0; line = 0; }
            if (x > 0)
            {
                if (arrange) _dots.Add(new Point(x + Gap / 2, y + want.Height / 2 + 1));
                x += Gap;
            }
            if (arrange) c.Arrange(new Rect(x, y, Math.Min(want.Width, Math.Max(0, width - x)), want.Height));
            x += Math.Min(want.Width, width);
            line = Math.Max(line, want.Height); widest = Math.Max(widest, x);
        }
        return new Size(widest, y + line);
    }

    protected override Size MeasureOverride(Size available)
    {
        foreach (UIElement c in InternalChildren) c.Measure(new Size(available.Width, double.PositiveInfinity));
        return Layout(available.Width, arrange: false);
    }

    protected override Size ArrangeOverride(Size final)
    {
        Layout(final.Width, arrange: true);
        InvalidateVisual();
        return final;
    }

    protected override void OnRender(DrawingContext dc)
    {
        var brush = Dot ?? Ui.Brush("Muted");
        foreach (var p in _dots) dc.DrawEllipse(brush, null, p, 1.5, 1.5);
    }
}

/// <summary>
/// The few transitions the app has, in one place: same durations, same easing, opacity and render transforms only
/// (the render thread runs those; no layout is recomputed per frame and a click is never delayed by one). All of it
/// is off when Windows has animations switched off, on a machine without graphics acceleration, and in the self-test.
/// </summary>
internal static class Motion
{
    public static bool Enabled = true;
    public static bool On => Enabled && SystemParameters.ClientAreaAnimation && RenderCapability.Tier > 0;

    private static readonly Duration In = TimeSpan.FromMilliseconds(220), Out = TimeSpan.FromMilliseconds(160), Slow = TimeSpan.FromMilliseconds(320);
    private static readonly IEasingFunction Ease = Frozen(new CubicEase { EasingMode = EasingMode.EaseOut });
    private static T Frozen<T>(T f) where T : Freezable { f.Freeze(); return f; }

    private static DoubleAnimation To(double from, double to, Duration d) => new(from, to, d) { EasingFunction = Ease };

    /// <summary>Something new settles in: fades up from slightly below.</summary>
    public static void Enter(FrameworkElement e)
    {
        if (!On) return;
        var move = new TranslateTransform(0, 10);
        e.RenderTransform = move; e.Opacity = 0;
        e.BeginAnimation(UIElement.OpacityProperty, To(0, 1, In));
        move.BeginAnimation(TranslateTransform.YProperty, To(10, 0, In));
    }

    /// <summary>Something finished leaves: fades while lifting a little, then <paramref name="gone"/> removes it.</summary>
    public static void Leave(FrameworkElement e, Action gone)
    {
        e.IsHitTestVisible = false;                                 // nothing that is on its way out can be clicked
        if (!On) { gone(); return; }
        var move = new TranslateTransform(0, 0);
        e.RenderTransform = move;
        var fade = To(e.Opacity, 0, Out);
        fade.Completed += (_, _) => gone();
        e.BeginAnimation(UIElement.OpacityProperty, fade);
        move.BeginAnimation(TranslateTransform.YProperty, To(0, -6, Out));
    }

    /// <summary>A change of state appears softly instead of popping (banners, the pairing code, a tab's content).</summary>
    public static void Fade(UIElement e)
    {
        if (!On) return;
        e.BeginAnimation(UIElement.OpacityProperty, To(0, 1, Slow));
    }

    public static void Colour(SolidColorBrush brush, Color to)
    {
        if (!On || brush.IsFrozen) { if (!brush.IsFrozen) brush.Color = to; return; }
        brush.BeginAnimation(SolidColorBrush.ColorProperty, new ColorAnimation(to, Slow) { EasingFunction = Ease });
    }

    /// <summary>The quiet "working" line under a job that is printing: a soft light gliding along a thin track.
    /// It is the only motion that repeats, so it runs only while it can be seen: with the window in the tray or
    /// minimised, or the Finished tab in front, a long print costs nothing.</summary>
    public static FrameworkElement Progress()
    {
        var glide = new TranslateTransform(0, 0);
        var light = new Border { Width = 140, Height = 3, CornerRadius = new CornerRadius(1.5), Background = Ui.Brush("Brand"), HorizontalAlignment = HorizontalAlignment.Left, RenderTransform = glide };
        var track = new Border { Height = 3, CornerRadius = new CornerRadius(1.5), Background = Ui.Brush("BrandLine"), ClipToBounds = true, Child = light, Margin = new Thickness(0, 10, 0, 0) };
        if (!On) return track;
        Window? window = null;
        bool running = false; double width = 0;
        void Run()
        {
            bool seen = track.IsVisible && track.ActualWidth > 0 && window is { WindowState: not WindowState.Minimized };
            if (seen == running && (!seen || width == track.ActualWidth)) return;
            running = seen; width = track.ActualWidth;
            glide.BeginAnimation(TranslateTransform.XProperty, !seen ? null
                : new DoubleAnimation(-140, width, TimeSpan.FromSeconds(1.8)) { RepeatBehavior = RepeatBehavior.Forever, EasingFunction = Frozen(new SineEase { EasingMode = EasingMode.EaseInOut }) });
        }
        void StateChanged(object? sender, EventArgs e) => Run();
        track.Loaded += (_, _) => { if (window is null) { window = Window.GetWindow(track); if (window is not null) window.StateChanged += StateChanged; } Run(); };
        track.Unloaded += (_, _) => { if (window is not null) window.StateChanged -= StateChanged; window = null; Run(); };     // the card is gone: the window must not keep it alive
        track.SizeChanged += (_, _) => Run();
        track.IsVisibleChanged += (_, _) => Run();
        return track;
    }
}

/// <summary>How the shop PC gets a busy shopkeeper's attention: a short soft chime and the taskbar button flashing.</summary>
internal static class Alerts
{
    /// <summary>Self-test only. When set, a chime or a flash is reported here ("chime", "flash", "flash-off") and not
    /// performed, so a test can count them without making a noise or lighting up the taskbar.</summary>
    internal static Action<string>? Probe;

    private static System.Media.SoundPlayer? _player;
    private static readonly object Gate = new();

    /// <summary>Two soft notes, made in memory once (no sound file to ship or lose). Played off the window's thread.</summary>
    public static void Chime()
    {
        if (Probe is { } probe) { probe("chime"); return; }
        Task.Run(Play);
    }

    private static void Play()
    {
        try
        {
            lock (Gate)
            {
                if (_player is null) { _player = new System.Media.SoundPlayer(Wave()); _player.Load(); }
                _player.Play();
            }
        }
        catch (Exception e) { App.Log("sound: " + e.GetType().Name); }       // no sound card, or audio service stopped: the flash and the notification still happen
    }

    private static MemoryStream Wave()
    {
        const int rate = 22050;
        (double Hz, double Secs)[] notes = [(659.25, 0.18), (880.0, 0.34)];
        int total = 0; foreach (var n in notes) total += (int)(n.Secs * rate);
        var ms = new MemoryStream();
        using (var w = new BinaryWriter(ms, System.Text.Encoding.ASCII, leaveOpen: true))
        {
            w.Write("RIFF"u8); w.Write(36 + total * 2); w.Write("WAVEfmt "u8); w.Write(16); w.Write((short)1); w.Write((short)1);
            w.Write(rate); w.Write(rate * 2); w.Write((short)2); w.Write((short)16); w.Write("data"u8); w.Write(total * 2);
            foreach (var (hz, secs) in notes)
            {
                int count = (int)(secs * rate);
                for (int i = 0; i < count; i++)
                {
                    double t = (double)i / rate;
                    double envelope = Math.Min(1, t / 0.008) * Math.Exp(-t * 7);          // quick soft start, gentle fade
                    w.Write((short)(Math.Sin(2 * Math.PI * hz * t) * envelope * 0.32 * short.MaxValue));
                }
            }
        }
        ms.Position = 0;
        return ms;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct FLASHWINFO { public uint cbSize; public IntPtr hwnd; public uint dwFlags; public uint uCount; public uint dwTimeout; }
    [DllImport("user32.dll")] private static extern bool FlashWindowEx(ref FLASHWINFO info);

    /// <summary>Flashes the taskbar button until the window is brought to the front. Does nothing if it is already in front.</summary>
    public static void Flash(Window w, bool on = true)
    {
        if (Probe is { } probe) { probe(on ? "flash" : "flash-off"); return; }
        var h = new WindowInteropHelper(w).Handle;
        if (h == IntPtr.Zero) return;
        var info = new FLASHWINFO { cbSize = (uint)Marshal.SizeOf<FLASHWINFO>(), hwnd = h, dwFlags = on ? 3u | 12u : 0u, uCount = on ? uint.MaxValue : 0 };   // FLASHW_ALL | FLASHW_TIMERNOFG
        FlashWindowEx(ref info);
    }
}
