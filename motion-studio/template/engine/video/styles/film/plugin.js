/* Плёнка — плагин стиля (engine/video/styles/README.md). Всё в слое 'back' — под каркасом и содержанием,
   поэтому текст и плашки остаются чистыми (catalog/styles.md, пресет 5: «зерно только на плёночном слое»).

   Мир (cfg.world): тёмный зал (decor.dark), светлый кадр-окно (decor.screen, params.world_window, дюймы) со
   скруглёнными углами — в нём весь каркас и содержание; перфорация сверху и снизу едет, на кромке —
   надпечатка шрифтом декора (decor.edge); в зонах сцены (decor_zones) — ракорд с отсчётом 3-2-1 и
   вращающимся сектором, бобина (вращается), хлопушка, кусок плёнки с кадрами, луч проектора.
   Внутри окна: зерно (тайл и сдвиг — от номера кадра без модуля), виньетка, царапины и пылинки — свои на
   каждом кадре, мерцание света ≤ flicker (далеко под порогом V23).
   При style_brand_lock (cfg.world = false): белый фирменный фон, перфорация по краям, зерно, виньетка. */
(window.StagePlugins = window.StagePlugins || []).push(function (FILM, api) {
  'use strict';
  var NAME = 'film', cfg = api.styleConfig(NAME);
  if (!cfg) return null;
  var C = window.StyleCore, P = cfg.params, D = cfg.decor, PX = FILM.px, WORLD = cfg.world;
  var root = document.getElementById('root'), W = root.clientWidth, H = root.clientHeight;
  var layer = api.addLayer('film-back', 'back');
  function div(css, parent) {
    var d = document.createElement('div'); d.className = 'layer';
    Object.keys(css).forEach(function (k) { d.style[k] = css[k]; });
    (parent || layer).appendChild(d); return d;
  }
  var inkC = WORLD ? D.dark : C.cssVar('--c-' + P.strip_role), holeC = WORLD ? D.hole : C.cssVar('--c-' + P.hole_role);

  // кадр-окно (мир) или весь кадр (замок): в нём зерно, мерцание, виньетка, царапины
  var win = layer, wx = 0, wy = 0, ww = W, wh = H;
  if (WORLD) {
    layer.style.background = D.dark;
    wx = P.world_window[0] * PX; wy = P.world_window[1] * PX; ww = P.world_window[2] * PX; wh = P.world_window[3] * PX;
    win = div({ left: wx + 'px', top: wy + 'px', width: ww + 'px', height: wh + 'px', background: D.screen,
                borderRadius: P.world_radius_px + 'px', overflow: 'hidden' });
  }
  var tiles = C.grainTiles(P.grain_tiles, P.grain_size, P.grain_seed, { alpha: P.grain_alpha, sigma: 0.6 });
  var grain = div({ backgroundSize: P.grain_size + 'px ' + P.grain_size + 'px' }, win);
  var flick = div({ background: WORLD ? D.sepia : C.cssVar('--c-' + P.vignette_role), opacity: '0' }, win);
  var vig = div({}, win);
  C.vignette(vig, { strength: P.vignette, inner: P.vignette_inner, rgb: C.rgbOf(WORLD ? D.sepia : C.cssVar('--c-' + P.vignette_role)) });
  var svg = C.svg('svg', { width: String(W), height: String(H), viewBox: '0 0 ' + W + ' ' + H }, layer);
  svg.style.position = 'absolute'; svg.style.left = '0'; svg.style.top = '0';
  // окна под текстом (StyleCore.textWindows): зоны текста — из раскладки сцены, а не из стиля; середина
  // окна — фон бренда, контраст надписи = контраст бренда на любом фильме (V21); оформление — языком мира
  var wins = WORLD ? C.textWindows(api, FILM, NAME, { parent: layer, pad: P.win_pad_px, css: { borderRadius: '12px' }, feather: 14 }) : null;
  if (WORLD) {                          // царапины и пылинки — только внутри окна
    C.svg('rect', { x: String(wx), y: String(wy), width: String(ww), height: String(wh), rx: String(P.world_radius_px) },
          C.svg('clipPath', { id: 'film-win' }, C.defs()));
  }
  var marks = C.svg('g', { stroke: WORLD ? D.sepia : inkC, fill: WORLD ? D.sepia : inkC, 'clip-path': WORLD ? 'url(#film-win)' : '' }, svg);

  // перфорация: полоса + дырки (+ надпечатка на кромке в мире); сдвиг — transform
  var topH = (WORLD ? P.world_strip_top_in : P.strip_top_in) * PX, botH = (WORLD ? P.world_strip_bottom_in : P.strip_bottom_in) * PX;
  var pitch = P.hole_pitch_in * PX, strips = [];
  [[0, topH, 1], [H - botH, botH, 0.75]].forEach(function (s) {
    if (!WORLD) C.svg('rect', { x: '0', y: s[0].toFixed(1), width: String(W), height: s[1].toFixed(1), fill: inkC }, svg);
    var g = C.svg('g', {}, svg), hw = P.hole_w_in * PX * s[2], hh = P.hole_h_in * PX * s[2], d = [];
    var y = s[0] + (WORLD && s[2] === 1 ? 8 : (s[1] - hh) / 2);
    for (var x = -pitch; x < W + pitch; x += pitch) {
      d.push('M' + (x + 3).toFixed(1) + ' ' + y.toFixed(1) + 'h' + (hw - 6).toFixed(1) + 'q3 0 3 3v' + (hh - 6).toFixed(1)
        + 'q0 3 -3 3h' + (-(hw - 6)).toFixed(1) + 'q-3 0 -3 -3v' + (-(hh - 6)).toFixed(1) + 'q0 -3 3 -3z');
    }
    C.svg('path', { d: d.join(''), fill: holeC }, g);
    if (WORLD && s[2] === 1) {
      var t = C.text(g, -pitch, y + hh + 19, new Array(12).join(P.edge_text), { fill: D.edge, 'font-size': '15', 'letter-spacing': '2' });
      t.style.fontFamily = cfg.fonts.decor;
    }
    strips.push(g);
  });

  // ---------------------------------------------------------------- мир: предметы в зонах сцены
  var world = [];
  function S(g, tag, a) { return C.svg(tag, a, g); }
  var DRAW = {
    countdown: function (g, x, y, s) {     // ракорд: кольца, перекрестье, сектор, цифра отсчёта
      var cx = x + s / 2, cy = y + s / 2, r = s * 0.46, o = {};
      S(g, 'circle', { cx: cx, cy: cy, r: r, fill: D.slate_light, stroke: D.reel, 'stroke-width': 4 });
      o.sweep = S(g, 'path', { fill: D.sepia, 'fill-opacity': 0.22 });
      S(g, 'circle', { cx: cx, cy: cy, r: r * 0.78, fill: 'none', stroke: D.reel, 'stroke-width': 2 });
      S(g, 'path', { d: 'M' + (cx - r) + ' ' + cy + 'H' + (cx + r) + 'M' + cx + ' ' + (cy - r) + 'V' + (cy + r), stroke: D.reel, 'stroke-width': 1.5 });
      o.num = C.text(g, cx, cy + s * 0.17, '3', { 'text-anchor': 'middle', 'font-size': String(Math.round(s * 0.5)), fill: D.reel });
      o.num.style.fontFamily = cfg.fonts.title; o.num.style.fontWeight = '700';
      o.cx = cx; o.cy = cy; o.r = r;
      return o;
    },
    reel: function (g, x, y, s) {          // бобина: обод, пять окон, ступица
      var cx = x + s / 2, cy = y + s / 2, r = s * 0.46, rot = S(g, 'g', {});
      S(rot, 'circle', { cx: cx, cy: cy, r: r, fill: D.reel });
      for (var k = 0; k < 5; k++) {
        var a = k / 5 * Math.PI * 2;
        S(rot, 'circle', { cx: cx + Math.cos(a) * r * 0.52, cy: cy + Math.sin(a) * r * 0.52, r: r * 0.24, fill: D.screen });
      }
      S(rot, 'circle', { cx: cx, cy: cy, r: r * 0.12, fill: D.sepia });
      S(g, 'circle', { cx: cx, cy: cy, r: r, fill: 'none', stroke: D.sepia, 'stroke-width': 3 });
      return { rot: rot, cx: cx, cy: cy };
    },
    slate: function (g, x, y, s) {         // хлопушка: полосатая планка и доска с надписью
      var w = s, top = y + s * 0.18, bh = s * 0.6;
      S(g, 'rect', { x: x, y: top + s * 0.16, width: w, height: bh, rx: 6, fill: D.slate });
      var bar = S(g, 'g', {});
      S(bar, 'rect', { x: x, y: top, width: w, height: s * 0.14, fill: D.slate_light, stroke: D.slate, 'stroke-width': 2 });
      for (var k = 0; k < 6; k++)
        S(bar, 'path', { d: 'M' + (x + k * w / 6) + ' ' + (top + s * 0.14) + 'l' + w / 12 + ' ' + (-s * 0.14) + 'h' + w / 12 + 'l' + (-w / 12) + ' ' + s * 0.14 + 'z', fill: D.slate });
      var t1 = C.text(g, x + s * 0.08, top + s * 0.38, 'СЦЕНА', { fill: D.slate_light, 'font-size': String(Math.round(s * 0.1)) });
      var t2 = C.text(g, x + s * 0.08, top + s * 0.6, 'ДУБЛЬ', { fill: D.slate_light, 'font-size': String(Math.round(s * 0.1)) });
      t1.style.fontFamily = t2.style.fontFamily = cfg.fonts.decor;
      return { bar: bar, x: x, top: top };
    },
    strip: function (g, x, y, s) {         // кусок плёнки с тремя кадрами, наискосок
      var rg = S(g, 'g', { transform: 'rotate(-12 ' + (x + s / 2) + ' ' + (y + s / 2) + ')' }), w = s * 0.42, h = s;
      var x0 = x + s / 2 - w / 2;
      S(rg, 'rect', { x: x0, y: y, width: w, height: h, fill: D.reel });
      for (var k = 0; k < 3; k++) S(rg, 'rect', { x: x0 + w * 0.2, y: y + 8 + k * (h - 16) / 3, width: w * 0.6, height: (h - 16) / 3 - 8, fill: D.slate_light, 'fill-opacity': 0.85 });
      for (var j = 0; j < 9; j++) {
        S(rg, 'rect', { x: x0 + 4, y: y + 6 + j * h / 9, width: w * 0.1, height: h / 18, rx: 2, fill: D.hole });
        S(rg, 'rect', { x: x0 + w - 4 - w * 0.1, y: y + 6 + j * h / 9, width: w * 0.1, height: h / 18, rx: 2, fill: D.hole });
      }
      return {};
    },
    beam: function (g, x, y, s) {          // луч проектора: мягкий конус света и объектив
      var id = 'film-beam-' + Math.round(x), gr = S(C.defs(), 'linearGradient', { id: id, x1: 0, y1: 0, x2: 1, y2: 0 });
      S(gr, 'stop', { offset: '0', 'stop-color': D.leak, 'stop-opacity': 0.55 });
      S(gr, 'stop', { offset: '1', 'stop-color': D.leak, 'stop-opacity': 0 });
      S(g, 'path', { d: 'M' + (x + s * 0.18) + ' ' + (y + s * 0.5) + 'L' + (x + s) + ' ' + (y + s * 0.1) + 'L' + (x + s) + ' ' + (y + s * 0.9) + 'Z', fill: 'url(#' + id + ')' });
      S(g, 'rect', { x: x, y: y + s * 0.35, width: s * 0.2, height: s * 0.3, rx: 6, fill: D.reel });
      S(g, 'circle', { cx: x + s * 0.2, cy: y + s * 0.5, r: s * 0.09, fill: D.leak, 'fill-opacity': 0.8 });
      return {};
    }
  };
  var ORDER = cfg.objects.filter(function (k) { return DRAW[k]; });
  if (WORLD) FILM.scenes.forEach(function (sc, i) {
    if (sc.style !== NAME) return;
    C.slots(sc.decor_zones, ORDER.length, 14).forEach(function (b, k) {
      var kind = ORDER[k % ORDER.length], g = C.svg('g', {}, svg);
      world.push({ i: i, kind: kind, g: g, o: DRAW[kind](g, b[0], b[1], b[2]), start: sc.start });
    });
  });

  return {
    render: function (t) {
      var w = api.styleWeight(NAME, t);
      api.setStyle(layer, 'opacity', api.styleOpacity(NAME, t, layer).toFixed(3));
      api.setStyle(layer, 'visibility', w > 0.001 ? 'visible' : 'hidden');
      if (w <= 0.001) return;
      if (wins) wins.render(t);
      var f = api.frameOf(t), rnd = C.rng(f * 7919 + 13);       // сид — целый номер кадра, без модуля
      api.setStyle(grain, 'backgroundImage', 'url(' + tiles[Math.floor(rnd() * tiles.length)] + ')');
      api.setStyle(grain, 'backgroundPosition', Math.floor(rnd() * P.grain_size) + 'px ' + Math.floor(rnd() * P.grain_size) + 'px');
      api.setStyle(flick, 'opacity', (rnd() * P.flicker).toFixed(4));
      var jx = (rnd() * 2 - 1) * P.weave_px, jy = (rnd() * 2 - 1) * P.weave_px;
      var shift = -((t * P.strip_speed_in * PX) % pitch);
      strips.forEach(function (s) { api.setAttr(s, 'transform', 'translate(' + (shift + jx).toFixed(2) + ',' + jy.toFixed(2) + ')'); });
      var parts = [];
      if (rnd() < P.scratch_prob) {
        var sx = wx + rnd() * ww, len = wh * (0.3 + rnd() * 0.7), sy = wy + rnd() * (wh - len);
        parts.push('<path d="M' + sx.toFixed(1) + ' ' + sy.toFixed(1) + ' q' + ((rnd() - 0.5) * 6).toFixed(1) + ' ' + (len / 2).toFixed(1)
          + ' ' + ((rnd() - 0.5) * 4).toFixed(1) + ' ' + len.toFixed(1) + '" fill="none" stroke-width="' + (0.8 + rnd()).toFixed(2)
          + '" stroke-opacity="' + P.scratch_alpha + '"/>');
      }
      var nd = Math.floor(rnd() * (P.dust_max + 1));
      for (var k = 0; k < nd; k++) {
        parts.push('<ellipse cx="' + (wx + rnd() * ww).toFixed(1) + '" cy="' + (wy + rnd() * wh).toFixed(1) + '" rx="' + (1 + rnd() * 3).toFixed(1)
          + '" ry="' + (0.8 + rnd() * 2).toFixed(1) + '" stroke="none" fill-opacity="' + (P.dust_alpha * (0.4 + rnd() * 0.6)).toFixed(2) + '"/>');
      }
      var html = parts.join('');
      if (marks.__last !== html) { marks.innerHTML = html; marks.__last = html; }
      world.forEach(function (it) {
        var sw = api.sceneWeight(it.i, t), o = it.o, ts = t - it.start;
        api.setAttr(it.g, 'opacity', sw.toFixed(3));
        if (sw <= 0.001) return;
        if (it.kind === 'countdown') {     // 3 → 2 → 1 по секунде, дальше «1»; сектор обходит круг за секунду
          var n = Math.max(1, P.count_from - Math.floor(Math.max(0, ts))), a = (Math.max(0, ts) % 1) * Math.PI * 2;
          if (ts >= P.count_from) a = 0;
          if (o.num.textContent !== String(n)) o.num.textContent = String(n);
          var ex = o.cx + Math.sin(a) * o.r, ey = o.cy - Math.cos(a) * o.r;
          api.setAttr(o.sweep, 'd', a <= 0 ? '' : 'M' + o.cx + ' ' + o.cy + 'L' + o.cx + ' ' + (o.cy - o.r) + 'A' + o.r + ' ' + o.r + ' 0 '
            + (a > Math.PI ? 1 : 0) + ' 1 ' + ex.toFixed(1) + ' ' + ey.toFixed(1) + 'Z');
        } else if (it.kind === 'reel') {
          api.setAttr(o.rot, 'transform', 'rotate(' + (t / P.reel_turn_sec * 360 % 360).toFixed(2) + ' ' + o.cx + ' ' + o.cy + ')');
        } else if (it.kind === 'slate') {  // планка хлопает один раз в начале сцены
          var ang = ts < 0.6 ? -18 * (1 - api.clamp01(ts / 0.6)) : 0;
          api.setAttr(o.bar, 'transform', 'rotate(' + ang.toFixed(2) + ' ' + o.x + ' ' + o.top + ')');
        }
      });
    },
    probe: function (t) { return { style: NAME, weight: api.styleWeight(NAME, t), world: WORLD }; }
  };
});
