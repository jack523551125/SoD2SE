using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Numerics;
using System.Text;
using System.Threading;
using SoD2SE;
using SoD2SE.GameApi;

namespace SoD2SE.Roguelite
{
    public enum RogueliteBuff
    {
        MaxHealth,
        MaxStamina,
        MeleeAttackSpeed,
        PlagueResistance,
        SneakMovementSpeed,
        StaminaRegeneration,
        MeleeStaminaCost,
        SprintStaminaCost
    }

    public sealed class RogueliteSettings
    {
        public bool Enabled = true;
        public bool Notifications = true;
        public int OrdinaryXp = 10;
        public int PlagueXp = 15;
        public int ScreamerXp = 30;
        public int BloaterXp = 30;
        public int FeralXp = 80;
        public int JuggernautXp = 200;
        public int HealthPerPick = 10;
        public int StaminaPerPick = 10;
        public int MeleeSpeedPercent = 5;
        public int PlagueResistancePercent = 5;
        public int SneakSpeedPercent = 5;
        public int StaminaRegenPercent = 5;
        public int MeleeCostReductionPercent = 5;
        public int SprintCostReductionPercent = 5;

        public RogueliteSettings Clone()
        {
            return (RogueliteSettings)MemberwiseClone();
        }

        public int XpFor(SurvivorKillCategory category, bool plague)
        {
            int value;
            switch (category)
            {
                case SurvivorKillCategory.Screamer: value = ScreamerXp; break;
                case SurvivorKillCategory.Bloater: value = BloaterXp; break;
                case SurvivorKillCategory.Feral: value = FeralXp; break;
                case SurvivorKillCategory.Juggernaut: value = JuggernautXp; break;
                case SurvivorKillCategory.Plague: value = PlagueXp; break;
                case SurvivorKillCategory.Ordinary: value = OrdinaryXp; break;
                default: return 0;
            }
            if (plague && category != SurvivorKillCategory.Plague &&
                category != SurvivorKillCategory.Ordinary)
            {
                long scaled = ((long)value * 3L + 1L) / 2L;
                value = scaled > Int32.MaxValue ? Int32.MaxValue : (int)scaled;
            }
            return Math.Max(0, value);
        }

        public int ValueFor(RogueliteBuff buff)
        {
            switch (buff)
            {
                case RogueliteBuff.MaxHealth: return Math.Max(0, HealthPerPick);
                case RogueliteBuff.MaxStamina: return Math.Max(0, StaminaPerPick);
                case RogueliteBuff.MeleeAttackSpeed: return Math.Max(0, MeleeSpeedPercent);
                case RogueliteBuff.PlagueResistance: return Math.Max(0, PlagueResistancePercent);
                case RogueliteBuff.SneakMovementSpeed: return Math.Max(0, SneakSpeedPercent);
                case RogueliteBuff.StaminaRegeneration: return Math.Max(0, StaminaRegenPercent);
                case RogueliteBuff.MeleeStaminaCost: return Math.Max(0, MeleeCostReductionPercent);
                case RogueliteBuff.SprintStaminaCost: return Math.Max(0, SprintCostReductionPercent);
                default: return 0;
            }
        }

        public int MaximumSelections(RogueliteBuff buff)
        {
            int percent = ValueFor(buff);
            if (percent <= 0) return 0;
            switch (buff)
            {
                case RogueliteBuff.MeleeAttackSpeed:
                case RogueliteBuff.SneakMovementSpeed: return CountForCap(percent, 2.0);
                case RogueliteBuff.StaminaRegeneration: return CountForCap(percent, 3.0);
                default: return Int32.MaxValue;
            }
        }

        // Derive the pick count that reaches a multiplier cap from the
        // configured per-pick percentage so changing the percentage does not
        // silently break the cap.
        static int CountForCap(int percent, double cap)
        {
            double needed = (cap - 1.0) * 100.0 / percent;
            if (needed >= Int32.MaxValue) return Int32.MaxValue;
            return Math.Max(1, (int)Math.Ceiling(needed));
        }
    }

    public sealed class RogueliteProgress
    {
        public string Identity { get; private set; }
        public BigInteger Level { get; set; }
        public BigInteger Experience { get; set; }
        public int PendingLevels { get; set; }
        public int ChoiceNonce { get; set; }
        public RogueliteBuff[] PendingCards { get; set; }
        readonly int[] counts = new int[8];

        public RogueliteProgress(string identity)
        {
            if (String.IsNullOrWhiteSpace(identity)) throw new ArgumentException("幸存者持久 ID 不能为空。", "identity");
            Identity = identity;
            Level = BigInteger.One;
            PendingCards = new RogueliteBuff[0];
        }

        public int Count(RogueliteBuff buff) { return counts[(int)buff]; }
        public void SetCount(RogueliteBuff buff, int value) { counts[(int)buff] = Math.Max(0, value); }
        public int[] CopyCounts() { return (int[])counts.Clone(); }
        public bool HasChoice { get { return ChoiceNonce != 0 && PendingCards.Length > 0; } }
    }

    public sealed class RogueliteProgressStore
    {
        const string Header = "SoD2SE-Roguelite/1";
        readonly string path;

        public string Path { get { return path; } }
        public int Seed { get; set; }
        public bool HasSeed { get; set; }

        public RogueliteProgressStore(string pathOverride = null)
        {
            var local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            if (String.IsNullOrWhiteSpace(local)) local = AppDomain.CurrentDomain.BaseDirectory;
            var overridePath = pathOverride ?? Environment.GetEnvironmentVariable("SOD2SE_ROGUELITE_DATA");
            path = String.IsNullOrWhiteSpace(overridePath)
                ? System.IO.Path.Combine(local, FrameworkInfo.GameDataFolderName, "SoD2SE", "Roguelite", "progress.dat")
                : System.IO.Path.GetFullPath(overridePath);
        }

