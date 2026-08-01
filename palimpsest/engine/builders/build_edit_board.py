#!/usr/bin/env python3
"""Revision tracker: the editing moves for this book as tickable columns.

Columns come from the book's own data/edit-board.json and are editable right in
the page when served (`pal serve`): add columns and items, remove them, and the
board saves + rebuilds. Ticking an item saves to the book too (a cheap /edit-board
post with rebuild:false); opened as a plain file, with no server to post to, ticks
fall back to localStorage namespaced per book."""
import html
import config
from nav import topbar_html, page_head, script_json

DOC = config._data("edit-board", {})
COLUMNS = [c for c in DOC.get("columns", []) if c.get("items") or c.get("title")]
BLURB = DOC.get("blurb", "Your editing moves, as a checklist. Add columns and items below; tick items off as you go.")
FOOTER = DOC.get("footer", "Columns and ticks both save to the book")
PALETTE = ["#16846b", "#b8860b", "#2874a6", "#c0392b", "#7d3c98", "#a04000", "#5b7a1f"]


def item_text(x):
    return str(x.get("text", "")) if isinstance(x, dict) else str(x)


def item_done(x):
    return bool(x.get("done")) if isinstance(x, dict) else False


def column_html(col, ci):
    key = str(col.get("key") or chr(ord("A") + ci))[:1].upper() or "A"
    # goes straight into a style attribute, so only a hex literal will do
    color = config.safe_color(col.get("color"), PALETTE[ci % len(PALETTE)])
    items = ""
    for i, it in enumerate(col.get("items", []), 1):
        text, done = item_text(it), item_done(it)
        items += (f'<label class="item{" done" if done else ""}"><input type="checkbox" '
                  f'data-col="{html.escape(key)}" data-ci="{ci}" data-ii="{i-1}" '
                  f'data-k="{html.escape(key.lower())}{i}"{" checked" if done else ""}>'
                  f'<span>{html.escape(text)}</span>'
                  f'<button class="eb-x eb-edit" data-ci="{ci}" data-ii="{i-1}" title="remove this item">✕</button>'
                  f'</label>')
    blurb = col.get("blurb", "")
    blurb_html = f'<p class="blurb">{html.escape(blurb)}</p>' if blurb else ""
    return (f'<div class="col" data-ci="{ci}" style="border-top-color:{color}">'
            f'<h3>{html.escape(str(col.get("title","")))} '
            f'<span class="prog" data-for="{html.escape(key)}"></span>'
            f'<button class="eb-x eb-colx eb-edit" data-ci="{ci}" title="remove this column">✕</button></h3>'
            f'{blurb_html}{items}'
            f'<div class="eb-additem eb-edit"><input type="text" placeholder="add an item…" data-ci="{ci}">'
            f'<button class="eb-addbtn" data-ci="{ci}">＋</button></div>'
            f'</div>')


board = "".join(column_html(c, i) for i, c in enumerate(COLUMNS))
SUB = f' <span>— {config.SUBTITLE_HTML}</span>' if config.SUBTITLE else ""
# the client's source of truth for edits: the current columns as clean JSON,
# each item {text, done} so tick state round-trips to disk
BOARD_JSON = script_json({"columns": [
    {"title": c.get("title", ""), "blurb": c.get("blurb", ""),
     "items": [{"text": item_text(x), "done": item_done(x)} for x in c.get("items", [])]}
    for c in COLUMNS]})

EMPTY_NOTE = ('<p class="note eb-noedit">No board yet — open this book with '
              '<code>pal serve</code> to build a checklist here, or add '
              '<code>data/edit-board.json</code> by hand.</p>')

