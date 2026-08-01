"""Palimpsest — active-book configuration.

One place that answers: *which book are we building, where does its manuscript
live, what is it called, and what data has the author supplied?*

A **book** is a directory containing a `book.toml`. It may live anywhere; its
manuscript may live anywhere (config points at it). Layout:

    book.toml            # this file — title, paths, enabled views
    manifests/           # authored STRUCTURE (order/labels/parts/held/…) — save_server writes these
    data/                # authored tables (motifs, edit board)
    dossier/             # generated HTML output (gitignored)

The active book is resolved once, at import, from either:
  1. $PAL_BOOK  — a path to a book directory, or
  2. the nearest `book.toml` found walking up from the current directory.

Everything book-specific is read from here, so the same engine builds any
manuscript. Data loaders return safe empty defaults, so a brand-new book with no
`data/` still builds every view.
"""
import os
import html as _html
import json
import re
import tomllib
from pathlib import Path


class ConfigError(RuntimeError):
    pass


# ---------------------------------------------------------------- safe values
# Everything below flows into generated HTML. Two kinds of value need pinning
# before they get there, because both end up INSIDE markup rather than as text:
#
#   colors   land in style="…" attributes, so an unvalidated string can close the
#            attribute and open a tag. Only a hex literal is ever meaningful here.
#   titles   land in <h1>/<title>, so they need escaping (see TITLE_HTML below).
#
# A book's own data files are hand-editable and its book.toml may have come from
# somewhere else, so neither is trusted to be well-formed.
_HEX = re.compile(r"#[0-9a-fA-F]{3,8}\Z")


def safe_color(value, fallback="#7a6f52") -> str:
    """A hex color, or `fallback` if `value` isn't one. Use for anything that
    reaches a style attribute."""
    v = str(value or "").strip()
    return v if _HEX.match(v) else fallback


# ---------------------------------------------------------------- resolution
def _resolve_book_dir() -> Path:
    env = os.environ.get("PAL_BOOK")
    if env:
        p = Path(env).expanduser().resolve()
        if (p / "book.toml").is_file():
            return p
        raise ConfigError(f"$PAL_BOOK={env!r} does not contain a book.toml")
    cur = Path.cwd().resolve()
    for d in (cur, *cur.parents):
        if (d / "book.toml").is_file():
            return d
    raise ConfigError(
        "no book.toml found — set $PAL_BOOK to a book directory, or run from "
        "inside one (a directory tree containing book.toml)."
    )


BOOK_DIR = _resolve_book_dir()

with open(BOOK_DIR / "book.toml", "rb") as _fh:
    _TOML = tomllib.load(_fh)

_BOOK = _TOML.get("book", {})
_VIEWS = _TOML.get("views", {})
_PDF = _TOML.get("pdf", {})


def _path(rel, default) -> Path:
    """Resolve a book.toml path: absolute stays, relative is under BOOK_DIR."""
    q = Path(str(rel or default)).expanduser()
    return q if q.is_absolute() else (BOOK_DIR / q).resolve()


# ---------------------------------------------------------------- paths
MANUSCRIPT = str(_path(_BOOK.get("manuscript"), "manuscript"))
SUGGESTIONS = str(_path(_BOOK.get("suggestions"), "manuscript-suggestions"))
MANIFESTS = str(_path(_BOOK.get("manifests"), "manifests"))
OUT = str(_path(_BOOK.get("out"), "dossier"))
DATA_DIR = str(_path(_BOOK.get("data"), "data"))
RUBRIC = str(_path(_BOOK.get("rubric"), "copyedit-rubric.md"))

# Every save can be git-committed, giving each section a browsable history.
# Requires the manuscript to live inside a git repo; set `git = false` in
# book.toml to write plain files instead (the server degrades gracefully
# either way — an un-versioned manuscript just loses the history panel).
GIT = bool(_BOOK.get("git", True))

# alias used by modules that import MAN rather than MANUSCRIPT
MAN = MANUSCRIPT

# ---------------------------------------------------------------- path trust
# book.toml may point these anywhere, which is a real feature for a manuscript
# you keep elsewhere — and a hazard for a book folder someone sent you, since
# those paths decide what the engine reads and writes. We don't forbid them, but
# we do surface them (`pal serve` and `pal build` print a warning) and we refuse
# the one that is a straight file-read primitive: a [pdf] header outside the book
# is handed to XeLaTeX, which can \input anything the user can read.
# Set PAL_ALLOW_EXTERNAL_PATHS=1 to allow that header anyway.
ALLOW_EXTERNAL_PATHS = os.environ.get("PAL_ALLOW_EXTERNAL_PATHS") == "1"


def _outside_book(p) -> bool:
    """True if `p` resolves outside this book's own directory."""
    try:
        Path(str(p)).resolve().relative_to(BOOK_DIR)
        return False
    except (ValueError, OSError):
        return True


def external_paths():
    """{setting: path} for every book.toml path that leaves the book directory."""
    return {name: p for name, p in (("manuscript", MANUSCRIPT), ("suggestions", SUGGESTIONS),
                                    ("manifests", MANIFESTS), ("out", OUT),
                                    ("data", DATA_DIR), ("rubric", RUBRIC))
            if _outside_book(p)}

