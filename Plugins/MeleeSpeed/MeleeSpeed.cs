using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.MemoryMappedFiles;
using System.Linq;
using System.Reflection;
using System.Threading;
using SoD2SE;
using SoD2SE.GameApi;

namespace SoD2SE.MeleeSpeed
{
    public sealed class Plugin : ISoD2Plugin, IMcmConfigurable, IPluginRuntimeStatus
    {
        // Channel layout shared with Native/MeleeProtocol.h.  verify_protocol.py
        // recomputes the packed struct, so a bare byte offset can never appear
        // here again and silently read the wrong field.
        const int ChannelMagic = 0x314c454d, ChannelVersion = 1, ChannelSize = 128;
        const int MagicOffset = 0, VersionOffset = 4, OwnerOffset = 8, ActiveOffset = 12;
        const int RatesOffset = 16, ScopesOffset = 32, ShutdownOffset = 44, HeartbeatOffset = 48;
        const int ActionTicksOffset = 64, AnimationTicksOffset = 72, FaultsOffset = 80;
        // RateNormal is 100%: the game's own speed, the MCM default and the
        // neutral value of the multiply modifier.
        const int RateCount = 4, ScopeCount = 3, RateMinimum = 25, RateMaximum = 1000, RateNormal = 100;
        // The four categories and three scopes are named once: the MCM page,
        // the property modifiers and the published channel all walk these lists.
        static readonly string[] RateIds = { "close", "blade", "blunt", "heavy" };
        static readonly string[] ScopeIds = { "player", "friendly", "others" };

        [System.Runtime.InteropServices.DllImport("kernel32.dll")] static extern ulong GetTickCount64();
        readonly object sync = new object();
        MemoryMappedFile mapping;
        MemoryMappedViewAccessor view;
        Mutex gate;
        Thread worker;
        ManualResetEvent stop;
        HookLease nativeLease;
        PropertyModifierLease[] rateModifiers;
        IGameSession session;
        GameRuntime runtime;
        bool active;
        string status = "未初始化。";

        public int ApiVersion { get { return FrameworkInfo.PluginApiVersion; } }
        public string Id { get { return "melee-speed"; } }
        public string Name { get { return "近战攻速 / Melee Attack Speed"; } }
        public string Description { get { return "四类普通近战及重武器蓄力攻击：同步动画与动作计时。100% 为原速。处决等双角色同步动作保持原速。 / Adjusts four normal melee and heavy-charge attacks with synchronized animation and action timing. 100% is normal speed; paired executions remain unchanged."; } }
        public bool IsActive { get { lock (sync) return active; } }
        public string Status { get { lock (sync) return status; } }

        public void RegisterMcm(McmRegistry registry)
        {
            var page = registry.RegisterPlugin(Id,
                new McmLocalizedText("近战攻速", "Melee Attack Speed"),
                new McmLocalizedText("四类普通近战及重武器蓄力攻击：同步动画与动作计时。100% 为原速。处决等双角色同步动作保持原速。", "Adjusts four normal melee and heavy-charge attacks with synchronized animation and action timing. 100% is normal speed; paired executions remain unchanged."));
            page.AddBool("active", new McmLocalizedText("启用攻速调整", "Enable speed adjustment"), true,
                new McmLocalizedText("实时开关；关闭后恢复游戏原始速度。", "Live switch; disabling restores the game's original speed."), false);
            var rateLabels = new[] {
                new[] { "近身格斗 (%)", "Close combat (%)" }, new[] { "刃器 (%)", "Bladed (%)" },
                new[] { "钝器 (%)", "Blunt (%)" }, new[] { "重型 (%)", "Heavy (%)" }
            };
            if (rateLabels.Length != RateIds.Length) throw new InvalidOperationException("攻速类别标签数量与协议不一致。");
            for (int index = 0; index < RateIds.Length; index++)
                page.AddInt(RateIds[index], new McmLocalizedText(rateLabels[index][0], rateLabels[index][1]),
                    RateNormal, RateMinimum, RateMaximum,
                    new McmLocalizedText("100＝原速，150＝1.5 倍，1000＝10 倍。与修改动画资源的 PAK 倍率叠加。", "100 = normal, 150 = 1.5x, 1000 = 10x. Stacks with animation-resource PAK multipliers."), false);
            // Only the local player is affected by default.
            var scopeLabels = new[] {
                new[] { "作用于本地玩家", "Apply to local player", "当前由你操控的角色。", "The character currently controlled by you." },
                new[] { "作用于友方 NPC", "Apply to friendly NPCs", "由游戏 AI 阵营关系判定，包括友方同伴。", "Determined by the game's AI attitude, including friendly companions." },
                new[] { "作用于其他人类", "Apply to other humans", "中立、敌对及其他玩家角色；不调整丧尸。全选表示所有人类。", "Neutral, hostile, and other player-controlled humans; zombies are never changed. Select all for every human." }
            };
            var scopeDefaults = new[] { true, false, false };
            if (scopeLabels.Length != ScopeIds.Length || scopeDefaults.Length != ScopeIds.Length)
                throw new InvalidOperationException("作用范围标签数量与协议不一致。");
            for (int index = 0; index < ScopeIds.Length; index++)
                page.AddBool(ScopeIds[index], new McmLocalizedText(scopeLabels[index][0], scopeLabels[index][1]),
                    scopeDefaults[index],
                    new McmLocalizedText(scopeLabels[index][2], scopeLabels[index][3]), false);
        }

