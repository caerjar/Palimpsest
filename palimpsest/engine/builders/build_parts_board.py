#!/usr/bin/env python3
"""Parts board: sections laid out as draggable cards in columns, one column per
part (plus a leading Front-matter column). Drag a card between columns to move a
section into that part; on drop the whole board is flattened back to a 1-D id list
and POSTed to /order (the same manifest the reading copy writes). Part membership is
purely positional — a section's part is whichever divider precedes it — so a valid
order.json falls straight out of the column layout.

Divider sections (the {{contents}} 'Part N' titles from part-dividers.json) are pinned
at the top of their column and not draggable, so parts stay contiguous."""
import html, os, re
import config
from sections import read_section, section_paths, load_dividers, part_of
from nav import topbar_html, page_head, script_json


def preview(path):
    body = read_section(path)[1]
    body = re.sub(r'\{\{/?contents\}\}', '', body)     # don't show the fence markers
    line = " ".join(body.split())
    return (line[:140] + "…") if len(line) > 140 else (line or "(empty)")


def wordcount(path):
    raw = open(path, encoding="utf-8").read()
    body = re.sub(r'^\s*#\s*\d+\s*\n', '', raw)        # drop the # N heading line
    return len(body.split())


files = section_paths()
order_ids = [os.path.basename(p)[:-3] for p in files]
dividers = load_dividers()
divider_title = {d["id"]: d["title"] for d in dividers}

# group sections into columns, in flow order: "" (front matter) then each divider id
columns = [("", "Front matter")] + [(d["id"], d["title"]) for d in dividers]
buckets = {key: [] for key, _ in columns}
for pos, (path, sid) in enumerate(zip(files, order_ids, strict=True), 1):
    buckets.setdefault(part_of(sid, order_ids, dividers), []).append((pos, sid, path))

cols_html = []
for key, title in columns:
    rows = buckets.get(key, [])
    col_words = 0
    cards = []
    for pos, sid, path in rows:
        wc = wordcount(path)
        col_words += wc
        if sid == key and key:                          # the divider itself — pinned header card
            cards.append(f'<div class="pcard divcard" data-sec="{sid}" data-words="{wc}">'
                         f'◆ {html.escape(divider_title.get(sid, title))}</div>')
        else:
            cards.append(f'<div class="pcard" data-sec="{sid}" data-words="{wc}" draggable="true">'
                         f'<span class="cpos">§{pos}</span><span class="cfid">{sid}</span>'
                         f'<span class="cprev">{html.escape(preview(path))}</span></div>')
    head = html.escape(title.split(":")[0] if key else title)
    sub = html.escape(title.split(":", 1)[1].strip()) if (key and ":" in title) else ""
    cols_html.append(
        f'<div class="col" data-part="{key}">'
        f'<div class="colhd"><span class="ctitle">{head}</span>'
        f'{f"<span class=csub>{sub}</span>" if sub else ""}'
        f'<span class="ct">{len(rows)}</span><span class="cw">{col_words:,}w</span></div>'
        f'<div class="colbody">{"".join(cards)}</div></div>')

# short column labels for the "move selected to …" toolbar
cols_meta = [{"key": key, "label": (title.split(":")[0].strip() if key else "Front matter")}
             for key, title in columns]
cols_js = script_json(cols_meta)

