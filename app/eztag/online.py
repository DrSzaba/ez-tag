"""Free online lookups - no account or key needed.

* MusicBrainz  (the big open music database) + Cover Art Archive
* iTunes / Apple Music search  (great for big, clean album covers)
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request

from . import VERSION

UA = f"EZTag/{VERSION} ( https://github.com/DrSzaba/ez-tag )"
_last_mb = [0.0]


def _get(url: str, timeout=20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _mb(path: str, **params) -> dict:
    # MusicBrainz asks for max 1 request per second
    wait = 1.05 - (time.time() - _last_mb[0])
    if wait > 0:
        time.sleep(wait)
    _last_mb[0] = time.time()
    params["fmt"] = "json"
    url = "https://musicbrainz.org/ws/2/" + path + "?" + urllib.parse.urlencode(params)
    return json.loads(_get(url))


def _lucene(s: str) -> str:
    return '"' + s.replace("\\", " ").replace('"', " ") + '"'


# --------------------------------------------------------------------------
# Results are plain dicts:
#   album:  {source, id, title, artist, year, tracks, country, label, extra}
#   track:  {disc, track, title, artist, length}
# --------------------------------------------------------------------------

def search_musicbrainz(artist: str = "", album: str = "", limit=15) -> list[dict]:
    q = []
    if album:
        q.append("release:" + _lucene(album))
    if artist:
        q.append("artist:" + _lucene(artist))
    if not q:
        return []
    data = _mb("release", query=" AND ".join(q), limit=limit)
    return [parse_mb_release_summary(r) for r in data.get("releases", [])]


def parse_mb_release_summary(r: dict) -> dict:
    credit = "".join(c.get("name", "") + c.get("joinphrase", "") for c in r.get("artist-credit", []))
    labels = [li.get("label", {}).get("name", "") for li in r.get("label-info", []) if li.get("label")]
    media = r.get("media", [])
    fmt = ", ".join(sorted({m.get("format", "") for m in media if m.get("format")}))
    return {
        "source": "MusicBrainz", "id": r.get("id", ""), "title": r.get("title", ""),
        "artist": credit, "year": (r.get("date") or "")[:4],
        "tracks": r.get("track-count") or sum(m.get("track-count", 0) for m in media),
        "country": r.get("country", ""), "label": labels[0] if labels else "",
        "extra": fmt,
    }


def get_musicbrainz_release(release_id: str) -> tuple[dict, list[dict]]:
    r = _mb("release/" + release_id, inc="recordings artist-credits labels genres release-groups isrcs")
    album = parse_mb_release_summary(r)
    genres = sorted(r.get("genres", []) + r.get("release-group", {}).get("genres", []),
                    key=lambda g: -g.get("count", 0))
    album["genre"] = genres[0]["name"].title() if genres else ""
    album["date"] = r.get("date", "")
    media = r.get("media", [])
    album["totaldiscs"] = str(len(media)) if len(media) > 1 else ""
    tracks = []
    for m in media:
        total = m.get("track-count", len(m.get("tracks", [])))
        for t in m.get("tracks", []):
            credit = "".join(c.get("name", "") + c.get("joinphrase", "")
                             for c in t.get("artist-credit", [])) or album["artist"]
            rec = t.get("recording", {})
            tracks.append({
                "disc": str(m.get("position", 1)), "track": str(t.get("position", "")),
                "totaltracks": str(total), "title": t.get("title", ""), "artist": credit,
                "length": (t.get("length") or 0) / 1000.0,
                "isrc": (rec.get("isrcs") or [""])[0],
            })
    return album, tracks


def musicbrainz_cover(release_id: str) -> bytes | None:
    for size in ("1200", "500", ""):
        url = f"https://coverartarchive.org/release/{release_id}/front" + (f"-{size}" if size else "")
        try:
            data = _get(url, timeout=30)
            if data[:3] == b"\xff\xd8\xff" or data[:4] == b"\x89PNG":
                return data
        except Exception:
            continue
    return None


# ---------------------------------------------------------------- iTunes ---

def search_itunes(artist: str = "", album: str = "", limit=15, country="US") -> list[dict]:
    term = " ".join(x for x in (artist, album) if x)
    if not term:
        return []
    url = "https://itunes.apple.com/search?" + urllib.parse.urlencode(
        {"term": term, "entity": "album", "limit": limit, "country": country})
    data = json.loads(_get(url))
    return [parse_itunes_album(a) for a in data.get("results", [])]


def parse_itunes_album(a: dict) -> dict:
    return {
        "source": "iTunes", "id": str(a.get("collectionId", "")),
        "title": a.get("collectionName", ""), "artist": a.get("artistName", ""),
        "year": (a.get("releaseDate") or "")[:4], "tracks": a.get("trackCount", 0),
        "country": a.get("country", ""), "label": "", "genre": a.get("primaryGenreName", ""),
        "copyright": a.get("copyright", ""), "art": a.get("artworkUrl100", ""),
        "extra": a.get("collectionExplicitness", "") == "explicit" and "Explicit" or "",
    }


def get_itunes_album(collection_id: str, country="US") -> tuple[dict, list[dict]]:
    url = "https://itunes.apple.com/lookup?" + urllib.parse.urlencode(
        {"id": collection_id, "entity": "song", "country": country, "limit": 200})
    data = json.loads(_get(url))
    return parse_itunes_lookup(data)


def parse_itunes_lookup(data: dict) -> tuple[dict, list[dict]]:
    results = data.get("results", [])
    coll = next((r for r in results if r.get("wrapperType") == "collection"), {})
    album = parse_itunes_album(coll) if coll else {}
    tracks = []
    for r in results:
        if r.get("wrapperType") != "track":
            continue
        tracks.append({
            "disc": str(r.get("discNumber", 1)), "track": str(r.get("trackNumber", "")),
            "totaltracks": str(r.get("trackCount", "")), "title": r.get("trackName", ""),
            "artist": r.get("artistName", ""), "length": (r.get("trackTimeMillis") or 0) / 1000.0,
            "genre": r.get("primaryGenreName", ""),
        })
    tracks.sort(key=lambda t: (int(t["disc"] or 1), int(t["track"] or 0)))
    discs = {t["disc"] for t in tracks}
    album["totaldiscs"] = str(len(discs)) if len(discs) > 1 else ""
    return album, tracks


def itunes_cover(art_url: str, size=1200) -> bytes | None:
    if not art_url:
        return None
    url = art_url.replace("100x100bb", f"{size}x{size}bb")
    try:
        return _get(url, timeout=30)
    except Exception:
        try:
            return _get(art_url, timeout=30)
        except Exception:
            return None


# ---------------------------------------------------------------- unified --

def search(source: str, artist: str, album: str) -> list[dict]:
    if source == "iTunes":
        return search_itunes(artist, album)
    return search_musicbrainz(artist, album)


def get_album(result: dict) -> tuple[dict, list[dict]]:
    if result["source"] == "iTunes":
        album, tracks = get_itunes_album(result["id"])
        album.setdefault("art", result.get("art", ""))
        return album, tracks
    return get_musicbrainz_release(result["id"])


def get_cover(album: dict) -> bytes | None:
    if album.get("source") == "iTunes":
        return itunes_cover(album.get("art", ""))
    return musicbrainz_cover(album.get("id", ""))


def match_tracks(files, tracks):
    """Pair files to tracks. Uses track numbers if every file has one, otherwise order."""
    nums = []
    for f in files:
        try:
            nums.append((int(f.get("disc") or 1), int(f.get("track"))))
        except (TypeError, ValueError):
            nums = None
            break
    by_num = {(int(t["disc"] or 1), int(t["track"] or 0)): t for t in tracks}
    if nums and all(n in by_num for n in nums) and len(set(nums)) == len(nums):
        return [(f, by_num[n]) for f, n in zip(files, nums)]
    return list(zip(files, tracks))
