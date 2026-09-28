using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Linq;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Forms;
using SoD2SE;

namespace SoD2SE.Loader
{
    // A deliberately small native Windows overlay for the first MCM release.
    // It stays outside the game process and therefore cannot corrupt the UE4
    // renderer. The loader owns its lifetime and closes it before patch restore.
    internal sealed class McmOverlay : IDisposable
    {
        readonly Thread thread;
        readonly ManualResetEvent ready = new ManualResetEvent(false);
        McmForm form;
        bool disposed;

        McmOverlay(Process game)
        {
            thread = new Thread(delegate() {
                try
                {
                    form = new McmForm(game);
                    ready.Set();
                    Application.Run(form);
                }
                catch (Exception error)
                {
                    Program.ReportMcmError(error);
                    ready.Set();
                }
            });
            thread.IsBackground = true;
            thread.Name = "SoD2SE MCM UI";
            thread.SetApartmentState(ApartmentState.STA);
        }

        public static McmOverlay Start(Process game)
        {
            var overlay = new McmOverlay(game);
            overlay.thread.Start();
            if (!overlay.ready.WaitOne(5000))
            {
                overlay.Dispose();
                throw new InvalidOperationException("MCM 界面线程启动超时。");
            }
            return overlay;
        }

        public void Dispose()
        {
            if (disposed) return;
            disposed = true;
            try
            {
                if (form != null && !form.IsDisposed)
                    form.BeginInvoke(new Action(form.Shutdown));
            }
            catch (InvalidOperationException) { }
            if (thread.IsAlive && !thread.Join(3000))
                Program.ReportMcmError(new InvalidOperationException("MCM 界面线程未能及时退出。"));
            ready.Dispose();
        }
    }

    internal sealed class McmForm : Form
    {
        // The overlay follows the shortcut stored by the MCM registry instead of
        // assuming F1, so the loader UI opens on the key the player configured.
        const int VkControl = 0x11, VkMenu = 0x12, VkShift = 0x10;
        const int SwRestore = 9;
        const int WsExToolWindow = 0x80;
        const int WsExNoActivate = 0x08000000;

        readonly Process game;
        readonly McmRegistry registry;
        readonly System.Windows.Forms.Timer timer;
        readonly ListBox pages = new ListBox();
        readonly Panel content = new Panel();
        readonly Label status = new Label();
        readonly Label title = new Label();
        bool shortcutDown;
        bool building;
        bool shuttingDown;
        bool menuVisible;

