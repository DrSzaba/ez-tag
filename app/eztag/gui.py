"""EZ Tag main window."""
from __future__ import annotations

import io
import os
import queue
import re
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox, ttk

from . import APP_NAME, VERSION, dialogs, tools, ezupdate
from .dialogs import BLANK_TEXT, KEEP_TEXT
from .settings import Settings
from .tags import AudioFile, Cover, FIELD_LABELS, fmt_length, fmt_size, is_audio
from .theme import (BG, COLORS, EMOJI, FAMILY, HEADER, INK, KEEP, LINE, MUTED, PANEL, BigButton,
                    PillButton, Tooltip, darken, font, label, set_text_scale, setup_styles)

try:
    from PIL import Image, ImageTk  # optional - shows JPEG covers
except Exception:  # missing or blocked by antivirus: we still work, PNG covers only
    Image = ImageTk = None

GENRES = sorted("""Acoustic Alternative Ambient Bachata Blues Classical Country Cumbia Dance Disco
Drum & Bass Dubstep EDM Electronic Folk Funk Gospel Hip-Hop House Indie Jazz K-Pop Latin Merengue
Metal Pop Punk R&B Rap Reggae Reggaeton Rock Salsa Soul Soundtrack Techno Trap Trance World
Christian Kompa Zouk Afrobeats Dancehall Bolero Bossa Nova Lo-Fi Instrumental Podcast Audiobook
Spoken Word Children's Comedy Holiday Opera Tropical Vallenato Corridos Banda Ranchera""".replace(
    "Drum & Bass", "Drum&Bass").replace("Bossa Nova", "BossaNova").replace("Spoken Word", "SpokenWord")
    .replace("Lo-Fi", "LoFi").split(), key=str.lower)
GENRES = [g.replace("Drum&Bass", "Drum & Bass").replace("BossaNova", "Bossa Nova")
          .replace("SpokenWord", "Spoken Word").replace("LoFi", "Lo-Fi") for g in GENRES]

COLUMNS = {
    "status": ("", 34, "center"), "_filename": ("File Name", 240, "w"), "title": ("Title", 200, "w"),
    "artist": ("Artist", 160, "w"), "album": ("Album", 170, "w"), "albumartist": ("Album Artist", 150, "w"),
    "track": ("#", 46, "center"), "disc": ("Disc", 46, "center"), "year": ("Year", 58, "center"),
    "genre": ("Genre", 110, "w"), "comment": ("Comment", 160, "w"), "composer": ("Composer", 140, "w"),
    "bpm": ("BPM", 50, "center"), "publisher": ("Label", 120, "w"),
    "_length": ("Time", 62, "center"), "_bitrate": ("kbps", 56, "center"),
    "_samplerate": ("Hz", 64, "center"), "_format": ("Format", 90, "w"), "_size": ("Size", 76, "e"),
    "cover": ("Art", 44, "center"), "_tag": ("Tag Type", 100, "w"), "_folder": ("Folder", 160, "w"),
    "_path": ("Full Path", 320, "w"),
}

PANEL_FIELDS = [("title", "Title"), ("artist", "Artist"), ("album", "Album"),
                ("albumartist", "Album Artist"), ("year", None), ("track", None), ("disc", None),
                ("genre", "Genre"), ("comment", "Comment"), ("composer", "Composer")]

FILTERS = ["All songs", "Missing title or artist", "No cover picture", "Has problems", "Changed this session"]


