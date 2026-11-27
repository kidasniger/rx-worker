"""Scripts JavaScript injectés dans la page.

Comprend les ponts de rendu (seek, capture audio) et les primitives motion
design MD.* des vidéos gsapvideo : heroWord, accent, popIn, outSlide/outMask,
transitions (rideau, iris, vague, flood, fondu2), compteurs, jauges, grain.
"""



JS_HELPERS = r"""
window.__raf = () => new Promise(r => { let d = false; const f = () => { if (!d) { d = true; r(); } };
  requestAnimationFrame(f); setTimeout(f, 120); });

window.__prep = async () => {
  const faces = [...document.fonts].filter(f => f.unicodeRange === 'U+0-10FFFF' || /U\+0000/.test(f.unicodeRange));
  await Promise.all(faces.map(f => f.load().catch(() => 0)));
  const au = [...document.querySelectorAll('audio')];
  await Promise.all(au.map(a => a.readyState >= 1 ? 1 :
    new Promise(r => { a.addEventListener('loadedmetadata', r, {once: true}); setTimeout(r, 15000); })));
  return au.map(a => a.duration);
};

window.__finish = async () => {
  await document.fonts.ready;
  const imgs = [...document.images];
  if (imgs.length) await Promise.all(imgs.map(i => i.decode ? i.decode().catch(() => 0) : 0));
  await window.__raf();
};

window.__seek = async (t) => {
  if (window.__profile === 'rendraxai') {
    window.__manual = true;
    const time = Math.max(0, Number(t) || 0);
    await window.__rendraxSeek(time);
    await window.__finish();
    return 1;
  }
  if (window.__profile === 'gsapvideo') {
    window.__manual = true;
    const time = Math.max(0, Number(t) || 0);
    // Seek GSAP directly; do not depend on real-time requestAnimationFrame sampling.
    tl.time(time, false);
    // Scrub CSS keyframes (floating, spinning, pulsing, progress stripes) to the same timestamp.
    for (const animation of document.getAnimations()) {
      try { animation.pause(); animation.currentTime = time * 1000; } catch (e) {}
    }
    let caption = '', captionStart = 0;
    for (const cue of SUB) {
      if (time >= cue[0]) { captionStart = cue[0]; caption = cue[1]; }
      else break;
    }
    const subtitle = document.querySelector('#sb');
    if (subtitle) {
      subtitle.textContent = caption;
      if (caption) {
        const p = Math.min(1, Math.max(0, (time - captionStart) / 0.3));
        const eased = 1 - Math.pow(1 - p, 3);
        subtitle.style.opacity = '1';
        subtitle.style.transform = 'translateY(' + ((1 - eased) * 24) + 'px) scale(' + (0.96 + eased * 0.04) + ')';
      } else {
        subtitle.style.opacity = '0';
        subtitle.style.transform = 'translateY(0) scale(1)';
      }
    }
    const progress = document.querySelector('#pg');
    if (progress) {
      // Certaines vidéos GSAP fournissent T, d'autres seulement D.
      // Ne jamais référencer T directement : son absence ferait échouer tout le rendu.
      let total = 0;
      try {
        if (typeof T !== 'undefined' && T && T.length) total = Number(T[T.length - 1]);
        if ((!Number.isFinite(total) || total <= 0) && typeof D !== 'undefined') total = Number(D);
      } catch (e) {}
      if (!Number.isFinite(total) || total <= 0) {
        const audio = document.querySelector('#a');
        total = audio && Number.isFinite(audio.duration) && audio.duration > 0 ? audio.duration : 1;
      }
      progress.style.width = (Math.max(0, Math.min(1, time / total)) * 1080) + 'px';
    }
    const overlay = document.querySelector('#go');
    if (overlay) overlay.style.display = 'none';
    await window.__finish();
    return 1;
  }
  if (window.__profile === 'editpro') {
    if (!window.__ep) {
      window.__manual = true; window.__ep = true;
      run = true; vi = 0; subEnd = 0;
      const ui = document.querySelector('#ui'); if (ui) ui.style.display = 'none';
    }
    render(Math.max(0, t));
    await window.__finish();
    return 1;
  }
  if (window.__profile === 'musicpro') {
    window.__manual = true;
    try { run = 0; } catch (e) {}
    render(Math.max(0, t));
    await window.__finish();
    return 1;
  }
  if (window.__profile === 'voicevideo') {
    window.__manual = true;
    document.querySelectorAll('audio').forEach(a => { try { a.pause(); } catch (e) {} });
    if (window.ReactDOM && ReactDOM.flushSync) ReactDOM.flushSync(() => window.__video.seek(t));
    else { window.__video.seek(t); await window.__raf(); }
    await window.__finish();
    for (const b of document.querySelectorAll('#stage button'))
      if (/Touchez pour lancer|Rejouer/.test(b.textContent) && b.parentElement) b.parentElement.style.display = 'none';
    return 1;
  }
  if (window.__setT && window.ReactDOM && ReactDOM.flushSync) {
    window.__manual = true;
    ReactDOM.flushSync(() => window.__setT(t));
  } else {
    const au = document.querySelectorAll('audio');
    au.forEach(a => { a.currentTime = t; });
    await window.__raf();
    await new Promise(r => setTimeout(r, 40));
    await window.__raf();
  }
  await window.__finish();
  for (const d of document.querySelectorAll('.stage div'))
    if (!d.children.length && d.textContent.startsWith('Touchez pour lancer')) d.style.display = 'none';
  return 1;
};

window.__sfx = async () => {
  if (typeof SFX === 'undefined' || typeof EV === 'undefined') return '';
  const sr = 44100, L = Math.ceil((D + 1.5) * sr);
  const oc = new OfflineAudioContext(1, L, sr);
  let T = 0;
  Object.defineProperty(oc, 'currentTime', { get: () => T });
  const S2 = Object.create(SFX);
  S2.ac = oc; S2.m = oc.createGain(); S2.m.gain.value = .5; S2.m.connect(oc.destination);
  S2.nb = oc.createBuffer(1, sr, sr);
  const nd = S2.nb.getChannelData(0);
  for (let i = 0; i < sr; i++) nd[i] = Math.random() * 2 - 1;
  for (const [et, kind] of EV) { T = Math.max(0, et); S2.play(kind); }
  const buf = await oc.startRendering();
  const x = buf.getChannelData(0), pcm = new Int16Array(x.length);
  for (let i = 0; i < x.length; i++) { const v = Math.max(-1, Math.min(1, x[i])); pcm[i] = v < 0 ? v * 32768 : v * 32767; }
  const u8 = new Uint8Array(pcm.buffer);
  let bin = '';
  for (let i = 0; i < u8.length; i += 0x8000) bin += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000));
  return btoa(bin);
};

window.__wavOf = async (key) => {
  let buf = null;
  try { buf = await (key === 'voice' ? vP : mP); } catch (e) {}
  if (!buf || !buf.getChannelData) return '';
  const ch = Math.min(2, buf.numberOfChannels), n = buf.length, pcm = new Int16Array(n * ch);
  for (let c = 0; c < ch; c++) {
    const x = buf.getChannelData(c);
    for (let i = 0; i < n; i++) { const s = Math.max(-1, Math.min(1, x[i])); pcm[i * ch + c] = s < 0 ? s * 32768 : s * 32767; }
  }
  const u8 = new Uint8Array(pcm.buffer);
  let bin = '';
  for (let i = 0; i < u8.length; i += 0x8000) bin += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000));
  return buf.sampleRate + ':' + ch + ':' + btoa(bin);
};

/* ===== Primitives motion design RENDRAX (MD.*) =====
   Bibliothèque partagée des vidéos gsapvideo : chaque fonction AJOUTE des
   tweens au timeline passé en argument (jamais de timeline parallèle), donc
   tout reste déterministe au seek image par image. Toutes les fonctions sont
   protégées : une primitive ne peut jamais interrompre un rendu. */
(() => {
  if (window.MD) return;
  const $ = (sel) => (typeof sel === 'string' ? document.querySelector(sel) : (sel && sel.nodeType === 1 ? sel : null));
  const num = (v, d) => (Number.isFinite(Number(v)) ? Number(v) : d);
  const stageRoot = () => document.getElementById('st') || document.body;
  const garde = (fn) => function () {
    try { return fn.apply(null, arguments); }
    catch (e) { try { console.warn('MD : ' + (e && e.message)); } catch (e2) {} }
  };
  const calque = (id, extra) => {
    let n = document.getElementById(id);
    if (!n) {
      n = document.createElement('div');
      n.id = id;
      n.setAttribute('style', 'position:absolute;inset:0;pointer-events:none;z-index:32;display:none;' + (extra || ''));
      stageRoot().appendChild(n);
    }
    return n;
  };
  const voit = (tl, n, mode, at0, apres) => {
    tl.set(n, { display: mode }, Math.max(0, at0 - 0.02));
    if (apres != null) tl.set(n, { display: 'none' }, at0 + apres);
  };

  // Grain (5,5 %) + vignette : posés une fois pour toute la vidéo, statiques,
  // donc sûrs au seek. Donne la profondeur « film » sans coût au rendu.
  const grainFX = garde(() => {
    if (document.getElementById('md-grain')) return true;
    const g = document.createElement('div');
    g.id = 'md-grain';
    g.setAttribute('style', 'position:absolute;inset:0;pointer-events:none;z-index:34;opacity:.055;mix-blend-mode:overlay;'
      + 'background-image:url("data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' width=\'140\' height=\'140\'%3E%3Cfilter id=\'n\'%3E%3CfeTurbulence type=\'fractalNoise\' baseFrequency=\'0.85\' numOctaves=\'2\' stitchTiles=\'stitch\'/%3E%3C/filter%3E%3Crect width=\'140\' height=\'140\' filter=\'url(%23n)\'/%3E%3C/svg%3E");');
    const v = document.createElement('div');
    v.id = 'md-vignette';
    v.setAttribute('style', 'position:absolute;inset:0;pointer-events:none;z-index:35;'
      + 'background:radial-gradient(ellipse at center, rgba(0,0,0,0) 60%, rgba(0,0,0,.24) 100%);');
    const hote = stageRoot();
    hote.appendChild(g);
    hote.appendChild(v);
    return true;
  });

  // Coupe un texte en caractères animables (spans inline-block).
  const splitChars = garde((sel) => {
    const elx = $(sel);
    if (!elx) return [];
    if (elx.dataset.mdSplit === '1') return Array.prototype.slice.call(elx.querySelectorAll('span.ch'));
    const texte = elx.textContent || '';
    elx.textContent = '';
    const out = [];
    for (const ch of texte) {
      const s = document.createElement('span');
      s.className = 'ch';
      s.style.display = 'inline-block';
      s.style.willChange = 'transform, opacity';
      if (ch === ' ') { s.style.width = '.26em'; } else { s.textContent = ch; }
      elx.appendChild(s);
      out.push(s);
    }
    elx.dataset.mdSplit = '1';
    return out;
  });

  // Mot héro : >= 170px, entrée masquée caractère par caractère, puis
  // graisse 800 -> 400 et interlettrage 0.18em -> 0.04em (moment signature).
  const heroWord = garde((tl, sel, o) => {
    o = o || {};
    const elx = $(sel);
    if (!elx || !tl) return;
    const taille = Math.max(170, num(o.size, 180));
    elx.style.fontSize = taille + 'px';
    elx.style.fontWeight = '800';
    const chars = splitChars(elx);
    if (!chars.length) return;
    const at0 = num(o.at, 0);
    const dur = num(o.dur, 0.7);
    const from = o.from === 'up' ? -120 : 120;
    tl.fromTo(chars, { yPercent: from, opacity: 0 },
      { yPercent: 0, opacity: 1, duration: dur * 0.75, ease: o.easing || 'power4.out',
        stagger: { each: (dur * 0.6) / Math.max(1, chars.length), from: o.staggerFrom || 'start' } }, at0);
    tl.fromTo(elx, { letterSpacing: '0.18em' }, { letterSpacing: '0.04em', fontWeight: 400, duration: dur, ease: 'power2.out' }, at0 + dur * 0.8);
    return elx;
  });

  // Surligneur : balayage d'un fond derrière le mot accentué (ancré at(i,"mot")).
  const accent = garde((tl, sel, o) => {
    o = o || {};
    const elx = $(sel);
    if (!elx || !tl) return;
    const color = o.color || 'rgba(255,197,49,.45)';
    elx.style.backgroundImage = 'linear-gradient(' + color + ',' + color + ')';
    elx.style.backgroundRepeat = 'no-repeat';
    elx.style.backgroundPosition = '0 72%';
    elx.style.backgroundSize = '0% 56%';
    tl.to(elx, { backgroundSize: '108% 56%', duration: num(o.dur, 0.45), ease: 'power2.inOut' }, num(o.at, 0));
    return elx;
  });

  // Révélation de ligne par masque (clip-path) avec dérive latérale.
  const maskLine = garde((tl, sel, o) => {
    o = o || {};
    const elx = $(sel);
    if (!elx || !tl) return;
    tl.fromTo(elx, { clipPath: 'inset(0% 100% 0% 0%)', x: -18 },
      { clipPath: 'inset(0% 0% 0% 0%)', x: 0, duration: num(o.dur, 0.5), ease: 'power3.out' }, num(o.at, 0));
    return elx;
  });

  // Entrée en profondeur (Z) : scale 1,15 + flou 10px -> net.
  const popIn = garde((tl, sel, o) => {
    o = o || {};
    const elx = $(sel);
    if (!elx || !tl) return;
    tl.fromTo(elx, { opacity: 0, scale: 1.15, filter: 'blur(10px)' },
      { opacity: 1, scale: 1, filter: 'blur(0px)', duration: num(o.dur, 0.5),
        ease: o.easing || 'power3.out', overwrite: 'auto' }, num(o.at, 0));
    return elx;
  });

  // Sortie anticipée : mini-anticipation (contremouvement) puis glissement hors champ.
  const outSlide = garde((tl, sel, o) => {
    o = o || {};
    const elx = $(sel);
    if (!elx || !tl) return;
    const at0 = num(o.at, 0);
    const dir = o.dir === 'r' ? 1 : -1;
    tl.to(elx, { x: -dir * 22, duration: 0.09, ease: 'power1.in', overwrite: 'auto' }, at0);
    tl.to(elx, { x: dir * 1400, opacity: 0, duration: num(o.dur, 0.45), ease: 'power3.in' }, at0 + 0.09);
    return elx;
  });

  // Sortie par masque : la scène se « referme » sur l'élément (jamais de coupure sèche).
  const outMask = garde((tl, sel, o) => {
    o = o || {};
    const elx = $(sel);
    if (!elx || !tl) return;
    const at0 = num(o.at, 0);
    const up = o.dir !== 'down';
    tl.fromTo(elx, { clipPath: 'inset(0% 0% 0% 0%)' },
      { clipPath: up ? 'inset(0% 0% 100% 0%)' : 'inset(100% 0% 0% 0%)',
        y: up ? -46 : 46, duration: num(o.dur, 0.4), ease: 'power3.in' }, at0);
    return elx;
  });

  // Dérive caméra : très lent zoom de respiration (1,035 -> 1) sur la scène.
  const driftCam = garde((tl, o) => {
    o = o || {};
    const st = document.getElementById('st');
    if (!st || !tl) return;
    tl.fromTo(st, { scale: num(o.from, 1.035) },
      { scale: 1, duration: num(o.dur, 6), ease: 'none', overwrite: 'auto' }, num(o.at, 0));
    return st;
  });

  // Ken Burns : zoom lent + dérive diagonale sur une image.
  const kenBurns = garde((tl, sel, o) => {
    o = o || {};
    const elx = $(sel);
    if (!elx || !tl) return;
    tl.fromTo(elx, { scale: 1, x: 0, y: 0 },
      { scale: num(o.zoom, 1.12), x: num(o.dx, -20), y: num(o.dy, -14),
        duration: num(o.dur, 6), ease: 'none', overwrite: 'auto' }, num(o.at, 0));
    return elx;
  });

  // Parallaxe : dérive continue d'une couche pendant les temps morts.
  const parallax = garde((tl, sel, o) => {
    o = o || {};
    const elx = $(sel);
    if (!elx || !tl) return;
    tl.to(elx, { y: -num(o.depth, 40), duration: num(o.dur, 4), ease: 'none', overwrite: 'auto' }, num(o.at, 0));
    return elx;
  });

  // Compteur avec pop du suffixe (%, +, €) à la fin du décompte.
  const countTo = garde((tl, sel, o) => {
    o = o || {};
    const elx = $(sel);
    if (!elx || !tl) return;
    const dec = Math.max(0, Math.min(2, num(o.decimals, 0)));
    const suffix = o.suffix == null ? '' : String(o.suffix);
    const fmt = (v) => {
      let s = Number(v).toFixed(dec);
      if (!dec && o.groupes !== false) s = s.replace(/\B(?=(\d{3})+(?!\d))/g, '\u00a0');
      return s + suffix;
    };
    const etat = { v: num(o.from, 0) };
    elx.textContent = fmt(etat.v);
    const at0 = num(o.at, 0);
    const dur = num(o.dur, 1.2);
    tl.to(etat, { v: num(o.to, 100), duration: dur, ease: o.easing || 'power2.out',
      onUpdate: () => { try { elx.textContent = fmt(etat.v); } catch (e) {} } }, at0);
    tl.fromTo(elx, { scale: 1.14 }, { scale: 1, duration: 0.3, ease: 'back.out(2.5)', overwrite: 'auto' }, at0 + dur + 0.02);
    return elx;
  });

  // Barre de progression : scaleX de 0 au pourcentage demandé.
  const bar = garde((tl, sel, o) => {
    o = o || {};
    const elx = $(sel);
    if (!elx || !tl) return;
    elx.style.transformOrigin = '0% 50%';
    tl.fromTo(elx, { scaleX: 0 }, { scaleX: Math.max(0, Math.min(1, num(o.pct, 80) / 100)),
      duration: num(o.dur, 1), ease: o.easing || 'power2.out', overwrite: 'auto' }, num(o.at, 0));
    return elx;
  });

  // Anneau SVG de progression (premier <circle> du sélecteur), rotation -90°.
  const ring = garde((tl, sel, o) => {
    o = o || {};
    const hote = $(sel);
    if (!hote || !tl) return;
    const c = hote.nodeType === 1 && hote.tagName === 'circle' ? hote : hote.querySelector('circle');
    if (!c) return;
    const r = parseFloat(c.getAttribute('r')) || 50;
    const C = 2 * Math.PI * r;
    c.style.strokeDasharray = String(C);
    c.style.transformOrigin = '50% 50%';
    c.style.transform = 'rotate(-90deg)';
    tl.fromTo(c, { strokeDashoffset: C },
      { strokeDashoffset: C * (1 - Math.max(0, Math.min(1, num(o.pct, 75) / 100))),
        duration: num(o.dur, 1.2), ease: o.easing || 'power2.inOut', overwrite: 'auto' }, num(o.at, 0));
    return c;
  });

  // Tracé SVG animé (stroke-dashoffset), pour pictos et soulignements dessinés.
  const drawPath = garde((tl, sel, o) => {
    o = o || {};
    const p = $(sel);
    if (!p || !tl || !p.getTotalLength) return;
    const L = p.getTotalLength();
    if (!L) return;
    p.style.strokeDasharray = String(L);
    tl.fromTo(p, { strokeDashoffset: L }, { strokeDashoffset: 0,
      duration: num(o.dur, 1), ease: o.easing || 'power2.inOut', overwrite: 'auto' }, num(o.at, 0));
    return p;
  });

  // Impact : éclair plein écran 80 ms (un seul par scène, sur le mot fort).
  const flash = garde((tl, o) => {
    o = o || {};
    const n = calque('md-flash', 'background:#ffffff;');
    if (!tl) return;
    const at0 = num(o.at, 0);
    voit(tl, n, 'block', at0, 0.25);
    tl.fromTo(n, { opacity: 0 }, { opacity: Math.max(0.2, Math.min(1, num(o.force, 0.85))), duration: 0.05, ease: 'none' }, at0);
    tl.to(n, { opacity: 0, duration: num(o.dur, 0.12), ease: 'power2.out' }, at0 + 0.05);
    return n;
  });

  // Rideau N colonnes : mode 'close' (couvre) puis 'open' (révèle) à la frontière de scène.
  const rideau = garde((tl, o) => {
    o = o || {};
    const n = calque('md-rideau');
    if (!tl) return;
    if (n.dataset.built !== '1') {
      const cols = Math.max(2, Math.min(12, num(o.cols, 6)));
      n.style.display = 'flex';
      for (let i = 0; i < cols; i += 1) {
        const b = document.createElement('div');
        b.style.flex = '1';
        b.style.background = o.color || '#05070d';
        b.style.transformOrigin = '50% 0%';
        n.appendChild(b);
      }
      n.dataset.built = '1';
    }
    const at0 = num(o.at, 0);
    const dur = num(o.dur, 0.55);
    const bands = Array.prototype.slice.call(n.children);
    if (o.mode === 'open') {
      tl.fromTo(bands, { scaleY: 1 }, { scaleY: 0, duration: dur, ease: 'power3.inOut',
        stagger: { each: 0.045, from: o.sens === 'fin' ? 'start' : 'end' } }, at0);
      voit(tl, n, 'flex', at0, dur + 0.32);
    } else {
      tl.fromTo(bands, { scaleY: 0 }, { scaleY: 1, duration: dur, ease: 'power3.inOut',
        stagger: { each: 0.045, from: o.sens === 'fin' ? 'end' : 'start' } }, at0);
      tl.set(n, { display: 'flex' }, Math.max(0, at0 - 0.02));
    }
    return n;
  });

  // Iris : cercle qui se referme (close) ou s'ouvre (open).
  const iris = garde((tl, o) => {
    o = o || {};
    const n = calque('md-iris', 'background:' + (o.color || '#05070d') + ';');
    if (!tl) return;
    const at0 = num(o.at, 0);
    const dur = num(o.dur, 0.6);
    if (o.mode === 'open') {
      tl.fromTo(n, { clipPath: 'circle(0% at 50% 50%)' }, { clipPath: 'circle(142% at 50% 50%)', duration: dur, ease: 'power3.inOut' }, at0);
      voit(tl, n, 'block', at0, dur + 0.08);
    } else {
      tl.fromTo(n, { clipPath: 'circle(142% at 50% 50%)' }, { clipPath: 'circle(0% at 50% 50%)', duration: dur, ease: 'power3.inOut' }, at0);
      tl.set(n, { display: 'block' }, Math.max(0, at0 - 0.02));
    }
    return n;
  });

  // Vague : bandes horizontales qui balaient en zigzag.
  const vague = garde((tl, o) => {
    o = o || {};
    const n = calque('md-vague');
    if (!tl) return;
    if (n.dataset.built !== '1') {
      const lignes = Math.max(2, Math.min(10, num(o.bandes, 5)));
      n.style.display = 'flex';
      n.style.flexDirection = 'column';
      for (let i = 0; i < lignes; i += 1) {
        const b = document.createElement('div');
        b.style.flex = '1';
        b.style.background = o.color || '#05070d';
        n.appendChild(b);
      }
      n.dataset.built = '1';
    }
    const at0 = num(o.at, 0);
    const dur = num(o.dur, 0.5);
    const stg = num(o.stagger, 0.06);
    const bands = Array.prototype.slice.call(n.children);
    if (o.mode === 'open') {
      bands.forEach((b, i) => tl.to(b, { xPercent: i % 2 ? -106 : 106, duration: dur, ease: 'power3.in' }, at0 + i * stg));
      voit(tl, n, 'flex', at0, dur + stg * bands.length + 0.08);
    } else {
      bands.forEach((b, i) => tl.fromTo(b, { xPercent: i % 2 ? 106 : -106 }, { xPercent: 0, duration: dur, ease: 'power3.out' }, at0 + i * stg));
      tl.set(n, { display: 'flex' }, Math.max(0, at0 - 0.02));
    }
    return n;
  });

  // Pleine page : un panneau de couleur traverse l'écran.
  const flood = garde((tl, o) => {
    o = o || {};
    const n = calque('md-flood', 'background:' + (o.color || '#0b1220') + ';');
    if (!tl) return;
    const at0 = num(o.at, 0);
    const dur = num(o.dur, 0.45);
    if (o.mode === 'open') {
      tl.fromTo(n, { xPercent: 0 }, { xPercent: 103, duration: dur, ease: 'power3.inOut' }, at0);
      voit(tl, n, 'block', at0, dur + 0.08);
    } else {
      tl.fromTo(n, { xPercent: -103 }, { xPercent: 0, duration: dur, ease: 'power3.inOut' }, at0);
      tl.set(n, { display: 'block' }, Math.max(0, at0 - 0.02));
    }
    return n;
  });

  // Fondu en deux temps vers le noir : ouverture douce de scène ou générique de fin.
  const fondu2 = garde((tl, o) => {
    o = o || {};
    const n = calque('md-fondu', 'background:#000;');
    if (!tl) return;
    const at0 = num(o.at, 0);
    if (o.mode === 'open') {
      tl.fromTo(n, { opacity: 1 }, { opacity: 0, duration: num(o.dur, 0.5), ease: 'power2.out' }, at0);
      voit(tl, n, 'block', at0, num(o.dur, 0.5) + 0.08);
    } else {
      tl.fromTo(n, { opacity: 0 }, { opacity: 1, duration: num(o.dur, 0.35), ease: 'power2.in' }, at0);
      tl.set(n, { display: 'block' }, Math.max(0, at0 - 0.02));
    }
    return n;
  });

  window.MD = {
    grainFX, splitChars, heroWord, accent, maskLine, popIn, outSlide, outMask,
    driftCam, kenBurns, parallax, countTo, bar, ring, drawPath, flash,
    rideau, iris, vague, flood, fondu2
  };
})();

0;
"""