        [DllImport("user32.dll")] static extern short GetAsyncKeyState(int key);
        [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
        [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr window, out uint processId);
        [DllImport("user32.dll")] static extern bool GetWindowRect(IntPtr window, out RECT rect);
        [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr window);
        [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr window, int command);

        [StructLayout(LayoutKind.Sequential)]
        struct RECT
        {
            public int Left;
            public int Top;
            public int Right;
            public int Bottom;
        }

        public McmForm(Process target)
        {
            game = target;
            registry = McmRegistry.Current;
            if (registry == null) throw new InvalidOperationException("MCM 注册表尚未初始化。");
            Text = "SoD2SE Mod Configuration";
            FormBorderStyle = FormBorderStyle.None;
            StartPosition = FormStartPosition.Manual;
            ShowInTaskbar = false;
            TopMost = true;
            BackColor = Color.FromArgb(20, 25, 24);
            ForeColor = Color.FromArgb(232, 236, 226);
            Width = 960;
            Height = 650;
            KeyPreview = true;
            BuildChrome();
            pages.SelectedIndexChanged += delegate { BuildSelectedPage(); };
            timer = new System.Windows.Forms.Timer { Interval = 45 };
            timer.Tick += Poll;
            timer.Start();
            HideMenu();
        }

        protected override CreateParams CreateParams
        {
            get
            {
                var result = base.CreateParams;
                result.ExStyle |= WsExToolWindow;
                return result;
            }
        }

        void BuildChrome()
        {
            var header = new Panel { Dock = DockStyle.Top, Height = 82, BackColor = Color.FromArgb(34, 47, 43) };
            title.Text = "MOD CONFIGURATION";
            title.Font = new Font("Segoe UI", 16, FontStyle.Bold);
            title.ForeColor = Color.FromArgb(219, 190, 106);
            title.AutoSize = true;
            title.Location = new Point(26, 17);
            header.Controls.Add(title);
            var hint = new Label {
                Text = UiShortcut.Describe(MenuKey, MenuModifiers) + " 关闭菜单    Esc 关闭    修改将在下次启动时生效",
                AutoSize = true,
                ForeColor = Color.FromArgb(175, 190, 180),
                Location = new Point(28, 51)
            };
            header.Controls.Add(hint);
            var close = MakeButton("×", 48, 34);
            close.Anchor = AnchorStyles.Top | AnchorStyles.Right;
            close.Location = new Point(Width - 70, 20);
            close.Click += delegate { HideMenu(); };
            header.Controls.Add(close);
            Controls.Add(header);

            pages.Dock = DockStyle.Left;
            pages.Width = 260;
            pages.BorderStyle = BorderStyle.None;
            pages.BackColor = Color.FromArgb(26, 33, 31);
            pages.ForeColor = Color.FromArgb(225, 231, 220);
            pages.Font = new Font("Segoe UI", 10, FontStyle.Regular);
            pages.DrawMode = DrawMode.OwnerDrawFixed;
            pages.ItemHeight = 48;
            pages.DrawItem += DrawPage;
            Controls.Add(pages);

            content.Dock = DockStyle.Fill;
            content.Padding = new Padding(34, 26, 34, 20);
            content.BackColor = Color.FromArgb(22, 28, 27);
            Controls.Add(content);

            status.Dock = DockStyle.Bottom;
            status.Height = 28;
            status.TextAlign = ContentAlignment.MiddleLeft;
            status.ForeColor = Color.FromArgb(159, 181, 157);
            status.Padding = new Padding(18, 0, 0, 0);
            Controls.Add(status);
            PopulatePages();
        }

        void PopulatePages()
        {
            var snapshot = registry.Snapshot();
            pages.Items.Clear();
            foreach (var page in snapshot) pages.Items.Add(page);
            if (pages.Items.Count > 0) pages.SelectedIndex = 0;
            else status.Text = "当前没有发现 SoD2SE Mod。";
            BuildSelectedPage();
        }

        void DrawPage(object sender, DrawItemEventArgs e)
        {
            e.DrawBackground();
            if (e.Index < 0 || e.Index >= pages.Items.Count) return;
            var page = (McmPageSnapshot)pages.Items[e.Index];
            var color = (e.State & DrawItemState.Selected) != 0 ? Color.FromArgb(67, 83, 72) : pages.BackColor;
            using (var brush = new SolidBrush(color)) e.Graphics.FillRectangle(brush, e.Bounds);
            using (var brush = new SolidBrush(page.Loaded ? Color.FromArgb(214, 225, 199) : Color.FromArgb(156, 169, 159)))
                e.Graphics.DrawString(page.Name, pages.Font, brush, e.Bounds.Left + 18, e.Bounds.Top + 8);
            using (var brush = new SolidBrush(Color.FromArgb(133, 149, 138)))
                e.Graphics.DrawString(page.Loaded ? "已加载" : "未启用", new Font("Segoe UI", 8), brush, e.Bounds.Left + 18, e.Bounds.Top + 28);
        }

        void BuildSelectedPage()
        {
            if (building || pages.SelectedIndex < 0) return;
            var page = pages.SelectedItem as McmPageSnapshot;
            if (page == null) return;
            building = true;
            try
            {
                content.Controls.Clear();
                var heading = new Label { Text = page.Name, AutoSize = true, Font = new Font("Segoe UI", 17, FontStyle.Bold), ForeColor = Color.FromArgb(221, 229, 213), Location = new Point(content.Padding.Left, content.Padding.Top) };
                content.Controls.Add(heading);
                var description = new Label { Text = page.Description, AutoSize = false, Width = content.ClientSize.Width - 45, Height = 62, ForeColor = Color.FromArgb(165, 181, 170), Location = new Point(content.Padding.Left, content.Padding.Top + 42) };
                content.Controls.Add(description);
                int y = content.Padding.Top + 118;
                foreach (var option in page.Options)
                {
                    var box = new Panel { Left = content.Padding.Left, Top = y, Width = content.ClientSize.Width - 55, Height = 72, BackColor = Color.FromArgb(31, 40, 37) };
                    var label = new Label { Text = option.Label + (option.RequiresRestart ? "  [重启生效]" : ""), AutoSize = true, Font = new Font("Segoe UI", 10, FontStyle.Bold), ForeColor = Color.FromArgb(218, 226, 211), Location = new Point(18, 13) };
                    box.Controls.Add(label);
                    var help = new Label { Text = option.Description, AutoSize = true, ForeColor = Color.FromArgb(151, 170, 158), Location = new Point(18, 39) };
                    box.Controls.Add(help);
                    if (option.Type == McmOptionType.Boolean)
                    {
                        var check = new CheckBox { Checked = option.BoolValue, Text = option.BoolValue ? "开启" : "关闭", AutoSize = true, ForeColor = Color.FromArgb(220, 231, 211), BackColor = box.BackColor, Anchor = AnchorStyles.Top | AnchorStyles.Right, Location = new Point(box.Width - 105, 23) };
                        check.CheckedChanged += delegate { registry.SetBool(page.Id, option.Id, check.Checked); check.Text = check.Checked ? "开启" : "关闭"; status.Text = "已保存：" + page.Name + " / " + option.Label + "（下次启动生效）"; };
                        box.Controls.Add(check);
                    }
                    else
                    {
                        var number = new NumericUpDown { Minimum = option.Minimum, Maximum = option.Maximum, Value = option.IntValue, Width = 90, Anchor = AnchorStyles.Top | AnchorStyles.Right, Location = new Point(box.Width - 110, 21) };
                        number.ValueChanged += delegate { registry.SetInt(page.Id, option.Id, (int)number.Value); status.Text = "已保存：" + page.Name + " / " + option.Label + "（下次启动生效）"; };
                        box.Controls.Add(number);
                    }
                    content.Controls.Add(box);
                    y += 86;
                }
                var reset = MakeButton("恢复全部默认值", 150, 34);
                reset.Location = new Point(content.Padding.Left, y + 8);
                reset.Click += delegate { registry.ResetAll(); PopulatePages(); status.Text = "已恢复默认配置。"; };
                content.Controls.Add(reset);
            }
            finally { building = false; }
        }

        Button MakeButton(string text, int width, int height)
        {
            return new Button { Text = text, Width = width, Height = height, FlatStyle = FlatStyle.Flat, BackColor = Color.FromArgb(72, 91, 76), ForeColor = Color.FromArgb(237, 241, 229), FlatAppearance = { BorderColor = Color.FromArgb(114, 137, 109) } };
        }

        void Poll(object sender, EventArgs e)
        {
            bool down = ShortcutDown();
            if (down && !shortcutDown && (IsGameForeground() || menuVisible)) ToggleMenu();
            shortcutDown = down;
            if (menuVisible) PositionOverGame();
            if (game.HasExited && !shuttingDown) Shutdown();
        }

        int MenuKey { get { return registry == null ? McmKeys.MenuKey : registry.ShortcutKey; } }
        int MenuModifiers { get { return registry == null ? McmKeys.MenuModifiers : registry.ShortcutModifiers; } }

        static int DownModifiers()
        {
            int modifiers = 0;
            if ((GetAsyncKeyState(VkControl) & 0x8000) != 0) modifiers |= McmKeys.ControlModifier;
            if ((GetAsyncKeyState(VkMenu) & 0x8000) != 0) modifiers |= McmKeys.AltModifier;
            if ((GetAsyncKeyState(VkShift) & 0x8000) != 0) modifiers |= McmKeys.ShiftModifier;
            return modifiers;
        }

        bool ShortcutDown()
        {
            return (GetAsyncKeyState(MenuKey) & 0x8000) != 0 && DownModifiers() == MenuModifiers;
        }

        bool IsGameForeground()
        {
            uint processId;
            GetWindowThreadProcessId(GetForegroundWindow(), out processId);
            return processId == (uint)game.Id;
        }

        IntPtr GameWindow()
        {
            try { return game.MainWindowHandle; }
            catch (InvalidOperationException) { return IntPtr.Zero; }
        }

        void PositionOverGame()
        {
            var window = GameWindow();
            RECT rect;
            if (window == IntPtr.Zero || !GetWindowRect(window, out rect)) return;
            int width = Math.Min(Width, Math.Max(720, rect.Right - rect.Left - 80));
            int height = Math.Min(Height, Math.Max(500, rect.Bottom - rect.Top - 80));
            SetBounds(rect.Left + ((rect.Right - rect.Left) - width) / 2, rect.Top + ((rect.Bottom - rect.Top) - height) / 2, width, height);
        }

        void ToggleMenu()
        {
            if (menuVisible) HideMenu(); else ShowMenu();
        }

        void ShowMenu()
        {
            menuVisible = true;
            PopulatePages();
            PositionOverGame();
            Show();
            Activate();
        }

        void HideMenu()
        {
            menuVisible = false;
            Hide();
            var window = GameWindow();
            if (window != IntPtr.Zero) { ShowWindow(window, SwRestore); SetForegroundWindow(window); }
        }

        protected override bool ProcessCmdKey(ref Message message, Keys keyData)
        {
            if (keyData == Keys.Escape && menuVisible) { HideMenu(); return true; }
            return base.ProcessCmdKey(ref message, keyData);
        }

        public void Shutdown()
        {
            if (shuttingDown) return;
            shuttingDown = true;
            timer.Stop();
            if (!IsDisposed) Close();
        }
    }
}
