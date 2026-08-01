#!/usr/bin/env python3
"""Local edit+save server for the active book's reading copy.

Serves the book's dossier and accepts POST /save to write a section back to
its manuscript/NNN.md and — when the manuscript lives in a git repo — commit
it, so every save is a version you can browse with `git log` / `git checkout`.
Binds to 127.0.0.1 only.

  pal serve           # or: PAL_BOOK=<book dir> python3 save_server.py
                     # (PORT env overrides 8137)

Every path below comes from the active book (config.py), so this serves any
book without edits. A manuscript outside a git repo still saves fine; the
history/restore features simply report that there is nothing to browse.
"""
import http.server, socketserver, json, logging, os, re, socket, subprocess, webbrowser, glob, urllib.parse, sys, threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
import dossier
import sections                        # the ONE build path — run_builder / build
import library
import build_book as pdf_engine       # the PDF assembler/renderer (aliased: a local
                                      # build_book() helper below builds dossiers)

# ---------------------------------------------------------------- logging
# Every endpoint answers {ok:false,error} rather than raising a 500 — that is a
# deliberate contract and the page depends on it. The cost is that a real bug and
# a malformed request look identical from the outside, so the exception is logged
# even when the reply is polite. Quiet by default (this is someone's writing desk,
# not a service); PAL_LOG=debug or `pal serve --verbose` turns on the detail and
# the request log.
LOG = logging.getLogger("pal")


def _init_logging():
    level = os.environ.get("PAL_LOG", "warning").strip().lower()
    levels = {"debug": logging.DEBUG, "info": logging.INFO,
              "warning": logging.WARNING, "error": logging.ERROR}
    logging.basicConfig(format="pal: %(levelname)s %(message)s",
                        level=levels.get(level, logging.WARNING))
    return levels.get(level, logging.WARNING)


def _verbose():
    return LOG.isEnabledFor(logging.DEBUG)


ENGINE = os.path.dirname(os.path.abspath(__file__))
BUILDERS = os.path.join(ENGINE, "builders")
DOSSIER = config.ensure_out()                 # generated HTML: what we serve
MAN = config.MANUSCRIPT                       # the sections themselves
SUGG = config.SUGGESTIONS                     # copyedit suggestions
RUBRIC = config.RUBRIC                        # copyedit rubric (single source of truth)
SLUG = config.SLUG                            # short book name, used in commit messages
ATTIC = os.path.join(MAN, "_attic")           # soft-deleted sections (reversible; git-tracked)
KEYS = os.path.join(DOSSIER, "keystrokes")    # writing-record JSONL logs (gitignored, local-only)
_MF = config.MANIFESTS                        # authored structure lives with the book, not the dossier
ORDER_JSON = os.path.join(_MF, "order.json")           # section display-order manifest (authored)
LABELS_JSON = os.path.join(_MF, "labels.json")         # section labels (authored)
PARTS_JSON = os.path.join(_MF, "parts.json")           # part-break definitions (authored)
UNNUMBERED_JSON = os.path.join(_MF, "unnumbered.json") # sections that print but aren't numbered
HELD_JSON = os.path.join(_MF, "held.json")             # parked sections (out of flow, kept on disk)
os.makedirs(_MF, exist_ok=True)
os.makedirs(SUGG, exist_ok=True)     # so accept / mark-done work on a book that has no suggestions yet


def _find_repo():
    """The git repo holding the manuscript, or None — versioning is optional.

    `git = false` in book.toml opts out entirely; otherwise a manuscript that
    simply isn't in a repo degrades to plain file writes."""
    if not config.GIT:
        return None
    try:
        r = subprocess.run(["git", "-C", MAN, "rev-parse", "--show-toplevel"],
                           capture_output=True, text=True)
        return r.stdout.strip() or None if r.returncode == 0 else None
    except Exception:
        return None


REPO = _find_repo()
PORT = int(os.environ.get("PORT", "8137"))


# ---------------------------------------------------------------- git layer
# All versioning goes through these. Without a repo they no-op truthfully, so
# a save still writes the file and the page reports "saved, not versioned"
# instead of failing.
def git_rel(p) -> str:
    return os.path.relpath(p, REPO)


