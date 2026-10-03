using System;
using System.Diagnostics;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Threading;
using SoD2SE;

class ThreadSafetySmoke
{
    [DllImport("kernel32.dll", SetLastError = true)] static extern IntPtr VirtualAlloc(IntPtr address, UIntPtr size, uint allocation, uint protect);
    [DllImport("kernel32.dll", SetLastError = true)] static extern bool VirtualProtect(IntPtr address, UIntPtr size, uint protect, out uint old);
    [DllImport("kernel32.dll", SetLastError = true)] static extern bool FlushInstructionCache(IntPtr process, IntPtr address, UIntPtr size);
    [DllImport("kernel32.dll", SetLastError = true)] static extern bool ReadProcessMemory(IntPtr process, IntPtr address, byte[] bytes, IntPtr size, out IntPtr read);
    [UnmanagedFunctionPointer(CallingConvention.Winapi)] delegate void NativeLoop();

    static byte[] Fixture(string mode)
    {
        var bytes = new byte[4096];
        for (int i = 0; i < bytes.Length; i++) bytes[i] = 0x90;
        // Function at +16; its callee spins at +128, returning to +25.
        byte[] caller = { 0x48, 0x83, 0xEC, 0x28, 0xE8, 0x67, 0, 0, 0, 0x48, 0x83, 0xC4, 0x28, 0xC3 };
        Array.Copy(caller, 0, bytes, 16, caller.Length);
        bytes[128] = 0xEB; bytes[129] = 0xFE;
        if (mode == "rip") { bytes[24] = 0xEB; bytes[25] = 0xFE; }
        return bytes;
    }

    static void Child(string mode)
    {
        var bytes = Fixture(mode);
        var memory = VirtualAlloc(IntPtr.Zero, (UIntPtr)bytes.Length, 0x3000, 4);
        if (memory == IntPtr.Zero) throw new Exception("fixture allocation failed");
        Marshal.Copy(bytes, 0, memory, bytes.Length);
        uint old;
        if (!VirtualProtect(memory, (UIntPtr)bytes.Length, 0x20, out old) ||
            !FlushInstructionCache(new IntPtr(-1), memory, (UIntPtr)bytes.Length)) throw new Exception("fixture executable protection failed");
        if (mode != "idle")
        {
            var entry = IntPtr.Add(memory, mode == "rip" ? 24 : 16);
            var loop = (NativeLoop)Marshal.GetDelegateForFunctionPointer(entry, typeof(NativeLoop));
            var worker = new Thread(delegate() { loop(); });
            worker.IsBackground = true;
            worker.Start();
            Thread.Sleep(100);
        }
        Console.WriteLine(memory.ToInt64());
        while (Console.ReadLine() != null) Console.WriteLine("PONG");
    }

    static string ReadLine(Process child)
    {
        var pending = child.StandardOutput.ReadLineAsync();
        if (!pending.Wait(5000)) throw new Exception("child response timed out; target may still be suspended");
        return pending.Result;
    }

    static void Test(string mode)
    {
        var info = new ProcessStartInfo(Assembly.GetExecutingAssembly().Location, "--child " + mode);
        info.UseShellExecute = false; info.CreateNoWindow = true;
        info.RedirectStandardInput = true; info.RedirectStandardOutput = true;
        using (var child = Process.Start(info))
        {
            try
            {
                var memory = new IntPtr(Int64.Parse(ReadLine(child)));
                var fixture = Fixture(mode);
                var original = new byte[8];
                var replacement = new byte[8];
                Array.Copy(fixture, 24, original, 0, original.Length);
                for (int i = 0; i < replacement.Length; i++) replacement[i] = 0xCC;
                var patches = new[] { new PatchSpec("thread-safety-fixture", 24, original, replacement, 24, original) };
                var native = typeof(FrameworkInfo).Assembly.GetType("SoD2SE.Native", true);
                var apply = native.GetMethod("ApplySuspended", BindingFlags.Public | BindingFlags.Static);
                bool rejected = false;
                try { apply.Invoke(null, new object[] { child.Handle, memory, patches, true }); }
                catch (TargetInvocationException error)
                {
                    if (error.InnerException.GetType().FullName != "SoD2SE.PatchBusyException") throw;
                    rejected = true;
                }
                if (rejected != (mode != "idle")) throw new Exception("unexpected quiescence decision: " + mode);
                var actual = new byte[8]; IntPtr read;
                if (!ReadProcessMemory(child.Handle, IntPtr.Add(memory, 24), actual, (IntPtr)8, out read) || read.ToInt64() != 8) throw new Exception("fixture read failed");
                var wanted = rejected ? original : replacement;
                for (int i = 0; i < 8; i++) if (actual[i] != wanted[i]) throw new Exception("unsafe/incorrect fixture write");
                if (!rejected) apply.Invoke(null, new object[] { child.Handle, memory, patches, false });
                child.StandardInput.WriteLine("ping"); child.StandardInput.Flush();
                if (ReadLine(child) != "PONG") throw new Exception("child did not resume");
                Console.WriteLine("PASS: suspended-process " + mode + " protection, exact bytes and resume");
            }
            finally
            {
                // Only this harness's explicitly created disposable child.
                if (!child.HasExited) child.Kill();
                child.WaitForExit();
            }
        }
    }

    static int Main(string[] args)
    {
        try
        {
            if (args.Length == 2 && args[0] == "--child") { Child(args[1]); return 0; }
            Test("idle"); Test("rip"); Test("return");
            return 0;
        }
        catch (Exception error) { Console.Error.WriteLine(error); return 1; }
    }
}
