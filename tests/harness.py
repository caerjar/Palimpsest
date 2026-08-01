"""Shared fixtures: a disposable book, and a server driven over real HTTP.

Everything here runs against a throwaway workbench under a temp PAL_HOME, so the
suite never touches your real books and never leaves a stray commit — the
discipline CLAUDE.md already asks for, automated.

Subprocesses, not imports: `config` binds the active book at import time, so an
in-process test would have to re-import half the engine between cases. Running the
CLI and the server the way a user does keeps the tests honest about the contract.
"""
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PAL = [sys.executable, "-m", "palimpsest"]

# Optional external tools. Export tests skip rather than fail without them, so the
# suite still means something on a machine with no pandoc.
HAVE_PANDOC = shutil.which("pandoc") is not None
HAVE_GIT = shutil.which("git") is not None


def free_port():
    """An unused localhost port. Racy in principle; fine for a test runner."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Book:
    """A disposable book in a temp workbench.

    Use as a context manager, or call setup()/teardown() from a TestCase.
    """

    def __init__(self, name="Smoke Test", sections=None, git=False):
        self.name = name
        self.sections = sections or ["The first section.", "The second section."]
        self.git = git and HAVE_GIT
        self.home = None
        self.dir = None
        self.slug = None
        self._server = None

    # ---------------------------------------------------------------- lifecycle
    def setup(self):
        self.home = Path(tempfile.mkdtemp(prefix="pal-test-home-"))
        r = self.pal("new", self.name)
        if r.returncode != 0:
            raise RuntimeError(f"`pal new` failed:\n{r.stdout}\n{r.stderr}")
        # `pal new` slugifies the name the same way library.slugify does
        books = [d for d in self.home.iterdir() if (d / "book.toml").is_file()]
        if len(books) != 1:
            raise RuntimeError(f"expected one book in {self.home}, got {books}")
        self.dir = books[0]
        self.slug = self.dir.name
        self.write_sections(self.sections)
        if self.git:
            self._git_init()
        return self

    def teardown(self):
        self.stop_server()
        if self.home and self.home.exists():
            shutil.rmtree(self.home, ignore_errors=True)

    def __enter__(self):
        return self.setup()

    def __exit__(self, *exc):
        self.teardown()
        return False

    # ---------------------------------------------------------------- contents
    def write_sections(self, bodies):
        """Replace the manuscript with `bodies`, numbered from 001."""
        man = self.dir / "manuscript"
        for old in man.glob("[0-9]*.md"):
            old.unlink()
        for i, body in enumerate(bodies, start=1):
            (man / f"{i:03d}.md").write_text(f"# {i}\n\n{body}\n", encoding="utf-8")

    def _git_init(self):
        man = self.dir / "manuscript"
        for cmd in (["init", "-q"],
                    ["config", "user.email", "test@example.invalid"],
                    ["config", "user.name", "Palimpsest Tests"],
                    ["add", "-A"],
                    ["commit", "-qm", "initial"]):
            subprocess.run(["git", "-C", str(man)] + cmd,
                           capture_output=True, text=True, check=False)

    def read_dossier(self, name):
        return (self.dir / "dossier" / name).read_text(encoding="utf-8")

    def read_json(self, relpath):
        return json.loads((self.dir / relpath).read_text(encoding="utf-8"))

    # ---------------------------------------------------------------- commands
    def env(self, **extra):
        e = dict(os.environ)
        e["PAL_HOME"] = str(self.home)
        e["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + e.get("PYTHONPATH", "")
        e["PAL_NO_BROWSER"] = "1"
        e.pop("PAL_BOOK", None)
        e.update({k: str(v) for k, v in extra.items()})
        return e

    def pal(self, *args, timeout=180, **envextra):
        return subprocess.run(PAL + [str(a) for a in args],
                              cwd=str(REPO_ROOT), env=self.env(**envextra),
                              capture_output=True, text=True, timeout=timeout)

    def build(self):
        r = self.pal("--book", self.slug, "build")
        if r.returncode != 0:
            raise AssertionError(f"build failed:\n{r.stdout}\n{r.stderr}")
        return r

    def engine_eval(self, code, stdin="", **envextra):
        """Run `code` inside the engine with this book bound, return its stdout.

        engine/config.py resolves the active book AT IMPORT, so `import build_book`
        fails outright without one and the binding is process-global once it
        succeeds. That makes in-process unit testing of anything downstream of
        config impossible — so downstream units get tested in a child instead.
        """
        engine = REPO_ROOT / "palimpsest" / "engine"
        env = self.env(PAL_BOOK=str(self.dir), **envextra)
        env["PYTHONPATH"] = str(engine) + os.pathsep + env["PYTHONPATH"]
        r = subprocess.run([sys.executable, "-c", code], input=stdin,
                           cwd=str(engine), env=env,
                           capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            raise AssertionError(f"engine_eval failed:\n{r.stdout}\n{r.stderr}")
        return r.stdout

    # ---------------------------------------------------------------- server
    def start_server(self, wait=30, args=(), **envextra):
        """Start `pal serve` on a free port and block until it answers."""
        self.build()                       # serve does not build; give it a dossier
        self.port = free_port()
        self._extra_args = list(args)
        # start_new_session so the whole tree can be signalled at once: `pal serve`
        # does not become the server, it RUNS engine/save_server.py as a child
        # (cli.cmd_serve). Terminating just the `pal` process leaves that child
        # alive, holding the port and the stdout pipe — which silently accumulates
        # one orphaned server per test class.
        self._server = subprocess.Popen(
            PAL + ["--book", self.slug, "serve"] + self._extra_args,
            cwd=str(REPO_ROOT), env=self.env(PORT=self.port, **envextra),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            start_new_session=True)
        deadline = time.time() + wait
        while time.time() < deadline:
            if self._server.poll() is not None:
                out = self._server.stdout.read()
                raise RuntimeError(f"server exited early (rc={self._server.returncode}):\n{out}")
            try:
                self.get("/reading-copy.html")
                return self
            except Exception:
                time.sleep(0.15)
        raise RuntimeError(f"server did not come up on port {self.port} within {wait}s")

    def _signal_group(self, sig):
        """Signal the whole session — see the note in start_server."""
        try:
            os.killpg(os.getpgid(self._server.pid), sig)
        except (ProcessLookupError, PermissionError):
            self._server.send_signal(sig)     # already gone, or not our group

    def drain_server(self):
        """Stop the server and return everything it printed (stdout+stderr).

        Read after termination, not while running: the pipe would otherwise block
        waiting for output that may never come.
        """
        if not self._server:
            return ""
        self._signal_group(signal.SIGTERM)
        try:
            out = self._server.communicate(timeout=15)[0] or ""
        except subprocess.TimeoutExpired:
            self._signal_group(signal.SIGKILL)
            out = self._server.communicate(timeout=5)[0] or ""
        self._server = None
        return out

    def stop_server(self):
        if not self._server:
            return
        self._signal_group(signal.SIGTERM)
        try:
            self._server.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self._signal_group(signal.SIGKILL)
            self._server.wait(timeout=5)
        if self._server.stdout:
            self._server.stdout.close()
        self._server = None

    # ---------------------------------------------------------------- HTTP
    @property
    def origin(self):
        return f"http://127.0.0.1:{self.port}"

    def request(self, path, data=None, method=None, headers=None, want_origin=True):
        """Raw request. Returns (status, body). Never raises on 4xx/5xx.

        Defaults to a well-formed same-origin JSON write, so a test only has to
        state the thing it is subverting.
        """
        url = f"{self.origin}{path}"
        body = None
        h = {}
        if data is not None:
            body = json.dumps(data).encode() if not isinstance(data, bytes) else data
            h["Content-Type"] = "application/json"
        if want_origin:
            h["Origin"] = self.origin
        h.update(headers or {})
        req = urllib.request.Request(url, data=body, method=method or ("POST" if body else "GET"))
        for k, v in h.items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")
        except (urllib.error.URLError, ConnectionError, OSError) as e:
            # An oversized or malformed body can have the connection dropped rather
            # than answered. That is a refusal too — report it as one instead of
            # letting the test error out.
            return 0, f"connection refused/reset: {e}"

    def get(self, path, **kw):
        status, body = self.request(path, **kw)
        if status != 200:
            raise RuntimeError(f"GET {path} -> {status}")
        return body

    def post(self, path, data, **kw):
        """POST JSON. Returns (status, parsed-or-raw-body)."""
        status, body = self.request(path, data=data, **kw)
        try:
            return status, json.loads(body)
        except ValueError:
            return status, body

    def post_ok(self, path, data, **kw):
        """POST and assert the endpoint reported success."""
        status, body = self.post(path, data, **kw)
        if status != 200 or not (isinstance(body, dict) and body.get("ok")):
            raise AssertionError(f"POST {path} -> {status} {body!r}")
        return body


class BookTestCase(unittest.TestCase):
    """A TestCase with a built book. Set SERVER = True to also get a live server."""

    SERVER = False
    SECTIONS = None
    GIT = False

    @classmethod
    def setUpClass(cls):
        cls.book = Book(sections=cls.SECTIONS, git=cls.GIT).setup()
        if cls.SERVER:
            cls.book.start_server()
        else:
            cls.book.build()

    @classmethod
    def tearDownClass(cls):
        cls.book.teardown()