        public Dictionary<string, RogueliteProgress> Load()
        {
            var result = new Dictionary<string, RogueliteProgress>(StringComparer.Ordinal);
            if (!File.Exists(path)) return result;
            bool corrupted = false;
            foreach (var raw in File.ReadAllLines(path, Encoding.UTF8))
            {
                if (String.IsNullOrWhiteSpace(raw) || raw.StartsWith("#", StringComparison.Ordinal)) continue;
                if (String.Equals(raw, Header, StringComparison.Ordinal)) continue;
                if (raw.StartsWith("seed|", StringComparison.Ordinal))
                {
                    int seed;
                    if (Int32.TryParse(raw.Substring(5), NumberStyles.Integer, CultureInfo.InvariantCulture, out seed) && seed != 0)
                    { Seed = seed; HasSeed = true; }
                    continue;
                }
                try
                {
                    var fields = raw.Split('|');
                    if (fields.Length != 7 || fields[0] != "record") continue;
                    string identity = Decode(fields[1]);
                    var progress = new RogueliteProgress(identity) {
                        Level = ParseBig(fields[2]),
                        Experience = ParseBig(fields[3]),
                        PendingLevels = Math.Max(0, Int32.Parse(fields[4], CultureInfo.InvariantCulture)),
                        ChoiceNonce = Int32.Parse(fields[5], CultureInfo.InvariantCulture),
                        PendingCards = ParseCards(fields[6])
                    };
                    for (int i = 0; i < 8; i++) progress.SetCount((RogueliteBuff)i, 0);
                    result[identity] = progress;
                }
                catch (Exception error)
                {
                    corrupted = true;
                    Console.Error.WriteLine("[Roguelite] 忽略损坏的成长记录：" + error.Message);
                }
            }
            // Counts are stored in a separate, backwards-compatible line.  A
            // second pass keeps the record format easy to inspect and recover.
            foreach (var raw in File.ReadAllLines(path, Encoding.UTF8))
            {
                if (!raw.StartsWith("counts|", StringComparison.Ordinal)) continue;
                try
                {
                    var fields = raw.Split('|');
                    var identity = Decode(fields[1]);
                    RogueliteProgress progress;
                    if (!result.TryGetValue(identity, out progress) || fields.Length != 10) continue;
                    for (int i = 0; i < 8; i++) progress.SetCount((RogueliteBuff)i, Int32.Parse(fields[i + 2], CultureInfo.InvariantCulture));
                }
                catch (Exception error) { corrupted = true; Console.Error.WriteLine("[Roguelite] 忽略损坏的强化记录：" + error.Message); }
            }
            if (corrupted) BackupCorrupt();
            return result;
        }

        // Keep the broken file once so a player can still recover manual edits
        // or send it for diagnosis; never overwrite it silently.
        void BackupCorrupt()
        {
            try
            {
                if (!File.Exists(path)) return;
                var backup = path + ".corrupt-" + DateTime.UtcNow.ToString("yyyyMMddHHmmss", CultureInfo.InvariantCulture);
                if (!File.Exists(backup)) File.Copy(path, backup, false);
                Console.Error.WriteLine("[Roguelite] 损坏的成长文件已备份到：" + backup);
            }
            catch (Exception error) { Console.Error.WriteLine("[Roguelite] 备份损坏文件失败：" + error.Message); }
        }

        public void Save(IDictionary<string, RogueliteProgress> values)
        {
            if (values == null) throw new ArgumentNullException("values");
            var directory = System.IO.Path.GetDirectoryName(path);
            if (!String.IsNullOrWhiteSpace(directory)) Directory.CreateDirectory(directory);
            var temp = path + ".tmp-" + Guid.NewGuid().ToString("N");
            var backup = path + ".bak";
            var lines = new List<string> { Header, "# This file is independent of the vanilla save and is safe to back up." };
            if (HasSeed) lines.Add("seed|" + Seed.ToString(CultureInfo.InvariantCulture));
            foreach (var progress in values.Values.OrderBy(item => item.Identity, StringComparer.Ordinal))
            {
                lines.Add(String.Join("|", "record", Encode(progress.Identity), progress.Level.ToString(CultureInfo.InvariantCulture),
                    progress.Experience.ToString(CultureInfo.InvariantCulture), progress.PendingLevels.ToString(CultureInfo.InvariantCulture),
                    progress.ChoiceNonce.ToString(CultureInfo.InvariantCulture), SerializeCards(progress.PendingCards)));
                var counts = progress.CopyCounts().Select(item => item.ToString(CultureInfo.InvariantCulture)).ToArray();
                lines.Add("counts|" + Encode(progress.Identity) + "|" + String.Join("|", counts));
            }
            File.WriteAllLines(temp, lines, new UTF8Encoding(false));
            if (File.Exists(path))
            {
                try { File.Replace(temp, path, backup, true); }
                catch (PlatformNotSupportedException) { File.Copy(path, backup, true); File.Delete(path); File.Move(temp, path); }
                catch (IOException) { File.Copy(path, backup, true); File.Delete(path); File.Move(temp, path); }
            }
            else File.Move(temp, path);
        }

        static BigInteger ParseBig(string value)
        {
            var result = BigInteger.Parse(value, CultureInfo.InvariantCulture);
            if (result < 0) throw new FormatException("负数成长值。");
            return result;
        }

        static RogueliteBuff[] ParseCards(string value)
        {
            if (String.IsNullOrEmpty(value)) return new RogueliteBuff[0];
            var cards = new List<RogueliteBuff>();
            foreach (var item in value.Split(','))
            {
                if (item.Length == 0) continue;
                int parsed = Int32.Parse(item, CultureInfo.InvariantCulture);
                // A hand-edited or truncated file must not index past the
                // per-buff counters; treat it as corruption instead.
                if (parsed < 0 || parsed >= 8) throw new FormatException("未知的强化编号：" + parsed.ToString(CultureInfo.InvariantCulture));
                if (cards.Count < 3) cards.Add((RogueliteBuff)parsed);
            }
            return cards.ToArray();
        }

        static string SerializeCards(IEnumerable<RogueliteBuff> cards)
        {
            return String.Join(",", (cards ?? Enumerable.Empty<RogueliteBuff>()).Select(item => ((int)item).ToString(CultureInfo.InvariantCulture)));
        }

        static string Encode(string value) { return Convert.ToBase64String(Encoding.UTF8.GetBytes(value ?? "")); }
        static string Decode(string value) { return Encoding.UTF8.GetString(Convert.FromBase64String(value ?? "")); }
    }

    public sealed class RogueliteStats
    {
        readonly RogueliteSettings settings;
        readonly RogueliteProgress progress;
        public RogueliteStats(RogueliteSettings settings, RogueliteProgress progress) { this.settings = settings; this.progress = progress; }

        public float MaxHealth(float baseline) { return baseline + ScaledTotal(settings.HealthPerPick, progress.Count(RogueliteBuff.MaxHealth)); }
        public float MaxStamina(float baseline) { return baseline + ScaledTotal(settings.StaminaPerPick, progress.Count(RogueliteBuff.MaxStamina)); }

