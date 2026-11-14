/* Скетчбук — плагин стиля (engine/video/styles/README.md). Всё в слое 'back' — под каркасом и содержанием.

   Мир (cfg.world): тёплый клетчатый лист (decor.paper, сетка decor.grid / grid_major, поле decor.margin) +
   бумажная фактура; карандашные рисунки от руки в зонах сцены (decor_zones): куб в перспективе с
   подписью, самолётик с пунктиром полёта, цветы, солнце, облако, домик, стрелка-пометка; жёлтый карандаш
   на поле листа. Рисунки «рисуются» линией по очереди с начала сцены и кипят «на двойках».
   Всегда (и при style_brand_lock): сетка и бумага поверх фирменного фона, карандашная обводка карточек
   и плашек со штрихованной тенью, обведённые маркеры, подчёркивание заголовка.

   Рисунок = номер кадра / step_frames; сид — hash(id) + номер рисунка. Текст не трогается. */
(window.StagePlugins = window.StagePlugins || []).push(function (FILM, api) {
  'use strict';
  var NAME = 'sketchbook', cfg = api.styleConfig(NAME);
  if (!cfg) return null;
  var C = window.StyleCore, P = cfg.params, D = cfg.decor, PX = FILM.px, WORLD = cfg.world;
  var root = document.getElementById('root'), W = root.clientWidth, H = root.clientHeight;
  var scenes = api.styleScenes(NAME);
  var pencil = WORLD ? D.pencil : C.cssVar('--c-ink');

  // ---------------------------------------------------------------- лист
  var layer = api.addLayer('sk-back', 'back');
  var sheet = document.createElement('div');
  sheet.className = 'layer';
  var cell = Math.round(P.grid_cell_in * PX), grid, mc, malpha;
  if (WORLD) {
    grid = C.gridPaper(cell, D.grid, { width: 1, major: P.grid_major, majorColor: D.grid_major });
    mc = C.rgbOf(D.margin); malpha = 1;
    sheet.style.backgroundColor = D.paper;
  } else {
    var gc = C.rgbOf(C.cssVar('--c-' + P.lock_grid_role)).join(',');
    grid = C.gridPaper(cell, 'rgba(' + gc + ',' + P.lock_grid_alpha + ')',
                       { width: 1, major: P.grid_major, majorColor: 'rgba(' + gc + ',' + P.lock_major_alpha + ')' });
    mc = C.rgbOf(C.cssVar('--c-' + P.lock_margin_role)); malpha = P.margin_alpha;
  }
  var paper = C.paperTile(256, P.paper_seed, { alpha: P.paper_alpha });
  var mx = Math.round(P.margin_x_in * PX), mrgb = 'rgba(' + mc.join(',') + ',' + malpha + ')';
  sheet.style.backgroundImage = 'url(' + paper + '),linear-gradient(to right, transparent ' + mx + 'px, ' + mrgb + ' ' + mx
    + 'px, ' + mrgb + ' ' + (mx + 2) + 'px, transparent ' + (mx + 2) + 'px),' + grid.image;
  sheet.style.backgroundSize = '256px 256px,100% 100%,' + grid.size;
  layer.appendChild(sheet);

  var svg = C.svg('svg', { width: String(W), height: String(H), viewBox: '0 0 ' + W + ' ' + H }, layer);
  svg.style.position = 'absolute'; svg.style.left = '0'; svg.style.top = '0';
  // окна под текстом (StyleCore.textWindows): зоны текста — из раскладки сцены, а не из стиля; середина
  // окна — фон бренда, контраст надписи = контраст бренда на любом фильме (V21); оформление — языком мира
  var wins = WORLD ? C.textWindows(api, FILM, NAME, { parent: layer, pad: P.win_pad_px, before: svg, css: { borderRadius: '6px' }, feather: 10 }) : null;
  var hatchFill = C.hatch('sk-hatch', { gap: P.hatch_gap_px, angle: 45, width: 1.2, color: pencil, opacity: P.hatch_alpha });
  var boil = C.boil('sk-boil', { scale: P.boil_scale, freq: P.boil_freq, octaves: 2 });

  // ---------------------------------------------------------------- обводка содержания
  function inStyle(el) { var s = el.closest('.scene'); return s && s.getAttribute('data-style') === NAME; }
  var items = [];
  function add(el, shape) {
    var g = C.svg('g', {}, svg), seed = C.hash(el.id || (el.parentNode && el.parentNode.id) || 'x');
    var shadow = shape === 'rect' ? C.svg('rect', { fill: hatchFill }, g) : null;
    var p1 = C.svg('path', { fill: 'none', stroke: pencil, 'stroke-width': String(P.pencil_width), 'stroke-linecap': 'round',
                             'stroke-opacity': String(P.pencil_alpha) }, g);
    var p2 = C.svg('path', { fill: 'none', stroke: pencil, 'stroke-width': String(P.pencil_width * 0.6), 'stroke-linecap': 'round',
                             'stroke-opacity': String(P.pencil_alpha * 0.6) }, g);
    items.push({ el: el, shape: shape, g: g, shadow: shadow, p1: p1, p2: p2, seed: seed });
  }
  (P.outline || []).forEach(function (sel) {
    document.querySelectorAll('#content ' + sel).forEach(function (el) { if (inStyle(el)) add(el, 'rect'); });
  });
  (P.circle || []).forEach(function (sel) {
    document.querySelectorAll('#content ' + sel).forEach(function (el) { if (inStyle(el)) add(el, 'circle'); });
  });
  var titles = [];
  if (P.title_underline) scenes.forEach(function (id) {
    var t = document.getElementById('title--' + id), span = t && t.querySelector('.t');
    if (!span) return;
    titles.push({ frame: t, span: span, seed: C.hash('title--' + id),
                  path: C.svg('path', { fill: 'none', stroke: pencil, 'stroke-width': '2.4', 'stroke-linecap': 'round',
                                        'stroke-opacity': String(P.pencil_alpha) }, svg) });
  });

  // ---------------------------------------------------------------- мир: рисунки от руки
  var world = [];          // {scene index, g, paths, t0, bob}
  function P_(g, d, o) {   // карандашная линия
    o = o || {};
    return C.svg('path', { d: d, fill: o.fill || 'none', 'fill-opacity': String(o.fo != null ? o.fo : 1), stroke: o.stroke || D.pencil,
                           'stroke-width': String(o.w || 2.2), 'stroke-linecap': 'round', 'stroke-linejoin': 'round',
                           'data-dash': o.dash || '' }, g);
  }
  function note(g, x, y, str, size) {
    var t = C.text(g, x, y, str, { fill: D.graphite, 'font-size': String(size || 18) });
    t.style.fontFamily = cfg.fonts.decor || cfg.fonts.title;
    return t;
  }
  var DRAW = {
    cube: function (g, x, y, s) {          // куб в перспективе на две точки + штриховка грани + подпись
      var cx = x + s * 0.5, top = y + s * 0.12, h = s * 0.42, wl = s * 0.32, wr = s * 0.36, dy = s * 0.12;
      var a = [cx, top + dy], l = [cx - wl, top], r = [cx + wr, top], b = [cx, top + dy * 2 - 2];
      var out = [];
      out.push(P_(g, 'M' + l + ' L' + [cx, top - dy * 0.9] + ' L' + r + ' L' + a + ' Z'));
      out.push(P_(g, 'M' + l + ' L' + [l[0], l[1] + h] + ' L' + [a[0], a[1] + h] + ' L' + [r[0], r[1] + h] + ' L' + r));
      out.push(P_(g, 'M' + a + ' L' + [a[0], a[1] + h]));
      out.push(P_(g, 'M' + [r[0], r[1]] + ' L' + [a[0], a[1]] + ' L' + [a[0], a[1] + h] + ' L' + [r[0], r[1] + h] + ' Z',
                  { fill: hatchFill, w: 0.6 }));
      out.push(P_(g, 'M' + [x + 4, top + h * 1.25] + ' L' + [x + s - 4, top + h * 1.25], { w: 1, dash: '6 6' }));
      note(g, x + s * 0.08, y + s * 0.95, 'перспектива, 2 точки', Math.max(13, s * 0.075));
      void b;
      return out;
    },
    plane: function (g, x, y, s) {         // бумажный самолётик и пунктир полёта
      var o = [];
      o.push(P_(g, 'M' + [x + s * 0.05, y + s * 0.85] + ' C' + [x + s * 0.3, y + s * 0.95] + ' ' + [x + s * 0.35, y + s * 0.5] + ' '
                + [x + s * 0.55, y + s * 0.55], { w: 1.4, dash: '7 8' }));
      o.push(P_(g, 'M' + [x + s * 0.55, y + s * 0.55] + ' L' + [x + s * 0.95, y + s * 0.3] + ' L' + [x + s * 0.68, y + s * 0.62] + ' Z'));
      o.push(P_(g, 'M' + [x + s * 0.95, y + s * 0.3] + ' L' + [x + s * 0.62, y + s * 0.42] + ' L' + [x + s * 0.68, y + s * 0.62]));
      o.push(P_(g, 'M' + [x + s * 0.62, y + s * 0.42] + ' L' + [x + s * 0.55, y + s * 0.55], { w: 1.4 }));
      return o;
    },
    flowers: function (g, x, y, s, rnd) {  // три цветка на стеблях
      var o = [];
      for (var k = 0; k < 3; k++) {
        var cx = x + s * (0.2 + k * 0.3), cy = y + s * (0.35 + 0.12 * (k % 2)), r = s * 0.09;
        o.push(P_(g, 'M' + [cx, cy + r] + ' Q' + [cx - s * 0.04, y + s * 0.7] + ' ' + [cx + s * 0.02, y + s * 0.97], { stroke: D.pencil }));
        o.push(P_(g, 'M' + [cx, y + s * 0.78] + ' q' + [-s * 0.1, -s * 0.03] + ' ' + [-s * 0.12, -s * 0.12], { fill: D.leaf, fo: 0.6, w: 1.6 }));
        for (var p = 0; p < 6; p++) {
          var a = p / 6 * Math.PI * 2 + rnd() * 0.3, px = cx + Math.cos(a) * r * 1.3, py = cy + Math.sin(a) * r * 1.3;
          o.push(P_(g, C.roughEllipse(px, py, r * 0.7, r * 0.7, rnd, 1.2), { w: 1.5 }));
        }
        o.push(P_(g, C.roughEllipse(cx, cy, r * 0.55, r * 0.55, rnd, 1), { fill: D.sun, fo: 0.8, w: 1.5 }));
      }
      return o;
    },
    sun: function (g, x, y, s, rnd) {      // солнце: круг и лучи
      var cx = x + s / 2, cy = y + s / 2, r = s * 0.2, o = [P_(g, C.roughEllipse(cx, cy, r, r, rnd, 2), { fill: D.sun, fo: 0.75 })];
      for (var k = 0; k < 12; k++) {
        var a = k / 12 * Math.PI * 2, r1 = r * 1.35, r2 = r * (k % 2 ? 1.9 : 2.2);
        o.push(P_(g, 'M' + [cx + Math.cos(a) * r1, cy + Math.sin(a) * r1] + ' L' + [cx + Math.cos(a) * r2, cy + Math.sin(a) * r2], { w: 1.8 }));
      }
      return o;
    },
    cloud: function (g, x, y, s) {         // облако из дуг
      var b = y + s * 0.62, l = x + s * 0.08, r = x + s * 0.92;
      return [P_(g, 'M' + [l, b] + ' Q' + [l - s * 0.06, b - s * 0.18] + ' ' + [l + s * 0.14, b - s * 0.2]
                 + ' Q' + [l + s * 0.2, b - s * 0.44] + ' ' + [l + s * 0.42, b - s * 0.34]
                 + ' Q' + [l + s * 0.6, b - s * 0.52] + ' ' + [l + s * 0.7, b - s * 0.28]
                 + ' Q' + [r + s * 0.06, b - s * 0.28] + ' ' + [r, b] + ' Z', { fill: '#FFFFFF', fo: 0.85 })];
    },
    house: function (g, x, y, s) {         // домик: стены, крыша, дверь, окно
      var l = x + s * 0.2, r = x + s * 0.8, t = y + s * 0.45, b = y + s * 0.92;
      return [P_(g, 'M' + [l, t] + ' L' + [l, b] + ' L' + [r, b] + ' L' + [r, t]),
              P_(g, 'M' + [l - s * 0.07, t + 2] + ' L' + [x + s / 2, y + s * 0.14] + ' L' + [r + s * 0.07, t + 2] + ' Z', { fill: D.roof, fo: 0.7 }),
              P_(g, 'M' + [x + s * 0.42, b] + ' L' + [x + s * 0.42, b - s * 0.24] + ' L' + [x + s * 0.55, b - s * 0.24] + ' L' + [x + s * 0.55, b]),
              P_(g, 'M' + [x + s * 0.62, t + s * 0.1] + ' h' + s * 0.12 + ' v' + s * 0.12 + ' h' + (-s * 0.12) + ' Z M' + [x + s * 0.68, t + s * 0.1]
                 + ' v' + s * 0.12, { w: 1.6 })];
    },
    arrow: function (g, x, y, s) {         // стрелка-пометка с подписью
      var o = [P_(g, 'M' + [x + s * 0.1, y + s * 0.3] + ' C' + [x + s * 0.5, y + s * 0.1] + ' ' + [x + s * 0.8, y + s * 0.4] + ' '
                  + [x + s * 0.78, y + s * 0.8]),
               P_(g, 'M' + [x + s * 0.66, y + s * 0.68] + ' L' + [x + s * 0.78, y + s * 0.82] + ' L' + [x + s * 0.88, y + s * 0.66])];
      note(g, x + s * 0.02, y + s * 0.2, 'смотри сюда', Math.max(13, s * 0.09));
      return o;
    }
  };
  var ORDER = cfg.objects.filter(function (k) { return DRAW[k]; });
  if (WORLD) {
    FILM.scenes.forEach(function (sc, i) {
      if (sc.style !== NAME) return;
      var sl = C.slots(sc.decor_zones, ORDER.length, 14), rnd = C.rng(C.hash(sc.id));
      sl.forEach(function (b, k) {
        var kind = ORDER[k % ORDER.length], g = C.svg('g', { filter: 'url(#sk-boil)' }, svg);
        world.push({ i: i, g: g, paths: DRAW[kind](g, b[0], b[1], b[2], rnd), t0: sc.start + P.draw_from + k * P.draw_gap,
                     bob: kind === 'plane' });
      });
      // жёлтый карандаш на поле листа — у каждой сцены стиля
      var gp = C.svg('g', { transform: 'rotate(-4 300 46)' }, svg);
      var body = [C.svg('path', { d: 'M60 34 h420 v26 h-420 Z', fill: D.pencil_body, stroke: D.pencil, 'stroke-width': '1.6' }, gp),
                  C.svg('path', { d: 'M480 34 L530 47 L480 60 Z', fill: D.pencil_wood, stroke: D.pencil, 'stroke-width': '1.6' }, gp),
                  C.svg('path', { d: 'M516 43.5 L530 47 L516 50.5 Z', fill: D.pencil }, gp),
                  C.svg('path', { d: 'M60 42.5 h420 M60 51.5 h420', stroke: D.pencil, 'stroke-width': '0.8', 'stroke-opacity': '0.5' }, gp)];
      world.push({ i: i, g: gp, paths: [], t0: -1, bob: false, body: body });
    });
  }

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
      var drawing = Math.floor(api.frameOf(t) / P.step_frames);    // рисунок «на двойках»
      boil.set(drawing);
      var o0 = root.getBoundingClientRect();
      items.forEach(function (it) {
        var o = opacityOf(it.el);
        api.setAttr(it.g, 'opacity', o.toFixed(3));
        if (o <= 0.001) return;
        var r = it.el.getBoundingClientRect(), x = r.left - o0.left, y = r.top - o0.top, gp = P.outline_gap_px;
        var rnd = C.rng(it.seed * 31 + drawing), j = P.jitter_px;
        if (it.shape === 'rect') {
          api.setAttr(it.p1, 'd', C.roughRect(x - gp, y - gp, r.width + 2 * gp, r.height + 2 * gp, rnd, j));
          api.setAttr(it.p2, 'd', C.roughRect(x - gp + 1, y - gp + 1, r.width + 2 * gp - 2, r.height + 2 * gp - 2, rnd, j * 1.3));
          api.setAttr(it.shadow, 'x', (x + P.shadow_px[0]).toFixed(1)); api.setAttr(it.shadow, 'y', (y + P.shadow_px[1]).toFixed(1));
          api.setAttr(it.shadow, 'width', r.width.toFixed(1)); api.setAttr(it.shadow, 'height', r.height.toFixed(1));
        } else {
          var cx = x + r.width / 2, cy = y + r.height / 2, rr = r.width / 2 + gp;
          api.setAttr(it.p1, 'd', C.roughEllipse(cx, cy, rr, rr, rnd, j));
          api.setAttr(it.p2, 'd', C.roughEllipse(cx, cy, rr + 1.5, rr + 1, rnd, j * 1.3));
        }
      });
      titles.forEach(function (tt) {
        var o = parseFloat(tt.frame.style.opacity) || 0;
        api.setAttr(tt.path, 'opacity', o.toFixed(3));
        if (o <= 0.001) return;
        var rg = document.createRange(); rg.selectNodeContents(tt.span);
        var r = rg.getBoundingClientRect(), x = r.left - o0.left, y = r.bottom - o0.top + 2, rnd = C.rng(tt.seed + drawing * 7);
        var dy = function () { return (rnd() * 2 - 1) * 1.6; };
        api.setAttr(tt.path, 'd', 'M' + (x - 6).toFixed(1) + ' ' + (y + dy()).toFixed(1) + ' Q' + (x + r.width * 0.5).toFixed(1) + ' '
          + (y + 3 + dy()).toFixed(1) + ' ' + (x + r.width + 10).toFixed(1) + ' ' + (y - 2 + dy()).toFixed(1));
      });
      world.forEach(function (o) {
        var sw = api.sceneWeight(o.i, t);
        api.setAttr(o.g, 'opacity', sw.toFixed(3));
        if (sw <= 0.001) return;
        var ts = api.stepTime(t, P.step_frames);                    // рисуется «на двойках»
        if (o.paths.length) C.drawOn(o.paths, o.t0 < 0 ? 1 : api.clamp01((ts - o.t0) / P.draw_in));
        if (o.bob) {
          var rr = C.rng(drawing * 13 + 5);
          api.setAttr(o.g, 'transform', 'translate(' + ((rr() - 0.5) * 3).toFixed(1) + ',' + (Math.sin(ts * 2.2) * 6).toFixed(1) + ')');
        }
      });
      lastDrawing = drawing;
    },
    probe: function (t) { return { style: NAME, weight: api.styleWeight(NAME, t), drawing: lastDrawing, world: WORLD }; }
  };
});