def git_commit(paths, msg) -> tuple[bool, str]:
    """Stage `paths` and commit -> (committed: bool, short sha: str).

    (False, "") when there is no repo — versioning is optional."""
    if not REPO:
        return False, ""
    try:
        for p in paths:
            subprocess.run(["git", "-C", REPO, "add", "-A", "--", git_rel(p)], check=True)
        r = subprocess.run(["git", "-C", REPO, "commit", "-m", msg],
                           capture_output=True, text=True)
        sha = subprocess.run(["git", "-C", REPO, "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True).stdout.strip()
        return (r.returncode == 0), sha
    except Exception:
        return False, ""


def git_show(path, commit):
    """The file's contents at `commit`, or None if unavailable."""
    if not REPO:
        return None
    r = subprocess.run(["git", "-C", REPO, "show", f"{commit}:{git_rel(path)}"],
                       capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def git_mv(src, dst):
    """Move a tracked file, falling back to a plain rename when git can't."""
    if REPO:
        r = subprocess.run(["git", "-C", REPO, "mv", git_rel(src), git_rel(dst)],
                           capture_output=True, text=True)
        if r.returncode == 0:
            return
    os.replace(src, dst)


NO_REPO_MSG = ("this book's manuscript isn't in a git repo, so there are no saved "
               "versions to browse — saves still write to disk")
MAXB = 800_000  # cap request / text size
MAX_UPLOAD = 300_000_000   # cap an imported .pdf/.docx (streamed to disk, not held in memory)
MAX_MD_IMPORT = 64_000_000 # cap an imported .md folder — JSON, so it is parsed in memory

# Per-endpoint input caps. Named because a bare literal in a validation line reads
# as arbitrary, and these are a policy: how much structure one book may declare in
# a single request. Generous — they exist to bound a hostile or runaway client, not
# to constrain a real manuscript.
MAX_EVENTS = 20_000        # keystroke events in one /keystrokes batch
MAX_LABELS = 64            # labels on a single section
MAX_ORDER = 10_000         # sections in one order/unnumbered list
MAX_PARTS = 64             # part breaks in a book
MAX_BOARD_COLS = 50        # columns on the edit board
MAX_MOTIFS = 200           # motifs in a book
MAX_TERM = 120             # characters in an index term or part title
SESSION_RE = re.compile(r"^\d{6,20}-[a-z0-9]{1,12}$")   # client session id; no path traversal
ID_RE = re.compile(r"^\d{1,4}$")                        # section id ("001"); no traversal
COMMIT_RE = re.compile(r"^[0-9a-f]{7,40}$")             # git short/long hash


# ------------------------------------------------------- who may talk to us
# There are no accounts and no tokens here: anything that can send this server a
# request can rewrite the manuscript. The browser on this machine is the only
# intended client, so requests are pinned to this origin by three cheap checks:
#
#   Host          must name loopback (or a host you allowed on purpose). Without
#                 this, a hostile site can point a DNS name at 127.0.0.1 and read
#                 the book through the user's own browser — DNS rebinding.
#   Origin        when present, must be one of ours. Browsers always send it on
#                 POST, so another site's page can't reach the write endpoints.
#                 A terminal client (curl, a script) sends none and still works.
#   Content-Type  writes must be JSON — which is not a "simple" content type, so a
#                 cross-site form or fetch can't send one without a preflight that
#                 we never answer. (/import also takes a raw binary body.)
#
# PAL_ALLOWED_HOSTS (comma-separated host[:port]) widens this deliberately — you
# need it only if you publish the port past loopback, which also means anyone who
# can reach it can edit the book.
_LOOPBACK = ("localhost", "127.0.0.1", "::1")


def _hostname(value) -> str:
    """The host part of a Host header or an Origin's netloc, lowercased, port
    dropped ('[::1]:8137' -> '::1'). The port is deliberately ignored: the app is
    often reached on a remapped port (a container publishing 9000:8137), and it is
    the *name* that decides whether a request came from this machine."""
    v = str(value or "").strip().lower()
    if v.startswith("["):                       # bracketed IPv6 literal
        return v[1:].split("]", 1)[0]
    return v.rsplit(":", 1)[0] if v.count(":") == 1 else v


def _allowed_hosts():
    hosts = set(_LOOPBACK)
    for extra in os.environ.get("PAL_ALLOWED_HOSTS", "").split(","):
        name = _hostname(extra)
        if name:
            hosts.add(name)
    return hosts


ALLOWED_HOSTS = _allowed_hosts()
WRITE_TYPES = {"application/json"}                     # every endpoint but /import
IMPORT_TYPES = WRITE_TYPES | {"application/octet-stream"}   # a raw .pdf/.docx body


def _err_text(e) -> str:
    """An error string safe to hand back to the page: the message, minus absolute
    paths. The console still gets the whole thing; a caller that shouldn't be here
    doesn't need a map of the filesystem."""
    msg = str(e)
    for secret in (str(config.BOOK_DIR), str(library.home()), os.path.expanduser("~")):
        if secret and len(secret) > 1:
            msg = msg.replace(secret, "…")
    return msg

# Background page-rebuild worker: the copyedit rebuild takes ~9s, so saves that don't reload
# (save-left, mark-done) request a rebuild via the event and return instantly. Requests coalesce —
# many saves collapse into one follow-up rebuild that reads the latest files.
_REBUILD = threading.Event()

def load_json(path):
    """Parse a JSON file and close it. Callers handle the exceptions — every one of
    these sits inside a try that falls back to a default."""
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def run_builder(script, timeout=180):
    """Run one builder against the active book. Returns the CompletedProcess.

    A binding, not a second implementation: it hands this server's book and
    dossier to the shared engine path, so an incremental rebuild here runs the
    same command `pal build` does. Spawn builders only through that path —
    dossier.child_python() resolves an interpreter that works inside a py2app
    .app, where sys.executable is the app binary and re-running it relaunches
    the application.
    """
    return dossier.run_builder(script, config.BOOK_DIR, DOSSIER,
                               timeout=timeout, capture=True)


PAGE_BUILDERS = ("build_reading_copy.py", "build_copyedit_review.py", "build_parts_board.py")

def build_book(book_dir, timeout=600):
    """Build another book's whole dossier via the shared engine build path
    (engine/dossier.py — the same code `pal build` runs), so a book made or imported
    in the browser is identical to one built on the CLI.

    Runs in a child process: dossier binds config to `book_dir`, and we don't want
    to rebind this server's own (open) book. Returns the subprocess result, so
    callers keep using r.stdout / r.stderr.  This runs from an isolated interpreter
    (no repo `pal` script needed), so it works the same when installed or in the app."""
    env = dict(os.environ, PAL_BOOK=str(book_dir),
               PYTHONPATH=ENGINE + os.pathsep + os.environ.get("PYTHONPATH", ""))
    code = ("import sys, dossier; "
            "ok, fail, out, title = dossier.build(sys.argv[1], "
            "log=lambda m: print(m, file=sys.stderr)); "
            "sys.exit(1 if fail else 0)")
    return subprocess.run([dossier.child_python(), "-c", code, str(book_dir)],
                          cwd=ENGINE, env=env, capture_output=True, text=True, timeout=timeout)


def switch_to(book_dir, handler=None):
    """Re-point this server at another book by restarting in place.

    The book is bound at import (config resolves once), so switching means a
    fresh process — same port, same URL, so the page just reloads into it.

    Call this AFTER writing the response: it replaces the process, so nothing
    after it runs. The reply is flushed and the write side of the connection shut
    down first, so the browser has the whole answer and sees EOF before the
    process is replaced — no timer, no race. exec keeps the listening socket
    open, so the port never drops and the page's reload lands on the new book.
    """
    if handler is not None:
        try:
            handler.wfile.flush()
            handler.close_connection = True
            handler.connection.shutdown(socket.SHUT_WR)
        except OSError:
            pass                      # client already hung up; nothing to deliver
    env = dict(os.environ, PAL_BOOK=str(book_dir), PORT=str(PORT))
    try:
        os.execve(sys.executable, [sys.executable, os.path.abspath(__file__)], env)
    except Exception:
        LOG.error("could not restart on %s", book_dir, exc_info=True)
        os._exit(1)


def _rebuild_worker():
    while True:
        _REBUILD.wait()
        _REBUILD.clear()
        for script in PAGE_BUILDERS:
            try:
                run_builder(script)
            except Exception:
                # A builder that starts failing here would otherwise be invisible
                # forever: this thread has no caller to report to and the page it
                # would have refreshed simply stays stale.
                LOG.warning("background rebuild of %s failed", script, exc_info=_verbose())


class Handler(http.server.SimpleHTTPRequestHandler):
    # Content-Length is trusted as a read length, so without a socket timeout a
    # client that declares a large body and then dribbles bytes holds a thread for
    # as long as it likes — and Server sets daemon_threads, so those accumulate
    # unbounded. Generous enough never to interrupt a real save.
    timeout = 60

    def __init__(self, *a, **k): super().__init__(*a, directory=DOSSIER, **k)
    def log_message(self, fmt, *a):
        # Silent by default: this runs in the writer's terminal, and a line per
        # asset request would bury the one message that matters. PAL_LOG=debug (or
        # `pal serve --verbose`) turns it into a real access log — worth having
        # when a write endpoint is misbehaving and there is otherwise no record
        # that the request ever arrived.
        LOG.debug("%s %s", self.address_string(), fmt % a)
    def end_headers(self):
        # never cache: a plain reload must always fetch the freshly-rebuilt page
        self.send_header("Cache-Control", "no-store, max-age=0")
        super().end_headers()

    ROUTES = {}   # set below the class

    # ---- the origin gate: every request enters through here (see ALLOWED_HOSTS) ----
    def _allowed(self, write=False, types=WRITE_TYPES):
        """True if this request may proceed. Otherwise answers 403 and returns False."""
        host = self.headers.get("Host")
        if host and _hostname(host) not in ALLOWED_HOSTS:
            return self._refuse("this server answers on localhost only "
                                f"(got Host: {str(host).strip()!r})")
        origin = (self.headers.get("Origin") or "").strip()
        if origin:
            netloc = urllib.parse.urlparse(origin).netloc
            if not netloc or _hostname(netloc) not in ALLOWED_HOSTS:
                return self._refuse("cross-site request blocked")
        if write:
            ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if ctype not in types:
                return self._refuse("this endpoint takes "
                                    + " or ".join(sorted(types)))
        return True

    def _refuse(self, why):
        self._json({"ok": False, "error": why}, code=403)
        return False

    def do_POST(self):
        path = self.path.split("?", 1)[0]        # routes are keyed by path, not query
        if not self._allowed(write=True,
                             types=IMPORT_TYPES if path == "/import" else WRITE_TYPES):
            return
        route = Handler.ROUTES.get(path)
        if route:
            return route(self)
        if path != "/save":
            self.send_error(404); return
        try:
            n = int(self.headers.get("Content-Length", "0"))
            if not (0 < n <= MAXB): raise ValueError("bad length")
            data = json.loads(self.rfile.read(n))
            sec = str(data.get("section", "")).strip()
            text = data.get("text", "")
            if not re.fullmatch(r"\d{1,4}", sec): raise ValueError("bad section id")
            if not isinstance(text, str) or len(text) > MAXB: raise ValueError("bad text")
            path_md = os.path.join(MAN, f"{sec}.md")
            if not os.path.isfile(path_md): raise ValueError("no such section")   # no new files / no traversal
            with open(path_md, encoding="utf-8") as fh:
                head = f"# {sections.heading_id(fh.read(), sec)}"
            body = text.replace("\r\n", "\n").rstrip() + "\n"
            with open(path_md, "w", encoding="utf-8") as fh:
                fh.write(f"{head}\n\n{body}")
            committed, commit = git_commit([path_md], f"docs({SLUG}): section {sec} via reading-copy")
            _REBUILD.set()   # rebuild both pages in the background (coalesced) — save returns instantly
            msg = ("committed" if committed else
                   "saved (no change to commit)" if REPO else "saved (not versioned)")
            self._json({"ok": True, "section": sec, "commit": commit, "committed": committed,
                        "msg": msg})
        except Exception as e:
            self._json({"ok": False, "error": _err_text(e)}, code=400)

    def do_keystrokes(self):
        """Append a batch of writing-record events to keystrokes/<session>.jsonl.

        Body: {"session": "<id>", "events": [ {..}, {..} ]}. No git commit —
        these logs are noisy and local-only. sendBeacon posts land here too."""
        try:
            n = int(self.headers.get("Content-Length", "0"))
            if not (0 < n <= MAXB): raise ValueError("bad length")
            data = json.loads(self.rfile.read(n))
            sess = str(data.get("session", "")).strip()
            if not SESSION_RE.fullmatch(sess): raise ValueError("bad session id")
            events = data.get("events", [])
            if not isinstance(events, list) or len(events) > MAX_EVENTS: raise ValueError("bad events")
            os.makedirs(KEYS, exist_ok=True)
            fn = os.path.join(KEYS, f"{sess}.jsonl")
            if os.path.dirname(os.path.abspath(fn)) != KEYS: raise ValueError("path escape")  # belt + suspenders
            with open(fn, "a", encoding="utf-8") as fh:
                for ev in events:
                    fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
            self._json({"ok": True, "session": sess, "appended": len(events)})
        except Exception as e:
            self._json({"ok": False, "error": _err_text(e)}, code=400)

    def do_HEAD(self):
        if not self._allowed():
            return
        return super().do_HEAD()

    def do_GET(self):
        if not self._allowed():
            return
        p = self.path.split("?")[0]
        if p == "/keystrokes/index.json": return self.keystroke_index()
        if p == "/history": return self.do_history()
        if p == "/version": return self.do_version()
        if p == "/suggestion-history": return self.do_suggestion_history()
        if p == "/suggestion-version": return self.do_suggestion_version()
        if p == "/attic": return self.do_attic_list()
        if p == "/books": return self.do_books()
        return super().do_GET()

    def _query(self):
        return urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)

    def do_history(self):
        """GET /history?section=NNN → that section's saved versions (git log)."""
        try:
            sec = (self._query().get("section") or [""])[0].strip()
            if not ID_RE.fullmatch(sec): raise ValueError("bad section id")
            if not REPO:
                self._json({"ok": True, "section": sec, "versions": [], "note": NO_REPO_MSG})
                return
            rel = git_rel(os.path.join(MAN, f"{sec}.md"))
            r = subprocess.run(["git", "-C", REPO, "log", "-50",
                                "--format=%H%x1f%h%x1f%ad%x1f%s", "--date=format:%b %d %H:%M",
                                "--", rel], capture_output=True, text=True)
            vers = []
            for line in r.stdout.splitlines():
                parts = line.split("\x1f")
                if len(parts) == 4:
                    vers.append({"hash": parts[0], "short": parts[1], "date": parts[2], "subject": parts[3]})
            self._json({"ok": True, "section": sec, "versions": vers})
        except Exception as e:
            self._json({"ok": False, "error": _err_text(e)}, code=400)

    def do_version(self):
        """GET /version?section=NNN&commit=HASH → that section's body at that commit."""
        try:
            q = self._query()
            sec = (q.get("section") or [""])[0].strip()
            commit = (q.get("commit") or [""])[0].strip()
            if not ID_RE.fullmatch(sec): raise ValueError("bad section id")
            if not COMMIT_RE.fullmatch(commit): raise ValueError("bad commit")
            shown = git_show(os.path.join(MAN, f"{sec}.md"), commit)
            if shown is None: raise ValueError("version not found")
            m = re.match(r"\s*#\s*\d+\s*\n(.*)", shown, re.S)
            body = (m.group(1) if m else shown).strip()
            self._json({"ok": True, "section": sec, "commit": commit, "text": body})
        except Exception as e:
            self._json({"ok": False, "error": _err_text(e)}, code=400)

    def do_restore(self):
        """POST /restore {section,commit} → write that old version back + commit (a new version; nothing is lost)."""
        try:
            data = self._body()
            sec = str(data.get("section", "")).strip()
            commit = str(data.get("commit", "")).strip()
            if not ID_RE.fullmatch(sec): raise ValueError("bad section id")
            if not COMMIT_RE.fullmatch(commit): raise ValueError("bad commit")
            fn = os.path.join(MAN, f"{sec}.md")
            if not os.path.isfile(fn): raise ValueError("no such section")
            shown = git_show(fn, commit)
            if shown is None: raise ValueError("version not found")
            vbody = sections.strip_heading(shown)
            with open(fn, encoding="utf-8") as fh:                  # keep the current heading (file id)
                head = f"# {sections.heading_id(fh.read(), sec)}"
            open(fn, "w", encoding="utf-8").write(f"{head}\n\n{vbody}\n")
            committed, sha = self._git([fn], f"docs({SLUG}): restore section {sec} to {commit[:7]} via reading-copy")
            self._json({"ok": True, "section": sec, "commit": sha, "committed": committed})
        except Exception as e:
            self._json({"ok": False, "error": _err_text(e)}, code=400)

    def keystroke_index(self):
        """List recorded sessions so writing-record.html can offer a picker."""
        try:
            out = []
            if os.path.isdir(KEYS):
                for name in sorted(os.listdir(KEYS)):
                    if not name.endswith(".jsonl"): continue
                    p = os.path.join(KEYS, name)
                    stat = os.stat(p)
                    out.append({"file": "keystrokes/" + name, "session": name[:-6],
                                "bytes": stat.st_size, "mtime": int(stat.st_mtime)})
            out.sort(key=lambda x: x["mtime"], reverse=True)
            self._json({"ok": True, "sessions": out})
        except Exception as e:
            self._json({"ok": False, "error": _err_text(e)}, code=400)

    # ---- shared helpers for the authored-data endpoints ----
    def _body(self):
        n = int(self.headers.get("Content-Length", "0"))
        if not (0 < n <= MAXB): raise ValueError("bad length")
        return json.loads(self.rfile.read(n))

    def _git(self, paths, msg):
        return git_commit(paths, msg)

    # ---- the library: which book am I editing, and what else is there? ----
    def do_books(self):
        """GET /books → every book in the workbench, and which one is open."""
        try:
            pandoc, xelatex = pdf_engine.tools_ok()
            self._json({"ok": True, "active": SLUG, "title": config.TITLE,
                        "pdf": bool(pandoc and xelatex),   # PDF needs both
                        "pandoc": bool(pandoc),            # Word (.docx) needs only pandoc
                        "home": str(library.home()),       # where books live
                        "books": library.books()})
        except Exception as e:
            self._json({"ok": False, "error": _err_text(e)}, code=400)

    # content-type per export format, for the streamed download
    _EXPORT_MIME = {"pdf": "application/pdf",
                    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    "html": "text/html", "md": "text/markdown"}

    def do_pdf(self):
        """POST /pdf → export as PDF (kept for back-compat); same as /export {format:pdf}."""
        try:
            data = self._body()
        except Exception:
            data = {}
        data.setdefault("format", "pdf")
        return self._export(data)

    def do_export(self):
        """POST /export {format,from,to,part,appendices} → render and stream the file.

        Full parity with `pal export`: same assembler + same pandoc build, so a
        document made in the browser is what the CLI makes. `format` ∈ pdf | docx
        | html | md — docx needs only pandoc, html/md need nothing, pdf needs
        pandoc + XeLaTeX. Errors: 503 (a needed tool is missing) / 400 (build)."""
        try:
            data = self._body()      # read the request body ONCE (it can't be re-read)
        except Exception:
            data = {}
        return self._export(data)

    def _export(self, data):
        try:
            def _int(k):
                v = data.get(k)
                return int(v) if str(v).strip().lstrip("-").isdigit() else None
            appx = str(data.get("appendices", "")).lower()
            fmt = (data.get("format") or "pdf").lower()
            if fmt not in self._EXPORT_MIME:
                raise ValueError(f"unknown format {fmt!r}")
            out = pdf_engine.build_doc(
                fmt,
                part=(str(data["part"]).strip() if data.get("part") else None),
                frm=_int("from"), to=_int("to"),
                held=appx in ("held", "both", "all", "1", "true"),
                deleted=appx in ("deleted", "both", "all"))
            with open(out, "rb") as fh:
                blob = fh.read()
            self.send_response(200)
            self.send_header("Content-Type", self._EXPORT_MIME.get(fmt, "application/octet-stream"))
            # basename() strips separators but not quotes or CR/LF, and the name is
            # derived from book.toml — so pin it to characters that cannot close the
            # quoted string or split the response.
            fname = re.sub(r'[^A-Za-z0-9._-]+', "-", os.path.basename(out)) or "export"
            self.send_header("Content-Disposition", f'attachment; filename="{fname}"')
            self.send_header("Content-Length", str(len(blob)))
            self.end_headers()
            self.wfile.write(blob)
        except RuntimeError as e:
            code = 503 if "needs" in str(e) or "not found" in str(e) else 400
            self._json({"ok": False, "error": _err_text(e)}, code=code)
        except Exception as e:
            self._json({"ok": False, "error": _err_text(e)}, code=400)

    def do_import(self):
        """POST /import?kind=md|pdf|docx&title=…&by=chapter|page → create a new book
        from an uploaded manuscript and open it.
          md   → JSON body {title, files:[{name,text}]}  (a folder of .md files)
          pdf  → the raw PDF bytes as the body   (split by chapter/page; needs PyMuPDF)
          docx → the raw .docx bytes as the body (split by heading; needs pandoc)
        Deterministic; both tools are bundled in the Docker image."""
        try:
            import import_book, tempfile
            q = self._query()
            kind = (q.get("kind") or [""])[0].lower()
            title = (q.get("title") or [""])[0].strip()
            by = (q.get("by") or ["chapter"])[0].lower()
            n = int(self.headers.get("Content-Length", "0"))
            if kind == "md":
                # a JSON body, so it has to be held in memory — keep it modest
                if not (0 < n <= MAX_MD_IMPORT):
                    raise ValueError("bad upload size")
                data = json.loads(self.rfile.read(n).decode("utf-8"))
                title = title or str(data.get("title", "")).strip() or "Imported book"
                files = [(str(f.get("name", "")), str(f.get("text", "")))
                         for f in (data.get("files") or [])]
                bodies = import_book.sections_from_md(files)
            elif kind in ("pdf", "docx"):
                if not (0 < n <= MAX_UPLOAD):
                    raise ValueError("bad upload size")
                # stream to disk in chunks: a document can be hundreds of megabytes,
                # and reading it whole would let one request size the server's memory
                tmp = None
                try:
                    with tempfile.NamedTemporaryFile(suffix="." + kind, delete=False) as tf:
                        tmp = tf.name
                        left = n
                        while left > 0:
                            chunk = self.rfile.read(min(1 << 20, left))
                            if not chunk:
                                raise ValueError("upload ended early")
                            tf.write(chunk)
                            left -= len(chunk)
                    bodies = (import_book.sections_from_pdf(tmp, by) if kind == "pdf"
                              else import_book.sections_from_docx(tmp))
                finally:
                    if tmp:
                        try:
                            os.unlink(tmp)
                        except OSError as e:
                            LOG.warning("could not remove the upload temp file: %s", e)
                title = title or "Imported book"
            else:
                raise ValueError("unknown import kind")
            if not bodies:
                raise ValueError("found no text to import")
            # the title comes off the query string: it names the book but must not
            # place it, so the directory is a slug of it, never the string itself
            d = library.create(library.slugify(title), title)
            man = os.path.join(str(d), "manuscript")
            os.makedirs(man, exist_ok=True)
            for f in glob.glob(os.path.join(man, "[0-9]*.md")):   # drop the template's starter
                try:
                    os.remove(f)
                except OSError as e:
                    LOG.warning("could not drop the template section %s: %s",
                                os.path.basename(f), e)
            for i, body in enumerate(bodies, 1):
                with open(os.path.join(man, f"{i:03d}.md"), "w", encoding="utf-8") as fh:
                    fh.write(f"# {i}\n\n{body}\n")
            r = build_book(d)
            if not (d / "dossier" / "reading-copy.html").is_file():
                err = [_err_text(x) for x in (r.stderr or r.stdout or "").strip().splitlines()[-1:]] or ["build failed"]
                self._json({"ok": False, "slug": d.name,
                            "error": f"imported {len(bodies)} sections but the build failed: {err[0]}"},
                           code=400)
                return
            self._json({"ok": True, "slug": d.name, "sections": len(bodies)})
            switch_to(d, self)          # replaces this process; nothing below runs
        except library.LibraryError as e:
            self._json({"ok": False, "error": _err_text(e)}, code=400)
        except Exception as e:
            self._json({"ok": False, "error": _err_text(e)}, code=400)

    def do_book_new(self):
        """POST /book-new {name,title,author} → create a book, build it, open it.

        The new book gets a full dossier BEFORE we switch, so the browser never
        lands on a book with no reading copy. If the build fails we do NOT switch
        — we report the error so the Library page can show it, and the book is
        left on disk to inspect rather than silently opened broken."""
        try:
            data = self._body()
            # The page posts the typed title as the name. A title is prose — it can
            # hold slashes, dots, anything — so the *directory* is a slug of it and
            # never the raw string, which would otherwise be read as a path.
            title = str(data.get("title") or data.get("name") or "").strip()
            if not title:
                raise ValueError("a book needs a name")
            d = library.create(library.slugify(data.get("name") or title),
                               title, data.get("author"))
            r = build_book(d)
            if not (d / "dossier" / "reading-copy.html").is_file():
                err = [_err_text(x) for x in (r.stderr or r.stdout or "").strip().splitlines()[-1:]] or ["build failed"]
                self._json({"ok": False, "slug": d.name, "dir": str(d),
                            "error": f"created {d.name}, but its build failed: {err[0]}"},
                           code=400)
                return
            self._json({"ok": True, "slug": d.name, "dir": str(d), "built": True,
                        "msg": f"created {d.name} — opening it now"})
            switch_to(d, self)          # replaces this process; nothing below runs
        except library.LibraryError as e:
            self._json({"ok": False, "error": _err_text(e)}, code=400)
        except Exception as e:
            self._json({"ok": False, "error": _err_text(e)}, code=400)

    def do_book_open(self):
        """POST /book-open {slug} → switch this server to another book.

        A book opened for the first time is built now; if that build leaves no
        reading copy we report the error instead of switching into a blank book."""
        try:
            # find_slug, not find: this is a web request, so it may name a book in
            # the workbench and nothing else
            d = library.find_slug(str(self._body().get("slug", "")).strip())
            if not d:
                raise ValueError("no such book")
            if str(d) == str(config.BOOK_DIR):
                self._json({"ok": True, "slug": d.name, "msg": "already open"})
                return
            rc = d / "dossier" / "reading-copy.html"
            if not rc.is_file():               # first open: give it its pages
                r = build_book(d)
                if not rc.is_file():
                    err = [_err_text(x) for x in (r.stderr or r.stdout or "").strip().splitlines()[-1:]] or ["build failed"]
                    self._json({"ok": False, "slug": d.name,
                                "error": f"could not build {d.name}: {err[0]}"}, code=400)
                    return
            self._json({"ok": True, "slug": d.name, "msg": f"opening {d.name}"})
            switch_to(d, self)          # replaces this process; nothing below runs
        except Exception as e:
            self._json({"ok": False, "error": _err_text(e)}, code=400)

    def do_book_delete(self):
        """POST /book-delete {slug} → remove a book (move it to the workbench's
        .trash/, reversible). Refuses the currently-open book, since this server is
        bound to it — open a different one first."""
        try:
            d = library.find_slug(str(self._body().get("slug", "")).strip())   # workbench only
            if not d:
                raise ValueError("no such book")
            if str(d) == str(config.BOOK_DIR):
                self._json({"ok": False,
                            "error": "that book is open — open a different book first, then delete it"},
                           code=400)
                return
            dest = library.delete(str(d))
            self._json({"ok": True, "slug": d.name, "trash": str(dest)})
        except library.LibraryError as e:
            self._json({"ok": False, "error": _err_text(e)}, code=400)
        except Exception as e:
            self._json({"ok": False, "error": _err_text(e)}, code=400)

    def _rebuild_reading(self):
        """Regenerate the section views (reading-copy + copyedit-review + parts-board) so a
        save is reflected on the next reload of any of them."""
        for script in PAGE_BUILDERS:
            try:
                run_builder(script, timeout=90)
            except Exception:
                LOG.warning("rebuild of %s failed after a save", script, exc_info=_verbose())

    def _write_json_file(self, path, obj, indent=0):
        """Write `obj` to `path` atomically (temp file + rename).

        indent=0 for the machine-written manifests, 2 for the files a person may
        open and edit by hand.
        """
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, indent=indent)
        os.replace(tmp, path)

    def do_labels(self):
        """Persist authored section labels -> labels.json (+commit)."""
        try:
            data = self._body()
            labels = data.get("labels", data)          # accept {labels:{...}} or {...}
            if not isinstance(labels, dict): raise ValueError("bad labels")
            clean = {}
            for sid, labs in labels.items():
                if not ID_RE.fullmatch(str(sid)): raise ValueError("bad section id")
                if not isinstance(labs, list) or len(labs) > MAX_LABELS: raise ValueError("bad label list")
                arr = []
                for l in labs:
                    if not isinstance(l, dict) or not str(l.get("text", "")).strip(): continue
                    # a color ends up in a style attribute, so store a hex literal
                    # or the default — never whatever string was posted
                    arr.append({"text": str(l["text"])[:80],
                                "color": config.safe_color(l.get("color"))})
                if arr: clean[str(sid)] = arr
            self._write_json_file(LABELS_JSON, clean)
            committed, sha = self._git([LABELS_JSON], f"docs({SLUG}): labels via reading-copy")
            self._json({"ok": True, "commit": sha, "committed": committed, "sections": len(clean)})
        except Exception as e:
            self._json({"ok": False, "error": _err_text(e)}, code=400)

    def do_order(self):
        """Persist section display order -> order.json (+commit)."""
        try:
            data = self._body()
            order = data.get("order", data)
            if not isinstance(order, list) or len(order) > MAX_ORDER: raise ValueError("bad order")
            seen, clean = set(), []
            for sid in order:
                sid = str(sid)
                if not ID_RE.fullmatch(sid): raise ValueError("bad section id")
                if not os.path.isfile(os.path.join(MAN, f"{sid}.md")): raise ValueError(f"no section {sid}")
                if sid in seen: raise ValueError(f"duplicate {sid}")
                seen.add(sid); clean.append(sid)
            self._write_json_file(ORDER_JSON, clean)
            committed, sha = self._git([ORDER_JSON], f"docs({SLUG}): reorder sections via reading-copy")
            _REBUILD.set()   # regenerate the section views in the background so a later reload isn't stale
            self._json({"ok": True, "commit": sha, "committed": committed, "count": len(clean)})
        except Exception as e:
            self._json({"ok": False, "error": _err_text(e)}, code=400)

    def do_parts(self):
        """Persist part-break definitions -> parts.json (+commit).

        Body: a full array of {"start","title","subtitle"?} (the UI posts the
        whole list each time, like /order). Start ids must be real sections."""
        try:
            data = self._body()
            parts = data.get("parts", data)            # accept {parts:[...]} or [...]
            if not isinstance(parts, list) or len(parts) > MAX_PARTS: raise ValueError("bad parts")
            seen, clean = set(), []
            for p in parts:
                if not isinstance(p, dict): raise ValueError("bad part entry")
                sid = str(p.get("start", ""))
                title = str(p.get("title", "")).strip()
                if not ID_RE.fullmatch(sid): raise ValueError("bad section id")
                if not os.path.isfile(os.path.join(MAN, f"{sid}.md")): raise ValueError(f"no section {sid}")
                if not title: raise ValueError(f"empty title for {sid}")
                if sid in seen: raise ValueError(f"duplicate start {sid}")
                seen.add(sid)
                clean.append({"start": sid, "title": title[:120],
                              "subtitle": str(p.get("subtitle", "")).strip()[:80]})
            self._write_json_file(PARTS_JSON, clean)
            committed, sha = self._git([PARTS_JSON], f"docs({SLUG}): part breaks via reading-copy")
            self._json({"ok": True, "commit": sha, "committed": committed, "count": len(clean)})
        except Exception as e:
            self._json({"ok": False, "error": _err_text(e)}, code=400)

    def do_unnumbered(self):
        """Persist the set of unnumbered sections -> unnumbered.json (+commit).

        Body: full array of section ids (the UI posts the whole set each time).
        These sections still print but carry no §-number."""
        try:
            data = self._body()
            ids = data.get("unnumbered", data)         # accept {unnumbered:[...]} or [...]
            if not isinstance(ids, list) or len(ids) > MAX_ORDER: raise ValueError("bad list")
            seen, clean = set(), []
            for sid in ids:
                sid = str(sid)
                if not ID_RE.fullmatch(sid): raise ValueError("bad section id")
                if not os.path.isfile(os.path.join(MAN, f"{sid}.md")): raise ValueError(f"no section {sid}")
                if sid in seen: continue
                seen.add(sid); clean.append(sid)
            self._write_json_file(UNNUMBERED_JSON, clean)
            committed, sha = self._git([UNNUMBERED_JSON], f"docs({SLUG}): unnumbered sections via reading-copy")
            self._json({"ok": True, "commit": sha, "committed": committed, "count": len(clean)})
        except Exception as e:
            self._json({"ok": False, "error": _err_text(e)}, code=400)

    _ENTITY_TYPES = {"concept", "people", "works", "places", "stories", "things", "events"}

    def do_watchlist(self):
        """POST /watchlist {op, name, type?, aliases?} — edit the index watchlist
        (manifests/entities-seed.json) from the browser, then rebuild the index.
          op=add    → add/replace {name, type, aliases} in `add`
          op=drop   → remove `name` from `add`; if it was only text-found (not a
                      seed term), record a drop override so it disappears too
          op=retype → change a term's bucket
        """
        try:
            data = self._body()
            op = str(data.get("op", "")).strip().lower()
            name = str(data.get("name", "")).strip()
            if op not in ("add", "drop", "retype"):
                raise ValueError("bad op")
            if not name or len(name) > MAX_TERM:
                raise ValueError("a term needs a name")
            low = name.lower()
            seed_path = os.path.join(_MF, "entities-seed.json")
            try:
                doc = load_json(seed_path)
                if not isinstance(doc, dict):
                    doc = {}
            except Exception:
                doc = {}
            add = [e for e in (doc.get("add") or []) if isinstance(e, dict)]
            ov = doc.get("_override") if isinstance(doc.get("_override"), dict) else {}
            ops = [o for o in (ov.get("ops") or []) if isinstance(o, dict)]

            def _drop_ops(kind):   # forget any prior override of `kind` for this name
                return [o for o in ops if not (o.get("op") == kind
                        and str(o.get("name", "")).lower() == low)]

            if op == "add":
                typ = str(data.get("type", "concept")).strip().lower()
                if typ not in self._ENTITY_TYPES:
                    typ = "concept"
                raw = data.get("aliases", [])
                aliases = ([a.strip() for a in raw.split(",")] if isinstance(raw, str)
                           else [str(a).strip() for a in (raw or [])])
                aliases = [a for a in aliases if a]
                add = [e for e in add if str(e.get("name", "")).lower() != low]  # replace dupes
                entry = {"name": name, "type": typ}
                if aliases:
                    entry["aliases"] = aliases
                add.append(entry)
                ops = _drop_ops("drop")            # un-drop if it was dropped before
            elif op == "retype":
                typ = str(data.get("type", "")).strip().lower()
                if typ not in self._ENTITY_TYPES:
                    raise ValueError("bad type")
                hit = False
                for e in add:
                    if str(e.get("name", "")).lower() == low:
                        e["type"] = typ
                        hit = True
                if not hit:
                    ops = _drop_ops("retype") + [{"op": "retype", "name": name, "type": typ}]
            else:  # drop
                before = len(add)
                add = [e for e in add if str(e.get("name", "")).lower() != low]
                if len(add) == before:             # not a seed term → it's text-found
                    ops = _drop_ops("drop") + [{"op": "drop", "name": name}]

            doc["add"] = add
            ov["ops"] = ops
            doc["_override"] = ov
            # write readably (this file is also hand-editable) and atomically
            self._write_json_file(seed_path, doc, indent=2)
            self._git([seed_path], f"docs({SLUG}): watchlist {op} '{name}' via index")
            r = run_builder("build_entity_index.py", timeout=60)
            self._json({"ok": r.returncode == 0, "op": op, "name": name})
        except Exception as e:
            self._json({"ok": False, "error": _err_text(e)}, code=400)

    def do_edit_board(self):
        """POST /edit-board {columns:[{title,blurb?,items:[str|{text,done}]}], rebuild?}
        → write the book's data/edit-board.json. Items keep their `done` (tick)
        state, so checkboxes persist to disk. `rebuild:false` (used when only a
        tick changed) saves without regenerating the page or committing — cheap
        and silent; structural edits rebuild + commit as before."""
        try:
            data = self._body()
            cols_in = data.get("columns", [])
            if not isinstance(cols_in, list) or len(cols_in) > MAX_BOARD_COLS:
                raise ValueError("bad columns")
            cols = []
            for c in cols_in:
                if not isinstance(c, dict):
                    continue
                title = str(c.get("title", "")).strip()[:200]
                items = []
                for x in (c.get("items") or []):
                    if isinstance(x, dict):
                        t = str(x.get("text", "")).strip()[:400]
                        done = bool(x.get("done"))
                    else:
                        t, done = str(x).strip()[:400], False
                    if t:
                        items.append({"text": t, "done": done})
                if not title and not items:
                    continue
                col = {"title": title, "items": items}
                if str(c.get("blurb", "")).strip():
                    col["blurb"] = str(c["blurb"]).strip()[:400]
                if c.get("color"):
                    col["color"] = config.safe_color(c["color"])   # style attribute → hex only
                cols.append(col)
            data_dir = config.DATA_DIR
            os.makedirs(data_dir, exist_ok=True)
            path = os.path.join(data_dir, "edit-board.json")
            try:
                doc = load_json(path)
                doc = doc if isinstance(doc, dict) else {}
            except Exception:
                doc = {}
            doc["columns"] = cols
            self._write_json_file(path, doc, indent=2)
            if data.get("rebuild", True) is False:      # a tick-only save
                self._json({"ok": True, "columns": len(cols), "saved": True})
                return
            self._git([path], f"docs({SLUG}): edit board via edit-board")
            r = run_builder("build_edit_board.py", timeout=30)
            self._json({"ok": r.returncode == 0, "columns": len(cols)})
        except Exception as e:
            self._json({"ok": False, "error": _err_text(e)}, code=400)

    def do_motif_search(self):
        """POST /motif-search {query} → the section ids whose text contains the query
        (word-boundary, case-insensitive). Powers "find sections with…" in the motif
        editor. Pure deterministic text search — no model."""
        try:
            q = str(self._body().get("query", "")).strip()
            if not q:
                raise ValueError("type a word or phrase to search for")
            rx = re.compile(r"\b" + re.escape(q) + r"\b", re.I)
            hits = []
            for p in sorted(glob.glob(os.path.join(MAN, "[0-9]*.md"))):
                sid = os.path.basename(p)[:-3]
                try:
                    with open(p, encoding="utf-8") as fh:
                        if rx.search(fh.read()):
                            hits.append(int(sid))
                except (OSError, ValueError) as e:
                    # an unreadable section silently not matching is a wrong answer,
                    # not a missing one — say so
                    LOG.warning("motif search skipped section %s: %s", sid, e)
            self._json({"ok": True, "query": q, "sections": sorted(set(hits))})
        except Exception as e:
            self._json({"ok": False, "error": _err_text(e)}, code=400)

    def do_motifs(self):
        """POST /motifs {motifs:[{name,color,sections:[int]}]} → write the book's
        data/motifs.json and rebuild the views that draw motifs.

        A motif is a name, a colour and the sections it appears in — nothing is inferred
        and nothing is scored."""
        try:
            data = self._body()
            m_in = data.get("motifs", [])
            if not isinstance(m_in, list) or len(m_in) > MAX_MOTIFS:
                raise ValueError("bad motifs")
            pal = list(config.PALETTE)
            motifs = []
            for m in m_in:
                if not isinstance(m, dict):
                    continue
                name = str(m.get("name", "")).strip()[:80]
                if not name:
                    continue
                color = config.safe_color(m.get("color"), pal[len(motifs) % len(pal)])
                secs = sorted({int(s) for s in (m.get("sections") or m.get("turns") or [])
                               if str(s).strip().lstrip("-").isdigit()})
                motifs.append({"name": name, "color": color, "sections": secs})

            data_dir = config.DATA_DIR
            os.makedirs(data_dir, exist_ok=True)
            path = os.path.join(data_dir, "motifs.json")
            try:
                doc = load_json(path)
                doc = doc if isinstance(doc, dict) else {}
            except Exception:
                doc = {}
            doc["motifs"] = motifs
            self._write_json_file(path, doc, indent=2)
            self._git([path], f"docs({SLUG}): motifs")
            for s in ("build_motifs.py", "build_reading_copy.py", "build_sections_json.py"):
                try:
                    run_builder(s, timeout=60)
                except Exception:
                    LOG.warning("rebuild of %s failed after a motif edit", s, exc_info=_verbose())
            self._json({"ok": True, "motifs": len(motifs)})
        except Exception as e:
            self._json({"ok": False, "error": _err_text(e)}, code=400)

    def _read_held(self):
        try:
            with open(HELD_JSON, encoding="utf-8") as fh:
                h = json.load(fh)
                return h if isinstance(h, list) else []
        except Exception:
            return []

    def do_section_park(self):
        """Park a section: pull it out of the flow (drop from order.json) and add it to
        held.json, remembering the id it sat AFTER (anchor). The file stays in manuscript/
        (no git mv, no _attic) so it can be re-placed later. Reversible."""
        try:
            data = self._body()
            sid = str(data.get("section", "")).strip()
            if not ID_RE.fullmatch(sid): raise ValueError("bad section id")
            if not os.path.isfile(os.path.join(MAN, f"{sid}.md")): raise ValueError("no such section")
            held = [h for h in self._read_held() if isinstance(h, dict)]
            if any(str(h.get("id")) == sid for h in held): raise ValueError("already set aside")
            order = self._read_order()
            anchor = None
            if sid in order:
                i = order.index(sid)
                anchor = order[i - 1] if i > 0 else None
                order = [s for s in order if s != sid]
                self._write_json_file(ORDER_JSON, order)
            held.append({"id": sid, "anchor": anchor})
            self._write_json_file(HELD_JSON, held)
            committed, sha = self._git([ORDER_JSON, HELD_JSON], f"docs({SLUG}): set aside section {sid}")
            self._rebuild_reading()
            self._json({"ok": True, "section": sid, "anchor": anchor, "commit": sha, "committed": committed})
        except Exception as e:
            self._json({"ok": False, "error": _err_text(e)}, code=400)

    def do_section_unpark(self):
        """Return a parked section to the flow. Insert it into order.json AFTER the
        client-supplied `after` id (place / drag), else after its stored anchor (plain
        return), else at the start. Removes it from held.json."""
        try:
            data = self._body()
            sid = str(data.get("section", "")).strip()
            if not ID_RE.fullmatch(sid): raise ValueError("bad section id")
            if not os.path.isfile(os.path.join(MAN, f"{sid}.md")): raise ValueError("no such section")
            held = [h for h in self._read_held() if isinstance(h, dict)]
            entry = next((h for h in held if str(h.get("id")) == sid), None)
            if entry is None: raise ValueError("not set aside")
            held = [h for h in held if str(h.get("id")) != sid]
            self._write_json_file(HELD_JSON, held)
            # placement target: explicit `after` wins; "" means "at the very start";
            # a missing key falls back to the stored anchor.
            after = data.get("after", None)
            anchor = str(after).strip() if after is not None else entry.get("anchor")
            order = [s for s in self._read_order() if s != sid]
            if anchor and anchor in order:
                order.insert(order.index(anchor) + 1, sid)
            else:
                order.insert(0, sid)                    # start (anchor was null / gone / "")
            self._write_json_file(ORDER_JSON, order)
            committed, sha = self._git([ORDER_JSON, HELD_JSON], f"docs({SLUG}): place section {sid}")
            self._rebuild_reading()
            self._json({"ok": True, "section": sid, "commit": sha, "committed": committed})
        except Exception as e:
            self._json({"ok": False, "error": _err_text(e)}, code=400)

    def do_section_add(self):
        """Create the next-free NNN.md and place it in order.json.

        Body may carry {"after": "<id>"} to insert the new section right after
        that one (insert-below); otherwise it is appended to the end."""
        try:
            try: data = self._body()
            except Exception: data = {}
            after = str(data.get("after", "")).strip()
            if after and not ID_RE.fullmatch(after): raise ValueError("bad after id")
            existing = sorted(os.path.basename(p)[:-3] for p in glob.glob(os.path.join(MAN, "[0-9]*.md")))
            new = (max(int(x) for x in existing) + 1) if existing else 1
            sid = f"{new:03d}"
            fn = os.path.join(MAN, f"{sid}.md")
            if os.path.exists(fn): raise ValueError("collision")
            with open(fn, "w", encoding="utf-8") as fh:
                fh.write(f"# {new}\n\n")
            # materialize the current display order so "after" is meaningful, then insert
            order = self._read_order() or existing[:]
            for x in existing:                       # include any on-disk id missing from the manifest
                if x not in order: order.append(x)
            if after and after in order:
                order.insert(order.index(after) + 1, sid)
            else:
                order.append(sid)
            self._write_json_file(ORDER_JSON, order)
            committed, sha = self._git([fn, ORDER_JSON], f"docs({SLUG}): add section {sid} via reading-copy")
            pos = order.index(sid) + 1
            self._json({"ok": True, "id": sid, "pos": pos, "commit": sha, "committed": committed})
        except Exception as e:
            self._json({"ok": False, "error": _err_text(e)}, code=400)

    def do_section_delete(self):
        """Soft-delete: git mv NNN.md -> manuscript/_attic/ + drop from order (+commit). Reversible."""
        try:
            data = self._body()
            sid = str(data.get("section", "")).strip()
            if not ID_RE.fullmatch(sid): raise ValueError("bad section id")
            src = os.path.join(MAN, f"{sid}.md")
            if not os.path.isfile(src): raise ValueError("no such section")
            os.makedirs(ATTIC, exist_ok=True)
            dst = os.path.join(ATTIC, f"{sid}.md")
            if os.path.exists(dst): raise ValueError("already archived")
            git_mv(src, dst)
            order = [s for s in self._read_order() if s != sid]
            self._write_json_file(ORDER_JSON, order)
            committed, sha = self._git([ORDER_JSON], f"docs({SLUG}): archive section {sid} via reading-copy")
            self._json({"ok": True, "id": sid, "archived": os.path.relpath(dst, MAN),
                        "commit": sha, "committed": committed})
        except Exception as e:
            self._json({"ok": False, "error": _err_text(e)}, code=400)

    def do_rebuild(self):
        """Regenerate the section-derived views (reading copy, copyedit review, parts
        board, writing record) so the page reloaded after an add/insert/delete/reorder
        shows the change. Targeted on purpose: the maps, index and overview are
        motif-driven and unaffected by a structural edit, so a full `pal build` here
        (every view in dossier.REGISTRY) would make each edit needlessly slow."""
        try:
            fail = 0
            for script in PAGE_BUILDERS + ("build_sections_json.py",):
                r = run_builder(script, timeout=120)
                fail += 0 if r.returncode == 0 else 1
            self._json({"ok": fail == 0, "msg": "rebuilt" if not fail else f"{fail} view(s) failed"})
        except Exception as e:
            self._json({"ok": False, "error": _err_text(e)}, code=400)


    def do_resolve(self):
        """Finalize a section (mark done). Body {section, text} where text = the LEFT column final.
        Saves text as the manuscript (+commit), archives the ORIGINAL suggestion to _resolved/ for
        then syncs the live suggestion to the final so no diff remains. Logs the outcome
        (used = final matched the suggestion; kept = you changed it). Does NOT hide the section."""
        try:
            import datetime
            data = self._body()
            sec = str(data.get("section", "")).strip()
            text = data.get("text", "")
            if not ID_RE.fullmatch(sec): raise ValueError("bad section id")
            if not isinstance(text, str) or len(text) > MAXB: raise ValueError("bad text")
            mp, sp = os.path.join(MAN, f"{sec}.md"), os.path.join(SUGG, f"{sec}.md")
            if not os.path.isfile(mp): raise ValueError("no such section")
            head = f"# {sections.read_section(mp)[0] or sec}"

            orig_sugg = None                                  # the suggestion as it stood
            if os.path.isfile(sp):
                m = re.match(r"\s*#\s*\d+\s*\n(.*)", open(sp, encoding="utf-8").read(), re.S)
                orig_sugg = (m.group(1) if m else "").strip()
            final = text.replace("\r\n", "\n").strip()
            open(mp, "w", encoding="utf-8").write(f"{head}\n\n{final}\n")     # save the left as final
            outcome = ("used" if orig_sugg == final else "kept") if orig_sugg is not None else "no-suggestion"
            if orig_sugg is not None:                          # keep the original, so it can be reopened
                arch = os.path.join(SUGG, "_resolved"); os.makedirs(arch, exist_ok=True)
                open(os.path.join(arch, f"{sec}.md"), "w", encoding="utf-8").write(f"{head}\n\n{orig_sugg}\n")
            open(sp, "w", encoding="utf-8").write(f"{head}\n\n{final}\n")     # sync suggestion -> no diff
            self._git([mp], f"docs({SLUG}): finalize section {sec} ({outcome})")
            with open(os.path.join(SUGG, "_resolutions.jsonl"), "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"section": sec, "outcome": outcome,
                                     "ts": datetime.datetime.now().isoformat(timespec="seconds")}) + "\n")
            _REBUILD.set()   # background rebuild — mark-done updates in place, so no need to wait
            self._json({"ok": True, "section": sec, "outcome": outcome})
        except Exception as e:
            self._json({"ok": False, "error": _err_text(e)}, code=400)

    def do_unresolve(self):
        """Undo /resolve: move a section's suggestion files back from _resolved/ to active."""
        try:
            data = self._body()
            sec = str(data.get("section", "")).strip()
            if not ID_RE.fullmatch(sec): raise ValueError("bad section id")
            arch = os.path.join(SUGG, "_resolved")
            moved = 0
            for suffix in (".md", ".flags.json", ".tense.json"):
                f = os.path.join(arch, f"{sec}{suffix}")
                if os.path.isfile(f):
                    os.replace(f, os.path.join(SUGG, f"{sec}{suffix}")); moved += 1
            with open(os.path.join(SUGG, "_resolutions.jsonl"), "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"section": sec, "outcome": "reopened"}) + "\n")
            run_builder("build_copyedit_review.py", timeout=90)
            self._json({"ok": True, "section": sec, "restored": moved})
        except Exception as e:
            self._json({"ok": False, "error": _err_text(e)}, code=400)


    def do_suggestion_history(self):
        """GET /suggestion-history?section=NNN -> prior suggestion version ids (newest first)."""
        try:
            import glob as _g
            sec = (self._query().get("section", [""])[0]).strip()
            if not ID_RE.fullmatch(sec): raise ValueError("bad section id")
            vd = os.path.join(SUGG, "_versions", sec)
            vers = [os.path.basename(f)[:-3] for f in sorted(_g.glob(os.path.join(vd, "*.md")), reverse=True)] \
                if os.path.isdir(vd) else []
            self._json({"ok": True, "section": sec, "versions": vers})
        except Exception as e:
            self._json({"ok": False, "error": _err_text(e)}, code=400)

    def do_suggestion_version(self):
        """GET /suggestion-version?section=NNN&v=TS -> that past suggestion's body."""
        try:
            q = self._query()
            sec = (q.get("section", [""])[0]).strip(); v = (q.get("v", [""])[0]).strip()
            if not ID_RE.fullmatch(sec): raise ValueError("bad section id")
            if not re.fullmatch(r"[0-9\-]{1,20}", v): raise ValueError("bad version")
            f = os.path.join(SUGG, "_versions", sec, f"{v}.md")
            m = re.match(r"\s*#\s*\d+\s*\n(.*)", open(f, encoding="utf-8").read(), re.S)
            self._json({"ok": True, "section": sec, "v": v, "text": (m.group(1) if m else "").strip()})
        except Exception as e:
            self._json({"ok": False, "error": _err_text(e)}, code=400)

    def do_suggestion_restore(self):
        """POST {section, v} -> make an old suggestion version the current suggestion (current is versioned first)."""
        try:
            import datetime
            data = self._body()
            sec = str(data.get("section", "")).strip(); v = str(data.get("v", "")).strip()
            if not ID_RE.fullmatch(sec): raise ValueError("bad section id")
            if not re.fullmatch(r"[0-9\-]{1,20}", v): raise ValueError("bad version")
            vf, cur = os.path.join(SUGG, "_versions", sec, f"{v}.md"), os.path.join(SUGG, f"{sec}.md")
            if not os.path.isfile(vf): raise ValueError("no such version")
            if os.path.isfile(cur):
                vd = os.path.join(SUGG, "_versions", sec); os.makedirs(vd, exist_ok=True)
                ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
                with open(cur, encoding="utf-8") as src, \
                     open(os.path.join(vd, f"{ts}.md"), "w", encoding="utf-8") as x:
                    x.write(src.read())
            with open(vf, encoding="utf-8") as src, \
                 open(cur, "w", encoding="utf-8") as x:
                x.write(src.read())
            run_builder("build_copyedit_review.py", timeout=90)
            self._json({"ok": True, "section": sec, "v": v})
        except Exception as e:
            self._json({"ok": False, "error": _err_text(e)}, code=400)

    def _sugg_triage(self, sid):
        try:
            d = load_json(os.path.join(SUGG, f"{sid}.flags.json"))
            return str(d.get("triage", ""))
        except Exception:
            return ""

    def do_accept_all(self):
        """Apply copyedit suggestions to the manuscript in ONE git commit.
        scope 'safe' = every section whose suggestion differs, EXCEPT weak/truncated;
        scope 'all'  = every section whose suggestion differs. Non-destructive: one
        commit, undo with `git revert HEAD`."""
        try:
            data = self._body()
            scope = "all" if str(data.get("scope", "")).lower() == "all" else "safe"
            applied, skipped = [], 0
            for sp in sorted(glob.glob(os.path.join(SUGG, "[0-9]*.md"))):
                sid = os.path.basename(sp)[:-3]
                mp = os.path.join(MAN, f"{sid}.md")
                if not os.path.isfile(mp):
                    continue
                sug_body = sections.read_section(sp)[1]
                printed_id, orig_body = sections.read_section(mp)
                printed = printed_id or sid
                if not sug_body or sug_body == orig_body:     # nothing to apply
                    skipped += 1
                    continue
                if scope == "safe" and self._sugg_triage(sid) in ("weak", "truncated"):
                    skipped += 1
                    continue
                open(mp, "w", encoding="utf-8").write(f"# {printed}\n\n{sug_body}\n")
                applied.append(sid)
            sha = ""
            if applied:
                _, sha = self._git([os.path.join(MAN, f"{s}.md") for s in applied],
                                   f"docs({SLUG}): accept-all copyedit ({scope}, {len(applied)} sections)")
                self._rebuild_reading()
                run_builder("build_copyedit_review.py", timeout=90)
            self._json({"ok": True, "scope": scope, "applied": len(applied),
                        "skipped": skipped, "commit": sha})
        except Exception as e:
            self._json({"ok": False, "error": _err_text(e)}, code=400)

    def do_attic_list(self):
        """GET /attic -> archived (deleted) sections with a one-line preview, newest file first."""
        try:
            rows = []
            for f in glob.glob(os.path.join(ATTIC, "[0-9]*.md")):
                sid = os.path.basename(f)[:-3]
                printed_id, body = sections.read_section(f)
                printed = printed_id or sid
                preview = (body.split("\n", 1)[0] or "(empty)")[:140]
                rows.append({"id": sid, "printed": printed, "preview": preview,
                             "mtime": os.path.getmtime(f)})
            rows.sort(key=lambda r: -r["mtime"])            # most-recently deleted first
            self._json({"ok": True, "sections": rows})
        except Exception as e:
            self._json({"ok": False, "error": _err_text(e)}, code=400)

    def do_attic_restore(self):
        """POST {section} -> move a section back from _attic/ to manuscript/ and re-add to the order."""
        try:
            data = self._body()
            sid = str(data.get("section", "")).strip()
            if not ID_RE.fullmatch(sid): raise ValueError("bad section id")
            src, dst = os.path.join(ATTIC, f"{sid}.md"), os.path.join(MAN, f"{sid}.md")
            if not os.path.isfile(src): raise ValueError("not in _attic")
            if os.path.isfile(dst): raise ValueError("a live section with that id already exists")
            git_mv(src, dst)
            order = self._read_order()                      # re-insert after the closest smaller numeric id
            best = -1
            for i, x in enumerate(order):
                if x.isdigit() and int(x) < int(sid):
                    best = i
            order.insert(best + 1, sid)
            self._write_json_file(ORDER_JSON, order)
            self._git([dst, ORDER_JSON], f"docs({SLUG}): restore section {sid} from _attic")
            self._rebuild_reading()                         # rebuilds both pages (client reloads)
            self._json({"ok": True, "section": sid})
        except Exception as e:
            self._json({"ok": False, "error": _err_text(e)}, code=400)

    def _read_order(self):
        try:
            with open(ORDER_JSON, encoding="utf-8") as fh:
                o = json.load(fh)
                return [str(x) for x in o] if isinstance(o, list) else []
        except Exception:
            return []

    def _json(self, obj, code=200):
        if code >= 400:
            # Endpoints answer {ok:false,error} instead of raising, so this is the
            # one place every failure passes through. Logged here rather than at
            # the 36 call sites, and sys.exc_info() is still live because callers
            # are inside their `except` block — so debug gets the real traceback
            # while the client keeps the path-scrubbed message.
            LOG.info("%s %s -> %s: %s", self.command, self.path, code,
                     (obj or {}).get("error", ""),
                     exc_info=_verbose() and sys.exc_info()[0] is not None)
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)

