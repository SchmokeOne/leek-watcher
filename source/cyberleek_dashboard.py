"""Native desktop dashboard for the Cyberleek monitoring engine."""
import copy
import datetime as dt
import os
import json
import re
import urllib.parse
import webbrowser
from pathlib import Path
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, colorchooser, messagebox
from tkinter import font as tkfont
from dashboard_adapter import engine

BG = '#0c1218'
CARD = '#141e28'
TEXT = '#e7edf3'
MUTED = '#8295a7'
ACCENT = '#64dfb2'


def windows_window_api(root):
    """Return the native top-level HWND and typed placement/monitor APIs."""
    import ctypes
    from ctypes import wintypes
    class MonitorInfo(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('monitor', wintypes.RECT),
                    ('work', wintypes.RECT), ('flags', wintypes.DWORD)]
    class WindowPlacement(ctypes.Structure):
        _fields_ = [('length', wintypes.UINT), ('flags', wintypes.UINT),
                    ('show', wintypes.UINT), ('minimum', wintypes.POINT),
                    ('maximum', wintypes.POINT), ('normal', wintypes.RECT)]
    api = ctypes.WinDLL('user32', use_last_error=True)
    api.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    api.GetAncestor.restype = wintypes.HWND
    api.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    api.MonitorFromWindow.restype = wintypes.HANDLE
    api.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
    api.GetWindowPlacement.argtypes = [wintypes.HWND, ctypes.POINTER(WindowPlacement)]
    api.SetWindowPlacement.argtypes = [wintypes.HWND, ctypes.POINTER(WindowPlacement)]
    api.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    hwnd = api.GetAncestor(root.winfo_id(), 2)
    return api, hwnd, MonitorInfo, WindowPlacement


