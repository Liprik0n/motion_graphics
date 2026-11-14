/* Стекло — плагин стиля (engine/video/styles/README.md). Всё в слое 'back' — под каркасом и содержанием.

   Мир (cfg.world): тёмный ночной фон (decor.night → night_2) и размытые неоновые пятна, которые медленно
   плывут; матовые светлые плашки-стёкла под каждой зоной текста содержания и каркаса (StyleCore.textWindows:
   зоны — из раскладки сцены, а не из дюймов стиля) — на них текст держит контраст бренда на любом фильме
   (V21); у плашки блик по верхней кромке, светлый ободок и мягкая тень. В зонах сцены
   (decor_zones) — стеклянное кольцо, светящийся шар, осколок с бликом, капсула, искра, неоновая волна;
   всё плавает по синусу, без ступеней. Мигания нет: искра «дышит» размером (V23).
   При style_brand_lock (cfg.world = false): только мягкие блики-пятна ролью бренда поверх фирменного фона.

   Кадр — чистая функция времени (V24): случайности нет. Текст не трогается. */
(window.StagePlugins = window.StagePlugins || []).push(function (FILM, api) {
  'use strict';
  var NAME = 'glass', cfg = api.styleConfig(NAME);
  if (!cfg) return null;
  var C = window.StyleCore, P = cfg.params, D = cfg.decor, PX = FILM.px, WORLD = cfg.world;
  var root = document.getElementById('root'), W = root.clientWidth, H = root.clientHeight;

  var layer = api.addLayer('gl-back', 'back');
  function div(css, parent) {
    var d = document.createElement('div'); d.className = 'layer';
    Object.keys(css).forEach(function (k) { d.style[k] = css[k]; });
    (parent || layer).appendChild(d); return d;
  }
  function rgba(hex, a) { return 'rgba(' + C.rgbOf(hex).join(',') + ',' + a + ')'; }
  function f1(v) { return v.toFixed(1); }

  if (WORLD) layer.style.background = 'linear-gradient(160deg, ' + D.night_2 + ' 0%, ' + D.night + ' 60%)';
  // неоновые пятна: радиальный градиент от цвета к прозрачному; в замке — роль бренда, бледно
  var blobs = P.blobs.map(function (b, k) {
    var col = WORLD ? D[b[3]] : C.cssVar('--c-' + P.lock_role), a = WORLD ? b[4] : P.lock_alpha * 3;
    var el = div({ left: '0', top: '0', width: b[2] * 2 + 'px', height: b[2] * 2 + 'px', right: 'auto', bottom: 'auto',
                   background: 'radial-gradient(circle at center, ' + rgba(col, a) + ' 0%, ' + rgba(col, a * 0.45) + ' 35%, '
                     + rgba(col, 0) + ' 70%)' });
    return { el: el, x: b[0] * W - b[2], y: b[1] * H - b[2], k: k };
  });

  // матовые плашки-стёкла: в них стоит текст. Где текст — решает раскладка сцены, а не стиль: окна под каждой
  // зоной текста содержания и каркаса (StyleCore.textWindows), середина — фон бренда, стекло — ободок, блик и тень
  var panes = WORLD ? C.textWindows(api, FILM, NAME, {
    parent: layer, frame: true, pad: P.pane_pad_px, merge: P.pane_merge_px,
    css: { borderRadius: P.pane_radius_px + 'px', border: '1.5px solid ' + rgba(D.rim, 0.75),
           boxShadow: '0 18px 50px ' + rgba(D.night, 0.55) + ', inset 0 2px 0 ' + rgba(D.rim, 0.95) }
  }) : null;

  var svg = C.svg('svg', { width: String(W), height: String(H), viewBox: '0 0 ' + W + ' ' + H }, layer);
  svg.style.position = 'absolute'; svg.style.left = '0'; svg.style.top = '0';
  function S(g, tag, a) { return C.svg(tag, a, g); }
  var defs = C.defs();
  var glow = S(defs, 'filter', { id: 'gl-glow', x: '-30%', y: '-30%', width: '160%', height: '160%' });
  S(glow, 'feGaussianBlur', { 'in': 'SourceGraphic', stdDeviation: '6', result: 'b' });
  var gm = S(glow, 'feMerge', {});
  S(gm, 'feMergeNode', { 'in': 'b' }); S(gm, 'feMergeNode', { 'in': 'SourceGraphic' });
  function radial(id, stops) {
    var g = S(defs, 'radialGradient', { id: id, cx: '0.38', cy: '0.32', r: '0.75' });
    stops.forEach(function (s) { S(g, 'stop', { offset: s[0], 'stop-color': s[1], 'stop-opacity': s[2] }); });
    return 'url(#' + id + ')';
  }

  var DRAW = {
    ring: function (g, x, y, s) {          // стеклянное кольцо: толстый полупрозрачный обод и блик дугой
      var cx = x + s / 2, cy = y + s / 2, r = s * 0.34;
      S(g, 'circle', { cx: cx, cy: cy, r: r, fill: 'none', stroke: D.rim, 'stroke-opacity': 0.22, 'stroke-width': s * 0.09 });
      S(g, 'circle', { cx: cx, cy: cy, r: r, fill: 'none', stroke: D.rim, 'stroke-opacity': 0.6, 'stroke-width': 1.5 });
      S(g, 'path', { d: 'M' + f1(cx - r * 0.85) + ' ' + f1(cy - r * 0.5) + ' A' + f1(r) + ' ' + f1(r) + ' 0 0 1 ' + f1(cx + r * 0.2) + ' ' + f1(cy - r * 0.98),
                     fill: 'none', stroke: D.rim, 'stroke-opacity': 0.9, 'stroke-width': 3, 'stroke-linecap': 'round' });
    },
    orb: function (g, x, y, s) {           // светящийся шар: радиальный градиент бирюзы и блик
      var cx = x + s / 2, cy = y + s / 2, r = s * 0.28;
      S(g, 'circle', { cx: cx, cy: cy, r: r * 1.5, fill: radial('gl-orb-glow-' + Math.round(x), [['0', D.neon_cyan, 0.45], ['1', D.neon_cyan, 0]]) });
      S(g, 'circle', { cx: cx, cy: cy, r: r, fill: radial('gl-orb-' + Math.round(x), [['0', D.rim, 0.9], ['0.35', D.neon_cyan, 0.85], ['1', D.neon_blue, 0.75]]) });
      S(g, 'ellipse', { cx: cx - r * 0.35, cy: cy - r * 0.45, rx: r * 0.3, ry: r * 0.16, fill: D.rim, 'fill-opacity': 0.8,
                        transform: 'rotate(-30 ' + f1(cx - r * 0.35) + ' ' + f1(cy - r * 0.45) + ')' });
    },
    shard: function (g, x, y, s) {         // осколок стекла: наклонная плитка, ободок, диагональный блик
      var cx = x + s / 2, cy = y + s / 2, w = s * 0.5, h = s * 0.66, rg = S(g, 'g', { transform: 'rotate(-14 ' + f1(cx) + ' ' + f1(cy) + ')' });
      S(rg, 'rect', { x: cx - w / 2, y: cy - h / 2, width: w, height: h, rx: 14, fill: D.rim, 'fill-opacity': 0.14, stroke: D.rim,
                      'stroke-opacity': 0.6, 'stroke-width': 1.5 });
      S(rg, 'path', { d: 'M' + f1(cx - w * 0.3) + ' ' + f1(cy + h * 0.1) + ' L' + f1(cx + w * 0.05) + ' ' + f1(cy - h * 0.38) + ' M' + f1(cx - w * 0.15)
                      + ' ' + f1(cy + h * 0.3) + ' L' + f1(cx + w * 0.3) + ' ' + f1(cy - h * 0.3), stroke: D.rim, 'stroke-opacity': 0.75,
                      'stroke-width': 3, 'stroke-linecap': 'round' });
    },
    capsule: function (g, x, y, s) {       // капсула: длинная матовая таблетка с бликом
      var w = s * 0.9, h = s * 0.26, x0 = x + (s - w) / 2, y0 = y + s * 0.55;
      S(g, 'rect', { x: x0, y: y0, width: w, height: h, rx: h / 2, fill: D.rim, 'fill-opacity': 0.13, stroke: D.rim, 'stroke-opacity': 0.5, 'stroke-width': 1.5 });
      S(g, 'path', { d: 'M' + f1(x0 + h * 0.5) + ' ' + f1(y0 + h * 0.25) + ' H' + f1(x0 + w * 0.6), stroke: D.rim, 'stroke-opacity': 0.8,
                     'stroke-width': 3, 'stroke-linecap': 'round' });
      S(g, 'circle', { cx: x0 + w - h / 2, cy: y0 + h / 2, r: h * 0.3, fill: D.neon_pink, 'fill-opacity': 0.9, filter: 'url(#gl-glow)' });
    },
    glint: function (g, x, y, s) {         // искра: четырёхлучевая звезда со свечением
      var cx = x + s / 2, cy = y + s * 0.45, r = s * 0.3, q = r * 0.14;
      S(g, 'path', { d: 'M' + f1(cx) + ' ' + f1(cy - r) + ' Q' + f1(cx + q) + ' ' + f1(cy - q) + ' ' + f1(cx + r) + ' ' + f1(cy) + ' Q' + f1(cx + q) + ' '
                     + f1(cy + q) + ' ' + f1(cx) + ' ' + f1(cy + r) + ' Q' + f1(cx - q) + ' ' + f1(cy + q) + ' ' + f1(cx - r) + ' ' + f1(cy) + ' Q'
                     + f1(cx - q) + ' ' + f1(cy - q) + ' ' + f1(cx) + ' ' + f1(cy - r) + ' Z', fill: D.rim, filter: 'url(#gl-glow)' });
      return { pulse: true, cx: cx, cy: cy };
    },
    wave: function (g, x, y, s) {          // неоновая волна: синусоида маджентой со свечением
      var d = 'M' + f1(x) + ' ' + f1(y + s * 0.6);
      for (var k = 1; k <= 24; k++) d += ' L' + f1(x + s * k / 24) + ' ' + f1(y + s * 0.6 + Math.sin(k / 24 * Math.PI * 3) * s * 0.14);
      S(g, 'path', { d: d, fill: 'none', stroke: D.neon_pink, 'stroke-width': 4, 'stroke-linecap': 'round', filter: 'url(#gl-glow)' });
      S(g, 'path', { d: d, fill: 'none', stroke: D.neon_cyan, 'stroke-width': 2, 'stroke-opacity': 0.8, transform: 'translate(0,16)' });
    }
  };
  var ORDER = cfg.objects.filter(function (k) { return DRAW[k]; });
  var world = [];
  if (WORLD) FILM.scenes.forEach(function (sc, i) {
    if (sc.style !== NAME) return;
    C.slots(sc.decor_zones, ORDER.length, 14).forEach(function (b, k) {
      var g = S(svg, 'g', {}), o = DRAW[ORDER[k % ORDER.length]](g, b[0], b[1], b[2]) || {};
      o.i = i; o.g = g; o.k = k;
      world.push(o);
    });
  });

  return {
    render: function (t) {
      var w = api.styleWeight(NAME, t);
      api.setStyle(layer, 'opacity', api.styleOpacity(NAME, t, layer).toFixed(3));
      api.setStyle(layer, 'visibility', w > 0.001 ? 'visible' : 'hidden');
      if (w <= 0.001) return;
      if (panes) panes.render(t);
      var ph = t / P.blob_period_sec * Math.PI * 2;
      blobs.forEach(function (b) {
        var dx = Math.sin(ph + b.k * 1.9) * P.blob_drift_px, dy = Math.cos(ph * 0.8 + b.k * 2.3) * P.blob_drift_px * 0.6;
        api.setStyle(b.el, 'transform', 'translate(' + f1(b.x + dx) + 'px,' + f1(b.y + dy) + 'px)');
      });
      var fp = t / P.float_period_sec * Math.PI * 2;
      world.forEach(function (o) {
        var sw = api.sceneWeight(o.i, t);
        api.setAttr(o.g, 'opacity', sw.toFixed(3));
        if (sw <= 0.001) return;
        var dy = Math.sin(fp + o.k * 1.3) * P.float_px, tr = 'translate(0,' + f1(dy) + ')';
        if (o.pulse) {
          var k = 1 + 0.15 * Math.sin(fp * 1.5 + o.k);
          tr += ' translate(' + f1(o.cx) + ',' + f1(o.cy) + ') scale(' + k.toFixed(3) + ') translate(' + f1(-o.cx) + ',' + f1(-o.cy) + ')';
        }
        api.setAttr(o.g, 'transform', tr);
      });
    },
    probe: function (t) { return { style: NAME, weight: api.styleWeight(NAME, t), world: WORLD }; }
  };
});
