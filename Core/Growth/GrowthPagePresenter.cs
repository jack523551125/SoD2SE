using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;

namespace SoD2SE
{
    // Original character movie's numeric RPC vocabulary. Big integers and IDs
    // remain strings; AVM2 numbers are never used as survivor/reward identities.
    public enum GrowthPageOp { Begin, Count, Header, Title, Description, Kind, Selected, Choose, Confirm, Status, Close, Group, Busy }
    public enum GrowthPageRowKind { Information, Choice, Confirm, Equipment, Profession, Heading, Navigation }
    public sealed class GrowthPageRow
    {
        public GrowthPageRowKind Kind { get; internal set; }
        public string Title { get; internal set; }
        public string Description { get; internal set; }
        internal string Group, Ability;
        internal int Slot;
    }
    public sealed class GrowthPageReply
    {
        public bool IsText { get; private set; }
        public int Number { get; private set; }
        public string Text { get; private set; }
        public static GrowthPageReply Numeric(int n) { return new GrowthPageReply { Number = n }; }
        public static GrowthPageReply String(string s) { return new GrowthPageReply { IsText = true, Text = s ?? "" }; }
    }
    public sealed class GrowthPagePresenter
    {
        readonly object sync = new object();
        readonly List<GrowthPageRow> rows = new List<GrowthPageRow>();
        readonly Dictionary<string, string> selections = new Dictionary<string, string>(StringComparer.Ordinal);
        readonly Queue<GrowthCommand> commands = new Queue<GrowthCommand>();
        string identity = "", revision = "", layout = "", rewardLayout = "", header = "", status = "";
        string selectFirst = "", saving = "";
        int generation;
        bool submitting, closed;

