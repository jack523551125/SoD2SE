"""Read-only verification for the fixed SoD2SE target executable."""

# Standalone script execution resolves imports from its source-owning project.
import sys as _layout_sys
_layout_sys.dont_write_bytecode = True
from pathlib import Path as _LayoutPath
_layout_sys.path.insert(0, str(_LayoutPath(__file__).resolve().parents[2]))
import hashlib
import json
import struct
import sys
from pathlib import Path


class VerificationError(Exception):
    pass


def parse_hex(value, label):
    if not isinstance(value, str) or not value.strip():
        raise VerificationError("%s 不是有效十六进制字符串" % label)
    try:
        result = bytes.fromhex(value)
    except ValueError as error:
        raise VerificationError("%s 解析失败：%s" % (label, error))
    if not result:
        raise VerificationError("%s 不能为空" % label)
    return result


def read_pe_sections(data):
    if len(data) < 0x40:
        raise VerificationError("EXE 文件过短")
    pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
    if pe_offset + 26 > len(data) or data[pe_offset:pe_offset + 4] != b"PE\0\0":
        raise VerificationError("不是有效的 PE 文件")
    if struct.unpack_from("<H", data, pe_offset + 4)[0] != 0x8664:
        raise VerificationError("目标不是 x64 PE 文件")
    if struct.unpack_from("<H", data, pe_offset + 24)[0] != 0x20B:
        raise VerificationError("目标不是 PE32+ 文件")
    section_count = struct.unpack_from("<H", data, pe_offset + 6)[0]
    optional_size = struct.unpack_from("<H", data, pe_offset + 20)[0]
    section_table = pe_offset + 24 + optional_size
    table_end = section_table + section_count * 40
    if table_end > len(data):
        raise VerificationError("PE 节表超出文件范围")
    sections = []
    for index in range(section_count):
        section = section_table + 40 * index
        virtual_size, rva, raw_size, raw_offset = struct.unpack_from("<IIII", data, section + 8)
        if raw_offset + raw_size > len(data):
            raise VerificationError("PE 节的文件范围无效")
        sections.append((rva, raw_size, raw_offset, virtual_size))
    return sections


def read_rva(data, sections, rva, size):
    if not isinstance(rva, int) or not isinstance(size, int) or rva < 0 or size <= 0:
        raise VerificationError("无效 RVA 范围")
    for start, raw_size, raw_offset, _ in sections:
        if start <= rva and rva + size <= start + raw_size:
            offset = raw_offset + rva - start
            return data[offset:offset + size]
    raise VerificationError("RVA 0x%X 不在文件映射节中" % rva)


def signed_byte(value):
    return value - 256 if value >= 128 else value


def verify_manifest(manifest_path, data, sections, digest):
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise VerificationError(str(error))

    raw_sha = manifest.get("sha256")
    if not isinstance(raw_sha, str) or len(raw_sha) != 64:
        raise VerificationError("清单中的 sha256 无效")
    expected_sha = raw_sha.upper()
    if digest != expected_sha:
        raise VerificationError("EXE SHA256 不匹配；没有修改任何文件")

    patches = manifest.get("patches")
    if not isinstance(patches, list) or not patches:
        raise VerificationError("清单没有补丁描述")
    normalized = []
    for patch in patches:
        try:
            name = patch["name"]
            rva = int(patch["rva"])
            guard_rva = int(patch["guard_rva"])
            original = parse_hex(patch["original"], name + ".original")
            replacement = parse_hex(patch["replacement"], name + ".replacement")
            guard = parse_hex(patch["guard_original"], name + ".guard_original")
        except (KeyError, TypeError, ValueError) as error:
            raise VerificationError("补丁清单格式错误：%s" % error)
        if rva < 0 or guard_rva < 0 or len(original) != len(replacement):
            raise VerificationError("补丁范围或字节长度无效：%s" % name)
        if not (guard_rva <= rva and rva + len(original) <= guard_rva + len(guard)):
            raise VerificationError('上下文没有覆盖补丁：' + name)
        if original == replacement or rva // 4096 != (rva + len(original) - 1) // 4096:
            raise VerificationError('无操作或跨页补丁：' + name)
        for other in normalized:
            if rva < other["rva"] + len(other["original"]) and other["rva"] < rva + len(original):
                raise VerificationError("补丁写入范围重叠：%s / %s" % (name, other["name"]))
        if read_rva(data, sections, rva, len(original)) != original:
            raise VerificationError("原始字节不匹配：%s" % name)
        if read_rva(data, sections, guard_rva, len(guard)) != guard:
            raise VerificationError("上下文字节不匹配：%s" % name)
        normalized.append({
            "name": name,
            "rva": rva,
            "original": original,
            "replacement": replacement,
            "guard_rva": guard_rva,
            "guard": guard,
        })
        print("PASS: " + name)

    if manifest_path.name == 'patch-manifest.json':
        verify_followers(data, sections, normalized)
    elif manifest_path.name == 'community-patch-manifest.json':
        verify_recruitment_layout(data, sections, normalized)
    print('PASS: ' + manifest_path.name + ' SHA256, PE and context guards')
    return normalized


