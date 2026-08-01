#!/usr/bin/env python3
"""Color-coded reading copy: every section of the active book with motif chips, colored
borders, and a sticky JS filter to isolate a single motif inside the text."""

import html, json, os, re
from sections import (
    read_section,
    section_paths,
    load_labels,
    load_parts,
    load_unnumbered,
    held_paths,
    load_dividers,
    part_of,
    label_chips_html,
)
from nav import topbar_html, page_head, script_json

import config

MAN = config.MANUSCRIPT
MOTIFS = config.motifs()

# section -> list of (idx, name, color)
sec_motifs = {}
for i, m in enumerate(MOTIFS):
    for s in m["sections"]:
        sec_motifs.setdefault(s, []).append((i, m["name"], m["color"]))


def slug(i):
    return f"m{i}"


files = section_paths()  # order.json manifest, then numeric remainder
labels = load_labels()  # section id -> [{text,color}]
parts = load_parts()  # start-section id -> {title, subtitle}
parts_js = script_json(parts)
unnum = load_unnumbered()  # sids that print but aren't numbered
unnum_js = json.dumps(sorted(unnum))
dividers = load_dividers()  # ordered [{id,title}] — the 4 part-divider sections
divider_ids = {d["id"] for d in dividers}
order_ids = [os.path.basename(p)[:-3] for p in files]  # flow order, for part_of()
dividers_js = script_json(dividers)
FENCE_RE = re.compile(r"(\{\{/?contents\}\})")  # dim the literal contents fences (round-trip safe)


def part_cell_html(fn):
    """The per-section 'which part' control: a badge for a divider, else a picker."""
    if fn in divider_ids:
        title = next(d["title"] for d in dividers if d["id"] == fn)
        return (
            f'<span class="partbadge" title="this section begins a part">'
            f"◆ {html.escape(title.split(':')[0].strip())}</span>"
        )
    if not dividers:
        return ""
    cur = part_of(fn, order_ids, dividers)
    o = [f'<option value=""{" selected" if cur == "" else ""}>front matter</option>']
    for d in dividers:
        short = html.escape(d["title"].split(":")[0].strip())
        o.append(f'<option value="{d["id"]}"{" selected" if cur == d["id"] else ""}>{short}</option>')
    return (
        f'<select class="partsel" data-sec="{fn}" title="move this section to a part">{"".join(o)}</select>'
    )


# distinct labels (in first-seen order) -> a stable color, for the filter bar
label_colors = {}
for _sid, labs in labels.items():
    for l in labs:
        label_colors.setdefault(l["text"], l["color"])

# filter bar chips — motifs first, then authored labels (a parallel dimension)
chips = ['<button class="chip allbtn" data-m="all">show all</button>']
for i, m in enumerate(MOTIFS):
    chips.append(
        f'<button class="chip" data-m="{slug(i)}" style="--c:{m["color"]}">'
        f'<span class="dot" style="background:{m["color"]}"></span>{html.escape(m["name"])} '
        f'<span class="ct">{len(m["sections"])}</span></button>'
    )
# label filter chips (data-l); count = sections carrying that label
if label_colors:
    chips.append('<span class="chipsep" title="your labels"></span>')
    lab_counts = {}
    for labs in labels.values():
        for l in labs:
            lab_counts[l["text"]] = lab_counts.get(l["text"], 0) + 1
    for text, color in label_colors.items():
        chips.append(
            f'<button class="chip lfilter" data-l="{html.escape(text, quote=True)}" style="--c:{color}">'
            f'<span class="dot" style="background:{color}"></span>{html.escape(text)} '
            f'<span class="ct">{lab_counts.get(text, 0)}</span></button>'
        )

blocks = []
num = 0
for _pos, path in enumerate(files, 1):  # pos = raw display position (order.json order)
    fn = os.path.basename(path).replace(".md", "")
    secnum = int(fn)
    numbered = fn not in unnum
    if numbered:
        num += 1  # scene number skips unnumbered sections
    filen = f"§{num}" if numbered else "§—"
    # strip the file's own heading (# N = stable file id); display uses `pos`
    body = read_section(path)[1]
    motifs_here = sec_motifs.get(secnum, [])
    classes = " ".join(slug(i) for (i, _, _) in motifs_here) or "none"
    border = motifs_here[0][2] if motifs_here else "var(--line)"
    chips_row = ""
    for _id, name, color in motifs_here:
        chips_row += (
            f'<span class="mchip" style="background:{color}1a;color:{color};'
            f'border-color:{color}55">{html.escape(name)}</span>'
        )
    body_html = html.escape(body).replace("\n", "<br>\n")
    # wrap the {{contents}}/{{/contents}} fence markers in a dim span — the marker
    # text is preserved verbatim, so the contenteditable body still round-trips to disk
    body_html = FENCE_RE.sub(r'<span class="fence">\1</span>', body_html)
    data_labels = "|".join(html.escape(l["text"], quote=True) for l in labels.get(fn, []))
    lchips = label_chips_html(fn, labels)
    if fn in parts:  # part-break banner (sibling of the article)
        p = parts[fn]
        sub = f'<span class="ps">{html.escape(p["subtitle"])}</span>' if p["subtitle"] else ""
        blocks.append(
            f'<div class="partbreak" data-start="{fn}">'
            f'<span class="pt">{html.escape(p["title"])}</span>{sub}</div>'
        )
    blocks.append(
        f'<article class="sec {classes}{"" if numbered else " unnum"}" data-motifs="{classes}" data-labels="{data_labels}" '
        f'id="s{fn}" style="border-left-color:{border}">'
        f'<div class="sechd"><span class="drag" title="drag to reorder">⠿</span>'
        f'<span class="filen">{filen}</span>'
        f'<span class="fid" title="file id (stable; used for links, motifs, delete)">{fn}</span>{chips_row}'
        f'<span class="labwrap" data-sec="{fn}">{lchips}</span>{part_cell_html(fn)}</div>'
        f'<div class="body" spellcheck="true" lang="en">{body_html}</div>'
        f'<div class="ed"><button class="edbtn">✎ edit</button> '
        f'<button class="rvbtn" hidden>revert</button><span class="edstatus"></span></div>'
        "</article>"
    )

# ---- the "Set aside" shelf: parked sections (out of the flow, still on disk) ----
shelf_cards = []
for path in held_paths():
    fn = os.path.basename(path).replace(".md", "")
    printed_id, body = read_section(path)
    printed = printed_id or fn
    preview = html.escape((body.split("\n", 1)[0] or "(empty)")[:140])
    full = html.escape(body).replace("\n", "<br>\n")
    shelf_cards.append(
        f'<div class="shelfcard" data-sec="{fn}" draggable="true">'
        f'<div class="schd"><span class="scgrip" title="drag into the flow">⠿</span>'
        f'<span class="fid" title="file id">{fn}</span><span class="sprn">#{printed}</span>'
        f'<button class="scbtn scview">view</button>'
        f'<button class="scbtn scplace">place…</button>'
        f'<button class="scbtn screturn">↩ return</button></div>'
        f'<div class="scprev">{preview}</div>'
        f'<div class="scfull" hidden>{full}</div>'
        "</div>"
    )