# Pont injecté DANS la fermeture de la page « canvas + voix » (profil rendraxai), juste avant son
# démarrage : il donne accès à ses variables privées sans modifier le fichier de l'utilisateur.
RENDRAXAI_BRIDGE = r"""/* RENDRAX : pont de rendu image par image (injecté au rendu, fichier d'origine intact) */
window.__rendraxSeek = (t) => {
  currentTime = Math.max(0, Number(t) || 0);
  isPlaying = false;
  renderFrame(currentTime);
};
window.__rendraxReady = () => {
  try { return !!(hasExternalPhoto || (externalPhoto.complete && externalPhoto.naturalWidth === 0)); }
  catch (e) { return true; }
};
window.__rendraxDuration = () => {
  const d = voiceAudio.duration;
  return Math.max(totalDuration, (Number.isFinite(d) && d > 0) ? d : 0);
};
window.__rendraxSfx = async (total) => {
  const sr = 44100;
  const oc = new OfflineAudioContext(1, Math.ceil((Number(total) + 2) * sr), sr);
  let T = 0;
  Object.defineProperty(oc, 'currentTime', { get: () => T });
  const keep = { c: sfxCtx, n: noiseBuf, s: lastSfxStep, p: isPlaying };
  try {
    sfxCtx = oc;
    const len = Math.floor(sr * 1.2);
    noiseBuf = oc.createBuffer(1, len, sr);
    const nd = noiseBuf.getChannelData(0);
    let seed = 20070629;
    for (let i = 0; i < len; i++) { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; nd[i] = seed / 2147483648 - 1; }
    isPlaying = true; lastSfxStep = -1;
    // Même grille que la lecture réelle : un déclenchement par pas de 200 ms, au premier instant du pas.
    const steps = Math.floor(Number(total) * 5);
    for (let k = 0; k <= steps; k++) { T = k / 5 + 0.008; triggerCinematicSfx(T); }
  } finally {
    sfxCtx = keep.c; noiseBuf = keep.n; lastSfxStep = keep.s; isPlaying = keep.p;
  }
  const buf = await oc.startRendering();
  const x = buf.getChannelData(0), pcm = new Int16Array(x.length);
  for (let i = 0; i < x.length; i++) { const v = Math.max(-1, Math.min(1, x[i])); pcm[i] = v < 0 ? v * 32768 : v * 32767; }
  const u8 = new Uint8Array(pcm.buffer);
  let bin = '';
  for (let i = 0; i < u8.length; i += 0x8000) bin += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000));
  return btoa(bin);
};
"""

