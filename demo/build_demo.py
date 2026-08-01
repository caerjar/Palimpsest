#!/usr/bin/env python3
"""Build the standalone Writing Record demo — one self-contained HTML file.

The demo page IS `palimpsest/engine/assets/writing-record.html`. This script
takes that page, fills the placeholders the dossier build would normally fill,
inlines style.css + pal.js + the demo chrome, bakes one recorded session into
the markup, and appends demo/autopilot.js, which loads the session and plays
the controls. Nothing is forked: fix the real page and rebuild the demo.

    python3 demo/build_demo.py                     # -> docs/index.html
    python3 demo/build_demo.py --session x.jsonl --out /tmp/x.html

The default target is `docs/index.html` because that is what GitHub Pages
serves (main branch, /docs folder) — the published page and the local one are
the same build, so there is nothing to keep in sync.

Stdlib only, like the rest of the tool.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
ASSETS = ROOT / "palimpsest" / "engine" / "assets"

REPO = "https://github.com/caerjar/Palimpsest"
NS = "paldemo"          # localStorage namespace — never collides with a real book
THEME = "vapor"         # the score art was drawn for the neon look

HEAD = (
    '<!DOCTYPE html>'
    f'<html lang="en" data-theme="{THEME}" data-ns="{NS}">'
    '<head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width, initial-scale=1">'
    '<meta name="description" content="A recorded writing session, replayed as notation '
    'and played back by a synthesizer — a live demo of Palimpsest\'s Writing Record.">'
    # same theme boot as nav.THEME_BOOT: apply the stored look before layout
    "<script>(function(d){try{"
    "var t=localStorage.getItem('pal:'+d.dataset.ns+':theme');"
    "if(t==='paper'||t==='vapor')d.dataset.theme=t;"
    "}catch(e){}})(document.documentElement)</script>"
)

# A demo has no book behind it, so no dossier links and no Export/Rebuild (those
# need `pal serve`). The theme toggle is real — pal.js wires it.
NAV = (
    '<div class="topbar">'
    f'<a class="brand" href="{REPO}" title="Palimpsest on GitHub">Palimpsest</a>'
    '<nav class="toc"><span class="navlink here">Writing Record</span>'
    '<span class="navlink" style="color:var(--gold);cursor:default">demo</span></nav>'
    '<button class="palbtn paltheme" data-pal="theme" aria-pressed="false" '
    'title="switch the look — vapor or paper">'
    '<span class="tg">◐</span><span class="tl">Vapor</span></button>'
    '</div>'
)

FOOTER = (
    '<footer>A live demo of <a href="' + REPO + '">Palimpsest</a> — a book-agnostic '
    'manuscript workbench. This is the real Writing Record page with one recorded '
    'session baked in. Everything runs in this browser: no server, no network, no model. '
    'In the app the sessions are your own, written to <code>keystrokes/</code> as you type.'
    '</footer>'
)

SUB = (
    '<p class="sub">Every keystroke, its speed, every deletion and pause — the prose caught '
    'in the act of being made. Visualized, and sung back. <b>This page plays one session for '
    'you and turns the dials as it goes; switch off <i>autopilot</i> at any point and the '
    'controls are yours.</b></p>'
)


def read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except OSError as e:
        sys.exit(f"build_demo: cannot read {p} — {e}")


def _gone(what: str) -> None:
    sys.exit(f"build_demo: expected {what} in writing-record.html — the page moved on; "
             f"update this script")


def sub_once(text: str, old: str, new: str, what: str) -> str:
    if old not in text:
        _gone(what)
    return text.replace(old, new, 1)


def sub_re(text: str, pattern: str, new: str, what: str) -> str:
    """Replace one match, literally — the replacement is HTML, never a template."""
    out, n = re.subn(pattern, lambda m: new, text, count=1, flags=re.S)
    if not n:
        _gone(what)
    return out


def build(session: Path, out: Path) -> None:
    page = read(ASSETS / "writing-record.html")
    css = read(ASSETS / "style.css") + "\n" + read(HERE / "demo.css")
    paljs = read(ASSETS / "pal.js")
    autopilot = read(HERE / "autopilot.js")
    jsonl = read(session)

    # A raw-text <script> ends only at "</script"; "\/" is a legal JSON escape, so
    # this is lossless for the data even in the pathological case.
    jsonl = re.sub(r"</(script)", r"<\\/\1", jsonl, flags=re.I)
    name = re.sub(r"[^\w.-]", "_", session.stem.replace("writing-", ""))

    page = sub_once(page, "__PAL_HEAD__", HEAD, "the head placeholder")
    page = sub_once(page, '<link rel="stylesheet" href="style.css">',
                    "<style>\n" + css + "\n</style>", "the stylesheet link")
    page = sub_once(page, "__PAL_NAV__", NAV, "the nav placeholder")
    page = sub_once(page, "<body>", f'<body data-demo-session="{name}">', "the body tag")
    page = sub_re(page, r'<p class="sub">.*?</p>', SUB, "the standfirst")
    page = sub_re(page, r"<footer>.*?</footer>", FOOTER, "the footer")
    page = page.replace("__PAL_TITLE__", "Palimpsest").replace("__PAL_NS__", NS)

    page = sub_once(
        page, '<script src="pal.js"></script>',
        "<script>\n" + paljs + "\n</script>\n"
        + '<script id="demo-session" type="application/x-ndjson">\n' + jsonl + "\n</script>\n"
        + "<script>\n" + autopilot + "\n</script>",
        "the pal.js include")

    left = [m for m in re.findall(r"__PAL_\w+__", page)]
    if left:
        sys.exit(f"build_demo: unfilled placeholders remain: {sorted(set(left))}")

    out.parent.mkdir(parents=True, exist_ok=True)
    # Pages runs Jekyll over the branch unless told not to; the demo is one flat
    # file and wants no processing at all.
    if out.parent.name == "docs":
        (out.parent / ".nojekyll").touch()
    out.write_text(page, encoding="utf-8")
    kb = len(page.encode()) / 1024
    events = sum(1 for line in jsonl.splitlines() if line.strip())
    print(f"wrote {out}  ({kb:.0f} KB, {events} events from {session.name})")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--session", type=Path, default=HERE / "session.jsonl",
                    help="the writing-*.jsonl to bake in (default: demo/session.jsonl)")
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "index.html",
                    help="where to write the standalone page (default: docs/index.html, "
                         "which is what GitHub Pages serves)")
    a = ap.parse_args()
    build(a.session, a.out)


if __name__ == "__main__":
    main()
