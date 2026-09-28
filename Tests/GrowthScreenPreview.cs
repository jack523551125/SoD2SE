using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.MemoryMappedFiles;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Threading;
using SoD2SE;
using SoD2SE.Roguelite;

// Renders the Survivor Roguelite screen through the real native host and saves
// a screenshot.  It proves the published rows survive the ABI, draw, and that
// the mod screen replaces the settings panel when it asks to be shown.
static class GrowthScreenPreview
{
    // ABI offsets from Native/McmProtocol.h.  verify_protocol.py recomputes the
    // packed layout, so these names cannot drift away from the header.
    const int VisibleOffset = 52, ReadyOffset = 56, Ready = 2;
    const int UiSurfaceCountOffset = 119888, UiSurfacesOffset = 119896;
    const int SurfaceWantOpen = 0, SurfaceOpen = 4, SurfaceNodeCount = 24;
    [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr window);
    [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr window, out uint pid);
    [DllImport("user32.dll")] static extern bool AttachThreadInput(uint first, uint second, bool attach);
    [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr window, int command);
    [DllImport("kernel32.dll")] static extern uint GetCurrentThreadId();
    [DllImport("user32.dll")] static extern void keybd_event(byte key, byte scan, uint flags, UIntPtr extra);

    static void Key(byte key, bool down) { keybd_event(key, 0, down ? 0U : 2U, UIntPtr.Zero); }

    sealed class Session : IGameSession
    {
        public Process GameProcess { get; set; }
        public IntPtr ModuleBase { get { return IntPtr.Zero; } }
        public string ExePath { get { return GameProcess.MainModule.FileName; } }
        public int Apply(string id, string sha, IList<PatchSpec> patches) { throw new NotSupportedException(); }
        public int Restore(string id, IList<PatchSpec> patches) { throw new NotSupportedException(); }
    }

    static void Wait(Func<bool> check, string message, int ms)
    {
        var watch = Stopwatch.StartNew();
        while (watch.ElapsedMilliseconds < ms) { if (check()) return; Thread.Sleep(50); }
        throw new Exception(message);
    }

    static void Focus(Process game)
    {
        // No keystroke is sent here on purpose.  A synthetic Alt tap hands the
        // window to the Windows system menu loop, DefWindowProc blocks the
        // message loop inside it, and the renderer stops presenting until some
        // other key arrives, which made the settings capture fail here and in
        // the MCM integration harness.
        for (int attempt = 0; attempt < 20; ++attempt)
        {
            game.Refresh();
            if (game.MainWindowHandle == IntPtr.Zero) { Thread.Sleep(100); continue; }
            ShowWindow(game.MainWindowHandle, 9);
            uint foregroundPid;
            uint foregroundThread = GetWindowThreadProcessId(GetForegroundWindow(), out foregroundPid);
            uint testThread = GetCurrentThreadId();
            bool attached = foregroundThread != 0 && foregroundThread != testThread &&
                AttachThreadInput(testThread, foregroundThread, true);
            try { SetForegroundWindow(game.MainWindowHandle); }
            finally { if (attached) AttachThreadInput(testThread, foregroundThread, false); }
            Thread.Sleep(120);
            if (GetForegroundWindow() == game.MainWindowHandle) return;
        }
        throw new Exception("test window did not receive focus");
    }

    // A shortcut is only noticed while the host is presenting frames, so prove
    // the render loop is alive before sending one.
    static void EnsurePumping(Process game, string output)
    {
        string request = Path.Combine(output, "capture.request");
        string screenshot = Path.Combine(output, "menu.bmp");
        for (int attempt = 0; attempt < 4; ++attempt)
        {
            Focus(game);
            if (File.Exists(screenshot)) File.Delete(screenshot);
            File.WriteAllText(request, "capture");
            var watch = Stopwatch.StartNew();
            while (watch.ElapsedMilliseconds < 3000)
            {
                if (File.Exists(screenshot) && !File.Exists(request)) return;
                Thread.Sleep(50);
            }
            if (File.Exists(request)) File.Delete(request);
            Thread.Sleep(300);
        }
        throw new Exception("render window stopped pumping frames");
    }

    // The render test clears to {0.11,0.15,0.18}; anything else was drawn.
    static int NonClearPixels(string path)
    {
        var bytes = File.ReadAllBytes(path);
        if (bytes.Length < 54) throw new Exception("screenshot is truncated");
        int offset = BitConverter.ToInt32(bytes, 10);
        int width = BitConverter.ToInt32(bytes, 18);
        int height = Math.Abs(BitConverter.ToInt32(bytes, 22));
        int count = 0;
        for (int y = 0; y < height; y++)
        {
            int row = offset + y * width * 4;
            for (int x = 0; x < width; x++)
            {
                int pixel = row + x * 4;
                if (pixel + 3 >= bytes.Length) break;
                if (bytes[pixel] != 46 || bytes[pixel + 1] != 38 || bytes[pixel + 2] != 28) count++;
            }
        }
        return count;
    }

