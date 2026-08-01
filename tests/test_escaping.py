r"""Authored text must not become markup or LaTeX.

Two sinks, each with its own failure mode:

  <script> embeds  A JSON value containing "</script>" ends the tag early and
      everything after it is parsed as markup. That payload then runs on
      http://127.0.0.1:PORT, so its own fetch() calls carry a valid Origin and
      satisfy every check in test_origin_gate.py — the gate cannot help once the
      attacker is inside the origin it protects. Every embed goes through
      nav.script_json().

  XeLaTeX  pandoc runs with raw_tex on (the assembled document needs it), and
      TeX Live's openin_any=a makes \input an arbitrary-file read whose contents
      land in the exported PDF. build_book.clean() must leave no backslash able
      to open a control word.
"""
import json
import re
import unittest

from harness import HAVE_PANDOC, BookTestCase
from payloads import (ALL_HOSTILE, BENIGN, LATEX, MARKUP, SCRIPT_BREAKOUT,
                      latex_is_live)

SCRIPT_BLOCK = re.compile(r"<script\b[^>]*>(.*?)</script\s*>", re.S | re.I)


def script_bodies(html):
    """The contents of every inline <script> block."""
    return [m.group(1) for m in SCRIPT_BLOCK.finditer(html)]


class EscapingAsserts:

    def assertNoTagBreakout(self, html, payload, where):
        """No payload may introduce a tag the page did not intend.

        Two separate invariants, because they have different remedies:
          - inside a <script>, the only thing that matters is `</script`, since
            everything else is inert within a JS string literal;
          - outside, hostile markup must arrive HTML-escaped.
        """
        # A payload containing "</" can only reach the page verbatim if nothing
        # guarded it: a <script> embed must rewrite it to "<\/", and any markup
        # context must HTML-escape it to "&lt;/". Checking for the verbatim string
        # catches both, and unlike scanning inside <script> bodies it still works
        # when the payload's own </script> is what terminated the block.
        if "</" in payload:
            self.assertNotIn(payload, html,
                             f"{where}: payload reached the page unescaped")
        for body in script_bodies(html):
            self.assertNotIn("</script", body.lower(),
                             f"{where}: payload closed its <script> block early")
        markup_only = SCRIPT_BLOCK.sub("<script></script>", html).lower()
        for probe in ("<img src=x", "<svg onload=", "<script>alert("):
            if probe in payload.lower():
                self.assertNotIn(probe, markup_only,
                                 f"{where}: {probe!r} survived unescaped in markup")


class TestScriptEmbedEscaping(BookTestCase, EscapingAsserts):
    """Every JSON blob embedded in a <script> needs the `</` guard."""

    SERVER = True

    def test_labels_cannot_break_out_of_the_script_block(self):
        for payload in SCRIPT_BREAKOUT + MARKUP:
            with self.subTest(payload=payload):
                self.book.post_ok("/labels", {"labels": {
                    "001": [{"text": payload, "color": "#cccccc"}]}})
                self.book.post_ok("/rebuild", {})
                for page in ("copyedit-review.html", "reading-copy.html"):
                    html = self.book.read_dossier(page)
                    self.assertNoTagBreakout(html, payload, f"{page} via /labels")

    def test_part_banner_titles_cannot_break_out(self):
        """The HTTP-reachable half: /parts writes manifests/parts.json."""
        for payload in SCRIPT_BREAKOUT:
            with self.subTest(payload=payload):
                self.book.post_ok("/parts", {"parts": [
                    {"start": "002", "title": payload}]})
                self.book.post_ok("/rebuild", {})
                html = self.book.read_dossier("parts-board.html")
                self.assertNoTagBreakout(html, payload, "parts-board via /parts")

    def test_part_divider_titles_cannot_break_out(self):
        """The other half: part-dividers.json has no endpoint, so it is only
        reachable by hand-editing a manifest — or by opening a book folder someone
        sent you, which config.py:105 names as in scope. build_parts_board.py
        embeds these titles in a <script> with no `</` guard.
        """
        seed = self.book.dir / "manifests" / "part-dividers.json"
        for payload in SCRIPT_BREAKOUT:
            with self.subTest(payload=payload):
                seed.write_text(json.dumps([{"id": "002", "title": payload}]),
                                encoding="utf-8")
                self.book.build()
                self.assertNoTagBreakout(self.book.read_dossier("parts-board.html"),
                                         payload, "parts-board via part-dividers.json")

    def test_watchlist_terms_cannot_break_out(self):
        for payload in SCRIPT_BREAKOUT:
            with self.subTest(payload=payload):
                self.book.post_ok("/watchlist", {"op": "add", "name": payload})
                html = self.book.read_dossier("index-terms.html")
                self.assertNoTagBreakout(html, payload, "index-terms via /watchlist")

    def test_edit_board_items_cannot_break_out(self):
        for payload in SCRIPT_BREAKOUT:
            with self.subTest(payload=payload):
                self.book.post_ok("/edit-board", {"columns": [
                    {"title": payload, "items": [{"text": payload}]}]})
                html = self.book.read_dossier("edit-board.html")
                self.assertNoTagBreakout(html, payload, "edit-board")


