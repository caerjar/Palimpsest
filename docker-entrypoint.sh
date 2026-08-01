#!/bin/sh
# Container entrypoint: make sure the mounted workbench (/data) has at least one
# book, then serve it. Everything else — create / import / switch books — happens
# from the Library page in the browser.
set -e
cd /app

# One-off commands (`docker compose run pal <cmd>` / `just books|new|export|…`) are
# passed as arguments — run them and exit. With no arguments (`docker compose up`)
# we fall through to the serve flow below.
if [ "$#" -gt 0 ]; then
    exec "$@"
fi

first_book() {
    # first slug printed by `pal books` (skips the "books in …:" header line)
    pal books 2>/dev/null | awk 'NR>1 && $1 != "" { print $1; exit }'
}

BOOK="${PAL_BOOK:-$(first_book)}"
if [ -z "$BOOK" ]; then
    echo "empty workbench — creating a starter book…"
    pal new "My Manuscript" >/dev/null 2>&1 || true
    BOOK="$(first_book)"
fi

if [ -z "$BOOK" ]; then
    echo "could not create or find a book in /data — check the volume mount." >&2
    exit 1
fi

# Always rebuild the served book's views on startup, so a restarted container
# (e.g. after `just serve` picks up new code) reflects the current app — not a
# dossier some older image generated.
echo "building '$BOOK' with the current code…"
pal --book "$BOOK" build >/dev/null 2>&1 || true

echo "Palimpsest — serving '$BOOK' from ${PAL_HOME:-/data}"
exec pal --book "$BOOK" serve