shelf_html = (
    f'<div id="shelf" class="shelf"{"" if shelf_cards else " hidden"}>'
    f'<div class="shelfhd">Set aside <span class="shelfct">{len(shelf_cards)}</span>'
    f'<span class="shelfhint">— pulled out of the flow (not printed, not numbered, not archived). '
    f"Drag a card into the text, or “place…”, to put it back.</span></div>"
    f'<div class="shelfbody">{"".join(shelf_cards)}</div></div>'
)

# edit + writing-record JS — kept as a plain (non-f) string so its many { }
# braces need no doubling; injected into the template below via {EDIT_JS}.
EDIT_JS = r"""
// ---- edit + save (writes manuscript/NNN.md and git-commits when served) ----
const HTTP=location.protocol.startsWith('http');
document.getElementById('modebar').textContent = HTTP
  ? '✎ edit mode — each save writes manuscript/NNN.md and git-commits it (a version). Your typing is recorded to keystrokes/ (local only).'
  : '✎ edit mode (offline) — saves download NNN.md; run “pal serve” for direct save + commit. Typing is recorded in-browser (⬇ session to export).';

// caret char-offset within an editable element (best-effort)
function caretOffset(el){
  const s=window.getSelection();
  if(!s || !s.rangeCount) return -1;
  const r=s.getRangeAt(0), pre=document.createRange();
  pre.selectNodeContents(el); pre.setEnd(r.endContainer, r.endOffset);
  return pre.toString().length;
}

// ---- writing-record: silently capture keystrokes, timing, deletes, saves ----
const REC=(function(){
  const SID=String(Date.now())+'-'+Math.random().toString(36).slice(2,8);
  const LS='__PAL_NS__-rec:'+SID;
  let buf=[], all=[], last=0, live=false, ac=null, ring=[];
  function push(ev){
    const t=Date.now();
    ev.v=1; ev.session=SID; ev.t=t; ev.pt=Math.round(performance.now());
    ev.dt=last?(t-last):0; last=t;
    buf.push(ev); all.push(ev);
    try{localStorage.setItem(LS,JSON.stringify(all));}catch(e){}
    if(live) tick(ev);
    if(buf.length>=40) flush(false);
  }
  function flush(beacon){
    if(!buf.length || !HTTP) return;
    const body=JSON.stringify({session:SID,events:buf}); buf=[];
    if(beacon && navigator.sendBeacon){
      navigator.sendBeacon('/keystrokes', new Blob([body],{type:'application/json'}));
    } else {
      fetch('/keystrokes',{method:'POST',headers:{'Content-Type':'application/json'},body:body,keepalive:true}).catch(function(){});
    }
  }
  setInterval(function(){flush(false);},2000);
  addEventListener('visibilitychange',function(){if(document.visibilityState==='hidden')flush(true);});
  addEventListener('beforeunload',function(){flush(true);});

  // small fixed control: rec indicator + live toggle + session download
  const bar=document.createElement('div'); bar.id='recbar';
  bar.innerHTML='<span class="rdot"></span><span class="rlab">rec</span>'
    +'<label class="rtog"><input type="checkbox" id="reclive"> live</label>'
    +'<canvas id="recspark" width="120" height="22"></canvas>'
    +'<a href="#" id="recdl" title="download this writing session as .jsonl">⬇ session</a>';
  function mount(){ document.body.appendChild(bar); wire(); }
  if(document.readyState==='loading'){ addEventListener('DOMContentLoaded',mount); } else { mount(); }
  function wire(){
    document.getElementById('reclive').addEventListener('change',function(e){
      live=e.target.checked;
      if(live && !ac){ try{ ac=new (window.AudioContext||window.webkitAudioContext)(); }catch(_){} }
    });
    document.getElementById('recdl').addEventListener('click',function(e){ e.preventDefault(); download(); });
  }
  function download(){
    const nl=String.fromCharCode(10);
    const lines=all.map(function(x){return JSON.stringify(x);}).join(nl)+nl;
    const b=new Blob([lines],{type:'application/x-ndjson'});
    const a=document.createElement('a'); a.href=URL.createObjectURL(b);
    a.download='writing-'+SID+'.jsonl'; a.click();
  }
  // the sparkline is canvas, so it reads the theme token instead of inheriting it
  // (pal.js loads after this script, hence the guard + fallback)
  function inkOf(tok, fb){ return (window.palTheme && palTheme.ink) ? palTheme.ink(tok, fb) : fb; }
  function tick(ev){
    if(ev.type!=='keydown' && ev.type!=='input') return;
    ring.push(Math.min(ev.dt||0,1000)); if(ring.length>60) ring.shift();
    const c=document.getElementById('recspark');
    if(c){
      const g=c.getContext('2d'), W=c.width, H=c.height; g.clearRect(0,0,W,H);
      g.strokeStyle=inkOf('--gold','#b8860b'); g.lineWidth=1; g.beginPath();
      for(let i=0;i<ring.length;i++){
        const x=i/59*W, y=H-(1-ring[i]/1000)*H*0.9-1;
        i?g.lineTo(x,y):g.moveTo(x,y);
      }
      g.stroke();
    }
    // sound on keydown only (so each keystroke rings once); each LETTER = its own note.
    if(ac && ev.type==='keydown'){
      const k=ev.key||'';
      const DIA=[0,2,4,5,7,9,11];                 // C-major scale degrees (semitones)
      const C3=130.81;                             // base pitch
      let type='sine', freq=null, dur=0.12, peak=0.07;
      if(k==='Backspace'||k==='Delete'){ type='sawtooth'; freq=150; }        // low descend
      else if(k==='Enter'){ type='sine'; freq=98; dur=0.2; }                  // low chime
      else if(k===' '){ type='triangle'; freq=131; dur=0.06; peak=0.05; }     // soft tap
      else if(k.length===1 && /[a-z]/i.test(k)){                              // a..z → ascending diatonic
        const i=k.toLowerCase().charCodeAt(0)-97;
        const semi=DIA[i%7]+12*Math.floor(i/7);   // new octave every 7 letters (~C3–G6, all 26 distinct)
        freq=C3*Math.pow(2, semi/12);
      }
      else if(k.length===1){                                                  // digits / punctuation → high sparkle
        type='triangle'; dur=0.07; freq=C3*Math.pow(2, (DIA[k.charCodeAt(0)%7]+36)/12);
      }
      if(freq){
        const o=ac.createOscillator(), gg=ac.createGain();
        o.type=type; o.frequency.value=freq;
        o.connect(gg); gg.connect(ac.destination);
        const n=ac.currentTime; gg.gain.setValueAtTime(0.0001,n);
        gg.gain.exponentialRampToValueAtTime(peak,n+0.005);
        gg.gain.exponentialRampToValueAtTime(0.0001,n+dur);
        o.start(n); o.stop(n+dur+0.02);
      }
    }
  }
  return {push:push, flush:flush, SID:SID};
})();

secs.forEach(function(sec){
  const body=sec.querySelector('.body'), btn=sec.querySelector('.edbtn'),
        rv=sec.querySelector('.rvbtn'), st=sec.querySelector('.edstatus');
  const num=sec.id.replace('s','');
  let orig=null, onKd=null, onInp=null;
  function attach(){
    onKd=function(e){ REC.push({type:'keydown',section:num,key:e.key,code:e.code,len:body.innerText.length,caret:caretOffset(body)}); };
    onInp=function(e){ REC.push({type:'input',section:num,inputType:e.inputType,data:e.data,len:body.innerText.length,caret:caretOffset(body)}); };
    body.addEventListener('keydown',onKd); body.addEventListener('input',onInp);
  }
  function detach(){
    if(onKd) body.removeEventListener('keydown',onKd);
    if(onInp) body.removeEventListener('input',onInp);
    onKd=onInp=null;
  }
  btn.addEventListener('click', async function(){
    if(btn.dataset.on!=='1'){
      orig=body.innerHTML; body.contentEditable='true'; body.spellcheck=true; body.classList.add('editing');
      btn.dataset.on='1'; btn.textContent='💾 save'; rv.hidden=false; st.textContent=''; body.focus();
      REC.push({type:'editstart',section:num,text0:body.innerText,len:body.innerText.length});
      attach();
    } else {
      const text=body.innerText.trim();
      body.contentEditable='false'; body.classList.remove('editing');
      btn.dataset.on=''; btn.textContent='✎ edit'; rv.hidden=true;
      REC.push({type:'editend',section:num,len:text.length,text:text}); detach();
      if(HTTP){
        st.textContent='saving…';
        try{
          const r=await fetch('/save',{method:'POST',headers:{'Content-Type':'application/json'},
            body:JSON.stringify({section:num,text:text})});
          const j=await r.json();
          st.textContent = j.ok ? ('✓ '+(j.committed?('committed '+j.commit):j.msg)) : ('✗ '+j.error);
          REC.push({type:'save',section:num,ok:!!j.ok,commit:j.commit||null,committed:!!j.committed});
        }catch(e){ st.textContent='✗ no save-server — run “pal serve”'; REC.push({type:'save',section:num,ok:false}); }
        REC.flush(false);
      } else {
        const printed=sec.querySelector('.prn').textContent.replace('§','');
        const nl=String.fromCharCode(10);
        const blob=new Blob([['# '+printed,'',text].join(nl)+nl],{type:'text/markdown'});
        const a=document.createElement('a'); a.href=URL.createObjectURL(blob); a.download=num+'.md'; a.click();
        st.textContent='downloaded '+num+'.md → drop into manuscript/';
        REC.push({type:'save',section:num,ok:true,offline:true});
      }
    }
  });
  rv.addEventListener('click', function(){
    if(orig!==null) body.innerHTML=orig;
    body.contentEditable='false'; body.classList.remove('editing');
    btn.dataset.on=''; btn.textContent='✎ edit'; rv.hidden=true; st.textContent='reverted';
    REC.push({type:'revert',section:num}); detach();
  });
});

// ---- authored labels · reorder · add · delete (all persist via save_server) ----
const counterEl = document.getElementById('counter');
function secStatus(t){ const s=document.getElementById('secst'); if(s) s.textContent=t; }

// label colors: deterministic from text (palette injected from config.PALETTE
// below, so JS and Python can't drift)
const PALETTE=__PALETTE__;
function labelColor(t){ let h=0; for(let i=0;i<t.length;i++) h+=t.charCodeAt(i); return PALETTE[h%PALETTE.length]; }

// filter sections by an authored label — COLLAPSE (hide) everything except that label
function clearCollapse(){
  document.querySelectorAll('.sec.collapsed,.partbreak.collapsed').forEach(e=>e.classList.remove('collapsed'));
}
function applyLabel(label){
  clearCollapse();
  let n=0;
  secs.forEach(s=>{
    const labs=(s.dataset.labels||'').split('|').filter(Boolean);
    const has=labs.indexOf(label)>=0;
    s.classList.remove('dim');
    s.classList.toggle('collapsed', !has);          // hide non-matching sections entirely
    if(has) n++;
  });
  document.querySelectorAll('.partbreak').forEach(b=>b.classList.add('collapsed'));  // hide part banners while filtered
  chips.forEach(c=>c.classList.toggle('active', c.dataset.l===label));
  const cn=document.getElementById('counter'); if(cn) cn.textContent = n+' sections · label “'+label+'”';
}
// ---- labels ----
const LKEY='__PAL_NS__-labels';
function collectLabels(){
  const out={};
  document.querySelectorAll('.labwrap').forEach(w=>{
    const arr=[];
    w.querySelectorAll('.lchip').forEach(ch=>arr.push({text:ch.dataset.label, color:ch.dataset.color||labelColor(ch.dataset.label)}));
    if(arr.length) out[w.dataset.sec]=arr;
  });
  return out;
}
let lsaveT=null;
function persistLabels(){
  const data=collectLabels();
  try{ localStorage.setItem(LKEY, JSON.stringify(data)); }catch(e){}
  if(!HTTP){ secStatus('labels saved in browser (offline)'); return; }
  clearTimeout(lsaveT);
  lsaveT=setTimeout(()=>{
    fetch('/labels',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({labels:data})})
      .then(r=>r.json()).then(j=>secStatus(j.ok?('labels saved · '+j.sections+' tagged'):'label save failed')).catch(()=>secStatus('label save failed'));
  },1000);
}
function chipX(ch){
  if(ch.querySelector('.x')) return;
  const x=document.createElement('span'); x.className='x'; x.textContent='×';
  x.addEventListener('click',e=>{ e.stopPropagation(); ch.remove(); persistLabels(); });
  ch.appendChild(x);
}
function chipFilter(ch){                              // click a section's label chip → collapse to that label
  if(ch.dataset.wired) return; ch.dataset.wired='1';
  ch.addEventListener('click',e=>{ if(e.target.classList.contains('x')) return; applyLabel(ch.dataset.label); });
}
function addChip(w, text, before){
  if([...w.querySelectorAll('.lchip')].some(c=>c.dataset.label===text)) return;
  const c=labelColor(text);
  const s=document.createElement('span'); s.className='lchip'; s.dataset.label=text; s.dataset.color=c;
  s.style.cssText='background:'+c+'22;color:'+c+';border-color:'+c+'66';
  s.appendChild(document.createTextNode(text));
  chipX(s); chipFilter(s);
  w.insertBefore(s, before);
}
function initLabels(){
  document.querySelectorAll('.labwrap').forEach(w=>{
    w.querySelectorAll('.lchip').forEach(ch=>{ chipX(ch); chipFilter(ch); });
    const add=document.createElement('button'); add.className='addlbl'; add.textContent='+ label';
    add.addEventListener('click',()=>{
      const inp=document.createElement('input'); inp.className='lin'; inp.placeholder='label…';
      w.insertBefore(inp, add); inp.focus();
      const commit=(keep)=>{
        const t=inp.value.trim(); inp.remove();
        if(keep && t){ addChip(w, t, add); persistLabels(); }
      };
      inp.addEventListener('keydown',e=>{ if(e.key==='Enter'){e.preventDefault();commit(true);} else if(e.key==='Escape'){commit(false);} });
      inp.addEventListener('blur',()=>commit(true));
    });
    w.appendChild(add);
  });
}

// ---- reorder (drag handle → move article → POST /order → rebuild) ----
function currentOrder(){ return [...document.querySelectorAll('.sec')].map(s=>s.id.replace('s','')); }
function persistOrder(){
  if(!HTTP){ secStatus('reordered (offline — not saved)'); return; }
  fetch('/order',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({order:currentOrder()})})
    .then(r=>r.json()).then(j=>{ if(j.ok){ secStatus('order saved · rebuilding…'); rebuild(); } else secStatus('order save failed: '+j.error); })
    .catch(()=>secStatus('order save failed'));
}
function initReorder(){
  let dragged=null;
  secs.forEach(sec=>{
    const handle=sec.querySelector('.drag'); if(!handle) return;
    handle.addEventListener('mousedown',()=>{ sec.draggable=true; });
    handle.addEventListener('mouseup',()=>{ sec.draggable=false; });
    sec.addEventListener('dragstart',e=>{ dragged=sec; sec.classList.add('dragging'); e.dataTransfer.effectAllowed='move'; try{e.dataTransfer.setData('text/plain',sec.id);}catch(_){}} );
    sec.addEventListener('dragend',()=>{ sec.classList.remove('dragging'); sec.draggable=false; document.querySelectorAll('.sec.dragover').forEach(s=>s.classList.remove('dragover')); });
    sec.addEventListener('dragover',e=>{ e.preventDefault(); if(sec!==dragged) sec.classList.add('dragover'); });
    sec.addEventListener('dragleave',()=>sec.classList.remove('dragover'));
    sec.addEventListener('drop',e=>{
      e.preventDefault(); sec.classList.remove('dragover');
      if(!dragged || dragged===sec) return;
      const r=sec.getBoundingClientRect(); const after=e.clientY > r.top + r.height/2;
      sec.parentNode.insertBefore(dragged, after ? sec.nextSibling : sec);
      persistOrder();
    });
  });
}

// ---- add / delete / rebuild ----
function rebuild(){
  if(!HTTP) return;
  fetch('/rebuild',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})
    .then(r=>r.json()).then(j=>secStatus(j.ok?'views rebuilt · reload to see':'rebuild failed')).catch(()=>{});
}
function addSection(){
  if(!HTTP){ secStatus('add needs “pal serve”'); return; }
  secStatus('adding…');
  fetch('/section/add',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})
    .then(r=>r.json()).then(j=>{
      if(!j.ok){ secStatus('add failed: '+j.error); return; }
      secStatus('added §'+j.pos+' · rebuilding…');
      fetch('/rebuild',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}).then(()=>location.reload());
    }).catch(()=>secStatus('add failed'));
}
function insertBelow(after){
  if(!HTTP){ secStatus('insert needs “pal serve”'); return; }
  secStatus('inserting after §·'+after+'…');
  fetch('/section/add',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({after})})
    .then(r=>r.json()).then(j=>{
      if(!j.ok){ secStatus('insert failed: '+j.error); return; }
      secStatus('inserted §'+j.pos+' · rebuilding…');
      fetch('/rebuild',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}).then(()=>location.reload());
    }).catch(()=>secStatus('insert failed'));
}
function delSection(num, btn){
  if(btn.dataset.arm!=='1'){                       // two-click confirm (no blocking dialog)
    btn.dataset.arm='1'; btn.textContent='archive §'+num+'? click again';
    setTimeout(()=>{ if(btn.dataset.arm==='1'){ btn.dataset.arm=''; btn.textContent='🗑 delete'; } },4000);
    return;
  }
  btn.dataset.arm=''; btn.textContent='archiving…';
  if(!HTTP){ secStatus('delete needs “pal serve”'); btn.textContent='🗑 delete'; return; }
  fetch('/section/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({section:num})})
    .then(r=>r.json()).then(j=>{
      if(!j.ok){ secStatus('delete failed: '+j.error); btn.textContent='🗑 delete'; return; }
      secStatus('archived §'+num+' → _attic · rebuilding…');
      fetch('/rebuild',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}).then(()=>location.reload());
    }).catch(()=>{ secStatus('delete failed'); btn.textContent='🗑 delete'; });
}
function mountSecbar(){
  // section-editing controls only; Export PDF + Rebuild live in the shared top bar
  const bar=document.createElement('div'); bar.id='secbar';
  bar.innerHTML='<button id="secadd">＋ section</button><span class="st" id="secst"></span>';
  document.body.appendChild(bar);
  document.getElementById('secadd').addEventListener('click',addSection);
  secs.forEach(sec=>{
    const ed=sec.querySelector('.ed'); if(!ed) return;
    const num=sec.id.replace('s','');
    const h=document.createElement('button'); h.className='delbtn histbtn'; h.textContent='⧗ history';
    h.addEventListener('click',()=>showHistory(num, sec));
    ed.appendChild(h);
    const ins=document.createElement('button'); ins.className='delbtn insbtn'; ins.textContent='＋ insert below';
    ins.addEventListener('click',()=>insertBelow(num));
    ed.appendChild(ins);
    const pk=document.createElement('button'); pk.className='delbtn parkbtn'; pk.textContent='⇥ set aside';
    pk.addEventListener('click',()=>parkSection(num,pk));
    ed.appendChild(pk);
    const b=document.createElement('button'); b.className='delbtn'; b.textContent='🗑 delete';
    b.addEventListener('click',()=>delSection(num,b));
    ed.appendChild(b);
  });
}
function parkSection(sid, btn){
  if(!HTTP){ secStatus('set aside needs “pal serve”'); return; }
  btn.textContent='setting aside…';
  fetch('/section/park',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({section:sid})})
    .then(r=>r.json()).then(j=>{
      if(!j.ok){ secStatus('set aside failed: '+j.error); btn.textContent='⇥ set aside'; return; }
      secStatus('set aside §'+sid+' · reloading'); location.reload();
    }).catch(()=>{ secStatus('set aside failed'); btn.textContent='⇥ set aside'; });
}

// ---- the "Set aside" shelf: return / place / drag a parked card into the flow ----
let placingSid=null, dragSid=null;
function unpark(sid, after){
  if(!HTTP){ secStatus('placing needs “pal serve”'); return; }
  const body={section:sid}; if(after!==undefined) body.after=after;
  fetch('/section/unpark',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
    .then(r=>r.json()).then(j=>{ if(j.ok){ secStatus('placed §'+sid+' · reloading'); location.reload(); }
      else secStatus('place failed: '+j.error); }).catch(()=>secStatus('place failed'));
}
function clearPlacing(){ placingSid=null; document.body.classList.remove('placing'); }
function initShelf(){
  const flow=[...document.querySelectorAll('.sec')];
  document.querySelectorAll('.shelfcard').forEach(card=>{
    const sid=card.dataset.sec;
    card.querySelector('.scview').addEventListener('click',()=>{
      const f=card.querySelector('.scfull'), p=card.querySelector('.scprev');
      const show=f.hidden; f.hidden=!show; p.hidden=show;
    });
    card.querySelector('.screturn').addEventListener('click',()=>unpark(sid)); // no after -> stored anchor
    card.querySelector('.scplace').addEventListener('click',()=>{
      if(placingSid===sid){ clearPlacing(); secStatus(''); return; }
      placingSid=sid; document.body.classList.add('placing');
      secStatus('placing §'+sid+' — click a ▸ place-here target (Esc to cancel)');
    });
    card.addEventListener('dragstart',e=>{ dragSid=sid; e.dataTransfer.effectAllowed='move';
      try{e.dataTransfer.setData('text/plain',sid);}catch(_){}} );
    card.addEventListener('dragend',()=>{ dragSid=null; document.querySelectorAll('.sec.dragover').forEach(s=>s.classList.remove('dragover')); });
  });
  if(!flow.length) return;
  // click-to-place targets (revealed only in placing mode via CSS): insert BEFORE each section
  flow.forEach((sec,i)=>{
    const prev = i>0 ? flow[i-1].id.replace('s','') : '';   // '' => at the very start
    const t=document.createElement('button'); t.className='placehere'; t.textContent='▸ place here';
    t.addEventListener('click',()=>{ if(placingSid) unpark(placingSid, prev); });
    sec.parentNode.insertBefore(t, sec);
  });
  const last=flow[flow.length-1];
  const end=document.createElement('button'); end.className='placehere'; end.textContent='▸ place at end';
  end.addEventListener('click',()=>{ if(placingSid) unpark(placingSid, last.id.replace('s','')); });
  last.parentNode.insertBefore(end, last.nextSibling);
  // drag a shelf card onto a flow section
  flow.forEach(sec=>{
    sec.addEventListener('dragover',e=>{ if(dragSid){ e.preventDefault(); sec.classList.add('dragover'); } });
    sec.addEventListener('dragleave',()=>{ if(dragSid) sec.classList.remove('dragover'); });
    sec.addEventListener('drop',e=>{
      if(!dragSid) return;                                  // a flow-reorder drop; leave it to initReorder
      e.preventDefault(); sec.classList.remove('dragover');
      const r=sec.getBoundingClientRect(); const below=e.clientY > r.top + r.height/2;
      const now=[...document.querySelectorAll('.sec')]; const idx=now.indexOf(sec);
      const afterId = below ? sec.id.replace('s','') : (idx>0 ? now[idx-1].id.replace('s','') : '');
      unpark(dragSid, afterId); dragSid=null;
    });
  });
  addEventListener('keydown',e=>{ if(e.key==='Escape' && placingSid){ clearPlacing(); secStatus(''); } });
}

// ---- per-section version history (view + restore; all read from git) ----
function showHistory(num, sec){
  const ed=sec.querySelector('.ed');
  let panel=ed.querySelector('.histpanel');
  if(panel){ panel.remove(); return; }             // toggle off
  panel=document.createElement('div'); panel.className='histpanel'; panel.textContent='loading history…';
  ed.appendChild(panel);
  if(!HTTP){ panel.textContent='history needs “pal serve”'; return; }
  fetch('/history?section='+encodeURIComponent(num)).then(r=>r.json()).then(j=>{
    if(!j.ok){ panel.textContent='history unavailable: '+j.error; return; }
    if(!j.versions.length){ panel.textContent='no saved versions yet for this section'; return; }
    panel.innerHTML='';
    const hd=document.createElement('div'); hd.className='hrow'; hd.style.opacity='.6';
    hd.innerHTML='<span class="htime">'+j.versions.length+' versions</span><span class="hsub">newest first · view or restore any</span>';
    panel.appendChild(hd);
    j.versions.forEach(v=>{
      const row=document.createElement('div'); row.className='hrow';
      const time=document.createElement('span'); time.className='htime'; time.textContent=v.date;
      const sub=document.createElement('span'); sub.className='hsub'; sub.textContent=v.subject;
      const view=document.createElement('button'); view.className='hbtn'; view.textContent='view';
      const rest=document.createElement('button'); rest.className='hbtn'; rest.textContent='restore';
      view.addEventListener('click',()=>viewVersion(num, v, panel));
      rest.addEventListener('click',()=>restoreVersion(num, v, rest));
      row.appendChild(time); row.appendChild(sub); row.appendChild(view); row.appendChild(rest);
      panel.appendChild(row);
    });
  }).catch(()=>{ panel.textContent='history needs the save-server'; });
}
function viewVersion(num, v, panel){
  fetch('/version?section='+encodeURIComponent(num)+'&commit='+v.hash).then(r=>r.json()).then(j=>{
    let box=panel.querySelector('.hview'); if(!box){ box=document.createElement('pre'); box.className='hview'; panel.appendChild(box); }
    box.textContent = j.ok ? j.text : ('could not load: '+j.error);
    box.scrollIntoView({block:'nearest'});
  }).catch(()=>{});
}
function restoreVersion(num, v, btn){
  if(btn.dataset.arm!=='1'){                        // two-click confirm (no blocking dialog)
    btn.dataset.arm='1'; btn.textContent='confirm restore?';
    setTimeout(()=>{ if(btn.dataset.arm==='1'){ btn.dataset.arm=''; btn.textContent='restore'; } },4000);
    return;
  }
  btn.dataset.arm=''; btn.textContent='restoring…';
  fetch('/restore',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({section:num, commit:v.hash})})
    .then(r=>r.json()).then(j=>{
      if(j.ok){ secStatus('restored §·'+num+' to '+v.short+' · reloading'); location.reload(); }
      else { secStatus('restore failed: '+j.error); btn.textContent='restore'; }
    }).catch(()=>{ secStatus('restore failed'); btn.textContent='restore'; });
}

// ---- part breaks (⋔ marks where a Part begins; banner is a sibling of .sec) ----
// PARTS (server truth at load) is defined in the main script above; {sid:{title,subtitle}}.
function partBanner(sid){ return document.querySelector('.partbreak[data-start="'+sid+'"]'); }
function renderBanner(sec, sid){
  let bn=partBanner(sid); const p=PARTS[sid];
  if(!p){ if(bn) bn.remove(); return; }
  if(!bn){ bn=document.createElement('div'); bn.className='partbreak'; bn.dataset.start=sid;
           sec.parentNode.insertBefore(bn, sec); }
  bn.innerHTML='<span class="pt"></span><span class="ps"></span>';
  bn.querySelector('.pt').textContent=p.title;
  bn.querySelector('.ps').textContent=p.subtitle||'';
}
function persistParts(){
  const arr=Object.keys(PARTS).map(sid=>({start:sid,title:PARTS[sid].title,subtitle:PARTS[sid].subtitle||''}));
  try{ localStorage.setItem('__PAL_NS__-parts', JSON.stringify(arr)); }catch(e){}
  if(!HTTP){ secStatus('part saved in browser (offline — run “pal serve” to persist)'); return; }
  fetch('/parts',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({parts:arr})})
    .then(r=>r.json()).then(j=>secStatus(j.ok?('parts saved · '+j.count+(j.committed?(' · '+j.commit):'')):('part save failed: '+j.error)))
    .catch(()=>secStatus('part save failed'));
}
function setPart(sec, sid, btn){
  const cur=PARTS[sid];
  const title=prompt('Part title (blank to clear the break):', cur?cur.title:'');
  if(title===null) return;                       // cancelled — no change
  const t=title.trim();
  if(!t){ delete PARTS[sid]; renderBanner(sec,sid); btn.classList.remove('on'); persistParts(); return; }
  let sub=prompt('Subtitle (optional):', cur?(cur.subtitle||''):'');
  if(sub===null) sub = cur?(cur.subtitle||''):'';
  PARTS[sid]={title:t, subtitle:sub.trim()};
  renderBanner(sec,sid); btn.classList.add('on'); persistParts();
}
function initParts(){
  secs.forEach(sec=>{
    const hd=sec.querySelector('.sechd'); if(!hd) return;
    const sid=sec.id.replace('s','');
    const b=document.createElement('button'); b.className='partbtn'+(PARTS[sid]?' on':'');
    b.textContent='⋔'; b.title='mark where a Part begins here';
    b.addEventListener('click',()=>setPart(sec, sid, b));
    hd.appendChild(b);
  });
}

// ---- unnumbered sections (№ prints the prose but assigns no §number) ----
// UNNUMBERED (a Set of sids) is defined in the main script above.
function renumber(){
  let n=0;
  secs.forEach(sec=>{
    const fe=sec.querySelector('.filen'); if(!fe) return;
    const sid=sec.id.replace('s','');
    if(UNNUMBERED.has(sid)){ fe.textContent='§—'; sec.classList.add('unnum'); }
    else { n++; fe.textContent='§'+n; sec.classList.remove('unnum'); }
  });
}
function persistUnnumbered(){
  const arr=[...UNNUMBERED];
  try{ localStorage.setItem('__PAL_NS__-unnumbered', JSON.stringify(arr)); }catch(e){}
  if(!HTTP){ secStatus('unnumbered saved in browser (offline — run “pal serve” to persist)'); return; }
  fetch('/unnumbered',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({unnumbered:arr})})
    .then(r=>r.json()).then(j=>secStatus(j.ok?('unnumbered saved · '+j.count+(j.committed?(' · '+j.commit):'')):('save failed: '+j.error)))
    .catch(()=>secStatus('unnumbered save failed'));
}
function initUnnumbered(){
  secs.forEach(sec=>{
    const hd=sec.querySelector('.sechd'); if(!hd) return;
    const sid=sec.id.replace('s','');
    const b=document.createElement('button'); b.className='numbtn'+(UNNUMBERED.has(sid)?' on':'');
    b.textContent='№'; b.title='don’t number this section (prints without a § number)';
    b.addEventListener('click',()=>{
      if(UNNUMBERED.has(sid)){ UNNUMBERED.delete(sid); b.classList.remove('on'); }
      else { UNNUMBERED.add(sid); b.classList.add('on'); }
      renumber(); persistUnnumbered();
    });
    hd.appendChild(b);
  });
  renumber();
}

// ---- inline "Part ▾" picker: move a section to the end of a chosen part ----
// A section's part is positional (which divider precedes it). "Move to Part X" =
// relocate the section just before the NEXT divider after X (end of X's range), then
// reuse the existing reorder path (renumber + persistOrder). No reload, no new endpoint.
function moveToPart(sid, target){          // target = divider id, or '' for front matter
  const sec=document.getElementById('s'+sid); if(!sec) return;
  const parent=sec.parentNode;
  const idx = target==='' ? -1 : DIVIDERS.findIndex(d=>d.id===target);
  let nextDiv=null;                        // first existing divider AFTER the target
  for(let k=idx+1;k<DIVIDERS.length;k++){
    const el=document.getElementById('s'+DIVIDERS[k].id);
    if(el){ nextDiv=el; break; }
  }
  if(nextDiv) parent.insertBefore(sec, nextDiv);   // end of the target part's range
  else parent.appendChild(sec);                    // Part IV / no later divider -> end
  renumber(); persistOrder();
  const label = target==='' ? 'front matter' : (DIVIDERS[idx].title.split(':')[0]);
  secStatus('moved §'+sid+' → '+label+' · rebuilding…');
}
function initPartPicker(){
  document.querySelectorAll('.partsel').forEach(sel=>{
    sel.addEventListener('change',()=>moveToPart(sel.dataset.sec, sel.value));
  });
}

function initSectionsUI(){ initLabels(); initReorder(); initParts(); initUnnumbered(); initPartPicker(); mountSecbar(); initShelf(); }
if(document.readyState==='loading'){ addEventListener('DOMContentLoaded', initSectionsUI); } else { initSectionsUI(); }
"""
EDIT_JS = EDIT_JS.replace("__PALETTE__", json.dumps(list(config.PALETTE)))

