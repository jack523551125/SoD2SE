using System;
using System.IO;
using System.Linq;
using System.Numerics;
using SoD2SE;
using SoD2SE.Roguelite;

static class RogueliteSmoke
{
    static void Check(bool value, string message) { if (!value) throw new Exception(message); }

    static int Main()
    {
        string path = Path.Combine(Path.GetTempPath(), "sod2-roguelite-" + Guid.NewGuid().ToString("N") + ".dat");
        string uiPath = Path.Combine(Path.GetTempPath(), "sod2-roguelite-ui-" + Guid.NewGuid().ToString("N") + ".ini");
        try
        {
            Environment.SetEnvironmentVariable("SOD2SE_UI_CONFIG", uiPath);
            var settings = new RogueliteSettings();
            var store = new RogueliteProgressStore(path);
            var engine = new RogueliteEngine(settings, store, 17);
            Check(engine.XpForNextLevel(BigInteger.One) == 100, "level one curve");
            Check(engine.XpForNextLevel(new BigInteger(1000000)) > new BigInteger(1000000000000), "unbounded curve");

            Check(engine.AwardForIdentity("survivor-A", 99) == 0, "pre-level XP");
            Check(engine.AwardForIdentity("survivor-A", 1) == 1, "level-up at exact threshold");
            var first = engine.OpenChoice("survivor-A", McmLanguage.Chinese, "Alice");
            Check(first.Visible && first.Cards.Count == 3 && first.Nonce != 0, "three choices");
            Check(first.Character == "Alice" && first.Experience == "0" && first.NextLevelExperience == "145", "choice survivor and XP summary");
            var ids = String.Join(",", first.Cards.Select(item => item.Id).ToArray());
            bool selected = false;
            McmChoiceBus.SelectionRequested += delegate(McmChoiceSelection selection)
            {
                selected = selection.Nonce == first.Nonce && selection.Index == 1;
                if (selected) McmChoiceBus.Clear(selection.Nonce);
            };
            McmChoiceBus.Publish(first);
            Check(!McmChoiceBus.TrySelect(first.Nonce, 2), "uncommitted choice rejected");
            Check(McmChoiceBus.TrySelect(first.Nonce, 1) && selected, "choice bus nonce and index");

            var restored = new RogueliteEngine(settings, new RogueliteProgressStore(path), 999);
            var afterReload = restored.OpenChoice("survivor-A", McmLanguage.English);
            Check(afterReload.Nonce == first.Nonce, "choice nonce persistence");
            Check(String.Join(",", afterReload.Cards.Select(item => item.Id).ToArray()) == ids, "choice candidates persist");
            Check(restored.ApplyChoice("survivor-A", afterReload.Nonce, 0, McmLanguage.English), "choice commit");
            Check(!restored.ApplyChoice("survivor-A", afterReload.Nonce, 0, McmLanguage.English), "duplicate choice rejected");
            Check(restored.Stats("survivor-A").MaxHealth(100) >= 100, "stats provider");

            var duplicate = new SurvivorKillEvent(55, new GameObjectToken(7, 1, "survivor"),
                new GameObjectToken(9, 1, "zombie"), "survivor-A", SurvivorKillCategory.Feral, false, true, 1);
            Check(restored.Award(duplicate) == 0, "kill below threshold");
            Check(restored.Award(duplicate) == 0, "duplicate kill ignored");
            var invalid = new SurvivorKillEvent(56, duplicate.Killer, duplicate.Victim, SurvivorKillCategory.Unknown, false, true, 1);
            Check(restored.Award(invalid) == 0, "unknown kill ignored");

            var data = File.ReadAllText(path);
            Check(data.Contains("SoD2SE-Roguelite/1") && data.Contains("counts|"), "atomic save format");

            // Loose XP must survive a reload once the buffered write is flushed.
            restored.AwardForIdentity("survivor-B", 50);
            restored.Flush();
            var reloaded = new RogueliteEngine(settings, new RogueliteProgressStore(path), 5);
            var carried = reloaded.Progress("survivor-B");
            Check(carried != null && carried.Experience == new BigInteger(50), "loose XP flushed and reloaded");

            // The plague bonus must saturate instead of throwing on a huge base value.
            var overflowSettings = new RogueliteSettings { FeralXp = Int32.MaxValue };
            Check(overflowSettings.XpFor(SurvivorKillCategory.Feral, true) == Int32.MaxValue, "plague bonus saturates");

            // Candidate caps follow the configured percentage.
            var capSettings = new RogueliteSettings { MeleeSpeedPercent = 10, SneakSpeedPercent = 5, StaminaRegenPercent = 5 };
            Check(capSettings.MaximumSelections(RogueliteBuff.MeleeAttackSpeed) == 10, "melee cap follows percentage");
            Check(capSettings.MaximumSelections(RogueliteBuff.SneakMovementSpeed) == 20, "sneak cap follows percentage");
            Check(capSettings.MaximumSelections(RogueliteBuff.StaminaRegeneration) == 40, "regen cap follows percentage");
            Check(capSettings.MaximumSelections(RogueliteBuff.MaxHealth) == Int32.MaxValue, "health is uncapped");

            // Diminishing reductions stay above zero even after absurd pick counts.
            var heavy = reloaded.Progress("survivor-A");
            heavy.SetCount(RogueliteBuff.PlagueResistance, 1000000);
            Check(reloaded.Stats("survivor-A").PlagueGainMultiplier > 0f, "diminishing stays positive");

            // The growth screen is a declarative surface the framework renders.
            var ui = UiRegistry.Initialize(Path.GetTempPath());
            var surface = ui.RegisterSurface("survivor-roguelite.growth", "幸存者成长", "progress");
            surface.SetShortcut(0, 0);
            surface.Clear();
            // The choice button only exists while a level is waiting to be claimed.
            reloaded.AwardForIdentity("survivor-A", 200);
            reloaded.BuildGrowthSurface(surface, "survivor-A", McmLanguage.Chinese, "Alice", "已启用。", "");
            surface.Publish();
            var published = ui.Snapshot();
            Check(published.Count == 1, "growth surface published");
            var growth = published[0];
            Check(growth.ShortcutKey == 0 && growth.ShortcutModifiers == 0, "growth surface has no key of its own");
            Check(growth.NodeStart == 0 && growth.NodeCount == growth.Nodes.Count, "node indices are contiguous");
            Check(growth.Nodes.Any(item => item.Kind == UiNodeKind.KeyValue && item.Label == "角色" && item.Value == "Alice"), "growth screen shows the survivor");
            Check(growth.Nodes.Any(item => item.Kind == UiNodeKind.Progress), "growth screen shows experience progress");
            Check(growth.Nodes.Count(item => item.Kind == UiNodeKind.KeyValue && item.Value.Contains("已选")) == 8, "growth screen lists every upgrade");
            Check(growth.Nodes.Any(item => item.Kind == UiNodeKind.Button && item.Action == "open-choice"), "growth screen offers the choice action");
            Check(growth.Nodes.Any(item => item.Tone == UiTone.Warning || item.Description != null), "growth rows keep their descriptions");

            Console.WriteLine("PASS: roguelite XP curve, buffered persistence, persistent cards, nonce-safe choice, deduplication, caps, saturation, diminishing floor, and declarative growth screen.");
            return 0;
        }
        catch (Exception error)
        {
            Console.Error.WriteLine("FAIL: " + error);
            return 1;
        }
        finally
        {
            if (File.Exists(path)) File.Delete(path);
            if (File.Exists(path + ".bak")) File.Delete(path + ".bak");
            if (File.Exists(uiPath)) File.Delete(uiPath);
            Environment.SetEnvironmentVariable("SOD2SE_UI_CONFIG", null);
        }
    }
}
