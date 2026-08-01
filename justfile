# Palimpsest — task runner. Everything runs inside the container, so the host
# only needs Docker + just. Don't have `just`? Each recipe shows the raw
# `docker compose` command it runs — copy that instead.
#
#   just            # list recipes
#   just serve      # build if needed, start the app, print the URL

set shell := ["bash", "-cu"]

# list the recipes
default:
    @just --list

# build/refresh the image
image:
    docker compose build

# start the app and print where to open it (rebuilds the image if code changed)
serve:
    docker compose up -d --build
    @echo ""
    @echo "  Palimpsest is running →  http://localhost:8137"
    @echo "  (hard-reload the browser — Cmd+Shift+R — to see UI changes)"
    @echo "  logs:  just logs      stop:  just stop"

# force a full refresh: rebuild the image AND recreate the container so the
# served book is regenerated with the current code. Use after editing the app.
rebuild:
    docker compose up -d --build --force-recreate
    @echo ""
    @echo "  Rebuilt → http://localhost:8137  (hard-reload the browser: Cmd+Shift+R)"

# start clean: archive the workbench (never deletes) and boot an empty one — asks first
fresh:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "This starts Palimpsest with an EMPTY workbench."
    echo "Your current books in ./workbench will be moved aside (not deleted)."
    read -r -p "Continue? [y/N] " ans
    if [ "$ans" != "y" ] && [ "$ans" != "Y" ]; then echo "cancelled — nothing changed"; exit 0; fi
    docker compose down
    bak=""
    if [ -d workbench ] && [ -n "$(ls -A workbench 2>/dev/null)" ]; then
        bak="workbench.bak-$(date +%Y%m%d-%H%M%S)"
        mv workbench "$bak"
        echo "→ your books are safe in ./$bak"
    fi
    docker compose up -d --build
    echo ""
    echo "  Fresh workbench → http://localhost:8137  (hard-reload: Cmd+Shift+R)"
    if [ -n "$bak" ]; then echo "  restore later:  just stop && rm -rf workbench && mv $bak workbench && just serve"; fi

# stop and remove the container (books stay on the host in ./workbench)
stop:
    docker compose down

# follow the server log
logs:
    docker compose logs -f pal

# open a shell inside the running container
shell:
    docker compose exec pal bash

# list the books in the workbench  (docker compose run --rm pal ... books)
books:
    docker compose run --rm --no-deps pal python3 -m palimpsest books

# create a new book:  just new "My Novel"
new name:
    docker compose run --rm --no-deps pal python3 -m palimpsest new "{{name}}"

# (re)build a book's views:  just build my-novel
build book:
    docker compose run --rm --no-deps pal python3 -m palimpsest --book "{{book}}" build

# build the standalone Writing Record demo page (host-side python3; no Docker).
# Writes docs/index.html — what GitHub Pages publishes. Commit it with any change
# to the Writing Record page, or the live demo drifts from the app.
demo:
    python3 demo/build_demo.py
    @echo ""
    @echo "  open docs/index.html   — one file, no server, no network"
    @echo "  live:  https://caerjar.github.io/Palimpsest/"

# run the test suite (host-side python3; no Docker — the suite makes its own
# throwaway workbench under a temp PAL_HOME, so it never touches ./workbench).
# Needs pandoc for the export + LaTeX-escaping cases; they skip without it.
test:
    python3 -m unittest discover -s tests -v

# lint (needs ruff: `pipx install ruff` / `uvx ruff`). Config in pyproject.toml.
lint:
    ruff check .

# just one file or case:  just test-one test_escaping
#                         just test-one test_escaping.TestLatexEscaping
test-one target:
    cd tests && python3 -m unittest "{{target}}" -v

# export a book:  just export my-novel docx   (format = pdf|docx|html|md)
export book format="pdf":
    docker compose run --rm --no-deps pal python3 -m palimpsest --book "{{book}}" export -f "{{format}}"
    @echo "→ wrote to ./workbench/{{book}}/  (on the host)"
