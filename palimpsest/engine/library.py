"""The library: the set of books in this workbench, and how to make a new one.

Shared by the `pal` CLI and the edit/save server so "new book" and "switch book"
mean exactly the same thing whether you type them or click them.

A **workbench** is the directory that holds your books, one folder each. Where it
lives is resolved once, in this order:
  1. $PAL_HOME                                    (explicit override)
  2. a stored setting (~/Library/Application Support/Palimpsest/config.json)
  3. the repo's own books/ dir            (a dev checkout — detected by a
                                           pyproject.toml above the package)
  4. ~/Documents/Palimpsest             (a fresh install's default)
So a developer running from the checkout keeps using ./books, while an installed
app keeps books in a writable, user-chosen place (the bundle itself is read-only).
The **template** a new book is copied from always ships inside the package
(palimpsest/_template), not in the workbench, so an empty workbench still knows
how to make a book.
"""
import json
import os
import re
import shutil
import tomllib
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent       # the palimpsest/ package dir
# In a py2app .app the template is shipped as a bundle resource (real files), while
# this module may be imported from a zip; if PKG/_template isn't a real dir, fall
# back to Contents/Resources where the bundle keeps it.
if not (PKG / "_template").is_dir():
    import sys as _sys
    _res = Path(_sys.executable).resolve().parent.parent / "Resources"
    if (_res / "_template").is_dir():
        PKG = _res
TEMPLATE = PKG / "_template"                        # always ships with the code
DEFAULT_HOME = Path.home() / "Documents" / "Palimpsest"

# A source checkout has a pyproject.toml one level above the package; an installed
# wheel (site-packages) or a py2app bundle does not. In a checkout we keep books
# in the repo's ./books; installed, they live in the user's Documents.
_REPO_ROOT = PKG.parent
_IS_DEV = (_REPO_ROOT / "pyproject.toml").is_file()


class LibraryError(RuntimeError):
    pass


def config_path() -> Path:
    return Path.home() / "Library" / "Application Support" / "Palimpsest" / "config.json"


def _stored_home():
    try:
        with open(config_path(), encoding="utf-8") as fh:
            v = json.load(fh).get("home")
        return Path(v).expanduser() if v else None
    except Exception:
        return None


def _resolve_home() -> Path:
    env = os.environ.get("PAL_HOME")
    if env:
        return Path(env).expanduser().resolve()
    stored = _stored_home()
    if stored:
        return stored.resolve()
    if _IS_DEV:                                     # source checkout: keep using ./books
        return (_REPO_ROOT / "books").resolve()
    return DEFAULT_HOME.resolve()


BOOKS = _resolve_home()


def home() -> Path:
    """The active workbench directory (where books live)."""
    return BOOKS


