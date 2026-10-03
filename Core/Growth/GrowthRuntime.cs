using System;
using System.Collections.Generic;

namespace SoD2SE
{
    // Versioned, renderer-independent managed contract. Not a reinterpretation of
    // McmChoiceState or its fixed three-card shared-memory layout.
    public static class GrowthRuntimeContract
    {
        public const int Version = 3;
        public const int RewardPageSize = 32;
        public static readonly string[] RequiredFeatures = {
            "persistent-identity", "attributed-deaths", "twelve-attributes", "vanilla-skill-suppression",
            "complete-technique-catalog", "technique-conflicts", "profession-knowledge",
            "all-non-plague-death-interception", "plague-death-priority", "fatigue-control",
            "native-character-ui", "native-hud", "single-player-pause", "input-consumption",
            "controller-navigation", "shared-melee-clock"
        };
    }
    public sealed class GrowthVanillaState
    {
        public string RestorableSnapshot, Profession, Specialization;
        public IList<string> LearnedTechniqueIds = new List<string>();
        public IList<string> ProfessionChoices = new List<string>();
    }
    public sealed class GrowthActorFrame
    {
        public string Identity, Name;
        public bool Dead, CanAct, Driving, SpecialAction, BloodPlagueDeathPending;
        public double SecondsSinceCombat, RecoverableHealth, UsableStamina;
        public long KnowledgeRevision;
    }
    public sealed class GrowthWorldFrame
    {
        public long DeltaMilliseconds;
        public bool SinglePlayer, Paused, Loading, Focused, MenuOpen, GrowthPageOpen;
        public string ControlledIdentity;
        public IList<GrowthActorFrame> Actors = new List<GrowthActorFrame>();
        public IList<SurvivorKillEvent> Kills = new List<SurvivorKillEvent>();
        public bool NewWorldSession;
    }
    public sealed class GrowthDeathRequest
    {
        public string Identity;
        public bool BloodPlagueDeath, DeathRequested;
        public double Health, RecoverableHealth;
    }
    public sealed class GrowthRecovery
    {
        public bool PreventDeath;
        public double Health, Stamina;
        public bool SetHealth;
    }
    public sealed class GrowthEffects
    {
        public string Identity, ProfessionSpecialization;
        // Stable order matches RogueliteBuff IDs 0..11. Values are flat points or percent.
        public double[] AttributeBonuses;
        public IList<string> Techniques;
        public bool NoFatigue;
        public double BloodAttackMultiplier = 1, DamageMultiplier = 1, LineMeleeCostMultiplier = 1,
            LineKnockdownMultiplier = 1, MovementMultiplier = 1;
        public double AttackCeiling = 4, MeleeCostFloor = 0.1;
    }
    public sealed class GrowthCard
    {
        public string Id, Title, Description;
        public bool Active;
    }
    public sealed class GrowthRewardSection
    {
        public string Id, Kind, Title;
        public IList<GrowthCard> Cards = new List<GrowthCard>();
    }
    public sealed class GrowthSlotView
    {
        public string Id, Name;
        public InputChord KeyboardBinding, GamepadBinding;
        public long CooldownMilliseconds, ActiveMilliseconds;
    }
    public sealed class GrowthPageSnapshot
    {
        public int Version = GrowthRuntimeContract.Version;
        public bool ShowNotices;
        public string Identity, Character, Level, Experience, NextExperience, PendingLevels, RewardLevel, Revision, Status;
        public IList<GrowthRewardSection> Sections = new List<GrowthRewardSection>();
        public IList<GrowthCard> Attributes = new List<GrowthCard>();
        public IList<GrowthCard> Techniques = new List<GrowthCard>();
        public IList<GrowthCard> SuperTraits = new List<GrowthCard>();
        public IList<GrowthCard> ProfessionChoices = new List<GrowthCard>();
        public IList<GrowthSlotView> Slots = new List<GrowthSlotView>();
        // A bounded view of the compressed pending queue. Future levels show
        // their saved schedule; only the first level has persisted candidates.
        public string RewardQueueStart = "0", RewardQueueTotal = "0", PreviousRewardPage = "", NextRewardPage = "";
        public IList<GrowthCard> RewardRecords = new List<GrowthCard>();
    }
    public enum GrowthCommandKind { ClaimRow, Equip, Profession, Close, RewardPage }
    public sealed class GrowthCommand
    {
        public GrowthCommandKind Kind;
        public string Identity, Revision, Ability, RewardPageStart;
        public int Slot;
        public IDictionary<string, string> Selections;
    }
    public interface IGrowthRuntimeAdapter : IGameInputSession
    {
        int Version { get; }
        ICollection<string> VerifiedFeatures { get; }
        ICollection<string> VerifiedTechniqueIds { get; }
        // All callbacks execute serially on the game thread. BeforeDeath is synchronous.
        IDisposable Subscribe(Action<GrowthWorldFrame> frame, Func<GrowthDeathRequest, GrowthRecovery> beforeDeath, Action<GrowthCommand> command);
        GrowthVanillaState ReadVanilla(string identity);
        string LocalizeProfession(string specialization, McmLanguage language);
        // Idempotent: repeated frames must not stack modifiers or replace the backup.
        void SuppressVanillaSkills(string identity, string restorableSnapshot);
        void RestoreVanillaSkills();
        // Replace this owner's full effect set on this actor; never add twice.
        void ApplyEffects(GrowthEffects effects);
        void ClearEffects();
        void Recover(string identity, GrowthRecovery recovery);
        void Publish(GrowthPageSnapshot page);
        // Original UI only; acquiring/releasing the game's pause lease belongs here.
        bool TryOpenGrowthPage();
        void CloseGrowthPage();
    }
}