# Scène fixée à 1080×1920 px en haut à gauche, sans bouton ▶, bords arrondis ni ombre.
RENDRAXAI_STAGE_CSS = (
    "html,body{margin:0!important;padding:0!important;background:#000!important;display:block!important;overflow:hidden!important}"
    ".stage-wrap{position:fixed!important;left:0!important;top:0!important;width:1080px!important;height:1920px!important;"
    "max-height:none!important;aspect-ratio:auto!important;border-radius:0!important;box-shadow:none!important;transform:none!important}"
    "#canvas{width:1080px!important;height:1920px!important}"
    "#playBtn{display:none!important}"
)


GENERIC_AUDIO_CAPTURE = r"""<script>
(() => {
  if (window.__h2mCaptureInstalled) return;
  window.__h2mCaptureInstalled = true;
  const Native = window.AudioContext || window.webkitAudioContext;
  const contexts = [];
  let active = false;
  const originalConnect = window.AudioNode && AudioNode.prototype.connect;
  if (originalConnect) {
    AudioNode.prototype.connect = function(destination, ...args) {
      const result = originalConnect.call(this, destination, ...args);
      try {
        const ctx = this.context;
        if (ctx && destination === ctx.destination && ctx.__h2mDest && !ctx.__h2mDup) {
          ctx.__h2mDup = true;
          originalConnect.call(this, ctx.__h2mDest);
          ctx.__h2mDup = false;
        }
      } catch (_) {}
      return result;
    };
  }
  function install(ctx) {
    if (!ctx || ctx.__h2mDest) return;
    try {
      ctx.__h2mDest = ctx.createMediaStreamDestination();
      ctx.__h2mChunks = [];
      ctx.__h2mRec = null;
      contexts.push(ctx);
      start(ctx);
    } catch (_) {}
  }
  if (Native) {
    function WrappedAudioContext(...args) {
      const ctx = new Native(...args);
      install(ctx);
      return ctx;
    }
    WrappedAudioContext.prototype = Native.prototype;
    try { Object.setPrototypeOf(WrappedAudioContext, Native); } catch (_) {}
    window.AudioContext = WrappedAudioContext;
    if (window.webkitAudioContext) window.webkitAudioContext = WrappedAudioContext;
  }
  function start(ctx) {
    if (!ctx || !ctx.__h2mDest || ctx.__h2mRec || !window.MediaRecorder) return;
    try {
      const type = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus' : 'audio/webm';
      const rec = new MediaRecorder(ctx.__h2mDest.stream, { mimeType: type });
      ctx.__h2mRec = rec;
      rec.ondataavailable = e => { if (e.data && e.data.size) ctx.__h2mChunks.push(e.data); };
      rec.start(250);
      ctx.__h2mRecStartPerf = performance.now();
      ctx.__h2mRecCt = ctx.currentTime;
    } catch (_) {}
  }
  window.__h2mStart = async () => {
    if (active) return contexts.length;
    active = true;
    if (Native) {
      for (const el of document.querySelectorAll('audio,video')) {
        try {
          if (!el.__h2mSource) {
            const ctx = new Native();
            install(ctx);
            const source = ctx.createMediaElementSource(el);
            el.__h2mSource = source;
            source.connect(ctx.destination);
          }
        } catch (_) {}
      }
    }
    for (const ctx of contexts) {
      try { await ctx.resume(); } catch (_) {}
      start(ctx);
    }
    for (const el of document.querySelectorAll('audio,video')) {
      try { el.muted = false; el.currentTime = 0; const p = el.play(); if (p) await p.catch(() => {}); } catch (_) {}
    }
    return contexts.length;
  };
  // L'horloge de l'AudioContext n'avance que lorsqu'il tourne, comme le flux enregistré :
  // elle donne un décalage fiable même si le contexte a démarré suspendu.
  window.__h2mMark = () => {
    window.__h2mVideoStartPerf = performance.now();
    for (const ctx of contexts) { try { ctx.__h2mMarkCt = ctx.currentTime; } catch (_) {} }
  };
  window.__h2mStop = async () => {
    const records = contexts.filter(c => c.__h2mRec);
    await Promise.all(records.map(c => new Promise(resolve => {
      const rec = c.__h2mRec;
      if (rec.state === 'inactive') return resolve();
      rec.addEventListener('stop', resolve, { once: true });
      try { rec.stop(); } catch (_) { resolve(); }
    })));
    const result = [];
    for (const ctx of records) {
      try {
        const blob = new Blob(ctx.__h2mChunks, { type: 'audio/webm' });
        if (blob.size < 500) continue;
        const data = await new Promise(resolve => {
          const reader = new FileReader();
          reader.onload = () => resolve(String(reader.result).split(',').pop());
          reader.onerror = () => resolve('');
          reader.readAsDataURL(blob);
        });
        if (data) result.push({
          mime: blob.type || 'audio/webm',
          data,
          offset: (ctx.__h2mMarkCt != null && ctx.__h2mRecCt != null) ? ctx.__h2mMarkCt - ctx.__h2mRecCt :
            window.__h2mVideoStartPerf == null ? 0 :
            (window.__h2mVideoStartPerf - (ctx.__h2mRecStartPerf || window.__h2mVideoStartPerf)) / 1000
        });
      } catch (_) {}
    }
    return result;
  };
  window.addEventListener('load', () => { try { window.__h2mStart(); } catch (_) {} }, { once: true });
})();
</script>"""