# ---------------------------------------------------------------- identity
TITLE = str(_BOOK.get("title", "Untitled"))
SUBTITLE = str(_BOOK.get("subtitle", ""))
AUTHOR = str(_BOOK.get("author", ""))
# a human page-title: "Title — Subtitle" when a subtitle exists.
FULL_TITLE = f"{TITLE} — {SUBTITLE}" if SUBTITLE else TITLE
# The same three, escaped for HTML. The plain values stay for non-HTML consumers
# (pandoc -V title=…, the export filename); anything writing markup uses
# these, since a title is just text from book.toml and may contain < > & ".
TITLE_HTML = _html.escape(TITLE)
SUBTITLE_HTML = _html.escape(SUBTITLE)
AUTHOR_HTML = _html.escape(AUTHOR)
FULL_TITLE_HTML = _html.escape(FULL_TITLE)
# A short machine name for this book: defaults to its directory name. Used to
# namespace browser localStorage keys and git commit messages, so two books
# opened in the same browser never share each other's drafts or overrides.
# Pinned to a plain identifier: it is substituted into JS string literals in the
# static pages, where a quote would end the string.
SLUG = str(_BOOK.get("slug") or BOOK_DIR.name)
SAFE_SLUG = re.sub(r"[^A-Za-z0-9._-]+", "-", SLUG).strip("-") or "book"

# ---------------------------------------------------------------- views
# Which nav pages to show. Empty/absent => all views (data-driven ones simply
# render empty when their data file is missing).
ENABLED_VIEWS = list(_VIEWS.get("enabled", [])) or None  # None == "all"

# ---------------------------------------------------------------- look
# Which of the two shipped themes a page is BUILT with. The reader can flip it in
# the browser (the choice is stored per book and applied in <head>, see
# nav.THEME_BOOT), so this only decides what a first visit sees:
#   localStorage (per book) → book.toml [book] theme → "vapor"
# A book that wants to open as paper for everyone sets it in book.toml, which
# travels with the book; flipping the top-bar toggle is browser-local.
_THEMES = ("vapor", "paper")
THEME = _t if (_t := str(_BOOK.get("theme", "vapor")).strip().lower()) in _THEMES else "vapor"

# stable hex palette; label default-color is a deterministic function of text.
_DEFAULT_PALETTE = ["#b8860b", "#c0392b", "#1f8a70", "#7d3c98", "#2874a6",
                    "#a04000", "#16846b", "#8e6f3e", "#5b2c6f", "#a93226"]
PALETTE = [safe_color(c, _DEFAULT_PALETTE[i % len(_DEFAULT_PALETTE)])
           for i, c in enumerate(_BOOK.get("palette") or _DEFAULT_PALETTE)]

# ---------------------------------------------------------------- pdf
# `pal pdf` renders the manuscript via pandoc + XeLaTeX. All optional:
#   header       LaTeX header (fonts/typography); defaults to the bundled one
#   front_matter a markdown file printed before the sections (title page, epigraph)
#   main_font / mono_font  override the header's fonts (for non-macOS machines)
def pdf_header():
    """Path to the LaTeX header, or None to use the engine's bundled default.

    Resolution: the book's `[pdf] header` wins; else the `PAL_PDF_HEADER` env var
    (how the Linux container points XeLaTeX at a font stack that exists there);
    else None → build_book uses the bundled macOS default."""
    h = _PDF.get("header")
    if h:
        p = _path(h, "")
        if _outside_book(p) and not ALLOW_EXTERNAL_PATHS:
            raise ConfigError(
                f"this book's [pdf] header points outside the book ({p}). A LaTeX "
                "header runs with your permissions and can pull in any file you can "
                "read, so it is refused by default — move it into the book, or set "
                "PAL_ALLOW_EXTERNAL_PATHS=1 if you wrote it yourself.")
        return str(p)
    env = os.environ.get("PAL_PDF_HEADER")
    if env and Path(env).is_file():
        return env
    return None


def pdf_front_matter():
    """Path to an optional front-matter .md printed before the sections, or None."""
    fm = _PDF.get("front_matter")
    if not fm:
        return None
    p = _path(fm, "")
    return str(p) if p.is_file() else None


PDF_MAIN_FONT = str(_PDF.get("main_font", ""))     # "" => header's default
PDF_MONO_FONT = str(_PDF.get("mono_font", ""))


# ---------------------------------------------------------------- data loaders
def _data(name, default):
    """Load `data/<name>.json`; return `default` if absent or unparseable."""
    f = Path(DATA_DIR) / f"{name}.json"
    if f.is_file():
        try:
            with open(f, encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return default
    return default


def _motifs_doc():
    return _data("motifs", {})


def motifs():
    """[{name, color, sections}] — the threads you've named, and where each appears.

    Accepts list-of-dicts or the list-of-lists form in motifs.json. `turns` is read
    as a synonym for `sections`, so a file written before the rename still loads."""
    out = []
    for m in _motifs_doc().get("motifs", []):
        if isinstance(m, dict):
            name, color = m.get("name", ""), m.get("color")
            secs = m.get("sections", m.get("turns", []))
        elif isinstance(m, (list, tuple)) and len(m) >= 4:
            name, color, secs = m[0], m[2], m[3]       # the list-of-lists form
        else:
            continue
        if name:
            out.append({"name": str(name), "color": safe_color(color, "#888"),
                        "sections": [int(s) for s in secs if str(s).strip().lstrip("-").isdigit()]})
    return out




def view_enabled(key) -> bool:
    return ENABLED_VIEWS is None or key in ENABLED_VIEWS


def ensure_out() -> str:
    Path(OUT).mkdir(parents=True, exist_ok=True)
    return OUT