class App:
    def __init__(self, root: tk.Tk, paths=None):
        self.root = root
        self.settings = Settings()
        set_text_scale(self.settings["large_text"])
        setup_styles(root)
        root.title(f"{APP_NAME}  •  easy music tag editor")
        root.configure(bg=BG)
        root.minsize(980, 620)
        try:
            root.geometry(self.settings["geometry"])
            if self.settings.get("zoomed"):
                root.state("zoomed")
        except tk.TclError:
            pass
        self._set_icon()

        self.files: list[AudioFile] = []
        self.by_iid: dict[str, AudioFile] = {}
        self.touched: set[int] = set()
        self.undo_stack: list[tuple[str, list]] = []
        self.sort_col, self.sort_rev = None, False
        self.panel_vars: dict[str, tk.StringVar] = {}
        self.panel_initial: dict[str, str] = {}
        self.panel_widgets: dict[str, ttk.Combobox] = {}
        self.cover_img = None
        self._loading = False
        self._suspend_select = False

        self._build_menu()
        self._build_header()
        self._build_toolbar()
        self._build_body()
        self._build_statusbar()
        self._bind_keys()
        self.update_status()
        self.root.protocol("WM_DELETE_WINDOW", self.quit)
        # automatic updates: checks GitHub quietly, downloads in the background, shows a bar when ready
        self.updater = ezupdate.Updater(APP_NAME, VERSION, "DrSzaba/ez-tag", "EZ-Tag-Setup.zip",
                                        os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "EZ Tag"))
        self.updater.close_app = self.quit
        self.update_bar = ezupdate.attach_to_tk(
            root, self.updater, root,
            {"bg": "#FFF3BF", "fg": "#3b2a00", "button": COLORS["green"], "button_fg": "white"},
            FAMILY, on_close_chain=self.quit)
        if paths:
            self.root.after(200, lambda: self.load_paths(paths, replace=True))
        elif self.settings.get("last_folder") and os.path.isdir(self.settings["last_folder"]):
            self.show_welcome()
        else:
            self.show_welcome()

    # ======================================================================
    # building the window
    # ======================================================================
    def _set_icon(self):
        here = os.path.dirname(os.path.abspath(__file__))
        for p in (os.path.join(here, "..", "assets", "ez-tag.ico"), os.path.join(here, "..", "..", "assets", "ez-tag.ico")):
            if os.path.exists(p) and sys.platform.startswith("win"):
                try:
                    self.root.iconbitmap(default=p)
                    return
                except tk.TclError:
                    pass
        for p in (os.path.join(here, "..", "assets", "ez-tag.png"), os.path.join(here, "..", "..", "assets", "ez-tag.png")):
            if os.path.exists(p):
                try:
                    self._icon = tk.PhotoImage(file=p)
                    self.root.iconphoto(True, self._icon)
                    return
                except tk.TclError:
                    pass

    def _build_menu(self):
        m = tk.Menu(self.root)
        self.root.config(menu=m)

        def menu(title, items):
            sub = tk.Menu(m, tearoff=False)
            for it in items:
                if it is None:
                    sub.add_separator()
                elif isinstance(it, tuple) and isinstance(it[1], tk.Menu):
                    sub.add_cascade(label=it[0], menu=it[1])
                else:
                    sub.add_command(label=it[0], command=it[1], accelerator=it[2] if len(it) > 2 else "")
            m.add_cascade(label=title, menu=sub)
            return sub
        self.recent_menu = tk.Menu(m, tearoff=False, postcommand=self._fill_recent)
        menu("File", [("📂  Open Folder...", self.open_folder, "Ctrl+O"),
                      ("➕  Add Folder (keep current list)...", lambda: self.open_folder(add=True)),
                      ("🎵  Add Songs...", self.add_files, "Ctrl+Shift+O"),
                      ("Recent Folders", self.recent_menu),
                      None,
                      ("🔄  Reload From Disk", self.reload, "F5"),
                      ("🧺  Clear the List", self.clear_list),
                      None,
                      ("📤  Export List / Playlist...", lambda: dialogs.export(self.root_app, self.targets())),
                      None,
                      ("Exit", self.quit, "Alt+F4")])
        menu("Edit", [("💾  Save", self.save_panel, "Ctrl+S"),
                      ("↩️  Undo", self.undo, "Ctrl+Z"),
                      None,
                      ("Select All", self.select_all, "Ctrl+A"),
                      ("Select Same Folder", self.select_same_folder),
                      ("Remove From List (files stay)", self.remove_from_list, "Delete"),
                      None,
                      ("🗂️  All Tag Fields...", lambda: dialogs.extended(self.root_app, self.targets()), "Ctrl+E"),
                      ("▶️  Play", self.play, "Enter"),
                      ("📁  Open Song's Folder", self.open_folder_of),
                      ("✏️  Rename One File...", self.rename_one, "F2")])
        menu("Convert", [("🔤  Tag → File Name...", lambda: dialogs.tag_to_filename(self.root_app, self.targets()), "Alt+1"),
                         ("📝  File Name → Tag...", lambda: dialogs.filename_to_tag(self.root_app, self.targets()), "Alt+2"),
                         ("📋  Text List → Tag...", lambda: dialogs.text_to_tag(self.root_app, self.targets()), "Alt+3"),
                         ("✏️  Set a Field (Tag → Tag)...", lambda: dialogs.set_field(self.root_app, self.targets()), "Alt+4"),
                         None,
                         ("🧠  Smart Guess Tags From File Names", self.smart_guess),
                         ("📁  Sort Into Folders (Artist\\Album)...", self.sort_into_folders)])
        menu("Actions", [("🪄  Fix It All...", lambda: dialogs.fix_it(self.root_app, self.targets())),
                         ("🔁  Find & Replace...", lambda: dialogs.replace(self.root_app, self.targets()), "Ctrl+H"),
                         ("🔠  Upper / Lower Case...", lambda: dialogs.change_case(self.root_app, self.targets())),
                         ("🔢  Auto Number Tracks...", lambda: dialogs.number(self.root_app, self.targets()), "Ctrl+K"),
                         ("✂️  Remove (Brackets) From Titles", self.remove_brackets),
                         ("🔀  Swap Artist and Title", self.swap_artist_title),
                         None,
                         ("🏷️  Rewrite Tags as ID3v2.3 (MP3)", lambda: self.rewrite_id3(3)),
                         ("🏷️  Rewrite Tags as ID3v2.4 (MP3)", lambda: self.rewrite_id3(4)),
                         None,
                         ("🧹  Remove All Tags...", self.remove_tags)])
        menu("Tools", [("🌐  Find Album Info Online...", lambda: dialogs.find_online(self.root_app, self.targets()), "Ctrl+I"),
                       ("🖼️  Cover Art...", lambda: dialogs.covers(self.root_app, self.targets())),
                       ("👯  Find Duplicate Songs...", lambda: dialogs.duplicates(self.root_app, self.files)),
                       None,
                       ("⚙️  Settings...", lambda: dialogs.settings(self.root_app))])
        self.col_menu = tk.Menu(m, tearoff=False)
        self.col_vars = {}
        for key, (title, *_rest) in COLUMNS.items():
            v = tk.BooleanVar(value=key in self.settings["columns"])
            self.col_vars[key] = v
            self.col_menu.add_checkbutton(label=title or "Status ✔", variable=v, command=self.apply_columns)
        vm = tk.Menu(m, tearoff=False)
        vm.add_cascade(label="Columns", menu=self.col_menu)
        vm.add_command(label="🔎  Filter", command=lambda: self.filter_entry.focus_set(), accelerator="Ctrl+F")
        m.add_cascade(label="View", menu=vm)
        menu("Help", [("❓  How to Use EZ Tag", lambda: dialogs.about(self.root_app), "F1"),
                      ("⟳  About · Updates", lambda: self.show_about()),
                      ("🌐  EZ Tag Website", lambda: webbrowser.open(dialogs.SITE_URL)),
                      ("💚  Donate ($Szaba on Cash App)", lambda: webbrowser.open(dialogs.DONATE_URL))])

    @property
    def root_app(self):
        return self

    def show_about(self):
        """'About & updates': shows your version and checks for a new one."""
        return ezupdate.open_about(
            self.root, self.updater,
            {"title": HEADER, "text": "#212529", "muted": MUTED, "button": COLORS["green"],
             "good": COLORS["green"], "bad": COLORS["red"]},
            FAMILY, extra_lines=["The easy music tag editor  •  every audio format", "Free, by Dr. Szaba"])

    def _build_header(self):
        h = tk.Frame(self.root, bg=HEADER)
        h.pack(fill="x")
        logo = tk.Frame(h, bg=HEADER)
        logo.pack(side="left", padx=(16, 0), pady=8)
        tk.Label(logo, text="🏷️", font=font(22, family=EMOJI), bg=HEADER, fg="white").pack(side="left")
        word = tk.Frame(logo, bg=HEADER)
        word.pack(side="left", padx=(8, 0))
        line = tk.Frame(word, bg=HEADER)
        line.pack(anchor="w")
        for ch, col in zip("EZ", ("#ffd43b", "#69db7c")):
            tk.Label(line, text=ch, font=font(22, "bold"), bg=HEADER, fg=col, bd=0, padx=0).pack(side="left")
        tk.Label(line, text=" Tag", font=font(22, "bold"), bg=HEADER, fg="white", padx=0).pack(side="left")
        tk.Label(word, text="The easy music tag editor  •  every audio format", font=font(9),
                 bg=HEADER, fg="#d0bfff").pack(anchor="w")
        right = tk.Frame(h, bg=HEADER)
        right.pack(side="right", padx=14)
        PillButton(right, "⚙️ Settings", darken(HEADER, .25),
                   lambda: dialogs.settings(self), fsize=9).pack(side="right", padx=4)
        PillButton(right, "❓ Help", darken(HEADER, .25), lambda: dialogs.about(self), fsize=9).pack(side="right", padx=4)
        PillButton(right, f"v{VERSION} ⟳", darken(HEADER, .25), self.show_about,
                   fsize=9).pack(side="right", padx=4)
        PillButton(right, "💚 Donate", COLORS["green"], lambda: webbrowser.open(dialogs.DONATE_URL),
                   fsize=9).pack(side="right", padx=4)

    def _build_toolbar(self):
        bar = tk.Frame(self.root, bg=BG)
        bar.pack(fill="x", padx=10, pady=(10, 4))
        t = lambda: self.targets()  # noqa: E731
        buttons = [
            ("Open Folder", "📂", "blue", self.open_folder, "Load every song in a folder (Ctrl+O)"),
            ("Add Songs", "🎵", "cyan", self.add_files, "Add single songs to the list"),
            ("Save", "💾", "green", self.save_panel, "Save what you typed on the left (Ctrl+S)"),
            ("Undo", "↩️", "gray", self.undo, "Take back the last change (Ctrl+Z)"),
            ("Tag → Name", "🔤", "orange", lambda: dialogs.tag_to_filename(self, t()), "Rename files from their tags"),
            ("Name → Tag", "📝", "purple", lambda: dialogs.filename_to_tag(self, t()), "Fill tags from file names"),
            ("Number", "🔢", "pink", lambda: dialogs.number(self, t()), "Number the tracks 1, 2, 3..."),
            ("Fix It All", "🪄", "yellow", lambda: dialogs.fix_it(self, t()), "Clean up messy tags in one click"),
            ("Replace", "🔁", "indigo", lambda: dialogs.replace(self, t()), "Find and replace words"),
            ("Find Online", "🌐", "teal", lambda: dialogs.find_online(self, t()), "Get album info + cover from the internet"),
            ("Covers", "🖼️", "red", lambda: dialogs.covers(self, t()), "Add, copy, save or remove cover pictures"),
            ("All Fields", "🗂️", "lime", lambda: dialogs.extended(self, t()), "See and edit every tag field (Ctrl+E)"),
            ("Export", "📤", "grape", lambda: dialogs.export(self, t()), "Make a list, spreadsheet or playlist"),
            ("Remove Tags", "🧹", "brown", self.remove_tags, "Delete all tags from the selected songs"),
        ]
        self.toolbar_buttons = {}
        for i, (text, icon, color, cmd, tip) in enumerate(buttons):
            b = BigButton(bar, text, icon, color, cmd, width=88, height=68, tip=tip)
            b.grid(row=0, column=i, padx=3)
            self.toolbar_buttons[text] = b

    def _build_body(self):
        body = tk.PanedWindow(self.root, orient="horizontal", bg=BG, sashwidth=8, bd=0,
                              sashrelief="flat", showhandle=False)
        body.pack(fill="both", expand=True, padx=10, pady=(4, 0))
        self.paned = body
        body.add(self._build_panel(body), minsize=300, width=340)
        body.add(self._build_list(body), minsize=400)

    # --------------------------------------------------------------- left panel
    def _build_panel(self, master):
        outer = tk.Frame(master, bg=PANEL, highlightthickness=1, highlightbackground=LINE)
        canvas = tk.Canvas(outer, bg=PANEL, highlightthickness=0, width=320)
        sb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=PANEL, padx=14, pady=10)
        win = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win, width=e.width))
        self.panel_canvas = canvas

        def wheel(e):
            if e.widget.winfo_class() in ("TCombobox", "Listbox", "Text"):
                return
            canvas.yview_scroll(int(-e.delta / 120) if e.delta else (-1 if e.num == 4 else 1), "units")
        for w in (canvas, inner):
            w.bind("<MouseWheel>", wheel)
            w.bind("<Button-4>", wheel)
            w.bind("<Button-5>", wheel)

        head = tk.Frame(inner, bg=PANEL)
        head.pack(fill="x")
        label(head, "✏️ Edit Tags", 14, True, color=COLORS["purple"]).pack(side="left")
        self.sel_label = label(head, "", 9, color=MUTED)
        self.sel_label.pack(side="right")

        # cover
        cov = tk.Frame(inner, bg=PANEL)
        cov.pack(fill="x", pady=(8, 4))
        self.cover_canvas = tk.Canvas(cov, width=150, height=150, bg="#f1ebff", highlightthickness=0,
                                      cursor="hand2")
        self.cover_canvas.pack(side="left")
        self.cover_canvas.bind("<Button-1>", lambda e: self.cover_add())
        cbtn = tk.Frame(cov, bg=PANEL)
        cbtn.pack(side="left", fill="y", padx=(10, 0))
        PillButton(cbtn, "➕ Add", "blue", self.cover_add, fsize=9, padx=10).pack(fill="x", pady=2)
        PillButton(cbtn, "💾 Save", "teal", self.cover_save, fsize=9, padx=10).pack(fill="x", pady=2)
        PillButton(cbtn, "🗑 Remove", "red", self.cover_remove, fsize=9, padx=10).pack(fill="x", pady=2)
        PillButton(cbtn, "🌐 Online", "cyan", lambda: dialogs.find_online(self, self.targets()),
                   fsize=9, padx=10).pack(fill="x", pady=2)
        self.cover_info = label(inner, "", 8, color=MUTED)
        self.cover_info.pack(anchor="w")

        # fields
        form = tk.Frame(inner, bg=PANEL)
        form.pack(fill="x", pady=(6, 0))
        form.columnconfigure(0, weight=1)
        row = 0

        def add_combo(parent, key, width=30, values=None):
            v = tk.StringVar()
            cb = ttk.Combobox(parent, textvariable=v, width=width, font=font(11), values=values or [])
            cb.bind("<Return>", lambda e: self.save_panel())
            cb.bind("<FocusIn>", lambda e, k=key: self._combo_focus(k))
            self.panel_vars[key] = v
            self.panel_widgets[key] = cb
            v.trace_add("write", lambda *_a, k=key: self._mark_edit(k))
            return cb

        for key, title in PANEL_FIELDS:
            if key == "year":
                pair = tk.Frame(form, bg=PANEL)
                pair.grid(row=row, column=0, sticky="ew", pady=(6, 0))
                label(pair, "Year", 9, True, color=MUTED).grid(row=0, column=0, sticky="w")
                label(pair, "Track", 9, True, color=MUTED).grid(row=0, column=1, sticky="w", padx=(10, 0))
                label(pair, "of", 9, color=MUTED).grid(row=0, column=2, sticky="w")
                add_combo(pair, "year", 7).grid(row=1, column=0, sticky="w")
                add_combo(pair, "track", 5).grid(row=1, column=1, sticky="w", padx=(10, 2))
                add_combo(pair, "totaltracks", 5).grid(row=1, column=2, sticky="w")
                label(pair, "Disc", 9, True, color=MUTED).grid(row=2, column=1, sticky="w", padx=(10, 0), pady=(6, 0))
                label(pair, "of", 9, color=MUTED).grid(row=2, column=2, sticky="w", pady=(6, 0))
                add_combo(pair, "disc", 5).grid(row=3, column=1, sticky="w", padx=(10, 2))
                add_combo(pair, "totaldiscs", 5).grid(row=3, column=2, sticky="w")
                label(pair, "BPM", 9, True, color=MUTED).grid(row=2, column=0, sticky="w", pady=(6, 0))
                add_combo(pair, "bpm", 7).grid(row=3, column=0, sticky="w")
                row += 1
                continue
            if title is None:
                continue
            label(form, title, 9, True, color=MUTED).grid(row=row, column=0, sticky="w", pady=(6, 0))
            row += 1
            cb = add_combo(form, key, 30, GENRES if key == "genre" else None)
            cb.grid(row=row, column=0, sticky="ew")
            row += 1

        btns = tk.Frame(inner, bg=PANEL)
        btns.pack(fill="x", pady=(14, 4))
        self.save_btn = BigButton(btns, "Save Tags", "💾", "green", self.save_panel, width=140, height=58,
                                  tip="Write the info above into the selected songs (Ctrl+S)")
        self.save_btn.pack(side="left")
        more = tk.Frame(btns, bg=PANEL)
        more.pack(side="left", padx=(8, 0), fill="y")
        PillButton(more, "🗂️ More fields", "lime", lambda: dialogs.extended(self, self.targets()),
                   fsize=9, padx=8).pack(fill="x", pady=(0, 4))
        PillButton(more, "↺ Reset", "gray", self.load_panel, fsize=9, padx=8).pack(fill="x")
        self.edit_hint = label(inner, "", 9, color=COLORS["orange"], wraplength=290, justify="left")
        self.edit_hint.pack(anchor="w", pady=(4, 0))
        label(inner, f"Tip: '{KEEP_TEXT}' keeps each song's own value.\n'{BLANK_TEXT}' empties the field.",
              8, color=MUTED, justify="left").pack(anchor="w", pady=(8, 0))
        self.info_box = label(inner, "", 9, color=INK, justify="left", wraplength=290)
        self.info_box.pack(anchor="w", pady=(10, 0))
        return outer

    # --------------------------------------------------------------- song list
    def _build_list(self, master):
        outer = tk.Frame(master, bg=BG)
        top = tk.Frame(outer, bg=BG)
        top.pack(fill="x", pady=(0, 6))
        label(top, "🔎", 12, bg=BG).pack(side="left")
        self.filter_var = tk.StringVar()
        self.filter_entry = tk.Entry(top, textvariable=self.filter_var, font=font(11), relief="flat",
                                     highlightthickness=2, highlightbackground=LINE,
                                     highlightcolor=COLORS["purple"], width=34)
        self.filter_entry.pack(side="left", padx=(4, 4), ipady=3)
        self.filter_var.trace_add("write", lambda *_: self._schedule_refresh())
        PillButton(top, "✖", "gray", lambda: self.filter_var.set(""), fsize=8, padx=8, pady=4).pack(side="left")
        label(top, "Show:", 10, True, bg=BG).pack(side="left", padx=(14, 4))
        self.show_var = tk.StringVar(value=FILTERS[0])
        sc = ttk.Combobox(top, textvariable=self.show_var, values=FILTERS, state="readonly", width=24, font=font(10))
        sc.pack(side="left")
        sc.bind("<<ComboboxSelected>>", lambda e: self.refresh_list())
        self.count_label = label(top, "", 10, True, color=COLORS["purple"], bg=BG)
        self.count_label.pack(side="right")

        frame = tk.Frame(outer, bg=PANEL, highlightthickness=1, highlightbackground=LINE)
        frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(frame, columns=list(COLUMNS), show="headings", selectmode="extended")
        for key, (title, width, anchor) in COLUMNS.items():
            self.tree.heading(key, text=title, anchor="center" if anchor == "center" else "w",
                              command=lambda k=key: self.sort_by(k))
            w = self.settings["col_widths"].get(key, width)
            self.tree.column(key, width=w, anchor=anchor, stretch=False, minwidth=30)
        ys = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        xs = ttk.Scrollbar(frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self.tree.tag_configure("odd", background="#faf8ff")
        self.tree.tag_configure("warn", background="#fff4e6")
        self.tree.tag_configure("err", background="#ffe3e3", foreground=COLORS["red"])
        self.tree.tag_configure("done", foreground=COLORS["green"])
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", self._on_double)
        self.tree.bind("<Return>", lambda e: self.play())
        self.tree.bind("<Button-3>", self._context_menu)
        self.tree.bind("<Button-2>", self._context_menu)
        self.apply_columns()

        self.welcome = tk.Frame(frame, bg=PANEL)
        return outer

    def _build_statusbar(self):
        sb = tk.Frame(self.root, bg="#ede7ff")
        sb.pack(fill="x", side="bottom")
        self.status = tk.Label(sb, text="", font=font(9), bg="#ede7ff", fg=INK, anchor="w", padx=12, pady=5)
        self.status.pack(side="left", fill="x", expand=True)
        self.progress = ttk.Progressbar(sb, length=220, mode="determinate")
        self.message = tk.Label(sb, text="", font=font(9, "bold"), bg="#ede7ff", fg=COLORS["green"], padx=12)
        self.message.pack(side="right")

    def _bind_keys(self):
        r = self.root
        t = lambda: self.targets()  # noqa: E731
        keys = {
            "<Control-o>": lambda e: self.open_folder(), "<Control-O>": lambda e: self.add_files(),
            "<Control-s>": lambda e: self.save_panel(), "<Control-z>": lambda e: self.undo(),
            "<Control-e>": lambda e: dialogs.extended(self, t()), "<Control-f>": lambda e: self.filter_entry.focus_set(),
            "<Control-h>": lambda e: dialogs.replace(self, t()), "<Control-k>": lambda e: dialogs.number(self, t()),
            "<Control-i>": lambda e: dialogs.find_online(self, t()), "<F5>": lambda e: self.reload(),
            "<F1>": lambda e: dialogs.about(self), "<F2>": lambda e: self.rename_one(),
            "<Alt-Key-1>": lambda e: dialogs.tag_to_filename(self, t()),
            "<Alt-Key-2>": lambda e: dialogs.filename_to_tag(self, t()),
            "<Alt-Key-3>": lambda e: dialogs.text_to_tag(self, t()),
            "<Alt-Key-4>": lambda e: dialogs.set_field(self, t()),
        }
        for k, fn in keys.items():
            r.bind_all(k, lambda e, fn=fn: (fn(e), "break")[1] if self._top_is_main(e) else None)
        self.tree.bind("<Control-a>", lambda e: (self.select_all(), "break")[1])
        self.tree.bind("<Delete>", lambda e: self.remove_from_list())

    def _top_is_main(self, e):
        try:
            return e.widget.winfo_toplevel() is self.root
        except (AttributeError, tk.TclError):
            return True

    # ======================================================================
    # welcome screen
    # ======================================================================
    def show_welcome(self):
        w = self.welcome
        for c in w.winfo_children():
            c.destroy()
        w.place(relx=0, rely=0, relwidth=1, relheight=1)
        box = tk.Frame(w, bg=PANEL)
        box.place(relx=0.5, rely=0.45, anchor="center")
        tk.Label(box, text="🎶", font=font(44, family=EMOJI), bg=PANEL).pack()
        label(box, "Welcome to EZ Tag!", 22, True, color=COLORS["purple"]).pack(pady=(4, 2))
        label(box, "Open a folder of music to start. Every format works:\n"
                   "MP3 • FLAC • M4A • AAC • ALAC • OGG • Opus • WMA • WAV • AIFF • APE • WavPack • and more",
              11, color=MUTED, justify="center").pack(pady=(0, 16))
        row = tk.Frame(box, bg=PANEL)
        row.pack()
        BigButton(row, "Open a Folder", "📂", "blue", self.open_folder, width=150, height=86).pack(side="left", padx=6)
        BigButton(row, "Add Songs", "🎵", "cyan", self.add_files, width=150, height=86).pack(side="left", padx=6)
        last = self.settings.get("last_folder")
        if last and os.path.isdir(last):
            BigButton(row, "Open Last Folder\n" + os.path.basename(last)[:22], "🕘", "purple",
                      lambda: self.load_paths([last], replace=True), width=170, height=86).pack(side="left", padx=6)
        label(box, "Tip: in Windows you can also right-click a music folder and pick  'Edit tags with EZ Tag'.",
              9, color=MUTED).pack(pady=(18, 0))

    def hide_welcome(self):
        self.welcome.place_forget()

    # ======================================================================
    # loading
    # ======================================================================
    def open_folder(self, add=False):
        d = filedialog.askdirectory(parent=self.root, title="Pick a music folder",
                                    initialdir=self.settings.get("last_folder") or os.path.expanduser("~"))
        if d:
            self.load_paths([d], replace=not add)

    def add_files(self):
        from .tags import AUDIO_EXTENSIONS
        pat = " ".join("*" + e for e in sorted(AUDIO_EXTENSIONS))
        ps = filedialog.askopenfilenames(parent=self.root, title="Pick songs",
                                         initialdir=self.settings.get("last_folder") or os.path.expanduser("~"),
                                         filetypes=[("All music", pat), ("All files", "*.*")])
        if ps:
            self.load_paths(list(ps), replace=False)

    def load_paths(self, paths, replace=True):
        if self._loading:
            return
        if not self.confirm_pending():
            return
        found = []
        for p in paths:
            if os.path.isdir(p):
                found.extend(tools.scan_folder(p, self.settings["recursive"]))
                self.settings["last_folder"] = os.path.abspath(p)
                self.settings.remember("recent_folders", os.path.abspath(p), 10)
            elif os.path.isfile(p) and is_audio(p):
                found.append(p)
        if replace:
            self.files = []
            self.undo_stack.clear()
            self.touched.clear()
        known = {os.path.normcase(af.path) for af in self.files}
        found = [p for p in found if os.path.normcase(os.path.abspath(p)) not in known]
        if not found:
            if replace:
                self.refresh_list()
            self.flash("No music files found there.", "orange")
            if not self.files:
                self.show_welcome()
            return
        self.hide_welcome()
        self._loading = True
        self.progress.configure(maximum=len(found), value=0)
        self.progress.pack(side="right", padx=8)
        q: queue.Queue = queue.Queue()

        def worker():
            for i, p in enumerate(found):
                try:
                    q.put(AudioFile(p))
                except Exception as e:  # never stop loading because of one bad file
                    af = AudioFile.__new__(AudioFile)
                    af.path, af.fields, af.extras, af.info = os.path.abspath(p), {}, {}, {}
                    af._covers, af._cover_count, af._covers_orig = [], 0, None
                    af.format, af.tag_family, af.error = "?", "?", str(e)
                    af._dirty, af._dirty_extras, af._covers_dirty = set(), set(), False
                    q.put(af)
            q.put(None)
        threading.Thread(target=worker, daemon=True).start()
        start_count = len(self.files)

        def pump():
            done = False
            for _ in range(400):
                try:
                    item = q.get_nowait()
                except queue.Empty:
                    break
                if item is None:
                    done = True
                    break
                self.files.append(item)
            self.progress.configure(value=len(self.files) - start_count)
            self.status.configure(text=f"Loading songs... {len(self.files) - start_count} of {len(found)}")
            if done:
                self._loading = False
                self.progress.pack_forget()
                self.refresh_list()
                self.flash(f"✔ Loaded {len(found)} songs", "green")
            else:
                if len(self.files) - start_count < 400 or (len(self.files) % 2000) < 400:
                    self.refresh_list()
                self.root.after(40, pump)
        pump()

    def reload(self):
        if not self.confirm_pending():
            return
        for af in self.files:
            if os.path.exists(af.path):
                af.load()
            else:
                af.error = "File is gone (moved or deleted)"
        self.refresh_list()
        self.flash("🔄 Reloaded from disk", "blue")

    def clear_list(self):
        if not self.confirm_pending():
            return
        self.files = []
        self.undo_stack.clear()
        self.refresh_list()
        self.show_welcome()

    def _fill_recent(self):
        self.recent_menu.delete(0, "end")
        rec = [p for p in self.settings.get("recent_folders", []) if os.path.isdir(p)]
        if not rec:
            self.recent_menu.add_command(label="(none yet)", state="disabled")
        for p in rec:
            self.recent_menu.add_command(label=p, command=lambda p=p: self.load_paths([p], replace=True))

    # ======================================================================
    # list
    # ======================================================================
    def apply_columns(self):
        cols = [k for k in COLUMNS if self.col_vars[k].get()]
        if not cols:
            cols = ["_filename"]
            self.col_vars["_filename"].set(True)
        self.tree.configure(displaycolumns=cols)
        self.settings["columns"] = cols

    def _schedule_refresh(self):
        if getattr(self, "_refresh_job", None):
            self.root.after_cancel(self._refresh_job)
        self._refresh_job = self.root.after(180, self.refresh_list)

    def visible_files(self):
        q = self.filter_var.get().strip().lower()
        mode = self.show_var.get()
        out = []
        for af in self.files:
            if mode == FILTERS[1] and af.get("title") and af.get("artist"):
                continue
            if mode == FILTERS[2] and af.cover_count:
                continue
            if mode == FILTERS[3] and not af.error:
                continue
            if mode == FILTERS[4] and id(af) not in self.touched:
                continue
            if q:
                hay = " ".join([af.filename] + list(af.fields.values())).lower()
                if not all(word in hay for word in q.split()):
                    continue
            out.append(af)
        if self.sort_col:
            out.sort(key=lambda af: self._sort_key(af, self.sort_col), reverse=self.sort_rev)
        return out

    def _sort_key(self, af, col):
        if col in ("track", "disc", "year", "bpm"):
            m = re.match(r"\d+", af.get(col) or "")
            return (0, int(m.group(0))) if m else (1, 0)
        if col == "_length":
            return af.info.get("length", 0)
        if col == "_bitrate":
            return af.info.get("bitrate", 0)
        if col == "_size":
            return af.info.get("size", 0)
        if col == "cover":
            return af.cover_count
        if col == "status":
            return (bool(af.error), not (af.get("title") and af.get("artist")))
        return self.cell(af, col).lower()

    def sort_by(self, col):
        if self.sort_col == col:
            self.sort_rev = not self.sort_rev
        else:
            self.sort_col, self.sort_rev = col, False
        for k, (title, *_r) in COLUMNS.items():
            arrow = (" ▼" if self.sort_rev else " ▲") if k == col else ""
            self.tree.heading(k, text=title + arrow)
        self.refresh_list()

    def cell(self, af, col):
        if col == "status":
            if af.error:
                return "❌"
            if id(af) in self.touched:
                return "✨"
            return "✔" if (af.get("title") and af.get("artist")) else "⚠"
        if col == "cover":
            return "🖼" if af.cover_count else ""
        if col == "track":
            t, tt = af.get("track"), af.get("totaltracks")
            return f"{t}/{tt}" if t and tt else t
        if col == "disc":
            t, tt = af.get("disc"), af.get("totaldiscs")
            return f"{t}/{tt}" if t and tt else t
        if col == "_filename":
            return af.filename
        if col == "_size":
            return fmt_size(af.info.get("size", 0))
        return af.value_for(col).replace("\n", " ")

    def _row_tags(self, af, i):
        if af.error:
            return ("err",)
        if not (af.get("title") and af.get("artist")):
            return ("warn",)
        return ("odd",) if i % 2 else ()

    def refresh_list(self, keep_selection=True):
        sel = set(self.tree.selection()) if keep_selection else set()
        self._suspend_select = True
        self.tree.delete(*self.tree.get_children())
        self.by_iid = {}
        vis = self.visible_files()
        cols = list(COLUMNS)
        for i, af in enumerate(vis):
            iid = str(id(af))
            self.by_iid[iid] = af
            self.tree.insert("", "end", iid=iid, values=[self.cell(af, c) for c in cols],
                             tags=self._row_tags(af, i))
        keep = [i for i in sel if i in self.by_iid]
        if keep:
            self.tree.selection_set(keep)
        self._suspend_select = False
        if self.files:
            self.hide_welcome()
        self.count_label.configure(text=f"{len(vis)} of {len(self.files)} songs" if len(vis) != len(self.files)
                                   else f"{len(self.files)} songs")
        self.load_panel()
        self.update_status()

    def refresh_rows(self, files):
        cols = list(COLUMNS)
        for af in files:
            iid = str(id(af))
            if self.tree.exists(iid):
                idx = self.tree.index(iid)
                self.tree.item(iid, values=[self.cell(af, c) for c in cols], tags=self._row_tags(af, idx))

    def selected(self) -> list[AudioFile]:
        return [self.by_iid[i] for i in self.tree.selection() if i in self.by_iid]

    def has_selection(self):
        return bool(self.tree.selection())

    def targets(self) -> list[AudioFile]:
        """Selected songs, or every visible song when nothing is selected."""
        sel = self.selected()
        if sel:
            # keep list order
            order = {iid: n for n, iid in enumerate(self.tree.get_children())}
            return sorted(sel, key=lambda af: order.get(str(id(af)), 0))
        return [self.by_iid[i] for i in self.tree.get_children()]

    def select_all(self):
        self.tree.selection_set(self.tree.get_children())

    def select_same_folder(self):
        sel = self.selected()
        if not sel:
            return
        folders = {af.folder for af in sel}
        self.tree.selection_set([i for i, af in self.by_iid.items() if af.folder in folders])

    def reveal(self, files):
        ids = [str(id(af)) for af in files if self.tree.exists(str(id(af)))]
        if ids:
            self.tree.selection_set(ids)
            self.tree.see(ids[0])

    def remove_from_list(self):
        sel = self.selected()
        if not sel or not self.confirm_pending():
            return
        gone = {id(af) for af in sel}
        self.files = [af for af in self.files if id(af) not in gone]
        self.tree.selection_remove(self.tree.selection())
        self.refresh_list(False)
        if not self.files:
            self.show_welcome()

    def _on_select(self, _e=None):
        if self._suspend_select:
            return
        if self._panel_dirty():
            self.save_panel(auto=True, files=getattr(self, "_panel_files", []))
        self.load_panel()
        self.update_status()

    def _on_double(self, e):
        if self.tree.identify_region(e.x, e.y) == "heading":
            return
        col_id = self.tree.identify_column(e.x)
        try:
            col = self.tree["displaycolumns"][int(col_id[1:]) - 1]
        except (ValueError, IndexError):
            col = None
        if col in self.panel_widgets:
            self.panel_widgets[col].focus_set()
            self.panel_widgets[col].select_range(0, "end")
        elif col == "_filename":
            self.rename_one()
        elif col == "cover":
            self.cover_add()
        else:
            self.play()

    def _context_menu(self, e):
        iid = self.tree.identify_row(e.y)
        if iid and iid not in self.tree.selection():
            self.tree.selection_set(iid)
        t = lambda: self.targets()  # noqa: E731
        m = tk.Menu(self.root, tearoff=False)
        for text, cmd in (("▶️  Play", self.play), ("📁  Open Folder", self.open_folder_of),
                          ("✏️  Rename File...", self.rename_one), None,
                          ("🗂️  All Tag Fields...", lambda: dialogs.extended(self, t())),
                          ("🔤  Tag → File Name...", lambda: dialogs.tag_to_filename(self, t())),
                          ("📝  File Name → Tag...", lambda: dialogs.filename_to_tag(self, t())),
                          ("🧠  Smart Guess From File Name", self.smart_guess),
                          ("🌐  Find Online...", lambda: dialogs.find_online(self, t())),
                          ("🖼️  Cover Art...", lambda: dialogs.covers(self, t())), None,
                          ("Select Same Folder", self.select_same_folder),
                          ("Remove From List", self.remove_from_list),
                          ("🧹  Remove Tags...", self.remove_tags)):
            if text is None:
                m.add_separator()
            else:
                m.add_command(label=text, command=cmd)
        m.tk_popup(e.x_root, e.y_root)

    # ======================================================================
    # left panel
    # ======================================================================
    def load_panel(self):
        sel = self.selected()
        self._panel_files = sel
        self._loading_panel = True
        n = len(sel)
        self.sel_label.configure(text=("Nothing selected" if not n else
                                       f"{n} song{'s' if n != 1 else ''} selected"))
        for key, var in self.panel_vars.items():
            vals = [af.get(key) for af in sel]
            uniq = list(dict.fromkeys(vals))
            if not sel:
                text = ""
            elif len(uniq) == 1:
                text = uniq[0]
            else:
                text = KEEP_TEXT
            var.set(text)
            self.panel_initial[key] = text
            w = self.panel_widgets[key]
            others = [v for v in uniq if v][:40]
            base = GENRES if key == "genre" else []
            w.configure(values=([KEEP_TEXT] if len(sel) > 1 else []) + [BLANK_TEXT] + others +
                        [g for g in base if g not in others])
            w.configure(foreground=KEEP if text == KEEP_TEXT else INK)
            state = "normal" if sel else "disabled"
            w.configure(state=state)
        self._loading_panel = False
        self.edit_hint.configure(text="")
        self.show_cover(sel)
        self.show_info(sel)

    def _combo_focus(self, key):
        v = self.panel_vars[key]
        if v.get() == KEEP_TEXT:
            self.panel_widgets[key].select_range(0, "end")

    def _mark_edit(self, key):
        if getattr(self, "_loading_panel", False):
            return
        w = self.panel_widgets[key]
        w.configure(foreground=KEEP if self.panel_vars[key].get() == KEEP_TEXT else INK)
        if self._panel_dirty():
            self.edit_hint.configure(text="✏️ Not saved yet - press 💾 Save Tags (or Enter).")
        else:
            self.edit_hint.configure(text="")

    def _panel_changes(self):
        ch = {}
        for key, var in self.panel_vars.items():
            text = var.get()
            if text == self.panel_initial.get(key, "") or text == KEEP_TEXT:
                continue
            ch[key] = "" if text == BLANK_TEXT else text
        return ch

    def _panel_dirty(self):
        return bool(getattr(self, "_panel_files", None)) and bool(self._panel_changes())

    def save_panel(self, auto=False, files=None):
        files = files if files is not None else self.selected()
        ch = self._panel_changes()
        if not files:
            if not auto:
                self.flash("Pick one or more songs in the list first.", "orange")
            return
        if not ch:
            if not auto:
                self.flash("Nothing changed.", "gray")
            return
        uses_codes = any(re.search(r"%[a-z_]+%", v) for v in ch.values())
        if uses_codes:
            values = {id(af): {k: tools.render(v, af) for k, v in ch.items()} for af in files}
        else:
            values = {id(af): ch for af in files}
        self.apply(files, lambda af: [af.set(k, v.strip() if k != "comment" else v)
                                      for k, v in values[id(af)].items()], "Edit tags")

    # ---------------------------------------------------------- cover
    def show_cover(self, sel):
        c = self.cover_canvas
        c.delete("all")
        self.cover_img = None
        w = h = 150
        if not sel:
            c.create_text(w / 2, h / 2, text="🖼️\nCover", font=font(14, family=EMOJI), fill="#b197fc", justify="center")
            self.cover_info.configure(text="")
            return
        datas = {(af.covers[0].data if af.cover_count and af.covers else b"") for af in sel[:60]}
        if len(datas) > 1:
            c.create_text(w / 2, h / 2, text="🖼️ 🖼️\nDifferent\ncovers", font=font(11, "bold"),
                          fill="#9775fa", justify="center")
            self.cover_info.configure(text="The selected songs have different covers")
            return
        data = datas.pop()
        if not data:
            c.create_text(w / 2, h / 2 - 10, text="➕", font=font(26, family=EMOJI), fill="#b197fc")
            c.create_text(w / 2, h / 2 + 30, text="Click to add a cover", font=font(9), fill="#9775fa")
            self.cover_info.configure(text="No cover picture")
            return
        cov = sel[0].covers[0]
        img = None
        dims = ""
        if Image is not None:
            try:
                im = Image.open(io.BytesIO(data))
                dims = f"{im.size[0]}×{im.size[1]}"
                im = im.convert("RGB")
                im.thumbnail((w, h))
                img = ImageTk.PhotoImage(im)
            except Exception:
                img = None
        if img is None and cov.mime in ("image/png", "image/gif"):
            try:
                import base64
                ph = tk.PhotoImage(data=base64.b64encode(data))
                f = max(1, (max(ph.width(), ph.height()) + w - 1) // w)
                img = ph.subsample(f, f) if f > 1 else ph
                dims = f"{ph.width()}×{ph.height()}"
            except tk.TclError:
                img = None
        if img is not None:
            self.cover_img = img
            c.create_image(w / 2, h / 2, image=img)
        else:
            c.create_text(w / 2, h / 2, text="🖼️\nHas a cover", font=font(12, "bold"), fill="#7950f2",
                          justify="center")
        extra = f" + {len(sel[0].covers) - 1} more" if len(sel[0].covers) > 1 else ""
        self.cover_info.configure(text=f"{cov.mime.split('/')[-1].upper()} {dims}  {fmt_size(len(data))}{extra}")

    def cover_add(self):
        sel = self.selected()
        if not sel:
            self.flash("Pick songs first, then add a cover.", "orange")
            return
        p = filedialog.askopenfilename(parent=self.root, title="Pick a cover picture",
                                       initialdir=sel[0].folder,
                                       filetypes=[("Pictures", "*.jpg *.jpeg *.png *.gif *.bmp *.webp"),
                                                  ("All files", "*.*")])
        if not p:
            return
        with open(p, "rb") as fh:
            data = fh.read()
        self.apply(sel, lambda af: af.set_covers([Cover(data)] + [c for c in af.covers if c.ptype != 3]),
                   "Add cover")

    def cover_save(self):
        sel = self.selected()
        if not sel or not sel[0].cover_count:
            self.flash("The selected song has no cover to save.", "orange")
            return
        c = sel[0].covers[0]
        name = tools.safe_part(sel[0].get("album") or "cover") + c.ext
        p = filedialog.asksaveasfilename(parent=self.root, initialdir=sel[0].folder, initialfile=name,
                                         defaultextension=c.ext)
        if p:
            with open(p, "wb") as fh:
                fh.write(c.data)
            self.flash("💾 Cover saved", "green")

    def cover_remove(self):
        sel = [af for af in self.selected() if af.cover_count]
        if not sel:
            return
        self.apply(sel, lambda af: af.set_covers([]), "Remove cover")

    def show_info(self, sel):
        if len(sel) != 1:
            if sel:
                total = sum(af.info.get("length", 0) for af in sel)
                size = sum(af.info.get("size", 0) for af in sel)
                self.info_box.configure(text=f"⏱ {fmt_length(total)} total   💽 {fmt_size(size)}")
            else:
                self.info_box.configure(text="")
            return
        af = sel[0]
        i = af.info
        lines = [f"🎵 {af.format}" + (f" ({i['codec']})" if i.get("codec") else ""),
                 f"⏱ {fmt_length(i.get('length', 0))}   📶 {i.get('bitrate', 0) // 1000} kbps",
                 f"🔊 {i.get('sample_rate', 0)} Hz  {'Stereo' if i.get('channels') == 2 else ('Mono' if i.get('channels') == 1 else str(i.get('channels', '')) + ' ch')}"
                 + (f"  {i['bits']}-bit" if i.get("bits") else ""),
                 f"🏷 {af.tag_family}   💽 {fmt_size(i.get('size', 0))}"]
        if af.extras:
            lines.append(f"★ {len(af.extras)} extra field{'s' if len(af.extras) != 1 else ''}")
        if af.error:
            lines.append("❌ " + af.error)
        self.info_box.configure(text="\n".join(lines))

    # ======================================================================
    # the one place that changes files (with undo)
    # ======================================================================
    def apply(self, files, func, label_text, renames=None, batch=None):
        files = list(dict.fromkeys(files))
        if not files:
            self.flash("Nothing to change.", "gray")
            return
        renames = renames or {}
        if renames and self.settings.get("confirm_rename") and len(renames) > 1:
            if not messagebox.askyesno(APP_NAME, f"Rename {len(renames)} files now?\n(You can Undo.)",
                                       parent=self.root):
                return
        before = {id(af): (dict(af.fields), dict(af.extras), None, af.path) for af in files}
        errors = []
        if batch:
            batch(files)
        if func:
            for af in files:
                try:
                    func(af)
                except Exception as e:
                    errors.append((af, e))
        for af in files:  # remember old pictures only for songs whose pictures changed
            if af._covers_dirty and af._covers_orig is not None:
                f, e, _c, p = before[id(af)]
                before[id(af)] = (f, e, list(af._covers_orig), p)
        changed = []
        show_progress = len(files) > 30
        if show_progress:
            self.progress.configure(maximum=len(files), value=0)
            self.progress.pack(side="right", padx=8)
        s = self.settings
        for n, af in enumerate(files):
            did = False
            try:
                if af.dirty:
                    did = af.save(s["id3_version"], s["id3v1"], s["keep_mtime"]) or did
                new = renames.get(id(af))
                if new and new != af.path:
                    tools.rename_file(af, new)
                    did = True
            except Exception as e:
                errors.append((af, e))
                af.load() if os.path.exists(af.path) else None
            if did:
                changed.append(af)
                self.touched.add(id(af))
            if show_progress and n % 10 == 0:
                self.progress.configure(value=n)
                self.status.configure(text=f"{label_text}... {n} of {len(files)}")
                self.root.update_idletasks()
        if show_progress:
            self.progress.pack_forget()
        if changed:
            self.undo_stack.append((label_text, [(af, before[id(af)]) for af in changed]))
            del self.undo_stack[:-30]
        if renames and changed:
            self.refresh_list()
        else:
            self.refresh_rows(files)
            self.load_panel()
            self.update_status()
        if errors:
            msg = "\n".join(f"• {af.filename}: {_friendly(e)}" for af, e in errors[:12])
            more = f"\n...and {len(errors) - 12} more" if len(errors) > 12 else ""
            messagebox.showwarning(APP_NAME, f"Some songs could not be changed:\n\n{msg}{more}", parent=self.root)
        if changed:
            self.flash(f"✔ {label_text}: {len(changed)} song{'s' if len(changed) != 1 else ''} saved", "green")
        elif not errors:
            self.flash("Nothing needed changing.", "gray")

    def undo(self):
        if not self.undo_stack:
            self.flash("Nothing to undo.", "gray")
            return
        label_text, items = self.undo_stack.pop()
        errors = []
        s = self.settings
        for af, (fields, extras, covers, path) in items:
            try:
                if af.path != path:
                    tools.rename_file(af, path)
                for k in set(fields) | set(af.fields):
                    af.set(k, fields.get(k, ""))
                for k in set(extras) | set(af.extras):
                    af.set(k, extras.get(k, ""))
                if covers is not None and [c.data for c in covers] != [c.data for c in af.covers]:
                    af.set_covers(covers)
                af.save(s["id3_version"], s["id3v1"], s["keep_mtime"])
            except Exception as e:
                errors.append((af, e))
        self.refresh_list()
        if errors:
            messagebox.showwarning(APP_NAME, "Could not undo everything:\n" +
                                   "\n".join(f"• {af.filename}: {_friendly(e)}" for af, e in errors[:10]),
                                   parent=self.root)
        self.flash(f"↩️ Undone: {label_text}", "blue")

    # ======================================================================
    # smaller actions
    # ======================================================================
    def smart_guess(self):
        fs = self.targets()
        if dialogs.need_files(self, fs):
            guesses = {id(af): tools.guess_from_filename(af) for af in fs}
            self.apply(fs, lambda af: [af.set(k, v) for k, v in guesses[id(af)].items() if not af.get(k)],
                       "Smart guess")

    def remove_brackets(self):
        fs = self.targets()
        if dialogs.need_files(self, fs):
            self.apply(fs, lambda af: af.set("title", tools.remove_brackets(af.get("title"))), "Remove brackets")

    def swap_artist_title(self):
        fs = self.targets()
        if dialogs.need_files(self, fs):
            def work(af):
                a, t = af.get("artist"), af.get("title")
                af.set("artist", t)
                af.set("title", a)
            self.apply(fs, work, "Swap artist/title")

    def rewrite_id3(self, version):
        fs = [af for af in self.targets() if af.tag_family == "ID3v2"]
        if not fs:
            self.flash("No MP3/ID3 songs selected.", "orange")
            return
        old = self.settings["id3_version"]
        self.settings["id3_version"] = version

        def work(af):
            af._dirty.update(af.fields.keys())
            af._dirty_extras.update(af.extras.keys())
            af._covers_dirty = True
        try:
            self.apply(fs, work, f"Rewrite as ID3v2.{version}")
        finally:
            self.settings["id3_version"] = old

    def remove_tags(self):
        fs = self.targets()
        if not dialogs.need_files(self, fs):
            return
        if not messagebox.askyesno(APP_NAME, f"Remove ALL tags and covers from {len(fs)} song"
                                   f"{'s' if len(fs) != 1 else ''}?\n\n(You can Undo this.)", parent=self.root):
            return
        before = [(af, (dict(af.fields), dict(af.extras), list(af.covers), af.path)) for af in fs]
        errors = []
        for af in fs:
            try:
                af.remove_tags()
                self.touched.add(id(af))
            except Exception as e:
                errors.append((af, e))
        self.undo_stack.append(("Remove tags", before))
        self.refresh_rows(fs)
        self.load_panel()
        if errors:
            messagebox.showwarning(APP_NAME, "\n".join(f"• {af.filename}: {_friendly(e)}" for af, e in errors[:10]),
                                   parent=self.root)
        self.flash(f"🧹 Removed tags from {len(fs) - len(errors)} songs", "green")

    def rename_one(self):
        sel = self.selected()
        if len(sel) != 1:
            self.flash("Pick one song to rename.", "orange")
            return
        af = sel[0]
        new = dialogs.simple_ask(self.root, "Rename File", "New file name (the .ext stays the same):", af.stem)
        if new and new.strip() and new.strip() != af.stem:
            self.apply([af], None, "Rename", renames={id(af): os.path.join(af.folder, tools.safe_part(new) + af.ext)})

    def sort_into_folders(self):
        fs = self.targets()
        if not dialogs.need_files(self, fs):
            return
        base = filedialog.askdirectory(parent=self.root, title="Where should the Artist\\Album folders go?",
                                       initialdir=self.settings.get("last_folder"))
        if not base:
            return
        fmt = base.replace("/", "\\") + "\\$if2(%albumartist%,%artist%)\\%album%\\$num(%track%,2) - %title%"
        dialogs_fmt = fmt
        self.settings.remember("tag2name_history", dialogs_fmt)
        dialogs.tag_to_filename(self, fs)

    def play(self):
        sel = self.selected()
        if sel:
            self.open_path(sel[0].path)

    def open_folder_of(self):
        sel = self.selected()
        if not sel:
            return
        p = sel[0].path
        if sys.platform.startswith("win"):
            subprocess.Popen(["explorer", "/select,", os.path.normpath(p)])
        else:
            self.open_path(os.path.dirname(p))

    def open_path(self, p):
        try:
            if sys.platform.startswith("win"):
                os.startfile(p)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", p])
            else:
                subprocess.Popen(["xdg-open", p])
        except OSError as e:
            messagebox.showerror(APP_NAME, str(e), parent=self.root)

    # ======================================================================
    # status
    # ======================================================================
    def update_status(self):
        n = len(self.files)
        sel = self.selected()
        total = sum(af.info.get("length", 0) for af in self.files)
        missing = sum(1 for af in self.files if not (af.get("title") and af.get("artist")))
        nocover = sum(1 for af in self.files if not af.cover_count)
        parts = [f"🎵 {n} songs", f"⏱ {fmt_length(total)}"]
        if sel:
            parts.append(f"✅ {len(sel)} selected")
        if missing:
            parts.append(f"⚠ {missing} missing title/artist")
        if nocover:
            parts.append(f"🖼 {nocover} without cover")
        if self.undo_stack:
            parts.append(f"↩️ can undo: {self.undo_stack[-1][0]}")
        self.status.configure(text="     ".join(parts))

    def flash(self, text, color="green"):
        self.message.configure(text=text, fg=COLORS.get(color, color))
        if getattr(self, "_flash_job", None):
            self.root.after_cancel(self._flash_job)
        self._flash_job = self.root.after(6000, lambda: self.message.configure(text=""))
        self.update_status()

    def confirm_pending(self):
        if self._panel_dirty():
            ans = messagebox.askyesnocancel(APP_NAME, "You typed changes that are not saved yet.\nSave them now?",
                                            parent=self.root)
            if ans is None:
                return False
            if ans:
                self.save_panel(files=self._panel_files)
        return True

    def quit(self):
        if not self.confirm_pending():
            return
        try:
            self.settings["zoomed"] = self.root.state() == "zoomed"
            if not self.settings["zoomed"]:
                self.settings["geometry"] = self.root.geometry()
            self.settings["col_widths"] = {k: self.tree.column(k, "width") for k in COLUMNS}
        except tk.TclError:
            pass
        self.settings.save()
        self.root.destroy()
        # a downloaded update installs now, quietly (and reopens EZ Tag if asked)
        try:
            self.updater.run_pending_setup()
        except Exception:
            pass


def _friendly(e):
    if isinstance(e, PermissionError):
        return "the file is open in another program or is read-only"
    if isinstance(e, FileNotFoundError):
        return "the file was moved or deleted"
    return str(e) or e.__class__.__name__


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("DrSzaba.EZTag")
        except Exception:
            pass
    root = tk.Tk()
    App(root, [a for a in argv if os.path.exists(a)])
    root.mainloop()