def verify_followers(data, sections, normalized):

    by_name = {patch["name"]: patch for patch in normalized}
    try:
        dialogue = by_name["Dialogue follower quantity gate"]
        community = by_name["Community screen follower quantity gate"]
    except KeyError as error:
        raise VerificationError("清单缺少固定补丁：%s" % error)

    dialogue_disp = read_rva(data, sections, dialogue["rva"] + 1, 1)[0]
    dialogue_target = dialogue["rva"] + 2 + signed_byte(dialogue_disp)
    if dialogue_target != 0x22D7F5 or not (dialogue["guard_rva"] <= dialogue_target < dialogue["guard_rva"] + len(dialogue["guard"])):
        raise VerificationError("对话数量分支目标无效")
    if dialogue["replacement"] != bytes.fromhex("EB"):
        raise VerificationError("对话补丁不是短跳转替换")

    if community["replacement"][:1] != bytes.fromhex("EB") or len(community["replacement"]) < 2:
        raise VerificationError("社区界面补丁不是短跳转替换")
    community_target = community["rva"] + 2 + signed_byte(community["replacement"][1])
    if community_target != 0x39598C or not (community["guard_rva"] <= community_target < community["guard_rva"] + len(community["guard"])):
        raise VerificationError("社区界面数量分支目标无效")

    duplicate_offset = 0x395953 - community["guard_rva"]
    if community["guard"][duplicate_offset:duplicate_offset + 2] != bytes.fromhex("7432"):
        raise VerificationError("重复随从分支没有保留")
    print("PASS: SHA256, PE architecture, context guards, jump targets and duplicate branch")


def verify_recruitment_layout(data, sections, patches):
    by_rva = {patch['rva']: patch for patch in patches}
    expected = {0x276360, 0x2763A0, 0x290665, 0x29073B, 0x2797CD,
                0x290F71, 0x291A06, 0x27B432, 0x27B415, 0x27ADC9, 0x281544}
    if set(by_rva) != expected:
        raise VerificationError('Community patch inventory mismatch')
    for patch in patches:
        if patch['rva'] < 0x27D1D1 and 0x27D150 < patch['rva'] + len(patch['original']):
            raise VerificationError('The real population getter must remain unchanged')
    for rva, prolog_size, epilogue in [(0x276360, 6, '4883c4205bc3'),
                                       (0x2763A0, 10, '488b5c24304883c4205fc3')]:
        patch = by_rva[rva]
        if patch['replacement'][:prolog_size] != patch['original'][:prolog_size] or not patch['replacement'].endswith(bytes.fromhex(epilogue)):
            raise VerificationError('Query stack/unwind contract changed')
    for rva in [0x27ADC9, 0x281544]:
        replacement = by_rva[rva]['replacement']
        if replacement[0] != 0xE8 or rva + 5 + struct.unpack_from('<i', replacement, 1)[0] != 0x27B432:
            raise VerificationError('Capacity query call target mismatch')
    leaf = by_rva[0x27B432]['replacement']
    if leaf[:8] != bytes.fromhex('f681f80a00000875') or 0x27B432 + 9 + signed_byte(leaf[8]) != 0x27B415:
        raise VerificationError('Player flag/leaf branch mismatch')
    if leaf[9] != 0xE9 or 0x27B432 + 14 + struct.unpack_from('<i', leaf, 10)[0] != 0x27D150 or by_rva[0x27B415]['replacement'] != bytes.fromhex('31c0c3'):
        raise VerificationError('NPC population tail-call/zero leaf mismatch')
    pe_offset = struct.unpack_from('<I', data, 0x3C)[0]
    runtime_rva, runtime_size = struct.unpack_from('<II', data, pe_offset + 24 + 112 + 3 * 8)
    runtime = read_rva(data, sections, runtime_rva, runtime_size)
    for rva in [0x27B432, 0x27B415]:
        patch = by_rva[rva]
        if patch['original'] != bytes([0xCC]) * len(patch['original']):
            raise VerificationError('Leaf storage is not original alignment padding')
        for pos in range(0, len(runtime), 12):
            start, end, _ = struct.unpack_from('<III', runtime, pos)
            if start < rva + len(patch['original']) and rva < end:
                raise VerificationError('Leaf helper overlaps a registered unwind function')
    print('PASS: player-only query routing, preserved prologs/count getter and leaf/unwind layout')


def main():
    if len(sys.argv) != 2:
        raise VerificationError("用法：python Automation/Check/verify_game.py <StateOfDecay2-Win64-Shipping.exe>")
    try:
        data = Path(sys.argv[1]).read_bytes()
    except OSError as error:
        raise VerificationError(str(error))
    sections = read_pe_sections(data)
    digest = hashlib.sha256(data).hexdigest().upper()
    manifests = sorted(Path(__file__).resolve().parents[2].glob('*patch-manifest.json'))
    if not manifests:
        raise VerificationError('No patch manifests found')
    combined = []
    for manifest in manifests:
        patches = verify_manifest(manifest, data, sections, digest)
        for patch in patches:
            for previous in combined:
                # Separate plugins cannot normalize each other's context guards.
                if (patch['rva'] < previous['guard_rva'] + len(previous['guard']) and
                        previous['guard_rva'] < patch['rva'] + len(patch['original'])) or (
                        previous['rva'] < patch['guard_rva'] + len(patch['guard']) and
                        patch['guard_rva'] < previous['rva'] + len(previous['original'])):
                    raise VerificationError('Cross-plugin write/context collision: ' + patch['name'] + ' / ' + previous['name'])
        combined.extend(patches)
    print('PASS: cross-plugin patch/guard isolation')
    print('SHA256: ' + digest)


if __name__ == "__main__":
    try:
        main()
    except VerificationError as error:
        raise SystemExit("FAIL: " + str(error))
