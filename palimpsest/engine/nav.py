"""Canonical navigation for a Palimpsest dossier — one source of truth.

Every generated page renders topbar_html('<thispage>.html'): a sticky bar with the
book's title, the shared menu bar, and the Export / Rebuild actions (wired by the
shared pal.js). Reading copy is the hub/home. The roster below is the full set of
pages; a book's book.toml `[views] enabled` list controls which of them appear
(config.view_enabled), and a dropdown whose items are all disabled is dropped."""
import html as _html
import json as _json

import config


def script_json(obj) -> str:
    """JSON for embedding inside a <script> block. Use this, never a bare dumps().

    json.dumps does not escape "/", so a string value containing "</script>" ends
    the tag early and everything after it is parsed as markup. Authored text
    reaches these embeds — section labels, part titles, motif names, index terms,
    board items — so the guard is not optional. Rewriting "</" to "<\\/" is inert
    inside a JS string literal and produces the identical value at runtime.
    """
    return _json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")

# A conventional menu bar: a home link, a couple of grouped dropdowns, and a few
# top-level links. Each entry is either a direct link or a dropdown of links.
# view-keys gate visibility (config.view_enabled); a dropdown with nothing enabled
# is dropped entirely rather than rendering empty.
NAV = [
    {"kind": "link", "href": "reading-copy.html", "label": "Reading copy", "key": "reading", "home": True},
    {"kind": "menu", "label": "Read", "items": [
        ("parts-board.html",     "Parts board",     "parts"),
        ("copyedit-review.html", "Copyedit review", "copyedit"),
        ("writing-record.html",  "Writing record",  "record"),
    ]},
    {"kind": "link", "href": "index-terms.html", "label": "Index",      "key": "index"},
    {"kind": "link", "href": "motifs.html",      "label": "Motifs",     "key": "motifs"},
    {"kind": "link", "href": "edit-board.html",  "label": "Edit board", "key": "board"},
    # always available: the library is how you reach the other books / make a new one
    {"kind": "link", "href": "library.html",    "label": "Library",    "key": None},
    {"kind": "link", "href": "help.html",       "label": "Help",       "key": None},
]

HOME = "⌂ "   # ⌂ prefix on the reading-copy link

# The look is one attribute on <html> (see the token block in style.css), so
# switching themes costs no rebuild and no redraw. This script runs in <head>,
# before any body layout, so a stored preference is applied without a flash of
# the other theme — and because the build-time default is already correct in the
# markup, the common case does no work at all. The whitelist stops a corrupted
# localStorage value producing a page with no tokens.
#
# data-ns carries the book slug into the DOM. That is how pal.js learns which
# book it is in: dossier.build() copies pal.js byte-for-byte (shutil.copy2), so
# unlike the generated pages it can never be templated.
THEME_BOOT = ("<script>(function(d){try{"
              "var t=localStorage.getItem('pal:'+d.dataset.ns+':theme');"
              "if(t==='paper'||t==='vapor')d.dataset.theme=t;"
              "}catch(e){}})(document.documentElement)</script>")


def _enabled(key):
    return key is None or config.view_enabled(key)


