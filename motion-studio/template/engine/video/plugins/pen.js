/* Плагин pen — буквы «пером»: метка раскадровки plugins.act.cues {id, t, until?, who, do: "write", motion, lines, from, …}.
   Линию буквы ведёт перо (стебель, провод, кисть): из точки from к началу строки растёт ведущая линия, перо идёт по
   строке слева направо и открывает контур букв, заливка идёт следом; дописав, линия втягивается к перу и гаснет.

   Два закона, ради которых плагин написан (дефекты прежнего набора букв):
     строка не видна, пока до неё не дошло перо — и контур, и заливка режутся по своей границе (перо и фронт заливки),
       правее границы на слое букв нет ни пикселя: бледной «заготовки» строки нет;
     ведущая линия растёт от точки from, а не появляется во всю длину, и гаснет за lead_out, а не одним кадром.

   Числа движения — строка tokens.json motion.act, названная в motion метки (pen_stem, pen_wire): сборка кладёт их в
   cue.m, длину записи — в cue.span, закон по строкам — в cue.pen {starts, line_span, family, weight, colors}
   (build.py pen_config). Своих чисел движения здесь нет. Кадр — чистая функция t: ни часов, ни памяти прошлого кадра.

   В элементе-хозяине (who) плагин ставит свой холст размером с рамку хозяина; координаты строк и from — px в этой
   рамке. Видимость, вход и уход — у хозяина, битами сцены. Слой букв рисуется отдельно от ведущей линии: по нему
   промер считает краску правее пера. Промер (probe): у каждой строки — рамка, перо, фронт заливки, краска всего и
   правее пера, длина ведущей линии; проверка — V38. Области текста для V37 — textRects(t). */
