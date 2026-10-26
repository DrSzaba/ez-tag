"""Converters, actions, numbering, export - everything that changes many files at once."""
from __future__ import annotations

import csv
import html
import io
import os
import re
import unicodedata

from .tags import AudioFile, FIELD_KEYS, FIELD_LABELS, fmt_length

ILLEGAL = '<>:"/\\|?*'

# ===========================================================================
# Format strings:  %artist% - %title%,  $num(%track%,2),  [ (%year%)]
# ===========================================================================


def _title_case(s: str) -> str:
    small = {"a", "an", "the", "and", "but", "or", "nor", "for", "of", "at", "by",
             "to", "in", "on", "de", "la", "el", "y", "del", "vs", "vs."}
    words = re.split(r"(\s+)", s.lower())
    out = []
    idx = 0
    real = [w for w in words if w.strip()]
    for w in words:
        if not w.strip():
            out.append(w)
            continue
        first, last = idx == 0, idx == len(real) - 1
        idx += 1
        if w in small and not first and not last:
            out.append(w)
            continue
        out.append(_cap_word(w))
    return "".join(out)


def _cap_word(w: str) -> str:
    # capitalise after hyphens/brackets/quotes too: "rock-n-roll" -> "Rock-N-Roll"
    return re.sub(r"(^|[-(\[\"'/.])(\w)", lambda m: m.group(1) + m.group(2).upper(), w)


def _caps_all(s: str) -> str:
    return " ".join(_cap_word(w) for w in s.lower().split(" "))


def _sentence(s: str) -> str:
    s = s.lower()
    return re.sub(r"(^\s*|[.!?]\s+)(\w)", lambda m: m.group(1) + m.group(2).upper(), s)


def _num(v, n):
    digits = re.match(r"\s*(\d+)", v or "")
    if not digits:
        return v
    return digits.group(1).zfill(int(n or 0))


def _int(v, default=0):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return default


FUNCTIONS = {
    "upper": lambda a: a[0].upper(),
    "lower": lambda a: a[0].lower(),
    "caps": lambda a: _title_case(a[0]),
    "capsall": lambda a: _caps_all(a[0]),
    "sentence": lambda a: _sentence(a[0]),
    "num": lambda a: _num(a[0], _int(a[1] if len(a) > 1 else 2)),
    "left": lambda a: a[0][:_int(a[1])],
    "right": lambda a: a[0][-_int(a[1]):] if _int(a[1]) else "",
    "mid": lambda a: a[0][_int(a[1]):_int(a[1]) + _int(a[2])] if len(a) > 2 else a[0][_int(a[1]):],
    "trim": lambda a: " ".join(a[0].split()),
    "replace": lambda a: a[0].replace(a[1], a[2] if len(a) > 2 else "") if len(a) > 1 and a[1] else a[0],
    "regexp": lambda a: _safe_re(a[0], a[1], a[2] if len(a) > 2 else ""),
    "if": lambda a: (a[1] if a[0] else (a[2] if len(a) > 2 else "")),
    "if2": lambda a: next((x for x in a if x), ""),
    "len": lambda a: str(len(a[0])),
    "firstword": lambda a: (a[0].split() or [""])[0],
    "noaccents": lambda a: "".join(c for c in unicodedata.normalize("NFKD", a[0])
                                   if not unicodedata.combining(c)),
    "validate": lambda a: "".join(("_" if len(a) < 2 else a[1]) if c in ILLEGAL else c for c in a[0]),
    "year": lambda a: (re.search(r"\d{4}", a[0]).group(0) if re.search(r"\d{4}", a[0]) else ""),
}

