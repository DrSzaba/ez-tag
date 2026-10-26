#!/usr/bin/env bash
# Builds  dist/EZ-Tag-Setup.exe  and  dist/EZ-Tag-Setup.zip  for Windows.
# Runs on Linux (Ubuntu) or in GitHub Actions - needs: curl, python3, makensis (apt install nsis), zip.
# The Setup bundles its own Python, so nobody has to install anything else.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="$(python3 -c "import re;print(re.search(r'VERSION = \"(.+?)\"', open('$ROOT/app/eztag/__init__.py').read()).group(1))")"
BUILD="$ROOT/build"
CACHE="$BUILD/cache"
STAGE="$BUILD/stage"
DIST="$ROOT/dist"

PY_URL="https://github.com/astral-sh/python-build-standalone/releases/download/20261009/cpython-3.12.15+20261009-x86_64-pc-windows-msvc-install_only_stripped.tar.gz"
PY_SHA="11ed9f8a6ac64fb1b5a55e40e305a6744a3f77a70863c8f8197a6e4349abc64a"
WHEELS=("mutagen==1.48.1" "pillow==12.3.0")

echo "== EZ Tag $VERSION =="
mkdir -p "$CACHE" "$DIST"
rm -rf "$STAGE"
mkdir -p "$STAGE"

# 1. Windows Python (portable, with tkinter)
if [ ! -f "$CACHE/python.tar.gz" ] || ! echo "$PY_SHA  $CACHE/python.tar.gz" | sha256sum -c --status; then
  echo "Downloading portable Windows Python..."
  curl -fsSL -o "$CACHE/python.tar.gz" "$PY_URL"
  echo "$PY_SHA  $CACHE/python.tar.gz" | sha256sum -c
fi
tar -xzf "$CACHE/python.tar.gz" -C "$STAGE"
P="$STAGE/python"
# trim what a desktop app never uses
rm -rf "$P/include" "$P/libs" "$P/Scripts" "$P/Lib/test" "$P/Lib/idlelib" "$P/Lib/ensurepip" \
       "$P/Lib/lib2to3" "$P/Lib/turtledemo" "$P/Lib/site-packages/pip"* "$P/tcl/tix8.4.3" \
       "$P/tcl/nmake" "$P/tcl/"*.lib "$P/tcl/"*.sh
find "$P" -name "__pycache__" -type d -prune -exec rm -rf {} +
find "$P/Lib" -path "*/tests" -type d -prune -exec rm -rf {} +

# 2. mutagen (tags) + Pillow (cover previews)
mkdir -p "$CACHE/wheels"
python3 -m pip download --quiet --dest "$CACHE/wheels" --only-binary=:all: --platform win_amd64 \
  --python-version 3.12 --implementation cp --no-deps "${WHEELS[@]}"
for w in "$CACHE"/wheels/*.whl; do
  python3 -m zipfile -e "$w" "$P/Lib/site-packages/"
done

# 3. the app
mkdir -p "$STAGE/app"
cp -r "$ROOT/app/." "$STAGE/app/"
find "$STAGE/app" -name "__pycache__" -type d -prune -exec rm -rf {} +
rm -f "$STAGE/app/assets/ez-tag-512.png"
cp "$ROOT/LICENSE" "$STAGE/LICENSE.txt"
cp "$ROOT/LICENSES.txt" "$STAGE/LICENSES.txt"
cat > "$STAGE/README.txt" <<EOF
EZ Tag $VERSION - the easy music tag editor
Free from Dr. Szaba - https://drszaba.github.io/ez-tag/

Start it from the desktop icon "EZ Tag" or right-click a music folder -> "Edit tags with EZ Tag".
Your settings are kept in %APPDATA%\\EZ Tag
If you like it, you can donate on Cash App: \$Szaba
EOF

# 4. installer
OUT="$DIST/EZ-Tag-Setup.exe"
makensis -V2 -DVERSION="$VERSION" -DSTAGE="$STAGE" -DOUTFILE="$OUT" "$ROOT/installer/ez-tag.nsi"
# Some PCs block .exe downloads, so we also ship it inside a zip
rm -f "$DIST/EZ-Tag-Setup.zip"
(cd "$DIST" && zip -q -9 "EZ-Tag-Setup.zip" "EZ-Tag-Setup.exe")
ls -la "$DIST"
echo "Done."
