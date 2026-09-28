#pragma once
#include "McmProtocol.h"
#include <algorithm>
#include <array>
#include <climits>
#include <cstring>
#include <deque>
#include <string>
#include <utility>

// Original Settings host. No game pointers, disk I/O or engine calls live here.
// Caller serializes access and holds the existing MCM channel lock for Pump.
namespace native_settings {
enum Op : int {
    Begin = 0, PageCount = 1, OptionCount = 2, PageName = 3, PageDescription = 4,
    PageLoaded = 5, OptionPage = 6, OptionLabel = 7, OptionDescription = 8,
    OptionType = 9, OptionValue = 10, OptionMinimum = 11, OptionMaximum = 12,
    OptionRestart = 13, Language = 14, SetOption = 15,
    Status = 17, StatusCode = 18
};
struct Reply {
    int number = -1;
    bool text = false;
    std::string value;
    static Reply Number(int n) { Reply r; r.number = n; return r; }
    static Reply Text(std::string s) { Reply r; r.text = true; r.value = std::move(s); return r; }
};
template<size_t N> std::string Text(const char (&s)[N]) {
    const auto end = std::find(s, s + N, '\0');
    return std::string(s, end);
}
class Model {
    struct Edit {
        int command, index, value;
        mcm::Page page{};
        mcm::Option option{};
    };
    std::array<mcm::Page, mcm::MaxPages> pages{};
    std::array<mcm::Option, mcm::MaxOptions> options{};
    int pageCount = 0, optionCount = 0, language = 2, token = 0, generation = 0;
    std::deque<Edit> pending;
    bool flight = false;
    int request = 0, status = 0;
    std::string message;

    static bool Valid(const mcm::State& s) {
        if (s.magic != mcm::Magic || s.version != mcm::Version || s.shutdown ||
            s.pageCount < 0 || s.pageCount > mcm::MaxPages ||
            s.optionCount < 0 || s.optionCount > mcm::MaxOptions) return false;
        for (int i = 0; i < s.optionCount; ++i) {
            const auto& o = s.options[i];
            if (o.page < 0 || o.page >= s.pageCount || o.minimum > o.maximum ||
                o.type < mcm::OptionBoolean || o.type > mcm::OptionIntegerInput) return false;
        }
        return true;
    }
    void Fail(const char* text) { status = -1; message = text; }
public:
    int Open(const mcm::State& s) {
        if (!Valid(s) || flight || !pending.empty() || s.request != s.acknowledged || generation == INT_MAX) return 0;
        pageCount = s.pageCount; optionCount = s.optionCount; language = s.language;
        std::copy_n(s.pages, pageCount, pages.begin());
        std::copy_n(s.options, optionCount, options.begin());
        status = 0; message.clear();
        return token = ++generation;
    }
    Reply Query(int op, int revision, int index, int value) {
        if (revision == generation && generation != 0) {
            if (op == Status) {
                if (flight || !pending.empty()) return Reply::Text(language == 1 ? "正在保存……" : "Saving...");
                return Reply::Text(message.empty() ? (language == 1 ? "设置已同步。" : "Settings synchronized.") : message);
            }
            if (op == StatusCode) return Reply::Number(flight || !pending.empty() ? 1 : status);
        }
        if (revision != token || token == 0) return Reply::Number(-2);
        switch (op) {
        case PageCount: return Reply::Number(pageCount);
        case OptionCount: return Reply::Number(optionCount);
        case Language: return Reply::Number(language);
        case Status: return Reply::Text(message);
        case StatusCode: return Reply::Number(flight || !pending.empty() ? 1 : status);
        }
        if (op >= PageName && op <= PageLoaded) {
            if (index < 0 || index >= pageCount) return Reply::Number(-3);
            if (op == PageName) return Reply::Text(Text(pages[index].name));
            if (op == PageDescription) return Reply::Text(Text(pages[index].description));
            return Reply::Number(pages[index].loaded);
        }
        if (index < 0 || index >= optionCount) return Reply::Number(-3);
        auto& o = options[index];
        switch (op) {
        case OptionPage: return Reply::Number(o.page);
        case OptionLabel: return Reply::Text(Text(o.label));
        case OptionDescription: return Reply::Text(Text(o.description));
        case OptionType: return Reply::Number(o.type);
        case OptionValue: return Reply::Number(o.value);
        case OptionMinimum: return Reply::Number(o.minimum);
        case OptionMaximum: return Reply::Number(o.maximum);
        case OptionRestart: return Reply::Number(o.restart);
        case SetOption:
            if (value < o.minimum || value > o.maximum ||
                (o.type == mcm::OptionBoolean && value != 0 && value != 1)) {
                Fail(language == 1 ? "数值超出允许范围，请修正后再次提交。" : "Value outside the allowed range. Correct it and submit again.");
                return Reply::Number(-3);
            }
            if (value == o.value) return Reply::Number(0);
            Queue(Edit{o.type == mcm::OptionBoolean ? mcm::CmdSetBool : mcm::CmdSetInt,
                index, value, pages[o.page], o});
            o.value = value;
            return Reply::Number(1);
        }
        return Reply::Number(-3);
    }
    void Queue(Edit edit) {
        for (auto& e : pending) {
            if (e.index == edit.index) { e.value = edit.value; return; }
        }
        if (pending.size() >= mcm::MaxOptions) { Fail("Native settings queue full"); return; }
        pending.push_back(edit);
    }
    void Pump(mcm::State& s) {
        if (!Valid(s)) { pending.clear(); flight = false; token = 0; Fail("MCM channel unavailable"); return; }
        if (flight) {
            if (s.acknowledged != request) return;
            flight = false;
            status = s.result == 0 ? 0 : -1;
            message = Text(s.message);
            if (s.result != 0) { pending.clear(); token = 0; return; }
        }
        if (pending.empty() || s.request != s.acknowledged) return;
        const auto edit = pending.front();
        pending.pop_front();
        int page = 0;
        if (edit.index >= 0) {
            if (edit.index >= s.optionCount) { Fail("Settings page changed; reopen it"); token = 0; pending.clear(); return; }
            const auto& now = s.options[edit.index];
            auto old = edit.option; old.value = now.value;
            if (std::memcmp(&old, &now, sizeof(now)) != 0 ||
                std::memcmp(&edit.page, &s.pages[now.page], sizeof(edit.page)) != 0) {
                Fail("Settings page changed; reopen it"); token = 0; pending.clear(); return;
            }
            page = now.page;
        }
        s.command = edit.command; s.page = page; s.option = edit.index; s.value = edit.value;
        s.key = 0; s.modifiers = 0;
        s.request = s.request == INT_MAX ? 1 : s.request + 1;
        request = s.request; flight = true;
    }
};
}
