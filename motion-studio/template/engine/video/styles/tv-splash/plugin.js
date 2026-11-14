/* tv-splash — заставка: титр на тёмной сцене (engine/video/styles/README.md, «Миры с набором сцены»).
   Мир — в слое 'back', под содержанием; кадр — чистая функция t (CSS-анимаций нет).

   Мир (cfg.world): фон decor.bg; два цветных пятна авроры медленно плывут; четыре кольца вокруг центра кадра —
   два пунктирных вращаются навстречу, два сплошных дышат; по внешнему пунктиру идёт комета; редкие искры мерцают.
   Углы кадра остаются чистым фоном. Смешения слоёв (mix-blend-mode) нет. В сцене с каркасом — светлые окна под
   текстом (StyleCore.textWindows). Сцена управляет светом мира из своей разметки:
     (window.TvSplashScenes = window.TvSplashScenes || []).push({scene, setup: function (kit, FILM, api) {
        return {light: function (t) → 0…1 (сила авроры и колец), rings: function (t) → 0…1 (только кольца и комета),
                hits: [t…] (удар титра: одно расходящееся кольцо-сонар), frame: function (t) {}}; }});
   kit = window.TvSplash: decor, params, track (дорожка ключей), strike (разгорание трубки между двумя моментами),
   breath (дыхание ореола), at({reply, at, offset}) → секунды, events(dom), scene(id). Хук сцены может дать ещё
   jolt(t) → [dx, dy] — толчок кадра на ударе: кольца и искры вздрагивают вместе с титром.
   Сцена без подключения — свет 1, ударов нет. Титра и слов в стиле нет — они в данных проекта.
   Замок бренда (cfg.world = false): фона и предметов нет. */
