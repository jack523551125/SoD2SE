# SoD2SE

The staged Rust product is **SoD2SE — State of Decay 2 System Extender**. Native ABI 1, Loader, Runtime, Settings Registry and native UI adapters are owned here. See [native APIs and commands](Docs/RUST-API.md) and [execution/acceptance status](Docs/Migration/Rust/STATUS.md). Select `Automation/dev.ps1 test SoD2SE --rust` for native checks. Legacy managed entrypoints remain available until required live acceptance permits release cutover.

[Existing usage and installation](README.zh-CN.md). Status: preview; this repository owns SoD2SE Core, GameApi, shared native runtime, and framework build entrypoints.

From workspace root: `Automation/dev.ps1 build SoD2SE`, `check SoD2SE`, `test SoD2SE`. A standalone checkout uses `Automation/Build/build.ps1` and `Automation/Test/test.ps1`. Product source lives in its own repository; no build or test requires workspace source junctions. See [DESIGN.md](DESIGN.md) for boundaries.

See [the physical internal layout and standalone commands](Docs/INTERNAL_LAYOUT.md).


## Development, offline validation, and packaging

Windows x64, PowerShell 7, Visual Studio 2022 C++ build tools with CMake, .NET Framework 4.x compiler, Python 3.13, and `python -m pip install -r Automation/Test/requirements.txt` for packaging tests.

From an independent checkout, use the repository-owned entrypoints:

```powershell
.\Automation\Build\build.ps1
.\Automation\Test\test.ps1
.\package.ps1
```


From the workspace root, `Automation/dev.ps1` dispatches to those same repository-owned entrypoints:

```powershell
.\Automation\dev.ps1 build SoD2SE
.\Automation\dev.ps1 check SoD2SE
.\Automation\dev.ps1 test SoD2SE
.\Automation\dev.ps1 package SoD2SE
```

Run `package.ps1` to generate package inputs below the repository's ignored `.work` directory. Checks never launch or attach to the game. See [RELEASE.md](RELEASE.md) for version authority, tag convention, required acceptance evidence, and release inputs.
