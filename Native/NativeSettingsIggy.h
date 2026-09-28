#pragma once
#include "NativeSettingsModel.h"
#include <bcrypt.h>
#include <cmath>
#include <deque>
#include <memory>
#pragma comment(lib, "bcrypt.lib")

// Build 16535856, iggy_w64.dll SHA-256 pinned below. Callback contracts are
// recorded in Research/StateOfDecay2/16535856/native-settings-mcm-bridge.json.
// Player/result pointers never survive an external-call callback.
namespace native_settings_iggy {
enum class InitStatus : unsigned char { NotAttempted, WaitingForModule, UnsupportedHash, UnsupportedExports, Ready };
enum class HookStatus : int { Waiting, CallbackMissing, Installed, CreateFailed, EnableFailed };
// The 16535856 dispatcher materializes numeric values as an IEEE-754 double,
// but stores Boolean payloads as an integer bit pattern in the same slot.
struct Value { int type, padding; uintptr_t atom; double number; uintptr_t length; };
struct Call { const void* name; int length, padding, count, padding2; Value args[4]; };
static_assert(sizeof(Value) == 32 && offsetof(Value, atom) == 8 && offsetof(Value, number) == 16 &&
    offsetof(Value, length) == 24 && offsetof(Call, args) == 24, "Iggy ABI");
using Callback = int (*)(void*, void*, Call*);
using ResultPath = void* (*)(void*);
using SetInt = int (*)(void*, void*, const char*, int);
using SetText = int (*)(void*, void*, const char*, const char*, int);
inline Callback original = nullptr;
inline ResultPath resultPath = nullptr;
inline SetInt setInt = nullptr;
inline SetText setText = nullptr;
inline Callback* callbackSlot = nullptr;
inline void* hookedTarget = nullptr;
inline bool wide = false;
inline HANDLE channelGate = nullptr;
inline mcm::State* channel = nullptr;
inline std::mutex mutex;
inline native_settings::Model model;
inline unsigned hookRetryFrames = 0;
inline unsigned initializeRetry = 0;
inline bool verified = false;
inline InitStatus initStatus = InitStatus::NotAttempted;
inline std::atomic<int> hookStatus{static_cast<int>(HookStatus::Waiting)};
inline std::atomic<int> hookError{0};
inline std::atomic<unsigned> customCalls{0};
inline std::atomic<unsigned> malformedCalls{0};
inline std::atomic<unsigned> busyCalls{0};
inline std::atomic<unsigned> beginFailures{0};
inline std::atomic<unsigned> rejectedReplies{0};
inline std::atomic<unsigned> resultPathFailures{0};
inline std::atomic<unsigned> resultWriteFailures{0};
using DispatchEvent = int (*)(void*, void*, void*);
using TickPlayer = int (*)(void*);
using MakeEventChar = void (*)(void*, int);
using MakeEventKey = void (*)(void*, int, int, int);
using HasFocusedEditable = int (*)(void*);
inline DispatchEvent dispatchEvent = nullptr;
inline TickPlayer originalTick = nullptr;
inline MakeEventChar makeEventChar = nullptr;
inline MakeEventKey makeEventKey = nullptr;
inline HasFocusedEditable hasFocusedEditable = nullptr;
inline void* eventHookTarget = nullptr;
inline std::mutex inputMutex;
struct PendingInput { int code; bool first; ULONGLONG tick; };
inline std::deque<PendingInput> inputQueue;
inline bool replaceOnNextDigit = true;
inline std::atomic<unsigned> inputQueued{0}, inputDelivered{0};
inline std::atomic<int> eventHookError{0};

inline void ResetNumericEdit() {
    std::lock_guard<std::mutex> lock(inputMutex);
    replaceOnNextDigit = true;
    inputQueue.clear();
    inputQueued = 0;
}
inline void QueueNumericKey(int key) {
    int code = -1;
    if (key >= '0' && key <= '9') code = key;
    else if (key >= VK_NUMPAD0 && key <= VK_NUMPAD9) code = '0' + key - VK_NUMPAD0;
    else if (key == VK_BACK || key == VK_DELETE) code = key;
    if (code < 0) return;
    std::lock_guard<std::mutex> lock(inputMutex);
    if (inputQueue.size() >= 16) return;
    const bool first = code >= '0' && code <= '9' && replaceOnNextDigit;
    if (first) replaceOnNextDigit = false;
    inputQueue.push_back({code, first, GetTickCount64()});
    inputQueued = static_cast<unsigned>(inputQueue.size());
}
inline int TickInput(void* player) {
    if (player && dispatchEvent && hasFocusedEditable && makeEventChar && makeEventKey &&
        inputQueued.load(std::memory_order_relaxed) && hasFocusedEditable(player)) {
        PendingInput pending{};
        bool ready = false;
        {
            std::lock_guard<std::mutex> lock(inputMutex);
            if (!inputQueue.empty()) {
                pending = inputQueue.front(); inputQueue.pop_front();
                inputQueued = static_cast<unsigned>(inputQueue.size()); ready = true;
            }
        }
        if (ready && GetTickCount64() - pending.tick <= 500) {
            alignas(8) unsigned char generated[32]{};
            if (pending.first) {
                // Replace the current slider value regardless of where the
                // player clicked inside its TextField. Iggy key events use the
                // Flash/Windows virtual-key values in this pinned build.
                for (int i = 0; i < 11; ++i) {
                    makeEventKey(generated, 9, VK_BACK, 0); dispatchEvent(player, generated, nullptr);
                    makeEventKey(generated, 9, VK_DELETE, 0); dispatchEvent(player, generated, nullptr);
                }
            }
            if (pending.code >= '0' && pending.code <= '9') {
                makeEventChar(generated, pending.code);
            } else makeEventKey(generated, 9, pending.code, 0);
            dispatchEvent(player, generated, nullptr);
            ++inputDelivered;
        }
    }
    return originalTick(player);
}
struct RpcTrace {
    int op = -1, revision = 0, index = 0, value = 0;
    int result = 0, textLength = 0, written = 0;
    std::atomic<bool> ready{false};
};
inline std::array<RpcTrace, 128> rpcTrace{};
inline std::atomic<unsigned> rpcTraceCount{0};

inline bool RetryDue(unsigned& frames) {
    return (++frames % 120) == 1;
}
inline bool InitializationRetryDue(unsigned& frames) {
    return RetryDue(frames);
}
inline bool HookRetryDue(unsigned& frames) {
    return (++frames % 120) == 0;
}

inline bool CanRetryInitialization() {
    return initStatus == InitStatus::NotAttempted || initStatus == InitStatus::WaitingForModule;
}

inline bool PinnedFile(HMODULE module) {
    wchar_t path[32768]{};
    if (!GetModuleFileNameW(module, path, 32768)) return false;
    HANDLE file = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_DELETE,
        nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE) return false;
    BCRYPT_ALG_HANDLE algorithm = nullptr; BCRYPT_HASH_HANDLE hash = nullptr;
    bool ok = BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0) == 0;
    if (ok) ok = BCryptCreateHash(algorithm, &hash, nullptr, 0, nullptr, 0, 0) == 0;
    BYTE buffer[16384], digest[32]{}; DWORD size = 0;
    while (ok) {
        if (!ReadFile(file, buffer, sizeof(buffer), &size, nullptr)) { ok = false; break; }
        if (!size) break;
        ok = BCryptHashData(hash, buffer, size, 0) == 0;
    }
    if (ok) ok = BCryptFinishHash(hash, digest, sizeof(digest), 0) == 0;
    if (hash) BCryptDestroyHash(hash);
    if (algorithm) BCryptCloseAlgorithmProvider(algorithm, 0);
    CloseHandle(file);
    static const BYTE expected[32] = {0x09,0x04,0x9f,0xfc,0x7b,0x48,0x63,0x9c,0x72,0x33,0x6b,0xb8,0x09,0x03,0x5f,0xa1,0xc1,0xb8,0x27,0xe8,0x98,0x69,0x3f,0xbc,0x29,0x68,0x16,0x5b,0xd2,0x39,0x40,0xa6};
    return ok && memcmp(digest, expected, 32) == 0;
}
inline bool LockChannel() {
    const DWORD r = WaitForSingleObject(channelGate, 0);
    return r == WAIT_OBJECT_0 || r == WAIT_ABANDONED;
}
inline bool IsOurs(const Call* call) {
    constexpr char name[] = "SoD2SE_Mcm_v1";
    if (!call || !call->name || call->length != sizeof(name) - 1) return false;
    return wide ? wmemcmp(static_cast<const wchar_t*>(call->name), L"SoD2SE_Mcm_v1", sizeof(name)-1) == 0
                : memcmp(call->name, name, sizeof(name)-1) == 0;
}
inline bool ReadInteger(const Value& value, int& result, bool boolean = false) {
    if (value.type == 4 && std::isfinite(value.number) && value.number >= INT_MIN &&
        value.number <= INT_MAX && std::trunc(value.number) == value.number) {
        result = static_cast<int>(value.number);
        return true;
    }
    if (boolean && value.type == 3) {
        // The pinned Iggy converter writes only a 32-bit Boolean payload;
        // upper bytes in the 64-bit union are unspecified stack contents.
        uint32_t bits = 0;
        memcpy(&bits, &value.number, sizeof(bits));
        if (bits <= 1) { result = static_cast<int>(bits); return true; }
    }
    return false;
}
inline int Dispatch(void* user, void* player, Call* call) {
    if (!IsOurs(call)) return original(user, player, call);
    ++customCalls;
    native_settings::Reply reply = native_settings::Reply::Number(-3);
    int args[4]{};
    bool valid = false;
    try {
        valid = call->count == 4;
        for (int i = 0; valid && i < 4; ++i)
            valid = ReadInteger(call->args[i], args[i], i == 3 && args[0] == native_settings::SetOption);
        std::unique_lock<std::mutex> lock(mutex, std::try_to_lock);
        if (!valid) ++malformedCalls;
        else if (!lock.owns_lock()) ++busyCalls;
        else {
            if (args[0] == native_settings::Begin) {
                int token = 0;
                if (channel && LockChannel()) {
                    token = model.Open(*channel); ReleaseMutex(channelGate);
                }
                if (!token) ++beginFailures;
                reply = native_settings::Reply::Number(token);
            } else reply = model.Query(args[0], args[1], args[2], args[3]);
            if (!reply.text && reply.number < 0) ++rejectedReplies;
        }
    } catch (...) { reply = native_settings::Reply::Number(-4); }
    void* path = resultPath(player);
    const int written = !path ? 0 : reply.text
        ? setText(path, nullptr, nullptr, reply.value.c_str(), static_cast<int>(reply.value.size()))
        : setInt(path, nullptr, nullptr, reply.number);
    const unsigned traceIndex = rpcTraceCount.fetch_add(1, std::memory_order_relaxed);
    if (traceIndex < rpcTrace.size()) {
        auto& trace = rpcTrace[traceIndex];
        trace.op = valid ? args[0] : -1;
        trace.revision = args[1];
        trace.index = args[2];
        trace.value = args[3];
        trace.result = reply.number;
        trace.textLength = reply.text ? static_cast<int>(reply.value.size()) : -1;
        trace.written = written;
        trace.ready.store(true, std::memory_order_release);
    }
    if (!path) { ++resultPathFailures; return 0; }
    if (!written) ++resultWriteFailures;
    return 1;
}
inline InitStatus Initialize(mcm::State* state, HANDLE gate) {
    channel = state; channelGate = gate;
    if (verified) return initStatus = InitStatus::Ready;
    if (initStatus == InitStatus::UnsupportedHash || initStatus == InitStatus::UnsupportedExports)
        return initStatus;
    const auto module = GetModuleHandleW(L"iggy_w64.dll");
    if (!module) return initStatus = InitStatus::WaitingForModule;
    if (!PinnedFile(module)) return initStatus = InitStatus::UnsupportedHash;
    const auto base = reinterpret_cast<unsigned char*>(module);
    resultPath = reinterpret_cast<ResultPath>(GetProcAddress(module, "IggyPlayerCallbackResultPath"));
    setInt = reinterpret_cast<SetInt>(GetProcAddress(module, "IggyValueSetS32RS"));
    setText = reinterpret_cast<SetText>(GetProcAddress(module, "IggyValueSetStringUTF8RS"));
    makeEventChar = reinterpret_cast<MakeEventChar>(GetProcAddress(module, "IggyMakeEventChar"));
    makeEventKey = reinterpret_cast<MakeEventKey>(GetProcAddress(module, "IggyMakeEventKey"));
    hasFocusedEditable = reinterpret_cast<HasFocusedEditable>(GetProcAddress(module, "IggyPlayerHasFocusedEditableTextfield"));
    dispatchEvent = reinterpret_cast<DispatchEvent>(GetProcAddress(module, "IggyPlayerDispatchEventRS"));
    if (reinterpret_cast<void*>(resultPath) != base + 0x66890 ||
        reinterpret_cast<void*>(setInt) != base + 0x67880 ||
        reinterpret_cast<void*>(setText) != base + 0x67a30)
        return initStatus = InitStatus::UnsupportedExports;
    callbackSlot = reinterpret_cast<Callback*>(base + 0x101d50);
    verified = true;
    return initStatus = InitStatus::Ready;
}
inline void Pump() {
    if (!channel) return;
    // The loader starts the MCM renderer before the game's Settings movie is
    // guaranteed to have loaded Iggy. Retry only that transient absence; a
    // hash or export mismatch remains a hard compatibility stop.
    if (!verified && CanRetryInitialization() && InitializationRetryDue(initializeRetry))
        Initialize(channel, channelGate);
    if (!verified) return;
    if (!eventHookTarget && !eventHookError.load()) {
        const auto module = GetModuleHandleW(L"iggy_w64.dll");
        const auto base = reinterpret_cast<unsigned char*>(module);
        auto address = module ? reinterpret_cast<void*>(GetProcAddress(module, "IggyPlayerTickRS")) : nullptr;
        if (module && address == base + 0x57bd0 &&
            reinterpret_cast<void*>(dispatchEvent) == base + 0x57ee0 &&
            reinterpret_cast<void*>(makeEventChar) == base + 0xbe4b0 &&
            reinterpret_cast<void*>(makeEventKey) == base + 0xbe450 &&
            reinterpret_cast<void*>(hasFocusedEditable) == base + 0x17180) {
            const auto created = MH_CreateHook(address, reinterpret_cast<void*>(&TickInput), reinterpret_cast<void**>(&originalTick));
            if (created == MH_OK) {
                const auto enabled = MH_EnableHook(address);
                if (enabled == MH_OK) eventHookTarget = address;
                else { eventHookError = static_cast<int>(enabled); MH_RemoveHook(address); }
            } else eventHookError = static_cast<int>(created);
        } else eventHookError = -1;
    }
    // The game registers the external callback lazily with its UI bridge. Poll
    // each presented frame until it exists so opening the category cannot race
    // a coarse multi-second discovery interval.
    if (!hookedTarget) {
        const auto status = static_cast<HookStatus>(hookStatus.load());
        const bool previousAttemptFailed = status == HookStatus::CreateFailed || status == HookStatus::EnableFailed;
        if (!previousAttemptFailed || HookRetryDue(hookRetryFrames)) {
            auto slot = callbackSlot;
            wide = false;
            if (!*slot) { slot = reinterpret_cast<Callback*>(reinterpret_cast<char*>(slot) + 16); wide = true; }
            auto address = reinterpret_cast<void*>(*slot);
            if (!address) hookStatus = static_cast<int>(HookStatus::CallbackMissing);
            else {
                const auto created = MH_CreateHook(address, reinterpret_cast<void*>(&Dispatch), reinterpret_cast<void**>(&original));
                if (created != MH_OK) {
                    hookError = static_cast<int>(created);
                    hookStatus = static_cast<int>(HookStatus::CreateFailed);
                } else {
                    const auto enabled = MH_EnableHook(address);
                    if (enabled == MH_OK) { hookedTarget = address; hookError = 0; hookStatus = static_cast<int>(HookStatus::Installed); }
                    else { hookError = static_cast<int>(enabled); hookStatus = static_cast<int>(HookStatus::EnableFailed); MH_RemoveHook(address); }
                }
            }
        }
    }
    std::unique_lock<std::mutex> lock(mutex, std::try_to_lock);
    if (lock.owns_lock() && LockChannel()) {
        model.Pump(*channel); ReleaseMutex(channelGate);
    }
}
}