(window.StagePlugins = window.StagePlugins || []).push(function (FILM, api) {
  'use strict';
  var NAME = 'tv-splash', cfg = api.styleConfig(NAME);
  if (!cfg) return null;
  var C = window.StyleCore, D = cfg.decor, P = cfg.params || {};
  var root = document.getElementById('root'), W = root.clientWidth, H = root.clientHeight, CX = W / 2, CY = H / 2;
  var ids = api.styleScenes(NAME);
  var layer = api.addLayer('tv-splash-back', 'back');
  if (cfg.world) layer.style.background = D[P.bg_role];

  function rgba(hex, a) { var c = C.rgbOf(hex); return 'rgba(' + c[0] + ',' + c[1] + ',' + c[2] + ',' + a + ')'; }
  function track(v0, keys) {            // дорожка ключей {t, v, d, e}: каждый едет от того, куда доехал предыдущий
    keys = keys.slice().sort(function (a, b) { return a.t - b.t; });
    var from = [];
    function upTo(n, t) {
      var v = v0;
      for (var i = 0; i < n; i++) {
        var k = keys[i];
        if (k.t > t) break;
        v = api.lerp(from[i], k.v, api.powerEase(k.e || 'power2.inOut')(api.prog(t, k.t, k.d || 0)));
      }
      return v;
    }
    keys.forEach(function (k, i) { from[i] = upTo(i, k.t); });
    return function (t) { return upTo(keys.length, t); };
  }
  /* Разгорание газовой трубки между двумя моментами (схватилась → встала): n вспышек-дрожи, каждая — целое
     число кадров (ни одна не теряется между кадрами), в паузах трубка не гаснет в ноль (послесвечение), с момента tOn —
     ровный свет с перекалом, который оседает. Расписание — от зерна: от прогона к прогону одно и то же.
     at(t) → {c — жила, h — ореол}: ореол во вспышках слабее жилы и расцветает, когда трубка встала. */
  function strike(seed, t0, tOn) {
    var L = P.strike, r = C.rng(C.hash('strike' + seed)), FR = 1 / FILM.fps, n = L.flashes, i;
    var total = Math.max(2 * n, Math.round((tOn - t0) * FILM.fps)), on = [], used = 0;
    for (i = 0; i < n; i++) { on.push(L.on[0] + Math.floor(r() * (L.on[1] - L.on[0] + 1))); used += on[i]; }
    var gaps = [], left = Math.max(n, total - used);
    for (i = 0; i < n; i++) { gaps.push(i < n - 1 ? Math.max(1, Math.floor(left / n)) : 0); }
    gaps[n - 1] = Math.max(1, left - gaps.slice(0, n - 1).reduce(function (a, b) { return a + b; }, 0));
    var segs = [], f = 0;
    for (i = 0; i < n; i++) {
      f += on[i]; segs.push([f, api.lerp(L.peak[0], L.peak[1], n > 1 ? i / (n - 1) : 1)]);
      f += gaps[i]; segs.push([f, L.dark[0] + r() * (L.dark[1] - L.dark[0])]);
    }
    function core(t) {
      var k = api.frameOf(t) - api.frameOf(t0);
      if (k < 0) return 0;
      if (t < tOn - 1e-6) { for (var j = 0; j < segs.length; j++) if (k < segs[j][0]) return segs[j][1]; }
      return 1 + (L.over - 1) * Math.exp(-5 * Math.max(0, t - tOn) / L.settle);
    }
    return { n: n, core: core, at: function (t) {
      var c = core(t);
      return { c: c, h: t < tOn - 1e-6 ? c * L.halo_strike : c * (1 - (1 - L.halo_strike) * Math.exp(-(t - tOn) / L.bloom)) };
    } };
  }
  function breath(t) { return 1 + P.breath.amp * Math.sin(2 * Math.PI * t / P.breath.period); }
  var kit = { decor: D, params: P, track: track, svg: C.svg, rgba: rgba, strike: strike, breath: breath,
              at: function (anchor) { return C.when(FILM, anchor); },      // якорь {reply, at, offset} → секунды фильма
              cues: function (scene) { return C.cues(FILM, scene); },      // метки act сцены: {id, t, who, do, m, span}
              events: function (dom) { return FILM.elements.filter(function (e) { return e.dom === dom && !e.part; })[0]; },
              scene: function (id) { return FILM.scenes.filter(function (x) { return x.id === id; })[0]; } };
  window.TvSplash = kit;

  var hooks = [];
  if (cfg.world) {
    ids.forEach(function (id) {         // роли decor — переменными --d-<роль> на секции сцены (свечение надписей)
      var sec = document.getElementById('scene--' + id);
      if (sec) Object.keys(D).forEach(function (role) { sec.style.setProperty('--d-' + role, D[role]); });
    });
    (window.TvSplashScenes || []).forEach(function (s) {
      if (ids.indexOf(s.scene) >= 0) hooks.push({ sc: kit.scene(s.scene), h: s.setup(kit, FILM, api) || {} });
    });
  }

  var aur = [], rings = [], sparks = [], comet = null, tail = [], sonar = null, ringG = null, svgRoot = null;
  if (cfg.world) {
    // ---- аврора: два пятна, плывут по своим эллипсам
    (P.aurora || []).forEach(function (a, k) {
      var d = document.createElement('div');
      d.style.cssText = 'position:absolute;left:' + (a.x - a.r) + 'px;top:' + (a.y - a.r) + 'px;width:' + (2 * a.r) + 'px;height:' +
        (2 * a.r) + 'px;border-radius:50%;background:radial-gradient(circle,' + rgba(D[a.role], a.alpha) + ' 0%,' +
        rgba(D[a.role], a.alpha * 0.45) + ' 34%,' + rgba(D[a.role], 0) + ' 68%);';
      layer.appendChild(d);
      aur.push({ n: d, a: a, k: k });
    });
    var svg = C.svg('svg', { width: String(W), height: String(H), viewBox: '0 0 ' + W + ' ' + H }, layer);
    svg.style.position = 'absolute'; svg.style.left = '0'; svg.style.top = '0'; svgRoot = svg;
    // ---- искры: редкие точки, мерцают каждая в своей фазе и медленно всплывают
    var rnd = C.rng(C.hash(NAME)), sg = C.svg('g', {}, svg);
    for (var i = 0; i < (P.sparks || 0); i++) {
      var ang = rnd() * 6.2832, rad = 180 + rnd() * 560;
      sparks.push({ n: C.svg('circle', { r: (1 + rnd() * 1.6).toFixed(2), fill: i % 5 === 0 ? D.gold : D.glow_soft }, sg),
                    x: CX + Math.cos(ang) * rad * 1.35, y: CY + Math.sin(ang) * rad * 0.62, ph: rnd() * 6.2832,
                    w: 0.5 + rnd() * 0.9, up: 4 + rnd() * 8 });
    }
    // ---- кольца
    ringG = C.svg('g', {}, svg);
    (P.rings || []).forEach(function (r, k) {
      var n = C.svg('circle', { cx: CX, cy: CY, r: r.r, fill: 'none', stroke: D[r.role || 'glow_soft'], 'stroke-width': r.w,
                                'stroke-dasharray': r.dash ? r.dash.join(' ') : 'none' }, ringG);
      rings.push({ n: n, r: r, k: k });
    });
    // ---- комета на орбите внешнего пунктира: голова и тающий хвост
    if (P.comet) {
      comet = C.svg('g', {}, ringG);
      for (var j = P.comet.tail; j >= 0; j--) {
        var a0 = -j * P.comet.step_deg * Math.PI / 180, rr = P.comet.r;
        tail.push(C.svg('circle', { cx: (CX + Math.sin(a0) * rr).toFixed(2), cy: (CY - Math.cos(a0) * rr).toFixed(2),
                                    r: (j ? 2.2 * (1 - j / (P.comet.tail + 1)) + 0.6 : 4.5).toFixed(2),
                                    fill: j ? D.glow_soft : D.hi, opacity: (j ? 0.75 * (1 - j / (P.comet.tail + 1)) : 1).toFixed(3) }, comet));
      }
    }
    sonar = C.svg('circle', { cx: CX, cy: CY, r: 240, fill: 'none', stroke: D.glow_soft, 'stroke-width': 2, visibility: 'hidden' }, svg);
  }

  // окна под текстом (сцена с каркасом) — последними в слое: поверх авроры, колец и искр, иначе свет мира ложится на текст
  var FRAMED = FILM.scenes.some(function (sc) { return sc.style === NAME && sc.frame !== false; });
  var wins = cfg.world && FRAMED ? C.textWindows(api, FILM, NAME, { parent: layer, pad: P.win_pad_px,
                                                                    css: { borderRadius: '6px', boxShadow: '0 0 0 2px ' + D.glow_soft } }) : null;

  function hookAt(t) {
    for (var i = 0; i < hooks.length; i++) if (t >= hooks[i].sc.start - 0.5 && t < hooks[i].sc.end + 0.5) return hooks[i].h;
    return null;
  }
  function render(t) {
    var w = api.styleWeight(NAME, t);
    api.setStyle(layer, 'opacity', api.styleOpacity(NAME, t, layer).toFixed(3));
    api.setStyle(layer, 'visibility', w > 0.001 ? 'visible' : 'hidden');
    hooks.forEach(function (q) { if (q.h.frame) q.h.frame(t); });
    if (w <= 0.001 || !cfg.world) return;
    if (wins) wins.render(t);
    var h = hookAt(t), L = h && h.light ? api.clamp01(h.light(t)) : 1, R = h && h.rings ? api.clamp01(h.rings(t)) : 1;
    aur.forEach(function (q) {
      var a = q.a, ph = 2 * Math.PI * t / a.period + q.k * 2.1;
      api.setStyle(q.n, 'transform', 'translate(' + (Math.cos(ph) * a.dx).toFixed(2) + 'px,' + (Math.sin(ph) * a.dy).toFixed(2) + 'px) scale(' +
        (1 + 0.05 * Math.sin(ph * 0.7 + 1)).toFixed(4) + ')');
      api.setStyle(q.n, 'opacity', L.toFixed(3));
    });
    api.setAttr(ringG, 'opacity', (L * R).toFixed(3));
    var jl = h && h.jolt ? h.jolt(t) : null;
    api.setStyle(svgRoot, 'transform', jl && (jl[0] || jl[1]) ? 'translate(' + jl[0].toFixed(2) + 'px,' + jl[1].toFixed(2) + 'px)' : 'none');
    rings.forEach(function (q) {
      var r = q.r, o = r.alpha, tf = '';
      if (r.spin) tf = 'rotate(' + (360 * t / r.spin).toFixed(3) + ' ' + CX + ' ' + CY + ')';
      if (r.breathe) {
        var b = 0.5 - 0.5 * Math.cos(2 * Math.PI * (t + (r.phase || 0)) / r.breathe);
        var s = 1 + r.amp * (2 * b - 1);
        tf = 'translate(' + CX + ' ' + CY + ') scale(' + s.toFixed(5) + ') translate(' + (-CX) + ' ' + (-CY) + ')';
        o = r.alpha * (0.55 + 0.45 * b);
      }
      if (tf) api.setAttr(q.n, 'transform', tf);
      api.setAttr(q.n, 'opacity', o.toFixed(3));
    });
    if (comet) api.setAttr(comet, 'transform', 'rotate(' + (360 * t / P.comet.period).toFixed(3) + ' ' + CX + ' ' + CY + ')');
    sparks.forEach(function (q) {
      var tw = 0.5 + 0.5 * Math.sin(q.ph + t * q.w * 2);
      api.setAttr(q.n, 'opacity', (L * 0.75 * tw * tw).toFixed(3));
      api.setAttr(q.n, 'cx', q.x.toFixed(1));
      api.setAttr(q.n, 'cy', (q.y - (t * q.up) % 60).toFixed(1));
    });
    // сонар: одно кольцо от удара титра, расходится и тает
    var son = null;
    (h && h.hits || []).forEach(function (t0) { var p = (t - t0) / P.sonar.dur; if (p > 0 && p < 1) son = p; });
    api.setAttr(sonar, 'visibility', son == null ? 'hidden' : 'visible');
    if (son != null) {
      var e = api.powerEase('power2.out')(son), k = api.lerp(P.sonar.from, P.sonar.to, e);
      api.setAttr(sonar, 'transform', 'translate(' + CX + ' ' + CY + ') scale(' + k.toFixed(4) + ') translate(' + (-CX) + ' ' + (-CY) + ')');
      api.setAttr(sonar, 'stroke-width', (2 / k).toFixed(3));
      api.setAttr(sonar, 'opacity', (P.sonar.alpha * (1 - e)).toFixed(3));
    }
  }
  return {
    render: render,
    probe: function (t) { return { style: NAME, weight: api.styleWeight(NAME, t), world: cfg.world }; }
  };
});
