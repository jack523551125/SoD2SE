using System;
using SoD2SE;
using SoD2SE.GameApi;

namespace SoD2SE.UnlimitedFollowers
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
        public string Id { get { return "unlimited-followers"; } }
        public string Name { get { return "无限随从 / Unlimited Followers"; } }
        public string Description { get { return "解除 Update 38.2 原版邀请随从数量限制，保留重复、关系和任务条件。 / Removes the Update 38.2 follower invitation limit while keeping duplicate, relationship, and mission checks."; } }
        public bool IsActive { get { lock (sync) return active; } }
        public string Status { get { lock (sync) return status; } }

        public void RegisterMcm(McmRegistry registry)
        {
            registry.RegisterPlugin(Id,
                new McmLocalizedText("无限随从", "Unlimited Followers"),
                new McmLocalizedText("解除 Update 38.2 原版邀请随从数量限制，保留重复、关系和任务条件。", "Removes the Update 38.2 follower invitation limit while keeping duplicate, relationship, and mission conditions."));
        }

        public void Initialize(IGameSession game)
        {
            if (game == null) throw new ArgumentNullException("game");
            lock (sync)
            {
                if (session != null) throw new InvalidOperationException("无限随从插件已经初始化。");
                runtime = GameRuntimeAccess.For(game);
                session = game;
                if (runtime.Api is StateOfDecay2GameApi && !runtime.Api.Capabilities.IsAvailable(StateOfDecay2Capabilities.Followers))
                {
                    active = false;
                    status = "已降级：" + runtime.Api.Capabilities.Reason(StateOfDecay2Capabilities.Followers);
                    Console.Error.WriteLine("[UnlimitedFollowers] " + status);
                    return;
                }
                var patches = runtime.Api.GetPatches(StateOfDecay2Capabilities.Followers);
                if (patches.Count == 0) patches = StateOfDecay2GameApi.GetCompatibilityPatches(StateOfDecay2Capabilities.Followers);
                lease = runtime.Hooks.Acquire(HookRequest.BytePatch(Id, StateOfDecay2Capabilities.Followers,
                    runtime.Api.Target.Sha256, patches));
                active = true;
                status = "已启用。";
                runtime.Events.Publish(new GameEvent(GameEventIds.FollowerGate, Id, 0, 0, new GameObjectToken(), lease.ChangedBytes, 0, 1, "enabled"));
                Console.WriteLine("[UnlimitedFollowers] 已加载；统一 Hook Broker 接管补丁位置：" + patches.Count + "；本次修改：" + lease.ChangedBytes + " 处。");
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
                        Console.WriteLine("[UnlimitedFollowers] 已还原；统一 Hook Broker 已释放补丁。");
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
