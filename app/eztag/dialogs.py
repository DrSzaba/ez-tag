"""All the pop-up windows: converters, actions, online lookup, covers, export, settings."""
from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox, ttk

from . import APP_NAME, VERSION, online, tools
from .tags import FIELD_KEYS, FIELD_LABELS, Cover, PICTURE_TYPES, fmt_length
from .theme import (COLORS, INK, KEEP, LINE, MUTED, PANEL, Dialog, PillButton, entry,
                    font, label)

KEEP_TEXT = "< keep >"
BLANK_TEXT = "< blank >"
DONATE_URL = "https://cash.app/$Szaba"
GITHUB_URL = "https://github.com/DrSzaba/ez-tag"
SITE_URL = "https://drszaba.github.io/ez-tag/"


# ===========================================================================
# helpers
# ===========================================================================

class PreviewTable(tk.Frame):
    def __init__(self, master, columns, height=10, widths=None):
        super().__init__(master, bg=PANEL)
        self.tree = ttk.Treeview(self, columns=[c for c, _ in columns], show="headings",
                                 height=height, selectmode="browse")
        for i, (key, title) in enumerate(columns):
            self.tree.heading(key, text=title, anchor="w")
            w = (widths or {}).get(key, 220)
            self.tree.column(key, width=w, anchor="w", stretch=True)
        sb = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.tag_configure("bad", foreground=COLORS["red"])
        self.tree.tag_configure("same", foreground=MUTED)
        self.tree.tag_configure("new", foreground=COLORS["green"])

    def set_rows(self, rows, tags=None):
        self.tree.delete(*self.tree.get_children())
        for i, r in enumerate(rows):
            t = (tags[i],) if tags and tags[i] else ()
            self.tree.insert("", "end", iid=str(i), values=r, tags=t)


def combo(master, values, var=None, width=46):
    c = ttk.Combobox(master, values=values, textvariable=var, width=width, font=font(11))
    return c


def field_choices(include_all=False):
    out = [f"{FIELD_LABELS[k]}  ({k})" for k in FIELD_KEYS]
    return (["All fields"] if include_all else []) + out


def key_from_choice(text):
    if text.startswith("All fields"):
        return "*"
    if "(" in text and text.endswith(")"):
        return text[text.rindex("(") + 1:-1]
    return text.strip().lower()


def help_box(master, rows):
    box = tk.Frame(master, bg="#f8f0fc", padx=10, pady=8)
    label(box, "Codes you can use:", 9, True, bg="#f8f0fc").grid(row=0, column=0, sticky="w", columnspan=2)
    for i, (code, what) in enumerate(rows, start=1):
        tk.Label(box, text=code, font=("Consolas", 9), bg="#f8f0fc", fg=COLORS["grape"]).grid(
            row=i, column=0, sticky="w", padx=(0, 12))
        label(box, what, 9, bg="#f8f0fc", color=MUTED).grid(row=i, column=1, sticky="w")
    return box


def need_files(app, files) -> bool:
    if not files:
        messagebox.showinfo(APP_NAME, "First open a folder or add some songs.", parent=app.root)
        return False
    return True


def scope_text(app, files):
    n = len(files)
    return f"Working on {n} song{'s' if n != 1 else ''}" + (
        " (the ones you selected)" if app.has_selection() else " (all songs in the list)")


# ===========================================================================
# Tag -> File name
# ===========================================================================

def tag_to_filename(app, files):
    if not need_files(app, files):
        return
    d = Dialog(app.root, "Tag → File Name", "🔤", "orange", 820, 720)
    label(d.body, scope_text(app, files), 10, color=MUTED).pack(anchor="w")
    label(d.body, "Name the files like this:", 11, True).pack(anchor="w", pady=(8, 2))
    var = tk.StringVar(value=app.settings["tag2name_history"][0])
    cb = combo(d.body, app.settings["tag2name_history"], var, 70)
    cb.pack(fill="x")
    label(d.body, "Tip: use \\ to make folders, for example  %artist%\\%album%\\%title%",
          9, color=MUTED).pack(anchor="w", pady=(2, 8))
    table = PreviewTable(d.body, [("old", "Now"), ("new", "Will become")], 11,
                         {"old": 330, "new": 400})
    table.pack(fill="both", expand=True)
    help_box(d.body, tools.FUNCTION_HELP[:6]).pack(fill="x", pady=(8, 0))
    plan = []

    def refresh(*_):
        plan.clear()
        rows, tags = [], []
        taken = set()
        for af in files:
            new = tools.filename_from_tags(af, var.get()) if var.get().strip() else None
            if new and new.lower() != af.path.lower():
                new = tools.unique_path(new, taken)
                taken.add(new.lower())
            plan.append((af, new))
            shown = os.path.relpath(new, af.folder) if new else "(empty - skipped)"
            rows.append((af.filename, shown))
            tags.append("bad" if not new else ("same" if new == af.path else "new"))
        table.set_rows(rows[:500], tags[:500])
    var.trace_add("write", refresh)
    refresh()

    def go():
        fmt = var.get().strip()
        if not fmt:
            return
        app.settings.remember("tag2name_history", fmt)
        d.close()
        todo = [(af, new) for af, new in plan if new and new != af.path]
        app.apply([af for af, _ in todo], None, "Rename files",
                  renames={id(af): new for af, new in todo})
    d.add_button("✔  Rename Files", "orange", go)
    d.add_button("Cancel", "gray", d.close)
    cb.focus_set()
    d.show()


# ===========================================================================
# File name -> Tag
# ===========================================================================

