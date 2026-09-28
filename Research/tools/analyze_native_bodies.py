#!/usr/bin/env python3
"""Decode selected SoD2 x64 native bodies and direct-call edges offline.

This is a static-analysis companion to the dependency-free PE tools. It uses
Capstone for instruction boundaries and never starts or attaches to the game.
The output deliberately records address-level evidence, not guessed C++ or
UFunction signatures.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import struct
import sys
from pathlib import Path

from pe_static import PeImage


ROOT = Path(__file__).resolve().parents[2]
DATABASE = ROOT / "Research" / "StateOfDecay2" / "16535856"
MAX_BODY_BYTES = 256 * 1024
MAX_RAW_CALL_CANDIDATES_PER_TARGET = 1024
MAX_STORED_CALLERS_PER_TARGET = 256
NATIVE_KINDS = {"native-ufunction", "ui-native-candidate"}
FOLLOWUP_NATIVE_NAMES = {
    "OnZombieKilled",
    "AuthOnZombieKilled",
    "AddZombieKilled",
    "GetCharacterWhoHitMost",
    "GetCurrentAttackers",
    "AddOrUpdateAttacker",
    "GetNumAttackers",
}


def is_xref_focus_record(row: dict, focus_doc: dict) -> bool:
    focus_ids = set(focus_doc.get("function_ids", []))
    focus_prefixes = tuple(focus_doc.get("function_id_prefixes", []))
    return any(
        function_id.startswith(focus_prefixes)
        or function_id in focus_ids
        for function_id in row.get("function_ids", [])
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _rva(value) -> int:
    return int(str(value), 16)


def collect_targets(functions_doc: dict, domains_doc: dict, pairs: list[dict]):
    """Join curated records and candidate names to exact native-pair rows."""
    pairs_by_name: dict[str, list[dict]] = {}
    pairs_by_identity: dict[tuple[str, int, int], dict] = {}
    names_by_rva: dict[int, set[str]] = {}
    for pair in pairs:
        name = str(pair.get("name", ""))
        func_rva = _rva(pair["func_rva"])
        pair_rva = _rva(pair["pair_rva"])
        normalized = {
            "name": name,
            "func_rva": func_rva,
            "pair_rva": pair_rva,
        }
        pairs_by_name.setdefault(name, []).append(normalized)
        pairs_by_identity[(name, func_rva, pair_rva)] = normalized
        names_by_rva.setdefault(func_rva, set()).add(name)

    targets: dict[tuple[str, int, int], dict] = {}

    def include(pair: dict, function_id: str | None = None, domain_id: str | None = None):
        key = (pair["name"], pair["func_rva"], pair["pair_rva"])
        item = targets.setdefault(
            key,
            {
                "native_name": pair["name"],
                "function_rva": pair["func_rva"],
                "registration_rva": pair["pair_rva"],
                "function_ids": set(),
                "domain_ids": set(),
            },
        )
        if function_id:
            item["function_ids"].add(function_id)
        if domain_id:
            item["domain_ids"].add(domain_id)

    missing_functions = []
    for function in functions_doc.get("functions", []):
        if function.get("kind") not in NATIVE_KINDS or not function.get("symbol") or not function.get("rva"):
            continue
        symbol = function["symbol"]
        function_rva = _rva(function["rva"])
        candidates = [p for p in pairs_by_name.get(symbol, []) if p["func_rva"] == function_rva]
        if function.get("registration_rva"):
            registration_rva = _rva(function["registration_rva"])
            candidates = [p for p in candidates if p["pair_rva"] == registration_rva]
        if not candidates:
            missing_functions.append(function["id"])
        for pair in candidates:
            include(pair, function_id=function["id"])

    missing_candidates = []
    for domain in domains_doc.get("domains", []):
        for name in domain.get("native_candidates", []):
            candidates = pairs_by_name.get(name, [])
            if not candidates:
                missing_candidates.append({"domain_id": domain["id"], "native_name": name})
            for pair in candidates:
                include(pair, domain_id=domain["id"])

    normalized_targets = []
    for item in targets.values():
        item["function_ids"] = sorted(item["function_ids"])
        item["domain_ids"] = sorted(item["domain_ids"])
        normalized_targets.append(item)
    normalized_targets.sort(key=lambda row: (row["native_name"], row["function_rva"], row["registration_rva"]))
    return normalized_targets, names_by_rva, missing_functions, missing_candidates


def _target_rva(immediate: int, image: PeImage) -> int | None:
    """Normalize Capstone's immediate to an RVA, without guessing outside PE."""
    if image.section_for_rva(immediate):
        return immediate
    candidate = immediate - image.image_base
    if candidate >= 0 and image.section_for_rva(candidate):
        return candidate
    return None


