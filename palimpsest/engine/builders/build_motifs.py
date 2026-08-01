#!/usr/bin/env python3
"""Motifs: the threads you name, and the sections each one appears in.

A motif is a name, a colour, and a list of sections. The reading copy draws them as
chips and as the coloured spine down the left of each section; sections.json carries
their names for the writing record. Nothing here infers a motif — you name it, and the
word search only finds where a word you chose already appears.

Editing needs the server (`pal serve`), so the form hides when the page is opened as a
plain file. Saving posts to /motifs, which writes data/motifs.json and rebuilds."""
import html
import config
from nav import topbar_html, page_head, script_json

MOTIFS = config.motifs()
OUT = "motifs.html"

# the client edits this array and posts it back whole
MOTIFS_JSON = script_json(MOTIFS)

rows = "".join(
    f'<div class="motrow" data-i="{i}">'
    f'<span class="sw" style="background:{m["color"]}"></span>'
    f'<span class="mn">{html.escape(m["name"])}</span>'
    f'<span class="mct">{len(m["sections"])} §</span>'
    f'<span class="msecs">{html.escape(", ".join(str(s) for s in m["sections"][:24]))}'
    f'{"…" if len(m["sections"]) > 24 else ""}</span>'
    f'<button class="mx eb-edit" data-i="{i}" title="remove this motif">✕</button>'
    f'</div>'
    for i, m in enumerate(MOTIFS))

EMPTY = ('<p class="note">No motifs yet. Type a word below and press <b>find</b> — '
         'every section containing it is added to this motif.</p>')

STYLE = """<style>
.motrow{display:flex;align-items:center;gap:10px;padding:7px 2px;border-bottom:1px solid var(--line)}
.motrow .sw{width:15px;height:15px;border-radius:4px;flex:none;border:1px solid #0002}
.motrow .mn{font-size:15px;min-width:150px}
.motrow .mct{font-size:12px;color:var(--soft);min-width:44px}
.motrow .msecs{font:12px ui-monospace,Menlo,monospace;color:var(--faint);flex:1;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.motrow .mx{font:11px Georgia,serif;border:1px solid transparent;background:none;color:var(--faint);
  cursor:pointer;border-radius:50%;width:20px;height:20px;line-height:1;padding:0;flex:none}
.motrow .mx:hover{color:var(--red);border-color:var(--red)}
.motadd{margin-top:16px;padding:14px;background:var(--sunk);border:1px solid var(--line);
  border-radius:8px;display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.motadd input[type=text]{font:14px Georgia,serif;border:1px solid var(--line);border-radius:16px;
  padding:6px 12px;background:var(--field);color:var(--ink)}
.motadd input[type=color]{width:34px;height:34px;border:1px solid var(--line);border-radius:8px;
  background:var(--field);cursor:pointer;padding:2px}
.motadd button{font:13px Georgia,serif;border:1px solid var(--gold);background:var(--gold);
  color:var(--on-accent);border-radius:16px;padding:6px 16px;cursor:pointer}
#mot-findbtn{background:var(--field);color:var(--gold)}
#mot-status{font:italic 12.5px Georgia,serif;color:var(--soft)}
.eb-edit{display:none}
body.mot-editable .eb-edit{display:inline-flex}
body.mot-editable .motadd{display:flex}
.motadd{display:none}
</style>"""

