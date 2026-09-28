# Plugin memory smoke tests

Run `run_memory_smoke.ps1 -GameExePath <path-to-StateOfDecay2-Win64-Shipping.exe>`. To test an existing build or extracted release, add `-BuildDirectory <directory-containing-SoD2SE.Core.dll-and-Plugins>`.

When no build directory is supplied, the script compiles the framework and every plugin into a temporary directory. The harness discovers the actual plugin DLLs, captures their patch descriptors through the plugin interface, reads the matching game executable, and maps a private inert copy of its PE sections into the test process. It uses the framework's actual memory transaction implementation by reflection; it never executes those game bytes or starts the game. Temporary test binaries are removed after completion; `-OutputDirectory` retains them for diagnostics without modifying the supplied build directory.

Coverage:

- Real plugin `Initialize`/`Shutdown` with both plugin orders, exact changed byte counts, entire-image comparisons, idempotency, and independent restoration.
- Corrupted patch byte and corrupted surrounding context must reject initialization without partial changes.
- An injected failure after a partial second write must roll back all changes.
- The framework self-test separately checks write/write and both write/context conflict directions, including compatible guard-only overlap and touching boundaries.

The runner also builds `ThreadSafetySmoke.cs`. It creates disposable child processes with synthetic native loops, exercises the actual suspended-process write path, checks rejection for instruction pointers and potential stack return addresses inside a patch, verifies exact bytes, and verifies each child resumes. It does not suspend the game.

These tests do **not** prove gameplay effects, recruitment logic coverage, game startup, save compatibility, or the absence of game engine capacity limits. `MemorySession` is a test adapter around the native transaction, not the production `GameSession`; target authentication, plugin ownership, and module-range checks remain covered by production framework checks and separate diagnostics. The separate `verify_recruitment.py` executes copied game routines with controlled engine callbacks; its limitations are described in `COMMUNITY.zh-CN.md`.
MCM additionally runs `McmSmoke.cs` for bilingual configuration persistence and `McmUiSmoke.cs` for the STA overlay thread's create/shutdown lifecycle. The native-only MeleeSpeed module is covered by `MeleeNativeTest.exe` and its managed settings by `MeleeConfigSmoke.cs`; the process-memory harness intentionally excludes native-only modules and the capability-gated Survivor Roguelite plugin. `run_roguelite_smoke.ps1` verifies the latter's pure progression core, atomic sidecar format, card nonce, duplicate-kill handling, and the declarative growth screen it publishes through the UI framework. These tests do not start the game or modify its process.

`run_headless_core_smoke.ps1 -BuildDirectory <build>` runs the MCM configuration, game-language detection, removal of saved manual-language overrides, load-status, and fixed-version Game API smoke tests without opening a window or accessing a game process. The MCM smoke distinguishes successful plugin initialization from gameplay feature availability.

`run_ui_smoke.ps1` (`UiFrameworkSmoke.cs`) covers the mod-facing UI framework: surface registration and duplicate rejection, automatic shortcut assignment and persistence through `SOD2SE_UI_CONFIG`, reserved-key and duplicate-key rejection, the per-surface row cap, live build callbacks, revision-checked action dispatch, and the `wantOpen`/`seenRevision` visibility handshake. It links only `SoD2SE.Core.dll`, so it cannot observe the native renderer.

`run_mcm_integration_smoke.ps1` is the only test that reaches the native host. It compiles `McmIntegrationSmoke.cs` against a build, starts `Native\build\Release\McmRenderTest.exe` as a stand-in D3D11 host, and drives the real ABI 6 shared-memory protocol: F1/Esc, a recorded Ctrl+Shift+M binding, obsolete-binding rejection, input block/restore around the menu, swapchain resize, shortcut persistence, and a framework screen being opened, drawn (non-clear pixel check on the captured bitmap), and having its button action round-tripped back to the publishing plugin. It creates a visible window and briefly holds keyboard focus; it never touches the game process, but it must not be run while the game is running because it injects key events into the foreground window.

`run_growth_screen_preview.ps1` (`GrowthScreenPreview.cs`) renders the custom Survivor Roguelite overlay through the native host and saves a PNG. It publishes the growth surface for a synthetic survivor, checks that the rows and frame arrive, and closes the screen. This only checks the custom overlay protocol; it does not test or satisfy the required integration with the game's original Character/Community UI. The screen remains a development prototype and is not a playable release.