def filename_to_tag(app, files):
    if not need_files(app, files):
        return
    d = Dialog(app.root, "File Name → Tag", "📝", "purple", 880, 650)
    label(d.body, scope_text(app, files), 10, color=MUTED).pack(anchor="w")
    label(d.body, "My file names look like this:", 11, True).pack(anchor="w", pady=(8, 2))
    row = tk.Frame(d.body, bg=PANEL)
    row.pack(fill="x")
    var = tk.StringVar(value=app.settings["name2tag_history"][0])
    cb = combo(row, app.settings["name2tag_history"], var, 60)
    cb.pack(side="left", fill="x", expand=True)
    smart = tk.BooleanVar(value=False)
    label(d.body, "Use %dummy% for parts to skip. Use \\ to read folder names too.",
          9, color=MUTED).pack(anchor="w", pady=(2, 8))
    keys = ["title", "artist", "album", "track", "year"]
    table = PreviewTable(d.body, [("file", "File name")] + [(k, FIELD_LABELS[k]) for k in keys], 12,
                         {"file": 280, "title": 170, "artist": 130, "album": 130, "track": 50, "year": 60})
    table.pack(fill="both", expand=True)
    results = []

    def refresh(*_):
        results.clear()
        rows, tags = [], []
        for af in files:
            res = tools.guess_from_filename(af) if smart.get() else tools.tags_from_filename(af, var.get())
            results.append((af, res))
            if res is None:
                rows.append([af.filename] + ["(no match)"] + [""] * (len(keys) - 1))
                tags.append("bad")
            else:
                rows.append([af.filename] + [res.get(k, "") for k in keys])
                tags.append("new")
        table.set_rows(rows[:500], tags[:500])

    def use_smart():
        smart.set(True)
        refresh()

    def pattern_changed(*_):
        smart.set(False)
        refresh()
    var.trace_add("write", pattern_changed)
    PillButton(row, "🧠 Smart Guess", "teal", use_smart).pack(side="left", padx=(8, 0))
    refresh()

    def go():
        if not smart.get():
            app.settings.remember("name2tag_history", var.get())
        d.close()
        todo = [(af, res) for af, res in results if res]
        mapping = {id(af): res for af, res in todo}
        app.apply([af for af, _ in todo], lambda af: [af.set(k, v) for k, v in mapping[id(af)].items()
                                                      if k in FIELD_LABELS or not k.startswith("_")],
                  "File name → Tag")
    d.add_button("✔  Fill In Tags", "purple", go)
    d.add_button("Cancel", "gray", d.close)
    d.show()


# ===========================================================================
# Text -> Tag
# ===========================================================================

def text_to_tag(app, files):
    if not need_files(app, files):
        return
    d = Dialog(app.root, "Text List → Tag", "📋", "cyan", 900, 700)
    label(d.body, scope_text(app, files) + " - one line per song, in list order.", 10,
          color=MUTED).pack(anchor="w")
    top = tk.Frame(d.body, bg=PANEL)
    top.pack(fill="x", pady=(8, 4))
    label(top, "Paste a track list (or load a .txt file):", 11, True).pack(side="left")

    txt = tk.Text(d.body, height=8, font=("Consolas", 10), bg="#f8f9fa", relief="flat",
                  highlightthickness=2, highlightbackground=LINE)
    txt.pack(fill="x")

    def load_file():
        p = filedialog.askopenfilename(parent=d, filetypes=[("Text", "*.txt *.csv"), ("All", "*.*")])
        if p:
            with open(p, encoding="utf-8", errors="replace") as fh:
                txt.delete("1.0", "end")
                txt.insert("1.0", fh.read())
            refresh()
    PillButton(top, "📂 Load .txt", "cyan", load_file, fsize=9).pack(side="right")
    label(d.body, "Each line looks like:", 11, True).pack(anchor="w", pady=(8, 2))
    var = tk.StringVar(value="%track%. %title%")
    cb = combo(d.body, ["%track%. %title%", "%track% - %title%", "%title%",
                        "%artist% - %title%", "%track%. %artist% - %title%"], var, 60)
    cb.pack(fill="x")
    table = PreviewTable(d.body, [("file", "File"), ("vals", "Will get")], 8, {"file": 300, "vals": 480})
    table.pack(fill="both", expand=True, pady=(8, 0))
    parsed = []

    def refresh(*_):
        lines = [ln for ln in txt.get("1.0", "end").splitlines() if ln.strip()]
        parsed[:] = tools.tags_from_lines(lines, var.get())
        rows, tags = [], []
        for i, af in enumerate(files):
            r = parsed[i] if i < len(parsed) else None
            rows.append((af.filename, "  |  ".join(f"{k}: {v}" for k, v in r.items()) if r else "(no line)"))
            tags.append("new" if r else "bad")
        table.set_rows(rows[:500], tags[:500])
    var.trace_add("write", refresh)
    txt.bind("<KeyRelease>", refresh)
    refresh()

    def go():
        d.close()
        pairs = {id(af): parsed[i] for i, af in enumerate(files) if i < len(parsed) and parsed[i]}
        app.apply([af for af in files if id(af) in pairs],
                  lambda af: [af.set(k, v) for k, v in pairs[id(af)].items()], "Text → Tag")
    d.add_button("✔  Fill In Tags", "cyan", go)
    d.add_button("Cancel", "gray", d.close)
    d.show()


# ===========================================================================
# Set a field with a format (Tag -> Tag)
# ===========================================================================

def set_field(app, files, field=None):
    if not need_files(app, files):
        return
    d = Dialog(app.root, "Set a Field (Tag → Tag)", "✏️", "indigo", 860, 780)
    label(d.body, scope_text(app, files), 10, color=MUTED).pack(anchor="w")
    label(d.body, "Field to change:", 11, True).pack(anchor="w", pady=(8, 2))
    fvar = tk.StringVar(value=field_choices()[0] if not field else
                        f"{FIELD_LABELS.get(field, field)}  ({field})")
    combo(d.body, field_choices(), fvar, 40).pack(anchor="w")
    label(d.body, "New value (you can mix fields and text):", 11, True).pack(anchor="w", pady=(10, 2))
    var = tk.StringVar(value=app.settings["format_history"][0])
    combo(d.body, app.settings["format_history"], var, 70).pack(fill="x")
    table = PreviewTable(d.body, [("file", "Song"), ("old", "Now"), ("new", "Will become")], 9,
                         {"file": 240, "old": 230, "new": 260})
    table.pack(fill="both", expand=True, pady=(10, 0))
    help_box(d.body, tools.FUNCTION_HELP).pack(fill="x", pady=(8, 0))

    def refresh(*_):
        key = key_from_choice(fvar.get())
        rows, tags = [], []
        for af in files[:500]:
            old = af.value_for(key)
            new = tools.render(var.get(), af)
            rows.append((af.filename, old, new))
            tags.append("same" if old == new else "new")
        table.set_rows(rows, tags)
    var.trace_add("write", refresh)
    fvar.trace_add("write", refresh)
    refresh()

    def go():
        key = key_from_choice(fvar.get())
        fmt = var.get()
        app.settings.remember("format_history", fmt)
        d.close()
        new = {id(af): tools.render(fmt, af) for af in files}
        app.apply(files, lambda af: af.set(key, new[id(af)]), f"Set {key}")
    d.add_button("✔  Apply", "indigo", go)
    d.add_button("Cancel", "gray", d.close)
    d.show()


