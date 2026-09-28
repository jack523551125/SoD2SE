using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.MemoryMappedFiles;
using System.Linq;
using System.Reflection;
using System.Text;
using System.Threading;
using SoD2SE;
using SoD2SE.GameApi;

namespace SoD2SE.Mcm
{
    public sealed class Plugin : ISoD2Plugin, IMcmConfigurable, IPluginRuntimeStatus
    {
        McmBridge bridge;
        GameRuntime runtime;
        bool active;
        string status = "未初始化。";
        public int ApiVersion { get { return FrameworkInfo.PluginApiVersion; } }
        public string Id { get { return "mcm"; } }
        public string Name { get { return "模组配置菜单 / Mod Configuration Menu"; } }
        public string Description { get { return "通过原版设置菜单提供 Mod 配置页。 / Provides Mod configuration through the game's Settings menu."; } }
        public bool IsActive { get { return active; } }
        public string Status { get { return status; } }
        public void RegisterMcm(McmRegistry registry)
        {
            // MCM itself owns the language and shortcut settings.  They are
            // rendered together on the native MCM home page rather than
            // exposed as a regular Mod page.
        }
        public void Initialize(IGameSession session)
        {
            if (session == null) throw new ArgumentNullException("session");
            if (bridge != null) throw new InvalidOperationException("MCM 已初始化。");
            runtime = GameRuntimeAccess.For(session);
            if (runtime.Api is StateOfDecay2GameApi && !runtime.Api.Capabilities.IsAvailable(GameCapabilityIds.McmOverlay))
            {
                active = false;
                status = "已降级：" + runtime.Api.Capabilities.Reason(GameCapabilityIds.McmOverlay);
                Console.Error.WriteLine("[MCM] " + status);
                return;
            }
            var native = Path.Combine(Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location), "Mcm", "SoD2SE.Mcm.Native.dll");
            if (!File.Exists(native)) throw new FileNotFoundException("MCM 缺少原生渲染组件，请安装完整 MCM Mod 包。", native);
            var instance = new McmBridge(session.GameProcess, McmRegistry.Current, runtime.Hooks);
            try { instance.Start(native); bridge = instance; }
            catch { instance.Dispose(); runtime = null; throw; }
            active = true;
            status = "已启用。";
            runtime.Events.Publish(new GameEvent(GameEventIds.SessionReady, Id, 0, 0, new GameObjectToken(), 0, 0, 1, "mcm"));
        }
        public void Shutdown()
        {
            if (bridge != null) { bridge.Dispose(); bridge = null; }
            runtime = null;
            active = false;
            status = "已停止。";
        }
    }

    internal sealed class McmBridge : IDisposable
    {
        // Offsets mirror mcm::State in Native/McmProtocol.h.  The header is the
        // single source of truth; verify_protocol.py compares both sides so a
        // layout change cannot land in one language only.
        const int ProtocolMagic = 0x314d434d, ProtocolVersion = 6;
        const int ReadyPending = 1, Ready = 2, Failed = -1;
        // State::command values.  Every one of them is also named in
        // Native/McmProtocol.h; verify_protocol.py fails the build when the two
        // lists disagree.
        const int CommandSetBool = 1, CommandSetInt = 2, CommandResetAll = 3,
            CommandSetShortcut = 4, CommandSelectChoice = 6,
            CommandSetChoiceShortcut = 7, CommandSetSurfaceShortcut = 8, CommandSurfaceAction = 9;
        const int MaxPages = 32, MaxOptions = 128, MaxChoiceCards = 3;
        // Named scalar header fields of mcm::State.  verify_protocol.py maps
        // every one of them back to the header's field list, so the pump never
        // counts bytes by hand.
        const int MagicOffset = 0, VersionOffset = 4, HostPidOffset = 8, GamePidOffset = 12,
            RequestOffset = 16, AcknowledgedOffset = 20, CommandOffset = 24, PageOffset = 28,
            OptionOffset = 32, ValueOffset = 36, KeyOffset = 40, ModifiersOffset = 44,
            ResultOffset = 48, VisibleOffset = 52, ReadyOffset = 56, ShutdownOffset = 60,
            PageCountOffset = 64, OptionCountOffset = 68, ShortcutKeyOffset = 72,
            ShortcutModifiersOffset = 76, LanguageOffset = 80, MessageOffset = 84, ConfigPathOffset = 596;
        const int Size = 176620, PagesOffset = 1620, OptionsOffset = 24276, ChoiceOffset = 117460;
        const int UiSurfaceCountOffset = 119888, UiChoiceOpenOffset = 119892, UiSurfacesOffset = 119896;
        const int UiNodeCountOffset = 122848, UiNodesOffset = 122852;
        const int UiChoiceOwnerOffset = 176612, UiChoiceRequestOffset = 176616;
        const int UiSurfaceSize = 492, UiNodeSize = 560, UiMaxSurfaces = 6, UiMaxNodes = 96;
        // Record layouts, named field by field.  They describe the same header
        // as the block above, so verify_protocol.py can check each one instead
        // of trusting a hand-counted byte offset.
        const int PageSize = 708, PageIdOffset = 0, PageNameOffset = 64, PageDescriptionOffset = 192, PageLoadedOffset = 704;
        const int OptionSize = 728, OptionPageOffset = 0, OptionIdOffset = 4, OptionLabelOffset = 68,
            OptionDescriptionOffset = 196, OptionTypeOffset = 708, OptionValueOffset = 712,
            OptionMinimumOffset = 716, OptionMaximumOffset = 720, OptionRestartOffset = 724;
        const int ChoiceCardSize = 712, ChoiceCardCurrentOffset = 0, ChoiceCardNextOffset = 4,
            ChoiceCardIdOffset = 8, ChoiceCardTitleOffset = 72, ChoiceCardDescriptionOffset = 200;
        const int ChoiceVisibleOffset = 0, ChoiceLevelOffset = 4, ChoicePendingOffset = 8, ChoiceNonceOffset = 12,
            ChoiceCountOffset = 16, ChoiceSelectedOffset = 20, ChoiceKeyOffset = 24, ChoiceModifiersOffset = 28,
            ChoiceResultOffset = 32, ChoiceCardsOffset = 36,
            ChoiceCharacterSize = 128, ChoiceExperienceSize = 64;
        const int ChoiceTextOffset = ChoiceOffset + ChoiceCardsOffset + MaxChoiceCards * ChoiceCardSize;
        const int ChoiceNextExperienceOffset = ChoiceCharacterSize + ChoiceExperienceSize;
        const int SurfaceWantOpen = 0, SurfaceOpen = 4, SurfaceModal = 8, SurfacePriority = 12, SurfaceRevision = 16,
            SurfaceNodeStart = 20, SurfaceNodeCount = 24, SurfaceShortcutKey = 28, SurfaceShortcutModifiers = 32,
            SurfaceWantRevision = 36, SurfaceSeenRevision = 40, SurfaceId = 44, SurfaceTitle = 108, SurfaceSubtitle = 236;
        const int NodeKind = 0, NodeTone = 4, NodeCurrent = 8, NodeMaximum = 12, NodeAction = 16,
            NodeLabel = 80, NodeValue = 208, NodeDescription = 304;
        // Text field widths.  They come from the same declarations the native
        // side compiles, so the verifier can confirm both the offset and the
        // width of every string field.
        const int MessageSize = 512, ConfigPathSize = 1024;
        const int PageIdSize = 64, PageNameSize = 128, PageDescriptionSize = 512;
        const int OptionIdSize = 64, OptionLabelSize = 128, OptionDescriptionSize = 512;
        const int ChoiceCardIdSize = 64, ChoiceCardTitleSize = 128, ChoiceCardDescriptionSize = 512;
        const int SurfaceIdSize = 64, SurfaceTitleSize = 128, SurfaceSubtitleSize = 256;
        const int NodeActionSize = 64, NodeLabelSize = 128, NodeValueSize = 96, NodeDescriptionSize = 256;
        readonly Process game;
        readonly McmRegistry registry;
        readonly string name = "Local\\SoD2SE.MCM." + Guid.NewGuid().ToString("N");
        readonly Mutex gate;
        readonly MemoryMappedFile mapping;
        readonly MemoryMappedViewAccessor view;
        readonly IHookBroker hooks;
        HookLease nativeLease;
        readonly ManualResetEvent stop = new ManualResetEvent(false);
        Thread worker;
        bool disposed;
        bool renderErrorReported;
        public McmBridge(Process target, McmRegistry configuration, IHookBroker hooks)
        {
            if (configuration == null) throw new InvalidOperationException("MCM 配置服务尚未初始化。");
            if (hooks == null) throw new InvalidOperationException("Hook Broker 尚未初始化。");
            game = target; registry = configuration; this.hooks = hooks;
            try
            {
                gate = new Mutex(false, name + ".lock");
                mapping = MemoryMappedFile.CreateNew(name, Size);
                view = mapping.CreateViewAccessor(0, Size);
                view.Write(MagicOffset, ProtocolMagic); view.Write(VersionOffset, ProtocolVersion);
                view.Write(HostPidOffset, Process.GetCurrentProcess().Id); view.Write(GamePidOffset, game.Id);
                Publish();
            }
            catch
            {
                if (view != null) view.Dispose();
                if (mapping != null) mapping.Dispose();
                if (gate != null) gate.Dispose();
                stop.Dispose();
                throw;
            }
        }
        public void Start(string native)
        {
            nativeLease = hooks.Acquire(HookRequest.NativeModule("mcm", GameCapabilityIds.McmOverlay, native, "SoD2McmStart", name));
            worker = new Thread(Pump) { IsBackground = true, Name = "SoD2SE MCM configuration" };
            worker.Start();
        }
        void Publish()
        {
            var pages = registry.Snapshot();
            if (pages.Count > MaxPages || pages.Sum(p => p.Options.Count) > MaxOptions)
                throw new InvalidOperationException("MCM 最多支持 " + MaxPages + " 个页面、" + MaxOptions + " 项设置。");
            view.Write(PageCountOffset, pages.Count);
            view.Write(ShortcutKeyOffset, registry.ShortcutKey); view.Write(ShortcutModifiersOffset, registry.ShortcutModifiers);
            view.Write(LanguageOffset, (int)registry.Language);
            WriteText(ConfigPathOffset, ConfigPathSize, registry.ConfigPath);
            int index = 0;
            for (int p = 0; p < pages.Count; p++)
            {
                var page = pages[p]; int offset = PagesOffset + p * PageSize;
                WriteText(offset + PageIdOffset, PageIdSize, page.Id);
                WriteText(offset + PageNameOffset, PageNameSize, page.Name);
                WriteText(offset + PageDescriptionOffset, PageDescriptionSize, page.Description);
                view.Write(offset + PageLoadedOffset, page.Loaded ? 1 : 0);
                foreach (var option in page.Options)
                {
                    int o = OptionsOffset + index++ * OptionSize;
                    view.Write(o + OptionPageOffset, p);
                    WriteText(o + OptionIdOffset, OptionIdSize, option.Id);
                    WriteText(o + OptionLabelOffset, OptionLabelSize, option.Label);
                    WriteText(o + OptionDescriptionOffset, OptionDescriptionSize, option.Description);
                    view.Write(o + OptionTypeOffset, (int)option.Type);
                    view.Write(o + OptionValueOffset, option.Type == McmOptionType.Boolean ? (option.BoolValue ? 1 : 0) : option.IntValue);
                    view.Write(o + OptionMinimumOffset, option.Minimum);
                    view.Write(o + OptionMaximumOffset, option.Maximum);
                    view.Write(o + OptionRestartOffset, option.RequiresRestart ? 1 : 0);
                }
            }
            view.Write(OptionCountOffset, index);
            var choice = McmChoiceBus.Snapshot();
            view.Write(ChoiceOffset + ChoiceVisibleOffset, choice.Visible ? 1 : 0);
            view.Write(ChoiceOffset + ChoiceLevelOffset, choice.Level);
            view.Write(ChoiceOffset + ChoicePendingOffset, choice.PendingLevels);
            view.Write(ChoiceOffset + ChoiceNonceOffset, choice.Nonce);
            view.Write(ChoiceOffset + ChoiceCountOffset, choice.Cards.Count);
            view.Write(ChoiceOffset + ChoiceSelectedOffset, -1);
            view.Write(ChoiceOffset + ChoiceKeyOffset, registry.ChoiceShortcutKey);
            view.Write(ChoiceOffset + ChoiceModifiersOffset, registry.ChoiceShortcutModifiers);
            view.Write(ChoiceOffset + ChoiceResultOffset, 0);
            for (int i = 0; i < MaxChoiceCards; i++)
            {
                int offset = ChoiceOffset + ChoiceCardsOffset + i * ChoiceCardSize;
                if (i < choice.Cards.Count)
                {
                    var card = choice.Cards[i];
                    view.Write(offset + ChoiceCardCurrentOffset, card.CurrentValue);
                    view.Write(offset + ChoiceCardNextOffset, card.NextValue);
                    WriteText(offset + ChoiceCardIdOffset, ChoiceCardIdSize, card.Id);
                    WriteText(offset + ChoiceCardTitleOffset, ChoiceCardTitleSize, card.Title);
                    WriteText(offset + ChoiceCardDescriptionOffset, ChoiceCardDescriptionSize, card.Description);
                }
                else
                {
                    view.Write(offset + ChoiceCardCurrentOffset, 0);
                    view.Write(offset + ChoiceCardNextOffset, 0);
                    WriteText(offset + ChoiceCardIdOffset, ChoiceCardIdSize, "");
                    WriteText(offset + ChoiceCardTitleOffset, ChoiceCardTitleSize, "");
                    WriteText(offset + ChoiceCardDescriptionOffset, ChoiceCardDescriptionSize, "");
                }
            }
            WriteText(ChoiceTextOffset, ChoiceCharacterSize, choice.Character);
            WriteText(ChoiceTextOffset + ChoiceCharacterSize, ChoiceExperienceSize, choice.Experience);
            WriteText(ChoiceTextOffset + ChoiceNextExperienceOffset, ChoiceExperienceSize, choice.NextLevelExperience);
            PublishSurfaces();
            // The host owns the choice overlay flag; mirror it so the owning mod
            // knows whether its pause lease is still required.
            McmChoiceBus.SetOverlayVisible(view.ReadInt32(UiChoiceOpenOffset) != 0);
        }
        // Publishes every registered module screen.  The managed side writes
        // descriptors and the visibility request; the native host writes back
        // "open" and the revision it acted on, which is applied right here.
        IList<UiSurfaceSnapshot> PublishSurfaces()
        {
            var ui = UiRegistry.Current;
            IList<UiSurfaceSnapshot> surfaces = ui == null ? new List<UiSurfaceSnapshot>() : ui.Snapshot();
            if (surfaces.Count > UiMaxSurfaces) throw new InvalidOperationException("界面框架最多支持 " + UiMaxSurfaces + " 个界面。");
            view.Write(UiSurfaceCountOffset, surfaces.Count);
            int nodeIndex = 0;
            for (int i = 0; i < UiMaxSurfaces; i++)
            {
                int offset = UiSurfacesOffset + i * UiSurfaceSize;
                if (i >= surfaces.Count)
                {
                    view.Write(offset + SurfaceWantOpen, 0);
                    view.Write(offset + SurfaceNodeStart, 0);
                    view.Write(offset + SurfaceNodeCount, 0);
                    view.Write(offset + SurfaceWantRevision, 0);
                    continue;
                }
                var surface = surfaces[i];
                view.Write(offset + SurfaceWantOpen, surface.WantsOpen ? 1 : 0);
                view.Write(offset + SurfaceModal, surface.Modal ? 1 : 0);
                view.Write(offset + SurfacePriority, surface.Priority);
                view.Write(offset + SurfaceRevision, surface.Revision);
                view.Write(offset + SurfaceNodeStart, nodeIndex);
                view.Write(offset + SurfaceNodeCount, surface.Nodes.Count);
                view.Write(offset + SurfaceShortcutKey, surface.ShortcutKey);
                view.Write(offset + SurfaceShortcutModifiers, surface.ShortcutModifiers);
                view.Write(offset + SurfaceWantRevision, surface.WantRevision);
                WriteText(offset + SurfaceId, SurfaceIdSize, surface.Id);
                WriteText(offset + SurfaceTitle, SurfaceTitleSize, surface.Title);
                WriteText(offset + SurfaceSubtitle, SurfaceSubtitleSize, surface.Subtitle);
                foreach (var node in surface.Nodes)
                {
                    if (nodeIndex >= UiMaxNodes) break;
                    int target = UiNodesOffset + nodeIndex++ * UiNodeSize;
                    view.Write(target + NodeKind, (int)node.Kind);
                    view.Write(target + NodeTone, (int)node.Tone);
                    view.Write(target + NodeCurrent, node.Current);
                    view.Write(target + NodeMaximum, node.Maximum);
                    WriteText(target + NodeAction, NodeActionSize, node.Action);
                    WriteText(target + NodeLabel, NodeLabelSize, node.Label);
                    WriteText(target + NodeValue, NodeValueSize, node.Value);
                    WriteText(target + NodeDescription, NodeDescriptionSize, node.Description);
                }
            }
            view.Write(UiNodeCountOffset, nodeIndex);
            view.Write(UiChoiceOwnerOffset, ui == null ? -1 : ui.ChoiceOwnerIndex());
            view.Write(UiChoiceRequestOffset, ui == null ? 0 : ui.ChoiceRequest);
            for (int i = 0; i < surfaces.Count; i++)
            {
                if (ui == null) break;
                int offset = UiSurfacesOffset + i * UiSurfaceSize;
                ui.ApplyHostState(surfaces[i], view.ReadInt32(offset + SurfaceSeenRevision), view.ReadInt32(offset + SurfaceOpen) != 0);
            }
            return surfaces;
        }
        void Pump()
        {
            while (!stop.WaitOne(50))
            {
                bool locked = false;
                try
                {
                    try { locked = gate.WaitOne(25); } catch (AbandonedMutexException) { locked = true; }
                    if (!locked) continue;
                    if (!renderErrorReported && view.ReadInt32(ReadyOffset) == Failed)
                    {
                        renderErrorReported = true;
                        Console.Error.WriteLine(registry.Language == McmLanguage.Chinese ? "[MCM] 游戏内渲染初始化失败，菜单已停用；详情见 Mcm-native 日志。" : "[MCM] In-game rendering failed; MCM has been disabled. See the native log.");
                    }
                    int request = view.ReadInt32(RequestOffset);
                    if (request != view.ReadInt32(AcknowledgedOffset))
                    {
                        try
                        {
                            int command = view.ReadInt32(CommandOffset);
                            if (command == CommandResetAll) registry.ResetAll();
                            else if (command == CommandSetShortcut) registry.SetShortcut(view.ReadInt32(KeyOffset), view.ReadInt32(ModifiersOffset));
                            else if (command == CommandSelectChoice)
                            {
                                int nonce = view.ReadInt32(PageOffset), index = view.ReadInt32(OptionOffset);
                                if (!McmChoiceBus.TrySelect(nonce, index)) throw new InvalidOperationException("升级选择已过期或不可用。");
                            }
                            else if (command == CommandSetChoiceShortcut) registry.SetChoiceShortcut(view.ReadInt32(KeyOffset), view.ReadInt32(ModifiersOffset));
                            else if (command == CommandSetSurfaceShortcut)
                            {
                                var ui = UiRegistry.Current;
                                var surfaces = ui == null ? null : ui.Snapshot();
                                int slot = view.ReadInt32(PageOffset);
                                if (surfaces == null || slot < 0 || slot >= surfaces.Count) throw new ArgumentException("界面索引无效。");
                                ui.SetSurfaceShortcut(surfaces[slot].Id, view.ReadInt32(KeyOffset), view.ReadInt32(ModifiersOffset));
                            }
                            else if (command == CommandSurfaceAction)
                            {
                                var ui = UiRegistry.Current;
                                var surfaces = ui == null ? null : ui.Snapshot();
                                int slot = view.ReadInt32(PageOffset);
                                if (surfaces == null || slot < 0 || slot >= surfaces.Count) throw new ArgumentException("界面索引无效。");
                                var target = surfaces[slot];
                                if (!ui.TryInvokeAction(target, view.ReadInt32(OptionOffset) - target.NodeStart, view.ReadInt32(ValueOffset)))
                                    throw new InvalidOperationException("界面动作已过期。");
                            }
                            else if (command == CommandSetBool || command == CommandSetInt)
                            {
                                int pageIndex = view.ReadInt32(PageOffset), optionIndex = view.ReadInt32(OptionOffset);
                                if (pageIndex < 0 || pageIndex >= view.ReadInt32(PageCountOffset) || optionIndex < 0 || optionIndex >= view.ReadInt32(OptionCountOffset))
                                    throw new ArgumentException("MCM 设置索引无效。");
                                int offset = OptionsOffset + optionIndex * OptionSize;
                                if (view.ReadInt32(offset + OptionPageOffset) != pageIndex) throw new ArgumentException("MCM 设置页面不匹配。");
                                string page = ReadText(PagesOffset + pageIndex * PageSize + PageIdOffset, PageIdSize),
                                    option = ReadText(offset + OptionIdOffset, OptionIdSize);
                                if (command == CommandSetBool) registry.SetBool(page, option, view.ReadInt32(ValueOffset) != 0);
                                else registry.SetInt(page, option, view.ReadInt32(ValueOffset));
                            }
                            else throw new ArgumentException("未知 MCM 命令。");
                            view.Write(ResultOffset, 0); WriteText(MessageOffset, MessageSize, registry.Language == McmLanguage.Chinese
                                ? (command == CommandSetShortcut ? "快捷键已保存，立即生效。" : command == CommandSetChoiceShortcut ? "升级界面快捷键已保存。" : command == CommandSetSurfaceShortcut ? "界面快捷键已保存。" : command == CommandSurfaceAction ? "界面操作已执行。" : command == CommandSelectChoice ? "升级已选择。" : "已保存。标记为重启生效的设置将在下次启动应用。")
                                : (command == CommandSetShortcut ? "Shortcut saved and active." : command == CommandSetChoiceShortcut ? "Upgrade shortcut saved." : command == CommandSetSurfaceShortcut ? "Screen shortcut saved." : command == CommandSurfaceAction ? "Screen action applied." : command == CommandSelectChoice ? "Upgrade selected." : "Saved. Settings marked for restart apply on the next launch."));
                        }
                        catch (Exception error) { view.Write(ResultOffset, 1); WriteText(MessageOffset, MessageSize, (registry.Language == McmLanguage.Chinese ? "保存失败：" : "Save failed: ") + error.Message); }
                        view.Write(AcknowledgedOffset, request);
                    }
                    Publish();
                }
                catch (Exception error) { Console.Error.WriteLine("[MCM] 配置桥接错误：" + error.Message); }
                finally { if (locked) gate.ReleaseMutex(); }
            }
        }
        void WriteText(int offset, int size, string text)
        {
            var buffer = new byte[size]; var chars = (text ?? "").ToCharArray();
            int usedChars, usedBytes; bool complete;
            Encoding.UTF8.GetEncoder().Convert(chars, 0, chars.Length, buffer, 0, size - 1, true, out usedChars, out usedBytes, out complete);
            view.WriteArray(offset, buffer, 0, buffer.Length);
        }
        string ReadText(int offset, int size)
        {
            var buffer = new byte[size]; view.ReadArray(offset, buffer, 0, size);
            int end = Array.IndexOf(buffer, (byte)0);
            return Encoding.UTF8.GetString(buffer, 0, end < 0 ? size : end);
        }
        public void Dispose()
        {
            if (disposed) return;
            disposed = true; stop.Set();
            if (worker != null) worker.Join();
            bool locked = false;
            try
            {
                try { locked = gate.WaitOne(1000); } catch (AbandonedMutexException) { locked = true; }
                if (locked) view.Write(ShutdownOffset, 1);
            }
            finally
            {
                McmChoiceBus.SetOverlayVisible(false);
                if (locked) gate.ReleaseMutex();
                view.Dispose(); mapping.Dispose(); gate.Dispose(); stop.Dispose();
                if (nativeLease != null) { nativeLease.Dispose(); nativeLease = null; }
            }
        }
    }
}
