# SoD2SE native ABI 1

The native preview is State of Decay 2 System Extender. Its version authority is the root Cargo workspace package version. The legacy managed 0.6.x product, assembly names, dependency pins and packages remain available until native acceptance permits cutover. Native ABI 1 and managed plugin API 1 are different interfaces; the native loader refuses legacy DLLs.

## Build and offline checks

Install the locked toolchain using `rustup toolchain install 1.97.1 --profile minimal --component rustfmt --component clippy`. Run `pwsh -File Automation/Rust.ps1 -Command test` from this repository. All outputs go to `.work/rust`. From the workspace use `Automation/dev.ps1 test SoD2SE --rust`; MCM and UnlimitedFollowers also support `--rust` and repository-owned `rust.ps1`. Standalone plugin checkouts need the exact SoD2SE checkout as a sibling named `SoD2SE`. The native SDK pin is recorded separately from the retained managed dependency pin.

`-Command package -Candidate` generates an unpublished development ZIP. Stable packaging requires reviewed acceptance for the exact source revision, a clean checkout, and reviewed fixed-build UI asset inputs. Missing inputs are SKIPPED, never replaced by a synthetic game asset. Builds, tests and packaging do not deploy, start, attach to, or write files in a game installation.

## ABI and ownership

The authored C header is `Rust/abi/include/sod2se.h`. Plugins export `sod2se_plugin_entry(native_abi, output)`. Return a `PluginApi` with static UTF-8 id/version strings and `start`/`stop` callbacks. Version negotiation happens before start. The host passes a live function table and an owner handle; the plugin may copy that table until stop completes. UTF-8 input is borrowed for one call. Output belongs to the caller; no cross-module allocator ownership is transferred.

All structs use C layout, fixed-width integers and explicit sizes. ABI 1 targets Windows x64. Return values: 0 success; -1 invalid input/ownership; -2 unsupported version/capability; -3 busy; -4 internal failure; -5 insufficient output; -6 not found; -7 stale revision. Host requests carry operation names and UTF-8 JSON. Use at least 128 output bytes for mutations and up to 1 MiB for snapshots. Insufficient minimum capacity is rejected before a mutation; clients must not retry mutations blindly.

Host functions serialize service access and support plugin workers. Native game UI callbacks use try-locks and do not perform disk I/O. Do not call host functions recursively from a callback while holding a host-owned resource. `stop` must join plugin workers and withdraw callbacks before returning. Libraries remain resident until game exit; no public hot-unload API exists. Rust panics are contained at entrypoints; foreign access violations and aborts cannot be treated as recoverable errors. Native plugins are trusted code, not sandboxed programs.

## Services

| Operation | Input and behavior |
|---|---|
| `capabilities` | Returns target eligibility and current native UI readiness. Startup/guard failures still refuse the actual operation. Live acceptance is reported separately. |
| `plugins.snapshot` | Lists registered owner identities. |
| `settings.register` | `{definitions:[...]}`; registers only the calling plugin's namespace, once per lifecycle. |
| `settings.snapshot` | Returns definitions, desired stored values and document revision. |
| `settings.get` | `{module,id}`; reads stored desired value or registered default. |
| `settings.set` | `{module,id,value,revision,risk_ack}`; validates and commits atomically. Other namespaces require declared `settings.frontend` permission. |
| `settings.changes` | `{since}`; bounded change journal. Stale cursors require a fresh snapshot. Restart-scoped settings must be applied by consumers on the next session. |
| `settings.schema` | `{module}`; returns the stored namespace schema. Registration can declare a supported schema (default 1). |
| `settings.migrate` | `{revision,from_schema,to_schema,values}`; only the owning Mod may migrate its namespace to its declared schema. Values are validated and the old document backed up before atomic commit. Downgraded Mods are refused. |
| `state.read` / `state.write` | Owning Mod namespace only. `{scope:"profile",schema}` reads a versioned document; writing adds `{revision,value}` and atomically commits with a last-good backup. Save scope returns unsupported until GameApi supplies a verified durable identity. |
| `translation.register` | `{locale:{key:text}}`; English fallback required, owned key prefix and placeholder sets validated. |
| `translation.get` / `translation.locale` | Resolves a key / reads the detected game locale. Translation service has no MCM dependency. |
| `ui.register` | `{id,target,title,description}`; settings target only; other surfaces return unsupported. |
| `ui.publish` | `{id,model}`; model includes view and settings revisions, language, pages and typed rows. Identical publications do not invalidate the open page. |
| `ui.actions` | `{id}`; drains bounded owner-specific actions. |
| `ui.complete` | `{token,status,message}`; a settings frontend acknowledges a queued native edit after Registry commit. |
| `ui.extensions` | Lists registered extensions. |
| `game.followers.acquire` / `release` | Acquires/releases the owner's semantic follower quantity lease; addresses and bytes are private to GameApi. |
| `events.subscribe` / `events.poll` | Subscribe by prefix; read bounded value-only events with an owned handle and revision cursor. Stale cursors require resynchronization. |
| `events.publish` | Publish only under the caller's `mod.<id>.` namespace. |
| `tasks.schedule` / `tasks.cancel` | Owned background timer notifications (`task.due`), not engine-thread execution. Delays/repeats are bounded; owner cleanup cancels timers. |

