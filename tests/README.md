# Tests

    just test                        # everything
    just test-one test_escaping      # one module
    just test-one test_escaping.TestLatexEscaping.test_control_words_are_never_live

Stdlib `unittest` only, matching the rest of the tool. Needs `pandoc` for the
export and LaTeX cases; they skip without it rather than fail.

## How it runs

Every test gets a **throwaway book in a temp `PAL_HOME`**, so the suite never
touches `./books` or `./workbench` and never leaves a stray commit. Nothing is
imported from the engine in-process: `engine/config.py` resolves the active book
*at import*, so `import build_book` fails outright without one and the binding is
process-global once it succeeds. Tests therefore drive the real CLI and the real
server the way a user does — subprocesses and HTTP. `harness.Book.engine_eval()`
exists for the few unit-level checks that still need to reach inside.

| File | Covers |
|---|---|
| `harness.py` | the book fixture, the server, the HTTP client |
| `payloads.py` | one injection corpus, shared by every escaping test |
| `test_build.py` | every registered view renders; builds are deterministic; no builder is orphaned |
| `test_origin_gate.py` | **the security model** — Host, Origin, Content-Type, both directions |
| `test_endpoints.py` | each write endpoint round-trips to its authored file and back into the view |
| `test_escaping.py` | authored text never becomes markup or LaTeX |

## Adding to it

- **A new authored-text field?** Add a case to `test_escaping.py`. It will inherit
  the whole corpus in `payloads.py`; you should not need a new payload.
- **A new endpoint?** Add it to the route list in
  `test_origin_gate.test_gate_covers_every_write_endpoint`, and give it a
  round-trip in `test_endpoints.py`. One unguarded route is the whole hole.
- **A new view?** `test_build.test_every_builder_on_disk_is_registered` will fail
  until it is in `dossier.REGISTRY` — that is deliberate. A builder nothing runs
  looks maintained, ships in the package, and produces nothing.

## When something fails

`test_origin_gate.py` is the security model, not a convenience: Host, Origin and
Content-Type are all that stand between the write endpoints and any page the
browser happens to have open. A failure there is a security regression.

`test_escaping.py` is the other half — authored text reaching a `<script>` block
or XeLaTeX. If you have added a field a writer can type into, add it there; it
inherits the whole corpus in `payloads.py` for free.
