"""Remembers your choices between runs (stored in %APPDATA%\\EZ Tag\\settings.json)."""
from __future__ import annotations

import json
import os

DEFAULTS = {
    "id3_version": 3,            # 3 = ID3v2.3 (works everywhere, incl. Windows Explorer)
    "id3v1": "keep",             # keep / remove / write
    "keep_mtime": False,
    "recursive": True,
    "large_text": False,
    "confirm_rename": False,
    "last_folder": "",
    "recent_folders": [],
    "geometry": "1400x860",
    "zoomed": True,
    "columns": ["status", "_filename", "title", "artist", "album", "track", "year",
                "genre", "_length", "_format", "cover"],
    "col_widths": {},
    "tag2name_history": ["%artist% - %title%", "$num(%track%,2) - %title%",
                         "$num(%track%,2) - %artist% - %title%",
                         "%albumartist%\\%album%\\$num(%track%,2) - %title%"],
    "name2tag_history": ["%artist% - %title%", "%track% - %title%",
                         "%track% - %artist% - %title%", "%track%. %artist% - %title%",
                         "%artist%\\%album%\\%track% - %title%"],
    "format_history": ["$caps(%title%)", "%artist%", "$year(%year%)"],
    "online_source": "MusicBrainz",
    "rename_cover_name": "cover",
}


def _dir():
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    d = os.path.join(base, "EZ Tag")
    os.makedirs(d, exist_ok=True)
    return d


class Settings(dict):
    def __init__(self):
        super().__init__(DEFAULTS)
        self.path = os.path.join(_dir(), "settings.json")
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                self.update(data)
        except (OSError, ValueError):
            pass

    def save(self):
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self, fh, indent=2)
            os.replace(tmp, self.path)
        except OSError:
            pass

    def remember(self, key, value, limit=12):
        lst = [v for v in self.get(key, []) if v != value]
        lst.insert(0, value)
        self[key] = lst[:limit]
