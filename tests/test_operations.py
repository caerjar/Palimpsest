"""Running the thing: what it warns about, and what it tells you when it breaks.

The server answers {ok:false,error} rather than raising, and prints nothing per
request. Both are deliberate, and together they can leave a failure with no trace
at all — a builder stops working and the only symptom is a page that quietly stops
changing. These assert the trace exists.
"""
import json
import unittest

from harness import Book, BookTestCase


class TestBindWarning(BookTestCase):
    """PAL_BIND=0.0.0.0 is correct in a container — a process must bind all
    interfaces to be reachable through `docker run -p`. What keeps it safe is the
    published port being loopback-only, which the process cannot see. So it warns
    rather than refuses; refusing would break the documented reverse-proxy case.
    """

    CODE = ("import json, sys, save_server\n"
            "print(json.dumps([save_server.bind_warning(b, a) "
            "for b, a in json.load(sys.stdin)]))")

    def warnings_for(self, cases):
        return json.loads(self.book.engine_eval(self.CODE, stdin=json.dumps(cases)))

    def test_loopback_binds_are_silent(self):
        quiet = [["127.0.0.1", ""], ["::1", ""], ["localhost", ""], ["", ""]]
        self.assertEqual(self.warnings_for(quiet), [""] * len(quiet))

    def test_public_bind_warns(self):
        [msg] = self.warnings_for([["0.0.0.0", ""]])
        self.assertTrue(msg, "binding all interfaces produced no warning")
        self.assertIn("no login", msg)
        # must be explicit that the origin gate is not authentication
        self.assertIn("does not stop a script", msg)

    def test_public_bind_still_warns_when_deliberate(self):
        """PAL_ALLOWED_HOSTS means you meant to expose it — worth acknowledging,
        not worth going quiet about."""
        [msg] = self.warnings_for([["0.0.0.0", "my-box.local:8137"]])
        self.assertTrue(msg)
        self.assertIn("deliberate", msg)


class TestQuietByDefault(BookTestCase):
    SERVER = True

    def test_no_request_log_by_default(self):
        """A line per asset request would bury the one message that matters."""
        self.book.get("/reading-copy.html")
        self.book.post_ok("/labels", {"labels": {"001": [{"text": "x", "color": "#ccc"}]}})
        out = self.book.drain_server()
        self.assertNotIn("GET /reading-copy.html", out)
        self.assertIn("edit+save server", out, "the startup banner should still print")


class TestVerboseLogging(unittest.TestCase):
    """PAL_LOG=debug turns the polite 400s into something you can debug."""

    def setUp(self):
        self.book = Book().setup()
        self.book.start_server(PAL_LOG="debug")

    def tearDown(self):
        self.book.teardown()

    def test_rejected_write_is_logged(self):
        self.book.post("/save", {"section": "../../etc/passwd", "text": "x"})
        out = self.book.drain_server()
        self.assertIn("/save", out)
        self.assertIn("400", out)

    def test_requests_are_logged(self):
        self.book.get("/reading-copy.html")
        out = self.book.drain_server()
        self.assertIn("reading-copy.html", out)


class TestVerboseFlagReachesTheServer(unittest.TestCase):
    """`pal serve` runs the server as a child rather than becoming it, so a flag
    on the CLI reaches it only if cmd_serve passes it along. It is documented in
    `pal`'s own help, so it has to actually work."""

    def test_verbose_flag_turns_on_the_request_log(self):
        book = Book().setup()
        try:
            book.start_server(args=["--verbose"])
            book.get("/reading-copy.html")
            out = book.drain_server()
            self.assertIn("reading-copy.html", out,
                          "--verbose did not reach the server process")
        finally:
            book.teardown()


class TestServerActuallyStops(unittest.TestCase):
    """A harness self-check.

    `pal serve` RUNS engine/save_server.py as a child rather than becoming it, so
    signalling the `pal` process alone leaves the real server holding the port and
    the stdout pipe — one orphan per server-using test class, silently. The
    harness signals the whole session; this proves it worked.
    """

    def test_the_port_is_released(self):
        import socket
        book = Book().setup()
        try:
            book.start_server()
            port = book.port
            book.get("/reading-copy.html")          # definitely alive
            book.stop_server()
            with socket.socket() as s:
                s.settimeout(5)
                self.assertNotEqual(
                    s.connect_ex(("127.0.0.1", port)), 0,
                    "something is still listening — the server outlived stop_server()")
        finally:
            book.teardown()


class TestRenderTimeoutIsBounded(BookTestCase):
    """/export is unauthenticated and threaded with no concurrency cap, so an
    unbounded pandoc run is a way to pin the machine."""

    CODE = "import build_book; print(build_book.RENDER_TIMEOUT)"

    def timeout(self, **env):
        return int(self.book.engine_eval(self.CODE, **env).strip())

    def test_a_bounded_default_exists(self):
        self.assertEqual(self.timeout(), 900)

    def test_env_overrides_it(self):
        """A genuinely enormous book must have an escape hatch, or the fix for a
        denial of service becomes one."""
        self.assertEqual(self.timeout(PAL_RENDER_TIMEOUT="1800"), 1800)

    def test_the_timeout_is_actually_passed_to_pandoc(self):
        """Naming a constant is not the same as using it."""
        src = (self.book.engine_eval(
            "import inspect, build_book; print(inspect.getsource(build_book))"))
        self.assertEqual(src.count("timeout=RENDER_TIMEOUT"), 2,
                         "both pandoc invocations must carry the timeout")


if __name__ == "__main__":
    unittest.main()
