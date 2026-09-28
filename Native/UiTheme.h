#pragma once
#include "imgui.h"

// Shared look and reusable widgets for every in-game screen.
//
// State of Decay 2 draws its menus as translucent dark panels with off-white
// labels and an amber highlight for the selected item.  Screens hosted by the
// framework copy that language so a mod screen does not look like a debug
// overlay bolted onto the game.
namespace ui {

// Node kinds.  Values are part of the wire protocol in McmProtocol.h.
enum Kind { KindSection = 0, KindText = 1, KindKeyValue = 2, KindProgress = 3, KindRow = 4, KindButton = 5, KindNote = 6, KindSeparator = 7 };
// Text tones.  Values are part of the wire protocol in McmProtocol.h.
enum Tone { ToneNormal = 0, TonePositive = 1, ToneWarning = 2, ToneDanger = 3, ToneMuted = 4, ToneAccent = 5 };

inline ImVec4 Accent() { return {0.85f, 0.69f, 0.36f, 1.0f}; }
inline ImVec4 Positive() { return {0.56f, 0.78f, 0.60f, 1.0f}; }
inline ImVec4 Warning() { return {0.88f, 0.72f, 0.40f, 1.0f}; }
inline ImVec4 Danger() { return {0.93f, 0.49f, 0.39f, 1.0f}; }
inline ImVec4 Muted() { return {0.58f, 0.63f, 0.60f, 1.0f}; }

inline float MinF(float a, float b) { return a < b ? a : b; }
inline float MaxF(float a, float b) { return a > b ? a : b; }
inline float ClampF(float value, float minimum, float maximum) { return value < minimum ? minimum : (value > maximum ? maximum : value); }

inline ImVec4 ToneColor(int tone) {
    switch (tone) {
        case TonePositive: return Positive();
        case ToneWarning: return Warning();
        case ToneDanger: return Danger();
        case ToneMuted: return Muted();
        case ToneAccent: return Accent();
        default: return ImGui::GetStyle().Colors[ImGuiCol_Text];
    }
}

// One place for the shell look so every screen stays consistent.  Call once
// after the ImGui context exists.
inline void ApplyTheme() {
    ImGui::StyleColorsDark();
    auto& s = ImGui::GetStyle();
    s.WindowRounding = 4; s.ChildRounding = 3; s.FrameRounding = 2; s.GrabRounding = 2;
    s.WindowPadding = {28, 24}; s.FramePadding = {12, 8};
    s.ItemSpacing = {12, 10}; s.ItemInnerSpacing = {8, 6};
    s.WindowBorderSize = 1; s.FrameBorderSize = 0; s.ScrollbarSize = 12;
    s.WindowTitleAlign = {0.0f, 0.5f};
    auto c = s.Colors;
    c[ImGuiCol_WindowBg] = {0.055f, 0.070f, 0.078f, 0.965f};
    c[ImGuiCol_ChildBg] = {0.075f, 0.094f, 0.102f, 1.0f};
    c[ImGuiCol_PopupBg] = {0.055f, 0.070f, 0.078f, 0.98f};
    c[ImGuiCol_Text] = {0.92f, 0.94f, 0.92f, 1.0f};
    c[ImGuiCol_TextDisabled] = Muted();
    c[ImGuiCol_Border] = {0.24f, 0.29f, 0.30f, 1.0f};
    c[ImGuiCol_Separator] = {0.30f, 0.36f, 0.36f, 0.85f};
    c[ImGuiCol_Button] = {0.14f, 0.19f, 0.20f, 1.0f};
    c[ImGuiCol_ButtonHovered] = {0.21f, 0.29f, 0.30f, 1.0f};
    c[ImGuiCol_ButtonActive] = {0.28f, 0.38f, 0.38f, 1.0f};
    c[ImGuiCol_Header] = {0.16f, 0.22f, 0.23f, 1.0f};
    c[ImGuiCol_HeaderHovered] = {0.24f, 0.33f, 0.34f, 1.0f};
    c[ImGuiCol_HeaderActive] = {0.31f, 0.42f, 0.42f, 1.0f};
    c[ImGuiCol_FrameBg] = {0.11f, 0.15f, 0.16f, 1.0f};
    c[ImGuiCol_FrameBgHovered] = {0.16f, 0.21f, 0.22f, 1.0f};
    c[ImGuiCol_FrameBgActive] = {0.19f, 0.26f, 0.27f, 1.0f};
    c[ImGuiCol_CheckMark] = Accent();
    c[ImGuiCol_SliderGrab] = Accent();
    c[ImGuiCol_SliderGrabActive] = {0.95f, 0.80f, 0.48f, 1.0f};
    c[ImGuiCol_PlotHistogram] = {0.72f, 0.58f, 0.30f, 1.0f};
    c[ImGuiCol_NavHighlight] = Accent();
}

// Screens share one shell: fixed size, centred, no title bar, no persisted
// position.  Returns the value of ImGui::Begin; callers must still call
// EndShell() unconditionally.
inline bool BeginShell(const char* id, ImVec2 size) {
    auto& io = ImGui::GetIO();
    size.x = MinF(size.x, io.DisplaySize.x - 32);
    size.y = MinF(size.y, io.DisplaySize.y - 32);
    ImGui::SetNextWindowPos({io.DisplaySize.x * 0.5f, io.DisplaySize.y * 0.5f}, ImGuiCond_Always, {0.5f, 0.5f});
    ImGui::SetNextWindowSize(size, ImGuiCond_Always);
    return ImGui::Begin(id, nullptr, ImGuiWindowFlags_NoDecoration | ImGuiWindowFlags_NoMove | ImGuiWindowFlags_NoSavedSettings);
}

inline void EndShell() { ImGui::End(); }

// Title block used by both the built-in settings screen and mod screens.
inline void Title(const char* title, const char* right, float width) {
    ImGui::TextColored(Accent(), "%s", title);
    if (right && right[0]) {
        ImGui::SameLine(MaxF(ImGui::GetCursorPosX(), width - ImGui::CalcTextSize(right).x));
        ImGui::TextDisabled("%s", right);
    }
    ImGui::Spacing();
    ImGui::Separator();
    ImGui::Spacing();
}

inline void Section(const char* label) {
    ImGui::Spacing();
    ImGui::TextColored(Accent(), "%s", label);
    ImGui::Separator();
}

// label on the left, value flush right on the same line.
inline void KeyValue(const char* label, const char* value, int tone, float width) {
    ImGui::TextUnformatted(label);
    if (value && value[0]) {
        ImGui::SameLine();
        ImGui::SetCursorPosX(MaxF(ImGui::GetCursorPosX(), width - ImGui::CalcTextSize(value).x - 24));
        ImGui::TextColored(ToneColor(tone), "%s", value);
    }
}

inline void Description(const char* text, int tone) {
    if (!text || !text[0]) return;
    ImGui::PushStyleColor(ImGuiCol_Text, tone == ToneNormal ? Muted() : ToneColor(tone));
    ImGui::TextWrapped("%s", text);
    ImGui::PopStyleColor();
}

inline void Progress(const char* label, int current, int maximum, const char* value, float width) {
    if (label && label[0]) {
        ImGui::TextUnformatted(label);
        if (value && value[0]) {
            ImGui::SameLine();
            ImGui::SetCursorPosX(MaxF(ImGui::GetCursorPosX(), width - ImGui::CalcTextSize(value).x - 24));
            ImGui::TextColored(Accent(), "%s", value);
        }
    }
    float fraction = maximum > 0 ? ClampF((float)current / (float)maximum, 0.0f, 1.0f) : 0.0f;
    ImGui::PushStyleColor(ImGuiCol_PlotHistogram, Accent());
    ImGui::ProgressBar(fraction, {-1.0f, 10.0f}, "");
    ImGui::PopStyleColor();
}

inline void Wrapped(const char* text, int tone) {
    if (!text || !text[0]) return;
    ImGui::PushStyleColor(ImGuiCol_Text, ToneColor(tone));
    ImGui::TextWrapped("%s", text);
    ImGui::PopStyleColor();
}

// Bottom strip of the shell: key hints on the left, close button on the right.
inline bool Footer(const char* hints, const char* closeLabel) {
    ImGui::Spacing();
    ImGui::Separator();
    ImGui::Spacing();
    if (hints && hints[0]) ImGui::TextDisabled("%s", hints);
    bool close = false;
    ImGui::SameLine();
    ImGui::SetCursorPosX(ImGui::GetWindowWidth() - 170);
    if (ImGui::Button(closeLabel, {140, 32})) close = true;
    return close;
}

}  // namespace ui
