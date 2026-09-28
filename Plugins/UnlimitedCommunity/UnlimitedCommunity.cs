using System;
using SoD2SE;
using SoD2SE.GameApi;

namespace SoD2SE.UnlimitedCommunity
{
    public sealed class Plugin : ISoD2Plugin, IMcmConfigurable, IPluginRuntimeStatus
    {
        readonly object sync = new object();
        IGameSession session;
        HookLease lease;
        GameRuntime runtime;
        bool active;
        string status = "未初始化。";

        public int ApiVersion { get { return FrameworkInfo.PluginApiVersion; } }
        public string Id { get { return "unlimited-community"; } }
        public string Name { get { return "社区招募无上限 / Unlimited Community Recruitment"; } }
        public string Description { get { return "解除 Update 38.2 玩家社区招募的 9/12 人数量门槛；保留 NPC 上限、真实人数和其他招募条件。 / Removes the Update 38.2 9/12-member recruitment gate while keeping NPC caps, real population, and other recruitment checks."; } }
        public bool IsActive { get { lock (sync) return active; } }
        public string Status { get { lock (sync) return status; } }

        public void RegisterMcm(McmRegistry registry)
        {
            registry.RegisterPlugin(Id,
                new McmLocalizedText("社区招募无上限", "Unlimited Community Recruitment"),
                new McmLocalizedText("解除 Update 38.2 玩家社区招募的 9/12 人数量门槛；保留 NPC 上限、真实人数和其他招募条件。", "Removes the Update 38.2 9/12-member recruitment gate while keeping NPC caps, real population, and other recruitment checks."));
        }

        public void Initialize(IGameSession game)
        {
            if (game == null) throw new ArgumentNullException("game");
            lock (sync)
            {
                if (session != null) throw new InvalidOperationException("社区招募插件已经初始化。");
                runtime = GameRuntimeAccess.For(game);
                session = game;
                if (runtime.Api is StateOfDecay2GameApi && !runtime.Api.Capabilities.IsAvailable(StateOfDecay2Capabilities.Community))
                {
                    active = false;
                    status = "已降级：" + runtime.Api.Capabilities.Reason(StateOfDecay2Capabilities.Community);
                    Console.Error.WriteLine("[UnlimitedCommunity] " + status);
                    return;
                }
                var patches = runtime.Api.GetPatches(StateOfDecay2Capabilities.Community);
                if (patches.Count == 0) patches = StateOfDecay2GameApi.GetCompatibilityPatches(StateOfDecay2Capabilities.Community);
                lease = runtime.Hooks.Acquire(HookRequest.BytePatch(Id, StateOfDecay2Capabilities.Community,
                    runtime.Api.Target.Sha256, patches));
                active = true;
                status = "已启用。";
                runtime.Events.Publish(new GameEvent(GameEventIds.RecruitmentGate, Id, 0, 0, new GameObjectToken(), lease.ChangedBytes, 0, 1, "enabled"));
                Console.WriteLine("[UnlimitedCommunity] 已加载；统一 Hook Broker 接管补丁位置：" + patches.Count + "；本次修改：" + lease.ChangedBytes + " 处。");
            }
        }

        public void Shutdown()
        {
            lock (sync)
            {
                if (session == null) return;
                try
                {
                    if (lease != null)
                    {
                        lease.Dispose();
                        Console.WriteLine("[UnlimitedCommunity] 已还原；统一 Hook Broker 已释放补丁。");
                    }
                }
                finally
                {
                    lease = null;
                    runtime = null;
                    session = null;
                    active = false;
                    status = "已停止。";
                }
            }
        }
    }
}
