"""pal — Palimpsest: a book-agnostic manuscript workbench.

Point it at a book (a directory containing a book.toml) and it builds an
set of HTML views over the manuscript: reading copy, motifs, parts board,
copyedit review, back-of-book index.

    pal new <name>       start a new book in the workbench (or at a path you give)
    pal books            list the books in this workbench
    pal home [<dir>]     show, or set, where your books live
    pal build [views]    build the dossier (default: all enabled views)
    pal serve            edit/save server (write sections in the browser)
                         --verbose  request log + the detail behind failed writes
    pal pdf              export the book as a PDF (pandoc + XeLaTeX)
    pal export -f docx   export as Word (pandoc only) — also html, md (no tools)
    pal list             list buildable views for the active book
    pal open             open the dossier in a browser
    pal --version        print the installed version

Every command except `new`/`books` runs against one active book, resolved in
this order: `pal --book <name-or-dir>`, then $PAL_BOOK, then the nearest book.toml
walking up from the current directory. So both of these work:

    pal --book my-novel build         # from anywhere in the workbench
    cd books/my-novel && pal build    # from inside the book
"""
import os
import sys
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent          # the installed package dir
# Inside a py2app .app, this module is imported from a zip, so HERE/engine isn't a
# real directory — the engine and template are shipped as bundle resources instead
# (see packaging/setup_app.py). Resolve to Contents/Resources in that case.
if not (HERE / "engine").is_dir():
    _res = Path(sys.executable).resolve().parent.parent / "Resources"
    if (_res / "engine").is_dir():
        HERE = _res
ENGINE = HERE / "engine"
BUILDERS = ENGINE / "builders"
ASSETS = ENGINE / "assets"
TEMPLATE = HERE / "_template"                    # ships with the package / in the bundle


def _bundle_tools_on_path():
    """When running inside a macOS .app (py2app), pandoc is bundled at
    Contents/Resources/bin. Nothing sets that on PATH for us, so subprocesses'
    shutil.which('pandoc') would miss it — prepend it here. A no-op everywhere
    else (the directory simply doesn't exist), so it's safe to always call."""
    try:
        res_bin = Path(sys.executable).resolve().parent.parent / "Resources" / "bin"
    except Exception:
        return
    if res_bin.is_dir() and str(res_bin) not in os.environ.get("PATH", "").split(os.pathsep):
        os.environ["PATH"] = str(res_bin) + os.pathsep + os.environ.get("PATH", "")


def _books_dir():
    """The active workbench directory, resolved by the library (PAL_HOME-aware)."""
    return library().home()


def reveal(path):
    """Open a file in the OS viewer where that's meaningful (macOS `open`,
    Linux `xdg-open`). A no-op in a container / headless box — the CLI already
    printed the path, so nothing is lost."""
    if os.environ.get("PAL_NO_BROWSER"):
        return
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    if shutil.which(opener):
        try:
            subprocess.run([opener, str(path)], check=False)
        except Exception:
            pass

def die(msg, code=1):
    print(f"pal: {msg}", file=sys.stderr)
    sys.exit(code)


def _engine(name):
    """Import a flat engine module (engine/*.py) with ENGINE on sys.path — the same
    way the builder subprocesses and the server reach these modules."""
    import importlib
    if str(ENGINE) not in sys.path:
        sys.path.insert(0, str(ENGINE))
    return importlib.import_module(name)


def library():
    """The shared library module (engine/library.py) — same code the server uses."""
    return _engine("library")


def _as_book(spec: str):
    return library().find(spec)


def _book_menu():
    names = [b["slug"] for b in library().books()]
    return ("known books: " + ", ".join(names)) if names else \
           "this workbench has no books yet — start one with `pal new <name>`"


def resolve_book(explicit=None) -> Path:
    if explicit:
        return _as_book(explicit) or die(
            f"{explicit!r} is not a book (no book.toml) — {_book_menu()}")
    env = os.environ.get("PAL_BOOK")
    if env:
        return _as_book(env) or die(f"$PAL_BOOK={env!r} has no book.toml")
    for d in (Path.cwd().resolve(), *Path.cwd().resolve().parents):
        if (d / "book.toml").is_file():
            return d
    return _workbench_default()   # nothing named & not inside a book → the workbench


def _book_mtime(d: Path) -> float:
    """Best 'most recently worked on' signal: newest manuscript file mtime, falling
    back to the book directory's own mtime."""
    man = d / "manuscript"
    times = [p.stat().st_mtime for p in man.glob("*.md")] if man.is_dir() else []
    times.append(d.stat().st_mtime)
    return max(times)


