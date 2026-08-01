#!/usr/bin/env python3
"""Aggregate the back-of-book index and render index-terms.html.

Built entirely from the author's watchlist, `manifests/entities-seed.json`:
  - `add[]` — each term is always included; its sections are found
    DETERMINISTICALLY by searching the manuscript for its name + aliases
    (word-boundary), so it lists every § it actually appears in.
  - `_override.ops` — drop / rename / retype, applied last.

Fully deterministic — no model involved, runs in milliseconds, so it's cheap to
re-run whenever the watchlist changes. `pal build index`."""
import html, json, os, re
from sections import section_paths
from nav import topbar_html, page_head

import config
DOSSIER = config.OUT                                       # generated HTML output dir
SEED_JSON = os.path.join(config.MANIFESTS, "entities-seed.json")  # authored watchlist

TYPE_ORDER = ["concept", "people", "works", "places", "stories", "things", "events"]
TYPE_LABEL = {"concept": "Concepts / Key Ideas", "people": "People", "works": "Works",
              "places": "Places", "stories": "Stories & Myths", "things": "Things",
              "events": "Events"}


def body_of(path):
    raw = open(path, encoding="utf-8").read()
    m = re.match(r"\s*#\s*\d+\s*\n(.*)", raw, re.S)
    return (m.group(1) if m else raw).strip()


def key(name):
    return re.sub(r"\s+", " ", str(name).strip().lower())


files = section_paths()
sid_pos = {os.path.basename(p)[:-3]: i for i, p in enumerate(files, 1)}
bodies = {os.path.basename(p)[:-3]: body_of(p) for p in files}

# seed watchlist + an alias->canonical map so variant spellings fold together
# (e.g. an initial -> the full name, a nickname -> the canonical form)
def _load_seed():
    if not os.path.isfile(SEED_JSON):
        return {}
    with open(SEED_JSON, encoding="utf-8") as fh:
        return json.load(fh)


seed = _load_seed()
alias_map = {}
for _s in seed.get("add", []):
    _c = _s.get("name")
    if not _c:
        continue
    for _nm in [_c] + list(_s.get("aliases", []) or []):
        alias_map[key(_nm)] = _c


def resolve(name):
    return alias_map.get(key(name), str(name).strip())


reg = {}   # key -> entry


def ensure(canon, typ):
    k = key(canon)
    if k not in reg:
        reg[k] = {"name": str(canon).strip(), "type": typ if typ in TYPE_ORDER else "concept",
                  "also": set(), "tag": None, "aliases": set(), "note": "", "secs": set(), "seed": False}
    return reg[k]


# The index is built entirely from the author's seed watchlist below: each
# entry's sections are found by searching the manuscript for its name + aliases
# (word-boundary). Fully deterministic — no model, runs in milliseconds, so it's
# cheap to re-run whenever the watchlist changes.

# seed watchlist: always include + deterministic section search
for s in seed.get("add", []):
    canon = s.get("name")
    if not canon:
        continue
    e = ensure(canon, s.get("type", "concept"))
    e["seed"] = True
    e["type"] = s.get("type", e["type"])         # seed type wins
    for a in s.get("also", []) or []:
        e["also"].add(a)
    if s.get("tag"):
        e["tag"] = s["tag"]
    if s.get("note"):
        e["note"] = e["note"] or str(s["note"])[:60]
    terms = [canon] + list(s.get("aliases", []) or [])
    e["aliases"].update(s.get("aliases", []) or [])
    rx = re.compile(r"\b(" + "|".join(re.escape(t) for t in sorted(set(terms), key=len, reverse=True)) + r")\b", re.I)
    for sid, body in bodies.items():
        if rx.search(body):
            e["secs"].add(sid)

# 3. author overrides
for op in (seed.get("_override", {}) or {}).get("ops", []):
    o = op.get("op")
    k = key(op.get("name", ""))
    if o == "drop" and k in reg:
        del reg[k]
    elif o == "retype" and k in reg and op.get("type") in TYPE_ORDER:
        reg[k]["type"] = op["type"]
    elif o == "rename" and k in reg and op.get("to"):
        reg[k]["name"] = op["to"]

