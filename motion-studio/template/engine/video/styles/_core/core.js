/* Общие фактуры стилей — window.StyleCore. Всё рисуется кодом, без картинок извне, и всё
   детерминировано: случайность только из сидированного генератора, сид — из имени и номера кадра
   (не Math.random, не Date). Один и тот же кадр в любом порядке и после перезагрузки — те же пиксели;
   это и проверяет V24 (check.py).

   Что есть:
     rng(seed)                      генератор 0…1 (mulberry32), seed — целое
     hash(str)                      целое из строки — сид от id элемента
     grainTiles(n, size, seed, o)   n тайлов моно-зерна (dataURL): o.alpha, o.sigma (разброс), o.dark (доля тёмного)
     paperTile(size, seed, o)       бумага: пятна + волокна + зуб (dataURL), o.alpha, o.fibres, o.blot
     gridPaper(cellPx, color, o)    клетка тетради (CSS background-image): o.major (каждая N-я линия), o.width
     svg(tag, attrs, parent)        элемент SVG
     defs()                         общий скрытый <svg><defs> страницы
     boil(id, o)                    фильтр кипения линий: feTurbulence → feDisplacementMap; .set(seed) — новый рисунок
     hatch(id, o)                   штриховка (pattern): o.angle, o.gap, o.width, o.color, o.opacity
     halftone(id, o)                полутон (pattern): o.cell, o.r, o.color, o.opacity
     vignette(el, o)                виньетка (radial-gradient на элементе): o.strength 0…1, o.rgb [r,g,b], o.inner
     roughRect(x, y, w, h, rnd, j)  путь «от руки» вокруг прямоугольника: стороны с дрожью j px и выносом за углы
     roughEllipse(cx, cy, rx, ry, rnd, j)  то же для круга
     slots(zones, n, pad)           квадраты [x, y, s] под предметы мира в зонах сцены (decor_zones)
     drawOn(paths, p)               рисование линией: видна доля p каждого контура
     text(parent, x, y, str, attrs) надпись SVG (шрифт декора — attrs['font-family'] = cfg.fonts.decor)
     pixelText(parent, str, x, y, o)  пиксельная надпись кодом с кириллицей: o.rows (высота в пикселях), o.cell, o.color, o.font
     fontsReady()                   шрифты страницы загружены (надпись по метрикам шрифта-файла рисуют заново, пока false)
     fontOf(style, role)            семейство шрифта роли стиля для холста (значение --sty-<стиль>-<роль>)
     codeTitle(api, scenes, parent, draw)  заголовок сцены кодом (fonts.title.kind "code"); → render(t)
     cssVar(name)                   значение CSS-переменной #root (--c-<роль> палитры)
     rgbOf(hex)                     [r, g, b]
   Как подключается: build.py кладёт этот файл на страницу один раз, перед plugin.js стилей. */
