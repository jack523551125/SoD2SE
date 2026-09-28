#include <windows.h>
#include <d3d11.h>
#include <dxgi.h>
#include <xinput.h>
#include <atomic>
#include <mutex>
#include <string>
#include <vector>
#include <algorithm>
#include <cstdio>
#include "imgui.h"
#include "imgui_impl_win32.h"
#include "imgui_impl_dx11.h"
#include "MinHook.h"
#include "McmProtocol.h"
#include "UiTheme.h"
#include "NativeSettingsIggy.h"

extern IMGUI_IMPL_API LRESULT ImGui_ImplWin32_WndProcHandler(HWND, UINT, WPARAM, LPARAM);
namespace {
using PresentFn = HRESULT (STDMETHODCALLTYPE*)(IDXGISwapChain*, UINT, UINT);
using ResizeFn = HRESULT (STDMETHODCALLTYPE*)(IDXGISwapChain*, UINT, UINT, UINT, DXGI_FORMAT, UINT);
PresentFn originalPresent = nullptr;
ResizeFn originalResize = nullptr;
decltype(&GetAsyncKeyState) originalKeys = nullptr;
decltype(&SetCursorPos) originalSetCursorPos = nullptr;
decltype(&ClipCursor) originalClipCursor = nullptr;
using XInputFn = DWORD (WINAPI*)(DWORD, XINPUT_STATE*);
XInputFn originalXInput = nullptr;
std::recursive_mutex renderLock;
std::atomic<bool> disabled{false}, started{false};
HANDLE mapping = nullptr, gate = nullptr, owner = nullptr;
mcm::State* shared = nullptr;
mcm::State snapshot{};
HWND window = nullptr;
WNDPROC originalWindow = nullptr;
IDXGISwapChain* activeSwap = nullptr;
ID3D11Device* device = nullptr;
ID3D11DeviceContext* context = nullptr;
ID3D11RenderTargetView* target = nullptr;
RECT previousClip{};
bool initialized = false, keys[256]{};
// Which screen the host is showing.  The built-in settings screen and the mod
// screens stay mutually exclusive so two panels never fight over the input.
int openSurface = -1;
// A saved upgrade choice is only data availability.  It becomes a visible
// screen after the player presses the progression shortcut or its button.
bool choiceOpen = false;
int choiceRequestSeen = 0;
int selectedPage = -1;
int integerDraft[mcm::MaxOptions]{};
bool editingInteger[mcm::MaxOptions]{};
unsigned fontHash = 0;

const char* T(const char* chinese, const char* english) {
    return snapshot.language == 1 ? chinese : english;
}

void Log(const char* message) {
    wchar_t base[32768]{};
    if (!GetEnvironmentVariableW(L"LOCALAPPDATA", base, 32768)) return;
    std::wstring dir = std::wstring(base) + L"\\StateOfDecay2";
    CreateDirectoryW(dir.c_str(), nullptr);
    dir += L"\\SoD2SE"; CreateDirectoryW(dir.c_str(), nullptr);
    std::wstring path = dir + L"\\Mcm-native-" + std::to_wstring(GetCurrentProcessId()) + L".log";
    FILE* file = nullptr;
    if (_wfopen_s(&file, path.c_str(), L"ab") == 0 && file) {
        fprintf(file, "[%llu] %s\n", GetTickCount64(), message); fclose(file);
    }
}

void LogIggyInitStatus(bool force = false) {
    using native_settings_iggy::InitStatus;
    static InitStatus previous = InitStatus::NotAttempted;
    const auto current = native_settings_iggy::initStatus;
    if (!force && current == previous) return;
    previous = current;
    switch (current) {
        case InitStatus::NotAttempted: Log("native settings: Iggy initialization not attempted"); break;
        case InitStatus::WaitingForModule: Log("native settings: waiting for iggy_w64.dll to load"); break;
        case InitStatus::UnsupportedHash: Log("native settings unavailable: Iggy DLL hash could not be verified"); break;
        case InitStatus::UnsupportedExports: Log("native settings unavailable: pinned Iggy exports do not match"); break;
        case InitStatus::Ready: Log("native settings: pinned Iggy ABI verified"); break;
    }
}

void LogIggyHookStatus() {
    static int previous = -1;
    const int status = native_settings_iggy::hookStatus.load();
    if (status == previous) return;
    previous = status;
    using native_settings_iggy::HookStatus;
    switch (static_cast<HookStatus>(status)) {
        case HookStatus::Waiting: Log("native settings: waiting to hook Iggy callback"); break;
        case HookStatus::CallbackMissing: Log("native settings unavailable: Iggy external callback slots are empty"); break;
        case HookStatus::Installed: Log("native settings: Iggy external callback hook installed"); break;
        case HookStatus::CreateFailed:
            Log(("native settings unavailable: MinHook create failed " + std::to_string(native_settings_iggy::hookError.load())).c_str()); break;
        case HookStatus::EnableFailed:
            Log(("native settings unavailable: MinHook enable failed " + std::to_string(native_settings_iggy::hookError.load())).c_str()); break;
    }
}

bool ChoiceModalVisible() {
    return choiceOpen && snapshot.choiceVisible != 0 && snapshot.choiceNonce != 0;
}
// The old F1 configuration window has been retired. MCM configuration now
// lives under the game's own Settings category; only gameplay surfaces and
// pending upgrade choices use this renderer.
bool AnyVisible() { return openSurface >= 0 || ChoiceModalVisible(); }
void ApplyVisibility(bool configOpen, int surface);
void OpenChoiceOverlay();
void ShowGrowthOverview();
bool IsForeground();
bool LockChannel() {
    DWORD result = WaitForSingleObject(gate, 0);
    return result == WAIT_OBJECT_0 || result == WAIT_ABANDONED;
}

// Copies the managed block, publishes this host's own state back, and refuses
// to draw when the protocol version does not match.
void ReadChannel() {
    if (!shared || !LockChannel()) return;
    snapshot = *shared;
    bool openChoiceRequest = false;
    bool closeChoiceRequest = false;
    // A mod button asking for the upgrade prompt opens it explicitly.  Merely
    // publishing saved candidates must not take over the player's screen.
    if (shared->uiChoiceRequest != choiceRequestSeen)
    {
        choiceRequestSeen = shared->uiChoiceRequest;
        openChoiceRequest = snapshot.choiceVisible != 0 && snapshot.choiceNonce != 0;
    }
    if (!snapshot.choiceVisible || snapshot.choiceNonce == 0) closeChoiceRequest = choiceOpen;
    // A visibility request is applied once per revision, so a mod asking for a
    // screen and the player closing it never ping-pong.  Only one screen shows
    // at a time; opening a mod screen closes the settings panel.  While the
    // game window is not focused the renderer hides every screen, so the
    // request stays pending instead of being consumed and lost.
    bool foreground = IsForeground();
    for (int i = 0; i < mcm::MaxSurfaces; ++i) {
        auto& live = shared->uiSurfaces[i];
        if (foreground && i < snapshot.uiSurfaceCount && live.wantRevision != live.seenRevision) {
            if (snapshot.uiSurfaces[i].wantOpen) { openSurface = i; }
            else if (openSurface == i) openSurface = -1;
            live.seenRevision = live.wantRevision;
        }
        live.open = openSurface == i ? 1 : 0;
    }
    if (openSurface >= snapshot.uiSurfaceCount) openSurface = -1;
    shared->visible = AnyVisible() ? 1 : 0;
    shared->uiChoiceOpen = ChoiceModalVisible() ? 1 : 0;
    if (initialized) shared->ready = mcm::Ready;
    ReleaseMutex(gate);
    if (closeChoiceRequest) ApplyVisibility(false, -1);
    else if (openChoiceRequest) OpenChoiceOverlay();
    if (snapshot.magic != mcm::Magic || snapshot.version != mcm::Version || snapshot.pageCount < 0 ||
        snapshot.pageCount > mcm::MaxPages || snapshot.optionCount < 0 || snapshot.optionCount > mcm::MaxOptions ||
        snapshot.uiSurfaceCount < 0 || snapshot.uiSurfaceCount > mcm::MaxSurfaces ||
        snapshot.uiNodeCount < 0 || snapshot.uiNodeCount > mcm::MaxNodes)
        disabled = true;
    if (snapshot.shutdown) disabled = true;
}

bool Command(int type, int page = 0, int option = 0, int value = 0, int key = 0, int modifiers = 0) {
    if (!LockChannel()) return false;
    bool available = shared->request == shared->acknowledged && !shared->shutdown;
    if (available) {
        shared->command = type; shared->page = page; shared->option = option;
        shared->value = value; shared->key = key; shared->modifiers = modifiers;
        shared->request = (shared->request == INT_MAX) ? 1 : shared->request + 1;
        snapshot.request = shared->request;
    }
    ReleaseMutex(gate);
    return available;
}

bool IsForeground() { return window && GetForegroundWindow() == window; }

void UpdateInputOwnership(bool wasVisible) {
    bool nowVisible = AnyVisible();
    if (nowVisible == wasVisible) return;
    if (nowVisible) {
        GetClipCursor(&previousClip);
        originalClipCursor(nullptr);
        // Release gameplay keys already held when the menu opens.
        for (int key = 8; key < 256; ++key)
            if (originalKeys(key) & 0x8000)
                CallWindowProcW(originalWindow, window, WM_KEYUP, key, (LPARAM)0xc0000001);
    } else {
        std::fill(std::begin(editingInteger), std::end(editingInteger), false);
        if (IsForeground()) originalClipCursor(&previousClip);
    }
    if (initialized) { ImGui::GetIO().MouseDrawCursor = nowVisible; ImGui::GetIO().ClearInputKeys(); }
    Log(nowVisible ? "screen opened" : "screen closed");
}

void ApplyVisibility(bool, int surface) {
    bool wasVisible = AnyVisible();
    choiceOpen = false;
    openSurface = (surface >= 0 && surface < snapshot.uiSurfaceCount) ? surface : -1;
    UpdateInputOwnership(wasVisible);
}

void OpenChoiceOverlay() {
    if (!snapshot.choiceVisible || snapshot.choiceNonce == 0) {
        ShowGrowthOverview();
        return;
    }
    bool wasVisible = AnyVisible();
    openSurface = -1;
    choiceOpen = true;
    UpdateInputOwnership(wasVisible);
}

void ShowGrowthOverview() {
    bool wasVisible = AnyVisible();
    choiceOpen = false;
    openSurface = snapshot.uiChoiceOwner >= 0 && snapshot.uiChoiceOwner < snapshot.uiSurfaceCount
        ? snapshot.uiChoiceOwner : -1;
    UpdateInputOwnership(wasVisible);
}

int Modifiers() {
    return ((originalKeys(VK_CONTROL) & 0x8000) ? mcm::ShortcutControlModifier : 0) |
           ((originalKeys(VK_MENU) & 0x8000) ? mcm::ShortcutAltModifier : 0) |
           ((originalKeys(VK_SHIFT) & 0x8000) ? mcm::ShortcutShiftModifier : 0);
}
bool MatchesSurfaceShortcut(int key, int modifiers) {
    for (int i = 0; i < snapshot.uiSurfaceCount; ++i)
        if (snapshot.uiSurfaces[i].shortcutKey == key && snapshot.uiSurfaces[i].shortcutModifiers == modifiers) return true;
    return false;
}
int SurfaceShortcutIndex(int key, int modifiers) {
    for (int i = 0; i < snapshot.uiSurfaceCount; ++i)
        if (snapshot.uiSurfaces[i].shortcutKey == key && snapshot.uiSurfaces[i].shortcutModifiers == modifiers) return i;
    return -1;
}

void PollKeys() {
    if (!IsForeground() || disabled) { ApplyVisibility(false, -1); for (bool& key : keys) key = false; return; }
    int modifiers = Modifiers();
    for (int key = 8; key < 256; ++key) {
        bool down = (originalKeys(key) & 0x8000) != 0;
        if (down && !keys[key]) {
            int surfaceIndex = SurfaceShortcutIndex(key, modifiers);
            if (key == VK_ESCAPE && AnyVisible()) {
                ApplyVisibility(false, -1);
            } else if (ChoiceModalVisible() && key >= '1' && key < '1' + mcm::MaxChoiceCards) {
                Command(mcm::CmdSelectChoice, snapshot.choiceNonce, key - '1');
            } else if (key == snapshot.choiceKey && modifiers == snapshot.choiceModifiers) {
                // F2 belongs to the progression system.  It opens the choice
                // when one is waiting, then toggles to the growth overview.
                if (ChoiceModalVisible()) ShowGrowthOverview();
                else if (snapshot.choiceVisible && snapshot.choiceNonce != 0) OpenChoiceOverlay();
                else if (snapshot.uiChoiceOwner >= 0 && openSurface == snapshot.uiChoiceOwner) ApplyVisibility(false, -1);
                else ShowGrowthOverview();
            } else if (surfaceIndex >= 0 && !ChoiceModalVisible()) {
                ApplyVisibility(false, openSurface == surfaceIndex ? -1 : surfaceIndex);
            }
        }
        keys[key] = down;
    }
}
SHORT WINAPI KeysHook(int key) { return AnyVisible() && !disabled ? 0 : originalKeys(key); }
BOOL WINAPI PositionHook(int x, int y) { return AnyVisible() && !disabled ? TRUE : originalSetCursorPos(x, y); }
BOOL WINAPI ClipHook(const RECT* clip) { return AnyVisible() && !disabled ? TRUE : originalClipCursor(clip); }
DWORD WINAPI XInputHook(DWORD index, XINPUT_STATE* state) {
    DWORD result = originalXInput(index, state);
    if (result == ERROR_SUCCESS && state && AnyVisible() && !disabled) ZeroMemory(&state->Gamepad, sizeof(state->Gamepad));
    return result;
}
LRESULT CALLBACK WindowHook(HWND hwnd, UINT message, WPARAM wparam, LPARAM lparam) {
    {
        std::lock_guard<std::recursive_mutex> lock(renderLock);
        if (initialized && !disabled) {
            if (native_settings_iggy::eventHookTarget && !AnyVisible()) {
                if (message == WM_LBUTTONDOWN || message == WM_KILLFOCUS ||
                    (message == WM_KEYDOWN && wparam == VK_TAB))
                    native_settings_iggy::ResetNumericEdit();
                else if (message == WM_KEYDOWN &&
                    !(GetKeyState(VK_CONTROL) & 0x8000) && !(GetKeyState(VK_MENU) & 0x8000))
                    native_settings_iggy::QueueNumericKey(static_cast<int>(wparam));
            }
            if (message == WM_KEYDOWN || message == WM_SYSKEYDOWN) {
                int key = (int)wparam, modifiers = Modifiers();
                if ((key == snapshot.choiceKey && modifiers == snapshot.choiceModifiers) ||
                    MatchesSurfaceShortcut(key, modifiers)) return 0;
            }
            if (AnyVisible()) {
                ImGui_ImplWin32_WndProcHandler(hwnd, message, wparam, lparam);
                if ((message >= WM_KEYFIRST && message <= WM_KEYLAST) ||
                    (message >= WM_MOUSEFIRST && message <= WM_MOUSELAST) || message == WM_INPUT) {
                    // DefWindowProc releases foreground raw-input buffers.
                    return message == WM_INPUT ? DefWindowProcW(hwnd, message, wparam, lparam) : 0;
                }
                if (message == WM_SETCURSOR) return TRUE;
            }
            if (message == WM_KILLFOCUS) ApplyVisibility(false, -1);
        }
    }
    return CallWindowProcW(originalWindow, hwnd, message, wparam, lparam);
}

// Cheap fingerprint of every string the atlas has to cover.  A mod that
// registers a screen after start-up changes the hash, and the atlas rebuilds
// once before the next frame.
struct Hasher {
    unsigned value = 2166136261u;
    void Add(const char* text) {
        for (const unsigned char* p = (const unsigned char*)(text ? text : ""); *p; ++p)
            value = (value ^ *p) * 16777619u;
        value = (value ^ 0x1fu) * 16777619u;
    }
};

void CollectGlyphs(ImFontGlyphRangesBuilder& ranges, Hasher& hasher) {
    ranges.AddRanges(ImGui::GetIO().Fonts->GetGlyphRangesChineseSimplifiedCommon());
    static const char* builtin[] = {
        "界面快捷键", "模块界面", "录制", "等待按键…", "升级界面快捷键", "录制升级快捷键",
        "配置保存", "恢复 Mod 默认设置", "恢复默认值？", "确认恢复", "取消", "返回游戏",
        "本次运行：已启用", "本次运行：未启用", "下次启动生效", "正在保存…", "设置自动保存。",
        "让配置留在游戏里", "幸存者成长", "升级选择", "选择一项强化", "选择", "确认", "未知",
        "尚未注册任何模块界面。", "按 1、2、3 或点击卡片", "已选", "次", "等级", "经验", "待领取",
        "角色", "按键", "Esc 返回游戏",
    };
    for (const char* label : builtin) { ranges.AddText(label); hasher.Add(label); }
    hasher.Add(T("中文", "English"));
    for (int i = 0; i < snapshot.pageCount && i < mcm::MaxPages; ++i) {
        hasher.Add(snapshot.pages[i].name); hasher.Add(snapshot.pages[i].description);
        ranges.AddText(snapshot.pages[i].name); ranges.AddText(snapshot.pages[i].description);
    }
    for (int i = 0; i < snapshot.optionCount && i < mcm::MaxOptions; ++i) {
        hasher.Add(snapshot.options[i].label); hasher.Add(snapshot.options[i].description);
        ranges.AddText(snapshot.options[i].label); ranges.AddText(snapshot.options[i].description);
    }
    for (int i = 0; i < snapshot.choiceCount && i < mcm::MaxChoiceCards; ++i) {
        hasher.Add(snapshot.choiceCards[i].title); hasher.Add(snapshot.choiceCards[i].description);
        ranges.AddText(snapshot.choiceCards[i].title); ranges.AddText(snapshot.choiceCards[i].description);
    }
    for (const char* text : {snapshot.choiceCharacter, snapshot.choiceExperience, snapshot.choiceNextExperience}) {
        hasher.Add(text); ranges.AddText(text);
    }
    for (int i = 0; i < snapshot.uiSurfaceCount && i < mcm::MaxSurfaces; ++i) {
        auto& surface = snapshot.uiSurfaces[i];
        hasher.Add(surface.title); hasher.Add(surface.subtitle);
        ranges.AddText(surface.title); ranges.AddText(surface.subtitle);
    }
    for (int i = 0; i < snapshot.uiNodeCount && i < mcm::MaxNodes; ++i) {
        auto& node = snapshot.uiNodes[i];
        hasher.Add(node.label); hasher.Add(node.value); hasher.Add(node.description);
        ranges.AddText(node.label); ranges.AddText(node.value); ranges.AddText(node.description);
    }
}

void BuildFonts() {
    auto& io = ImGui::GetIO();
    io.Fonts->Clear();
    ImFontGlyphRangesBuilder ranges;
    Hasher hasher;
    CollectGlyphs(ranges, hasher);
    static ImVector<ImWchar> glyphs;
    glyphs.clear();
    ranges.BuildRanges(&glyphs);
    wchar_t fonts[MAX_PATH]{};
    GetWindowsDirectoryW(fonts, MAX_PATH);
    std::wstring wide = std::wstring(fonts) + L"\\Fonts\\msyh.ttc";
    char path[MAX_PATH * 3]{};
    WideCharToMultiByte(CP_UTF8, 0, wide.c_str(), -1, path, sizeof(path), nullptr, nullptr);
    if (GetFileAttributesW(wide.c_str()) != INVALID_FILE_ATTRIBUTES)
        io.Fonts->AddFontFromFileTTF(path, 21, nullptr, glyphs.Data);
    if (io.Fonts->Fonts.empty()) io.Fonts->AddFontDefault();
    fontHash = hasher.value;
}

std::string KeyName(int key) {
    if (key <= 0) return T("未设置", "Not set");
    if (key >= VK_F1 && key <= VK_F12) return "F" + std::to_string(key - VK_F1 + 1);
    char name[64]{};
    GetKeyNameTextA((LONG)(MapVirtualKeyW(key, MAPVK_VK_TO_VSC) << 16), name, sizeof(name));
    return name[0] ? name : "Key";
}
std::string ShortcutText(int key, int modifiers) {
    std::string value;
    if (modifiers & 1) value += "Ctrl + ";
    if (modifiers & 2) value += "Alt + ";
    if (modifiers & 4) value += "Shift + ";
    return value + KeyName(key);
}
std::string ChoiceShortcut() { return ShortcutText(snapshot.choiceKey, snapshot.choiceModifiers); }

bool Initialize(IDXGISwapChain* swap) {
    DXGI_SWAP_CHAIN_DESC desc{};
    if (FAILED(swap->GetDesc(&desc)) || !IsWindowVisible(desc.OutputWindow)) return false;
    DWORD pid = 0; GetWindowThreadProcessId(desc.OutputWindow, &pid);
    if (pid != GetCurrentProcessId()) return false;
    if (FAILED(swap->GetDevice(__uuidof(ID3D11Device), (void**)&device))) return false;
    device->GetImmediateContext(&context);
    window = desc.OutputWindow; activeSwap = swap;
    IMGUI_CHECKVERSION(); ImGui::CreateContext();
    auto& io = ImGui::GetIO(); io.IniFilename = nullptr; io.LogFilename = nullptr;
    io.ConfigFlags |= ImGuiConfigFlags_NoMouseCursorChange | ImGuiConfigFlags_NavEnableKeyboard;
    BuildFonts();
    ui::ApplyTheme();
    bool win32Ready = ImGui_ImplWin32_Init(window);
    bool dx11Ready = win32Ready && ImGui_ImplDX11_Init(device, context);
    SetLastError(0);
    if (dx11Ready) originalWindow = (WNDPROC)SetWindowLongPtrW(window, GWLP_WNDPROC, (LONG_PTR)WindowHook);
    if (!originalWindow) {
        if (dx11Ready) ImGui_ImplDX11_Shutdown();
        if (win32Ready) ImGui_ImplWin32_Shutdown();
        ImGui::DestroyContext(); context->Release(); device->Release();
        context = nullptr; device = nullptr; activeSwap = nullptr; window = nullptr;
        disabled = true;
        if (LockChannel()) { shared->ready = mcm::Failed; ReleaseMutex(gate); }
        Log("renderer initialization failed; menu disabled");
        return false;
    }
    initialized = true;
    Log("D3D11 swapchain initialized; UI host ready");
    return true;
}

// Rebuilds the glyph atlas when a mod registers text the atlas has not seen.
void RefreshFontsIfNeeded() {
    if (!initialized) return;
    ImFontGlyphRangesBuilder ranges;
    Hasher hasher;
    CollectGlyphs(ranges, hasher);
    if (hasher.value == fontHash) return;
    ImGui_ImplDX11_InvalidateDeviceObjects();
    BuildFonts();
    if (!ImGui_ImplDX11_CreateDeviceObjects()) Log("font atlas rebuild failed");
}

// ---------------------------------------------------------------------------
// Screens
// ---------------------------------------------------------------------------

void ChoiceOverlay() {
    ImGui::SetNextWindowPos({ImGui::GetIO().DisplaySize.x * 0.5f, ImGui::GetIO().DisplaySize.y * 0.5f},
                            ImGuiCond_Always, {0.5f, 0.5f});
    bool open = ImGui::Begin("SoD2SE Choice", nullptr, ImGuiWindowFlags_NoDecoration | ImGuiWindowFlags_NoMove |
        ImGuiWindowFlags_NoSavedSettings | ImGuiWindowFlags_AlwaysAutoResize);
    if (open) {
        float width = ImGui::GetWindowWidth() - 60;
        ImGui::TextColored(ui::Accent(), "%s", T("升级选择", "UPGRADE CHOICE"));
        ImGui::Separator();
        ui::KeyValue(T("角色", "Survivor"), snapshot.choiceCharacter, ui::ToneNormal, width);
        std::string level = std::to_string(snapshot.choiceLevel);
        ui::KeyValue(T("等级", "Level"), level.c_str(), ui::ToneNormal, width);
        std::string experience = std::string(snapshot.choiceExperience) + " / " + snapshot.choiceNextExperience;
        ui::KeyValue(T("经验", "Experience"), experience.c_str(), ui::ToneNormal, width);
        std::string pending = std::to_string(snapshot.choicePending);
        ui::KeyValue(T("待领取", "Pending"), pending.c_str(), ui::ToneAccent, width);
        ImGui::Spacing();
        ui::Wrapped(T("选择一项强化。结果立即保存；按 1、2、3 或点击卡片。",
            "Choose one upgrade. The result is saved immediately; press 1, 2, 3 or click a card."), ui::ToneMuted);
        ImGui::Spacing();
        for (int i = 0; i < snapshot.choiceCount && i < mcm::MaxChoiceCards; ++i) {
            auto& card = snapshot.choiceCards[i];
            ImGui::PushID(i);
            ui::Section(card.title);
            ui::Wrapped(card.description, ui::ToneNormal);
            if (ImGui::Button(T("选择", "Choose"), {200, 40})) Command(mcm::CmdSelectChoice, snapshot.choiceNonce, i);
            ImGui::PopID();
            ImGui::Spacing();
        }
        if (ImGui::Button(T("查看成长总览", "View progression overview"), {240, 40})) ShowGrowthOverview();
    }
    ImGui::End();
}

// Draws one declarative screen.  This is the point of the framework: a mod
// publishes rows and the host owns spacing, tone, input and the shell.
void SurfaceNodes(const mcm::UiSurface& surface, int surfaceIndex, float width) {
    int start = std::max(0, surface.nodeStart);
    int count = std::min(surface.nodeCount, mcm::MaxNodesPerSurface);
    for (int i = 0; i < count; ++i) {
        int index = start + i;
        if (index < 0 || index >= snapshot.uiNodeCount || index >= mcm::MaxNodes) break;
        auto& node = snapshot.uiNodes[index];
        switch (node.kind) {
            case ui::KindSection:
                ui::Section(node.label);
                break;
            case ui::KindText:
                ui::Wrapped(node.label, node.tone);
                break;
            case ui::KindKeyValue:
                ui::KeyValue(node.label, node.value, node.tone, width);
                ui::Description(node.description, ui::ToneMuted);
                break;
            case ui::KindProgress:
                ui::Progress(node.label, node.current, node.maximum, node.value, width);
                ui::Description(node.description, ui::ToneMuted);
                break;
            case ui::KindRow:
                ImGui::Spacing();
                ui::KeyValue(node.label, node.value, node.tone, width);
                ui::Description(node.description, node.tone == ui::ToneNormal ? ui::ToneMuted : node.tone);
                break;
            case ui::KindButton:
                ImGui::Spacing();
                if (ImGui::Button(node.label[0] ? node.label : T("确认", "Confirm"), {240, 40}))
                    Command(mcm::CmdSurfaceAction, surfaceIndex, index, surface.revision);
                ui::Description(node.description, ui::ToneMuted);
                break;
            case ui::KindNote:
                ui::Wrapped(node.description[0] ? node.description : node.label,
                            node.tone == ui::ToneNormal ? ui::ToneMuted : node.tone);
                break;
            default:
                ImGui::Spacing();
                ImGui::Separator();
                ImGui::Spacing();
                break;
        }
    }
}

void SurfaceWindow(int index) {
    auto& surface = snapshot.uiSurfaces[index];
    // Taller than the settings panel: a mod screen is a progress or status
    // page, and the host clamps the size to the real display.
    bool open = ui::BeginShell("SoD2SE Surface", {960.f, 960.f});
    if (open) {
        float width = ImGui::GetWindowWidth() - 64;
        // A screen without a key of its own says how it is reached instead of
        // showing "not set", which tells the player nothing.  The upgrade key
        // brings its owning screen forward, so that is the honest hint.  Keep
        // the string alive: Title only borrows the pointer.
        std::string hint;
        if (surface.shortcutKey > 0) hint = ShortcutText(surface.shortcutKey, surface.shortcutModifiers);
        else if (snapshot.uiChoiceOwner == index) hint = ChoiceShortcut();
        ui::Title(surface.title, hint.c_str(), width);
        if (surface.subtitle[0]) { ui::Wrapped(surface.subtitle, ui::ToneMuted); ImGui::Spacing(); }
        ImGui::BeginChild("surface-body", {0, -64}, ImGuiChildFlags_None);
        SurfaceNodes(surface, index, width);
        ImGui::EndChild();
        if (ui::Footer(T("Esc 返回游戏", "Esc returns to game"), T("返回游戏", "Return to game"))) ApplyVisibility(false, -1);
    }
    ImGui::End();
}

void RenderFrame() {
    ImGui_ImplDX11_NewFrame(); ImGui_ImplWin32_NewFrame(); ImGui::NewFrame();
    if (openSurface >= 0 && openSurface < snapshot.uiSurfaceCount) SurfaceWindow(openSurface);
    if (ChoiceModalVisible()) ChoiceOverlay();
    ImGui::Render();
    ID3D11RenderTargetView* old[D3D11_SIMULTANEOUS_RENDER_TARGET_COUNT]{};
    ID3D11DepthStencilView* depth = nullptr;
    context->OMGetRenderTargets(D3D11_SIMULTANEOUS_RENDER_TARGET_COUNT, old, &depth);
    context->OMSetRenderTargets(1, &target, nullptr);
    ImGui_ImplDX11_RenderDrawData(ImGui::GetDrawData());
    context->OMSetRenderTargets(D3D11_SIMULTANEOUS_RENDER_TARGET_COUNT, old, depth);
    for (auto oldTarget : old) if (oldTarget) oldTarget->Release();
    if (depth) depth->Release();
}

HRESULT STDMETHODCALLTYPE PresentHook(IDXGISwapChain* swap, UINT interval, UINT flags) {
    static unsigned loggedTrace = 0, loggedMalformedCalls = 0, loggedBusyCalls = 0;
    static unsigned loggedBeginFailures = 0, loggedRejectedReplies = 0;
    static unsigned loggedResultPathFailures = 0, loggedResultWriteFailures = 0;
    static unsigned loggedInputDelivered = 0;
    static int loggedInputHookState = 0;
    {
        std::lock_guard<std::recursive_mutex> lock(renderLock);
        try {
            if (owner && WaitForSingleObject(owner, 0) == WAIT_OBJECT_0) disabled = true;
            if (!disabled) {
                const auto previousIggyStatus = native_settings_iggy::initStatus;
                native_settings_iggy::Pump();
                if (previousIggyStatus != native_settings_iggy::initStatus) LogIggyInitStatus();
                LogIggyHookStatus();
                const int inputHookState = native_settings_iggy::eventHookTarget ? 1 :
                    native_settings_iggy::eventHookError.load() ? -1 : 0;
                if (inputHookState != loggedInputHookState) {
                    loggedInputHookState = inputHookState;
                    Log(inputHookState > 0 ? "native settings numeric input: Iggy event hook installed" :
                        ("native settings numeric input: hook unavailable " +
                         std::to_string(native_settings_iggy::eventHookError.load())).c_str());
                }
                const unsigned deliveredInput = native_settings_iggy::inputDelivered.load();
                if (deliveredInput != loggedInputDelivered) {
                    loggedInputDelivered = deliveredInput;
                    Log(("native settings numeric input: forwarded " +
                         std::to_string(deliveredInput) + " edit events").c_str());
                }
                const unsigned traces = std::min<unsigned>(native_settings_iggy::rpcTraceCount.load(),
                    static_cast<unsigned>(native_settings_iggy::rpcTrace.size()));
                while (loggedTrace < traces) {
                    const auto& trace = native_settings_iggy::rpcTrace[loggedTrace];
                    if (!trace.ready.load(std::memory_order_acquire)) break;
                    Log(("native settings RPC #" + std::to_string(loggedTrace + 1) +
                        " op=" + std::to_string(trace.op) +
                        " revision=" + std::to_string(trace.revision) +
                        " index=" + std::to_string(trace.index) +
                        " reply=" + (trace.textLength >= 0 ? "text:" + std::to_string(trace.textLength)
                            : std::to_string(trace.result)) +
                        " written=" + std::to_string(trace.written)).c_str());
                    ++loggedTrace;
                }
                const unsigned malformed = native_settings_iggy::malformedCalls.load();
                if (malformed > loggedMalformedCalls) { loggedMalformedCalls = malformed; Log("native settings unavailable: Iggy MCM RPC arguments did not match the pinned ABI"); }
                const unsigned busy = native_settings_iggy::busyCalls.load();
                if (busy > loggedBusyCalls) { loggedBusyCalls = busy; Log("native settings unavailable: Iggy MCM RPC collided with settings processing"); }
                const unsigned beginFailures = native_settings_iggy::beginFailures.load();
                if (beginFailures > loggedBeginFailures) { loggedBeginFailures = beginFailures; Log("native settings unavailable: MCM channel refused to begin a settings snapshot"); }
                const unsigned rejected = native_settings_iggy::rejectedReplies.load();
                if (rejected > loggedRejectedReplies) { loggedRejectedReplies = rejected; Log("native settings unavailable: MCM bridge rejected an Iggy settings request"); }
                const unsigned pathFailures = native_settings_iggy::resultPathFailures.load();
                if (pathFailures > loggedResultPathFailures) { loggedResultPathFailures = pathFailures; Log("native settings unavailable: Iggy callback result path is null"); }
                const unsigned writeFailures = native_settings_iggy::resultWriteFailures.load();
                if (writeFailures > loggedResultWriteFailures) { loggedResultWriteFailures = writeFailures; Log("native settings unavailable: Iggy refused the callback result value"); }
            }
            ReadChannel();
            if (disabled) ApplyVisibility(false, -1);
            else if ((initialized || Initialize(swap)) && swap == activeSwap) {
                PollKeys();
                RefreshFontsIfNeeded();
                if (AnyVisible()) {
                    if (!target) {
                        ID3D11Texture2D* buffer = nullptr;
                        if (SUCCEEDED(swap->GetBuffer(0, __uuidof(ID3D11Texture2D), (void**)&buffer))) {
                            device->CreateRenderTargetView(buffer, nullptr, &target); buffer->Release();
                        }
                    }
                    if (target) RenderFrame();
                }
            }
        } catch (...) { disabled = true; ApplyVisibility(false, -1); Log("render exception: UI host disabled"); }
    }
    return originalPresent(swap, interval, flags);
}
HRESULT STDMETHODCALLTYPE ResizeHook(IDXGISwapChain* swap, UINT count, UINT width, UINT height, DXGI_FORMAT format, UINT flags) {
    std::lock_guard<std::recursive_mutex> lock(renderLock);
    if (swap == activeSwap && target) { target->Release(); target = nullptr; }
    return originalResize(swap, count, width, height, format, flags);
}
bool Hook(void* targetAddress, void* replacement, void** original) {
    return MH_CreateHook(targetAddress, replacement, original) == MH_OK && MH_QueueEnableHook(targetAddress) == MH_OK;
}
}