# ---- write registry ----
# Keep every term you put on the watchlist, even one that doesn't appear in the
# text yet — it shows with a 0 count as a reminder, rather than silently vanishing.
# (Only a non-seed term with no matches would be dropped; today all terms are seed.)
registry = {}
for e in reg.values():
    if not e["secs"] and not e.get("seed"):
        continue
    registry.setdefault(e["type"], []).append({
        "name": e["name"], "tag": e["tag"], "also": sorted(e["also"]),
        "aliases": sorted(a for a in e["aliases"] if key(a) != key(e["name"])),
        "note": e["note"], "count": len(e["secs"]), "seed": e["seed"],
        "sections": sorted(({"sid": s, "pos": sid_pos.get(s, 0)} for s in e["secs"]), key=lambda x: x["pos"]),
    })
with open(os.path.join(DOSSIER, "entities.json"), "w", encoding="utf-8") as fh:
    json.dump(registry, fh, ensure_ascii=False, indent=0)

# ---- render index-terms.html (back-of-book) ----
def seclinks(entry):
    return " ".join(f'<a href="reading-copy.html#s{s["sid"]}">§{s["pos"]}</a>' for s in entry["sections"])


blocks = []
total_terms = 0
for typ in TYPE_ORDER:
    # a type's list: its primaries + entries whose `also` includes it (cross-listed)
    items = list(registry.get(typ, []))
    for other in TYPE_ORDER:
        if other == typ:
            continue
        for e in registry.get(other, []):
            if typ in e.get("also", []):
                items.append({**e, "_xref": True})
    if not items:
        continue
    items.sort(key=lambda e: e["name"].lower().lstrip("the "))
    rows = []
    for e in items:
        total_terms += 0 if e.get("_xref") else 1
        al = f' <span class="al">({", ".join(e["aliases"][:4])})</span>' if e["aliases"] else ""
        tag = f' <span class="tg">{html.escape(e["tag"])}</span>' if e.get("tag") else ""
        xref = ' <span class="xr">↗</span>' if e.get("_xref") else ""
        note = f' <span class="nt">{html.escape(e["note"])}</span>' if e["note"] else ""
        seed = ' <span class="sd" title="author watchlist">★</span>' if e.get("seed") else ""
        # a remove (✕) on the primary listing of each term (not cross-listings);
        # wired by the page script when served, hidden otherwise.
        rm = ("" if e.get("_xref") else
              f'<button class="term-x" title="remove “{html.escape(e["name"], quote=True)}” from the index">✕</button>')
        rows.append(f'<div class="term" data-name="{html.escape(e["name"].lower(), quote=True)}" '
                    f'data-canon="{html.escape(e["name"], quote=True)}">'
                    f'<span class="tn">{html.escape(e["name"])}{seed}{tag}{xref}</span>{al}{note}'
                    f'<span class="ct">{e["count"]}</span>{rm}'
                    f'<div class="secs">{seclinks(e)}</div></div>')
    blocks.append(f'<section class="typegrp" data-type="{typ}"><h2>{TYPE_LABEL[typ]} '
                  f'<span class="gn">{len([i for i in items if not i.get("_xref")])}</span></h2>{"".join(rows)}</section>')

