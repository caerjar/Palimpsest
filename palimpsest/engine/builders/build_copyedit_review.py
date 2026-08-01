#!/usr/bin/env python3
"""Side-by-side copyedit review: original (left) vs. suggestion (right), with
word-level change highlighting, per-section flags, and a triage badge.

Non-destructive: suggestions live in ../manuscript-suggestions/NNN.md (+ NNN.flags.json).
The originals in ../manuscript/NNN.md are never touched here. Accepting a section in
the UI reuses the reading-copy save-server's /save endpoint (writes manuscript/NNN.md
and git-commits), so every acceptance is a retrievable version.

Build:  pal build copyedit
Serve:  pal serve  (then open copyedit-review.html)"""
import difflib, html, json, os, re
from sections import read_section, section_paths, load_labels, label_chips_html
from nav import topbar_html, page_head, script_json

import config
MAN = config.MANUSCRIPT
SUGG = config.SUGGESTIONS
OUT = os.path.join(config.OUT, "copyedit-review.html")

TOKEN_RE = re.compile(r"\s+|\S+")          # whitespace-runs and word-runs as separate tokens
ETC_RE = re.compile(r"\betc\b", re.I)
# 1-letter name initials: a standalone capital, excluding pronoun "I", article "A", and "O".
INIT1_RE = re.compile(r"(?<![A-Za-z])([B-HJ-NP-Z])(?![A-Za-z'’])")
# 2-letter all-caps names, excluding common acronyms.
ACRONYMS = {"AI", "TV", "US", "UK", "EU", "OK", "LA", "NY", "SF", "DC", "HD", "PM", "AM",
            "ID", "IQ", "CV", "MD", "DJ", "ET", "TM", "PC", "UN", "OG", "BC", "AD"}
INIT2_RE = re.compile(r"(?<![A-Za-z])([A-Z]{2})(?![A-Za-z'’])")


def detect_initials(text):
    """Distinct 1–2 letter name-initials in a body -> Counter(letter -> count)."""
    from collections import Counter
    c = Counter()
    for m in INIT1_RE.finditer(text):
        c[m.group(1)] += 1
    for m in INIT2_RE.finditer(text):
        if m.group(1) not in ACRONYMS:
            c[m.group(1)] += 1
    return c

# copyedit-state triage. Notes are copyedited like prose, so they have no category.
TRIAGE_ORDER = ["truncated", "flags", "fixes", "clean", "done", "pending"]
TRIAGE_LABEL = {"truncated": "truncated", "flags": "flags",
                "fixes": "fixes", "clean": "clean",
                "done": "done", "pending": "pending"}


def read_body(path):
    return read_section(path)[1]


def esc_ws(tok):
    """Escape a token; render newlines inside whitespace runs as <br>."""
    return html.escape(tok).replace("\n", "<br>\n")


def diff_cols(orig, sugg):
    """Return (left_html, right_html, n_changes). Left marks deletions (<del>),
    right marks insertions/changes (<mark>). Whitespace is never wrapped."""
    a, b = TOKEN_RE.findall(orig), TOKEN_RE.findall(sugg)
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    left, right, changes = [], [], 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            left.append("".join(esc_ws(t) for t in a[i1:i2]))
            right.append("".join(esc_ws(t) for t in b[j1:j2]))
            continue
        for t in a[i1:i2]:
            left.append(f"<del>{esc_ws(t)}</del>" if t.strip() else esc_ws(t))
        for t in b[j1:j2]:
            right.append(f"<mark>{esc_ws(t)}</mark>" if t.strip() else esc_ws(t))
        if any(t.strip() for t in a[i1:i2]) or any(t.strip() for t in b[j1:j2]):
            changes += 1
    return "".join(left), "".join(right), changes


def highlight_flags(s):
    """Deterministic inline highlight of 'etc' and 1–2 letter name initials
    (safe on the diff HTML: tag/attr names carry no standalone capitals)."""
    s = ETC_RE.sub(lambda m: f'<span class="flag flag-etc" title="etc">{m.group(0)}</span>', s)
    s = INIT1_RE.sub(lambda m: f'<span class="flag flag-initial" title="1-letter name">{m.group(1)}</span>', s)
    s = INIT2_RE.sub(lambda m: (f'<span class="flag flag-initial" title="2-letter name">{m.group(1)}</span>'
                                if m.group(1) not in ACRONYMS else m.group(0)), s)
    return s