def analyze_target(
    image: PeImage,
    md,
    target: dict,
    names_by_rva: dict[int, set[str]],
    call_group: int,
    immediate_operand: int,
) -> dict:
    entry_rva = target["function_rva"]
    pair_rva = target["registration_rva"]
    record = {
        "native_name": target["native_name"],
        "function_rva": hex(entry_rva),
        "registration_rva": hex(pair_rva),
        "function_ids": target["function_ids"],
        "domain_ids": target["domain_ids"],
        "direct_calls": [],
        "indirect_call_sites": [],
    }

    function_range = image.function_containing(entry_rva)
    if function_range is None:
        section = image.section_for_rva(entry_rva)
        if section and section.is_executable:
            record["status"] = "executable-rva-without-unwind-range"
            record["executable_section"] = section.name
        else:
            record["status"] = "unmapped-or-non-executable-rva"
        return record

    start, end = function_range
    size = end - start
    record["unwind_range_rva"] = {"start": hex(start), "end_exclusive": hex(end)}
    record["function_size"] = size
    record["is_function_entry"] = start == entry_rva
    if start != entry_rva:
        record["status"] = "registration-points-inside-function"
        return record
    if size > MAX_BODY_BYTES:
        record["status"] = "body-size-limit"
        return record

    offset = image.rva_to_offset(start, size)
    code = image.data[offset : offset + size]
    decoded_bytes = 0
    instruction_count = 0
    for insn in md.disasm(code, start):
        instruction_count += 1
        decoded_bytes += insn.size
        if not insn.group(call_group):
            continue
        if not insn.operands:
            record["indirect_call_sites"].append(
                {"site_rva": hex(insn.address), "operand": insn.op_str}
            )
            continue
        operand = insn.operands[0]
        if operand.type != immediate_operand:
            record["indirect_call_sites"].append(
                {"site_rva": hex(insn.address), "operand": insn.op_str}
            )
            continue
        target_rva = _target_rva(operand.imm, image)
        if target_rva is None:
            record["direct_calls"].append(
                {"site_rva": hex(insn.address), "target_rva": None, "target_in_image": False}
            )
            continue
        callee_range = image.function_containing(target_rva)
        call = {
            "site_rva": hex(insn.address),
            "target_rva": hex(target_rva),
            "target_in_image": True,
            "registered_names_at_target": sorted(names_by_rva.get(target_rva, set())),
        }
        if callee_range:
            call["callee_unwind_range_rva"] = {
                "start": hex(callee_range[0]),
                "end_exclusive": hex(callee_range[1]),
            }
            call["target_is_function_entry"] = target_rva == callee_range[0]
        record["direct_calls"].append(call)

    record["status"] = "decoded" if instruction_count else "no-instructions-decoded"
    record["decoded_instruction_count"] = instruction_count
    record["decoded_bytes"] = decoded_bytes
    record["decode_coverage"] = round(decoded_bytes / size, 4) if size else 1.0
    return record


