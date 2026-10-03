#pragma once
#include <cstdint>

// Game-version offsets for the verified Update 38.2 / build 16535856 image.
// This header is the only place in the native sources where a raw offset may
// appear.  Every entry names the research record it was read from, and
// verify_native.py fails the build when a value and its record disagree:
//
//   rva::*    -> Research/StateOfDecay2/<build>/functions.json
//   field::*  -> Research/StateOfDecay2/<build>/structs.json
//
// Updating a record is therefore a one-file edit, and a stale consumer cannot
// keep compiling against an offset the database no longer claims.
namespace melee {
namespace rva {
constexpr uintptr_t FNameIndexTable = 0x4629460;   // melee.fname-index-table
constexpr uintptr_t FNamePool = 0x4629dc8;         // melee.fname-pool
constexpr uintptr_t LocalPlayerGlobal = 0x470c690; // melee.local-player-global
constexpr uintptr_t Attitude = 0x14fe90;           // melee.attitude
constexpr uintptr_t ActionTick = 0x341320;         // melee.action-tick
constexpr uintptr_t AnimationTick = 0x1c88f50;     // melee.animation-tick
}
namespace field {
constexpr uintptr_t UObjectClass = 0x10;              // unreal.uobject-minimum
constexpr uintptr_t UObjectFNameIndex = 0x18;         // unreal.uobject-minimum
constexpr uintptr_t UClassSuperStruct = 0x30;         // unreal.uclass-minimum
constexpr uintptr_t LocalPlayerController = 0x30;     // unreal.local-player
constexpr uintptr_t ControllerPawn = 0x368;           // unreal.player-controller
constexpr uintptr_t ActionComponentPawn = 0xb8;       // melee.action-component
constexpr uintptr_t ActionImplementation = 0x200;     // melee.action-component
constexpr uintptr_t AnimationComponentPawn = 0xb8;    // melee.animation-component
constexpr uintptr_t PawnController = 0x3a8;           // melee.pawn
constexpr uintptr_t PawnAnimationComponent = 0x3d0;   // melee.pawn
constexpr uintptr_t PawnActionComponent = 0x7a0;      // melee.pawn
constexpr uintptr_t HeavyWeapon = 0x58;               // melee-action-implementations
constexpr uintptr_t MeleeWeapon = 0x78;               // melee-action-implementations
constexpr uintptr_t MeleeUnarmedMarker = 0x80;        // melee-action-implementations
constexpr uintptr_t WeaponStats = 0xf8;               // melee-weapon-and-stats
constexpr uintptr_t WeaponCategory = 0x110;           // melee-weapon-and-stats
constexpr uintptr_t FNameEntryHeader = 0x08;          // unreal.fname-entry
}
// A pool-style FName index (UE4.23+) is a byte offset into the name pool;
// smaller indexes are stored inline in the FName itself.
constexpr uint32_t FNameInlineIndexLimit = 4096;
}
