# Palimpsest — architecture

How the pieces fit and why they are arranged this way. `AI_ASSISTANT.md` is the terse
working reference; this is the explanation behind it. Read this before changing
how a book is resolved, how the dossier is built, or what the server accepts.

---

## The shape of the thing

Palimpsest is a **generator with an editing surface, with a sonification engine, that lets you listen to how you write **. It reads a folder
of Markdown, writes a folder of HTML, and serves that HTML with a small API that
writes back to the Markdown. Nothing is stored anywhere else — no database, no
config service, no account.

```
  a BOOK on disk                the ENGINE                    what you use
  ─────────────────             ──────────                    ────────────
  book.toml         ──┐
  manuscript/*.md     ├──▶  config  ──▶  builders  ──▶  dossier/*.html  ──▶  browser
  manifests/*.json    │       │                                 ▲              │
  data/*.json       ──┘       └────────  save_server  ──────────┘              │
                                              ▲                                │
                                              └──────── POST /save, … ─────────┘
                                                        (and git commit)
```

Two properties fall out of that shape and everything else defers to them:

**It is a pure function of the book folder.** Same input, same bytes out. There is
no clock, no randomness, no network, no model. `tests/test_build.py` asserts this
directly — build twice, compare bytes. It is what makes the tool trustworthy for
someone's manuscript, and it is why "no LLM" is an architectural constraint rather
than a slogan.

**The authored files are the source of truth, not the HTML.** The dossier is
disposable and gitignored; delete it and `pal build` reconstructs it exactly. Every
edit in the browser writes through to `manuscript/` or `manifests/` first, and the
HTML is regenerated from that. There is no state that lives only in the page.

---

## A book

A book is a directory containing `book.toml`. Everything else is named by it, so
nothing in the engine hardcodes a layout:

```toml
[book]
title    = "…"           # display + PDF title
subtitle = ""
author   = ""
manuscript  = "manuscript"             # NNN.md, one per section
suggestions = "manuscript-suggestions" # optional copyedit pass
manifests   = "manifests"              # authored STRUCTURE (server writes these)
data        = "data"                   # authored TABLES (motifs, edit board)
out         = "dossier"                # generated HTML (gitignored)
git = true                             # commit on save when in a repo

[views]
enabled = ["reading", "motifs", "record", "copyedit", "parts", "index", "board"]
```

**Sections are files; order is a manifest.** `manuscript/001.md` starts with a
`# 1` heading — that number is the section's _stable id_, used for anchors, motif
membership and deletion. Files are never renumbered. Reordering writes
`manifests/order.json`, a list of ids. This is the single most important data
decision in the project: because ids are stable, a section can move, be parked, or
be deleted and restored without any other file needing to know.

The manifests, all optional, all authored through the browser:

| File                 | Holds                                      |
| -------------------- | ------------------------------------------ |
| `order.json`         | display order, as a list of ids            |
| `labels.json`        | per-section labels `{text, color}`         |
| `parts.json`         | part banners: `{start, title, subtitle}`   |
| `part-dividers.json` | sections that _are_ part dividers          |
| `unnumbered.json`    | sections excluded from §-numbering         |
| `held.json`          | parked sections — on disk, out of the flow |
| `entities-seed.json` | index watchlist terms                      |

`data/` holds interpretive tables rather than structure: `motifs.json`,
`edit-board.json`.

Paths in `book.toml` may point outside the book. That is deliberate — it lets you
keep a manuscript wherever you like — but it is also a hazard for a book someone
sent you, so `config.external_paths()` reports it at build and serve time, and a
LaTeX header from outside the book is refused outright unless
`PAL_ALLOW_EXTERNAL_PATHS=1`.

---

## The engine

`palimpsest/engine/` is a flat set of modules run with the engine directory on
`PYTHONPATH`. They are deliberately _not_ an importable subpackage: builders run as
subprocesses, and a flat namespace is what lets the same module be imported the
same way from the CLI, the server, and a builder child.

| Module           | Responsibility                                                                                              |
| ---------------- | ----------------------------------------------------------------------------------------------------------- |
| `config.py`      | **the active book.** Resolves `book.toml`, exposes paths, title, theme, palette, and the safe-value helpers |
| `sections.py`    | shared section data: order, labels, parts, dividers, held; and the one heading parser                       |
| `dossier.py`     | **the one build path.** `REGISTRY`, `run_builder()`, `build()`                                              |
| `nav.py`         | the shared top bar, `page_head()`, and `script_json()`                                                      |
| `builders/*.py`  | one script per view; each writes exactly one HTML file                                                      |
| `save_server.py` | the `pal serve` HTTP server                                                                                 |
| `build_book.py`  | export: assemble the manuscript, shell out to pandoc                                                        |
| `import_book.py` | md / pdf / docx → a list of section bodies                                                                  |
| `library.py`     | the workbench: list, create, delete, resolve books                                                          |

