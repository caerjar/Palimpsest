# Palimpsest

A book-agnostic manuscript workbench. Point it at a book (a folder of numbered
Markdown sections) and it builds an editorial dossier in your browser — a
color-coded reading copy you can edit and save, a parts board, a copyedit review,
a back-of-book index, and the motifs you name — then
exports the whole thing to **PDF, Word, HTML, or Markdown**. Fully deterministic:
no accounts, no network. Your writing never leaves your machine.

**Try it without installing anything → <https://caerjar.github.io/Palimpsest/>**
A single self-contained page: one recorded writing session replayed as notation
and played back by a synthesizer, with the dials moving as it goes. Sound on.
It is built from the app's own Writing Record page by `just demo` — see
[`demo/README.md`](demo/README.md).

## Run it (Docker — the easy way)

Everything the app uses (pandoc, XeLaTeX + fonts, git) is baked into the image, so
you don't install any of it. You need **Docker** and, optionally, **[`just`](https://github.com/casey/just)**.

```bash
just serve      # builds the image the first time, then starts the app
```

Open **http://localhost:8137**. Your books live in **`./workbench/`** on your
computer (created on first run) — the container is disposable; nothing is trapped
inside it. Stop with `just stop`; your books stay put.

No `just`? Every recipe is a thin wrapper — run the raw command instead:

```bash
docker compose up -d --build       # = just serve   → http://localhost:8137
docker compose logs -f pal          # = just logs
docker compose down                # = just stop
docker compose run --rm pal python3 -m palimpsest new "My Novel"                 # = just new "My Novel"
docker compose run --rm pal python3 -m palimpsest --book my-novel export -f docx # = just export my-novel docx
```

Recipe reference: `just new "My Novel"`, `just build my-novel`,
`just export my-novel docx` (format = `pdf|docx|html|md`), `just books`,
`just shell`, `just logs`, `just stop`.

### From the browser

The **Library** link (top bar of any page) is the hub: create a new book, switch
between books, and see where your books live. The top-bar **Export ▾** menu
downloads the whole book as PDF / Word / HTML / Markdown. **↻ Rebuild**
regenerates every view from your latest edits.

### Exports

- **Markdown / HTML** need nothing — always available.
- **Word (.docx)** and **PDF** are produced by the tools bundled in the image, so
  they work out of the box here.
- Files land in `./workbench/<book>/` on the host.

## Install it (no Docker)

The core is pure-Python stdlib (Python 3.11+), so it installs with no dependencies.
Your books live in **`~/Documents/Palimpsest`** (override with `pal home <folder>`).

**pipx** (any platform with Python):

```bash
pipx install git+https://github.com/caerjar/Palimpsest
pal new "My Novel"
pal --book my-novel serve       # → http://127.0.0.1:8137
```

**Homebrew** (macOS/Linux):

```bash
brew tap caerjar/tap
brew install palimpsest
```

**macOS app (.dmg):** a double-clickable build with pandoc bundled — download it
from the releases page, drag to Applications, and the first launch opens the app in
your browser. (First open: right-click the app → **Open**, once.)

For nicer exports, optionally install `pandoc` (Word/HTML) and XeLaTeX / BasicTeX
(PDF); the app works without them and just enables those formats when present. The
Docker image bundles everything, so it's the zero-setup route for full export.

**Importing a PDF** additionally needs PyMuPDF, which must live in the _same_
environment Palimpsest runs from — a `pip install pymupdf` in a different Python
won't be found. The Homebrew formula installs it for you; elsewhere:

```bash
pipx inject palimpsest pymupdf        # pipx install
pip install 'palimpsest[pdf]'         # plain pip / venv
```

If it's missing, the app says so and prints the exact command for your install.
Markdown and Word (.docx) import need nothing extra.

Full packaging & release details: [`packaging/README.md`](packaging/README.md).

### From a source checkout (developers)

```bash
./pal new "My Book"            # scaffold a book in ./books (a clone ships none)
./pal --book my-book serve     # edit it in the browser
./pal                          # full command list
```

Book folders live under `./books/` when you run from a checkout; `./pal home <folder>`
points the workbench elsewhere.

