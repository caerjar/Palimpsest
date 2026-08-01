#!/usr/bin/env python3
"""Assemble the active book's manuscript into one markdown file for the PDF.

Each section becomes a small centered scene-number (not a big heading) with a
PDF bookmark, and the prose is cleaned of browser-editing artifacts (non-breaking
spaces, stray interior double-spaces, and [figure: … stubbed] placeholders).
Cleaning happens ONLY here — the source manuscript/NNN.md files are left as-is.
Output: <dossier>/<slug>.book.md (generated; rendered to PDF by `pal pdf`).

Part breaks (manifests/parts.json) become raw \\part* divisions; an author-typed
{{contents}} … {{/contents}} block becomes a centered small-caps contents block.

Optional range (a subset of the positional order — the rest of the book is
omitted, but positional §-numbers stay true to the full book):
  --from N --to M   positional slice, inclusive (1-based)
  --part SUBSTR     everything under the part whose title contains SUBSTR
Optional appendices (out-of-flow material, appended after the book):
  --held            the set-aside sections (held.json)
  --deleted         the deleted sections (manuscript/_attic)
  --extras          both

Nothing here is book-specific: paths, title and slug come from the active book
(config)."""

import argparse, glob, os, re, sys
from types import SimpleNamespace
import config
from sections import section_paths, load_parts, load_unnumbered, held_paths, MAN

OUT_DIR = config.ensure_out()  # generated markdown goes in the dossier
# SAFE_SLUG, not SLUG: these are filenames, and a book.toml slug is just
# text — "../../x" would otherwise write outside the book on every export.
BOOK_MD = os.path.join(OUT_DIR, f"{config.SAFE_SLUG}.book.md")
ATTIC = os.path.join(MAN, "_attic")  # soft-deleted sections (save_server archives here)

FIG = re.compile(r"\[figure:[^\]]*\]")  # editorial placeholder, no art yet
INNER_SPACES = re.compile(r"(?<=\S)[ \t]{2,}(?=\S)")  # runs BETWEEN words (keeps line-end hard breaks)
# author-typed contents block: {{contents}} <lines> {{/contents}}
CONTENTS_RE = re.compile(r"\{\{contents\}\}[ \t]*\n(.*?)\n?[ \t]*\{\{/contents\}\}", re.S)

_LATEX = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def latex_escape(s) -> str:
    return "".join(_LATEX.get(c, c) for c in s)


# A font name is a short identifier ("EB Garamond", "Iosevka Term"), never prose.
# It is written straight into a LaTeX header as \setmainfont{...}, so it is
# rejected rather than escaped: anything that isn't a plain name is a mistake or an
# injection, and silently mangling it into a font XeLaTeX can't find is worse than
# falling back to the default. The header PATH beside this is already refused when
# it points outside the book (config.pdf_header) — same reasoning.
# Rendering budget. /export is an unauthenticated, threaded endpoint with no
# concurrency cap, so an unbounded pandoc/XeLaTeX run is a way to pin the box.
# Generous enough for a full book on slow hardware; a real render that exceeds
# this has gone wrong rather than gotten slow.
RENDER_TIMEOUT = int(os.environ.get("PAL_RENDER_TIMEOUT", "900"))


_FONT_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}$")


def safe_font(name) -> str | None:
    """The font name if it is a plain identifier, else None (use the default)."""
    n = str(name or "").strip()
    return n if n and _FONT_OK.fullmatch(n) else None


def render_contents_latex(inner):
    """A styled, centered contents block from the author's literal lines."""
    lines = [l.strip() for l in inner.splitlines() if l.strip()]
    if not lines:
        return ""
    body = "\\\\[0.5em]\n".join(f"{{\\scshape {latex_escape(l)}}}" for l in lines)
    return (
        "\n\\begin{center}\n\\rule{3em}{0.4pt}\\\\[0.9em]\n"
        f"{body}\\\\[0.9em]\n\\rule{{3em}}{{0.4pt}}\n\\end{{center}}\n"
    )


