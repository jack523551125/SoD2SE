# Rust migration execution record

Owner decision: merge SoD2SE, SoD2SE-Loader and NativeModSettingsEntry into SoD2SE — State of Decay 2 System Extender. The subsequent bundling decision moves native MCM into the prerequisite as a built-in Registry frontend; UnlimitedFollowers remains separate. Original UI extension v1 targets settings only. New native ABI; preserve managed rollback packages. Framework services and gameplay plugins do not require the MCM implementation; without-frontend acceptance is an isolated developer scenario, not a player installation step.

## Current publication preparation, 2026-10-09

The owner accepted the final UnlimitedFollowers candidate's outside-base restart, same-process main-menu reload, nearby appearance and sustained following. This is **OWNER_REPORTED_SCOPED_PASS** for the reported fault in the recorded environment, not formal framework or plugin release acceptance. The [product's scoped acceptance](../../../../UnlimitedFollowers/RELEASE.md#scoped-owner-live-acceptance-2026-10-09) is the authority for the tested candidate, ZIP/Runtime hashes, environment, owner feedback and coverage limits. Its [final offline/install record](../../../../UnlimitedFollowers/RELEASE.md#outside-base-reload-failure-2026-10-09) identifies the retained candidate and installation evidence. The generated installation handoff still records pending live acceptance; those original bytes remain unchanged, while the later scoped owner result supersedes that pending state only for the reported fault.

The tested source is framework base revision `5eef660a560ab0c99dbed57e8ae6396e3526c7ed` plus recorded uncommitted changes, including shared framework work. The exact SDK pin at that revision does not identify or contain the later uncommitted repair. Current source is dirty; a synchronized clean release revision, matching reviewed formal report and final formal package have not been prepared. Preserve the accepted candidate bytes and their evidence. Committing source or packaging a formal ZIP cannot automatically transfer the candidate's acceptance to changed artifact bytes.

The table separates evidence already available from the remaining release work. These are scoped static, offline, installation or owner-reported observations as stated; no formal gate is promoted to PASS here. [acceptance.json](acceptance.json) remains the unchanged schema-1 placeholder: `reviewed=false`, pending release revision and all 18 checks `NOT_RUN`.

| Formal check ID | Available scoped evidence | Remaining coverage or review |
|---|---|---|
| `save-compat` | Owner-reported final restart/menu-reload and nearby following. | Full existing-save load/play/save/reload, supported modes, community/slot isolation, dismissal/death/task cases and recovery. |
| `safe-uninstall` | Offline ownership/refusal tests and verified predecessor backup. | Exit, uninstall and original-game load/play/save of affected saves, including applicable over-capacity states. |
| `update-compat` | Owned framework update with backup; offline Registry migration/state recovery tests. | Matched plugin/framework upgrade, rollback and configuration/state failure recovery through actual user paths. |
| `original-file-integrity` | Nine protected files retained exact bytes at the final framework installation; twelve predecessor files verified in backup. | Complete clean-install/update/uninstall ownership inventory and original/other-Mod integrity through those paths. |
| `fail-closed` | Independent C ABI, inert foreign-process refusal and authored context/native-call guard tests. | Final-object unsupported image, dependency/ABI/capability and resource refusal coverage with diagnostics. |
| `api-docs` | Current [native API contract](../../RUST-API.md), including follower identity, ownership, guards and restoration conditions. | Formal contract review against the exact release source and consumer integration. |
| `diagnostics` | Owner-session log stages and nearby/AI-target confirmations; sanitized report allowlist tested offline. | Final live report inspection and failure/recovery coverage. The remaining `pending=1` is unexplained and does not prove complete restoration of every stored entry. |
| `git-provenance` | Recorded base revisions, selected source hashes, candidate/installed hashes and retained local evidence. | Review and synchronize exact clean owning-repository commits/dependencies, then separately update the workspace gitlinks. |
| `shared-gameapi` | Final record: 73 GameApi cases and ten fixed-original follower checks; shared implementation and research references. | Exact-release-source evidence/promotion review and applicable live integration beyond the accepted fault. |
| `gameapi-only` | UnlimitedFollowers source uses semantic SDK services for quantity/persistence, with no product-owned raw game access. | Final official consumer/source audit at the release revisions; do not inherit platform PASS without integration evidence. |
| `rust-abi` | Rust build/check/test, independent C consumer and inert refusal fixtures; ABI 1 pairing. | Exact clean release source, dependency and final DLL/package identity review. |
| `input-support` | Xbox Bluetooth hardware is recorded; the scoped owner result does not identify input coverage. | Final keyboard/controller recruitment, interaction, focus, confirm/back and device-switch coverage. |
| `live-tools` | Offline diagnostic/session and redaction tests; tool commands documented. | Connect/report against the explicitly selected final test session and record reproducible checks; connectivity alone is insufficient. |
| `translations` | Catalog/template and package checks; native text contract documented. | Actual final text, fallback, layout and display paths for the declared locales. |
| `mcm-optional` | Registry/API independence and offline frontend-absence paths; follower plugin registers an empty settings namespace. | Isolated developer-host gameplay without the frontend, preserving effective configuration; do not move bundled MCM files in the player installation. |
| `mcm-adapter` | Registry/UI protocol tests and historical basic MCM owner observations. | Final pause-panel edits, persisted roundtrip, stale/failed saves, repeated open/close and keyboard/controller focus. |
| `risk-markers` | Offline Registry acknowledgement/refusal and presentation tests. | Final frontend labels, dangerous-change confirmation and execution-side refusal through the actual UI path. |
| `settings-authority` | Registry contract and semantic plugin integration; persistent roster state is separate from settings. | Exact-source frontend/consumer audit plus effective configuration retention when the frontend is absent or fails. |

Standard 19 additionally requires applicable automated checks, actual user paths and a clean installation of the final released object. Current candidate CRC/hash/pairing checks, owned update and scoped gameplay acceptance do not cover clean installation or the full matrix. A future formal package will have different metadata and archive bytes; record its identity, revalidate affected paths and explicitly justify any reuse of unchanged evidence. Do not edit or relabel the accepted generated candidate.

Distribution scope also remains unresolved: the accepted player package includes derived `pause`, `main_menu` and `settings` UI resources. Its `Root/SoD2SE/Assets/native-ui.json` receipt records `protected_local_output=true`; `reviewed=true` covers the stated fixed-input/static review, not permission to distribute protected outputs. The candidate and those inputs remain local evidence. Review permitted distribution inputs and package scope before any upload; neither packaging success nor the receipt's reviewed flag resolves this boundary.

Standard 20 remains open for actual game frame time, memory and resource growth. The [product design](../../../../UnlimitedFollowers/DESIGN.md#最终候选包与一次实机验收准备) records historical authored 20-person journal measurements and their offline budgets. Those measurements do not measure the final native game-access/restoration workload. Record a representative environment/load, duration and live budgets before the final performance run; no live numerical budget or measurement is claimed here.

Preparation can continue without game operations: review the final source/API/dependency and distribution boundaries, preserve evidence and candidate identity, and maintain the remaining scenario records in these existing product documents. Once separately authorized, commit and synchronize the owning repositories before the separate workspace gitlink commit; identify the exact paired release object and report. The remaining live coverage should be one final acceptance campaign in an authorized isolated environment, with installation/upgrade/uninstall, configuration/input/failure paths and performance recorded together. The already accepted follower fault does not require another intermediate test or roster reseeding. Formal packaging and publication remain separate authorized actions after the applicable evidence and permitted payload scope are reviewed.

The selected source checkpoint passed its own isolated native build/check/test: 53 GameApi cases, the remaining Rust suites, independent C ABI and inert foreign-process bootstrap refusal. The selected snapshot also passed 16 Python checks plus four subtests and cached diff validation. These results cover the task-only tree and do not replace the larger combined candidate's historical test counts or scoped owner result.

The local source checkpoint for this task selects the follower implementation, contracts and task evidence only. Existing UI, community and managed-retirement changes remain outside that checkpoint; the accepted installed Runtime was built from the recorded combined working tree. This checkpoint receives separate offline verification and is not relabeled as that accepted binary. Local commits and the matching follower dependency update are authorized by the owner; push, publication and additional game operations are not authorized.

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
| 4 | Rust UnlimitedFollowers requests semantic quantity and persistence leases; no quantity slider added | Outside-base restart/menu-reload and nearby following have scoped owner acceptance above; full save/gameplay/uninstall coverage remains pending. |
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

On 2026-10-05 the owner confirmed both MCM entries open and UnlimitedFollowers works, but reported a blank MCM panel. Fixed original movie inspection found the menu code accessing the private dynamic_text.textField getter. The authored resource renderer now uses native symbol text and the nested wrapper's public getter; both resource builders validate the independently decoded result. Runtime logs numeric drawing stages through MCM_PANEL_DRAW_STAGE. Static generation and package validation remain separate from the owner's pending rendering/controller retest.

The owner subsequently requested one SoD2SE prerequisite with built-in MCM and Plugins-based configuration. Native MCM source is now canonical in Rust/mcm, preserving its prior source revision e2bcd2e33a479e9d77c2349753ab1738774f56cf in the compatibility repository's history. Framework packages include Mcm.dll and its native manifest under SoD2SE/BuiltinPlugins. Registry persistence uses Plugins/SoD2SE/Settings/<profile>/registry.json and imports the old AppData document once without removing it. MO2 prepares overwrite/Root/Plugins with an explicit creation target; Loader directly creates Plugins only in standalone mode. A real USVFS authored filesystem test created and atomically replaced configuration under overwrite without creating a physical target Plugins directory.

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
