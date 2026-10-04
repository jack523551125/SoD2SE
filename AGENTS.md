# SoD2SE agent rules

Native MCM is canonical under Rust/mcm and bundled in the prerequisite. Do not create a second active native MCM implementation. Registry files are under Plugins/SoD2SE/Settings/<profile>; MO2 supplies the overwrite creation target.

The owner-authorized native migration is implemented under Rust/ and the root Cargo workspace. Cargo workspace package version owns the native preview; existing FrameworkInfo.Version owns the retained managed line. Use Automation/Rust.ps1 or workspace --rust for native build/check/test/package. Preserve legacy packages and record missing live/protected-input acceptance; do not retire compatibility repositories or publish a native release before mandatory gates pass.

Read README.md, DESIGN.md, Docs/INTERNAL_LAYOUT.md, and the affected product guide before editing. This repository owns Core, GameApi, shared native runtime, and framework automation; inspect this repository's Git status and preserve user work. Validate with Automation/Test/check.ps1 and Automation/Test/test.ps1 or the workspace dispatcher. `Core/SoD2SE.Core.cs` remains the version authority; do not change version, ABI, gameplay, or release paths as part of structural work.

Read [the internal layout](Docs/INTERNAL_LAYOUT.md) and [workspace Mod standards](../../Engineering/Standards/ModDevelopment.md). Product-owned sources and tests belong to their product repositories. ReverseEngineering owns reviewed evidence and research tools; raw inputs remain protected local data. Default generated output belongs in .work. Preserve assembly/ABI boundaries and avoid source junctions.