Definitions contain `id`, `kind` (boolean/integer), default, optional integer minimum/maximum, label/description translation keys, `apply` (immediate/restart), and `risk` (normal/experimental/dangerous). Profile identity selects a separate Registry document. Save-scoped configuration is unavailable until a durable GameApi identity exists. Persistent gameplay state is not a settings value.

Configuration revisions prevent lost updates. Unknown future documents and corrupt documents are preserved and refused. Atomic commits retain a last-good document; explicit offline recovery must obtain the same writer lock. Legacy flat `page.option=value` settings are backed up before a one-time import; unsupported values remain preserved rather than guessed. Disabling/unregistering a plugin retains its stored configuration.

## Game and native UI boundary

Native plugin verification uses a validated single-component filename in its virtual namespace, SHA-256 and rejection of filesystem reparse/symlink paths. USVFS may resolve a DLL to an MO2 source directory while its virtual parent remains physical; physical-prefix comparison is not an ownership proof in that environment. `--preflight-launch` runs Loader checks without starting a game or activating a standalone UI overlay.

Schema migration cannot introduce a dangerous nondefault value without consent. An unchanged stored value may carry forward; other dangerous values must migrate to their default and then use acknowledged `settings.set`. Persistent state has a separate format/schema/revision and a 1 MiB limit; malformed/future data is preserved and refused. State is retained when a Mod is removed.

Only `sod2se-game-api` owns fixed-build facts. Follower descriptors use the existing reviewed patch manifest. Full image SHA-256, contexts, page boundaries, paused-thread instruction pointers and active stacks are checked before writes. Restoration verifies the complete expected patched context and refuses foreign changes. Any failed write poisons the lease; no further mutations are permitted in that session.

The Iggy bridge ports the existing reviewed 16535856 callback layout, pinned module hash/export addresses and four-argument resource protocol. It retains no player/result pointer beyond a callback. Resource activation requires a reviewed receipt and matching hashes; unknown versions and missing resources cannot enable this component. Keyboard/gamepad focus and save behavior remain live acceptance gates. The legacy resource protocol cannot carry explicit dangerous-value consent, so dangerous changes are refused there; Developer Tools can send explicit acknowledgement.

## Player installation, diagnostics and rollback

`archive-legacy <game-root> <reviewed-inventory.json>` archives only the three explicitly allowed legacy framework filenames after exact SHA-256 review. A durable transition record supports interrupted recovery. `restore-legacy <game-root>` requires native uninstall and refuses foreign targets, including identical content with a different file identity. `recover-overlay <profile-id>` removes only a matching framework-owned UI overlay after game exit. `recover-settings <offline-settings.json>` restores last-good configuration with the writer lock and preserves the damaged input.

`verify-plugins <game-root>` validates manifest/ABI/hash and exact framework revision before launch. Loader and Runtime both refuse mismatched dependency pins. Installing, updating, recovering and uninstalling the framework take the same deployment lock.

The package includes `SoD2SE/Tools/NativeTest.py` and a Chinese live-test guide. Explicit test preparation validates package/game inputs, snapshots saves, archives reviewed legacy files and installs a matched test set without starting the game. It provides MCM mode switching, sanitized reporting and ownership-checked rollback. Default offline commands never invoke preparation.

The prerequisite ZIP contains `Root` plus `Install.ps1`. Run the installer once and choose the game root. Install MCM and UnlimitedFollowers separately. Framework files are declared and hashed; existing foreign files block installation. Updates retain backups and a durable pending journal. Interrupted operations use `SoD2SE.DevTools.exe recover-install <game-root>` from the original unpacked package. Uninstall similarly runs from outside the game directory, after game/loader exit, and checks ownership before removing files. Configuration and save data remain outside the removal list. Existing unmanaged legacy installations need a separately reviewed adoption receipt; the installer never claims ownership solely from filenames.

`doctor <shipping-exe>` checks a file without launching. `verify-package <Root>` verifies package paths/hashes. `connect <session.json>` and `live-check <session.json>` query an explicitly selected running native session. `set <session.json> <mod> <id> <JSON> [--ack-risk]` writes through Registry with optimistic revision checking. Session connection nonces are local-only and must never appear in diagnostic reports. Logs rotate at 2 MiB and contain stable error codes, owner, PID and framework version.

`report <session.json> <new-report.json>` queries capabilities, plugin count, Registry revision/module count and UI extension count. It creates a fresh report and refuses to overwrite earlier evidence. Configuration values, session nonces, local paths and arbitrary response fields are excluded. Failed connections are recorded as FAIL and produce a nonzero exit code. Connectivity PASS does not certify gameplay, saves or keyboard/controller acceptance.

Native preview startup supports game root/shipping EXE selection, direct main startup, raw game arguments, MO2 child tracking and an explicit profile id. MO2 requires its updated native integration; it must map approved UI resources before launch and preserve USVFS on the actual created child. The loader never attaches to an unrelated existing game.

Use the legacy framework and legacy matching plugin packages for rollback until native save/UI/controller acceptance is complete. Candidate status must not be presented as a stable release.