BOARD_JS = r'''
const HTTP=location.protocol.startsWith('http');
const bar=document.getElementById('bstatus');
function status(t){ if(bar) bar.textContent=t; }
status(HTTP ? 'click cards to select a block, then “move to” · or drag one card · double-click opens it in the reading copy'
            : 'read-only (offline) — run “pal serve” to drag & save · double-click opens a card in the reading copy');

// live per-column tallies (section count + word total), recomputed after any move
function fmtN(n){ return n.toLocaleString(); }
function recount(){
  document.querySelectorAll('.board .col').forEach(col=>{
    const cards=[...col.querySelectorAll('.pcard')];
    let w=0; cards.forEach(c=>w+=parseInt(c.dataset.words||'0'));
    const ct=col.querySelector('.ct'); if(ct) ct.textContent=cards.length;
    const cw=col.querySelector('.cw'); if(cw) cw.textContent=fmtN(w)+'w';
  });
}

// double-click any card → open that section in the reading copy
document.querySelectorAll('.pcard').forEach(c=>{
  c.addEventListener('dblclick',()=>{ location.href='reading-copy.html#s'+c.dataset.sec; });
});

// ---- selection (single-click a card to toggle; build a block to move at once) ----
const selected=new Set();
function selCards(){ return [...document.querySelectorAll('.pcard.selected')]; }
function clearSel(){ selCards().forEach(c=>c.classList.remove('selected')); selected.clear(); syncToolbar(); }
function toggleSel(card){
  const sid=card.dataset.sec;
  if(selected.has(sid)){ selected.delete(sid); card.classList.remove('selected'); }
  else { selected.add(sid); card.classList.add('selected'); }
  syncToolbar();
}
const toolbar=document.createElement('div'); toolbar.id='seltoolbar'; toolbar.hidden=true;
document.body.appendChild(toolbar);
function syncToolbar(){
  if(!selected.size){ toolbar.hidden=true; return; }
  toolbar.hidden=false;
  let words=0; selCards().forEach(c=>words+=parseInt(c.dataset.words||'0'));
  toolbar.innerHTML='<span class="selct">'+selected.size+' selected · '+fmtN(words)+'w</span><span class="sellbl">move to:</span>';
  COLS.forEach(c=>{ const b=document.createElement('button'); b.textContent=c.label;
    b.addEventListener('click',()=>moveSelectedTo(c.key)); toolbar.appendChild(b); });
  const clr=document.createElement('button'); clr.textContent='clear'; clr.className='clr';
  clr.addEventListener('click',clearSel); toolbar.appendChild(clr);
}
function pinDivider(body){ const d=body.querySelector('.divcard'); if(d && body.firstElementChild!==d) body.insertBefore(d, body.firstElementChild); }
function moveSelectedTo(key){
  const body=document.querySelector('.board .col[data-part="'+key+'"] .colbody'); if(!body) return;
  selCards().forEach(c=>body.appendChild(c));   // to the end of the target part (DOM order preserved)
  pinDivider(body); clearSel(); persist();
}
document.querySelectorAll('.pcard[draggable="true"]').forEach(c=>{
  c.addEventListener('click',()=>toggleSel(c));
});

// ---- drag (a single card, or the whole selection if the dragged card is selected) ----
let drag=null;
document.querySelectorAll('.pcard[draggable="true"]').forEach(c=>{
  c.addEventListener('dragstart',e=>{ drag=c; c.classList.add('dragging'); e.dataTransfer.effectAllowed='move';
    try{e.dataTransfer.setData('text/plain',c.dataset.sec);}catch(_){}} );
  c.addEventListener('dragend',()=>{ if(drag) drag.classList.remove('dragging'); drag=null;
    document.querySelectorAll('.colbody.over').forEach(b=>b.classList.remove('over')); });
});
function cardAfter(body, y){
  const cards=[...body.querySelectorAll('.pcard:not(.dragging):not(.divcard):not(.selected)')];
  for(const c of cards){ const r=c.getBoundingClientRect(); if(y < r.top + r.height/2) return c; }
  return null;
}
document.querySelectorAll('.colbody').forEach(body=>{
  body.addEventListener('dragover',e=>{ if(!drag) return; e.preventDefault(); body.classList.add('over'); });
  body.addEventListener('dragleave',()=>body.classList.remove('over'));
  body.addEventListener('drop',e=>{
    if(!drag) return; e.preventDefault(); body.classList.remove('over');
    const moving = drag.classList.contains('selected') ? selCards() : [drag];
    const ref=cardAfter(body, e.clientY);
    moving.forEach(c=>{ if(ref) body.insertBefore(c, ref); else body.appendChild(c); });
    pinDivider(body); clearSel(); persist();
  });
});

// renumber the §positions on cards after a move (flow order = board order, dividers included)
function renumberBoard(){
  let pos=0;
  document.querySelectorAll('.board .col').forEach(col=>
    col.querySelectorAll('.pcard').forEach(c=>{ pos++; const cp=c.querySelector('.cpos'); if(cp) cp.textContent='§'+pos; }));
}
function persist(){
  recount(); renumberBoard();                 // update the board IN PLACE — never reload to stale HTML
  if(!HTTP){ status('offline — not saved · open the board via “pal serve” (http://127.0.0.1:8137/parts-board.html)'); return; }
  const ids=[];
  document.querySelectorAll('.board .col').forEach(col=>
    col.querySelectorAll('.pcard').forEach(c=>ids.push(c.dataset.sec)));
  status('saving…');
  fetch('/order',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({order:ids})})
    .then(r=>r.json()).then(j=>{ status(j.ok ? ('✓ saved · '+ids.length+' sections'+(j.commit?(' · '+j.commit):''))
                                             : ('save failed: '+(j.error||'?'))); })
    .catch(()=>status('save failed — is “pal serve” running? open the board at http://127.0.0.1:8137/parts-board.html'));
}
'''

