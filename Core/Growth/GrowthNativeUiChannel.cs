using System;
using System.IO;
using System.IO.MemoryMappedFiles;
using System.Text;
using System.Threading;

namespace SoD2SE
{
    // The Iggy host reads complete snapshots under this mutex. Its synchronous
    // callbacks never wait for managed code or touch the game's save file.
    // Poll must be called by the runtime adapter on the game/UI thread.
    public sealed class GrowthNativeUiChannel : IDisposable
    {
        public const int Magic = 0x32575247, Version = 3, MaxRows = 256, MaxSelections = 64;
        public const int HeaderSize = 64, RowSize = 28, StringCapacity = 524288;
        public const int StringOffset = HeaderSize + MaxRows * RowSize;
        public const int CommandOffset = StringOffset + StringCapacity;
        public const int Capacity = CommandOffset + 16 + MaxSelections * 4;
        public const int MagicOffset = 0, VersionOffset = 4, CapacityOffset = 8, ShutdownOffset = 12,
            HeartbeatOffset = 16, BusyOffset = 20, TokenOffset = 24, RowCountOffset = 28, TextBytesOffset = 32,
            HeaderTextOffset = 36, StatusTextOffset = 44, RequestOffset = 52, AcknowledgedOffset = 56, ResultOffset = 60;
        public const int RowTitleOffset = 12, RowDescriptionOffset = 20,
            CommandTokenOffset = 4, CommandRowOffset = 8, CommandCountOffset = 12, CommandSelectionsOffset = 16;
        readonly GrowthPagePresenter presenter;
        readonly MemoryMappedFile mapping;
        readonly MemoryMappedViewAccessor view;
        readonly Mutex gate;
        readonly byte[] payloadBuffer = new byte[Capacity];
        int lastToken = -1, lastBusy = -1, lastPublished;
        bool disposed;
        public static string Name(int processId) { return "Local\\SoD2SE.Growth.v3." + processId; }
        public GrowthNativeUiChannel(int gameProcessId, GrowthPagePresenter pagePresenter)
        {
            if (gameProcessId <= 0 || pagePresenter == null) throw new ArgumentException("Invalid growth UI channel owner.");
            presenter = pagePresenter;
            bool fresh;
            gate = new Mutex(false, Name(gameProcessId) + ".Gate", out fresh);
            if (!fresh) { gate.Dispose(); throw new InvalidOperationException("Another growth UI owner already exists for this game."); }
            try {
                mapping = MemoryMappedFile.CreateNew(Name(gameProcessId), Capacity, MemoryMappedFileAccess.ReadWrite);
                view = mapping.CreateViewAccessor(0, Capacity, MemoryMappedFileAccess.ReadWrite);
                view.Write(MagicOffset, Magic); view.Write(VersionOffset, Version); view.Write(CapacityOffset, Capacity);
            } catch { if (view != null) view.Dispose(); if (mapping != null) mapping.Dispose(); gate.Dispose(); throw; }
        }
        bool TryLock()
        {
            try { return gate.WaitOne(0); }
            catch (AbandonedMutexException) { return true; }
        }
        public void Publish()
        {
            if (disposed) throw new ObjectDisposedException("GrowthNativeUiChannel");
            int token = presenter.Query(GrowthPageOp.Begin, 0, 0, 0).Number;
            int busy = token == 0 ? 0 : presenter.Query(GrowthPageOp.Busy, token, 0, 0).Number;
            int now = Environment.TickCount;
            if (token == lastToken && busy == lastBusy && unchecked((uint)(now - lastPublished)) < 100) return;
            using (var data = new MemoryStream(payloadBuffer, true))
            using (var writer = new BinaryWriter(data, new UTF8Encoding(false, true))) {
                int count = token == 0 ? 0 : presenter.Query(GrowthPageOp.Count, token, 0, 0).Number;
                if (count < 0 || count > MaxRows) throw new InvalidOperationException("Growth UI row capacity exceeded.");
                int cursor = StringOffset;
                Action<int, string> text = (at, value) => {
                    byte[] bytes = new UTF8Encoding(false, true).GetBytes(value ?? "");
                    if (bytes.Length > CommandOffset - cursor) throw new InvalidOperationException("Growth UI text capacity exceeded.");
                    data.Position = at; writer.Write(cursor - StringOffset); writer.Write(bytes.Length);
                    data.Position = cursor; writer.Write(bytes); cursor += bytes.Length;
                };
                text(HeaderTextOffset, token == 0 ? "" : presenter.Query(GrowthPageOp.Header, token, 0, 0).Text);
                text(StatusTextOffset, token == 0 ? "" : presenter.Query(GrowthPageOp.Status, token, 0, 0).Text);
                for (int i = 0; i < count; ++i) {
                    int offset = HeaderSize + i * RowSize;
                    data.Position = offset;
                    writer.Write(presenter.Query(GrowthPageOp.Kind, token, i, 0).Number);
                    writer.Write(presenter.Query(GrowthPageOp.Group, token, i, 0).Number);
                    writer.Write(presenter.Query(GrowthPageOp.Selected, token, i, 0).Number);
                    text(offset + RowTitleOffset, presenter.Query(GrowthPageOp.Title, token, i, 0).Text);
                    text(offset + RowDescriptionOffset, presenter.Query(GrowthPageOp.Description, token, i, 0).Text);
                }
                if (presenter.Query(GrowthPageOp.Begin, 0, 0, 0).Number != token) return;
                byte[] payload = payloadBuffer;
                if (!TryLock()) return;
                try {
                    view.Write(HeartbeatOffset, now); view.Write(BusyOffset, busy);
                    view.Write(TokenOffset, token); view.Write(RowCountOffset, count); view.Write(TextBytesOffset, cursor - StringOffset);
                    view.WriteArray(HeaderTextOffset, payload, HeaderTextOffset, RequestOffset - HeaderTextOffset);
                    view.WriteArray(HeaderSize, payload, HeaderSize, cursor - HeaderSize);
                    lastToken = token; lastBusy = busy; lastPublished = now;
                } finally { gate.ReleaseMutex(); }
            }
        }
        public GrowthCommand Poll()
        {
            if (disposed) return null;
            if (!TryLock()) return null;
            try {
                int request = view.ReadInt32(RequestOffset);
                if (request != view.ReadInt32(AcknowledgedOffset)) {
                    int operation = view.ReadInt32(CommandOffset), token = view.ReadInt32(CommandOffset + CommandTokenOffset), row = view.ReadInt32(CommandOffset + CommandRowOffset), count = view.ReadInt32(CommandOffset + CommandCountOffset);
                    int result = -3;
                    if (operation == (int)GrowthPageOp.Close) result = presenter.Query(GrowthPageOp.Close, token, 0, 0).Number;
                    else if (operation == (int)GrowthPageOp.Confirm && count >= 0 && count <= MaxSelections) {
                        // Validate every selected row before mutating local choices.
                        bool valid = token > 0 && token == presenter.Query(GrowthPageOp.Begin, 0, 0, 0).Number;
                        // Navigation, profession and equipment carry no choices.
                        // Reject injected selection lists before mutating the page.
                        valid = valid && (count == 0 || presenter.Query(GrowthPageOp.Kind, token, row, 0).Number == (int)GrowthPageRowKind.Confirm);
                        var chosen = new System.Collections.Generic.HashSet<int>();
                        for (int i = 0; valid && i < count; ++i) {
                            int index = view.ReadInt32(CommandOffset + CommandSelectionsOffset + i * 4);
                            valid = presenter.Query(GrowthPageOp.Kind, token, index, 0).Number == (int)GrowthPageRowKind.Choice &&
                                chosen.Add(presenter.Query(GrowthPageOp.Group, token, index, 0).Number);
                        }
                        if (valid) {
                            for (int i = 0; i < count; ++i) presenter.Query(GrowthPageOp.Choose, token, view.ReadInt32(CommandOffset + CommandSelectionsOffset + i * 4), 0);
                            result = presenter.Query(GrowthPageOp.Confirm, token, row, 0).Number;
                        }
                    }
                    view.Write(ResultOffset, result); view.Write(AcknowledgedOffset, request);
                }
            } finally { gate.ReleaseMutex(); }
            return presenter.TakeCommand();
        }
        public void Dispose()
        {
            if (disposed) return;
            disposed = true;
            if (TryLock()) { try { view.Write(ShutdownOffset, 1); view.Write(TokenOffset, 0); } finally { gate.ReleaseMutex(); } }
            view.Dispose(); mapping.Dispose(); gate.Dispose();
        }
    }
}
