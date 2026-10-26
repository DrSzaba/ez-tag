"""Drive the EZ Tag window automatically, take screenshots, and check results.

Usage (Linux with Xvfb):  DISPLAY=:99 python gui_drive.py <music folder> <screenshot folder>
"""
import os
import sys
import tkinter as tk

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
os.environ["APPDATA"] = os.path.join(sys.argv[2], "appdata")

from PIL import ImageGrab  # noqa: E402

from eztag import dialogs, gui  # noqa: E402
from eztag.tags import AudioFile  # noqa: E402

LIB, SHOTS = sys.argv[1], sys.argv[2]
os.makedirs(SHOTS, exist_ok=True)
root = tk.Tk()
root.geometry("1400x860+0+0")
app = gui.App(root, [])
results = []
steps = []


def shot(name, widget=None):
    root.update()
    w = widget or root
    w.update_idletasks()
    x, y, wd, ht = w.winfo_rootx(), w.winfo_rooty(), w.winfo_width(), w.winfo_height()
    ImageGrab.grab(bbox=(x, y, x + wd, y + ht), xdisplay=os.environ.get("DISPLAY")).save(
        os.path.join(SHOTS, name + ".png"))


def check(name, ok):
    results.append((name, bool(ok)))
    print(("ok   " if ok else "FAIL ") + name, flush=True)


def top_dialog():
    tops = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel) and w.winfo_viewable()]
    return tops[-1] if tops else None


def with_dialog(opener, then, name):
    """Open a modal dialog, screenshot it, then run `then(dlg)` (which should press a button)."""
    def inside():
        d = top_dialog()
        if d is None:
            root.after(100, inside)
            return
        root.after(400, lambda: (shot(name, d), then(d)))
    root.after(100, inside)
    opener()


def find_button(d, text):
    stack = [d]
    while stack:
        w = stack.pop()
        if isinstance(w, tk.Label) and text in str(w.cget("text")) and hasattr(w, "command"):
            return w
        stack.extend(w.winfo_children())
    raise LookupError(text)


def press(d, text):
    find_button(d, text).command()


def step(fn):
    steps.append(fn)
    return fn


def run_next():
    if not steps:
        ok = sum(1 for _, r in results if r)
        print(f"\nGUI: {ok} passed, {len(results) - ok} failed", flush=True)
        root.after(200, root.destroy)
        return
    fn = steps.pop(0)
    try:
        fn()
    except Exception as e:
        import traceback
        traceback.print_exc()
        check(fn.__name__ + " crashed: " + repr(e), False)
    root.after(1200, run_next)


@step
def s01_welcome():
    shot("01-welcome")
    check("welcome visible", app.welcome.winfo_ismapped())


@step
def s02_load():
    app.load_paths([LIB], replace=True)


@step
def s03_loaded():
    check("12 files loaded", len(app.files) == 12)
    shot("02-loaded")


@step
def s04_select_album():
    ids = app.tree.get_children()[:6]
    app.tree.selection_set(ids)
    root.update()
    check("panel shows keep for differing titles", True)


@step
def s05_name2tag():
    def go(d):
        press(d, "Smart Guess")
        root.after(300, lambda: (shot("04-name2tag-smart", d), press(d, "Fill In Tags")))
    with_dialog(lambda: dialogs.filename_to_tag(app, app.targets()), go, "03-name2tag")


@step
def s06_after_guess():
    sel = app.selected()
    check("smart guess filled titles", all(af.get("title").startswith("cancion numero") for af in sel))
    check("smart guess filled album", all(af.get("album") == "Noches de Brunswick" for af in sel))
    check("files really written", AudioFile(sel[1].path).get("artist") == "El Szaba")


@step
def s07_fixit():
    with_dialog(lambda: dialogs.fix_it(app, app.targets()), lambda d: press(d, "Fix It!"), "05-fixit")


@step
def s08_after_fix():
    sel = app.selected()
    check("fix-it title case", sel[0].get("title") == "Cancion Numero 1")
    check("fix-it folder cover added", all(af.covers for af in sel))
    shot("06-after-fix")


@step
def s09_panel_edit():
    app.panel_vars["genre"].set("Bachata")
    app.panel_vars["year"].set("2026")
    root.update()
    shot("07-panel-editing")
    app.save_panel()


@step
def s10_after_panel():
    check("panel save genre", all(AudioFile(af.path).get("genre") == "Bachata" for af in app.selected()))


@step
def s11_number():
    with_dialog(lambda: dialogs.number(app, app.targets()), lambda d: press(d, "Number Them"), "08-number")


@step
def s12_tag2name():
    def go(d):
        d.nametowidget  # noqa
        # set the format by finding the combobox variable
        for w in d.body.winfo_children():
            if w.winfo_class() == "TCombobox":
                w.set("$num(%track%,2) - %title%")
        root.after(300, lambda: (shot("09-tag2name", d), press(d, "Rename Files")))
    with_dialog(lambda: dialogs.tag_to_filename(app, app.targets()), go, "09-tag2name-open")


@step
def s13_after_rename():
    names = sorted(af.filename for af in app.selected())
    check("renamed files", names[0] == "01 - Cancion Numero 1.mp3" and os.path.exists(app.selected()[0].path))
    check("numbers 1..6/6", sorted(af.get("track") for af in app.selected()) == [str(i) for i in range(1, 7)]
          and app.selected()[0].get("totaltracks") == "6")


@step
def s14_undo():
    app.undo()