        static string Pick(McmLanguage language, string zh, string en) { return language == McmLanguage.Chinese ? zh : en; }
        static string Safe(string value) { return value ?? ""; }
        static string Markup(string value)
        {
            return Safe(value).Replace("&", "&amp;").Replace("<", "&lt;").Replace(">", "&gt;").Replace("\"", "&quot;");
        }
        static string Seconds(long milliseconds) { return (Math.Max(0, milliseconds) / 1000.0).ToString("0.#", CultureInfo.InvariantCulture); }
        void Add(GrowthPageRowKind kind, string title, string description, string group, string ability, int slot)
        {
            rows.Add(new GrowthPageRow { Kind = kind, Title = Safe(title), Description = Markup(description), Group = group, Ability = ability, Slot = slot });
        }
        void Heading(string text) { Add(GrowthPageRowKind.Heading, text, "", "", "", 0); }
        // Copy only semantic fields. Caller mutation or frame-by-frame cooldown
        // updates cannot change a command's meaning after it has been displayed.
        public void Publish(GrowthPageSnapshot page, McmLanguage language)
        {
            if (page == null || page.Version != GrowthRuntimeContract.Version || String.IsNullOrEmpty(page.Identity))
                throw new ArgumentException("Invalid growth page snapshot.");
            if (page.Sections == null || page.Sections.Any(s => s == null || String.IsNullOrEmpty(s.Id) || s.Cards == null ||
                    s.Cards.Count == 0 || s.Cards.Any(c => c == null || String.IsNullOrEmpty(c.Id))) ||
                page.Sections.Select(s => s.Id).Distinct(StringComparer.Ordinal).Count() != page.Sections.Count ||
                page.Sections.Any(s => s.Cards.Select(c => c.Id).Distinct(StringComparer.Ordinal).Count() != s.Cards.Count))
                throw new ArgumentException("Invalid growth reward sections.");
            if (new[] { page.Attributes, page.Techniques, page.SuperTraits, page.ProfessionChoices, page.RewardRecords }.Any(list => list == null ||
                    list.Any(card => card == null || String.IsNullOrEmpty(card.Id))) || page.Slots == null || page.Slots.Any(slot => slot == null))
                throw new ArgumentException("Invalid growth page library.");
            if (page.RewardRecords.Count > GrowthRuntimeContract.RewardPageSize ||
                page.RewardRecords.Select(r => r.Id).Distinct(StringComparer.Ordinal).Count() != page.RewardRecords.Count)
                throw new ArgumentException("Invalid growth reward window.");
            lock (sync) {
                var previous = rows.ToArray(); rows.Clear();
                header = Safe(page.Character) + "  " + Pick(language, "等级 ", "Level ") + Safe(page.Level) + "\n" +
                    Pick(language, "经验 ", "XP ") + Safe(page.Experience) + " / " + Safe(page.NextExperience) + "  " +
                    Pick(language, "待领取 ", "Pending ") + Safe(page.PendingLevels);
                selectFirst = Pick(language, "请在每个奖励分区选择一项，再确认本级奖励。", "Choose one card in each reward section, then confirm this level.");
                saving = Pick(language, "正在保存……", "Saving...");
                foreach (var section in page.Sections) {
                    Heading(Pick(language, "等级 ", "Level ") + page.RewardLevel + " · " + section.Title);
                    foreach (var card in section.Cards) Add(GrowthPageRowKind.Choice, card.Title, card.Description, section.Id, card.Id, 0);
                }
                if (page.Sections.Count > 0) Add(GrowthPageRowKind.Confirm, Pick(language, "确认本级奖励", "Confirm this level"),
                    Pick(language, "一次保存本级所有选择；下一等级继续在本页领取。", "Save all choices for this level together. Claim the next level on this page."), "", "", 0);
                if (page.RewardRecords.Count > 0) {
                    Heading(Pick(language, "待领取等级记录", "Pending level records"));
                    if (!String.IsNullOrEmpty(page.PreviousRewardPage)) Add(GrowthPageRowKind.Navigation,
                        Pick(language, "查看前一组等级", "Previous levels"), "", "", page.PreviousRewardPage, 0);
                    foreach (var record in page.RewardRecords) Add(GrowthPageRowKind.Information, record.Title, record.Description, "", "", 0);
                    if (!String.IsNullOrEmpty(page.NextRewardPage)) Add(GrowthPageRowKind.Navigation,
                        Pick(language, "查看后一组等级", "Next levels"),
                        Pick(language, "按等级顺序领取。后续候选在轮到该等级时生成并保存。", "Claim in level order. Later cards are generated and saved when their level becomes current."), "", page.NextRewardPage, 0);
                }
                Heading(Pick(language, "属性", "Attributes"));
                foreach (var card in page.Attributes) Add(GrowthPageRowKind.Information, card.Title, card.Description, "", "", 0);
                Heading(Pick(language, "战斗技巧", "Combat techniques"));
                foreach (var card in page.Techniques) Add(GrowthPageRowKind.Information, card.Title, card.Description, "", "", 0);
                Heading(Pick(language, "超级特性", "Super traits"));
                foreach (var card in page.SuperTraits) Add(GrowthPageRowKind.Information, card.Title, card.Description, "", "", 0);
                Heading(Pick(language, "职业知识", "Profession knowledge"));
                foreach (var card in page.ProfessionChoices) Add(GrowthPageRowKind.Profession, card.Title, card.Description, "", card.Id, 0);
                for (int i = 0; i < page.Slots.Count; ++i) {
                    var slot = page.Slots[i];
                    Heading(Pick(language, "主动槽位 ", "Active slot ") + (i + 1));
                    Add(GrowthPageRowKind.Information, slot.Name,
                        Pick(language, "冷却 ", "Cooldown ") + Seconds(slot.CooldownMilliseconds) + "s / " +
                        Pick(language, "持续 ", "Active ") + Seconds(slot.ActiveMilliseconds) + "s\n" +
                        Safe(slot.KeyboardBinding == null ? "" : slot.KeyboardBinding.Describe(language)) + " / " +
                        Safe(slot.GamepadBinding == null ? "" : slot.GamepadBinding.Describe(language)), "", "", i);
                    Add(GrowthPageRowKind.Equipment, Pick(language, "卸下", "Unequip"), "", "", "", i);
                    foreach (var card in page.SuperTraits.Where(c => c.Active)) Add(GrowthPageRowKind.Equipment, card.Title, card.Description, "", card.Id, i);
                }
                // Length prefixes prevent ambiguities in translated strings, IDs,
                // or player-supplied names. Dynamic cooldown text is excluded.
                string nextLayout = String.Join("", rows.Select(r => r.Kind + ":" + r.Slot + ":" +
                    r.Group.Length + ":" + r.Group + r.Ability.Length + ":" + r.Ability + r.Title.Length + ":" + r.Title));
                bool changed = identity != page.Identity || revision != Safe(page.Revision) || nextLayout != layout;
                string nextRewards = String.Join("", rows.Where(r => r.Kind == GrowthPageRowKind.Choice).Select(r =>
                    r.Group.Length + ":" + r.Group + r.Ability.Length + ":" + r.Ability));
                if (changed) {
                    if (generation == Int32.MaxValue) throw new InvalidOperationException("Growth UI generation exhausted; reopen the session.");
                    ++generation;
                    if (identity != page.Identity || revision != Safe(page.Revision) || nextRewards != rewardLayout) selections.Clear();
                    submitting = false; commands.Clear();
                } else if (rows.Count != previous.Length) throw new InvalidOperationException("Growth UI layout changed without a new generation.");
                identity = page.Identity; revision = Safe(page.Revision); layout = nextLayout; rewardLayout = nextRewards;
                status = Safe(page.Status); closed = false;
            }
        }
        public GrowthPageReply Query(GrowthPageOp operation, int token, int index, int value)
        {
            lock (sync) {
                if (operation == GrowthPageOp.Begin) return GrowthPageReply.Numeric(closed || identity.Length == 0 ? 0 : generation);
                if (closed || generation == 0 || token != generation) return GrowthPageReply.Numeric(-2);
                if (operation == GrowthPageOp.Count) return GrowthPageReply.Numeric(rows.Count);
                if (operation == GrowthPageOp.Header) return GrowthPageReply.String(header);
                if (operation == GrowthPageOp.Status) return GrowthPageReply.String(submitting ? saving : status);
                if (operation == GrowthPageOp.Busy) return GrowthPageReply.Numeric(submitting ? 1 : 0);
                if (operation == GrowthPageOp.Close) {
                    commands.Enqueue(new GrowthCommand { Kind = GrowthCommandKind.Close, Identity = identity, Revision = revision });
                    closed = true; return GrowthPageReply.Numeric(1);
                }
                if (index < 0 || index >= rows.Count) return GrowthPageReply.Numeric(-3);
                var row = rows[index];
                switch (operation) {
                    case GrowthPageOp.Title: return GrowthPageReply.String(row.Title);
                    case GrowthPageOp.Description: return GrowthPageReply.String(row.Description);
                    case GrowthPageOp.Kind: return GrowthPageReply.Numeric((int)row.Kind);
                    case GrowthPageOp.Group: return GrowthPageReply.Numeric(row.Kind != GrowthPageRowKind.Choice ? -1 :
                        rows.Where(r => r.Kind == GrowthPageRowKind.Choice).Select(r => r.Group).Distinct().ToList().IndexOf(row.Group));
                    case GrowthPageOp.Selected:
                        string selected; return GrowthPageReply.Numeric(row.Kind == GrowthPageRowKind.Choice && selections.TryGetValue(row.Group, out selected) && selected == row.Ability ? 1 : 0);
                    case GrowthPageOp.Choose:
                        if (submitting || row.Kind != GrowthPageRowKind.Choice) return GrowthPageReply.Numeric(-3);
                        selections[row.Group] = row.Ability; return GrowthPageReply.Numeric(1);
                    case GrowthPageOp.Confirm:
                        if (submitting) return GrowthPageReply.Numeric(0);
                        GrowthCommand command;
                        if (row.Kind == GrowthPageRowKind.Confirm) {
                            var groups = rows.Where(r => r.Kind == GrowthPageRowKind.Choice).Select(r => r.Group).Distinct().ToArray();
                            if (groups.Any(g => !selections.ContainsKey(g))) { status = selectFirst; return GrowthPageReply.Numeric(-3); }
                            command = new GrowthCommand { Kind = GrowthCommandKind.ClaimRow, Selections = new Dictionary<string, string>(selections, StringComparer.Ordinal) };
                        } else if (row.Kind == GrowthPageRowKind.Equipment) command = new GrowthCommand { Kind = GrowthCommandKind.Equip, Slot = row.Slot, Ability = row.Ability };
                        else if (row.Kind == GrowthPageRowKind.Profession) command = new GrowthCommand { Kind = GrowthCommandKind.Profession, Ability = row.Ability };
                        else if (row.Kind == GrowthPageRowKind.Navigation) command = new GrowthCommand { Kind = GrowthCommandKind.RewardPage, RewardPageStart = row.Ability };
                        else return GrowthPageReply.Numeric(-3);
                        command.Identity = identity; command.Revision = revision;
                        commands.Enqueue(command); submitting = true; return GrowthPageReply.Numeric(1);
                    default: return GrowthPageReply.Numeric(-3);
                }
            }
        }
        // Runtime adapter drains on the game thread, executes the transaction,
        // then acknowledges. A failed disk save keeps every choice for retry.
        public GrowthCommand TakeCommand()
        {
            lock (sync) { return commands.Count == 0 ? null : commands.Dequeue(); }
        }
        public void Acknowledge(string commandIdentity, string commandRevision, string message)
        {
            lock (sync) {
                if (identity != commandIdentity || revision != Safe(commandRevision)) return;
                submitting = false; status = Safe(message);
            }
        }
        public void Suspend()
        {
            lock (sync) { closed = true; commands.Clear(); selections.Clear(); submitting = false; }
        }
    }
}