        // The pick count is uncapped, so the product must not wrap around.
        static float ScaledTotal(int perPick, int count)
        {
            long total = (long)Math.Max(0, perPick) * Math.Max(0, count);
            return total > Int32.MaxValue ? Int32.MaxValue : (float)total;
        }
        public float MeleeAttackMultiplier { get { return SoftUpper(1f, settings.MeleeSpeedPercent, progress.Count(RogueliteBuff.MeleeAttackSpeed), 2f); } }
        public float SneakMovementMultiplier { get { return SoftUpper(1f, settings.SneakSpeedPercent, progress.Count(RogueliteBuff.SneakMovementSpeed), 2f); } }
        public float StaminaRegenerationMultiplier { get { return SoftUpper(1f, settings.StaminaRegenPercent, progress.Count(RogueliteBuff.StaminaRegeneration), 3f); } }
        public float PlagueGainMultiplier { get { return Diminishing(settings.PlagueResistancePercent, progress.Count(RogueliteBuff.PlagueResistance)); } }
        public float MeleeStaminaCostMultiplier { get { return Diminishing(settings.MeleeCostReductionPercent, progress.Count(RogueliteBuff.MeleeStaminaCost)); } }
        public float SprintStaminaCostMultiplier { get { return Diminishing(settings.SprintCostReductionPercent, progress.Count(RogueliteBuff.SprintStaminaCost)); } }

        static float SoftUpper(float baseline, int percent, int count, float maximum)
        {
            double value = baseline + (double)Math.Max(0, percent) * Math.Max(0, count) / 100.0;
            return (float)Math.Min((double)maximum, value);
        }
        static float Diminishing(int percent, int count)
        {
            if (percent <= 0 || count <= 0) return 1f;
            var factor = 1.0 / (1.0 + (double)percent * count / 100.0);
            var result = (float)factor;
            // Never let rounding turn a reduced cost into a free action.
            return result > 0f ? result : float.Epsilon;
        }
    }

    public sealed class RogueliteEngine
    {
        const int MaxTrackedDeaths = 4096;
        const int SaveIntervalMs = 5000;
        readonly object sync = new object();
        readonly RogueliteProgressStore store;
        readonly Random random;
        readonly HashSet<string> sessionDeaths = new HashSet<string>(StringComparer.Ordinal);
        readonly Queue<string> deathOrder = new Queue<string>();
        readonly Dictionary<string, RogueliteProgress> records;
        RogueliteSettings settings;
        int nonceSeed = 1;
        bool dirty;
        bool urgentSave;
        int lastSaveTicks;

        public RogueliteEngine(RogueliteSettings settings, RogueliteProgressStore store, int randomSeed = 0)
        {
            this.settings = (settings ?? new RogueliteSettings()).Clone();
            if (store == null) throw new ArgumentNullException("store");
            this.store = store;
            records = store.Load();
            int seed = randomSeed != 0 ? randomSeed : (store.HasSeed ? store.Seed : new Random().Next(1, Int32.MaxValue));
            if (!store.HasSeed) { store.Seed = seed; store.HasSeed = true; }
            random = new Random(seed);
            lastSaveTicks = Environment.TickCount;
            foreach (var progress in records.Values) nonceSeed = Math.Max(nonceSeed, progress.ChoiceNonce);
        }

        public RogueliteSettings Settings { get { lock (sync) return settings.Clone(); } }

        public RogueliteProgress GetOrCreate(string identity)
        {
            lock (sync)
            {
                RogueliteProgress result;
                if (!records.TryGetValue(identity ?? "", out result))
                    records[identity] = result = new RogueliteProgress(identity);
                return result;
            }
        }

        public BigInteger XpForNextLevel(BigInteger level)
        {
            if (level < BigInteger.One) level = BigInteger.One;
            var n = level - BigInteger.One;
            return 100 + 40 * n + 5 * n * n;
        }

        public int Award(SurvivorKillEvent value)
        {
            if (!value.ConfirmedPlayerCommunityMember || String.IsNullOrWhiteSpace(value.KillerPersistentId) || value.EventId == 0 || value.Category == SurvivorKillCategory.Unknown) return 0;
            var key = value.EventId.ToString(CultureInfo.InvariantCulture) + ":" + value.Victim.Value.ToString(CultureInfo.InvariantCulture) + ":" + value.Victim.Generation.ToString(CultureInfo.InvariantCulture);
            lock (sync)
            {
                if (!TrackDeathLocked(key)) return 0;
                return AwardLocked(value.KillerPersistentId, settings.XpFor(value.Category, value.VictimHasPlague));
            }
        }

        public int AwardForIdentity(string identity, int xp, long eventId = 1)
        {
            if (String.IsNullOrWhiteSpace(identity) || xp <= 0) return 0;
            lock (sync) return AwardLocked(identity, xp);
        }

        int AwardLocked(string identity, int xp)
        {
            var progress = GetOrCreate(identity);
            progress.Experience += xp;
            int levels = 0;
            while (progress.Experience >= XpForNextLevel(progress.Level))
            {
                progress.Experience -= XpForNextLevel(progress.Level);
                progress.Level += BigInteger.One;
                if (progress.PendingLevels < Int32.MaxValue) progress.PendingLevels++;
                levels++;
            }
            // Never touch the disk from the kill callback: the event thread
            // can be a game hook.  Ask the pump to persist promptly instead.
            dirty = true;
            if (levels > 0) urgentSave = true;
            return levels;
        }

        // Death keys are only needed to reject duplicate callbacks for the same
        // victim; keep a bounded window instead of growing forever.
        bool TrackDeathLocked(string key)
        {
            if (!sessionDeaths.Add(key)) return false;
            deathOrder.Enqueue(key);
            while (deathOrder.Count > MaxTrackedDeaths) sessionDeaths.Remove(deathOrder.Dequeue());
            return true;
        }

        public McmChoiceState OpenChoice(string identity, McmLanguage language, string character = null)
        {
            lock (sync)
            {
                RogueliteProgress progress;
                if (!records.TryGetValue(identity ?? "", out progress) || progress.PendingLevels <= 0) return McmChoiceState.Empty;
                if (!progress.HasChoice)
                {
                    var oldNonceSeed = nonceSeed;
                    var oldNonce = progress.ChoiceNonce;
                    var oldCards = progress.PendingCards;
                    GenerateCardsLocked(progress);
                    try { SaveLocked(); }
                    catch
                    {
                        nonceSeed = oldNonceSeed;
                        progress.ChoiceNonce = oldNonce;
                        progress.PendingCards = oldCards;
                        throw;
                    }
                }
                return BuildChoiceLocked(progress, language, String.IsNullOrWhiteSpace(character) ? identity : character);
            }
        }

