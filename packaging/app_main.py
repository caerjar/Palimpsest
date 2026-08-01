"""Entry point for the double-clickable macOS app (py2app bundles this).

A CLI user runs `pal build`, `pal serve`, etc. The .app has no command line, so
this does the sensible thing on launch: make sure the workbench has a book
(creating a starter on first run), build its views, then start the local server —
which opens the Library/reading copy in the browser. Everything else (new book,
import, switch book) happens from there.

The workbench for an installed app is ~/Documents/Palimpsest (library resolves
this because a bundle isn't a dev checkout), so all writes land in a normal,
user-owned folder — never inside the read-only .app.
"""
import sys

from palimpsest import cli


def main():
    cli._bundle_tools_on_path()          # put the bundled pandoc on PATH
    lib = cli.library()
    books = lib.books()
    if not books:                        # first launch: seed a starter manuscript
        lib.create("My Manuscript")
        books = lib.books()
    if not books:
        print("could not create a starter book", file=sys.stderr)
        return 1
    slug = books[0]["slug"]
    cli.main(["--book", slug, "build"])  # reflect the current app on every launch
    return cli.main(["--book", slug, "serve"])   # serves + opens the browser


if __name__ == "__main__":
    sys.exit(main())
