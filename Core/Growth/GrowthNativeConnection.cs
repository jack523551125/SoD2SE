using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Diagnostics;
using System.IO;
using System.IO.MemoryMappedFiles;
using System.Threading;
using W = SoD2SE.GrowthNativeProtocol;

namespace SoD2SE
{
    public enum GrowthNativeState { AwaitingFrame, Observing, OutsideCampaign, CampaignUnavailable, RosterUnavailable, Failed, Stopped, LoadingScreenUnavailable, LoadingScreenPresent, ReadinessUnavailable, OriginalHideRequired, MatchNotInProgress }
    // Native UObject tokens describe a process-local incarnation only. Candidate
    // identifiers here deliberately cannot be passed as GrowthActorFrame.Identity.
    public sealed class GrowthNativeToken
    {
        public int Index { get; private set; }
        public int Serial { get; private set; }
        internal bool Valid { get { return Index >= 0 && Serial > 0; } }
        internal bool Absent { get { return Index == -1 && Serial == 0; } }
        internal GrowthNativeToken(byte[] data, int offset) { Index = BitConverter.ToInt32(data, offset); Serial = BitConverter.ToInt32(data, offset + W.TokenSerialOffset); }
    }
    public sealed class GrowthNativeActor
    {
        public GrowthNativeToken Character { get; private set; }
        public GrowthNativeToken Pawn { get; private set; }
        public GrowthNativeToken Component { get; private set; }
        public int CandidateLocalId { get; private set; }
        public ulong CandidateNarrativeId { get; private set; }
        public ulong CandidateEntityId { get; private set; }
        public uint RawPawnMode { get; private set; }
        public bool Dead { get; private set; }
        public bool Controlled { get; private set; }
        internal GrowthNativeActor(byte[] data, int offset)
        {
            Character = new GrowthNativeToken(data, offset + W.ActorCharacterOffset); Pawn = new GrowthNativeToken(data, offset + W.ActorPawnOffset); Component = new GrowthNativeToken(data, offset + W.ActorComponentOffset);
            CandidateLocalId = BitConverter.ToInt32(data, offset + W.ActorCandidateLocalIdOffset);
            uint flags = BitConverter.ToUInt32(data, offset + W.ActorFlagsOffset);
            if ((flags & ~3u) != 0 || BitConverter.ToUInt32(data, offset + W.ActorReservedOffset) != 0) throw new InvalidDataException("Invalid native actor flags.");
            Dead = (flags & 1) != 0; Controlled = (flags & 2) != 0;
            if (!Character.Valid || (!Pawn.Valid && !Pawn.Absent) || (!Component.Valid && !Component.Absent) || (Controlled && (Dead || !Pawn.Valid || !Component.Valid)))
                throw new InvalidDataException("Invalid native actor incarnation.");
            CandidateNarrativeId = BitConverter.ToUInt64(data, offset + W.ActorCandidateNarrativeIdOffset); CandidateEntityId = BitConverter.ToUInt64(data, offset + W.ActorCandidateEntityIdOffset);
            RawPawnMode = BitConverter.ToUInt32(data, offset + W.ActorRawPawnModeOffset);
            if (RawPawnMode > 255) throw new InvalidDataException("Invalid diagnostic pawn mode.");
        }
    }
    public sealed class GrowthNativeObservation
    {
        public ulong FrameSerial { get; private set; }
        public GrowthNativeState State { get; private set; }
        public uint Error { get; private set; }
        public GrowthNativeToken World { get; private set; }
        public GrowthNativeToken GameMode { get; private set; }
        public GrowthNativeToken GameInstance { get; private set; }
        public GrowthNativeToken Enclave { get; private set; }
        public GrowthNativeToken Controller { get; private set; }
        public uint RawCampaignMode { get; private set; }
        public bool CampaignContent { get; private set; }
        public bool LoadingScreenPresent { get; private set; } // Absence does not prove complete world readiness.
        public int ControlledActor { get; private set; } // 128 explicitly means none
        public ReadOnlyCollection<GrowthNativeActor> Actors { get; private set; }
        internal GrowthNativeObservation(byte[] data)
        {
            FrameSerial = BitConverter.ToUInt64(data, W.FrameSerialOffset);
            uint state = BitConverter.ToUInt32(data, W.StateOffset);
            if (state > 11) throw new InvalidDataException("Unknown native host state.");
            State = (GrowthNativeState)state; Error = BitConverter.ToUInt32(data, W.ErrorOffset);
            World = new GrowthNativeToken(data, W.WorldOffset); GameMode = new GrowthNativeToken(data, W.GameModeOffset); GameInstance = new GrowthNativeToken(data, W.GameInstanceOffset);
            Enclave = new GrowthNativeToken(data, W.EnclaveOffset); Controller = new GrowthNativeToken(data, W.ControllerOffset);
            RawCampaignMode = BitConverter.ToUInt32(data, W.RawCampaignModeOffset);
            uint flags = BitConverter.ToUInt32(data, W.FlagsOffset), count = BitConverter.ToUInt32(data, W.ActorCountOffset), controlled = BitConverter.ToUInt32(data, W.ControlledActorOffset);
            if (count > 128 || (controlled != 128 && controlled >= count) || (flags & ~3u) != 0 || RawCampaignMode > 255)
                throw new InvalidDataException("Invalid native roster bounds.");
            CampaignContent = (flags & 1) != 0; ControlledActor = (int)controlled;
            LoadingScreenPresent = (flags & 2) != 0;
            if (LoadingScreenPresent != (State == GrowthNativeState.LoadingScreenPresent)) throw new InvalidDataException("Invalid native loading-screen marker.");
            if ((State == GrowthNativeState.LoadingScreenPresent || State == GrowthNativeState.LoadingScreenUnavailable ||
                State == GrowthNativeState.ReadinessUnavailable || State == GrowthNativeState.OriginalHideRequired || State == GrowthNativeState.MatchNotInProgress) &&
                (!CampaignContent || FrameSerial == 0 || !World.Valid || !GameMode.Valid || !GameInstance.Valid))
                throw new InvalidDataException("Invalid loading-screen campaign incarnation.");
            if (State == GrowthNativeState.Observing && (!CampaignContent || FrameSerial == 0 || controlled == 128)) throw new InvalidDataException("Invalid observed campaign frame.");
            if (State == GrowthNativeState.Observing && (!World.Valid || !GameMode.Valid || !GameInstance.Valid || !Enclave.Valid || !Controller.Valid))
                throw new InvalidDataException("Invalid native campaign incarnation.");
            if (State != GrowthNativeState.Observing && (count != 0 || controlled != 128)) throw new InvalidDataException("Unavailable frame retained actors.");
            var actors = new List<GrowthNativeActor>((int)count);
            for (int i = 0; i < count; i++) {
                var actor = new GrowthNativeActor(data, W.ActorsOffset + i * W.ActorSize);
                if (actor.Controlled != (controlled == i)) throw new InvalidDataException("Native possession marker mismatch.");
                actors.Add(actor);
            }
            Actors = actors.AsReadOnly();
        }
    }
    public static class GrowthNativeProtocol
    {
        public const int Version = 3, Size = 7288;
        public const uint Magic = 0x33484c47;
        public const int ActorSize = 56, TokenSerialOffset = 4, ChannelOffset = 0;
        public const int MagicOffset = 0, VersionOffset = 4, SizeOffset = 8, OwnerPidOffset = 12,
            NonceLowOffset = 16, NonceHighOffset = 24, HeartbeatOffset = 32, StopOffset = 36, HostPidOffset = 40, ReservedOffset = 44;
        public const int FrameSerialOffset = 48, StateOffset = 56, ErrorOffset = 60, WorldOffset = 64, GameModeOffset = 72,
            GameInstanceOffset = 80, EnclaveOffset = 88, ControllerOffset = 96, RawCampaignModeOffset = 104, FlagsOffset = 108,
            ActorCountOffset = 112, ControlledActorOffset = 116, ActorsOffset = 120;
        public const int ActorCharacterOffset = 0, ActorPawnOffset = 8, ActorComponentOffset = 16, ActorCandidateLocalIdOffset = 24,
            ActorFlagsOffset = 28, ActorCandidateNarrativeIdOffset = 32, ActorCandidateEntityIdOffset = 40, ActorRawPawnModeOffset = 48, ActorReservedOffset = 52;

