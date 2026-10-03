using System;
using System.Linq;
using SoD2SE;
using SoD2SE.GameApi;

static class GameApiSmoke
{
    static void Check(bool value, string message)
    {
        if (!value) throw new Exception(message);
    }

    static int Main()
    {
        try
        {
            var api = StateOfDecay2GameApi.Create();
            Check(api.Id == "sod2.update38.2", "unexpected Game API id");
            Check(api.Target.BuildId == StateOfDecay2GameApi.BuildId, "target build mismatch");
            Check(api.GetPatches(StateOfDecay2Capabilities.Followers).Count == 2, "follower patch set mismatch");
            Check(api.GetPatches(StateOfDecay2Capabilities.Community).Count == 11, "community patch set mismatch");
            Check(api.GetNativeHook(StateOfDecay2Capabilities.MeleeAction).Rva == 0x341320, "action hook metadata mismatch");
            Check(api.GetNativeHook(StateOfDecay2Capabilities.MeleeAnimation).Rva == 0x1C88F50, "animation hook metadata mismatch");
            Check(!api.Capabilities.IsAvailable(StateOfDecay2Capabilities.Community), "unverified API was reported available");
            Check(!api.Capabilities.IsAvailable(StateOfDecay2Capabilities.RogueliteKillEvents) &&
                  !api.Capabilities.IsAvailable(StateOfDecay2Capabilities.SurvivorIdentity) &&
                  !api.Capabilities.IsAvailable(StateOfDecay2Capabilities.SurvivorAttributes) &&
                  !api.Capabilities.IsAvailable(StateOfDecay2Capabilities.SinglePlayerPause) &&
                  !api.Capabilities.IsAvailable(StateOfDecay2Capabilities.NativeProgressionUi),
                "unverified roguelite capability was reported available");
            var duplicateIds = api.GetPatches(StateOfDecay2Capabilities.Community).GroupBy(item => item.Name).Where(group => group.Count() > 1).ToList();
            Check(duplicateIds.Count == 0, "duplicate Game API patch names");
            Console.WriteLine("PASS: centralized StateOfDecay2 Game API target, patch sets, native hook metadata and capability gates");
            return 0;
        }
        catch (Exception error)
        {
            Console.Error.WriteLine("FAIL: " + error.Message);
            return 1;
        }
    }
}
