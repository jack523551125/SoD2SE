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
| 5 | Rust MCM publishes Registry models, queued edits and translations; native settings adapter owned by GameApi | Protected UI asset missing; resource generation/installation SKIPPED. Keyboard/gamepad/focus/text are NOT_RUN. |
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
