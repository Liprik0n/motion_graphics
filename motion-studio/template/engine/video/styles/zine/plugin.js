/* Зин-коллаж — плагин стиля (engine/video/styles/README.md). Мир — в слое 'back'; скотч на карточках — в слое
   'over' (только по углам карточек и концам плашек, мимо строк текста; без смешения и фильтров).

   Мир (cfg.world): серая бумага (decor.paper) с волокнами; полосы «авиа» сверху и снизу; обрывок плёнки у
   правого края и тетрадный клочок у левого; в зонах сцены — наклеенные вырезки с рваным краем, тенью и
   полоской скотча: «ШУМ» на розовом растре, молния, тетрадный клочок, марка со штемпелем, звезда-взрыв,
   фото с растром. Заголовок — буквами из разных журналов (StyleCore.codeTitle): у каждой буквы своя
   плашка, свой шрифт (роль из params.cut_fonts — файлы движка, style.json fonts), поворот и сдвиг от сида.
   Движение: стоп-моушен «на тройках» (step_frames) — вырезка шлёпается с перелётом и подрагивает.
   При style_brand_lock (cfg.world = false): бумажная фактура поверх фирменного фона и скотч роли бренда.

   Детерминизм: случайность — rng(hash(id) + номер рисунка); рисунок = номер кадра / step_frames. */