SUBTITLE_HTML = f" <span>— {config.SUBTITLE_HTML}</span>" if config.SUBTITLE else ""

HTML = f"""{page_head(f"{config.TITLE} — Color-coded Reading Copy")}
<style>
/* topbar/brand styles are shared in style.css */
.filterbar{{background:var(--bar);
  border-bottom:1px solid var(--line);padding:12px 0;margin:0 -60px 18px;padding-left:60px;padding-right:60px;
  display:flex;flex-wrap:wrap;gap:6px;align-items:center}}
.chip{{font:13px Georgia,serif;cursor:pointer;border:1px solid var(--line);background:var(--field);
  border-radius:18px;padding:4px 11px;color:var(--soft);display:inline-flex;align-items:center;gap:6px}}
.chip .dot{{width:9px;height:9px;border-radius:50%}}
.chip .ct{{font-size:11px;opacity:.6}}
.chip.active{{border-color:var(--c,var(--gold));color:var(--ink);box-shadow:0 0 0 1px var(--c,var(--gold)) inset}}
.allbtn{{font-style:italic}}
.sec{{border-left:5px solid;padding:4px 18px 12px;margin:14px 0;background:var(--card);border-radius:0 8px 8px 0}}
.partbreak{{margin:40px -20px 26px;padding:18px 20px;text-align:center;
  border-top:2px solid var(--gold);border-bottom:2px solid var(--gold);background:var(--bg2)}}
.partbreak .pt{{display:block;font:600 22px Georgia,serif;color:var(--ink);letter-spacing:.01em}}
.partbreak .ps{{display:block;margin-top:3px;font:italic 14px Georgia,serif;color:var(--soft)}}
.partbtn{{font-size:13px;border:1px dashed var(--line);border-radius:12px;padding:0 8px;line-height:18px;
  background:var(--field);color:var(--soft);cursor:pointer;margin-left:2px}}
.partbtn:hover{{border-color:var(--gold);color:var(--gold)}}
.partbtn.on{{border-style:solid;border-color:var(--gold);color:var(--gold);background:var(--hilite)}}
.numbtn{{font-size:13px;border:1px dashed var(--line);border-radius:12px;padding:0 8px;line-height:18px;
  background:var(--field);color:var(--soft);cursor:pointer;margin-left:2px}}
.numbtn:hover{{border-color:var(--gold);color:var(--gold)}}
.numbtn.on{{border-style:solid;border-color:var(--soft);color:var(--soft);background:var(--bg2);text-decoration:line-through}}
.sec.unnum .filen{{opacity:.45;font-style:italic;font-weight:normal}}
.sec.unnum{{border-left-style:dotted}}
.body .fence{{opacity:.4;font-family:Menlo,monospace;font-size:.82em;color:var(--soft)}}
.partsel{{margin-left:auto;font:12px Georgia,serif;color:var(--soft);border:1px solid var(--line);
  border-radius:12px;padding:1px 6px;background:var(--field);cursor:pointer}}
.partsel:hover{{border-color:var(--gold);color:var(--gold)}}
.partbadge{{margin-left:auto;font:600 12px Georgia,serif;color:var(--gold);border:1px solid var(--gold);
  border-radius:12px;padding:1px 9px;background:var(--hilite)}}
.shelf{{margin:0 -20px 18px;padding:12px 20px 14px;background:var(--bg2);border:1px solid var(--line);
  border-radius:8px}}
.shelf .shelfhd{{font:600 14px Georgia,serif;color:var(--ink);margin-bottom:8px}}
.shelf .shelfct{{display:inline-block;min-width:18px;text-align:center;background:var(--soft);color:var(--on-accent);
  border-radius:9px;font-size:12px;padding:0 6px;margin:0 4px}}
.shelf .shelfhint{{font:italic 12px Georgia,serif;color:var(--soft);font-weight:normal}}
.shelfbody{{display:flex;flex-wrap:wrap;gap:8px}}
.shelfcard{{flex:1 1 260px;max-width:420px;background:var(--card);border:1px solid var(--line);
  border-left:4px solid var(--soft);border-radius:6px;padding:6px 10px;cursor:grab}}
.shelfcard .schd{{display:flex;align-items:center;gap:6px;margin-bottom:3px}}
.shelfcard .scgrip{{color:var(--soft);opacity:.4}}
.shelfcard .sprn{{font-size:12px;color:var(--soft)}}
.shelfcard .scbtn{{margin-left:auto;font:12px Georgia,serif;border:1px solid var(--line);background:var(--field);
  border-radius:10px;padding:1px 8px;cursor:pointer;color:var(--soft)}}
.shelfcard .scbtn+.scbtn{{margin-left:4px}}
.shelfcard .scbtn:hover{{border-color:var(--gold);color:var(--gold)}}
.shelfcard .scprev{{font:14px/1.4 Georgia,serif;color:var(--soft);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.shelfcard .scfull{{font:14px/1.6 Georgia,serif;color:var(--ink2);margin-top:6px;max-height:320px;overflow:auto;
  padding:8px;background:var(--field);border:1px solid var(--line);border-radius:5px}}
.parkbtn{{color:var(--soft)}}
.placehere{{display:none}}
body.placing .placehere{{display:block;width:100%;margin:6px 0;font:12px Georgia,serif;
  border:1px dashed var(--gold);background:var(--hilite);color:var(--gold);border-radius:12px;padding:3px 0;cursor:pointer}}
body.placing .placehere:hover{{background:var(--gold);color:var(--on-accent)}}
body.placing .sec.dragover{{box-shadow:0 -3px 0 var(--gold)}}
.sechd{{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:8px 0 6px}}
.filen{{font-weight:bold;font-size:15px;color:var(--ink)}}
.prn{{font-size:12px;color:var(--soft);margin-right:8px}}
.fid{{font-size:10px;color:var(--soft);opacity:.55;margin-right:8px;font-variant-numeric:tabular-nums}}
.fid::before{{content:"·"}}
.mchip{{font-size:11px;border:1px solid;border-radius:12px;padding:1px 8px}}
.body{{font-size:15.5px;line-height:1.6;color:var(--ink2);white-space:normal}}
.sec.dim{{opacity:.12;filter:grayscale(.6)}}
.sec.collapsed,.partbreak.collapsed{{display:none}}
.counter{{font-size:12.5px;color:var(--soft);margin-left:auto}}
.search{{font:13.5px Georgia,serif;border:1px solid var(--gold);border-radius:18px;padding:5px 14px;
  min-width:230px;background:var(--field);color:var(--ink)}}
mark{{background:var(--mark-bg);color:var(--ink);padding:0 1px;border-radius:2px}}
.ed{{margin-top:8px;font-size:12px;color:var(--soft)}}
.edbtn,.rvbtn{{font:12px Georgia,serif;border:1px solid var(--line);background:var(--field);border-radius:12px;
  padding:2px 11px;cursor:pointer;color:var(--soft)}}
.edbtn:hover,.rvbtn:hover{{border-color:var(--gold);color:var(--gold)}}
.body.editing{{outline:2px solid var(--gold);outline-offset:5px;border-radius:4px;background:var(--card)}}
.edstatus{{margin-left:8px;font-style:italic}}
#modebar{{margin:0 0 10px}}
#recbar{{position:fixed;right:12px;bottom:12px;z-index:50;display:flex;align-items:center;gap:8px;
  background:var(--card);border:1px solid var(--line);border-radius:16px;padding:5px 11px;
  font:12px Georgia,serif;color:var(--soft);box-shadow:0 2px 10px #0000001a}}
#recbar .rdot{{width:9px;height:9px;border-radius:50%;background:var(--red);
  animation:rpulse 2s infinite}}
@keyframes rpulse{{0%{{box-shadow:0 0 0 0 color-mix(in srgb,var(--red) 40%,transparent)}}70%{{box-shadow:0 0 0 6px color-mix(in srgb,var(--red) 0%,transparent)}}100%{{box-shadow:0 0 0 0 color-mix(in srgb,var(--red) 0%,transparent)}}}}
#recbar .rlab{{letter-spacing:.5px;text-transform:uppercase;font-size:11px}}
#recbar .rtog{{cursor:pointer;display:inline-flex;align-items:center;gap:3px}}
#recbar canvas{{background:var(--field);border:1px solid var(--line);border-radius:4px}}
#recbar a{{color:var(--gold);text-decoration:none}}
.drag{{cursor:grab;color:var(--soft);opacity:.35;user-select:none;margin-right:4px;font-size:14px}}
.drag:hover{{opacity:.9;color:var(--gold)}}
.sec.dragging{{opacity:.45}}
.sec.dragover{{box-shadow:0 -3px 0 var(--gold)}}
.labwrap{{display:inline-flex;flex-wrap:wrap;gap:4px;align-items:center;margin-left:6px}}
.labwrap .addlbl{{font-size:12px;border:1px dashed var(--line);border-radius:12px;padding:0 8px;
  cursor:pointer;color:var(--soft);background:transparent}}
.labwrap .addlbl:hover{{border-color:var(--gold);color:var(--gold)}}
.labwrap input.lin{{font:12px Georgia,serif;border:1px solid var(--gold);border-radius:12px;
  padding:1px 8px;width:120px;background:var(--field);color:var(--ink)}}
.lchip{{cursor:pointer}}
.lchip:hover{{filter:brightness(.94)}}
.lchip .x{{cursor:pointer;margin-left:5px;opacity:.5;font-weight:bold;font-style:normal}}
.lchip .x:hover{{opacity:1;color:var(--red)}}
.chip.lfilter{{font-style:italic}}
.chipsep{{display:inline-block;width:1px;height:20px;background:var(--line);margin:0 4px}}
.delbtn{{font:12px Georgia,serif;border:1px solid var(--line);background:var(--field);border-radius:12px;
  padding:2px 10px;cursor:pointer;color:var(--soft);margin-left:8px}}
.delbtn:hover,.delbtn[data-arm="1"]{{border-color:var(--red);color:var(--red)}}
.insbtn:hover{{border-color:var(--gold);color:var(--gold)}}
#secbar{{position:fixed;left:12px;bottom:12px;z-index:50;display:flex;align-items:center;gap:8px;
  background:var(--card);border:1px solid var(--line);border-radius:16px;padding:5px 11px;
  font:12px Georgia,serif;color:var(--soft);box-shadow:0 2px 10px #0000001a}}
#secbar button{{font:12px Georgia,serif;border:1px solid var(--line);background:var(--field);border-radius:12px;
  padding:2px 10px;cursor:pointer;color:var(--soft)}}
#secbar button:hover{{border-color:var(--gold);color:var(--gold)}}
#secbar button:disabled{{opacity:.4;cursor:not-allowed;border-color:var(--line);color:var(--soft)}}
#secbar .st{{font-style:italic;max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.histbtn:hover{{border-color:var(--gold);color:var(--gold)}}
.histpanel{{margin-top:8px;border:1px solid var(--line);border-radius:8px;background:var(--card);
  padding:8px 12px;font-size:12.5px;color:var(--soft)}}
.histpanel .hrow{{display:flex;align-items:center;gap:8px;padding:3px 0;border-bottom:1px solid var(--line)}}
.histpanel .hrow:last-child{{border-bottom:none}}
.histpanel .htime{{font-variant-numeric:tabular-nums;color:var(--ink);min-width:96px}}
.histpanel .hsub{{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;opacity:.7}}
.histpanel .hbtn{{font:12px Georgia,serif;border:1px solid var(--line);background:var(--field);border-radius:10px;
  padding:1px 9px;cursor:pointer;color:var(--soft)}}
.histpanel .hbtn:hover,.histpanel .hbtn[data-arm="1"]{{border-color:var(--gold);color:var(--gold)}}
.histpanel .hview{{margin-top:8px;padding:10px;background:var(--field);border:1px solid var(--line);border-radius:6px;
  white-space:pre-wrap;font:13px/1.5 Georgia,serif;color:var(--ink2);max-height:280px;overflow:auto}}
</style></head><body><div class="wrap">
{topbar_html("reading-copy.html")}
<header><div class="kicker">Reading Copy</div>
<h1>{config.TITLE_HTML}{SUBTITLE_HTML}</h1>
</header>
<div class="filterbar"><input id="q" class="search" type="search" placeholder="search the text — any word, motif, or label…" autocomplete="off">{"".join(chips)}<span class="counter" id="counter"></span></div>
<p id="modebar" class="note"></p>
{shelf_html}
{"".join(blocks)}
<footer>{len(files)} sections · filter is client-side, no data leaves your machine</footer>
</div>
<script>
const secs=[...document.querySelectorAll('.sec')];
const PARTS={parts_js};
const DIVIDERS={dividers_js};
const UNNUMBERED=new Set({unnum_js});
const chips=[...document.querySelectorAll('.chip')];
const counter=document.getElementById('counter');
function apply(m){{
  clearCollapse();
  let n=0;
  secs.forEach(s=>{{
    const has = m==='all' || s.classList.contains(m);
    s.classList.toggle('dim', !has);
    if(has && m!=='all') n++;
  }});
  chips.forEach(c=>c.classList.toggle('active', c.dataset.m===m));
  counter.textContent = m==='all' ? '' : n+' sections';
}}
chips.forEach(c=>c.addEventListener('click',()=>{{
  q.value='';clearMarks();
  if(c.dataset.l!==undefined) applyLabel(c.dataset.l);
  else apply(c.dataset.m);
}}));
const q=document.getElementById('q');
const bodies=secs.map(s=>s.querySelector('.body'));
function clearMarks(){{bodies.forEach(b=>{{if(b.dataset.orig!==undefined){{b.innerHTML=b.dataset.orig;delete b.dataset.orig;}}}});}}
function esc(s){{return s.replace(/[.*+?^${{}}()|[\\]\\\\]/g,'\\\\$&');}}
function search(){{
  clearCollapse();
  const term=q.value.trim();
  if(!term){{clearMarks();apply('all');return;}}
  chips.forEach(c=>c.classList.remove('active'));
  const rx=new RegExp(esc(term),'ig'); let n=0;
  secs.forEach((s,i)=>{{
    const b=bodies[i]; if(b.dataset.orig!==undefined) b.innerHTML=b.dataset.orig;
    const txt=b.textContent; const hit=rx.test(txt); rx.lastIndex=0;
    s.classList.toggle('dim', !hit);
    if(hit){{n++; b.dataset.orig=b.innerHTML; b.innerHTML=b.innerHTML.replace(rx,m=>'<mark>'+m+'</mark>');}}
  }});
  counter.textContent = n+" sections match “"+term+"”";
}}
q.addEventListener('input', search);
apply('all');
{EDIT_JS}
</script>
<script src="pal.js"></script>
</body></html>"""

with open("reading-copy.html", "w", encoding="utf-8") as fh:
    # per-book localStorage namespace: two books never share labels/drafts
    fh.write(HTML.replace("__PAL_NS__", config.SAFE_SLUG))
print(f"wrote reading-copy.html · {len(files)} sections · {len(sec_motifs)} tagged")
