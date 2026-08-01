/* Palimpsest — shared top-bar behavior.
 *   • theme toggle (paper ⇄ vapor) — works offline, remembered per book
 *   • dropdown menus (Read / Maps nav + Export) — open/close, one at a time
 *   • Export formats + Rebuild actions — these need the edit/save server, so
 *     they appear only when the page is viewed through `pal serve` (http://…).
 * Self-contained, no dependencies; every dossier page includes it once. */
(function () {
  // ---- theme: one attribute on <html>, stored per book ----------------------
  // The stored value was already applied in <head> (nav.THEME_BOOT) so the page
  // never flashes the wrong look; this only wires the button and keeps the label
  // honest. Namespaced by book slug — two books open in one browser don't share.
  var ROOT = document.documentElement;
  var TKEY = 'pal:' + (ROOT.dataset.ns || 'book') + ':theme';

  function paintToggle(t) {
    var b = document.querySelector('[data-pal="theme"]');
    if (!b) return;
    b.setAttribute('aria-pressed', t === 'vapor' ? 'true' : 'false');
    var l = b.querySelector('.tl'), g = b.querySelector('.tg');
    // the button says what you are IN, and its glyph leans the way it will go
    if (l) l.textContent = (t === 'vapor' ? 'Vapor' : 'Paper');
    if (g) g.textContent = (t === 'vapor' ? '◑' : '◐');
    b.title = (t === 'vapor' ? 'switch to paper — the quiet look'
                             : 'switch to vapor — the neon look');
  }

  // A <canvas> cannot inherit CSS, so anything drawn with a 2D context has to read
  // the tokens itself and redraw when the theme flips. Two canvases need this: the
  // reading copy's typing sparkline and the writing record's cadence strip.
  var themeHooks = [];
  window.palTheme = {
    ink: function (token, fallback) {
      var v = getComputedStyle(ROOT).getPropertyValue(token).trim();
      return v || fallback || '#000';
    },
    // register a redraw; it runs now and on every theme change
    onChange: function (fn) {
      themeHooks.push(fn);
      try { fn(); } catch (e) {}
    }
  };

  function setTheme(t) {
    ROOT.dataset.theme = t;
    try { localStorage.setItem(TKEY, t); } catch (e) {}   // private mode: still switches
    paintToggle(t);
    themeHooks.forEach(function (fn) { try { fn(); } catch (e) {} });
  }

  paintToggle(ROOT.dataset.theme === 'paper' ? 'paper' : 'vapor');
  var themeBtn = document.querySelector('[data-pal="theme"]');
  if (themeBtn) themeBtn.addEventListener('click', function (e) {
    e.stopPropagation();
    setTheme(ROOT.dataset.theme === 'vapor' ? 'paper' : 'vapor');
  });

  // ---- P·A·L·I·M·P·S·E·S·T ---------------------------------------------------
  // CSS can't put a glyph BETWEEN characters, so the characters get wrapped here
  // and CSS supplies the dot (.dt::after, gated on the theme). Three things fall
  // out of doing it that way rather than baking '·' into the text:
  //   · switching themes is one attribute flip — no DOM work, no drift
  //   · the accessible name and what you copy stay the original string
  //   · a book title containing < & or " cannot inject anything, because every
  //     character moves through textContent and never through innerHTML
  // Runs once at load whatever the theme, so the spans are simply inert in paper.
  function dotifyLead(el) {
    if (!el || el.dataset.dotted) return;
    var node = el.firstChild;                    // only the LEADING text run:
    if (!node || node.nodeType !== 3) return;    // an h1's "— register" tail is a
    var text = node.nodeValue;                   // <span> and is left alone
    if (!text || !text.trim()) return;
    el.dataset.dotted = '1';
    var frag = document.createDocumentFragment();
    text.split(/(\s+)/).forEach(function (run) {
      if (!run) return;
      if (/^\s+$/.test(run)) { frag.appendChild(document.createTextNode(run)); return; }
      var chars = Array.from(run);               // astral-safe: accents, emoji
      chars.forEach(function (ch, i) {
        var s = document.createElement('span');
        s.className = 'dt' + (i === chars.length - 1 ? ' last' : '');
        s.textContent = ch;
        frag.appendChild(s);
      });
    });
    el.replaceChild(frag, node);
  }
  dotifyLead(document.querySelector('.topbar .brand'));
  dotifyLead(document.querySelector('header h1'));

  // ---- dropdowns: nav menus + the Export menu. Work with or without a server. ----
  var poppers = [];
  document.querySelectorAll('.navdrop').forEach(function (dd) {
    var b = dd.querySelector('.navdrop-btn'), m = dd.querySelector('.navdrop-menu');
    if (b && m) poppers.push({ btn: b, menu: m });
  });
  var acts = document.querySelector('.topacts');
  var exp = acts && acts.querySelector('.palexport');
  if (exp) {
    var eb = exp.querySelector('[data-pal="export-menu"]'), em = exp.querySelector('.palmenu');
    if (eb && em) poppers.push({ btn: eb, menu: em });
  }

  function closeAll(except) {
    poppers.forEach(function (p) {
      if (p !== except) { p.menu.hidden = true; if (p.btn) p.btn.setAttribute('aria-expanded', 'false'); }
    });
  }
  poppers.forEach(function (p) {
    p.btn.addEventListener('click', function (e) {
      e.stopPropagation();
      var willOpen = p.menu.hidden;
      closeAll();
      if (willOpen) { p.menu.hidden = false; p.btn.setAttribute('aria-expanded', 'true'); }
    });
  });
  document.addEventListener('click', function () { closeAll(); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeAll(); });

  // ---- top-bar actions (Export formats, Rebuild) — need the server ----
  if (!acts) return;
  var HTTP = location.protocol.indexOf('http') === 0;
  if (!HTTP) { acts.hidden = true; return; }
  acts.hidden = false;

  var msg = acts.querySelector('.palmsg');
  function say(t) { if (msg) msg.textContent = t || ''; }
  var rebuildBtn = acts.querySelector('[data-pal="rebuild"]');
  var items = acts.querySelectorAll('.palitem');

  // Gate formats by installed tools: PDF needs pandoc+xelatex, Word needs pandoc.
  fetch('/books').then(function (r) { return r.json(); }).then(function (d) {
    if (!d || !d.ok) return;
    items.forEach(function (it) {
      var f = it.getAttribute('data-fmt');
      if (f === 'pdf' && !d.pdf) { it.disabled = true; it.title = 'install pandoc + XeLaTeX to enable PDF'; }
      if (f === 'docx' && !d.pandoc) { it.disabled = true; it.title = 'install pandoc to enable Word export'; }
    });
  }).catch(function () {});

  items.forEach(function (it) {
    it.addEventListener('click', function (e) {
      e.stopPropagation();
      closeAll();
      if (it.disabled) return;
      exportAs(it.getAttribute('data-fmt'), it.textContent.trim());
    });
  });

  function exportAs(fmt, label) {
    say('preparing ' + label + '…');
    fetch('/export', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                       body: JSON.stringify({ format: fmt }) })
      .then(function (r) {
        if (!r.ok) return r.json().then(function (j) { throw new Error(j.error || ('HTTP ' + r.status)); });
        var cd = r.headers.get('Content-Disposition') || '';
        var m = cd.match(/filename="([^"]+)"/);
        return r.blob().then(function (blob) { return { blob: blob, name: m ? m[1] : ('book.' + fmt) }; });
      })
      .then(function (o) {
        var a = document.createElement('a');
        a.href = URL.createObjectURL(o.blob); a.download = o.name;
        document.body.appendChild(a); a.click();
        setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
        say(label + ' downloaded');
        setTimeout(function () { say(''); }, 4000);
      })
      .catch(function (e) { say(label + ' failed: ' + e.message); });
  }

  if (rebuildBtn) rebuildBtn.addEventListener('click', function () {
    rebuildBtn.disabled = true; say('rebuilding…');
    fetch('/rebuild', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (!j.ok) throw new Error(j.error || 'rebuild failed');
        say('rebuilt — reloading'); location.reload();
      })
      .catch(function (e) { say('rebuild failed: ' + e.message); rebuildBtn.disabled = false; });
  });
})();
