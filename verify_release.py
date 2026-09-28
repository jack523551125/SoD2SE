"""Verify the file hashes and exact layout recorded in RELEASE-MANIFEST.json."""
import hashlib
import json
import sys
from pathlib import Path


class VerificationError(Exception):
    pass


def main():
    base = Path(sys.argv[1]).resolve() if len(sys.argv) == 2 else Path(__file__).resolve().parent
    manifest_path = base / "RELEASE-MANIFEST.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        raise VerificationError(str(error))
    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries:
        raise VerificationError("发布清单没有文件记录")
    expected = set()
    for entry in entries:
        try:
            relative = entry["path"].replace("/", "\\")
            size = int(entry["size"])
            expected_hash = entry["sha256"].upper()
        except (KeyError, TypeError, ValueError) as error:
            raise VerificationError("发布清单格式错误：%s" % error)
        relative_path = Path(relative)
        if relative in expected or relative == "RELEASE-MANIFEST.json" or relative_path.is_absolute() or ".." in relative_path.parts:
            raise VerificationError("发布清单路径无效或重复：" + relative)
        expected.add(relative)
        path = base / relative
        if not path.is_file():
            raise VerificationError("缺少发布文件：" + relative)
        actual_size = path.stat().st_size
        actual_hash = hashlib.sha256(path.read_bytes()).hexdigest().upper()
        if actual_size != size or actual_hash != expected_hash:
            raise VerificationError("发布文件校验失败：" + relative)

    actual = {
        str(path.relative_to(base)).replace("/", "\\")
        for path in base.rglob("*")
        if path.is_file() and path.name != "RELEASE-MANIFEST.json"
    }
    if actual != expected:
        extra = sorted(actual - expected)
        missing = sorted(expected - actual)
        raise VerificationError("发布目录布局不一致；额外：%s；缺少：%s" % (extra, missing))
    print("PASS: release manifest, file hashes and package layout")


if __name__ == "__main__":
    try:
        main()
    except VerificationError as error:
        raise SystemExit("FAIL: " + str(error))