# ===========================================================================
# Replace
# ===========================================================================

def replace(app, files):
    if not need_files(app, files):
        return
    d = Dialog(app.root, "Find & Replace", "🔁", "indigo", 800, 620)
    label(d.body, scope_text(app, files), 10, color=MUTED).pack(anchor="w")
    grid = tk.Frame(d.body, bg=PANEL)
    grid.pack(fill="x", pady=8)
    fvar = tk.StringVar(value="All fields")
    find, repl = tk.StringVar(), tk.StringVar()
    for r, (lbl, w) in enumerate((("In:", combo(grid, field_choices(True) + ["File name  (_filename)"], fvar, 40)),
                                  ("Find:", entry(grid, find, 50)),
                                  ("Replace with:", entry(grid, repl, 50)))):
        label(grid, lbl, 11, True).grid(row=r, column=0, sticky="w", pady=4, padx=(0, 10))
        w.grid(row=r, column=1, sticky="w", pady=4)
    opts = tk.Frame(d.body, bg=PANEL)
    opts.pack(fill="x")
    mc, ww, rx = tk.BooleanVar(), tk.BooleanVar(), tk.BooleanVar()
    for t, v in (("Match UPPER/lower case", mc), ("Whole words only", ww), ("Regular expression (advanced)", rx)):
        ttk.Checkbutton(opts, text=t, variable=v).pack(side="left", padx=(0, 16))
    table = PreviewTable(d.body, [("file", "Song"), ("field", "Field"), ("old", "Now"), ("new", "Will become")],
                         10, {"file": 200, "field": 90, "old": 200, "new": 220})
    table.pack(fill="both", expand=True, pady=(10, 0))

    def changes():
        key = key_from_choice(fvar.get())
        keys = FIELD_KEYS if key == "*" else [key]
        out = []
        for af in files:
            for k in keys:
                old = af.stem if k == "_filename" else af.get(k)
                if not old:
                    continue
                new = tools.replace_text(old, find.get(), repl.get(), mc.get(), ww.get(), rx.get())
                if new != old:
                    out.append((af, k, old, new))
        return out

    def refresh(*_):
        ch = changes()
        table.set_rows([(af.filename, k, o, n) for af, k, o, n in ch[:500]], ["new"] * min(500, len(ch)))
    for v in (fvar, find, repl, mc, ww, rx):
        v.trace_add("write", refresh)

    def go():
        ch = changes()
        d.close()
        tag_changes, renames = {}, {}
        for af, k, old, new in ch:
            if k == "_filename":
                renames[id(af)] = os.path.join(af.folder, tools.safe_part(new) + af.ext)
            else:
                tag_changes.setdefault(id(af), []).append((k, new))
        targets = [af for af in files if id(af) in tag_changes or id(af) in renames]
        app.apply(targets, lambda af: [af.set(k, v) for k, v in tag_changes.get(id(af), [])],
                  "Replace", renames=renames)
    d.add_button("✔  Replace", "indigo", go)
    d.add_button("Cancel", "gray", d.close)
    d.show()


# ===========================================================================
# Case
# ===========================================================================

