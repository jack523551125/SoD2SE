#include "NativeSettingsModel.h"
#include <iostream>
#include <memory>
#include <stdexcept>

static void Check(bool value, const char* message) { if (!value) throw std::runtime_error(message); }
int main() {
    try {
        auto state = std::make_unique<mcm::State>();
        state->magic = mcm::Magic; state->version = mcm::Version;
        state->pageCount = 1; state->optionCount = 2; state->language = 1;
        strcpy_s(state->pages[0].id, "melee"); strcpy_s(state->pages[0].name, "近战攻速");
        strcpy_s(state->options[0].id, "enabled");
        state->options[0].maximum = 1;
        strcpy_s(state->options[1].id, "speed"); state->options[1].type = mcm::OptionIntegerInput;
        state->options[1].minimum = 10; state->options[1].maximum = 1000; state->options[1].value = 100;
        native_settings::Model model;
        int revision = model.Open(*state);
        Check(revision > 0, "snapshot opens");
        Check(model.Query(native_settings::PageName, revision, 0, 0).value == "近战攻速", "UTF-8 title");
        Check(model.Query(native_settings::SetOption, revision + 1, 0, 1).number == -2, "stale receipt refused");
        Check(model.Query(native_settings::SetOption, revision, 1, 1001).number == -3, "range enforced");
        Check(model.Query(native_settings::SetOption, revision, 1, 200).number == 1, "integer accepted");
        model.Query(native_settings::SetOption, revision, 1, 300);
        model.Pump(*state);
        Check(state->command == mcm::CmdSetInt && state->value == 300, "rapid edits coalesced");
        Check(model.Open(*state) == 0, "unacknowledged edits cannot lose their snapshot");
        auto request = state->request; model.Pump(*state);
        Check(state->request == request, "no duplicate command while pending");
        state->options[1].value = 300; state->acknowledged = request;
        model.Pump(*state);
        Check(model.Query(native_settings::StatusCode, revision, 0, 0).number == 0, "acknowledged");
        model.Query(native_settings::SetOption, revision, 0, 1);
        strcpy_s(state->options[0].id, "different-setting");
        model.Pump(*state);
        Check(state->request == request, "reordered/replaced option never receives stale edit");
        Check(model.Query(native_settings::SetOption, revision, 0, 1).number == -2, "drift invalidates session");
        revision = model.Open(*state);
        Check(model.Query(native_settings::Language, revision, 0, 0).number == 1, "detected game language is exposed read-only");
        Check(model.Query(16, revision, 0, 2).number == -3, "manual language changes are no longer accepted");
        state->shutdown = 1;
        Check(model.Open(*state) == 0, "shutdown refused");
        std::cout << "PASS: native settings snapshots, revisions, UTF-8, bounds, coalescing, acknowledgements, identity drift and read-only language\n";
        return 0;
    } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
