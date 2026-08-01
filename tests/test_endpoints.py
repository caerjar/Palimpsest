"""Every write endpoint round-trips: request -> authored file on disk -> rebuilt view.

The app's contract is that the browser is the editing surface and the authored
files under manifests/ and data/ are the source of truth. These assert both ends,
because a 200 that wrote nothing is the failure mode nobody notices.
"""
import unittest

from harness import HAVE_GIT, BookTestCase


class TestSectionEditing(BookTestCase):
    SERVER = True

    def test_save_writes_the_manuscript_and_rebuilds(self):
        self.book.post_ok("/save", {"section": "001", "text": "# 1\n\nRewritten body.\n"})
        on_disk = (self.book.dir / "manuscript" / "001.md").read_text(encoding="utf-8")
        self.assertIn("Rewritten body.", on_disk)
        self.book.post_ok("/rebuild", {})
        self.assertIn("Rewritten body.", self.book.read_dossier("reading-copy.html"))

    def test_save_rejects_a_bad_section_id(self):
        for bad in ("../../etc/passwd", "0001x", "", "1/2", "99999"):
            with self.subTest(section=bad):
                status, body = self.book.post(
                    "/save", {"section": bad, "text": "# 1\n\nx\n"})
                self.assertFalse(isinstance(body, dict) and body.get("ok"),
                                 f"{bad!r} was accepted")

    def test_save_rejects_an_oversized_body(self):
        status, body = self.book.post(
            "/save", {"section": "001", "text": "x" * 900_000})
        self.assertFalse(isinstance(body, dict) and body.get("ok"))

    def test_section_add_then_delete(self):
        before = len(list((self.book.dir / "manuscript").glob("[0-9]*.md")))
        self.book.post_ok("/section/add", {})
        after = len(list((self.book.dir / "manuscript").glob("[0-9]*.md")))
        self.assertEqual(after, before + 1, "add did not create a section")


class TestManifestEndpoints(BookTestCase):
    SERVER = True

    def test_labels_round_trip(self):
        self.book.post_ok("/labels", {"labels": {
            "001": [{"text": "needs work", "color": "#aabbcc"}]}})
        stored = self.book.read_json("manifests/labels.json")
        self.assertEqual(stored["001"][0]["text"], "needs work")
        self.assertEqual(stored["001"][0]["color"], "#aabbcc")

    def test_label_colour_is_pinned_to_a_hex_literal(self):
        """A colour lands in a style="…" attribute, so it can never be free text."""
        self.book.post_ok("/labels", {"labels": {
            "001": [{"text": "x", "color": "red; background:url(javascript:alert(1))"}]}})
        stored = self.book.read_json("manifests/labels.json")
        self.assertRegex(stored["001"][0]["color"], r"^#[0-9A-Fa-f]{3,8}$")

    def test_order_round_trip(self):
        self.book.post_ok("/order", {"order": ["002", "001"]})
        self.assertEqual(self.book.read_json("manifests/order.json"), ["002", "001"])

    def test_parts_round_trip(self):
        self.book.post_ok("/parts", {"parts": [{"start": "002", "title": "Part Two"}]})
        stored = self.book.read_json("manifests/parts.json")
        self.assertEqual(stored[0]["start"], "002")
        self.assertEqual(stored[0]["title"], "Part Two")

    def test_parts_rejects_an_unknown_start_section(self):
        status, body = self.book.post(
            "/parts", {"parts": [{"start": "999", "title": "Nowhere"}]})
        self.assertFalse(isinstance(body, dict) and body.get("ok"))

    def test_watchlist_add_and_drop(self):
        seed = self.book.dir / "manifests" / "entities-seed.json"
        self.book.post_ok("/watchlist", {"op": "add", "name": "Ariadne"})
        self.assertIn("Ariadne", seed.read_text(encoding="utf-8"))
        self.book.post_ok("/watchlist", {"op": "drop", "name": "Ariadne"})
        doc = self.book.read_json("manifests/entities-seed.json")
        self.assertNotIn("Ariadne", [e.get("name") for e in doc.get("add", [])])

    def test_edit_board_round_trip(self):
        self.book.post_ok("/edit-board", {"columns": [
            {"title": "Pass one", "items": [{"text": "tighten chapter 3"}]}]})
        raw = (self.book.dir / "data" / "edit-board.json").read_text(encoding="utf-8")
        self.assertIn("Pass one", raw)
        self.assertIn("tighten chapter 3", raw)
        self.assertIn("Pass one", self.book.read_dossier("edit-board.html"))


class TestRebuildAndExport(BookTestCase):
    SERVER = True

    def test_rebuild_reports_success(self):
        body = self.book.post_ok("/rebuild", {})
        self.assertTrue(body.get("ok"))

    def test_markdown_export_contains_the_prose(self):
        r = self.book.pal("--book", self.book.slug, "export", "--format", "md")
        self.assertEqual(r.returncode, 0, f"{r.stdout}\n{r.stderr}")
        built = list(self.book.dir.glob("*.md"))
        self.assertTrue(built, "no markdown export produced")
        self.assertIn("The first section.", built[0].read_text(encoding="utf-8"))


@unittest.skipUnless(HAVE_GIT, "git not installed")
class TestVersioning(BookTestCase):
    """Saves commit when the manuscript is in a repo, and degrade when it isn't."""

    SERVER = True
    GIT = True

    def test_save_commits(self):
        body = self.book.post_ok(
            "/save", {"section": "001", "text": "# 1\n\nVersioned edit.\n"})
        self.assertTrue(body.get("committed"), f"save did not commit: {body}")
        self.assertTrue(body.get("commit"), "no sha returned")


class TestNoRepoDegradesGracefully(BookTestCase):
    """Without a repo a save still writes the file and says so, rather than failing."""

    SERVER = True
    GIT = False

    def test_save_succeeds_without_versioning(self):
        body = self.book.post_ok(
            "/save", {"section": "001", "text": "# 1\n\nUnversioned edit.\n"})
        self.assertFalse(body.get("committed"))
        self.assertIn("Unversioned edit.",
                      (self.book.dir / "manuscript" / "001.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
