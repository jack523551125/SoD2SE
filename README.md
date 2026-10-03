# SoD2SE

[Existing usage and installation](README.zh-CN.md). Status: preview; this repository owns SoD2SE Core, GameApi, shared native runtime, and framework build entrypoints.

From workspace root: `Automation/dev.ps1 build SoD2SE`, `check SoD2SE`, `test SoD2SE`. A standalone checkout uses `Automation/Build/build.ps1` and `Automation/Test/test.ps1`. Product source lives in its own repository; no build or test requires workspace source junctions. See [DESIGN.md](DESIGN.md) for boundaries.

See [the physical internal layout and standalone commands](Docs/INTERNAL_LAYOUT.md).