def clean(body) -> str:
    body = body.replace("\xa0", " ")  # non-breaking space -> normal space
    body = FIG.sub("", body)  # drop stubbed figure markers
    # Neutralise every backslash that could open a LaTeX control word, so XeLaTeX
    # prints it instead of executing it (printf("...\n"), chess "\d.", and also
    # \input{...}, which would otherwise read a file off disk into the PDF —
    # pandoc runs with raw_tex on, because the assembled document needs it for
    # \part* and the {{contents}} blocks).
    #
    # Done per backslash RUN, not per backslash: replacing them one at a time lets
    # an already-doubled "\\input" re-form into a live "\input" (the first \ has no
    # letter after it, so only the second is rewritten). \textbackslash{} is the
    # literal-backslash escape and cannot itself start a control word.
    # A backslash before punctuation is left alone — that is a markdown escape
    # (\*, \%), and only \+letter can begin a control sequence.
    body = re.sub(r"\\+(?=[A-Za-z])", lambda m: r"\textbackslash{}" * len(m.group(0)), body)
    body = INNER_SPACES.sub(" ", body)  # collapse interior double-spaces
    body = re.sub(r"[ \t]+\n", "\n", body)  # strip trailing spaces (breaks are re-added uniformly below)
    body = re.sub(r"\n{3,}", "\n\n", body)  # no triple blank lines
    # keep every line break the author typed: a lone newline inside a paragraph
    # becomes a real (markdown hard) break instead of being reflowed into a space.
    # blank-line paragraph separations (\n\n) are left untouched.
    body = re.sub(r"(?<!\n)\n(?!\n)", "  \n", body)
    return body.strip()


def section_body(raw):
    """Strip the file's own id-heading, protect {{contents}} blocks from clean()
    (which would double-escape the injected LaTeX), clean, then reinsert."""
    m = re.match(r"\s*#\s*\d+\s*\n(.*)", raw, re.S)
    body = m.group(1) if m else raw
    stash = []
    body = CONTENTS_RE.sub(
        lambda mm: stash.append(mm.group(1)) or f"\n\n@@CONTENTS{len(stash) - 1}@@\n\n", body
    )
    body = clean(body)
    for i, inner in enumerate(stash):
        body = body.replace(f"@@CONTENTS{i}@@", render_contents_latex(inner))
    return body


def attic_paths():
    """Soft-deleted section files in manuscript/_attic, numeric filename order."""
    ps = glob.glob(os.path.join(ATTIC, "[0-9]*.md"))
    return sorted(ps, key=lambda p: os.path.basename(p))


def render_appendix(paths, title, note):
    """A back-of-book division (\\part*) listing out-of-flow sections. Each carries a
    small id header (its stable manuscript filename) instead of a positional scene
    number, since these are not part of the numbered flow."""
    if not paths:
        return []
    t = latex_escape(title)
    out = [f"\\part*{{{t}}}\n\\addcontentsline{{toc}}{{part}}{{{t}}}\n"]
    if note:
        out.append(f"\\begin{{center}}\\textit{{{latex_escape(note)}}}\\end{{center}}\n\n")
    for path in paths:
        fid = os.path.basename(path)[:-3]
        with open(path, encoding="utf-8") as fh:
            body = section_body(fh.read())
        shown = body if body.strip() else r"\textit{(empty section)}"
        out.append(
            f"\\phantomsection\\addcontentsline{{toc}}{{section}}{{{fid}}}\n"
            f"\\begin{{center}}\\small\\textsc{{[{fid}]}}\\end{{center}}\n\n"
            f"{shown}\n"
        )
    return out


def compute_range(full, part_map, args):
    """Return (lo, hi) inclusive positional bounds (1-based) over `full`."""
    n = len(full)
    id_to_pos = {os.path.basename(p)[:-3]: i for i, p in enumerate(full, 1)}
    starts = sorted((id_to_pos[sid], sid) for sid in part_map if sid in id_to_pos)
    if args.part:
        q = args.part.lower()
        hit = next(((pos, sid) for pos, sid in starts if q in part_map[sid]["title"].lower()), None)
        if not hit:
            sys.exit(f"--part {args.part!r} matched no part title in parts.json")
        pos, _ = hit
        later = [p for p, _ in starts if p > pos]
        return pos, (min(later) - 1 if later else n)
    if args.frm is not None or args.to is not None:
        return max(1, args.frm or 1), min(n, args.to or n)
    return 1, n


# ---------------------------------------------------------------- PDF render
# One place both `pal pdf` and the web "Generate PDF" button go through, so a PDF
# made in the browser is byte-for-byte what the CLI makes.
import shutil, subprocess


def tools_ok():
    """(pandoc_path, xelatex_path) — either may be None if not installed."""
    return shutil.which("pandoc"), shutil.which("xelatex")


