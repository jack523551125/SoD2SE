#pragma once
#include <cstdint>
#include <cmath>
#include "MeleeProtocol.h"

namespace melee {
enum Category { Close, Blade, Blunt, Heavy, Invalid };
enum Scope { Player, Friendly, Other };
// Packed policy layout: one ten-bit percentage per category, then one bit per
// scope, then the active bit.  Named because Pack() and Multiplier() must
// agree on the shift and the mask.
constexpr int RateBits = 10, RateMask = (1 << RateBits) - 1;
constexpr int ScopeBitFirst = RateBits * MaxCategories, ActiveBit = ScopeBitFirst + MaxScopes;
inline Category WeaponCategory(unsigned char type) {
    return type == 0 ? Blunt : type == 1 ? Blade : type == 2 ? Heavy : Invalid;
}
inline uint64_t Pack(bool active, const int* rates, const int* scopes) {
    uint64_t result = active ? uint64_t{1} << ActiveBit : 0;
    for (int i = 0; i < MaxCategories; ++i) {
        if (rates[i] < RateMinimum || rates[i] > RateMaximum) return 0;
        result |= uint64_t(rates[i]) << (i * RateBits);
    }
    for (int i = 0; i < MaxScopes; ++i) if (scopes[i]) result |= uint64_t{1} << (ScopeBitFirst + i);
    return result;
}
inline float Multiplier(uint64_t config, Category category, Scope scope) {
    if (category == Invalid || !(config & (uint64_t{1} << ActiveBit)) ||
        !(config & (uint64_t{1} << (ScopeBitFirst + scope)))) return 1.0f;
    return float((config >> (RateBits * category)) & RateMask) / float(RateNormal);
}
inline float ScaleDelta(float delta, float multiplier) {
    return std::isfinite(delta) && delta > 0 && std::isfinite(multiplier) ? delta * multiplier : delta;
}
}