Handler.ROUTES = {
    "/keystrokes":     Handler.do_keystrokes,
    "/labels":         Handler.do_labels,
    "/order":          Handler.do_order,
    "/parts":          Handler.do_parts,
    "/unnumbered":     Handler.do_unnumbered,
    "/watchlist":      Handler.do_watchlist,
    "/edit-board":     Handler.do_edit_board,
    "/motif-search":   Handler.do_motif_search,
    "/motifs":         Handler.do_motifs,
    "/section/park":   Handler.do_section_park,
    "/section/unpark": Handler.do_section_unpark,
    "/section/add":    Handler.do_section_add,
    "/section/delete": Handler.do_section_delete,
    "/rebuild":        Handler.do_rebuild,
    "/book-new":       Handler.do_book_new,
    "/book-open":      Handler.do_book_open,
    "/book-delete":    Handler.do_book_delete,
    "/import":         Handler.do_import,
    "/pdf":            Handler.do_pdf,
    "/export":         Handler.do_export,
    "/restore":        Handler.do_restore,
    "/accept-all":     Handler.do_accept_all,
    "/resolve":        Handler.do_resolve,
    "/unresolve":      Handler.do_unresolve,
    "/suggestion-restore": Handler.do_suggestion_restore,
    "/attic-restore":  Handler.do_attic_restore,
}

class Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
    """Threaded so a slow rebuild doesn't block the page or other clicks."""
    allow_reuse_address = True
    daemon_threads = True

    def handle_error(self, request, client_address):
        et = sys.exc_info()[0]
        if et and issubclass(et, (ConnectionResetError, BrokenPipeError, ConnectionAbortedError)):
            return                     # browser closed the connection mid-request — harmless, ignore
        super().handle_error(request, client_address)


def bind_warning(bind, allowed=None) -> str:
    """The warning to print for a non-loopback bind, or "" when there is none.

    PAL_BIND=0.0.0.0 is correct and necessary in a container — a process must bind
    all interfaces to be reachable through `docker run -p`. What makes it safe is
    the published port being loopback-only (compose.yaml does this), and nothing
    inside the process can see that. So it warns rather than refuses: refusing
    would break the reverse-proxy setup compose.yaml already documents.

    Worth being exact about what the origin gate does and does not do here. It
    blocks a BROWSER on another site (Origin, and Host against DNS rebinding). It
    is not authentication: `curl -H 'Host: localhost'` satisfies it from anywhere
    on the network, and there are no accounts or tokens behind it.
    """
    if bind in ("127.0.0.1", "::1", "localhost", ""):
        return ""
    if allowed is None:
        allowed = os.environ.get("PAL_ALLOWED_HOSTS", "")
    deliberate = " (PAL_ALLOWED_HOSTS is set, so this looks deliberate)" if allowed.strip() else ""
    return (f"⚠ bound to {bind}, not loopback{deliberate}.\n"
            "  This server has no login: anyone who can reach the port can read and\n"
            "  rewrite the manuscript, and can make it export a PDF. The Host check\n"
            "  stops another site's page in your browser; it does not stop a script.\n"
            "  In Docker this is expected — publish the port on 127.0.0.1 (as\n"
            "  compose.yaml does) and only the host can reach it.")


