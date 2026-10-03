#pragma once
#include <cstdint>
#include <cstddef>

namespace growth_ui {
constexpr int Magic = 0x32575247, Version = 3, MaxRows = 256, MaxSelections = 64, StringCapacity = 524288;
enum Op : int { Begin, Count, Header, Title, Description, Kind, Selected, Choose, Confirm, Status, Close, Group, Busy };
enum RowKind : int { Information, Choice, Confirmation, Equipment, Profession, Heading, Navigation };
#pragma pack(push, 4)
struct Row { int kind, group, selected, titleOffset, titleLength, descriptionOffset, descriptionLength; };
struct Command { int op, token, row, count, selections[MaxSelections]; };
struct State {
    int magic, version, capacity, shutdown, heartbeat, busy, token, rowCount, textBytes;
    int headerOffset, headerLength, statusOffset, statusLength, request, acknowledged, result;
    Row rows[MaxRows];
    char text[StringCapacity];
    Command command;
};
#pragma pack(pop)
static_assert(sizeof(Row) == 28 && offsetof(State, rows) == 64 && offsetof(State, text) == 7232 &&
    offsetof(State, command) == 531520 && sizeof(State) == 531792, "Growth v3 UI ABI");
}
