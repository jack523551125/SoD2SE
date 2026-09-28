using System;
using System.IO;
using System.Linq;
using SoD2SE;

static class StatusPagesSmoke
{
    static void Check(bool value, string reason) { if (!value) throw new Exception(reason); }
    static int Main()
    {
        string path = Path.Combine(Path.GetTempPath(), "sod2-status-" + Guid.NewGuid().ToString("N") + ".ini");
        try
        {
            Environment.SetEnvironmentVariable("SOD2SE_MCM_CONFIG", path);
            var old = McmRegistry.Initialize(Path.GetTempPath());
            foreach (string id in new[] { "unlimited-followers", "unlimited-community" })
            {
                old.RegisterPlugin(id, id, "").AddBool("enabled", "Enabled", true, "", true);
                old.SetBool(id, "enabled", false);
            }
            var registry = McmRegistry.Initialize(Path.GetTempPath());
            new SoD2SE.UnlimitedFollowers.Plugin().RegisterMcm(registry);
            new SoD2SE.UnlimitedCommunity.Plugin().RegisterMcm(registry);
            Check(registry.Snapshot().Count == 2, "both status pages registered");
            foreach (var page in registry.Snapshot())
            {
                Check(page.Options.Count == 0, "status page must not expose old toggle");
                Check(registry.IsEnabled(page.Id), "stale disabled setting must not prevent loading");
                Check(!page.Loaded, "registration alone must not imply loaded");
                registry.MarkLoaded(page.Id, true);
                Check(registry.Snapshot().Single(x => x.Id == page.Id).Loaded, "successful init status");
                registry.MarkLoaded(page.Id, false);
                Check(!registry.Snapshot().Single(x => x.Id == page.Id).Loaded, "unload status");
            }
            Console.WriteLine("PASS: load-only pages; old enabled=false migration; load/unload states.");
            return 0;
        }
        finally
        {
            if (File.Exists(path)) File.Delete(path);
            Environment.SetEnvironmentVariable("SOD2SE_MCM_CONFIG", null);
        }
    }
}