        public bool ApplyChoice(string identity, int nonce, int index, McmLanguage language)
        {
            lock (sync)
            {
                RogueliteProgress progress;
                if (!records.TryGetValue(identity ?? "", out progress) || !progress.HasChoice || progress.ChoiceNonce != nonce || index < 0 || index >= progress.PendingCards.Length) return false;
                var buff = progress.PendingCards[index];
                int oldCount = progress.Count(buff);
                int oldPending = progress.PendingLevels;
                int oldNonce = progress.ChoiceNonce;
                var oldCards = progress.PendingCards;
                progress.SetCount(buff, oldCount + 1);
                progress.PendingLevels = Math.Max(0, progress.PendingLevels - 1);
                progress.PendingCards = new RogueliteBuff[0];
                progress.ChoiceNonce = 0;
                try { SaveLocked(); }
                catch
                {
                    progress.SetCount(buff, oldCount);
                    progress.PendingLevels = oldPending;
                    progress.PendingCards = oldCards;
                    progress.ChoiceNonce = oldNonce;
                    throw;
                }
                return true;
            }
        }

        public RogueliteStats Stats(string identity)
        {
            lock (sync) return new RogueliteStats(settings, GetOrCreate(identity));
        }

        public void ReplaceSettings(RogueliteSettings value)
        {
            if (value == null) throw new ArgumentNullException("value");
            lock (sync) { settings = value.Clone(); FlushIfDue(); }
        }

        void GenerateCardsLocked(RogueliteProgress progress)
        {
            var candidates = Enum.GetValues(typeof(RogueliteBuff)).Cast<RogueliteBuff>()
                .Where(item => settings.MaximumSelections(item) > progress.Count(item) && settings.ValueFor(item) > 0).ToList();
            var cards = new List<RogueliteBuff>();
            while (candidates.Count > 0 && cards.Count < 3)
            {
                int index = random.Next(candidates.Count);
                cards.Add(candidates[index]); candidates.RemoveAt(index);
            }
            progress.PendingCards = cards.ToArray();
            progress.ChoiceNonce = ++nonceSeed;
        }

        McmChoiceState BuildChoiceLocked(RogueliteProgress progress, McmLanguage language, string character)
        {
            var cards = progress.PendingCards.Select(item => BuildCard(item, progress, language)).ToList();
            int level = progress.Level > Int32.MaxValue ? Int32.MaxValue : (int)progress.Level;
            return new McmChoiceState(level, progress.PendingLevels, progress.ChoiceNonce, character,
                progress.Experience.ToString(CultureInfo.InvariantCulture),
                XpForNextLevel(progress.Level).ToString(CultureInfo.InvariantCulture), cards);
        }

        McmChoiceCard BuildCard(RogueliteBuff buff, RogueliteProgress progress, McmLanguage language)
        {
            int current = progress.Count(buff), next = current + 1;
            string zh, en, descriptionZh, descriptionEn;
            switch (buff)
            {
                case RogueliteBuff.MaxHealth: zh = "最大生命值"; en = "Max Health"; descriptionZh = "+" + settings.HealthPerPick + " 最大生命值"; descriptionEn = "+" + settings.HealthPerPick + " max health"; break;
                case RogueliteBuff.MaxStamina: zh = "最大体力值"; en = "Max Stamina"; descriptionZh = "+" + settings.StaminaPerPick + " 最大体力值"; descriptionEn = "+" + settings.StaminaPerPick + " max stamina"; break;
                case RogueliteBuff.MeleeAttackSpeed: zh = "近战攻速"; en = "Melee Speed"; descriptionZh = "+" + settings.MeleeSpeedPercent + "%，最高 2 倍"; descriptionEn = "+" + settings.MeleeSpeedPercent + "%, up to 2x"; break;
                case RogueliteBuff.PlagueResistance: zh = "血疫抗性"; en = "Plague Resistance"; descriptionZh = "新增感染量递减"; descriptionEn = "Less incoming plague"; break;
                case RogueliteBuff.SneakMovementSpeed: zh = "潜行速度"; en = "Sneak Speed"; descriptionZh = "+" + settings.SneakSpeedPercent + "%，最高 2 倍"; descriptionEn = "+" + settings.SneakSpeedPercent + "%, up to 2x"; break;
                case RogueliteBuff.StaminaRegeneration: zh = "体力恢复"; en = "Stamina Regeneration"; descriptionZh = "+" + settings.StaminaRegenPercent + "%，最高 3 倍"; descriptionEn = "+" + settings.StaminaRegenPercent + "%, up to 3x"; break;
                case RogueliteBuff.MeleeStaminaCost: zh = "近战体力消耗"; en = "Melee Stamina Cost"; descriptionZh = "近战消耗递减"; descriptionEn = "Lower melee stamina cost"; break;
                default: zh = "奔跑体力消耗"; en = "Sprint Stamina Cost"; descriptionZh = "奔跑消耗递减"; descriptionEn = "Lower sprint stamina cost"; break;
            }
            string title = language == McmLanguage.Chinese ? zh : en;
            string description = (language == McmLanguage.Chinese ? descriptionZh : descriptionEn) + "  [" + current + " -> " + next + "]";
            return new McmChoiceCard(((int)buff).ToString(CultureInfo.InvariantCulture), title, description, current, next);
        }

