#!/usr/bin/env python3
"""Analyze selected native registrations in a local executable (offline only)."""

import argparse
import json
from pathlib import Path

from pe_static import PeImage


GROUPS = {
    "kill-death": [
        "OnDaytonCharacterDead", "OnZombieKilled", "MulticastZombieKilled", "AuthOnZombieKilled",
        "KilledZombie", "AddZombieKilled", "OnZombieDead", "OnSurvivorDied", "OnMomentOfDeath",
        "Die", "DeathOver", "MarkAsDead", "HandleDeathAfterDelay", "IsDead", "IsDeathOccurred",
        "OnDead", "GetValidCharactersAfterDeath", "MulticastTriggerDeathReaction",
        "OnDeadCharacterTurnToZombie", "OnLocalPlayerDeath", "OnSpeakerDied",
        "LocalTriggerDeathReaction", "MulticastHordeKilled", "MulticastPostJuggernautKilled",
        "OnDeathSequenceOver", "OnDeathSequenceCancelled",
    ],
    "damage-attribution": [
        "ApplyDamage", "ApplyDamageToHuman_Native", "OwnerDamagedHuman", "HitCharacter",
        "AddOrUpdateAttacker", "GetCurrentAttackers", "GetNumAttackers", "AttackerAdd",
        "AttackerRemove", "GetCharacterWhoHitMost", "NotifyDamageTaken", "AddDamageListener",
        "GetAccumulatedDamage", "GetRemainingHealth", "ApplyDamageFromAttachedCharacter",
        "ClientCharacterWasHit", "ClientOwnerWasHit", "MulticastExplosiveHit",
        "NetMulticastApplyDynamicHitReacts", "ApplyFallInjury", "ApplyDynamicHitReacts",
    ],
    "enemy-classification": [
        "GetZombieSurvivorCasting", "GetZombieBloodPlagueQualifierTextByType", "GetHasBloodPlague",
        "GetHasPlague", "ContainsBloodPlagueNode",
    ],
    "survivor-identity": [
        "GetCharacterRecord_BP", "GetIncomingCharacterRecordFromId", "GetLegacyCharacterRecordFromId",
        "GenerateCharacterRecordFromSchema", "GetSurvivorByID", "ClientSetCurrentSurvivorID",
        "ClientClearCurrentSurvivorID", "OnRep_CurrentSurvivorID",
        "MulticastSetMissionActiveSurvivorId", "GetValidCharactersAfterDeath", "GetPortraitAssetId",
        "GetPortrait",
    ],
    "attributes": [
        "GetHealth", "GetHealthCurrent", "GetHealthMax", "GetHealthPeak", "GetMaximumHealth",
        "OnHealthChanged", "GetEffectiveHealthPercentage", "HasLowHealth", "IsDamaged",
        "GetStaminaCurrent", "GetStaminaMax", "GetStaminaPeak", "GetStaminaBurnRateModifier",
        "GetStaminaDrainRate", "ApplyStaminaLoss", "BeginStaminaDrainUntyped", "EndStaminaDrain",
        "GetFatigueRate", "IsImmuneToFatigue", "IsOverFatigueThreshold", "IsImmuneToPlague",
        "ChanceApplyPlagueToCharacter", "IsImmuneToInjury", "ChanceApplyInjuryToCharacter",
        "ChanceApplyInjury", "GetPainkillerEffectType", "HasPainkillerDurationEffect",
        "GetEffectiveLevelBuffResources", "GetEffectiveLevelCommunityBuffResources",
        "GetDeathHandlerComponent", "GetStaminaEffects",
    ],
    "progression": [
        "AwardExperience", "AuthAwardExperience", "CanGainExperience", "GetExperienceFraction",
        "GetCurrentLevel", "NextLevel", "GetMaxLevel", "ClampLevel", "GetHighestLevel",
        "AddSkills", "AddTrait", "AddTraits", "FindTrait", "HasTrait", "HasTraitWithTag",
        "GetTraits", "GetBaseSkill", "GetSkillByDefinition", "GetSkills", "FindSkill",
        "GetCharacterSkillLibrary",
    ],
    "pause-session": [
        "IsGamePaused", "OnPaused", "CanPause", "IsPaused", "Pause", "PauseAnimation",
        "Montage_Pause", "DaytonInputAction_Debug_Pause_Toggle", "GetTickableWhenPaused",
        "K2_PauseTimer", "K2_IsTimerPaused", "SetPause", "FlushLevelStreaming",
    ],
    "native-ui-surface": [
        "GetCharacterUI", "OnPlayerCharacterUIClosed", "CloseCharacterUI", "SetAttachedCharacter",
        "ShowSkills", "ShowSkillsRestricted", "CloseCharacterUI_Native",
        "OnAttachedCharacterInfoChanged", "RefreshHintsInternal", "SetAttachedCharacter_Native",
        "ShowSkills_Native", "ShowSkillsRestricted_Native", "UI_SkillsRefreshHints",
        "OnCommunityUIHiddenNative", "OnCommunityUIShownNative",
    ],
    "ui-movie-pipeline": [
        "CloseAllMoviePlayers", "CreateMoviePlayer", "GetAllMoviePlayers", "GetMoviePlayerByClass",
        "OnMoviePlayerClosed", "PushExistingMoviePlayer", "PushMoviePlayer",
        "GetMovieSourcePathInfo", "GetTextureReferenceForIggy", "PassInputToIggy",
    ],
}


