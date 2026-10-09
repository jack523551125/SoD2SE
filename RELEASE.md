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
