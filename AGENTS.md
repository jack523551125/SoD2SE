# SoD2SE agent rules

Read README.md, DESIGN.md, Docs/INTERNAL_LAYOUT.md, and the affected product guide before editing. This repository owns Core, GameApi, shared native runtime, and framework automation; inspect this repository's Git status and preserve user work. Validate with Automation/Test/check.ps1 and Automation/Test/test.ps1 or the workspace dispatcher. `Core/SoD2SE.Core.cs` remains the version authority; do not change version, ABI, gameplay, or release paths as part of structural work.

Read [the internal layout](Docs/INTERNAL_LAYOUT.md) and [workspace Mod standards](../../Engineering/Standards/ModDevelopment.md). Product-owned sources and tests belong to their product repositories. ReverseEngineering owns reviewed evidence and research tools; raw inputs remain protected local data. Default generated output belongs in .work. Preserve assembly/ABI boundaries and avoid source junctions.