FUNCTION_HELP = [
    ("%artist%", "the value of a field"),
    ("$num(%track%,2)", "track as 01, 02..."),
    ("$upper(x)  $lower(x)", "UPPER / lower case"),
    ("$caps(x)", "Title Case (smart)"),
    ("$left(x,n)  $right(x,n)", "first / last n letters"),
    ("$replace(x,old,new)", "replace text"),
    ("$if2(%albumartist%,%artist%)", "first value that is filled"),
    ("$year(%year%)", "just the 4-digit year"),
    ("[ (%year%)]", "only shown when the fields inside are filled"),
    ("%_filename%  %_folder%  %_ext%", "file name, folder name, extension"),
    ("%_length%  %_bitrate%  %_format%", "audio length, kbps, format"),
]


def _safe_re(text, pattern, repl):
    try:
        return re.sub(pattern, repl, text)
    except re.error:
        return text


class _Parser:
    def __init__(self, template: str, lookup):
        self.s = template
        self.lookup = lookup

    def render(self) -> str:
        text, _, _ = self._seq(0, "")
        return text

    def _seq(self, i, stops):
        """Parse until a stop char. Returns (text, index, any_field_empty)."""
        out = []
        empty = False
        s = self.s
        while i < len(s):
            ch = s[i]
            if ch in stops:
                break
            if ch == "%":
                j = s.find("%", i + 1)
                if j == -1:
                    out.append(s[i:])
                    i = len(s)
                    break
                name = s[i + 1:j]
                if name == "":
                    out.append("%")
                else:
                    v = self.lookup(name)
                    if not v:
                        empty = True
                    out.append(v)
                i = j + 1
            elif ch == "$":
                m = re.match(r"\$([a-zA-Z0-9_]+)\(", s[i:])
                if not m:
                    out.append(ch)
                    i += 1
                    continue
                name = m.group(1).lower()
                i += m.end()
                args = []
                while True:
                    arg, i, e = self._seq(i, ",)")
                    args.append(arg)
                    if i >= len(s) or s[i] == ")":
                        i += 1
                        break
                    i += 1  # comma
                fn = FUNCTIONS.get(name)
                if fn is None:
                    out.append(f"${name}(" + ",".join(args) + ")")
                else:
                    try:
                        val = fn(args + ["", "", ""])
                    except Exception:
                        val = args[0] if args else ""
                    out.append(val)
            elif ch == "[":
                inner, i, e = self._seq(i + 1, "]")
                i += 1
                if not e:
                    out.append(inner)
            elif ch == "\\" and i + 1 < len(s) and s[i + 1] in "%$[],()'":
                out.append(s[i + 1])
                i += 2
            else:
                out.append(ch)
                i += 1
        return "".join(out), i, empty


def render(template: str, af: AudioFile, extra: dict | None = None) -> str:
    extra = {k.lower(): v for k, v in (extra or {}).items()}

    def lookup(name):
        n = name.lower()
        if n in extra:
            return extra[n]
        return af.value_for(n)
    return _Parser(template, lookup).render()


# ===========================================================================
# Tag -> Filename
# ===========================================================================

def safe_part(name: str, replacement: str = "_") -> str:
    name = "".join(replacement if (c in ILLEGAL or ord(c) < 32) else c for c in name)
    name = name.strip().rstrip(".")
    reserved = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}
    if name.upper() in reserved:
        name = "_" + name
    return name[:200]


def filename_from_tags(af: AudioFile, template: str) -> str | None:
    """Return the new full path for a file (keeps its extension)."""
    text = render(template, af)
    text = text.replace("/", "\\")
    absolute = bool(re.match(r"^[a-zA-Z]:\\", text)) or text.startswith("\\\\")
    drive = ""
    if absolute and text[1] == ":":
        drive, text = text[:2], text[3:]
    parts = [safe_part(p) for p in text.split("\\")]
    parts = [p for p in parts if p]
    if not parts:
        return None
    if absolute:
        base = drive + os.sep if drive else os.sep
    else:
        base = af.folder
    return os.path.join(base, *parts) + af.ext


