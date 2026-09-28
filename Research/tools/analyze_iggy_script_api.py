#!/usr/bin/env python3
"""Extract the pinned Settings movie's AVM2 block and summarize its script API."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from inspect_iggy_movie import inspect_iggy


PINNED_SETTINGS_SHA256 = "e69875cd5421f8082cf4e0b66e8a2cd09ba81f8455b08243635695ea0b4bdb57"
PINNED_ABC_SHA256 = "b87ec1df0229db246d189cc0f880ab78b25014f0daa08b043c4707526ce5f74c"
PINNED_ABC_VERSION = (16, 46)
PINNED_FFDEC_VERSION = "26.3.0"
REQUIRED_SETTINGS_METHODS = {
    "InitializeCategoryMenu": "private",
    "AddCategory": "private",
    "GetSettingsCategory": "private",
    "PopulateSettingsCategory": "private",
    "AddSettingToTracker": "private",
    "AddTextSetting": "private",
    "AddToggleSetting": "private",
    "AddSliderSetting": "private",
    "AddSliderSettingWithValue": "private",
    "AddDropdownSetting": "private",
    "AddTextBlock": "private",
    "AddSubHeader": "private",
    "ApiInit": "public",
    "ApiShow": "public",
}
METHOD_RE = re.compile(
    r"(?m)^\s*(public|private|protected|internal)\s+"
    r"(?:(?:static|override|final)\s+)*function\s+"
    r"([A-Za-z_$][\w$]*)\s*\(([^)]*)\)\s*"
    r"(?::\s*([^\r\n{]+))?"
)
CLASS_RE = re.compile(r"\bpublic\s+class\s+settings\b")
CATEGORY_RE = re.compile(
    r"\b(?:public|private|protected|internal)\s+static\s+const\s+"
    r"(CATEGORY_[A-Z0-9_]+)\s*:\s*int\s*=\s*(-?\d+)"
)


def extract_abc_block(
    payload: bytes,
    *,
    section_offset: int,
    section_end: int,
) -> tuple[bytes, dict[str, int]]:
    """Extract one length-prefixed ABC block bounded by movie-relative offsets."""
    if section_offset < 0 or section_end > len(payload) or section_offset + 12 > section_end:
        raise ValueError("ABC section header is outside the movie bounds")
    marker = struct.unpack_from("<Q", payload, section_offset)[0]
    if marker != 1:
        raise ValueError("Unexpected Iggy declaration-section marker")
    abc_length = struct.unpack_from("<I", payload, section_offset + 8)[0]
    abc_offset = section_offset + 12
    abc_end = abc_offset + abc_length
    if abc_length < 4 or abc_end > section_end:
        raise ValueError("ABC payload length escapes its declared section bounds")
    abc = payload[abc_offset:abc_end]
    minor, major = struct.unpack_from("<HH", abc)
    if (minor, major) != PINNED_ABC_VERSION:
        raise ValueError(f"Unexpected AVM2 ABC version: {major}.{minor}")
    return abc, {
        "section_offset": section_offset,
        "section_end": section_end,
        "abc_offset": abc_offset,
        "abc_length": abc_length,
        "abc_end": abc_end,
        "abc_minor_version": minor,
        "abc_major_version": major,
    }


def _extract_braced_body(source: str, opening_brace: int) -> str:
    depth = 0
    quote: str | None = None
    escaped = False
    line_comment = False
    block_comment = False
    i = opening_brace
    while i < len(source):
        char = source[i]
        next_char = source[i + 1] if i + 1 < len(source) else ""
        if line_comment:
            if char in "\r\n":
                line_comment = False
        elif block_comment:
            if char == "*" and next_char == "/":
                block_comment = False
                i += 1
        elif quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char == "/" and next_char == "/":
            line_comment = True
            i += 1
        elif char == "/" and next_char == "*":
            block_comment = True
            i += 1
        elif char in "\"'":
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[opening_brace + 1 : i]
        i += 1
    raise ValueError("Unterminated ActionScript block")


def extract_class_body(source: str) -> str:
    match = CLASS_RE.search(source)
    if not match:
        raise ValueError("FFDec output does not contain public class settings")
    opening_brace = source.find("{", match.end())
    if opening_brace < 0:
        raise ValueError("Settings class has no body")
    return _extract_braced_body(source, opening_brace)


def parse_settings_script(source: str) -> dict[str, Any]:
    """Keep only method names/signatures and selected structural facts, not source."""
    class_body = extract_class_body(source)
    methods: dict[str, dict[str, Any]] = {}
    for match in METHOD_RE.finditer(class_body):
        visibility, name, params, return_type = match.groups()
        parameters = [part.strip() for part in params.split(",") if part.strip()]
        methods[name] = {
            "visibility": visibility,
            "parameter_count": len(parameters),
            "return_type": return_type.strip() if return_type else None,
        }
    missing = [
        name
        for name, visibility in REQUIRED_SETTINGS_METHODS.items()
        if name not in methods or methods[name]["visibility"] != visibility
    ]
    if missing:
        raise ValueError("Settings script method/access contract changed: " + ", ".join(missing))

    categories = {
        name: int(value)
        for name, value in CATEGORY_RE.findall(class_body)
    }
    if categories.get("CATEGORY_COUNT") != 10:
        raise ValueError("Pinned settings category count no longer matches expected source")

    initializer = re.search(
        r"(?m)^\s*private\s+function\s+InitializeCategoryMenu\s*\(\s*\)\s*:\s*void",
        class_body,
    )
    if not initializer:
        raise ValueError("Cannot locate InitializeCategoryMenu body")
    initializer_open = class_body.find("{", initializer.end())
    initializer_body = _extract_braced_body(class_body, initializer_open)
    initialized_categories = [
        {"category": name, "label": label}
        for name, label in re.findall(
            r"this\.AddCategory\(\s*(CATEGORY_[A-Z0-9_]+)\s*,\s*\"([^\"]+)\"",
            initializer_body,
        )
    ]
    expected_categories = {
        "CATEGORY_GAMEPLAY",
        "CATEGORY_MULTIPLAYER",
        "CATEGORY_CONTROLS",
        "CATEGORY_ACCESS",
        "CATEGORY_HUD",
        "CATEGORY_VIDEO",
        "CATEGORY_ADVANCED_VIDEO",
        "CATEGORY_AUDIO",
        "CATEGORY_HELP_SUPPORT",
    }
    if {row["category"] for row in initialized_categories} != expected_categories:
        raise ValueError("InitializeCategoryMenu category set differs from the pinned layout")

    public_methods = sorted(
        name for name, metadata in methods.items() if metadata["visibility"] == "public"
    )
    public_extension_methods = sorted(
        name
        for name in public_methods
        if "keybinding" not in name.lower()
        and re.search(r"(?:setting|category|mod)", name, re.IGNORECASE)
        and re.search(r"(?:add|register|create|append|insert|mod)", name, re.IGNORECASE)
    )

    add_category_body = _extract_braced_body(
        class_body,
        class_body.find(
            "{",
            re.search(r"(?m)^\s*private\s+function\s+AddCategory\s*\(", class_body).end(),
        ),
    )
    add_setting_body = _extract_braced_body(
        class_body,
        class_body.find(
            "{",
            re.search(r"(?m)^\s*private\s+function\s+AddSettingToTracker\s*\(", class_body).end(),
        ),
    )
    if "categoryList.addChild(newButton)" not in add_category_body:
        raise ValueError("AddCategory no longer creates and attaches a category button")
    if not all(
        token in add_setting_body
        for token in (
            "param1.SettingsList.container_settings.addChild(param2)",
            "param1.ButtonSet.AddButton(param2)",
            "param1.Settings.push(param2)",
        )
    ):
        raise ValueError("AddSettingToTracker no longer attaches and registers setting controls")

    key_methods = {
        name: methods[name]
        for name in REQUIRED_SETTINGS_METHODS
    }
    return {
        "class_name": "settings",
        "base_class": "base_window",
        "method_count": len(methods),
        "public_method_names": public_methods,
        "public_custom_registration_methods": public_extension_methods,
        "category_constants": categories,
        "initialized_category_calls": initialized_categories,
        "key_method_access": key_methods,
        "private_category_builder_attaches_button": True,
        "private_setting_builder_attaches_control_and_focus_entry": True,
        "public_dynamic_category_or_setting_registration_found": bool(public_extension_methods),
        "interpretation": (
            "The movie contains a native ActionScript settings implementation with dynamic control builders, "
            "but category creation and setting registration helpers are private methods. The existing public "
            "API inventory has no custom Mod/category/setting registration entry point. This does not prove "
            "that IggyPlayerCallMethodRS can or cannot resolve private-namespace methods."
        ),
    }


def make_swf_wrapper(abc: bytes) -> bytes:
    """Wrap a standalone ABC block in the minimal FWS/DoABC tags required by FFDec."""
    rect = bytes.fromhex("08 00")  # zero-size RECT with one-bit coordinates
    file_attributes_body = struct.pack("<I", 0x08)  # ActionScript 3 flag
    file_attributes = struct.pack("<H", (69 << 6) | len(file_attributes_body)) + file_attributes_body
    doabc_body = struct.pack("<I", 0) + b"\0" + abc
    doabc = struct.pack("<H", (82 << 6) | 63) + struct.pack("<I", len(doabc_body)) + doabc_body
    end = struct.pack("<H", 0)
    body = rect + struct.pack("<HH", 0x1800, 1) + file_attributes + doabc + end
    return b"FWS" + bytes([10]) + struct.pack("<I", 8 + len(body)) + body


def _run_ffdec_export(ffdec_cli: Path, abc: bytes) -> tuple[str, int]:
    version = subprocess.run(
        [str(ffdec_cli), "-help"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    version_text = version.stdout + version.stderr
    if version.returncode != 0 or f"v.{PINNED_FFDEC_VERSION}" not in version_text:
        raise ValueError(f"Expected FFDec {PINNED_FFDEC_VERSION}; version query failed")
    with tempfile.TemporaryDirectory(prefix="sod2-iggy-script-api-") as temp_name:
        temp = Path(temp_name)
        wrapper = temp / "settings-abc.swf"
        export_dir = temp / "export"
        wrapper.write_bytes(make_swf_wrapper(abc))
        result = subprocess.run(
            [str(ffdec_cli), "-export", "script", str(export_dir), str(wrapper)],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        output = result.stdout + result.stderr
        if result.returncode != 0 or "Export finished." not in output:
            raise ValueError("FFDec failed to export the extracted ABC: " + output[-1000:])
        script_path = export_dir / "scripts" / "settings.as"
        if not script_path.is_file():
            raise ValueError("FFDec export did not produce scripts/settings.as")
        source = script_path.read_text(encoding="utf-8")
        return source, sum(1 for path in (export_dir / "scripts").rglob("*.as") if path.is_file())


def build_report(iggy_path: Path, ffdec_cli: Path) -> dict[str, Any]:
    payload = iggy_path.read_bytes()
    payload_sha256 = hashlib.sha256(payload).hexdigest()
    if payload_sha256 != PINNED_SETTINGS_SHA256:
        raise ValueError(
            f"Settings Iggy hash mismatch: expected {PINNED_SETTINGS_SHA256}, got {payload_sha256}"
        )
    movie = inspect_iggy(payload, source_name=iggy_path.name)
    movie_start = movie["subfiles"][movie["movie_subfile_index"]]["offset"]
    movie_end = movie_start + movie["movie_subfile_size"]
    pointers = {row["name"]: row for row in movie["movie_header_relative_pointers"]}
    declaration = pointers.get("declaration_strings", {})
    names = pointers.get("names", {})
    if declaration.get("target_movie_offset") is None or names.get("target_movie_offset") is None:
        raise ValueError("Settings movie is missing its declaration-string bounds")
    section_offset = movie_start + declaration["target_movie_offset"]
    section_end = movie_start + names["target_movie_offset"]
    abc, abc_layout = extract_abc_block(
        payload,
        section_offset=section_offset,
        section_end=section_end,
    )
    abc_sha256 = hashlib.sha256(abc).hexdigest()
    if abc_sha256 != PINNED_ABC_SHA256:
        raise ValueError(f"Settings ABC hash mismatch: expected {PINNED_ABC_SHA256}, got {abc_sha256}")
    source, exported_script_count = _run_ffdec_export(ffdec_cli, abc)
    script_api = parse_settings_script(source)
    return {
        "schema": 1,
        "target_build": 16535856,
        "source_asset": "Art/UI/settings.uasset",
        "source_iggy_name": iggy_path.name,
        "source_iggy_sha256": payload_sha256,
        "extraction": {
            "movie_subfile_index": movie["movie_subfile_index"],
            "movie_subfile_offset": movie_start,
            "declaration_strings_movie_offset": declaration["target_movie_offset"],
            "section_marker": 1,
            "abc_sha256": abc_sha256,
            **abc_layout,
            "padding_before_names_bytes": section_end - abc_layout["abc_end"],
        },
        "decompiler": {
            "name": "JPEXS Free Flash Decompiler",
            "version": PINNED_FFDEC_VERSION,
            "exported_script_file_count": exported_script_count,
            "source_and_abc_retained_in_report": False,
        },
        "settings_script": script_api,
        "external_primary_sources": [
            {
                "url": "https://www.radgametools.com/iggy.htm",
                "supports": "Iggy runs Flash-authored interactive content and supports ActionScript 3.",
            },
            {
                "url": "https://www.radgametools.com/iggyhist.htm",
                "supports": "The published API history describes IggyPlayerCallMethodRS for methods on objects addressed by IggyValuePath and arbitrary IggyValuePath arguments for IggyPlayerCallFunctionRS.",
            },
        ],
        "scope": "Offline extraction and decompilation of the pinned Settings movie's ABC; no game process, DLL loading, or runtime invocation.",
        "limitations": [
            "Decompiled method visibility is evidence from the embedded ABC; it does not prove the exact name-resolution rules used by IggyPlayerCallMethodRS.",
            "No controls were created or attached, and the report does not prove that the game accepts a modified Settings movie.",
            "The extracted ActionScript source and ABC bytes are intentionally not copied into the repository report.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iggy", type=Path, required=True, help="Pinned extracted settings.iggy")
    parser.add_argument("--ffdec-cli", type=Path, required=True, help="JPEXS FFDec 26.3.0 CLI executable")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = build_report(args.iggy, args.ffdec_cli)
    except (OSError, ValueError, struct.error) as error:
        parser.error(str(error))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        "PASS: extracted pinned Settings ABC and mapped "
        f"{report['settings_script']['method_count']} settings-class methods"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