        // Builds the in-game screen.  The UI framework calls this before every
        // publish, so the rows always show current values without a refresh path.
        public void BuildGrowthSurface(UiSurface surface, string identity, McmLanguage language, string character,
            string status, string missing)
        {
            lock (sync)
            {
                surface.Section(language == McmLanguage.Chinese ? "状态" : "Status");
                surface.Note(status);
                if (!String.IsNullOrEmpty(missing)) surface.Note(missing, UiTone.Warning);
                RogueliteProgress progress = null;
                if (!String.IsNullOrWhiteSpace(identity)) records.TryGetValue(identity, out progress);
                if (progress == null && !String.IsNullOrWhiteSpace(identity))
                {
                    progress = new RogueliteProgress(identity);
                    records.Add(identity, progress);
                    dirty = true;
                }
                if (progress == null)
                {
                    surface.Section(language == McmLanguage.Chinese ? "进度" : "Progress");
                    surface.Note(language == McmLanguage.Chinese
                        ? "当前没有可用的幸存者档案；进入单人社区后这里会显示等级与强化。"
                        : "No survivor profile is active. Enter a single-player community to see level and upgrades.");
                    return;
                }
                var stats = new RogueliteStats(settings, progress);
                int level = progress.Level > Int32.MaxValue ? Int32.MaxValue : (int)progress.Level;
                string who = String.IsNullOrWhiteSpace(character) ? (identity ?? "") : character;
                surface.Section(language == McmLanguage.Chinese ? "进度" : "Progress");
                surface.KeyValue(language == McmLanguage.Chinese ? "角色" : "Survivor", who);
                surface.KeyValue(language == McmLanguage.Chinese ? "等级" : "Level",
                    level.ToString(CultureInfo.InvariantCulture), null, UiTone.Accent);
                var experience = progress.Experience.ToString(CultureInfo.InvariantCulture);
                var next = XpForNextLevel(progress.Level).ToString(CultureInfo.InvariantCulture);
                surface.Progress(language == McmLanguage.Chinese ? "经验" : "Experience",
                    ToDisplayInt(progress.Experience), ToDisplayInt(XpForNextLevel(progress.Level)),
                    experience + " / " + next);
                surface.KeyValue(language == McmLanguage.Chinese ? "待领取升级" : "Pending upgrades",
                    progress.PendingLevels.ToString(CultureInfo.InvariantCulture), null,
                    progress.PendingLevels > 0 ? UiTone.Accent : UiTone.Normal);
                surface.Section(language == McmLanguage.Chinese ? "已获得强化" : "Owned upgrades");
                foreach (RogueliteBuff buff in Enum.GetValues(typeof(RogueliteBuff)))
                {
                    int count = progress.Count(buff);
                    // One line per upgrade keeps all eight visible without
                    // scrolling; the pick count rides along with the value.
                    surface.KeyValue(Name(buff, language),
                        Effect(buff, progress, stats, language) +
                        (language == McmLanguage.Chinese ? "，已选 " : ", picked ") + count +
                        (language == McmLanguage.Chinese ? " 次" : "x"),
                        null, count > 0 ? UiTone.Positive : UiTone.Muted);
                }
                if (progress.PendingLevels > 0)
                    surface.Button(language == McmLanguage.Chinese ? "查看升级选择" : "Open upgrade choice", "open-choice",
                        language == McmLanguage.Chinese ? "或按提示快捷键重新显示选择界面。" : "Or press the prompt key to bring the choice back.");
            }
        }

        // The progress bar is integer-only over the wire; keep it meaningful for
        // very large values without overflowing.
        static int ToDisplayInt(System.Numerics.BigInteger value)
        {
            if (value <= System.Numerics.BigInteger.Zero) return 0;
            return value > Int32.MaxValue ? Int32.MaxValue : (int)value;
        }

        static string Name(RogueliteBuff buff, McmLanguage language)
        {
            switch (buff)
            {
                case RogueliteBuff.MaxHealth: return language == McmLanguage.Chinese ? "最大生命值" : "Max health";
                case RogueliteBuff.MaxStamina: return language == McmLanguage.Chinese ? "最大体力值" : "Max stamina";
                case RogueliteBuff.MeleeAttackSpeed: return language == McmLanguage.Chinese ? "近战攻速" : "Melee speed";
                case RogueliteBuff.PlagueResistance: return language == McmLanguage.Chinese ? "血疫抗性" : "Plague resistance";
                case RogueliteBuff.SneakMovementSpeed: return language == McmLanguage.Chinese ? "潜行速度" : "Sneak speed";
                case RogueliteBuff.StaminaRegeneration: return language == McmLanguage.Chinese ? "体力恢复" : "Stamina regeneration";
                case RogueliteBuff.MeleeStaminaCost: return language == McmLanguage.Chinese ? "近战体力消耗" : "Melee stamina cost";
                default: return language == McmLanguage.Chinese ? "奔跑体力消耗" : "Sprint stamina cost";
            }
        }

        string Effect(RogueliteBuff buff, RogueliteProgress progress, RogueliteStats stats, McmLanguage language)
        {
            int count = progress.Count(buff);
            switch (buff)
            {
                case RogueliteBuff.MaxHealth: return "+" + ((long)settings.HealthPerPick * count) + (language == McmLanguage.Chinese ? " 生命" : " health");
                case RogueliteBuff.MaxStamina: return "+" + ((long)settings.StaminaPerPick * count) + (language == McmLanguage.Chinese ? " 体力" : " stamina");
                case RogueliteBuff.MeleeAttackSpeed: return "x" + stats.MeleeAttackMultiplier.ToString("0.00", CultureInfo.InvariantCulture);
                case RogueliteBuff.SneakMovementSpeed: return "x" + stats.SneakMovementMultiplier.ToString("0.00", CultureInfo.InvariantCulture);
                case RogueliteBuff.StaminaRegeneration: return "x" + stats.StaminaRegenerationMultiplier.ToString("0.00", CultureInfo.InvariantCulture);
                case RogueliteBuff.PlagueResistance: return "x" + stats.PlagueGainMultiplier.ToString("0.000", CultureInfo.InvariantCulture) + (language == McmLanguage.Chinese ? " 感染量" : " plague gain");
                case RogueliteBuff.MeleeStaminaCost: return "x" + stats.MeleeStaminaCostMultiplier.ToString("0.000", CultureInfo.InvariantCulture) + (language == McmLanguage.Chinese ? " 近战消耗" : " melee cost");
                default: return "x" + stats.SprintStaminaCostMultiplier.ToString("0.000", CultureInfo.InvariantCulture) + (language == McmLanguage.Chinese ? " 奔跑消耗" : " sprint cost");
            }
        }

        void SaveLocked() { store.Save(records); dirty = false; urgentSave = false; lastSaveTicks = Environment.TickCount; }

        void FlushIfDue()
        {
            if (!dirty) return;
            if (!urgentSave && unchecked(Environment.TickCount - lastSaveTicks) < SaveIntervalMs) return;
            SaveLocked();
        }

        // Called by the plugin loop so loose XP survives a crash without
        // rewriting the whole file on every kill.
        public void Tick() { lock (sync) FlushIfDue(); }
        public void Flush() { lock (sync) { if (dirty) SaveLocked(); } }
        public RogueliteProgress Progress(string identity)
        {
            lock (sync)
            {
                RogueliteProgress value;
                return records.TryGetValue(identity ?? "", out value) ? value : null;
            }
        }
    }