(function () {
  'use strict';
  function rng(seed) {
    var a = seed | 0;
    return function () {
      a = a + 0x6D2B79F5 | 0;
      var t = Math.imul(a ^ a >>> 15, 1 | a);
      t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
      return ((t ^ t >>> 14) >>> 0) / 4294967296;
    };
  }
  function hash(s) {
    var h = 2166136261;
    for (var i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
    return h | 0;
  }
  function canvas(w, h) { var c = document.createElement('canvas'); c.width = w; c.height = h; return c; }

  function grainTiles(n, size, seed, o) {
    o = o || {};
    var alpha = o.alpha != null ? o.alpha : 0.12, sigma = o.sigma != null ? o.sigma : 0.5, out = [];
    for (var k = 0; k < n; k++) {
      var c = canvas(size, size), g = c.getContext('2d'), img = g.createImageData(size, size), d = img.data, r = rng(seed * 131 + k * 7919 + 1);
      for (var i = 0; i < size * size; i++) {
        var v = (r() + r() + r() - 1.5) * sigma;            // ≈ нормальное, среднее 0
        var lum = v < 0 ? 0 : 255, a = Math.min(1, Math.abs(v)) * alpha;
        d[i * 4] = d[i * 4 + 1] = d[i * 4 + 2] = lum; d[i * 4 + 3] = Math.round(a * 255);
      }
      g.putImageData(img, 0, 0);
      out.push(c.toDataURL('image/png'));
    }
    return out;
  }

  function paperTile(size, seed, o) {
    o = o || {};
    var c = canvas(size, size), g = c.getContext('2d'), r = rng(seed), img = g.createImageData(size, size), d = img.data;
    var cell = 32, n = size / cell + 1, grid = [];
    for (var i = 0; i < n * n; i++) grid.push(r());
    function blot(x, y) {                                   // гладкие пятна: билинейный шум крупной сетки
      var gx = x / cell, gy = y / cell, x0 = Math.floor(gx), y0 = Math.floor(gy), fx = gx - x0, fy = gy - y0;
      var at = function (a, b) { return grid[((b % (n - 1)) * n) + (a % (n - 1))]; };
      var top = at(x0, y0) * (1 - fx) + at(x0 + 1, y0) * fx, bot = at(x0, y0 + 1) * (1 - fx) + at(x0 + 1, y0 + 1) * fx;
      return top * (1 - fy) + bot * fy;
    }
    var alpha = o.alpha != null ? o.alpha : 0.1, bl = o.blot != null ? o.blot : 0.6;
    for (var y = 0; y < size; y++) for (var x = 0; x < size; x++) {
      var k = (y * size + x) * 4, tooth = r();
      var v = bl * blot(x, y) + (1 - bl) * tooth;
      d[k] = d[k + 1] = d[k + 2] = 60; d[k + 3] = Math.round(v * alpha * 255);
    }
    g.putImageData(img, 0, 0);
    g.strokeStyle = 'rgba(60,60,60,' + (alpha * 1.4).toFixed(3) + ')';
    g.lineWidth = 0.6;
    for (var f = 0; f < (o.fibres != null ? o.fibres : 60); f++) {   // волокна: короткие изогнутые штрихи
      var fx0 = r() * size, fy0 = r() * size, ang = r() * Math.PI * 2, len = 6 + r() * 18;
      g.beginPath(); g.moveTo(fx0, fy0);
      g.quadraticCurveTo(fx0 + Math.cos(ang + 0.6) * len / 2, fy0 + Math.sin(ang + 0.6) * len / 2,
                         fx0 + Math.cos(ang) * len, fy0 + Math.sin(ang) * len);
      g.stroke();
    }
    return c.toDataURL('image/png');
  }

  function gridPaper(cell, color, o) {
    o = o || {};
    var w = o.width || 1, major = o.major || 0, majorColor = o.majorColor || color;
    var lines = ['linear-gradient(to right, ' + color + ' ' + w + 'px, transparent ' + w + 'px)',
                 'linear-gradient(to bottom, ' + color + ' ' + w + 'px, transparent ' + w + 'px)'];
    var sizes = [cell + 'px ' + cell + 'px', cell + 'px ' + cell + 'px'];
    if (major) {
      lines.unshift('linear-gradient(to right, ' + majorColor + ' ' + w + 'px, transparent ' + w + 'px)',
                    'linear-gradient(to bottom, ' + majorColor + ' ' + w + 'px, transparent ' + w + 'px)');
      sizes.unshift(cell * major + 'px ' + cell * major + 'px', cell * major + 'px ' + cell * major + 'px');
    }
    return { image: lines.join(','), size: sizes.join(',') };
  }

  var NS = 'http://www.w3.org/2000/svg';
  function svg(tag, attrs, parent) {
    var e = document.createElementNS(NS, tag);
    Object.keys(attrs || {}).forEach(function (k) { e.setAttribute(k, attrs[k]); });
    if (parent) parent.appendChild(e);
    return e;
  }
  var DEFS = null;
  function defs() {
    if (DEFS) return DEFS;
    var s = svg('svg', { id: 'style-defs', width: '0', height: '0', 'aria-hidden': 'true' });
    s.style.position = 'absolute'; s.style.left = '0'; s.style.top = '0';
    DEFS = svg('defs', {}, s);
    document.getElementById('root').appendChild(s);
    return DEFS;
  }
  function boil(id, o) {
    o = o || {};
    var f = svg('filter', { id: id, x: '-10%', y: '-10%', width: '120%', height: '120%', 'color-interpolation-filters': 'sRGB' }, defs());
    var tu = svg('feTurbulence', { type: 'fractalNoise', baseFrequency: String(o.freq || 0.03), numOctaves: String(o.octaves || 2),
                                   seed: '1', result: 'n' }, f);
    svg('feDisplacementMap', { 'in': 'SourceGraphic', in2: 'n', scale: String(o.scale || 3), xChannelSelector: 'R', yChannelSelector: 'G' }, f);
    var last = null;
    return { id: id, set: function (seed) { var v = String((seed % 100000) + 1); if (v !== last) { last = v; tu.setAttribute('seed', v); } } };
  }
  function hatch(id, o) {
    o = o || {};
    var gap = o.gap || 6, p = svg('pattern', { id: id, patternUnits: 'userSpaceOnUse', width: String(gap), height: String(gap),
                                                patternTransform: 'rotate(' + (o.angle != null ? o.angle : 45) + ')' }, defs());
    svg('line', { x1: '0', y1: '0', x2: '0', y2: String(gap), stroke: o.color || '#000', 'stroke-width': String(o.width || 1),
                  'stroke-opacity': String(o.opacity != null ? o.opacity : 1) }, p);
    return 'url(#' + id + ')';
  }
  function halftone(id, o) {
    o = o || {};
    var cell = o.cell || 8, p = svg('pattern', { id: id, patternUnits: 'userSpaceOnUse', width: String(cell), height: String(cell) }, defs());
    svg('circle', { cx: String(cell / 2), cy: String(cell / 2), r: String(o.r || cell / 4), fill: o.color || '#000',
                    'fill-opacity': String(o.opacity != null ? o.opacity : 1) }, p);
    return 'url(#' + id + ')';
  }
  function vignette(el, o) {
    o = o || {};
    var c = o.rgb || [0, 0, 0], s = o.strength != null ? o.strength : 0.35, inner = o.inner != null ? o.inner : 55;
    el.style.background = 'radial-gradient(ellipse at center, rgba(' + c.join(',') + ',0) ' + inner + '%, rgba('
      + c.join(',') + ',' + s + ') 100%)';
  }
  function jit(rnd, j) { return (rnd() * 2 - 1) * j; }
  function roughRect(x, y, w, h, rnd, j) {
    var over = j * 2.5, p = [];
    function side(x0, y0, x1, y1) {                 // отрезок с выносом за углы и прогибом в середине
      var dx = x1 - x0, dy = y1 - y0, len = Math.sqrt(dx * dx + dy * dy) || 1, ux = dx / len, uy = dy / len;
      var a = [x0 - ux * over * rnd() + jit(rnd, j), y0 - uy * over * rnd() + jit(rnd, j)];
      var b = [x1 + ux * over * rnd() + jit(rnd, j), y1 + uy * over * rnd() + jit(rnd, j)];
      var m = [(x0 + x1) / 2 + jit(rnd, j) - uy * jit(rnd, j), (y0 + y1) / 2 + jit(rnd, j) + ux * jit(rnd, j)];
      p.push('M' + a[0].toFixed(1) + ' ' + a[1].toFixed(1) + ' Q' + m[0].toFixed(1) + ' ' + m[1].toFixed(1) + ' '
             + b[0].toFixed(1) + ' ' + b[1].toFixed(1));
    }
    side(x, y, x + w, y); side(x + w, y, x + w, y + h); side(x + w, y + h, x, y + h); side(x, y + h, x, y);
    return p.join(' ');
  }
  function roughEllipse(cx, cy, rx, ry, rnd, j) {
    var n = 14, a0 = rnd() * Math.PI * 2, pts = [];
    for (var i = 0; i <= n + 1; i++) {             // чуть больше круга: конец заходит за начало
      var a = a0 + i / n * Math.PI * 2, k = 1 + jit(rnd, j) / Math.max(rx, ry);
      pts.push((cx + Math.cos(a) * rx * k).toFixed(1) + ' ' + (cy + Math.sin(a) * ry * k).toFixed(1));
    }
    return 'M' + pts[0] + ' L' + pts.slice(1).join(' L');
  }
  /* Место под предметы мира: зоны сцены [[x, y, w, h] px] → квадраты [x, y, s] слева направо, по
     n штук не больше; сторона — высота зоны без полей. Предметы стиля рисуются в эти квадраты. */
  function slots(zones, n, pad) {
    pad = pad == null ? 12 : pad;
    var out = [];
    (zones || []).forEach(function (z) {
      var s = z[3] - 2 * pad, k = Math.max(1, Math.floor((z[2] - pad) / (s + pad)));
      var gap = (z[2] - k * s) / (k + 1);
      for (var i = 0; i < k; i++) out.push([z[0] + gap + i * (s + gap), z[1] + pad, s]);
    });
    return out.slice(0, n == null ? out.length : n);
  }
  /* Рисование линией: доля p (0…1) каждого контура видна — pathLength = 1 */
  function drawOn(els, p) {
    els.forEach(function (e) {
      if (!e.__dl) { e.setAttribute('pathLength', '1'); e.__dl = 1; }
      var fin = e.getAttribute('data-dash') || 'none';     // пунктир рисунка — после того, как линия дорисована
      var v = p >= 1 ? fin : '1 1', o = p >= 1 ? '0' : (1 - p).toFixed(4);
      if (p >= 1 && fin !== 'none') e.removeAttribute('pathLength'), e.__dl = 0;
      if (e.__da !== v) { e.style.strokeDasharray = v; e.__da = v; }
      if (e.__do !== o) { e.style.strokeDashoffset = o; e.__do = o; }
    });
  }
  function text(parent, x, y, str, attrs) {
    var t = svg('text', Object.assign({ x: String(x), y: String(y) }, attrs || {}), parent);
    t.textContent = str;
    return t;
  }
  /* Шрифты страницы загружены? Шрифт стиля — файл (@font-face кладёт сборка), он приходит не сразу: надпись,
     нарисованная кодом по его метрикам (ширина буквы на холсте, растр пиксельной надписи), до загрузки стоит на
     запасном шрифте. Такую надпись рисуют заново, пока ответ не станет true (codeTitle делает это сам; своя
     надпись плагина — в render по образцу табло пикселя). Промеры и рендер ждут готовности шрифтов страницы, поэтому
     кадр фильма — всегда с загруженным шрифтом. Правило — одно на движок, по начертанию: StageFonts.all (lib/fonts.js). */
  function fontsReady() { return window.StageFonts.all(); }
  /* Семейство шрифта роли стиля для холста: ctx.font не понимает var(), поэтому берётся значение переменной
     --sty-<стиль>-<роль> (файл стиля, за ним фирменный). В SVG и CSS ставят cfg.fonts.<роль>. */
  function fontOf(style, role) { return cssVar('--sty-' + style + '-' + role) || 'sans-serif'; }
  /* Пиксельная надпись кодом с кириллицей: строка рисуется шрифтом o.font на маленьком холсте высотой o.rows
     пикселей, порог 50 % — и каждый закрашенный пиксель становится квадратом o.cell px. o.font — шрифт холста
     целиком («8px » + fontOf(стиль, роль)): пиксельный шрифт-файл в своём размере ложится в сетку точно. Без
     o.font — жирный рубленый шрифт браузера (sans-serif, без имени). Шрифт-файл грузится не сразу — см. fontsReady.
     → {g, w, h} (размер в px полотна). */
  function pixelText(parent, str, x, y, o) {
    o = o || {};
    var rows = o.rows || 12, cell = o.cell || 4, font = o.font || 'bold ' + rows + 'px sans-serif';
    var c = canvas(4, 4), g = c.getContext('2d');
    g.font = font;
    var w = Math.ceil(g.measureText(str).width) + 2, h = Math.ceil(rows * 1.3);
    c.width = w; c.height = h;
    g = c.getContext('2d'); g.font = font; g.textBaseline = 'top'; g.fillStyle = '#000'; g.fillText(str, 1, 0);
    var d = g.getImageData(0, 0, w, h).data, path = [];
    for (var yy = 0; yy < h; yy++) for (var xx = 0; xx < w; xx++)
      if (d[(yy * w + xx) * 4 + 3] > 127) path.push('M' + (x + xx * cell) + ' ' + (y + yy * cell) + 'h' + cell + 'v' + cell + 'h-' + cell + 'z');
    var gr = svg('g', {}, parent);
    svg('path', { d: path.join(''), fill: o.color || '#000' }, gr);
    return { g: gr, w: w * cell, h: h * cell, rows: h };
  }
  /* Заголовок сцены, нарисованный кодом (style.json fonts.title.kind = "code"). Для каждой сцены стиля:
     группа <g data-style-title="<сцена>" data-text="<заголовок>"> в слое parent; draw(g, text, box) рисует
     надпись в рамку box = {x, y, w, h} строки заголовка каркаса (px полотна) — и не выходит за неё (V22).
     Текст каркаса прячет world.css стиля: #root[data-style="<имя>"] .fr-title .t { color: transparent; }.
     → render(t): непрозрачность группы = непрозрачность заголовка каркаса. Надпись рисуется сразу и заново —
     пока шрифты страницы не загрузятся (fontsReady): draw меряет буквы шрифтом-файлом стиля. */
  function codeTitle(api, scenes, parent, draw) {
    var root = document.getElementById('root'), o0 = root.getBoundingClientRect(), items = [], final = false;
    scenes.forEach(function (id) {
      var fr = document.getElementById('title--' + id), span = fr && fr.querySelector('.t');
      if (!span) return;
      var text = span.textContent.replace(/\s+/g, ' ').trim(), r = fr.getBoundingClientRect();
      var g = svg('g', { 'data-style-title': id, 'data-text': text }, parent);
      items.push({ fr: fr, g: g, text: text, box: { x: r.left - o0.left, y: r.top - o0.top, w: r.width, h: r.height } });
    });
    function paint() {
      items.forEach(function (it) {
        while (it.g.firstChild) it.g.removeChild(it.g.firstChild);
        draw(it.g, it.text, it.box);
      });
      final = fontsReady();
    }
    paint();
    return function (t) {
      if (!final) paint();
      items.forEach(function (it) { api.setAttr(it.g, 'opacity', (parseFloat(it.fr.style.opacity) || 0).toFixed(3)); });
    };
  }
  /* ---------------------------------------------------------------- окна под текстом (читаемость на любом фильме)
     Мир стиля не знает, где на чужой сцене стоит текст: раскладку пишет режиссёр, а стиль калибровался на
     одной пробе. Поэтому мир не рисуется вслепую под надписями — под каждой зоной текста содержания стоит
     «окно» цветом фона бренда (--c-paper): буквы стоят на том же поле, что и без стиля, и контраст строки
     (V21) равен контрасту бренда на ЛЮБОЙ раскладке. Стиль оформляет окно своим языком (стекло, лоскут,
     клочок бумаги, рамка), но не красит его середину.

     layoutRect(el)                 рамка узла в px полотна по раскладке (offset*, без transform анимации)
     textZones(api, FILM, name, o)  {frame: [[x,y,w,h]], scenes: [{i, id, rects: [[x,y,w,h]]}]} — зоны текста:
                                    узлы .el сцен стиля с непустым .t (и карточки с заливкой: на
                                    приглушённом уровне сквозь них виден мир — окно под ними) + цели move текстовых узлов (в сцене конца
                                    движения); o.frame — и надписи каркаса (#frame .fr); o.pad (14) — поле
                                    вокруг; соседние после поля сливаются в одну зону, o.merge (0) — зазор
                                    слияния, px
     textWindows(api, FILM, name, o)  слой окон над миром стиля и под содержанием: div на зону, заливка
                                    --c-paper непрозрачно; o.css — свойства оформления окна (borderRadius,
                                    boxShadow, border…), o.feather — мягкий край цветом окна, px;
                                    o.decorate(div, rect, kind) — свои детали ('frame' | 'scene');
                                    o.parent (+ o.before) — окна внутри своего слоя стиля: над фоном мира, под
                                    обводками содержания (вес стиля тогда несёт слой стиля); без parent — свой
                                    слой 'back' (звать ДО addLayer мира: слой, добавленный раньше, лежит выше);
                                    → {layer, zones, render(t)}: окна сцены входят и уходят со сценой, у
                                    соседей того же стиля перекрываются (без провала яркости на стыке, V23). */
  function layoutRect(el) {
    var root = document.getElementById('root'), x = 0, y = 0, n = el;
    while (n && n !== root) { x += n.offsetLeft; y += n.offsetTop; n = n.offsetParent; }
    return [x, y, el.offsetWidth, el.offsetHeight];
  }
  function union(a, b) {
    var x = Math.min(a[0], b[0]), y = Math.min(a[1], b[1]);
    return [x, y, Math.max(a[0] + a[2], b[0] + b[2]) - x, Math.max(a[1] + a[3], b[1] + b[3]) - y];
  }
  function near(a, b, g) {
    return a[0] - g <= b[0] + b[2] && b[0] - g <= a[0] + a[2] && a[1] - g <= b[1] + b[3] && b[1] - g <= a[1] + a[3];
  }
  function cluster(rects, pad, merge, W, H) {
    var z = rects.filter(function (r) { return r[2] > 0 && r[3] > 0; })
      .map(function (r) { return [r[0] - pad, r[1] - pad, r[2] + 2 * pad, r[3] + 2 * pad]; });
    for (var again = true; again;) {
      again = false;
      for (var i = 0; i < z.length && !again; i++) for (var j = i + 1; j < z.length; j++) {
        if (near(z[i], z[j], merge)) { z[i] = union(z[i], z[j]); z.splice(j, 1); again = true; break; }
      }
    }
    return z.map(function (r) {
      var x0 = Math.max(0, r[0]), y0 = Math.max(0, r[1]);
      return [x0, y0, Math.min(W, r[0] + r[2]) - x0, Math.min(H, r[1] + r[3]) - y0].map(function (v) { return Math.round(v * 10) / 10; });
    });
  }
  function hasText(el) {
    return [].some.call(el.querySelectorAll('.t'), function (t) { return t.textContent.trim(); });
  }
  function textRects(el) {
    var r = layoutRect(el);
    [].forEach.call(el.querySelectorAll('.t'), function (t) { if (t.textContent.trim() && t.offsetWidth) r = union(r, layoutRect(t)); });
    return r;
  }
  function textZones(api, FILM, name, o) {
    o = o || {};
    var root = document.getElementById('root'), W = root.clientWidth, H = root.clientHeight;
    var pad = o.pad != null ? o.pad : 14, merge = o.merge || 0, mine = {}, per = {};
    FILM.scenes.forEach(function (sc, i) { if (sc.style === name) { mine[sc.id] = i; per[i] = []; } });
    document.querySelectorAll('#content .el[data-scene]').forEach(function (el) {
      var i = mine[el.getAttribute('data-scene')];
      if (i == null || !hasText(el)) return;
      per[i].push(textRects(el));
    });
    (FILM.moves || []).forEach(function (mv) {
      var el = mv.dom && document.getElementById(mv.dom), d = mv.dest || {};
      if (!el || !hasText(el)) return;
      var i = api.sceneAt(mv.t + (mv.dur || 0)), r = null;
      if (per[i] == null) return;
      if (d.box) r = d.box.slice(0, 4);
      else if (d.dom && document.getElementById(d.dom)) r = textRects(document.getElementById(d.dom));
      if (r) per[i].push(r);
    });
    var frame = [];
    if (o.frame) document.querySelectorAll('#frame .fr').forEach(function (f) {
      if (f.textContent.trim() && !f.closest('.fr .fr')) frame.push(textRects(f));
    });
    return { frame: cluster(frame, pad, merge, W, H),
             scenes: Object.keys(per).map(function (i) { return { i: +i, id: FILM.scenes[i].id, rects: cluster(per[i], pad, merge, W, H) }; }) };
  }
  /* вес окон сцены i: окно входит к началу сцены и уходит после её конца, если сосед — той же стиля
     (окна соседей перекрываются, без провала яркости на стыке, V23); иначе — вместе со сценой. */
  function windowWeight(FILM, name, i, t) {
    var s = FILM.scenes, sc = s[i], h = FILM.frame.seam_half;
    var sm = function (v) { v = Math.max(0, Math.min(1, v)); return v * v * (3 - 2 * v); };
    var inn = i === 0 ? 1 : sm((t - (s[i - 1].style === name ? sc.start - h : sc.start)) / h);
    var out = i === s.length - 1 ? 1 : 1 - sm((t - (s[i + 1].style === name ? sc.end : sc.end - h)) / h);
    return Math.min(inn, out);
  }
  function textWindows(api, FILM, name, o) {
    o = o || {};
    var own = !o.parent, layer, zones = textZones(api, FILM, name, o);
    if (own) layer = api.addLayer(name + '-windows', 'back');
    else {
      layer = document.createElement('div'); layer.className = 'layer';
      o.parent.insertBefore(layer, o.before || null);
    }
    layer.setAttribute('data-style-windows', name);
    var fill = cssVar('--c-paper') || '#FFFFFF', css = o.css || {}, items = [];
    function win(r, kind, i) {
      var d = document.createElement('div');
      d.className = 'layer style-window';
      d.setAttribute('data-style-window', kind);
      d.style.left = r[0] + 'px'; d.style.top = r[1] + 'px'; d.style.width = r[2] + 'px'; d.style.height = r[3] + 'px';
      d.style.right = 'auto'; d.style.bottom = 'auto';
      Object.keys(css).forEach(function (k) { d.style[k] = css[k]; });
      d.style.background = fill;                 // середина окна — всегда фон бренда: его не перекрашивает оформление
      if (o.feather) d.style.boxShadow = (css.boxShadow ? css.boxShadow + ', ' : '') + '0 0 ' + o.feather + 'px ' + (o.feather / 2) + 'px ' + fill;
      layer.appendChild(d);
      if (o.decorate) o.decorate(d, r, kind);
      items.push({ d: d, i: i });
    }
    zones.frame.forEach(function (r) { win(r, 'frame', null); });
    zones.scenes.forEach(function (s) { s.rects.forEach(function (r) { win(r, 'scene', s.i); }); });
    return {
      layer: layer, zones: zones,
      render: function (t) {
        if (own) {
          var w = api.styleWeight(name, t);
          api.setStyle(layer, 'opacity', w.toFixed(3));
          api.setStyle(layer, 'visibility', w > 0.001 ? 'visible' : 'hidden');
          if (w <= 0.001) return;
        }
        items.forEach(function (it) { if (it.i != null) api.setStyle(it.d, 'opacity', windowWeight(FILM, name, it.i, t).toFixed(3)); });
      }
    };
  }

  function cssVar(name) { return getComputedStyle(document.getElementById('root')).getPropertyValue(name).trim(); }
  function rgbOf(h) { h = h.replace('#', ''); return [parseInt(h.substr(0, 2), 16), parseInt(h.substr(2, 2), 16), parseInt(h.substr(4, 2), 16)]; }

  /* Якорь времени сцены {reply, at, offset} → секунды фильма: то же правило, что у битов раскадровки (build.py):
     начало реплики + доля её длины + сдвиг. Набор стиля отдаёт его сцене как kit.at — секунд в сцене нет. */
  function when(FILM, a) {
    var r = null;
    for (var i = 0; i < FILM.replies.length; i++) if (FILM.replies[i].num === a.reply) r = FILM.replies[i];
    if (!r) throw new Error('StyleCore.when: реплики ' + a.reply + ' нет в фильме');
    return r.start + (a.at || 0) * (r.end - r.start) + (a.offset || 0);
  }
  /* Метки действий мира сцены (плагин act, раскадровка plugins.act.cues) — как их собрала сборка: у каждой
     {id, t — секунды фильма, who, do, motion, m — числа tokens.json motion.act.<motion>, span — длина действия} и
     свои поля метки. Набор стиля отдаёт их сцене как kit.cues(сцена): мир стиля ставит своё движение на ту же
     метку, что исполняет разметка сцены, — время одно на всех. Сцена без меток — пустой список. */
  function cues(FILM, scene) {
    var sc = null;
    for (var i = 0; i < FILM.scenes.length; i++) if (FILM.scenes[i].id === scene) sc = FILM.scenes[i];
    return ((sc && sc.plugins && sc.plugins.act) || {}).cues || [];
  }
  /* Разметка конечности героя для условия позы (check.py V25): узел рисунка получает
     data-limb="<герой>:<сторона>:<up|down>". Промер DOM отдаёт, какие конечности видны в кадре; при видимой «up»
     видимая «down» той же стороны — третья рука. Скрывать — display: none либо visibility: hidden на узле или предке. */
  function limb(node, who, side, pos) {
    if (pos !== 'up' && pos !== 'down') throw new Error('StyleCore.limb: положение up | down, а не ' + pos);
    node.setAttribute('data-limb', who + ':' + side + ':' + pos);
    return node;
  }

  window.StyleCore = { when: when, cues: cues, limb: limb, rng: rng, hash: hash, grainTiles: grainTiles, paperTile: paperTile, gridPaper: gridPaper, svg: svg,
                       defs: defs, boil: boil, hatch: hatch, halftone: halftone, vignette: vignette, roughRect: roughRect,
                       roughEllipse: roughEllipse, cssVar: cssVar, rgbOf: rgbOf, slots: slots, drawOn: drawOn, text: text,
                       pixelText: pixelText, codeTitle: codeTitle, fontsReady: fontsReady, fontOf: fontOf, layoutRect: layoutRect, textZones: textZones,
                       textWindows: textWindows };
})();
