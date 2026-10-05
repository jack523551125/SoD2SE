# SoD2SE

The player prerequisite now includes built-in Rust MCM. No separate MCM download is needed. Loader creates the Plugins namespace; Registry configuration lives under `Plugins/SoD2SE/Settings/<profile>/registry.json`. MO2 redirects creation to overwrite; standalone startup uses the game directory.

The current candidate uses [original native controls](Docs/UI/MCM-NATIVE-CONTROLS.md) in a dedicated Mod view of the native settings host. Main-menu and pause entries share this view; the original host owns modality and the single hint bar. Normal Settings retains its categories. Live MCM acceptance remains pending.

MCM opens from the main and pause menus: Mod list on the left, selected Mod controls/status on the right. Normal Settings retains its original categories and game-value bindings. Keyboard/controller actions and native mouse callbacks drive navigation; live rendering/input acceptance remains separate from static resource checks.

Presentation v2 shares one modal panel between the main and pause menus, with fixed typography, native input hints, separate boolean/numeric controls, per-setting reset, translated save feedback and single-use dangerous-change confirmation. See the [visual specification and protocol](Docs/UI/MCM-PRESENTATION-V2.md). Real-game visual/input acceptance is pending.

Player packages contain runtime files, installation/diagnostic support and one `THIRD-PARTY-NOTICES.txt`. SDK, API documents, translation templates, test tools and complete dependency provenance are distributed separately in `-developer.zip`. The superseded standalone Loader, MCM and native settings repositories are compatibility/rollback sources; new native development is owned here.

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
