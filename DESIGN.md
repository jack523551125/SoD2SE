# SoD2SE design boundary

## Authorized Rust transition

After the E01/E02 native-control experiment passed owner testing, MCM optimization moves rendering to a dedicated Mod view hosted by the original settings layer. Pause/main-menu entries issue a one-shot internal request; the native host retains modal and hint ownership. Framework-owned, hash-checked settings/pause/main_menu resources ship together. Plugins still register only Registry data, and the public C ABI remains unchanged. This does not claim arbitrary independent Iggy-player creation.

The owner subsequently requested an independent pause MCM panel. The fixed pause movie receives three bounded hooks and an authored component; original settings is no longer overlaid. GameApi selects only a reviewed settings/pause resource with fixed original identity and derived hash. The current built-in MCM uses pause; Runtime refuses UI targets that do not match the active resource. Settings configuration identities, file format and game/save behavior are unchanged. Authored resource tooling/evidence belongs to ReverseEngineering; runtime guards, lifecycle, API and packaging belong here.

The owner subsequently authorized moving native MCM ownership into this Cargo workspace and bundling it in the framework. `SoD2SE/BuiltinPlugins` is framework-owned; external Mods and Registry persistence use the Plugins namespace. MO2 supplies an explicit overwrite creation target. Config IDs/formats are unchanged; the old AppData Registry document is preserved and imported once into the new profile-scoped location. SDK/gameplay access remains independent of the frontend.

The owner approved merging Loader and NativeModSettingsEntry responsibilities into this repository. The new native line uses the Cargo workspace version authority, C ABI 1, profile-owned Settings Registry, GameApi-only game access and a generic original-UI extension interface (settings surface first). Native MCM is the bundled Registry frontend; UnlimitedFollowers remains an independent Rust plugin. Native release and retiring the old submodules require the explicit gates in Docs/Migration/Rust/STATUS.md. The managed line below remains the historical compatibility boundary during staged rollout.

Product: SoD2SE. Current status: preview. This repository owns Core, GameApi, shared native runtime, and framework automation. The machine-readable entry is project.toml; version authority is `Core/SoD2SE.Core.cs`.

This is an independent Git repository. Its build/release scripts must work independently of workspace navigation. Do not assume another repository's Core or GameApi snapshot can replace its files.

Invariants: no game-file mutation; preserve version guards, ABI, existing package paths and save behavior. Gameplay changes are outside the directory migration. Production access uses GameApi; evidence remains research.

Validation: use the root Automation/dev.ps1 commands. Offline tests do not certify gamepad coverage, localization completeness, save compatibility or game integration. Existing implementation is C#/C++ or Python; Rust and C ABI adoption is a separate task.

## Responsibilities and interactions

Core owns lifecycle, configuration, events and runtime services; GameApi owns semantic fixed-build capabilities; shared Native code and pinned vendor dependencies are consumed by product-owned native builds. MCM, MeleeSpeed, UnlimitedCommunity, UnlimitedFollowers, NativeModSettingsEntry, SkipStartupIntro and Roguelite are separate repositories. ReverseEngineering owns reviewed research evidence and tools, not a runtime API. This repository does not rely on source junctions.

## Current physical source layout

Core uses Runtime/Input/UI/Interop/Growth directories within the same assembly. Native/src and Native/tests separate implementation and tests by Growth/Mcm/Melee/Shared; vendor remains isolated. Automation owns actual Build/Check/Package/Deploy/Test scripts. Research/tools and Research/tests use semantic topic packages. Tests groups managed fixtures by consumer. See [internal layout](Docs/INTERNAL_LAYOUT.md) for commands, source ownership and compatibility details.
