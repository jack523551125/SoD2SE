#pragma once
#include <windows.h>
#include <bcrypt.h>
#include <array>
#include <memory>
#include <new>
#include <cwchar>
#include <cstring>
#include <iterator>
#include <atomic>

namespace sod2_native {
// Startup only. Never call this from a damage, attribute, animation or UI hook.
inline bool ReadPinnedImageFile(HMODULE module, const char* expected) {
    if (!module || !expected || std::strlen(expected) != 64) return false;
    wchar_t path[32768]{};
    const DWORD length = GetModuleFileNameW(module, path, static_cast<DWORD>(std::size(path)));
    if (!length || length >= std::size(path)) return false;
    HANDLE file = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE) return false;
    BCRYPT_ALG_HANDLE algorithm = nullptr;
    BCRYPT_HASH_HANDLE hash = nullptr;
    std::array<unsigned char, 32> digest{};
    DWORD size = 0, received = 0;
    bool ok = BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0) >= 0;
    if (ok) ok = BCryptGetProperty(algorithm, BCRYPT_OBJECT_LENGTH,
        reinterpret_cast<PUCHAR>(&size), sizeof(size), &received, 0) >= 0 && received == sizeof(size);
    // SHA-256's object length is bounded; a failed provider never drives an
    // unbounded allocation on startup.
    if (ok) ok = size > 0 && size <= 1024 * 1024;
    std::unique_ptr<unsigned char[]> object(ok ? new(std::nothrow) unsigned char[size] : nullptr);
    if (ok) ok = object != nullptr;
    if (ok) ok = BCryptCreateHash(algorithm, &hash, object.get(), size, nullptr, 0, 0) >= 0;
    std::array<unsigned char, 65536> buffer{};
    while (ok) {
        DWORD count = 0;
        if (!ReadFile(file, buffer.data(), static_cast<DWORD>(buffer.size()), &count, nullptr)) { ok = false; break; }
        if (!count) break;
        ok = BCryptHashData(hash, buffer.data(), count, 0) >= 0;
    }
    if (ok) ok = BCryptFinishHash(hash, digest.data(), static_cast<ULONG>(digest.size()), 0) >= 0;
    if (hash) BCryptDestroyHash(hash);
    if (algorithm) BCryptCloseAlgorithmProvider(algorithm, 0);
    CloseHandle(file);
    if (!ok) return false;
    constexpr char digits[] = "0123456789ABCDEF";
    for (size_t i = 0; i < digest.size(); ++i)
        if (expected[i * 2] != digits[digest[i] >> 4] || expected[i * 2 + 1] != digits[digest[i] & 15]) return false;
    return true;
}
namespace image_cache {
// An immutable successful authentication belongs to the process's main image.
// Each injected module owns its own cache; nothing is trusted across processes.
inline std::atomic<unsigned> state{0}; // 0 fresh, 1 preparing, 2 authenticated, 3 rejected
inline HMODULE module = nullptr;
inline std::array<char, 65> hash{};
}
inline bool PinnedImageCached(HMODULE module, const char* expected) {
    if (!module || module != GetModuleHandleW(nullptr) || !expected || std::strlen(expected) != 64 ||
        image_cache::state.load(std::memory_order_acquire) != 2) return false;
    return module == image_cache::module && std::memcmp(expected, image_cache::hash.data(), 64) == 0;
}
// The first call is startup work and reads the file. Frame startup authenticates
// on its worker before publishing callbacks; game-thread component activation
// must require PinnedImageCached first. Contending callers never wait or hash.
inline bool PinnedImageFile(HMODULE module, const char* expected) {
    if (!module || module != GetModuleHandleW(nullptr) || !expected || std::strlen(expected) != 64) return false;
    unsigned state = 0;
    if (!image_cache::state.compare_exchange_strong(state, 1, std::memory_order_acq_rel)) return PinnedImageCached(module, expected);
    if (!ReadPinnedImageFile(module, expected)) { image_cache::state.store(3, std::memory_order_release); return false; }
    image_cache::module = module; std::memcpy(image_cache::hash.data(), expected, 64);
    image_cache::state.store(2, std::memory_order_release); return true;
}
}