def _workbench_default() -> Path:
    """No book named, not inside one, no $PAL_BOOK — fall back to the workbench so a
    bare `pal serve`/`build`/`open` still does something: open the most-recently-
    worked-on book, or, if the workbench is empty, create a starter and open that."""
    lib = library()
    books = lib.books()
    if books:
        pick = max(books, key=lambda b: _book_mtime(Path(b["dir"])))
        print(f"pal: no book given — using {pick['slug']!r} "
              f"(most recent in {lib.home()}; choose another with --book)", file=sys.stderr)
        return Path(pick["dir"])
    d = lib.create("My Manuscript")
    print(f"pal: empty workbench — created starter {d.name!r} in {lib.home()}",
          file=sys.stderr)
    return d


def book_config(book: Path):
    """Import engine/config.py bound to `book`, returning the module."""
    import importlib
    sys.path.insert(0, str(ENGINE))
    os.environ["PAL_BOOK"] = str(book)
    # config caches at import; drop it so a fresh resolve happens per invocation
    for m in ("config", "sections", "nav"):
        sys.modules.pop(m, None)
    return importlib.import_module("config")


def cmd_build(book: Path, wanted):
    # the actual build lives in engine/dossier.py — the one path the server shares,
    # so a book built here is byte-for-byte what the browser's "rebuild" produces.
    dossier = _engine("dossier")
    if wanted:
        unknown = set(wanted) - {k for k, _ in dossier.REGISTRY}
        if unknown:
            die(f"unknown view(s): {', '.join(sorted(unknown))}. try: pal list")
    ok, fail, out, title = dossier.build(
        book, wanted or None, log=lambda m: print(m, file=sys.stderr))
    # book.toml may point the manuscript/data/output anywhere; that's a feature for
    # your own book and worth flagging for one you were given, since those paths
    # decide what gets read and written.
    outside = _engine("config").external_paths()
    if outside:
        print("pal: this book.toml points outside the book directory — "
              + ", ".join(f"{k}: {v}" for k, v in outside.items()), file=sys.stderr)
    print(f"built {title}: {ok} view(s)" + (f", {fail} failed" if fail else "")
          + f" · open {out}/reading-copy.html")
    return 0 if not fail else 1


def cmd_list(book: Path):
    cfg = book_config(book)
    dossier = _engine("dossier")
    print(f"{cfg.TITLE} — buildable views:")
    for key, script in dossier.REGISTRY:
        mark = "•" if cfg.view_enabled(key) else "·"
        state = "" if cfg.view_enabled(key) else "  (disabled in book.toml)"
        print(f"  {mark} {key:16s} {script}{state}")
    return 0


def cmd_serve(book: Path):
    env = dict(os.environ)
    env["PAL_BOOK"] = str(book)
    env["PYTHONPATH"] = str(ENGINE) + os.pathsep + env.get("PYTHONPATH", "")
    # The server runs as a child, not in place, so a flag on this command line
    # reaches it only if we pass it along — as the environment, which is how it
    # takes all its other settings.
    if "--verbose" in sys.argv or "-v" in sys.argv:
        env["PAL_LOG"] = "debug"
    cfg = book_config(book)
    out = Path(cfg.ensure_out())
    if not (out / "reading-copy.html").is_file():   # never built (e.g. a fresh starter)
        print(f"{cfg.TITLE}: no dossier yet — building it first…")
        cmd_build(book, set())
    # dossier.child_python(), not sys.executable: inside a py2app .app the latter
    # is the app binary, and spawning it relaunches the app.
    return subprocess.run([_engine("dossier").child_python(), str(ENGINE / "save_server.py")],
                          cwd=str(out), env=env).returncode



def cmd_export(book: Path, fmt, opts):
    """Export the manuscript to fmt (pdf | docx | html | md). PDF needs pandoc +
    XeLaTeX; docx needs only pandoc; html/md need nothing."""
    book_config(book)                       # bind the active book for build_book
    if str(ENGINE) not in sys.path:
        sys.path.insert(0, str(ENGINE))
    import importlib
    sys.modules.pop("build_book", None)
    bb = importlib.import_module("build_book")
    try:
        out = bb.build_doc(fmt, part=opts.get("part"), frm=opts.get("from"),
                           to=opts.get("to"), held=opts.get("held", False),
                           deleted=opts.get("deleted", False))
    except RuntimeError as e:
        die(str(e))
    print(f"✓ {out}")
    reveal(out)
    return 0


