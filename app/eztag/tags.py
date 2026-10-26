"""Tag engine: one simple interface over every audio format mutagen can tag.

Every file becomes an AudioFile with plain text fields such as "title",
"artist", "track".  Only fields that were changed are written back, so tags
EZ Tag does not know about are always left untouched.
"""
from __future__ import annotations

import base64
import os
import struct
from collections import OrderedDict
from dataclasses import dataclass, field

import mutagen
from mutagen.apev2 import APEv2, APEv2File, APENoHeaderError, APEValue, BINARY
from mutagen.asf import ASF, ASFByteArrayAttribute
from mutagen.flac import FLAC, Picture
from mutagen.id3 import ID3, ID3FileType, Frames, COMM, USLT, TXXX, APIC, TCMP, ID3NoHeaderError
from mutagen.mp4 import MP4, MP4Cover, MP4FreeForm

# --------------------------------------------------------------------------
# Field catalogue
# --------------------------------------------------------------------------
FIELDS = [
    ("title", "Title"),
    ("artist", "Artist"),
    ("album", "Album"),
    ("albumartist", "Album Artist"),
    ("year", "Year"),
    ("track", "Track"),
    ("totaltracks", "Total Tracks"),
    ("disc", "Disc"),
    ("totaldiscs", "Total Discs"),
    ("genre", "Genre"),
    ("comment", "Comment"),
    ("composer", "Composer"),
    ("lyricist", "Lyricist"),
    ("conductor", "Conductor"),
    ("bpm", "BPM"),
    ("key", "Musical Key"),
    ("mood", "Mood"),
    ("grouping", "Grouping"),
    ("subtitle", "Subtitle"),
    ("publisher", "Publisher / Label"),
    ("copyright", "Copyright"),
    ("encodedby", "Encoded By"),
    ("isrc", "ISRC"),
    ("compilation", "Compilation"),
    ("sorttitle", "Sort Title"),
    ("sortartist", "Sort Artist"),
    ("sortalbum", "Sort Album"),
    ("sortalbumartist", "Sort Album Artist"),
    ("lyrics", "Lyrics"),
]
FIELD_KEYS = [k for k, _ in FIELDS]
FIELD_LABELS = dict(FIELDS)

AUDIO_EXTENSIONS = {
    ".mp3", ".mp2", ".flac", ".ogg", ".oga", ".opus", ".spx", ".m4a", ".m4b",
    ".m4p", ".m4r", ".mp4", ".aac", ".alac", ".wma", ".asf", ".wav", ".aif",
    ".aiff", ".aifc", ".ape", ".wv", ".mpc", ".mp+", ".mpp", ".tta", ".ofr",
    ".ofs", ".tak", ".dsf", ".dff", ".ac3",
}

PICTURE_TYPES = {
    0: "Other", 1: "File icon", 2: "Other file icon", 3: "Front cover",
    4: "Back cover", 5: "Leaflet page", 6: "Media (CD)", 7: "Lead artist",
    8: "Artist", 9: "Conductor", 10: "Band", 11: "Composer", 12: "Lyricist",
    13: "Recording location", 14: "During recording", 15: "During performance",
    16: "Video capture", 17: "Bright fish", 18: "Illustration",
    19: "Band logo", 20: "Publisher logo",
}


