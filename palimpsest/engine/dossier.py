"""Build a book's dossier — the ONE build path shared by the `pal build` CLI and the
save server, so a book made in the browser is byte-for-byte what `pal build` makes.

Lives in the engine (flat-importable with the rest of engine/ on PYTHONPATH) so both
callers reach it the same way. It runs each view builder as a subprocess, and copies
the shared assets and the hand-written static pages, filling their nav placeholders so
their top bar can never drift.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parent
BUILDERS = ENGINE / "builders"
ASSETS = ENGINE / "assets"

# view-key -> builder script. Order matters: sectionsjson feeds writing-record;
# index aggregates the entity sidecars. Keys match nav.py.
REGISTRY = [
    ("reading",         "build_reading_copy.py"),
    ("motifs",          "build_motifs.py"),
    ("record",          "build_sections_json.py"),
    ("copyedit",        "build_copyedit_review.py"),
    ("parts",           "build_parts_board.py"),
    ("index",           "build_entity_index.py"),
    ("board",           "build_edit_board.py"),
]
# static (hand-written) pages copied verbatim into the dossier
STATIC_PAGES = ["writing-record.html", "library.html", "help.html"]


def child_python() -> str:
    """The interpreter to spawn builders with. Normally sys.executable — but inside
    a py2app .app that's the app binary (re-running it relaunches the app), so use
    the real `python` py2app ships beside it in Contents/MacOS."""
    exe = Path(sys.executable)
    if exe.name.lower().startswith("python"):
        return str(exe)
    for name in ("python", "python3"):
        sib = exe.with_name(name)
        if sib.exists():
            return str(sib)
    return str(exe)


def run_builder(script, book_dir, out, timeout=None, capture=False):
    """Run one view builder against `book_dir`, writing into `out`.

    Returns the CompletedProcess — check `.returncode`. This is the only place a
    builder is spawned: the save server calls it too (through a thin binding that
    supplies its own book and dossier), so an incremental rebuild in the browser
    runs the same command as `pal build`.

    `capture` keeps a builder's chatter off the caller's stdout — the server wants
    that, the CLI wants the progress lines.
    """
    env = dict(os.environ)
    env["PAL_BOOK"] = str(book_dir)
    env["PYTHONPATH"] = str(ENGINE) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run([child_python(), str(BUILDERS / script)],
                          cwd=str(out), env=env, timeout=timeout,
                          capture_output=capture, text=True)


def _config_for(book_dir):
    """Import engine config bound to `book_dir` (dropping any cached bind first), and
    a matching fresh nav. Returns (config_module, nav_module)."""
    import importlib
    if str(ENGINE) not in sys.path:
        sys.path.insert(0, str(ENGINE))
    os.environ["PAL_BOOK"] = str(book_dir)
    for m in ("config", "sections", "nav"):
        sys.modules.pop(m, None)          # config caches at import; force a fresh resolve
    cfg = importlib.import_module("config")
    nav = importlib.import_module("nav")  # imported after the pop → binds to fresh config
    return cfg, nav


def build(book_dir, wanted=None, log=None):
    """Build `book_dir`'s dossier. `wanted` limits to those view keys (None = all
    enabled). Returns (ok_count, fail_count, out_dir, title). `log` gets per-failure
    lines if given."""
    book_dir = Path(book_dir)
    cfg, nav = _config_for(book_dir)
    out = Path(cfg.ensure_out())
    # shared assets first, so freshly-built HTML always has its CSS + JS
    shutil.copy2(ASSETS / "style.css", out / "style.css")
    shutil.copy2(ASSETS / "pal.js", out / "pal.js")
    # static pages carry a __PAL_NAV__ placeholder we fill with the same sticky top
    # bar the builders render, so their nav can never drift from the generated pages.
    # Title and subtitle land in markup and the slug lands inside JS string
    # literals, so both go in pre-pinned (config escapes / normalizes them) — a
    # book.toml is just text, and may not have been written here.
    for pg in STATIC_PAGES:
        src = ASSETS / pg
        if src.is_file():
            (out / pg).write_text(
                src.read_text(encoding="utf-8")
                   # doctype + themed <html> + metas + theme boot script; each page
                   # keeps its own <title> and stylesheet link on the lines below it
                   .replace("__PAL_HEAD__", nav.html_open())
                   .replace("__PAL_NAV__", nav.topbar_html(pg))
                   .replace("__PAL_TITLE__", cfg.TITLE_HTML)
                   .replace("__PAL_SUBTITLE__", cfg.SUBTITLE_HTML)
                   .replace("__PAL_NS__", cfg.SAFE_SLUG),
                encoding="utf-8")
    # The reading copy is home. Nothing writes index.html any more, and without one a
    # bare GET / falls through to the server's directory listing — so point it home.
    (out / "index.html").write_text(
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        '<meta http-equiv="refresh" content="0; url=reading-copy.html">'
        '<title>' + cfg.TITLE_HTML + '</title></head>'
        '<body><a href="reading-copy.html">reading copy</a></body></html>',
        encoding="utf-8")
    todo = [(k, s) for (k, s) in REGISTRY
            if cfg.view_enabled(k) and (not wanted or k in wanted)]
    ok = fail = 0
    for key, script in todo:
        if run_builder(script, book_dir, out).returncode == 0:
            ok += 1
        else:
            fail += 1
            if log:
                log(f"  ✗ {key} ({script}) failed")
    return ok, fail, out, cfg.TITLE
