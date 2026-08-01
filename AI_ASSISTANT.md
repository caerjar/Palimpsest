# Palimpsest — project guide for Claude

A **book-agnostic manuscript workbench**. Point it at a _book_ (a folder of
numbered Markdown sections) and it builds an editorial **dossier** of HTML views
you edit in the browser — reading copy, parts board, copyedit review, back-of-book
index, and a motifs page — then exports to PDF, Word,
HTML, or Markdown.

**Core principle: fully deterministic. No network, no accounts.** Nothing
in the app calls a model; the user's writing never leaves their machine. Do not
introduce any AI/LLM dependency.

**[ARCHITECTURE.md](ARCHITECTURE.md)** explains _why_ the pieces are arranged this
way — the book-as-pure-function property, config's import-time binding and what it
costs, the one build path, the origin gate, and the four escaping contexts. Read it
before changing book resolution, the build path, or what the server accepts. This
file is the terse working reference.

## Run it

- **Docker (the shared path):** `just serve` → build image + start → open
  http://localhost:8137. Books live on the host in `./workbench/` (mounted at
  `/data`). `just rebuild` forces a full refresh after code changes;
  `just fresh` archives the workbench and boots an empty one. Recipes wrap
  `docker compose` (see `justfile`); the image bundles pandoc + XeLaTeX + git +
  fonts so every export works.
- **Local (dev):** `./pal --book <name> serve` (or `cd books/<name> && ../../pal
serve`). Pure Python **stdlib only, 3.11+** (needs `tomllib`). Export then
  needs `pandoc` (+ XeLaTeX for PDF) installed locally.

`./pal` with no args prints all commands.

## Layout

```
pyproject.toml         packaging: `pal` console script → palimpsest.cli:main_cli
pal                     dev launcher (puts repo on sys.path → palimpsest.cli.main)
palimpsest/          the installable package
  cli.py               the CLI (arg parsing + commands; resolves engine/_template)
  __main__.py          `python -m palimpsest`
  engine/              run as subprocesses on PYTHONPATH (not imported as a subpkg)
    config.py          the ACTIVE BOOK: resolves book.toml, exposes paths/title/
                       views + data loaders (motifs, register cues, analysis)
    library.py         the workbench: list/create/delete books; PAL_HOME resolution
    dossier.py         the ONE build path (REGISTRY + static pages); cli & server
                       both call dossier.build() so CLI and browser builds match.
                       run_builder() is the ONLY place a builder is spawned — the
                       server binds to it rather than keeping its own (see below);
                       tests/test_one_build_path.py holds both halves of that claim
    nav.py             topbar_html()/nav_html() — the one shared menu bar
    sections.py        section ordering, labels, part helpers
    save_server.py     the `pal serve` HTTP server (edit/save + all endpoints)
    build_book.py      PDF/Word/HTML/MD export (pandoc; assembles the manuscript)
    builders/          one script per view → writes <book>/dossier/*.html
    assets/            style.css, pal.js (shared top-bar JS), header*.tex,
                       writing-record.html · library.html · help.html (static pages)
  _template/           what `pal new` copies (ships inside the package)
packaging/             py2app .app + .dmg build (build_dmg.sh, setup_app.py)
homebrew/              tap formula (source of truth; copy into homebrew-tap repo)
books/                 dev workbench — your books (gitignored); only from a checkout
  <book>/              book.toml · manuscript/ · manifests/ · data/ · dossier/
```

Installed (pipx/Homebrew/.app), the workbench is `~/Documents/Palimpsest`; from a
source checkout it's `./books` (detected by a `pyproject.toml` above the package).

A **book** = `book.toml` + `manuscript/NNN.md` (one file per section, `# N`
heading) + `manifests/` (authored _structure_: order, labels, parts, watchlist —
the server writes these) + `data/` (authored _interpretive tables_: motifs,
register cues, analysis, edit-board) + `dossier/` (generated HTML,
gitignored). Paths in `book.toml` are relative to the book.

## How building works

`pal build` calls `dossier.build()`, which (a) copies `assets/style.css` +
`assets/pal.js` and the static pages (substituting
`__PAL_NAV__`/`__PAL_TITLE__`/`__PAL_NS__`) into `dossier/`, then (b) runs each enabled
builder in `dossier.REGISTRY` as a subprocess (via `dossier.child_python()`, which
resolves the real interpreter inside a py2app .app), each reading the book via
`config`/`sections` and writing one HTML file. The server's `build_book()` calls the
same `dossier.build()`, so a book made in the browser is identical to `pal build`. `[views] enabled` in `book.toml`
gates which builders run and which nav entries appear (`config.view_enabled`).
Every page shares the sticky top bar via `nav.topbar_html(current)`.

## The server (`pal serve`)

Serves `dossier/` on `127.0.0.1:$PORT` (default 8137). Env: `PAL_BIND` (container
uses `0.0.0.0`; a non-loopback bind prints an exposure warning — the origin gate
blocks browsers, not scripts), `PAL_NO_BROWSER` (skip auto-open), `PAL_HOME`
(workbench dir), `PAL_PDF_HEADER` (Linux LaTeX header), `PAL_LOG=debug` (or
`pal serve --verbose`: request log + tracebacks behind the polite 400s),
`PAL_RENDER_TIMEOUT` (pandoc/XeLaTeX budget, default 900s). Saves write
`manuscript/NNN.md` and
git-commit when the manuscript is in a repo (degrades to plain writes otherwise).
Switching books re-execs the process. Notable POST endpoints: `/save`,
`/section/add|delete|park`, `/labels` `/order` `/parts` `/unnumbered`,
`/watchlist` (index terms), `/edit-board` (revision board), `/export` `/pdf`,
`/rebuild`, `/book-new` `/book-open`.

## In-app editing (deterministic, browser-first)

The app favors editing _in the browser_, not by hand-editing JSON or running
terminal commands. Already in place: reading-copy section editing + labels +
reorder + parts; the **Index watchlist** (add/remove terms → `/watchlist` →
`manifests/entities-seed.json`); the **Edit board** (add columns/items →
`/edit-board` → `data/edit-board.json`). When adding a feature, prefer a server
endpoint that writes the authored file + rebuilds, plus an in-page control gated
to `location.protocol === http` (works only under `pal serve`). The top-bar
**↻ Rebuild** button re-runs the build; **Export ▾** downloads the book.

## Conventions & gotchas

- **Match the surrounding style.** Builders are f-strings emitting HTML; double
  every literal `{`/`}` inside them.
- **`dossier/` is generated + gitignored** — never edit built HTML; change the
  builder. Exports (`*.pdf/.docx/.html`) and `workbench/` are gitignored too.
- **Docker serves a stale dossier unless rebuilt.** After editing the app, the
  container needs the image rebuilt AND the book regenerated — `just rebuild`
  (the entrypoint always rebuilds the served book on start). Then hard-reload.
- **Two books in one browser** never collide: localStorage keys and commit
  messages are namespaced by the book slug (`config.SLUG`).
- **No book ships** — the repo carries only `palimpsest/_template`. Make a book to
  work with: `./pal new "Test"` (a book with all views enabled lets you exercise the
  views; add motifs on the Motifs page or in `data/motifs.json`).
- **Tests: `just test`** (`python3 -m unittest discover -s tests`). The suite makes
  its own book in a temp `PAL_HOME` and drives the real CLI and the real server
  over HTTP, so the workbench is never touched and no stray commits are made. Add
  a case with any behaviour change; `tests/README.md` says where things go.
  `tests/test_origin_gate.py` is the regression lock on the origin gate — treat a
  failure there as a security regression, not a flaky test.
