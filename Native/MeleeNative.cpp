#include <windows.h>
#include <atomic>
#include <cstdint>
#include <cstring>
#include <cstdio>
#include "MinHook.h"
#include "MeleePolicy.h"
#include "MeleeProtocol.h"
#include "MeleeOffsets.h"

namespace {
using Channel = melee::Channel;
using ActionTick = void(__fastcall*)(void*, float, int, void*);
using AnimationTick = void(__fastcall*)(void*, float, bool);
ActionTick originalAction = nullptr;
AnimationTick originalAnimation = nullptr;
uintptr_t base = 0;
std::atomic<uint64_t> config{0}, actionTicks{0}, animationTicks{0}, faults{0};
std::atomic<bool> started{false};
std::atomic<bool> classificationFailed{false};
HANDLE mapping = nullptr, gate = nullptr, owner = nullptr;
Channel* shared = nullptr;
template<class T> T Read(uintptr_t object, uintptr_t offset = 0) {
    return *reinterpret_cast<const T*>(object + offset);
}
// UObject/FName layout is specific to the verified Update 38.2 executable.
bool Named(uintptr_t object, const char* expected) {
    const uint32_t index = Read<uint32_t>(object, melee::field::UObjectFNameIndex);
    const uint32_t offset = index < melee::FNameInlineIndexLimit
        ? Read<uint32_t>(base + melee::rva::FNameIndexTable, index * 4) : index;
    const auto pool = Read<uintptr_t>(base + melee::rva::FNamePool);
    return std::strcmp(reinterpret_cast<const char*>(pool + offset + melee::field::FNameEntryHeader), expected) == 0;
}
bool IsA(uintptr_t object, const char* expected) {
    if (!object) return false;
    auto cls = Read<uintptr_t>(object, melee::field::UObjectClass);
    for (int depth = 0; cls && depth < 32; ++depth, cls = Read<uintptr_t>(cls, melee::field::UClassSuperStruct))
        if (Named(cls, expected)) return true;
    return false;
}
melee::Scope ActorScope(uintptr_t pawn) {
    const auto localPlayer = Read<uintptr_t>(base + melee::rva::LocalPlayerGlobal);
    if (!localPlayer || !IsA(localPlayer, "DaytonLocalPlayer")) return melee::Other;
    const auto localController = Read<uintptr_t>(localPlayer, melee::field::LocalPlayerController);
    if (!localController) return melee::Other;
    const auto playerPawn = Read<uintptr_t>(localController, melee::field::ControllerPawn);
    if (playerPawn == pawn) return melee::Player;
    const auto controller = Read<uintptr_t>(pawn, melee::field::PawnController);
    if (playerPawn && IsA(controller, "DaytonHumanAIController")) {
        using Attitude = unsigned char(__fastcall*)(void*, void*);
        const auto attitude = reinterpret_cast<Attitude>(base + melee::rva::Attitude);
        if (attitude(reinterpret_cast<void*>(controller), reinterpret_cast<void*>(playerPawn)) == 0)
            return melee::Friendly;
    }
    return melee::Other;
}
float ActionMultiplier(uintptr_t component, uintptr_t expectedOwner, uint64_t settings) {
    if (!component || !(settings & (uint64_t{1} << melee::ActiveBit))) return 1.0f;
    const auto pawn = Read<uintptr_t>(component, melee::field::ActionComponentPawn);
    if ((expectedOwner && expectedOwner != pawn) || !IsA(pawn, "DaytonHumanCharacter")) return 1.0f;
    const auto implementation = Read<uintptr_t>(component, melee::field::ActionImplementation);
    if (!implementation) return 1.0f;
    uintptr_t weapon = 0;
    melee::Category category = melee::Invalid;
    if (IsA(implementation, "HumanHeavyWeaponChannelAttackActionImpl_C")) {
        weapon = Read<uintptr_t>(implementation, melee::field::HeavyWeapon);
    } else if (IsA(implementation, "HumanMeleeActionImpl_C")) {
        weapon = Read<uintptr_t>(implementation, melee::field::MeleeWeapon);
        if (!weapon && Read<uintptr_t>(implementation, melee::field::MeleeUnarmedMarker)) category = melee::Close;
    } else return 1.0f;
    if (weapon && IsA(weapon, "MeleeWeaponItemInstance")) {
        const auto stats = Read<uintptr_t>(weapon, melee::field::WeaponStats);
        if (stats && IsA(stats, "MeleeWeaponResourceStats"))
            category = melee::WeaponCategory(Read<unsigned char>(stats, melee::field::WeaponCategory));
    }
    return melee::Multiplier(settings, category, ActorScope(pawn));
}
// Keep the SEH boundary explicit. The optimized MSVC build failed the injected
// invalid-pointer test (zero return, handler skipped); this small boundary is
// intentionally unoptimized while the classifier and original game ticks remain optimized.
#pragma optimize("", off)
__declspec(noinline) float SafeMultiplier(void* object, bool animation) {
    // Guard only our classification reads; exceptions from original game code are not swallowed.
    // The disabled/configuration-fault path exits before touching an object.  A
    // hook callback never stores a UObject pointer; all object addresses below
    // are short-lived locals for this one callback.
    __try {
        auto address = reinterpret_cast<uintptr_t>(object);
        const auto settings = classificationFailed.load(std::memory_order_relaxed) ? 0 : config.load(std::memory_order_acquire);
        if (!settings) return 1.0f;
        if (!animation) return ActionMultiplier(address, 0, settings);
        if (!(settings & (uint64_t{1} << melee::ActiveBit))) return 1.0f;
        const auto pawn = Read<uintptr_t>(address, melee::field::AnimationComponentPawn);
        if (!IsA(pawn, "DaytonHumanCharacter") ||
            Read<uintptr_t>(pawn, melee::field::PawnAnimationComponent) != address) return 1.0f;
        return ActionMultiplier(Read<uintptr_t>(pawn, melee::field::PawnActionComponent), pawn, settings);
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        classificationFailed.store(true, std::memory_order_release);
        faults.fetch_add(1, std::memory_order_relaxed); return 1.0f;
    }
}
#pragma optimize("", on)
void __fastcall TickAction(void* object, float delta, int type, void* tickFunction) {
    const float multiplier = SafeMultiplier(object, false);
    if (multiplier != 1.0f) actionTicks.fetch_add(1, std::memory_order_relaxed);
    originalAction(object, melee::ScaleDelta(delta, multiplier), type, tickFunction);
}
void __fastcall TickAnimation(void* object, float delta, bool rootMotion) {
    const float multiplier = SafeMultiplier(object, true);
    if (multiplier != 1.0f) animationTicks.fetch_add(1, std::memory_order_relaxed);
    originalAnimation(object, melee::ScaleDelta(delta, multiplier), rootMotion);
}
void CloseChannel() {
    config.store(0, std::memory_order_release);
    if (shared) { UnmapViewOfFile(shared); shared = nullptr; }
    if (mapping) { CloseHandle(mapping); mapping = nullptr; }
    if (gate) { CloseHandle(gate); gate = nullptr; }
    if (owner) { CloseHandle(owner); owner = nullptr; }
}
DWORD WINAPI Watchdog(void*) {
    for (;;) {
        // The channel field is int32_t; the interlocked intrinsic wants a LONG*.
        if (WaitForSingleObject(owner, 50) != WAIT_TIMEOUT ||
            InterlockedCompareExchange(reinterpret_cast<volatile LONG*>(&shared->shutdown), 0, 0)) break;
        const DWORD locked = WaitForSingleObject(gate, 25);
        if (locked != WAIT_OBJECT_0 && locked != WAIT_ABANDONED) { config.store(0); continue; }
        const bool alive = GetTickCount64() - shared->heartbeat < 2000;
        config.store(alive ? melee::Pack(shared->active != 0, shared->rates, shared->scopes) : 0, std::memory_order_release);
        shared->actionTicks = actionTicks.load(); shared->animationTicks = animationTicks.load(); shared->faults = faults.load();
        ReleaseMutex(gate);
    }
    CloseChannel();
    return 0;
}
}