    public sealed class Plugin : ISoD2Plugin, IMcmConfigurable, IPluginRuntimeStatus
    {
        // The MCM page and the runtime settings must agree on the defaults, so
        // the page reads them from one instance instead of repeating the
        // numbers; verify_sources.py rejects literals at the AddXp/AddInt
        // call sites.  The instance is never mutated.
        static readonly RogueliteSettings DefaultSettings = new RogueliteSettings();
        const int MaxPerPick = 1000, MaxPercentPerPick = 100, MaxXpPerKill = 1000000;
        const int KillQueueCapacity = 4096, KillDrainBatch = 64;

        readonly object sync = new object();
        readonly Queue<SurvivorKillEvent> killQueue = new Queue<SurvivorKillEvent>();
        IGameSession session;
        GameRuntime runtime;
        RogueliteEngine engine;
        ISurvivorKillEventSource killSource;
        ISurvivorContextSource contextSource;
        IDisposable killSubscription;
        IDisposable contextSubscription;
        IDisposable choicePause;
        IGamePauseService pause;
        Thread worker;
        ManualResetEvent stop;
        string currentIdentity;
        string currentCharacter;
        UiSurface growthSurface;
        string missingCapabilities = "";
        long droppedKillEvents;
        bool overflowNoticeWritten;
        bool settingsEnabled = true;
        bool active;
        string status = "未初始化。";

        public int ApiVersion { get { return FrameworkInfo.PluginApiVersion; } }
        public string Id { get { return "survivor-roguelite"; } }
        public string Name { get { return "幸存者成长 - Survivor Roguelite"; } }
        public string Description { get { return "幸存者成长原型；游戏能力与原版 UI 尚未验证，玩法保持停用。 / Survivor progression prototype; gameplay remains disabled until game capabilities and original UI integration are verified."; } }
        public bool IsActive { get { lock (sync) return active; } }
        public string Status { get { lock (sync) return status; } }

        public void RegisterMcm(McmRegistry registry)
        {
            var page = registry.RegisterPlugin(Id,
                new McmLocalizedText("幸存者成长", "Survivor Roguelite"),
                new McmLocalizedText(
                    "玩法目前因击杀、角色身份、属性、暂停和原版角色界面接口未验证而停用。MCM 只保存设置，不代表成长效果已生效。",
                    "Gameplay is currently disabled because kill attribution, survivor identity, attributes, pause, and original character UI integration are unverified. MCM only stores settings; it does not mean growth effects are active."));
            page.AddBool("enabled", new McmLocalizedText("启用成长系统", "Enable progression"), DefaultSettings.Enabled,
                new McmLocalizedText("需要所有首版游戏能力均已验证；能力缺失时自动停用并保留成长数据。", "All v1 game capabilities must be verified; missing capabilities disable runtime effects and preserve data."), false);
            page.AddBool("notifications", new McmLocalizedText("显示升级提示", "Show level-up notices"), DefaultSettings.Notifications,
                new McmLocalizedText("只显示待领取数量，不会自动选择强化。", "Shows pending choices without selecting an upgrade automatically."), false);
            AddXp(page, "ordinary-xp", "普通丧尸经验", "Ordinary zombie XP", DefaultSettings.OrdinaryXp);
            AddXp(page, "plague-xp", "血疫普通丧尸经验", "Plague zombie XP", DefaultSettings.PlagueXp);
            AddXp(page, "screamer-xp", "尖叫者经验", "Screamer XP", DefaultSettings.ScreamerXp);
            AddXp(page, "bloater-xp", "浮肿者经验", "Bloater XP", DefaultSettings.BloaterXp);
            AddXp(page, "feral-xp", "狂猛者经验", "Feral XP", DefaultSettings.FeralXp);
            AddXp(page, "juggernaut-xp", "巨无霸经验", "Juggernaut XP", DefaultSettings.JuggernautXp);
            AddInt(page, "health-per-pick", "每次生命值", "Health per choice", DefaultSettings.HealthPerPick, 0, MaxPerPick);
            AddInt(page, "stamina-per-pick", "每次体力值", "Stamina per choice", DefaultSettings.StaminaPerPick, 0, MaxPerPick);
            AddInt(page, "melee-speed-percent", "每次近战攻速 (%)", "Melee speed per choice (%)", DefaultSettings.MeleeSpeedPercent, 0, MaxPercentPerPick);
            AddInt(page, "plague-resistance-percent", "每次血疫抗性 (%)", "Plague resistance per choice (%)", DefaultSettings.PlagueResistancePercent, 0, MaxPercentPerPick);
            AddInt(page, "sneak-speed-percent", "每次潜行速度 (%)", "Sneak speed per choice (%)", DefaultSettings.SneakSpeedPercent, 0, MaxPercentPerPick);
            AddInt(page, "stamina-regen-percent", "每次体力恢复 (%)", "Stamina regeneration per choice (%)", DefaultSettings.StaminaRegenPercent, 0, MaxPercentPerPick);
            AddInt(page, "melee-cost-percent", "每次近战消耗降低 (%)", "Melee cost reduction per choice (%)", DefaultSettings.MeleeCostReductionPercent, 0, MaxPercentPerPick);
            AddInt(page, "sprint-cost-percent", "每次奔跑消耗降低 (%)", "Sprint cost reduction per choice (%)", DefaultSettings.SprintCostReductionPercent, 0, MaxPercentPerPick);
        }

        static void AddXp(McmPage page, string id, string zh, string en, int value)
        {
            page.AddIntInput(id, new McmLocalizedText(zh, en), value, 0, MaxXpPerKill,
                new McmLocalizedText("击杀确认后发放；未知或无法归属的击杀不发放经验。", "Granted only for confirmed kills; unknown or unattributed kills give no XP."), false);
        }

        static void AddInt(McmPage page, string id, string zh, string en, int value, int min, int max)
        {
            page.AddIntInput(id, new McmLocalizedText(zh, en), value, min, max,
                new McmLocalizedText("修改后按已有选择次数重新计算，不改变历史选择。", "Recalculates from existing choice counts without changing history."), false);
        }

