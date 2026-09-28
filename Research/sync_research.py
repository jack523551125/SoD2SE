"""Bootstrap and export the fixed-version reverse-engineering patch database.

The database under Research/StateOfDecay2/<build>/ is the editable source of
truth.  The two root manifests remain generated compatibility exports because
the loader and older verification tools already consume them.
"""
import argparse
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "Research" / "StateOfDecay2" / "16535856"
TARGET_PATH = DATABASE / "target.json"
PATCHES_PATH = DATABASE / "patches.json"


def locate_core():
    """Finds SoD2SE.Core.cs in both the development tree and a release package."""
    for candidate in (ROOT / "Core" / "SoD2SE.Core.cs",
                      ROOT / "source" / "Core" / "SoD2SE.Core.cs"):
        if candidate.is_file():
            return candidate
    raise ValueError("找不到 Core/SoD2SE.Core.cs")


def framework_version():
    """Reads FrameworkInfo.Version so the mod version has one literal."""
    match = re.search(r'public\s+const\s+string\s+Version\s*=\s*"([^"]+)"',
                      locate_core().read_text(encoding="utf-8"))
    if match is None:
        raise ValueError("Core/SoD2SE.Core.cs 没有 FrameworkInfo.Version")
    return match.group(1)


def framework_label(game_version):
    """The root manifests describe the game target, not the mod version."""
    return "SoD2SE " + game_version.replace("Update ", "fixed ")

PLUGIN_SPECS = {
    "unlimited-followers": {
        "manifest": ROOT / "patch-manifest.json",
        "domain": "follower-quantity",
        "source": "GameApi/StateOfDecay2GameApi.cs",
    },
    "unlimited-community": {
        "manifest": ROOT / "community-patch-manifest.json",
        "domain": "community-recruitment",
        "source": "GameApi/StateOfDecay2GameApi.cs",
        "plugin_id": "unlimited-community",
        "scope": "Player enclave flag 0x08 at +0xAF8; preserve non-player caps and existing rejection flags.",
    },
}
FORCE_BOOTSTRAP = False


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def slug(value):
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", value)
    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return value


def load_target():
    target = read_json(TARGET_PATH)
    required = {
        "steam_app_id", "steam_build_id", "sha256", "game_version", "framework"
    }
    missing = required.difference(target)
    if missing:
        raise ValueError("target.json 缺少字段：" + ", ".join(sorted(missing)))
    expected = "SoD2SE " + framework_version()
    if target["framework"] != expected:
        raise ValueError(
            "target.json 的 framework 为 %s，应为 %s（与 FrameworkInfo.Version 一致）"
            % (target["framework"], expected))
    return target


def database_from_root():
    target = load_target()
    patches = []
    for plugin, spec in PLUGIN_SPECS.items():
        manifest = read_json(spec["manifest"])
        for item in manifest.get("patches", []):
            entry = {
                "id": plugin + "." + slug(item["name"]),
                "plugin": plugin,
                "domain": spec["domain"],
                "manifest": spec["manifest"].name,
                "source": spec["source"],
                "name": item["name"],
                "rva": int(item["rva"]),
                "original": item["original"].lower(),
                "replacement": item["replacement"].lower(),
                "guard_rva": int(item["guard_rva"]),
                "guard_original": item["guard_original"].lower(),
            }
            patches.append(entry)
    return {
        "schema": 1,
        "target": "target.json",
        "description": "Unified byte-patch inventory for the three gameplay plugins. Root patch-manifest.json and community-patch-manifest.json are compatibility exports generated from this file.",
        "patches": patches,
        "target_sha256": target["sha256"],
    }


def render_exports(database):
    target = load_target()
    by_manifest = {}
    for item in database.get("patches", []):
        by_manifest.setdefault(item["manifest"], []).append(item)
    common = {
        "framework": framework_label(target["game_version"]),
        "steam_app_id": target["steam_app_id"],
        "steam_build_id": target["steam_build_id"],
        "sha256": target["sha256"],
    }
    exports = {}
    follower = dict(common)
    follower["patches"] = [export_patch(item) for item in by_manifest.get("patch-manifest.json", [])]
    exports["patch-manifest.json"] = follower
    community = dict(common)
    community["patches"] = [export_patch(item) for item in by_manifest.get("community-patch-manifest.json", [])]
    community["plugin_source"] = "GameApi/StateOfDecay2GameApi.cs"
    community["plugin_id"] = "unlimited-community"
    community["scope"] = "Player enclave flag 0x08 at +0xAF8; preserve non-player caps and existing rejection flags."
    exports["community-patch-manifest.json"] = community
    return exports


def export_patch(item):
    return {
        "name": item["name"],
        "rva": int(item["rva"]),
        "original": item["original"].lower(),
        "replacement": item["replacement"].lower(),
        "guard_rva": int(item["guard_rva"]),
        "guard_original": item["guard_original"].lower(),
    }


def bootstrap():
    current = read_json(PATCHES_PATH)
    if current.get("patches") and not FORCE_BOOTSTRAP:
        raise ValueError("patches.json 已有内容；如需覆盖请先确认后删除或手动迁移。")
    write_json(PATCHES_PATH, database_from_root())
    print("PASS: bootstrapped unified patch database from root manifests")


def sync(check=False):
    database = read_json(PATCHES_PATH)
    exports = render_exports(database)
    mismatches = []
    for name, expected in exports.items():
        path = ROOT / name
        actual = read_json(path)
        if actual != expected:
            mismatches.append(name)
            if not check:
                write_json(path, expected)
    if mismatches and check:
        raise ValueError("导出清单与研究数据库不一致：" + ", ".join(mismatches))
    if mismatches:
        print("PASS: regenerated " + ", ".join(mismatches))
    else:
        print("PASS: root patch manifests already match unified database")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bootstrap", action="store_true", help="create patches.json once from the existing root manifests")
    parser.add_argument("--force", action="store_true", help="allow --bootstrap to rebuild the database from root exports")
    parser.add_argument("--check", action="store_true", help="check generated manifests without writing them")
    args = parser.parse_args()
    if args.bootstrap and args.check:
        raise ValueError("--bootstrap 和 --check 不能同时使用")
    global FORCE_BOOTSTRAP
    FORCE_BOOTSTRAP = args.force
    if args.bootstrap:
        bootstrap()
    else:
        sync(check=args.check)


if __name__ == "__main__":
    try:
        main()
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit("FAIL: " + str(error))