def unique_path(path: str, taken: set) -> str:
    root, ext = os.path.splitext(path)
    n = 2
    candidate = path
    while candidate.lower() in taken or (os.path.exists(candidate)):
        candidate = f"{root} ({n}){ext}"
        n += 1
    return candidate


def rename_file(af: AudioFile, new_path: str) -> str:
    """Rename/move a file, creating folders. Returns the final path."""
    if os.path.normcase(os.path.abspath(new_path)) == os.path.normcase(af.path):
        return af.path
    os.makedirs(os.path.dirname(new_path), exist_ok=True)
    if os.path.exists(new_path) and os.path.normcase(new_path) != os.path.normcase(af.path):
        new_path = unique_path(new_path, set())
    if os.path.normcase(new_path) == os.path.normcase(af.path):
        # only case differs (Windows) -> go through a temp name
        tmp = af.path + ".eztag-tmp"
        os.rename(af.path, tmp)
        os.rename(tmp, new_path)
    else:
        os.rename(af.path, new_path)
    af.path = os.path.abspath(new_path)
    return af.path


# ===========================================================================
# Filename -> Tag
# ===========================================================================

def pattern_to_regex(pattern: str):
    pattern = pattern.replace("/", "\\")
    tokens = re.split(r"(%[^%]+%)", pattern)
    fields = []
    rx = ""
    placeholders = [t for t in tokens if t.startswith("%") and t.endswith("%") and len(t) > 2]
    seen = 0
    for t in tokens:
        if t.startswith("%") and t.endswith("%") and len(t) > 2:
            seen += 1
            name = t[1:-1].lower()
            last = seen == len(placeholders)
            body = "[^\\\\]+" if last else "[^\\\\]+?"
            if name in ("dummy", "_", "skip") or name in [f for f, _ in fields]:
                rx += f"(?:{body})"
            else:
                gname = f"g{len(fields)}"
                fields.append((name, gname))
                rx += f"(?P<{gname}>{body})"
        else:
            rx += re.escape(t)
    return re.compile(r"(?:^|\\)" + rx + r"$", re.IGNORECASE), fields


def tags_from_filename(af: AudioFile, pattern: str) -> dict | None:
    rx, fields = pattern_to_regex(pattern)
    target = os.path.splitext(af.path)[0].replace("/", "\\")
    m = rx.search(target)
    if not m:
        return None
    out = {}
    for name, g in fields:
        val = m.group(g).strip()
        if name in ("track", "disc"):
            n = re.match(r"(\d+)", val)
            val = str(int(n.group(1))) if n else val
        out[name] = val
    return out


GUESS_PATTERNS = [
    "%track% - %artist% - %title%",
    "%track%. %artist% - %title%",
    "%artist% - %album% - %track% - %title%",
    "%track% %artist% - %title%",
    "%artist% - %track% - %title%",
    "%track% - %title%",
    "%track%. %title%",
    "%track%_%title%",
    "%track% %title%",
    "%artist% - %title%",
    "%artist%-%title%",
    "%title%",
]


def guess_from_filename(af: AudioFile) -> dict:
    """Smart guess: try common naming patterns, best match wins."""
    stem = af.stem.replace("_", " ").strip()
    stem = re.sub(r"\s+", " ", stem)
    folder = os.path.basename(af.folder)

    class Fake:
        path = os.path.join(af.folder, stem + af.ext)
    for p in GUESS_PATTERNS:
        if "%track%" in p and not re.match(r"^\d{1,3}\b", stem):
            if not ("%artist% - %track%" in p and re.search(r" - \d{1,3} - ", stem)):
                continue
        res = tags_from_filename(Fake, p)  # type: ignore[arg-type]
        if res and all(res.values()):
            if "track" in res and not res["track"].isdigit():
                continue
            # folder "Artist - Album" -> album info
            fm = re.match(r"^(.+?) - (.+)$", folder)
            if fm and "album" not in res:
                res.setdefault("album", re.sub(r"^\(?\d{4}\)?\s*-?\s*", "", fm.group(2)).strip())
                res.setdefault("albumartist", fm.group(1).strip())
            return res
    return {"title": stem}


