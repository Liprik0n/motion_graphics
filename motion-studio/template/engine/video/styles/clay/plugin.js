/* Глина — плагин стиля (engine/video/styles/README.md). Всё в слое 'back' — под каркасом и содержанием.

   Мир (cfg.world): тёплый стол (decor.table) с мягкой виньеткой и следами пальцев; по верхнему полю —
   облака-колбаски и волны-«тильды»; внизу — галька; в зонах сцены — объёмные мягкие формы без 3D:
   радиальный градиент своего цвета (блик сверху-слева, тень к краю), блик и размытая падающая тень —
   холм-купол, дерево-шарик на палочке, самолётик, облако, галька, волны с лужицей. Заголовок — пластилиновые
   буквы (StyleCore.codeTitle): шрифт декора стиля, у каждой буквы свой цвет, кромка и тень.
   Движение покадровое «на двойках»: дрожь формы (jitter_px, новая на каждый рисунок), мягкий отскок входа,
   предметы «дышат» — сжимаются по вертикали от основания.
   При style_brand_lock (cfg.world = false): следы пальцев ролью ink поверх фирменного фона (+ тени style.css).

   Детерминизм: рисунок = номер кадра / step_frames; сид — hash(id) + номер рисунка. */
(window.StagePlugins = window.StagePlugins || []).push(function (FILM, api) {
  'use strict';
  var NAME = 'clay', cfg = api.styleConfig(NAME);
  if (!cfg) return null;
  var C = window.StyleCore, P = cfg.params, D = cfg.decor, PX = FILM.px, WORLD = cfg.world;
  var root = document.getElementById('root'), W = root.clientWidth, H = root.clientHeight;
  var scenes = api.styleScenes(NAME);
  var layer = api.addLayer('cl-back', 'back');
  if (WORLD) {
    layer.style.background = D.table;
    var vg = document.createElement('div'); vg.className = 'layer'; layer.appendChild(vg);
    C.vignette(vg, { strength: P.vignette, inner: P.vignette_inner, rgb: C.rgbOf(D.shadow) });
  }
  var svg = C.svg('svg', { width: String(W), height: String(H), viewBox: '0 0 ' + W + ' ' + H }, layer);
  svg.style.position = 'absolute'; svg.style.left = '0'; svg.style.top = '0';
  // окна под текстом (StyleCore.textWindows): зоны текста — из раскладки сцены, а не из стиля; середина
  // окна — фон бренда, контраст надписи = контраст бренда на любом фильме (V21); оформление — языком мира
  var wins = WORLD ? C.textWindows(api, FILM, NAME, { parent: layer, pad: P.win_pad_px, css: { borderRadius: '20px', boxShadow: '0 6px 0 ' + 'rgba(' + C.rgbOf(D.shadow).join(',') + ',0.16)' + ', 0 14px 24px ' + 'rgba(' + C.rgbOf(D.shadow).join(',') + ',0.22)' } }) : null;
  function S(g, tag, a) { return C.svg(tag, a, g); }

  // следы пальцев: концентрические овалы, едва заметные (и под замком — ролью ink)
  var printC = WORLD ? D.shadow : C.cssVar('--c-ink'), pr = C.rng(P.print_seed);
  for (var n = 0; n < P.print_count; n++) {
    var px = pr() * W, py = pr() * H, a = pr() * 180, g0 = S(svg, 'g', { transform: 'rotate(' + a.toFixed(0) + ' ' + px.toFixed(0) + ' ' + py.toFixed(0) + ')' });
    for (var r = 6; r < 46; r += 6) S(g0, 'ellipse', { cx: px, cy: py, rx: r * 1.3, ry: r, fill: 'none', stroke: printC, 'stroke-width': 1.4, 'stroke-opacity': P.print_alpha });
  }

  var world = [], titleR = null, titleG = null;
  if (WORLD) {
    var defs = C.defs();
    var blur = S(defs, 'filter', { id: 'cl-soft', x: '-30%', y: '-30%', width: '160%', height: '160%' });
    S(blur, 'feGaussianBlur', { stdDeviation: 7 });
    var blur2 = S(defs, 'filter', { id: 'cl-hi', x: '-30%', y: '-30%', width: '160%', height: '160%' });
    S(blur2, 'feGaussianBlur', { stdDeviation: 3 });
    var grads = {};
    function clay(c) {                       // радиальный градиент глины: блик → цвет → тёмный край
      if (grads[c]) return grads[c];
      var gr = S(defs, 'radialGradient', { id: 'cl-r-' + c, cx: '0.38', cy: '0.32', r: '0.75' });
      S(gr, 'stop', { offset: '0', 'stop-color': D[c + '_light'] || D[c] });
      S(gr, 'stop', { offset: '0.55', 'stop-color': D[c] });
      S(gr, 'stop', { offset: '1', 'stop-color': D[c + '_dark'] || D[c + '_shade'] || D.shadow });
      return (grads[c] = 'url(#cl-r-' + c + ')');
    }
    function lin(c) {
      var id = 'cl-l-' + c;
      if (!document.getElementById(id)) {
        var gr = S(defs, 'linearGradient', { id: id, x1: 0, y1: 0, x2: 0, y2: 1 });
        S(gr, 'stop', { offset: '0', 'stop-color': D[c + '_light'] || D[c] });
        S(gr, 'stop', { offset: '0.45', 'stop-color': D[c] });
        S(gr, 'stop', { offset: '1', 'stop-color': D[c + '_dark'] || D.shadow });
      }
      return 'url(#' + id + ')';
    }
    function blob(g, d, c, hl) {             // форма глины: падающая тень, тело, блик
      S(g, 'path', { d: d, fill: D.shadow, 'fill-opacity': 0.28, filter: 'url(#cl-soft)', transform: 'translate(6,10)' });
      S(g, 'path', { d: d, fill: clay(c) });
      if (hl) S(g, 'ellipse', { cx: hl[0], cy: hl[1], rx: hl[2], ry: hl[2] * 0.6, fill: D.white, 'fill-opacity': 0.45, filter: 'url(#cl-hi)' });
    }
    function circ(cx, cy, r) { return 'M' + (cx - r) + ' ' + cy + 'a' + r + ' ' + r + ' 0 1 0 ' + 2 * r + ' 0a' + r + ' ' + r + ' 0 1 0 ' + (-2 * r) + ' 0Z'; }
    function ell(cx, cy, rx, ry) { return 'M' + (cx - rx) + ' ' + cy + 'a' + rx + ' ' + ry + ' 0 1 0 ' + 2 * rx + ' 0a' + rx + ' ' + ry + ' 0 1 0 ' + (-2 * rx) + ' 0Z'; }
    function cloudD(x, y, s) {
      var b = y + s * 0.6, r = s * 0.16;
      return 'M' + (x + r) + ' ' + b + 'A' + r + ' ' + r + ' 0 0 1 ' + (x + s * 0.3) + ' ' + (b - s * 0.24) + 'A' + s * 0.2 + ' ' + s * 0.2 + ' 0 0 1 ' + (x + s * 0.68) + ' ' + (b - s * 0.28)
        + 'A' + s * 0.16 + ' ' + s * 0.16 + ' 0 0 1 ' + (x + s - r * 0.6) + ' ' + (b - r * 0.2) + 'A' + r * 0.6 + ' ' + r * 0.6 + ' 0 0 1 ' + (x + s - r) + ' ' + (b + r * 0.5)
        + 'H' + (x + r) + 'A' + r * 0.5 + ' ' + r * 0.5 + ' 0 0 1 ' + (x + r) + ' ' + b + 'Z';
    }
    function waves(g, x, y, w, k) {
      for (var i = 0; i < k; i++) {
        var wx = x + i * w / k, wy = y + (i % 2) * 10;
        S(g, 'path', { d: 'M' + wx + ' ' + wy + 'q8 -9 16 0t16 0', fill: 'none', stroke: D.wave, 'stroke-width': 4, 'stroke-linecap': 'round', 'stroke-opacity': 0.7 });
      }
    }
    var DRAW = {
      hill: function (g, x, y, s) {
        var b = y + s, d = 'M' + (x - s * 0.05) + ' ' + b + 'C' + (x + s * 0.05) + ' ' + (y + s * 0.35) + ' ' + (x + s * 0.95) + ' ' + (y + s * 0.35) + ' ' + (x + s * 1.05) + ' ' + b + 'Z';
        blob(g, d, 'green', [x + s * 0.38, y + s * 0.58, s * 0.12]);
      },
      tree: function (g, x, y, s) {
        var cx = x + s / 2;
        blob(g, 'M' + (cx - 7) + ' ' + (y + s * 0.5) + 'h14v' + s * 0.48 + 'h-14Z', 'brown');
        blob(g, circ(cx, y + s * 0.36, s * 0.24), 'green', [cx - s * 0.08, y + s * 0.26, s * 0.07]);
      },
      plane: function (g, x, y, s) {
        var y0 = y + s * 0.25;
        blob(g, 'M' + (x + s * 0.06) + ' ' + (y0 + s * 0.3) + 'L' + (x + s * 0.94) + ' ' + y0 + 'L' + (x + s * 0.42) + ' ' + (y0 + s * 0.42) + 'Z', 'orange', [x + s * 0.5, y0 + s * 0.18, s * 0.08]);
        S(g, 'path', { d: 'M' + (x + s * 0.42) + ' ' + (y0 + s * 0.42) + 'L' + (x + s * 0.94) + ' ' + y0 + 'L' + (x + s * 0.5) + ' ' + (y0 + s * 0.56) + 'Z', fill: D.orange_dark });
      },
      cloud: function (g, x, y, s) { blob(g, cloudD(x, y + s * 0.1, s), 'white', [x + s * 0.42, y + s * 0.38, s * 0.1]); },
      pebbles: function (g, x, y, s) {
        [['pebble', 0.25, 0.86, 0.16, 0.09], ['red', 0.52, 0.9, 0.12, 0.07], ['orange', 0.74, 0.87, 0.15, 0.085], ['brown', 0.42, 0.78, 0.09, 0.06]].forEach(function (p) {
          blob(g, ell(x + s * p[1], y + s * p[2], s * p[3], s * p[4]), p[0], [x + s * (p[1] - p[3] * 0.3), y + s * (p[2] - p[4] * 0.4), s * p[3] * 0.3]);
        });
      },
      waves: function (g, x, y, s) {
        blob(g, ell(x + s / 2, y + s * 0.78, s * 0.42, s * 0.12), 'blue', [x + s * 0.4, y + s * 0.74, s * 0.1]);
        waves(g, x + s * 0.1, y + s * 0.3, s * 0.8, 3);
      }
    };
    // верхнее поле: облака и тильды; низ: галька
    var top = S(svg, 'g', {});
    [[1.4, 0.15, 1.6, 0], [6.2, 0.35, 1.3, 1]].forEach(function (c) {
      var g = S(top, 'g', {}); DRAW.cloud(g, c[0] * PX, c[1] * PX, c[2] * PX);
      world.push({ i: -1, g: g, kind: 'cloud', k: c[3], cx: (c[0] + c[2] / 2) * PX, by: (c[1] + c[2] * 0.7) * PX, t0: -1, seed: c[3] + 5 });
    });
    waves(top, 4.0 * PX, 0.95 * PX, 1.0 * PX, 3); waves(top, 9.0 * PX, 0.6 * PX, 1.0 * PX, 3);
    var bot = S(svg, 'g', {});
    for (var k = 0; k < 14; k++) {
      var bx = (k + 0.5) * W / 14 + (C.rng(k + 3)() - 0.5) * 60, cols = ['pebble', 'orange', 'brown', 'red'];
      blob(bot, ell(bx, H + 6, 34 + (k % 3) * 10, 20 + (k % 2) * 6), cols[k % 4]);
    }
    var ORDER = cfg.objects.filter(function (kk) { return DRAW[kk]; });
    FILM.scenes.forEach(function (sc, i) {
      if (sc.style !== NAME) return;
      C.slots(sc.decor_zones, ORDER.length, 14).forEach(function (b, kk) {
        var kind = ORDER[kk % ORDER.length], g = S(svg, 'g', {});
        DRAW[kind](g, b[0], b[1], b[2]);
        world.push({ i: i, g: g, kind: kind, k: kk, cx: b[0] + b[2] / 2, by: b[1] + b[2], t0: sc.start + P.enter_from + kk * P.enter_gap, seed: C.hash(sc.id + kind) });
      });
    });

    // заголовок — пластилиновые буквы, каждая своим цветом
    titleG = S(svg, 'g', {});
    titleR = C.codeTitle(api, scenes, titleG, function (g, text, box) {
      var fs = P.title_size_px, base = box.y + box.h / 2 + fs * 0.36;
      var mk = function (dx, dy, shadow) {
        var t = S(g, 'text', { x: box.x + dx, y: base + dy, 'font-size': fs, 'font-weight': 700 });
        t.style.fontFamily = cfg.fonts.decor;
        var j = 0;
        Array.prototype.forEach.call(text, function (ch) {
          var sp = S(t, 'tspan', {}); sp.textContent = ch;
          if (shadow) { sp.setAttribute('fill', D.shadow); sp.setAttribute('fill-opacity', '0.3'); return; }
          if (ch === ' ') return;
          var c = P.title_colors[j++ % P.title_colors.length];
          sp.setAttribute('fill', lin(c)); sp.setAttribute('stroke', D[c + '_dark']); sp.setAttribute('stroke-width', '2');
          sp.setAttribute('paint-order', 'stroke'); sp.setAttribute('stroke-linejoin', 'round');
        });
        return t;
      };
      mk(2, 3, true); mk(0, 0, false);
    });
  }

  function backOut(x, k) { x -= 1; return 1 + (k + 1) * x * x * x + k * x * x; }
  return {
    render: function (t) {
      var w = api.styleWeight(NAME, t);
      api.setStyle(layer, 'opacity', api.styleOpacity(NAME, t, layer).toFixed(3));
      api.setStyle(layer, 'visibility', w > 0.001 ? 'visible' : 'hidden');
      if (w <= 0.001 || !WORLD) return;
      if (wins) wins.render(t);
      var ts = api.stepTime(t, P.step_frames), drawing = Math.floor(api.frameOf(t) / P.step_frames);
      titleR(t);
      var tr = C.rng(drawing * 31 + 7);                       // буквы чуть «живут» вместе с рисунком
      api.setAttr(titleG, 'transform', 'translate(' + Math.round((tr() - 0.5) * 2) + ',' + Math.round((tr() - 0.5) * 2) + ')');   // целые px: дробный сдвиг текста растрируется по-разному
      world.forEach(function (o) {
        var sw = o.i < 0 ? 1 : api.sceneWeight(o.i, t);
        api.setAttr(o.g, 'opacity', sw.toFixed(3));
        if (sw <= 0.001) return;
        var sc = 1;
        if (o.t0 >= 0) {
          var p = (ts - o.t0) / P.pop_sec;
          if (p < 0) { api.setAttr(o.g, 'visibility', 'hidden'); return; }
          api.setAttr(o.g, 'visibility', 'visible');
          sc = backOut(Math.min(1, p), 1.8);
        }
        var rr = C.rng(o.seed + drawing * 101), jx = (rr() - 0.5) * 2 * P.jitter_px, jy = (rr() - 0.5) * 2 * P.jitter_px;
        var br = Math.sin(ts * Math.PI * 2 * P.breathe_hz + o.k * 1.3) * P.breathe, sy = sc * (1 + br), sx = sc * (1 - br * 0.6);
        var dx = o.kind === 'cloud' ? Math.sin(ts * 0.6 + o.k * 2) * 10 : 0;
        api.setAttr(o.g, 'transform', 'translate(' + (o.cx + jx + dx).toFixed(1) + ',' + (o.by + jy).toFixed(1) + ') scale(' + sx.toFixed(3) + ',' + sy.toFixed(3)
          + ') translate(' + (-o.cx) + ',' + (-o.by) + ')');
      });
    },
    probe: function (t) { return { style: NAME, weight: api.styleWeight(NAME, t), world: WORLD }; }
  };
});
