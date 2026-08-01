"""Values from book.toml and from the browser that end up inside something.

A book.toml is just text and may have arrived with a book someone sent you
(config.py names that threat model explicitly), so the values it supplies are
pinned before they reach a filename, a LaTeX header, a style attribute, or a
JS string literal.
"""
import json
import unittest

from harness import Book, BookTestCase


class TestScriptJson(BookTestCase):
    """nav.script_json is the one sanctioned way to embed JSON in a <script>."""

    CODE = ("import json, sys, nav\n"
            "print(nav.script_json(json.load(sys.stdin)))")

    def embed(self, obj):
        return self.book.engine_eval(self.CODE, stdin=json.dumps(obj)).strip()

    def test_closes_no_tag(self):
        out = self.embed({"t": "</script><img src=x onerror=alert(1)>"})
        self.assertNotIn("</script", out.lower())
        self.assertIn("<\\/script", out)

    def test_value_is_unchanged_at_runtime(self):
        """`<\\/` is an escape JS resolves back to `</`, so the guard must not
        alter the value the page actually sees."""
        original = {"t": "</script>", "n": "plain", "u": "café — dash"}
        out = self.embed(original)
        self.assertEqual(json.loads(out.replace("<\\/", "</")), original)

    def test_non_ascii_survives(self):
        out = self.embed({"t": "café — dash"})
        self.assertIn("café", out)


class TestFontValidation(BookTestCase):
    """book.toml fonts are written raw into a LaTeX header, so they are rejected
    rather than escaped — a name is an identifier, not prose."""

    CODE = ("import json, sys, build_book\n"
            "print(json.dumps([build_book.safe_font(s) for s in json.load(sys.stdin)]))")

    def check(self, names):
        return json.loads(self.book.engine_eval(self.CODE, stdin=json.dumps(names)))

    def test_real_font_names_are_accepted(self):
        good = ["EB Garamond", "Iosevka Term", "Times New Roman", "Georgia",
                "Source Code Pro", "Noto-Serif_2"]
        self.assertEqual(self.check(good), good)

    def test_injection_is_rejected(self):
        bad = ["X}\\input{/etc/passwd}%",
               "Georgia}\\immediate\\write18{id}{",
               "a" * 200,
               "",
               "  ",
               "\\input{/etc/hostname}",
               "Font\nName"]
        self.assertEqual(self.check(bad), [None] * len(bad))


class TestSlugCannotEscapeTheBook(unittest.TestCase):
    """The export filename comes from book.toml's slug. SLUG is raw (a display
    and commit-message value); SAFE_SLUG is the scrubbed twin. Export paths must
    use the scrubbed one, or a slug of "../../x" writes outside the book."""

    HOSTILE = "../../../pwned"

    def setUp(self):
        self.book = Book().setup()
        toml = self.book.dir / "book.toml"
        text = toml.read_text(encoding="utf-8")
        self.assertIn("[book]", text)
        toml.write_text(text.replace("[book]", f'[book]\nslug = "{self.HOSTILE}"', 1),
                        encoding="utf-8")

    def tearDown(self):
        self.book.teardown()

    # Asserted positively — "no stray file appeared" is not checkable here: the
    # escape lands above the temp home, in the shared system temp dir, where debris
    # from any other run would be indistinguishable. That the output arrived where
    # it belongs is the same claim, and it is local to this book.
    #
    # A ".." inside the FILENAME (SAFE_SLUG turns "../../x" into "..-..-x") is
    # harmless — it carries no separator, so it cannot traverse. What matters is
    # the directory the file lands in.

    def test_export_stays_inside_the_book(self):
        self.book.pal("--book", self.book.slug, "export", "--format", "md")
        here = [p for p in self.book.dir.glob("*.md") if p.is_file()]
        self.assertTrue(here, "the markdown export was written outside the book")
        for p in here:
            self.assertEqual(p.resolve().parent, self.book.dir.resolve())

    def test_build_intermediate_lands_in_the_dossier(self):
        self.book.pal("--book", self.book.slug, "export", "--format", "pdf")
        here = list((self.book.dir / "dossier").glob("*.book.md"))
        self.assertTrue(here, "the PDF intermediate was written outside the dossier")
        for p in here:
            self.assertEqual(p.resolve().parent, (self.book.dir / "dossier").resolve())


class TestColourIsPinned(BookTestCase):
    """A colour lands in a style="…" attribute, so it can never be free text."""

    SERVER = True

    def test_hostile_colour_becomes_a_hex_literal(self):
        for hostile in ('red" onload="alert(1)',
                        "#000; background:url(javascript:alert(1))",
                        "</style><script>alert(1)</script>"):
            with self.subTest(colour=hostile):
                self.book.post_ok("/labels", {"labels": {
                    "001": [{"text": "x", "color": hostile}]}})
                stored = self.book.read_json("manifests/labels.json")
                self.assertRegex(stored["001"][0]["color"], r"^#[0-9A-Fa-f]{3,8}$")


if __name__ == "__main__":
    unittest.main()
