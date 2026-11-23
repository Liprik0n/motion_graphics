/* Пиксель — плагин стиля (engine/video/styles/README.md). Мир — в слое 'back', под каркасом и содержанием.

   Мир (cfg.world): синее небо (decor.sky) во весь кадр; по верхнему полю — пиксельные облака, солнце, холмы
   и деревья, выглядывающие из-за окна, счёт игры (HUD) пиксельной надписью; табло глав — на светлой
   панели. Светлое игровое окно (decor.screen, params.window_in) с пиксельной рамкой и ступенчатыми углами —
   в нём весь каркас и содержание. Внизу — кирпичная земля. Каждая зона сцены (decor_zones) — «уровень»:
   небо, кирпичный пол и предметы по слотам: холм, облако, дерево, блоки с «?», солнце, монета, самолётик,
   труба. Заголовок — пикселями кодом (StyleCore.codeTitle + pixelText), с тенью на клетку.
   Всё на сетке unit_px; движение предметов — ступенями «на тройках» (step_frames) и целыми клетками.
   При style_brand_lock (cfg.world = false): только пиксельная сетка роли бренда поверх фирменного фона.
   Сцена, объявившая себя без каркаса (s.frame === false): игрового окна, панели табло глав,
   счёта игры, кирпичной земли под окном и заголовка пикселями нет — их место у каркаса, которого нет; небо —
   сумеречное decor.sky_dusk. Окно рисуется, только если в фильме есть сцена этого стиля с каркасом.

   Детерминизм: всё — функция номера кадра (api.stepTime); случайность — rng(hash(id)). */