def is_audio(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in AUDIO_EXTENSIONS


def guess_mime(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"GIF8":
        return "image/gif"
    if data[:2] == b"BM":
        return "image/bmp"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


@dataclass
class Cover:
    data: bytes
    mime: str = ""
    ptype: int = 3
    desc: str = ""

    def __post_init__(self):
        if not self.mime:
            self.mime = guess_mime(self.data)

    @property
    def ext(self) -> str:
        return {"image/png": ".png", "image/gif": ".gif", "image/bmp": ".bmp",
                "image/webp": ".webp"}.get(self.mime, ".jpg")


def _split_num(value: str):
    """'3/12' -> ('3', '12'); '3' -> ('3', '')"""
    value = (value or "").strip()
    if "/" in value:
        a, b = value.split("/", 1)
        return a.strip(), b.strip()
    return value, ""


def _join(values) -> str:
    out = []
    for v in values:
        if isinstance(v, bytes):
            try:
                v = v.decode("utf-8")
            except UnicodeDecodeError:
                continue
        out.append(str(v))
    return "; ".join(x for x in out if x != "")


# --------------------------------------------------------------------------
# Format handlers
# --------------------------------------------------------------------------
class Handler:
    family = "?"

    def read(self, mf):  # -> (fields, extras, covers)
        raise NotImplementedError

    def write(self, mf, fields: dict, extras: dict, covers):
        raise NotImplementedError

    def ensure_tags(self, mf):
        if mf.tags is None:
            mf.add_tags()


# ---------------------------------------------------------------- ID3 ------
ID3_MAP = {
    "title": "TIT2", "artist": "TPE1", "album": "TALB", "albumartist": "TPE2",
    "year": "TDRC", "genre": "TCON", "composer": "TCOM", "lyricist": "TEXT",
    "conductor": "TPE3", "bpm": "TBPM", "key": "TKEY", "mood": "TMOO",
    "grouping": "TIT1", "subtitle": "TIT3", "publisher": "TPUB",
    "copyright": "TCOP", "encodedby": "TENC", "isrc": "TSRC",
    "compilation": "TCMP", "sorttitle": "TSOT", "sortartist": "TSOP",
    "sortalbum": "TSOA", "sortalbumartist": "TSO2",
}


class ID3Handler(Handler):
    family = "ID3v2"

    def read(self, mf):
        f, extras, covers = {}, {}, []
        tags = mf.tags
        if tags is None:
            return f, extras, covers
        for key, fid in ID3_MAP.items():
            frames = tags.getall(fid)
            if fid == "TDRC" and not frames:
                frames = tags.getall("TYER")
            if frames:
                f[key] = _join(frames[0].text)
        trck = tags.getall("TRCK")
        if trck:
            f["track"], f["totaltracks"] = _split_num(_join(trck[0].text))
        tpos = tags.getall("TPOS")
        if tpos:
            f["disc"], f["totaldiscs"] = _split_num(_join(tpos[0].text))
        comms = [c for c in tags.getall("COMM") if not c.desc.startswith("iTun")]
        main = [c for c in comms if c.desc == ""] or comms
        if main:
            f["comment"] = _join(main[0].text)
        uslt = tags.getall("USLT")
        if uslt:
            f["lyrics"] = uslt[0].text
        for fr in tags.getall("TXXX"):
            extras[fr.desc] = _join(fr.text)
        for fr in tags.getall("APIC"):
            covers.append(Cover(fr.data, fr.mime or "", int(fr.type), fr.desc or ""))
        return f, extras, covers

    def write(self, mf, fields, extras, covers):
        self.ensure_tags(mf)
        tags = mf.tags
        for key, value in fields.items():
            if key in ("track", "totaltracks", "disc", "totaldiscs"):
                continue
            if key == "comment":
                tags.setall("COMM", [c for c in tags.getall("COMM") if c.desc != ""])
                if value:
                    tags.add(COMM(encoding=3, lang="eng", desc="", text=[value]))
                continue
            if key == "lyrics":
                tags.delall("USLT")
                if value:
                    tags.add(USLT(encoding=3, lang="eng", desc="", text=value))
                continue
            fid = ID3_MAP[key]
            tags.delall(fid)
            if fid == "TDRC":
                tags.delall("TYER")
                tags.delall("TDAT")
            if value:
                frame_cls = Frames[fid]
                if fid == "TCMP":
                    value = "1" if value.strip().lower() in ("1", "yes", "true") else "0"
                tags.add(frame_cls(encoding=3, text=[value]))
        for numkey, totkey, fid in (("track", "totaltracks", "TRCK"), ("disc", "totaldiscs", "TPOS")):
            if numkey in fields or totkey in fields:
                cur_n, cur_t = _split_num(_join(tags[fid].text)) if fid in tags else ("", "")
                n = fields.get(numkey, cur_n)
                t = fields.get(totkey, cur_t)
                tags.delall(fid)
                if n or t:
                    tags.add(Frames[fid](encoding=3, text=[f"{n}/{t}" if t else n]))
        for name, value in extras.items():
            tags.delall("TXXX:" + name)
            if value:
                tags.add(TXXX(encoding=3, desc=name, text=[value]))
        if covers is not None:
            tags.delall("APIC")
            for i, c in enumerate(covers):
                desc = c.desc or ("" if i == 0 else f"cover {i}")
                tags.add(APIC(encoding=3, mime=c.mime, type=c.ptype, desc=desc, data=c.data))


# ------------------------------------------------------- Vorbis / FLAC -----
VORBIS_MAP = {
    "title": ["TITLE"], "artist": ["ARTIST"], "album": ["ALBUM"],
    "albumartist": ["ALBUMARTIST", "ALBUM ARTIST"], "year": ["DATE", "YEAR"],
    "genre": ["GENRE"], "comment": ["COMMENT", "DESCRIPTION"],
    "composer": ["COMPOSER"], "lyricist": ["LYRICIST"], "conductor": ["CONDUCTOR"],
    "bpm": ["BPM"], "key": ["INITIALKEY", "KEY"], "mood": ["MOOD"],
    "grouping": ["GROUPING"], "subtitle": ["SUBTITLE"],
    "publisher": ["ORGANIZATION", "PUBLISHER", "LABEL"], "copyright": ["COPYRIGHT"],
    "encodedby": ["ENCODEDBY", "ENCODED-BY"], "isrc": ["ISRC"],
    "compilation": ["COMPILATION"], "sorttitle": ["TITLESORT"],
    "sortartist": ["ARTISTSORT"], "sortalbum": ["ALBUMSORT"],
    "sortalbumartist": ["ALBUMARTISTSORT"], "lyrics": ["LYRICS", "UNSYNCEDLYRICS"],
    "track": ["TRACKNUMBER"], "totaltracks": ["TRACKTOTAL", "TOTALTRACKS"],
    "disc": ["DISCNUMBER"], "totaldiscs": ["DISCTOTAL", "TOTALDISCS"],
}
_VORBIS_KNOWN = {k for keys in VORBIS_MAP.values() for k in keys} | {
    "METADATA_BLOCK_PICTURE", "COVERART", "COVERARTMIME"}


class VorbisHandler(Handler):
    family = "Vorbis Comment"

    def read(self, mf):
        f, extras, covers = {}, {}, []
        tags = mf.tags
        if tags is not None:
            upper = {}
            for k, v in tags.items():
                upper.setdefault(k.upper(), []).extend(v)
            for key, names in VORBIS_MAP.items():
                for n in names:
                    if n in upper:
                        f[key] = _join(upper[n])
                        break
            n, t = _split_num(f.get("track", ""))
            if t:
                f["track"] = n
                f.setdefault("totaltracks", t)
            n, t = _split_num(f.get("disc", ""))
            if t:
                f["disc"] = n
                f.setdefault("totaldiscs", t)
            for k, v in upper.items():
                if k not in _VORBIS_KNOWN:
                    extras[k] = _join(v)
            for b64 in upper.get("METADATA_BLOCK_PICTURE", []):
                try:
                    p = Picture(base64.b64decode(b64))
                    covers.append(Cover(p.data, p.mime, p.type, p.desc))
                except Exception:
                    pass
        if isinstance(mf, FLAC):
            for p in mf.pictures:
                covers.append(Cover(p.data, p.mime, p.type, p.desc))
        return f, extras, covers

    def _set(self, tags, names, value):
        for n in names:
            for existing in [k for k in tags.keys() if k.upper() == n]:
                del tags[existing]
        if value:
            tags[names[0]] = [value]

    def write(self, mf, fields, extras, covers):
        self.ensure_tags(mf)
        tags = mf.tags
        for key, value in fields.items():
            self._set(tags, VORBIS_MAP[key], value)
        for name, value in extras.items():
            self._set(tags, [name.upper()], value)
        if covers is not None:
            self._set(tags, ["METADATA_BLOCK_PICTURE"], "")
            self._set(tags, ["COVERART"], "")
            self._set(tags, ["COVERARTMIME"], "")
            pics = []
            for c in covers:
                p = Picture()
                p.data, p.mime, p.type, p.desc = c.data, c.mime, c.ptype, c.desc
                pics.append(p)
            if isinstance(mf, FLAC):
                mf.clear_pictures()
                for p in pics:
                    mf.add_picture(p)
            elif pics:
                tags["METADATA_BLOCK_PICTURE"] = [
                    base64.b64encode(p.write()).decode("ascii") for p in pics]


# ---------------------------------------------------------------- MP4 ------
FF = "----:com.apple.iTunes:"
MP4_MAP = {
    "title": "\xa9nam", "artist": "\xa9ART", "album": "\xa9alb", "albumartist": "aART",
    "year": "\xa9day", "genre": "\xa9gen", "comment": "\xa9cmt", "composer": "\xa9wrt",
    "lyrics": "\xa9lyr", "grouping": "\xa9grp", "encodedby": "\xa9too",
    "copyright": "cprt", "bpm": "tmpo", "compilation": "cpil",
    "sorttitle": "sonm", "sortartist": "soar", "sortalbum": "soal",
    "sortalbumartist": "soaa", "subtitle": FF + "SUBTITLE", "publisher": FF + "LABEL",
    "lyricist": FF + "LYRICIST", "conductor": FF + "CONDUCTOR", "isrc": FF + "ISRC",
    "mood": FF + "MOOD", "key": FF + "initialkey",
}
_MP4_KNOWN = set(MP4_MAP.values()) | {"trkn", "disk", "covr"}


class MP4Handler(Handler):
    family = "MP4 / iTunes"

    def read(self, mf):
        f, extras, covers = {}, {}, []
        tags = mf.tags
        if tags is None:
            return f, extras, covers
        for key, atom in MP4_MAP.items():
            if atom in tags:
                v = tags[atom]
                if atom == "cpil":
                    f[key] = "1" if v else "0"
                else:
                    f[key] = _join(v if isinstance(v, list) else [v])
        for atom, nk, tk in (("trkn", "track", "totaltracks"), ("disk", "disc", "totaldiscs")):
            if atom in tags and tags[atom]:
                n, t = tags[atom][0]
                f[nk] = str(n) if n else ""
                f[tk] = str(t) if t else ""
        for k, v in tags.items():
            if k.startswith(FF) and k not in _MP4_KNOWN:
                extras[k[len(FF):]] = _join(v)
        for c in tags.get("covr", []):
            mime = "image/png" if c.imageformat == MP4Cover.FORMAT_PNG else "image/jpeg"
            covers.append(Cover(bytes(c), mime, 3, ""))
        return f, extras, covers

    def write(self, mf, fields, extras, covers):
        self.ensure_tags(mf)
        tags = mf.tags
        for key, value in fields.items():
            if key in ("track", "totaltracks", "disc", "totaldiscs"):
                continue
            atom = MP4_MAP[key]
            tags.pop(atom, None)
            if not value:
                continue
            if atom == "tmpo":
                try:
                    tags[atom] = [int(float(value))]
                except ValueError:
                    pass
            elif atom == "cpil":
                tags[atom] = value.strip().lower() in ("1", "yes", "true")
            elif atom.startswith(FF):
                tags[atom] = [MP4FreeForm(value.encode("utf-8"))]
            else:
                tags[atom] = [value]
        for atom, nk, tk in (("trkn", "track", "totaltracks"), ("disk", "disc", "totaldiscs")):
            if nk in fields or tk in fields:
                cur = tags[atom][0] if atom in tags and tags[atom] else (0, 0)
                n = fields.get(nk, str(cur[0] or ""))
                t = fields.get(tk, str(cur[1] or ""))
                tags.pop(atom, None)
                ni, ti = _to_int(n), _to_int(t)
                if ni or ti:
                    tags[atom] = [(ni, ti)]
        for name, value in extras.items():
            tags.pop(FF + name, None)
            if value:
                tags[FF + name] = [MP4FreeForm(value.encode("utf-8"))]
        if covers is not None:
            tags.pop("covr", None)
            if covers:
                tags["covr"] = [MP4Cover(c.data, MP4Cover.FORMAT_PNG if c.mime == "image/png"
                                         else MP4Cover.FORMAT_JPEG) for c in covers]


def _to_int(v) -> int:
    try:
        return int(str(v).strip() or 0)
    except ValueError:
        digits = "".join(ch for ch in str(v) if ch.isdigit())
        return int(digits) if digits else 0


# ---------------------------------------------------------------- ASF ------
ASF_MAP = {
    "title": "Title", "artist": "Author", "album": "WM/AlbumTitle",
    "albumartist": "WM/AlbumArtist", "year": "WM/Year", "track": "WM/TrackNumber",
    "totaltracks": "TotalTracks", "disc": "WM/PartOfSet", "genre": "WM/Genre",
    "comment": "Description", "composer": "WM/Composer", "lyricist": "WM/Writer",
    "conductor": "WM/Conductor", "bpm": "WM/BeatsPerMinute", "key": "WM/InitialKey",
    "mood": "WM/Mood", "grouping": "WM/ContentGroupDescription",
    "subtitle": "WM/SubTitle", "publisher": "WM/Publisher", "copyright": "Copyright",
    "encodedby": "WM/EncodedBy", "isrc": "WM/ISRC", "compilation": "WM/IsCompilation",
    "lyrics": "WM/Lyrics", "sorttitle": "WM/TitleSortOrder",
    "sortartist": "WM/ArtistSortOrder", "sortalbum": "WM/AlbumSortOrder",
    "sortalbumartist": "WM/AlbumArtistSortOrder",
}
_ASF_SKIP = set(ASF_MAP.values()) | {"WM/Picture", "TotalDiscs"}


def _asf_pic_parse(raw: bytes) -> Cover | None:
    try:
        ptype = raw[0]
        size = struct.unpack_from("<I", raw, 1)[0]
        pos = 5
        parts = []
        for _ in range(2):
            end = pos
            while raw[end:end + 2] != b"\x00\x00":
                end += 2
            parts.append(raw[pos:end].decode("utf-16-le"))
            pos = end + 2
        return Cover(raw[pos:pos + size], parts[0], ptype, parts[1])
    except Exception:
        return None


def _asf_pic_build(c: Cover) -> bytes:
    return (struct.pack("<bI", c.ptype, len(c.data)) + c.mime.encode("utf-16-le") + b"\x00\x00"
            + c.desc.encode("utf-16-le") + b"\x00\x00" + c.data)


class ASFHandler(Handler):
    family = "WMA / ASF"

    def read(self, mf):
        f, extras, covers = {}, {}, []
        tags = mf.tags
        if tags is None:
            return f, extras, covers
        for key, name in ASF_MAP.items():
            if name in tags:
                f[key] = _join(str(v) for v in tags[name])
        n, t = _split_num(f.get("disc", ""))
        if t:
            f["disc"], f["totaldiscs"] = n, t
        elif "TotalDiscs" in tags:
            f["totaldiscs"] = _join(str(v) for v in tags["TotalDiscs"])
        for k in tags.keys():
            if k not in _ASF_SKIP:
                try:
                    extras[k] = _join(str(v) for v in tags[k] if not isinstance(v, ASFByteArrayAttribute))
                except Exception:
                    pass
        for v in tags.get("WM/Picture", []):
            c = _asf_pic_parse(v.value)
            if c:
                covers.append(c)
        return f, extras, covers

    def write(self, mf, fields, extras, covers):
        self.ensure_tags(mf)
        tags = mf.tags
        for key, value in fields.items():
            if key in ("disc", "totaldiscs"):
                continue
            name = ASF_MAP[key]
            if name in tags:
                del tags[name]
            if value:
                tags[name] = [value]
        if "disc" in fields or "totaldiscs" in fields:
            cur_n, cur_t = _split_num(_join(str(v) for v in tags.get("WM/PartOfSet", [])))
            n = fields.get("disc", cur_n)
            t = fields.get("totaldiscs", cur_t)
            for nm in ("WM/PartOfSet", "TotalDiscs"):
                if nm in tags:
                    del tags[nm]
            if n or t:
                tags["WM/PartOfSet"] = [f"{n}/{t}" if t else n]
        for name, value in extras.items():
            if name in tags:
                del tags[name]
            if value:
                tags[name] = [value]
        if covers is not None:
            if "WM/Picture" in tags:
                del tags["WM/Picture"]
            if covers:
                tags["WM/Picture"] = [ASFByteArrayAttribute(_asf_pic_build(c)) for c in covers]


# ---------------------------------------------------------------- APEv2 ----
APE_MAP = {
    "title": ["Title"], "artist": ["Artist"], "album": ["Album"],
    "albumartist": ["Album Artist", "AlbumArtist"], "year": ["Year"],
    "genre": ["Genre"], "comment": ["Comment"], "composer": ["Composer"],
    "lyricist": ["Lyricist"], "conductor": ["Conductor"], "bpm": ["BPM"],
    "key": ["INITIALKEY", "Key"], "mood": ["Mood"], "grouping": ["Grouping"],
    "subtitle": ["Subtitle"], "publisher": ["Publisher", "Label"],
    "copyright": ["Copyright"], "encodedby": ["EncodedBy"], "isrc": ["ISRC"],
    "compilation": ["Compilation"], "sorttitle": ["TitleSort"],
    "sortartist": ["ArtistSort"], "sortalbum": ["AlbumSort"],
    "sortalbumartist": ["AlbumArtistSort"], "lyrics": ["Lyrics"],
    "track": ["Track"], "disc": ["Disc"],
}
_APE_KNOWN = {n.lower() for v in APE_MAP.values() for n in v}
APE_COVER_KEYS = {3: "Cover Art (Front)", 4: "Cover Art (Back)"}


class APEHandler(Handler):
    """APEv2 tags (Monkey's Audio, WavPack, Musepack, TAK, OptimFROG, raw AAC...)."""
    family = "APEv2"

    def __init__(self, standalone_path: str | None = None):
        self.standalone_path = standalone_path

    def _tags(self, mf):
        return mf if self.standalone_path else mf.tags

    def read(self, mf):
        f, extras, covers = {}, {}, []
        tags = self._tags(mf)
        if tags is None:
            return f, extras, covers
        lower = {k.lower(): k for k in tags.keys()}
        for key, names in APE_MAP.items():
            for n in names:
                if n.lower() in lower:
                    v = tags[lower[n.lower()]]
                    if v.kind != BINARY:
                        f[key] = _join(list(v))
                    break
        f["track"], tt = _split_num(f.get("track", ""))
        f["disc"], td = _split_num(f.get("disc", ""))
        if tt:
            f["totaltracks"] = tt
        if td:
            f["totaldiscs"] = td
        for k in ("track", "disc"):
            if not f[k]:
                del f[k]
        for lk, k in lower.items():
            v = tags[k]
            if lk.startswith("cover art"):
                raw = bytes(v.value)
                nul = raw.find(b"\x00")
                data = raw[nul + 1:] if nul >= 0 else raw
                covers.append(Cover(data, "", 4 if "back" in lk else 3, ""))
            elif lk not in _APE_KNOWN and v.kind != BINARY:
                extras[k] = _join(list(v))
        return f, extras, covers

    def _set(self, tags, names, value):
        lower = {k.lower(): k for k in tags.keys()}
        for n in names:
            if n.lower() in lower:
                del tags[lower[n.lower()]]
        if value:
            tags[names[0]] = value

    def write(self, mf, fields, extras, covers):
        if not self.standalone_path:
            self.ensure_tags(mf)
        tags = self._tags(mf)
        for key, value in fields.items():
            if key in ("track", "totaltracks", "disc", "totaldiscs"):
                continue
            self._set(tags, APE_MAP[key], value)
        for nk, tk, name in (("track", "totaltracks", "Track"), ("disc", "totaldiscs", "Disc")):
            if nk in fields or tk in fields:
                lower = {k.lower(): k for k in tags.keys()}
                cur = str(tags[lower[name.lower()]]) if name.lower() in lower else ""
                cn, ct = _split_num(cur)
                n, t = fields.get(nk, cn), fields.get(tk, ct)
                self._set(tags, [name], f"{n}/{t}" if t else n)
        for name, value in extras.items():
            self._set(tags, [name], value)
        if covers is not None:
            for k in [k for k in tags.keys() if k.lower().startswith("cover art")]:
                del tags[k]
            for c in covers:
                key = APE_COVER_KEYS.get(c.ptype, "Cover Art (Front)")
                if key in tags:
                    continue
                tags[key] = APEValue(b"cover" + c.ext.encode() + b"\x00" + c.data, BINARY)


# --------------------------------------------------------------------------
# AudioFile
# --------------------------------------------------------------------------
FORMAT_NAMES = {
    "MP3": "MP3", "EasyMP3": "MP3", "FLAC": "FLAC", "OggVorbis": "Ogg Vorbis",
    "OggOpus": "Opus", "OggSpeex": "Speex", "OggFLAC": "Ogg FLAC", "OggTheora": "Ogg Theora",
    "MP4": "MP4/M4A", "ASF": "WMA", "WAVE": "WAV", "AIFF": "AIFF",
    "MonkeysAudio": "Monkey's Audio", "WavPack": "WavPack", "Musepack": "Musepack",
    "TrueAudio": "TTA", "OptimFROG": "OptimFROG", "TAK": "TAK", "DSF": "DSF",
    "DSDIFF": "DSDIFF", "AAC": "AAC", "AC3": "AC3",
}


class TagError(Exception):
    pass


_COVER_CACHE: "OrderedDict[int, AudioFile]" = OrderedDict()
_COVER_CACHE_MAX = 80


class AudioFile:
    def __init__(self, path: str):
        self.path = os.path.abspath(path)
        self.fields: dict[str, str] = {}
        self.extras: dict[str, str] = {}
        self._covers: list[Cover] | None = []
        self._cover_count = 0
        self._covers_orig: list[Cover] | None = None
        self.info: dict = {}
        self.format = "?"
        self.tag_family = "?"
        self.error = ""
        self._dirty: set[str] = set()
        self._dirty_extras: set[str] = set()
        self._covers_dirty = False
        self.load()

    # -------------------------------------------------------------- loading
    def _open(self):
        try:
            mf = mutagen.File(self.path)
        except Exception as e:  # corrupt file etc.
            raise TagError(str(e))
        if mf is None:
            raise TagError("Not a supported audio file")
        return mf

    def _handler_for(self, mf):
        if type(mf).__name__ == "TrueAudio" or (
                type(mf).__name__ == "APEv2File" and self.path.lower().endswith(".tta")):
            return self._standalone_ape()
        if isinstance(mf, ID3FileType) or isinstance(getattr(mf, "tags", None), ID3) \
                or type(mf).__name__ in ("WAVE", "AIFF", "DSF", "DSDIFF"):
            return ID3Handler(), mf
        if isinstance(mf, MP4):
            return MP4Handler(), mf
        if isinstance(mf, ASF):
            return ASFHandler(), mf
        if isinstance(mf, APEv2File):
            return APEHandler(), mf
        if type(mf).__name__ in ("FLAC", "OggVorbis", "OggOpus", "OggSpeex", "OggFLAC", "OggTheora"):
            return VorbisHandler(), mf
        # No native tag support (raw AAC, AC3 ...) -> APEv2 at end of file, like Mp3tag.
        return self._standalone_ape()

    def _standalone_ape(self):
        try:
            ape = APEv2(self.path)
        except APENoHeaderError:
            ape = APEv2()
        return APEHandler(self.path), ape

    def load(self):
        self.fields, self.extras, self.info = {}, {}, {}
        self._covers, self._cover_count, self._covers_orig = [], 0, None
        _COVER_CACHE.pop(id(self), None)
        self._dirty.clear()
        self._dirty_extras.clear()
        self._covers_dirty = False
        self.error = ""
        try:
            mf = self._open()
        except TagError as e:
            self.error = str(e)
            self.format = os.path.splitext(self.path)[1].lstrip(".").upper()
            return
        handler, target = self._handler_for(mf)
        info_src = mf
        if type(mf).__name__ == "APEv2File":
            # e.g. a raw .aac that already has an APE tag - get real audio info
            try:
                from mutagen.aac import AAC
                from mutagen.ac3 import AC3
                from mutagen.trueaudio import TrueAudio
                found = mutagen.File(self.path, options=[TrueAudio, AAC, AC3])
                info_src = mf if found is None else found
            except Exception:
                info_src = mf
        self.format = FORMAT_NAMES.get(type(info_src).__name__, type(info_src).__name__)
        mf = info_src
        self.tag_family = handler.family
        try:
            fields, extras, covers = handler.read(target)
        except Exception as e:
            fields, extras, covers = {}, {}, []
            self.error = f"Could not read tags: {e}"
        self.fields = {k: v for k, v in fields.items() if v is not None}
        self.extras = extras
        # Pictures can be big - remember how many there are and read them again only when needed.
        self._cover_count = len(covers)
        self._covers = None if covers else []
        info = getattr(mf, "info", None)
        if info is not None:
            self.info = {
                "length": float(getattr(info, "length", 0) or 0),
                "bitrate": int(getattr(info, "bitrate", 0) or 0),
                "sample_rate": int(getattr(info, "sample_rate", 0) or 0),
                "channels": int(getattr(info, "channels", 0) or 0),
                "bits": int(getattr(info, "bits_per_sample", 0) or 0),
                "codec": getattr(info, "codec_description", "") or "",
            }
            if not self.info["bitrate"] and self.info["length"]:
                try:
                    self.info["bitrate"] = int(os.path.getsize(self.path) * 8 / self.info["length"])
                except OSError:
                    pass
        try:
            st = os.stat(self.path)
            self.info["size"] = st.st_size
            self.info["mtime"] = st.st_mtime
        except OSError:
            pass

    # -------------------------------------------------------------- editing
    def get(self, key: str) -> str:
        return self.fields.get(key, "")

    def set(self, key: str, value: str) -> bool:
        value = "" if value is None else str(value)
        if key in FIELD_LABELS:
            if self.fields.get(key, "") == value:
                return False
            if value:
                self.fields[key] = value
            else:
                self.fields.pop(key, None)
            self._dirty.add(key)
            return True
        # unknown name -> extra / custom field
        if self.extras.get(key, "") == value:
            return False
        if value:
            self.extras[key] = value
        else:
            self.extras.pop(key, None)
        self._dirty_extras.add(key)
        return True

    @property
    def covers(self) -> list[Cover]:
        if self._covers is None:
            self._covers = self._read_covers()
            _COVER_CACHE[id(self)] = self
            _COVER_CACHE.move_to_end(id(self))
            while len(_COVER_CACHE) > _COVER_CACHE_MAX:
                _, old = _COVER_CACHE.popitem(last=False)
                if old is not self and not old._covers_dirty and old._covers:
                    old._covers = None
        elif id(self) in _COVER_CACHE:
            _COVER_CACHE.move_to_end(id(self))
        return self._covers

    @property
    def cover_count(self) -> int:
        return self._cover_count if self._covers is None else len(self._covers)

    def _read_covers(self) -> list[Cover]:
        try:
            mf = self._open()
            handler, target = self._handler_for(mf)
            return handler.read(target)[2]
        except Exception:
            return []

    def set_covers(self, covers: list[Cover]):
        covers = list(covers)
        if not self._covers_dirty:
            self._covers_orig = list(self.covers)   # kept for Undo
        self._covers = covers
        self._covers_dirty = True
        _COVER_CACHE.pop(id(self), None)

    @property
    def dirty(self) -> bool:
        return bool(self._dirty or self._dirty_extras or self._covers_dirty)

    def snapshot(self):
        return (dict(self.fields), dict(self.extras), list(self.covers),
                set(self._dirty), set(self._dirty_extras), self._covers_dirty, self.path)

    def restore(self, snap):
        (self.fields, self.extras, self._covers, self._dirty,
         self._dirty_extras, self._covers_dirty, self.path) = (
            dict(snap[0]), dict(snap[1]), list(snap[2]), set(snap[3]),
            set(snap[4]), snap[5], snap[6])

    # -------------------------------------------------------------- saving
    def save(self, id3_version: int = 3, id3v1: str = "keep", keep_mtime: bool = False):
        if not self.dirty:
            return False
        mtime = self.info.get("mtime")
        mf = self._open()
        handler, target = self._handler_for(mf)
        fields = {k: self.fields.get(k, "") for k in self._dirty}
        extras = {k: self.extras.get(k, "") for k in self._dirty_extras}
        handler.write(target, fields, extras, self.covers if self._covers_dirty else None)
        if isinstance(handler, APEHandler) and handler.standalone_path:
            target.save(self.path)
        elif isinstance(handler, ID3Handler):
            kwargs = {"v2_version": 4 if id3_version == 4 else 3}
            if type(mf).__name__ in ("MP3", "EasyMP3"):
                kwargs["v1"] = {"remove": 0, "keep": 1, "write": 2}.get(id3v1, 1)
            if id3_version == 3:
                kwargs["v23_sep"] = "/"
            try:
                target.save(**kwargs)
            except TypeError:
                kwargs.pop("v1", None)
                target.save(**kwargs)
        else:
            target.save()
        if keep_mtime and mtime:
            try:
                os.utime(self.path, (mtime, mtime))
            except OSError:
                pass
        self.load()
        return True

    def remove_tags(self):
        """Strip every tag (and picture) from the file."""
        mf = self._open()
        handler, target = self._handler_for(mf)
        if isinstance(handler, APEHandler) and handler.standalone_path:
            try:
                APEv2(self.path).delete(self.path)
            except APENoHeaderError:
                pass
        else:
            if isinstance(mf, FLAC):
                mf.clear_pictures()
                mf.save()
                mf = self._open()
            try:
                mf.delete()
            except Exception:
                if mf.tags is not None:
                    mf.tags.clear()
                    mf.save()
            if type(mf).__name__ in ("MP3", "EasyMP3"):
                try:
                    ID3(self.path).delete(self.path, delete_v1=True, delete_v2=True)
                except ID3NoHeaderError:
                    pass
        self.load()

    # -------------------------------------------------------------- helpers
    @property
    def filename(self) -> str:
        return os.path.basename(self.path)

    @property
    def stem(self) -> str:
        return os.path.splitext(self.filename)[0]

    @property
    def ext(self) -> str:
        return os.path.splitext(self.filename)[1]

    @property
    def folder(self) -> str:
        return os.path.dirname(self.path)

    def value_for(self, name: str) -> str:
        """Value for a %placeholder% - fields, extras and file properties."""
        name = name.lower()
        if name in FIELD_LABELS:
            return self.fields.get(name, "")
        props = {
            "_filename": self.stem, "_ext": self.ext.lstrip("."), "_path": self.path,
            "_folder": os.path.basename(self.folder), "_folderpath": self.folder,
            "_parent": os.path.basename(os.path.dirname(self.folder)),
            "_length": fmt_length(self.info.get("length", 0)),
            "_bitrate": str(self.info.get("bitrate", 0) // 1000 or ""),
            "_samplerate": str(self.info.get("sample_rate", "") or ""),
            "_format": self.format, "_size": fmt_size(self.info.get("size", 0)),
            "_tag": self.tag_family, "_covers": str(self.cover_count),
        }
        if name in props:
            return props[name]
        for k, v in self.extras.items():
            if k.lower() == name:
                return v
        return ""


def fmt_length(seconds: float) -> str:
    s = int(round(seconds or 0))
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_size(n: int) -> str:
    n = n or 0
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return str(n)