class TestSectionTextEscaping(BookTestCase, EscapingAsserts):
    """Manuscript prose is authored text too, and it reaches every view."""

    SERVER = True

    def test_section_body_cannot_inject_markup(self):
        for payload in SCRIPT_BREAKOUT + MARKUP:
            with self.subTest(payload=payload):
                self.book.post_ok("/save", {"section": "001", "text": f"# 1\n\n{payload}\n"})
                self.book.post_ok("/rebuild", {})
                for page in ("reading-copy.html", "copyedit-review.html"):
                    self.assertNoTagBreakout(
                        self.book.read_dossier(page), payload, f"{page} via /save")


@unittest.skipUnless(HAVE_PANDOC, "pandoc not installed")
class TestLatexEscaping(BookTestCase):
    """No author prose may reach XeLaTeX as an executable control word.

    Unit-level against build_book.clean(), via engine_eval because config binds
    the active book at import (see harness.Book.engine_eval).
    """

    CLEAN = ("import sys, json, build_book\n"
             "print(json.dumps([build_book.clean(s) for s in json.load(sys.stdin)]))")

    def cleaned(self, texts):
        import json
        return json.loads(self.book.engine_eval(self.CLEAN, stdin=json.dumps(texts)))

    def to_latex(self, markdown):
        """Through the exact reader build_book.py uses."""
        import subprocess
        r = subprocess.run(["pandoc", "-f", "markdown+smart", "-t", "latex"],
                           input=markdown, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_control_words_are_never_live(self):
        for payload, escaped in zip(LATEX, self.cleaned(LATEX), strict=True):
            with self.subTest(payload=payload):
                rendered = self.to_latex(escaped)
                self.assertFalse(
                    latex_is_live(rendered),
                    f"{payload!r} -> clean() {escaped!r} -> survived as "
                    f"executable LaTeX: {rendered!r}")

    def test_benign_prose_survives(self):
        """An escaper that mangles ordinary writing is not a fix."""
        for text, escaped in zip(BENIGN, self.cleaned(BENIGN), strict=True):
            with self.subTest(text=text):
                rendered = self.to_latex(escaped)
                self.assertNotEqual(rendered.strip(), "", f"{text!r} was erased")
                self.assertFalse(latex_is_live(rendered))

    def test_hard_line_breaks_are_preserved(self):
        out = self.cleaned(["line one\nline two"])[0]
        self.assertIn("  \n", out, "author line breaks must become markdown breaks")

    def test_pdf_assembly_contains_no_live_control_words(self):
        """End-to-end over the LaTeX path.

        `<slug>.book.md` in the dossier is the exact text handed to pandoc for the
        PDF, so asserting on it covers assembly as well as clean() — and it is
        written before pandoc runs, so this needs no XeLaTeX.

        Deliberately NOT the markdown export: that path uses _clean_md(), which
        skips LaTeX escaping on purpose because its output is portable Markdown
        that never reaches TeX.
        """
        self.book.write_sections(
            ["Ordinary prose.\n\n\\\\input{/etc/hostname}\n",
             "More prose.\n\n\\input{/etc/hostname}\n"])
        self.book.pal("--book", self.book.slug, "export", "--format", "pdf")
        intermediate = list((self.book.dir / "dossier").glob("*.book.md"))
        self.assertTrue(intermediate, "the PDF path wrote no .book.md intermediate")
        text = intermediate[0].read_text(encoding="utf-8")
        self.assertFalse(
            latex_is_live(text),
            f"live LaTeX reached the PDF assembly:\n{text}")


class TestPayloadsRoundTripAsText(BookTestCase):
    """Whatever the escaping does, the author must get their text back."""

    SERVER = True

    def test_labels_survive_a_round_trip(self):
        for payload in ALL_HOSTILE:
            with self.subTest(payload=payload):
                self.book.post_ok("/labels", {"labels": {
                    "001": [{"text": payload, "color": "#cccccc"}]}})
                stored = self.book.read_json("manifests/labels.json")
                self.assertEqual(stored["001"][0]["text"], payload[:80],
                                 "stored text should be the author's, only length-capped")


if __name__ == "__main__":
    unittest.main()
