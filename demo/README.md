# The Writing Record demo

A single self-contained HTML file that shows the **Writing Record** page playing
one recorded writing session: the prose retyping itself, the same keystrokes
drawn as notation, and a synthesizer reading that notation — with the dials,
scale, key and instrument moving as it goes.

**Live: <https://caerjar.github.io/Palimpsest/>**

    python3 demo/build_demo.py
    open docs/index.html                        # no server needed

## What it is

The demo page **is** `palimpsest/engine/assets/writing-record.html`. `build_demo.py`
takes that page, fills the placeholders `dossier.build()` normally fills, inlines
`style.css`, `pal.js` and `demo.css`, bakes `session.jsonl` into the markup as a
`<script type="application/x-ndjson">`, and appends `autopilot.js`.

`autopilot.js` doesn't reimplement anything. It loads the baked-in session
through the page's own `ingest()`, then drives the real controls — setting the
knob, slider or select and dispatching the event that control's own listener
already handles — so the sound, the staff and the CONFIG editor can't drift
apart. A cue list placed by fraction of the piece narrates each move into the
caption bar at the bottom.

Nothing about it is special-cased: **fix the real page, then rebuild the demo.**
`build_demo.py` fails loudly if a piece of markup it patches has moved.

## Files

| | |
|---|---|
| `build_demo.py` | the builder — stdlib only, like the rest of the tool |
| `autopilot.js`  | loads the session, works the controls, narrates |
| `demo.css`      | splash + caption bar; hides the file pickers |
| `session.jsonl` | the recorded session that ships with the demo |
| `../docs/index.html` | the built page — regenerate it, don't hand-edit it |

`docs/` is what GitHub Pages publishes (main branch, `/docs` folder), so the
page people open is byte-for-byte the one `build_demo.py` writes here. Rebuild
it in the same commit as any change to the Writing Record page, or the live
demo drifts from the app.

## Swapping in another session

Any `writing-*.jsonl` written by the reading copy works:

    python3 demo/build_demo.py --session ~/Downloads/writing-….jsonl

The autopilot's cues are positioned by *fraction* of the piece, so they land in
the same musical places whatever the session's length. Only the closing line of
`CUES` in `autopilot.js` names this particular session's numbers.

## Publishing it

The file has no external references — no fonts, no scripts, no network calls of
any kind — so it can be dropped anywhere static (GitHub Pages, a gist, an email
attachment) and will work offline. It needs one click before it makes a sound:
browsers require a gesture before an `AudioContext` may start, which is what the
splash screen is for.