    static int Main(string[] args)
    {
        Process game = null; ISoD2Plugin plugin = null;
        string output = Path.GetFullPath(args[2]); Directory.CreateDirectory(output);
            string progress = Path.Combine(output, "preview-progress.dat");
            // "settings" captures the MCM configuration page instead, which is
            // where a player records the screen shortcuts.
            bool settingsMode = args.Length > 4 && String.Equals(args[4], "settings", StringComparison.OrdinalIgnoreCase);
        try
        {
            Environment.SetEnvironmentVariable("SOD2SE_MCM_CONFIG", Path.Combine(output, "mcm.ini"));
            Environment.SetEnvironmentVariable("SOD2SE_UI_CONFIG", Path.Combine(output, "ui.ini"));
            McmRegistry.Initialize(output);
            var ui = UiRegistry.Initialize(output);

            var engine = new RogueliteEngine(new RogueliteSettings(), new RogueliteProgressStore(progress), 11);
            engine.AwardForIdentity("survivor-A", 260);
            var sample = engine.GetOrCreate("survivor-A");
            sample.SetCount(RogueliteBuff.MaxHealth, 3);
            sample.SetCount(RogueliteBuff.MeleeAttackSpeed, 4);
            sample.SetCount(RogueliteBuff.PlagueResistance, 2);
            sample.SetCount(RogueliteBuff.SprintStaminaCost, 1);
            var surface = ui.RegisterSurface("survivor-roguelite.growth",
                new McmLocalizedText("幸存者成长", "Survivor Progression"),
                new McmLocalizedText("击杀丧尸积累经验；升级后在这里查看进度与已获得的强化。",
                    "Earn XP by killing zombies; check progress and owned upgrades here."),
                delegate(UiSurface target)
                {
                    engine.BuildGrowthSurface(target, "survivor-A", McmLanguage.Chinese, "Alice", "已启用。", "");
                });
            surface.SetShortcut(0, 0);
            ui.SetChoiceOwner(surface.Id);
            if (!settingsMode) surface.Open();

            string renderArguments = "\"" + output + "\"";
            if (args.Length > 3 && !String.IsNullOrWhiteSpace(args[3])) renderArguments += " " + args[3];
            game = Process.Start(new ProcessStartInfo(args[1], renderArguments) { UseShellExecute = false });
            Wait(delegate { game.Refresh(); return game.MainWindowHandle != IntPtr.Zero; }, "render test window missing", 8000);
            var mcm = Assembly.LoadFrom(Path.Combine(args[0], "Plugins", "Mcm.dll"));
            plugin = (ISoD2Plugin)Activator.CreateInstance(mcm.GetType("SoD2SE.Mcm.Plugin", true));
            plugin.Initialize(new Session { GameProcess = game });
            var bridge = plugin.GetType().GetField("bridge", BindingFlags.NonPublic | BindingFlags.Instance).GetValue(plugin);
            var view = (MemoryMappedViewAccessor)bridge.GetType().GetField("view", BindingFlags.NonPublic | BindingFlags.Instance).GetValue(bridge);
            Wait(delegate { return view.ReadInt32(ReadyOffset) == Ready; }, "native renderer did not initialize", 15000);
            Focus(game);
            // No key is pressed: the mod asked for the screen, so the host must
            // show it and mirror the request back through seenRevision.
            if (settingsMode)
            {
                EnsurePumping(game, output);
                Key(112, true); Thread.Sleep(120); Key(112, false);
                Wait(delegate { return view.ReadInt32(VisibleOffset) == 1; }, "settings panel did not open", 5000);
            }
            else
            {
                Wait(delegate { return view.ReadInt32(UiSurfaceCountOffset) == 1 && view.ReadInt32(UiSurfacesOffset + SurfaceOpen) == 1; },
                    "growth screen did not open", 5000);
            }
            int nodes = view.ReadInt32(UiSurfacesOffset + SurfaceNodeCount);
            if (nodes < 10) throw new Exception("growth screen published only " + nodes + " rows");
            File.WriteAllText(Path.Combine(output, "capture.request"), "capture");
            Wait(delegate { return File.Exists(Path.Combine(output, "menu.bmp")) && !File.Exists(Path.Combine(output, "capture.request")); },
                "screenshot failed", 5000);
            int drawn = NonClearPixels(Path.Combine(output, "menu.bmp"));
            if (drawn < 50000) throw new Exception("growth screen did not draw anything");
            surface.Close();
            Wait(delegate { return view.ReadInt32(UiSurfacesOffset + SurfaceOpen) == 0; }, "growth screen did not close", 4000);
            Console.WriteLine("PASS: growth screen rows=" + nodes + ", drawn pixels=" + drawn + ", open and close through the native host");
            Console.WriteLine("Screenshot: " + Path.Combine(output, "menu.bmp"));
            return 0;
        }
        catch (Exception error) { Console.Error.WriteLine("FAIL: " + error); return 1; }
        finally
        {
            if (plugin != null) plugin.Shutdown();
            File.WriteAllText(Path.Combine(output, "stop.request"), "stop");
            if (game != null) { game.WaitForExit(5000); game.Dispose(); }
        }
    }
}