(window.StagePlugins = window.StagePlugins || []).push(function (FILM, api) {
  'use strict';
  var SEG = 48;                 // отрезков в ломаной ведущей линии (точность рисунка, не движение)
  var INK_ALPHA = 24;           // альфа пикселя слоя букв, с которой он считается краской (сглаживание кромки — ниже)
  var items = [];
  FILM.scenes.forEach(function (sc) {
    (((sc.plugins || {}).act || {}).cues || []).forEach(function (q) { if (q.do === 'write') items.push(make(sc, q)); });
  });
  if (!items.length) return null;

  function make(sc, q) {
    var host = document.getElementById(sc.id + '--' + q.who);
    if (!host) throw new Error('pen: нет элемента #' + sc.id + '--' + q.who);
    if (!q.pen) throw new Error('pen: у метки ' + q.id + ' нет закона записи (сборка: build.py pen_config)');
    var W = host.offsetWidth, H = host.offsetHeight;
    var cv = document.createElement('canvas'), ink = document.createElement('canvas');
    cv.width = ink.width = W; cv.height = ink.height = H;
    cv.className = 'pen-canvas'; cv.setAttribute('data-pen', q.id);
    cv.style.cssText = 'position:absolute;left:0;top:0;width:' + W + 'px;height:' + H + 'px;pointer-events:none;';
    host.appendChild(cv);
    var mark = document.createElement('i');          // отпечаток исполнителя метки (V31): меняется вместе с записью
    mark.setAttribute('data-pen-mark', q.id); mark.style.display = 'none';
    host.appendChild(mark);
    var it = { sc: sc, q: q, m: q.m, host: host, cv: cv, ink: ink, W: W, H: H, lines: null, ease: api.powerEase(q.m.ease), mark: mark };
    (window.ActExec = window.ActExec || []).push({ scene: sc.id, who: q.who, node: mark, run: function (t, cues) {
      api.setAttr(mark, 'data-s', cues.filter(function (c) { return c.cue.id === q.id; })
        .map(function (c) { return c.p.toFixed(3); }).join(','));
    } });
    return it;
  }

  // геометрия строк: начертание роли должно быть загружено (правило движка StageFonts.face, lib/fonts.js) — до тех
  // пор мерить нечем (и не запоминать)
  function layout(it) {
    if (it.lines) return it.lines;
    var q = it.q, c = it.ink.getContext('2d'), ready = window.StageFonts.face(q.pen.family, q.pen.weight);
    var lines = q.lines.map(function (ln, i) {
      var font = q.pen.weight + ' ' + ln.size + 'px "' + q.pen.family + '"';
      c.font = font; c.textAlign = 'left'; c.textBaseline = 'alphabetic';
      var mt = c.measureText(ln.text), w = mt.width, al = ln.align || 'left';
      var left = al === 'left' ? ln.x : al === 'right' ? ln.x - w : ln.x - w / 2;
      var sw = it.m.stroke_frac * ln.size, pad = sw / 2 + 1;
      var x0 = left - (mt.actualBoundingBoxLeft || 0) - pad, x1 = left + (mt.actualBoundingBoxRight || w) + pad;
      var y0 = ln.y - (mt.actualBoundingBoxAscent || ln.size * 0.8) - pad, y1 = ln.y + (mt.actualBoundingBoxDescent || ln.size * 0.2) + pad;
      return { i: i, text: ln.text, font: font, size: ln.size, left: left, y: ln.y, sw: sw, lw: it.m.lead_frac * ln.size,
               rx: x0, ry: y0, rw: x1 - x0, rh: y1 - y0, tipY: ln.y - it.m.tip_rise_frac * ln.size,
               sag: it.m.sag_frac * ln.size, start: q.pen.starts[i] };
    });
    if (ready) it.lines = lines;
    return lines;
  }

  /* Состояние строки в момент t — закон записи (доли длины записи строки, tokens.json motion.act.<motion>):
       g — доля выросшей ведущей линии (0…1 за lead_in); c — доля строки под пером (кривая ease от lead_in до contour_until);
       f — фронт заливки (тот же ход с отставанием fill_lag); r — доля втянутой ведущей линии (0…1 за lead_out после contour_until). */
  function stateOf(it, L, t) {
    var m = it.m, p = api.clamp01((t - L.start) / it.q.pen.line_span), run = m.contour_until - m.lead_in;
    return { p: p, on: t > L.start,
             g: api.clamp01(p / m.lead_in),
             c: p <= m.lead_in ? 0 : it.ease(api.clamp01((p - m.lead_in) / run)),
             f: p <= m.lead_in + m.fill_lag ? 0 : it.ease(api.clamp01((p - m.lead_in - m.fill_lag) / run)),
             r: api.clamp01((p - m.contour_until) / m.lead_out) };
  }

  // ведущая линия: кривая от точки from до точки (x, y) с провисом — ломаная с длинами
  function leadPath(it, L, x, y) {
    var s = it.q.from, cx = (s[0] + x) / 2, cy = (s[1] + y) / 2 + L.sag, pts = [], len = [0];
    for (var k = 0; k <= SEG; k++) {
      var u = k / SEG, v = 1 - u;
      pts.push([v * v * s[0] + 2 * v * u * cx + u * u * x, v * v * s[1] + 2 * v * u * cy + u * u * y]);
      if (k) len.push(len[k - 1] + Math.hypot(pts[k][0] - pts[k - 1][0], pts[k][1] - pts[k - 1][1]));
    }
    return { pts: pts, len: len, total: len[SEG] };
  }
  function pointAt(path, d) {
    var k = 1;
    while (k < SEG && path.len[k] < d) k++;
    var a = path.pts[k - 1], b = path.pts[k], seg = path.len[k] - path.len[k - 1], u = seg > 0 ? (d - path.len[k - 1]) / seg : 0;
    return [a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u];
  }
  // видимая часть ведущей линии в состоянии st: {path, from, to} — отрезок длины вдоль пути; null — линии нет
  function leadOf(it, L, st) {
    if (!st.on || st.r >= 1) return null;
    var path = leadPath(it, L, L.rx + L.rw * st.c, L.tipY);
    if (st.c <= 0) return { path: path, from: 0, to: path.total * st.g, alpha: 1 };          // растёт к началу строки
    return { path: path, from: path.total * st.r, to: path.total, alpha: 1 - st.r };       // идёт за пером, затем втягивается
  }

  function drawInk(it, t) {
    var k = it.ink.getContext('2d'), col = it.q.pen.colors, m = it.m;
    k.setTransform(1, 0, 0, 1, 0, 0); k.clearRect(0, 0, it.W, it.H);
    layout(it).forEach(function (L) {
      var st = stateOf(it, L, t);
      if (st.c <= 0) return;                                  // перо ещё не дошло до строки: на слое букв пусто
      var tipX = L.rx + L.rw * st.c;
      var fillTo = L.rx + L.rw * st.f, fillOn = st.f > 0, fillAlpha = 1;
      k.save();
      k.font = L.font; k.textAlign = 'left'; k.textBaseline = 'alphabetic'; k.lineJoin = 'round';
      if (fillOn) {                                           // заливка — до своего фронта (он позади пера: fill_lag ≥ 0)
        k.save(); k.beginPath(); k.rect(L.rx, L.ry - L.size, fillTo - L.rx, L.rh + 2 * L.size); k.clip();
        k.globalAlpha = fillAlpha;
        if (col.glow) { k.shadowColor = col.glow; k.shadowBlur = m.glow_frac * L.size; k.globalAlpha = fillAlpha * m.glow_alpha; k.fillStyle = col.glow; k.fillText(L.text, L.left, L.y); k.shadowBlur = 0; k.globalAlpha = fillAlpha; }
        k.fillStyle = col.ink; k.fillText(L.text, L.left, L.y);
        k.restore();
      }
      k.beginPath(); k.rect(L.rx, L.ry - L.size, tipX - L.rx, L.rh + 2 * L.size); k.clip();      // контур — до пера
      k.strokeStyle = col.outline; k.lineWidth = L.sw; k.strokeText(L.text, L.left, L.y);
      k.restore();
    });
  }
  function draw(it, t) {
    drawInk(it, t);
    var c = it.cv.getContext('2d'), col = it.q.pen.colors;
    c.setTransform(1, 0, 0, 1, 0, 0); c.clearRect(0, 0, it.W, it.H);
    c.drawImage(it.ink, 0, 0);
    layout(it).forEach(function (L) {
      var ld = leadOf(it, L, stateOf(it, L, t));
      if (!ld || ld.to - ld.from <= 0) return;
      c.save();
      c.globalAlpha = ld.alpha; c.strokeStyle = col.lead; c.lineWidth = L.lw; c.lineCap = 'round'; c.lineJoin = 'round';
      c.beginPath();
      var a = pointAt(ld.path, ld.from);
      c.moveTo(a[0], a[1]);
      for (var k = 1; k <= SEG; k++) if (ld.path.len[k] > ld.from && ld.path.len[k] < ld.to) c.lineTo(ld.path.pts[k][0], ld.path.pts[k][1]);
      var b = pointAt(ld.path, ld.to);
      c.lineTo(b[0], b[1]); c.stroke();
      c.restore();
    });
  }
  function render(t) { items.forEach(function (it) { draw(it, t); }); }

  // краска слоя букв в рамке строки: всего и правее границы x (px холста)
  function inkCount(it, L, x) {
    var x0 = Math.max(0, Math.floor(L.rx)), y0 = Math.max(0, Math.floor(L.ry));
    var w = Math.min(it.W, Math.ceil(L.rx + L.rw)) - x0, h = Math.min(it.H, Math.ceil(L.ry + L.rh)) - y0;
    if (w <= 0 || h <= 0) return { all: 0, ahead: 0 };
    var d = it.ink.getContext('2d').getImageData(x0, y0, w, h).data, all = 0, ahead = 0, edge = Math.ceil(x) - x0;
    for (var yy = 0; yy < h; yy++) for (var xx = 0; xx < w; xx++) {
      if (d[(yy * w + xx) * 4 + 3] > INK_ALPHA) { all++; if (xx > edge) ahead++; }
    }
    return { all: all, ahead: ahead };
  }
  function r2(v) { return Math.round(v * 100) / 100; }
  function probe(t) {
    return { plugin: 'pen', items: items.map(function (it) {
      draw(it, t);
      return { scene: it.sc.id, cue: it.q.id, who: it.q.who, motion: it.q.motion, lines: layout(it).map(function (L) {
        var st = stateOf(it, L, t), tip = st.c > 0 ? L.rx + L.rw * st.c : null, n = inkCount(it, L, tip == null ? L.rx - 1 : tip);
        var ld = leadOf(it, L, st);
        return { text: L.text, rect: [r2(L.rx), r2(L.ry), r2(L.rw), r2(L.rh)], p: r2(st.p), tip: tip == null ? null : r2(tip),
                 fill: r2(st.f), ink: n.all, ink_ahead: n.ahead,
                 lead: ld ? r2(Math.max(0, ld.to - ld.from)) : 0, lead_full: ld ? r2(ld.path.total) : 0, lead_alpha: ld ? r2(ld.alpha) : 0 };
      }) };
    }) };
  }

  // области текста для читаемости по пикселям (V37): строка мерится, когда дописана и хозяин виден на 1,0
  function shownOf(node) {
    var o = 1;
    for (var e = node; e && e.nodeType === 1 && e.id !== 'root'; e = e.parentElement) {
      var cs = getComputedStyle(e);
      if (cs.display === 'none' || cs.visibility === 'hidden') return 0;
      o *= parseFloat(cs.opacity);
    }
    return o;
  }
  function textRects(t) {
    var out = [], root = document.getElementById('root').getBoundingClientRect();
    items.forEach(function (it) {
      var b = it.cv.getBoundingClientRect(), kx = b.width / it.W, ky = b.height / it.H, shown = shownOf(it.host);
      layout(it).forEach(function (L) {
        var st = stateOf(it, L, t);
        out.push({ id: it.sc.id + '--' + it.q.who + ':' + L.i, text: L.text, opacity: r2(shown * (st.f >= 1 ? 1 : st.f * 0.99)),
                   rect: [r2(b.left - root.left + L.rx * kx), r2(b.top - root.top + L.ry * ky), r2(L.rw * kx), r2(L.rh * ky)] });
      });
    });
    return out;
  }
  return { render: render, probe: probe, textRects: textRects };
});
