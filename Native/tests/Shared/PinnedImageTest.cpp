#include "PinnedImage.h"
#include <iostream>
#include <stdexcept>
#include <thread>
#include <string>

namespace {
int checks = 0;
void Check(bool value, const char* label) { ++checks; if (!value) throw std::runtime_error(label); }
}
int main(int argc, char** argv) {
    try {
        if (argc != 2 || std::strlen(argv[1]) != 64) throw std::runtime_error("pass the inert executable SHA256 from the runner");
        const auto module = GetModuleHandleW(nullptr); const auto expected = argv[1];
        Check(!sod2_native::PinnedImageCached(module, expected), "unprepared image is never treated as authenticated");
        Check(!sod2_native::PinnedImageFile(nullptr, expected) && !sod2_native::PinnedImageFile(module, "short"), "invalid startup arguments cannot consume authentication attempt");
        sod2_native::image_cache::state.store(1);
        Check(!sod2_native::PinnedImageFile(module, expected) && !sod2_native::PinnedImageCached(module, expected), "contending callers fail immediately without waiting or reading file");
        sod2_native::image_cache::state.store(0);
        Check(sod2_native::PinnedImageFile(module, expected) && sod2_native::PinnedImageCached(module, expected), "actual inert image hash authenticates once during startup");
        std::string wrong(expected); wrong[0] = wrong[0] == '0' ? '1' : '0';
        Check(!sod2_native::PinnedImageCached(module, wrong.c_str()) && !sod2_native::PinnedImageFile(module, wrong.c_str()), "wrong expected hash cannot borrow successful cache");
        Check(sod2_native::PinnedImageFile(module, expected), "failed later request cannot poison original successful authentication");
        Check(!sod2_native::PinnedImageCached(GetModuleHandleW(L"kernel32.dll"), expected), "another module cannot borrow main-image proof");
        bool verified = false;
        std::thread worker([&] { verified = sod2_native::PinnedImageCached(module, expected) && sod2_native::PinnedImageFile(module, expected); }); worker.join();
        Check(verified, "immutable cache is safe to acquire from activation threads");
        // Owned fixture reset only; production never resets the process cache.
        sod2_native::image_cache::state.store(0);
        Check(!sod2_native::PinnedImageFile(module, wrong.c_str()) && sod2_native::image_cache::state.load() == 3,
            "rejected first image fails closed");
        Check(!sod2_native::PinnedImageFile(module, expected), "rejected authentication cannot retry into another startup state");
        std::cout << "PASS: " << checks << " process image authentication/cache checks; inert executable only.\n";
        return 0;
    } catch (const std::exception& error) { std::cerr << "FAIL: " << error.what() << '\n'; return 1; }
}
