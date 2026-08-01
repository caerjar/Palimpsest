"""CLAUDE.md's central claim, made testable.

    dossier.py — the ONE build path … cli & server both call dossier.build()
    so CLI and browser builds match

A second builder runner anywhere breaks it silently: whole-book builds and the
incremental rebuild after each save would drift apart, and the incremental path
is the one a writer hits on every keystroke. These assert the claim rather than
restating it.
"""
import unittest

from harness import Book, BookTestCase


class TestOneInterpreter(BookTestCase):
    """The server must spawn builders with dossier.child_python().

    sys.executable is the specific thing that helper exists to avoid: inside a
    py2app .app it is the app binary, so spawning it relaunches the application
    instead of running a builder. That is unreachable from CI on Linux, so it is
    asserted structurally instead.
    """

    def test_the_server_delegates_to_the_shared_runner(self):
        src = self.book.engine_eval(
            "import inspect, save_server;"
            "print(inspect.getsource(save_server.run_builder))")
        # the docstring names sys.executable to explain why it is wrong, so look at
        # the code after it rather than the whole source
        body = src.split('"""')[-1]
        self.assertIn("dossier.run_builder", body)
        self.assertNotIn("sys.executable", body)
        self.assertNotIn("subprocess.run", body, "the server still spawns its own")

    def test_there_is_one_builder_spawn_in_the_engine(self):
        """Exactly one place constructs a builder subprocess."""
        src = self.book.engine_eval(
            "import inspect, dossier, save_server;"
            "print(inspect.getsource(dossier) + inspect.getsource(save_server))")
        self.assertEqual(src.count("BUILDERS / script"), 1)
        self.assertNotIn("os.path.join(BUILDERS, script)", src)

    def test_the_cli_uses_it_too(self):
        from pathlib import Path
        cli = (Path(__file__).resolve().parent.parent / "palimpsest" / "cli.py"
               ).read_text(encoding="utf-8")
        self.assertNotIn("def _child_python", cli, "cli kept its own copy")
        self.assertIn("child_python()", cli)


class TestCliAndBrowserBuildsMatch(unittest.TestCase):
    """The claim itself: a book built by `pal build` and the same book rebuilt
    through the server's /rebuild must be byte-for-byte identical."""

    SECTIONS = ["First section, with a label.", "Second section.", "Third."]

    def setUp(self):
        self.book = Book(sections=self.SECTIONS).setup()

    def tearDown(self):
        self.book.teardown()

    def dossier_files(self):
        return sorted(p.name for p in (self.book.dir / "dossier").iterdir() if p.is_file())

    def test_rebuild_reproduces_the_cli_build(self):
        self.book.build()
        cli_state = {p.name: p.read_bytes()
                     for p in (self.book.dir / "dossier").iterdir() if p.is_file()}

        # authored state the browser can change, so the comparison is not trivial
        self.book.start_server()
        self.book.post_ok("/labels", {"labels": {
            "001": [{"text": "needs work", "color": "#aabbcc"}]}})
        self.book.post_ok("/parts", {"parts": [{"start": "002", "title": "Part Two"}]})
        self.book.post_ok("/rebuild", {})
        browser_state = {p.name: p.read_bytes()
                         for p in (self.book.dir / "dossier").iterdir() if p.is_file()}
        self.book.stop_server()

        # the browser changed things, so these must differ — otherwise the test
        # would pass on a server that silently did nothing
        self.assertNotEqual(cli_state, browser_state,
                            "the edits had no effect; this test would prove nothing")

        # now rebuild the SAME authored state on the CLI: it must land in the same place
        self.book.build()
        cli_again = {p.name: p.read_bytes()
                     for p in (self.book.dir / "dossier").iterdir() if p.is_file()}
        self.assertEqual(sorted(cli_again), sorted(browser_state),
                         "CLI and browser produced different files")
        differing = [n for n in cli_again if cli_again[n] != browser_state[n]]
        self.assertEqual(differing, [],
                         f"CLI and browser builds differ in: {differing}")


class TestBookSwitchStillWorks(unittest.TestCase):
    """/book-open replaces the process via exec. The reply is now flushed and the
    connection shut down first, instead of racing a 0.6s timer — so the client
    must still receive the answer, and the port must survive the restart."""

    def setUp(self):
        self.book = Book(name="First Book").setup()

    def tearDown(self):
        self.book.teardown()

    def test_switching_answers_then_restarts_on_the_new_book(self):
        second = self.book.pal("new", "Second Book")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.book.start_server()

        status, body = self.book.post("/book-open", {"slug": "second-book"})
        self.assertEqual(status, 200, f"the reply was lost across the exec: {body}")
        self.assertTrue(body.get("ok"), body)
        self.assertEqual(body.get("slug"), "second-book")

        # same port, now serving the other book
        import time
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                if "Second Book" in self.book.get("/reading-copy.html"):
                    return
            except Exception:
                pass
            time.sleep(0.2)
        self.fail("the server did not come back up on the new book")


if __name__ == "__main__":
    unittest.main()