extern "C" __declspec(dllexport) DWORD WINAPI SoD2MeleeStart(const wchar_t* name) {
    if (started.exchange(true)) return ERROR_ALREADY_INITIALIZED;
    base = reinterpret_cast<uintptr_t>(GetModuleHandleW(nullptr));
    auto dos = reinterpret_cast<const IMAGE_DOS_HEADER*>(base);
    auto pe = reinterpret_cast<const IMAGE_NT_HEADERS64*>(base + dos->e_lfanew);
    // The image must cover the globals this component reads.
    const uintptr_t requiredImage = melee::rva::LocalPlayerGlobal + sizeof(void*);
    if (dos->e_magic != IMAGE_DOS_SIGNATURE || pe->Signature != IMAGE_NT_SIGNATURE ||
        pe->OptionalHeader.SizeOfImage < requiredImage) return ERROR_REVISION_MISMATCH;
    // Reject foreign hooks or a changed executable before touching instructions.
    const unsigned char actionBytes[] = {0x40,0x55,0x53,0x57,0x48,0x8d,0x6c,0x24,0xd0,0x48,0x81,0xec,0x30,0x01,0,0};
    const unsigned char animationBytes[] = {0x40,0x56,0x48,0x83,0xec,0x30,0x48,0x83,0xb9,0x78,0x06,0,0,0};
    if (std::memcmp(reinterpret_cast<void*>(base + melee::rva::ActionTick), actionBytes, sizeof(actionBytes)) ||
        std::memcmp(reinterpret_cast<void*>(base + melee::rva::AnimationTick), animationBytes, sizeof(animationBytes)))
        return ERROR_REVISION_MISMATCH;
    wchar_t mutexName[256]{};
    if (!name || wcslen(name) > 240 || swprintf_s(mutexName, L"%s.lock", name) < 0) return ERROR_INVALID_NAME;
    mapping = OpenFileMappingW(FILE_MAP_ALL_ACCESS, FALSE, name);
    if (mapping) shared = static_cast<Channel*>(MapViewOfFile(mapping, FILE_MAP_ALL_ACCESS, 0, 0, sizeof(Channel)));
    gate = OpenMutexW(SYNCHRONIZE | MUTEX_MODIFY_STATE, FALSE, mutexName);
    if (!shared || !gate || shared->magic != melee::ChannelMagic || shared->version != melee::ChannelVersion)
    { CloseChannel(); return ERROR_INVALID_DATA; }
    owner = OpenProcess(SYNCHRONIZE, FALSE, static_cast<DWORD>(shared->owner));
    if (!owner) { CloseChannel(); return ERROR_INVALID_HANDLE; }
    auto action = reinterpret_cast<void*>(base + melee::rva::ActionTick);
    auto animation = reinterpret_cast<void*>(base + melee::rva::AnimationTick);
    if (MH_Initialize() != MH_OK ||
        MH_CreateHook(action, reinterpret_cast<void*>(TickAction), reinterpret_cast<void**>(&originalAction)) != MH_OK ||
        MH_CreateHook(animation, reinterpret_cast<void*>(TickAnimation), reinterpret_cast<void**>(&originalAnimation)) != MH_OK ||
        MH_QueueEnableHook(action) != MH_OK || MH_QueueEnableHook(animation) != MH_OK || MH_ApplyQueued() != MH_OK) {
        config.store(0); MH_DisableHook(MH_ALL_HOOKS); CloseChannel(); return ERROR_INVALID_FUNCTION;
    }
    shared->ready = 1;
    HANDLE thread = CreateThread(nullptr, 0, Watchdog, nullptr, 0, nullptr);
    if (!thread) { CloseChannel(); return ERROR_NOT_ENOUGH_MEMORY; }
    CloseHandle(thread);
    return 0;
}

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) DisableThreadLibraryCalls(instance);
    // Never unload while a game thread might be executing a trampoline.
    return TRUE;
}