## VS Code / Codespaces

Open the folder and **Reopen in Container** — the `.devcontainer` gives you a ready
environment; run `./pal serve` inside it and open the forwarded port 8137.

## The writing record

**[Hear one → caerjar.github.io/Palimpsest](https://caerjar.github.io/Palimpsest/)**

While you write in the reading copy, Palimpsest keeps a record of the typing
itself — every keystroke and the gap before it. The Writing Record page plays that
back three ways at once: the prose retyping itself, the same session drawn as
notation, and a synthesizer reading that notation aloud.

What you hear is the *act* of writing, not the text. The rhythm is the signal:
the pause before a difficult sentence, the burst when it finally comes, a
deletion arriving as a dashed descending phrase. Spaces and line breaks are
rests, because they already were.

The pitch material is yours to set, and it is real material rather than
decoration:

- **Tunings in cents**, not just the twelve equal semitones — 5-limit just
  intonation, seven-note Hindustani scale sets, an equipentatonic *slendro~*
  (the tilde is honest: real slendro is never equal).
- **Chords that stay in the scale.** Stack by scale-step and the harmony follows
  whatever tuning you chose; stack by semitone when you want fixed colour.
- **Instruments built from the harmonic series** — the organ is a 1:2:3 drawbar,
  the bell a 1:3:5 chime — with the usual dials for tone, vibrato, reverb and
  drones.

The notation is a four-line chant staff with graphic overlays, which suits a
score whose content is a session rather than a composition. Sound and staff are
generated from the same function, so what you see is what you hear.

Everything stays on your machine. The record is a plain `.jsonl` file in the
book's `dossier/` (see **Privacy & access** below), and the page loads it from
your own machine — no external host is ever contacted, and there is nothing to
sign in to. `just demo` bakes a session into a single HTML file that loads
nothing from outside — no fonts, no scripts, no images — which is what the link
above is: openable offline, or sendable as one attachment.

## How a book is laid out

```
<book>/
  book.toml          title, author, paths, which views to build
  manuscript/        001.md, 002.md, … — one file per section
  manifests/         structure you author in the UI (order, labels, parts)
  data/              motifs and the edit board — optional
  dossier/           generated HTML (rebuilt any time; not committed)
```

The authored files are the source of truth; `dossier/` is disposable and can be
rebuilt from them exactly. For how the pieces fit together, see
**[ARCHITECTURE.md](ARCHITECTURE.md)**.

## Privacy & access

Palimpsest makes no network calls and has no accounts, so your writing stays on
your machine. A few things worth knowing about the local server:

- **It binds to localhost, and only answers to localhost.** (In Docker it binds
  inside the container and the port is published to `127.0.0.1`.) Requests carrying
  another site's `Origin`, or addressed to another hostname, are refused — so a
  page open in another browser tab can't reach your book. That check stops a
  *browser*; it is not a password, and a script (`curl -H 'Host: localhost'`)
  satisfies it from anywhere that can reach the port. If you deliberately publish
  the port (a reverse proxy, a different Docker `ports:` line), list that hostname
  in `PAL_ALLOWED_HOSTS` (e.g. `PAL_ALLOWED_HOSTS=my-box.local:8137`) and put your
  own authentication in front of it: there is no login, so anything that can reach
  the port can read and rewrite the book. Starting on a non-loopback address
  prints a warning saying exactly this.
- **The writing record stores keystrokes.** That page logs typing to
  `dossier/keystrokes/*.jsonl` — a plain-text record of what you typed and when.
  Palimpsest never commits it (saves stage only the manuscript and your authored
  files), and a new book's `.gitignore` excludes `dossier/`, so your own commits
  skip it too. It's readable by anything that can read the folder; delete the
  files to clear it.
- **A book folder decides what gets read and written.** `book.toml` can point the
  manuscript, data and output anywhere, and can name a LaTeX header used for PDF
  export. Palimpsest warns at startup when a book points outside its own folder,
  and refuses a LaTeX header from outside it (`PAL_ALLOW_EXTERNAL_PATHS=1`
  overrides that for a header you wrote yourself). Treat a book someone sent you
  the way you'd treat any other file from them.
