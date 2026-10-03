using System;
using System.IO;
using System.Linq;
using SoD2SE;

// Exercises the declarative UI framework without a renderer: surface
// registration, shortcut assignment and persistence, node limits, build
// callbacks, action dispatch and the request-revision handshake with the host.
static class UiFrameworkSmoke
{
    static void Check(bool value, string message) { if (!value) throw new Exception(message); }

    static int Main()
    {
        string config = Path.Combine(Path.GetTempPath(), "sod2-ui-smoke-" + Guid.NewGuid().ToString("N") + ".ini");
        int failures = 0;
        try
        {
            Environment.SetEnvironmentVariable("SOD2SE_UI_CONFIG", config);
            var ui = UiRegistry.Initialize(Path.GetTempPath());
            Check(ui.Language == McmLanguage.English, "language falls back when MCM is absent");

            int refreshes = 0;
            var growth = ui.RegisterSurface("smoke.growth", "Growth", "subtitle", surface =>
            {
                refreshes++;
                surface.Section("Status");
                surface.KeyValue("Survivor", "Alice");
                surface.Progress("XP", refreshes, 100, refreshes + " / 100");
                surface.Row("Max health", "+" + refreshes, "picked " + refreshes + "x");
                surface.Button("Open choice", "open-choice", "hint");
                surface.Note("no capabilities", UiTone.Warning);
                surface.Separator();
            });
            Check(growth.ShortcutKey == 113 && growth.ShortcutModifiers == 0, "first screen defaults to F2");
            var inventory = ui.RegisterSurface("smoke.inventory", "Inventory", "");
            Check(inventory.ShortcutKey == 114, "second screen takes the next free function key");

            var first = ui.Snapshot();
            Check(first.Count == 2, "both screens are published");
            Check(refreshes == 1, "build callback runs once per publish");
            Check(first[0].NodeStart == 0 && first[1].NodeStart == first[0].NodeCount, "node offsets accumulate");
            Check(first[0].Nodes.Count == 7, "every declared row is published");
            Check(first[0].Nodes[0].Kind == UiNodeKind.Section && first[0].Nodes[1].Kind == UiNodeKind.KeyValue, "row kinds survive the round trip");
            Check(first[0].Nodes.Any(item => item.Tone == UiTone.Warning), "tones survive the round trip");
            Check(ui.Snapshot()[0].Nodes[2].Current == 2, "build callback re-evaluates live values");

            // Row cap keeps a runaway mod from overflowing the shared block.
            var capped = ui.RegisterSurface("smoke.capped", "Capped", "");
            capped.Clear();
            for (int i = 0; i < UiRegistry.MaxNodesPerSurface + 12; i++) capped.Text("row " + i);
            capped.Publish();
            Check(capped.Revision == 1, "manual publish bumps the revision");
            var cappedSnapshot = ui.Snapshot().First(item => item.Id == "smoke.capped");
            Check(cappedSnapshot.Nodes.Count == UiRegistry.MaxNodesPerSurface, "row cap enforced");

            // Buttons dispatch by action id and reject stale clicks.
            string invoked = null;
            growth.ActionRequested += action => invoked = action;
            var live = growthSnapshot(ui);
            Check(ui.TryInvokeAction(live, 4, live.Revision), "button action accepted");
            Check(invoked == "open-choice", "action id delivered");
            Check(!ui.TryInvokeAction(live, 1, live.Revision), "non-button row rejected");
            Check(!ui.TryInvokeAction(live, 4, live.Revision + 5), "stale revision rejected");

            // Visibility is a request the host answers; the mod mirrors the result.
            growth.Open();
            var opened = growthSnapshot(ui);
            Check(opened.WantsOpen && !opened.IsOpen, "open is a request until the host confirms");
            Check(opened.WantRevision == 1, "request revision starts at one");
            ui.ApplyHostState(opened, 1, true);
            Check(growth.IsOpen, "host confirmation reaches the mod");
            growth.Open();
            Check(growthSnapshot(ui).WantRevision == 1, "repeating open is not a new request");
            growth.Close();
            Check(growthSnapshot(ui).WantRevision == 2, "close is a new request");
            ui.ApplyHostState(growthSnapshot(ui), 2, false);
            Check(!growth.IsOpenRequested, "host close is mirrored without a new request");

            // The prompt key routes to the owning screen.
            ui.SetChoiceOwner(growth.Id);
            Check(ui.ChoiceOwnerIndex() == 0, "choice owner index resolves");
            Check(ui.ChoiceRequest == 0, "choice request starts clean");
            ui.RequestChoicePrompt();
            Check(ui.ChoiceRequest == 1, "choice request counts up");

            bool duplicateRejected = false;
            try { ui.RegisterSurface("smoke.growth", "Again", ""); } catch (InvalidOperationException) { duplicateRejected = true; }
            Check(duplicateRejected, "duplicate screen id rejected");
            bool shortRejected = false;
            try { growth.SetShortcut(115, 2); } catch (ArgumentException) { shortRejected = true; }
            Check(shortRejected && growth.ShortcutKey == 113, "reserved Alt+F4 shortcut rejected");
            bool clashRejected = false;
            try { growth.SetShortcut(inventory.ShortcutKey, 0); } catch (ArgumentException) { clashRejected = true; }
            Check(clashRejected, "duplicate shortcut across screens rejected");

            // Shortcuts persist between sessions.
            growth.SetShortcut(118, 4);
            ui = UiRegistry.Initialize(Path.GetTempPath());
            var reloaded = ui.RegisterSurface("smoke.growth", "Growth", "subtitle");
            Check(reloaded.ShortcutKey == 118 && reloaded.ShortcutModifiers == 4, "shortcut persisted");
            var keyless = ui.RegisterSurface("smoke.keyless", "Keyless", "");
            keyless.SetShortcut(0, 0);
            ui = UiRegistry.Initialize(Path.GetTempPath());
            var keylessAgain = ui.RegisterSurface("smoke.keyless", "Keyless", "");
            Check(keylessAgain.ShortcutKey == 0, "screen without a key stays keyless");
            Check(File.Exists(config) && File.ReadAllText(config).Contains("shortcut.smoke.growth.key=118"), "shortcut file written");

            // Unregistering releases the id, its key, and the prompt ownership.
            ui.SetChoiceOwner(keylessAgain.Id);
            ui.UnregisterSurface(keylessAgain.Id);
            Check(ui.ChoiceOwnerIndex() == -1, "unregister clears prompt ownership");
            Check(ui.Snapshot().Count == 0, "unregister removes the screen");

            Console.WriteLine("PASS: UI framework registration, shortcut assignment and persistence, row limits, live build callbacks, action dispatch, and host visibility handshake.");
            return 0;
        }
        catch (Exception error)
        {
            Console.Error.WriteLine("FAIL: " + error);
            failures = 1;
            return 1;
        }
        finally
        {
            if (failures == 0)
            {
                if (File.Exists(config)) File.Delete(config);
            }
            Environment.SetEnvironmentVariable("SOD2SE_UI_CONFIG", null);
        }
    }

    static UiSurfaceSnapshot growthSnapshot(UiRegistry ui)
    {
        return ui.Snapshot().First(item => item.Id == "smoke.growth");
    }
}
