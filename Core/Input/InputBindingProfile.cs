using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;

namespace SoD2SE
{
    // Profile ownership is independent of any gameplay Mod. Null is an explicit
    // unbinding; absence means use that action's default.
    public sealed class InputBindingProfile
    {
        readonly string path;
        Dictionary<string, InputChord> values = new Dictionary<string, InputChord>(StringComparer.Ordinal);
        static string Key(string action, InputDevice device) { return action + ":" + (int)device; }
        public InputBindingProfile(string path)
        {
            this.path = Path.GetFullPath(path);
            if (!File.Exists(this.path)) return;
            var lines = File.ReadAllLines(this.path, Encoding.UTF8);
            if (lines.Length == 0 || lines[0] != "SoD2SE-Input/1") throw new InvalidDataException("Unsupported input profile.");
            foreach (var line in lines.Skip(1)) {
                var f = line.Split('|'); if (f.Length != 4) throw new InvalidDataException("Invalid input binding row.");
                string id = Encoding.UTF8.GetString(Convert.FromBase64String(f[0]));
                var device = (InputDevice)Int32.Parse(f[1], CultureInfo.InvariantCulture);
                if (!Enum.IsDefined(typeof(InputDevice), device)) throw new InvalidDataException("Unknown binding device.");
                int code = Int32.Parse(f[2], CultureInfo.InvariantCulture), modifiers = Int32.Parse(f[3], CultureInfo.InvariantCulture);
                values.Add(Key(id, device), code == 0 && modifiers == 0 ? null : new InputChord(device, code, modifiers));
            }
        }
        public InputChord Resolve(string action, InputDevice device, InputChord fallback)
        { InputChord chord; return values.TryGetValue(Key(action, device), out chord) ? chord : fallback; }
        public void Apply(InputActionRegistry registry, string action)
        {
            foreach (InputDevice device in Enum.GetValues(typeof(InputDevice))) {
                InputChord chord; if (values.TryGetValue(Key(action, device), out chord)) registry.Bind(action, device, chord);
            }
        }
        public void Save(string action, InputDevice device, InputChord chord)
        {
            if (chord != null && chord.Device != device) throw new ArgumentException("Binding device mismatch.");
            var next = new Dictionary<string, InputChord>(values, StringComparer.Ordinal); next[Key(action, device)] = chord;
            var lines = new List<string> { "SoD2SE-Input/1" };
            foreach (var entry in next.OrderBy(x => x.Key, StringComparer.Ordinal)) {
                int split = entry.Key.LastIndexOf(':'); string id = entry.Key.Substring(0, split), d = entry.Key.Substring(split + 1);
                lines.Add(Convert.ToBase64String(Encoding.UTF8.GetBytes(id)) + "|" + d + "|" +
                    (entry.Value == null ? "0|0" : entry.Value.Key.ToString(CultureInfo.InvariantCulture) + "|" + entry.Value.Modifiers.ToString(CultureInfo.InvariantCulture)));
            }
            Directory.CreateDirectory(Path.GetDirectoryName(path)); string temp = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
            try {
                File.WriteAllLines(temp, lines, new UTF8Encoding(false));
                if (File.Exists(path)) File.Replace(temp, path, path + ".bak", true); else File.Move(temp, path);
                values = next;
            } finally { if (File.Exists(temp)) File.Delete(temp); }
        }
        public void Change(InputActionRegistry registry, string action, InputDevice device, InputChord chord)
        {
            var old = registry.Binding(action, device); registry.Bind(action, device, chord);
            try { Save(action, device, chord); } catch { registry.Bind(action, device, old); throw; }
        }
    }
}
