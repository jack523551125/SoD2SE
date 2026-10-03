using System;
using System.IO;
using System.Linq;
using SoD2SE;
using SoD2SE.MeleeSpeed;

static class MeleeConfigSmoke
{
    static void Check(bool pass, string message) { if (!pass) throw new Exception(message); }
    static int Main()
    {
        string path = Path.Combine(Path.GetTempPath(), "sod2-melee-" + Guid.NewGuid().ToString("N") + ".ini");
        try
        {
            Environment.SetEnvironmentVariable("SOD2SE_MCM_CONFIG", path);
            var registry = McmRegistry.Initialize(Path.GetTempPath()); var plugin = new Plugin(); plugin.RegisterMcm(registry);
            var options = registry.Snapshot().Single().Options;
            Check(options.Count == 8 && options.All(o => !o.RequiresRestart), "eight live options expected");
            Check(options.Where(o => o.Type == McmOptionType.Integer || o.Type == McmOptionType.IntegerInput).All(o => o.IntValue == 100), "default rates");
            Check(options.Count(o => o.Type == McmOptionType.Integer) == 4 && !options.Any(o => o.Type == McmOptionType.IntegerInput), "four native sliders with read-only value labels");
            Check(options.Single(o => o.Id == "player").BoolValue && !options.Single(o => o.Id == "friendly").BoolValue && !options.Single(o => o.Id == "others").BoolValue, "default scope");
            registry.SetInt(plugin.Id, "blade", 175); registry.SetInt(plugin.Id, "heavy", 9999);
            registry.SetInt(plugin.Id, "close", -1); registry.SetBool(plugin.Id, "friendly", true);
            registry.SetBool(plugin.Id, "active", false);
            registry = McmRegistry.Initialize(Path.GetTempPath()); plugin.RegisterMcm(registry); options = registry.Snapshot().Single().Options;
            Check(options.Single(o => o.Id == "blade").IntValue == 175 && options.Single(o => o.Id == "heavy").IntValue == 1000 && options.Single(o => o.Id == "close").IntValue == 25,
                "persistence and bounds: blade=" + options.Single(o => o.Id == "blade").IntValue + ", heavy=" + options.Single(o => o.Id == "heavy").IntValue + ", close=" + options.Single(o => o.Id == "close").IntValue);
            Check(options.Single(o => o.Id == "friendly").BoolValue && !options.Single(o => o.Id == "active").BoolValue, "scope persistence");
            Check(registry.IsEnabled(plugin.Id), "runtime disabled plugin must load to allow re-enable");
            registry.ResetAll(); Check(registry.Snapshot().Single().Options.Single(o => o.Id == "active").BoolValue, "reset");
            plugin.Shutdown(); plugin.Shutdown();
            Console.WriteLine("PASS: melee MCM defaults, independent rates/scopes, clamping, persistence, reset and lifecycle."); return 0;
        }
        finally { if (File.Exists(path)) File.Delete(path); Environment.SetEnvironmentVariable("SOD2SE_MCM_CONFIG", null); }
    }
}
