/* Комикс — плагин стиля (engine/video/styles/README.md). Всё в слое 'back' — под каркасом и содержанием.

   Мир (cfg.world): газетный лист (decor.newsprint) с редким полутоном; каждая зона сцены (decor_zones) —
   панель комикса в толстой чёрной рамке со смещённой тенью. Первая панель: солнечные лучи из точки фокуса
   (поворачиваются «на тройках»), звезда-взрыв «БАХ!» и молния — входят ударом с перелётом. Вторая
   панель: голубое поле с розовым полутоном, облачко реплики «ОЙ!», линии скорости, звёздочки.
   Остальные зоны — панели с лучами. Всегда (и при style_brand_lock): редкий полутон по листу ролью бренда.
   Мигания нет: звёзды «дышат» размером, лучи — поворотом (V23).

   Кадр — чистая функция времени (V24): случайности нет. Текст не трогается. */
(window.StagePlugins = window.StagePlugins || []).push(function (FILM, api) {
  'use strict';
  var NAME = 'comic', cfg = api.styleConfig(NAME);
  if (!cfg) return null;
  var C = window.StyleCore, P = cfg.params, D = cfg.decor, WORLD = cfg.world;
  var root = document.getElementById('root'), W = root.clientWidth, H = root.clientHeight;

  var layer = api.addLayer('cm-back', 'back');
  var svg = C.svg('svg', { width: String(W), height: String(H), viewBox: '0 0 ' + W + ' ' + H }, layer);
  svg.style.position = 'absolute'; svg.style.left = '0'; svg.style.top = '0';
  // окна под текстом (StyleCore.textWindows): зоны текста — из раскладки сцены, а не из стиля; середина
  // окна — фон бренда, контраст надписи = контраст бренда на любом фильме (V21); оформление — языком мира
  // окна под текстом — у сцен с каркасом (s.frame !== false; сцена, объявившая frame: false, рисует мир и подложки сама)
  var wins = WORLD && FILM.scenes.some(function (s) { return s.style === NAME && s.frame !== false; }) ? C.textWindows(api, FILM, NAME, { parent: layer, pad: P.win_pad_px, css: { border: '3px solid ' + D.ink, boxShadow: '6px 6px 0 ' + D.ink } }) : null;
  if (WORLD) C.svg('rect', { x: 0, y: 0, width: W, height: H, fill: D.newsprint }, svg);
  var pageDots = C.halftone('cm-page-dots', { cell: P.dot_cell_px, r: P.dot_r_px,
                                               color: WORLD ? D.red : C.cssVar('--c-' + P.lock_role),
                                               opacity: WORLD ? P.page_dot_alpha : P.lock_dot_alpha });
  C.svg('rect', { x: 0, y: 0, width: W, height: H, fill: pageDots }, svg);
  var pinkDots = C.halftone('cm-pink-dots', { cell: 14, r: 4.2, color: D.pink, opacity: 0.9 });
  var hotDots = C.halftone('cm-hot-dots', { cell: 10, r: 2.4, color: D.red, opacity: 0.5 });

  function S(g, tag, a) { return C.svg(tag, a, g); }
  function f1(v) { return v.toFixed(1); }
  function star(cx, cy, n, r1, r2, rot) {  // звезда / взрыв: n лучей, радиусы r1 (вершины) и r2 (впадины)
    var d = '';
    for (var k = 0; k < n * 2; k++) {
      var a = rot + k / (n * 2) * Math.PI * 2, r = k % 2 ? r2 : r1 * (k % 4 === 0 ? 1 : 0.86);
      d += (k ? ' L' : 'M') + f1(cx + Math.cos(a) * r) + ' ' + f1(cy + Math.sin(a) * r);
    }
    return d + ' Z';
  }
  function back(p, s) { var q = p - 1; return 1 + (s + 1) * q * q * q + s * q * q; }   // перелёт удара
  function label(g, x, y, str, size, fill) {
    var t = C.text(g, x, y, str, { 'text-anchor': 'middle', 'font-size': String(Math.round(size)), fill: fill,
                                   stroke: D.ink, 'stroke-width': String(Math.max(2, size * 0.06)), 'paint-order': 'stroke',
                                   'stroke-linejoin': 'round' });
    t.style.fontFamily = cfg.fonts.decor || cfg.fonts.title;
    return t;
  }

  var panels = [], hits = [], spins = [], shifts = [], twinkles = [];
  function pop(g, cx, cy, at, i) { hits.push({ g: g, cx: cx, cy: cy, at: at, i: i }); }
  if (WORLD) FILM.scenes.forEach(function (sc, i) {
    if (sc.style !== NAME) return;
    (sc.decor_zones || []).forEach(function (z, zi) {
      var x = z[0] + P.panel_pad_px, y = z[1] + P.panel_pad_px, w = z[2] - 2 * P.panel_pad_px, h = z[3] - 2 * P.panel_pad_px;
      var g = S(svg, 'g', {}), id = 'cm-clip-' + sc.id + '-' + zi;
      S(S(C.defs(), 'clipPath', { id: id }), 'rect', { x: x, y: y, width: w, height: h });
      S(g, 'rect', { x: x + P.shadow_px, y: y + P.shadow_px, width: w, height: h, fill: D.ink });
      var inner = S(g, 'g', { 'clip-path': 'url(#' + id + ')' });
      panels.push({ i: i, g: g });
      if (zi % 2 === 0) {                  // панель удара: лучи, взрыв, молния
        S(inner, 'rect', { x: x, y: y, width: w, height: h, fill: D.sun });
        var fx = x + w * 0.42, fy = y + h * 0.55, R = Math.max(w, h) * 1.2, d = '', rays = S(inner, 'g', {});
        for (var k = 0; k < P.rays; k++) {
          var a0 = k / P.rays * Math.PI * 2, a1 = a0 + Math.PI / P.rays;
          d += 'M' + f1(fx) + ' ' + f1(fy) + ' L' + f1(fx + Math.cos(a0) * R) + ' ' + f1(fy + Math.sin(a0) * R) + ' L'
            + f1(fx + Math.cos(a1) * R) + ' ' + f1(fy + Math.sin(a1) * R) + ' Z';
        }
        S(rays, 'path', { d: d, fill: D.orange });
        S(inner, 'rect', { x: x, y: y, width: w, height: h, fill: hotDots });
        spins.push({ i: i, g: rays, cx: fx, cy: fy, k: zi });
        var bg = S(inner, 'g', {}), bx = x + w * 0.4, by = y + h * 0.52, br = h * 0.42;
        S(bg, 'path', { d: star(bx, by, 11, br, br * 0.62, 0.2), fill: D.red, stroke: D.ink, 'stroke-width': 5, 'stroke-linejoin': 'round' });
        S(bg, 'path', { d: star(bx, by, 11, br * 0.72, br * 0.45, 0.35), fill: D.sun });
        label(bg, bx, by + br * 0.18, P.boom_text, br * 0.5, D.red);
        pop(bg, bx, by, sc.start + P.boom_at, i);
        var lg = S(inner, 'g', {}), lx = x + w * 0.8, ly = y + h * 0.12, ls = h * 0.75;
        S(lg, 'path', { d: 'M' + f1(lx + ls * 0.12) + ' ' + f1(ly) + ' L' + f1(lx - ls * 0.14) + ' ' + f1(ly + ls * 0.52) + ' L' + f1(lx + ls * 0.02)
          + ' ' + f1(ly + ls * 0.5) + ' L' + f1(lx - ls * 0.08) + ' ' + f1(ly + ls) + ' L' + f1(lx + ls * 0.2) + ' ' + f1(ly + ls * 0.4)
          + ' L' + f1(lx + ls * 0.04) + ' ' + f1(ly + ls * 0.42) + ' L' + f1(lx + ls * 0.22) + ' ' + f1(ly) + ' Z',
          fill: D.white, stroke: D.ink, 'stroke-width': 4, 'stroke-linejoin': 'round' });
        pop(lg, lx, ly + ls / 2, sc.start + P.bolt_at, i);
      } else {                             // панель реплики: полутон, облачко, линии скорости, звёзды
        S(inner, 'rect', { x: x, y: y, width: w, height: h, fill: D.sky });
        S(inner, 'rect', { x: x, y: y, width: w, height: h, fill: pinkDots });
        var sl = S(inner, 'g', {}), sd = '';
        for (var j = 0; j < 9; j++) {
          var yy = y + h * (0.12 + j * 0.095), len = w * (0.25 + (j * 37 % 11) / 30);
          sd += 'M' + f1(x + w - 6) + ' ' + f1(yy) + ' h' + f1(-len);
        }
        S(sl, 'path', { d: sd, stroke: D.white, 'stroke-width': 5, 'stroke-linecap': 'round' });
        S(sl, 'path', { d: sd, stroke: D.ink, 'stroke-width': 2, 'stroke-linecap': 'round', transform: 'translate(0,6)' });
        shifts.push({ i: i, g: sl });
        var ub = S(inner, 'g', {}), ux = x + w * 0.3, uy = y + h * 0.42, uw = w * 0.22, uh = h * 0.3;
        S(ub, 'path', { d: 'M' + f1(ux - uw) + ' ' + f1(uy) + ' A' + f1(uw) + ' ' + f1(uh) + ' 0 1 1 ' + f1(ux + uw * 0.2) + ' ' + f1(uy + uh * 0.98)
          + ' L' + f1(ux - uw * 0.5) + ' ' + f1(uy + uh * 1.6) + ' L' + f1(ux - uw * 0.35) + ' ' + f1(uy + uh * 0.8) + ' A' + f1(uw) + ' ' + f1(uh)
          + ' 0 0 1 ' + f1(ux - uw) + ' ' + f1(uy) + ' Z', fill: D.white, stroke: D.ink, 'stroke-width': 4, 'stroke-linejoin': 'round' });
        label(ub, ux, uy + uh * 0.28, P.bubble_text, uh * 0.8, D.red);
        pop(ub, ux, uy + uh, sc.start + P.bubble_at, i);
        [[0.66, 0.3, 0.13], [0.84, 0.62, 0.1], [0.58, 0.78, 0.08]].forEach(function (q, n) {
          var sg = S(inner, 'g', {}), cx = x + w * q[0], cy = y + h * q[1], r = h * q[2];
          S(sg, 'path', { d: star(cx, cy, 5, r, r * 0.45, -Math.PI / 2), fill: D.sun, stroke: D.ink, 'stroke-width': 3, 'stroke-linejoin': 'round' });
          twinkles.push({ i: i, g: sg, cx: cx, cy: cy, k: n });
        });
      }
      S(g, 'rect', { x: x, y: y, width: w, height: h, fill: 'none', stroke: D.ink, 'stroke-width': P.panel_border_px });
    });
  });

  /* ================================================================== НАБОР КОМИКСА
     Сцене стиля plugin даёт window.ComicKit: фигура тушью (ink), полутон (dots), звезда-взрыв (star), перелёт удара
     (back), перо переменной толщины (taper), зеркало контура (mx), пушистый круг (fluff), группа под обрезкой (clip),
     такси (taxi), вертолёт (heli), проход лопастей через кадр — шов (bladeWedge), рот по огибающей реплики (level),
     моргание (blink), дорожки ключей (track), якорь времени at({reply, at, offset}) → секунды, события элемента.
     Сцена подключается из своей разметки: (window.ComicScenes = window.ComicScenes || []).push({scene, setup});
     setup(kit, FILM, api) → {frame(t)}. Героя, слов и названий в стиле нет — они в данных проекта: героя рисует
     разметка сцены этим набором (цвета героя — роли палитры проекта), конечности размечает StyleCore.limb (V25). */
  var kitFrames = [];
  (function () {
    var INK = D.ink, LW = 6, nDots = 0;
    function A(n, k, v) { api.setAttr(n, k, v); }
    function ink(g, d, fill, o) {
      o = o || {};
      return S(g, 'path', { d: d, fill: fill || 'none', stroke: o.stroke || INK, 'stroke-width': o.w != null ? o.w : LW,
                            'stroke-linejoin': 'round', 'stroke-linecap': 'round', opacity: o.opacity != null ? o.opacity : 1 });
    }
    function dots(color, cell, r, opacity) { return C.halftone('cm-kit-dots-' + (nDots++), { cell: cell, r: r, color: color, opacity: opacity }); }
    function svgIn(host, w, h) {
      var s = C.svg('svg', { width: w, height: h, viewBox: '0 0 ' + w + ' ' + h, overflow: 'visible' }, host);
      s.style.position = 'absolute'; s.style.left = '0'; s.style.top = '0';
      return s;
    }
    var nClip = 0;
    function clip(g, d) {                    // группа, обрезанная контуром d
      var id = 'cm-kit-clip-' + (nClip++);
      S(S(C.defs(), 'clipPath', { id: id }), 'path', { d: d });
      return S(g, 'g', { 'clip-path': 'url(#' + id + ')' });
    }
    function tr(n, x, y, rot, sc) {
      A(n, 'transform', 'translate(' + f1(x) + ',' + f1(y) + ')' + (rot ? ' rotate(' + rot.toFixed(2) + ')' : '') + (sc != null && sc !== 1 ? ' scale(' + sc.toFixed(3) + ')' : ''));
    }
    /* видимость узла рисунка: «виден» = inherit, а не visible. Явное visible пересиливает скрытие самого элемента битом
       (visibility: hidden у .el): узел оставался бы в отрисовке под непрозрачностью 0, Chrome выделял бы под него слой, и
       кадры ДРУГИХ сцен зависели бы от того, заходили ли в эту (замер: V24 краснел на кадрах соседней сцены) */
    function show(n, v) { A(n, 'visibility', v ? 'inherit' : 'hidden'); }
    function level(t) {                      // огибающая голоса 0…1 в момент t (рот говорит своей репликой)
      var r = null;
      for (var i = 0; i < FILM.replies.length; i++) if (t >= FILM.replies[i].start && t < FILM.replies[i].end) r = FILM.replies[i];
      if (!r || r.silent || !r.mouth) return 0;
      var k = Math.floor((t - r.start) * FILM.fps), sum = 0, n = 0;
      for (var j = k - 1; j <= k + 1; j++) if (j >= 0 && j < r.mouth.length) { sum += +r.mouth.charAt(j); n++; }
      return n ? sum / n / 9 : 0;
    }
    function blink(t, seed) {                // 0…1: веки закрыты; раз в ≈ 3,4 с, 4 кадра
      var per = 3.4, k = Math.floor(t / per), rnd = C.rng(seed + k * 7919), at = k * per + 0.4 + rnd() * (per - 1.0), x = (t - at) * FILM.fps;
      return x >= 0 && x < 4 ? (x < 1 || x >= 3 ? 0.6 : 1) : 0;
    }
    var shade = null;
    function shadeDots() { return shade || (shade = dots(INK, 7, 1.7, 0.28)); }
    /* ---- перо: штрих переменной толщины (тушь). Линия d становится залитой фигурой: ширина идёт от w0 к w1, концы
       сходят на остриё. Длина и точки берутся у самого контура (узел в defs — в отрисовку не попадает) */
    var probe = null;
    function taper(g, d, w0, w1, fill) {
      probe = probe || S(C.defs(), 'path', {});
      probe.setAttribute('d', d);
      var L = probe.getTotalLength(), n = Math.max(6, Math.ceil(L / 5)), a = [], b = [];
      for (var i = 0; i <= n; i++) {
        var u = i / n, q = probe.getPointAtLength(L * u), q0 = probe.getPointAtLength(Math.max(0, L * u - 1)), q1 = probe.getPointAtLength(Math.min(L, L * u + 1));
        var tx = q1.x - q0.x, ty = q1.y - q0.y, len = Math.hypot(tx, ty) || 1, w = (w0 + (w1 - w0) * u) * Math.sqrt(Math.min(1, u * 6, (1 - u) * 6)) / 2;
        a.push((q.x - ty / len * w).toFixed(2) + ' ' + (q.y + tx / len * w).toFixed(2));
        b.unshift((q.x + ty / len * w).toFixed(2) + ' ' + (q.y - tx / len * w).toFixed(2));
      }
      return S(g, 'path', { d: 'M' + a.concat(b).join(' L') + ' Z', fill: fill || INK });
    }
    function mx(d) {                         // зеркало контура по вертикали (только команды M L C Q с парами x y)
      var i = 0;
      return d.replace(/-?\d+(?:\.\d+)?/g, function (n) { return (i++ % 2) ? n : String(-parseFloat(n)); });
    }
    function fluff(cx, cy, r, n, amp, rot) {  // пушистый круг: n дуг наружу
      var d = '';
      for (var k = 0; k <= n; k++) {
        var a = rot + k / n * Math.PI * 2, am = a - Math.PI / n;
        d += k ? ' Q' + f1(cx + Math.cos(am) * (r + amp * 2)) + ' ' + f1(cy + Math.sin(am) * (r + amp * 2)) + ' ' + f1(cx + Math.cos(a) * r) + ' ' + f1(cy + Math.sin(a) * r)
               : 'M' + f1(cx + Math.cos(a) * r) + ' ' + f1(cy + Math.sin(a) * r);
      }
      return d + ' Z';
    }
    /* Такси, передом влево. Начало координат — низ колёс под серединой кузова; ≈ 440 × 190.
       → {g, wheels: [g, g], light} — спицы колёс (крутит сцена), конус фары */
    function taxi(parent) {
      var g = S(parent, 'g', {}), BODY = 'M-214 -34 L-214 -84 C-214 -98 -196 -104 -150 -108 L-104 -162 C-98 -170 -88 -172 -78 -172 L92 -172 C106 -172 114 -166 124 -154 L160 -108 L196 -104 C210 -102 216 -94 216 -82 L216 -34 Z';
      var light = S(g, 'path', { d: 'M-206 -72 L-560 -26 L-560 10 L-206 -44 Z', fill: D.sun, opacity: 0.45 });
      S(g, 'path', { d: BODY, fill: D.sun });
      S(g, 'path', { d: 'M-214 -58 H216 V-34 H-214 Z', fill: D.orange });
      ink(g, BODY);
      ink(g, 'M-126 -112 L-88 -156 L-12 -156 L-12 -112 Z', D.snow_shade, { w: 5 });
      var rear = clip(g, 'M6 -112 L6 -156 L88 -156 L124 -112 Z');
      S(rear, 'rect', { x: 0, y: -160, width: 130, height: 52, fill: D.night });
      ink(g, 'M6 -112 L6 -156 L88 -156 L124 -112 Z', null, { w: 5 });
      S(g, 'path', { d: 'M-116 -116 l22 -26 M-102 -116 l22 -26', stroke: D.white, 'stroke-width': 5, 'stroke-linecap': 'round' });
      var ch = '';
      for (var k = 0; k < 20; k++) ch += 'M' + (-200 + k * 20) + ' ' + (k % 2 ? -86 : -76) + ' h20 v10 h-20 Z';
      S(g, 'path', { d: ch, fill: INK });
      ink(g, 'M-4 -108 V-40 M-134 -108 V-40 M132 -108 V-40 M18 -96 h26', null, { w: 4 });
      ink(g, 'M-24 -172 L-16 -192 L40 -192 L48 -172 Z', D.white, { w: 5 });             // фонарь на крыше
      S(g, 'path', { d: 'M-8 -186 h8 v8 h-8 Z M8 -186 h8 v8 h-8 Z M24 -186 h8 v8 h-8 Z M0 -178 h8 v6 h-8 Z M16 -178 h8 v6 h-8 Z', fill: INK });
      ink(g, 'M-214 -86 h14 v20 h-14 Z', D.white, { w: 4 }); ink(g, 'M204 -86 h12 v18 h-12 Z', D.red, { w: 4 });
      var wheels = [-128, 132].map(function (x) {
        ink(g, 'M' + (x - 40) + ' -34 a40 40 0 1 0 80 0 a40 40 0 1 0 -80 0 Z', INK);
        var w = S(g, 'g', { transform: 'translate(' + x + ',-34)' }), sp = S(w, 'g', {});
        S(sp, 'circle', { r: 18, fill: D.steel, stroke: INK, 'stroke-width': 4 });
        S(sp, 'path', { d: 'M-16 0 H16 M0 -16 V16', stroke: INK, 'stroke-width': 4 });
        return sp;
      });
      return { g: g, wheels: wheels, light: light };
    }
    /* Вертолёт, носом влево. Начало координат — втулка винта; кузов ≈ 560 × 240 под ней. Силуэт тот же, что у
       бумажного вертолёта (styles/paper-cut, PaperKit.heli): шов комикс → бумага держит форму. → {g, rotor(ang, k)} */
    var HELI = { body: 'M-190 115 C-190 50 -120 30 -40 30 L60 30 C100 30 120 50 140 62 L330 55 L345 15 L365 15 L358 88 L140 118 C110 170 60 195 -40 195 L-110 195 C-160 195 -190 160 -190 115 Z',
                 glass: 'M-172 110 C-170 65 -120 48 -60 48 L-20 48 L-20 130 L-165 130 Z',
                 skid: 'M-110 195 L-124 236 M20 195 L34 236 M-176 226 C-170 238 -160 238 -150 238 L96 238' };
    function heli(parent) {
      var g = S(parent, 'g', {});
      ink(g, HELI.skid, null, { w: 8 });
      ink(g, HELI.body, D.red);
      S(g, 'path', { d: 'M140 118 C110 170 60 195 -40 195 L-110 195 C-150 195 -176 172 -186 140 C-120 160 40 160 140 118 Z', fill: shadeDots() });
      ink(g, HELI.glass, D.snow_shade, { w: 5 });
      S(g, 'path', { d: 'M-140 62 l18 0 l-30 62 l-18 0 Z', fill: D.white, opacity: 0.8 });
      ink(g, 'M-8 0 h16 v30 h-16 Z', D.steel_dark, { w: 5 });
      var tail = S(g, 'g', { transform: 'translate(350,34)' }), tb = ink(tail, 'M-34 -4 h68 v8 h-68 Z', INK, { w: 2 });
      var blur = S(g, 'ellipse', { cx: 0, cy: -4, rx: 310, ry: 12, fill: INK, opacity: 0 });
      var blade = ink(g, 'M-300 -8 h600 v8 h-600 Z', INK, { w: 2 });
      ink(g, 'M-14 -14 h28 v16 h-28 Z', INK, { w: 2 });
      return { g: g, rotor: function (ang, k) {         // ang — угол винта, k — 0…1 раскрутка (смаз диска)
        A(blade, 'transform', 'scale(' + (Math.abs(Math.cos(ang)) * 0.94 + 0.06).toFixed(3) + ',1)'); A(blade, 'opacity', (1 - 0.75 * k).toFixed(2));
        A(blur, 'opacity', (0.5 * k).toFixed(2)); A(tb, 'transform', 'rotate(' + (ang * 137).toFixed(1) + ')');
      } };
    }
    /* Проход лопастей через кадр — шов двух миров (blades-wipe): две лопасти от втулки (px, py) идут по часовой, за каждой
       остаётся закрытый сектор. cover 0…1 — передние кромки прошли долю полуоборота (кадр закрывается), open 0…1 —
       задние кромки (кадр открывается). Геометрия одна на оба мира: то же считает PaperKit.bladeWedge. → путь d */
    function bladeWedge(px, py, a0, cover, open) {
      var R = 2700, d = '';
      if (cover <= open) return 'M0 0';
      [0, Math.PI].forEach(function (off) {
        var a = a0 + off + Math.PI * open, b = a0 + off + Math.PI * cover, n = Math.max(2, Math.ceil((b - a) / 0.12));
        d += 'M' + f1(px) + ' ' + f1(py);
        for (var k = 0; k <= n; k++) { var q = a + (b - a) * k / n; d += ' L' + f1(px + Math.cos(q) * R) + ' ' + f1(py + Math.sin(q) * R); }
        d += ' Z';
      });
      return d;
    }
    function track(v0, keys) {               // дорожка ключей {t, v, d, e}: значение в момент t
      keys = keys.slice().sort(function (a, b) { return a.t - b.t; });
      var from = [];
      function upTo(n, t) {
        var v = v0;
        for (var i = 0; i < n; i++) {
          var k = keys[i];
          if (k.t > t) break;
          v = api.lerp(from[i], k.v, api.powerEase(k.e || 'power2.out')(api.prog(t, k.t, k.d || 0)));
        }
        return v;
      }
      keys.forEach(function (k, i) { from[i] = upTo(i, k.t); });
      return function (t) { return upTo(keys.length, t); };
    }
    var kit = { S: S, ink: ink, dots: dots, svgIn: svgIn, clip: clip, tr: tr, show: show, star: star, back: back, level: level, blink: blink,
                taper: taper, mx: mx, fluff: fluff, taxi: taxi, heli: heli, bladeWedge: bladeWedge, track: track,
                rng: C.rng, hash: C.hash, decor: D, f1: f1, step: function (t) { return api.stepTime(t, P.rays_step_frames); },
                at: function (anchor) { return C.when(FILM, anchor); },      // якорь {reply, at, offset} → секунды фильма
                cues: function (scene) { return C.cues(FILM, scene); },      // метки act сцены: {id, t, who, do, m, span}
                events: function (dom) { return FILM.elements.filter(function (e) { return e.dom === dom && !e.part; })[0]; },
                scene: function (id) { return FILM.scenes.filter(function (x) { return x.id === id; })[0]; } };
    window.ComicKit = kit;
    if (WORLD) (window.ComicScenes || []).forEach(function (s) {
      if (api.styleScenes(NAME).indexOf(s.scene) >= 0) kitFrames.push(s.setup(kit, FILM, api));
    });
  })();

  return {
    render: function (t) {
      var w = api.styleWeight(NAME, t);
      api.setStyle(layer, 'opacity', api.styleOpacity(NAME, t, layer).toFixed(3));
      api.setStyle(layer, 'visibility', w > 0.001 ? 'visible' : 'hidden');
      kitFrames.forEach(function (f) { if (f && f.frame) f.frame(t); });     // сцены с набором: свой мир в своих элементах
      if (w <= 0.001) return;
      if (wins) wins.render(t);
      var t3 = api.stepTime(t, P.rays_step_frames);               // лучи и линии — «на тройках»
      panels.forEach(function (p) { api.setAttr(p.g, 'opacity', api.sceneWeight(p.i, t).toFixed(3)); });
      spins.forEach(function (s) {
        api.setAttr(s.g, 'transform', 'rotate(' + (Math.sin(t3 * 0.8 + s.k) * P.rays_turn_deg).toFixed(2) + ' ' + f1(s.cx) + ' ' + f1(s.cy) + ')');
      });
      shifts.forEach(function (s) { api.setAttr(s.g, 'transform', 'translate(' + f1((t3 * 60) % 24 - 12) + ',0)'); });
      hits.forEach(function (h) {
        var p = api.clamp01((t - h.at) / P.boom_in), k = p <= 0 ? 0 : back(p, P.boom_overshoot);
        api.setAttr(h.g, 'transform', 'translate(' + f1(h.cx) + ',' + f1(h.cy) + ') scale(' + Math.max(0, k).toFixed(3) + ') translate('
          + f1(-h.cx) + ',' + f1(-h.cy) + ')');
      });
      twinkles.forEach(function (s) {
        var k = 1 + 0.12 * Math.sin(t3 * 2.4 + s.k * 2);
        api.setAttr(s.g, 'transform', 'translate(' + f1(s.cx) + ',' + f1(s.cy) + ') scale(' + k.toFixed(3) + ') translate(' + f1(-s.cx) + ','
          + f1(-s.cy) + ')');
      });
    },
    probe: function (t) { return { style: NAME, weight: api.styleWeight(NAME, t), world: WORLD }; }
  };
});
