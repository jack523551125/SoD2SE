#pragma once
#include <windows.h>
#include "GrowthUiModel.h"

namespace growth_ui {
class Client {
    HANDLE mapping = nullptr, gate = nullptr;
    State* state = nullptr;
    Model model;
    uint32_t lastAttempt = 0;
    bool attempted = false;
    void Disconnect() {
        if (state) UnmapViewOfFile(state);
        if (mapping) CloseHandle(mapping);
        if (gate) CloseHandle(gate);
        state = nullptr; mapping = gate = nullptr; model.Reset();
    }
    bool Connect(uint32_t now) {
        if (state) return true;
        if (attempted && static_cast<uint32_t>(now - lastAttempt) < 1000) return false;
        attempted = true; lastAttempt = now;
        const auto name = L"Local\\SoD2SE.Growth.v3." + std::to_wstring(GetCurrentProcessId());
        gate = OpenMutexW(SYNCHRONIZE | MUTEX_MODIFY_STATE, FALSE, (name + L".Gate").c_str());
        if (!gate) return false;
        mapping = OpenFileMappingW(FILE_MAP_READ | FILE_MAP_WRITE, FALSE, name.c_str());
        if (mapping) state = static_cast<State*>(MapViewOfFile(mapping, FILE_MAP_READ | FILE_MAP_WRITE, 0, 0, sizeof(State)));
        if (!state) { Disconnect(); return false; }
        return true;
    }
public:
    ~Client() { Disconnect(); }
    void Pump() {
        if (!state) return;
        const auto locked = WaitForSingleObject(gate, 0);
        if (locked != WAIT_OBJECT_0 && locked != WAIT_ABANDONED) return;
        const bool expired = state->shutdown != 0 || static_cast<uint32_t>(GetTickCount() - static_cast<uint32_t>(state->heartbeat)) > 2000;
        ReleaseMutex(gate);
        // Also release handles while Character is hidden, so a stopped owner
        // cannot leave a stale named mapping behind until the next menu open.
        if (expired) { Disconnect(); attempted = false; }
    }
    Reply Query(int op, int revision, int index, int value) {
        const uint32_t now = GetTickCount();
        if (!Connect(now)) return Reply::Number(op == Begin ? 0 : -2);
        const auto locked = WaitForSingleObject(gate, 0);
        if (locked != WAIT_OBJECT_0 && locked != WAIT_ABANDONED) return Reply::Number(-4);
        Reply reply;
        bool expired = false;
        try {
            expired = state->shutdown != 0 || static_cast<uint32_t>(now - static_cast<uint32_t>(state->heartbeat)) > 2000;
            reply = model.Query(*state, op, revision, index, value, now);
        } catch (...) { reply = Reply::Number(-4); }
        ReleaseMutex(gate);
        if (expired) { Disconnect(); attempted = false; }
        return reply;
    }
};
inline Client client;
}
