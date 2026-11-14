/* Лайн-бойл — плагин стиля (engine/video/styles/README.md). Всё в слое 'back' — под каркасом и содержанием.

   Мир (cfg.world): тёплый лист (decor.paper) с бумажной фактурой; два холма внизу кадра — дальний светлый
   и ближний со штриховкой чернилами; солнце и облака в верхнем поле; в зонах сцены (decor_zones) —
   домик, дерево, самолётик с пунктиром полёта, облако, заборчик, трава. Предметы «рисуются» линией по
   очереди с начала сцены. Каждая линия кипит: фильтр смещения получает новый сид на каждый рисунок
   (кадр / step_frames — «на двойках»), облака плывут и самолётик покачивается теми же ступенями.
   Всегда (и при style_brand_lock): кипящая чернильная обводка карточек и плашек, бумажная фактура.

   Сид рисунка — hash(id) + номер рисунка; кадр — чистая функция времени (V24). Текст не трогается. */
(window.StagePlugins = window.StagePlugins || []).push(function (FILM, api) {
  'use strict';
  var NAME = 'line-boil', cfg = api.styleConfig(NAME);
  if (!cfg) return null;
  var C = window.StyleCore, P = cfg.params, D = cfg.decor, PX = FILM.px, WORLD = cfg.world;
  var root = document.getElementById('root'), W = root.clientWidth, H = root.clientHeight;
  var STEP = P.step_frames || cfg.motion.step_frames || 2;
  var ink = WORLD ? D.ink : C.cssVar('--c-' + P.lock_ink_role);

  // ---------------------------------------------------------------- лист
  var layer = api.addLayer('lb-back', 'back');
  var sheet = document.createElement('div');
  sheet.className = 'layer';
  var paper = C.paperTile(256, P.paper_seed, { alpha: P.paper_alpha, fibres: 40 });
  if (WORLD) sheet.style.backgroundColor = D.paper;
  sheet.style.backgroundImage = 'url(' + paper + ')';
  sheet.style.backgroundSize = '256px 256px';
  layer.appendChild(sheet);

  var svg = C.svg('svg', { width: String(W), height: String(H), viewBox: '0 0 ' + W + ' ' + H }, layer);
  svg.style.position = 'absolute'; svg.style.left = '0'; svg.style.top = '0';
  // окна под текстом (StyleCore.textWindows): зоны текста — из раскладки сцены, а не из стиля; середина
  // окна — фон бренда, контраст надписи = контраст бренда на любом фильме (V21); оформление — языком мира
  var wins = WORLD ? C.textWindows(api, FILM, NAME, { parent: layer, pad: P.win_pad_px, css: { borderRadius: '10px' }, feather: 12 }) : null;
  var boil = C.boil('lb-boil', { scale: P.boil_scale, freq: P.boil_freq, octaves: 2 });
  var hatchFill = C.hatch('lb-hatch', { gap: P.hatch_gap_px, angle: -38, width: 1.3, color: WORLD ? D.hatch : ink,
                                        opacity: P.hatch_alpha });
  var worldG = C.svg('g', {}, svg), outG = C.svg('g', {}, svg);
  function boiled(parent) { return C.svg('g', { filter: 'url(#lb-boil)' }, parent); }

  function L(g, d, o) {                    // чернильная линия
    o = o || {};
    var a = { d: d, fill: o.fill || 'none', stroke: o.stroke || D.ink, 'stroke-width': String(o.w || P.ink_width),
              'stroke-linecap': 'round', 'stroke-linejoin': 'round' };
    if (o.dash) a['data-dash'] = o.dash;
    return C.svg('path', a, g);
  }
  function blob(cx, cy, r, rnd, n) {       // круглая крона / облачко: волна дуг по кругу
    var pts = [], k;
    n = n || 9;
    for (k = 0; k <= n; k++) {
      var a = k / n * Math.PI * 2, rr = r * (0.92 + rnd() * 0.12);
      pts.push([cx + Math.cos(a) * rr, cy + Math.sin(a) * rr]);
    }
    var d = 'M' + pts[0][0].toFixed(1) + ' ' + pts[0][1].toFixed(1);
    for (k = 1; k < pts.length; k++) {
      var m = (k - 0.5) / n * Math.PI * 2, bulge = r * 1.22;
      d += ' Q' + (cx + Math.cos(m) * bulge).toFixed(1) + ' ' + (cy + Math.sin(m) * bulge).toFixed(1) + ' '
        + pts[k][0].toFixed(1) + ' ' + pts[k][1].toFixed(1);
    }
    return d + ' Z';
  }
  function cloudPath(x, y, w) {            // облако: плоское дно и три шапки
    var h = w * 0.42, b = y + h;
    return 'M' + [x, b] + ' Q' + [x - w * 0.06, b - h * 0.5] + ' ' + [x + w * 0.16, b - h * 0.55]
      + ' Q' + [x + w * 0.22, y] + ' ' + [x + w * 0.46, y + h * 0.12]
      + ' Q' + [x + w * 0.66, y - h * 0.2] + ' ' + [x + w * 0.8, b - h * 0.5]
      + ' Q' + [x + w * 1.06, b - h * 0.5] + ' ' + [x + w, b] + ' Z';
  }

  // ---------------------------------------------------------------- предметы в зонах
  var DRAW = {
    house: function (g, x, y, s) {         // домик: стены, крыша, дверь, окно с переплётом, труба
      var l = x + s * 0.18, r = x + s * 0.82, t = y + s * 0.5, b = y + s * 0.96, o = [];
      o.push(L(g, 'M' + [l, t] + ' L' + [l, b] + ' L' + [r, b] + ' L' + [r, t] + ' Z', { fill: D.wall }));
      o.push(L(g, 'M' + [r - s * 0.16, t - s * 0.2] + ' v' + (-s * 0.12) + ' h' + s * 0.09 + ' v' + s * 0.2, { fill: D.wall }));
      o.push(L(g, 'M' + [l - s * 0.08, t + 3] + ' L' + [x + s / 2, y + s * 0.16] + ' L' + [r + s * 0.08, t + 3] + ' Z', { fill: D.roof }));
      o.push(L(g, 'M' + [x + s * 0.3, b] + ' v' + (-s * 0.26) + ' h' + s * 0.14 + ' v' + s * 0.26, { fill: D.roof }));
      o.push(L(g, 'M' + [x + s * 0.56, t + s * 0.1] + ' h' + s * 0.16 + ' v' + s * 0.15 + ' h' + (-s * 0.16) + ' Z M'
               + [x + s * 0.64, t + s * 0.1] + ' v' + s * 0.15 + ' M' + [x + s * 0.56, t + s * 0.175] + ' h' + s * 0.16,
               { fill: D.sun }));
      return o;
    },
    tree: function (g, x, y, s, rnd) {     // круглое дерево: ствол и крона со штриховкой тени
      var cx = x + s / 2, o = [];
      o.push(L(g, 'M' + [cx - s * 0.04, y + s * 0.97] + ' L' + [cx - s * 0.03, y + s * 0.55] + ' M' + [cx + s * 0.04, y + s * 0.97]
               + ' L' + [cx + s * 0.03, y + s * 0.55], { stroke: D.ink }));
      o.push(L(g, blob(cx, y + s * 0.38, s * 0.27, rnd), { fill: D.leaf }));
      o.push(L(g, 'M' + [cx + s * 0.02, y + s * 0.6] + ' Q' + [cx + s * 0.26, y + s * 0.58] + ' ' + [cx + s * 0.27, y + s * 0.36],
               { fill: hatchFill, w: 1.2 }));
      return o;
    },
    plane: function (g, x, y, s) {         // бумажный самолётик и пунктир его полёта
      var o = [];
      o.push(L(g, 'M' + [x + s * 0.02, y + s * 0.9] + ' C' + [x + s * 0.3, y + s * 0.98] + ' ' + [x + s * 0.2, y + s * 0.5] + ' '
               + [x + s * 0.5, y + s * 0.56], { w: 1.6, dash: '6 9' }));
      o.push(L(g, 'M' + [x + s * 0.5, y + s * 0.56] + ' L' + [x + s * 0.96, y + s * 0.28] + ' L' + [x + s * 0.66, y + s * 0.66] + ' Z',
               { fill: D.cloud }));
      o.push(L(g, 'M' + [x + s * 0.96, y + s * 0.28] + ' L' + [x + s * 0.6, y + s * 0.44] + ' L' + [x + s * 0.66, y + s * 0.66] + ' Z',
               { fill: D.hill }));
      return o;
    },
    cloud: function (g, x, y, s) {
      return [L(g, cloudPath(x + s * 0.05, y + s * 0.3, s * 0.9), { fill: D.cloud })];
    },
    fence: function (g, x, y, s) {         // заборчик из штакетин на двух жердях
      var o = [], n = 6, b = y + s * 0.95, top = y + s * 0.55, d = '';
      for (var k = 0; k < n; k++) {
        var px = x + s * (0.06 + k * 0.16);
        d += 'M' + [px, b] + ' V' + (top + s * 0.05) + ' L' + [px + s * 0.05, top] + ' L' + [px + s * 0.1, top + s * 0.05] + ' V' + b + ' Z';
      }
      o.push(L(g, d, { fill: D.wall }));
      o.push(L(g, 'M' + [x, top + s * 0.14] + ' H' + (x + s) + ' M' + [x, b - s * 0.12] + ' H' + (x + s), { w: 2 }));
      return o;
    },
    grass: function (g, x, y, s, rnd) {    // кусты травы: пучки штрихов и куст-шапка
      var o = [], d = '';
      for (var k = 0; k < 4; k++) {
        var cx = x + s * (0.12 + k * 0.25), b = y + s * 0.96;
        for (var j = -2; j <= 2; j++) d += 'M' + [cx + j * 3, b] + ' Q' + [cx + j * 6, b - s * 0.1] + ' ' + [cx + j * s * 0.04 + (rnd() - 0.5) * 6, b - s * (0.16 + rnd() * 0.08)];
      }
      o.push(L(g, d, { w: 1.6 }));
      o.push(L(g, blob(x + s * 0.5, y + s * 0.78, s * 0.13, rnd, 7), { fill: D.leaf_dark }));
      return o;
    }
  };
  var ORDER = cfg.objects.filter(function (k) { return DRAW[k]; });

  var world = [], drift = [], hills = null;
  if (WORLD) {
    // холмы: дальний — светлый, ближний — со штриховкой; низ — над нижней линией каркаса
    var top = P.hills_top_in * PX, bot = P.hills_bottom_in * PX;
    hills = boiled(worldG);
    L(hills, 'M0 ' + (top + 40) + ' Q' + W * 0.22 + ' ' + (top - 30) + ' ' + W * 0.45 + ' ' + (top + 30) + ' T' + W * 0.8 + ' ' + (top - 10)
      + ' T' + W + ' ' + (top + 20) + ' V' + bot + ' H0 Z', { fill: D.hill_far, stroke: D.ink });
    L(hills, 'M0 ' + (top + 150) + ' Q' + W * 0.3 + ' ' + (top + 60) + ' ' + W * 0.55 + ' ' + (top + 140) + ' T' + W + ' ' + (top + 120)
      + ' V' + bot + ' H0 Z', { fill: D.hill, stroke: D.ink });
    L(hills, 'M' + W * 0.6 + ' ' + (top + 160) + ' Q' + W * 0.8 + ' ' + (top + 100) + ' ' + W + ' ' + (top + 120) + ' V' + bot + ' H'
      + W * 0.6 + ' Z', { fill: hatchFill, stroke: 'none' });
    L(hills, 'M0 ' + bot + ' H' + W, { w: 2 });
    // солнце и облака в верхнем поле (слева: справа трекер)
    var sun = boiled(worldG), sr = 40, sx = 190, sy = 100, rays = '';
    L(sun, 'M' + (sx + sr) + ' ' + sy + ' A' + sr + ' ' + sr + ' 0 1 1 ' + (sx + sr - 0.1) + ' ' + (sy - 3), { fill: D.sun });
    for (var k = 0; k < 10; k++) {
      var a = k / 10 * Math.PI * 2;
      rays += 'M' + (sx + Math.cos(a) * sr * 1.3).toFixed(1) + ' ' + (sy + Math.sin(a) * sr * 1.3).toFixed(1) + ' L'
        + (sx + Math.cos(a) * sr * 1.75).toFixed(1) + ' ' + (sy + Math.sin(a) * sr * 1.75).toFixed(1);
    }
    L(sun, rays, { w: 2.2 });
    [[430, 70, 190], [760, 110, 140]].forEach(function (c, i) {
      var g = boiled(worldG);
      L(g, cloudPath(c[0], c[1], c[2]), { fill: D.cloud });
      drift.push({ g: g, k: i });
    });
    FILM.scenes.forEach(function (sc, i) {
      if (sc.style !== NAME) return;
      var rnd = C.rng(C.hash(sc.id));
      C.slots(sc.decor_zones, ORDER.length, 14).forEach(function (b, k) {
        var kind = ORDER[k % ORDER.length], g = boiled(worldG);
        world.push({ i: i, g: g, kind: kind, paths: DRAW[kind](g, b[0], b[1], b[2], rnd), t0: sc.start + P.draw_from + k * P.draw_gap });
      });
    });
  }

  // ---------------------------------------------------------------- кипящая обводка содержания (и в замке)
  function inStyle(el) { var s = el.closest('.scene'); return s && s.getAttribute('data-style') === NAME; }
  var items = [];
  (P.outline || []).forEach(function (sel) {
    document.querySelectorAll('#content ' + sel).forEach(function (el) {
      if (!inStyle(el)) return;
      var g = C.svg('g', {}, outG);
      items.push({ el: el, g: g, seed: C.hash(el.id || (el.parentNode && el.parentNode.id) || 'x'),
                   p1: C.svg('path', { fill: 'none', stroke: ink, 'stroke-width': String(P.outline_width), 'stroke-linecap': 'round',
                                       'stroke-opacity': WORLD ? '1' : String(P.lock_alpha) }, g),
                   p2: C.svg('path', { fill: 'none', stroke: ink, 'stroke-width': String(P.outline_width * 0.45), 'stroke-linecap': 'round',
                                       'stroke-opacity': String(WORLD ? 0.7 : P.lock_alpha * 0.6) }, g) });
    });
  });
  function opacityOf(el) {
    var o = 1;
    for (var n = el; n && n !== root; n = n.parentElement) {
      var v = parseFloat(n.style.opacity);
      if (!isNaN(v)) o *= v;
      if (n.style.visibility === 'hidden') return 0;
    }
    return o;
  }

  var lastDrawing = null;
  return {
    render: function (t) {
      var w = api.styleWeight(NAME, t);
      api.setStyle(layer, 'opacity', api.styleOpacity(NAME, t, layer).toFixed(3));
      api.setStyle(layer, 'visibility', w > 0.001 ? 'visible' : 'hidden');
      if (w <= 0.001) return;
      if (wins) wins.render(t);
      var drawing = Math.floor(api.frameOf(t) / STEP), ts = api.stepTime(t, STEP);
      boil.set(drawing);
      var o0 = root.getBoundingClientRect();
      items.forEach(function (it) {
        var o = opacityOf(it.el);
        api.setAttr(it.g, 'opacity', o.toFixed(3));
        if (o <= 0.001) return;
        var r = it.el.getBoundingClientRect(), x = r.left - o0.left, y = r.top - o0.top, gp = P.outline_gap_px;
        var rnd = C.rng(it.seed * 31 + drawing), j = P.jitter_px;
        api.setAttr(it.p1, 'd', C.roughRect(x - gp, y - gp, r.width + 2 * gp, r.height + 2 * gp, rnd, j));
        api.setAttr(it.p2, 'd', C.roughRect(x - gp + 2, y - gp + 2, r.width + 2 * gp - 4, r.height + 2 * gp - 4, rnd, j * 1.4));
      });
      drift.forEach(function (c) {
        api.setAttr(c.g, 'transform', 'translate(' + (Math.sin(ts * 0.35 + c.k * 2) * P.cloud_drift_px).toFixed(1) + ',0)');
      });
      world.forEach(function (o) {
        var sw = api.sceneWeight(o.i, t);
        api.setAttr(o.g, 'opacity', sw.toFixed(3));
        if (sw <= 0.001) return;
        var p = api.clamp01((ts - o.t0) / P.draw_in);
        C.drawOn(o.paths, p);
        api.setAttr(o.g, 'fill-opacity', api.clamp01(p * 1.6 - 0.4).toFixed(3));
        if (o.kind === 'plane') {
          var ph = ts / P.plane_loop_sec * Math.PI * 2;
          api.setAttr(o.g, 'transform', 'translate(' + (Math.cos(ph) * 10).toFixed(1) + ',' + (Math.sin(ph * 2) * 8).toFixed(1) + ')');
        } else if (o.kind === 'cloud') {
          api.setAttr(o.g, 'transform', 'translate(' + (Math.sin(ts * 0.4) * 14).toFixed(1) + ',0)');
        }
      });
      lastDrawing = drawing;
    },
    probe: function (t) { return { style: NAME, weight: api.styleWeight(NAME, t), drawing: lastDrawing, world: WORLD }; }
  };
});
