#include <windows.h>
#include <mutex>
#include "MinHook.h"
#include "NativeSettingsIggy.h"
#include <iostream>
#include <stdexcept>
#include <cstdint>
#include <vector>

namespace ns = native_settings_iggy;
static int result = 0, forwarded = 0, writeResult = 1;
static std::string text;
static void* const player = reinterpret_cast<void*>(0x1234);
static void Check(bool b, const char* reason) { if (!b) throw std::runtime_error(reason); }
static void* Path(void* p) { Check(p == player, "player passed through"); return player; }
static int Int(void* p, void* name, const char* key, int n) {
    Check(p == player && !name && !key, "root callback result path"); result = n; return writeResult;
}
static int Text(void* p, void* name, const char* key, const char* value, int size) {
    Check(p == player && !name && !key, "string result path"); text.assign(value, size); return 1;
}
static int Forward(void* user, void* p, ns::Call*) {
    Check(user == player && p == player, "foreign callback context preserved"); ++forwarded; return 42;
}
static std::vector<int> inputEvents;
static bool editable = true;
static int MockFocus(void*) { return editable ? 1 : 0; }
static int MockTick(void*) { return 71; }
static void MockChar(void* event, int code) { static_cast<int*>(event)[0] = 1; static_cast<int*>(event)[1] = code; }
static void MockKey(void* event, int type, int code, int) { static_cast<int*>(event)[0] = type; static_cast<int*>(event)[1] = code; }
static int MockEvent(void*, void* event, void*) {
    inputEvents.push_back(static_cast<int*>(event)[0] * 1000 + static_cast<int*>(event)[1]);
    return 1;
}
int main() {
    try {
        unsigned retryFrames = 0;
        Check(ns::InitializationRetryDue(retryFrames), "first Present retries an Iggy module missed at startup");
        for (int frame = 2; frame <= 120; ++frame)
            Check(!ns::InitializationRetryDue(retryFrames), "deferred Iggy initialization is throttled");
        Check(ns::InitializationRetryDue(retryFrames), "deferred Iggy initialization retries after 120 Presents");
        unsigned hookRetryFrames = 0;
        for (int frame = 1; frame < 120; ++frame)
            Check(!ns::HookRetryDue(hookRetryFrames), "failed callback hook is not retried on every Present");
        Check(ns::HookRetryDue(hookRetryFrames), "failed callback hook retries after 120 Presents");
        ns::initStatus = ns::InitStatus::WaitingForModule;
        Check(ns::CanRetryInitialization(), "missing Iggy module is transient");
        ns::initStatus = ns::InitStatus::UnsupportedHash;
        Check(!ns::CanRetryInitialization(), "unrecognized Iggy hash remains blocked");
        ns::initStatus = ns::InitStatus::UnsupportedExports;
        Check(!ns::CanRetryInitialization(), "unrecognized Iggy exports remain blocked");
        ns::initStatus = ns::InitStatus::NotAttempted;

        auto state = std::make_unique<mcm::State>();
        state->magic = mcm::Magic; state->version = mcm::Version; state->pageCount = 1; state->optionCount = 2;
        strcpy_s(state->pages[0].name, "近战攻速 / Melee Speed");
        strcpy_s(state->options[0].id, "enabled"); state->options[0].maximum = 1;
        strcpy_s(state->options[1].id, "speed"); state->options[1].type = mcm::OptionIntegerInput;
        state->options[1].minimum = 10; state->options[1].maximum = 1000; state->options[1].value = 100;
        ns::channel = state.get(); ns::channelGate = CreateMutexW(nullptr, FALSE, nullptr);
        ns::resultPath = Path; ns::setInt = Int; ns::setText = Text; ns::original = Forward;
        ns::Call call{}; call.name = "UI_Settings_CategoryChanged"; call.length = 27;
        Check(ns::Dispatch(player, player, &call) == 42 && forwarded == 1, "foreign calls forwarded");
        call.name = "SoD2SE_Mcm_v1"; call.length = sizeof("SoD2SE_Mcm_v1") - 1; call.count = 4;
        for (auto& a : call.args) a.type = 4;
        call.args[0].number = native_settings::Begin;
        ++state->version;
        Check(ns::Dispatch(player, player, &call) == 1 && result == 0 && ns::beginFailures == 1,
            "invalid shared MCM state is reported as a failed snapshot begin");
        --state->version;
        Check(ns::Dispatch(player, player, &call) == 1 && result > 0, "native begin");
        Check(ns::rpcTraceCount >= 2 && ns::rpcTrace[1].ready.load(std::memory_order_acquire) &&
            ns::rpcTrace[1].op == native_settings::Begin && ns::rpcTrace[1].result == result &&
            ns::rpcTrace[1].written == 1, "bounded RPC trace records opcode and returned result");
        int revision = result; call.args[0].number = native_settings::PageName;
        call.args[1].number = revision;
        Check(ns::Dispatch(player, player, &call) == 1 && text == "近战攻速 / Melee Speed", "UTF-8 return");
        call.args[0].number = native_settings::SetOption;
        call.args[1].number = revision;
        call.args[2].number = 0;
        call.args[3].type = 3; // Iggy Boolean; its payload is a raw integer bit pattern.
        const std::uint64_t enabledBits = (std::uint64_t{0xdeadbeef} << 32) | 1;
        std::memcpy(&call.args[3].number, &enabledBits, sizeof(enabledBits));
        Check(ns::Dispatch(player, player, &call) == 1 && result == 1, "Boolean option marshalled from native Iggy type 3");
        ns::model.Pump(*state);
        Check(state->command == mcm::CmdSetBool && state->option == 0 && state->value == 1, "Boolean edit reaches the existing MCM save command");
        const auto boolRequest = state->request;
        state->options[0].value = 1; state->acknowledged = boolRequest;
        ns::model.Pump(*state);
        Check(ns::model.Query(native_settings::StatusCode, revision, 0, 0).number == 0, "Boolean save acknowledgement updates status");
        call.args[0].number = native_settings::SetOption;
        call.args[2].number = 1;
        call.args[3].type = 4; call.args[3].number = 375;
        Check(ns::Dispatch(player, player, &call) == 1 && result == 1, "integer input value accepted");
        ns::model.Pump(*state);
        Check(state->command == mcm::CmdSetInt && state->option == 1 && state->value == 375, "integer input reaches the existing MCM save command");
        const auto intRequest = state->request;
        state->options[1].value = 375; state->acknowledged = intRequest;
        ns::model.Pump(*state);
        Check(ns::model.Query(native_settings::StatusCode, revision, 0, 0).number == 0, "integer save acknowledgement updates status");
        call.args[2].number = 0;
        call.args[3].type = 3;
        const std::uint64_t invalidBooleanBits = 2;
        std::memcpy(&call.args[3].number, &invalidBooleanBits, sizeof(invalidBooleanBits));
        Check(ns::Dispatch(player, player, &call) == 1 && result == -3, "invalid Boolean payload refused");
        call.args[0].number = native_settings::Begin;
        call.args[1].number = 0; call.args[2].number = 0; call.args[3].type = 4; call.args[3].number = 0;
        ns::wide = true; call.name = L"SoD2SE_Mcm_v1";
        Check(ns::Dispatch(player, player, &call) == 1 && result > 0, "UTF-16 names supported");
        revision = result;
        call.args[0].number = 1.5;
        Check(ns::Dispatch(player, player, &call) == 1 && result == -3, "fractional opcode refused");
        call.args[0].number = 1; call.args[0].type = 5;
        Check(ns::Dispatch(player, player, &call) == 1 && result == -3, "non-number refused");
        call.args[0].type = 4; call.count = 5;
        Check(ns::Dispatch(player, player, &call) == 1 && result == -3, "argument count bounded");
        Check(ns::malformedCalls > 0, "malformed RPC input is counted for runtime diagnostics");
        call.count = 4; call.args[1].number = revision + 1;
        Check(ns::Dispatch(player, player, &call) == 1 && result == -2, "stale token refused");
        call.args[0].number = native_settings::Begin; call.args[1].number = 0;
        writeResult = 0;
        Check(ns::Dispatch(player, player, &call) == 1 && result > 0 && ns::resultWriteFailures == 1,
            "failed Iggy result write is counted for runtime diagnostics");
        writeResult = 1;
        ns::dispatchEvent = MockEvent;
        ns::makeEventChar = MockChar;
        ns::makeEventKey = MockKey;
        ns::hasFocusedEditable = MockFocus;
        ns::originalTick = MockTick;
        ns::ResetNumericEdit();
        ns::QueueNumericKey('4');
        Check(ns::TickInput(player) == 71 && inputEvents.size() == 23 &&
            inputEvents.front() == 9000 + VK_BACK && inputEvents.back() == 1000 + '4',
            "first number replaces the old slider value and forwards a character");
        ns::QueueNumericKey(VK_NUMPAD2);
        ns::TickInput(player);
        Check(inputEvents.size() == 24 && inputEvents.back() == 1000 + '2',
            "later digits append without clearing the edited number");
        editable = false;
        ns::QueueNumericKey('9');
        ns::TickInput(player);
        Check(inputEvents.size() == 24, "keyboard input is not dispatched without an editable field");
        editable = true;
        ns::ResetNumericEdit();
        Check(ns::inputQueued == 0, "focus transition discards queued input");
        CloseHandle(ns::channelGate);
        std::cout << "PASS: deferred Iggy discovery, callback hook retry backoff, strict hash/export states, callback forwarding, Boolean/integer conversion, save acknowledgements, result paths, UTF-8 and UTF-16; no game loaded\n";
        return 0;
    } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