extern "C" __declspec(dllexport) DWORD WINAPI SoD2McmStart(void* argument) {
    if (started.exchange(true)) return 1;
    const auto channel = static_cast<const wchar_t*>(argument);
    if (!channel || wcsnlen_s(channel, 256) >= 256) return 2;
    mapping = OpenFileMappingW(FILE_MAP_ALL_ACCESS, FALSE, channel);
    gate = OpenMutexW(SYNCHRONIZE | MUTEX_MODIFY_STATE, FALSE, (std::wstring(channel) + L".lock").c_str());
    if (!mapping || !gate) return 3;
    shared = (mcm::State*)MapViewOfFile(mapping, FILE_MAP_ALL_ACCESS, 0, 0, sizeof(mcm::State));
    if (!shared || shared->magic != mcm::Magic || shared->version != mcm::Version || shared->game != GetCurrentProcessId()) return 4;
    owner = OpenProcess(SYNCHRONIZE, FALSE, shared->owner);
    if (!owner) return 5;
    ReadChannel();
    HINSTANCE instance = GetModuleHandleW(nullptr);
    const wchar_t* cls = L"SoD2SE.MCM.D3D11.Probe";
    WNDCLASSEXW wc{sizeof(wc)}; wc.lpfnWndProc = DefWindowProcW; wc.hInstance = instance; wc.lpszClassName = cls;
    if (!RegisterClassExW(&wc)) return 6;
    HWND probe = CreateWindowExW(0, cls, L"", WS_OVERLAPPEDWINDOW, 0, 0, 64, 64, nullptr, nullptr, instance, nullptr);
    DXGI_SWAP_CHAIN_DESC desc{};
    desc.BufferCount = 1; desc.BufferDesc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
    desc.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT; desc.OutputWindow = probe;
    desc.SampleDesc.Count = 1; desc.Windowed = TRUE; desc.SwapEffect = DXGI_SWAP_EFFECT_DISCARD;
    IDXGISwapChain* swap = nullptr; ID3D11Device* probeDevice = nullptr; ID3D11DeviceContext* probeContext = nullptr;
    HRESULT hr = D3D11CreateDeviceAndSwapChain(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, 0, nullptr, 0,
                                             D3D11_SDK_VERSION, &desc, &swap, &probeDevice, nullptr, &probeContext);
    if (FAILED(hr)) { DestroyWindow(probe); UnregisterClassW(cls, instance); Log("D3D11 probe failed"); return 7; }
    void** table = *(void***)swap;
    bool success = MH_Initialize() == MH_OK;
    success = success && Hook(table[8], (void*)PresentHook, (void**)&originalPresent);
    success = success && Hook(table[13], (void*)ResizeHook, (void**)&originalResize);
    success = success && Hook((void*)&GetAsyncKeyState, (void*)KeysHook, (void**)&originalKeys);
    success = success && Hook((void*)&SetCursorPos, (void*)PositionHook, (void**)&originalSetCursorPos);
    success = success && Hook((void*)&ClipCursor, (void*)ClipHook, (void**)&originalClipCursor);
    for (const auto dll : {L"xinput1_3.dll", L"xinput1_4.dll", L"xinput9_1_0.dll"}) {
        HMODULE module = GetModuleHandleW(dll);
        auto entry = module ? GetProcAddress(module, "XInputGetState") : nullptr;
        if (entry) { success = success && Hook((void*)entry, (void*)XInputHook, (void**)&originalXInput); break; }
    }
    native_settings_iggy::Initialize(shared, gate);
    LogIggyInitStatus(true);
    if (success) success = MH_ApplyQueued() == MH_OK;
    probeContext->Release(); probeDevice->Release(); swap->Release();
    DestroyWindow(probe); UnregisterClassW(cls, instance);
    if (!success) { disabled = true; MH_DisableHook(MH_ALL_HOOKS); Log("hook installation failed"); return 8; }
    if (LockChannel()) { shared->ready = mcm::ReadyPending; ReleaseMutex(gate); }
    Log("hooks installed; waiting for game Present; native settings bridge prepared");
    return 0;
}

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) DisableThreadLibraryCalls(instance);
    // Hooks/code stay resident until process exit: never unload a live trampoline.
    return TRUE;
}
