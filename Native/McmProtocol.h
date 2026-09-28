#pragma once
#include <cstdint>
#include <cstddef>

// ABI v6: v2/v3/v4/v5 fields keep their offsets.  The v5 fixed "growth" block
// is replaced by a generic surface block, so any mod can describe a screen
// once and let the shared host draw it.  Older clients reject the version.
namespace mcm {
constexpr uint32_t Magic = 0x314d434d;
// Bumped whenever the layout below changes.  Both sides compare it before
// touching anything, so a half-updated install fails loudly instead of
// reading another build's memory.
constexpr uint32_t Version = 6;
// Handshake written by the host into State::ready.  Named so the C# bridge and
// the verifier do not have to guess what a bare 1 or 2 means.
constexpr int32_t ReadyPending = 1, Ready = 2, Failed = -1;
constexpr int MaxPages = 32, MaxOptions = 128;
constexpr int MaxChoiceCards = 3;
constexpr int MaxSurfaces = 6;
constexpr int MaxNodes = 96;
constexpr int MaxNodesPerSurface = 24;
// Shortcut capture windows.  The host decides whether a recorded key is
// acceptable and the managed bridge revalidates it before it stores anything,
// so both sides read the same table here.  Core/McmKeys.cs mirrors these
// values, and verify_protocol.py compares the two lists.
constexpr int ShortcutFunctionFirst = 112, ShortcutFunctionLast = 123;   // VK_F1..VK_F12
constexpr int ShortcutLetterFirst = 65, ShortcutLetterLast = 90;         // VK_A..VK_Z
constexpr int ShortcutDigitFirst = 48, ShortcutDigitLast = 57;           // VK_0..VK_9
constexpr int ShortcutNavigationFirst = 33, ShortcutNavigationLast = 36; // VK_PRIOR..VK_HOME
constexpr int ShortcutInsert = 45, ShortcutDelete = 46, ShortcutTab = 9;
// Alt+F4 belongs to Windows, so a recording never claims it: 115 is VK_F4.
constexpr int ShortcutReservedKey = 115;
constexpr int ShortcutControlModifier = 1, ShortcutAltModifier = 2, ShortcutShiftModifier = 4;
constexpr int ShortcutMaxModifiers = 7;
// State::command values.  The host writes one of these and the managed bridge
// switches on it; both sides name the same operation instead of repeating a
// bare integer.  verify_protocol.py checks the two lists against each other.
enum CommandId : int32_t {
    CmdSetBool = 1,
    CmdSetInt = 2,
    CmdResetAll = 3,
    CmdSetShortcut = 4,
    CmdSelectChoice = 6,
    CmdSetChoiceShortcut = 7,
    CmdSetSurfaceShortcut = 8,
    CmdSurfaceAction = 9,
};
// Option::type values.  The managed side names the same three kinds in the
// McmOptionType enum in Core/Mcm.cs, and verify_protocol.py compares the two
// lists, so a new widget cannot ship with only one side knowing about it.
enum OptionType : int32_t {
    OptionBoolean = 0,
    OptionInteger = 1,
    OptionIntegerInput = 2,
};
#pragma pack(push, 4)
struct Page { char id[64], name[128], description[512]; int32_t loaded; };
struct Option {
    int32_t page;
    char id[64], label[128], description[512];
    int32_t type, value, minimum, maximum, restart;
};
struct ChoiceCard {
    int32_t currentValue, nextValue;
    char id[64], title[128], description[512];
};
// One declarative screen.  The managed bridge owns wantOpen/wantRevision and
// every descriptor field; the native host owns open/seenRevision and applies a
// visibility request exactly once per revision.  Because each side only writes
// its own fields, a publish never erases the host's state and a host-side
// toggle (shortcut or Esc) never fights the mod's request.
struct UiSurface {
    int32_t wantOpen, open, modal, priority, revision, nodeStart, nodeCount, shortcutKey, shortcutModifiers;
    int32_t wantRevision, seenRevision;
    char id[64], title[128], subtitle[256];
};
struct UiNode {
    int32_t kind, tone, current, maximum;
    char action[64], label[128], value[96], description[256];
};
struct State {
    uint32_t magic, version, owner, game;
    int32_t request, acknowledged, command, page, option, value, key, modifiers;
    int32_t result, visible, ready, shutdown, pageCount, optionCount, shortcutKey, shortcutModifiers;
    int32_t language;
    char message[512], configPath[1024];
    Page pages[MaxPages];
    Option options[MaxOptions];
    int32_t choiceVisible, choiceLevel, choicePending, choiceNonce, choiceCount, choiceSelected, choiceKey, choiceModifiers, choiceResult;
    ChoiceCard choiceCards[MaxChoiceCards];
    char choiceCharacter[128], choiceExperience[64], choiceNextExperience[64];
    int32_t uiSurfaceCount, uiChoiceOpen;
    UiSurface uiSurfaces[MaxSurfaces];
    int32_t uiNodeCount;
    UiNode uiNodes[MaxNodes];
    // Surface index that owns the upgrade prompt, or -1.  The managed side
    // writes it; the host routes the "show upgrade" key to that screen.
    // uiChoiceRequest is a counter: a new value asks the host to un-dismiss the
    // prompt (a mod button can bring the choice back).
    int32_t uiChoiceOwner, uiChoiceRequest;
};
#pragma pack(pop)
static_assert(sizeof(Page) == 708 && sizeof(Option) == 728 && sizeof(ChoiceCard) == 712, "MCM ABI packing changed");
static_assert(sizeof(UiSurface) == 492 && sizeof(UiNode) == 560, "UI packing changed");
static_assert(offsetof(State, pages) == 1620 && offsetof(State, choiceVisible) == 117460 &&
    offsetof(State, uiSurfaceCount) == 119888 && offsetof(State, uiChoiceOpen) == 119892 &&
    offsetof(State, uiSurfaces) == 119896 && offsetof(State, uiNodeCount) == 122848 &&
    offsetof(State, uiNodes) == 122852 && offsetof(State, uiChoiceOwner) == 176612 &&
    offsetof(State, uiChoiceRequest) == 176616 && sizeof(State) == 176620, "MCM ABI mismatch");
}