def analyze_direct_call_xrefs(
    image: PeImage,
    md,
    records: list[dict],
    names_by_rva: dict[int, set[str]],
    focus_doc: dict,
    call_group: int,
    immediate_operand: int,
) -> dict:
    """Confirm incoming direct-call edges for selected gameplay registrations.

    Raw E8 bytes are only used to find possible containing functions. Each
    reported edge must then decode as a direct call to the exact target inside
    a .pdata-bounded body. Candidate bytes without a safe body boundary remain
    unresolved and are never counted as confirmed callers.
    """
    target_info: dict[int, dict] = {}

    def add_target(rva: int, kind: str, source_name: str | None = None):
        item = target_info.setdefault(
            rva,
            {"target_kinds": set(), "source_native_functions": set()},
        )
        item["target_kinds"].add(kind)
        if source_name:
            item["source_native_functions"].add(source_name)

    focus_records = [row for row in records if is_xref_focus_record(row, focus_doc)]
    for row in focus_records:
        entry_rva = _rva(row["function_rva"])
        entry_kind = row.get("xref_kind", "registered-entry")
        add_target(entry_rva, entry_kind, row["native_name"] if entry_kind == "registered-entry" else None)
        for call in row.get("direct_calls", []):
            value = call.get("target_rva")
            if value is None or not call.get("target_in_image"):
                continue
            add_target(_rva(value), "internal-callee", row["native_name"])

    target_rvas = set(target_info)
    raw_candidates: dict[int, list[int]] = {rva: [] for rva in target_rvas}
    for section in image.sections:
        if not section.is_executable or section.raw_size < 5:
            continue
        code = image.data[section.raw_offset : section.raw_offset + section.raw_size]
        index = code.find(b"\xE8")
        while 0 <= index <= len(code) - 5:
            target = section.virtual_address + index + 5 + struct.unpack_from("<i", code, index + 1)[0]
            if target in raw_candidates:
                raw_candidates[target].append(section.virtual_address + index)
            index = code.find(b"\xE8", index + 1)

    candidate_functions: dict[tuple[int, int], set[int]] = defaultdict(set)
    no_unwind_sites: dict[int, list[int]] = defaultdict(list)
    high_fanout_targets = {
        target_rva
        for target_rva, sites in raw_candidates.items()
        if len(sites) > MAX_RAW_CALL_CANDIDATES_PER_TARGET
    }
    for target_rva, sites in raw_candidates.items():
        if target_rva in high_fanout_targets:
            continue
        for site_rva in sites:
            function_range = image.function_containing(site_rva)
            if function_range is None:
                no_unwind_sites[target_rva].append(site_rva)
                continue
            candidate_functions[function_range].add(target_rva)

    confirmed: dict[int, list[dict]] = {rva: [] for rva in target_rvas}
    skipped_callers: dict[int, set[tuple[int, int, str]]] = defaultdict(set)
    decoded_caller_count = 0
    for (start, end), _candidate_targets in candidate_functions.items():
        size = end - start
        section = image.section_for_rva(start, size)
        if not section or not section.is_executable:
            for target_rva in _candidate_targets:
                skipped_callers[target_rva].add((start, end, "non-executable-range"))
            continue
        if size > MAX_BODY_BYTES:
            for target_rva in _candidate_targets:
                skipped_callers[target_rva].add((start, end, "body-size-limit"))
            continue
        try:
            offset = image.rva_to_offset(start, size)
        except ValueError:
            for target_rva in _candidate_targets:
                skipped_callers[target_rva].add((start, end, "range-not-file-backed"))
            continue
        decoded_caller_count += 1
        code = image.data[offset : offset + size]
        for insn in md.disasm(code, start):
            if not insn.group(call_group) or not insn.operands:
                continue
            operand = insn.operands[0]
            if operand.type != immediate_operand:
                continue
            target_rva = _target_rva(operand.imm, image)
            if target_rva not in target_rvas:
                continue
            caller_names = sorted(names_by_rva.get(start, set()))
            confirmed[target_rva].append(
                {
                    "site_rva": hex(insn.address),
                    "caller_unwind_range_rva": {"start": hex(start), "end_exclusive": hex(end)},
                    "caller_is_function_entry": True,
                    "registered_names_at_caller": caller_names,
                }
            )

    targets = []
    for target_rva in sorted(target_rvas):
        item = target_info[target_rva]
        sites = sorted(confirmed[target_rva], key=lambda row: (int(row["site_rva"], 16), row["registered_names_at_caller"]))
        skipped = sorted(skipped_callers.get(target_rva, set()))
        raw_count = len(raw_candidates[target_rva])
        if target_rva in high_fanout_targets:
            analysis_status = "raw-candidate-fanout-limit"
        elif raw_count:
            analysis_status = "candidate-callers-decoded"
        else:
            analysis_status = "no-raw-call-candidates"
        targets.append(
            {
                "target_rva": hex(target_rva),
                "analysis_status": analysis_status,
                "target_kinds": sorted(item["target_kinds"]),
                "registered_names_at_target": sorted(names_by_rva.get(target_rva, set())),
                "source_native_functions": sorted(item["source_native_functions"]),
                "raw_e8_candidate_count": raw_count,
                "verified_direct_callers_observed_count": len(sites),
                "verified_direct_callers": sites[:MAX_STORED_CALLERS_PER_TARGET],
                "verified_direct_callers_truncated": len(sites) > MAX_STORED_CALLERS_PER_TARGET,
                "direct_e8_search_complete": (
                    target_rva not in high_fanout_targets
                    and not no_unwind_sites.get(target_rva)
                    and not skipped_callers.get(target_rva)
                ),
                "raw_candidates_deferred_by_fanout_limit": raw_count if target_rva in high_fanout_targets else 0,
                "candidates_without_unwind_range": len(no_unwind_sites.get(target_rva, [])),
                "unwindless_candidate_sample": [hex(site) for site in sorted(no_unwind_sites.get(target_rva, []))[:16]],
                "callers_skipped_for_boundary_or_size": [
                    {"start_rva": hex(start), "end_exclusive": hex(end), "reason": reason}
                    for start, end, reason in skipped
                ],
            }
        )
    return {
        "method": "Raw E8 bytes locate candidate callers; every confirmed edge is independently decoded as an x64 direct immediate call inside a .pdata-bounded executable function body.",
        "focus_function_ids": sorted(focus_doc.get("function_ids", [])),
        "focus_function_id_prefixes": sorted(focus_doc.get("function_id_prefixes", [])),
        "limits": [
            "This only finds direct E8 calls; virtual calls, indirect calls, ProcessEvent, delegates, and data-driven dispatch are not represented.",
            "Raw E8 matches without a containing .pdata range are unresolved candidates, not callers.",
            "Targets with more than %d raw E8 candidates are reported as high-fanout and are not expanded into caller-body scans; this keeps common-helper noise bounded." % MAX_RAW_CALL_CANDIDATES_PER_TARGET,
            "At most %d confirmed caller records are serialized per target; a truncation flag and full edge count are retained." % MAX_STORED_CALLERS_PER_TARGET,
            "A missing direct caller does not show that a function is unused; it may be reached through indirect or reflected dispatch.",
            "RVA call edges do not establish C++ names, parameter types, authority, event ordering, or semantic ownership.",
        ],
        "statistics": {
            "target_count": len(targets),
            "focus_registration_count": len(focus_records),
            "decoded_caller_bodies": decoded_caller_count,
            "verified_direct_call_edges_observed": sum(row["verified_direct_callers_observed_count"] for row in targets),
            "serialized_verified_callers": sum(len(row["verified_direct_callers"]) for row in targets),
            "raw_e8_candidate_count": sum(len(sites) for sites in raw_candidates.values()),
            "high_fanout_targets_skipped": len(high_fanout_targets),
            "raw_candidates_deferred_by_fanout_limit": sum(len(raw_candidates[target]) for target in high_fanout_targets),
            "candidates_without_unwind_range": sum(len(sites) for sites in no_unwind_sites.values()),
        },
        "targets": targets,
    }