(window.StagePlugins = window.StagePlugins || []).push(function (FILM, api) {
  'use strict';
  var NAME = 'zine', cfg = api.styleConfig(NAME);
  if (!cfg) return null;
  var C = window.StyleCore, P = cfg.params, D = cfg.decor, WORLD = cfg.world;
  var root = document.getElementById('root'), W = root.clientWidth, H = root.clientHeight;
  var scenes = api.styleScenes(NAME);
  var layer = api.addLayer('zn-back', 'back');
  var paper = document.createElement('div'); paper.className = 'layer';
  if (WORLD) paper.style.backgroundColor = D.paper;
  paper.style.backgroundImage = 'url(' + C.paperTile(256, P.paper_seed, { alpha: P.paper_alpha, fibres: 90 }) + ')';
  paper.style.backgroundSize = '256px 256px';
  layer.appendChild(paper);
  var svg = C.svg('svg', { width: String(W), height: String(H), viewBox: '0 0 ' + W + ' ' + H }, layer);
  svg.style.position = 'absolute'; svg.style.left = '0'; svg.style.top = '0';
  // окна под текстом (StyleCore.textWindows): зоны текста — из раскладки сцены, а не из стиля; середина
  // окна — фон бренда, контраст надписи = контраст бренда на любом фильме (V21); оформление — языком мира
  var wins = WORLD ? C.textWindows(api, FILM, NAME, { parent: layer, pad: P.win_pad_px, css: { boxShadow: '4px 5px 0 ' + 'rgba(' + C.rgbOf(D.shadow).join(',') + ',0.55)' } }) : null;
  function S(g, tag, a) { return C.svg(tag, a, g); }
  function torn(x, y, w, h, rnd, amp, step) {      // многоугольник с рваным краем
    var pts = [], k, n;
    function edge(x0, y0, x1, y1, nx, ny) {
      n = Math.max(2, Math.round(Math.hypot(x1 - x0, y1 - y0) / step));
      for (k = 0; k < n; k++) {
        var f = k / n, j = (rnd() - 0.5) * 2 * amp;
        pts.push((x0 + (x1 - x0) * f + nx * j).toFixed(1) + ' ' + (y0 + (y1 - y0) * f + ny * j).toFixed(1));
      }
    }
    edge(x, y, x + w, y, 0, 1); edge(x + w, y, x + w, y + h, 1, 0); edge(x + w, y + h, x, y + h, 0, 1); edge(x, y + h, x, y, 1, 0);
    return 'M' + pts.join(' L') + 'Z';
  }
  function txt(g, x, y, str, size, fill, family, extra) {
    var t = C.text(g, x, y, str, Object.assign({ 'font-size': String(size), fill: fill, 'font-weight': '700' }, extra || {}));
    t.style.fontFamily = family;
    return t;
  }
  function tape(g, cx, cy, w, h, ang, color, alpha) {
    return S(g, 'rect', { x: (cx - w / 2).toFixed(1), y: (cy - h / 2).toFixed(1), width: w, height: h, fill: color, 'fill-opacity': alpha,
                          transform: 'rotate(' + ang + ' ' + cx.toFixed(1) + ' ' + cy.toFixed(1) + ')' });
  }

  var world = [], titleR = null;
  if (WORLD) {
    var dots = C.halftone('zn-dots', { cell: 9, r: 2.6, color: D.white, opacity: 0.55 });
    var dotsDark = C.halftone('zn-dots-dark', { cell: 7, r: 2.2, color: D.paper_light, opacity: 0.9 });
    // полосы «авиа»
    [P.airmail_y_px, H - P.airmail_y_px - P.airmail_h_px].forEach(function (y) {
      var cols = [D.red, D.white, D.blue, D.white, D.black, D.white], seg = P.airmail_seg_px, h = P.airmail_h_px, by = {};
      S(svg, 'rect', { x: 0, y: y, width: W, height: h, fill: D.white });
      for (var x = -seg, k = 0; x < W + seg; x += seg, k++) {
        var c = cols[k % cols.length];
        (by[c] = by[c] || []).push('M' + x + ' ' + (y + h) + 'l' + h * 0.6 + ' ' + (-h) + 'h' + seg + 'l' + (-h * 0.6) + ' ' + h + 'z');
      }
      Object.keys(by).forEach(function (c) { S(svg, 'path', { d: by[c].join(''), fill: c }); });
    });
    // обрывок плёнки у правого края
    var fs = S(svg, 'g', { transform: 'rotate(2 1860 600)' }), fx = 1832, fy = 250, fw = 58, fh = 640;
    S(fs, 'rect', { x: fx, y: fy, width: fw, height: fh, fill: D.film });
    for (var j = 0; j < 22; j++) {
      S(fs, 'rect', { x: fx + 5, y: fy + 8 + j * 29, width: 9, height: 14, rx: 2, fill: D.hole });
      S(fs, 'rect', { x: fx + fw - 14, y: fy + 8 + j * 29, width: 9, height: 14, rx: 2, fill: D.hole });
    }
    for (j = 0; j < 4; j++) S(fs, 'rect', { x: fx + 18, y: fy + 14 + j * 156, width: fw - 36, height: 136, fill: D.paper_light, 'fill-opacity': 0.25 });
    // тетрадный клочок у левого края
    var nr = C.rng(91), ng = S(svg, 'g', { transform: 'rotate(-3 60 450)' });
    S(ng, 'path', { d: torn(16, 330, 92, 250, nr, 3, 12), fill: D.paper_light });
    for (j = 0; j < 9; j++) S(ng, 'path', { d: 'M18 ' + (360 + j * 24) + 'H104', stroke: D.ruled, 'stroke-width': 1.4 });
    S(ng, 'path', { d: 'M34 334V576', stroke: D.margin, 'stroke-width': 1.4 });
    txt(ng, 40, 386, '№7', 22, D.black, cfg.fonts.decor);
    tape(ng, 62, 334, 74, 22, -6, D.tape, P.tape_alpha);

    // вырезки в зонах сцены
    var DRAW = {
      noise: function (g, x, y, s, rnd) {
        var w = s * 0.8, x0 = x + s * 0.1, y0 = y + s * 0.12, d = torn(x0, y0, w, w * 0.9, rnd, 2.5, 14);
        S(g, 'path', { d: d, fill: D.pink }); S(g, 'path', { d: d, fill: dots });
        txt(g, x0 + w / 2, y0 + w * 0.6, 'ШУМ', Math.round(s * 0.2), D.white, cfg.fonts.cut_poster, { 'text-anchor': 'middle', 'letter-spacing': '2' });
        return [x0 + w / 2, y0];
      },
      bolt: function (g, x, y, s, rnd) {
        var w = s * 0.7, x0 = x + s * 0.15, y0 = y + s * 0.1, h = s * 0.85;
        S(g, 'path', { d: torn(x0, y0, w, h, rnd, 2.5, 14), fill: D.yellow });
        var u = w / 10;
        S(g, 'path', { d: 'M' + (x0 + 6 * u) + ' ' + (y0 + h * 0.08) + 'L' + (x0 + 2 * u) + ' ' + (y0 + h * 0.55) + 'L' + (x0 + 5 * u) + ' ' + (y0 + h * 0.55)
          + 'L' + (x0 + 3.5 * u) + ' ' + (y0 + h * 0.93) + 'L' + (x0 + 8.2 * u) + ' ' + (y0 + h * 0.4) + 'L' + (x0 + 5.2 * u) + ' ' + (y0 + h * 0.4) + 'Z', fill: D.black });
        return [x0 + w / 2, y0];
      },
      note: function (g, x, y, s, rnd) {
        var w = s * 0.78, h = s * 0.8, x0 = x + s * 0.11, y0 = y + s * 0.14;
        S(g, 'path', { d: torn(x0, y0, w, h, rnd, 3.5, 10), fill: D.paper_light });
        for (var k = 1; k < 7; k++) S(g, 'path', { d: 'M' + x0 + ' ' + (y0 + k * h / 7) + 'h' + w, stroke: D.ruled, 'stroke-width': 1.3 });
        S(g, 'path', { d: 'M' + (x0 + w * 0.16) + ' ' + y0 + 'v' + h, stroke: D.margin, 'stroke-width': 1.3 });
        txt(g, x0 + w * 0.22, y0 + h * 2 / 7 - 5, 'не сюда!', Math.round(s * 0.1), D.black, cfg.fonts.decor);
        S(g, 'path', { d: 'M' + (x0 + w * 0.22) + ' ' + (y0 + h * 0.52) + 'q' + w * 0.2 + ' -8 ' + w * 0.5 + ' 2', fill: 'none', stroke: D.red, 'stroke-width': 3, 'stroke-linecap': 'round' });
        S(g, 'path', { d: 'M' + (x0 + w * 0.22) + ' ' + (y0 + h * 0.68) + 'q' + w * 0.25 + ' 6 ' + w * 0.55 + ' -3', fill: 'none', stroke: D.black, 'stroke-width': 2, 'stroke-linecap': 'round' });
        return [x0 + w / 2, y0];
      },
      stamp: function (g, x, y, s) {
        var w = s * 0.62, h = s * 0.74, x0 = x + s * 0.18, y0 = y + s * 0.13, r = 5, d = [];
        S(g, 'rect', { x: x0, y: y0, width: w, height: h, fill: D.white });
        for (var k = 0; k <= w / (r * 2.6); k++) { d.push('M' + (x0 + k * r * 2.6) + ' ' + y0 + 'm-' + r + ' 0a' + r + ' ' + r + ' 0 1 0 ' + 2 * r + ' 0a' + r + ' ' + r + ' 0 1 0 -' + 2 * r + ' 0');
          d.push('M' + (x0 + k * r * 2.6) + ' ' + (y0 + h) + 'm-' + r + ' 0a' + r + ' ' + r + ' 0 1 0 ' + 2 * r + ' 0a' + r + ' ' + r + ' 0 1 0 -' + 2 * r + ' 0'); }
        for (k = 0; k <= h / (r * 2.6); k++) { d.push('M' + x0 + ' ' + (y0 + k * r * 2.6) + 'm-' + r + ' 0a' + r + ' ' + r + ' 0 1 0 ' + 2 * r + ' 0a' + r + ' ' + r + ' 0 1 0 -' + 2 * r + ' 0');
          d.push('M' + (x0 + w) + ' ' + (y0 + k * r * 2.6) + 'm-' + r + ' 0a' + r + ' ' + r + ' 0 1 0 ' + 2 * r + ' 0a' + r + ' ' + r + ' 0 1 0 -' + 2 * r + ' 0'); }
        S(g, 'path', { d: d.join(''), fill: D.paper });
        S(g, 'rect', { x: x0 + 12, y: y0 + 12, width: w - 24, height: h - 24, fill: D.blue });
        var cx = x0 + w / 2, cy = y0 + h / 2;     // самолётик на марке
        S(g, 'path', { d: 'M' + (cx - w * 0.28) + ' ' + (cy + 6) + 'L' + (cx + w * 0.28) + ' ' + (cy - h * 0.18) + 'L' + (cx - w * 0.02) + ' ' + (cy + h * 0.16) + 'Z', fill: D.white });
        txt(g, x0 + 16, y0 + h - 18, '7 коп', 13, D.white, cfg.fonts.decor);
        S(g, 'circle', { cx: x0 + w * 0.9, cy: y0 + h * 0.3, r: s * 0.16, fill: 'none', stroke: D.black, 'stroke-width': 2.5, 'stroke-opacity': 0.7 });
        for (k = 0; k < 3; k++) S(g, 'path', { d: 'M' + (x0 + w * 0.95) + ' ' + (y0 + h * 0.62 + k * 10) + 'q15 -8 30 0t30 0t30 0', fill: 'none', stroke: D.black, 'stroke-width': 2, 'stroke-opacity': 0.6 });
        return [x0 + w / 2, y0];
      },
      star: function (g, x, y, s, rnd) {
        var cx = x + s / 2, cy = y + s / 2, pts = [];
        for (var k = 0; k < 24; k++) { var a = k / 24 * Math.PI * 2, r = (k % 2 ? 0.27 : 0.46) * s * (0.92 + rnd() * 0.16); pts.push((cx + Math.cos(a) * r).toFixed(1) + ' ' + (cy + Math.sin(a) * r).toFixed(1)); }
        S(g, 'path', { d: 'M' + pts.join(' L') + 'Z', fill: D.red });
        txt(g, cx, cy + s * 0.11, 'СТОП', Math.round(s * 0.13), D.white, cfg.fonts.cut_poster, { 'text-anchor': 'middle' });
        return [cx, cy - s * 0.3];
      },
      photo: function (g, x, y, s) {
        var w = s * 0.72, h = s * 0.82, x0 = x + s * 0.14, y0 = y + s * 0.1;
        S(g, 'rect', { x: x0, y: y0, width: w, height: h, fill: D.white });
        S(g, 'rect', { x: x0 + 10, y: y0 + 10, width: w - 20, height: h * 0.7, fill: D.black });
        S(g, 'rect', { x: x0 + 10, y: y0 + 10 + h * 0.36, width: w - 20, height: h * 0.34, fill: dotsDark });
        S(g, 'circle', { cx: x0 + w * 0.7, cy: y0 + h * 0.22, r: w * 0.08, fill: D.paper_light });
        txt(g, x0 + 14, y0 + h - 14, 'фото', 16, D.black, cfg.fonts.decor);
        return [x0 + w / 2, y0];
      }
    };
    var ORDER = cfg.objects.filter(function (k) { return DRAW[k]; });
    FILM.scenes.forEach(function (sc, i) {
      if (sc.style !== NAME) return;
      C.slots(sc.decor_zones, ORDER.length, 14).forEach(function (b, k) {
        var kind = ORDER[k % ORDER.length], rnd = C.rng(C.hash(sc.id + kind) + k), g = S(svg, 'g', {}), sh = S(g, 'g', { opacity: 0.3, transform: 'translate(5,6)' });
        var body = S(g, 'g', {}), top = DRAW[kind](body, b[0], b[1], b[2], rnd);
        DRAW[kind](sh, b[0], b[1], b[2], C.rng(C.hash(sc.id + kind) + k));
        [].forEach.call(sh.querySelectorAll('*'), function (n) { if (n.getAttribute('fill') !== 'none') n.setAttribute('fill', D.shadow); n.removeAttribute('stroke'); });
        tape(body, top[0] + (rnd() - 0.5) * 20, top[1] + 2, b[2] * 0.36, 24, (rnd() - 0.5) * 16, D.tape, P.tape_alpha);
        world.push({ i: i, g: g, cx: b[0] + b[2] / 2, cy: b[1] + b[2] / 2, tilt: (rnd() - 0.5) * 2 * P.tilt_deg, seed: C.hash(sc.id + kind),
                     t0: sc.start + P.enter_from + k * P.enter_gap });
      });
    });

    // заголовок — вырезанные буквы
    var meas = document.createElement('canvas').getContext('2d');
    var CUT = [[D.black, D.white], [D.yellow, D.black], [D.white, D.pink], [D.pink, D.white], [D.paper_light, D.black], [D.red, D.white], [D.white, D.blue]];
    titleR = C.codeTitle(api, scenes, S(svg, 'g', {}), function (g, text, box) {
      var rnd = C.rng(C.hash(text)), fsz = P.cut_size_px, th = P.cut_tile_h_px, letters = [], x = 0;
      for (var k = 0; k < text.length; k++) {
        var ch = text[k];
        if (ch === ' ') { x += P.cut_space_px; continue; }
        var fam = P.cut_fonts[Math.floor(rnd() * P.cut_fonts.length)], col = CUT[Math.floor(rnd() * CUT.length)];
        var size = fsz * (0.88 + rnd() * 0.18);
        meas.font = '700 ' + size + 'px ' + C.fontOf(NAME, fam);      // ширина буквы — по шрифту-файлу роли
        var tw = meas.measureText(ch).width, w = tw + 2 * P.cut_pad_px;
        letters.push({ ch: ch, fam: fam, col: col, size: size, x: x, w: w, rot: (rnd() - 0.5) * 2 * P.cut_rot_deg, dy: (rnd() - 0.5) * 2 * P.cut_dy_px, r: rnd() });
        x += w - 2;
      }
      var scale = Math.min(1, (box.w - 8) / Math.max(1, x)), cy = box.y + box.h / 2;
      var inner = S(g, 'g', { transform: 'translate(' + (box.x + 4) + ',' + cy.toFixed(1) + ') scale(' + scale.toFixed(3) + ')' });
      letters.forEach(function (L) {
        var lg = S(inner, 'g', { transform: 'translate(' + (L.x + L.w / 2).toFixed(1) + ',' + L.dy.toFixed(1) + ') rotate(' + L.rot.toFixed(1) + ')' });
        S(lg, 'path', { d: torn(-L.w / 2, -th / 2, L.w, th, C.rng(Math.floor(L.r * 1e6)), 1.2, 9), fill: L.col[0] });
        txt(lg, 0, th * 0.3, L.ch, L.size.toFixed(1), L.col[1], cfg.fonts[L.fam], { 'text-anchor': 'middle' });
      });
      // рамка надписи (с ячейками глифов) обязана лечь в рамку заголовка: вписать масштабом и отцентровать
      var bb = inner.getBBox(), k2 = Math.min(scale, (box.h - 6) / bb.height * scale, (box.w - 8) / bb.width * scale);
      var ox = box.x + 4 - bb.x * k2, oy = box.y + box.h / 2 - (bb.y + bb.height / 2) * k2;
      inner.setAttribute('transform', 'translate(' + ox.toFixed(1) + ',' + oy.toFixed(1) + ') scale(' + k2.toFixed(3) + ')');
    });
  }

  // скотч по углам карточек и концам плашек — слой над содержанием
  var over = api.addLayer('zn-over', 'over');
  var osvg = C.svg('svg', { width: String(W), height: String(H), viewBox: '0 0 ' + W + ' ' + H }, over);
  osvg.style.position = 'absolute'; osvg.style.left = '0'; osvg.style.top = '0';
  var tapeC = WORLD ? D.tape : C.cssVar('--c-' + P.lock_tape_role), tapes = [];
  function inStyle(el) { var s = el.closest('.scene'); return s && s.getAttribute('data-style') === NAME; }
  [['.k-card', 'corners'], ['.k-plaque', 'ends']].forEach(function (q) {
    document.querySelectorAll('#content ' + q[0]).forEach(function (el) {
      if (!inStyle(el)) return;
      var g = S(osvg, 'g', {}), seed = C.hash(el.id || 'x');
      tapes.push({ el: el, how: q[1], g: g, a: tape(g, 0, 0, P.tape_w_px, P.tape_h_px, 0, tapeC, P.tape_alpha),
                   b: tape(g, 0, 0, P.tape_w_px, P.tape_h_px, 0, tapeC, P.tape_alpha), seed: seed });
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
  function place(r, cx, cy, ang) {
    api.setAttr(r, 'x', (cx - P.tape_w_px / 2).toFixed(1)); api.setAttr(r, 'y', (cy - P.tape_h_px / 2).toFixed(1));
    api.setAttr(r, 'transform', 'rotate(' + ang.toFixed(1) + ' ' + cx.toFixed(1) + ' ' + cy.toFixed(1) + ')');
  }
  function backOut(x, k) { x -= 1; return 1 + (k + 1) * x * x * x + k * x * x; }

  return {
    render: function (t) {
      var w = api.styleWeight(NAME, t);
      api.setStyle(layer, 'opacity', api.styleOpacity(NAME, t, layer).toFixed(3)); api.setStyle(over, 'opacity', w.toFixed(3));
      api.setStyle(layer, 'visibility', w > 0.001 ? 'visible' : 'hidden'); api.setStyle(over, 'visibility', w > 0.001 ? 'visible' : 'hidden');
      if (w <= 0.001) return;
      if (wins) wins.render(t);
      var ts = api.stepTime(t, P.step_frames), drawing = Math.floor(api.frameOf(t) / P.step_frames);
      if (titleR) titleR(t);
      var o0 = root.getBoundingClientRect();
      tapes.forEach(function (it) {
        var o = opacityOf(it.el);
        api.setAttr(it.g, 'opacity', o.toFixed(3));
        if (o <= 0.001) return;
        var r = it.el.getBoundingClientRect(), x = r.left - o0.left, y = r.top - o0.top, rnd = C.rng(it.seed);
        if (it.how === 'corners') { place(it.a, x + 6, y + 6, -38 + rnd() * 10); place(it.b, x + r.width - 6, y + 6, 38 - rnd() * 10); }
        else { place(it.a, x, y + r.height / 2, 84 + rnd() * 8); place(it.b, x + r.width, y + r.height / 2, 96 - rnd() * 8); }
      });
      world.forEach(function (o) {
        var sw = api.sceneWeight(o.i, t);
        api.setAttr(o.g, 'opacity', sw.toFixed(3));
        if (sw <= 0.001) return;
        var p = (ts - o.t0) / P.slap_sec;
        if (p < 0) { api.setAttr(o.g, 'visibility', 'hidden'); return; }
        api.setAttr(o.g, 'visibility', 'visible');
        var sc = 1 + P.slap_scale * (1 - backOut(Math.min(1, p), 1.7)), rr = C.rng(o.seed + drawing * 977);
        var a = o.tilt + (rr() - 0.5) * 2 * P.wobble_deg, jx = (rr() - 0.5) * 2, jy = (rr() - 0.5) * 2;
        api.setAttr(o.g, 'transform', 'translate(' + (o.cx + jx).toFixed(1) + ',' + (o.cy + jy).toFixed(1) + ') rotate(' + a.toFixed(2) + ') scale('
          + sc.toFixed(3) + ') translate(' + (-o.cx) + ',' + (-o.cy) + ')');
      });
    },
    probe: function (t) { return { style: NAME, weight: api.styleWeight(NAME, t), world: WORLD }; }
  };
});