HTML = f"""{page_head(f"{config.TITLE} — Parts Board")}
<style>
/* topbar/brand styles are shared in style.css */
#bstatus{{font:13px Georgia,serif;color:var(--soft);margin:0 0 12px}}
.board{{display:flex;gap:12px;align-items:flex-start;overflow-x:auto;padding-bottom:20px}}
.col{{flex:1 0 260px;min-width:240px;max-width:340px;background:var(--bg2);border:1px solid var(--line);
  border-radius:8px;padding:8px}}
.col[data-part=""]{{background:var(--bg2)}}
.colhd{{display:flex;align-items:baseline;gap:6px;margin:2px 4px 8px;flex-wrap:wrap}}
.colhd .ctitle{{font:600 15px Georgia,serif;color:var(--ink)}}
.colhd .csub{{font:italic 12px Georgia,serif;color:var(--soft)}}
.colhd .ct{{margin-left:auto;font-size:12px;color:var(--on-accent);background:var(--soft);border-radius:9px;padding:0 7px}}
.colhd .cw{{font-size:12px;color:var(--soft);font-variant-numeric:tabular-nums}}
.colbody{{min-height:60px;display:flex;flex-direction:column;gap:6px}}
.colbody.over{{outline:2px dashed var(--gold);outline-offset:2px;border-radius:6px}}
.pcard{{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--soft);border-radius:5px;
  padding:5px 8px;cursor:grab;font:13px/1.35 Georgia,serif;color:var(--ink3)}}
.pcard.dragging{{opacity:.4}}
.pcard .cpos{{font-weight:bold;color:var(--ink);margin-right:6px}}
.pcard .cfid{{font-size:11px;color:var(--soft);margin-right:6px}}
.pcard .cprev{{color:var(--soft)}}
.pcard.divcard{{cursor:default;background:var(--hilite);border-left-color:var(--gold);color:var(--gold);
  font-weight:600}}
.pcard.selected{{outline:2px solid var(--gold);outline-offset:1px;background:var(--hilite)}}
#seltoolbar{{position:fixed;bottom:18px;left:50%;transform:translateX(-50%);z-index:50;
  background:var(--invert-bg);color:var(--invert-ink);border-radius:24px;padding:8px 16px;display:flex;gap:6px;align-items:center;
  box-shadow:0 6px 22px rgba(40,30,10,.35);font:13px Georgia,serif;flex-wrap:wrap;max-width:92vw}}
#seltoolbar .selct{{font-weight:bold}}
#seltoolbar .sellbl{{opacity:.7;margin:0 2px 0 6px}}
#seltoolbar button{{font:13px Georgia,serif;border:1px solid #ffffff55;background:#ffffff22;color:var(--invert-ink);
  border-radius:14px;padding:2px 11px;cursor:pointer}}
#seltoolbar button:hover{{background:#ffffff3a;border-color:var(--on-accent)}}
#seltoolbar .clr{{margin-left:4px;background:transparent;border-color:#ffffff33}}
</style></head><body><div class="wrap">
{topbar_html("parts-board.html")}
<header><div class="kicker">Parts Board</div>
<h1>Move sections between parts</h1></header>
<p id="bstatus"></p>
<div class="board">{''.join(cols_html)}</div>
</div>
<script>const COLS={cols_js};{BOARD_JS}</script>
<script src="pal.js"></script>
</body></html>"""

with open("parts-board.html", "w", encoding="utf-8") as fh:
    fh.write(HTML)
total = sum(len(v) for v in buckets.values())
print(f"wrote parts-board.html · {len(columns)} columns · {total} sections")
