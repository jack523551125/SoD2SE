using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.MemoryMappedFiles;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Threading;
using SoD2SE;

static class McmIntegrationSmoke
{
    // ABI offsets from Native/McmProtocol.h.  verify_protocol.py recomputes the
    // packed layout and fails when any of these drifts, so the names below are
    // checked numbers rather than copies that rot silently.
    const int RequestOffset = 16, AcknowledgedOffset = 20, CommandOffset = 24, PageOffset = 28,
        OptionOffset = 32, ValueOffset = 36, KeyOffset = 40, ModifiersOffset = 44,
        VisibleOffset = 52, ReadyOffset = 56;
    const int Ready = 2;
    const int CommandSetBool = 1, CommandSetShortcut = 4, CommandSurfaceAction = 9;
    const int UiSurfacesOffset = 119896, UiSurfaceSize = 492;
    const int SurfaceOpen = 4, SurfaceRevision = 16;
    [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr window);
    [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr window, out uint pid);
    [DllImport("user32.dll")] static extern bool AttachThreadInput(uint first, uint second, bool attach);
    [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr window, int command);
    [DllImport("kernel32.dll")] static extern uint GetCurrentThreadId();
    [DllImport("user32.dll")] static extern void keybd_event(byte key, byte scan, uint flags, UIntPtr extra);
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
    static void Key(byte key, bool down) { keybd_event(key, 0, down ? 0U : 2U, UIntPtr.Zero); }
    static void Tap(byte key) { Key(key, true); Thread.Sleep(160); Key(key, false); Thread.Sleep(180); }
    // Brings the render window to the foreground.  No keystroke is sent here on
    // purpose: a synthetic Alt tap makes the window enter the Windows system
    // menu loop, DefWindowProc blocks the message loop inside it, and the
    // renderer stops presenting until some other key arrives.  That looked
    // exactly like a broken shortcut, so the focus step stays input-free.
    static void Focus(Process game)
    {
        for (int attempt = 0; attempt < 40; attempt++)
        {
            game.Refresh();
            if (game.MainWindowHandle != IntPtr.Zero)
            {
                ShowWindow(game.MainWindowHandle, 9);
                uint foregroundPid;
                uint foregroundThread = GetWindowThreadProcessId(GetForegroundWindow(), out foregroundPid);
                uint testThread = GetCurrentThreadId();
                bool attached = foregroundThread != 0 && foregroundThread != testThread &&
                    AttachThreadInput(testThread, foregroundThread, true);
                try { SetForegroundWindow(game.MainWindowHandle); }
                finally { if (attached) AttachThreadInput(testThread, foregroundThread, false); }
                Thread.Sleep(120);
                if (GetForegroundWindow() == game.MainWindowHandle)
                {
                    Console.WriteLine("Test foreground: True; game window=" + game.MainWindowHandle);
                    return;
                }
            }
            Thread.Sleep(100);
        }
        throw new Exception("could not bring the render window to the foreground");
    }
    // Frames must be advancing before a shortcut is sent: while the window is
    // not pumping, the native host never polls the key and the menu silently
    // stays shut.
    static void EnsurePumping(Process game, string output)
    {
        for (int attempt = 0; attempt < 4; attempt++)
        {
            Focus(game);
            try { InputCounts(output); return; }
            catch (Exception) { Thread.Sleep(300); }
        }
        throw new Exception("render window stopped pumping frames");
    }
    // The render test clears to {0.11,0.15,0.18}; anything else came from a
    // drawn screen.  A blank frame means the host rendered nothing.
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
    static int[] InputCounts(string output)
    {
        var request = Path.Combine(output, "input.request");
        File.WriteAllText(request, "query");
        Wait(delegate { return !File.Exists(request); }, "input probe timed out", 3000);
        return Array.ConvertAll(File.ReadAllText(Path.Combine(output, "input.txt")).Split(' '), int.Parse);
    }
    static int Main(string[] args)
    {
        Process game = null; ISoD2Plugin plugin = null;
        string output = Path.GetFullPath(args[2]); Directory.CreateDirectory(output);
        try
        {
            Environment.SetEnvironmentVariable("SOD2SE_MCM_CONFIG", Path.Combine(output, "mcm.ini"));
            Environment.SetEnvironmentVariable("SOD2SE_UI_CONFIG", Path.Combine(output, "ui.ini"));
            var registry = McmRegistry.Initialize(output);
            registry.SetShortcut(112, 0);
            var ui = UiRegistry.Initialize(output);
            // A framework screen published like any mod would: no key collision
            // with F1 or the upgrade prompt, one button, stable revision.
            var demo = ui.RegisterSurface("smoke-screen", "Smoke Screen", "framework verification");
            string action = null;
            demo.ActionRequested += value => action = value;
            demo.Clear();
            demo.Section("Rows");
            demo.KeyValue("Label", "Value", "row description");
            demo.Progress("Bar", 50, 100, "50%");
            demo.Button("Act", "smoke-action", "button description");
            demo.Publish();
            if (demo.ShortcutKey == 112 || demo.ShortcutKey == 113) throw new Exception("framework screen reused a reserved key");
            foreach (string dll in new[] { "UnlimitedCommunity.dll", "UnlimitedFollowers.dll" })
            {
                var assembly = Assembly.LoadFrom(Path.Combine(args[0], "Plugins", dll));
                foreach (var type in assembly.GetTypes())
                    if (typeof(IMcmConfigurable).IsAssignableFrom(type) && !type.IsAbstract)
                        ((IMcmConfigurable)Activator.CreateInstance(type)).RegisterMcm(registry);
            }
            registry.MarkLoaded("unlimited-community", true); registry.MarkLoaded("unlimited-followers", true);
            game = Process.Start(new ProcessStartInfo(args[1], "\"" + output + "\"") { UseShellExecute = false });
            Wait(delegate { game.Refresh(); return game.MainWindowHandle != IntPtr.Zero; }, "render test window missing", 8000);
            var mcm = Assembly.LoadFrom(Path.Combine(args[0], "Plugins", "Mcm.dll"));
            plugin = (ISoD2Plugin)Activator.CreateInstance(mcm.GetType("SoD2SE.Mcm.Plugin", true));
            plugin.Initialize(new Session { GameProcess = game });
            var bridge = plugin.GetType().GetField("bridge", BindingFlags.NonPublic | BindingFlags.Instance).GetValue(plugin);
            var view = (MemoryMappedViewAccessor)bridge.GetType().GetField("view", BindingFlags.NonPublic | BindingFlags.Instance).GetValue(bridge);
            var gate = (Mutex)bridge.GetType().GetField("gate", BindingFlags.NonPublic | BindingFlags.Instance).GetValue(bridge);
            Wait(delegate { return view.ReadInt32(ReadyOffset) == Ready; }, "native renderer did not initialize", 15000);
            EnsurePumping(game, output);
            Tap(112);
            Wait(delegate { return view.ReadInt32(VisibleOffset) == 1; }, "F1 did not open MCM", 4000);
            var beforeInput = InputCounts(output);
            Tap(87);
            var blockedInput = InputCounts(output);
            if (blockedInput[0] != beforeInput[0] || blockedInput[1] != beforeInput[1]) throw new Exception("menu leaked W input to game");
            File.WriteAllText(Path.Combine(output, "capture.request"), "capture");
            Wait(delegate { return File.Exists(Path.Combine(output, "menu.bmp")) && !File.Exists(Path.Combine(output, "capture.request")); }, "screenshot failed", 5000);
            if (NonClearPixels(Path.Combine(output, "menu.bmp")) < 50000) throw new Exception("settings screen did not draw anything");
            File.WriteAllText(Path.Combine(output, "resize.request"), "resize");
            Wait(delegate { return !File.Exists(Path.Combine(output, "resize.request")); }, "swapchain resize failed", 4000);
            gate.WaitOne();
            try { view.Write(CommandOffset, CommandSetShortcut); view.Write(KeyOffset, 77); view.Write(ModifiersOffset, 5); view.Write(RequestOffset, 1); }
            finally { gate.ReleaseMutex(); }
            Wait(delegate { return view.ReadInt32(AcknowledgedOffset) == 1; }, "shortcut save not acknowledged", 4000);
            if (registry.ShortcutKey != 77 || registry.ShortcutModifiers != 5) throw new Exception("shortcut did not persist");
            Tap(27); Wait(delegate { return view.ReadInt32(VisibleOffset) == 0; }, "Esc did not close menu", 4000);
            Tap(87);
            var restoredInput = InputCounts(output);
            if (restoredInput[0] <= blockedInput[0] || restoredInput[1] <= blockedInput[1]) throw new Exception("game input did not resume after closing menu");
            Tap(112); if (view.ReadInt32(VisibleOffset) != 0) throw new Exception("old F1 binding still active");
            Key(17, true); Key(16, true); Tap(77); Key(16, false); Key(17, false);
            Wait(delegate { return view.ReadInt32(VisibleOffset) == 1; }, "Ctrl+Shift+M did not open menu", 4000);
            gate.WaitOne();
            try { view.Write(CommandOffset, CommandSetBool); view.Write(PageOffset, 0); view.Write(OptionOffset, 0); view.Write(ValueOffset, 0); view.Write(RequestOffset, 2); }
            finally { gate.ReleaseMutex(); }
            Wait(delegate { return view.ReadInt32(AcknowledgedOffset) == 2; }, "plugin config not acknowledged", 4000);
            var first = registry.Snapshot()[0];
            if (registry.IsEnabled(first.Id)) throw new Exception("plugin change was not applied to config");

            // Framework screen: its own key opens it, the host draws it, and a
            // button press is routed back to the mod that published the row.
            Tap(27);
            Wait(delegate { return view.ReadInt32(VisibleOffset) == 0; }, "menu did not close before the screen test", 4000);
            Tap((byte)demo.ShortcutKey);
            Wait(delegate { return view.ReadInt32(VisibleOffset) == 1 && view.ReadInt32(UiSurfacesOffset + SurfaceOpen) == 1; },
                "framework screen did not open", 4000);
            File.WriteAllText(Path.Combine(output, "capture.request"), "capture");
            Wait(delegate { return File.Exists(Path.Combine(output, "menu.bmp")) && !File.Exists(Path.Combine(output, "capture.request")); },
                "framework screen screenshot failed", 5000);
            if (NonClearPixels(Path.Combine(output, "menu.bmp")) < 50000) throw new Exception("framework screen did not draw anything");
            int revision = view.ReadInt32(UiSurfacesOffset + SurfaceRevision);
            gate.WaitOne();
            try { view.Write(CommandOffset, CommandSurfaceAction); view.Write(PageOffset, 0); view.Write(OptionOffset, 3); view.Write(ValueOffset, revision); view.Write(RequestOffset, 3); }
            finally { gate.ReleaseMutex(); }
            Wait(delegate { return view.ReadInt32(AcknowledgedOffset) == 3; }, "framework action not acknowledged", 4000);
            if (action != "smoke-action") throw new Exception("framework button action was not routed to the mod");
            Tap(27);
            Wait(delegate { return view.ReadInt32(VisibleOffset) == 0 && view.ReadInt32(UiSurfacesOffset + SurfaceOpen) == 0; }, "Esc did not close the framework screen", 4000);
            plugin.Shutdown(); plugin = null;
            Thread.Sleep(200);
            if (game.HasExited) throw new Exception("renderer died during shutdown");
            Console.WriteLine("PASS: injected D3D11 renderer, F1/Esc, Ctrl+Shift+M, obsolete binding rejected, input block/restore, ResizeBuffers, save roundtrip, framework screen open/draw/action roundtrip, shutdown");
            Console.WriteLine("Screenshot: " + Path.Combine(output, "menu.bmp"));
            return 0;
        }
        catch (Exception error) { Console.Error.WriteLine(error); return 1; }
        finally
        {
            if (plugin != null) plugin.Shutdown();
            Key(16, false); Key(17, false); Key(77, false); Key(112, false);
            File.WriteAllText(Path.Combine(output, "stop.request"), "stop");
            if (game != null) { game.WaitForExit(5000); game.Dispose(); }
        }
    }
}