### config binds once, at import

`config.py` resolves the active book **when it is imported** and caches it. This is
the single most consequential design decision in the engine, and everything else
bends around it:

- The CLI drops `config`, `sections`, `nav` from `sys.modules` before rebinding to
  another book (`cli.book_config`, `dossier._config_for`).
- The server **cannot** rebind at all, so switching books re-execs the process
  (`save_server.switch_to`).
- Anything downstream of `config` cannot be unit-tested in-process; the test
  harness runs those checks in a child (`tests/harness.py`, `engine_eval`).

The upside is that no function anywhere needs a `book` argument. The cost is the
three workarounds above. If you ever want to change one thing about the
architecture, change this.

### One build path

`dossier.build()` is the only way a dossier is produced, and `dossier.run_builder()`
is the only place a builder subprocess is spawned. `pal build` calls it; the
server's `/rebuild` calls it; the server's incremental rebuild after a save calls it
through a thin binding that supplies its own book and dossier.

That matters because the incremental path is the one a writer hits on every
keystroke — if it diverged, the book you see while typing would differ from the one
`pal build` makes. `tests/test_one_build_path.py` asserts both halves: exactly one
spawn site, and CLI output byte-identical to browser output.

`run_builder` resolves its interpreter through `dossier.child_python()`, never
`sys.executable`. Inside a py2app `.app` the latter is the app binary, and spawning
it relaunches the application instead of building a view.

Builders are one-shot scripts, not modules: each reads the book through `config`
and `sections`, emits one HTML file, and exits. They share chrome through
`nav.page_head()` / `nav.topbar_html()` and `assets/style.css`, so no builder owns
the page frame. `[views] enabled` gates both which builders run and which nav
entries appear.

---

## The server

`pal serve` binds `127.0.0.1:8137` and serves the dossier, plus an API that writes
to the book.

### The security model is three headers

There are **no accounts and no tokens**. Anything that can reach the port can
rewrite the manuscript. The browser on this machine is the only intended client, so
requests are pinned to this origin by three cheap checks in `_allowed()`:

| Check                                | Stops                                                                                                 |
| ------------------------------------ | ----------------------------------------------------------------------------------------------------- |
| `Host` must name loopback            | DNS rebinding — a hostile name resolving to 127.0.0.1                                                 |
| `Origin`, when present, must be ours | another site's page driving the API                                                                   |
| writes must be `application/json`    | cross-site forms and `no-cors` fetch, which cannot send it without a preflight that is never answered |

`PAL_ALLOWED_HOSTS` widens this deliberately. **This is not authentication:** it
stops a browser, not a script — `curl -H 'Host: localhost'` satisfies it from
anywhere that can reach the port. Binding non-loopback prints a warning saying so.

`tests/test_origin_gate.py` exercises each check in both directions. Treat a
failure there as a security regression.

### Writing, and versioning

A save writes `manuscript/NNN.md` and, when the manuscript is inside a git repo,
commits it — so every save is a version you can browse and restore. Without a repo
it degrades to plain writes and says so. Commit messages are namespaced by book
slug, as are browser `localStorage` keys, so two books open in one browser never
collide.

Rebuilds after a save are coalesced through a background worker: the copyedit view
takes seconds to build, so a save returns immediately and one follow-up rebuild
absorbs any number of saves.

Endpoints group as: section text (`/save`, `/section/*`, `/restore`), structure
(`/order`, `/parts`, `/labels`, `/unnumbered`), interpretive tables (`/motifs`,
`/watchlist`, `/edit-board`), the copyedit workflow (`/accept-all`, `/resolve`,
`/suggestion-*`), books (`/book-new`, `/book-open`, `/book-delete`, `/import`), and
output (`/export`, `/pdf`, `/rebuild`).

### Errors are answers, not exceptions

Every endpoint returns `{ok: false, error: …}` rather than a 500, because the page
depends on being able to show the message. The cost is that a real bug and a
malformed request look alike from outside, so failures are logged even when the
reply is polite. Quiet by default; `PAL_LOG=debug` or `pal serve --verbose` turns
on the detail and a request log.

---

## Escaping: where text becomes markup

