/* flat-edu — плоский вектор учебного ролика: студия записи (engine/video/styles/README.md, «Миры с набором сцены»).
   Мир (cfg.world): ровный фон decor.wall в слое 'back' под каркасом и содержанием. В сцене с каркасом: светлые окна
   под текстом (StyleCore.textWindows) и в каждой зоне decor_zones — уголок студии: поролон на стене, пол, короб
   лампы (горящая секция дышит), микрофон на стойке, кружка. Сверх мира стиль даёт сцене НАБОР (window.FlatEdu):
     1. роли decor как CSS-переменные --d-<роль> на секции сцены: разметка сцены красит свой SVG ролями, а не hex
        (в слое содержания страницы hex вне палитры бренда запрещён, V12);
     2. предметы студии, нарисованные кодом: узел разметки <div data-obj="<имя>" style="left;top;width;height">
        получает SVG предмета в размер узла (foam, floor, monitor, booth-window, lamp-box, desk, mic, mug, door,
        hook-keys);
     3. марионетку (rig): управление частями SVG героя по контракту рига (styles/README.md) — поза одним объектом
        состояния; сам SVG героя — данные проекта;
     4. дорожки ключей (track, steps), рот по огибающей своей реплики (mouth), моргание (blink), двойник надписи
        за кадром (gate), якорь времени at({reply, at, offset}) → секунды.
   Сцена подключается из своей разметки: (window.FlatEduScenes = window.FlatEduScenes || []).push({scene, setup}),
   setup(kit, FILM, api) → {frame(t)}; frame зовётся на каждый кадр после битов. Героев и текстов в стиле нет — они
   в данных проекта. Кадр — чистая функция t. Замок бренда (cfg.world = false): фона и предметов мира нет. */