class Dashboard:
    def __init__(self, root, offline=False):
        self.root = root
        # Use explicit pixel fonts so Windows DPI cannot enlarge content beyond the viewport.
        root.tk.call('tk', 'scaling', 1.0)
        self.resize_job = None
        self.font_widgets = []
        self.panels = []
        self.tree_widths = []
        self.events = queue.Queue(maxsize=2500)
        self.ready = False
        self.offline = offline
        self.last_poll = None
        self.fullscreen = False
        self.started_at = time.monotonic()
        self.config_path = Path.cwd() / 'watcher_config.json'
        self.preferences_path = Path.cwd() / 'dashboard_preferences.json'
        self.config = engine.load_config(str(self.config_path))
        engine._download_dir = os.path.abspath(self.config.get('download_dir', './leaks'))
        engine._mask_spoilers = self.config.get('mask_spoilers', False)
        engine.log_msg = self.log
        engine.set_status = lambda text: None
        root.title('Cyberleek • Watcher')
        width = min(1760, root.winfo_screenwidth() - 80)
        height = min(980, root.winfo_screenheight() - 100)
        root.geometry(f'{width}x{height}+30+30')
        root.minsize(1280, 900)
        root.configure(bg=BG)
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.bind('<F11>', lambda event: self.toggle_fullscreen())
        root.bind('<Escape>', lambda event: self.exit_fullscreen())
        style = ttk.Style(root)
        self.style = style
        style.theme_use('clam')
        style.configure('TProgressbar', background=ACCENT, troughcolor='#23323f', borderwidth=0, lightcolor=ACCENT, darkcolor=ACCENT)
        style.configure('Treeview', background=CARD, fieldbackground=CARD, foreground=TEXT, rowheight=29, borderwidth=0, font=('Segoe UI', 10))
        style.configure('Treeview.Heading', background='#1d2b38', foreground=MUTED, font=('Segoe UI', 9), relief='flat')
        style.map('Treeview', background=[('selected', '#285044')])
        shell = tk.Frame(root, bg=BG)
        self.shell = shell
        shell.pack(fill='both', expand=True, padx=28, pady=22)
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(2, weight=1)
        header = tk.Frame(shell, bg=BG)
        header.grid(row=0, column=0, sticky='ew', pady=(0, 12))
        self.label(header, '●', 28, ACCENT).pack(side='left', padx=(0, 12))
        brand = tk.Frame(header, bg=BG)
        brand.pack(side='left')
        self.label(brand, 'CYBERLEEK', 22, TEXT, bold=True).pack(anchor='w')
        self.label(brand, 'On-chain intelligence  /  Live overview', 10).pack(anchor='w')
        self.state = self.label(header, 'PREVIEW' if offline else 'CONNECTING', 10, ACCENT, bold=True)
        self.state.pack(side='right')
        self.fullscreen_button = self.button(header, 'Fullscreen · F11', self.toggle_fullscreen)
        self.fullscreen_button.pack(side='right', padx=(10, 0))
        self.button(header, 'Credits', self.open_credits).pack(side='right', padx=(10, 0))
        self.button(header, 'Appearance', self.open_appearance).pack(side='right', padx=(10, 0))
        self.button(header, 'Open downloads ↗', self.open_downloads).pack(side='right', padx=20)
        self.button(header, 'Open CyberLeek site ↗', lambda: webbrowser.open('https://wayfinder.ar.io/?q=cyberleek')).pack(side='right', padx=(10, 0))
        metrics = tk.Frame(shell, bg=BG)
        metrics.grid(row=1, column=0, sticky='ew')
        self.values = {}
        self.metric_titles = {}
        self.metric_details = {}
        for i, (key, title, detail) in enumerate([
            ('mcap', 'MARKET CAPITALIZATION', 'CoinGecko · USD'),
            ('price', 'TOKEN PRICE', 'USD · DexScreener'),
            ('reserve', 'DEVELOPER RESERVE', 'Tracked token accounts'),
            ('accounts', 'DISCOVERED LINKS', 'On-chain asset entries'),
        ]):
            metrics.columnconfigure(i, weight=1, uniform='metric')
            card = self.panel(metrics)
            card.grid(row=0, column=i, sticky='nsew', padx=(0 if i == 0 else 8, 0), pady=(0, 16))
            self.metric_titles[key] = self.label(card, title, 9)
            self.metric_titles[key].pack(anchor='w')
            self.values[key] = self.label(card, '—', 27, TEXT, bold=True)
            self.values[key].pack(anchor='w', pady=(9, 4))
            self.metric_details[key] = self.label(card, detail, 9)
            self.metric_details[key].pack(anchor='w')
        body = tk.Frame(shell, bg=BG)
        body.grid(row=2, column=0, sticky='nsew')
        body.columnconfigure(0, weight=4, uniform='columns')
        body.columnconfigure(1, weight=3, uniform='columns')
        body.columnconfigure(2, weight=3, uniform='columns')
        body.rowconfigure(0, weight=1)
        body.rowconfigure(1, weight=1)
        poll = self.panel(body)
        poll.grid(row=0, column=0, sticky='nsew', padx=(0, 12), pady=(0, 12))
        self.label(poll, 'COMMUNITY POLL', 10, ACCENT, bold=True).pack(anchor='w')
        self.poll_title = self.label(poll, 'Waiting for on-chain state…', 15, TEXT, bold=True)
        self.poll_title.pack(anchor='w', pady=(8, 3))
        self.poll_meta = self.label(poll, 'Live vote distribution will appear here', 10)
        self.poll_meta.pack(anchor='w', pady=(0, 12))
        self.votes = self.tree(poll, ('Option', 'Tokens', 'Share', 'USD'), (180, 95, 65, 85), height=2)
        self.label(poll, 'SELECTED POOL  /  MARKET ACTIVITY', 9, ACCENT, bold=True).pack(anchor='w', pady=(9, 5))
        market_grid = tk.Frame(poll, bg=CARD)
        market_grid.pack(fill='x')
        self.market_details = {}
        for index, (key, title) in enumerate([
            ('liquidity', 'LIQUIDITY'), ('volume', '24H VOLUME'),
            ('fdv', 'FDV'), ('trades', '24H BUYS / SELLS'),
            ('m5', '5M CHANGE'), ('h1', '1H CHANGE'),
            ('h6', '6H CHANGE'), ('h24', '24H CHANGE'),
        ]):
            column = index % 4
            market_grid.columnconfigure(column, weight=1, uniform='market')
            cell = tk.Frame(market_grid, bg=CARD)
            cell.grid(row=index // 4, column=column, sticky='ew', pady=3)
            self.label(cell, title, 8).pack(anchor='w')
            self.market_details[key] = self.label(cell, '—', 12, TEXT, bold=True)
            self.market_details[key].pack(anchor='w')
        milestones = self.panel(body)
        milestones.grid(row=0, column=1, sticky='nsew', padx=(0, 12), pady=(0, 12))
        self.label(milestones, 'MILESTONE PROGRESS', 10, ACCENT, bold=True).pack(anchor='w', pady=(0, 10))
        self.tiers = []
        for index, (target, title) in enumerate(engine.MCAP_MILESTONES):
            row = tk.Frame(milestones, bg=CARD)
            row.pack(fill='x', pady=4)
            label = self.label(row, '', 10, TEXT)
            label.pack(anchor='w')
            bar = ttk.Progressbar(row, maximum=100)
            bar.pack(fill='x', pady=(4, 0))
            self.tiers.append((label, bar, target, title, index))
        activity = self.panel(body)
        activity.grid(row=1, column=0, sticky='nsew', padx=(0, 12))
        self.label(activity, 'MARKET CAP  /  LAST HOUR', 10, ACCENT, bold=True).pack(anchor='w')
        self.market_status = self.label(activity, 'Waiting for market data…', 9)
        self.market_status.pack(anchor='w', pady=(4, 4))
        self.market_chart = tk.Canvas(activity, height=115, bg=CARD, highlightthickness=0)
        self.market_chart.pack(fill='x', pady=(0, 9))
        self.market_chart.bind('<Configure>', lambda event: self.draw_market_chart())
        top = tk.Frame(activity, bg=CARD)
        top.pack(fill='x', pady=(0, 10))
        self.label(top, 'ACTIVITY FEED', 10, ACCENT, bold=True).pack(side='left')
        self.button(top, 'Clear', lambda: self.feed.delete('1.0', 'end')).pack(side='right')
        self.feed = tk.Text(activity, bg=CARD, fg=MUTED, insertbackground=TEXT, relief='flat', wrap='word', font=('Consolas', 10), height=5)
        scroll = ttk.Scrollbar(activity, command=self.feed.yview)
        scroll.pack(side='right', fill='y')
        self.feed.configure(yscrollcommand=scroll.set)
        self.feed.pack(fill='both', expand=True)
        self.feed.tag_configure('alert', foreground=ACCENT)
        self.feed.tag_configure('error', foreground='#ffad87')
        self.feed.bind('<Key>', lambda e: 'break' if not (e.state & 4 and e.keysym.lower() in ('c', 'a')) else None)
        controls = self.panel(body)
        controls.grid(row=1, column=1, sticky='nsew', padx=(0, 12))
        self.label(controls, 'MONITOR & CONTROLS', 10, ACCENT, bold=True).pack(anchor='w')
        self.health = self.label(controls, 'Initializing…', 10, TEXT)
        self.health.pack(anchor='w', pady=(8, 4))
        self.freshness = self.label(controls, 'No observations yet', 9)
        self.freshness.pack(anchor='w', pady=(0, 10))
        rate_row = tk.Frame(controls, bg=CARD)
        rate_row.pack(fill='x')
        self.label(rate_row, 'Update every', 10, TEXT).pack(side='left')
        self.rate = tk.StringVar(value=str(self.config.get('poll_interval_seconds', 15)))
        self.rate_input = tk.Spinbox(rate_row, from_=5, to=3600, textvariable=self.rate, width=6, bg='#21313f', fg=TEXT, insertbackground=TEXT, buttonbackground='#21313f', relief='flat', font=('Segoe UI', 10))
        self.rate_input.pack(side='left', padx=8)
        self.rate_input.bind('<Return>', lambda event: self.apply_rate())
        self.label(rate_row, 'seconds', 9).pack(side='left')
        self.rate_apply = self.button(rate_row, 'Apply', self.apply_rate)
        self.rate_apply.pack(side='right')
        self.countdown_label = self.label(controls, 'Waiting for monitor…', 9)
        self.countdown_label.pack(anchor='w', pady=(5, 3))
        self.countdown_bar = ttk.Progressbar(controls, maximum=100)
        self.countdown_bar.pack(fill='x', pady=(0, 7))
        self.toggles = []
        toggle_grid = tk.Frame(controls, bg=CARD)
        toggle_grid.pack(fill='x')
        toggle_grid.columnconfigure(0, weight=1)
        toggle_grid.columnconfigure(1, weight=1)
        for index, (label, attr, config_key, inverse) in enumerate([
            ('Mask spoilers', '_mask_spoilers', 'mask_spoilers', False),
            ('Audio alerts', '_enable_sound', 'enable_sound', False),
            ('Download new assets', '_watch_only', 'download_payloads', True),
            ('Automatically open media', '_auto_open', 'auto_open_media', False),
        ]):
            var = tk.BooleanVar(value=self.config.get(config_key, True))
            widget = tk.Checkbutton(toggle_grid, text=label, variable=var, command=lambda a=attr, v=var, inv=inverse: self.toggle(a, v, inv), bg=CARD, fg=TEXT, selectcolor='#243745', activebackground=CARD, activeforeground=ACCENT, font=('Segoe UI', 10), anchor='w', borderwidth=0)
            widget.grid(row=index // 2, column=index % 2, sticky='ew', pady=2)
            self.toggles.append((var, attr, inverse, widget))
        actions = tk.Frame(controls, bg=CARD)
        actions.pack(fill='x', pady=(10, 0))
        self.action_buttons = []
        for index, (title, action) in enumerate([('Export snapshot', self.export), ('Backfill assets', lambda: self.action('a')), ('Extract archives', lambda: self.action('x')), ('Test sound', self.test_sound)]):
            button = self.button(actions, title, action)
            actions.columnconfigure(index % 2, weight=1, uniform='action')
            button.grid(row=index // 2, column=index % 2, sticky='ew', padx=(0, 5), pady=2)
            self.action_buttons.append(button)
        diagnostics = self.panel(body)
        diagnostics.grid(row=0, column=2, sticky='nsew', pady=(0, 12))
        self.label(diagnostics, 'CONNECTION DIAGNOSTICS', 10, ACCENT, bold=True).pack(anchor='w')
        self.rpc_summary = self.label(diagnostics, 'No RPC requests observed yet', 9)
        self.rpc_summary.pack(anchor='w', pady=(6, 6))
        self.rpc_table = self.tree(diagnostics, ('Endpoint', 'Latency', 'State'), (175, 65, 90), height=2)
        self.rpc_table.bind('<Double-1>', self.show_rpc_detail)
        self.label(diagnostics, 'DOWNLOADS  /  MIRROR ATTEMPTS', 10, ACCENT, bold=True).pack(anchor='w', pady=(12, 4))
        self.download_summary = self.label(diagnostics, 'No transfers started this session', 9)
        self.download_summary.pack(anchor='w', pady=(0, 5))
        self.download_table = self.tree(diagnostics, ('Source', 'State', 'Progress'), (120, 90, 120), height=2)
        self.download_table.bind('<<TreeviewSelect>>', self.show_download_detail)
        self.download_detail = self.label(diagnostics, 'Select a transfer for details', 8)
        self.download_detail.configure(height=2, anchor='nw')
        self.download_detail.pack(anchor='w', pady=(4, 0))
        websites = self.panel(body)
        websites.grid(row=1, column=2, sticky='nsew')
        self.label(websites, 'WEBSITE CHANGES', 10, ACCENT, bold=True).pack(anchor='w')
        self.site_table = self.tree(websites, ('Site', 'Deployment', 'Status'), (70, 150, 130), height=2)
        self.site_table.bind('<<TreeviewSelect>>', self.show_website_detail)
        self.site_times = self.label(websites, 'Waiting for website checks…', 9)
        self.site_times.pack(anchor='w', pady=(10, 8))
        self.site_summary = tk.Text(websites, height=6, bg=CARD, fg=TEXT, relief='flat', wrap='word', font=('Segoe UI', 10), state='disabled')
        self.site_summary.pack(fill='both', expand=True, pady=(0, 10))
        self.button(websites, 'Open website history ↗', self.open_website_history).pack(anchor='w')
        self.footer = self.label(shell, 'Solana mainnet  •  Arweave  •  IPFS     |     Your existing configuration is preserved', 9)
        self.footer.grid(row=3, column=0, sticky='ew', pady=(10, 0))
        self.capture_fonts(root)
        self.set_accent(ACCENT, persist=False)
        try:
            preferences = json.loads(self.preferences_path.read_text(encoding='utf-8'))
            self.set_accent(preferences.get('accent_color', '#64dfb2'), persist=False)
        except (OSError, ValueError, AttributeError, TypeError):
            pass
        root.bind('<Configure>', self.schedule_layout, add='+')
        root.after_idle(self.scale_layout)
        self.log('Dashboard ready. Connecting to monitoring services.' if not offline else 'Offline preview. No network services started.')
        if not offline:
            threading.Thread(target=self.run_engine, daemon=True).start()
        self.refresh()
        self.update_countdown()

    def label(self, parent, text, size=10, color=MUTED, bold=False):
        return tk.Label(parent, text=text, bg=parent['bg'], fg=color, font=('Segoe UI', size, 'bold' if bold else 'normal'), anchor='w')

    def set_accent(self, color, persist=True):
        global ACCENT
        if not isinstance(color, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', color):
            raise ValueError('Use a six-digit hex color, such as #64DFB2.')
        previous = ACCENT
        ACCENT = color.lower()
        if not hasattr(self, 'accent_widgets'):
            self.accent_widgets = []
            def register(widget):
                for option in ('foreground', 'activeforeground'):
                    if option in widget.keys() and str(widget.cget(option)).lower() == previous.lower():
                        self.accent_widgets.append((widget, option))
                for child in widget.winfo_children():
                    register(child)
            register(self.root)
        for widget, option in self.accent_widgets:
            widget.configure(**{option: ACCENT})
        rgb = tuple(int(ACCENT[i:i + 2], 16) for i in (1, 3, 5))
        selected = '#' + ''.join(f'{round(channel * .3 + background * .7):02x}' for channel, background in zip(rgb, (20, 30, 40)))
        self.style.configure('TProgressbar', background=ACCENT, lightcolor=ACCENT, darkcolor=ACCENT)
        self.style.map('Treeview', background=[('selected', selected)])
        self.feed.tag_configure('alert', foreground=ACCENT)
        self.draw_market_chart()
        if persist:
            try:
                data = {}
                if self.preferences_path.exists():
                    try:
                        data = json.loads(self.preferences_path.read_text(encoding='utf-8'))
                        if not isinstance(data, dict):
                            data = {}
                    except (ValueError, OSError):
                        pass
                data['accent_color'] = ACCENT
                temporary = self.preferences_path.with_suffix('.json.tmp')
                temporary.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
                os.replace(temporary, self.preferences_path)
            except OSError as exc:
                self.log(f'[!] Color applied, but could not save preferences: {exc}')
                messagebox.showerror('Appearance', f'Color applied, but could not save it:\n{exc}', parent=self.root)

    def open_credits(self):
        dialog = tk.Toplevel(self.root)
        dialog.title('Cyberleek - Credits')
        dialog.configure(bg=BG)
        dialog.geometry('620x330')
        dialog.minsize(520, 300)
        dialog.transient(self.root)
        tabs = ttk.Notebook(dialog)
        tabs.pack(fill='both', expand=True, padx=18, pady=18)
        credits = tk.Frame(tabs, bg=CARD)
        tabs.add(credits, text='Credits')
        tk.Label(credits, text='Original console script', bg=CARD, fg=ACCENT,
                 font=('Segoe UI', 15, 'bold')).pack(anchor='w', padx=20, pady=(22, 8))
        tk.Label(credits, text='Penistone (GitHub: wpenistone)', bg=CARD, fg=TEXT,
                 font=('Segoe UI', 12, 'bold')).pack(anchor='w', padx=20)
        tk.Label(credits, text='Created the original Cyberleek Python console monitor.\n'
                 'This dashboard builds on that monitoring and asset retrieval work.',
                 bg=CARD, fg=MUTED, justify='left', wraplength=460,
                 font=('Segoe UI', 11)).pack(anchor='w', padx=20, pady=12)
        tk.Button(credits, text='View original script on GitHub', bg=BG, fg=ACCENT,
                  relief='flat', padx=14, pady=10,
                  command=lambda: webbrowser.open('https://gist.github.com/wpenistone/22d418d7160e2ca6eb0c5f95283aae71')).pack(anchor='w', padx=20)

    def open_appearance(self):
        existing = getattr(self, 'appearance_dialog', None)
        if existing is not None and existing.winfo_exists():
            existing.lift()
            return
        dialog = tk.Toplevel(self.root)
        self.appearance_dialog = dialog
        dialog.title('Appearance')
        dialog.configure(bg=CARD)
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.geometry(f'+{self.root.winfo_rootx() + 100}+{self.root.winfo_rooty() + 100}')
        content = tk.Frame(dialog, bg=CARD, padx=22, pady=20)
        content.pack(fill='both', expand=True)
        tk.Label(content, text='Accent color', bg=CARD, fg=TEXT, font=('Segoe UI', -20, 'bold')).pack(anchor='w')
        tk.Label(content, text='Headings, progress bars, graph, and positive changes', bg=CARD, fg=MUTED, font=('Segoe UI', -13)).pack(anchor='w', pady=(5, 15))
        value = tk.StringVar(value=ACCENT.upper())
        swatch = tk.Label(content, bg=ACCENT, width=8, height=2)
        swatch.pack(anchor='w', pady=(0, 10))
        def apply(color):
            try:
                self.set_accent(color)
            except ValueError as exc:
                messagebox.showerror('Invalid color', str(exc), parent=dialog)
                return
            value.set(ACCENT.upper())
            swatch.configure(bg=ACCENT)
        presets = tk.Frame(content, bg=CARD)
        presets.pack(fill='x', pady=(0, 12))
        for name, color in [('Mint', '#64dfb2'), ('Blue', '#69b7ff'), ('Purple', '#b89aff'), ('Pink', '#ff8bc8'), ('Amber', '#ffc66b'), ('White', '#e7edf3')]:
            tk.Button(presets, text=name, bg=color, fg=BG, relief='flat', padx=9, pady=7, font=('Segoe UI', -13), command=lambda c=color: apply(c)).pack(side='left', padx=(0, 6))
        row = tk.Frame(content, bg=CARD)
        row.pack(fill='x')
        entry = tk.Entry(row, textvariable=value, width=12, bg=BG, fg=TEXT, insertbackground=TEXT, relief='flat', font=('Consolas', -15))
        entry.pack(side='left', ipady=6, padx=(0, 10))
        entry.bind('<Return>', lambda event: apply(value.get().strip()))
        self.button(row, 'Apply hex', lambda: apply(value.get().strip())).pack(side='left', padx=(0, 8))
        def choose():
            color = colorchooser.askcolor(color=ACCENT, title='Choose accent color', parent=dialog)[1]
            if color:
                apply(color)
        self.button(row, 'Custom color…', choose).pack(side='left')
        bottom = tk.Frame(content, bg=CARD)
        bottom.pack(fill='x', pady=(16, 0))
        self.button(bottom, 'Reset to mint', lambda: apply('#64dfb2')).pack(side='left')
        self.button(bottom, 'Done', dialog.destroy).pack(side='right')

    def capture_fonts(self, widget):
        if 'font' in widget.keys():
            actual = tkfont.Font(root=self.root, font=widget.cget('font')).actual()
            self.font_widgets.append((widget, actual['family'], abs(actual['size']), actual['weight']))
        for child in widget.winfo_children():
            self.capture_fonts(child)

    def schedule_layout(self, event):
        if event.widget is self.root:
            if self.resize_job is not None:
                self.root.after_cancel(self.resize_job)
            self.resize_job = self.root.after(80, self.scale_layout)

    def scale_layout(self):
        self.resize_job = None
        factor = max(.72, min(1.3, self.root.winfo_width() / 1920, self.root.winfo_height() / 1080))
        for widget, family, size, weight in self.font_widgets:
            widget.configure(font=(family, -max(10, round(size * 1.3 * factor)), weight))
        self.style.configure('Treeview', font=('Segoe UI', -round(14 * factor)), rowheight=round(28 * factor))
        self.style.configure('Treeview.Heading', font=('Segoe UI', -round(13 * factor)))
        self.style.configure('TProgressbar', thickness=max(8, round(12 * factor)))
        for tree, widths in self.tree_widths:
            available = max(210, tree.master.winfo_width() - 40)
            for column, width in zip(tree['columns'], widths):
                tree.column(column, width=max(50, round(available * width / sum(widths))))
        self.shell.pack_configure(padx=round(28 * factor), pady=round(18 * factor))
        for panel in self.panels:
            panel.configure(padx=round(18 * factor), pady=round(10 * factor))
        self.market_chart.configure(height=round(115 * factor))
        self.poll_title.configure(wraplength=max(300, self.votes.winfo_width() - 20))
        self.market_status.configure(wraplength=max(300, self.market_chart.winfo_width() - 10))
        self.footer.configure(wraplength=max(700, self.root.winfo_width() - 60))
        for label in (self.rpc_summary, self.download_summary, self.download_detail, self.site_times):
            label.configure(wraplength=max(240, label.master.winfo_width() - 40))
        self.draw_market_chart()

    def toggle_fullscreen(self):
        if sys.platform == 'win32':
            # Tk's fullscreen attribute can select the primary display. Use the
            # current window's monitor and a borderless native window instead.
            import ctypes
            self.root.update_idletasks()
            api, hwnd, MonitorInfo, WindowPlacement = windows_window_api(self.root)
            if not self.fullscreen:
                info = MonitorInfo()
                info.size = ctypes.sizeof(info)
                placement = WindowPlacement()
                placement.length = ctypes.sizeof(placement)
                if not api.GetMonitorInfoW(api.MonitorFromWindow(hwnd, 2), ctypes.byref(info)) or not api.GetWindowPlacement(hwnd, ctypes.byref(placement)):
                    self.log('[!] Could not determine the current monitor for fullscreen.')
                    return 'break'
                self.windowed_placement = placement
                self.windowed_state = self.root.state()
                self.root.state('normal')
                self.root.overrideredirect(True)
                self.root.update_idletasks()
                api, hwnd, _, _ = windows_window_api(self.root)
                rect = info.monitor
                if not api.SetWindowPos(hwnd, None, rect.left, rect.top,
                                        rect.right - rect.left, rect.bottom - rect.top, 0x64):
                    self.root.overrideredirect(False)
                    self.root.state(self.windowed_state)
                    self.log('[!] Could not resize the window for fullscreen.')
                    return 'break'
            else:
                self.root.overrideredirect(False)
                self.root.state(self.windowed_state)
                self.root.update_idletasks()
                api, hwnd, _, Placement = windows_window_api(self.root)
                # Recreate the typed structure because each API helper call
                # defines a fresh ctypes type with the same native layout.
                saved = Placement.from_buffer_copy(self.windowed_placement)
                api.SetWindowPlacement(hwnd, ctypes.byref(saved))
            self.fullscreen = not self.fullscreen
        else:
            self.fullscreen = not self.fullscreen
            self.root.attributes('-fullscreen', self.fullscreen)
        self.fullscreen_button.configure(text='Exit fullscreen · Esc' if self.fullscreen else 'Fullscreen · F11')
        return 'break'

    def exit_fullscreen(self):
        if self.fullscreen:
            self.toggle_fullscreen()
        return 'break'

    def panel(self, parent):
        panel = tk.Frame(parent, bg=CARD, padx=18, pady=10, highlightbackground='#23313e', highlightthickness=1)
        self.panels.append(panel)
        return panel

    def button(self, parent, title, command):
        return tk.Button(parent, text=title, command=command, bg='#21313f', fg=TEXT, activebackground='#315447', activeforeground=TEXT, relief='flat', borderwidth=0, padx=10, pady=5, cursor='hand2', font=('Segoe UI', 9))

    def tree(self, parent, columns, widths, height):
        tree = ttk.Treeview(parent, columns=columns, show='headings', height=height)
        for name, width in zip(columns, widths):
            tree.heading(name, text=name)
            tree.column(name, width=width, minwidth=50, stretch=True)
        tree.pack(fill='both', expand=True)
        self.tree_widths.append((tree, widths))
        return tree

    def log(self, message):
        try:
            self.events.put_nowait((dt.datetime.now().strftime('%H:%M:%S'), engine._sanitize_output(message)))
        except queue.Full:
            pass

    def run_engine(self):
        c = self.config
        try:
            # Signal startup completion when the engine launches its workers.
            original = engine.start_ws_thread
            def start_ws():
                if engine._shutdown_event.is_set():
                    return
                original()
                self.ready = True
            engine.start_ws_thread = start_ws
            engine.start_monitor(interval=engine.normalize_poll_interval(c.get('poll_interval_seconds', 15)), download_dir=engine._download_dir, enable_sound=c.get('enable_sound', True), download_all=True, watch_only=not c.get('download_payloads', True), no_auto_open=not c.get('auto_open_media', False), no_browser_fallback=True, mask_spoilers=c.get('mask_spoilers', False), custom_rpc=c.get('custom_rpc_url'), custom_ws=c.get('custom_ws_url'), config_file=str(self.config_path), quiet=True, interactive=False)
        except BaseException as exc:
            self.log(f'[!] Monitoring stopped: {exc}')
        finally:
            self.ready = False
            engine._shutdown_event.set()

    def toggle(self, attr, var, inverse):
        setattr(engine, attr, not var.get() if inverse else var.get())
        self.last_poll = None
        engine.save_config()

    def apply_rate(self):
        try:
            seconds = int(self.rate.get())
            if not 5 <= seconds <= 3600:
                raise ValueError
        except ValueError:
            self.countdown_label.configure(text='Enter a whole number from 5 to 3600 seconds.')
            self.rate_input.focus_set()
            return
        if not self.ready:
            return
        engine._poll_interval = seconds
        saved = engine.save_config()
        self.config['poll_interval_seconds'] = seconds
        self.log(f'All refreshes set to {seconds}s' + (' and saved.' if saved else '; settings could not be saved.') + ' The shared countdown restarts.')

    def update_countdown(self):
        if not self.ready or engine._shutdown_event.is_set():
            text, percent = 'Waiting for monitor…' if not engine._shutdown_event.is_set() else 'Monitor stopped', 0
        else:
            with engine._refresh_condition:
                active = bool(engine._refresh_active)
            remaining = max(0.0, engine._next_poll_time - time.time())
            text = f'Refreshing data · next cycle in {remaining:.1f}s' if active else f'Next update in {remaining:.1f}s'
            percent = min(100.0, remaining / max(5, engine._poll_interval) * 100)
        # Preserve validation feedback until the input is corrected.
        try:
            valid = 5 <= int(self.rate.get()) <= 3600
        except ValueError:
            valid = False
        if valid:
            self.countdown_label.configure(text=text)
        self.countdown_bar['value'] = percent
        self.root.after(100, self.update_countdown)

    def background(self, fn):
        def worker():
            try:
                fn()
            except Exception as exc:
                self.log(f'[!] Action failed: {exc}')
        threading.Thread(target=worker, daemon=True).start()

    def action(self, key):
        self.background(lambda: engine._handle_hotkey(key))

    def test_sound(self):
        engine._play_chime('info', force=True)

    def export(self):
        path = filedialog.asksaveasfilename(defaultextension='.json', initialfile='cyberleek_snapshot.json', filetypes=[('JSON snapshot', '*.json')])
        if path:
            self.background(lambda: engine.dump_snapshot(path))

    def open_downloads(self):
        Path(engine._download_dir).mkdir(parents=True, exist_ok=True)
        os.startfile(engine._download_dir)

    def open_website_history(self):
        folder = Path.cwd() / 'website_history'
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(str(folder))

    def sync_tree(self, tree, rows):
        wanted = {key for key, values in rows}
        for key in tree.get_children():
            if key not in wanted:
                tree.delete(key)
        for position, (key, values) in enumerate(rows):
            if tree.exists(key):
                tree.item(key, values=values)
                tree.move(key, '', position)
            else:
                tree.insert('', position, iid=key, values=values)

    def show_download_detail(self, event=None):
        selected = self.download_table.selection()
        if not selected:
            return
        with engine._state_lock:
            job = dict(engine._download_jobs.get(selected[0], {}))
        name = 'Title masked' if engine._mask_spoilers else job.get('name', '')
        detail = job.get('state', '') if engine._mask_spoilers else job.get('error') or job.get('state', '')
        self.download_detail.configure(text=f'{name} · {engine._sanitize_output(detail)}'[:100])

    def show_website_detail(self, event=None):
        selected = self.site_table.selection()
        name = selected[0] if selected else next(iter(engine.ARNS_NAMES), '')
        with engine._state_lock:
            record = dict(engine._website_state.get(name, {}))
        def timestamp(value):
            try:
                return dt.datetime.fromtimestamp(float(value)).strftime('%b %d, %H:%M:%S') if value else '—'
            except (ValueError, TypeError, OSError, OverflowError):
                return '—'
        self.site_times.configure(text=f"Last checked: {timestamp(record.get('checked_at'))}\nChange observed: {timestamp(record.get('changed_at'))}")
        summary = record.get('summary', 'Waiting for first deployment snapshot.')
        if record.get('error'):
            summary += '\n' + str(record['error'])
        if engine._mask_spoilers and record.get('summary'):
            summary = 'Content summary hidden while Mask spoilers is enabled.\n' + record.get('status', '')
        content = f"{name}\nDeployment: {record.get('version', '—')}\n\n{engine._sanitize_output(summary)}"
        if self.site_summary.get('1.0', 'end-1c') != content:
            self.site_summary.configure(state='normal')
            self.site_summary.delete('1.0', 'end')
            self.site_summary.insert('1.0', content)
            self.site_summary.configure(state='disabled')

    def show_rpc_detail(self, event=None):
        selected = self.rpc_table.selection()
        if not selected:
            return
        with engine._state_lock:
            item = dict(engine._rpc_diagnostics.get(selected[0], {}))
        error = re.sub(r'https?://[^\s]+', '[endpoint]', str(item.get('error') or 'None'))
        messagebox.showinfo('RPC connection details', f"Endpoint: {urllib.parse.urlparse(selected[0]).hostname}\nLast method: {item.get('method', '—')}\nLatency: {item.get('latency_ms', 0):.0f} ms\nSuccessful: {item.get('successes', 0)}\nFailed: {item.get('failures', 0)}\nLast error: {engine._sanitize_output(error)}", parent=self.root)

    def refresh_operational_panels(self):
        with engine._state_lock:
            diagnostics = copy.deepcopy(engine._rpc_diagnostics)
            cooldowns = dict(engine._rpc_cooldowns)
            jobs = copy.deepcopy(engine._download_jobs)
            totals = dict(engine._download_totals)
            sites = copy.deepcopy(engine._website_state)
        now = time.time()
        successes = sum(item['successes'] for item in diagnostics.values())
        failures = sum(item['failures'] for item in diagnostics.values())
        last_success = max((item.get('last_success') or 0 for item in diagnostics.values()), default=0)
        latest = max(diagnostics.values(), key=lambda item: item['last_attempt'], default={})
        age = f'{int(now - last_success)}s ago' if last_success else 'not yet'
        self.rpc_summary.configure(text=f'{successes} successful · {failures} failed · last OK {age}\nLatest request: {latest.get("method", "—")}')
        def endpoint_label(url):
            parsed = urllib.parse.urlparse(url)
            return parsed.hostname or 'RPC'
        rows = []
        for url, item in sorted(diagnostics.items(), key=lambda pair: pair[1]['last_attempt'], reverse=True):
            remaining = max(0, int(cooldowns.get(url, 0) - now))
            status = f'Cooldown {remaining}s' if remaining else 'Error' if item.get('error') else 'OK'
            rows.append((url, (endpoint_label(url), f'{item["latency_ms"]:.0f} ms', status)))
        self.sync_tree(self.rpc_table, rows)
        active = sum(job['state'] in ('connecting', 'downloading') for job in jobs.values())
        self.download_summary.configure(text=f'{active} active · {totals["completed"]} completed · {totals["failed"]} failed\n{totals["canceled"]} canceled · {totals["external"]} handed to browser/client')
        def progress(job):
            received, total = job.get('received', 0), job.get('total')
            if job['state'] == 'completed':
                return f'{received / 1048576:.1f} MB · done'
            if total:
                return f'{min(99, received / total * 100):.0f}% · {received / 1048576:.1f} MB'
            return f'{received / 1048576:.1f} MB' if received else '—'
        ordered = sorted(jobs.items(), key=lambda pair: (pair[1]['state'] not in ('connecting', 'downloading'), -pair[1]['started']))
        self.sync_tree(self.download_table, [(key, (job['source'], job['state'].title(), progress(job))) for key, job in ordered])
        self.show_download_detail()
        self.sync_tree(self.site_table, [(name, (name, sites.get(name, {}).get('version', '—')[:18], sites.get(name, {}).get('status', 'Waiting'))) for name in engine.ARNS_NAMES])
        self.show_website_detail()

    def draw_market_chart(self):
        chart = self.market_chart
        chart.delete('all')
        with engine._state_lock:
            points = [(t, v) for t, v in engine._market_history if t >= time.time() - 3600]
        width, height = chart.winfo_width(), chart.winfo_height()
        if width < 100:
            return
        if not points:
            chart.create_text(width / 2, height / 2, text='History builds from successful market updates', fill=MUTED, font=('Segoe UI', 9))
            return
        left, right, top, bottom = 76, width - 12, 12, height - 24
        low, high = min(v for _, v in points), max(v for _, v in points)
        padding = max((high - low) * .15, high * .001, 1)
        low, high = max(0, low - padding), high + padding
        start, end = points[0][0], max(points[-1][0], points[0][0] + 1)
        for fraction in (0, .5, 1):
            y = top + fraction * (bottom - top)
            chart.create_line(left, y, right, y, fill='#23313e')
            chart.create_text(left - 8, y, text=engine.format_usd(high - fraction * (high - low)), anchor='e', fill=MUTED, font=('Segoe UI', 8))
        coords = [(left + (t - start) / (end - start) * (right - left), bottom - (v - low) / (high - low) * (bottom - top)) for t, v in points]
        # Break the line across failed/missing refreshes instead of fabricating continuity.
        cadence = max(5, engine._poll_interval)
        for index in range(1, len(points)):
            if points[index][0] - points[index - 1][0] <= cadence * 2.5:
                chart.create_line(*coords[index - 1], *coords[index], fill=ACCENT, width=2)
        x, y = coords[-1]
        chart.create_oval(x - 3, y - 3, x + 3, y + 3, fill=ACCENT, outline='')
        for timestamp, position, anchor in [(start, left, 'w'), (points[-1][0], right, 'e')]:
            chart.create_text(position, height - 8, text=dt.datetime.fromtimestamp(timestamp).strftime('%H:%M:%S'), anchor=anchor, fill=MUTED, font=('Segoe UI', 8))

    def refresh(self):
        self.refresh_operational_panels()
        for _ in range(150):
            try:
                stamp, message = self.events.get_nowait()
            except queue.Empty:
                break
            at_bottom = self.feed.yview()[1] >= .98
            tag = 'error' if '[!]' in message or '[-]' in message else 'alert' if '[+]' in message else ''
            self.feed.insert('end', f'{stamp}  {message.strip()}\n', tag)
            if int(self.feed.index('end-1c').split('.')[0]) > 1800:
                self.feed.delete('1.0', '200.0')
            if at_bottom:
                self.feed.see('end')
        with engine._state_lock:
            poll = copy.deepcopy(engine._active_poll_info)
            reserve = engine._dev_reserve
            count = len(engine._known_links)
            market = dict(engine._market_data)
            totals = (len(engine._known_proposals), len(engine._known_notices), len(engine._known_ar_txs), len(engine._known_cids), len(engine._monitored_reserve_atas))
        price = market.get('price_usd', 0)
        mcap = market.get('market_cap_usd') or 0
        self.values['mcap'].configure(text=f'${mcap:,.0f}' if mcap else '—')
        self.values['price'].configure(text=f'${price:.7f}' if price else '—')
        self.values['reserve'].configure(text=engine.format_tokens(reserve) if self.ready else '—')
        self.values['accounts'].configure(text=str(count) if self.ready else '—')
        def dollars(value):
            return engine.format_usd(value) if value is not None else '—'
        self.market_details['liquidity'].configure(text=dollars(market.get('liquidity_usd')))
        self.market_details['volume'].configure(text=dollars(market.get('volume', {}).get('h24')))
        self.market_details['fdv'].configure(text=dollars(market.get('fdv_usd')))
        trades = market.get('transactions', {}).get('h24', {})
        buy, sell = trades.get('buys'), trades.get('sells')
        self.market_details['trades'].configure(text=f'{buy:,.0f} / {sell:,.0f}' if buy is not None and sell is not None else '—')
        for period in ('m5', 'h1', 'h6', 'h24'):
            change = market.get('price_change', {}).get(period)
            self.market_details[period].configure(text=f'{change:+.2f}%' if change is not None else '—', fg=ACCENT if change is not None and change > 0 else '#ffad87' if change is not None and change < 0 else TEXT)
        uptime = int(time.monotonic() - self.started_at)
        self.footer.configure(text=f'Solana mainnet · Session {uptime // 3600:02}:{uptime // 60 % 60:02}:{uptime % 60:02}  |  Proposals {totals[0]} · Notices {totals[1]} · Arweave IDs {totals[2]} · IPFS IDs {totals[3]} · Reserve accounts {totals[4]}')
        for label, bar, target, title, idx in self.tiers:
            name = f'Tier {idx + 1}' if engine._mask_spoilers else title
            pct = min(100, mcap / target * 100)
            label.configure(text=f'${target / 1e6:g}M  ·  {name}  ·  {pct:.1f}%')
            bar['value'] = pct
        poll_version = (poll, price, engine._mask_spoilers, self.ready)
        if poll_version != self.last_poll:
            self.last_poll = copy.deepcopy(poll_version)
            self.votes.delete(*self.votes.get_children())
            if poll:
                self.poll_title.configure(text='Active community poll' if engine._mask_spoilers else poll['title'][:58])
                self.poll_meta.configure(text=f"{poll['time_rem_str']} remaining  ·  {poll['total']:,.0f} tokens staked")
                ranked_options = sorted(enumerate(zip(poll['choices'], poll['balances'])), key=lambda option: option[1][1], reverse=True)
                for i, (choice, balance) in ranked_options:
                    share = balance / poll['total'] * 100 if poll['total'] else 0
                    self.votes.insert('', 'end', values=(f'Option {i + 1}' if engine._mask_spoilers else choice, f'{balance:,.0f}', f'{share:.1f}%', f'${balance * price:,.2f}' if price else '—'))
            else:
                self.poll_title.configure(text='No active community poll' if self.ready else 'Waiting for on-chain state…')
        if poll:
            remaining = max(0, int(poll.get('ends_at', time.time()) - time.time()))
            deadline = f"{remaining // 86400}d {remaining // 3600 % 24}h" if remaining >= 86400 else f"{remaining // 3600}h {remaining // 60 % 60}m"
            stale_votes = poll.get('stale', False) or (poll.get('observed_at') is not None and time.time() - poll['observed_at'] > max(5, engine._poll_interval) * 2 + 5)
            self.poll_meta.configure(text=f"{'STALE ? ' if stale_votes else ''}{deadline} remaining ? {poll['total']:,.0f} tokens staked")
        else:
            self.poll_meta.configure(text='')
        state = 'PREVIEW' if self.offline else 'STOPPED' if engine._shutdown_event.is_set() else 'LIVE' if self.ready and engine._ws_status == 'ON' else 'MONITORING' if self.ready else 'CONNECTING'
        self.state.configure(text=state)
        self.health.configure(text=f'WebSocket  {engine._ws_status}   /   HTTP  {engine._http_poll_status}\nStorage  {engine._ar_status}   /   Slot  {engine._highest_slot:,}')
        age = int(time.time() - engine._token_price_last_ts) if engine._token_price_last_ts else None
        stale = bool(market.get('error')) or (age is not None and age > max(5, engine._poll_interval) * 2 + 5)
        market_text = f"{'STALE · ' if stale else ''}{market.get('basis', '')} · {market.get('dex', '')} · fetched {age}s ago · every {max(5, engine._poll_interval)}s" if age is not None else 'Market data unavailable · retrying' if market.get('error') else 'Waiting for market data…'
        self.market_status.configure(text=market_text, fg='#ffad87' if stale else MUTED)
        self.values['mcap'].configure(fg='#ffad87' if stale else TEXT)
        if not mcap:
            self.values['mcap'].configure(text='--')
        estimated_cap = market.get('market_cap_estimated', False)
        self.metric_titles['mcap'].configure(text='MARKET CAP - ESTIMATE' if estimated_cap else 'MARKET CAPITALIZATION')
        supply = market.get('circulating_supply_used')
        supply_age = max(0, int(time.time() - market['supply_observed_at'])) if market.get('supply_observed_at') else None
        detail = f"CG supply {supply / 1e6:.2f}M - fetched {supply_age}s ago" if supply and supply_age is not None else 'Waiting for CoinGecko supply'
        if market.get('supply_error'):
            detail = 'SUPPLY STALE - ' + detail
        self.metric_details['mcap'].configure(text=detail if estimated_cap else 'CoinGecko reported - USD')

        self.draw_market_chart()
        self.freshness.configure(text=f'Price observed {age}s ago  ·  Last activity {engine.format_event_age()}' if age is not None else 'Waiting for first market observation')
        for var, attr, inverse, widget in self.toggles:
            widget.configure(state='normal' if self.ready else 'disabled')
            if self.ready:
                var.set(not getattr(engine, attr) if inverse else getattr(engine, attr))
        for button in self.action_buttons:
            button.configure(state='normal' if self.ready or button.cget('text') == 'Test sound' else 'disabled')
        self.rate_input.configure(state='normal' if self.ready else 'disabled')
        self.rate_apply.configure(state='normal' if self.ready else 'disabled')
        self.root.after(750, self.refresh)

    def close(self):
        engine._shutdown_event.set()
        self.root.destroy()


def main():
    if sys.platform == 'win32':
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (OSError, AttributeError):
            pass
    base = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
    if getattr(sys, 'frozen', False):
        base = base / 'data'
        base.mkdir(parents=True, exist_ok=True)
    os.chdir(base)
    # Some engine diagnostics still print directly in a consoleless build.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, 'w')
    if sys.stderr is None:
        sys.stderr = open(os.devnull, 'w')
    root = tk.Tk()
    app = Dashboard(root, offline='--preview' in sys.argv)
    if '--smoke-test' in sys.argv:
        root.after(1500, app.close)
    root.mainloop()


if __name__ == '__main__':
    main()