def analyze(image: PeImage, target_doc: dict, functions_doc: dict, domains_doc: dict, focus_doc: dict, capstone_module) -> dict:
    actual_hash = sha256_file(image.path)
    expected_hash = str(target_doc.get("sha256", "")).upper()
    if actual_hash != expected_hash:
        raise ValueError(
            "executable SHA256 does not match target.json: expected %s, got %s"
            % (expected_hash, actual_hash)
        )

    pairs = list(image.iter_native_pairs())
    targets, names_by_rva, missing_functions, missing_candidates = collect_targets(
        functions_doc, domains_doc, pairs
    )
    md = capstone_module.Cs(capstone_module.CS_ARCH_X86, capstone_module.CS_MODE_64)
    md.detail = True
    md.skipdata = False
    records = [
        analyze_target(
            image,
            md,
            target,
            names_by_rva,
            capstone_module.CS_GRP_CALL,
            capstone_module.CS_OP_IMM,
        )
        for target in targets
    ]
    direct_call_xrefs = analyze_direct_call_xrefs(
        image,
        md,
        records,
        names_by_rva,
        focus_doc,
        capstone_module.CS_GRP_CALL,
        capstone_module.CS_OP_IMM,
    )
    followup_relations: dict[int, list[dict]] = defaultdict(list)
    followup_records_by_rva: dict[int, dict] = {}
    for parent in direct_call_xrefs["targets"]:
        if parent["analysis_status"] == "raw-candidate-fanout-limit":
            continue
        for source_name in sorted(set(parent["source_native_functions"]).intersection(FOLLOWUP_NATIVE_NAMES)):
            for caller in parent["verified_direct_callers"]:
                if caller["registered_names_at_caller"]:
                    continue
                caller_rva = _rva(caller["caller_unwind_range_rva"]["start"])
                followup_records_by_rva.setdefault(
                    caller_rva,
                    {
                        "native_name": "followup-caller-%s" % hex(caller_rva),
                        "function_rva": hex(caller_rva),
                        "function_ids": ["roguelite-kill.followup-caller"],
                        "direct_calls": [],
                        "xref_kind": "followup-caller",
                    },
                )
                followup_relations[caller_rva].append(
                    {
                        "source_native_function": source_name,
                        "called_target_rva": parent["target_rva"],
                        "call_site_rva": caller["site_rva"],
                    }
                )
    followup_call_xrefs = analyze_direct_call_xrefs(
        image,
        md,
        list(followup_records_by_rva.values()),
        names_by_rva,
        focus_doc,
        capstone_module.CS_GRP_CALL,
        capstone_module.CS_OP_IMM,
    )
    for followup_target in followup_call_xrefs["targets"]:
        caller_rva = _rva(followup_target["target_rva"])
        followup_target["previously_observed_as_caller_of"] = sorted(
            followup_relations[caller_rva],
            key=lambda relation: (
                relation["source_native_function"],
                int(relation["called_target_rva"], 16),
                int(relation["call_site_rva"], 16),
            ),
        )
    domains = []
    records_by_domain = {}
    for record in records:
        for domain_id in record["domain_ids"]:
            records_by_domain.setdefault(domain_id, []).append(
                {"native_name": record["native_name"], "function_rva": record["function_rva"],
                 "registration_rva": record["registration_rva"], "status": record["status"]}
            )
    for domain in domains_doc.get("domains", []):
        domains.append(
            {
                "id": domain["id"],
                "status": domain.get("status", "candidate-only"),
                "resolved_entries": sorted(
                    records_by_domain.get(domain["id"], []),
                    key=lambda row: (row["native_name"], row["function_rva"], row["registration_rva"]),
                ),
            }
        )
    status_counts = {}
    for row in records:
        status_counts[row["status"]] = status_counts.get(row["status"], 0) + 1
    return {
        "schema": 2,
        "target": "target.json",
        "target_sha256": actual_hash,
        "method": "Capstone x86-64 instruction decoding bounded by PE .pdata unwind ranges; only direct immediate calls and unresolved indirect call operands are recorded.",
        "decoder": {"name": "Capstone", "version": capstone_module.__version__},
        "limits": [
            "This is function-body disassembly, not a complete Unreal reflection call graph.",
            "Indirect virtual calls, ProcessEvent dispatch, UObject ownership, parameter schemas, and runtime event order remain unresolved.",
            "Registration entries inside an unwind range are reported but not decoded from a guessed instruction boundary.",
            "Executable entries without a .pdata unwind boundary are labeled and skipped; the absence of a boundary is not treated as proof that an entry is invalid.",
            "Incoming direct-call xrefs are reported only after instruction-level confirmation inside bounded caller bodies; absence of a direct edge does not rule out indirect or reflected dispatch.",
            "Disassembly evidence never promotes a runtime capability by itself.",
        ],
        "statistics": {
            "native_pairs_scanned": len(pairs),
            "selected_registration_entries": len(records),
            "decoded_bodies": sum(row.get("status") == "decoded" for row in records),
            "mid_function_entries": sum(row.get("status") == "registration-points-inside-function" for row in records),
            "status_counts": dict(sorted(status_counts.items())),
            "missing_function_catalog_entries": missing_functions,
            "missing_domain_candidates": missing_candidates,
        },
        "domains": domains,
        "functions": records,
        "direct_call_xrefs": {
            **direct_call_xrefs,
            "one_hop_followup": {
                "description": "For bounded callers of selected kill/attacker native implementations that have no native registration name at their function entry, perform one additional direct-E8 caller search. This is a bounded follow-up, not recursive graph closure.",
                "relation_count": sum(len(rows) for rows in followup_relations.values()),
                "analysis": followup_call_xrefs,
            },
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path, help="local fixed-version StateOfDecay2-Win64-Shipping.exe")
    parser.add_argument("--database", type=Path, default=DATABASE, help="fixed-version research directory")
    parser.add_argument("--output", type=Path, help="derived JSON output; defaults to native-body-analysis.json in the database")
    args = parser.parse_args(argv)
    try:
        import capstone
    except ImportError as error:
        parser.error("Capstone is required for this optional decoder tool; install Research/tools/requirements.txt (%s)" % error)

    try:
        target_doc = json.loads((args.database / "target.json").read_text(encoding="utf-8"))
        functions_doc = json.loads((args.database / "functions.json").read_text(encoding="utf-8"))
        domains_doc = json.loads((args.database / "research-domains.json").read_text(encoding="utf-8"))
        focus_doc = json.loads((args.database / "native-xref-focus.json").read_text(encoding="utf-8"))
        image = PeImage(args.executable)
        report = analyze(image, target_doc, functions_doc, domains_doc, focus_doc, capstone)
        output = args.output or (args.database / "native-body-analysis.json")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))

    stats = report["statistics"]
    print(
        "PASS: %d registration entries, %d decoded bodies, %d candidate domains; wrote %s"
        % (stats["selected_registration_entries"], stats["decoded_bodies"], len(report["domains"]), output)
    )
    print("Static disassembly only; indirect dispatch and runtime semantics remain unresolved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
