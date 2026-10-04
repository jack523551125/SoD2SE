# Rust migration execution record

Owner decision: merge SoD2SE, SoD2SE-Loader and NativeModSettingsEntry into SoD2SE — State of Decay 2 System Extender. First native delivery includes MCM and UnlimitedFollowers. MCM remains optional. Original UI extension v1 targets settings only. New native ABI; preserve managed rollback packages.

## Baseline

The generated `baseline.json` records source revisions, legacy source hashes, repository state and every command/log hash. Workspace check and legacy SoD2SE, Loader and MCM build/check/test passed. UnlimitedFollowers build/check passed; its legacy product fixture was absent (SKIPPED). NativeModSettingsEntry build/check/test were SKIPPED without the protected asset. MO2-Support build/check passed and tests had 11 existing failures / 66 passes, primarily assertions against Chinese errors after uncommitted English localization changes. Those user changes are preserved.

No historical release artifact is overwritten. Legacy source revisions recorded here remain the rollback authority. New work uses `codex/sod2se-rust` branches and product-owned commits. GitHub synchronization does not imply a stable binary release or permission to upload protected inputs.

## Stage gates

| Stage | Implemented work | Remaining acceptance |
|---|---|---|
| 0 | Legacy baseline generator, recorded checks, source provenance, decisions and acceptance matrix | Baseline is not live certification. |
| 1 | Native ownership converges on SoD2SE; common Rust build/package entrypoint; legacy source dependency cache preserves exact old pins | Retire old repositories only after consumers and release gates pass. |
| 2 | Native ABI/C header, thin SDK, Registry, import/backups, UI model, translations, diagnostics, example | Offline test results are recorded by the entrypoint; API stability awaits review. |
| 3 | Rust launch/injection, game-process runtime, owned services, fixed-build follower adapter, guarded Iggy bridge and local tools connection | Actual game startup/MO2/cleanup are NOT_RUN. |
| 4 | Rust UnlimitedFollowers requests semantic GameApi lease; no quantity slider added | Existing saves, gameplay conditions and uninstall saves are NOT_RUN. |
| 5 | Rust MCM publishes Registry models, queued edits and translations; native settings adapter owned by GameApi; protected fixed-build asset reproduced and statically reviewed locally | Resource installation and keyboard/gamepad/focus/text are NOT_RUN. |
| 6 | Candidate packaging, file hashes, installer ownership, update/recovery/uninstall and release gates | Stable release, topology cutover and remote archival blocked by mandatory missing acceptance. |

These gates prevent code completion being confused with release acceptance. Default managed entrypoints are retained during the transition; native entrypoints are selected with `--rust`.

## Required live scenarios

Use a specifically selected test community/save and MO2 profile after preserving the original. No default offline command launches, attaches, deploys or touches profiles/saves. Developer Tools can query an explicitly launched test session; its diagnostic success does not prove save compatibility.

1. Without MCM: native startup, follower invitations through dialogue/community UI, duplicate/relationship/mission conditions, game exit and restart.
2. With MCM: original settings entry, loaded state, bool/integer edits through Registry, successful/failed/stale saves, repeated open/close, keyboard and controller focus/confirm/back.
3. Existing-save load/save/reload, game exit, framework/mod upgrade, rollback and original game after uninstall, including over-capacity follower states.
4. Unsupported image and mismatched resource/module: no runtime mutation or stale UI overlay; clear diagnostics.
5. MO2 profile switching, USVFS on actual child, enable/disable both plugin packages, conflict refusal and complete session tracking.

Missing fixed inputs remain SKIPPED. No synthetic original asset, accepted save, game process or controller result is substituted.

## Owner-directed test handoff

On 2026-10-05 the owner reported that the current features work in game, then requested removal of the persistent command window. This confirms the basic live load/function path; it does not certify all save/update/controller scenarios. Player release Loader binaries now use the Windows GUI subsystem, with an explicit developer `--console` opt-in and existing file logging.

After child readiness succeeded, the owner reached RUNTIME_MODULE_FOUND but bootstrap returned -1. Local profile state confirmed that legacy import had completed. Runtime's separate DLL-loading function still compared physical canonical paths and rejected legal mapped DLLs. Runtime now obtains its virtual DLL path from the same manifest verifier as preflight, and shares DLL/ABI inspection with a developer-only inactive probe. Plugin refusals are logged with manifest identity and stable error code; no real-game success is inferred from the probe.

A read-only isolated USVFS diagnostic reproduced the continuing `-1`: all three DLL hashes matched, but their resolved paths were outside the physical virtual-parent directory. The old Rust preflight returned `PLUGIN_PREFLIGHT_REFUSED: -1` in this non-game child. Verification now retains the safe virtual filename with hash/link guards rather than requiring physical-parent containment. A full non-launching Loader preflight is provided for this diagnostic; real-game results remain separate.

The first owner-run standalone test failed: MCM and UnlimitedFollowers were not effective, and the loader recorded `LAUNCH_FAILED: -4` without Runtime initialization logs. This is a failed live result, not a pass. Investigation found extended-length (`\\?\`) DLL paths were compared literally with ToolHelp's ordinary paths. The Loader now normalizes full Windows paths, retries early module enumeration, and emits injection stage diagnostics. An authored inert child fixture exercises actual remote loading and confirms bootstrap rejects the foreign image; no game is started by this fixture.

The owner requested gameplay Mods only through `E:\Game\SD2_mod`. Physical test plugins are withdrawn; the framework stays in the game root, while matched MCM/follower/example packages use a dedicated native MO2 profile. Subsequent game tests remain the owner's responsibility.

The owner confirmed Xbox Bluetooth input and reserved live testing for themselves. Preparation/installation is authorized; the agent must leave the game stopped and provide an explicit launch entrypoint. NativeTest.py snapshots and verifies local saves, installs matched packages, switches MCM modes and checks ownership during rollback. Portable MO2 preparation uses a separate program copy/profile; shared test saves are backed up. Formal release eligibility and retiring compatibility repositories remain contingent on the owner's live results.

Additional offline implementation includes profile-scoped persistent state (save scope is unsupported without verified identity), legacy transition/recovery, installation writer locking, module snapshot retries, exact plugin/framework dependency checks in both Loader and Runtime, cross-frontend UI completion ownership, and migration consent guards. Packages now carry locked Cargo source/checksum/license evidence. A clearly labelled optional SDK fixture provides configuration controls without gameplay changes.

## Additional execution, 2026-10-04

- Reproduced the original settings component from installed build 16535856 through the research-owned parser/movie/container tools. Original asset SHA-256: `d8d320363be69ea9dfb39b5c20c8de5237c642841fe3ac86b00f8115050fe06e`. Generated component SHA-256: `5fa3cdc9e4a3f5aaeee1a7f8ddeae30a42f9bdc98c6f4971338373e4c47c81bd`. Static movie review, container roundtrip and independent CUE4Parse validation passed. Original bytes and generated asset remain protected local data; this is not live acceptance.
- Added Developer Tools diagnostic export with an explicit field allowlist and a regression test excluding session secrets, configuration values and protected paths.
- Native workspace tests passed, including the new diagnostic export test, independent C ABI fixture and inert foreign-process Runtime refusal. No game was launched by these checks.
- SoD2SE, MCM, UnlimitedFollowers and MO2-Support migration branches were synchronized through private Git remotes. A per-command proxy override resolved the previous localhost proxy failure; global Git settings were preserved.
- Located the existing SoD2 MO2 instance: it uses a shared-save Default profile containing other gameplay mods. A separate test profile and save preservation are still required before controlled live acceptance.
