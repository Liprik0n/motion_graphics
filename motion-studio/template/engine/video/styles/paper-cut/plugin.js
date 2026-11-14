/* Бумага-вырезка — плагин стиля (engine/video/styles/README.md). Всё в слое 'back' — под каркасом и содержанием.

   Мир (cfg.world): небо (decor.sky_top → sky), солнце из двух слоёв с вырезанными лучами и облака в верхнем
   поле, три слоя холмов внизу кадра (светлый → тёмный), белая полоса бумаги с рваным краем под подвалом;
   в зонах сцены (decor_zones) — хвойные деревья, домики, бумажный самолётик, птица, куст. Каждый лист — бумажная
   фигура с мягкой тенью на нижний слой (смещение + размытие) и светлой кромкой среза. Предметы въезжают
   снизу «на двойках» с перелётом, как при перекладке; солнце поворачивается, облака плывут.
   При style_brand_lock (cfg.world = false): только бумажная фактура и мягкие тени листов ролью бренда.

   Кадр — чистая функция времени (V24): случайности нет, рваный край — от сида имени. Текст не трогается. */
(window.StagePlugins = window.StagePlugins || []).push(function (FILM, api) {
  'use strict';
  var NAME = 'paper-cut', cfg = api.styleConfig(NAME);
  if (!cfg) return null;
  var C = window.StyleCore, P = cfg.params, D = cfg.decor, PX = FILM.px, WORLD = cfg.world;
  var root = document.getElementById('root'), W = root.clientWidth, H = root.clientHeight;
  var STEP = P.step_frames || 2;

  var layer = api.addLayer('pc-back', 'back');
  var sheet = document.createElement('div');
  sheet.className = 'layer';
  if (WORLD) sheet.style.backgroundColor = D.sky;
  sheet.style.backgroundImage = (WORLD ? 'url(' + C.paperTile(256, 57, { alpha: 0.05, fibres: 50 }) + '),linear-gradient(180deg,'
    + D.sky_top + ' 0%,' + D.sky + ' 70%)' : 'url(' + C.paperTile(256, 57, { alpha: 0.04, fibres: 50 }) + ')');
  sheet.style.backgroundSize = WORLD ? '256px 256px,100% 100%' : '256px 256px';
  layer.appendChild(sheet);
  var svg = C.svg('svg', { width: String(W), height: String(H), viewBox: '0 0 ' + W + ' ' + H }, layer);
  svg.style.position = 'absolute'; svg.style.left = '0'; svg.style.top = '0';
  // окна под текстом (StyleCore.textWindows): зоны текста — из раскладки сцены, а не из стиля; середина
  // окна — фон бренда, контраст надписи = контраст бренда на любом фильме (V21); оформление — языком мира
  // окна под текстом — у сцен с каркасом: сцена без каркаса (s.frame === false) рисует свой мир и свои подложки сама
  var wins = WORLD && FILM.scenes.some(function (s) { return s.style === NAME && s.frame !== false; }) ? C.textWindows(api, FILM, NAME, { parent: layer, pad: P.win_pad_px, css: { borderRadius: '4px', boxShadow: P.shadow_px[0] + 'px ' + P.shadow_px[1] + 'px ' + P.shadow_blur + 'px ' + 'rgba(' + C.rgbOf(D.shadow).join(',') + ',' + P.shadow_alpha + ')' } }) : null;
  function S(g, tag, a) { return C.svg(tag, a, g); }
  function f1(v) { return v.toFixed(1); }
  var sh = S(C.defs(), 'filter', { id: 'pc-soft', x: '-20%', y: '-20%', width: '140%', height: '140%' });
  S(sh, 'feGaussianBlur', { 'in': 'SourceGraphic', stdDeviation: String(P.shadow_blur) });
  var shadowC = WORLD ? D.shadow : C.cssVar('--c-' + P.lock_role);

  function cut(g, d, fill) {               // бумажный лист: тень на нижний слой, сам лист, светлая кромка
    S(g, 'path', { d: d, fill: shadowC, 'fill-opacity': P.shadow_alpha, filter: 'url(#pc-soft)',
                   transform: 'translate(' + P.shadow_px[0] + ',' + P.shadow_px[1] + ')' });
    S(g, 'path', { d: d, fill: fill, stroke: D.paper, 'stroke-opacity': 0.35, 'stroke-width': 1.2 });
  }
  function circ(cx, cy, r) {               // круг двумя полудугами (одна дуга с совпавшими концами не рисуется)
    return 'M' + f1(cx + r) + ' ' + f1(cy) + ' A' + f1(r) + ' ' + f1(r) + ' 0 1 1 ' + f1(cx - r) + ' ' + f1(cy) + ' A' + f1(r) + ' ' + f1(r)
      + ' 0 1 1 ' + f1(cx + r) + ' ' + f1(cy) + ' Z';
  }
  function cloudD(x, y, w) {
    var h = w * 0.4, b = y + h;
    return 'M' + f1(x) + ' ' + f1(b) + ' A' + f1(h * 0.45) + ' ' + f1(h * 0.45) + ' 0 0 1 ' + f1(x + w * 0.2) + ' ' + f1(b - h * 0.55)
      + ' A' + f1(h * 0.55) + ' ' + f1(h * 0.55) + ' 0 0 1 ' + f1(x + w * 0.55) + ' ' + f1(b - h * 0.75)
      + ' A' + f1(h * 0.45) + ' ' + f1(h * 0.45) + ' 0 0 1 ' + f1(x + w * 0.85) + ' ' + f1(b - h * 0.35)
      + ' A' + f1(h * 0.3) + ' ' + f1(h * 0.3) + ' 0 0 1 ' + f1(x + w) + ' ' + f1(b) + ' Z';
  }

  var DRAW = {
    pine: function (g, x, y, s) {          // хвойное дерево: три яруса треугольников и ствол
      var cx = x + s / 2, b = y + s * 0.98;
      cut(g, 'M' + f1(cx - s * 0.04) + ' ' + f1(b) + ' v' + f1(-s * 0.14) + ' h' + f1(s * 0.08) + ' v' + f1(s * 0.14) + ' Z', D.trunk);
      [[0.84, 0.3, D.pine_dark], [0.62, 0.25, D.pine], [0.42, 0.19, D.pine]].forEach(function (q) {
        cut(g, 'M' + f1(cx - s * q[1]) + ' ' + f1(y + s * q[0]) + ' L' + f1(cx) + ' ' + f1(y + s * (q[0] - 0.4)) + ' L' + f1(cx + s * q[1]) + ' '
            + f1(y + s * q[0]) + ' Z', q[2]);
      });
    },
    house: function (g, x, y, s) {         // домик: стена, крыша, дверь, окно
      var l = x + s * 0.22, r = x + s * 0.78, t = y + s * 0.55, b = y + s * 0.97;
      cut(g, 'M' + f1(l) + ' ' + f1(t) + ' H' + f1(r) + ' V' + f1(b) + ' H' + f1(l) + ' Z', D.wall);
      cut(g, 'M' + f1(l - s * 0.07) + ' ' + f1(t + 2) + ' L' + f1(x + s / 2) + ' ' + f1(y + s * 0.26) + ' L' + f1(r + s * 0.07) + ' ' + f1(t + 2) + ' Z', D.roof);
      cut(g, 'M' + f1(x + s * 0.32) + ' ' + f1(b) + ' v' + f1(-s * 0.22) + ' h' + f1(s * 0.12) + ' v' + f1(s * 0.22) + ' Z', D.roof);
      cut(g, 'M' + f1(x + s * 0.54) + ' ' + f1(t + s * 0.08) + ' h' + f1(s * 0.14) + ' v' + f1(s * 0.12) + ' h' + f1(-s * 0.14) + ' Z', D.sun);
    },
    plane: function (g, x, y, s) {         // бумажный самолётик: два крыла разного тона
      cut(g, 'M' + f1(x + s * 0.1) + ' ' + f1(y + s * 0.6) + ' L' + f1(x + s * 0.92) + ' ' + f1(y + s * 0.3) + ' L' + f1(x + s * 0.48) + ' '
          + f1(y + s * 0.62) + ' Z', D.paper);
      cut(g, 'M' + f1(x + s * 0.92) + ' ' + f1(y + s * 0.3) + ' L' + f1(x + s * 0.4) + ' ' + f1(y + s * 0.66) + ' L' + f1(x + s * 0.5) + ' '
          + f1(y + s * 0.8) + ' Z', D.sky_top);
      return { fly: true };
    },
    bird: function (g, x, y, s) {          // птица: тело-капля, крыло, клюв
      var cx = x + s * 0.5, cy = y + s * 0.45;
      cut(g, 'M' + f1(cx - s * 0.22) + ' ' + f1(cy) + ' Q' + f1(cx) + ' ' + f1(cy - s * 0.2) + ' ' + f1(cx + s * 0.2) + ' ' + f1(cy - s * 0.04)
          + ' Q' + f1(cx + s * 0.05) + ' ' + f1(cy + s * 0.18) + ' ' + f1(cx - s * 0.22) + ' ' + f1(cy) + ' Z', D.sun_rays);
      cut(g, 'M' + f1(cx + s * 0.2) + ' ' + f1(cy - s * 0.07) + ' l' + f1(s * 0.08) + ' ' + f1(s * 0.03) + ' l' + f1(-s * 0.08) + ' ' + f1(s * 0.03) + ' Z', D.sun);
      cut(g, 'M' + f1(cx - s * 0.05) + ' ' + f1(cy - s * 0.05) + ' L' + f1(cx + s * 0.02) + ' ' + f1(cy - s * 0.3) + ' L' + f1(cx + s * 0.1) + ' '
          + f1(cy - s * 0.06) + ' Z', D.roof);
      return { fly: true };
    },
    bush: function (g, x, y, s) {          // куст из трёх кругов
      cut(g, circ(x + s * 0.35, y + s * 0.8, s * 0.17) + circ(x + s * 0.62, y + s * 0.78, s * 0.2) + circ(x + s * 0.5, y + s * 0.68, s * 0.17), D.hill_near);
    }
  };
  var ORDER = cfg.objects.filter(function (k) { return DRAW[k]; });

  var sun = null, clouds = [], world = [];
  // солнце, холмы и белая полоса под подвалом — пейзаж сцен с каркасом; сцена без каркаса (s.frame === false) — небо за
  // вертолётом) получает только небо, свой мир она рисует сама из набора PaperKit (ниже)
  var FRAMED = FILM.scenes.some(function (s) { return s.style === NAME && s.frame !== false; });
  if (WORLD && FRAMED) {
    // солнце: лучи-треугольники (поворачиваются) и два круга
    var sg = S(svg, 'g', {}), sx = 210, sy = 112, sr = 52, rays = S(sg, 'g', {}), rd = '';
    for (var k = 0; k < 14; k++) {
      var a = k / 14 * Math.PI * 2, b1 = a - 0.11, b2 = a + 0.11, r1 = sr * 1.2, r2 = sr * (k % 2 ? 1.7 : 1.95);
      rd += 'M' + f1(sx + Math.cos(b1) * r1) + ' ' + f1(sy + Math.sin(b1) * r1) + ' L' + f1(sx + Math.cos(a) * r2) + ' ' + f1(sy + Math.sin(a) * r2)
        + ' L' + f1(sx + Math.cos(b2) * r1) + ' ' + f1(sy + Math.sin(b2) * r1) + ' Z';
    }
    cut(rays, rd, D.sun_rays);
    cut(sg, circ(sx, sy, sr), D.sun_rays);
    cut(sg, circ(sx, sy, sr * 0.8), D.sun);
    sun = { rays: rays, cx: sx, cy: sy };
    [[470, 62, 200], [800, 112, 150], [1480, 14, 110]].forEach(function (c, i) {
      var g = S(svg, 'g', {});
      cut(g, cloudD(c[0], c[1], c[2]), D.cloud);
      clouds.push({ g: g, k: i });
    });
    // холмы: три слоя, низ — под белой полосой
    var gt = P.ground_top_in * PX;
    P.hills.forEach(function (h, i) {
      var y0 = h[0] * H, amp = 46 - i * 8, d = 'M0 ' + f1(y0 + amp * 0.6);
      for (var xx = 0; xx <= W; xx += 40) d += ' L' + xx + ' ' + f1(y0 + Math.sin(xx / (260 - i * 40) + i * 1.9) * amp);
      cut(S(svg, 'g', {}), d + ' L' + W + ' ' + f1(gt + 20) + ' L0 ' + f1(gt + 20) + ' Z', D[h[1]]);
    });
    // белая полоса бумаги с рваным краем — подвал стоит на ней
    var rnd = C.rng(C.hash(NAME + '-ground')), gd = 'M0 ' + f1(gt);
    for (var gx = 0; gx <= W; gx += 14) gd += ' L' + gx + ' ' + f1(gt + (rnd() - 0.5) * 6);
    cut(S(svg, 'g', {}), gd + ' L' + W + ' ' + H + ' L0 ' + H + ' Z', D.paper);
    FILM.scenes.forEach(function (sc, i) {
      if (sc.style !== NAME) return;
      C.slots(sc.decor_zones, 6, 14).forEach(function (b, k) {
        var g = S(svg, 'g', {}), kind = ORDER[k % ORDER.length], o = DRAW[kind](g, b[0], b[1], b[2]) || {};
        o.i = i; o.g = g; o.k = k; o.t0 = sc.start + P.rise_from + k * P.rise_gap;
        world.push(o);
      });
    });
  }
  function back(p, s) { var q = p - 1; return 1 + (s + 1) * q * q * q + s * q * q; }

  /* ================================================================== НАБОР БУМАГИ
     Сцене стиля plugin даёт window.PaperKit: лист с тенью на нижний слой (sheet), облако и гряда облаков (cloud, bank),
     вертолёт (heli — тот же силуэт, что ComicKit.heli; cabin — группа за стеклом, туда сцена сажает своего героя),
     проход лопастей — шов (bladeWedge — та же геометрия, что ComicKit), вдавленные буквы (inset), зеркало контура (mx),
     пушистый круг (fluff), полоска со скруглёнными концами (capsule), узкая полоска без тени (strip), группа под
     обрезкой (clipIn), рот по огибающей реплики (level), моргание (blink), дорожки ключей (track), якорь времени
     at({reply, at, offset}) → секунды. Сцена подключается из своей разметки:
     (window.PaperScenes = window.PaperScenes || []).push({scene, setup}); setup(kit, FILM, api) → {frame(t)}.
     Героя и надписей в стиле нет — они в данных проекта: героя сцена собирает из листов (sheet) этим набором,
     цвета героя — роли палитры проекта, конечности размечает StyleCore.limb (V25). */
  var kitFrames = [];
  (function () {
    function A(n, k, v) { api.setAttr(n, k, v); }
    /* видимость узла рисунка: «виден» = inherit, а не visible. Явное visible пересиливает скрытие самого элемента битом
       (visibility: hidden у .el): узел оставался бы в отрисовке под непрозрачностью 0, Chrome выделял бы под него слой, и
       кадры ДРУГИХ сцен зависели бы от того, заходили ли в эту (замер: V24 краснел на кадрах соседней сцены) */
    function show(n, v) { A(n, 'visibility', v ? 'inherit' : 'hidden'); }
    function svgIn(host, w, h) {
      var s = C.svg('svg', { width: w, height: h, viewBox: '0 0 ' + w + ' ' + h, overflow: 'visible' }, host);
      s.style.position = 'absolute'; s.style.left = '0'; s.style.top = '0'; s.style.overflow = 'visible';
      return s;
    }
    /* лист: тень двумя сдвинутыми копиями (мягкая без размытия — кадр считается быстро), сам лист, светлая кромка.
       o.sh — множитель сдвига тени (высота листа над нижним), o.stroke — своя кромка */
    function sheet(g, d, fill, o) {
      o = o || {};
      var k = o.sh != null ? o.sh : 1, gg = S(g, 'g', {});
      if (k > 0) {
        S(gg, 'path', { d: d, fill: D.shadow, 'fill-opacity': 0.13, transform: 'translate(' + f1(P.shadow_px[0] * k * 1.5) + ',' + f1(P.shadow_px[1] * k * 1.5) + ')' });
        S(gg, 'path', { d: d, fill: D.shadow, 'fill-opacity': 0.16, transform: 'translate(' + f1(P.shadow_px[0] * k * 0.7) + ',' + f1(P.shadow_px[1] * k * 0.7) + ')' });
      }
      S(gg, 'path', { d: d, fill: fill, stroke: o.stroke || D.paper, 'stroke-opacity': o.stroke ? 1 : 0.35, 'stroke-width': o.w || 1.2, 'stroke-linejoin': 'round' });
      return gg;
    }
    function cloud(x, y, w, seed) {          // облако: ровный низ, верх из дуг (число и рост — от зерна)
      var rnd = C.rng(seed), n = 3 + Math.floor(rnd() * 3), h = w * 0.34, d = 'M' + f1(x) + ' ' + f1(y) + ' a' + f1(h * 0.3) + ' ' + f1(h * 0.3) + ' 0 0 1 ' + f1(h * 0.3) + ' ' + f1(-h * 0.3);
      var cx = x + h * 0.3, step = (w - h * 0.6) / n;
      for (var k = 0; k < n; k++) {
        var r = step / 2, lift = h * (0.35 + 0.65 * Math.sin(Math.PI * (k + 0.5) / n) * (0.7 + 0.3 * rnd()));
        d += ' a' + f1(r) + ' ' + f1(lift) + ' 0 0 1 ' + f1(step) + ' 0'; cx += step;
      }
      return d + ' a' + f1(h * 0.3) + ' ' + f1(h * 0.3) + ' 0 0 1 ' + f1(h * 0.3) + ' ' + f1(h * 0.3) + ' Z';
    }
    function bank(x0, x1, depth, seed) {     // гряда облаков: верх из дуг на высоте 0, тело уходит вниз на depth
      var rnd = C.rng(seed), x = x0, d = 'M' + f1(x0) + ' ' + f1(depth) + ' L' + f1(x0) + ' 60';
      while (x < x1 - 1) { var w = Math.min(150 + rnd() * 190, x1 - x), r = w / 2; d += ' a' + f1(r) + ' ' + f1(Math.max(r, 60) * (0.5 + 0.5 * rnd())) + ' 0 0 1 ' + f1(w) + ' 0'; x += w; }
      return d + ' L' + f1(x1) + ' ' + f1(depth) + ' Z';      // края половин — ровно на x0 и x1: две гряды встык без щели
    }
    function level(t) {
      var r = null;
      for (var i = 0; i < FILM.replies.length; i++) if (t >= FILM.replies[i].start && t < FILM.replies[i].end) r = FILM.replies[i];
      if (!r || r.silent || !r.mouth) return 0;
      var k = Math.floor((t - r.start) * FILM.fps), sum = 0, n = 0;
      for (var j = k - 1; j <= k + 1; j++) if (j >= 0 && j < r.mouth.length) { sum += +r.mouth.charAt(j); n++; }
      return n ? sum / n / 9 : 0;
    }
    function blink(t, seed) {
      var per = 3.1, k = Math.floor(t / per), rnd = C.rng(seed + k * 7919), at = k * per + 0.4 + rnd() * (per - 1.0), x = (t - at) * FILM.fps;
      return x >= 0 && x < 4 ? 1 : 0;
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
    function capsule(x1, y1, x2, y2, r) {     // полоска со скруглёнными концами — палец
      var dx = x2 - x1, dy = y2 - y1, l = Math.hypot(dx, dy) || 1, nx = -dy / l * r, ny = dx / l * r;
      return 'M' + f1(x1 + nx) + ' ' + f1(y1 + ny) + ' A' + r + ' ' + r + ' 0 0 1 ' + f1(x1 - nx) + ' ' + f1(y1 - ny) + ' L' + f1(x2 - nx) + ' ' + f1(y2 - ny)
        + ' A' + r + ' ' + r + ' 0 0 1 ' + f1(x2 + nx) + ' ' + f1(y2 + ny) + ' Z';
    }
    function strip(g, d, color, w, o) {       // узкая полоска бумаги без тени (рубчик, блик, складка)
      return S(g, 'path', { d: d, fill: 'none', stroke: color, 'stroke-width': w, 'stroke-linecap': 'round', 'stroke-linejoin': 'round', opacity: o != null ? o : 1 });
    }
    var nKitClip = 0;
    function clipIn(g, d) {
      var id = 'pc-kit-part-clip-' + (nKitClip++);
      S(S(C.defs(), 'clipPath', { id: id }), 'path', { d: d });
      return S(g, 'g', { 'clip-path': 'url(#' + id + ')' });
    }
    /* Вертолёт, носом влево. Начало координат — втулка винта; кузов ≈ 560 × 240 под ней (силуэт — ComicKit.heli).
       → {g, cabin (группа за стеклом — сюда сцена сажает своего героя), rotor(ang)} */
    var HELI = { body: 'M-190 115 C-190 50 -120 30 -40 30 L60 30 C100 30 120 50 140 62 L330 55 L345 15 L365 15 L358 88 L140 118 C110 170 60 195 -40 195 L-110 195 C-160 195 -190 160 -190 115 Z',
                 glass: 'M-176 118 C-176 62 -124 44 -60 44 L4 44 L4 170 L-150 170 C-168 158 -176 140 -176 118 Z',
                 skid: 'M-110 195 L-124 236 M20 195 L34 236 M-176 226 C-170 238 -160 238 -150 238 L96 238' };
    var nClip = 0;
    function heli(parent) {
      var g = S(parent, 'g', {}), id = 'pc-kit-clip-' + (nClip++);
      S(g, 'path', { d: HELI.skid, fill: 'none', stroke: D.shadow, 'stroke-width': 9, 'stroke-linecap': 'round' });
      sheet(g, HELI.body, D.heli, { sh: 1.4 });
      S(g, 'path', { d: 'M140 118 C110 170 60 195 -40 195 L-110 195 C-150 195 -176 172 -186 140 C-120 160 40 160 140 118 Z', fill: D.heli_dark });
      sheet(g, HELI.glass, D.glass, { sh: 0.3 });
      S(S(C.defs(), 'clipPath', { id: id }), 'path', { d: HELI.glass });
      var cabin = S(S(g, 'g', { 'clip-path': 'url(#' + id + ')' }), 'g', {});
      var shine = S(g, 'path', { d: 'M-150 60 l22 0 l-34 70 l-12 -30 Z', fill: D.paper, opacity: 0.55 });
      S(g, 'path', { d: HELI.glass, fill: 'none', stroke: D.heli_dark, 'stroke-width': 7, 'stroke-linejoin': 'round' });
      sheet(g, 'M-8 0 h16 v30 h-16 Z', D.metal, { sh: 0.5 });
      var tail = S(g, 'g', { transform: 'translate(350,34)' }), tb = S(tail, 'g', {});
      sheet(tb, 'M-36 -5 h72 v10 h-72 Z', D.blade, { sh: 0.6 });
      var blade = S(g, 'g', {});
      sheet(blade, 'M-310 -9 h620 v10 h-620 Z', D.blade, { sh: 1.2 });
      sheet(g, 'M-16 -16 h32 v18 h-32 Z', D.metal, { sh: 0.5 });
      void shine;
      return { g: g, cabin: cabin, rotor: function (ang) {
        A(blade, 'transform', 'scale(' + (Math.abs(Math.cos(ang)) * 0.9 + 0.1).toFixed(3) + ',1)');
        A(tb, 'transform', 'rotate(' + (ang * 137 % 360).toFixed(1) + ')');
      } };
    }
    function bladeWedge(px, py, a0, cover, open) {     // та же геометрия, что ComicKit.bladeWedge: шов двух миров
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
    var insetId = null;
    function inset() {                       // фильтр «буквы-прорези»: тень кромки листа внутри буквы (смещение + размытие)
      if (insetId) return insetId;
      insetId = 'pc-kit-inset';
      var f = S(C.defs(), 'filter', { id: insetId, x: '-5%', y: '-5%', width: '110%', height: '110%' });
      S(f, 'feOffset', { 'in': 'SourceAlpha', dx: 7, dy: 9, result: 'o' });
      S(f, 'feGaussianBlur', { 'in': 'o', stdDeviation: 4, result: 'b' });
      S(f, 'feComposite', { 'in': 'SourceAlpha', in2: 'b', operator: 'out', result: 'rim' });
      var m = S(f, 'feMerge', {}); S(m, 'feMergeNode', { 'in': 'SourceGraphic' }); S(m, 'feMergeNode', { 'in': 'rim' });
      return insetId;
    }
    function track(v0, keys) {
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
    var kit = { S: S, sheet: sheet, cloud: cloud, bank: bank, circ: circ, svgIn: svgIn, show: show, level: level, blink: blink, back: back,
                heli: heli, clipIn: clipIn, mx: mx, fluff: fluff, capsule: capsule, strip: strip, bladeWedge: bladeWedge, inset: inset, track: track,
                rng: C.rng, hash: C.hash, decor: D, f1: f1, step: function (t) { return api.stepTime(t, STEP); },
                at: function (anchor) { return C.when(FILM, anchor); },      // якорь {reply, at, offset} → секунды фильма
                cues: function (scene) { return C.cues(FILM, scene); },      // метки act сцены: {id, t, who, do, m, span}
                events: function (dom) { return FILM.elements.filter(function (e) { return e.dom === dom && !e.part; })[0]; },
                scene: function (id) { return FILM.scenes.filter(function (x) { return x.id === id; })[0]; } };
    window.PaperKit = kit;
    if (WORLD) (window.PaperScenes || []).forEach(function (s) {
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
      var ts = api.stepTime(t, STEP);                              // перекладка «на двойках»
      if (sun) api.setAttr(sun.rays, 'transform', 'rotate(' + (ts / P.sun_turn_sec * 360).toFixed(2) + ' ' + sun.cx + ' ' + sun.cy + ')');
      clouds.forEach(function (c) {
        api.setAttr(c.g, 'transform', 'translate(' + f1(Math.sin(ts * 0.3 + c.k * 2.1) * P.cloud_drift_px) + ',0)');
      });
      world.forEach(function (o) {
        var sw = api.sceneWeight(o.i, t), p = api.clamp01((ts - o.t0) / P.rise_in);
        api.setAttr(o.g, 'opacity', (sw * api.clamp01(p * 3)).toFixed(3));
        if (sw <= 0.001) return;
        var dy = (1 - back(p, P.rise_overshoot)) * P.rise_px, dx = 0;
        if (o.fly && p >= 1) { dy += Math.sin(ts * 1.6 + o.k) * 6; dx = Math.sin(ts * 0.8 + o.k) * 8; }
        api.setAttr(o.g, 'transform', 'translate(' + f1(dx) + ',' + f1(dy) + ')');
      });
    },
    probe: function (t) { return { style: NAME, weight: api.styleWeight(NAME, t), world: WORLD }; }
  };
});
