"""Round-trip test of the tag engine on every sample file.

Usage: python test_engine.py <folder with sample audio files>
"""
import io
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
from eztag.tags import AudioFile, Cover, FIELD_KEYS, is_audio  # noqa: E402


def make_png():
    import struct
    import zlib
    raw = b"".join(b"\x00" + bytes([255, 80, 0]) * 8 for _ in range(8))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


VALUES = {k: f"Ünïcode {k} ✓" for k in FIELD_KEYS}
VALUES.update(year="2026", track="7", totaltracks="12", disc="1", totaldiscs="2",
              bpm="128", compilation="1", lyrics="Line one\nLine two ñ")


def run(folder):
    tmp = tempfile.mkdtemp()
    png = make_png()
    ok = fail = 0
    for name in sorted(os.listdir(folder)):
        src = os.path.join(folder, name)
        if not is_audio(src) or name == "base.wav":
            continue
        path = os.path.join(tmp, name)
        shutil.copy(src, path)
        problems = []
        af = AudioFile(path)
        if af.error:
            problems.append("open: " + af.error)
        for k, v in VALUES.items():
            af.set(k, v)
        af.set("MY CUSTOM", "custom value")
        af.set_covers([Cover(png)])
        try:
            af.save(id3_version=3)
        except Exception as e:
            problems.append(f"save: {e!r}")
        b = AudioFile(path)
        for k, v in VALUES.items():
            got = b.get(k)
            if got != v:
                problems.append(f"{k}: {got!r}")
        if b.value_for("my custom") != "custom value":
            problems.append(f"extra: {b.extras}")
        if not b.covers or b.covers[0].data != png:
            problems.append(f"cover: {len(b.covers)}")
        # change one field only, the others must stay
        b.set("title", "Second")
        b.save(id3_version=4)
        c = AudioFile(path)
        if c.get("title") != "Second" or c.get("artist") != VALUES["artist"] or not c.covers:
            problems.append("partial save lost data")
        # clear a field
        c.set("comment", "")
        c.save()
        d = AudioFile(path)
        if d.get("comment"):
            problems.append("clear failed")
        d.remove_tags()
        e = AudioFile(path)
        if e.get("title") or e.covers:
            problems.append(f"remove failed {e.fields} covers={len(e.covers)}")
        if e.error:
            problems.append("after remove: " + e.error)
        status = "OK  " if not problems else "FAIL"
        print(f"{status} {name:12} {b.format:14} {b.tag_family:16} "
              f"{b.info.get('length', 0):.1f}s {b.info.get('bitrate', 0)//1000}kbps "
              + ("; ".join(problems[:6])))
        ok += not problems
        fail += bool(problems)
    print(f"\n{ok} passed, {fail} failed")
    return fail


if __name__ == "__main__":
    sys.exit(1 if run(sys.argv[1]) else 0)
