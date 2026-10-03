using System;
using System.Collections.Generic;
using System.Linq;

namespace SoD2SE
{
    public interface IGameInputSession
    {
        InputActionRegistry InputActions { get; }
    }
    [Flags] public enum InputContext { None = 0, Gameplay = 1, Menu = 2, TextEntry = 4 }
    public enum InputTrigger { Press, Release, Hold }
    public enum InputDevice { Keyboard, Gamepad }
    public sealed class InputChord : IEquatable<InputChord>
    {
        public readonly InputDevice Device;
        public readonly int Key, Modifiers;
        // Gamepad keys/modifiers are XInput button bits, keyboard uses McmKeys.
        public InputChord(InputDevice device, int key, int modifiers)
        {
            if (device != InputDevice.Keyboard && device != InputDevice.Gamepad) throw new ArgumentException("Unknown input device.");
            if (device == InputDevice.Keyboard && !ValidKeyboardOrMouse(key, modifiers)) throw new ArgumentException("Invalid keyboard/mouse chord.");
            const int allowedButtons = 0xF3FF;
            if (device == InputDevice.Gamepad && (key <= 0 || (key & (key - 1)) != 0 || (key & ~allowedButtons) != 0 ||
                (modifiers & ~allowedButtons) != 0 || (modifiers & key) != 0)) throw new ArgumentException("Invalid controller chord.");
            Device = device; Key = key; Modifiers = modifiers;
        }
        public static bool ValidKeyboardOrMouse(int key, int modifiers)
        { return McmKeys.ValidKey(key, modifiers) || (modifiers >= 0 && modifiers <= McmKeys.MaxModifiers && (key == 1 || key == 2 || key == 4 || key == 5 || key == 6)); }
        public bool Equals(InputChord other) { return other != null && Device == other.Device && Key == other.Key && Modifiers == other.Modifiers; }
        public override bool Equals(object other) { return Equals(other as InputChord); }
        public override int GetHashCode() { return ((int)Device * 397 ^ Key) * 397 ^ Modifiers; }
        public string Describe(McmLanguage language)
        {
            if (Device == InputDevice.Keyboard) {
                if (Key != 1 && Key != 2 && Key != 4 && Key != 5 && Key != 6) return UiShortcut.Describe(Key, Modifiers);
                string name = Key == 1 ? (language == McmLanguage.Chinese ? "鼠标左键" : "Mouse Left") :
                    Key == 2 ? (language == McmLanguage.Chinese ? "鼠标右键" : "Mouse Right") :
                    Key == 4 ? (language == McmLanguage.Chinese ? "鼠标中键" : "Mouse Middle") : "Mouse " + (Key == 5 ? "X1" : "X2");
                return ((Modifiers & McmKeys.ControlModifier) != 0 ? "Ctrl+" : "") +
                    ((Modifiers & McmKeys.AltModifier) != 0 ? "Alt+" : "") + ((Modifiers & McmKeys.ShiftModifier) != 0 ? "Shift+" : "") + name;
            }
            var names = new List<string>();
            int buttons = Modifiers | Key;
            int[] bits = { 0x100, 0x200, 0x10, 0x20, 0x40, 0x80, 1, 2, 4, 8, 0x1000, 0x2000, 0x4000, 0x8000 };
            string[] english = { "LB", "RB", "Start", "Back", "LS", "RS", "D-pad Up", "D-pad Down", "D-pad Left", "D-pad Right", "A", "B", "X", "Y" };
            string[] chinese = { "LB", "RB", "Start", "Back", "LS", "RS", "十字键上", "十字键下", "十字键左", "十字键右", "A", "B", "X", "Y" };
            for (int i = 0; i < bits.Length; ++i) if ((buttons & bits[i]) != 0) names.Add(language == McmLanguage.Chinese ? chinese[i] : english[i]);
            return String.Join("+", names);
        }
    }
    public sealed class InputActionDefinition
    {
        public readonly string Id, Owner;
        public readonly McmLocalizedText Name;
        public readonly InputContext Contexts;
        public readonly InputTrigger Trigger;
        public readonly bool Consume;
        public readonly InputChord Keyboard, Gamepad;
        public readonly Func<bool> Available;
        public readonly Action Invoke;
        public InputActionDefinition(string owner, string id, McmLocalizedText name, InputContext contexts,
            InputTrigger trigger, bool consume, InputChord keyboard, InputChord gamepad, Func<bool> available, Action invoke)
        {
            if (!FrameworkInfo.IsValidPluginId(owner) || String.IsNullOrWhiteSpace(id) || name == null || invoke == null ||
                contexts == InputContext.None || (contexts & ~(InputContext.Gameplay | InputContext.Menu | InputContext.TextEntry)) != 0 || !Enum.IsDefined(typeof(InputTrigger), trigger) ||
                (keyboard != null && keyboard.Device != InputDevice.Keyboard) || (gamepad != null && gamepad.Device != InputDevice.Gamepad))
                throw new ArgumentException("Invalid input action.");
            Owner = owner; Id = id; Name = name; Contexts = contexts; Trigger = trigger; Consume = consume;
            Keyboard = keyboard; Gamepad = gamepad; Available = available ?? (() => true); Invoke = invoke;
        }
    }
    public sealed class InputFrame
    {
        public bool Focused, Loading, CharacterCanAct;
        public InputContext Context;
        public int KeyboardModifiers, GamepadButtons;
        public ISet<int> KeyboardKeys = new HashSet<int>();
    }
    public sealed class InputDispatchResult
    {
        public bool SuppressAllInput;
        public readonly List<string> Triggered = new List<string>();
        public readonly List<InputChord> Consumed = new List<InputChord>();
        public readonly List<string> Errors = new List<string>();
    }
    // Feed only from a verified input interception point BEFORE original actions run.
    // This registry does not poll Win32 keys or claim to consume game input itself.
    public sealed class InputActionRegistry
    {
        sealed class Entry
        {
            public InputActionDefinition Action;
            public InputChord Keyboard, Gamepad;
            public bool KeyboardDown, GamepadDown, Armed;
            public bool KeyboardCaptured, GamepadCaptured;
        }
        sealed class Lease : IDisposable
        {
            Action release;
            public Lease(Action release) { this.release = release; }
            public void Dispose() { var r = System.Threading.Interlocked.Exchange(ref release, null); if (r != null) r(); }
        }
        readonly object sync = new object();
        readonly Dictionary<string, Entry> entries = new Dictionary<string, Entry>(StringComparer.Ordinal);
        string recordingId;
        InputDevice recordingDevice;
        bool captureArmed;
        Action<InputChord> persistCapture;
        public string RecordingId { get { lock (sync) return recordingId; } }
        public void BeginRecording(string id, InputDevice device, Action<InputChord> persist)
        {
            lock (sync) {
                if (!entries.ContainsKey(id)) throw new ArgumentException("Unknown action.");
                if (device != InputDevice.Keyboard && device != InputDevice.Gamepad) throw new ArgumentException("Unknown device.");
                recordingId = id; recordingDevice = device; captureArmed = false; persistCapture = persist;
            }
        }
        public void CancelRecording() { lock (sync) { recordingId = null; persistCapture = null; captureArmed = false; } }
        public IDisposable Register(InputActionDefinition action)
        {
            if (action == null) throw new ArgumentNullException("action");
            lock (sync) {
                if (entries.ContainsKey(action.Id)) throw new InvalidOperationException("Duplicate input action: " + action.Id);
                CheckConflict(action.Id, action.Contexts, action.Keyboard); CheckConflict(action.Id, action.Contexts, action.Gamepad);
                entries.Add(action.Id, new Entry { Action = action, Keyboard = action.Keyboard, Gamepad = action.Gamepad });
            }
            return new Lease(delegate { lock (sync) entries.Remove(action.Id); });
        }
        public IDisposable RegisterLegacyShortcut(string owner, string id, McmLocalizedText name, int key, int modifiers, Action invoke)
        {
            return Register(new InputActionDefinition(owner, id, name, InputContext.Gameplay | InputContext.Menu,
                InputTrigger.Press, true, key == 0 && modifiers == 0 ? null : new InputChord(InputDevice.Keyboard, key, modifiers), null, null, invoke));
        }
        void CheckConflict(string id, InputContext contexts, InputChord chord)
        {
            if (chord == null) return;
            foreach (var entry in entries.Values)
                if (entry.Action.Id != id && (entry.Action.Contexts & contexts) != 0 &&
                    (Conflicts(chord, entry.Keyboard) || Conflicts(chord, entry.Gamepad))) throw new InvalidOperationException("Binding conflicts with " + entry.Action.Id);
        }
        static bool Conflicts(InputChord a, InputChord b)
        {
            if (a == null || b == null || a.Device != b.Device) return false;
            if (a.Device == InputDevice.Keyboard) return a.Equals(b);
            // Controller modifiers use subset matching. Reject chords that can
            // consume the same principal button, even with different bumpers.
            return a.Key == b.Key || (a.Modifiers & b.Key) != 0 || (b.Modifiers & a.Key) != 0;
        }
        public void Bind(string id, InputDevice device, InputChord chord)
        {
            lock (sync) {
                var e = entries[id];
                if (chord != null && chord.Device != device) throw new ArgumentException("Binding device mismatch.");
                CheckConflict(id, e.Action.Contexts, chord);
                if (device == InputDevice.Keyboard) e.Keyboard = chord;
                else if (device == InputDevice.Gamepad) e.Gamepad = chord;
                else throw new ArgumentException("Unknown binding device.");
                e.Armed = false; e.KeyboardDown = e.GamepadDown = false; e.KeyboardCaptured = e.GamepadCaptured = false;
            }
        }
        public InputChord Binding(string id, InputDevice device)
        { lock (sync) return device == InputDevice.Keyboard ? entries[id].Keyboard : entries[id].Gamepad; }
        public void RestoreDefaults(string id)
        {
            lock (sync) {
                var e = entries[id];
                CheckConflict(id, e.Action.Contexts, e.Action.Keyboard); CheckConflict(id, e.Action.Contexts, e.Action.Gamepad);
                e.Keyboard = e.Action.Keyboard; e.Gamepad = e.Action.Gamepad; e.Armed = false;
            }
        }
        public void Reset()
        { lock (sync) foreach (var e in entries.Values) { e.Armed = false; e.KeyboardDown = e.GamepadDown = false; e.KeyboardCaptured = e.GamepadCaptured = false; } }
        static bool Down(InputChord c, InputFrame f)
        {
            if (c == null) return false;
            return c.Device == InputDevice.Keyboard ? f.KeyboardKeys.Contains(c.Key) && f.KeyboardModifiers == c.Modifiers :
                (f.GamepadButtons & (c.Key | c.Modifiers)) == (c.Key | c.Modifiers);
        }
        public InputDispatchResult Feed(InputFrame frame)
        {
            if (frame == null) throw new ArgumentNullException("frame");
            var result = new InputDispatchResult();
            var calls = new List<InputActionDefinition>();
            lock (sync) {
                if (recordingId != null) {
                    result.SuppressAllInput = true;
                    if (!frame.Focused || frame.Loading) { captureArmed = false; return result; }
                    if (frame.KeyboardKeys.Contains(27)) { CancelRecording(); Reset(); return result; }
                    bool neutral = recordingDevice == InputDevice.Keyboard ? frame.KeyboardKeys.Count == 0 && frame.KeyboardModifiers == 0 : frame.GamepadButtons == 0;
                    if (!captureArmed) { captureArmed = neutral; return result; }
                    InputChord captured = null;
                    if (recordingDevice == InputDevice.Keyboard) {
                        var keys = frame.KeyboardKeys.Where(k => InputChord.ValidKeyboardOrMouse(k, frame.KeyboardModifiers)).ToArray();
                        if (keys.Length == 1) captured = new InputChord(InputDevice.Keyboard, keys[0], frame.KeyboardModifiers);
                    } else {
                        int modifiers = frame.GamepadButtons & 0x300, key = frame.GamepadButtons & 0xF0FF;
                        if (key > 0 && (key & (key - 1)) == 0) captured = new InputChord(InputDevice.Gamepad, key, modifiers);
                    }
                    if (captured != null) {
                        var previous = Binding(recordingId, recordingDevice);
                        try {
                            Bind(recordingId, recordingDevice, captured);
                            if (persistCapture != null) persistCapture(captured);
                            result.Consumed.Add(captured); CancelRecording(); Reset();
                        } catch (Exception ex) {
                            Bind(recordingId, recordingDevice, previous); result.Errors.Add(ex.Message); captureArmed = false;
                        }
                    }
                    return result;
                }
                foreach (var e in entries.Values.OrderBy(x => x.Action.Id)) {
                    bool permitted = frame.Focused && !frame.Loading && (frame.Context & e.Action.Contexts) != 0 &&
                        ((frame.Context & InputContext.Gameplay) == 0 || (frame.CharacterCanAct && (frame.Context & (InputContext.Menu | InputContext.TextEntry)) == 0));
                    bool keyboard = Down(e.Keyboard, frame), gamepad = Down(e.Gamepad, frame);
                    if (!permitted) { e.Armed = false; e.KeyboardDown = e.GamepadDown = false; e.KeyboardCaptured = e.GamepadCaptured = false; continue; }
                    // Require neutral input after registration/context changes/focus loss.
                    if (!e.Armed) { e.Armed = !keyboard && !gamepad; continue; }
                    bool wasDown = e.KeyboardDown || e.GamepadDown, isDown = keyboard || gamepad;
                    bool fire = e.Action.Trigger == InputTrigger.Press ? isDown && !wasDown :
                        e.Action.Trigger == InputTrigger.Release ? !isDown && wasDown : isDown;
                    bool available = false;
                    try { available = e.Action.Available(); } catch (Exception ex) { result.Errors.Add(e.Action.Id + ": " + ex.Message); }
                    // Consume held owned chords even during cooldown; never leak D-pad to the game.
                    if (e.Action.Consume) {
                        if (keyboard) e.KeyboardCaptured = true;
                        if (gamepad) e.GamepadCaptured = true;
                        if (e.KeyboardCaptured && e.Keyboard != null) {
                            result.Consumed.Add(e.Keyboard);
                            e.KeyboardCaptured = frame.KeyboardKeys.Contains(e.Keyboard.Key);
                        }
                        if (e.GamepadCaptured && e.Gamepad != null) {
                            result.Consumed.Add(e.Gamepad);
                            e.GamepadCaptured = (frame.GamepadButtons & e.Gamepad.Key) != 0;
                        }
                    }
                    e.KeyboardDown = keyboard; e.GamepadDown = gamepad;
                    if (fire && available) calls.Add(e.Action);
                }
            }
            foreach (var action in calls) {
                lock (sync) { Entry entry; if (!entries.TryGetValue(action.Id, out entry) || entry.Action != action) continue; }
                try { action.Invoke(); result.Triggered.Add(action.Id); }
                catch (Exception ex) { result.Errors.Add(action.Id + ": " + ex.Message); }
            }
            return result;
        }
    }
}