        public void Initialize(IGameSession game)
        {
            if (game == null) throw new ArgumentNullException("game");
            lock (sync)
            {
                if (session != null) throw new InvalidOperationException("攻速插件已经初始化。");
                runtime = GameRuntimeAccess.For(game);
                session = game;
                if (runtime.Api is StateOfDecay2GameApi &&
                    (!runtime.Api.Capabilities.IsAvailable(StateOfDecay2Capabilities.MeleeAction) ||
                     !runtime.Api.Capabilities.IsAvailable(StateOfDecay2Capabilities.MeleeAnimation)))
                {
                    active = false;
                    status = "已降级：动作或动画 Hook 能力不可用。";
                    Console.Error.WriteLine("[MeleeSpeed] " + status);
                    return;
                }
                string channel = "Local\\SoD2SE.Melee." + Guid.NewGuid().ToString("N");
                try
                {
                    SetupPropertyModifiers();
                    gate = new Mutex(false, channel + ".lock");
                    mapping = MemoryMappedFile.CreateNew(channel, ChannelSize);
                    view = mapping.CreateViewAccessor(0, ChannelSize);
                    stop = new ManualResetEvent(false);
                    view.Write(MagicOffset, ChannelMagic); view.Write(VersionOffset, ChannelVersion);
                    view.Write(OwnerOffset, Process.GetCurrentProcess().Id);
                    Publish();
                    string library = Path.Combine(Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location), "MeleeSpeed", "SoD2SE.MeleeSpeed.Native.dll");
                    if (!File.Exists(library)) throw new FileNotFoundException("缺少攻速插件原生 DLL。", library);
                    nativeLease = runtime.Hooks.Acquire(HookRequest.NativeModule(Id, StateOfDecay2Capabilities.MeleeAction,
                        library, "SoD2MeleeStart", channel));
                    worker = new Thread(Pump) { IsBackground = true, Name = "SoD2SE melee configuration" };
                    worker.Start();
                    active = true;
                    status = "已启用。";
                    runtime.Events.Publish(new GameEvent(GameEventIds.PropertyChanged, Id, 0, 0, new GameObjectToken(), 0, 0, 1, "melee-rate-stack"));
                    Console.WriteLine("[MeleeSpeed] 已通过统一 Hook Broker 安装动作/动画 Hook；四类倍率由属性修改器堆栈合成。");
                }
                catch
                {
                    DisposeResources();
                    session = null;
                    runtime = null;
                    active = false;
                    status = "初始化失败。";
                    throw;
                }
            }
        }

        void SetupPropertyModifiers()
        {
            var keys = new string[RateIds.Length];
            for (int index = 0; index < keys.Length; index++)
                keys[index] = "melee." + RateIds[index];
            rateModifiers = new PropertyModifierLease[keys.Length];
            try
            {
                for (int i = 0; i < keys.Length; i++)
                    rateModifiers[i] = runtime.Properties.Register(keys[i], Id, PropertyModifierMode.Multiply, RateNormal, 1.0f, 1.0f, true);
            }
            catch
            {
                if (rateModifiers != null) foreach (var item in rateModifiers) if (item != null) item.Dispose();
                rateModifiers = null;
                throw;
            }
        }

