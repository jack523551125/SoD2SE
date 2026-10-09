# SoD2SE release record

Native player and developer archives are generated separately by Automation/Rust.ps1. The player archive contains one consolidated third-party notices file; the developer archive retains SDK, tools and complete dependency provenance. Never remove copyright, license conditions or required NOTICE content to reduce file count. No player acknowledgment dialog is required by these bundled notices.

## Authority and current state

- Version authority: Core/SoD2SE.Core.cs (`FrameworkInfo.Version`)
- Current authority value at E8 start: `0.6.0-preview`.
- Remote tags at E8 start: 0; create the first tag only in a separately authorized release.
- Release tag convention for a future approved release: `v<exact-version-value>`.
- No tag or release is created by this maintenance change.
- Framework Core/GameApi and shared native runtime. The package is the framework runtime payload; no game files are included.

## Release inputs

- Generate inputs only with `package.ps1` / `Automation/Package/package.ps1`.
- Do not hand-edit `.work` outputs or upload files copied from a game install, a local research database, a private profile, or a third-party checkout.
- Record the source commit, version authority value, build/test results, package file list, and SHA-256 for each release asset.
- Preserve current assembly names, ABI, game behavior, compatibility guard, and install-relative paths.

## Acceptance

1. Confirm the selected source commit and version match the authority above; do not infer a version from a workspace manifest.
2. Run `Automation/Build/build.ps1` and `Automation/Test/test.ps1` (or the equivalent product entrypoint) at the pinned dependency revision.
3. Record each required offline check as PASS, FAIL, or SKIPPED with its reason. A missing protected asset or research database remains SKIPPED.
4. Generate the package through `package.ps1` / `Automation/Package/package.ps1`; validate its manifest and payload against the product's release inputs.
5. Review the resulting file list, sizes, hashes, license/provenance, and install-relative paths before any separately authorized release action.

## Follower persistence source checkpoint, 2026-10-09

The final follower repair has [scoped owner acceptance](../UnlimitedFollowers/RELEASE.md#scoped-owner-live-acceptance-2026-10-09) for outside-base restart/menu-reload, nearby appearance and sustained following. This accepted candidate remains unchanged; its product record owns the artifact identities and evidence limits. It is separate from formal framework/plugin release acceptance.

The [current publication preparation and gate matrix](Docs/Migration/Rust/STATUS.md#current-publication-preparation-2026-10-09) records the available evidence, the eighteen formal check IDs, standards 19/20 and the protected UI payload distribution gap. Current source is dirty. A synchronized clean release revision, matching reviewed report and final formal artifact are still missing; the SDK's exact base pin `5eef660a560ab0c99dbed57e8ae6396e3526c7ed` does not contain the later uncommitted repair. Preserve the accepted candidate and generated evidence bytes. Future formal packaging changes artifact identity and requires affected-path revalidation, with explicit limits on any reused evidence; source commits or packaging success alone cannot transfer acceptance. The current UI receipt records protected local outputs: its input/static reviewed flag does not authorize uploading those derived resources.

The owner authorized local task-source commits and the matching exact follower dependency update. This source checkpoint excludes unrelated dirty UI, community and managed-retirement changes. It does not replace the unchanged owner-tested candidate or authorize upload, tag or game operation.

## Owner-authorized preview publication, 2026-10-09

The owner expressly authorized completing source synchronization, push, tag and GitHub Release publication for the already accepted repair. The selected release label is `v0.7.0-preview.1`; its release channel is GitHub prerelease. This dated authorization supersedes earlier statements that publication permission was still pending, only for the selected original archives below. It does not grant new installation, game, MO2-profile or save operations.

The original candidate filenames, archive metadata and payload bytes are retained. No rebuild, repack, changed candidate promotion or new acceptance result is part of this publication. The published objects remain a preview with **OWNER_REPORTED_SCOPED_PASS** for outside-base restart, same-process main-menu reload, nearby appearance and sustained following in game build 16535856 on Windows x64/native ABI 1. This is not a full or stable product acceptance result. The recorded `pending=1` remains unexplained; input-device coverage and repeat counts were not supplied.

### Selected unchanged framework artifacts

| Object | SHA-256 |
|---|---|
| Player `SoD2SE-v0.7.0-preview.1-candidate.zip` | `1da76561673ebabb76e4626ac57ac4eca85c6a51f76a3b41d91263768d05729c` |
| Developer `SoD2SE-v0.7.0-preview.1-candidate-developer.zip` | `eec191b7eb7e566d1efd7e3de0fdac9244f864db61d9b01a082958f0f276e642` |
| Accepted Runtime DLL | `3ad2e6f05b3a7f8e9eed5eea10229d4bf6e2db21d846f030e52e9cd4070e5a4f` |

The matching UnlimitedFollowers player is `52562908cc527c444597fda393cc9cbf04c5c7d278affc3a3b5949f423bcfd49`; its DLL is `7d5bc2ed6c590100a28163d3046b03e8cd7b8c143cdcb431fa699e0ee27b15e9`. Use that pair together. The complete paired archive identities and evidence limits are recorded in [the product publication record](../UnlimitedFollowers/RELEASE.md#owner-authorized-preview-publication-2026-10-09).

The accepted framework retains compatibility identity `5eef660a560ab0c99dbed57e8ae6396e3526c7ed` and was built from that base plus recorded combined uncommitted work. The later follower-task source checkpoints are framework `48be20055e4bd188da5dde9610eed51ecf174d69`, UnlimitedFollowers `2bf6a5a12a94763dad307e494a41295631d4e25b`, ReverseEngineering `406289eee22a6cf17d1cf0de6f9e3d965a0b414e`, and workspace `298e2adfc9ecad99d55a13f339e75e5ffc69f43d`. They, later documentation commits and automatic tag source archives are not a complete source snapshot for reproducing the original accepted binaries. Source-matched newer candidates remain offline evidence only. The current native version authority is `Cargo.toml` -> `workspace.package.version`; this publication does not change the version, ABI, installation paths or product dependency pins.

The owner explicitly permitted distribution of the three exact reviewed derived UI resources: `pause` SHA-256 `d0dad26df9467580b8ba0299f7aedece16f38a2ff9f73dc9e4d24cec7c3c10e4`, `main_menu` SHA-256 `a412f023727d078da1b67ea41c466496ce99f43da3968522a61b56d8dbf74170`, and `settings` SHA-256 `7b96f499b4e2c197ed7a65e945aa9093ca1bf6f0b3f906b026d5df83c06d8a78`. The historical receipt's `protected_local_output=true` and all artifact bytes remain unchanged. This permission excludes original game inputs, private saves/logs and other protected material.

[acceptance.json](Docs/Migration/Rust/acceptance.json) remains the unchanged placeholder: `reviewed=false`, pending formal revision and all eighteen checks `NOT_RUN`. The [existing gate matrix](Docs/Migration/Rust/STATUS.md#current-publication-preparation-2026-10-09), standards 19/20 and broader clean-install, upgrade/uninstall, input/frontend, save/scenario and measured-performance coverage remain open. This preview publication does not bypass the formal packager, invent results or establish full stable release acceptance. Earlier dated preparation statements retain their historical scope except for the newly explicit publication and derived-resource permissions above.
