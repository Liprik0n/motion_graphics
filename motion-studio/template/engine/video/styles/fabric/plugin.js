/* Ткань — плагин стиля (engine/video/styles/README.md). Всё в слое 'back' — под каркасом и содержанием.

   Мир (cfg.world): джинса (decor.denim) с саржевым рубчиком и зерном, строчка по краю кадра; пришитый
   льняной лоскут (params.window_in) со строчкой — в нём каркас и содержание; фетровая нашивка с кантом и
   стежками под заголовком (рамка строки заголовка — каждый кадр); фетровая нашивка под табло глав; по
   верхнему полю — фетровое солнце с лицом, облака, вышитый самолётик со стежковым следом; вязаная трава
   внизу; в зонах сцены — фетровые предметы со стежками: облако, самолётик, пуговица, дерево, сердечко,
   катушка. Строчки «прошиваются» с начала сцены; фетр входит с мягким перелётом «на двойках».
   Всегда (и при style_brand_lock): строчка вокруг карточек и плашек; замок — роль бренда, рубчик бледной
   ролью ink поверх фирменного фона.

   Детерминизм: всё — функция времени «на двойках» (api.stepTime); случайность — rng(hash(id)). */
(window.StagePlugins = window.StagePlugins || []).push(function (FILM, api) {
  'use strict';
  var NAME = 'fabric', cfg = api.styleConfig(NAME);
  if (!cfg) return null;
  var C = window.StyleCore, P = cfg.params, D = cfg.decor, PX = FILM.px, WORLD = cfg.world;
  var root = document.getElementById('root'), W = root.clientWidth, H = root.clientHeight;
  var scenes = api.styleScenes(NAME);
  var layer = api.addLayer('fb-back', 'back');
  function div(css, parent) {
    var d = document.createElement('div'); d.className = 'layer';
    Object.keys(css).forEach(function (k) { d.style[k] = css[k]; });
    (parent || layer).appendChild(d); return d;
  }
  function rgba(hex, a) { return 'rgba(' + C.rgbOf(hex).join(',') + ',' + a + ')'; }
  var stitchC = WORLD ? D.stitch : C.cssVar('--c-' + P.lock_stitch_role);

  // ---------------------------------------------------------------- полотно
  if (WORLD) {
    var grain = C.grainTiles(1, 256, P.grain_seed, { alpha: P.grain_alpha, sigma: 0.7 })[0];
    div({ backgroundColor: D.denim,
          backgroundImage: 'url(' + grain + '),repeating-linear-gradient(45deg,' + rgba(D.denim_light, 0.55) + ' 0 2px,transparent 2px 6px),'
            + 'repeating-linear-gradient(-45deg,' + rgba(D.denim_dark, 0.35) + ' 0 1px,transparent 1px 9px)',
          backgroundSize: '256px 256px,auto,auto' });
    var wx = P.window_in[0] * PX, wy = P.window_in[1] * PX, ww = P.window_in[2] * PX, wh = P.window_in[3] * PX;
    div({ left: wx + 'px', top: wy + 'px', width: ww + 'px', height: wh + 'px', borderRadius: P.window_radius_px + 'px',
          backgroundColor: D.linen, boxShadow: '0 5px 0 ' + rgba(D.denim_dark, 0.8) + ', 0 10px 18px ' + rgba(D.shade, 0.35),
          backgroundImage: 'repeating-linear-gradient(0deg,' + rgba(D.felt_brown, 0.045) + ' 0 1px,transparent 1px 4px),'
            + 'repeating-linear-gradient(90deg,' + rgba(D.felt_brown, 0.045) + ' 0 1px,transparent 1px 4px)' });
  } else {
    var ic = C.rgbOf(C.cssVar('--c-ink')).join(',');
    div({ backgroundImage: 'repeating-linear-gradient(45deg,rgba(' + ic + ',' + P.lock_weave_alpha + ') 0 1px,transparent 1px 6px)' });
  }
  var svg = C.svg('svg', { width: String(W), height: String(H), viewBox: '0 0 ' + W + ' ' + H }, layer);
  svg.style.position = 'absolute'; svg.style.left = '0'; svg.style.top = '0';
  // окна под текстом (StyleCore.textWindows): зоны текста — из раскладки сцены, а не из стиля; середина
  // окна — фон бренда, контраст надписи = контраст бренда на любом фильме (V21); оформление — языком мира
  var wins = WORLD ? C.textWindows(api, FILM, NAME, { parent: layer, pad: P.win_pad_px, css: { borderRadius: '12px', outline: '2px dashed ' + D.stitch, outlineOffset: '-7px', boxShadow: '0 3px 0 ' + 'rgba(' + C.rgbOf(D.shade).join(',') + ',0.2)' } }) : null;
  function S(g, tag, a) { return C.svg(tag, a, g); }
  function felt(g, d, fill, thread, cx, cy, k) {      // фетр: тень, лоскут, строчка внутрь
    S(g, 'path', { d: d, fill: D.shade, 'fill-opacity': 0.22, transform: 'translate(3,4)' });
    S(g, 'path', { d: d, fill: fill });
    k = k || 0.84;
    S(g, 'path', { d: d, fill: 'none', stroke: thread, 'stroke-width': 2.2, 'stroke-dasharray': '7 5', 'stroke-linecap': 'round',
                   transform: 'translate(' + cx + ',' + cy + ') scale(' + k + ') translate(' + (-cx) + ',' + (-cy) + ')',
                   'vector-effect': 'non-scaling-stroke' });
  }
  function circ(cx, cy, r) { return 'M' + (cx - r) + ' ' + cy + 'a' + r + ' ' + r + ' 0 1 0 ' + 2 * r + ' 0a' + r + ' ' + r + ' 0 1 0 ' + (-2 * r) + ' 0Z'; }
  function rrect(x, y, w, h, r) {
    return 'M' + (x + r) + ' ' + y + 'H' + (x + w - r) + 'Q' + (x + w) + ' ' + y + ' ' + (x + w) + ' ' + (y + r) + 'V' + (y + h - r) + 'Q' + (x + w) + ' ' + (y + h) + ' '
      + (x + w - r) + ' ' + (y + h) + 'H' + (x + r) + 'Q' + x + ' ' + (y + h) + ' ' + x + ' ' + (y + h - r) + 'V' + (y + r) + 'Q' + x + ' ' + y + ' ' + (x + r) + ' ' + y + 'Z';
  }
  function cloudD(x, y, s) {
    var b = y + s * 0.62;
    return 'M' + (x + s * 0.12) + ' ' + b + 'Q' + (x) + ' ' + (b - s * 0.2) + ' ' + (x + s * 0.2) + ' ' + (b - s * 0.24) + 'Q' + (x + s * 0.26) + ' ' + (b - s * 0.48) + ' '
      + (x + s * 0.48) + ' ' + (b - s * 0.38) + 'Q' + (x + s * 0.66) + ' ' + (b - s * 0.56) + ' ' + (x + s * 0.76) + ' ' + (b - s * 0.3) + 'Q' + (x + s) + ' ' + (b - s * 0.3) + ' '
      + (x + s * 0.92) + ' ' + b + 'Z';
  }
  function planeD(x, y, s) {
    return 'M' + (x + s * 0.1) + ' ' + (y + s * 0.62) + 'L' + (x + s * 0.92) + ' ' + (y + s * 0.3) + 'L' + (x + s * 0.5) + ' ' + (y + s * 0.78) + 'L' + (x + s * 0.44) + ' ' + (y + s * 0.6) + 'Z';
  }
  function sun(g, cx, cy, r) {
    var rays = S(g, 'g', {}), d = [];
    for (var k = 0; k < 10; k++) {
      var a = k / 10 * Math.PI * 2, a1 = a - 0.16, a2 = a + 0.16;
      d.push('M' + (cx + Math.cos(a1) * r * 1.12) + ' ' + (cy + Math.sin(a1) * r * 1.12) + 'L' + (cx + Math.cos(a) * r * 1.55) + ' ' + (cy + Math.sin(a) * r * 1.55)
        + 'L' + (cx + Math.cos(a2) * r * 1.12) + ' ' + (cy + Math.sin(a2) * r * 1.12) + 'Z');
    }
    S(rays, 'path', { d: d.join(''), fill: D.felt_ray });
    felt(g, circ(cx, cy, r), D.felt_sun, D.felt_ray, cx, cy, 0.86);
    S(g, 'path', { d: 'M' + (cx - r * 0.38) + ' ' + (cy - r * 0.1) + 'q' + r * 0.1 + ' -' + r * 0.14 + ' ' + r * 0.2 + ' 0M' + (cx + r * 0.18) + ' ' + (cy - r * 0.1)
      + 'q' + r * 0.1 + ' -' + r * 0.14 + ' ' + r * 0.2 + ' 0M' + (cx - r * 0.3) + ' ' + (cy + r * 0.22) + 'q' + r * 0.3 + ' ' + r * 0.3 + ' ' + r * 0.6 + ' 0',
      fill: 'none', stroke: D.felt_brown, 'stroke-width': 3, 'stroke-linecap': 'round' });
    return rays;
  }

  var world = [], seams = [], spin = [], titles = [], outl = [];
  if (WORLD) {
    // строчка по краю кадра и по лоскуту — «прошивается» в начале сцены
    var e = P.edge_inset_px, si = P.seam_inset_px;
    [S(svg, 'path', { d: rrect(e, e, W - 2 * e, H - 2 * e, 18), fill: 'none', stroke: D.thread, 'stroke-width': P.seam_width, 'data-dash': P.seam_dash, 'stroke-linecap': 'round' }),
     S(svg, 'path', { d: rrect(wx + si, wy + si, ww - 2 * si, wh - 2 * si, P.window_radius_px - 6), fill: 'none', stroke: D.stitch, 'stroke-width': P.seam_width,
                      'data-dash': P.seam_dash, 'stroke-linecap': 'round' })].forEach(function (p) { seams.push(p); });
    // вязаная трава под лоскутом
    var ky = wy + wh + 6, knit = [];
    for (var x = 0; x < W; x += 14) knit.push('M' + x + ' ' + ky + 'l7 9l7 -9M' + x + ' ' + (ky + 9) + 'l7 9l7 -9');
    S(svg, 'rect', { x: 0, y: ky - 3, width: W, height: H - ky + 3, fill: D.felt_green_dark });
    S(svg, 'path', { d: knit.join(''), fill: 'none', stroke: D.felt_green, 'stroke-width': 5, 'stroke-linejoin': 'round' });
    // верхнее поле: солнце, облака, вышитый самолётик со стежковым следом
    var top = S(svg, 'g', {});
    spin.push({ g: sun(top, 1.2 * PX, 0.98 * PX, 50), cx: 1.2 * PX, cy: 0.98 * PX });
    [[2.6, 0.32, 1.5, 0], [8.4, 0.18, 1.3, 1]].forEach(function (c) {
      var g = S(top, 'g', {}), s = c[2] * PX; felt(g, cloudD(c[0] * PX, c[1] * PX, s), D.felt_white, D.denim_light, c[0] * PX + s / 2, c[1] * PX + s * 0.45);
      world.push({ i: -1, g: g, kind: 'sway', k: c[3], t0: -1 });
    });
    var trail = S(top, 'path', { d: 'M' + 4.4 * PX + ' ' + 1.5 * PX + 'C' + 5 * PX + ' ' + 1.0 * PX + ' ' + 5.6 * PX + ' ' + 1.6 * PX + ' ' + 6.3 * PX + ' ' + 0.95 * PX,
      fill: 'none', stroke: D.thread, 'stroke-width': 2.5, 'data-dash': '8 7', 'stroke-linecap': 'round' });
    seams.push(trail);
    var pg = S(top, 'g', {}); felt(pg, planeD(6.2 * PX, 0.3 * PX, 1.2 * PX), D.felt_red, D.felt_cream, 6.8 * PX, 0.95 * PX, 0.78);
    S(pg, 'path', { d: 'M' + (6.2 * PX + 1.2 * PX * 0.44) + ' ' + (0.3 * PX + 1.2 * PX * 0.6) + 'L' + (6.2 * PX + 1.2 * PX * 0.92) + ' ' + (0.3 * PX + 1.2 * PX * 0.3),
      stroke: D.felt_cream, 'stroke-width': 2, 'stroke-dasharray': '6 4' });
    world.push({ i: -1, g: pg, kind: 'bob', k: 2, t0: -1 });
    // нашивка под табло глав
    felt(top, rrect(11.33 * PX, 0.82 * PX, 7.56 * PX, 0.84 * PX, 14), D.felt_cream, D.felt_red, 15.11 * PX, 1.24 * PX, 0.985);

    // предметы в зонах сцены
    var DRAW = {
      cloud: function (g, x, y, s) { felt(g, cloudD(x, y + s * 0.1, s), D.felt_white, D.denim_light, x + s / 2, y + s * 0.5); },
      plane: function (g, x, y, s) {
        felt(g, planeD(x, y, s), D.felt_red, D.felt_cream, x + s * 0.5, y + s * 0.55, 0.78);
        S(g, 'path', { d: 'M' + (x - s * 0.1) + ' ' + (y + s * 0.9) + 'Q' + (x + s * 0.05) + ' ' + (y + s * 0.6) + ' ' + (x + s * 0.12) + ' ' + (y + s * 0.64),
          fill: 'none', stroke: D.stitch, 'stroke-width': 2.4, 'stroke-dasharray': '7 6', 'stroke-linecap': 'round' });
      },
      button: function (g, x, y, s) {
        var cx = x + s / 2, cy = y + s / 2, r = s * 0.3;
        S(g, 'path', { d: circ(cx, cy, r), fill: D.shade, 'fill-opacity': 0.22, transform: 'translate(3,4)' });
        S(g, 'path', { d: circ(cx, cy, r), fill: D.button });
        S(g, 'path', { d: circ(cx, cy, r * 0.78), fill: 'none', stroke: D.felt_brown, 'stroke-width': 3 });
        [[-1, -1], [1, -1], [-1, 1], [1, 1]].forEach(function (q) { S(g, 'path', { d: circ(cx + q[0] * r * 0.24, cy + q[1] * r * 0.24, r * 0.1), fill: D.felt_brown }); });
        S(g, 'path', { d: 'M' + (cx - r * 0.24) + ' ' + (cy - r * 0.24) + 'L' + (cx + r * 0.24) + ' ' + (cy + r * 0.24) + 'M' + (cx + r * 0.24) + ' ' + (cy - r * 0.24) + 'L' + (cx - r * 0.24) + ' ' + (cy + r * 0.24),
          stroke: D.felt_red, 'stroke-width': 3, 'stroke-linecap': 'round' });
      },
      tree: function (g, x, y, s) {
        felt(g, rrect(x + s * 0.45, y + s * 0.55, s * 0.1, s * 0.4, 3), D.felt_brown, D.felt_cream, x + s / 2, y + s * 0.75, 0.7);
        felt(g, circ(x + s / 2, y + s * 0.38, s * 0.28), D.felt_green, D.felt_green_dark, x + s / 2, y + s * 0.38);
      },
      heart: function (g, x, y, s) {
        var cx = x + s / 2, t = y + s * 0.3, b = y + s * 0.88;
        felt(g, 'M' + cx + ' ' + b + 'C' + (x + s * 0.05) + ' ' + (y + s * 0.6) + ' ' + (x + s * 0.08) + ' ' + (y + s * 0.12) + ' ' + cx + ' ' + t
          + 'C' + (x + s * 0.92) + ' ' + (y + s * 0.12) + ' ' + (x + s * 0.95) + ' ' + (y + s * 0.6) + ' ' + cx + ' ' + b + 'Z', D.felt_pink, D.felt_cream, cx, y + s * 0.5, 0.8);
      },
      spool: function (g, x, y, s) {
        var cx = x + s / 2;
        felt(g, rrect(cx - s * 0.18, y + s * 0.22, s * 0.36, s * 0.56, 6), D.felt_red, D.felt_cream, cx, y + s / 2, 0.8);
        for (var k = 0; k < 7; k++) S(g, 'path', { d: 'M' + (cx - s * 0.17) + ' ' + (y + s * (0.27 + k * 0.07)) + 'h' + s * 0.34, stroke: D.stitch, 'stroke-width': 2 });
        S(g, 'path', { d: rrect(cx - s * 0.28, y + s * 0.14, s * 0.56, s * 0.09, 4) + rrect(cx - s * 0.28, y + s * 0.77, s * 0.56, s * 0.09, 4), fill: D.button });
        S(g, 'path', { d: 'M' + (cx + s * 0.17) + ' ' + (y + s * 0.6) + 'q' + s * 0.2 + ' ' + s * 0.05 + ' ' + s * 0.28 + ' ' + s * 0.3, fill: 'none', stroke: D.stitch, 'stroke-width': 2 });
      }
    };
    var ORDER = cfg.objects.filter(function (k) { return DRAW[k]; });
    FILM.scenes.forEach(function (sc, i) {
      if (sc.style !== NAME) return;
      C.slots(sc.decor_zones, ORDER.length, 14).forEach(function (b, k) {
        var kind = ORDER[k % ORDER.length], g = S(svg, 'g', {}), inner = S(g, 'g', {});
        DRAW[kind](inner, b[0], b[1], b[2]);
        world.push({ i: i, g: g, inner: inner, kind: kind, k: k, cx: b[0] + b[2] / 2, cy: b[1] + b[2] / 2, t0: sc.start + P.enter_from + k * P.enter_gap,
                     start: sc.start });
      });
    });
    // нашивка под заголовком: размер — по строке заголовка (шрифт стиля), каждый кадр
    scenes.forEach(function (id) {
      var fr = document.getElementById('title--' + id), span = fr && fr.querySelector('.t');
      if (!span) return;
      var g = S(svg, 'g', {});
      titles.push({ fr: fr, span: span, g: g, sh: S(g, 'path', { fill: D.shade, 'fill-opacity': 0.2 }), rim: S(g, 'path', { fill: D.felt_red }),
                    body: S(g, 'path', { fill: D.felt_cream }),
                    st: S(g, 'path', { fill: 'none', stroke: D.felt_red, 'stroke-width': 2.2, 'stroke-dasharray': '7 5', 'stroke-linecap': 'round' }) });
    });
  }
  // строчка вокруг карточек и плашек — и в мире, и под замком
  function inStyle(el) { var s = el.closest('.scene'); return s && s.getAttribute('data-style') === NAME; }
  (P.outline || []).forEach(function (sel) {
    document.querySelectorAll('#content ' + sel).forEach(function (el) {
      if (inStyle(el)) outl.push({ el: el, p: S(svg, 'path', { fill: 'none', stroke: stitchC, 'stroke-width': 2.4, 'stroke-dasharray': '10 7', 'stroke-linecap': 'round' }) });
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
  function backOut(x, k) { x -= 1; return 1 + (k + 1) * x * x * x + k * x * x; }

  return {
    render: function (t) {
      var w = api.styleWeight(NAME, t);
      api.setStyle(layer, 'opacity', api.styleOpacity(NAME, t, layer).toFixed(3));
      api.setStyle(layer, 'visibility', w > 0.001 ? 'visible' : 'hidden');
      if (w <= 0.001) return;
      if (wins) wins.render(t);
      var ts = api.stepTime(t, P.step_frames), o0 = root.getBoundingClientRect(), cur = api.styleAt(t), sStart = 0;
      FILM.scenes.forEach(function (sc) { if (sc.start <= t && sc.style === NAME) sStart = sc.start; });
      void cur;
      outl.forEach(function (it) {
        var o = opacityOf(it.el); api.setAttr(it.p, 'opacity', o.toFixed(3));
        if (o <= 0.001) return;
        var r = it.el.getBoundingClientRect(), g = P.outline_gap_px;
        api.setAttr(it.p, 'd', rrect(r.left - o0.left - g, r.top - o0.top - g, r.width + 2 * g, r.height + 2 * g, 10));
      });
      if (!WORLD) return;
      C.drawOn(seams, api.clamp01((ts - sStart - P.sew_from) / P.sew_in));
      titles.forEach(function (tt) {
        var o = parseFloat(tt.fr.style.opacity) || 0;
        api.setAttr(tt.g, 'opacity', o.toFixed(3));
        if (o <= 0.001) return;
        var rg = document.createRange(); rg.selectNodeContents(tt.span);
        var r = rg.getBoundingClientRect(), px = P.patch_pad[0], py = P.patch_pad[1], rim = P.patch_rim_px;
        var x = r.left - o0.left - px, y = r.top - o0.top - py, ww2 = r.width + 2 * px, hh = r.height + 2 * py;
        api.setAttr(tt.sh, 'd', rrect(x + 3, y + 5, ww2, hh, 16));
        api.setAttr(tt.rim, 'd', rrect(x, y, ww2, hh, 16));
        api.setAttr(tt.body, 'd', rrect(x + rim, y + rim, ww2 - 2 * rim, hh - 2 * rim, 12));
        api.setAttr(tt.st, 'd', rrect(x + rim + 5, y + rim + 5, ww2 - 2 * rim - 10, hh - 2 * rim - 10, 9));
      });
      spin.forEach(function (s) { api.setAttr(s.g, 'transform', 'rotate(' + (ts * P.sun_turn_deg_sec % 360).toFixed(2) + ' ' + s.cx + ' ' + s.cy + ')'); });
      world.forEach(function (o) {
        var sw = o.i < 0 ? 1 : api.sceneWeight(o.i, t);
        api.setAttr(o.g, 'opacity', sw.toFixed(3));
        if (sw <= 0.001) return;
        if (o.kind === 'sway') { api.setAttr(o.g, 'transform', 'translate(' + (Math.sin(ts * 0.9 + o.k * 2) * P.sway_px).toFixed(1) + ',0)'); return; }
        if (o.kind === 'bob') { api.setAttr(o.g, 'transform', 'translate(0,' + (Math.sin(ts * 1.6) * P.sway_px).toFixed(1) + ')'); return; }
        var p = (ts - o.t0) / P.pop_sec;
        if (p < 0) { api.setAttr(o.g, 'visibility', 'hidden'); return; }
        api.setAttr(o.g, 'visibility', 'visible');
        var sc = 0.6 + 0.4 * backOut(Math.min(1, p), 1.4), dy = o.kind === 'cloud' || o.kind === 'plane' ? Math.sin(ts * 1.4 + o.k) * P.sway_px * 0.6 : 0;
        var rot = o.kind === 'button' ? Math.sin(ts * 1.1 + o.k) * 6 : 0;
        api.setAttr(o.g, 'transform', 'translate(' + o.cx + ',' + (o.cy + dy).toFixed(1) + ') rotate(' + rot.toFixed(2) + ') scale(' + sc.toFixed(3) + ') translate(' + (-o.cx) + ',' + (-o.cy) + ')');
      });
    },
    probe: function (t) { return { style: NAME, weight: api.styleWeight(NAME, t), world: WORLD }; }
  };
});