def _suffix(part=None, frm=None, to=None, held=False, deleted=False):
    s = ""
    if part:
        s += "." + re.sub(r"[^A-Za-z0-9]+", "-", part).strip("-")
    elif frm is not None:
        s += f".{frm}-{to if to is not None else ''}"
    elif to is not None:
        s += f".to-{to}"
    if held and deleted:
        s += ".appendices"
    elif held:
        s += ".held"
    elif deleted:
        s += ".deleted"
    return s


def build_pdf(part=None, frm=None, to=None, held=False, deleted=False):
    """Assemble the manuscript and render it to a PDF. Returns the output path.

    Raises RuntimeError with a human message on any failure (missing tools,
    assembly error, pandoc/xelatex error)."""
    pandoc, xelatex = tools_ok()
    if not pandoc or not xelatex:
        missing = " and ".join(x for x, ok in (("pandoc", pandoc), ("xelatex", xelatex)) if not ok)
        raise RuntimeError(
            f"{missing} not found. PDF export needs pandoc + XeLaTeX. On macOS:\n"
            '  brew install pandoc\n  brew install --cask basictex   (then: eval "$(/usr/libexec/path_helper)")'
        )

    # 1. assemble the markdown (reuse this module's own logic, in-process)
    a = SimpleNamespace(part=part, frm=frm, to=to)  # compute_range takes an argparse ns
    full = section_paths()
    part_map = load_parts()
    unnum = load_unnumbered()
    lo, hi = compute_range(full, part_map, a)
    _assemble(full, part_map, unnum, lo, hi, held, deleted)

    # 2. inputs: optional front matter, then the assembled book
    inputs = []
    fm = config.pdf_front_matter()
    if fm:
        inputs.append(fm)
    inputs.append(BOOK_MD)

    # 3. header(s): the book's or the bundled default, plus a font-override snippet
    header = config.pdf_header() or os.path.join(os.path.dirname(__file__), "assets", "header.tex")
    headers = [header]
    main_font, mono_font = safe_font(config.PDF_MAIN_FONT), safe_font(config.PDF_MONO_FONT)
    if main_font or mono_font:
        snip = os.path.join(OUT_DIR, "_fonts.tex")
        with open(snip, "w", encoding="utf-8") as fh:
            if main_font:
                fh.write(f"\\setmainfont{{{main_font}}}\n")
            if mono_font:
                fh.write(f"\\setmonofont{{{mono_font}}}\n")
        headers.append(snip)  # a later -H wins, so this overrides the default fonts

    out_pdf = os.path.join(
        str(config.BOOK_DIR), config.SAFE_SLUG + _suffix(part, frm, to, held, deleted) + ".pdf"
    )
    cmd = [pandoc, "-f", "markdown+smart", *inputs, "-o", out_pdf, "--pdf-engine=xelatex"]
    for h in headers:
        cmd += ["-H", h]
    cmd += [
        "-V",
        "geometry:margin=1in",
        "-V",
        "fontsize=12pt",
        "-V",
        f"title={config.TITLE}",
        "-V",
        "colorlinks=true",
        "-V",
        "linkcolor=black",
        "--strip-comments",
    ]
    if config.SUBTITLE:
        cmd += ["-V", f"subtitle={config.SUBTITLE}"]
    if config.AUTHOR:
        cmd += ["-V", f"author={config.AUTHOR}"]

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=RENDER_TIMEOUT)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(
            f"PDF render timed out after {RENDER_TIMEOUT}s "
            "(raise PAL_RENDER_TIMEOUT if this book is genuinely that long)"
        ) from e
    if r.returncode != 0 or not os.path.isfile(out_pdf):
        tail = (r.stderr or r.stdout or "pandoc failed").strip().splitlines()[-6:]
        raise RuntimeError("PDF render failed:\n" + "\n".join(tail))
    return out_pdf


# ---------------------------------------------------------------- portable export
# PDF goes through LaTeX (nicer type); Word/HTML/Markdown go through a PORTABLE
# markdown assembly with no raw LaTeX, so pandoc can target .docx/.html — neither
# of which needs XeLaTeX — and .md needs no tools at all.
EXPORT_EXT = {"pdf": ".pdf", "docx": ".docx", "html": ".html", "md": ".md"}


