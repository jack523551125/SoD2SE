using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Runtime.ExceptionServices;
using System.Runtime.InteropServices;
using SoD2SE;

// Maps the executable as inert data in this test process. No game process,
// save, instruction execution, process suspension, or game file write occurs.
internal static class PluginMemorySmoke
{
    static readonly MethodInfo Transaction = typeof(GameSession).Assembly.GetType("SoD2SE.Native", true)
        .GetMethods(BindingFlags.NonPublic | BindingFlags.Static)
        .Single(method => method.Name == "ApplyTransaction" && method.GetParameters().Length == 4);
    static readonly MethodInfo TransactionWithWriter = typeof(GameSession).Assembly.GetType("SoD2SE.Native", true)
        .GetMethods(BindingFlags.NonPublic | BindingFlags.Static)
        .Single(method => method.Name == "ApplyTransaction" && method.GetParameters().Length == 5);
    static readonly MethodInfo Isolation = typeof(GameSession).GetMethod("EnsurePatchSetIsolation", BindingFlags.NonPublic | BindingFlags.Static);

    [DllImport("kernel32.dll", SetLastError = true)]
    static extern IntPtr VirtualAlloc(IntPtr address, UIntPtr size, uint allocationType, uint protection);
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool VirtualFree(IntPtr address, UIntPtr size, uint freeType);

    sealed class PluginDefinition
    {
        public Type Type;
        public string Id;
        public string Sha256;
        public IList<PatchSpec> Patches;
        public ISoD2Plugin Create() { return (ISoD2Plugin)Activator.CreateInstance(Type); }
    }

    sealed class CaptureSession : IGameSession
    {
        public PluginDefinition Definition;
        public Process GameProcess { get { return null; } }
        public IntPtr ModuleBase { get { return IntPtr.Zero; } }
        public string ExePath { get { return "descriptor-capture-only"; } }
        public int Apply(string id, string sha256, IList<PatchSpec> patches)
        {
            if (Definition.Patches != null) throw new Exception("Plugin called Apply more than once: " + id);
            Definition.Id = id;
            Definition.Sha256 = sha256;
            Definition.Patches = patches.ToArray();
            return 0;
        }
        public int Restore(string id, IList<PatchSpec> patches) { return 0; }
    }

    sealed class MemorySession : IGameSession, IDisposable
    {
        readonly Process current = Process.GetCurrentProcess();
        readonly string digest;
        readonly string exePath;
        readonly Dictionary<string, IList<PatchSpec>> active = new Dictionary<string, IList<PatchSpec>>(StringComparer.OrdinalIgnoreCase);
        readonly byte[] image;
        readonly IntPtr module;
        public int LastChanged;
        public Process GameProcess { get { return current; } }
        public IntPtr ModuleBase { get { return module; } }
        public string ExePath { get { return exePath; } }

        public MemorySession(byte[] originalImage, string executable, string sha256)
        {
            image = originalImage;
            exePath = executable;
            digest = sha256;
            module = VirtualAlloc(IntPtr.Zero, (UIntPtr)image.Length, 0x3000, 0x04);
            if (module == IntPtr.Zero) throw new Exception("Fixture allocation failed: " + Marshal.GetLastWin32Error());
            Marshal.Copy(image, 0, module, image.Length);
        }
        public int Apply(string id, string sha256, IList<PatchSpec> patches)
        {
            if (!String.Equals(digest, sha256, StringComparison.OrdinalIgnoreCase)) throw new InvalidOperationException("Fixture executable hash does not match plugin");
            foreach (var entry in active)
                if (!String.Equals(entry.Key, id, StringComparison.OrdinalIgnoreCase)) Invoke(Isolation, new object[] { entry.Key, entry.Value, patches });
            LastChanged = ApplyRaw(patches, true);
            active[id] = patches.ToArray();
            return LastChanged;
        }
        public int Restore(string id, IList<PatchSpec> patches)
        {
            if (!active.ContainsKey(id)) return 0;
            LastChanged = ApplyRaw(patches, false);
            active.Remove(id);
            return LastChanged;
        }
        public int ApplyRaw(IList<PatchSpec> patches, bool enabled)
        {
            return (int)Invoke(Transaction, new object[] { current.Handle, module, patches, enabled });
        }
        public void TestRollback(IList<PatchSpec> patches)
        {
            int writes = 0;
            Action<IntPtr, IntPtr, byte[]> writer = delegate(IntPtr handle, IntPtr address, byte[] bytes) {
                // Simulate a partial write, then failure. The real transaction must
                // restore both the partial write and every preceding write.
                if (++writes == 2)
                {
                    Marshal.WriteByte(address, bytes[0]);
                    throw new InvalidOperationException("injected partial write failure");
                }
                Marshal.Copy(bytes, 0, address, bytes.Length);
            };
            MustReject(delegate { Invoke(TransactionWithWriter, new object[] { current.Handle, module, patches, true, writer }); }, "injected transaction failure");
            AssertMemory(image, "partial-write rollback");
        }
        public void AssertMemory(byte[] expected, string label)
        {
            var actual = new byte[expected.Length];
            Marshal.Copy(module, actual, 0, actual.Length);
            for (int index = 0; index < expected.Length; index++)
                if (actual[index] != expected[index]) throw new Exception(label + " changed unexpected byte at RVA 0x" + index.ToString("X"));
        }
        public void Dispose()
        {
            if (!VirtualFree(module, UIntPtr.Zero, 0x8000)) throw new Exception("Fixture release failed");
            current.Dispose();
        }
    }