Authored text — titles, labels, part names, index terms, prose — reaches four
contexts that each need different treatment. Getting this wrong is how a manuscript
tool becomes an exfiltration vector, since a payload that runs in the page runs
_inside the origin the gate protects_.

| Context                   | Rule                        | Helper                             |
| ------------------------- | --------------------------- | ---------------------------------- |
| HTML text / attributes    | escape                      | `html.escape`, `config.TITLE_HTML` |
| inside a `<script>` block | escape `</` as well as JSON | **`nav.script_json()` — always**   |
| a `style="…"` colour      | validate to a hex literal   | `config.safe_color`                |
| a filename                | scrub to `[A-Za-z0-9._-]`   | `config.SAFE_SLUG`                 |
| XeLaTeX                   | neutralise backslash runs   | `build_book.clean()`               |

Two of these are easy to get subtly wrong:

**`<script>` embeds.** `json.dumps` does not escape `/`, so a value containing
`</script>` closes the tag early and everything after it is parsed as markup. Never
call `json.dumps` directly into a `<script>`; call `nav.script_json()`.

**LaTeX.** pandoc runs with `raw_tex` on, because the assembled document emits real
LaTeX (`\part*`, the `{{contents}}` blocks). So a control word in author prose would
execute — and TeX Live's default `openin_any=a` makes `\input` an arbitrary-file
read whose contents land in the exported PDF. `clean()` therefore neutralises each
backslash **run**, not each backslash: doing it one at a time lets a pre-doubled
`\\input` re-form into a live `\input`.

---

## Export

`build_book.py` assembles the manuscript twice, by two paths that must not be
confused:

- **PDF** → LaTeX-flavoured Markdown (`<slug>.book.md`) → pandoc → XeLaTeX. Part
  breaks become `\part*`, `{{contents}}` blocks become centred small-caps.
- **docx / html / md** → portable Markdown, no LaTeX, no TeX required.

The escaping differs between them by design: the portable path deliberately skips
LaTeX escaping, because its output never reaches TeX. Renders are bounded by
`PAL_RENDER_TIMEOUT` (default 900s) — `/export` is unauthenticated and threaded, so
an unbounded pandoc is a way to pin the machine.

pandoc and XeLaTeX are **optional and detected at runtime**. The core is stdlib-only
on Python 3.11+ (`tomllib`); PyMuPDF is an optional extra for PDF _import_. Every
one of these degrades with a message rather than crashing.

---

## Distribution

The same code ships four ways, which is why interpreter and path resolution are
indirected rather than assumed:

| Channel      | Notes                                                                                                                                                |
| ------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| pipx / pip   | `pal` console script → `palimpsest.cli:main_cli`                                                                                                     |
| Homebrew     | formula in `homebrew/` is the source of truth; copied to the tap                                                                                     |
| macOS `.app` | py2app; engine and template ship as bundle resources, so `cli.HERE` resolves to `Contents/Resources` and `child_python()` finds the real interpreter |
| Docker       | binds `0.0.0.0` inside the container; safety comes from publishing the port on `127.0.0.1`                                                           |

The workbench — where books live — is `~/Documents/Palimpsest` when installed, or
`./books` from a source checkout, overridable by `PAL_HOME`.

---

## Environment

| Variable                   | Effect                                                        |
| -------------------------- | ------------------------------------------------------------- |
| `PAL_BOOK`                 | the active book (else `--book`, else the nearest `book.toml`) |
| `PAL_HOME`                 | the workbench directory                                       |
| `PAL_BIND` / `PORT`        | server bind address and port                                  |
| `PAL_ALLOWED_HOSTS`        | additional hostnames the origin gate accepts                  |
| `PAL_LOG=debug`            | request log and tracebacks behind failed writes               |
| `PAL_RENDER_TIMEOUT`       | pandoc/XeLaTeX budget, seconds                                |
| `PAL_NO_BROWSER`           | do not auto-open a browser                                    |
| `PAL_ALLOW_EXTERNAL_PATHS` | permit a `book.toml` pointing outside the book                |
| `PAL_PDF_HEADER`           | LaTeX header override                                         |

---

## Conventions

- **`dossier/` is generated.** Never edit built HTML; change the builder.
- **Builders are f-strings emitting HTML** — double every literal `{`/`}` inside
  them, or keep the JS in a separate non-f string and interpolate it.
- **Match the surrounding style.** The engine uses compact imports and one-line
  validation guards; `ruff` is configured to allow them deliberately.
- **Add a test with any behaviour change.** `tests/README.md` says where things go.
- **Two books never collide**: `localStorage` keys and commit messages are
  namespaced by `config.SLUG`.
