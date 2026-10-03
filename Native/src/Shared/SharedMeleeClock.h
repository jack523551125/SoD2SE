#pragma once
#include <windows.h>
#include <atomic>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstddef>
#include <limits>

namespace melee::clock {
constexpr uint32_t Version = 1;
inline constexpr char RegisterExport[] = "SoD2MeleeRegisterClockV1";
inline constexpr char UnregisterExport[] = "SoD2MeleeUnregisterClockV1";
inline constexpr char QueryExport[] = "SoD2MeleeQueryClockV1";
constexpr size_t Capacity = 8;
struct Contribution { double multiplier = 1, ceiling = 4; };
// Native bounded policy callback. Pawn is ephemeral for the call. Return false
// when this owner has no contribution. No IPC, locks, disk or engine mutations.
using Lookup = bool(__cdecl*)(void*, void*, uint32_t, uint32_t, Contribution*);
struct Registration {
    uint32_t size = sizeof(Registration), version = Version;
    uint64_t ownerLow = 0, ownerHigh = 0; // stable 128-bit Mod/service ID
    Lookup lookup = nullptr;
    void* context = nullptr;
};
static_assert(sizeof(Contribution) == 16 && sizeof(Registration) == 40 && offsetof(Registration, lookup) == 24,
              "shared melee clock x64 ABI changed");
// Registry mutation and lookup run on the actual engine game thread. The
// consumer checks thread proof before entering. Native owners and callbacks
// remain alive for the host's lifetime; a revoked generation cannot be reused.
class Registry {
    struct Slot { Registration owner; uint64_t handle = 0; };
    std::array<Slot, Capacity> slots{};
    uint64_t generation = 0;
    std::atomic<uint32_t> count{0};
    mutable bool resolving = false;
public:
    bool Present() const { return count.load(std::memory_order_acquire) != 0; }
    DWORD Add(const Registration& registration, uint64_t& handle) {
        handle = 0;
        if (resolving) return ERROR_BUSY;
        if (registration.size != sizeof(Registration) || registration.version != Version ||
            (!registration.ownerLow && !registration.ownerHigh) || !registration.lookup) return ERROR_INVALID_PARAMETER;
        for (const auto& slot : slots)
            if (slot.handle && slot.owner.ownerLow == registration.ownerLow && slot.owner.ownerHigh == registration.ownerHigh) return ERROR_ALREADY_EXISTS;
        if (generation >= (std::numeric_limits<uint64_t>::max() >> 8)) return ERROR_ARITHMETIC_OVERFLOW;
        for (size_t i = 0; i < slots.size(); ++i) {
            if (slots[i].handle) continue;
            slots[i].owner = registration;
            slots[i].handle = (++generation << 8) | (i + 1);
            handle = slots[i].handle;
            count.fetch_add(1, std::memory_order_release);
            return ERROR_SUCCESS;
        }
        return ERROR_NOT_ENOUGH_MEMORY;
    }
    DWORD Remove(uint64_t handle) {
        if (resolving) return ERROR_BUSY;
        if (!handle) return ERROR_INVALID_HANDLE;
        const auto position = (handle & 255);
        if (!position || position > slots.size() || slots[position - 1].handle != handle) return ERROR_INVALID_HANDLE;
        slots[position - 1] = {};
        count.fetch_sub(1, std::memory_order_release);
        return ERROR_SUCCESS;
    }
    bool Resolve(void* pawn, uint32_t category, uint32_t scope, float existing, float& result) const {
        result = existing;
        if (resolving) return false;
        struct Guard { bool& value; explicit Guard(bool& flag) : value(flag) { value = true; } ~Guard() { value = false; } } guard(resolving);
        if (!std::isfinite(existing) || existing <= 0) return false;
        double logarithm = std::log(static_cast<double>(existing));
        double ceiling = std::numeric_limits<float>::max();
        bool applied = false;
        for (const auto& slot : slots) {
            if (!slot.handle) continue;
            Contribution contribution;
            if (!slot.owner.lookup(slot.owner.context, pawn, category, scope, &contribution)) continue;
            if (!std::isfinite(contribution.multiplier) || contribution.multiplier <= 0 ||
                !std::isfinite(contribution.ceiling) || contribution.ceiling < 1 || contribution.ceiling > std::numeric_limits<float>::max()) return false;
            logarithm += std::log(contribution.multiplier);
            ceiling = std::fmin(ceiling, contribution.ceiling);
            applied = true;
        }
        if (!applied) return true; // preserve the existing Mod's exact rate
        // Apply the ceiling once after all layers. Capping an early layer would
        // produce a different answer when a later owner slows the same action.
        const double combined = logarithm >= std::log(ceiling) ? ceiling : std::exp(logarithm);
        const auto value = static_cast<float>(combined);
        if (!std::isfinite(value) || value <= 0) return false;
        result = value;
        return true;
    }
};
// These exports live in the existing sole action/animation hook host. A future
// native growth owner resolves them by versioned name; no remote managed
// function pointer or second MinHook owner can register a contribution.
using RegisterFunction = DWORD(WINAPI*)(const Registration*, uint64_t*);
using UnregisterFunction = DWORD(WINAPI*)(uint64_t);
// Preview for a qualified live pawn and weapon category, using the same current
// baseline settings and registered policy layers as the actual tick consumers.
using QueryFunction = DWORD(WINAPI*)(void*, uint32_t, float*);
}