if __name__ == "__main__":
    if "--verbose" in sys.argv:
        os.environ["PAL_LOG"] = "debug"
    _init_logging()
    threading.Thread(target=_rebuild_worker, daemon=True).start()   # background page rebuilder
    # Bind host is configurable so the same server runs locally (127.0.0.1, safe
    # default) and inside a container (PAL_BIND=0.0.0.0, reachable via the mapped
    # port). The URL we print is always the host-facing one.
    bind = os.environ.get("PAL_BIND", "127.0.0.1")
    host = "localhost" if bind in ("0.0.0.0", "") else bind
    with Server((bind, PORT), Handler) as httpd:
        url = f"http://{host}:{PORT}/reading-copy.html"
        vers = f"versioned in {REPO}" if REPO else "NOT versioned (manuscript is not in a git repo)"
        # A book.toml can point the manuscript (and the rest) anywhere on disk. That
        # is fine for your own book and worth knowing about for one you were sent,
        # since those paths are what this server reads and writes — so say so.
        outside = config.external_paths()
        warn = ""
        if outside:
            warn = ("\n⚠ this book.toml points outside the book directory:\n"
                    + "".join(f"    {k}: {v}\n" for k, v in outside.items())
                    + "  those paths are what gets read and written — check them if "
                      "the book came from someone else.")
        exposed = bind_warning(bind)
        if exposed:
            warn += "\n" + exposed
        print(f"{config.TITLE} — edit+save server → {url}\n"
              f"book:       {config.BOOK_DIR}\n"
              f"manuscript: {MAN}  ({vers})\n"
              f"threaded; every save writes a section back to the manuscript. ctrl-C to stop."
              f"{warn}",
              flush=True)   # flush so the URL shows immediately in `docker logs` / redirected output
        # In a container there's no host browser to open — PAL_NO_BROWSER skips it.
        if not os.environ.get("PAL_NO_BROWSER"):
            try: webbrowser.open(url)
            except Exception: pass
        httpd.serve_forever()