        public void Initialize(IGameSession game)
        {
            if (game == null) throw new ArgumentNullException("game");
            // Register the screen before taking the plugin lock: the UI registry
            // lock is taken in the opposite order by the publish thread.
            RegisterUiSurface();
            lock (sync)
            {
                if (session != null) throw new InvalidOperationException("幸存者成长插件已经初始化。");
                session = game;
                runtime = GameRuntimeAccess.For(game);
                var initialSettings = ReadSettings();
                settingsEnabled = initialSettings.Enabled;
                engine = new RogueliteEngine(initialSettings, new RogueliteProgressStore());
                McmChoiceBus.SelectionRequested += OnChoiceSelected;
                McmChoiceBus.OverlayVisibilityChanged += OnOverlayVisibilityChanged;
                pause = runtime.Pause;
                killSource = game as ISurvivorKillEventSource;
                contextSource = game as ISurvivorContextSource;
                var missing = new List<string>();
                if (runtime.Api is StateOfDecay2GameApi)
                {
                    Check(runtime.Api, StateOfDecay2Capabilities.RogueliteKillEvents, missing);
                    Check(runtime.Api, StateOfDecay2Capabilities.SurvivorIdentity, missing);
                    Check(runtime.Api, StateOfDecay2Capabilities.SurvivorAttributes, missing);
                    Check(runtime.Api, StateOfDecay2Capabilities.SinglePlayerPause, missing);
                    Check(runtime.Api, StateOfDecay2Capabilities.NativeProgressionUi, missing);
                }
                if (killSource == null) missing.Add("击杀事件源");
                if (contextSource == null) missing.Add("幸存者上下文源");
                if (pause == null || !pause.IsAvailable) missing.Add(pause == null ? "暂停服务" : pause.Reason);
                if (missing.Count > 0)
                {
                    active = false;
                    missingCapabilities = String.Join("、", missing.ToArray());
                    status = "已降级：首版能力未完成静态验证（" + missingCapabilities + "）。成长数据核心已加载，但不会接收击杀或应用属性。按升级界面快捷键可查看成长总览与缺失原因。";
                    McmChoiceBus.Publish(McmChoiceState.Empty);
                    Console.Error.WriteLine("[Roguelite] " + status);
                    return;
                }
                killSubscription = killSource.Subscribe(OnKill);
                contextSubscription = contextSource.Subscribe(OnContextChanged);
                stop = new ManualResetEvent(false);
                worker = new Thread(Pump) { IsBackground = true, Name = "SoD2SE survivor progression" };
                worker.Start();
                active = true;
                missingCapabilities = "";
                status = "已启用。";
            }
        }

        // Publishes this mod's gameplay screen through the UI framework.  The
        // screen has no key of its own: it is the owner of the upgrade prompt,
        // so the prompt key opens it.
        void RegisterUiSurface()
        {
            var ui = UiRegistry.Current;
            if (ui == null) return;
            try
            {
                growthSurface = ui.RegisterSurface("survivor-roguelite.growth",
                    new McmLocalizedText("幸存者成长", "Survivor Progression"),
                    new McmLocalizedText("击杀丧尸积累经验；升级后在这里查看进度与已获得的强化。",
                        "Earn XP by killing zombies; check progress and owned upgrades here."),
                    BuildGrowthSurfaceForUi);
                growthSurface.SetShortcut(0, 0);
                growthSurface.ActionRequested += OnGrowthAction;
                ui.SetChoiceOwner(growthSurface.Id);
            }
            catch (Exception error)
            {
                growthSurface = null;
                Console.Error.WriteLine("[Roguelite] 无法注册界面：" + error.Message);
            }
        }

        void OnGrowthAction(string action)
        {
            if (action != "open-choice") return;
            var ui = UiRegistry.Current;
            if (ui != null) ui.RequestChoicePrompt();
        }

        void UnregisterUiSurface()
        {
            var surface = growthSurface;
            growthSurface = null;
            if (surface == null) return;
            surface.ActionRequested -= OnGrowthAction;
            var ui = UiRegistry.Current;
            if (ui != null) ui.UnregisterSurface(surface.Id);
        }

        void BuildGrowthSurfaceForUi(UiSurface surface)
        {
            var registry = McmRegistry.Current;
            var language = registry == null ? McmLanguage.English : registry.Language;
            string identity, character, localStatus, missing;
            long dropped;
            RogueliteEngine localEngine;
            lock (sync)
            {
                identity = currentIdentity;
                character = currentCharacter;
                localStatus = status;
                missing = missingCapabilities;
                dropped = droppedKillEvents;
                localEngine = engine;
            }
            if (localEngine == null)
            {
                surface.Section(language == McmLanguage.Chinese ? "状态" : "Status");
                surface.Note(localStatus);
                return;
            }
            localEngine.BuildGrowthSurface(surface, identity, language, character, localStatus, missing);
            if (dropped > 0)
                surface.Note(language == McmLanguage.Chinese
                    ? "事件队列溢出，已丢弃击杀事件：" + dropped.ToString(CultureInfo.InvariantCulture)
                    : "Kill events dropped after queue overflow: " + dropped.ToString(CultureInfo.InvariantCulture), UiTone.Warning);
        }

        static void Check(IGameVersionApi api, string capability, IList<string> missing)
        {
            if (!api.Capabilities.IsAvailable(capability)) missing.Add(api.Capabilities.Reason(capability));
        }

        RogueliteSettings ReadSettings()
        {
            var settings = new RogueliteSettings();
            var registry = McmRegistry.Current;
            if (registry == null) return settings;
            var page = registry.Snapshot().SingleOrDefault(item => item.Id == Id);
            if (page == null) return settings;
            foreach (var option in page.Options)
            {
                int value = option.IntValue;
                switch (option.Id)
                {
                    case "enabled": settings.Enabled = option.BoolValue; break;
                    case "notifications": settings.Notifications = option.BoolValue; break;
                    case "ordinary-xp": settings.OrdinaryXp = value; break;
                    case "plague-xp": settings.PlagueXp = value; break;
                    case "screamer-xp": settings.ScreamerXp = value; break;
                    case "bloater-xp": settings.BloaterXp = value; break;
                    case "feral-xp": settings.FeralXp = value; break;
                    case "juggernaut-xp": settings.JuggernautXp = value; break;
                    case "health-per-pick": settings.HealthPerPick = value; break;
                    case "stamina-per-pick": settings.StaminaPerPick = value; break;
                    case "melee-speed-percent": settings.MeleeSpeedPercent = value; break;
                    case "plague-resistance-percent": settings.PlagueResistancePercent = value; break;
                    case "sneak-speed-percent": settings.SneakSpeedPercent = value; break;
                    case "stamina-regen-percent": settings.StaminaRegenPercent = value; break;
                    case "melee-cost-percent": settings.MeleeCostReductionPercent = value; break;
                    case "sprint-cost-percent": settings.SprintCostReductionPercent = value; break;
                }
            }
            return settings;
        }

