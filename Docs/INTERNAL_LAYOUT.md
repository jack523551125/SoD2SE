# SoD2SE repository layout

This repository owns SoD2SE Core, semantic GameApi, shared native implementation, pinned native vendor dependencies, and the framework build/test/package logic. Its `project.toml` is repo-local; `Core/SoD2SE.Core.cs` remains the version authority.

```text
Core/                         # Existing managed runtime assembly
GameApi/                      # Semantic, fixed-build game capabilities
Native/
  CMakeLists.txt              # SoD2SE-owned shared native tests only
  src/Shared/                 # Shared native runtime and contracts
  tests/Shared/               # Shared native tests
  vendor/                     # Pinned imgui submodule and MinHook vendor source
Automation/
  Build/                      # Framework and product build support
  Check/                      # SoD2SE-owned static checks
  Package/                    # Shared safe package resolver
  Test/                       # Framework offline checks
Docs/                         # Framework and shared-runtime documentation
Tests/                        # Framework/Core/GameApi/loader/package tests
```

MCM, MeleeSpeed, UnlimitedCommunity, UnlimitedFollowers, NativeModSettingsEntry, SkipStartupIntro, and Roguelite source/tests/manifests are owned by their own product repositories. Their native CMake files resolve this repository by the fixed revision in each product's `dependencies.lock.json`; no source junctions are required. Packages in the workspace retain contracts and navigation notes, not duplicate runtime source.

ReverseEngineering owns reviewed self-authored evidence, tools, tests, and research documentation. Game originals, dumps, unpacked assets, private data, third-party checkouts, and unreviewed generated outputs remain protected local data and are not framework source.

## Commands

From the workspace root:

```powershell
Automation/dev.ps1 build SoD2SE
Automation/dev.ps1 check SoD2SE
Automation/dev.ps1 test SoD2SE
Automation/dev.ps1 check workspace
```

From this repository checkout:

```powershell
Automation/Build/build.ps1 -FrameworkOnly
Automation/Test/check.ps1
Automation/Test/test.ps1
```

Build and test output belongs in `.work`. Framework validation never launches or attaches to the game, deploys files, or edits game data. Product-specific tests and packaging run from the product repository that owns those inputs.
