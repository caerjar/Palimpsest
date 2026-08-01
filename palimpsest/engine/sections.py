"""Shared section data for the active book's dossier generators.

One place that answers three questions every section-view builder asks:
  - in what ORDER do the sections appear?   -> order.json (a manifest of ids)
  - what LABELS has the author put on them?  -> labels.json
  - how do I render a label chip?            -> label_chips_html()

order.json / labels.json are authored via reading-copy.html + save_server.py.
Both are optional: absent => numeric order / no labels. Ids are the zero-padded
manuscript filenames ("001", "002", …) — the same string used for the #s001 anchor.
We never renumber files; ordering is a manifest over stable ids.
"""
import glob, html, json, os, re
import config

# Paths come from the active book (config.py), not this file's location, so the
# same engine serves any manuscript. Authored manifests live in the book's
# manifests/ dir; generated HTML goes to its dossier/ (== DOSSIER, kept for the
# builders that write there).
MAN = config.MANUSCRIPT
SUGG = config.SUGGESTIONS
DOSSIER = config.ensure_out()
_MF = config.MANIFESTS
ORDER_JSON = os.path.join(_MF, "order.json")
LABELS_JSON = os.path.join(_MF, "labels.json")
PARTS_JSON = os.path.join(_MF, "parts.json")
UNNUMBERED_JSON = os.path.join(_MF, "unnumbered.json")
HELD_JSON = os.path.join(_MF, "held.json")
PART_DIVIDERS_JSON = os.path.join(_MF, "part-dividers.json")

# stable hex palette; a label's default color is a deterministic function of its
# text (same algorithm mirrored in reading-copy's JS so colors match everywhere).
PALETTE = config.PALETTE


def label_color(text):
    return PALETTE[sum(ord(c) for c in text) % len(PALETTE)]


_HEADING = re.compile(r"\s*#\s*(\d+)\s*\n(.*)", re.S)


def split_heading(raw) -> tuple[str | None, str]:
    """(printed_id or None, body) from a section's raw text. The `# N` first line
    is the section's stable id; the body is everything after it."""
    m = _HEADING.match(raw or "")
    return (m.group(1), m.group(2).strip()) if m else (None, (raw or "").strip())


def strip_heading(raw) -> str:
    """A section's body with its leading `# N` id-heading removed."""
    return split_heading(raw)[1]


def heading_id(raw, default=None) -> str | None:
    """A section's printed `# N` id, or `default`.

    The id-only half of split_heading, for the several places that rewrite a file
    and must preserve the heading it already had rather than assume the filename.
    """
    return split_heading(raw)[0] or default


def read_section(path) -> tuple[str | None, str]:
    """(printed_id or None, body) for a section file on disk."""
    with open(path, encoding="utf-8") as fh:
        return split_heading(fh.read())


def _read_json(path, fallback):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return fallback


def section_paths():
    """Manuscript .md paths in display order.

    order.json (list of ids) leads; any on-disk section not named in it is
    appended in numeric order; ids in the manifest with no file (archived or
    typo'd) are skipped. Result always covers exactly the files on disk."""
    by_id = {}
    for p in glob.glob(os.path.join(MAN, "[0-9]*.md")):
        by_id[os.path.basename(p)[:-3]] = p          # "001" -> abs path
    order = _read_json(ORDER_JSON, [])
    if not isinstance(order, list):
        order = []
    for hid in load_held():                            # parked sections: out of the flow
        by_id.pop(hid, None)                           # (still on disk, shown in the shelf)
    out, seen = [], set()
    for sid in order:
        sid = str(sid)
        if sid in by_id and sid not in seen:
            out.append(by_id[sid]); seen.add(sid)
    for sid in sorted(by_id):                          # numeric-order remainder
        if sid not in seen:
            out.append(by_id[sid])
    return out


def load_labels():
    """dict: section id -> list of {"text","color"}. {} if none authored."""
    data = _read_json(LABELS_JSON, {})
    if not isinstance(data, dict):
        return {}
    clean = {}
    for sid, labs in data.items():
        if not isinstance(labs, list):
            continue
        norm = []
        for l in labs:
            if isinstance(l, dict) and l.get("text"):
                t = str(l["text"])
                # a label's color reaches a style attribute, so it must be a hex
                # literal or nothing (config.safe_color falls back to the default)
                norm.append({"text": t, "color": config.safe_color(l.get("color"), label_color(t))})
            elif isinstance(l, str) and l.strip():
                norm.append({"text": l.strip(), "color": label_color(l.strip())})
        if norm:
            clean[str(sid)] = norm
    return clean


