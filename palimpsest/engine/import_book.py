"""Import an existing manuscript into section bodies for a new book.

Three sources, all deterministic (no model):
  - a folder of Markdown files  (one file → one section; needs nothing)
  - a PDF, split by chapter or page   (needs PyMuPDF — bundled in the image)
  - a Word .docx, split by heading     (needs pandoc)

Each function returns a list of section-body strings; the caller writes them as
manuscript/001.md, 002.md, … The heading line a book uses (`# N`) is added by the
caller, so bodies here never carry one.
"""
import re
import subprocess
import sys
from pathlib import Path


def _install_hint(pkg):
    """The command that installs `pkg` into *this* interpreter's environment.

    Palimpsest runs from several places — a pipx venv, a Homebrew formula venv, a
    .app bundle, a plain checkout — and each needs a different command. Telling a
    Homebrew user to `pip install pymupdf` sends the package to some other Python
    and leaves the app exactly as broken, so work out the real one.

    Note both paths are used UNRESOLVED: a venv's bin/python is a symlink to the
    base interpreter, and resolving it would name the very environment we must not
    install into."""
    exe = sys.executable
    where = set(Path(sys.prefix).parts) | set(Path(exe).parts)
    if "pipx" in where:                       # ~/.local/pipx/venvs/palimpsest/bin/python
        return f"pipx inject palimpsest {pkg}"
    if any(p.endswith(".app") for p in Path(exe).parts):   # py2app bundle: read-only
        return ("(this build of the app doesn't include it — use the Docker image, "
                "or import the file as .docx/.md instead)")
    if "Cellar" in where:                     # Homebrew formula virtualenv
        return (f'"{exe}" -m pip install {pkg}\n'
                "  (a `brew upgrade` rebuilds that environment — re-run it afterwards)")
    return f'"{exe}" -m pip install {pkg}'

_ID_HEAD = re.compile(r"^\s*#\s*\d+\s*\n")       # an existing "# 12" id heading
_WS = re.compile(r"[ \t]+\n")
_BLANKS = re.compile(r"\n{3,}")


def _tidy(body: str) -> str:
    body = body.replace("\xa0", " ")
    body = _WS.sub("\n", body)
    body = _BLANKS.sub("\n\n", body)
    return body.strip()


def sections_from_md(files):
    """files: list of (filename, text). One file → one section, in filename order.
    A leading `# N` id heading is stripped so it isn't doubled."""
    out = []
    for _name, text in sorted(files, key=lambda f: str(f[0])):
        body = _tidy(_ID_HEAD.sub("", text or ""))
        if body:
            out.append(body)
    return out


def sections_from_pdf(path, by="chapter"):
    """Split a PDF into sections. `by='chapter'` uses the PDF's own bookmarks/outline
    when it has them (title + page per chapter); otherwise it falls back to one
    section per page. `by='page'` forces per-page."""
    try:
        import fitz  # PyMuPDF
    except ImportError as e:
        raise RuntimeError("PDF import needs PyMuPDF, which isn't installed here.\n"
                           f"  Install it with:  {_install_hint('pymupdf')}\n"
                           "  (the Docker image already has it — so does `pip install "
                           "'palimpsest[pdf]'`)") from e
    doc = fitz.open(path)
    n = doc.page_count

    def page_text(p):
        try:
            t = doc[p].get_text().strip()
            t = re.sub(r"\n\s*\d{1,4}\s*$", "", t)   # drop a lone page-number footer
            return t.strip()
        except Exception:
            return ""

    if by == "chapter":
        toc = []
        try:
            toc = doc.get_toc()          # [[level, title, page1based], …]
        except Exception:
            toc = []
        tops = [(t[2] - 1, str(t[1]).strip()) for t in toc if t[0] <= 1] or \
               [(t[2] - 1, str(t[1]).strip()) for t in toc]
        tops = [(max(0, min(pg, n - 1)), title) for pg, title in tops]
        if tops:
            out = []
            for i, (pg, title) in enumerate(tops):
                end = tops[i + 1][0] if i + 1 < len(tops) else n
                body = "\n\n".join(t for t in (page_text(p) for p in range(pg, end)) if t)
                body = _tidy((title + "\n\n" + body) if title else body)
                if body:
                    out.append(body)
            if out:
                return out
        # no usable outline → per page
    return [t for t in (_tidy(page_text(p)) for p in range(n)) if t]


def sections_from_docx(path):
    """Convert a .docx to Markdown with pandoc, then split into sections at top-level
    headings (# / ##). If the document has no headings, it becomes one section."""
    import shutil
    if not shutil.which("pandoc"):
        raise RuntimeError("Word (.docx) import needs pandoc, which isn't on PATH.\n"
                           "  Install it with:  brew install pandoc   (the Docker image "
                           "already has it)")
    r = subprocess.run(["pandoc", path, "-t", "markdown", "--wrap=none"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("pandoc could not read that file: "
                           + (r.stderr or "").strip()[:200])
    md = r.stdout
    # split at lines that start a heading (# or ##); the heading text stays in-body
    parts, cur = [], []
    for line in md.splitlines():
        if re.match(r"^#{1,2}\s+\S", line) and cur and any(x.strip() for x in cur):
            parts.append("\n".join(cur))
            cur = [line]
        else:
            cur.append(line)
    if cur:
        parts.append("\n".join(cur))
    # Palimpsest sections are plain prose (the reading copy shows text verbatim),
    # so turn Markdown heading markers into plain title lines instead of literal '#'.
    def unhead(s):
        return re.sub(r"(?m)^#{1,6}[ \t]+", "", s)
    out = [t for t in (unhead(_tidy(p)) for p in parts) if t]
    return out or [unhead(_tidy(md))]