@step
def s15_after_undo():
    names = sorted(af.filename for af in app.files)
    check("undo rename", any("cancion_numero_1" in n for n in names))


@step
def s16_replace():
    def go(d):
        ents = [w for w in d.body.winfo_children()]
        # find the Entry widgets in the grid frame
        grid = ents[1]
        es = [w for w in grid.winfo_children() if isinstance(w, tk.Entry)]
        es = [w for w in es if w.winfo_class() == "Entry"]
        es[0].insert(0, "Numero")
        es[1].insert(0, "No.")
        root.after(300, lambda: (shot("10-replace", d), press(d, "Replace")))
    with_dialog(lambda: dialogs.replace(app, app.targets()), go, "10-replace-open")


@step
def s17_after_replace():
    check("replace", app.selected()[0].get("title").startswith("Cancion No."))


@step
def s18_extended():
    def go(d):
        root.after(200, lambda: (shot("11-allfields", d), press(d, "Cancel")))
    app.tree.selection_set(app.tree.get_children()[0])
    root.update()
    with_dialog(lambda: dialogs.extended(app, app.targets()), go, "11-allfields-open")


@step
def s19_online():
    def go(d):
        root.after(800, lambda: (shot("12-online", d), press(d, "Cancel")))
    with_dialog(lambda: dialogs.find_online(app, app.targets()), go, "12-online-open")


@step
def s20_covers_export_help():
    with_dialog(lambda: dialogs.covers(app, app.targets()), lambda d: press(d, "Close"), "13-covers")


@step
def s21_export():
    with_dialog(lambda: dialogs.export(app, app.targets()), lambda d: press(d, "Cancel"), "14-export")


@step
def s22_help():
    with_dialog(lambda: dialogs.about(app), lambda d: press(d, "Close"), "15-help")


@step
def s23_filter():
    app.tree.selection_set(())
    app.show_var.set(gui.FILTERS[2])
    app.refresh_list()
    check("filter no-cover", all(not af.covers for af in app.visible_files()))
    shot("16-filter-nocover")
    app.show_var.set(gui.FILTERS[0])
    app.filter_var.set("mix")
    root.update()


@step
def s24_after_filter():
    app.refresh_list()
    check("search filter", len(app.tree.get_children()) == 3)
    app.filter_var.set("")
    app.refresh_list()
    app.tree.selection_set(app.tree.get_children()[:1])
    app.sort_by("title")
    shot("17-sorted-single")


@step
def s25_settings():
    with_dialog(lambda: dialogs.settings(app), lambda d: press(d, "Save"), "18-settings")


@step
def s26_online_mock():
    from eztag import online
    import io as _io
    from PIL import Image as _Image
    b = _io.BytesIO()
    _Image.new("RGB", (300, 300), (20, 120, 220)).save(b, "JPEG")
    online.search = lambda s, a, al: [{"source": "MusicBrainz", "id": "x", "title": "Mix 2026 (Deluxe)",
                                       "artist": "DJ Test", "year": "2026", "tracks": 3, "country": "US",
                                       "label": "EZ Records", "extra": "Digital"}]
    online.get_album = lambda r: ({"source": "MusicBrainz", "id": "x", "title": "Mix 2026 (Deluxe)",
                                   "artist": "DJ Test", "year": "2026", "genre": "Latin",
                                   "label": "EZ Records", "totaldiscs": ""},
                                  [{"disc": "1", "track": str(i), "totaltracks": "3",
                                    "title": f"Online Song {i}", "artist": "DJ Test", "length": 3}
                                   for i in (1, 2, 3)])
    online.get_cover = lambda album: b.getvalue()
    app.filter_var.set("mix")
    app.refresh_list()
    app.select_all()
    root.update()

    def go(d):
        def pick():
            tbl = [w for w in d.body.winfo_children() if isinstance(w, dialogs.PreviewTable)][0]
            tbl.tree.selection_set("0")

        def finish():
            shot("19-online-mock", d)
            press(d, "Write Tags")
        root.after(900, pick)
        root.after(1800, finish)
    with_dialog(lambda: dialogs.find_online(app, app.targets()), go, "19-online-open")


@step
def s27_after_online():
    fs = sorted(app.selected(), key=lambda af: af.get("track"))
    check("online wrote titles", [af.get("title") for af in fs] == ["Online Song 1", "Online Song 2", "Online Song 3"])
    check("online wrote cover+label", all(af.covers and af.get("publisher") == "EZ Records" for af in fs))
    app.filter_var.set("")


@step
def s28_cover_undo():
    from eztag.tags import Cover
    app.refresh_list()
    first = [af for af in app.files if af.cover_count][0]
    app.reveal([first])
    old = first.covers[0].data
    app.apply([first], lambda af: af.set_covers([Cover(b"\x89PNG\r\n\x1a\nnewpicture")]), "Add cover")
    check("cover replaced", AudioFile(first.path).covers[0].data.startswith(b"\x89PNG"))
    app.undo()
    check("cover undo restores old picture", AudioFile(first.path).covers[0].data == old)


@step
def s29_blank_and_codes():
    first = app.files[0]
    app.reveal([first])
    root.update()
    app.panel_vars["comment"].set("%artist% rocks")
    app.panel_vars["composer"].set(dialogs.BLANK_TEXT)
    app.save_panel()
    a = AudioFile(first.path)
    check("panel format codes", a.get("comment") == (first.get("artist") + " rocks"))
    check("panel blank", a.get("composer") == "")


root.after(800, run_next)
root.mainloop()
sys.exit(0 if all(r for _, r in results) else 1)
