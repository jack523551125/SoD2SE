#pragma once
#include <cstdint>
#include <cstddef>

// ABI v1 of the melee speed channel between Plugins/MeleeSpeed/MeleeSpeed.cs and
// SoD2SE.MeleeSpeed.Native.dll.  This header is the single source of truth: the
// C# bridge names the same fields, and verify_protocol.py recomputes the packed
// layout so the two sides cannot drift apart.
namespace melee {
constexpr int32_t ChannelMagic = 0x314c454d;  // 'MELC' when read as bytes
// Bumped whenever the layout below changes; both sides compare it before use.
constexpr int32_t ChannelVersion = 1;
// Percentage bounds shared by the MCM input, the managed clamp and Pack().
constexpr int32_t RateMinimum = 25, RateMaximum = 1000;
// Rates travel as whole percentages, so 100 is the game's own speed.
constexpr int32_t RateNormal = 100;
constexpr int MaxCategories = 4, MaxScopes = 3;

#pragma pack(push, 4)
struct Channel {
    int32_t magic, version, owner, active;
    int32_t rates[MaxCategories], scopes[MaxScopes];
    // Written by the managed side on shutdown so the injected watchdog can
    // unhook without the mod having to unload a live DLL.
    volatile int32_t shutdown;
    uint64_t heartbeat;
    int32_t ready, reserved;
    // Counters the native hook raises; the managed side only reports them.
    uint64_t actionTicks, animationTicks, faults;
    char padding[40];
};
#pragma pack(pop)
static_assert(sizeof(Channel) == 128, "melee channel size changed");
static_assert(offsetof(Channel, active) == 12, "melee active offset changed");
static_assert(offsetof(Channel, rates) == 16, "melee rates offset changed");
static_assert(offsetof(Channel, scopes) == 32, "melee scopes offset changed");
static_assert(offsetof(Channel, shutdown) == 44, "melee shutdown offset changed");
static_assert(offsetof(Channel, heartbeat) == 48, "melee heartbeat offset changed");
static_assert(offsetof(Channel, actionTicks) == 64, "melee action ticks offset changed");
static_assert(offsetof(Channel, animationTicks) == 72, "melee animation ticks offset changed");
static_assert(offsetof(Channel, faults) == 80, "melee faults offset changed");
}