    static object Invoke(MethodInfo method, object[] arguments)
    {
        if (method == null) throw new Exception("Expected framework test entry point missing");
        try { return method.Invoke(null, arguments); }
        catch (TargetInvocationException exception)
        {
            ExceptionDispatchInfo.Capture(exception.InnerException).Throw();
            throw;
        }
    }

    static void MustReject(Action operation, string label)
    {
        try { operation(); }
        catch (InvalidOperationException) { return; }
        throw new Exception("Expected rejection: " + label);
    }

    static byte[] MapImage(string path)
    {
        var file = File.ReadAllBytes(path);
        if (file.Length < 64) throw new Exception("Truncated executable");
        int pe = BitConverter.ToInt32(file, 0x3C);
        if (pe < 0 || pe > file.Length - 264 || BitConverter.ToUInt32(file, pe) != 0x4550 || BitConverter.ToUInt16(file, pe + 4) != 0x8664 || BitConverter.ToUInt16(file, pe + 24) != 0x20B)
            throw new Exception("Expected x64 PE32+ executable");
        int imageSize = BitConverter.ToInt32(file, pe + 80);
        int headerSize = BitConverter.ToInt32(file, pe + 84);
        if (imageSize <= 0 || imageSize > 512 * 1024 * 1024 || headerSize < 0 || headerSize > file.Length || headerSize > imageSize) throw new Exception("Invalid PE image size");
        var image = new byte[imageSize];
        Buffer.BlockCopy(file, 0, image, 0, headerSize);
        int sectionCount = BitConverter.ToUInt16(file, pe + 6);
        int sectionTable = pe + 24 + BitConverter.ToUInt16(file, pe + 20);
        for (int section = 0; section < sectionCount; section++)
        {
            int start = checked(sectionTable + section * 40);
            if (start < 0 || start > file.Length - 40) throw new Exception("Invalid PE section table");
            int rva = BitConverter.ToInt32(file, start + 12);
            int length = BitConverter.ToInt32(file, start + 16);
            int offset = BitConverter.ToInt32(file, start + 20);
            if (length < 0 || rva < 0 || offset < 0 || (long)rva + length > image.Length || (long)offset + length > file.Length) throw new Exception("Invalid PE section bounds");
            Buffer.BlockCopy(file, offset, image, rva, length);
        }
        return image;
    }

    static List<PluginDefinition> Discover(string directory)
    {
        var definitions = new List<PluginDefinition>();
        foreach (var path in Directory.GetFiles(directory, "*.dll").OrderBy(value => value, StringComparer.OrdinalIgnoreCase))
            foreach (var type in Assembly.LoadFrom(path).GetTypes().Where(type => type.IsClass && !type.IsAbstract && typeof(ISoD2Plugin).IsAssignableFrom(type)))
            {
                var definition = new PluginDefinition { Type = type };
                var plugin = definition.Create();
                // MCM and MeleeSpeed are native-only integrations, not byte patch
                // tables. MCM is covered by the managed configuration smoke test;
                // MeleeSpeed's classifier, rate packing, and hook parity are covered
                // by MeleeNativeTest. Keep this harness focused on process-memory
                // transactions exposed through IGameSession.Apply.
                if (plugin.Id == "mcm" || plugin.Id == "melee-speed" || plugin.Id == "survivor-roguelite") continue;
                if (plugin.ApiVersion != FrameworkInfo.PluginApiVersion) throw new Exception("Unexpected plugin API");
                var capture = new CaptureSession { Definition = definition };
                plugin.Initialize(capture);
                plugin.Shutdown();
                if (definition.Patches == null || definition.Patches.Count == 0 || definition.Id != plugin.Id) throw new Exception("Missing plugin patch transaction");
                if (definitions.Any(other => String.Equals(other.Id, definition.Id, StringComparison.OrdinalIgnoreCase))) throw new Exception("Duplicate plugin ID");
                definitions.Add(definition);
            }
        if (definitions.Count == 0) throw new Exception("No plugin DLLs discovered");
        return definitions;
    }