def set_home(path) -> Path:
    """Point the workbench at `path` (created if needed) and remember the choice.

    Takes effect for new CLI invocations immediately; a running server picks it up
    on its next restart. Returns the resolved directory."""
    global BOOKS
    d = Path(str(path)).expanduser().resolve()
    d.mkdir(parents=True, exist_ok=True)
    cp = config_path()
    cp.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    try:
        with open(cp, encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        pass
    data["home"] = str(d)
    cp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    BOOKS = d
    return d


def slugify(text: str) -> str:
    """A directory-safe name: lowercase, alphanumerics and dashes, nothing else.

    Capped at 80 characters — a slug is a folder name, and a long title (or a
    string that was really a path) shouldn't produce one the filesystem refuses."""
    s = re.sub(r"[^a-z0-9]+", "-", str(text).strip().lower()).strip("-")
    return s[:80].strip("-") or "book"


def _title_of(d: Path) -> str:
    try:
        with open(d / "book.toml", "rb") as fh:
            return str(tomllib.load(fh).get("book", {}).get("title", "")) or d.name
    except Exception:
        return d.name


def _sections_in(d: Path) -> int:
    try:
        with open(d / "book.toml", "rb") as fh:
            man = tomllib.load(fh).get("book", {}).get("manuscript", "manuscript")
    except Exception:
        man = "manuscript"
    p = Path(man)
    p = p if p.is_absolute() else d / p
    try:
        return len([x for x in p.glob("[0-9]*.md")])
    except OSError:
        return 0


def book_dirs():
    """Every book directory in the workbench, name-sorted."""
    if not BOOKS.is_dir():
        return []
    return sorted((d for d in BOOKS.iterdir()
                   if d.is_dir() and not d.name.startswith("_")
                   and (d / "book.toml").is_file()),
                  key=lambda d: d.name)


def books():
    """[{slug, title, dir, sections, built}] — everything a picker needs."""
    return [{"slug": d.name,
             "title": _title_of(d),
             "dir": str(d),
             "sections": _sections_in(d),
             "built": (d / "dossier" / "reading-copy.html").is_file()}
            for d in book_dirs()]


def find(spec):
    """Resolve a book by bare name (books/<spec>) or by path. None if neither.

    Accepts a path anywhere on disk, which is right for the CLI (`pal --book
    ../elsewhere build`) and wrong for anything driven by the browser — use
    find_slug() there."""
    spec = str(spec or "").strip()
    if not spec:
        return None
    if "/" not in spec and (BOOKS / spec / "book.toml").is_file():
        return (BOOKS / spec).resolve()
    p = Path(spec).expanduser().resolve()
    return p if (p / "book.toml").is_file() else None


def find_slug(spec):
    """Resolve a book **inside this workbench** by its directory name. None otherwise.

    The strict half of find(): no paths, no traversal, nothing outside BOOKS. The
    server uses this because its callers are web requests — a request that can name
    any directory on disk can open or bin any directory on disk."""
    slug = str(spec or "").strip()
    if not slug or slug != os.path.basename(slug) or slug in (".", ".."):
        return None
    d = (BOOKS / slug).resolve()
    if d.parent != BOOKS.resolve() or not (d / "book.toml").is_file():
        return None
    return d


def delete(spec) -> Path:
    """Remove a book — safely. The book is MOVED into the workbench's `.trash/`
    (never erased), so it can be restored by moving it back. Returns the trash path.

    `.trash/` starts with a dot, so book_dirs() never lists it — a trashed book
    just disappears from the Library."""
    import datetime
    d = find(spec)
    if not d:
        raise LibraryError(f"{spec!r} is not a book")
    trash = home() / ".trash"
    trash.mkdir(parents=True, exist_ok=True)
    dest = trash / f"{d.name}-{datetime.datetime.now().strftime('%H%M%S')}"
    if dest.exists():                       # extremely unlikely collision within a second
        dest = trash / f"{d.name}-{datetime.datetime.now().strftime('%H%M%S%f')}"
    shutil.move(str(d), str(dest))
    return dest


def create(name, title=None, author=None, allow_path=False) -> Path:
    """Create a book from the template and fill in its identity.

    A bare `name` becomes books/<slug>. A name containing a "/" is a path, so the
    book can live outside the workbench — that is a CLI convenience (`pal new
    ~/writing/novel`), and callers must ask for it with allow_path=True. It stays
    off by default because the server creates books from request bodies, where a
    path would mean "write into any directory the user can write to"."""
    name = str(name or "").strip()
    if not name:
        raise LibraryError("a book needs a name")
    if ("/" in name or "\\" in name or name.startswith("~")) and not allow_path:
        raise LibraryError(
            "a book name can't contain a path — give it a plain name "
            "(use `pal new <path>` on the command line to put a book elsewhere)")
    if "/" in name:
        d = Path(name).expanduser().resolve()
        title = title or d.name
    else:
        title = title or name
        BOOKS.mkdir(parents=True, exist_ok=True)     # fresh workbench: create on first book
        d = BOOKS / slugify(name)
    if d.exists() and any(d.iterdir()):
        raise LibraryError(f"{d.name!r} already exists and is not empty")
    if not (TEMPLATE / "book.toml").is_file():
        raise LibraryError(f"the book template is missing at {TEMPLATE}")

    shutil.copytree(TEMPLATE, d)
    toml = d / "book.toml"
    toml.write_text(toml.read_text(encoding="utf-8")
                        .replace("__TITLE__", str(title).replace('"', "'"))
                        .replace("__AUTHOR__", str(author or "").replace('"', "'")),
                    encoding="utf-8")
    for keep in (d / "manifests" / ".gitkeep", d / "data" / ".gitkeep"):
        keep.unlink(missing_ok=True)
    return d
