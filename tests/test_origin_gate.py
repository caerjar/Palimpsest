"""The origin gate.

There are no accounts and no tokens: Host, Origin and Content-Type ARE the
security model, so each gets a case in both directions. Weaken any one of them
and cross-site POSTs, DNS rebinding, or a form-encoded write compose into
same-origin manuscript exfiltration.

Treat a failure here as a security regression, not a flaky test.
"""
import unittest

from harness import BookTestCase

WRITE = "/labels"
PAYLOAD = {"labels": {"001": [{"text": "ok", "color": "#cccccc"}]}}


class TestOriginGate(BookTestCase):
    SERVER = True

    def assertRefused(self, status, body, why):
        self.assertNotEqual(status, 200, f"{why}: request was ACCEPTED")
        if isinstance(body, dict):
            self.assertFalse(body.get("ok"), f"{why}: endpoint reported ok")

    # ------------------------------------------------------------- must pass
    def test_same_origin_json_write_is_accepted(self):
        """The intended client. If this breaks, the app is broken."""
        self.book.post_ok(WRITE, PAYLOAD)

    def test_terminal_client_without_origin_is_accepted(self):
        """curl and scripts send no Origin and must keep working — the gate is
        aimed at other people's web pages, not at the user's own shell."""
        self.book.post_ok(WRITE, PAYLOAD, want_origin=False)

    def test_loopback_host_variants_are_accepted(self):
        for host in (f"127.0.0.1:{self.book.port}", f"localhost:{self.book.port}"):
            with self.subTest(host=host):
                status, body = self.book.post(WRITE, PAYLOAD, headers={"Host": host})
                self.assertEqual(status, 200, f"{host} should be allowed")

    def test_remapped_port_is_accepted(self):
        """A container publishing 9000:8137 changes the port, not the name — the
        gate compares hostnames without the port on purpose."""
        status, _ = self.book.post(WRITE, PAYLOAD, headers={"Host": "127.0.0.1:9000"})
        self.assertEqual(status, 200)

    # ------------------------------------------------------------- must fail
    def test_dns_rebinding_host_is_refused(self):
        """A hostile name resolving to 127.0.0.1 reads the book through the
        user's own browser unless Host is checked."""
        status, body = self.book.post(WRITE, PAYLOAD, headers={"Host": "evil.example.com"})
        self.assertRefused(status, body, "rebound Host")

    def test_cross_site_origin_is_refused(self):
        status, body = self.book.post(
            WRITE, PAYLOAD, headers={"Origin": "http://evil.example.com"})
        self.assertRefused(status, body, "foreign Origin")

    def test_null_origin_is_refused(self):
        """A sandboxed iframe or a data: URL sends Origin: null."""
        status, body = self.book.post(WRITE, PAYLOAD, headers={"Origin": "null"})
        self.assertRefused(status, body, "Origin: null")

    def test_simple_content_types_are_refused_on_writes(self):
        """The three CORS-safelisted types are exactly what a cross-site <form>
        or a no-cors fetch can send without a preflight we never answer."""
        for ctype in ("text/plain", "application/x-www-form-urlencoded",
                      "multipart/form-data"):
            with self.subTest(content_type=ctype):
                status, body = self.book.post(
                    WRITE, PAYLOAD, headers={"Content-Type": ctype})
                self.assertRefused(status, body, ctype)

    def test_gate_covers_every_write_endpoint(self):
        """One unguarded route is the whole hole, so assert the gate is global
        rather than trusting it was applied route by route."""
        routes = ["/save", "/labels", "/order", "/parts", "/unnumbered",
                  "/watchlist", "/edit-board", "/motifs", "/rebuild",
                  "/book-new", "/book-open", "/section/add", "/section/delete"]
        for route in routes:
            with self.subTest(route=route):
                status, body = self.book.post(
                    route, {}, headers={"Origin": "http://evil.example.com"})
                self.assertRefused(status, body, f"{route} with foreign Origin")

    def test_refusal_does_not_leak_filesystem_paths(self):
        """Error text is scrubbed of absolute paths — a caller that shouldn't be
        here doesn't need a map of the disk."""
        _, body = self.book.post(WRITE, PAYLOAD, headers={"Origin": "http://evil.example.com"})
        text = body if isinstance(body, str) else repr(body)
        self.assertNotIn(str(self.book.home), text)
        self.assertNotIn(str(self.book.dir), text)


if __name__ == "__main__":
    unittest.main()
