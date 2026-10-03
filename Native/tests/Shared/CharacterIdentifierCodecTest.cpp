#include "CharacterIdentifierCodec.h"
#include <cstring>
#include <iostream>
#include <limits>

int main() {
    using namespace sod2_native::character_identifier;
    unsigned checks = 0;
    const int32_t values[] = {0, 1, -1, 87, std::numeric_limits<int32_t>::min(), std::numeric_limits<int32_t>::max()};
    for (const auto player : values) for (const auto enclave : values) for (const auto character : values) {
        const RuntimeId runtime{{player, enclave}, character}; const auto saved = ToSaved(runtime); const auto restored = ToRuntime(saved);
        ++checks;
        if (saved.character != character || saved.enclave != enclave || saved.owningPlayer != player || std::memcmp(&runtime, &restored, sizeof(runtime))) {
            std::cerr << "FAIL: identifier component/order roundtrip\n"; return 1;
        }
    }
    const RuntimeId distinct{{11, 22}, 33}; const auto saved = ToSaved(distinct);
    ++checks;
    if (!std::memcmp(&distinct, &saved, sizeof(saved))) { std::cerr << "FAIL: different layouts mistaken for identical wire bytes\n"; return 1; }
    std::cout << "PASS: " << checks << " identifier layout conversion checks; persistent namespace remains unapproved.\n";
    return 0;
}