def build_report(image: PeImage, pairs: list[dict]) -> list[dict]:
    groups_for_name: dict[str, set[str]] = {}
    for group, names in GROUPS.items():
        for name in names:
            groups_for_name.setdefault(name, set()).add(group)

    selected: dict[str, dict] = {}
    for pair in pairs:
        name = pair.get("name")
        if name not in groups_for_name:
            continue
        selected.setdefault(name, {"name": name, "groups": sorted(groups_for_name[name]), "entries": []})
        selected[name]["entries"].append(pair)

    target_rvas = {
        int(entry["func_rva"], 16)
        for record in selected.values()
        for entry in record["entries"]
    }
    call_refs = image.direct_relative_refs(target_rvas)

    report = []
    for name in sorted(selected):
        record = selected[name]
        item = {"name": name, "groups": record["groups"], "entries": []}
        for pair in record["entries"]:
            rva = int(pair["func_rva"], 16)
            function = image.function_containing(rva)
            guard = None
            try:
                offset = image.rva_to_offset(rva, 32)
                guard = image.data[offset : offset + 32].hex()
            except ValueError:
                pass
            references = call_refs.get(rva, [])
            item["entries"].append(
                {
                    "func_rva": pair["func_rva"],
                    "pair_rva": pair["pair_rva"],
                    "is_function_start": bool(function and function[0] == rva),
                    "func_end_rva": None if function is None else hex(function[1]),
                    "guard_32": guard,
                    "relative_branch_refs_heuristic": len(references),
                    "reference_sample_rva": [hex(value) for value in references[:6]],
                }
            )
        report.append(item)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path, help="local StateOfDecay2-Win64-Shipping.exe")
    parser.add_argument("--pairs", required=True, type=Path, help="JSON produced by extract_native_pairs.py")
    parser.add_argument("--output", required=True, type=Path, help="path for selected static evidence")
    args = parser.parse_args(argv)
    try:
        image = PeImage(args.executable)
        pairs = json.loads(args.pairs.read_text(encoding="utf-8"))
        if not isinstance(pairs, list):
            raise ValueError("pair JSON must be an array")
        report = build_report(image, pairs)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))
    entries = sum(len(item["entries"]) for item in report)
    print(f"selected names: {len(report)}; registered entries: {entries}")
    print("relative E8/E9 references are raw-byte triage only, not decoded call-site proof")
    print(f"wrote derived metadata: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