def change_case(app, files):
    if not need_files(app, files):
        return
    d = Dialog(app.root, "Change Upper / Lower Case", "🔠", "pink", 760, 600)
    label(d.body, scope_text(app, files), 10, color=MUTED).pack(anchor="w")
    label(d.body, "Make it look like:", 11, True).pack(anchor="w", pady=(8, 2))
    mode = tk.StringVar(value="caps")
    for text, m in tools.CASE_MODES:
        ttk.Radiobutton(d.body, text=text, value=m, variable=mode).pack(anchor="w")
    label(d.body, "In these fields:", 11, True).pack(anchor="w", pady=(10, 2))
    fr = tk.Frame(d.body, bg=PANEL)
    fr.pack(fill="x")
    fvars = {}
    for i, k in enumerate(["title", "artist", "album", "albumartist", "genre", "composer", "comment"]):
        fvars[k] = tk.BooleanVar(value=k in ("title", "artist", "album", "albumartist"))
        ttk.Checkbutton(fr, text=FIELD_LABELS[k], variable=fvars[k]).grid(row=i // 4, column=i % 4, sticky="w", padx=(0, 14))
    table = PreviewTable(d.body, [("old", "Now"), ("new", "Will become")], 8, {"old": 330, "new": 330})
    table.pack(fill="both", expand=True, pady=(10, 0))

    def refresh(*_):
        rows = []
        for af in files[:200]:
            for k, v in fvars.items():
                if v.get() and af.get(k):
                    new = tools.change_case(af.get(k), mode.get())
                    if new != af.get(k):
                        rows.append((af.get(k), new))
        table.set_rows(rows[:400])
    mode.trace_add("write", refresh)
    for v in fvars.values():
        v.trace_add("write", refresh)
    refresh()

    def go():
        keys = [k for k, v in fvars.items() if v.get()]
        m = mode.get()
        d.close()
        app.apply(files, lambda af: [af.set(k, tools.change_case(af.get(k), m)) for k in keys], "Change case")
    d.add_button("✔  Apply", "pink", go)
    d.add_button("Cancel", "gray", d.close)
    d.show()


# ===========================================================================
# Fix it all
# ===========================================================================

FIXES = [
    ("clean", "Clean up spaces and _underscores_, fix ALL CAPS / all lowercase", True),
    ("fill_title", "Fill an empty Title from the file name", True),
    ("strip_num", "Remove track numbers stuck on the front of titles (\"03 - Song\")", True),
    ("albumartist", "Fill an empty Album Artist with the Artist", False),
    ("brackets", "Remove (extra stuff) and [extra stuff] from titles", False),
    ("folder_cover", "Add the folder's cover.jpg / folder.jpg to songs with no cover", True),
    ("year", "Make the Year just 4 digits (2019-05-01 → 2019)", True),
]


def fix_it(app, files):
    if not need_files(app, files):
        return
    d = Dialog(app.root, "Fix It All", "🪄", "yellow", 760, 560)
    label(d.body, scope_text(app, files), 10, color=MUTED).pack(anchor="w")
    label(d.body, "Pick what to fix - one click cleans up messy tags:", 11, True).pack(anchor="w", pady=(8, 6))
    vars_ = {}
    for key, text, default in FIXES:
        vars_[key] = tk.BooleanVar(value=default)
        ttk.Checkbutton(d.body, text=text, variable=vars_[key]).pack(anchor="w", pady=2)
    info = label(d.body, "", 11, True, color=COLORS["green"])
    info.pack(anchor="w", pady=(14, 0))

    def plan_for(af):
        ch = {}
        cover = None
        on = {k: v.get() for k, v in vars_.items()}
        for k in FIELD_KEYS:
            v = af.get(k)
            new = v
            if on["clean"] and v:
                new = tools.fix_up(new, k)
            if on["year"] and k == "year" and v:
                new = tools.fix_up(new, "year")
            if k == "title":
                if on["fill_title"] and not new:
                    g = tools.guess_from_filename(af)
                    new = g.get("title", af.stem)
                if on["strip_num"] and new:
                    new = tools.strip_track_prefix(new)
                if on["brackets"] and new:
                    new = tools.remove_brackets(new)
            if k == "albumartist" and on["albumartist"] and not new and af.get("artist"):
                new = tools.fix_up(af.get("artist"), "artist") if on["clean"] else af.get("artist")
            if new != v:
                ch[k] = new
        if on["folder_cover"] and not af.cover_count:
            p = tools.find_folder_cover(af.folder)
            if p:
                cover = p
        return ch, cover

    def refresh(*_):
        n = sum(1 for af in files if any(plan_for(af)))
        info.configure(text=f"✨ {n} song{'s' if n != 1 else ''} will be fixed")
    for v in vars_.values():
        v.trace_add("write", refresh)
    refresh()

    def go():
        plans = {id(af): plan_for(af) for af in files}
        d.close()
        cache = {}

        def work(af):
            ch, cover = plans[id(af)]
            for k, v in ch.items():
                af.set(k, v)
            if cover:
                if cover not in cache:
                    with open(cover, "rb") as fh:
                        cache[cover] = fh.read()
                af.set_covers([Cover(cache[cover])])
        targets = [af for af in files if plans[id(af)][0] or plans[id(af)][1]]
        app.apply(targets, work, "Fix it all")
    d.add_button("🪄  Fix It!", "yellow", go)
    d.add_button("Cancel", "gray", d.close)
    d.show()


# ===========================================================================
# Auto numbering
# ===========================================================================

def number(app, files):
    if not need_files(app, files):
        return
    d = Dialog(app.root, "Auto Number Tracks", "🔢", "pink", 640, 470)
    label(d.body, scope_text(app, files) + " - numbered in the order shown in the list.", 10,
          color=MUTED, wraplength=580, justify="left").pack(anchor="w")
    g = tk.Frame(d.body, bg=PANEL)
    g.pack(fill="x", pady=10)
    start = tk.StringVar(value="1")
    disc = tk.StringVar(value="")
    pad = tk.StringVar(value="No (1, 2, 3)")
    label(g, "Start at:", 11, True).grid(row=0, column=0, sticky="w", pady=4)
    ttk.Spinbox(g, from_=0, to=999, textvariable=start, width=6, font=font(11)).grid(row=0, column=1, sticky="w")
    label(g, "Leading zero:", 11, True).grid(row=1, column=0, sticky="w", pady=4)
    combo(g, ["No (1, 2, 3)", "Yes (01, 02, 03)", "Two zeros (001, 002)"], pad, 22).grid(row=1, column=1, sticky="w")
    label(g, "Disc number (optional):", 11, True).grid(row=2, column=0, sticky="w", pady=4, padx=(0, 12))
    entry(g, disc, 6).grid(row=2, column=1, sticky="w")
    per_folder = tk.BooleanVar(value=True)
    total = tk.BooleanVar(value=True)
    ttk.Checkbutton(d.body, text="Start again at each new folder (each album)", variable=per_folder).pack(anchor="w")
    ttk.Checkbutton(d.body, text="Also fill in Total Tracks", variable=total).pack(anchor="w")

    def go():
        try:
            s = int(start.get())
        except ValueError:
            s = 1
        p = {"No (1, 2, 3)": 0, "Yes (01, 02, 03)": 2, "Two zeros (001, 002)": 3}.get(pad.get(), 0)
        d.close()
        app.apply(files, None, "Auto number",
                  batch=lambda fs: tools.auto_number(fs, s, p, per_folder.get(), total.get(), disc.get().strip()))
    d.add_button("✔  Number Them", "pink", go)
    d.add_button("Cancel", "gray", d.close)
    d.show()


# ===========================================================================
# Online lookup
# ===========================================================================

def find_online(app, files):
    if not need_files(app, files):
        return
    d = Dialog(app.root, "Find Album Info Online", "🌐", "teal", 1000, 800)
    label(d.body, scope_text(app, files) + ". Free databases - no account needed.", 10,
          color=MUTED).pack(anchor="w")
    top = tk.Frame(d.body, bg=PANEL)
    top.pack(fill="x", pady=8)
    src = tk.StringVar(value=app.settings.get("online_source", "MusicBrainz"))
    artists = [af.get("albumartist") or af.get("artist") for af in files]
    albums = [af.get("album") for af in files]
    artist_v = tk.StringVar(value=max(set(artists), key=artists.count) if any(artists) else "")
    album_v = tk.StringVar(value=max(set(albums), key=albums.count) if any(albums) else "")
    label(top, "Search:", 11, True).grid(row=0, column=0, sticky="w")
    ttk.Radiobutton(top, text="MusicBrainz (huge, open)", value="MusicBrainz", variable=src).grid(row=0, column=1, sticky="w")
    ttk.Radiobutton(top, text="iTunes (big clean covers)", value="iTunes", variable=src).grid(row=0, column=2, columnspan=2, sticky="w", padx=12)
    label(top, "Artist:", 11, True).grid(row=1, column=0, sticky="w", pady=4)
    e1 = entry(top, artist_v, 28)
    e1.grid(row=1, column=1, sticky="w", pady=4)
    label(top, "Album:", 11, True).grid(row=1, column=2, sticky="e", padx=(12, 6))
    e2 = entry(top, album_v, 28)
    e2.grid(row=1, column=3, sticky="w")
    status = label(d.body, "Type the artist and album, then click Search.", 10, color=MUTED)
    results = PreviewTable(d.body, [("album", "Album"), ("artist", "Artist"), ("year", "Year"),
                                    ("tracks", "Songs"), ("country", "Country"), ("extra", "Info")], 5,
                           {"album": 280, "artist": 200, "year": 60, "tracks": 60, "country": 70, "extra": 160})
    tracks_tbl = PreviewTable(d.body, [("file", "Your file"), ("num", "#"), ("title", "Title from online"),
                                       ("artist", "Artist")], 6,
                              {"file": 300, "num": 50, "title": 300, "artist": 200})
    opts = tk.Frame(d.body, bg=PANEL)
    write = {}
    for i, (k, t, on) in enumerate((("title", "Title", True), ("artist", "Artist", True),
                                    ("album", "Album", True), ("albumartist", "Album Artist", True),
                                    ("year", "Year", True), ("track", "Track #", True),
                                    ("genre", "Genre", True), ("cover", "Cover Art", True))):
        write[k] = tk.BooleanVar(value=on)
        ttk.Checkbutton(opts, text=t, variable=write[k]).grid(row=0, column=i, sticky="w", padx=(0, 10))
    opts.pack(fill="x", side="bottom")
    label(d.body, "Write these:", 10, True).pack(anchor="w", side="bottom")
    status.pack(anchor="w")
    results.pack(fill="both", expand=True, pady=(4, 6))
    label(d.body, "Songs will be matched like this (by track number, or in list order):", 10, True).pack(anchor="w")
    tracks_tbl.pack(fill="both", expand=True, pady=(4, 6))

    q = queue.Queue()
    found = []
    state = {"album": None, "pairs": []}

    def run_bg(fn, kind):
        def worker():
            try:
                q.put((kind, fn()))
            except Exception as e:  # network problems etc.
                q.put(("error", e))
        threading.Thread(target=worker, daemon=True).start()
        poll()

    def poll():
        try:
            kind, data = q.get_nowait()
        except queue.Empty:
            if d.winfo_exists():
                d.after(120, poll)
            return
        if kind == "error":
            status.configure(text=f"⚠ Could not reach the online database. Check your internet. ({data})",
                             fg=COLORS["red"])
        elif kind == "search":
            found[:] = data
            results.set_rows([(r["title"], r["artist"], r["year"], r["tracks"], r["country"],
                               " ".join(x for x in (r.get("label", ""), r.get("extra", "")) if x))
                              for r in data])
            status.configure(text=f"Found {len(data)} albums. Click the right one." if data
                             else "Nothing found - try fewer words.", fg=MUTED)
            tracks_tbl.set_rows([])
        elif kind == "album":
            album, trs = data
            state["album"] = album
            state["pairs"] = online.match_tracks(files, trs)
            rows = [(af.filename, t["track"], t["title"], t["artist"]) for af, t in state["pairs"]]
            tracks_tbl.set_rows(rows)
            extra = "" if len(trs) == len(files) else \
                f"   (album has {len(trs)} songs, you picked {len(files)})"
            status.configure(text=f"✔ {album.get('title')} - {album.get('artist')} {album.get('year', '')}{extra}",
                             fg=COLORS["green"])

    def do_search(*_):
        app.settings["online_source"] = src.get()
        status.configure(text="🔎 Searching...", fg=MUTED)
        a, b, s = artist_v.get().strip(), album_v.get().strip(), src.get()
        run_bg(lambda: online.search(s, a, b), "search")

    def pick(_e=None):
        sel = results.tree.selection()
        if not sel:
            return
        r = found[int(sel[0])]
        status.configure(text="⏳ Getting the song list...", fg=MUTED)
        run_bg(lambda: online.get_album(r), "album")
    results.tree.bind("<<TreeviewSelect>>", pick)
    e1.bind("<Return>", do_search)
    e2.bind("<Return>", do_search)
    PillButton(top, "🔎  Search", "teal", do_search).grid(row=1, column=4, padx=(12, 0))

    def go():
        album, pairs = state["album"], state["pairs"]
        if not album or not pairs:
            messagebox.showinfo(APP_NAME, "Pick an album from the list first.", parent=d)
            return
        w = {k: v.get() for k, v in write.items()}
        status.configure(text="⏳ Writing tags...", fg=MUTED)
        d.update()
        cover = online.get_cover(album) if w["cover"] else None
        d.close()
        disc_total = album.get("totaldiscs", "")

        def work(af, by_id={id(af): t for af, t in pairs}):
            t = by_id[id(af)]
            if w["title"]:
                af.set("title", t["title"])
            if w["artist"]:
                af.set("artist", t["artist"])
            if w["album"]:
                af.set("album", album.get("title", ""))
            if w["albumartist"]:
                af.set("albumartist", album.get("artist", ""))
            if w["year"] and album.get("year"):
                af.set("year", album["year"])
            if w["track"]:
                af.set("track", t["track"])
                af.set("totaltracks", t.get("totaltracks", ""))
                if disc_total:
                    af.set("disc", t.get("disc", ""))
                    af.set("totaldiscs", disc_total)
            if w["genre"] and (t.get("genre") or album.get("genre")):
                af.set("genre", t.get("genre") or album.get("genre"))
            if t.get("isrc"):
                af.set("isrc", t["isrc"])
            if album.get("label"):
                af.set("publisher", album["label"])
            if cover:
                af.set_covers([Cover(cover)])
        app.apply([af for af, _ in pairs], work, "Online lookup")
        if w["cover"] and not cover:
            messagebox.showinfo(APP_NAME, "Tags saved. No cover picture was found for this album.",
                                parent=app.root)
    d.add_button("✔  Write Tags", "teal", go)
    d.add_button("Cancel", "gray", d.close)
    if artist_v.get() or album_v.get():
        d.after(300, do_search)
    d.show()


# ===========================================================================
# Covers
# ===========================================================================

def covers(app, files):
    if not need_files(app, files):
        return
    d = Dialog(app.root, "Cover Art", "🖼️", "red", 760, 600)
    label(d.body, scope_text(app, files), 10, color=MUTED).pack(anchor="w")
    with_cover = sum(1 for af in files if af.cover_count)
    label(d.body, f"{with_cover} of {len(files)} songs have a cover picture.", 12, True,
          color=COLORS["red"]).pack(anchor="w", pady=(6, 10))
    grid = tk.Frame(d.body, bg=PANEL)
    grid.pack(fill="both", expand=True)

    def add_image():
        p = filedialog.askopenfilename(parent=d, title="Pick a cover picture",
                                       filetypes=[("Pictures", "*.jpg *.jpeg *.png *.gif *.bmp *.webp")])
        if not p:
            return
        with open(p, "rb") as fh:
            data = fh.read()
        d.close()
        app.apply(files, lambda af: af.set_covers([Cover(data)] + [c for c in af.covers if c.ptype != 3]),
                  "Add cover")

    def folder_images():
        cache = {}

        def work(af):
            p = tools.find_folder_cover(af.folder)
            if p:
                if p not in cache:
                    with open(p, "rb") as fh:
                        cache[p] = fh.read()
                af.set_covers([Cover(cache[p])] + [c for c in af.covers if c.ptype != 3])
        d.close()
        targets = [af for af in files if tools.find_folder_cover(af.folder)]
        if not targets:
            messagebox.showinfo(APP_NAME, "No cover.jpg / folder.jpg / front.jpg found next to these songs.",
                                parent=app.root)
            return
        app.apply(targets, work, "Folder cover")

    def copy_first():
        src = next((af for af in files if af.cover_count), None)
        if not src:
            messagebox.showinfo(APP_NAME, "None of these songs has a cover yet.", parent=d)
            return
        cov = list(src.covers)
        d.close()
        app.apply(files, lambda af: af.set_covers(cov), "Copy cover")

    def save_to_folders():
        done = 0
        name = app.settings.get("rename_cover_name", "cover")
        written = set()
        for af in files:
            if not af.cover_count or af.folder in written:
                continue
            c = next((c for c in af.covers if c.ptype == 3), af.covers[0])
            path = os.path.join(af.folder, name + c.ext)
            try:
                with open(path, "wb") as fh:
                    fh.write(c.data)
                written.add(af.folder)
                done += 1
            except OSError as e:
                messagebox.showerror(APP_NAME, f"Could not save {path}\n{e}", parent=d)
                break
        messagebox.showinfo(APP_NAME, f"Saved {done} cover picture{'s' if done != 1 else ''} "
                            f"as {name}.jpg next to the songs.", parent=d)

    def shrink():
        try:
            from PIL import Image
        except ImportError:
            messagebox.showinfo(APP_NAME, "Shrinking needs the picture helper (Pillow), which is missing.",
                                parent=d)
            return
        import io
        d.close()

        def work(af):
            new = []
            changed = False
            for c in af.covers:
                try:
                    im = Image.open(io.BytesIO(c.data))
                    if max(im.size) > 800 or len(c.data) > 400_000:
                        im = im.convert("RGB")
                        im.thumbnail((800, 800))
                        b = io.BytesIO()
                        im.save(b, "JPEG", quality=88)
                        new.append(Cover(b.getvalue(), "image/jpeg", c.ptype, c.desc))
                        changed = True
                        continue
                except Exception:
                    pass
                new.append(c)
            if changed:
                af.set_covers(new)
        app.apply([af for af in files if af.cover_count], work, "Shrink covers")

    def remove_all():
        if not messagebox.askyesno(APP_NAME, f"Remove every cover picture from {len(files)} songs?", parent=d):
            return
        d.close()
        app.apply([af for af in files if af.cover_count], lambda af: af.set_covers([]), "Remove covers")

    actions = [
        ("➕  Add a picture to all of them", "blue", add_image),
        ("📁  Use cover.jpg / folder.jpg from each folder", "teal", folder_images),
        ("📑  Copy the first song's cover to all of them", "purple", copy_first),
        ("🌐  Find covers online", "cyan", lambda: (d.close(), find_online(app, files))),
        ("💾  Save covers as cover.jpg in the song folders", "green", save_to_folders),
        ("🗜️  Shrink giant covers (smaller files, 800 px)", "orange", shrink),
        ("🗑️  Remove all covers", "red", remove_all),
    ]
    for i, (t, c, cmd) in enumerate(actions):
        PillButton(grid, t, c, cmd, padx=16, pady=10, fsize=11).grid(row=i, column=0, sticky="ew", pady=4)
    grid.columnconfigure(0, weight=1)
    d.add_button("Close", "gray", d.close)
    d.show()


# ===========================================================================
# Export
# ===========================================================================

def export(app, files):
    if not need_files(app, files):
        return
    d = Dialog(app.root, "Export a List or Playlist", "📤", "grape", 640, 470)
    label(d.body, scope_text(app, files), 10, color=MUTED).pack(anchor="w")
    kind = tk.StringVar(value="html")
    for v, t in (("html", "🌈  Pretty web page (HTML) - great for printing or sharing"),
                 ("csv", "📊  Spreadsheet (CSV) - opens in Excel"),
                 ("m3u8", "🎶  Playlist (M3U8) - plays in VLC, Winamp, Windows Media Player..."),
                 ("txt", "📝  Plain text list (Artist - Title)")):
        ttk.Radiobutton(d.body, text=t, value=v, variable=kind).pack(anchor="w", pady=4)

    def go():
        k = kind.get()
        types = {"html": ("Web page", "*.html"), "csv": ("CSV", "*.csv"), "m3u8": ("Playlist", "*.m3u8"),
                 "txt": ("Text", "*.txt")}
        base = files[0].get("album") or os.path.basename(files[0].folder) or "My Music"
        p = filedialog.asksaveasfilename(parent=d, defaultextension="." + k, filetypes=[types[k]],
                                         initialdir=files[0].folder, initialfile=tools.safe_part(base) + "." + k)
        if not p:
            return
        try:
            if k == "html":
                tools.export_html(files, p, title=base)
            elif k == "csv":
                tools.export_csv(files, p)
            elif k == "m3u8":
                tools.export_m3u(files, p)
            else:
                tools.export_txt(files, p)
        except OSError as e:
            messagebox.showerror(APP_NAME, str(e), parent=d)
            return
        d.close()
        if messagebox.askyesno(APP_NAME, "Saved! Open it now?", parent=app.root):
            app.open_path(p)
    d.add_button("💾  Save As...", "grape", go)
    d.add_button("Cancel", "gray", d.close)
    d.show()


# ===========================================================================
# Extended tags (every field, plus your own)
# ===========================================================================

def extended(app, files):
    if not need_files(app, files):
        return
    d = Dialog(app.root, "All Tag Fields", "🗂️", "blue", 900, 720)
    label(d.body, scope_text(app, files) + ". Click a field to change it.", 10, color=MUTED).pack(anchor="w")
    tree = ttk.Treeview(d.body, columns=("field", "value"), show="headings", height=14)
    tree.heading("field", text="Field", anchor="w")
    tree.heading("value", text="Value", anchor="w")
    tree.column("field", width=200, stretch=False)
    tree.column("value", width=620)
    tree.pack(fill="both", expand=True, pady=(6, 6))
    tree.tag_configure("keep", foreground=KEEP)
    tree.tag_configure("changed", foreground=COLORS["orange"])

    def common(getter):
        vals = {getter(af) for af in files}
        return vals.pop() if len(vals) == 1 else KEEP_TEXT

    values = {}
    extra_names = sorted({k for af in files for k in af.extras}, key=str.lower)
    for k in FIELD_KEYS:
        values[k] = common(lambda af, k=k: af.get(k))
    for k in extra_names:
        values[k] = common(lambda af, k=k: af.extras.get(k, ""))
    original = dict(values)

    def fill():
        tree.delete(*tree.get_children())
        for k in list(FIELD_KEYS) + [n for n in values if n not in FIELD_LABELS]:
            v = values[k]
            title = FIELD_LABELS.get(k, f"★ {k}")
            shown = v.replace("\n", " ⏎ ")
            tag = "keep" if v == KEEP_TEXT else ("changed" if v != original.get(k) else "")
            tree.insert("", "end", iid=k, values=(title, shown), tags=(tag,) if tag else ())
    fill()

    edit = tk.Frame(d.body, bg=PANEL)
    edit.pack(fill="x")
    cur = tk.StringVar()
    name_lbl = label(edit, "Pick a field above", 11, True)
    name_lbl.pack(anchor="w")
    box = tk.Text(edit, height=4, font=font(11), bg="#f8f9fa", relief="flat", wrap="word",
                  highlightthickness=2, highlightbackground=LINE)
    box.pack(fill="x", pady=4)
    btns = tk.Frame(edit, bg=PANEL)
    btns.pack(fill="x")

    def on_select(_e=None):
        sel = tree.selection()
        if not sel:
            return
        cur.set(sel[0])
        name_lbl.configure(text=FIELD_LABELS.get(sel[0], sel[0]))
        box.delete("1.0", "end")
        v = values[sel[0]]
        if v != KEEP_TEXT:
            box.insert("1.0", v)
        box.focus_set()
    tree.bind("<<TreeviewSelect>>", on_select)

    def set_value(*_):
        k = cur.get()
        if not k:
            return
        values[k] = box.get("1.0", "end-1c")
        fill()
        tree.selection_set(k)

    def clear_value():
        box.delete("1.0", "end")
        set_value()

    def add_custom():
        n = simple_ask(d, "New field", "Name of the new field (for example MOOD, LANGUAGE, RATING):")
        if not n:
            return
        n = n.strip().upper()
        if n.lower() in FIELD_LABELS:
            n = n.lower()
        values.setdefault(n, "")
        original.setdefault(n, "")
        fill()
        tree.selection_set(n)
        tree.see(n)

    PillButton(btns, "✔ Set", "green", set_value, fsize=9).pack(side="left")
    PillButton(btns, "🗑 Clear field", "red", clear_value, fsize=9).pack(side="left", padx=6)
    PillButton(btns, "➕ Add my own field", "blue", add_custom, fsize=9).pack(side="left")

    def go():
        if cur.get() and values.get(cur.get()) != box.get("1.0", "end-1c") and \
                not (values.get(cur.get()) == KEEP_TEXT and box.get("1.0", "end-1c") == ""):
            set_value()
        changes = {k: v for k, v in values.items() if v != original.get(k) and v != KEEP_TEXT}
        d.close()
        if changes:
            app.apply(files, lambda af: [af.set(k, v) for k, v in changes.items()], "Edit fields")
    d.add_button("💾  Save", "green", go)
    d.add_button("Cancel", "gray", d.close)
    d.show()


def simple_ask(parent, title, prompt, initial=""):
    d = Dialog(parent, title, "", "blue", 520, 230)
    label(d.body, prompt, 11, wraplength=470, justify="left").pack(anchor="w")
    v = tk.StringVar(value=initial)
    e = entry(d.body, v, 50)
    e.pack(fill="x", pady=10)

    def ok(*_):
        d.result = v.get()
        d.close()
    e.bind("<Return>", ok)
    d.add_button("OK", "blue", ok)
    d.add_button("Cancel", "gray", d.close)
    d.after(50, e.focus_set)
    return d.show()


# ===========================================================================
# Duplicates
# ===========================================================================

def duplicates(app, files):
    if not need_files(app, files):
        return
    groups = tools.find_duplicates(files)
    if not groups:
        messagebox.showinfo(APP_NAME, "🎉 No duplicate songs found (same artist + title).", parent=app.root)
        return
    d = Dialog(app.root, "Duplicate Songs", "👯", "orange", 960, 600)
    label(d.body, f"{len(groups)} songs appear more than once (same artist and title). "
                  "Click one to find it in the main list.", 10, color=MUTED).pack(anchor="w")
    table = PreviewTable(d.body, [("song", "Song"), ("file", "File"), ("info", "Quality"), ("folder", "Folder")],
                         16, {"song": 250, "file": 240, "info": 150, "folder": 280})
    table.pack(fill="both", expand=True, pady=6)
    rows, refs = [], []
    for g in groups:
        g = sorted(g, key=lambda af: -af.info.get("bitrate", 0))
        for i, af in enumerate(g):
            rows.append((f"{af.get('artist')} - {af.get('title') or af.stem}" if i == 0 else "   ↳ same song",
                         af.filename, f"{af.format} {af.info.get('bitrate', 0) // 1000} kbps "
                                      f"{fmt_length(af.info.get('length', 0))}", af.folder))
            refs.append(af)
    table.set_rows(rows)
    table.tree.bind("<<TreeviewSelect>>", lambda e: app.reveal([refs[int(i)] for i in table.tree.selection()]))

    def select_all_dupes():
        d.close()
        app.reveal(refs)
    d.add_button("Close", "gray", d.close)
    d.add_button("Select them all in the list", "orange", select_all_dupes)
    d.show()


# ===========================================================================
# Settings
# ===========================================================================

def settings(app):
    s = app.settings
    d = Dialog(app.root, "Settings", "⚙️", "gray", 640, 560)
    v_id3 = tk.IntVar(value=s["id3_version"])
    v_v1 = tk.StringVar(value=s["id3v1"])
    v_mtime = tk.BooleanVar(value=s["keep_mtime"])
    v_rec = tk.BooleanVar(value=s["recursive"])
    v_large = tk.BooleanVar(value=s["large_text"])
    v_conf = tk.BooleanVar(value=s["confirm_rename"])
    label(d.body, "MP3 tag version", 11, True).pack(anchor="w")
    ttk.Radiobutton(d.body, text="ID3v2.3  (recommended - works with Windows, cars, phones)", value=3,
                    variable=v_id3).pack(anchor="w")
    ttk.Radiobutton(d.body, text="ID3v2.4  (newest)", value=4, variable=v_id3).pack(anchor="w")
    label(d.body, "Old ID3v1 tags (very old players)", 11, True).pack(anchor="w", pady=(10, 0))
    for v, t in (("keep", "Leave them as they are"), ("write", "Always write them too"),
                 ("remove", "Remove them")):
        ttk.Radiobutton(d.body, text=t, value=v, variable=v_v1).pack(anchor="w")
    label(d.body, "Other", 11, True).pack(anchor="w", pady=(10, 0))
    ttk.Checkbutton(d.body, text="Open folders with all their sub-folders", variable=v_rec).pack(anchor="w")
    ttk.Checkbutton(d.body, text="Keep the file's original date when saving", variable=v_mtime).pack(anchor="w")
    ttk.Checkbutton(d.body, text="Ask before renaming files", variable=v_conf).pack(anchor="w")
    ttk.Checkbutton(d.body, text="Bigger text (takes effect next time EZ Tag starts)",
                    variable=v_large).pack(anchor="w")

    def ok():
        s.update(id3_version=v_id3.get(), id3v1=v_v1.get(), keep_mtime=v_mtime.get(),
                 recursive=v_rec.get(), large_text=v_large.get(), confirm_rename=v_conf.get())
        s.save()
        d.close()
    d.add_button("✔  Save", "green", ok)
    d.add_button("Cancel", "gray", d.close)
    d.show()


# ===========================================================================
# Help / About
# ===========================================================================

HELP_TEXT = [
    ("📂 Open Folder", "Loads every song in a folder (and its sub-folders)."),
    ("✏️ Left panel", "Click songs, type new info, press 💾 Save. Select many songs to change them all at once. "
                     "< keep > means 'leave each song as it is'."),
    ("🖼️ Cover box", "Click Add to put a picture on the selected songs."),
    ("🔤 Tag → Name", "Renames files from their tags, like '01 - Song Title.mp3'."),
    ("📝 Name → Tag", "Reads the file names and fills in Title, Artist, Track... Try 🧠 Smart Guess!"),
    ("🔢 Number", "Numbers the tracks 1, 2, 3 in the order of the list."),
    ("🪄 Fix It All", "One click to clean messy tags: spaces, CAPS, missing titles, folder covers."),
    ("🔁 Replace", "Find and replace words in any field or in file names."),
    ("🌐 Find Online", "Looks up the album on MusicBrainz or iTunes and fills everything in, with the cover."),
    ("📤 Export", "Makes a web page, spreadsheet, text list, or playlist of your songs."),
    ("🧹 Remove Tags", "Deletes all tags from the selected songs."),
    ("↩️ Undo", "Takes back the last change - even renames."),
    ("⌨️ Keys", "Ctrl+O open • Ctrl+S save • Ctrl+Z undo • Ctrl+A select all • Ctrl+F filter • "
               "F5 reload • Delete = remove from list (files are not deleted) • Enter = play"),
]


def about(app):
    d = Dialog(app.root, f"How to Use {APP_NAME}", "❓", "lime", 780, 720)
    label(d.body, f"{APP_NAME} {VERSION} - the easy music tag editor. Free, by Dr. Szaba.", 11, True).pack(anchor="w")
    label(d.body, "Works with MP3, FLAC, M4A/AAC/ALAC, OGG, Opus, WMA, WAV, AIFF, APE, WavPack, "
                  "Musepack, TTA, TAK, DSF, Speex, AC3 and more.", 10, color=MUTED,
          wraplength=720, justify="left").pack(anchor="w", pady=(2, 10))
    box = tk.Frame(d.body, bg=PANEL)
    box.pack(fill="both", expand=True)
    for i, (a, b) in enumerate(HELP_TEXT):
        label(box, a, 10, True).grid(row=i, column=0, sticky="nw", pady=3, padx=(0, 12))
        label(box, b, 10, wraplength=560, justify="left").grid(row=i, column=1, sticky="w", pady=3)
    d.add_button("💚  Donate ($Szaba)", "green", lambda: webbrowser.open(DONATE_URL), side="left")
    d.add_button("🌐  Website", "blue", lambda: webbrowser.open(SITE_URL), side="left")
    d.add_button("Close", "gray", d.close)
    d.show()
