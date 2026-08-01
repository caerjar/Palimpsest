#!/bin/bash
# Build the Palimpsest macOS .app (with pandoc bundled) and wrap it in a .dmg.
#
#   ./packaging/build_dmg.sh
#
# Produces:  dist/Palimpsest.app   and   dist/Palimpsest-<version>.dmg
#
# Decisions baked in (see the packaging discussion):
#   • pandoc is bundled (~150 MB) so Word/HTML/Markdown export work out of the box.
#   • XeLaTeX is NOT bundled — PDF export prompts the user to `brew install basictex`.
#   • The .dmg is UNSIGNED (free). First launch: right-click the app → Open, once,
#     to get past Gatekeeper. Notarizing (no warning) needs an Apple Developer
#     account — see packaging/README.md.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"
# py2app is most reliable on a stable Python (3.11–3.12). Override if your default
# python3 is newer/unsupported:  PYTHON=/opt/homebrew/bin/python3.12 ./build_dmg.sh
PYTHON="${PYTHON:-python3}"
VERSION="$("$PYTHON" -c 'import tomllib;print(tomllib.load(open("pyproject.toml","rb"))["project"]["version"])')"
BUILD_VENV="$REPO/.build-venv"
BUNDLED_BIN="$REPO/packaging/bundled/bin"

echo "==> Palimpsest $VERSION — macOS .app + .dmg"

# 1. Stage pandoc. Prefer a pandoc already on this machine (a single, mostly-static
#    binary — copying just the executable is enough). Otherwise download a release.
mkdir -p "$BUNDLED_BIN"
if [ -x "$BUNDLED_BIN/pandoc" ]; then
    echo "==> pandoc already staged: $BUNDLED_BIN/pandoc"
elif command -v pandoc >/dev/null 2>&1; then
    echo "==> copying local pandoc: $(command -v pandoc)"
    cp "$(command -v pandoc)" "$BUNDLED_BIN/pandoc"
else
    # A downloaded binary gets shipped inside the .app we hand to other people, so
    # it is verified before it is bundled: set PANDOC_SHA256 to the checksum from
    # the pandoc release page. Without one we refuse rather than bundle an unchecked
    # binary — install pandoc locally (brew install pandoc) and we'll copy that.
    PANDOC_VERSION="${PANDOC_VERSION:-3.1.11}"
    ARCH="$(uname -m)"; case "$ARCH" in arm64) PA=arm64;; *) PA=x86_64;; esac
    URL="https://github.com/jgm/pandoc/releases/download/${PANDOC_VERSION}/pandoc-${PANDOC_VERSION}-${PA}-macOS.zip"
    if [ -z "${PANDOC_SHA256:-}" ]; then
        echo "no pandoc found, and PANDOC_SHA256 is not set." >&2
        echo "  Either install pandoc (brew install pandoc) and re-run, or take the" >&2
        echo "  checksum for $(basename "$URL") from" >&2
        echo "  https://github.com/jgm/pandoc/releases/tag/${PANDOC_VERSION} and re-run with:" >&2
        echo "    PANDOC_SHA256=<sha256> ./packaging/build_dmg.sh" >&2
        exit 1
    fi
    echo "==> downloading pandoc $PANDOC_VERSION ($PA) from $URL"
    tmp="$(mktemp -d)"
    curl -fL "$URL" -o "$tmp/pandoc.zip"
    echo "==> verifying checksum"
    echo "${PANDOC_SHA256}  ${tmp}/pandoc.zip" | shasum -a 256 -c - || {
        echo "pandoc download does NOT match PANDOC_SHA256 — refusing to bundle it." >&2
        rm -rf "$tmp"; exit 1; }
    unzip -q "$tmp/pandoc.zip" -d "$tmp"
    cp "$(find "$tmp" -name pandoc -type f | head -1)" "$BUNDLED_BIN/pandoc"
    rm -rf "$tmp"
fi
chmod +x "$BUNDLED_BIN/pandoc"

# 2. Fresh build venv with py2app + the package itself.
echo "==> preparing build venv ($PYTHON)"
rm -rf "$BUILD_VENV"
"$PYTHON" -m venv "$BUILD_VENV"
"$BUILD_VENV/bin/pip" install --quiet --upgrade pip
"$BUILD_VENV/bin/pip" install --quiet py2app
# [pdf] pulls in PyMuPDF so the bundled app can import PDFs (setup_app.py bundles it
# only if it's importable here). Falls back to a plain install if the wheel can't be
# had for this Python/arch — the app then builds without PDF import.
"$BUILD_VENV/bin/pip" install --quiet '.[pdf]' || {
    echo "==> PyMuPDF unavailable; building without PDF import"
    "$BUILD_VENV/bin/pip" install --quiet .
}

# 3. Build the .app. (-O clean strips old build/ and dist/ first.)
echo "==> building .app with py2app"
rm -rf build dist
"$BUILD_VENV/bin/python" packaging/setup_app.py py2app >/dev/null

APP="dist/Palimpsest.app"
[ -d "$APP" ] || { echo "py2app did not produce $APP" >&2; exit 1; }
echo "==> built $APP ($(du -sh "$APP" | cut -f1))"

# 4. Wrap in a compressed .dmg with a drag-to-Applications layout.
DMG="dist/Palimpsest-$VERSION.dmg"
echo "==> creating $DMG"
staging="$(mktemp -d)"
cp -R "$APP" "$staging/"
ln -s /Applications "$staging/Applications"
rm -f "$DMG"
hdiutil create -volname "Palimpsest" -srcfolder "$staging" -ov -format UDZO "$DMG" >/dev/null
rm -rf "$staging"

echo "==> done:"
echo "    $APP"
echo "    $DMG  ($(du -sh "$DMG" | cut -f1))"
echo
echo "The .dmg is unsigned. Tell users: drag Palimpsest to Applications, then the"
echo "first time, right-click the app → Open (Gatekeeper asks once). After that it"
echo "opens normally and serves the workbench at http://127.0.0.1:8137."