SCRIPT = """<script>
(function(){
  var HTTP = location.protocol.indexOf('http')===0;
  if(!HTTP) return;                         // read-only when opened as a plain file
  document.body.classList.add('mot-editable');
  var MOTIFS = __MOTIFS__;
  var $ = function(id){ return document.getElementById(id); };
  function say(t){ $('mot-status').textContent = t||''; }

  // "1, 15, 31-40" -> [1,15,31,…,40]
  function parseSecs(s){
    var out = {};
    (s||'').split(',').forEach(function(part){
      part = part.trim(); if(!part) return;
      var m = part.match(/^(\\d+)\\s*-\\s*(\\d+)$/);
      if(m){ var a=+m[1], b=+m[2]; if(a>b){ var t=a; a=b; b=t; } for(var i=a;i<=b;i++) out[i]=1; }
      else if(/^\\d+$/.test(part)) out[+part]=1;
    });
    return Object.keys(out).map(Number).sort(function(x,y){ return x-y; });
  }

  async function save(saying){
    say(saying||'saving…');
    try{
      var r = await fetch('/motifs',{method:'POST',headers:{'Content-Type':'application/json'},
                                     body:JSON.stringify({motifs:MOTIFS})});
      var j = await r.json(); if(!j.ok) throw new Error(j.error||'failed');
      location.reload();
    }catch(e){ say('failed: '+e.message); }
  }

  document.querySelectorAll('.motrow .mx').forEach(function(b){
    b.addEventListener('click', function(){
      var i = +b.dataset.i, name = MOTIFS[i] && MOTIFS[i].name;
      MOTIFS.splice(i,1); save('removing “'+name+'”…');
    });
  });

  $('mot-findbtn').addEventListener('click', async function(){
    var q = $('mot-find').value.trim();
    if(!q){ $('mot-find').focus(); return; }
    say('searching for “'+q+'”…');
    try{
      var r = await fetch('/motif-search',{method:'POST',headers:{'Content-Type':'application/json'},
                                           body:JSON.stringify({query:q})});
      var j = await r.json(); if(!j.ok) throw new Error(j.error||'failed');
      $('mot-secs').value = (j.sections||[]).join(', ');
      if(!$('mot-name').value.trim()) $('mot-name').value = q;
      say(j.sections.length + ' section(s) found — adjust them, then add');
    }catch(e){ say('search failed: '+e.message); }
  });

  $('mot-add').addEventListener('click', function(){
    var name = $('mot-name').value.trim();
    if(!name){ $('mot-name').focus(); return; }
    var secs = parseSecs($('mot-secs').value);
    if(!secs.length){ say('give it at least one section — type a word and press find, or list numbers'); return; }
    MOTIFS = MOTIFS.filter(function(m){ return m.name.toLowerCase() !== name.toLowerCase(); });  // replace dupes
    MOTIFS.push({name:name, color:$('mot-color').value, sections:secs});
    save('adding “'+name+'”…');
  });
  $('mot-secs').addEventListener('keydown', function(e){ if(e.key==='Enter') $('mot-add').click(); });
  $('mot-find').addEventListener('keydown', function(e){ if(e.key==='Enter'){ e.preventDefault(); $('mot-findbtn').click(); } });
})();
</script>"""

HTML = f"""{page_head(f"{config.TITLE} — Motifs")}
{STYLE}</head><body><div class="wrap">
{topbar_html("motifs.html")}
<header><div class="kicker">Motifs</div>
<h1>{config.TITLE_HTML} <span>&mdash; motifs</span></h1>
<p class="sub">A motif is a thread you name: a word or an idea that keeps coming back.
Mark the sections it appears in and the reading copy colours them.</p></header>
<div id="motlist">{rows or EMPTY}</div>
<div class="motadd">
  <input id="mot-name" type="text" placeholder="motif name… e.g. the sea" autocomplete="off">
  <input id="mot-color" type="color" value="{config.PALETTE[0]}" title="pick a colour">
  <input id="mot-find" type="text" placeholder="find sections containing…" autocomplete="off">
  <button id="mot-findbtn" type="button">find</button>
  <input id="mot-secs" type="text" placeholder="sections: 1, 15, 31-40" autocomplete="off">
  <button id="mot-add" type="button">＋ add motif</button>
  <span id="mot-status"></span>
</div>
<p class="note">Editing needs the app to be served — run <code>pal serve</code>.
The search is a plain word match over your sections; nothing is inferred.</p>
<footer>{len(MOTIFS)} motif(s) · stored in <code>data/motifs.json</code></footer>
</div>
{SCRIPT.replace("__MOTIFS__", MOTIFS_JSON)}
<script src="pal.js"></script></body></html>"""

if __name__ == "__main__":
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(HTML)
    print(f"wrote {OUT} · {len(MOTIFS)} motif(s)")
