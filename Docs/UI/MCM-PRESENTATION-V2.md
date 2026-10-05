# MCM presentation v2

The authored [visual specification](mcm-preview.html) has Chinese, English, Xbox focus, no-settings, long-text and save-error states. It contains no game assets and is not a game screenshot. Browser screenshot validation was unavailable in this environment; the automated approval layer refused the headless browser launch.

## Layout and interaction

The 1920×1080 canvas contains a centered 1400×880 panel with a 360-pixel Mod column, a 32-pixel gap, and a 944-pixel settings column. One viewport scale preserves proportions. Fonts are 32/28/24/20 design pixels; labels use native existing TextFields found through the public display tree. Font bindings survive reparenting; public TextFormat controls size/alignment, and fixed width/height enables wrapping/scrolling without custom game getters or font shrinking.

The sidebar shows eight Mods and the parameter area four rows. Selection has an orange marker; input focus has a border; pointer hover has its own background. Boolean and integer controls have separate hit targets, with boundary/pending controls disabled. Long names have shortened headers and complete text in the detail area. Details scroll by wheel/buttons; keyboard/controller navigation enters a scrollable detail area after the final row, then proceeds to per-setting reset and close. The last valid Mod ID survives reopening.

The overlay hides and later restores original movie children, consumes original menu inputs while open and dims the viewport. Native input_mode_manager action icons provide current keyboard bindings/Xbox glyphs. No hardcoded keyboard key is presented as the actual binding. The main menu retains its original focus graph; pause restores its saved button index.

## Model and protocol

The C ABI remains 1. JSON Model adds presentation=2 and chrome, Page adds optional version, and OptionRow adds optional default_value. Old fields and configuration IDs are unchanged. The ordered localization keys and geometry authority are in Rust/mcm/ui-contract.json. The research generators consume that contract; all shell translations are registered through the host translation service. Opening takes one complete language/model snapshot; transient read failures are retried without switching languages.

SoD2SE_Mcm_v1 retains its behavior and never acknowledges dangerous edits. SoD2SE_Mcm_v2 uses the same four integer arguments (operation, session token, index, value). Operations 0–19 retain their meanings, except v2 numeric setting data (10–12) uses decimal UTF-8 replies, distinguishing valid negative values from BUSY errors. V2 description operation 8 omits legacy bilingual risk suffixes.

| Operation | Result/action |
|---|---|
| 20 | Localized shell text by contract index |
| 21 / 22 | Stable Mod ID / optional version |
| 23 | Default as decimal text; empty when absent |
| 24 | Risk: normal 0, experimental 1, dangerous 2 |
| 25 | Prepare dangerous value: returns positive one-use nonce |
| 26 | Confirm nonce supplied as index |
| 27 | Cancel outstanding confirmation |
| 28 | Whether a default exists |

Consent is bound to the open snapshot, exact row/target and Registry revision, expires after 30 seconds, and is consumed on confirmation. Closing, reopening, cancellation, external changes and replay cannot grant consent. The Registry still performs final validation and atomic persistence. Per-setting reset reuses this edit path; batch reset is absent.

Accepted changes show Saving, then Saved for 1.8 seconds; failed writes restore committed values. Restart metadata remains visible in details and is never reported as an observed runtime effect. External model/value changes invalidate a v2 view and expose Refresh/Close. Empty MCM self-pages are omitted; no-setting gameplay Mods retain their status page. The separate development example includes inert risk/restart/long-text fixtures and is not part of the player prerequisite.

## Acceptance boundary

Rust state tests cover consent cancellation, expiry, replay, revision changes, default restoration, negative values, rollback and legacy behavior. Resource builders preserve original methods/bindings and validate authored calls, shared contract helpers and approved font access before container validation. Real font rendering, hover geometry, backdrop input isolation and Bluetooth Xbox navigation require owner game testing at 1080p, 1440p and 4K. Preparation must not launch the game.