    static void TestOrder(List<PluginDefinition> definitions, byte[] original, string executable, string digest, bool reverse)
    {
        var order = reverse ? definitions.AsEnumerable().Reverse().ToArray() : definitions.ToArray();
        var expected = (byte[])original.Clone();
        using (var session = new MemorySession(original, executable, digest))
        {
            var loaded = new List<ISoD2Plugin>();
            foreach (var definition in order)
            {
                var plugin = definition.Create();
                plugin.Initialize(session);
                loaded.Add(plugin);
                if (session.LastChanged != definition.Patches.Count) throw new Exception("Unexpected applied patch count: " + definition.Id);
                foreach (var patch in definition.Patches) Buffer.BlockCopy(patch.Replacement, 0, expected, patch.Rva, patch.Replacement.Length);
                session.AssertMemory(expected, definition.Id + " apply");
                MustReject(delegate { plugin.Initialize(session); }, definition.Id + " double initialization");
                if (session.ApplyRaw(definition.Patches, true) != 0) throw new Exception("Idempotent native transaction changed bytes");
                session.AssertMemory(expected, definition.Id + " repeated initialization");
            }
            for (int index = loaded.Count - 1; index >= 0; index--)
            {
                loaded[index].Shutdown();
                foreach (var patch in order[index].Patches) Buffer.BlockCopy(patch.Original, 0, expected, patch.Rva, patch.Original.Length);
                session.AssertMemory(expected, order[index].Id + " independent restore");
                loaded[index].Shutdown();
            }
            session.AssertMemory(original, "complete restore");
        }
        Console.WriteLine("PASS: real plugin apply/idempotency/coexistence/restore, " + (reverse ? "reverse" : "forward") + " order");
    }

    static void TestConflicts(PluginDefinition definition, byte[] original, string executable, string digest)
    {
        var patch = definition.Patches[definition.Patches.Count - 1];
        int writeOffset = patch.Rva;
        byte conflict = 0;
        while (conflict == patch.Original[0] || conflict == patch.Replacement[0]) conflict++;
        using (var session = new MemorySession(original, executable, digest))
        {
            var expected = (byte[])original.Clone();
            expected[writeOffset] = conflict;
            Marshal.WriteByte(session.ModuleBase, writeOffset, conflict);
            var plugin = definition.Create();
            MustReject(delegate { plugin.Initialize(session); }, definition.Id + " write conflict");
            plugin.Shutdown();
            session.AssertMemory(expected, "failed initialization made no partial writes");
        }
        int contextOffset = -1;
        foreach (var candidate in definition.Patches)
        {
            for (int offset = candidate.GuardRva; offset < candidate.GuardRva + candidate.GuardOriginal.Length; offset++)
                if (!definition.Patches.Any(other => other.Rva <= offset && offset < other.Rva + other.Original.Length)) { contextOffset = offset; break; }
            if (contextOffset >= 0) break;
        }
        if (contextOffset >= 0)
            using (var session = new MemorySession(original, executable, digest))
            {
                var expected = (byte[])original.Clone();
                expected[contextOffset] ^= 0xFF;
                Marshal.WriteByte(session.ModuleBase, contextOffset, expected[contextOffset]);
                var plugin = definition.Create();
                MustReject(delegate { plugin.Initialize(session); }, definition.Id + " context conflict");
                plugin.Shutdown();
                session.AssertMemory(expected, "context rejection made no writes");
            }
        if (definition.Patches.Count >= 2)
            using (var session = new MemorySession(original, executable, digest)) session.TestRollback(definition.Patches);
        Console.WriteLine("PASS: " + definition.Id + " corrupt-code/context rejection and partial-write rollback");
    }

    static int Main(string[] arguments)
    {
        try
        {
            if (arguments.Length != 2) throw new ArgumentException("Usage: PluginMemorySmoke.exe <game-exe> <plugin-directory>");
            string executable = Path.GetFullPath(arguments[0]);
            var definitions = Discover(Path.GetFullPath(arguments[1]));
            string digest = FrameworkInfo.HashFile(executable);
            foreach (var definition in definitions)
                if (!String.Equals(definition.Sha256, digest, StringComparison.OrdinalIgnoreCase)) throw new Exception("Executable hash mismatch: " + definition.Id);
            var image = MapImage(executable);
            TestOrder(definitions, image, executable, digest, false);
            TestOrder(definitions, image, executable, digest, true);
            foreach (var definition in definitions) TestConflicts(definition, image, executable, digest);
            Console.WriteLine("PASS: inert-image plugin memory smoke tests for " + definitions.Count + " plugin(s)");
            Console.WriteLine("LIMIT: does not test gameplay, save loading, game startup, process suspension, or recruitment behavior.");
            return 0;
        }
        catch (Exception error)
        {
            Console.Error.WriteLine("FAIL: " + error);
            return 1;
        }
    }
}
