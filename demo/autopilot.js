/* Palimpsest — writing-record DEMO autopilot.
 *
 * The demo page IS writing-record.html: same markup, same synth, same score.
 * This file only *drives* it — it loads the session baked into the page, then
 * plays the controls the way a person would: turning the knobs, changing the
 * scale and the key, swapping the instrument, mapping the vowels to a chord.
 * Nothing here reimplements the page. Every change is made by setting the real
 * control and dispatching the event its own listener already handles, so the
 * notation, the sound and the CONFIG editor all stay in step. */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };

  // ---------------------------------------------------------------- the score
  // Cues are placed by fraction of the piece, so they land in the same musical
  // spot whatever the tempo is. `run` fires once when the playhead crosses `at`.
  var CUES = [
    { at: 0.00, say: 'One note per keystroke — pentatonic, in C. The staff below is the same data the synth is playing.' },
    { at: 0.05, say: 'Opening the tone dial: the filter lets the top of each note through.',
      run: function () { tween('tone', 6400, 4200); } },
    { at: 0.11, say: 'A little vibrato — the wavy marks under the noteheads are the depth.',
      run: function () { tween('vib', 11, 3000); } },
    { at: 0.18, say: 'Changing the scale to dorian. The whole staff re-pitches; nothing is re-recorded.',
      run: function () { set('mscale', 'dorian', 'change'); } },
    { at: 0.25, say: 'Instrument → bell, and chorus up: each note gets a detuned ghost beside it.',
      run: function () { set('minst', 'bell', 'change'); tween('chorus', 0.62, 2600); } },
    { at: 0.33, say: 'Moving the key to G and holding a tonic drone under the writing.',
      run: function () { set('mroot', 'G3', 'change'); set('mdrone', 'tonic', 'change'); } },
    { at: 0.41, say: 'Pushing the tempo. Score mode quantises the typing onto a grid, so bpm re-times the piece.',
      run: function () { tween('bpm', 132, 2800); } },
    { at: 0.49, say: 'Harmony as maj7 — the chord stack appears on the staff as it appears in the sound.',
      run: function () { set('mchord', 'maj7', 'change'); set('mharm', true, 'change'); } },
    { at: 0.57, say: 'Mapping the vowels: a e i o u now sound a chord of their own. Diamond noteheads mark them.',
      run: function () { mapVowels(); } },
    { at: 0.65, say: 'Up an octave, and more body — the sub dial thickens the line under each note.',
      run: function () { $('octup').click(); tween('body', 0.85, 2400); } },
    { at: 0.73, say: 'A raga: raga yaman. Just-intoned degrees, so the staff spacing shifts with the tuning.',
      run: function () { set('mscale', 'raga yaman', 'change'); set('minst', 'reed', 'change'); } },
    { at: 0.81, say: 'Pad on, reverb up, long ring — the session blurs into one sustained thing.',
      run: function () { set('mpad', true, 'change'); tween('reverb', 0.72, 3000); tween('ring', 1.9, 3000); } },
    { at: 0.90, say: 'Back to warm, tone down, vibrato off. The last keystrokes land, then the save.',
      run: function () { set('minst', 'warm', 'change'); set('mpad', false, 'change');
                         tween('tone', 1800, 3400); tween('vib', 0, 2400); tween('bpm', 96, 3400); } },
    { at: 0.985, say: 'That was 92 seconds of writing — 245 keystrokes, three lines kept — played back as a piece.' }
  ];

  // Where every run starts. Applied on load and again on each loop, so the demo
  // is the same performance every time.
  var BASE = {
    speed: '1', gain: '0.55', sonify: true, drones: true,
    mmode: 'score', mscale: 'pentatonic', mroot: 'C3', mbpm: '96',
    minst: 'warm', mrev: '0.35', msus: '0.7', mharm: true, mpad: false,
    mdrone: 'off', mchord: 'triad', scfollow: true
  };

  // --------------------------------------------------------- driving controls
  // A dispatched event is `isTrusted:false`, which is also how we tell our own
  // moves apart from the viewer's (see the takeover listener at the bottom).
  function set(id, value, evt) {
    var el = $(id); if (!el) return;
    if (el.type === 'checkbox') el.checked = !!value; else el.value = value;
    el.dispatchEvent(new Event(evt || 'input', { bubbles: true }));
  }

  // Knobs are <span>s, not form controls: makeKnob() draws the dot from set()
  // and the page listens for a bubbling 'input' to re-sync the notation — the
  // same pair of moves a real drag makes.
  // A tween moves 60 times a second; the page re-notates and re-serialises CONFIG
  // on every event it hears, so emit at ~12fps and always on the final value.
  var lastEmit = {};
  function due(id, force) {
    var now = performance.now();
    if (!force && now - (lastEmit[id] || 0) < 80) return false;
    lastEmit[id] = now; return true;
  }
  function knob(elId, key, v, force) {
    var K = (typeof KNOBS !== 'undefined') && KNOBS[key];
    if (K) K.set(v);                                    // the dot follows every frame
    if (!due(elId, force)) return;
    var el = $(elId); if (el) el.dispatchEvent(new Event('input', { bubbles: true }));
  }
  function slider(id, v, force, digits) {
    if (!due(id, force)) return;
    set(id, digits == null ? Math.round(v) : v.toFixed(digits));
  }
  function bus() { return (typeof AC !== 'undefined' && AC && AC._bus) ? AC._bus : null; }
  function fx() { return (CONFIG.music.fx = CONFIG.music.fx || {}); }

  // Every tweenable parameter: where it reads from, and how it is applied.
  var PARAM = {
    tone:   { get: function () { return fx().tone || 2600; },
              set: function (v, f) { fx().tone = v; if (bus()) bus().tone.frequency.value = v; knob('ktone', 'tone', v, f); } },
    vib:    { get: function () { return (CONFIG.music.vibrato || {}).depth || 0; },
              set: function (v, f) { (CONFIG.music.vibrato = CONFIG.music.vibrato || {}).depth = v; knob('kvib', 'vib', v, f); } },
    chorus: { get: function () { return CONFIG.music.chorus || 0; },
              set: function (v, f) { CONFIG.music.chorus = v; knob('kchor', 'chor', v, f); } },
    body:   { get: function () { return CONFIG.music.sub || 0; },
              set: function (v, f) { CONFIG.music.sub = v; knob('ksub', 'sub', v, f); } },
    reverb: { get: function () { return +$('mrev').value; }, set: function (v, f) { slider('mrev', v, f, 2); } },
    ring:   { get: function () { return +$('msus').value; }, set: function (v, f) { slider('msus', v, f, 2); } },
    bpm:    { get: function () { return +$('mbpm').value; }, set: function (v, f) { slider('mbpm', v, f); } }
  };

  var TW = [];                       // active tweens
  function tween(name, to, ms) {
    var p = PARAM[name]; if (!p) return;
    TW = TW.filter(function (t) { return t.name !== name; });
    TW.push({ name: name, p: p, from: p.get(), to: to, t0: performance.now(), ms: ms || 2000 });
  }
  function stepTweens(now) {
    TW = TW.filter(function (t) {
      var f = Math.min(1, (now - t.t0) / t.ms);
      var e = f < 0.5 ? 2 * f * f : 1 - Math.pow(-2 * f + 2, 2) / 2;   // ease in-out
      t.p.set(t.from + (t.to - t.from) * e, f >= 1);
      return f < 1;
    });
  }

  function mapVowels() {
    'aeiou'.split('').forEach(function (c) { setLetter(c, '', 'maj7'); });
    renderLetterMap();
  }

  // ------------------------------------------------------------- the demo bar
  var bar = document.createElement('div');
  bar.className = 'demobar';
  bar.innerHTML =
    '<button id="demo-play" title="pause / resume">⏸</button>' +
    '<button id="demo-restart" title="start again">⟲</button>' +
    '<label><input type="checkbox" id="demo-auto" checked> autopilot</label>' +
    '<label><input type="checkbox" id="demo-loop" checked> loop</label>' +
    '<span id="demo-say"></span>' +
    '<span id="demo-prog">0:00</span>';
  document.body.appendChild(bar);

  var splash = document.createElement('div');
  splash.className = 'demosplash';
  splash.innerHTML =
    '<div class="card">' +
    '<div class="kicker">Palimpsest · demo</div>' +
    '<h2>A writing session, played back as music</h2>' +
    '<p>Ninety-two seconds of typing — every keystroke, pause and deletion — replayed on the ' +
    'writing-record page: the prose retyping itself, the same events drawn as notation, and the ' +
    'synth reading that notation. The demo turns the dials for you.</p>' +
    '<button id="demo-start">▶ Play the session</button>' +
    '<p class="fine">Sound on. Nothing is uploaded — the session is baked into this page.</p>' +
    '</div>';
  document.body.appendChild(splash);

  function say(t) {
    var s = $('demo-say');
    s.style.opacity = 0;
    setTimeout(function () { s.textContent = t; s.style.opacity = 1; }, 160);
  }
  function fmt(ms) {
    var s = Math.max(0, Math.round(ms / 1000));
    return Math.floor(s / 60) + ':' + ('0' + (s % 60)).slice(-2);
  }

  // ------------------------------------------------------------------ running
  var fired = [], auto = true, ended = false;

  function applyBase() {
    Object.keys(BASE).forEach(function (id) {
      var el = $(id); if (!el) return;
      set(id, BASE[id], el.tagName === 'SELECT' || el.type === 'checkbox' ? 'change' : 'input');
    });
    CONFIG.music.letterMap = {}; renderLetterMap();
    while ((CONFIG.music.transpose || 0) > 0) $('octdn').click();
    while ((CONFIG.music.transpose || 0) < 0) $('octup').click();
    PARAM.tone.set(2600, true); PARAM.vib.set(0, true);
    PARAM.chorus.set(0.25, true); PARAM.body.set(0.45, true);
    TW = [];
  }

  function restart() {
    fired = []; ended = false;
    applyBase();
    $('rewind').click();
    $('play').click();
    $('demo-play').textContent = '⏸';
  }

  function frame() {
    requestAnimationFrame(frame);
    var now = performance.now();
    stepTweens(now);
    if (typeof RP === 'undefined' || !RP) return;

    var vt = curVt(), frac = vt / RP.total;
    $('demo-prog').textContent = fmt(vt) + ' / ' + fmt(RP.total);

    if (auto) {
      CUES.forEach(function (c, i) {
        if (fired[i] || frac < c.at) return;
        fired[i] = 1;
        if (c.say) say(c.say);
        if (c.run) try { c.run(); } catch (e) {}
      });
    }
    if (!RP.playing && frac >= 0.999 && !ended) {
      ended = true;
      $('demo-play').textContent = '▶';
      if ($('demo-loop').checked) setTimeout(function () { if ($('demo-loop').checked) restart(); }, 2600);
    }
  }

  // ----------------------------------------------------------------- controls
  $('demo-play').addEventListener('click', function () {
    if (!RP) return;
    if (RP.playing) { $('play').click(); this.textContent = '▶'; }
    else { if (curVt() >= RP.total) restart(); else { $('play').click(); this.textContent = '⏸'; } }
  });
  $('demo-restart').addEventListener('click', restart);
  $('demo-auto').addEventListener('change', function () {
    auto = this.checked;
    say(auto ? 'Autopilot on — the demo drives the controls again.'
             : 'Autopilot off — the controls are yours. Everything above is live.');
  });

  // The viewer touching anything in the replay panel takes the wheel. Our own
  // moves are dispatched events (isTrusted:false), so they never trip this.
  ['pointerdown', 'input', 'change'].forEach(function (ev) {
    document.querySelector('.replay').addEventListener(ev, function (e) {
      if (!e.isTrusted || !auto) return;
      $('demo-auto').checked = false;
      $('demo-auto').dispatchEvent(new Event('change', { bubbles: true }));
    }, true);
  });

  // -------------------------------------------------------------------- start
  function parse(text) {
    var out = [];
    text.split('\n').forEach(function (l) {
      l = l.trim(); if (!l) return;
      try { out.push(JSON.parse(l)); } catch (e) {}
    });
    return out;
  }
  var events = parse(($('demo-session') || {}).textContent || '');
  var session = (document.body.dataset.demoSession || 'demo');

  ingest(events, { session: session, source: 'demo' }).then(function () {
    applyBase();
    say(CUES[0].say);
    $('demo-start').addEventListener('click', function () {
      splash.classList.add('gone');
      setTimeout(function () { splash.remove(); }, 400);
      document.querySelector('.scorewrap').scrollIntoView({ behavior: 'smooth', block: 'center' });
      restart();
    });
    requestAnimationFrame(frame);
  });
})();