def load_parts():
    """dict: start-section id -> {"title","subtitle"}.

    parts.json is a flat array of {"start","title","subtitle"?}; a part-break
    renders immediately BEFORE its start section in display order. Keyed on the
    stable section id so the break follows the section across reorders. Entries
    whose start id is not a valid string are skipped; callers decide what to do
    with starts that aren't currently on disk (banner simply won't render)."""
    data = _read_json(PARTS_JSON, [])
    if not isinstance(data, list):
        return {}
    out = {}
    for p in data:
        if not isinstance(p, dict):
            continue
        start = str(p.get("start") or "").strip()
        title = str(p.get("title") or "").strip()
        if not start or not title:
            continue
        out[start] = {"title": title, "subtitle": str(p.get("subtitle") or "").strip()}
    return out


def _held_entries():
    """held.json as a list of {"id","anchor"} (tolerant of bare id strings)."""
    data = _read_json(HELD_JSON, [])
    if not isinstance(data, list):
        return []
    out = []
    for h in data:
        if isinstance(h, dict) and str(h.get("id") or "").strip():
            anchor = h.get("anchor")
            out.append({"id": str(h["id"]).strip(),
                        "anchor": str(anchor).strip() if anchor else None})
        elif isinstance(h, str) and h.strip():
            out.append({"id": h.strip(), "anchor": None})
    return out


def load_held():
    """set of section ids that are PARKED — pulled out of the flow (no print, no
    number) but kept on disk in manuscript/ and shown in the reading-copy shelf."""
    return {h["id"] for h in _held_entries()}


def held_paths():
    """[path] for parked sections, in held.json (shelf display) order."""
    out = []
    for h in _held_entries():
        p = os.path.join(MAN, f"{h['id']}.md")
        if os.path.isfile(p):
            out.append(p)
    return out


def load_dividers():
    """Ordered [{"id","title"}] for the part-divider sections (part-dividers.json),
    filtered to ids that exist on disk. A section's PART = which divider precedes it
    in the flow; these ids self-title via their own {{contents}} block, so they are
    NOT parts.json banners (that path is untouched)."""
    data = _read_json(PART_DIVIDERS_JSON, [])
    if not isinstance(data, list):
        return []
    out = []
    for d in data:
        if not isinstance(d, dict):
            continue
        sid = str(d.get("id") or "").strip()
        if sid and os.path.isfile(os.path.join(MAN, f"{sid}.md")):
            out.append({"id": sid, "title": str(d.get("title") or f"Part ({sid})").strip()})
    return out


def part_of(sid, order_ids, dividers=None):
    """Which divider id `sid` belongs under, given the flow id-list `order_ids`:
    the divider with the greatest flow-position at or before `sid`. Returns "" for
    front matter (before the first divider) or if `sid` isn't in the flow."""
    if dividers is None:
        dividers = load_dividers()
    pos = {s: i for i, s in enumerate(order_ids)}
    if sid not in pos:
        return ""
    here = pos[sid]
    best_pos, best_id = -1, ""
    for d in dividers:
        dp = pos.get(d["id"])
        if dp is not None and dp <= here and dp > best_pos:
            best_pos, best_id = dp, d["id"]
    return best_id


def load_unnumbered():
    """set of section ids that still PRINT but are not counted/numbered.

    An unnumbered section (front matter, an interlude, a contents page) renders
    its prose but carries no §-number and does not advance the scene counter, so
    the numbered sections around it stay in unbroken sequence."""
    data = _read_json(UNNUMBERED_JSON, [])
    if not isinstance(data, list):
        return set()
    return {str(x).strip() for x in data if str(x).strip()}


def label_chips_html(sid, labels=None):
    """Shared <span class="lchip"> markup for a section's authored labels.

    Distinct from motif .mchip so the two tag dimensions read differently."""
    if labels is None:
        labels = load_labels()
    row = ""
    for l in labels.get(str(sid), []):
        c = l["color"]
        row += (f'<span class="lchip" data-label="{html.escape(l["text"], quote=True)}" '
                f'data-color="{c}" style="background:{c}22;color:{c};border-color:{c}66">'
                f'{html.escape(l["text"])}</span>')
    return row
