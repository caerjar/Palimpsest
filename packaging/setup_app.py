"""py2app build spec for the Palimpsest .app (macOS).

Run indirectly via packaging/build_dmg.sh, which stages the bundled pandoc into
packaging/bundled/bin first. py2app keeps a real, bundled Python interpreter, so
the subprocess model (pal shells out to engine builders with sys.executable) works
unchanged inside the .app.

    python packaging/setup_app.py py2app     # from the repo root

The bundled pandoc lands at MyApp.app/Contents/Resources/bin/pandoc; the app puts
that on PATH at launch (see palimpsest.cli._bundle_tools_on_path). XeLaTeX is
NOT bundled — PDF export prompts the user to install BasicTeX; Word/HTML/Markdown
export work out of the box.
"""
import os
from setuptools import setup

HERE = os.path.dirname(os.path.abspath(__file__))
VERSION = "0.1.3"

APP = [os.path.join(HERE, "app_main.py")]

REPO = os.path.dirname(HERE)

# The engine (run as subprocesses by path) and the book template (copied to make a
# book) must be REAL files on disk, not entries in py2app's module zip. So ship them
# as bundle resources -> Contents/Resources/{engine,_template}. cli.py/library.py
# detect the zip at runtime and resolve to these (see their _resource fallbacks).
RESOURCES = [
    os.path.join(REPO, "palimpsest", "engine"),
    os.path.join(REPO, "palimpsest", "_template"),
]
# Bundled pandoc (~150 MB), staged by build_dmg.sh -> Contents/Resources/bin/pandoc.
_bundled_bin = os.path.join(HERE, "bundled", "bin")
if os.path.isdir(_bundled_bin):
    RESOURCES.append(_bundled_bin)

# PyMuPDF (imported as `fitz`) powers "import a PDF". It's a binary extension, so
# py2app only bundles it if it's present in the build venv — build_dmg.sh installs
# the [pdf] extra to make sure it is. If it's missing the app still builds; PDF
# import is the one feature that goes away, and it says so when you try it.
_PDF_PACKAGES = []
try:
    import fitz  # noqa: F401  (presence check only)
    _PDF_PACKAGES = ["fitz", "pymupdf"]
except Exception:
    print("setup_app: PyMuPDF not in the build environment — "
          "the .app will be built WITHOUT PDF import")

OPTIONS = {
    # palimpsest pulls in engine/ + _template via package data
    "packages": ["palimpsest"] + _PDF_PACKAGES,
    "includes": ["tomllib"],
    "resources": RESOURCES,             # -> Contents/Resources/bin/pandoc
    "plist": {
        "CFBundleName": "Palimpsest",
        "CFBundleDisplayName": "Palimpsest",
        "CFBundleIdentifier": "com.caerjar.palimpsest",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "LSMinimumSystemVersion": "11.0",
        "NSHighResolutionCapable": True,
        # The app opens a local web UI; it doesn't need to appear in the Dock as a
        # normal windowed app, but keeping it visible is friendlier for quitting.
        "LSUIElement": False,
    },
}

setup(
    name="Palimpsest",
    app=APP,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
