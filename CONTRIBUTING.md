# Contributing to Palimpsest

Thanks for your interest. Palimpsest is a small, deterministic, dependency-light
tool; contributions that keep it that way are very welcome.

## Principles

- **Deterministic, offline.** Nothing in the app calls a model or the
  network; a user's writing never leaves their machine. Please don't add LLM/AI
  dependencies or AI-referencing UI text.
- **Standard library first.** The core is pure Python 3.11+ (stdlib only). Optional
  features may use external tools (git, pandoc, XeLaTeX, PyMuPDF) but must **degrade
  gracefully** when they're absent.
- **Edit in the browser.** Prefer features that write the book's own files and are
  usable from `pal serve`, over ones that require hand-editing JSON or a terminal.

## Getting set up

```bash
./pal new "Test Book"      # scaffold a book in ./books
./pal --book test-book serve   # edit it in the browser
```

Or run everything in a container: `just serve` (see `README.md`).

## Making a change

- Builders are Python files that emit HTML into a book's `dossier/`; match the
  surrounding style (f-strings; double every literal `{`/`}` inside them). See
  `AI_ASSISTANT.md` for the architecture and conventions.
- There's no formal test suite yet. Verify a change by building a book
  (`pal build`) and, for server changes, exercising the endpoint against a
  throwaway book (`PAL_HOME=/tmp/wb ./pal new … ; ./pal --book … serve`).
- Keep `dossier/` (generated), exports, and personal books out of commits — the
  `.gitignore` already handles this.

## Pull requests

Small, focused PRs with a clear description are easiest to review. Please note how
you verified the change.
