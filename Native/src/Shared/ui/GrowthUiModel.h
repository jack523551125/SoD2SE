#pragma once
#include "GrowthUiProtocol.h"
#include <array>
#include <cstring>
#include <string>
#include <utility>
#include <climits>

// Pure snapshot/command model. Caller owns the named mutex; no pointers to
// Iggy players or game objects, no save I/O and no managed callback waits.
namespace growth_ui {
struct Reply {
    int number = -3; bool text = false; std::string value;
    static Reply Number(int n) { Reply r; r.number = n; return r; }
    static Reply Text(std::string s) { Reply r; r.text = true; r.value = std::move(s); return r; }
};
class Model {
    std::array<bool, MaxRows> selected{};
    std::array<Row, MaxRows> identities{};
    int token = 0, request = 0, rowCount = 0, blockedToken = 0;
    bool flight = false;
    static bool Span(int offset, int length, int total) { return offset >= 0 && length >= 0 && offset <= total && length <= total - offset; }
    static bool Valid(const State& s) {
        if (s.magic != Magic || s.version != Version || s.capacity != sizeof(State) || s.shutdown || s.busy < 0 || s.busy > 1 ||
            s.token < 0 || s.rowCount < 0 || s.rowCount > MaxRows || s.textBytes < 0 || s.textBytes > StringCapacity ||
            !Span(s.headerOffset, s.headerLength, s.textBytes) || !Span(s.statusOffset, s.statusLength, s.textBytes)) return false;
        for (int i = 0; i < s.rowCount; ++i) {
            const auto& r = s.rows[i];
            if (r.kind < Information || r.kind > Navigation || r.selected < 0 || r.selected > 1 ||
                (r.kind == Choice ? r.group < 0 || r.group >= MaxSelections : r.group != -1) ||
                !Span(r.titleOffset, r.titleLength, s.textBytes) || !Span(r.descriptionOffset, r.descriptionLength, s.textBytes)) return false;
        }
        return true;
    }
    static Reply Text(const State& s, int offset, int length) { return Reply::Text(std::string(s.text + offset, static_cast<size_t>(length))); }
public:
    void Reset() { selected.fill(false); token = 0; request = 0; rowCount = 0; blockedToken = 0; flight = false; }
    Reply Query(State& s, int op, int revision, int index, int value, uint32_t now) {
        (void)value;
        if (!Valid(s) || static_cast<uint32_t>(now - static_cast<uint32_t>(s.heartbeat)) > 2000) {
            Reset(); return Reply::Number(op == Begin ? 0 : -2);
        }
        if (blockedToken != 0 && s.token == blockedToken) return Reply::Number(op == Begin ? 0 : -2);
        if (s.token != token) {
            Reset(); token = s.token; rowCount = s.rowCount;
            for (int i = 0; i < s.rowCount; ++i) { selected[i] = s.rows[i].selected != 0; identities[i] = s.rows[i]; }
        } else {
            // A producer may update descriptions, but semantic row identity
            // cannot change within a token. Reject mixed/invalid publications.
            if (rowCount != s.rowCount) { blockedToken = token; return Reply::Number(op == Begin ? 0 : -2); }
            for (int i = 0; i < s.rowCount; ++i)
                if (identities[i].kind != s.rows[i].kind || identities[i].group != s.rows[i].group) {
                    blockedToken = token; return Reply::Number(op == Begin ? 0 : -2);
                }
        }
        if (flight && s.acknowledged == request) flight = false;
        if (op == Begin) return Reply::Number(token);
        if (token == 0 || revision != token) return Reply::Number(-2);
        switch (op) {
        case Count: return Reply::Number(s.rowCount);
        case Header: return Text(s, s.headerOffset, s.headerLength);
        case Status: return Text(s, s.statusOffset, s.statusLength);
        case Busy: return Reply::Number(flight || s.busy);
        case Close:
            if (flight || s.request != s.acknowledged) return Reply::Number(0);
            s.command = {}; s.command.op = Close; s.command.token = token;
            request = s.request = s.request == INT_MAX ? 1 : s.request + 1; flight = true;
            return Reply::Number(1);
        }
        if (index < 0 || index >= s.rowCount) return Reply::Number(-3);
        const auto& r = s.rows[index];
        switch (op) {
        case Title: return Text(s, r.titleOffset, r.titleLength);
        case Description: return Text(s, r.descriptionOffset, r.descriptionLength);
        case Kind: return Reply::Number(r.kind);
        case Group: return Reply::Number(r.group);
        case Selected: return Reply::Number(selected[index] ? 1 : 0);
        case Choose:
            if (flight || s.busy || r.kind != Choice) return Reply::Number(-3);
            for (int i = 0; i < s.rowCount; ++i) if (s.rows[i].group == r.group) selected[i] = i == index;
            return Reply::Number(1);
        case Confirm:
            if (flight || s.busy || s.request != s.acknowledged) return Reply::Number(0);
            if (r.kind != Confirmation && r.kind != Equipment && r.kind != Profession && r.kind != Navigation) return Reply::Number(-3);
            s.command = {}; s.command.op = Confirm; s.command.token = token; s.command.row = index;
            if (r.kind == Confirmation) {
                std::array<bool, MaxSelections> groups{}, chosen{};
                for (int i = 0; i < s.rowCount; ++i) if (s.rows[i].kind == Choice) {
                    const auto group = s.rows[i].group; groups[group] = true;
                    if (selected[i]) {
                        if (chosen[group] || s.command.count == MaxSelections) return Reply::Number(-3);
                        chosen[group] = true; s.command.selections[s.command.count++] = i;
                    }
                }
                if (groups != chosen) return Reply::Number(-3);
            }
            request = s.request = s.request == INT_MAX ? 1 : s.request + 1; flight = true;
            return Reply::Number(1);
        }
        return Reply::Number(-3);
    }
};
}