HTML = f"""{page_head(f"{config.TITLE} — Edit Board")}
<style>
.board{{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:16px;align-items:start}}
.col{{background:var(--card);border:1px solid var(--line);border-top:4px solid var(--gold);border-radius:8px;padding:6px 16px 16px}}
.col h3{{font-size:16px;margin:.7em 0 .2em;display:flex;align-items:center;gap:6px}}
.col .blurb{{font-size:12.5px;color:var(--soft);margin:0 0 8px}}
.prog{{font-size:11px;color:var(--soft);font-variant:small-caps;margin-left:auto}}
.item{{display:flex;gap:8px;align-items:flex-start;font-size:13.5px;margin:9px 0;cursor:pointer;color:var(--ink2)}}
.item input[type=checkbox]{{margin-top:3px;flex:none}}
.item span{{flex:1;border-radius:4px;padding:0 4px;transition:background .1s,color .1s}}
/* a ticked-off item reads black-on-white; hovering it inverts to white-on-black */
.item.done span{{color:var(--paper);background:var(--ink);text-decoration:line-through}}
.item.done:hover span{{color:var(--ink);background:var(--paper)}}
.reset{{font:12px Georgia,serif;color:var(--soft);background:none;border:1px solid var(--line);border-radius:14px;padding:3px 11px;cursor:pointer}}
.eb-x{{font:11px Georgia,serif;border:1px solid transparent;background:none;color:var(--faint);cursor:pointer;border-radius:50%;width:18px;height:18px;line-height:1;padding:0;flex:none}}
.eb-x:hover{{color:var(--red);border-color:var(--red)}}
.eb-additem{{display:flex;gap:6px;margin-top:10px}}
.eb-additem input{{flex:1;font:12.5px Georgia,serif;border:1px solid var(--line);border-radius:12px;padding:3px 10px;background:var(--field)}}
.eb-addbtn{{font:13px Georgia,serif;border:1px solid var(--line);background:var(--field);color:var(--soft);border-radius:12px;padding:0 10px;cursor:pointer}}
.eb-addbtn:hover{{border-color:var(--gold);color:var(--gold)}}
.eb-addcol{{margin:14px 0 0;display:flex;gap:8px;align-items:center}}
.eb-addcol input{{font:14px Georgia,serif;border:1px solid var(--line);border-radius:16px;padding:5px 12px;min-width:220px;background:var(--field)}}
.eb-addcol button{{font:13px Georgia,serif;border:1px solid var(--gold);background:var(--gold);color:var(--on-accent);border-radius:16px;padding:5px 16px;cursor:pointer}}
.eb-edit{{display:none}}                         /* editing controls appear only when served */
body.eb-editable .eb-edit{{display:inline-flex}}
body.eb-editable .eb-additem{{display:flex}}
body.eb-editable .eb-noedit{{display:none}}
#eb-status{{font:italic 12.5px Georgia,serif;color:var(--soft);margin-left:8px}}
</style></head><body><div class="wrap">
{topbar_html("edit-board.html")}
<header><div class="kicker">Edit Board</div>
<h1>{config.TITLE_HTML}{SUB}</h1>
<p class="sub">{html.escape(BLURB)}</p></header>
<div style="margin:10px 0"><button class="reset" id="reset">reset all ticks</button><span id="eb-status"></span></div>

{f'<div class="board">{board}</div>' if board else ''}
{EMPTY_NOTE if not board else ''}
<div class="eb-addcol eb-edit"><input id="eb-newcol" type="text" placeholder="new column title…" autocomplete="off">
<button id="eb-addcol">＋ add column</button></div>
<footer>{html.escape(FOOTER)}</footer>
</div>
<script>
const KEY='{config.SAFE_SLUG}-edit-board';
const HTTP=location.protocol.startsWith('http');
const BOARD={BOARD_JSON};
const state=JSON.parse(localStorage.getItem(KEY)||'{{}}');
const boxes=[...document.querySelectorAll('input[type=checkbox]')];
function counts(){{
  const by={{}};
  boxes.forEach(b=>{{const col=b.dataset.col;by[col]=by[col]||[0,0];by[col][1]++;if(b.checked)by[col][0]++;
    b.closest('.item').classList.toggle('done',b.checked);}});
  document.querySelectorAll('.prog').forEach(p=>{{const c=by[p.dataset.for]||[0,0];p.textContent=c[0]+'/'+c[1];}});
}}
// tick state: saved to the book on disk when served; localStorage when offline
function saveTicks(){{
  fetch('/edit-board',{{method:'POST',headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{columns:BOARD.columns,rebuild:false}})}}).catch(()=>{{}});
}}
boxes.forEach(b=>{{
  if(!HTTP) b.checked=!!state[b.dataset.k];         // offline: restore from this browser
  b.addEventListener('change',()=>{{
    if(HTTP){{
      const ci=+b.dataset.ci, ii=+b.dataset.ii;
      if(BOARD.columns[ci] && BOARD.columns[ci].items[ii]) BOARD.columns[ci].items[ii].done=b.checked;
      saveTicks();
    }} else {{ state[b.dataset.k]=b.checked; localStorage.setItem(KEY,JSON.stringify(state)); }}
    counts();
  }});
}});
document.getElementById('reset').addEventListener('click',()=>{{
  boxes.forEach(b=>b.checked=false);
  if(HTTP){{ BOARD.columns.forEach(c=>(c.items||[]).forEach(it=>it.done=false)); saveTicks(); }}
  else {{ localStorage.removeItem(KEY); }}
  counts();}});
counts();

// ---- edit the board in the browser (needs the server) ----
const st=document.getElementById('eb-status');
async function save(saying){{
  if(st) st.textContent=saying||'saving…';
  try{{
    const r=await fetch('/edit-board',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(BOARD)}});
    const j=await r.json(); if(!j.ok) throw new Error(j.error||'failed');
    location.reload();
  }}catch(e){{ if(st) st.textContent='failed: '+e.message; }}
}}
if(HTTP){{
  document.body.classList.add('eb-editable');
  document.getElementById('eb-addcol').addEventListener('click',()=>{{
    const el=document.getElementById('eb-newcol'); const t=(el.value||'').trim(); if(!t){{ el.focus(); return; }}
    BOARD.columns.push({{title:t,blurb:'',items:[]}}); save('adding column…');
  }});
  document.getElementById('eb-newcol').addEventListener('keydown',e=>{{ if(e.key==='Enter') document.getElementById('eb-addcol').click(); }});
  document.querySelectorAll('.eb-addbtn').forEach(b=>b.addEventListener('click',()=>{{
    const ci=+b.dataset.ci; const inp=document.querySelector('.eb-additem input[data-ci="'+ci+'"]');
    const t=(inp.value||'').trim(); if(!t){{ inp.focus(); return; }}
    (BOARD.columns[ci].items=BOARD.columns[ci].items||[]).push(t); save('adding item…');
  }}));
  document.querySelectorAll('.eb-additem input').forEach(inp=>inp.addEventListener('keydown',e=>{{
    if(e.key==='Enter') document.querySelector('.eb-addbtn[data-ci="'+inp.dataset.ci+'"]').click(); }}));
  document.querySelectorAll('.eb-colx').forEach(x=>x.addEventListener('click',()=>{{
    BOARD.columns.splice(+x.dataset.ci,1); save('removing column…'); }}));
  document.querySelectorAll('.item .eb-x').forEach(x=>x.addEventListener('click',ev=>{{
    ev.preventDefault(); BOARD.columns[+x.dataset.ci].items.splice(+x.dataset.ii,1); save('removing item…'); }}));
}}
</script>
<script src="pal.js"></script>
</body></html>"""

with open("edit-board.html", "w", encoding="utf-8") as fh:
    fh.write(HTML)
print(f"wrote edit-board.html · {len(COLUMNS)} column(s)")
