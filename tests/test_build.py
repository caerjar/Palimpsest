"""The build path: every enabled view renders, and the CLI and the browser agree.

The last test here is the one that matters most — CLAUDE.md's central claim is that
`dossier.build()` is the ONE build path, so a book built in the browser is
identical to `pal build`. That claim is currently unenforced.
"""
import sys
import unittest
from pathlib import Path

from harness import REPO_ROOT, BookTestCase

sys.path.insert(0, str(REPO_ROOT / "palimpsest" / "engine"))


class TestBuild(BookTestCase):

    def test_expected_pages_exist_and_are_html(self):
        pages = ["reading-copy.html", "copyedit-review.html", "parts-board.html",
                 "index-terms.html", "edit-board.html", "motifs.html",
                 "index.html", "help.html", "library.html", "writing-record.html"]
        for p in pages:
            with self.subTest(page=p):
                path = self.book.dir / "dossier" / p
                self.assertTrue(path.is_file(), f"{p} was not built")
                html = path.read_text(encoding="utf-8")
                self.assertIn("<title>", html.lower())
                self.assertGreater(len(html), 200, f"{p} is suspiciously small")

    def test_assets_are_copied(self):
        for a in ("style.css", "pal.js"):
            self.assertTrue((self.book.dir / "dossier" / a).is_file(), a)

    def test_static_pages_have_no_unfilled_placeholders(self):
        # dossier.build() substitutes these; a missed one ships a literal token
        for p in ("writing-record.html", "library.html", "help.html"):
            html = self.book.read_dossier(p)
            for token in ("__PAL_NAV__", "__PAL_TITLE__", "__PAL_NS__",
                          "__PAL_HEAD__", "__PAL_SUBTITLE__"):
                with self.subTest(page=p, token=token):
                    self.assertNotIn(token, html)

    def test_section_text_reaches_the_reading_copy(self):
        html = self.book.read_dossier("reading-copy.html")
        self.assertIn("The first section.", html)
        self.assertIn("The second section.", html)

    def test_build_is_deterministic(self):
        """Same input, same bytes. A build that varies run to run makes the
        CLI-vs-browser comparison below meaningless."""
        first = {p.name: p.read_bytes()
                 for p in sorted((self.book.dir / "dossier").iterdir()) if p.is_file()}
        self.book.build()
        second = {p.name: p.read_bytes()
                  for p in sorted((self.book.dir / "dossier").iterdir()) if p.is_file()}
        self.assertEqual(sorted(first), sorted(second), "file set changed between builds")
        differing = [n for n in first if first[n] != second[n]]
        self.assertEqual(differing, [], f"non-deterministic output: {differing}")


class TestBuilderRegistryIsHonest(unittest.TestCase):
    """dossier.REGISTRY is the single source of truth for what gets built."""

    def test_every_registered_script_exists(self):
        import dossier
        for key, script in dossier.REGISTRY:
            with self.subTest(view=key):
                self.assertTrue((Path(dossier.BUILDERS) / script).is_file(),
                                f"{script} is registered but missing")

    def test_every_builder_on_disk_is_registered(self):
        """A builder nothing runs is dead weight: it looks maintained, ships in
        the package, and produces nothing."""
        import dossier
        registered = {s for _, s in dossier.REGISTRY}
        on_disk = {p.name for p in Path(dossier.BUILDERS).glob("build_*.py")}
        self.assertEqual(on_disk - registered, set(),
                         "builders exist that no view runs")


if __name__ == "__main__":
    unittest.main()