# ===========================================================================
# Text file -> Tag
# ===========================================================================

def tags_from_lines(lines: list[str], pattern: str) -> list[dict]:
    rx, fields = pattern_to_regex(pattern)
    out = []
    for line in lines:
        line = line.rstrip("\r\n")
        m = re.compile(rx.pattern.replace(r"(?:^|\\)", "^", 1), re.IGNORECASE).search(line)
        if not m:
            out.append({})
            continue
        out.append({name: m.group(g).strip() for name, g in fields})
    return out


# ===========================================================================
# Actions
# ===========================================================================

CASE_MODES = [
    ("Title Case (smart)", "caps"),
    ("Every Word Capitalized", "capsall"),
    ("UPPER CASE", "upper"),
    ("lower case", "lower"),
    ("Sentence case", "sentence"),
]


def change_case(value: str, mode: str) -> str:
    return {"caps": _title_case, "capsall": _caps_all, "upper": str.upper,
            "lower": str.lower, "sentence": _sentence}.get(mode, lambda x: x)(value)


def replace_text(value: str, find: str, repl: str, match_case=False, whole_word=False,
                 regex=False) -> str:
    if not find:
        return value
    flags = 0 if match_case else re.IGNORECASE
    if regex:
        pat = find
    else:
        pat = re.escape(find)
        if whole_word:
            pat = r"\b" + pat + r"\b"
        repl = repl.replace("\\", "\\\\")
    try:
        return re.sub(pat, repl, value, flags=flags)
    except re.error:
        return value


def clean_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace(" ", " ")).strip()


def fix_up(value: str, key: str) -> str:
    """The 'Fix It All' cleanup for one value."""
    if key in ("lyrics", "comment"):
        return value.strip()
    v = value.replace("_", " ") if key in ("title", "artist", "album", "albumartist") else value
    v = clean_spaces(v)
    if key in ("title", "artist", "album", "albumartist", "genre", "composer") and v:
        letters = [c for c in v if c.isalpha()]
        if letters and (all(c.isupper() for c in letters) or all(c.islower() for c in letters)):
            v = _title_case(v)
    if key in ("track", "disc", "totaltracks", "totaldiscs"):
        m = re.match(r"0*(\d+)", v)
        v = m.group(1) if m else v
    if key == "year":
        m = re.search(r"\d{4}", v)
        v = m.group(0) if m else v
    return v


def strip_track_prefix(title: str) -> str:
    return re.sub(r"^\s*\d{1,3}\s*[-._)\]]?\s+", "", title)


def remove_brackets(value: str) -> str:
    return clean_spaces(re.sub(r"\s*[\(\[\{][^\)\]\}]*[\)\]\}]", "", value))


# ===========================================================================
# Auto numbering
# ===========================================================================

def auto_number(files: list[AudioFile], start=1, pad=0, per_folder=True,
                set_total=True, disc=""):
    groups: dict[str, list[AudioFile]] = {}
    for af in files:
        groups.setdefault(af.folder if per_folder else "", []).append(af)
    for group in groups.values():
        total = len(group)
        for i, af in enumerate(group):
            af.set("track", str(start + i).zfill(pad) if pad else str(start + i))
            if set_total:
                af.set("totaltracks", str(total + start - 1))
            if disc:
                af.set("disc", disc)


# ===========================================================================
# Duplicates
# ===========================================================================

