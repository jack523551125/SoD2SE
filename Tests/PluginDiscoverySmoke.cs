using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Reflection;

// Run in a fresh process for each MO2 selection; CLR assemblies cannot unload individually.
static class PluginDiscoverySmoke
{
    static int Main(string[] args)
    {
        try
        {
            var program = Assembly.LoadFrom(args[0]).GetType("SoD2SE.Loader.Program", true);
            var discover = program.GetMethod("DiscoverPlugins", BindingFlags.Static | BindingFlags.NonPublic);
            var ids = new List<string>();
            foreach (var plugin in (IEnumerable)discover.Invoke(null, null))
                ids.Add((string)plugin.GetType().GetProperty("Id").GetValue(plugin, null));
            ids.Sort(StringComparer.Ordinal);
            var actual = String.Join(",", ids);
            File.WriteAllText(args[1], actual);
            if (actual != args[2]) throw new Exception("Expected " + args[2] + "; found " + actual);
            return 0;
        }
        catch (Exception error)
        {
            File.WriteAllText(args[1] + ".error", error.ToString());
            return 1;
        }
    }
}