(window.StagePlugins = window.StagePlugins || []).push(function (FILM, api) {
  'use strict';
  var NAME = 'pixel', cfg = api.styleConfig(NAME);
  if (!cfg) return null;
  var C = window.StyleCore, P = cfg.params, D = cfg.decor, PX = FILM.px, WORLD = cfg.world;
  var root = document.getElementById('root'), W = root.clientWidth, H = root.clientHeight;
  var U = P.unit_px, scenes = api.styleScenes(NAME);
  var layer = api.addLayer('px-back', 'back');
  function snap(v) { return Math.round(v / U) * U; }
  function tri(n, a) { var m = ((n % (2 * a)) + 2 * a) % (2 * a); return m < a ? m : 2 * a - m; }   // 0…a…0 по целым

  // ---------------------------------------------------------------- спрайты: строки символов → прямоугольники
  function sprite(g, x, y, rows, pal, u) {
    var paths = {};
    rows.forEach(function (row, r) {
      for (var c = 0; c < row.length; c++) {
        var ch = row[c];
        if (!pal[ch]) continue;
        (paths[ch] = paths[ch] || []).push('M' + (x + c * u) + ' ' + (y + r * u) + 'h' + u + 'v' + u + 'h-' + u + 'z');
      }
    });
    Object.keys(paths).forEach(function (ch) { C.svg('path', { d: paths[ch].join(''), fill: pal[ch], 'shape-rendering': 'crispEdges' }, g); });
    return { w: rows[0].length * u, h: rows.length * u };
  }
  function disk(r, edge) {                // круг из клеток: E — кромка, F — заливка
    var out = [];
    for (var y = 0; y < 2 * r; y++) {
      var s = '';
      for (var x = 0; x < 2 * r; x++) {
        var dx = x - r + 0.5, dy = y - r + 0.5, d = Math.sqrt(dx * dx + dy * dy);
        s += d > r ? '.' : (d > r - edge ? 'E' : 'F');
      }
      out.push(s);
    }
    return out;
  }
  function hillRows(r, seed) {            // полукруг-холм: кромка, заливка, тёмные пятна
    var rnd = C.rng(seed), out = [];
    for (var y = 0; y < r; y++) {
      var s = '';
      for (var x = 0; x < 2 * r; x++) {
        var dx = x - r + 0.5, dy = r - y - 0.5, d = Math.sqrt(dx * dx + dy * dy);
        s += d > r ? '.' : (d > r - 1 ? 'E' : (rnd() < 0.06 && y > 1 ? 'E' : 'F'));
      }
      out.push(s);
    }
    return out;
  }
  function brickRows(cols, rowsN) {       // кирпичная кладка в клетках по 1/2 unit: K — шов
    var out = [];
    for (var r = 0; r < rowsN * 4; r++) {
      var s = '';
      for (var c = 0; c < cols * 2; c++) {
        var off = (Math.floor(r / 4) % 2) * 2;
        s += (r % 4 === 3 || (c + off) % 4 === 3) ? 'K' : (r % 4 === 0 ? 'L' : 'B');
      }
      out.push(s);
    }
    return out;
  }
  var CLOUD = ['....WWWW........', '...WWWWWW.WWW...', '.WWWWWWWWWWWWWW.', 'WWWWWWWWWWWWWWWW', 'SWWWWWWWWWWWWWWS', '.SSSSSSSSSSSSSS.'];
  var TREE = ['..GGGG..', '.GGGGGGD', 'GGGGGGGD', 'GGGGGGDD', '.GGGGDD.', '..DDDD..', '...TT...', '...TT...', '...TT...'];
  var QBLOCK = ['KKKKKKKK', 'KYYYYYYK', 'KYYKKYYK', 'KYYYYKYK', 'KYYYKYYK', 'KYYYYYYK', 'KYYYKYYK', 'KKKKKKKK'];
  var PLANE = ['..........WW', '......WWWWW.', '..WWWWWWSS..', 'WWWWWWSSR...', '...SSSWWR...', '.....SSR....'];
  var PIPE = ['KDDDDDDDDK', 'KGGGGGGGDK', 'KKKKKKKKKK', '.KGGGGGDK.', '.KGGGGGDK.', '.KGGGGGDK.', '.KGGGGGDK.', '.KGGGGGDK.'];
  var COIN = [['.KKKK.', 'KYYYYK', 'KYKKYK', 'KYKKYK', 'KYKKYK', 'KYKKYK', 'KYYYYK', '.KKKK.'],
              ['.KKK.', 'KYYYK', 'KYKYK', 'KYKYK', 'KYKYK', 'KYKYK', 'KYYYK', '.KKK.'],
              ['.KK.', 'KYYK', 'KYYK', 'KYYK', 'KYYK', 'KYYK', 'KYYK', '.KK.'],
              ['.KKK.', 'KYYYK', 'KYKYK', 'KYKYK', 'KYKYK', 'KYKYK', 'KYYYK', '.KKK.']];
  var pal = {
    cloud: { W: D.cloud, S: D.cloud_shade }, tree: { G: D.hill, D: D.hill_dark, T: D.trunk },
    q: { K: D.brick_dark, Y: D.block }, plane: { W: D.cloud, S: D.cloud_shade, R: D.brick },
    pipe: { K: D.frame, G: D.hill, D: D.hill_dark }, coin: { K: D.brick_dark, Y: D.coin },
    sun: { E: D.sun_edge, F: D.sun }, hill: { E: D.hill_dark, F: D.hill }, brick: { B: D.brick, L: D.block, K: D.brick_dark }
  };

  var svg = C.svg('svg', { width: String(W), height: String(H), viewBox: '0 0 ' + W + ' ' + H }, layer);
  svg.style.position = 'absolute'; svg.style.left = '0'; svg.style.top = '0';
  // окна под текстом (StyleCore.textWindows): зоны текста — из раскладки сцены, а не из стиля; середина
  // окна — фон бренда, контраст надписи = контраст бренда на любом фильме (V21); оформление — языком мира
  // окно, табло, счёт и заголовок — у сцен с каркасом (их место у каркаса учебного жанра)
  var FRAMED = FILM.scenes.some(function (s) { return s.style === NAME && s.frame !== false; });
  var wins = WORLD && FRAMED ? C.textWindows(api, FILM, NAME, { parent: layer, pad: P.win_pad_px, css: { border: '4px solid ' + D.cloud_shade } }) : null;
  var anim = [];                       // {i (сцена) | -1, g, kind, x, y, t0, k, frames?}
  var hud = null, titleR = null;
  // пиксельный шрифт-файл стиля (fonts.decor) в размере rows px: при rows = 8 буква Press Start 2P — ровно 8×8 клеток
  function pxFont(rows) { return rows + 'px ' + C.fontOf(NAME, 'decor'); }

  function steppedRect(x, y, w, h, n) {  // прямоугольник со ступенчатыми углами (n клеток)
    var d = 'M' + (x + n * U) + ' ' + y + 'H' + (x + w - n * U);
    for (var k = 0; k < n; k++) d += 'v' + U + 'h' + U;
    d += 'V' + (y + h - n * U);
    for (k = 0; k < n; k++) d += 'h-' + U + 'v' + U;
    d += 'H' + (x + n * U);
    for (k = 0; k < n; k++) d += 'v-' + U + 'h-' + U;
    d += 'V' + (y + n * U);
    for (k = 0; k < n; k++) d += 'h' + U + 'v-' + U;
    return d + 'Z';
  }

  if (WORLD && !FRAMED) {          // без каркаса — только сумеречное небо; город рисует сцена набором PixelKit
    layer.style.background = D.sky_dusk;
  }
  if (WORLD && FRAMED) {
    layer.style.background = D.sky;
    var wx = snap(P.window_in[0] * PX), wy = snap(P.window_in[1] * PX), ww = snap(P.window_in[2] * PX), wh = snap(P.window_in[3] * PX);
    // верхнее поле: холмы и деревья выглядывают из-за окна, облака, солнце
    var top = C.svg('g', {}, svg);
    [[snap(0.9 * PX), 11, 3], [snap(6.6 * PX), 8, 5], [snap(13.2 * PX), 10, 7]].forEach(function (h) {
      sprite(top, h[0], wy - h[1] * U + 2 * U, hillRows(h[1], h[2]), pal.hill, U);
    });
    [[snap(4.4 * PX)], [snap(10.1 * PX)]].forEach(function (p) { sprite(top, p[0], wy - 9 * U + U, TREE, pal.tree, U); });
    sprite(top, snap(9.55 * PX), U * 3, disk(6, 1), pal.sun, U);
    [[snap(2.4 * PX), U * 10, 0], [snap(6.4 * PX), U * 6, 1]].forEach(function (c, k) {
      var g = C.svg('g', {}, top); sprite(g, c[0], c[1], CLOUD, pal.cloud, U);
      anim.push({ i: -1, g: g, kind: 'cloud', k: k + 7, t0: -1 });
    });
    // панель табло глав
    C.svg('path', { d: steppedRect(snap(11.37 * PX), snap(0.85 * PX), snap(7.5 * PX), snap(0.78 * PX), 1), fill: D.frame }, top);
    C.svg('path', { d: steppedRect(snap(11.37 * PX) + 4, snap(0.85 * PX) + 4, snap(7.5 * PX) - 8, snap(0.78 * PX) - 8, 1), fill: D.screen }, top);
    // игровое окно
    C.svg('path', { d: steppedRect(wx, wy, ww, wh, 2), fill: D.frame }, svg);
    C.svg('path', { d: steppedRect(wx + 6, wy + 6, ww - 12, wh - 12, 2), fill: D.screen }, svg);
    var gridC = C.rgbOf(D.frame).join(',');
    var gr = document.createElement('div'); gr.className = 'layer';
    gr.style.left = (wx + 6 + 2 * U) + 'px'; gr.style.top = (wy + 6 + 2 * U) + 'px';
    gr.style.width = (ww - 12 - 4 * U) + 'px'; gr.style.height = (wh - 12 - 4 * U) + 'px';
    var gp = C.gridPaper(U * 2, 'rgba(' + gridC + ',0.04)', { width: 1 });
    gr.style.backgroundImage = gp.image; gr.style.backgroundSize = gp.size;
    layer.insertBefore(gr, wins ? wins.layer : null);     // сетка экрана — под окнами текста
    // земля: кирпичи под окном
    var gy = wy + wh;
    sprite(C.svg('g', {}, svg), 0, gy, brickRows(Math.ceil(W / U), Math.ceil((H - gy) / (U * 2))), pal.brick, U / 2);
    // счёт игры
    hud = { g: C.svg('g', {}, svg), v: null };

    // уровни в зонах сцен
    var ORDER = cfg.objects.filter(function (k) { return ['hill', 'cloud', 'tree', 'blocks', 'sun', 'coin', 'plane', 'pipe'].indexOf(k) >= 0; });
    FILM.scenes.forEach(function (sc, i) {
      if (sc.style !== NAME) return;
      var zg = C.svg('g', {}, svg), zones = sc.decor_zones || [];
      zones.forEach(function (z) {
        var x = snap(z[0]), y = snap(z[1]), w = snap(z[2]), h = snap(z[3]);
        C.svg('path', { d: steppedRect(x, y, w, h, 1), fill: D.frame }, zg);
        C.svg('path', { d: steppedRect(x + 4, y + 4, w - 8, h - 8, 1), fill: D.sky }, zg);
        var fy = y + h - 4 - 2 * U;
        sprite(zg, x + 4, fy, brickRows(Math.floor((w - 8) / U), 1), pal.brick, U / 2);
        z.__floor = fy;
      });
      var slots = C.slots(zones, ORDER.length, 14), rnd = C.rng(C.hash(sc.id));
      slots.forEach(function (b, k) {
        var kind = ORDER[k % ORDER.length], zone = zones.filter(function (z) { return b[0] >= z[0] && b[0] < z[0] + z[2] && b[1] >= z[1] && b[1] < z[1] + z[3]; })[0];
        var floor = zone ? zone.__floor : b[1] + b[2], x = snap(b[0] + b[2] * 0.1), g = C.svg('g', {}, zg), it = { i: i, g: g, kind: kind, k: k,
          t0: sc.start + P.enter_from + k * P.enter_gap };
        if (kind === 'hill') { var r = Math.min(12, Math.floor(b[2] / U / 2)); sprite(g, snap(b[0] + b[2] / 2) - r * U, floor - r * U, hillRows(r, C.hash(sc.id) + k), pal.hill, U); }
        else if (kind === 'tree') sprite(g, x + 2 * U, floor - 9 * U, TREE, pal.tree, U), sprite(g, x + 12 * U, floor - 9 * U, TREE, pal.tree, U);
        else if (kind === 'pipe') sprite(g, x + 6 * U, floor - 8 * U, PIPE, pal.pipe, U);
        else if (kind === 'cloud') sprite(g, x, snap(b[1] + U * 2), CLOUD, pal.cloud, U);
        else if (kind === 'sun') sprite(g, x + 6 * U, snap(b[1] + U), disk(6, 1), pal.sun, U);
        else if (kind === 'plane') sprite(g, x + 3 * U, snap(b[1] + b[2] * 0.35), PLANE, pal.plane, U);
        else if (kind === 'blocks') {
          var by = snap(b[1] + b[2] * 0.3);
          [0, 1, 2, 3].forEach(function (j) {
            if (j === 1) sprite(g, x + j * 4 * U, by, QBLOCK, pal.q, U / 2);
            else sprite(g, x + j * 4 * U, by, brickRows(4, 2), pal.brick, U / 2);
          });
        } else if (kind === 'coin') {
          it.frames = COIN.map(function (rows) {
            var cg = C.svg('g', {}, g); sprite(cg, x + 8 * U + (6 - rows[0].length) * U / 2, snap(b[1] + b[2] * 0.4), rows, pal.coin, U); return cg;
          });
        }
        void rnd;
        anim.push(it);
      });
    });

    // заголовок пикселями — в рамке строки заголовка каркаса
    titleR = C.codeTitle(api, scenes.filter(function (id) {
      return FILM.scenes.some(function (s) { return s.id === id && s.frame !== false; });
    }), C.svg('g', {}, svg), function (g, text, box) {
      var cell = P.title_cell, r;
      for (;;) {
        var sh = C.pixelText(g, text, box.x + cell, box.y + 2 + cell, { rows: P.title_rows, cell: cell, color: D.title_shade, font: pxFont(P.title_rows) });
        r = C.pixelText(g, text, box.x, box.y + 2, { rows: P.title_rows, cell: cell, color: D.title, font: pxFont(P.title_rows) });
        if (r.w + cell <= box.w || cell <= P.title_cell_min) break;
        g.removeChild(sh.g); g.removeChild(r.g); cell -= 1;
      }
    });
  }
  if (!WORLD) {
    var lc = C.rgbOf(C.cssVar('--c-' + P.lock_grid_role)).join(',');
    var lg = C.gridPaper(U, 'rgba(' + lc + ',' + P.lock_grid_alpha + ')', { width: 1 });
    var ld = document.createElement('div'); ld.className = 'layer';
    ld.style.backgroundImage = lg.image; ld.style.backgroundSize = lg.size;
    layer.appendChild(ld);
  }

  /* ================================================================== НАБОР ГОРОДА
     Сцене стиля plugin даёт window.PixelKit: спрайты из клеток (px), рисунки города (art: лошадь, заяц, снеговик,
     хвойное дерево, блок с вопросом, монета, огонь, искра), дом с вывеской (house), гирлянда (garland), такси (taxi),
     надпись клетками (text), дорожки ключей (track), якорь времени at({reply, at, offset}) → секунды.
     Сцена подключается из своей разметки: (window.PixelScenes = window.PixelScenes || []).push({scene, setup});
     setup(kit, FILM, api) → {frame(t)} — frame зовётся на каждый кадр после битов.
     Героя и слов вывесок в стиле нет — они в данных проекта: спрайт героя (строки клеток и своя палитра) кладёт
     разметка сцены через kit.px(g, x, y, rows, u, pal). */
  var kitFrames = [];
  (function () {
    var KP = { K: D.frame, W: D.snow, S: D.ear, H: D.cap, T: D.lamp_cool, N: D.frame, L: D.snow_shade,
               R: D.red, G: D.frame, B: D.frame, Y: D.coin, O: D.garland_warm, E: D.steel, e: D.steel_dark, C: D.horse,
               c: D.horse_dark, F: D.fir, f: D.fir_light, M: D.brick_dark, m: D.brick, Q: D.block, y: D.garland, t: D.trunk };
    var ART = {
      horse: [['..cc..................', '.CCCCc................', 'CCCCCCc...............', 'CKCCCCCc..............', 'CCCCCCCCc.............',
               '.CC.CCCCCcccccccccc...', '....CCCCCCCEEEECCCCC..', '.....CCCCCCEEEECCCCCc.', '.....CCCCCCCCCCCCCCCc.', '.....CCCCCCCCCCCCCC.cc',
               '.....CCC.CC....CC.CCc.', '.....CC..CC....CC.CC..', '.....CC..CC....CC.CC..', '.....KK..KK....KK.KK..'],
              ['..cc..................', '.CCCCc................', 'CCCCCCc...............', 'CKCCCCCc..............', 'CCCCCCCCc.............',
               '.CC.CCCCCcccccccccc...', '....CCCCCCCEEEECCCCC..', '.....CCCCCCEEEECCCCCc.', '.....CCCCCCCCCCCCCCCc.', '.....CCCCCCCCCCCCCC.cc',
               '....CCC..CC...CCC.CC..', '...CC....CC..CC...CC..', '...CC...CC...CC..CC...', '...KK...KK...KK..KK...']],
      /* заяц в шапке, мордой вправо — туда, куда скачет; уши торчат из-под шапки, в прыжке (второй кадр) отстают */
      hare: [['..WS.WS.', '..WS.WS.', '..WS.WS.', '..WS.HH.', '..WWHHHH', '....NNNN', '....WWWW', '....WWKW', '.WWWWWWW', 'WWWWWWW.', 'WWWWWWW.', '.WW..WW.'],
             ['.WS.WS..', '.WS.WS..', '..WS.WS.', '..WS.HH.', '..WWHHHH', '....NNNN', '....WWWW', '....WWKW', 'WWWWWWWW', 'WWWWWWWW', 'W......W', '........']],
      snowman: ['...MMMM...', '...MMMM...', '..WWWWWW..', '..WKWWKW..', '..WWOOWW..', '..WWWWWL..', '.WWWWWWWW.', 'tWWWKWWWLt', '.WWWWWWLL.',
                'WWWWWWWWWW', 'WWWWKWWWWL', 'WWWWWWWWLL', 'WWWWWWWLLL', '.WWWWWLLL.'],
      fir: ['......yy......', '......yy......', '.....FFFF.....', '....FFFFFF....', '...FFyFFFFF...', '..FFFFFFRFFF..', '....FFFFFF....',
            '...FFFFTFFF...', '..FFRFFFFFFF..', '.FFFFFFFFyFFF.', '...FFFFFFFF...', '..FFFyFFFFFF..', '.FFFFFFFFTFFF.', 'FFFRFFFFFFFFFF',
            'WWFFFFFFFFFFWW', '......tt......', '......tt......'],
      qblock: ['MMMMMMMM', 'MQQQQQQM', 'MQQMMQQM', 'MQQQQMQM', 'MQQQMQQM', 'MQQQQQQM', 'MQQQMQQM', 'MMMMMMMM'],
      used: ['MMMMMMMM', 'MmmmmmmM', 'MmmmmmmM', 'MmmmmmmM', 'MmmmmmmM', 'MmmmmmmM', 'MmmmmmmM', 'MMMMMMMM'],
      coin: [['.MMMM.', 'MYYYYM', 'MYMMYM', 'MYMMYM', 'MYMMYM', 'MYMMYM', 'MYYYYM', '.MMMM.'], ['.MMM.', 'MYYYM', 'MYMYM', 'MYMYM', 'MYMYM', 'MYMYM', 'MYYYM', '.MMM.'],
             ['.MM.', 'MYYM', 'MYYM', 'MYYM', 'MYYM', 'MYYM', 'MYYM', '.MM.'], ['.MMM.', 'MYYYM', 'MYMYM', 'MYMYM', 'MYMYM', 'MYMYM', 'MYYYM', '.MMM.']],
      flame: [['...O..', '..OO..', '.OyyO.', '.OyyO.', 'OyyyyO', 'OyyyyO', '.OyyO.'], ['..O...', '..OO..', '..OyO.', '.OyyO.', 'OyyyyO', 'OyyyO.', '.OyyO.'],
              ['....O.', '..OO..', '.OyO..', '.OyyO.', '.OyyyO', 'OyyyyO', '.OyyO.']],
      spark: ['R.R.R', '.RyR.', 'RyyyR', '.RyR.', 'R.R.R']
    };
    function px(g, x, y, rows, u, pal) { var gg = C.svg('g', {}, g); sprite(gg, x, y, rows, pal || KP, u || U); return gg; }
    function rect(g, x, y, w, h, fill, extra) {
      var a = { x: x, y: y, width: w, height: h, fill: fill, 'shape-rendering': 'crispEdges' };
      for (var k in extra || {}) a[k] = extra[k];
      return C.svg('rect', a, g);
    }
    var brickId = null;                       // кирпичная заливка — узор (один на страницу)
    function brick(svgRoot) {
      if (brickId) return brickId;
      brickId = 'px-brick';
      var defs = C.svg('defs', {}, svgRoot), p = C.svg('pattern', { id: brickId, width: 4 * U, height: 4 * U, patternUnits: 'userSpaceOnUse' }, defs);
      rect(p, 0, 0, 4 * U, 4 * U, D.brick);
      rect(p, 0, 0, 4 * U, U / 2, D.brick_dark); rect(p, 0, 2 * U, 4 * U, U / 2, D.brick_dark);
      rect(p, 0, 0, U / 2, 2 * U, D.brick_dark); rect(p, 2 * U, 2 * U, U / 2, 2 * U, D.brick_dark);
      return brickId;
    }
    /* дом: кирпич, снег на крыше, окна; o.sign {w, h} — тёмная доска вывески (буквы кладёт сцена), o.booth — окошко
       кассы под вывеской, o.door — дверь, o.lit — светятся ли окна. → {g, x, w, top, sign: {x, y, w, h}} */
    function house(g, x, ground, w, h, o) {
      o = o || {};
      var top = ground - h, root = g.ownerSVGElement || g, hg = C.svg('g', {}, g), k;
      rect(hg, x, top, w, h, D.brick_dark);
      rect(hg, x + U / 2, top + U / 2, w - U, h - U / 2, 'url(#' + brick(root) + ')');
      rect(hg, x - U, top - 2 * U, w + 2 * U, 3 * U, D.snow);
      for (k = 0; k < w / U + 2; k += 3) rect(hg, x - U + k * U, top + U, U * (1 + (k * 7 % 2)), U, D.snow);
      rect(hg, x - U, top + U, w + 2 * U, U / 2, D.snow_shade);
      var n = Math.max(2, Math.floor((w - 4 * U) / (10 * U))), gap = (w - n * 6 * U) / (n + 1);
      for (k = 0; k < n; k++) {
        var wx = snap(x + gap + k * (6 * U + gap)), wy = top + 5 * U, lit = o.lit !== false && (k * 5 + (o.seed || 0)) % 3 !== 0;
        rect(hg, wx - U / 2, wy - U / 2, 7 * U, 9 * U, D.brick_dark);
        rect(hg, wx, wy, 6 * U, 8 * U, lit ? D.garland : D.frame);
        rect(hg, wx + 2.5 * U, wy, U, 8 * U, D.brick_dark); rect(hg, wx, wy + 3.5 * U, 6 * U, U, D.brick_dark);
        rect(hg, wx - U, wy + 8 * U, 8 * U, U, D.snow);
      }
      var out = { g: hg, x: x, w: w, top: top };
      if (o.sign) {
        var sx = snap(x + (w - o.sign.w) / 2), sy = top + 16 * U;
        rect(hg, sx - U, sy - U, o.sign.w + 2 * U, o.sign.h + 2 * U, D.block);
        rect(hg, sx, sy, o.sign.w, o.sign.h, D.frame);
        out.sign = { x: sx, y: sy, w: o.sign.w, h: o.sign.h };
      }
      var dy = ground - 11 * U;
      if (o.booth) {
        var bx = snap(x + w / 2 - 6 * U);
        rect(hg, bx - U, dy - U, 14 * U, 9 * U, D.brick_dark);
        rect(hg, bx, dy, 12 * U, 7 * U, D.garland);
        rect(hg, bx, dy, 12 * U, U, D.garland_warm);
        rect(hg, bx + 4 * U, dy + 3 * U, 4 * U, 4 * U, D.frame);
        rect(hg, bx + 5 * U, dy + 2 * U, 2 * U, U, D.frame);
        rect(hg, bx - 2 * U, dy + 7 * U, 16 * U, 2 * U, D.snow);
      } else if (o.door !== false) {
        var dx = snap(x + w / 2 - 3 * U);
        rect(hg, dx - U / 2, dy + U, 7 * U, 10 * U, D.brick_dark);
        rect(hg, dx, dy + 1.5 * U, 6 * U, 9.5 * U, o.door === 'open' ? D.snow : D.trunk);
        if (o.door !== 'open') rect(hg, dx + 4.5 * U, dy + 6 * U, U, U, D.garland);
        out.door = { x: dx, y: dy + 1.5 * U };
      }
      return out;
    }
    /* гирлянда между точками: провисающая нить и лампочки двух групп (сцена мигает группами) */
    function garland(g, x0, x1, y, sag) {
      var a = C.svg('g', {}, g), b = C.svg('g', {}, g), cols = [D.garland, D.red, D.lamp_cool, D.garland_warm, D.fir_light], n = Math.round((x1 - x0) / (5 * U));
      for (var k = 0; k <= n; k++) {
        var p = k / n, xx = snap(x0 + (x1 - x0) * p), yy = snap(y + sag * 4 * p * (1 - p));
        if (k < n) rect(g, xx, yy, 5 * U, U / 2, D.frame);
        rect(k % 2 ? a : b, xx, yy + U / 2, U, 1.5 * U, cols[k % cols.length]);
      }
      return [a, b];
    }
    /* такси: кузов из клеток, передом влево; задняя дверь — отдельной группой в doorParent: closed / open.
       → {g, door, closed, open, w, h, glass: [x, y, w, h]} — стекло задней двери (за ним — пассажир) */
    function taxi(g, doorParent) {
      var tg = C.svg('g', {}, g), T = D.taxi, sh = D.garland_warm, k;
      rect(tg, 12 * U, 0, 34 * U, 2 * U, T);
      rect(tg, 24 * U, -3 * U, 10 * U, 3 * U, D.frame);
      for (k = 0; k < 8; k++) rect(tg, 25 * U + k * U, -2 * U, U, U, k % 2 ? D.frame : D.snow);
      rect(tg, 10 * U, 2 * U, 38 * U, 8 * U, T);
      rect(tg, 12 * U, 3 * U, 10 * U, 6 * U, D.snow_shade);
      rect(tg, 0, 10 * U, 60 * U, 12 * U, T);
      rect(tg, 0, 20 * U, 60 * U, 2 * U, sh);
      for (k = 0; k < 30; k++) { rect(tg, k * 2 * U, 13 * U, U, U, D.frame); rect(tg, k * 2 * U + U, 14 * U, U, U, D.frame); }
      rect(tg, 0, 12 * U, 2 * U, 3 * U, D.snow);
      rect(tg, 58 * U, 11 * U, 2 * U, 2 * U, D.red);
      rect(tg, 24 * U, 3 * U, 0.5 * U, 19 * U, D.frame);
      rect(tg, 26 * U, 3 * U, 18 * U, 18 * U, D.frame);                // проём задней двери: тёмный салон
      [8, 44].forEach(function (c) {
        sprite(C.svg('g', {}, tg), c * U, 18 * U, disk(4, 1), { E: D.frame, F: D.steel_dark }, U);
        rect(tg, c * U + 3 * U, 21 * U, 2 * U, 2 * U, D.steel);
      });
      var inside = C.svg('g', {}, tg);                                 // пассажир за стеклом (кладёт сцена)
      function shut(parent) {
        var closed = C.svg('g', {}, parent);
        rect(closed, 26 * U, 2 * U, 18 * U, 18 * U, T);
        rect(closed, 26 * U, 20 * U, 18 * U, 2 * U, sh);
        rect(closed, 28 * U, 3 * U, 14 * U, 7 * U, D.frame);
        var pass = C.svg('g', {}, closed);                             // силуэт пассажира за стеклом закрытой двери
        rect(closed, 28 * U, 3 * U, 14 * U, 7 * U, D.snow_shade, { opacity: 0.3 });
        rect(closed, 26 * U, 2 * U, 0.5 * U, 20 * U, D.frame); rect(closed, 43.5 * U, 2 * U, 0.5 * U, 20 * U, D.frame);
        for (var j = 0; j < 9; j++) { rect(closed, 26 * U + j * 2 * U, 13 * U, U, U, D.frame); rect(closed, 27 * U + j * 2 * U, 14 * U, U, U, D.frame); }
        rect(closed, 28 * U, 11 * U, 3 * U, U, D.frame);
        return [closed, pass];
      }
      var twin = shut(tg);                                             // двойник закрытой двери в кузове
      var dg = C.svg('g', {}, doorParent || tg), own = shut(dg), closed = own[0], pass = own[1], open = C.svg('g', { visibility: 'hidden' }, dg);
      rect(open, 43 * U, 1 * U, 3 * U, 22 * U, sh); rect(open, 43 * U, 1 * U, U, 22 * U, T);
      return { g: tg, door: dg, closed: closed, open: open, inside: inside, pass: pass, closed2: twin[0], pass2: twin[1], w: 60 * U, h: 23 * U, glass: [28 * U, 3 * U, 14 * U, 7 * U] };
    }
    function track(v0, keys) {
      keys = keys.slice().sort(function (a, b) { return a.t - b.t; });
      var from = [];
      function upTo(n, t) {
        var v = v0;
        for (var i = 0; i < n; i++) {
          var k = keys[i];
          if (k.t > t) break;
          v = api.lerp(from[i], k.v, api.powerEase(k.e || 'power1.inOut')(api.prog(t, k.t, k.d || 0)));
        }
        return v;
      }
      keys.forEach(function (k, i) { from[i] = upTo(i, k.t); });
      return function (t) { return upTo(keys.length, t); };
    }
    var kit = { U: U, snap: snap, svg: C.svg, px: px, rect: rect, art: ART, house: house, garland: garland, taxi: taxi, disk: disk,
                text: function (parent, str, x, y, o) { return C.pixelText(parent, str, x, y, Object.assign({ font: pxFont((o && o.rows) || 8) }, o || {})); }, track: track, rng: C.rng, hash: C.hash, decor: D, pal: KP,
                step: function (t) { return api.stepTime(t, P.step_frames); },
                at: function (anchor) { return C.when(FILM, anchor); },      // якорь {reply, at, offset} → секунды фильма
                cues: function (scene) { return C.cues(FILM, scene); },      // метки act сцены: {id, t, who, do, m, span}
                events: function (dom) { return FILM.elements.filter(function (e) { return e.dom === dom && !e.part; })[0]; },
                scene: function (id) { return FILM.scenes.filter(function (x) { return x.id === id; })[0]; } };
    window.PixelKit = kit;
    if (WORLD) (window.PixelScenes || []).forEach(function (s) {
      if (scenes.indexOf(s.scene) >= 0) kitFrames.push(s.setup(kit, FILM, api));
    });
  })();

  return {
    render: function (t) {
      var w = api.styleWeight(NAME, t);
      api.setStyle(layer, 'opacity', api.styleOpacity(NAME, t, layer).toFixed(3));
      api.setStyle(layer, 'visibility', w > 0.001 ? 'visible' : 'hidden');
      kitFrames.forEach(function (f) { if (f && f.frame) f.frame(t); });     // сцены с набором: свой мир в своих элементах
      if (w <= 0.001 || !WORLD) return;
      if (wins) wins.render(t);
      var ts = api.stepTime(t, P.step_frames);                       // всё «на тройках»
      if (titleR) titleR(t);
      if (!hud) return;
      var score = String(P.hud_score + 10 * Math.max(0, Math.floor(ts / P.hud_step_sec)));
      while (score.length < 6) score = '0' + score;
      var hv = 'СЧЁТ ' + score + '    МОНЕТЫ 08    ЖИЗНИ 3';
      if (hud.v !== hv || !hud.final) {         // и заново, пока шрифт-файл не загрузился (StyleCore.fontsReady)
        while (hud.g.firstChild) hud.g.removeChild(hud.g.firstChild);
        C.pixelText(hud.g, hv, 3 * U, 3 * U, { rows: P.hud_rows, cell: P.hud_cell, color: D.hud, font: pxFont(P.hud_rows) });
        hud.v = hv; hud.final = C.fontsReady();
      }
      anim.forEach(function (it) {
        var sw = it.i < 0 ? 1 : api.sceneWeight(it.i, t);
        api.setAttr(it.g, 'opacity', sw.toFixed(3));
        if (sw <= 0.001) return;
        var dy = 0, dx = 0;
        if (it.t0 >= 0) {                                             // вход: падает целыми клетками
          var p = ts - it.t0;
          if (p < 0) { api.setAttr(it.g, 'visibility', 'hidden'); return; }
          api.setAttr(it.g, 'visibility', 'visible');
          dy = -Math.max(0, P.enter_drop_units - Math.floor(p / (P.step_frames / FILM.fps))) * U;
        }
        var n = Math.floor(ts * P.cloud_speed_units);
        if (it.kind === 'cloud') dx = (tri(n + it.k * 3, 6) - 3) * U;
        if (it.kind === 'plane') { dx = (tri(n + it.k, 4) - 2) * U; dy += (tri(Math.floor(ts * 3), P.plane_bob_units) - 1) * U; }
        api.setAttr(it.g, 'transform', 'translate(' + dx + ',' + dy + ')');
        if (it.frames) {
          var f = Math.floor(ts / P.coin_frames_sec) % it.frames.length;
          it.frames.forEach(function (cg, j) { api.setAttr(cg, 'visibility', j === f ? 'visible' : 'hidden'); });
        }
      });
    },
    probe: function (t) { return { style: NAME, weight: api.styleWeight(NAME, t), world: WORLD }; }
  };
});