        void OnKill(SurvivorKillEvent value)
        {
            // The game callback only copies a normalized value into a bounded
            // queue. XP calculation, deduplication, and persistence run on the
            // consumer thread, outside the native hook path.
            lock (sync)
            {
                if (!active || !settingsEnabled) return;
                if (killQueue.Count >= KillQueueCapacity)
                {
                    droppedKillEvents++;
                    if (!overflowNoticeWritten)
                    {
                        overflowNoticeWritten = true;
                        Console.Error.WriteLine("[Roguelite] 击杀事件队列已满；新事件将被丢弃，成长页面会显示累计数量。");
                    }
                    return;
                }
                killQueue.Enqueue(value);
            }
        }

        void OnContextChanged(SurvivorContext context)
        {
            string next = context == null ? null : context.PersistentId;
            string character = context == null ? null : context.DisplayName;
            bool changed;
            lock (sync) { changed = !String.Equals(currentIdentity, next, StringComparison.Ordinal); currentIdentity = next; currentCharacter = character; }
            if (changed)
            {
                McmChoiceBus.Publish(McmChoiceState.Empty);
                ReleaseChoicePause();
            }
        }

        void OnChoiceSelected(McmChoiceSelection selection)
        {
            string identity;
            lock (sync)
            {
                if (!active) return;
                // A selection is only meaningful while the choice window owns
                // a pause lease.  Without it the player could pick while combat
                // keeps running, so keep the pending choice for the next attempt.
                if (choicePause == null) return;
                identity = currentIdentity;
            }
            if (String.IsNullOrWhiteSpace(identity) || engine == null) return;
            if (engine.ApplyChoice(identity, selection.Nonce, selection.Index, McmRegistry.Current.Language))
            {
                McmChoiceBus.Clear(selection.Nonce);
                ReleaseChoicePause();
            }
        }

        void OnOverlayVisibilityChanged(bool visible)
        {
            if (visible) EnsureChoicePause(); else ReleaseChoicePause();
        }

        void EnsureChoicePause()
        {
            if (!McmChoiceBus.OverlayVisible || !McmChoiceBus.Snapshot().Visible) { ReleaseChoicePause(); return; }
            lock (sync)
            {
                if (!active || choicePause != null || pause == null) return;
            }
            IDisposable lease;
            string reason;
            if (pause.TryAcquire(Id, out lease, out reason))
            {
                lock (sync)
                {
                    if (active && choicePause == null) choicePause = lease;
                    else lease.Dispose();
                }
            }
            else
            {
                lock (sync) if (active) status = "已启用；选择界面未取得暂停租约：" + reason;
            }
        }

        void ReleaseChoicePause()
        {
            IDisposable lease;
            lock (sync) { lease = choicePause; choicePause = null; }
            if (lease != null) lease.Dispose();
        }

        void Pump()
        {
            while (stop != null && !stop.WaitOne(100))
            {
                try
                {
                    var nextSettings = ReadSettings();
                    if (!SameSettings(engine.Settings, nextSettings)) engine.ReplaceSettings(nextSettings);
                    lock (sync)
                    {
                        settingsEnabled = nextSettings.Enabled;
                        if (!settingsEnabled) killQueue.Clear();
                    }
                    if (!nextSettings.Enabled)
                    {
                        engine.Tick();
                        McmChoiceBus.Publish(McmChoiceState.Empty);
                        EnsureChoicePause();
                        continue;
                    }
                    var batch = new List<SurvivorKillEvent>(KillDrainBatch);
                    lock (sync)
                    {
                        while (killQueue.Count > 0 && batch.Count < KillDrainBatch)
                            batch.Add(killQueue.Dequeue());
                    }
                    foreach (var kill in batch) engine.Award(kill);
                    engine.Tick();
                    SurvivorContext context;
                    if (contextSource == null || !contextSource.TryGetCurrent(out context) || context == null || String.IsNullOrWhiteSpace(context.PersistentId) || !context.IsSinglePlayer || !context.IsPlayerCommunityMember)
                    {
                        McmChoiceBus.Publish(McmChoiceState.Empty);
                        EnsureChoicePause();
                        continue;
                    }
                    lock (sync) { currentIdentity = context.PersistentId; currentCharacter = context.DisplayName; }
                    var state = engine.OpenChoice(context.PersistentId, McmRegistry.Current.Language, context.DisplayName);
                    McmChoiceBus.Publish(state);
                    EnsureChoicePause();
                }
                catch (Exception error) { Console.Error.WriteLine("[Roguelite] 进度循环错误：" + error.Message); }
            }
        }

        static bool SameSettings(RogueliteSettings left, RogueliteSettings right)
        {
            return left.Enabled == right.Enabled && left.Notifications == right.Notifications &&
                left.OrdinaryXp == right.OrdinaryXp && left.PlagueXp == right.PlagueXp &&
                left.ScreamerXp == right.ScreamerXp && left.BloaterXp == right.BloaterXp &&
                left.FeralXp == right.FeralXp && left.JuggernautXp == right.JuggernautXp &&
                left.HealthPerPick == right.HealthPerPick && left.StaminaPerPick == right.StaminaPerPick &&
                left.MeleeSpeedPercent == right.MeleeSpeedPercent && left.PlagueResistancePercent == right.PlagueResistancePercent &&
                left.SneakSpeedPercent == right.SneakSpeedPercent && left.StaminaRegenPercent == right.StaminaRegenPercent &&
                left.MeleeCostReductionPercent == right.MeleeCostReductionPercent && left.SprintCostReductionPercent == right.SprintCostReductionPercent;
        }

        public void Shutdown()
        {
            Thread localWorker;
            ManualResetEvent localStop;
            IDisposable localKill;
            IDisposable localContext;
            IDisposable localPause;
            lock (sync)
            {
                if (session == null) return;
                active = false;
                killQueue.Clear();
                localWorker = worker; worker = null;
                localStop = stop; stop = null;
                localKill = killSubscription; killSubscription = null;
                localContext = contextSubscription; contextSubscription = null;
                localPause = choicePause; choicePause = null;
            }
            McmChoiceBus.SelectionRequested -= OnChoiceSelected;
            McmChoiceBus.OverlayVisibilityChanged -= OnOverlayVisibilityChanged;
            McmChoiceBus.Publish(McmChoiceState.Empty);
            if (engine != null) engine.Flush();
            UnregisterUiSurface();
            if (localStop != null) localStop.Set();
            if (localWorker != null) localWorker.Join(1000);
            if (localKill != null) localKill.Dispose();
            if (localContext != null) localContext.Dispose();
            if (localPause != null) localPause.Dispose();
            if (localStop != null) localStop.Dispose();
            lock (sync)
            {
                session = null; runtime = null; engine = null; killSource = null; contextSource = null; pause = null; currentIdentity = null;
                status = "已停止。";
            }
        }
    }
}
