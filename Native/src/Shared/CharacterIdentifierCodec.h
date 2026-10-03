#pragma once
#include <cstddef>
#include <cstdint>

namespace sod2_native::character_identifier {
// Original live and saved layouts have different field order. These values
// describe game ID components only; this codec does NOT approve a persistent
// survivor namespace or produce a growth save key.
struct EnclaveId { int32_t owningPlayer = 0, id = 0; };
struct RuntimeId { EnclaveId enclave; int32_t character = 0; };
struct SavedId { int32_t character = 0, enclave = 0, owningPlayer = 0; };
static_assert(sizeof(RuntimeId) == 12 && sizeof(SavedId) == 12 && sizeof(EnclaveId) == 8, "original identifier layouts changed");
static_assert(offsetof(RuntimeId, character) == 8 && offsetof(RuntimeId, enclave) == 0, "runtime identifier field order changed");
static_assert(offsetof(EnclaveId, owningPlayer) == 0 && offsetof(EnclaveId, id) == 4, "runtime enclave identifier changed");
static_assert(offsetof(SavedId, character) == 0 && offsetof(SavedId, enclave) == 4 && offsetof(SavedId, owningPlayer) == 8, "saved identifier field order changed");
inline SavedId ToSaved(const RuntimeId& value) { return {value.character, value.enclave.id, value.enclave.owningPlayer}; }
inline RuntimeId ToRuntime(const SavedId& value) { return {{value.owningPlayer, value.enclave}, value.character}; }
}