        public static GrowthNativeObservation Decode(byte[] data, int ownerPid, int gamePid, ulong nonceLow, ulong nonceHigh)
        {
            if (data == null || data.Length != Size) throw new InvalidDataException("Native host message size mismatch.");
            uint hostPid = BitConverter.ToUInt32(data, W.HostPidOffset);
            if (ownerPid <= 0 || gamePid <= 0 || (nonceLow == 0 && nonceHigh == 0) ||
                BitConverter.ToUInt32(data, W.MagicOffset) != Magic || BitConverter.ToUInt32(data, W.VersionOffset) != Version || BitConverter.ToUInt32(data, W.SizeOffset) != Size ||
                BitConverter.ToUInt32(data, W.OwnerPidOffset) != ownerPid || BitConverter.ToUInt64(data, W.NonceLowOffset) != nonceLow || BitConverter.ToUInt64(data, W.NonceHighOffset) != nonceHigh ||
                (hostPid != 0 && hostPid != gamePid) || BitConverter.ToUInt32(data, W.ReservedOffset) != 0 || BitConverter.ToUInt32(data, W.StopOffset) > 1)
                throw new InvalidDataException("Native host owner/version mismatch.");
            var observation = new GrowthNativeObservation(data);
            if (hostPid == 0 && observation.State != GrowthNativeState.AwaitingFrame) throw new InvalidDataException("Native host not acknowledged.");
            return observation;
        }
    }
    // Explicit connection for the production bootstrap and integration probes.
    // Observations arrive on a worker, never as fake game-thread callbacks. This
    // is not IGrowthRuntimeAdapter and does not declare gameplay features valid.
    public sealed class GrowthNativeConnection : IDisposable
    {
        readonly object sync = new object();
        readonly int ownerPid, gamePid;
        readonly ulong nonceLow, nonceHigh;
        MemoryMappedFile mapping;
        MemoryMappedViewAccessor view;
        Mutex gate;
        Timer timer;
        bool disposed;
        GrowthNativeObservation latest;
        Exception error;
        public GrowthNativeObservation Latest { get { lock (sync) { return latest; } } }
        public Exception Failure { get { lock (sync) { return error; } } }
        GrowthNativeConnection(int targetPid)
        {
            gamePid = targetPid;
            using (var process = Process.GetCurrentProcess()) ownerPid = process.Id;
            var nonce = Guid.NewGuid().ToByteArray(); nonceLow = BitConverter.ToUInt64(nonce, 0); nonceHigh = BitConverter.ToUInt64(nonce, 8);
            string name = "Local\\SoD2SE.Growth.Native.v3." + gamePid;
            try {
                mapping = MemoryMappedFile.CreateNew(name, GrowthNativeProtocol.Size);
                view = mapping.CreateViewAccessor(0, GrowthNativeProtocol.Size);
                bool created; gate = new Mutex(false, name + ".Gate", out created);
                if (!created) throw new InvalidOperationException("原生成长连接已存在。 / A native growth connection already exists.");
                gate.WaitOne();
                try {
                    view.WriteArray(W.ChannelOffset, new byte[GrowthNativeProtocol.Size], 0, GrowthNativeProtocol.Size);
                    view.Write(W.MagicOffset, GrowthNativeProtocol.Magic); view.Write(W.VersionOffset, GrowthNativeProtocol.Version); view.Write(W.SizeOffset, GrowthNativeProtocol.Size);
                    view.Write(W.OwnerPidOffset, ownerPid); view.Write(W.NonceLowOffset, nonceLow); view.Write(W.NonceHighOffset, nonceHigh); view.Write(W.HeartbeatOffset, unchecked((uint)Environment.TickCount));
                    view.Write(W.RawCampaignModeOffset, 255u); view.Write(W.ControlledActorOffset, 128u);
                } finally { gate.ReleaseMutex(); }
                // Keep the lease alive while the remote startup hashes the image.
                timer = new Timer(Poll, null, 0, 250);
            } catch { Dispose(); throw; }
        }
        public static GrowthNativeConnection Start(Process game, string nativeLibrary)
        {
            if (game == null) throw new ArgumentNullException("game");
            if (game.HasExited) throw new InvalidOperationException("游戏进程已经退出。 / The game has exited.");
            nativeLibrary = Path.GetFullPath(nativeLibrary);
            if (!File.Exists(nativeLibrary)) throw new FileNotFoundException("缺少原生成长模块。 / Native growth module missing.", nativeLibrary);
            var connection = new GrowthNativeConnection(game.Id);
            try { NativePluginModule.LoadAndStart(game, nativeLibrary, "SoD2GrowthStart", "Local\\SoD2SE.Growth.Native.v3." + game.Id); return connection; }
            catch { connection.Dispose(); throw; }
        }
        void Poll(object unused)
        {
            lock (sync) {
                if (disposed || error != null) return;
                bool locked = false;
                try {
                    try { locked = gate.WaitOne(10); }
                    catch (AbandonedMutexException) { locked = true; throw new InvalidDataException("Native growth channel mutex abandoned."); }
                    if (!locked) return;
                    var data = new byte[GrowthNativeProtocol.Size]; view.ReadArray(W.ChannelOffset, data, 0, data.Length);
                    latest = GrowthNativeProtocol.Decode(data, ownerPid, gamePid, nonceLow, nonceHigh);
                    view.Write(W.HeartbeatOffset, unchecked((uint)Environment.TickCount));
                } catch (Exception failure) { error = failure; }
                finally { if (locked) gate.ReleaseMutex(); }
            }
        }
        public void Dispose()
        {
            lock (sync) {
                if (disposed) return; disposed = true;
                if (timer != null) { timer.Dispose(); timer = null; }
                try {
                    if (gate != null && view != null) {
                        bool locked = false;
                        try {
                            try { locked = gate.WaitOne(10); } catch (AbandonedMutexException) { locked = true; }
                            if (locked && view.ReadUInt64(W.NonceLowOffset) == nonceLow && view.ReadUInt64(W.NonceHighOffset) == nonceHigh && view.ReadUInt32(W.OwnerPidOffset) == ownerPid) view.Write(W.StopOffset, 1u);
                        } finally { if (locked) gate.ReleaseMutex(); }
                    }
                } catch (Exception failure) { if (error == null) error = failure; }
                finally {
                    try { if (view != null) { view.Dispose(); view = null; } }
                    finally {
                        try { if (mapping != null) { mapping.Dispose(); mapping = null; } }
                        finally { if (gate != null) { gate.Dispose(); gate = null; } }
                    }
                }
            }
        }
    }
}