def _norm(s: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFKD", s.lower()) if not unicodedata.combining(c))
    s = re.sub(r"\(.*?\)|\[.*?\]", "", s)
    return re.sub(r"[^a-z0-9]+", "", s)


def find_duplicates(files: list[AudioFile]) -> list[list[AudioFile]]:
    groups: dict[str, list[AudioFile]] = {}
    for af in files:
        title = af.get("title") or af.stem
        key = _norm(af.get("artist")) + "|" + _norm(title)
        if key.strip("|"):
            groups.setdefault(key, []).append(af)
    return [g for g in groups.values() if len(g) > 1]


# ===========================================================================
# Export
# ===========================================================================

EXPORT_COLUMNS = ["_filename", "title", "artist", "album", "albumartist", "track", "year",
                  "genre", "_length", "_bitrate", "_format", "_path"]
COLUMN_TITLES = dict(FIELD_LABELS, _filename="File", _length="Length", _bitrate="kbps",
                     _format="Format", _path="Path", _folder="Folder", _size="Size")


def export_csv(files, path, columns=EXPORT_COLUMNS):
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow([COLUMN_TITLES.get(c, c) for c in columns])
        for af in files:
            w.writerow([af.value_for(c) for c in columns])


def export_txt(files, path, template="%artist% - %title%"):
    with open(path, "w", encoding="utf-8") as fh:
        for af in files:
            fh.write(render(template, af) + "\n")


def export_html(files, path, title="My Music", columns=EXPORT_COLUMNS[:-1]):
    total = sum(af.info.get("length", 0) for af in files)
    rows = "\n".join(
        "<tr>" + "".join(f"<td>{html.escape(af.value_for(c))}</td>" for c in columns) + "</tr>"
        for af in files)
    head = "".join(f"<th>{html.escape(COLUMN_TITLES.get(c, c))}</th>" for c in columns)
    doc = f"""<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>body{{font-family:Segoe UI,Arial,sans-serif;background:#fff8ef;color:#222;margin:24px}}
h1{{color:#e8590c}}table{{border-collapse:collapse;width:100%;background:#fff}}
th{{background:#6741d9;color:#fff;text-align:left;padding:8px}}td{{padding:6px 8px;border-bottom:1px solid #eee}}
tr:nth-child(even) td{{background:#f3f0ff}}</style></head><body>
<h1>{html.escape(title)}</h1><p>{len(files)} songs &middot; total time {fmt_length(total)} &middot; made with EZ Tag</p>
<table><tr>{head}</tr>
{rows}
</table></body></html>"""
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(doc)


def export_m3u(files, path, relative=True):
    base = os.path.dirname(os.path.abspath(path))
    lines = ["#EXTM3U"]
    for af in files:
        secs = int(af.info.get("length", 0))
        name = " - ".join(x for x in (af.get("artist"), af.get("title")) if x) or af.stem
        lines.append(f"#EXTINF:{secs},{name}")
        p = af.path
        if relative:
            try:
                p = os.path.relpath(af.path, base)
            except ValueError:  # different drive
                p = af.path
        lines.append(p)
    with open(path, "w", encoding="utf-8-sig" if path.lower().endswith(".m3u8") else "utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


# ===========================================================================
# Folder covers
# ===========================================================================

COVER_NAMES = ["cover", "folder", "front", "album", "albumart", "albumartsmall"]


def find_folder_cover(folder: str) -> str | None:
    try:
        names = os.listdir(folder)
    except OSError:
        return None
    images = [n for n in names if os.path.splitext(n)[1].lower() in (".jpg", ".jpeg", ".png")]
    for want in COVER_NAMES:
        for n in images:
            if os.path.splitext(n)[0].lower() == want:
                return os.path.join(folder, n)
    return os.path.join(folder, images[0]) if len(images) == 1 else None


def scan_folder(folder: str, recursive=True):
    from .tags import is_audio
    out = []
    if recursive:
        for root, dirs, files in os.walk(folder):
            dirs.sort(key=str.lower)
            for f in sorted(files, key=str.lower):
                if is_audio(f):
                    out.append(os.path.join(root, f))
    else:
        for f in sorted(os.listdir(folder), key=str.lower):
            p = os.path.join(folder, f)
            if os.path.isfile(p) and is_audio(p):
                out.append(p)
    return out
