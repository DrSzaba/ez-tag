"""Tests for converters, actions, numbering, export and the online parsers."""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
from eztag import online, tools  # noqa: E402
from eztag.tags import AudioFile  # noqa: E402

FAILS = []


def check(name, got, want):
    if got != want:
        FAILS.append(f"{name}: got {got!r} want {want!r}")
        print("FAIL", name, repr(got), "!=", repr(want))
    else:
        print("ok  ", name)


def main(sample_mp3):
    tmp = tempfile.mkdtemp()
    album = os.path.join(tmp, "El Szaba - Noches de Brunswick")
    os.makedirs(album)
    names = ["01 - El Szaba - Luna Llena.mp3", "02 - El Szaba - la playa_azul.mp3",
             "03 - El Szaba - FUEGO (Remix).mp3"]
    for n in names:
        shutil.copy(sample_mp3, os.path.join(album, n))
    files = [AudioFile(os.path.join(album, n)) for n in names]

    # filename -> tag
    res = tools.tags_from_filename(files[0], "%track% - %artist% - %title%")
    check("name->tag", res, {"track": "1", "artist": "El Szaba", "title": "Luna Llena"})
    res = tools.tags_from_filename(files[0], "%albumartist% - %album%\\%track% - %dummy% - %title%")
    check("name->tag folder", res, {"albumartist": "El Szaba", "album": "Noches de Brunswick",
                                    "track": "1", "title": "Luna Llena"})
    check("no match", tools.tags_from_filename(files[0], "%artist% _ %title% _ %x%"), None)
    g = tools.guess_from_filename(files[1])
    check("guess", (g.get("track"), g.get("artist"), g.get("title"), g.get("album")),
          ("2", "El Szaba", "la playa azul", "Noches de Brunswick"))

    for af in files:
        for k, v in tools.guess_from_filename(af).items():
            af.set(k, v)
        af.set("year", "2026")
        af.save()

    # format strings
    a = AudioFile(files[1].path)
    check("render", tools.render("$num(%track%,2). %artist% - $caps(%title%)", a),
          "02. El Szaba - La Playa Azul")
    check("render optional", tools.render("%title%[ (%genre%)][ \\[%year%\\]]", a), "la playa azul [2026]")
    check("render if2", tools.render("$if2(%albumartist%,%artist%)", a), "El Szaba")
    check("render nested", tools.render("$upper($left(%artist%,2))", a), "EL")
    check("render props", tools.render("%_ext% %_folder%", a), "mp3 El Szaba - Noches de Brunswick")
    check("render escape", tools.render("100\\% %title%", a), "100% la playa azul")

    # actions
    check("case caps", tools.change_case("the king of the hill", "caps"), "The King of the Hill")
    check("case sentence", tools.change_case("HELLO THERE. how ARE you", "sentence"),
          "Hello there. How are you")
    check("fixup", tools.fix_up("  fuego_(remix)  ", "title"), "Fuego (Remix)")
    check("fix track", tools.fix_up("003", "track"), "3")
    check("replace word", tools.replace_text("Feat. Bob feat Al", "feat", "ft", whole_word=True),
          "ft. Bob ft Al")
    check("regex", tools.replace_text("Song (Remix 2020)", r"\s*\(.*\)", "", regex=True), "Song")
    check("brackets", tools.remove_brackets("Song [Live] (2009 Remaster)"), "Song")
    check("strip num", tools.strip_track_prefix("03 - Fuego"), "Fuego")

    # tag -> filename + rename
    b = AudioFile(files[2].path)
    newp = tools.filename_from_tags(b, "$num(%track%,2) %title%")
    check("tag->name", os.path.basename(newp), "03 FUEGO (Remix).mp3")
    newp2 = tools.filename_from_tags(b, "%artist%: %title%?")
    check("sanitize", os.path.basename(newp2), "El Szaba_ FUEGO (Remix)_.mp3")
    tools.rename_file(b, newp)
    check("renamed", os.path.exists(newp) and b.path == os.path.abspath(newp), True)

    # numbering
    fl = [AudioFile(f.path if os.path.exists(f.path) else newp) for f in files]
    tools.auto_number(fl, start=1, pad=2)
    check("number", [f.get("track") for f in fl] + [fl[0].get("totaltracks")], ["01", "02", "03", "3"])

    # text -> tag
    rows = tools.tags_from_lines(["1. Uno - First", "2. Dos - Second"], "%track%. %title% - %comment%")
    check("text->tag", rows, [{"track": "1", "title": "Uno", "comment": "First"},
                              {"track": "2", "title": "Dos", "comment": "Second"}])

    # duplicates
    dupe = os.path.join(tmp, "copy.mp3")
    shutil.copy(fl[0].path, dupe)
    allf = fl + [AudioFile(dupe)]
    check("duplicates", len(tools.find_duplicates(allf)), 1)

    # export
    for fn, ext in ((tools.export_csv, "csv"), (tools.export_html, "html"),
                    (tools.export_m3u, "m3u8"), (tools.export_txt, "txt")):
        out = os.path.join(tmp, "list." + ext)
        fn(fl, out)
        check("export " + ext, os.path.getsize(out) > 20, True)
    print(open(os.path.join(tmp, "list.m3u8"), encoding="utf-8-sig").read())

    # folder cover
    open(os.path.join(album, "Folder.JPG"), "wb").write(b"\xff\xd8\xff\xe0fake")
    check("folder cover", os.path.basename(tools.find_folder_cover(album) or ""), "Folder.JPG")

    # online parsers (offline sample data)
    lookup = {"results": [
        {"wrapperType": "collection", "collectionId": 9, "collectionName": "Album",
         "artistName": "Artist", "releaseDate": "2019-05-01T07:00:00Z", "trackCount": 2,
         "primaryGenreName": "Latin", "artworkUrl100": "https://x/100x100bb.jpg"},
        {"wrapperType": "track", "discNumber": 1, "trackNumber": 2, "trackCount": 2,
         "trackName": "B", "artistName": "Artist", "trackTimeMillis": 1000},
        {"wrapperType": "track", "discNumber": 1, "trackNumber": 1, "trackCount": 2,
         "trackName": "A", "artistName": "Artist", "trackTimeMillis": 2000}]}
    alb, trs = online.parse_itunes_lookup(lookup)
    check("itunes parse", (alb["title"], alb["year"], [t["title"] for t in trs]), ("Album", "2019", ["A", "B"]))
    pairs = online.match_tracks(fl[:2], trs)
    check("match by number", [t["title"] for _, t in pairs], ["A", "B"])
    mb = online.parse_mb_release_summary({"id": "x", "title": "T", "date": "2001-02-03",
                                          "artist-credit": [{"name": "A", "joinphrase": " & "}, {"name": "B"}],
                                          "media": [{"format": "CD", "track-count": 10}]})
    check("mb parse", (mb["artist"], mb["year"], mb["tracks"], mb["extra"]), ("A & B", "2001", 10, "CD"))

    print(f"\n{len(FAILS)} failures")
    return len(FAILS)


if __name__ == "__main__":
    sys.exit(1 if main(sys.argv[1]) else 0)