mode = f"{len(reg)} watchlist term(s) · sections found by text search"
HTML = f"""{page_head(f"{config.TITLE} — Index")}
<style>
/* topbar/brand styles are shared in style.css */
.idxctl{{position:sticky;top:46px;z-index:20;background:var(--bar);border-bottom:1px solid var(--line);
  margin:0 -60px 14px;padding:8px 60px;display:flex;gap:10px;flex-wrap:wrap;align-items:center}}
.idxctl input{{font:14px Georgia,serif;border:1px solid var(--line);border-radius:16px;padding:5px 12px;min-width:220px}}
.idxctl .fb{{font:12.5px Georgia,serif;border:1px solid var(--line);background:var(--field);border-radius:14px;padding:3px 10px;cursor:pointer;color:var(--soft)}}
.idxctl .fb.on{{border-color:var(--gold);color:var(--gold);background:var(--hilite)}}
.idxmode{{font:italic 12px Georgia,serif;color:var(--soft);margin-left:auto}}
.typegrp h2{{font:600 20px Georgia,serif;color:var(--ink);border-bottom:2px solid var(--gold);padding-bottom:3px;margin:22px 0 8px}}
.typegrp h2 .gn{{font-size:13px;color:var(--soft);font-weight:normal}}
.term{{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px;padding:3px 0;border-bottom:1px dotted var(--line)}}
.term .tn{{font:600 15px Georgia,serif;color:var(--ink)}}
.term .sd{{color:var(--gold)}} .term .tg{{font:11px system-ui;color:var(--on-accent);background:var(--soft);border-radius:8px;padding:0 6px}}
.term .xr{{color:var(--soft);font-size:12px}} .term .al{{font:italic 13px Georgia,serif;color:var(--soft)}}
.term .nt{{font:13px Georgia,serif;color:var(--faint)}}
.term .ct{{margin-left:auto;font:12px Georgia,serif;color:var(--on-accent);background:var(--gold);border-radius:9px;padding:0 7px}}
.term .term-x{{font:12px Georgia,serif;border:1px solid var(--line);background:var(--field);color:var(--soft);
  border-radius:50%;width:20px;height:20px;line-height:1;cursor:pointer;padding:0;margin-left:2px}}
.term .term-x:hover{{border-color:var(--red);color:var(--red)}}
.idxadd{{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:0 0 14px;padding:10px 14px;
  background:var(--sunk);border:1px solid var(--line);border-radius:8px}}
.idxadd input,.idxadd select{{font:14px Georgia,serif;border:1px solid var(--line);border-radius:16px;padding:5px 12px;background:var(--field)}}
.idxadd #addname{{min-width:220px}} .idxadd #addalias{{min-width:200px;flex:1}}
.idxadd #addbtn{{font:13px Georgia,serif;border:1px solid var(--gold);background:var(--gold);color:var(--on-accent);border-radius:16px;padding:5px 16px;cursor:pointer}}
.idxadd #addbtn:hover{{background:var(--accent-hi)}}
.idxadd #addstatus{{font:italic 12.5px Georgia,serif;color:var(--soft)}}
.term .secs{{flex-basis:100%;font:13px/1.7 Georgia,serif;margin:2px 0 3px 6px}}
.term .secs a{{color:var(--soft);text-decoration:none;margin-right:2px;border-bottom:1px solid transparent}}
.term .secs a:hover{{color:var(--gold);border-bottom-color:var(--gold)}}
.idxhelp{{margin:0 0 14px;border:1px solid var(--line);border-radius:8px;background:var(--sunk)}}
.idxhelp>summary{{cursor:pointer;padding:8px 13px;font:600 13px Georgia,serif;color:var(--ink);list-style:none}}
.idxhelp>summary::before{{content:"▸ ";color:var(--gold)}}
.idxhelp[open]>summary::before{{content:"▾ "}}
.idxhelp .hb{{padding:2px 15px 12px;font:13.5px/1.55 Georgia,serif;color:var(--soft)}}
.idxhelp .hb p{{margin:.5em 0}}
.idxhelp code{{background:var(--code-bg);padding:0 4px;border-radius:3px;font-size:.9em}}
</style></head><body><div class="wrap">
{topbar_html("index-terms.html")}
<header><div class="kicker">Index</div><h1>Back-of-book index <span>— terms &amp; where they appear</span></h1></header>
<div class="idxctl"><input id="q" type="search" placeholder="filter terms…" autocomplete="off">
<span class="fb on" data-t="all">all</span>{''.join(f'<span class="fb" data-t="{t}">{TYPE_LABEL[t].split(" ")[0]}</span>' for t in TYPE_ORDER)}
<span class="idxmode">{mode} · ★ = your watchlist</span></div>
<div class="idxadd" hidden>
  <input id="addname" type="text" placeholder="add a term to the index…" autocomplete="off">
  <select id="addtype">{''.join(f'<option value="{t}">{TYPE_LABEL[t].split(" / ")[0].split(" ")[0]}</option>' for t in TYPE_ORDER)}</select>
  <input id="addalias" type="text" placeholder="aliases (optional, comma-separated)" autocomplete="off">
  <button id="addbtn">＋ add</button>
  <span id="addstatus"></span>
</div>
<details class="idxhelp"><summary>How this index works</summary>
<div class="hb">
<p>This index is your <b>watchlist</b>: every term you name is listed with the sections (§) where it
appears, found by searching the text. Buckets: Concepts/Key Ideas · People · Works · Places ·
Stories · Things · Events — a term can belong to more than one (↗ = cross-listed). <b>★</b> = watchlist.</p>
<p><b>Add</b> a term with the box above; <b>remove</b> one with the ✕ beside it. Changes save and
rebuild the index right here. (You can also edit <code>manifests/entities-seed.json</code> directly if
you prefer.)</p>
</div></details>
{''.join(blocks)}
<footer>{total_terms} index terms · {len(files)} sections · ↗ cross-listed under a secondary type · click a § to jump to the section</footer>
</div>
<script>
const terms=[...document.querySelectorAll('.term')], grps=[...document.querySelectorAll('.typegrp')];
const q=document.getElementById('q');
function apply(){{
  const s=q.value.trim().toLowerCase();
  const t=(document.querySelector('.fb.on')||{{}}).dataset?.t||'all';
  terms.forEach(el=>{{ const okS=!s||el.dataset.name.includes(s); el.style.display=okS?'':'none'; }});
  grps.forEach(g=>{{ const okT=t==='all'||g.dataset.type===t; g.style.display=okT?'':'none';
    if(okT){{ const any=[...g.querySelectorAll('.term')].some(el=>el.style.display!=='none'); g.style.display=any?'':'none'; }} }});
}}
q.addEventListener('input',apply);
document.querySelectorAll('.fb').forEach(b=>b.addEventListener('click',()=>{{
  document.querySelectorAll('.fb').forEach(x=>x.classList.remove('on')); b.classList.add('on'); apply();
}}));

// ---- edit the watchlist in the browser (needs the server) ----
const HTTP = location.protocol.startsWith('http');
if(HTTP){{
  const add=document.querySelector('.idxadd'); if(add) add.hidden=false;
  const name=document.getElementById('addname'), type=document.getElementById('addtype'),
        alias=document.getElementById('addalias'), btn=document.getElementById('addbtn'),
        st=document.getElementById('addstatus');
  async function watch(body, saying){{
    if(st) st.textContent=saying;
    try{{
      const r=await fetch('/watchlist',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(body)}});
      const j=await r.json();
      if(!j.ok) throw new Error(j.error||'failed');
      location.reload();
    }}catch(e){{ if(st) st.textContent='failed: '+e.message; }}
  }}
  function submitAdd(){{
    const n=(name.value||'').trim(); if(!n){{ name.focus(); return; }}
    watch({{op:'add',name:n,type:type.value,aliases:alias.value}}, 'adding “'+n+'”…');
  }}
  if(btn) btn.addEventListener('click',submitAdd);
  if(name) name.addEventListener('keydown',e=>{{ if(e.key==='Enter') submitAdd(); }});
  document.querySelectorAll('.term-x').forEach(x=>x.addEventListener('click',()=>{{
    const term=x.closest('.term'); const canon=term&&term.dataset.canon; if(!canon) return;
    watch({{op:'drop',name:canon}}, 'removing “'+canon+'”…');
  }}));
}} else {{
  document.querySelectorAll('.term-x').forEach(x=>x.remove());   // read-only when opened as a file
}}
</script>
<script src="pal.js"></script>
</body></html>"""

with open(os.path.join(DOSSIER, "index-terms.html"), "w", encoding="utf-8") as fh:
    fh.write(HTML)
print(f"wrote index-terms.html · {total_terms} terms · {mode}")