def html_open():
    """Everything before a page's own <title>: doctype, the themed <html>, the
    meta tags, the theme boot script.

    Split out of page_head() so the three hand-written static pages — which keep
    their own <title> where it is authored — get the theme hook from the same
    place the generated pages do. Both values interpolated here are safe in an
    attribute: THEME comes from a whitelist and SAFE_SLUG is scrubbed to
    [A-Za-z0-9._-] (config.py)."""
    return (
        '<!DOCTYPE html>'
        f'<html lang="en" data-theme="{config.THEME}" data-ns="{config.SAFE_SLUG}">'
        '<head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        + THEME_BOOT)


def page_head(title):
    """The shared <head> opening every dossier page uses: doctype, meta, <title>,
    the stylesheet link. Centralized so this boilerplate lives in one place; each
    builder appends its own <style> (if any) then </head><body><div class="wrap">."""
    return (html_open()
            + f'<title>{_html.escape(str(title))}</title>'
            + '<link rel="stylesheet" href="style.css">')


def topbar_html(current=None):
    """The sticky top bar every page shares: title (→ reading copy), the menu bar,
    and the Export / Rebuild actions. The actions are wired by pal.js, which hides
    them when the page is opened as a file rather than through `pal serve`."""
    title = _html.escape(config.TITLE)
    return (
        '<div class="topbar">'
        f'<a class="brand" href="reading-copy.html" title="{title} — reading copy">{title}</a>'
        + nav_html(current) +
        # The theme toggle sits OUTSIDE .topacts on purpose: pal.js keeps .topacts
        # hidden unless the page is served, and the look must be switchable even
        # when the dossier is opened as a plain file. pal.js corrects the label and
        # aria-pressed on load to match whichever theme is actually active.
        '<button class="palbtn paltheme" data-pal="theme" aria-pressed="false" '
        'title="switch the look — vapor or paper">'
        '<span class="tg">◐</span><span class="tl">Vapor</span></button>'
        '<div class="topacts" hidden>'
        '<div class="palexport">'
        '<button class="palbtn" data-pal="export-menu" aria-haspopup="menu" aria-expanded="false" '
        'title="download the whole book"><span>⤓ Export</span><span class="caret">▾</span></button>'
        '<div class="palmenu" role="menu" hidden>'
        '<button class="palitem" role="menuitem" data-fmt="pdf" title="needs pandoc + XeLaTeX">PDF</button>'
        '<button class="palitem" role="menuitem" data-fmt="docx" title="Word — needs pandoc (no LaTeX)">Word (.docx)</button>'
        '<button class="palitem" role="menuitem" data-fmt="html">Web page (.html)</button>'
        '<button class="palitem" role="menuitem" data-fmt="md">Markdown (.md)</button>'
        '</div></div>'
        '<button class="palbtn" data-pal="rebuild" title="rebuild the reading pages from your latest edits">↻ Rebuild</button>'
        '<span class="palmsg" id="palmsg"></span>'
        '</div>'
        '</div>')


def nav_html(current=None):
    """The shared menu bar: home link, grouped dropdowns, top-level links. Marks the
    current page (and its parent menu) active. Dropdowns are opened by pal.js."""
    out = ['<nav class="toc">']
    for item in NAV:
        if item["kind"] == "link":
            if not _enabled(item.get("key")):
                continue
            here = " here" if current == item["href"] else ""
            home = HOME if item.get("home") else ""
            out.append(f'<a class="navlink{here}" href="{item["href"]}">{home}{_html.escape(item["label"])}</a>')
        else:  # dropdown menu
            items = [(h, l, k) for (h, l, k) in item["items"] if config.view_enabled(k)]
            if not items:
                continue
            active = any(current == h for h, _, _ in items)
            rows = "".join(
                f'<a class="navitem{" here" if current == h else ""}" role="menuitem" href="{h}">{_html.escape(l)}</a>'
                for h, l, _ in items)
            out.append(
                '<div class="navdrop">'
                f'<button class="navdrop-btn{" here" if active else ""}" aria-haspopup="menu" aria-expanded="false">'
                f'{_html.escape(item["label"])} <span class="caret">▾</span></button>'
                f'<div class="navdrop-menu" role="menu" hidden>{rows}</div>'
                '</div>')
    out.append('</nav>')
    out.append(build_stamp())
    return "".join(out)


def build_stamp():
    """A small fixed-corner 'built HH:MM' badge so a stale browser tab is obvious at a
    glance. Reflects when this page was generated (nav_html is called once per build)."""
    import datetime
    t = datetime.datetime.now().strftime("%H:%M")
    # styled by .buildstamp in style.css — keep the colours there, not inline, or it
    # stops following the theme
    return ('<div class="buildstamp" title="when this page was generated — reload if it looks old"'
            '>built ' + t + '</div>')