def cmd_open(book: Path):
    cfg = book_config(book)
    idx = Path(cfg.OUT) / "reading-copy.html"
    if not idx.is_file():                 # never `open` a path that isn't there
        print(f"{cfg.TITLE}: no dossier yet — building it first…")
        cmd_build(book, set())
    if not idx.is_file():
        die(f"still no reading copy at {idx} — `pal --book {book.name} build` "
            f"to see the error")
    reveal(idx)
    return 0


def cmd_books():
    books = library().books()
    if not books:
        print("no books yet — start one with `pal new \"My Book\"`")
        return 0
    print(f"books in {_books_dir()}:")
    for b in books:
        built = "built" if b["built"] else "—"
        print(f"  {b['slug']:20s} {b['title']:28s} {b['sections']:>4} sections  {built}")
    return 0


def cmd_new(name: str, title=None, author=None):
    """Create a book. A bare name lands in books/; a path with a / is used as given."""
    lib = library()
    try:
        # the CLI is the one caller allowed to name a path: `pal new ~/writing/novel`
        d = lib.create(name, title, author, allow_path=True)
    except lib.LibraryError as e:
        die(str(e))
    title = title or (name if "/" not in name else d.name)
    where = d.name if d.parent == _books_dir() else str(d)
    print(f"✓ new book {title!r} at {d}")
    print(f"  1. pal --book {where} serve     — write in the browser, or")
    print(f"     drop your own 001.md, 002.md, … into {d}/manuscript/")
    print(f"  2. pal --book {where} build     — build the dossier")
    return 0


def main(argv):
    _bundle_tools_on_path()          # find pandoc bundled inside a macOS .app, if any
    # optional --book <dir> before the subcommand
    explicit = None
    if len(argv) >= 2 and argv[0] == "--book":
        explicit, argv = argv[1], argv[2:]
    if not argv:
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]

    if cmd in ("--version", "-V", "version"):
        from . import __version__
        print(f"palimpsest {__version__}")
        return 0

    if cmd in ("new", "init"):
        if not rest:
            die('usage: pal new <name> [--title "…"] [--author "…"]')
        opts = {}
        args = []
        it = iter(rest)
        for a in it:
            if a in ("--title", "--author"):
                opts[a[2:]] = next(it, "")
            else:
                args.append(a)
        if not args:
            die('usage: pal new <name> [--title "…"] [--author "…"]')
        return cmd_new(args[0], opts.get("title"), opts.get("author"))
    if cmd == "books":
        return cmd_books()
    if cmd == "home":
        lib = library()
        if rest:                                  # set the workbench location
            d = lib.set_home(rest[0])
            print(f"✓ workbench → {d}")
            print(f"  (saved in {lib.config_path()})")
        else:
            print(f"workbench: {lib.home()}")
        return 0

    book = resolve_book(explicit)
    if cmd == "build":
        return cmd_build(book, set(rest))
    if cmd == "list":
        return cmd_list(book)
    if cmd == "serve":
        return cmd_serve(book)
    if cmd == "open":
        return cmd_open(book)
    if cmd in ("pdf", "export"):
        fmt = "pdf"                              # `pal pdf` = PDF; `pal export -f docx|html|md`
        opts = {}
        it = iter(rest)
        for a in it:
            if a in ("--format", "-f", "--to-format"):
                fmt = (next(it, "") or "").lower()
            elif a in ("--from", "--to", "--part"):
                opts[a[2:]] = next(it, None)
            elif a == "--appendices":
                opts["held"] = opts["deleted"] = True
            elif a == "--held":
                opts["held"] = True
            elif a == "--deleted":
                opts["deleted"] = True
            else:
                die(f"pal {cmd}: unknown option {a!r}")
        if fmt not in ("pdf", "docx", "html", "md"):
            die(f"pal export -f: choose pdf, docx, html, or md (got {fmt!r})")
        for k in ("from", "to"):
            if opts.get(k) is not None:
                try:
                    opts[k] = int(opts[k])
                except ValueError:
                    die(f"pal {cmd}: --{k} wants a number")
        return cmd_export(book, fmt, opts)
    die(f"unknown command {cmd!r}. try: pal (with no args) for help")


def main_cli():
    """Zero-arg entry point for the `pal` console script (see pyproject.toml)."""
    sys.exit(main(sys.argv[1:]))


if __name__ == "__main__":
    main_cli()