        void Publish()
        {
            var page = McmRegistry.Current.Snapshot().Single(p => p.Id == Id);
            bool enabled = page.Options.Single(o => o.Id == "active").BoolValue;
            var ids = RateIds;
            if (ids.Length != RateCount || ids.Length != rateModifiers.Length)
                throw new InvalidOperationException("攻速类别数量与协议不一致。");
            var baselines = new Dictionary<string, float>(StringComparer.OrdinalIgnoreCase);
            for (int i = 0; i < ids.Length; i++)
            {
                int value = page.Options.Single(o => o.Id == ids[i]).IntValue;
                rateModifiers[i].Update(value / (float)RateNormal, enabled);
                baselines["melee." + ids[i]] = 1.0f;
            }
            var resolved = runtime.Properties.Snapshot(baselines);
            view.Write(ActiveOffset, enabled ? 1 : 0);
            int offset = RatesOffset;
            foreach (var id in ids)
            {
                int percentage = (int)Math.Round(Math.Max(RateMinimum / (float)RateNormal,
                    Math.Min(RateMaximum / (float)RateNormal, resolved["melee." + id])) * RateNormal);
                view.Write(offset, percentage); offset += 4;
            }
            var scopes = ScopeIds;
            if (scopes.Length != ScopeCount) throw new InvalidOperationException("作用范围数量与协议不一致。");
            offset = ScopesOffset;
            foreach (string id in scopes)
            { view.Write(offset, page.Options.Single(o => o.Id == id).BoolValue ? 1 : 0); offset += 4; }
            // Only this heartbeat is written every pump.  The native hook reads
            // one atomic packed policy, never this managed stack or MMF fields.
            view.Write(HeartbeatOffset, GetTickCount64());
        }

        void Pump()
        {
            ulong lastReport = GetTickCount64();
            ulong lastAction = 0, lastAnimation = 0, lastFault = 0;
            while (!stop.WaitOne(50))
            {
                bool locked = false;
                try
                {
                    try { locked = gate.WaitOne(100); } catch (AbandonedMutexException) { locked = true; }
                    if (locked)
                    {
                        Publish();
                        ulong action = view.ReadUInt64(ActionTicksOffset),
                            animation = view.ReadUInt64(AnimationTicksOffset),
                            fault = view.ReadUInt64(FaultsOffset);
                        if (GetTickCount64() - lastReport >= 10000 && (action != lastAction || animation != lastAnimation || fault != lastFault))
                        {
                            Console.WriteLine("[MeleeSpeed] 累计调整帧：动作=" + action + "，动画=" + animation + "，读取异常=" + fault + (fault > 0 ? "；本次运行已停止调整，请报告日志。" : ""));
                            lastAction = action; lastAnimation = animation; lastFault = fault; lastReport = GetTickCount64();
                        }
                    }
                }
                catch (Exception error)
                { Console.Error.WriteLine("[MeleeSpeed] 配置更新失败，停止攻速调整：" + error.Message); return; }
                finally { if (locked) gate.ReleaseMutex(); }
            }
        }

        public void Shutdown()
        {
            lock (sync)
            {
                if (session == null) return;
                if (stop != null) stop.Set();
                if (worker != null) { worker.Join(); worker = null; }
                DisposeResources();
                session = null;
                runtime = null;
                active = false;
                status = "已停止。";
            }
        }

        void DisposeResources()
        {
            // Signal the injected watchdog before releasing the channel.  The
            // lease never unloads a live DLL or retains a game object pointer.
            if (view != null) { view.Write(ShutdownOffset, 1); view.Dispose(); view = null; }
            if (mapping != null) { mapping.Dispose(); mapping = null; }
            if (gate != null) { gate.Dispose(); gate = null; }
            if (stop != null) { stop.Dispose(); stop = null; }
            if (nativeLease != null) { nativeLease.Dispose(); nativeLease = null; }
            if (rateModifiers != null) foreach (var item in rateModifiers) if (item != null) item.Dispose();
            rateModifiers = null;
        }
    }
}

