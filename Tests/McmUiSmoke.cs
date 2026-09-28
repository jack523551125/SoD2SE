using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using SoD2SE;

static class McmUiSmoke
{
    static int Main(string[] args)
    {
        string config = Path.Combine(Path.GetTempPath(), "sod2se-mcm-ui-" + Guid.NewGuid().ToString("N") + ".ini");
        try
        {
            Environment.SetEnvironmentVariable("SOD2SE_MCM_CONFIG", config);
            var registry = McmRegistry.Initialize(Path.GetTempPath());
            registry.RegisterPlugin("ui-smoke", "UI Smoke", "overlay")
                .AddBool("enabled", "Enabled", true, "restart", true);
            var assembly = Assembly.LoadFrom(args[0]);
            var overlayType = assembly.GetType("SoD2SE.Loader.McmOverlay", true);
            var start = overlayType.GetMethod("Start", BindingFlags.Static | BindingFlags.Public);
            var overlay = (IDisposable)start.Invoke(null, new object[] { Process.GetCurrentProcess() });
            overlay.Dispose();
            Console.WriteLine("PASS: MCM STA overlay thread creates and shuts down cleanly");
            return 0;
        }
        finally
        {
            if (File.Exists(config)) File.Delete(config);
            Environment.SetEnvironmentVariable("SOD2SE_MCM_CONFIG", null);
        }
    }
}