def _clean_md(body):
    """Same tidy-up as clean() but WITHOUT the LaTeX escaping, so the result is
    portable Markdown (safe for pandoc's docx/html writers and for plain reading)."""
    body = body.replace("\xa0", " ")
    body = FIG.sub("", body)  # drop [figure: … stubbed] markers
    body = INNER_SPACES.sub(" ", body)
    body = re.sub(r"[ \t]+\n", "\n", body)
    body = re.sub(r"\n{3,}", "\n\n", body)
    body = re.sub(r"(?<!\n)\n(?!\n)", "  \n", body)  # keep the author's line breaks
    return body.strip()


def _section_body_md(raw):
    m = re.match(r"\s*#\s*\d+\s*\n(.*)", raw, re.S)
    body = m.group(1) if m else raw

    # a {{contents}} block → a simple centered small-caps-ish line list in markdown
    def _c(mm):
        lines = [l.strip() for l in mm.group(1).splitlines() if l.strip()]
        return "\n\n" + "\n".join(f"*{l}*" for l in lines) + "\n\n"

    body = CONTENTS_RE.sub(_c, body)
    return _clean_md(body)


def assemble_markdown(part=None, frm=None, to=None, held=False, deleted=False):
    """Return the whole book as portable Markdown (parts as headings, a small
    scene number before each numbered section). No LaTeX, no tools required."""
    a = SimpleNamespace(part=part, frm=frm, to=to)  # compute_range takes an argparse ns
    full = section_paths()
    part_map = load_parts()
    unnum = load_unnumbered()
    lo, hi = compute_range(full, part_map, a)

    out, num = [], 0
    for pos, path in enumerate(full, 1):
        fn = os.path.basename(path)[:-3]
        numbered = fn not in unnum
        if numbered:
            num += 1
        if pos < lo or pos > hi:
            continue
        if fn in part_map:
            meta = part_map[fn]
            out.append(f"\n# {meta['title']}\n")
            if meta.get("subtitle"):
                out.append(f"*{meta['subtitle']}*\n")
        with open(path, encoding="utf-8") as fh:
            body = _section_body_md(fh.read())
        if numbered:
            out.append(f"\n**{num}**\n\n{body}\n")
        else:
            out.append(f"\n{body}\n")

    def _appendix(paths, title, note):
        if not paths:
            return
        out.append(f"\n# {title}\n")
        if note:
            out.append(f"*{note}*\n")
        for p in paths:
            fid = os.path.basename(p)[:-3]
            with open(p, encoding="utf-8") as fh:
                body = _section_body_md(fh.read())
            out.append(f"\n**[{fid}]**\n\n{body or '*(empty section)*'}\n")

    if held:
        _appendix(held_paths(), "Set aside", "Sections pulled out of the flow — kept, not placed.")
    if deleted:
        _appendix(attic_paths(), "Deleted", "Sections cut from the manuscript — archived, recoverable.")
    return "\n".join(out).strip() + "\n"


def build_doc(fmt="pdf", part=None, frm=None, to=None, held=False, deleted=False):
    """Export the book to `fmt` (pdf | docx | html | md). Returns the output path.

    Dependency ladder — the point of offering more than PDF:
      md    → nothing (pure Python)
      html  → nothing needed (pandoc used if present for a nicer standalone file)
      docx  → pandoc only (NO XeLaTeX)
      pdf   → pandoc + XeLaTeX
    Raises RuntimeError with a human message on any failure."""
    fmt = (fmt or "pdf").lower()
    if fmt == "pdf":
        return build_pdf(part, frm, to, held, deleted)
    if fmt not in EXPORT_EXT:
        raise RuntimeError(f"unknown export format {fmt!r} (use pdf, docx, html, or md)")

    md = assemble_markdown(part, frm, to, held, deleted)
    # a title block so Word/HTML show the book's title/author
    meta = f"% {config.TITLE}\n"
    if config.AUTHOR:
        meta += f"% {config.AUTHOR}\n"
    src = os.path.join(OUT_DIR, f"{config.SAFE_SLUG}.export.md")
    with open(src, "w", encoding="utf-8") as fh:
        fh.write(meta + "\n" + md)

    out = os.path.join(
        str(config.BOOK_DIR), config.SAFE_SLUG + _suffix(part, frm, to, held, deleted) + EXPORT_EXT[fmt]
    )

    if fmt == "md":  # zero dependencies
        shutil.copyfile(src, out)
        return out

    pandoc, _ = tools_ok()
    if fmt == "html" and not pandoc:  # graceful pure-Python HTML fallback
        _minimal_html(md, out)
        return out
    if not pandoc:
        raise RuntimeError(
            "Word (.docx) export needs pandoc (a small, free tool — no LaTeX required).\n"
            "On macOS:  brew install pandoc"
        )

    cmd = [pandoc, "-f", "markdown+smart", src, "-o", out, "--standalone", "--strip-comments"]
    if config.SUBTITLE:
        cmd += ["-V", f"subtitle={config.SUBTITLE}"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=RENDER_TIMEOUT)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"{fmt} export timed out after {RENDER_TIMEOUT}s") from e
    if r.returncode != 0 or not os.path.isfile(out):
        tail = (r.stderr or r.stdout or "pandoc failed").strip().splitlines()[-6:]
        raise RuntimeError(f"{fmt} export failed:\n" + "\n".join(tail))
    return out


