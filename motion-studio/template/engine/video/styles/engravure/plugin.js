/* Гравюра — плагин стиля (engine/video/styles/README.md). Всё в слое 'back' — под каркасом и содержанием.

   Мир (cfg.world): пергамент (decor.parchment) с бумажной фактурой в двойной рамке с угольниками; лента-
   картуш с раздвоенными концами под заголовком сцены (ширина — по строке заголовка, непрозрачность — его);
   море из параллельных волнистых линий под правой зоной; в зонах сцены (decor_zones) — маяк с качающимся
   лучом, парусник, солнце с лучами-штрихами (медленно поворачивается), роза ветров, чайки, гусиное перо
   с чернильницей. Предметы прорезаются линией по очереди, тени — штриховкой; движение ровное, без отскоков.
   Всегда (и при style_brand_lock): тень карточек и плашек перекрёстной штриховкой, тонкая рамка, фактура.

   Кадр — чистая функция времени (V24): случайности нет, всё от t. Текст не трогается. */
(window.StagePlugins = window.StagePlugins || []).push(function (FILM, api) {
  'use strict';
  var NAME = 'engravure', cfg = api.styleConfig(NAME);
  if (!cfg) return null;
  var C = window.StyleCore, P = cfg.params, D = cfg.decor, PX = FILM.px, WORLD = cfg.world;
  var root = document.getElementById('root'), W = root.clientWidth, H = root.clientHeight;
  var etch = WORLD ? D.etch : C.cssVar('--c-' + P.lock_role), lockA = WORLD ? 1 : P.lock_alpha;

  var layer = api.addLayer('eg-back', 'back');
  var sheet = document.createElement('div');
  sheet.className = 'layer';
  if (WORLD) sheet.style.backgroundColor = D.parchment;
  sheet.style.backgroundImage = 'url(' + C.paperTile(256, 23, { alpha: WORLD ? 0.07 : 0.04, fibres: 30, blot: 0.75 }) + ')';
  sheet.style.backgroundSize = '256px 256px';
  layer.appendChild(sheet);
  var svg = C.svg('svg', { width: String(W), height: String(H), viewBox: '0 0 ' + W + ' ' + H }, layer);
  svg.style.position = 'absolute'; svg.style.left = '0'; svg.style.top = '0';
  // окна под текстом (StyleCore.textWindows): зоны текста — из раскладки сцены, а не из стиля; середина
  // окна — фон бренда, контраст надписи = контраст бренда на любом фильме (V21); оформление — языком мира
  var wins = WORLD ? C.textWindows(api, FILM, NAME, { parent: layer, pad: P.win_pad_px, css: { border: '1.2px solid ' + D.etch, boxShadow: 'inset 0 0 0 4px ' + C.cssVar('--c-paper') + ', inset 0 0 0 5px ' + D.etch_soft } }) : null;
  var hatch = C.hatch('eg-hatch', { gap: P.hatch_gap_px, angle: 45, width: 1, color: etch, opacity: P.hatch_alpha * lockA });
  var hatch2 = C.hatch('eg-hatch2', { gap: P.cross_gap_px, angle: -45, width: 0.9, color: etch, opacity: P.hatch_alpha * lockA });
  var hatchH = C.hatch('eg-hatch-h', { gap: 3, angle: 0, width: 0.8, color: etch, opacity: 0.6 * lockA });

  function L(g, d, o) {
    o = o || {};
    return C.svg('path', { d: d, fill: o.fill || 'none', stroke: o.stroke || etch, 'stroke-width': String(o.w || P.line_w),
                           'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'stroke-opacity': String(o.so != null ? o.so : lockA) }, g);
  }
  function circ(cx, cy, r) {
    return 'M' + (cx + r) + ' ' + cy + ' A' + r + ' ' + r + ' 0 1 1 ' + (cx + r) + ' ' + (cy - 0.01) + ' Z';
  }

  // ---------------------------------------------------------------- рамка листа (и в замке — тонкая)
  var fr = C.svg('g', {}, svg);
  P.frame_inset_px.forEach(function (m, k) {
    L(fr, 'M' + m + ' ' + m + ' H' + (W - m) + ' V' + (H - m) + ' H' + m + ' Z', { w: k ? 1 : 2.4, so: WORLD ? 1 : lockA });
  });
  if (WORLD) {
    var c = P.corner_px, m2 = P.frame_inset_px[1] + 6;
    [[m2, m2, 1, 1], [W - m2, m2, -1, 1], [m2, H - m2, 1, -1], [W - m2, H - m2, -1, -1]].forEach(function (q) {
      L(fr, 'M' + q[0] + ' ' + (q[1] + q[3] * c) + ' V' + q[1] + ' H' + (q[0] + q[2] * c)
        + ' M' + (q[0] + q[2] * 8) + ' ' + (q[1] + q[3] * 8) + ' L' + (q[0] + q[2] * 22) + ' ' + (q[1] + q[3] * 22), { w: 2 });
    });
  }

  // ---------------------------------------------------------------- тени карточек штриховкой
  function inStyle(el) { var s = el.closest('.scene'); return s && s.getAttribute('data-style') === NAME; }
  var shadows = [];
  (P.outline || []).forEach(function (sel) {
    document.querySelectorAll('#content ' + sel).forEach(function (el) {
      if (!inStyle(el)) return;
      var g = C.svg('g', {}, svg);
      shadows.push({ el: el, g: g, a: C.svg('rect', { fill: hatch }, g), b: C.svg('rect', { fill: hatch2 }, g),
                     o: C.svg('rect', { fill: 'none', stroke: etch, 'stroke-width': '1.2', 'stroke-opacity': String(0.8 * lockA) }, g) });
    });
  });

  // ---------------------------------------------------------------- картуш под заголовком
  var ribbons = [];
  if (WORLD) api.styleScenes(NAME).forEach(function (id) {
    var t = document.getElementById('title--' + id), span = t && t.querySelector('.t');
    if (!span) return;
    var g = C.svg('g', {}, svg);
    ribbons.push({ frame: t, span: span, g: g,
                   tails: L(g, '', { fill: D.sea }), tailHatch: L(g, '', { fill: hatchH, w: 0 }),
                   folds: L(g, '', { fill: D.etch_soft, w: 1 }), body: L(g, '', { fill: D.ribbon, w: 2 }),
                   rule: L(g, '', { w: 0.8 }) });
  });

  // ---------------------------------------------------------------- предметы мира
  var DRAW = {
    lighthouse: function (g, x, y, s) {    // башня с полосами, галерея, фонарь, купол, камни; луч — отдельно
      var cx = x + s * 0.5, b = y + s * 0.98, tw = s * 0.11, bw = s * 0.17, top = y + s * 0.34, o = [];
      o.push(L(g, 'M' + [cx - bw, b] + ' L' + [cx - tw, top] + ' L' + [cx + tw, top] + ' L' + [cx + bw, b] + ' Z', { fill: D.ribbon }));
      for (var k = 0; k < 3; k++) {
        var y0 = top + (b - top) * (0.12 + k * 0.3), y1 = y0 + (b - top) * 0.13;
        var w0 = tw + (bw - tw) * (y0 - top) / (b - top), w1 = tw + (bw - tw) * (y1 - top) / (b - top);
        o.push(L(g, 'M' + [cx - w0, y0] + ' L' + [cx + w0, y0] + ' L' + [cx + w1, y1] + ' L' + [cx - w1, y1] + ' Z', { fill: hatch }));
      }
      o.push(L(g, 'M' + [cx - tw * 1.5, top] + ' H' + (cx + tw * 1.5) + ' M' + [cx - tw * 1.3, top - 4] + ' H' + (cx + tw * 1.3)));
      o.push(L(g, 'M' + [cx - tw * 0.8, top - 4] + ' V' + (top - s * 0.1) + ' H' + (cx + tw * 0.8) + ' V' + (top - 4) + ' Z', { fill: D.lamp }));
      o.push(L(g, 'M' + [cx - tw, top - s * 0.1] + ' Q' + [cx, top - s * 0.19] + ' ' + [cx + tw, top - s * 0.1] + ' Z', { fill: hatch2 }));
      o.push(L(g, 'M' + [cx - bw * 1.9, b] + ' Q' + [cx - bw * 1.4, b - s * 0.07] + ' ' + [cx - bw * 0.9, b - s * 0.02]
               + ' M' + [cx + bw * 0.9, b - s * 0.02] + ' Q' + [cx + bw * 1.5, b - s * 0.08] + ' ' + [cx + bw * 2, b]));
      var beam = C.svg('path', { fill: D.lamp, 'fill-opacity': '0.45', stroke: 'none' }, g);
      g.insertBefore(beam, g.firstChild);
      return { paths: o, beam: beam, lx: cx, ly: top - s * 0.055, len: s * 0.75 };
    },
    ship: function (g, x, y, s) {          // парусник: корпус, мачта, два паруса со штриховкой, вымпел
      var cx = x + s * 0.5, wl = y + s * 0.82, o = [];
      o.push(L(g, 'M' + [x + s * 0.14, wl - s * 0.08] + ' L' + [x + s * 0.86, wl - s * 0.08] + ' Q' + [x + s * 0.8, wl + s * 0.04] + ' '
               + [x + s * 0.7, wl + s * 0.05] + ' L' + [x + s * 0.28, wl + s * 0.05] + ' Q' + [x + s * 0.2, wl] + ' ' + [x + s * 0.14, wl - s * 0.08] + ' Z',
               { fill: hatch2 }));
      o.push(L(g, 'M' + [cx, wl - s * 0.08] + ' V' + (y + s * 0.1), { w: 2 }));
      o.push(L(g, 'M' + [cx + 3, y + s * 0.14] + ' Q' + [cx + s * 0.3, y + s * 0.42] + ' ' + [cx + 3, wl - s * 0.14] + ' Z', { fill: D.ribbon }));
      o.push(L(g, 'M' + [cx + 3, y + s * 0.3] + ' Q' + [cx + s * 0.2, y + s * 0.48] + ' ' + [cx + 3, wl - s * 0.16] + ' Z', { fill: hatch }));
      o.push(L(g, 'M' + [cx - 3, y + s * 0.2] + ' L' + [x + s * 0.2, wl - s * 0.14] + ' H' + (cx - 3) + ' Z', { fill: D.ribbon }));
      o.push(L(g, 'M' + [cx, y + s * 0.1] + ' l' + s * 0.12 + ' ' + s * 0.03 + ' l' + (-s * 0.12) + ' ' + s * 0.03, { fill: D.rust }));
      return { paths: o };
    },
    sun: function (g, x, y, s) {           // солнце: двойной круг, штриховка, 24 луча-штриха
      var cx = x + s / 2, cy = y + s / 2, r = s * 0.17, rot = C.svg('g', {}, g), o = [], d = '';
      for (var k = 0; k < 24; k++) {
        var a = k / 24 * Math.PI * 2, r2 = r * (k % 2 ? 1.9 : 2.6);
        d += 'M' + (cx + Math.cos(a) * r * 1.25).toFixed(1) + ' ' + (cy + Math.sin(a) * r * 1.25).toFixed(1) + ' L'
          + (cx + Math.cos(a) * r2).toFixed(1) + ' ' + (cy + Math.sin(a) * r2).toFixed(1);
      }
      o.push(L(rot, d, { w: 1.1 }));
      o.push(L(g, circ(cx, cy, r), { fill: D.ribbon, w: 2 }));
      o.push(L(g, circ(cx, cy, r * 0.8), { fill: hatchH, w: 0.8 }));
      return { paths: o, rot: rot, cx: cx, cy: cy };
    },
    compass: function (g, x, y, s) {       // роза ветров: два кольца, звезда из 8 лучей (половина в штриховке), «С»
      var cx = x + s / 2, cy = y + s * 0.54, r = s * 0.36, o = [L(g, circ(cx, cy, r), { w: 1.8 }), L(g, circ(cx, cy, r * 0.9), { w: 0.8 })];
      for (var k = 0; k < 8; k++) {
        var a = k / 8 * Math.PI * 2 - Math.PI / 2, rr = k % 2 ? r * 0.55 : r * 1.0, w = k % 2 ? 0.25 : 0.32, rw = r * 0.16;
        var tip = [cx + Math.cos(a) * rr, cy + Math.sin(a) * rr];
        var l = [cx + Math.cos(a - Math.PI / 2) * rw * w * 3, cy + Math.sin(a - Math.PI / 2) * rw * w * 3];
        var rr2 = [cx + Math.cos(a + Math.PI / 2) * rw * w * 3, cy + Math.sin(a + Math.PI / 2) * rw * w * 3];
        o.push(L(g, 'M' + [cx, cy] + ' L' + l + ' L' + tip + ' Z', { fill: D.ribbon, w: 1.1 }));
        o.push(L(g, 'M' + [cx, cy] + ' L' + rr2 + ' L' + tip + ' Z', { fill: hatch, w: 1.1 }));
      }
      var n = C.text(g, cx, cy - r - 8, 'С', { 'text-anchor': 'middle', fill: D.etch, 'font-size': String(Math.round(s * 0.11)) });
      n.style.fontFamily = cfg.fonts.decor || cfg.fonts.title;
      return { paths: o };
    },
    birds: function (g, x, y, s) {         // чайки: дуги-«галочки»
      var o = [], at = [[0.2, 0.3, 1], [0.45, 0.18, 0.8], [0.62, 0.4, 1.1], [0.8, 0.26, 0.7]];
      at.forEach(function (b) {
        var bx = x + s * b[0], by = y + s * b[1], w = s * 0.09 * b[2];
        o.push(L(g, 'M' + [bx - w, by] + ' Q' + [bx - w * 0.5, by - w * 0.6] + ' ' + [bx, by] + ' Q' + [bx + w * 0.5, by - w * 0.6] + ' ' + [bx + w, by],
                 { w: 1.6 }));
      });
      return { paths: o, birds: true };
    },
    quill: function (g, x, y, s) {         // гусиное перо и чернильница
      var o = [], bx = x + s * 0.35, by = y + s * 0.95;
      o.push(L(g, 'M' + [x + s * 0.2, by] + ' H' + (x + s * 0.52) + ' L' + [x + s * 0.48, by - s * 0.2] + ' H' + (x + s * 0.24) + ' Z',
               { fill: hatch2 }));
      o.push(L(g, 'M' + [x + s * 0.28, by - s * 0.2] + ' V' + (by - s * 0.26) + ' H' + (x + s * 0.44) + ' V' + (by - s * 0.2), { fill: D.etch_soft }));
      o.push(L(g, 'M' + [bx, by - s * 0.24] + ' Q' + [x + s * 0.55, y + s * 0.35] + ' ' + [x + s * 0.88, y + s * 0.05], { w: 1.4 }));
      var d = '';
      for (var k = 1; k < 12; k++) {
        var p = k / 12, px = bx + (x + s * 0.88 - bx) * p, py = by - s * 0.24 + (y + s * 0.05 - by + s * 0.24) * p;
        d += 'M' + px.toFixed(1) + ' ' + py.toFixed(1) + ' l' + (-s * 0.1 * Math.sin(p * 3)).toFixed(1) + ' ' + (-s * 0.04).toFixed(1);
        d += 'M' + px.toFixed(1) + ' ' + py.toFixed(1) + ' l' + (s * 0.07 * Math.sin(p * 3)).toFixed(1) + ' ' + (s * 0.06).toFixed(1);
      }
      o.push(L(g, d, { w: 0.9 }));
      return { paths: o };
    }
  };
  var ORDER = cfg.objects.filter(function (k) { return DRAW[k]; });

  var world = [], seas = [];
  if (WORLD) FILM.scenes.forEach(function (sc, i) {
    if (sc.style !== NAME) return;
    var zr = (sc.decor_zones || [])[0];
    if (zr) {                              // море — параллельные волнистые линии у низа первой зоны
      var g = C.svg('g', {}, svg), y0 = P.waves_top_in * PX, y1 = zr[1] + zr[3], d = '';
      for (var r = 0; r < P.waves_rows; r++) {
        var yy = y0 + (y1 - y0) * r / (P.waves_rows - 1), amp = 2 + r * 0.4, ph = r * 1.7;
        d += 'M' + zr[0] + ' ' + yy.toFixed(1);
        for (var xx = zr[0]; xx <= zr[0] + zr[2]; xx += 12) d += ' L' + xx + ' ' + (yy + Math.sin(xx / 22 + ph) * amp).toFixed(1);
      }
      C.svg('rect', { x: zr[0], y: y0 - 4, width: zr[2], height: y1 - y0 + 8, fill: D.sea, 'fill-opacity': '0.55' }, g);
      seas.push({ i: i, g: g, p: L(g, d, { w: 1 }), t0: sc.start + P.draw_from });
    }
    C.slots(sc.decor_zones, ORDER.length, 14).forEach(function (b, k) {
      var kind = ORDER[k % ORDER.length], g = C.svg('g', {}, svg), o = DRAW[kind](g, b[0], b[1], b[2]);
      o.i = i; o.g = g; o.kind = kind; o.t0 = sc.start + P.draw_from + (k + 1) * P.draw_gap;
      world.push(o);
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
  function f1(v) { return v.toFixed(1); }

  return {
    render: function (t) {
      var w = api.styleWeight(NAME, t);
      api.setStyle(layer, 'opacity', api.styleOpacity(NAME, t, layer).toFixed(3));
      api.setStyle(layer, 'visibility', w > 0.001 ? 'visible' : 'hidden');
      if (w <= 0.001) return;
      if (wins) wins.render(t);
      var o0 = root.getBoundingClientRect();
      shadows.forEach(function (s) {
        var o = opacityOf(s.el);
        api.setAttr(s.g, 'opacity', o.toFixed(3));
        if (o <= 0.001) return;
        var r = s.el.getBoundingClientRect(), x = r.left - o0.left + P.shadow_px[0], y = r.top - o0.top + P.shadow_px[1];
        [s.a, s.b, s.o].forEach(function (e) {
          api.setAttr(e, 'x', f1(x)); api.setAttr(e, 'y', f1(y)); api.setAttr(e, 'width', f1(r.width)); api.setAttr(e, 'height', f1(r.height));
        });
      });
      ribbons.forEach(function (rb) {
        var o = parseFloat(rb.frame.style.opacity) || 0;
        api.setAttr(rb.g, 'opacity', o.toFixed(3));
        if (o <= 0.001) return;
        var rg = document.createRange(); rg.selectNodeContents(rb.span);
        var tr = rg.getBoundingClientRect(), fb = rb.frame.getBoundingClientRect();
        var x0 = tr.left - o0.left - P.ribbon_pad_px, x1 = tr.right - o0.left + P.ribbon_pad_px;
        var y0 = fb.top - o0.top + 2, y1 = fb.bottom - o0.top - 2, h = y1 - y0, dr = P.ribbon_drop_px, tl = P.ribbon_tail_px;
        x0 = Math.max(x0, P.frame_inset_px[1] + tl + 8);
        var tails = 'M' + f1(x0 + 6) + ' ' + f1(y0 + dr) + ' H' + f1(x0 - tl) + ' L' + f1(x0 - tl + 18) + ' ' + f1(y0 + dr + h / 2)
          + ' L' + f1(x0 - tl) + ' ' + f1(y1 + dr) + ' H' + f1(x0 + 6) + ' Z'
          + ' M' + f1(x1 - 6) + ' ' + f1(y0 + dr) + ' H' + f1(x1 + tl) + ' L' + f1(x1 + tl - 18) + ' ' + f1(y0 + dr + h / 2)
          + ' L' + f1(x1 + tl) + ' ' + f1(y1 + dr) + ' H' + f1(x1 - 6) + ' Z';
        api.setAttr(rb.tails, 'd', tails);
        api.setAttr(rb.tailHatch, 'd', tails);
        api.setAttr(rb.folds, 'd', 'M' + f1(x0) + ' ' + f1(y1) + ' L' + f1(x0 + 6) + ' ' + f1(y1 + dr) + ' H' + f1(x0) + ' Z M'
          + f1(x1) + ' ' + f1(y1) + ' L' + f1(x1 - 6) + ' ' + f1(y1 + dr) + ' H' + f1(x1) + ' Z');
        api.setAttr(rb.body, 'd', 'M' + f1(x0) + ' ' + f1(y0) + ' Q' + f1((x0 + x1) / 2) + ' ' + f1(y0 - 6) + ' ' + f1(x1) + ' ' + f1(y0)
          + ' V' + f1(y1) + ' Q' + f1((x0 + x1) / 2) + ' ' + f1(y1 - 6) + ' ' + f1(x0) + ' ' + f1(y1) + ' Z');
        api.setAttr(rb.rule, 'd', 'M' + f1(x0 + 8) + ' ' + f1(y0 + 5) + ' Q' + f1((x0 + x1) / 2) + ' ' + f1(y0 - 1) + ' ' + f1(x1 - 8) + ' '
          + f1(y0 + 5) + ' M' + f1(x0 + 8) + ' ' + f1(y1 - 5) + ' Q' + f1((x0 + x1) / 2) + ' ' + f1(y1 - 11) + ' ' + f1(x1 - 8) + ' ' + f1(y1 - 5));
      });
      seas.forEach(function (s) {
        var sw = api.sceneWeight(s.i, t);
        api.setAttr(s.g, 'opacity', sw.toFixed(3));
        if (sw > 0.001) C.drawOn([s.p], api.clamp01((t - s.t0) / P.draw_in));
      });
      world.forEach(function (o) {
        var sw = api.sceneWeight(o.i, t);
        api.setAttr(o.g, 'opacity', sw.toFixed(3));
        if (sw <= 0.001) return;
        var p = api.clamp01((t - o.t0) / P.draw_in);
        C.drawOn(o.paths, p);
        api.setAttr(o.g, 'fill-opacity', api.clamp01(p * 1.5 - 0.5).toFixed(3));
        if (o.beam) {                       // луч маяка качается над морем
          var a = Math.PI * (-0.05 + 0.1 * Math.sin(t / P.beam_sweep_sec * Math.PI * 2)), sp = 0.12;
          var ex = function (k) { return f1(o.lx + Math.cos(a + k) * o.len) + ' ' + f1(o.ly + Math.sin(a + k) * o.len); };
          api.setAttr(o.beam, 'd', p < 1 ? '' : 'M' + f1(o.lx) + ' ' + f1(o.ly) + ' L' + ex(-sp) + ' L' + ex(sp) + ' Z');
        } else if (o.rot) {
          api.setAttr(o.rot, 'transform', 'rotate(' + (t / P.sun_turn_sec * 360).toFixed(2) + ' ' + f1(o.cx) + ' ' + f1(o.cy) + ')');
        } else if (o.kind === 'ship') {
          api.setAttr(o.g, 'transform', 'translate(0,' + (Math.sin(t * 1.3) * P.ship_bob_px).toFixed(2) + ')');
        } else if (o.birds) {
          api.setAttr(o.g, 'transform', 'translate(' + f1(Math.sin(t * 0.5) * 12) + ',' + f1(Math.sin(t * 0.9) * 5) + ')');
        }
      });
    },
    probe: function (t) { return { style: NAME, weight: api.styleWeight(NAME, t), world: WORLD }; }
  };
});
