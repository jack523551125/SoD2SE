# SoD2SE repository layout

This repository owns the Rust Loader, Runtime, semantic GameApi, Settings Registry, original UI adapter, built-in MCM and framework build/package logic. Cargo workspace package version owns the native product. `Core/SoD2SE.Core.cs` owns the retained managed line; legacy install paths and source are preserved.

```text
Rust/
  loader/ runtime/ game-api/  # Native startup, hosting and semantic access
  services/ abi/ sdk/        # Registry, diagnostics and language-neutral contracts
  mcm/                      # Built-in frontend; the only active native MCM source
  devtools/ example/ locales/ # Developer CLI, example and translation template
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

MeleeSpeed, UnlimitedCommunity, UnlimitedFollowers, SkipStartupIntro and Roguelite remain separate products. Historical managed MCM, standalone Loader and NativeModSettingsEntry are independent repositories under workspace Compatibility/. Their historical dependency pins and native CMake sources remain valid for rollback. New native MCM source and native settings packaging belong here. Packages in the workspace retain contracts and navigation notes, not duplicate runtime source.

Player packaging omits SDK headers, development documentation and test scripts. Required license text is consolidated without removing attribution or conditions. `-developer.zip` retains per-dependency license/source/hash evidence, SDK and tools; it is not installed as a player Mod.

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