def _minimal_html(md, out):
    """A no-dependency HTML fallback (used only when pandoc isn't installed):
    escape the text and keep paragraph breaks. Not a full markdown renderer —
    just a readable, shareable single file."""
    import html as _h

    title = _h.escape(config.FULL_TITLE)
    paras = "".join(f"<p>{_h.escape(p).strip()}</p>\n" for p in re.split(r"\n\s*\n", md) if p.strip())
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(
            f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{title}</title><style>body{{max-width:40em;margin:3em auto;padding:0 1em;"
            f"font:17px/1.6 Georgia,serif;color:#222}}h1{{font-size:1.6em}}</style></head><body>"
            f"<h1>{title}</h1>\n{paras}</body></html>"
        )


def _assemble(full, part_map, unnum, lo, hi, held, deleted):
    """Write BOOK_MD from the given positional range + optional appendices."""
    chunks, num = [], 0
    for pos, path in enumerate(full, 1):
        fn = os.path.basename(path)[:-3]
        numbered = fn not in unnum
        if numbered:
            num += 1
        if pos < lo or pos > hi:
            continue
        if fn in part_map:
            meta = part_map[fn]
            t = latex_escape(meta["title"])
            chunks.append(f"\\part*{{{t}}}\n\\addcontentsline{{toc}}{{part}}{{{t}}}\n")
            if meta["subtitle"]:
                chunks.append(
                    f"\\begin{{center}}\\textit{{{latex_escape(meta['subtitle'])}}}\\end{{center}}\n\n"
                )
        with open(path, encoding="utf-8") as fh:
            body = section_body(fh.read())
        if numbered:
            chunks.append(
                f"\\phantomsection\\addcontentsline{{toc}}{{section}}{{{num}}}\n"
                f"\\begin{{center}}\\small\\textsc{{{num}}}\\end{{center}}\n\n"
                f"{body}\n"
            )
        else:
            chunks.append(f"{body}\n")
    if held:
        chunks += render_appendix(
            held_paths(), "Set aside", "Sections pulled out of the flow — kept, not placed."
        )
    if deleted:
        chunks += render_appendix(
            attic_paths(), "Deleted", "Sections cut from the manuscript — archived, recoverable."
        )
    with open(BOOK_MD, "w", encoding="utf-8") as fh:
        fh.write("\n".join(chunks))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="frm", type=int, default=None, help="positional start (inclusive)")
    ap.add_argument("--to", dest="to", type=int, default=None, help="positional end (inclusive)")
    ap.add_argument("--part", dest="part", default=None, help="substring match against a part title")
    ap.add_argument("--held", action="store_true", help="append a 'Set aside' appendix (held.json sections)")
    ap.add_argument(
        "--deleted", action="store_true", help="append a 'Deleted' appendix (manuscript/_attic sections)"
    )
    ap.add_argument("--extras", action="store_true", help="shorthand for --held --deleted")
    args = ap.parse_args()
    if args.extras:
        args.held = args.deleted = True

    full = section_paths()
    part_map = load_parts()  # {start_sid: {title, subtitle}}
    unnum = load_unnumbered()  # sids that print but aren't numbered
    lo, hi = compute_range(full, part_map, args)
    _assemble(full, part_map, unnum, lo, hi, args.held, args.deleted)
    rng = "" if (lo, hi) == (1, len(full)) else f" (positions {lo}–{hi})"
    print(f"wrote {BOOK_MD}{rng} (positional order, cleaned)")


if __name__ == "__main__":
    main()