def load_sidecar(sid):
    p = os.path.join(SUGG, f"{sid}.flags.json")
    try:
        with open(p, encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def flag_list_html(flags):
    if not flags:
        return ""
    rows = []
    for f in flags:
        t = html.escape(str(f.get("type", "")))
        q = html.escape(str(f.get("quote", "")))
        n = html.escape(str(f.get("note", "")))
        rows.append(f'<li class="fl fl-{t}"><span class="fltype">{t}</span>'
                    f'<span class="flquote">{q}</span><span class="flnote">{n}</span></li>')
    return '<ul class="ceflags">' + "".join(rows) + "</ul>"





def load_resolutions():
    """sid -> last outcome from ../manuscript-suggestions/_resolutions.jsonl ({} if none).
    A section is 'done' when it has no live suggestion file and its last outcome isn't 'reopened'."""
    out = {}
    p = os.path.join(SUGG, "_resolutions.jsonl")
    try:
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if r.get("section"):
                out[str(r["section"])] = str(r.get("outcome", ""))
    except Exception:
        pass
    return out


def build():
    files = section_paths()
    blocks, counts, n_hasflags = [], {}, 0
    resolutions = load_resolutions()
    labels = load_labels()
    for pos, path in enumerate(files, 1):
        fn = os.path.basename(path)[:-3]                 # stable id "001"
        orig = read_body(path)
        sugg_path = os.path.join(SUGG, f"{fn}.md")

        side = load_sidecar(fn)
        flags = list(side.get("flags", []) if isinstance(side.get("flags"), list) else [])
        tf = os.path.join(SUGG, f"{fn}.tense.json")            # tense-pass flags (separate sidecar)
        if os.path.exists(tf):
            try:
                with open(tf, encoding="utf-8") as fh:
                    td = json.load(fh)
                if isinstance(td.get("flags"), list):
                    flags += td["flags"]
            except Exception:
                pass
        diagnosis = html.escape(str(side.get("diagnosis", "")))
        raw_triage = side.get("triage")

        if os.path.exists(sugg_path):
            sugg = read_body(sugg_path)
            sugg_body = sugg
            left, right, n = diff_cols(orig, sugg)
        else:                                            # not generated yet
            left = html.escape(orig).replace("\n", "<br>\n")
            right, n = left, 0
            sugg_body = ""
            raw_triage = raw_triage or "pending"

        # computed here, deterministically, from the section itself
        n_etc = len(ETC_RE.findall(orig))
        if n_etc:
            flags.append({"type": "etc", "quote": "etc", "note": f"{n_etc} occurrence{'s' if n_etc!=1 else ''}"})
        seen_init = {f.get("quote") for f in flags if f.get("type") == "initial"}
        for letter, ct in detect_initials(orig).items():
            if letter in seen_init:
                continue
            flags.append({"type": "initial", "quote": letter,
                          "note": f"{ct} occurrence{'s' if ct != 1 else ''} — 1–2 letter name to replace"})
        n_flags = len(flags)
        done_outcome = resolutions.get(fn)
        is_done = bool(done_outcome) and done_outcome != "reopened"
        if is_done:                       # a finished section shows no flags at all
            flags, n_flags = [], 0

        # BADGE = primary state (weak/truncated/notes/pending win; else fixes; else flags; else clean).
        # Flags are surfaced separately by the ⚑ chip so edited sections still read "fixes".
        if is_done:
            triage = "done"
        elif raw_triage in ("truncated", "pending"):   # weak/notes retired as copyedit-triage (weak is now a structural axis)
            triage = raw_triage
        elif n:
            triage = "fixes"
        elif n_flags:
            triage = "flags"
        else:
            triage = "clean"
        counts[triage] = counts.get(triage, 0) + 1
        badge_label = f"done · {done_outcome}" if (triage == "done" and done_outcome) else TRIAGE_LABEL[triage]
        if n_flags:
            n_hasflags += 1

        right = right if is_done else highlight_flags(right)
        diag_html = f'<span class="cediag">{diagnosis}</span>' if diagnosis else ""
        lchips = label_chips_html(fn, labels)
        flagchip = f'<span class="ceflagchip" title="{n_flags} flag(s) to resolve">⚑{n_flags}</span>' if n_flags else ""

        blocks.append(
            f'<article class="ce t-{triage}" id="ce{fn}" data-triage="{triage}" '
            f'data-flags="{1 if n_flags else 0}" '
            f'data-sec="{fn}">'
            f'<div class="cehd"><span class="cepos">§{pos}</span>'
            f'<span class="cefid">{fn}</span>'
            f'<span class="cebadge b-{triage}">{badge_label}</span>'
            f'{flagchip}'
            f'<span class="cecount">{n} change{"s" if n != 1 else ""}</span>{diag_html}'
            f'<span class="cewc">{len(orig.split())} words</span>'
            f'<span class="celabels" data-sec="{fn}">{lchips}</span>'
            f'<button class="ce-addcat" title="add a category pill">+ cat</button>'
            f'<button class="ce-ins" title="insert a new blank section below this one">insert below</button>'
            f'<button class="ce-del" title="delete (archive) this section">delete</button></div>'
            f'<div class="cecols">'
            f'<textarea class="ceorig" spellcheck="true" lang="en" '
            f'title="your working version - edit here, then save with save left version">{html.escape(orig)}</textarea>'
            f'<div class="cesugg ro" title="suggestion (read-only reference) - pull it into your left">{right}</div>'
            f'</div>'
            f'<textarea class="ce-suggsrc" hidden>{html.escape(sugg_body)}</textarea>'
            f'{flag_list_html(flags)}'
            f'<div class="ceactions">'
            f'<button class="ce-accept-orig" title="save your left working version to the file">save left version</button>'
            f'<button class="ce-pull" title="pull all the suggestion edits into your left version">accept suggestion -&gt; left</button>'
            f'<button class="ce-hist" title="past saved versions of your left working text">history (left)</button>'
            f'<button class="ce-shist" title="past versions of the suggestion file">history (suggestion)</button>'
            f'<button class="ce-done" title="finish - save your version as final and record it">mark done</button>'
            f'<span class="cestatus"></span></div>'
            f'<div class="cehist" hidden></div>'
            f'</article>')

    filt = [f'<button class="fbtn on" data-t="all">all ({len(files)})</button>']
    for t in TRIAGE_ORDER:
        if counts.get(t):
            filt.append(f'<button class="fbtn" data-t="{t}">{TRIAGE_LABEL[t]} ({counts[t]})</button>')
    if n_hasflags:
        filt.append(f'<button class="fbtn" data-t="hasflags">⚑ has flags ({n_hasflags})</button>')

    doc = (TEMPLATE.replace("<!--LABELS-->", "<script>window.CE_LABELS=" + script_json(labels) + ";</script>")
                   .replace("<!--NAV-->", topbar_html("copyedit-review.html"))
                   .replace("<!--FILTERS-->", "".join(filt))
                   .replace("<!--BLOCKS-->", "\n".join(blocks))
                   # per-book localStorage namespace: two books never share drafts
                   .replace("__PAL_NS__", config.SAFE_SLUG))
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(doc)
    print(f"wrote {OUT} · {len(files)} sections · " +
          " ".join(f"{k}:{v}" for k, v in sorted(counts.items())))


STYLE = r"""
<style>
/* Inherit the shared chrome (body, .wrap, header, h1, fonts) from style.css so
   this page matches every other one. Only the diff-specific vars are added here;
   --bg aliases the shared paper so the local component styles keep working. */
:root{--bg:var(--paper);--del:var(--red);--ins:var(--ok);--flag:var(--warn);}
/* the two-column diff wants more room than the default column — widen just the
   copyedit content, but keep the same boxed paper look as the rest of the site */
.wrap{max-width:1280px;}
.acceptbar{display:flex;align-items:center;flex-wrap:wrap;gap:8px;padding:10px 12px;margin:10px 0;
  background:var(--bg2);border:1px solid var(--line);border-radius:8px;font:13px system-ui;}
.acceptbar button{font:12px system-ui;border:1px solid var(--line);border-radius:6px;padding:4px 12px;cursor:pointer;background:var(--field);}
#acc-safe{background:var(--ok);color:var(--on-accent);border-color:var(--ok);} #acc-safe:hover{background:#186c58;}
#acc-all{background:var(--warn);color:var(--on-accent);border-color:var(--warn);} #acc-all:hover{background:#853500;}
.accstatus{color:var(--soft);} .accnote{color:var(--faint);margin-left:auto;font-size:12px;}
.statsbar{padding:4px 2px;font:13px system-ui;color:var(--soft);} #total-wc{color:#1f8a70;font-size:15px;}
#view-deleted{font:12px system-ui;border:1px solid var(--line);border-radius:6px;padding:4px 12px;cursor:pointer;background:var(--field);color:var(--soft);}
#attic-panel{margin:6px 0;padding:8px 12px;border:1px solid var(--line);border-radius:8px;background:var(--sunk);font:12px system-ui;max-height:320px;overflow:auto;}
.atrow{display:flex;align-items:center;gap:8px;padding:3px 0;border-bottom:1px dashed var(--line);}
.atid{font-weight:700;min-width:40px;} .atprev{flex:1;color:var(--soft);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.atbtn{font:11px system-ui;border:1px solid var(--ok);border-radius:5px;padding:2px 10px;cursor:pointer;background:var(--ok);color:var(--on-accent);}
.filterbar{position:sticky;top:46px;background:var(--paper);padding:10px 0;border-bottom:1px solid var(--line);z-index:5;
  display:flex;flex-wrap:wrap;gap:6px;}
.fbtn{font:12px system-ui;border:1px solid var(--line);background:var(--field);border-radius:14px;padding:3px 10px;cursor:pointer;color:var(--soft);}
.fbtn.on{background:var(--invert-bg);color:var(--invert-ink);border-color:var(--invert-bg);}
.ce{border:1px solid var(--line);border-radius:8px;margin:16px 0;background:var(--field);overflow:hidden;}
.ce.hide{display:none;}
/* weak spotlight: a distinct left border so structurally weak sections stand out at a glance */
.ce.w-weak{border-left:5px solid #c0392b;}
.cehd{display:flex;align-items:center;gap:10px;padding:7px 12px;background:var(--bg2);border-bottom:1px solid var(--line);font:13px system-ui;}
.cepos{font-weight:700;} .cefid{color:var(--faint);font-size:11px;}
.cehd button{font:11px system-ui;border:1px solid var(--line);border-radius:5px;padding:1px 8px;cursor:pointer;background:var(--field);color:var(--soft);}
.celabels{display:inline-flex;gap:4px;flex-wrap:wrap;align-items:center;margin-left:auto;}
.lchip{font-size:11px;padding:1px 8px;border-radius:10px;border:1px solid #ccc;cursor:pointer;}
.ce-del{color:#a02c17;}
.cebadge{font-size:11px;padding:1px 8px;border-radius:10px;background:#e8e0cd;color:var(--soft);}
.b-weak{background:#f2d5cf;color:#a02c17;} .b-truncated{background:#efd9b8;color:#8a5a12;}
.b-flags{background:#f6e6c8;color:#8a6410;} .b-fixes{background:#cfe9df;color:#166b52;}
.b-clean{background:#e5eee9;color:#5a7d6f;} .b-pending{background:#eee;color:#888;} .b-done{background:#e2e0d8;color:var(--soft);}
.ce.resolved{opacity:.62;} .ce.resolved .cehd{background:var(--bg2);}
.ce-reopen{font:11px system-ui;border:1px solid var(--line);border-radius:5px;padding:2px 9px;cursor:pointer;background:var(--field);color:var(--soft);margin-left:8px;}
.ce-done{background:#5b2c6f;color:var(--on-accent);border-color:#5b2c6f;} .ce-done:hover{background:#4a2259;}
.ceflagchip{font-size:11px;padding:1px 7px;border-radius:10px;background:#f7e2c9;color:#a04000;border:1px solid #a0400044;}
.cecount{color:var(--faint);font-size:11px;} .cewc{color:var(--soft);font-size:11px;font-weight:600;} .cediag{color:#a02c17;font-style:italic;font-size:12px;}
.cecols{display:grid;grid-template-columns:1fr 1fr;gap:0;}
.ceorig,.cesugg{padding:12px 14px;min-height:40px;white-space:normal;}
.ceorig{border-right:1px solid var(--line);background:var(--paper);}
.cesugg{outline:none;color:var(--ink2);} .cesugg:focus{background:var(--card);}
.cesugg.ro{background:var(--sunk);color:var(--ink2);cursor:default;}
textarea.ceorig{display:block;width:100%;box-sizing:border-box;border:none;border-right:1px solid var(--line);background:var(--paper);color:var(--ink2);caret-color:var(--gold);font:16px/1.6 Georgia,serif;padding:12px 14px;resize:vertical;min-height:60px;outline:none;overflow:hidden;}
textarea.ceorig:focus{background:var(--card);}
.ce.dirty textarea.ceorig{border-left:3px solid #c0392b;}
del{color:var(--del);text-decoration:line-through;text-decoration-color:#c0392b88;}
mark{background:#d3f0e5;color:#12503c;padding:0 1px;border-radius:2px;}
.flag{background:#f7e2c9;border-bottom:2px solid var(--flag);border-radius:2px;padding:0 1px;}
.ceflags{margin:0;padding:8px 14px;list-style:none;border-top:1px dashed var(--line);background:var(--sunk);font:12px system-ui;}
.fl{display:flex;gap:8px;padding:2px 0;} .fltype{color:var(--flag);font-weight:600;min-width:64px;}
.fl-language{background:#f6eefb;border-radius:3px;} .fl-language .fltype{color:#7d3c98;}
.flag-initial{background:#fde3e3;border-bottom:2px solid #c0392b;border-radius:2px;padding:0 1px;}
.fl-initial{background:#fdeaea;border-radius:3px;} .fl-initial .fltype{color:#c0392b;}
.fl-tense{background:#eaf4fb;border-radius:3px;} .fl-tense .fltype{color:#2874a6;}
.flquote{color:#4a4335;font-style:italic;} .flnote{color:#8a7f68;}
.ceactions{display:flex;align-items:center;gap:8px;padding:8px 12px;border-top:1px solid var(--line);background:var(--bg2);}
.ceactions button{font:12px system-ui;border:1px solid var(--line);border-radius:6px;padding:4px 12px;cursor:pointer;background:var(--field);}
.ce-accept{background:var(--ok);color:var(--on-accent);border-color:var(--ok);} .ce-accept:hover{background:#186c58;}
.ce-sugg,.ce-orig,.ce-hist{color:var(--soft);} .ce-hist{color:#5b7d95;} .cestatus{font:12px system-ui;color:var(--soft);}
.ce.saved{opacity:.72;} .ce.saved .ceactions{background:#e5eee9;} .ce.saved .cebadge{background:#cfe9df;color:#166b52;}
.cehist{padding:8px 12px;border-top:1px dashed var(--line);background:var(--sunk);font:12px system-ui;}
.hrow{display:flex;align-items:center;gap:8px;padding:2px 0;}
.htime{color:#4a4335;} .hsub{color:#8a7f68;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.hbtn{font:11px system-ui;border:1px solid var(--line);border-radius:5px;padding:1px 8px;cursor:pointer;background:var(--field);}
@media(max-width:820px){.cecols{grid-template-columns:1fr;}.ceorig{border-right:none;border-bottom:1px solid var(--line);}}

/* Vapor: these chips are semantic — the hue MEANS something, so it is kept and
   moved to the text, over a dark ground of the same hue. Not a blanket filter:
   that darkens text and background together, leaving the contrast unchanged.
[data-theme="vapor"] .cebadge{background:#312916;color:#d2c29d;border-color:#776437;}
[data-theme="vapor"] .b-weak{background:#38160f;color:#ed9382;border-color:#982a16;}
[data-theme="vapor"] .b-truncated{background:#3a280d;color:#efc381;border-color:#996414;}
[data-theme="vapor"] .b-flags{background:#3d2c0a;color:#f0cd7f;border-color:#9b7112;}
[data-theme="vapor"] .b-fixes{background:#163127;color:#89e7cb;border-color:#1e906e;}
[data-theme="vapor"] .b-clean{background:#1c2b23;color:#acc3ba;border-color:#49655a;}
[data-theme="vapor"] .b-pending{background:#242424;color:#b8b8b8;border-color:#575757;}
[data-theme="vapor"] .b-done{background:#29271e;color:#c2bead;border-color:#635e4a;}
[data-theme="vapor"] .ce-done{color:#f4f1ff;border-color:#7e3d99;}
[data-theme="vapor"] .ceflagchip{background:#3e2609;color:#ffa970;border-color:#ad4500;}
[data-theme="vapor"] .flag{background:#3e2609;color:#edbc83;border-color:#975c16;}
[data-theme="vapor"] .fl-language{background:#290e3a;color:#c28be4;border-color:#63218c;}
[data-theme="vapor"] .flag-initial{background:#430505;color:#f57a7a;border-color:#a20c0c;}
[data-theme="vapor"] .fl-initial{background:#410606;color:#f37d7d;border-color:#9e0f0f;}
[data-theme="vapor"] .fl-tense{background:#0b283c;color:#87c0e8;border-color:#1c6192;}
[data-theme="vapor"] .ce.saved .ceactions{background:#1c2b23;color:#a9c7b6;border-color:#456955;}
[data-theme="vapor"] .ce.saved .cebadge{background:#163127;color:#89e7cb;border-color:#1e906e;}

[data-theme="vapor"] mark{background:#13392b;color:#93e7cc;}
</style>
"""

SCRIPT = r"""
<script>
const HTTP=location.protocol.startsWith('http');
// triage filter
document.querySelectorAll('.fbtn').forEach(b=>b.addEventListener('click',()=>{
  document.querySelectorAll('.fbtn').forEach(x=>x.classList.remove('on'));
  b.classList.add('on'); const t=b.dataset.t;
  document.querySelectorAll('.ce').forEach(a=>{
    let show;
    if(t==='all') show=true;
    else if(t==='hasflags') show=a.dataset.flags==='1';
    else show=a.dataset.triage===t;
    a.classList.toggle('hide', !show);
  });
}));

// ---- accept all ----
async function acceptAll(scope){
  const s=document.getElementById('acc-status');
  if(!HTTP){s.textContent='needs `pal serve` (you are viewing this file directly, not through the server)';return;}
  const label=scope==='all'?'EVERY changed section (including weak/truncated)':'all changed sections except weak/truncated';
  if(!confirm('Apply '+label+' to the manuscript?\n\nThis writes the suggestions into your files as ONE git commit.\nUndo anytime with: git revert HEAD'))return;
  const bs=document.getElementById('acc-safe'), ba=document.getElementById('acc-all');
  bs.disabled=true; ba.disabled=true; s.textContent='applying '+scope+'… (this rebuilds the page)';
  try{
    const j=await (await fetch('/accept-all',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({scope:scope})})).json();
    if(j.ok){s.textContent='applied '+j.applied+' · skipped '+j.skipped+' · '+(j.commit||'no change')+' — reloading';
      setTimeout(()=>location.reload(),1000);}
    else{s.textContent='failed: '+(j.error||'?');bs.disabled=false;ba.disabled=false;}
  }catch(e){s.textContent='failed — is `pal serve` running?';bs.disabled=false;ba.disabled=false;}
}
(function(){const a=document.getElementById('acc-safe'),b=document.getElementById('acc-all');
  if(a)a.addEventListener('click',()=>acceptAll('safe'));
  if(b)b.addEventListener('click',()=>acceptAll('all'));})();
function esc(x){return x.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function toHTML(t){return esc(t).replace(/\n/g,'<br>\n');}
function wcount(t){return (t.match(/\S+/g)||[]).length;}
function updateTotal(){let s=0;document.querySelectorAll('textarea.ceorig').forEach(t=>s+=wcount(t.value));const el=document.getElementById('total-wc');if(el)el.textContent=s.toLocaleString();}
// per-section editor (mimics the reading interface: edit here, save sticks, undo via history)
document.querySelectorAll('.ce').forEach(art=>{
  const sec=art.dataset.sec, status=art.querySelector('.cestatus');
  const left=art.querySelector('.ceorig'), sugg=art.querySelector('.cesugg'), hist=art.querySelector('.cehist'), suggsrc=art.querySelector('.ce-suggsrc');
  const grow=(t)=>{if(t){t.style.height='auto';t.style.height=(t.scrollHeight+2)+'px';}};
  const draftKey='__PAL_NS___draft_'+sec;
  if(left&&left.tagName==='TEXTAREA'){
    const d=localStorage.getItem(draftKey);
    if(d!==null){ if(d===left.value){localStorage.removeItem(draftKey);} else {left.value=d;art.classList.add('dirty');} }
    grow(left);
    left.addEventListener('input',()=>{grow(left);localStorage.setItem(draftKey,left.value);art.classList.add('dirty');const wcel=art.querySelector('.cewc');if(wcel)wcel.textContent=wcount(left.value)+' words';updateTotal();});
  }
  const say=(m)=>{status.textContent=m;};
  const clean=(t)=>t.replace(/ /g,' ').replace(/\s+$/,'');

  async function doSaveLeft(btn){
    if(!HTTP){say('NOT saved - open http://127.0.0.1:8137/copyedit-review.html via pal serve');return;}
    btn.disabled=true;say('saving...');
    try{
      const j=await (await fetch('/save',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({section:sec,text:clean(left.value)})})).json();
      if(j.ok){localStorage.removeItem(draftKey);art.classList.remove('dirty');say(j.committed?('saved left version - '+j.commit):'unchanged - nothing to commit');}
      else say('save failed: '+(j.error||'?'));
    }catch(e){say('save failed - is pal serve running?');}
    btn.disabled=false;
  }
  const sb=art.querySelector('.ce-accept-orig'); if(sb)sb.addEventListener('click',(e)=>doSaveLeft(e.target));

  const pb=art.querySelector('.ce-pull');
  if(pb)pb.addEventListener('click',()=>{left.value=suggsrc?suggsrc.value:'';grow(left);localStorage.setItem(draftKey,left.value);art.classList.add('dirty');const wcel=art.querySelector('.cewc');if(wcel)wcel.textContent=wcount(left.value)+' words';updateTotal();say('pulled suggestion into left - edit it, then save left version');});

  const db=art.querySelector('.ce-done');
  if(db)db.addEventListener('click',async(e)=>{
    if(!HTTP){say('mark done needs pal serve');return;}
    e.target.disabled=true;say('finishing...');
    try{
      const j=await (await fetch('/resolve',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({section:sec,text:clean(left.value)})})).json();
      if(j.ok){
        localStorage.removeItem(draftKey); art.classList.remove('dirty');
        ['fixes','flags','clean','truncated'].forEach(x=>art.classList.remove('t-'+x));
        art.classList.add('t-done'); art.dataset.triage='done'; art.dataset.flags='0';
        const bdg=art.querySelector('.cebadge'); if(bdg){bdg.textContent='done \u00b7 '+j.outcome; bdg.className='cebadge b-done';}
        const chp=art.querySelector('.ceflagchip'); if(chp)chp.remove();
        const flg=art.querySelector('.ceflags'); if(flg)flg.remove();
        const cc=art.querySelector('.cecount'); if(cc)cc.textContent='0 changes';
        if(sugg)sugg.innerHTML=toHTML(left.value);
        say('done ('+j.outcome+') - no reload, keep working');
      }
      else{say('failed: '+(j.error||'?'));e.target.disabled=false;}
    }catch(err){say('failed - is pal serve running?');e.target.disabled=false;}
  });

  async function showHist(listUrl,verUrl,isSugg){
    if(!HTTP){say('history needs pal serve');return;}
    if(!hist.hidden){hist.hidden=true;return;}
    hist.hidden=false;hist.textContent='loading...';
    try{
      const j=await (await fetch(listUrl+'?section='+encodeURIComponent(sec))).json();
      if(!j.ok){hist.textContent='unavailable: '+(j.error||'?');return;}
      const vers=j.versions||[];
      hist.innerHTML='';
      if(!vers.length){hist.textContent=isSugg?'no earlier versions of the suggestion':'no past versions';return;}
      vers.forEach(v=>{
        const id=isSugg?v:v.hash, lbl=isSugg?v:((v.date||'')+'  '+(v.subject||''));
        const row=document.createElement('div');row.className='hrow';
        row.innerHTML='<span class="hsub">'+esc(lbl)+'</span>';
        const vb=document.createElement('button');vb.className='hbtn';vb.textContent='view';
        vb.addEventListener('click',async()=>{
          const q=isSugg?('?section='+encodeURIComponent(sec)+'&v='+encodeURIComponent(id))
                        :('?section='+encodeURIComponent(sec)+'&commit='+encodeURIComponent(id));
          const vj=await (await fetch(verUrl+q)).json();
          if(vj.ok){let pre=row.querySelector('pre');if(!pre){pre=document.createElement('pre');pre.className='hview';row.appendChild(pre);}pre.textContent=vj.text;}
        });
        const rn=document.createElement('button');rn.className='hbtn';rn.textContent='restore';
        rn.addEventListener('click',async()=>{
          const url=isSugg?'/suggestion-restore':'/restore';
          const payload=isSugg?{section:sec,v:id}:{section:sec,commit:id};
          const rj=await (await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)})).json();
          if(rj.ok){say('restored - reloading');setTimeout(()=>location.reload(),600);}else say('restore failed: '+(rj.error||'?'));
        });
        row.appendChild(vb);row.appendChild(rn);hist.appendChild(row);
      });
    }catch(e){hist.textContent='history failed';}
  }
  const hb=art.querySelector('.ce-hist'); if(hb)hb.addEventListener('click',()=>showHist('/history','/version',false));
  const shb=art.querySelector('.ce-shist'); if(shb)shb.addEventListener('click',()=>showHist('/suggestion-history','/suggestion-version',true));
  const insb=art.querySelector('.ce-ins');
  if(insb)insb.addEventListener('click',async(e)=>{
    if(!HTTP){say('needs pal serve');return;}
    e.target.disabled=true;say('inserting below...');
    try{
      const j=await (await fetch('/section/add',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({after:sec})})).json();
      if(j.ok){await fetch('/rebuild',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});say('inserted - reloading');setTimeout(()=>location.reload(),700);}
      else{say('failed: '+(j.error||'?'));e.target.disabled=false;}
    }catch(err){say('failed - is pal serve running?');e.target.disabled=false;}
  });
  const delb=art.querySelector('.ce-del');
  if(delb)delb.addEventListener('click',async(e)=>{
    if(!HTTP){say('needs pal serve');return;}
    if(!confirm('Delete (archive) section '+sec+'? It moves to _attic and can be recovered.'))return;
    e.target.disabled=true;say('deleting...');
    try{
      const j=await (await fetch('/section/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({section:sec})})).json();
      if(j.ok){await fetch('/rebuild',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});say('deleted - reloading');setTimeout(()=>location.reload(),700);}
      else{say('failed: '+(j.error||'?'));e.target.disabled=false;}
    }catch(err){say('failed - is pal serve running?');e.target.disabled=false;}
  });
  const celabels=art.querySelector('.celabels');
  function postLabels(L){return fetch('/labels',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({labels:L})}).then(r=>r.json());}
  function wirePill(ch){
    ch.title='click to remove this category';
    ch.addEventListener('click',async()=>{
      if(!HTTP)return;
      const txt=(ch.dataset.label||ch.textContent||'').trim();
      if(!txt||!confirm('Remove category "'+txt+'"?'))return;
      const L=window.CE_LABELS||{}; L[sec]=(L[sec]||[]).filter(x=>String(x.text||x)!==txt); window.CE_LABELS=L;
      try{ const j=await postLabels(L); if(j.ok){ch.remove();say('removed "'+txt+'"');} else say('failed: '+(j.error||'?')); }
      catch(e){say('failed - is pal serve running?');}
    });
  }
  function makePill(text){
    const p=document.createElement('span'); p.className='lchip'; p.dataset.label=text; p.textContent=text;
    p.style.cssText='background:#e8e0cd55;color:#6a6152;border-color:#6a615266;'; wirePill(p); return p;
  }
  if(celabels)celabels.querySelectorAll('.lchip').forEach(wirePill);
  const addcat=art.querySelector('.ce-addcat');
  if(addcat)addcat.addEventListener('click',async()=>{
    if(!HTTP){say('categories need pal serve');return;}
    const t=prompt('Category / label for this section:'); if(!t||!t.trim())return;
    const text=t.trim();
    const L=window.CE_LABELS||{}; L[sec]=(L[sec]||[]).slice(); L[sec].push({text:text}); window.CE_LABELS=L;
    try{ const j=await postLabels(L); if(j.ok){ if(celabels)celabels.appendChild(makePill(text)); say('added "'+text+'"'); } else say('failed: '+(j.error||'?')); }
    catch(e){say('failed - is pal serve running?');}
  });
});
(function(){
  const vb=document.getElementById('view-deleted'), panel=document.getElementById('attic-panel');
  if(!vb)return;
  vb.addEventListener('click',async()=>{
    if(!panel.hidden){panel.hidden=true;return;}
    panel.hidden=false; panel.textContent='loading deleted sections...';
    try{
      const j=await (await fetch('/attic')).json();
      if(!j.ok){panel.textContent='failed: '+(j.error||'?');return;}
      if(!j.sections.length){panel.textContent='nothing deleted';return;}
      panel.innerHTML='<div style="margin-bottom:4px;color:#8a7f68;">'+j.sections.length+' deleted section(s) - newest first. Restore puts one back in the order.</div>';
      j.sections.forEach(sc=>{
        const row=document.createElement('div');row.className='atrow';
        row.innerHTML='<span class="atid">'+esc(sc.id)+'</span><span class="atprev">'+esc(sc.preview||'')+'</span>';
        const rb=document.createElement('button');rb.className='atbtn';rb.textContent='restore';
        rb.addEventListener('click',async()=>{
          rb.disabled=true;rb.textContent='restoring...';
          try{
            const rj=await (await fetch('/attic-restore',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({section:sc.id})})).json();
            if(rj.ok){location.reload();} else {rb.textContent='failed: '+(rj.error||'?');rb.disabled=false;}
          }catch(e){rb.textContent='failed';rb.disabled=false;}
        });
        row.appendChild(rb);panel.appendChild(row);
      });
    }catch(e){panel.textContent='failed - is pal serve running?';}
  });
})();
updateTotal();
</script>"""

TEMPLATE = (page_head(f"{config.TITLE} · copyedit review") + STYLE + "</head><body>"
            "<div class=\"wrap\"><!--NAV-->"
            f"<header><div class=\"kicker\">Copyedit Review</div>"
            f"<h1>{html.escape(config.TITLE)} <span>&mdash; copyedit</span></h1>"
            "<p class=\"sub\">Left = original. Right = <b>edit here</b> (live spellcheck on) — "
            "green = a change in the suggestion · orange = a flag to review. "
            "<b>save</b> writes the section and commits; <b>history</b> undoes. "
            "Do all editing in this window (not the reading copy) so saves don't collide.</p></header>"
            "<div class=\"acceptbar\"><b>Accept all &rarr;</b> "
            "<button id=\"acc-safe\" title=\"apply every changed suggestion except weak/truncated\">accept safe fixes</button> "
            "<button id=\"acc-all\" title=\"apply every changed suggestion, including weak/truncated\">accept everything</button>"
            "<span id=\"acc-status\" class=\"accstatus\"></span>"
            "<button id=\"view-deleted\" title=\"see and restore deleted sections\">view deleted</button>"
            "<span class=\"accnote\">one git commit · undo: <code>git revert HEAD</code></span></div>"
            "<div id=\"attic-panel\" hidden></div>"
            "<div class=\"statsbar\">Manuscript total: <b id=\"total-wc\"></b> words</div>"
            "<div class=\"filterbar\"><!--FILTERS--></div>"
            "<!--BLOCKS--></div><!--LABELS-->" + SCRIPT + '<script src="pal.js"></script></body></html>')


if __name__ == "__main__":
    build()
