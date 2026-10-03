
# Standalone script execution resolves imports from its source-owning project.
import sys as _layout_sys
from pathlib import Path as _LayoutPath
_layout_sys.path.insert(0, str(_LayoutPath(__file__).resolve().parents[2]))
from Automation.source_layout import work_root
import argparse
import tempfile
import shutil
import sys
import ctypes
import json
import os
import subprocess
import uuid
from ctypes import wintypes as w
from pathlib import Path

parser = argparse.ArgumentParser(description="Run the actual SoD2SE launch path inside private USVFS; no real game is started.")
parser.add_argument("--mo2-path", type=Path, required=True)
parser.add_argument("--plugin-source", type=Path, required=True)
parser.add_argument("--case", choices=["all", "mcm", "melee", "roguelite", "both", "followers", "community", "none"])
parser.add_argument("--build-dir", type=Path, default=work_root(Path(__file__).resolve().parents[2]) / "build")
args = parser.parse_args()
if args.case is None:
    for case in ("all", "mcm", "melee", "roguelite", "both", "followers", "community", "none"):
        subprocess.run([sys.executable, __file__, *sys.argv[1:], "--case", case], check=True)
    print("PASS: all DLL enable/disable combinations through real USVFS and actual CLR plugin discovery")
    sys.exit(0)
root = Path(tempfile.mkdtemp(prefix="SoD2SE-vfs-smoke-"))
(root / "work").mkdir()
mo = args.mo2_path.resolve()
build = args.build_dir.resolve()
harness = root / "PluginDiscoverySmoke.exe"
subprocess.run([str(Path(os.environ["WINDIR"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"),
    "/nologo", "/platform:x64", "/target:exe", "/warnaserror+", "/out:" + str(harness),
    str(Path(__file__).resolve().parents[2] / 'Tests/Loader/PluginDiscoverySmoke.cs')], check=True)
dll_dirs = [os.add_dll_directory(str(p)) for p in [mo, mo / "dlls"]]
lib = ctypes.WinDLL(str(mo / "usvfs_x64.dll"))
lib.usvfsCreateParameters.restype = ctypes.c_void_p
lib.usvfsSetInstanceName.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
lib.usvfsSetDebugMode.argtypes = [ctypes.c_void_p, w.BOOL]
lib.usvfsCreateVFS.argtypes = [ctypes.c_void_p]
lib.usvfsCreateVFS.restype = w.BOOL
lib.usvfsFreeParameters.argtypes = [ctypes.c_void_p]
lib.usvfsVirtualLinkFile.argtypes = [w.LPCWSTR, w.LPCWSTR, w.UINT]
lib.usvfsVirtualLinkFile.restype = w.BOOL
lib.usvfsVirtualLinkDirectoryStatic.argtypes = [w.LPCWSTR, w.LPCWSTR, w.UINT]
lib.usvfsVirtualLinkDirectoryStatic.restype = w.BOOL
lib.usvfsInitLogging.argtypes = [ctypes.c_bool]
lib.usvfsInitLogging(False)
token = uuid.uuid4().hex
params = lib.usvfsCreateParameters()
lib.usvfsSetInstanceName(params, ("sod2-test-" + token).encode())
lib.usvfsSetDebugMode(params, False)
assert lib.usvfsCreateVFS(params)
lib.usvfsFreeParameters(params)

class STARTUPINFO(ctypes.Structure):
    _fields_ = [("cb", w.DWORD), ("lpReserved", w.LPWSTR), ("lpDesktop", w.LPWSTR),
                ("lpTitle", w.LPWSTR), ("dwX", w.DWORD), ("dwY", w.DWORD),
                ("dwXSize", w.DWORD), ("dwYSize", w.DWORD), ("dwXCountChars", w.DWORD),
                ("dwYCountChars", w.DWORD), ("dwFillAttribute", w.DWORD),
                ("dwFlags", w.DWORD), ("wShowWindow", w.WORD), ("cbReserved2", w.WORD),
                ("lpReserved2", ctypes.c_void_p), ("hStdInput", w.HANDLE),
                ("hStdOutput", w.HANDLE), ("hStdError", w.HANDLE)]
class PROCESSINFO(ctypes.Structure):
    _fields_ = [("hProcess", w.HANDLE), ("hThread", w.HANDLE), ("dwProcessId", w.DWORD), ("dwThreadId", w.DWORD)]
lib.usvfsCreateProcessHooked.argtypes = [w.LPCWSTR, w.LPWSTR, ctypes.c_void_p, ctypes.c_void_p,
                                      w.BOOL, w.DWORD, ctypes.c_void_p, w.LPCWSTR,
                                      ctypes.POINTER(STARTUPINFO), ctypes.POINTER(PROCESSINFO)]
lib.usvfsCreateProcessHooked.restype = w.BOOL
kernel = ctypes.WinDLL("kernel32", use_last_error=True)
kernel.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
kernel.GetExitCodeProcess.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
kernel.CloseHandle.argtypes = [w.HANDLE]
sys.path.insert(0, str(args.plugin_source.resolve()))
from sod2_support.core import Mod, build_plan
from sod2_support.runtime import build_runtime
mods = []
selected = []
for name, plugin_id, cases in [("UnlimitedFollowers", "unlimited-followers", ("all", "both", "followers")),
                              ("UnlimitedCommunity", "unlimited-community", ("all", "both", "community")),
                              ("Mcm", "mcm", ("all", "mcm")),
                              ("MeleeSpeed", "melee-speed", ("all", "melee")),
                              ("Roguelite", "survivor-roguelite", ("all", "roguelite"))]:
    if args.case not in cases:
        continue
    directory = root / "mod-source" / name
    (directory / "Plugins").mkdir(parents=True)
    shutil.copy2(build / "Plugins" / (name + ".dll"), directory / "Plugins" / (name + ".dll"))
    if name in ("Mcm", "MeleeSpeed"):
        shutil.copytree(build / "Plugins" / name, directory / "Plugins" / name)
    mods.append(Mod(name, directory, len(mods)))
    selected.append(plugin_id)
plan = build_plan(mods, {"profile": args.case})
assert not plan.errors, plan.errors
runtime = build_runtime(plan, root / "state")
output = root / "discovered.txt"
try:
    if (runtime / "Root").is_dir():
        assert lib.usvfsVirtualLinkDirectoryStatic(str(runtime / "Root"), str(root), 8)
    si, pi = STARTUPINFO(), PROCESSINFO()
    si.cb = ctypes.sizeof(si)
    cmd = ctypes.create_unicode_buffer(subprocess.list2cmdline([
        str(harness), str(build / "SoD2SE.Loader.exe"), str(output), ",".join(sorted(selected))]))
    assert lib.usvfsCreateProcessHooked(None, cmd, None, None, False, 0x08000000, None,
                                      str(root), ctypes.byref(si), ctypes.byref(pi))
    assert kernel.WaitForSingleObject(pi.hProcess, 30000) == 0
    status = w.DWORD()
    kernel.GetExitCodeProcess(pi.hProcess, ctypes.byref(status))
    kernel.CloseHandle(pi.hThread)
    kernel.CloseHandle(pi.hProcess)
    error = Path(str(output) + ".error")
    assert status.value == 0, error.read_text(encoding="utf-8-sig") if error.exists() else status.value
    assert output.read_text() == ",".join(sorted(selected))
    assert not (root / "Plugins").exists(), "DLLs must remain virtual"
    print("PASS:", args.case, output.read_text() or "zero plugins")
finally:
    lib.usvfsDisconnectVFS()