(window.StagePlugins = window.StagePlugins || []).push(function (FILM, api) {
  'use strict';
  var NAME = 'flat-edu', cfg = api.styleConfig(NAME);
  if (!cfg) return null;
  var CORE = window.StyleCore, D = cfg.decor, PRM = cfg.params, NS = 'http://www.w3.org/2000/svg';
  var layer = api.addLayer('flat-edu-back', 'back');
  if (cfg.world) layer.style.background = D[cfg.params.bg_role];
  var ids = api.styleScenes(NAME);

  // ------------------------------------------------------------------ SVG-помощники
  function el(tag, attrs, parent) {
    var n = document.createElementNS(NS, tag);
    for (var k in attrs) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  }
  function P(g, d, fill, stroke, sw, extra) {
    var a = { d: d, fill: fill || 'none' };
    if (stroke) { a.stroke = stroke; a['stroke-width'] = sw || 4; a['stroke-linejoin'] = 'round'; a['stroke-linecap'] = 'round'; }
    for (var k in extra || {}) a[k] = extra[k];
    return el('path', a, g);
  }
  function R(g, x, y, w, h, fill, stroke, sw, rx) {
    var a = { x: x, y: y, width: w, height: h, fill: fill || 'none' };
    if (rx) a.rx = rx;
    if (stroke) { a.stroke = stroke; a['stroke-width'] = sw || 4; a['stroke-linejoin'] = 'round'; }
    return el('rect', a, g);
  }
  function C(g, cx, cy, r, fill, stroke, sw) {
    var a = { cx: cx, cy: cy, r: r, fill: fill || 'none' };
    if (stroke) { a.stroke = stroke; a['stroke-width'] = sw || 4; }
    return el('circle', a, g);
  }
  var OL = D.line;

  // ------------------------------------------------------------------ предметы студии: draw(g, w, h, узел)
  var OBJ = {
    // стена: поролон клеткой — тонкий ромб тоном темнее по всей стене (цвет стены сам — фон сцены)
    foam: function (g, w, h, host) {
      var id = 'fe-foam-' + (OBJ._n = (OBJ._n || 0) + 1), defs = el('defs', {}, g), t = 64;
      var p = el('pattern', { id: id, width: t, height: t, patternUnits: 'userSpaceOnUse' }, defs);
      P(p, 'M0 ' + t / 2 + 'L' + t / 2 + ' 0L' + t + ' ' + t / 2 + 'L' + t / 2 + ' ' + t + 'Z', 'none', D.foam, 2, { opacity: 0.55 });
      P(p, 'M' + t / 2 + ' 0V' + t + 'M0 ' + t / 2 + 'H' + t, 'none', D.foam, 1.2, { opacity: 0.3 });
      R(g, 0, 0, w, h, 'url(#' + id + ')');
    },
    floor: function (g, w, h) { R(g, 0, 0, w, h, D.line); R(g, 0, 0, w, 6, D.panel_dark); },
    // монитор: рамка, ножка; экран — узел .screen (картинку кладёт сцена), вспышка — .blink
    monitor: function (g, w, h, host) {
      var sx = +host.getAttribute('data-sx'), sy = +host.getAttribute('data-sy'), sw = +host.getAttribute('data-sw'), sh = +host.getAttribute('data-sh');
      R(g, sx - 14, sy - 14, sw + 28, sh + 28, D.line, null, 0, 8);
      R(g, sx + sw / 2 - 26, sy + sh + 14, 52, h - sy - sh - 26, D.panel_dark, OL, 4);
      R(g, sx + sw / 2 - 90, h - 14, 180, 14, D.panel_dark, OL, 4, 6);
      R(g, sx, sy, sw, sh, D.ink);
    },
    // окно аппаратной: тёмное стекло, в нём отражение пульта и блик
    'booth-window': function (g, w, h) {
      R(g, 0, 0, w, h, D.line, null, 0, 10);
      R(g, 12, 12, w - 24, h - 24, D.panel_dark, null, 0, 4);
      var k, x0 = w * 0.16, y0 = h * 0.62;
      R(g, x0, y0, w * 0.5, h * 0.2, D.foam, null, 0, 4).setAttribute('opacity', 0.55);
      for (k = 0; k < 7; k++) R(g, x0 + 14 + k * w * 0.065, y0 + 8 + (k * 7 % 3) * 5, 6, 14, D.silver).setAttribute('opacity', 0.5);
      P(g, 'M' + (w * 0.62) + ' 20L' + (w * 0.78) + ' 20L' + (w * 0.5) + ' ' + (h - 20) + 'L' + (w * 0.34) + ' ' + (h - 20) + 'Z', D.light, null, 0, { opacity: 0.07 });
      P(g, 'M' + (w * 0.82) + ' 20L' + (w * 0.87) + ' 20L' + (w * 0.59) + ' ' + (h - 20) + 'L' + (w * 0.54) + ' ' + (h - 20) + 'Z', D.light, null, 0, { opacity: 0.07 });
    },
    // короб лампы из двух секций: погасшие секции (горящую кладёт элемент сцены поверх)
    'lamp-box': function (g, w, h) {
      R(g, 0, 0, w, h, D.line, null, 0, 8);
      R(g, 6, 6, w / 2 - 9, h - 12, D.panel_dark, null, 0, 4);
      R(g, w / 2 + 3, 6, w / 2 - 9, h - 12, D.panel_dark, null, 0, 4);
    },
    // стол с пультом: столешница, передняя панель, ряды движков; тумблер — группа .toggle (её качает сцена)
    desk: function (g, w, h, host) {
      R(g, 0, 0, w, 26, D.panel_dark, OL, 4, 6);
      R(g, 14, 26, w - 28, h - 26, D.line);
      var cx = +host.getAttribute('data-console') || w * 0.3, cw = 420, k;
      R(g, cx, 52, cw, 150, D.panel_dark, null, 0, 8);
      for (k = 0; k < 12; k++) {
        var x = cx + 60 + k * 29, y = 70 + (k * 37 % 5) * 14;
        R(g, x + 3, 66, 3, 120, D.foam);
        R(g, x - 3, y + 10, 15, 22, k % 4 === 1 ? D.lamp : D.silver, null, 0, 3);
      }
      for (k = 0; k < 6; k++) C(g, cx + 70 + k * 26, 226, 5, k === 1 ? D.lamp : D.foam);
      // тумблер: основание и рычаг
      R(g, cx + 14, 70, 30, 44, D.line, D.silver, 2, 5);
      var tg = el('g', { 'class': 'toggle', 'data-pivot': (cx + 29) + ' 98' }, g);
      P(tg, 'M' + (cx + 29) + ' 98L' + (cx + 29) + ' 70', 'none', D.silver, 8);
      C(tg, cx + 29, 68, 7, D.light, OL, 2);
    },
    // микрофон с поп-фильтром на стойке: data-flip — фильтр с другой стороны
    mic: function (g, w, h, host) {
      var f = host.getAttribute('data-flip') ? -1 : 1, cx = w / 2;
      R(g, cx - 34, h - 12, 68, 12, D.panel_dark, OL, 3, 5);
      P(g, 'M' + cx + ' ' + (h - 12) + 'L' + cx + ' ' + (h * 0.5) + 'L' + (cx + f * 18) + ' ' + (h * 0.34), 'none', OL, 7);
      P(g, 'M' + cx + ' ' + (h - 12) + 'L' + cx + ' ' + (h * 0.5) + 'L' + (cx + f * 18) + ' ' + (h * 0.34), 'none', D.silver, 3);
      var mg = el('g', { transform: 'rotate(' + (f * 24) + ' ' + (cx + f * 18) + ' ' + (h * 0.3) + ')' }, g);
      R(mg, cx + f * 18 - 15, h * 0.08, 30, h * 0.3, D.panel_dark, OL, 4, 14);
      R(mg, cx + f * 18 - 15, h * 0.08, 30, h * 0.13, D.silver, OL, 4, 14);
      P(mg, 'M' + (cx + f * 18 - 13) + ' ' + (h * 0.15) + 'h26M' + (cx + f * 18 - 13) + ' ' + (h * 0.12) + 'h26', 'none', OL, 1.6);
      var px = cx + f * 18 - f * 44, py = h * 0.2;
      C(g, px, py, 27, D.panel_dark, OL, 4).setAttribute('fill-opacity', 0.55);
      C(g, px, py, 19, 'none', D.silver, 1.5);
      P(g, 'M' + px + ' ' + (py + 27) + 'Q' + px + ' ' + (h * 0.5) + ' ' + cx + ' ' + (h * 0.52), 'none', OL, 3);
    },
    mug: function (g, w, h) {
      P(g, 'M' + (w * 0.66) + ' ' + (h * 0.3) + 'C' + (w * 1.02) + ' ' + (h * 0.26) + ' ' + (w * 1.02) + ' ' + (h * 0.78) + ' ' + (w * 0.64) + ' ' + (h * 0.74), 'none', OL, 7);
      P(g, 'M' + (w * 0.66) + ' ' + (h * 0.3) + 'C' + (w * 1.02) + ' ' + (h * 0.26) + ' ' + (w * 1.02) + ' ' + (h * 0.78) + ' ' + (w * 0.64) + ' ' + (h * 0.74), 'none', D.pale, 3);
      P(g, 'M4 ' + (h * 0.12) + 'L' + (w * 0.7) + ' ' + (h * 0.12) + 'L' + (w * 0.64) + ' ' + (h - 4) + 'L10 ' + (h - 4) + 'Z', D.pale, OL, 3);
      var s = el('g', { 'class': 'steam' }, g);
      P(s, 'M' + (w * 0.24) + ' ' + (h * 0.02) + 'c-6 -8 6 -12 0 -22M' + (w * 0.46) + ' ' + (h * 0.02) + 'c-6 -8 6 -12 0 -22', 'none', D.silver, 2.5);
    },
    // дверь: коробка, проём (за дверью — сумеречный свет: группа .glow), полотно — группа .leaf
    // (сцена сжимает её по ширине: открыта)
    door: function (g, w, h) {
      R(g, 0, 0, w, h, D.line, null, 0, 6);
      var gl = el('g', { 'class': 'glow' }, g);
      R(gl, 12, 12, w - 24, h - 12, D.dusk);
      R(gl, 12, h - 150, w - 24, 150, D.pale);
      var lf = el('g', { 'class': 'leaf', 'data-pivot': (w - 12) + ' 0' }, g);
      R(lf, 12, 12, w - 24, h - 12, D.panel, OL, 4);
      R(lf, 30, 40, w - 60, h * 0.36, D.foam, null, 0, 6);
      R(lf, 30, h * 0.48, w - 60, h * 0.42, D.foam, null, 0, 6);
      C(lf, 34, h * 0.5, 9, D.silver, OL, 3);
    },
    // крючок со связкой ключей
    'hook-keys': function (g, w, h) {
      P(g, 'M' + (w / 2) + ' 4v12q0 8 -8 8', 'none', OL, 6);
      C(g, w / 2, 6, 6, D.silver, OL, 2.5);
      C(g, w / 2 - 6, 36, 13, 'none', D.silver, 3.5);
      [[-16, 14], [-2, -6], [12, 20]].forEach(function (q, k) {
        var kg = el('g', { transform: 'rotate(' + q[1] + ' ' + (w / 2 - 6) + ' 48)' }, g);
        R(kg, w / 2 - 10 + q[0] * 0.3, 48, 8, 40 + k * 6, D.silver, OL, 2.5, 3);
        R(kg, w / 2 - 2 + q[0] * 0.3, 70 + k * 6, 7, 5, D.silver, OL, 2);
        C(kg, w / 2 - 6 + q[0] * 0.3, 50, 8, D.coin, OL, 2.5);
      });
    },
  };

  // ------------------------------------------------------------------ дорожки ключей
  /* track(v0, keys): keys [{t, v, d?, e?}] — значение едет к v за d секунд по кривой e, стартуя оттуда, где было в t.
     steps(v0, keys): ступень — последнее значение с t ≤ времени. Обе — чистые функции времени. */
  function track(v0, keys) {
    keys = keys.slice().sort(function (a, b) { return a.t - b.t; });
    var from = [];
    function upTo(n, t) {
      var v = v0;
      for (var i = 0; i < n; i++) {
        var k = keys[i];
        if (k.t > t) break;
        v = api.lerp(from[i], k.v, api.powerEase(k.e || 'power2.inOut')(api.prog(t, k.t, k.d || 0)));
      }
      return v;
    }
    keys.forEach(function (k, i) { from[i] = upTo(i, k.t); });
    return function (t) { return upTo(keys.length, t); };
  }
  function steps(v0, keys) {
    keys = keys.slice().sort(function (a, b) { return a.t - b.t; });
    return function (t) { var v = v0; for (var i = 0; i < keys.length && keys[i].t <= t; i++) v = keys[i].v; return v; };
  }
  // рот: уровень 0…9 своей реплики в кадре t (FILM.replies[].mouth — огибающая звука; немая опора — нули)
  function level(voice, t) {
    var r = FILM.replies;
    for (var i = 0; i < r.length; i++) {
      if (r[i].voice !== voice || r[i].silent || t < r[i].start || t >= r[i].end) continue;
      var k = Math.floor((t - r[i].start) * FILM.fps + 1e-6);
      return +(r[i].mouth.charAt(k) || 0);
    }
    return 0;
  }
  var SHAPES = ['closed', 'ajar', 'ajar', 'o', 'ajar', 'a', 'o', 'a', 'a', 'a'];
  function mouth(voice, t) {                        // форма рта «на двойках»: не дрожит покадрово
    var ts = api.stepTime(t, 2), a = level(voice, ts), b = level(voice, ts + 1 / FILM.fps);
    return SHAPES[Math.max(a, b)];
  }
  function talking(voice, t) { return level(voice, t) > 0 || level(voice, t - 0.1) > 0 || level(voice, t + 0.1) > 0; }
  function blink(seed, t) {                         // моргание: раз в 2,6–4,4 с на 4 кадра, расписание от зерна
    var period = 2.6 + (Math.abs(seed) % 19) / 10, ph = (t + (Math.abs(seed) % 7) * 0.37) % period;
    return ph < 4 / FILM.fps;
  }

  // ------------------------------------------------------------------ марионетка
  /* rig(prefix): prefix — id без части («<сцена>--<кто>»); SVG героя — данные проекта, части — по контракту рига
     (styles/README.md). apply(st) ставит позу целиком:
       x, y, s        где в мире стоит точка пояса (ось фигуры, низ корпуса) и масштаб
       lean, bob      наклон фигуры (град.) и сдвиг вниз (ед. полотна)
       head [rot, dy] голова и волосы сзади; caps — id частей, которые сидят на голове отдельным слоем
       look [dx, dy]  зрачки; eyes, brows, mouth — имя члена набора; pose — free | crossed | hold
       browDy         сдвиг группы бровей по высоте (ед. полотна, вверх — минус): плавный переход между членами набора
       armL, armR     [плечо, предплечье] в градусах; handL, handR — relaxed | open | point
       legL, legR     ноги (если есть); show {часть: bool}; xf {часть: transform} — свободные части */
  var SETS = { eyes: ['open', 'closed', 'happy'], brows: ['neutral', 'raised', 'frown'],
               mouth: ['closed', 'ajar', 'a', 'o', 'smile', 'grin'], pose: ['free', 'crossed', 'hold'],
               'hand-left': ['relaxed', 'open', 'point'], 'hand-right': ['relaxed', 'open', 'point'] };
  function rig(prefix) {
    var cache = {};
    function part(id) { return id in cache ? cache[id] : (cache[id] = document.getElementById(prefix + '-' + id)); }
    var fig = part('figure');
    if (!fig) throw new Error('flat-edu: нет марионетки #' + prefix + '-figure');
    var svg = fig.ownerSVGElement, vb = svg.viewBox.baseVal;
    function disp(n, on) { if (n) api.setAttr(n, 'display', on ? 'inline' : 'none'); }
    function one(set, v) { SETS[set].forEach(function (m) { disp(part(set + '-' + m), m === v); }); }
    function rot(id, deg, pre) {
      var n = part(id);
      if (n) api.setAttr(n, 'transform', (pre || '') + 'rotate(' + (+deg).toFixed(2) + ' ' + n.getAttribute('data-pivot') + ')');
    }
    function apply(st) {
      var s = st.s;
      api.setStyle(svg, 'width', (vb.width * s).toFixed(2) + 'px');
      api.setStyle(svg, 'height', (vb.height * s).toFixed(2) + 'px');
      api.setStyle(svg, 'transform', 'translate(' + (st.x - (400 - vb.x) * s).toFixed(2) + 'px,' + (st.y - 1000 * s).toFixed(2) + 'px)');
      rot('figure', st.lean || 0, 'translate(0 ' + (st.bob || 0).toFixed(2) + ') ');
      var h = st.head || [0, 0], hx = 'translate(0 ' + h[1].toFixed(2) + ') ';
      rot('head', h[0], hx); rot('hair-back', h[0], hx);
      var lk = st.look || [0, 0], pu = part('pupils');
      if (pu) api.setAttr(pu, 'transform', 'translate(' + lk[0].toFixed(2) + ' ' + lk[1].toFixed(2) + ')');
      one('eyes', st.eyes || 'open'); one('brows', st.brows || 'neutral'); one('mouth', st.mouth || 'closed');
      var br = part('brows');                                          // плавный ход бровей: сдвиг всей группы (browDy, ед. полотна)
      if (br) api.setAttr(br, 'transform', 'translate(0 ' + (+(st.browDy || 0)).toFixed(2) + ')');
      one('pose', st.pose || 'free');
      var L = st.armL || [0, 0], Rr = st.armR || [0, 0];
      rot('arm-left-upper', L[0]); rot('arm-left-fore', L[1]);
      rot('arm-right-upper', Rr[0]); rot('arm-right-fore', Rr[1]);
      one('hand-left', st.handL || 'relaxed'); one('hand-right', st.handR || 'relaxed');
      if (part('leg-left')) { rot('leg-left', st.legL || 0); rot('leg-right', st.legR || 0); }
      var k;
      for (k in st.show || {}) disp(part(k), st.show[k]);
      for (k in st.xf || {}) if (part(k)) api.setAttr(part(k), 'transform', st.xf[k]);
      for (k in st.op || {}) if (part(k)) api.setAttr(part(k), 'opacity', (+st.op[k]).toFixed(3));
    }
    return { apply: apply, part: part, svg: svg, pivot: function (id) { return part(id).getAttribute('data-pivot'); } };
  }

  // ------------------------------------------------------------------ двойник надписи за кадром
  /* Надпись элемента (.t) обязана целиком стоять в кадре, пока она видна (V3), а камера въезжает и выезжает.
     gate(span, closed?) кладёт под надпись её точную копию без класса .t; в кадре видна надпись, за кадром — копия:
     картинка та же, а промеру надпись достаётся только там, где её можно прочесть. closed() — ещё одна причина
     считать надпись нечитаемой (её заливает свет шва: V10 «строка под чужой заливкой»). */
  function gate(span, closed) {
    var tw = span.cloneNode(true);
    tw.classList.remove('t'); tw.classList.add('tw'); tw.removeAttribute('id');
    tw.style.position = 'absolute'; tw.style.left = span.offsetLeft + 'px'; tw.style.top = span.offsetTop + 'px';
    tw.style.width = span.offsetWidth + 'px';
    span.parentNode.insertBefore(tw, span);
    var root = document.getElementById('root');
    return function () {
      var q = root.getBoundingClientRect(), r = span.getBoundingClientRect();
      var inside = r.left >= q.left && r.top >= q.top && r.right <= q.right && r.bottom <= q.bottom && !(closed && closed());
      api.setStyle(span, 'opacity', inside ? '1' : '0');
      api.setStyle(tw, 'opacity', inside ? '0' : '1');
    };
  }

  // ------------------------------------------------------------------ сцены стиля
  var kit = { el: el, track: track, steps: steps, level: level, mouth: mouth, talking: talking, blink: blink, rig: rig,
              gate: gate, decor: D, hash: function (s) { return CORE.hash(s); },
              at: function (anchor) { return CORE.when(FILM, anchor); },      // якорь {reply, at, offset} → секунды фильма
              cues: function (scene) { return CORE.cues(FILM, scene); },      // метки act сцены: {id, t, who, do, m, span}
              events: function (dom) { return FILM.elements.filter(function (e) { return e.dom === dom && !e.part; })[0]; } };
  // ------------------------------------------------------------------ сцена с каркасом: уголок студии в зонах и окна под текстом
  var FRAMED = FILM.scenes.some(function (sc) { return sc.style === NAME && sc.frame !== false; });
  var nooks = [];
  function put(parent, name, x, y, w, h) {          // предмет студии в рамке x, y, w, h (px) слоя мира
    var host = document.createElement('div');
    host.style.cssText = 'position:absolute;left:' + x + 'px;top:' + y + 'px;width:' + w + 'px;height:' + h + 'px;';
    parent.appendChild(host);
    var sv = el('svg', { width: w, height: h, viewBox: '0 0 ' + w + ' ' + h, overflow: 'visible' }, host);
    sv.style.position = 'absolute'; sv.style.left = '0'; sv.style.top = '0';
    OBJ[name](sv, w, h, host);
    return host;
  }
  if (cfg.world) FILM.scenes.forEach(function (sc, i) {
    if (sc.style !== NAME || sc.frame === false) return;
    (sc.decor_zones || []).forEach(function (z, zi) {
      var g = document.createElement('div'), w = Math.round(z[2]), h = Math.round(z[3]), fl = Math.round(h * 0.1);
      g.style.cssText = 'position:absolute;left:' + Math.round(z[0]) + 'px;top:' + Math.round(z[1]) + 'px;width:' + w + 'px;height:' + h +
        'px;overflow:hidden;border-radius:12px;';
      layer.appendChild(g);
      put(g, 'foam', 0, 0, w, h);
      put(g, 'floor', 0, h - fl, w, fl);
      var lw = Math.round(Math.min(260, w * 0.34)), lh = Math.round(lw * 0.3), lx = Math.round(w * (zi % 2 ? 0.1 : 0.58)), ly = Math.round(h * 0.1);
      put(g, 'lamp-box', lx, ly, lw, lh);
      var lit = document.createElement('div');      // горящая секция лампы: дышит, не мигает (V23)
      lit.style.cssText = 'position:absolute;left:' + (lx + 6) + 'px;top:' + (ly + 6) + 'px;width:' + Math.round(lw / 2 - 9) + 'px;height:' +
        (lh - 12) + 'px;border-radius:4px;background:' + D.lamp + ';';
      g.appendChild(lit);
      var mh = Math.round(h * 0.62), mw = Math.round(mh * 0.5);
      put(g, 'mic', Math.round(w * (zi % 2 ? 0.62 : 0.12)), h - fl - mh, mw, mh);
      var gh = Math.round(h * 0.2), gw = Math.round(gh * 0.9);
      put(g, 'mug', Math.round(w * (zi % 2 ? 0.84 : 0.36)), h - fl - gh, gw, gh);
      nooks.push({ i: i, g: g, lit: lit, k: zi });
    });
  });
  // окна под текстом — последними в слое: поверх предметов мира
  var wins = cfg.world && FRAMED ? CORE.textWindows(api, FILM, NAME, { parent: layer, pad: PRM.win_pad_px,
                                                                      css: { borderRadius: '10px', border: '3px solid ' + D.line } }) : null;

  var frames = [];
  if (cfg.world) {
    ids.forEach(function (id) {
      var sec = document.getElementById('scene--' + id);
      if (!sec) return;
      Object.keys(D).forEach(function (role) { sec.style.setProperty('--d-' + role, D[role]); });
      [].forEach.call(sec.querySelectorAll('[data-obj]'), function (host) {
        var draw = OBJ[host.getAttribute('data-obj')];
        if (!draw) throw new Error('flat-edu: нет предмета «' + host.getAttribute('data-obj') + '»');
        var w = parseFloat(host.style.width), h = parseFloat(host.style.height);
        var svg = el('svg', { width: w, height: h, viewBox: '0 0 ' + w + ' ' + h, overflow: 'visible' }, host);
        svg.style.position = 'absolute'; svg.style.left = '0'; svg.style.top = '0';
        draw(svg, w, h, host);
      });
    });
    (window.FlatEduScenes || []).forEach(function (s) {
      if (ids.indexOf(s.scene) >= 0) frames.push(s.setup(kit, FILM, api));
    });
  }
  window.FlatEdu = kit;
  return {
    render: function (t) {
      var w = api.styleWeight(NAME, t);
      api.setStyle(layer, 'opacity', api.styleOpacity(NAME, t, layer).toFixed(3));
      api.setStyle(layer, 'visibility', w > 0.001 ? 'visible' : 'hidden');
      frames.forEach(function (f) { if (f && f.frame) f.frame(t); });
      if (w <= 0.001) return;
      if (wins) wins.render(t);
      nooks.forEach(function (n) {
        api.setStyle(n.g, 'opacity', api.sceneWeight(n.i, t).toFixed(3));
        api.setStyle(n.lit, 'opacity', (0.8 + 0.2 * Math.sin(2 * Math.PI * t / PRM.lamp_period + n.k)).toFixed(3));
      });
    },
    probe: function (t) { return { style: NAME, weight: api.styleWeight(NAME, t), world: cfg.world }; }
  };
});
