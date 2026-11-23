/* card-kit — набор букв: механика «предметы → текст → окна → нырок» и бумажная глубина (профиль profiles/card.md).
   Библиотека движка: подключается ключом фильма films/<f>.json "libs": ["card-kit"] (скрипт в <head> до разметки
   сцен: разметка зовёт CardKit.entry уже при разборе). Сцены его зовут, но не копируют. Поля меток и числа —
   engine/video/plugins/README.md, раздел «card-kit».

   Закон кадра: всё — чистая функция времени t (секунды фильма). Своего таймера нет; случайность — только зерно
   (mulberry32 от строки), ни Math.random, ни Date, ни памяти прошлого кадра. Числа движения — tokens.json motion.act.card_*
   (FILM.motion), цвета — роли палитры (CSS-переменные --c-<роль>), шрифты — роли (--font-<роль>). Своих чисел движения
   здесь нет; единственные константы — бумажная тень уровней DEPTH (доли ширины кадра) и роли палитры по умолчанию
   (светлая — paper, тёмная — ink).

   Публичное:
     CardKit.sampleText({text, font, x, y, align, step, seed}) → Point[]        точки внутри глифов (x, y — px кадра, y — база)
     CardKit.particleText({canvas, targets, sources, material, start, dur, order, motion, seed, consume?})
         → {render(t, ctx?), fall(word, t0, dur, motion? | {motion?, shape}), state(t), at(i, t), restAt(t), source(id, t),
            lineDone(line, t), particles}
         sources[].spout {x, y, dir_deg?, jitter}, sources[].emit [с, по] — поток из излива в окне вылета;
         material.consume — расход источника; motion.flight_size_frac_w — крупнее в полёте
     CardKit.strokeText({canvas, lines, sources, material, start, dur, motion, seed}) → тот же интерфейс: запись штрихом
         (у штриха прежний вид; буквы «пером» без бледной строки и с растущей линией — плагин plugins/pen.js)
     CardKit.shapePoints(shape, n, seed, src?) → [{x, y, part}]                  смайлик (обод, глаза, улыбка; from) | points
     CardKit.letterWindows({canvas, text, font, x, y, align, word, open: [t0, t1]})
         → {open(t), cut(t, ctx?), shadow(t), rect}                              прорези + кромка + тень верхнего слоя
     CardKit.strokePivot(text, font, x, y, charIndex, align) → {x, y, charX, baseline, size, ch, r_in}
     CardKit.dive({upper, lower, pivot, t0, dur, motion?, hole?, through?, fillAt?})
         → {at(t) → {upperScale, upperAlpha, lowerScale, fill, P, Ps, shadowK}, draw, drawLower(ctx, t), upperTransform(ctx, t), through}
         нырок насквозь: log_keys, pivot_to_center, shadow_fade, cover_by; hole — радиус окна в штрихе, px
     CardKit.paperDepth(el | ctx2d, level)                                       тень и толщина слоя (уровни 1–3)
     CardKit.entry(sceneId, fn(ctx, t)) / CardKit.entry(sceneId) → fn             реестр кадров входа сцен
     CardKit.drift(t, t0, t1, m) → {k, scale, dy}; CardKit.bloom(t, t0, t1, m) → mix
     CardKit.state(t) → [{scene, cue, kind, …}]                                   промер (probe.json, плагин cardkit)
     CardKit.tracks(t) → {сцена: {id: {x, y, angle?, alpha?}}}                    точки живых предметов кадра t
     CardKit.layer({scene, canvas, world, over?, compose?, sources?, materials?}) — слой сцены целиком:
         фраза из меток act (gather / fall / windows / dive), исполнители меток, кадр входа следующей сцены в окнах.
         L.track(id, {x, y, angle?, alpha?, space?, depth?}) — точка живого предмета в кадре;
         L.source(id, t) → {act, lift, tilt_deg, scale, emit, spent, back, left} — состояние источника по sources_act;
         L.shape(to) → фигура осыпания в px из метки fall (to: {shape: 'smiley', center, diameter_frac_w, ring, eyes, smile} | points).
         L.textRects(t) → [{id, rect, text, opacity}] — строки фразы для читаемости по пикселям (V37): слой сам отдаёт их
         движку (window.__textRects, lib/stage.js), сцене объявлять области фразы не надо.
         Метка gather: spend 'all' — расход, sources_act[] {id, t, emit_from, spent, until, spout, with[]}, lines[].by_source;
         метка fall: to + formed — осыпание в фигуру; метка dive: fade 'none' / through, cover_by — нырок насквозь. */
(function () {
  'use strict';
  var CK = {};
  var DEPTH = [null, { dy: 0.0049, blur: 0.0062, a: 0.30 }, { dy: 0.0099, blur: 0.0123, a: 0.35 }, { dy: 0.0160, blur: 0.0200, a: 0.40 }];
  var REG = { entries: {}, probes: [], tracks: {} };
  var LIGHT = 'paper', DARK = 'ink';        // роли палитры по умолчанию: материал без цвета и тень слоя

  // ------------------------------------------------------------------ основа
  function film() { var F = window.__FILM__; if (!F) throw new Error('CardKit: нет window.__FILM__ (вызов до сборки страницы)'); return F; }
  function size() {
    var r = document.getElementById('root');
    return { W: r ? (+r.getAttribute('data-width') || r.clientWidth) : 1080, H: r ? (+r.getAttribute('data-height') || r.clientHeight) : 1920 };
  }
  CK.size = size;
  CK.motion = function (name) {
    var m = ((film().motion || {}).act || {})[name];
    if (!m) throw new Error('CardKit: нет tokens.json motion.act.' + name);
    return m;
  };
  CK.clamp01 = function (x) { return x < 0 ? 0 : x > 1 ? 1 : x; };
  CK.lerp = function (a, b, p) { return a + (b - a) * p; };
  var easeCache = {};
  CK.ease = function (name) {
    name = name || 'none';
    if (!easeCache[name]) easeCache[name] = name === 'none' ? function (x) { return x; } : window.gsap.parseEase(name);
    return easeCache[name];
  };
  CK.hash = function (s) { var h = 2166136261; s = String(s); for (var i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return h | 0; };
  CK.rng = function (seed) {
    var a = typeof seed === 'number' ? seed | 0 : CK.hash(seed);
    return function () {
      a |= 0; a = a + 0x6D2B79F5 | 0;
      var t = Math.imul(a ^ a >>> 15, 1 | a);
      t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
      return ((t ^ t >>> 14) >>> 0) / 4294967296;
    };
  };
  CK.gauss = function (r) { var u = 0, v = 0; while (!u) u = r(); while (!v) v = r(); return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v); };

  // цвета — роли палитры tokens.json (--c-<роль>), в разметке hex не пишется (V12)
  var colorCache = {};
  CK.color = function (role) {
    if (colorCache[role]) return colorCache[role];
    var v = getComputedStyle(document.documentElement).getPropertyValue('--c-' + role).trim();
    if (!/^#[0-9a-fA-F]{6}$/.test(v)) throw new Error('CardKit: роли палитры «' + role + '» нет в tokens.json palette');
    return (colorCache[role] = v);
  };
  CK.rgb = function (role) { var h = CK.color(role); return [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)]; };
  CK.rgba = function (role, a) { var c = CK.rgb(role); return 'rgba(' + c[0] + ',' + c[1] + ',' + c[2] + ',' + (+a).toFixed(4) + ')'; };
  CK.mix = function (roleA, roleB, p, a) {
    var x = CK.rgb(roleA), y = CK.rgb(roleB);
    return 'rgba(' + [0, 1, 2].map(function (k) { return Math.round(CK.lerp(x[k], y[k], p)); }).join(',') + ',' + (a == null ? 1 : a) + ')';
  };
  // шрифт — роль (--font-<роль>, project.json fonts / tokens.json fonts), начертание 700
  var famCache = {};
  CK.family = function (role) {
    if (famCache[role]) return famCache[role];
    var v = getComputedStyle(document.documentElement).getPropertyValue(role === 'brand' ? '--font-brand' : '--font-' + role).trim();
    var m = v.match(/"([^"]+)"/);
    if (!m) throw new Error('CardKit: роли шрифта «' + role + '» нет на странице');
    return (famCache[role] = m[1]);
  };
  CK.font = function (role, px) { return '700 ' + (+px).toFixed(2) + 'px "' + CK.family(role) + '"'; };
  function fontPx(font) { var m = String(font).match(/([\d.]+)px/); return m ? +m[1] : 16; }
  // начертание загружено — правило движка StageFonts.face (lib/fonts.js): состояние самого начертания страницы, а не
  // общий ответ, который «да» и про шрифт, которого ещё нет (геометрия букв запомнилась бы по запасному шрифту).
  // У шрифта без названного в кавычках семейства (font: «700 40px sans-serif») начертания страницы нет — отвечает браузер
  function fontReady(font, text) {
    var fam = (String(font).match(/"([^"]+)"/) || [])[1], wt = (String(font).match(/^\s*(\d+)/) || [])[1];
    if (!fam) return !document.fonts || document.fonts.check(font, text || 'Аа');
    return window.StageFonts.face(fam, wt || null);
  }
  CK.fontReady = fontReady;

  var meas = null;
  function mctx() { if (!meas) meas = document.createElement('canvas').getContext('2d'); return meas; }
  function measure(font, s) { var c = mctx(); c.font = font; return c.measureText(s).width; }
  function leftOf(text, font, x, align) { var w = measure(font, text); return align === 'left' ? x : align === 'right' ? x - w : x - w / 2; }
  CK.measure = measure;

  // ------------------------------------------------------------------ sampleText
  var sampleCache = {};
  CK.sampleText = function (o) {
    var text = o.text, font = o.font, align = o.align || 'center', step = o.step;
    if (!(step > 0)) throw new Error('CardKit.sampleText: нужен step > 0 (px)');
    var key = [text, font, o.x, o.y, align, step, o.seed || ''].join('|');
    if (sampleCache[key]) return sampleCache[key];
    var size = fontPx(font), left = leftOf(text, font, o.x, align), w = measure(font, text);
    var pad = Math.ceil(size * 0.6), x0 = Math.floor(left - pad), y0 = Math.floor(o.y - size * 1.3);
    var cw = Math.ceil(w + 2 * pad), ch = Math.ceil(size * 1.9);
    var cv = document.createElement('canvas'); cv.width = cw; cv.height = ch;
    var c = cv.getContext('2d', { willReadFrequently: true });
    c.font = font; c.textBaseline = 'alphabetic'; c.textAlign = 'left'; c.fillStyle = '#000';
    c.fillText(text, left - x0, o.y - y0);
    var d = c.getImageData(0, 0, cw, ch).data, r = CK.rng('sample|' + key), pts = [];
    var edges = [];
    for (var i = 0; i <= text.length; i++) edges.push(left + measure(font, text.slice(0, i)));
    var minX = 1e9, minY = 1e9, maxX = -1e9, maxY = -1e9;
    for (var yy = 0; yy < ch; yy += step) {
      for (var xx = 0; xx < cw; xx += step) {
        var px = Math.round(xx), py = Math.round(yy);
        if (d[(py * cw + px) * 4 + 3] > 140) {
          var X = x0 + xx + (r() - 0.5) * step * 0.3, Y = y0 + yy + (r() - 0.5) * step * 0.3, ci = 0;
          while (ci < text.length - 1 && X >= edges[ci + 1]) ci++;
          pts.push({ x: X, y: Y, ci: ci });
          if (X < minX) minX = X; if (X > maxX) maxX = X; if (Y < minY) minY = Y; if (Y > maxY) maxY = Y;
        }
      }
    }
    pts.box = [minX, minY, maxX - minX, maxY - minY];
    pts.edges = edges; pts.text = text; pts.font = font; pts.left = left; pts.width = w;
    if (fontReady(font, text)) sampleCache[key] = pts;    // шрифт ещё не пришёл — не запоминать (рисуется запасным)
    return pts;
  };

  // ------------------------------------------------------------------ particleText
  /* targets — Point[] (sampleText) с полями line (номер строки), key (точка ключевого слова), word (слово точки).
     sources — рамки предметов-источников [{id, x, y, w, h, shape?: 'rect' | 'gauss' | 'trail', spout?}] (px кадра).
       spout — точка излива {x, y, dir_deg, jitter}: частица выходит из неё (± jitter px), первую часть пути летит
       струёй по dir_deg (0 — вправо, 90 — вниз; длина струи motion.spout_len_frac_w × W) и до вылета не видна (она внутри
       предмета); без spout — из случайной точки рамки и до вылета лежит там.
     material — {colors: [css], size: px, kind: 'dust' | 'emboss' | 'petal' | 'stroke', rest: число частиц в источнике, consume}.
       consume — остаток уходит вместе с вылетами своего источника: к последнему вылету (не позже until − flight)
       в источнике пусто; source(id, t) — доля, что ещё в источнике (сцена рисует горку и дорожки по ней).
     start, dur — сборка: последняя частица садится ровно в start + dur (motion.fit = last_lands_at_until).
     motion — числа card_gather* (flight, ltr_spread, line_lag, key_lag, jitter, arc_frac_w, swirl_frac_w, ease, settle_wobble_frac_w,
       flight_scale — во сколько раз частица крупнее в середине полёта, spout_len_frac_w — длина струи из излива). */
  function pickSource(sources, r) {
    var s = sources[Math.floor(r() * sources.length) % sources.length], x, y;
    if (s.spout) {
      var j = s.spout.jitter || 0;
      x = s.spout.x + CK.gauss(r) * j / 2; y = s.spout.y + CK.gauss(r) * j / 2;
    } else if (s.shape === 'gauss') {
      x = s.x + s.w / 2 + CK.gauss(r) * s.w / 6; y = s.y + s.h / 2 + CK.gauss(r) * s.h / 6;
    } else if (s.shape === 'trail') {
      var u = r(); x = s.x + u * s.w; y = s.y + s.h * (0.5 + 0.38 * Math.sin(Math.PI * u) * (s.bow || -1)) + (r() - 0.5) * s.h * 0.25;
    } else { x = s.x + r() * s.w; y = s.y + r() * s.h; }
    if (!s.spout) { x = Math.min(s.x + s.w, Math.max(s.x, x)); y = Math.min(s.y + s.h, Math.max(s.y, y)); }   // излив — точка горлышка, может выходить за рамку
    return { x: x, y: y, src: s.id, s: s };
  }
  function sm01(x) { x = x < 0 ? 0 : x > 1 ? 1 : x; return x * x * (3 - 2 * x); }
  function spoutDir(sp) { var a = (sp.dir_deg || 0) * Math.PI / 180; return [Math.cos(a), Math.sin(a)]; }

  /* Точки фигуры осыпания, px кадра. shape:
       {kind: 'smiley', x, y, r, cell, ring: {from?, line: [от, до]}, eyes: {from?, at: [[dx, dy], [dx, dy]], size: [от, до]},
        smile: {from?, through: [[dx, dy] × 3], line: [от, до]}} — обод радиуса r, глаза (центры — смещения от центра, диаметр),
        улыбка — кривая через три точки; толщина обода и улыбки, диаметр глаз — в своих пределах по плотности: n точек
        с шагом cell ложатся без дыр и без лишних (избыток — линия толще, но не толще «до»);
       {kind: 'points', points: [{x, y}], spread?} — произвольный набор: n точек по кругу набора, ± spread px.
     src — источник частиц: точки только в частях, у которых from = src (нет таких — в частях без from, нет и их — во всех).
     Зерно — seed. У каждой точки часть: ring, eye-l, eye-r, smile, points. */
  function bezier3(t, p) {           // кривая через три точки: B(0) = p0, B(½) = p1, B(1) = p2
    var cx = 2 * p[1][0] - (p[0][0] + p[2][0]) / 2, cy = 2 * p[1][1] - (p[0][1] + p[2][1]) / 2, u = 1 - t;
    return [u * u * p[0][0] + 2 * u * t * cx + t * t * p[2][0], u * u * p[0][1] + 2 * u * t * cy + t * t * p[2][1],
            2 * u * (cx - p[0][0]) + 2 * t * (p[2][0] - cx), 2 * u * (cy - p[0][1]) + 2 * t * (p[2][1] - cy)];
  }
  CK.smilePath = function (through, n) {     // [[x, y, nx, ny]] — n + 1 точек кривой улыбки, равномерно по длине, с нормалью
    var raw = [], L = [0], i;
    for (i = 0; i <= 200; i++) { raw.push(bezier3(i / 200, through)); if (i) L.push(L[i - 1] + Math.hypot(raw[i][0] - raw[i - 1][0], raw[i][1] - raw[i - 1][1])); }
    var out = [], j = 0;
    for (i = 0; i <= n; i++) {
      var want = L[200] * i / n;
      while (j < 199 && L[j + 1] < want) j++;
      var f = (want - L[j]) / Math.max(1e-9, L[j + 1] - L[j]), q = raw[j], q2 = raw[j + 1];
      var x = q[0] + (q2[0] - q[0]) * f, y = q[1] + (q2[1] - q[1]) * f, tx = q[2] + (q2[2] - q[2]) * f, ty = q[3] + (q2[3] - q[3]) * f, tl = Math.hypot(tx, ty) || 1;
      out.push([x, y, -ty / tl, tx / tl]);
    }
    out.length_px = L[200];
    return out;
  };
  CK.shapePoints = function (shape, n, seed, src) {
    var r = CK.rng('shape|' + (seed || '')), out = [], i;
    if (shape.kind === 'points') {
      var pts0 = shape.points || [], sp = shape.spread || 0;
      if (!pts0.length) throw new Error('CardKit.shapePoints: пустой набор точек');
      for (i = 0; i < n; i++) {
        var q = pts0[Math.floor(i * pts0.length / Math.max(1, n)) % pts0.length];
        out.push({ x: q.x + (r() - 0.5) * 2 * sp, y: q.y + (r() - 0.5) * 2 * sp, part: 'points' });
      }
      return out;
    }
    if (shape.kind !== 'smiley') throw new Error('CardKit.shapePoints: фигуры «' + shape.kind + '» нет (smiley | points)');
    var R = shape.r, cell2 = Math.pow(shape.cell || 4, 2), mid = function (a) { return (a[0] + a[1]) / 2; };
    var smile = shape.smile ? CK.smilePath(shape.smile.through, 64) : null;
    var parts = [];
    if (shape.ring) parts.push({ id: 'ring', from: shape.ring.from, w: 2 * Math.PI * R * mid(shape.ring.line) });
    if (shape.eyes) shape.eyes.at.forEach(function (a, k) { parts.push({ id: k ? 'eye-r' : 'eye-l', from: shape.eyes.from, at: a, w: Math.PI * Math.pow(mid(shape.eyes.size) / 2, 2) }); });
    if (shape.smile) parts.push({ id: 'smile', from: shape.smile.from, w: smile.length_px * mid(shape.smile.line) });
    var sel = parts.filter(function (p) { return src != null && p.from === src; });
    if (!sel.length) sel = parts.filter(function (p) { return p.from == null; });
    if (!sel.length) sel = parts;
    var tot = sel.reduce(function (s, p) { return s + p.w; }, 0), left = n;
    sel.forEach(function (p, k) { p.n = k === sel.length - 1 ? left : Math.round(n * p.w / tot); left -= p.n; });
    var clampR = function (v, a) { return Math.max(a[0], Math.min(a[1], v)); };
    sel.forEach(function (p) {
      var j, u, th, rho;
      if (p.id === 'ring') {
        var lw = clampR(p.n * cell2 / (2 * Math.PI * R), shape.ring.line);
        for (j = 0; j < p.n; j++) { u = (j + r()) / p.n; th = 2 * Math.PI * u; rho = R + (r() - 0.5) * lw; out.push({ x: shape.x + rho * Math.cos(th), y: shape.y + rho * Math.sin(th), part: 'ring' }); }
      } else if (p.id === 'smile') {
        var sw = clampR(p.n * cell2 / smile.length_px, shape.smile.line);
        for (j = 0; j < p.n; j++) {
          u = (j + r()) / p.n; var k2 = Math.min(63, Math.floor(u * 64)), q2 = smile[k2], q3 = smile[k2 + 1], f = u * 64 - k2, off = (r() - 0.5) * sw;
          out.push({ x: shape.x + q2[0] + (q3[0] - q2[0]) * f + q2[2] * off, y: shape.y + q2[1] + (q3[1] - q2[1]) * f + q2[3] * off, part: 'smile' });
        }
      } else {
        var dm = clampR(2 * Math.sqrt(p.n * cell2 / Math.PI), shape.eyes.size);
        for (j = 0; j < p.n; j++) { th = 2 * Math.PI * r(); rho = dm / 2 * Math.sqrt((j + r()) / p.n); out.push({ x: shape.x + p.at[0] + rho * Math.cos(th), y: shape.y + p.at[1] + rho * Math.sin(th), part: p.id }); }
      }
    });
    return out;
  };

  CK.particleText = function (o) {
    var S = size(), W = S.W, H = S.H, m = o.motion, mat = o.material || {};
    if (!o.sources || !o.sources.length) throw new Error('CardKit.particleText: нет sources — текст не появляется из воздуха');
    var r = CK.rng(o.seed || 'particles'), ease = CK.ease(m.ease), flight = Math.min(m.flight, o.dur);
    var arc = m.arc_frac_w, swirl = m.swirl_frac_w * W, wob = m.settle_wobble_frac_w * W;
    var wr = m.settle_wobble_rad_s, restA = m.rest_wobble_frac_w * W, restR = m.rest_wobble_rad_s;
    // размер в полёте: у источника source_size_frac_w, в середине пути flight_size_frac_w ([от, до] — у каждой частицы своё),
    // к посадке — размер материала; без flight_size_frac_w — flight_scale (во сколько раз крупнее в середине пути)
    var msz = mat.size || 2, fsz = m.flight_size_frac_w, fscale = m.flight_scale || 1;
    var srcSz = m.source_size_frac_w ? m.source_size_frac_w * W / msz : 1, qs = m.stream_share || 0;
    var gU = m.size_grow_until != null ? m.size_grow_until : 0.5, sF = m.size_shrink_from != null ? m.size_shrink_from : 0.5, spLen = (m.spout_len_frac_w || 0) * W, consume = !!(mat.consume || o.consume);
    var colors = mat.colors || [CK.color(LIGHT)];
    var P = o.targets.map(function (p, i) {
      var s = pickSource(p.srcs ? p.srcs.map(function (k) { return o.sources[k]; }) : o.sources, r);
      var d = (m.ltr_spread || 0) * (p.x / W) + (m.line_lag || 0) * (p.line || 0) + (p.key ? (m.key_lag || 0) : 0) + (m.jitter || 0) * r();
      return { i: i, sx: s.x, sy: s.y, src: s.src, so: s.s, tx: p.x, ty: p.y, d: d, line: p.line || 0, key: !!p.key, word: p.word || null,
               col: p.col != null ? p.col : Math.floor(r() * colors.length), arc: (arc[0] + r() * (arc[1] - arc[0])) * W,
               sw: (r() - 0.5) * 2 * swirl, vx: r() - 0.5, ph: r() * 6.283, u: r(), fl: flight, sp: null, cx: 0, cy: 0,
               pk: fsz ? (Array.isArray(fsz) ? fsz[0] + r() * (fsz[1] - fsz[0]) : fsz) * W / msz : fscale };
    });
    var maxD = 0;
    P.forEach(function (p) { if (p.d > maxD) maxD = p.d; });
    var room = Math.max(0, o.dur - flight), k = maxD > 0 ? room / maxD : 0;     // fit: последняя садится ровно в start + dur
    P.forEach(function (p) { p.d *= k; });
    // по предметам: излив (направление — dir_deg, иначе к середине своих букв) и окно вылета emit [с, по] (источник пуст в «по»;
    // полёт min(flight, start + dur − по) — последняя частица источника садится не позже конца сборки)
    o.sources.forEach(function (so) {
      var mine = P.filter(function (p) { return p.so === so; });
      if (!mine.length) return;
      if (so.spout) {
        var dir;
        if (so.spout.dir_deg != null) dir = spoutDir(so.spout);
        else {
          var mx = 0, my = 0;
          mine.forEach(function (p) { mx += p.tx; my += p.ty; });
          mx = mx / mine.length - so.spout.x; my = my / mine.length - so.spout.y;
          var ln = Math.hypot(mx, my) || 1; dir = [mx / ln, my / ln];
        }
        // ствол струи: от излива по направлению на spout_len — общий для всех частиц предмета (первые stream_share пути),
        // дальше — к своей букве, касательная непрерывна (контроль на 0,2 оставшегося пути)
        mine.forEach(function (p) {
          p.sp = dir; p.cx = p.sx + dir[0] * spLen; p.cy = p.sy + dir[1] * spLen;
          var rem = Math.hypot(p.tx - p.cx, p.ty - p.cy) * 0.2; p.kx = p.cx + dir[0] * rem; p.ky = p.cy + dir[1] * rem;
        });
      }
      if (so.emit) {
        var e0 = so.emit[0], e1 = so.emit[1], fl = Math.max(1e-3, Math.min(m.flight, o.start + o.dur - e1));
        mine.sort(function (a, b) { return a.d - b.d || a.i - b.i; });
        mine.forEach(function (p, j) { p.d = e0 - o.start + (e1 - e0) * (mine.length > 1 ? j / (mine.length - 1) : 1); p.fl = fl; });
      }
    });
    // источник: вылеты частиц и остаток по предметам (расход)
    var bySrc = {};
    function srcRec(id) { return (bySrc[id] = bySrc[id] || { dep: [], rest: [] }); }
    P.forEach(function (p) { srcRec(p.src).dep.push(o.start + p.d); });
    Object.keys(bySrc).forEach(function (id) { bySrc[id].dep.sort(function (a, b) { return a - b; }); });
    var rest = [];
    for (var i = 0; i < (mat.rest || 0); i++) {
      var s0 = pickSource(o.sources, r), rp0 = { x: s0.x, y: s0.y, src: s0.src, col: Math.floor(r() * colors.length), ph: r() * 6.283, leave: Infinity };
      rest.push(rp0); srcRec(s0.src).rest.push(rp0);
    }
    if (consume) {             // j-я крупинка остатка уходит вместе с соответствующим по порядку вылетом своего источника
      Object.keys(bySrc).forEach(function (id) {
        var b = bySrc[id], dep = b.dep.length ? b.dep : [o.start + maxD * k];
        b.rest.forEach(function (rp, j) { rp.leave = dep[Math.max(0, Math.ceil((j + 1) * dep.length / b.rest.length) - 1)]; });
      });
    }
    var falls = [];
    function pos(p, t) {
      var q = CK.clamp01((t - o.start - p.d) / p.fl), e = ease(q), s = Math.sin(Math.PI * e), x, y, a = 1;
      if (p.sp) {                      // струя из излива: ствол (общий для предмета), затем кривая к своей букве
        if (qs > 0 && e <= qs) { var v = e / qs; x = p.sx + (p.cx - p.sx) * v; y = p.sy + (p.cy - p.sy) * v; }
        else {
          var w2 = qs > 0 ? (e - qs) / (1 - qs) : e, u = 1 - w2, bx = qs > 0 ? p.cx : p.sx, by = qs > 0 ? p.cy : p.sy;
          var kx = qs > 0 ? p.kx : p.cx, ky = qs > 0 ? p.ky : p.cy, s2 = Math.sin(Math.PI * w2);
          x = u * u * bx + 2 * u * w2 * kx + w2 * w2 * p.tx + s2 * p.sw * 0.5; y = u * u * by + 2 * u * w2 * ky + w2 * w2 * p.ty;
        }
        if (t <= o.start + p.d) a = 0;    // до вылета — внутри предмета
      } else { x = p.sx + (p.tx - p.sx) * e + s * p.sw; y = p.sy + (p.ty - p.sy) * e - s * p.arc; }
      if (q >= 1 && wob) { x += Math.sin(t * wr[0] + p.ph) * wob; y += Math.cos(t * wr[1] + p.ph) * wob; }
      var fs = null;
      for (var j = 0; j < falls.length; j++) {
        var f = falls[j];
        if (!f.match(p)) continue;
        if (f.tg) {                    // осыпание в фигуру: падает (card_fall: ease по y, smile_ease по x) в свою точку, подпрыгивает, к formed лежит
          var tg = f.tg[p.i];
          if (!tg) continue;
          var fdp = Math.min(f.dur, f.fd) * (0.8 + 0.2 * p.u), k2 = (t - f.t0) / fdp;
          if (k2 <= 0) continue;
          if (k2 < 1) { x += (tg[0] - x) * f.ex(k2); y += (tg[1] - y) * f.ease(k2); }
          else {
            var land = f.t0 + fdp, v = f.dur > fdp ? CK.clamp01((t - land) / (f.t0 + f.dur - land)) : 1;
            x = tg[0]; y = tg[1] - f.bounce * Math.abs(Math.sin(2 * Math.PI * v)) * (1 - v);
          }
          fs = CK.lerp(1, f.crumb, sm01(k2));
          continue;
        }
        var fk = CK.clamp01((t - f.t0) / f.dur);
        if (fk <= 0) continue;
        var fe = f.ease(fk);
        y += f.dir * fe * f.drop; x += p.vx * f.spread * fk;
        a = Math.min(a, 1 - f.aease(fk));
      }
      var sz;
      // растёт до size_grow_until пути, держится, сжимается с size_shrink_from к посадке
      if (fsz) sz = q <= 0 ? srcSz : q >= 1 ? 1 : q < gU ? CK.lerp(srcSz, p.pk, sm01(q / gU)) : q < sF ? p.pk : CK.lerp(p.pk, 1, sm01((q - sF) / (1 - sF)));
      else sz = q > 0 && q < 1 ? 1 + (p.pk - 1) * Math.sin(Math.PI * q) : 1;
      if (fs != null) sz = fs;         // осыпание в фигуру ведёт свой размер (крупинка crumb_frac_w)
      return { x: x, y: y, a: a, q: q, size: sz };
    }
    function restHere(rp, t) { return t < rp.leave; }
    var landAt = {};            // строка → моменты посадки её частиц (start + задержка + полёт), по возрастанию
    P.forEach(function (p) { (landAt[p.line] = landAt[p.line] || []).push(o.start + p.d + p.fl); });
    Object.keys(landAt).forEach(function (k) { landAt[k].sort(function (a, b) { return a - b; }); });
    var api = {
      particles: P, sources: o.sources, start: o.start, dur: o.dur, material: mat, consume: consume,
      // доля строки line, что уже на месте в t (0…1): севшие частицы; 1 — строка собрана
      lineDone: function (line, t) {
        var a = landAt[line] || [], n = 0;
        while (n < a.length && a[n] <= t + 1e-6) n++;
        return a.length ? n / a.length : 0;
      },
      // положение частицы i в t (сцена со своим видом материала рисует по нему): {x, y, a, q, size}
      at: function (i, t) { return pos(P[i], t); },
      // остаток в источнике в t: [{x, y, col, src}] (с дрожью rest_wobble); при consume — без ушедших
      restAt: function (t) {
        return rest.filter(function (rp) { return restHere(rp, t); })
                   .map(function (rp) { return { x: rp.x + Math.sin(t * restR + rp.ph) * restA, y: rp.y, col: rp.col, src: rp.src }; });
      },
      // доля источника id, что ещё в нём в t (0…1): не вылетевшие частицы + остаток
      source: function (id, t) {
        var b = bySrc[id], n = 0, j;
        if (!b || !(b.dep.length + b.rest.length)) return 1;
        for (j = 0; j < b.dep.length; j++) if (t <= b.dep[j]) n++;
        for (j = 0; j < b.rest.length; j++) if (restHere(b.rest[j], t)) n++;
        return n / (b.dep.length + b.rest.length);
      },
      render: function (t, ctx) {
        ctx = ctx || o.canvas.getContext('2d');
        var sz = mat.size || 2, buckets = colors.map(function () { return []; });
        rest.forEach(function (p) { if (restHere(p, t)) buckets[p.col].push(p.x + Math.sin(t * restR + p.ph) * restA, p.y, 1, 1); });
        for (var i = 0; i < P.length; i++) { var q = pos(P[i], t); if (q.a > 0.01) buckets[P[i].col].push(q.x, q.y, q.a, q.size); }
        ctx.save();
        buckets.forEach(function (b, ci) {
          ctx.fillStyle = colors[ci];
          for (var j = 0; j < b.length; j += 4) {
            var z = sz * b[j + 3];
            ctx.globalAlpha = b[j + 2];
            if (mat.kind === 'petal') { ctx.beginPath(); ctx.ellipse(b[j], b[j + 1], z * 0.9, z * 0.55, (b[j] + b[j + 1]) % 3, 0, 6.2832); ctx.fill(); }
            else ctx.fillRect(b[j] - z / 2, b[j + 1] - z / 2, z, z);
          }
        });
        if (mat.kind === 'emboss') {          // тиснение: вдавленная частица — тень снизу-справа поверх краски
          ctx.globalAlpha = 0.25; ctx.fillStyle = CK.color(DARK);
          for (var n = 0; n < P.length; n += 3) { var w = pos(P[n], t); if (w.q >= 1) ctx.fillRect(w.x + sz * 0.3, w.y + sz * 0.3, sz * 0.6, sz * 0.6); }
        }
        ctx.restore();
      },
      /* fall(word, t0, dur, motion?) — осыпание вниз (card_fall) или вверх (card_sparks), гаснет по alpha_ease;
         fall(word, t0, dur, {motion?, shape}) — осыпание в фигуру: частицы слова падают и садятся в точки фигуры
         (CardKit.shapePoints, px кадра) и не гаснут; motion.ease — падение по y, x_ease — снос по x, stagger — доля dur,
         на которую разнесены старты (последняя садится ровно в t0 + dur). */
      fall: function (word, t0, dur, mo) {
        var opts = mo && (mo.shape || mo.motion) ? mo : { motion: mo };
        var fm = opts.motion || CK.motion('card_fall'), up = 'rise_frac_h' in fm;
        var match = function (p) { return word == null ? true : p.word === word; };
        dur = dur || fm.dur;
        if (opts.shape) {
          // по источникам: крупинки каждого предмета — в свои части фигуры (from), внутри — слева направо
          var tg = {}, groups = {};
          P.filter(match).forEach(function (p) { (groups[p.src] = groups[p.src] || []).push(p); });
          Object.keys(groups).sort().forEach(function (src) {
            var mine = groups[src].sort(function (a, b) { return a.tx - b.tx || a.ty - b.ty; });
            var pts = CK.shapePoints(opts.shape, mine.length, (o.seed || 'particles') + '|' + word + '|' + src, src)
                        .sort(function (a, b) { return a.x - b.x || a.y - b.y; });
            mine.forEach(function (p, j) { tg[p.i] = [pts[j].x, pts[j].y, pts[j].part]; });
          });
          falls.push({ match: match, t0: t0, dur: dur, tg: tg, shape: opts.shape, word: word, fd: fm.dur || dur,
                       ease: CK.ease(fm.ease), ex: CK.ease(fm.smile_ease || fm.x_ease || 'power1.inOut'),
                       bounce: (fm.settle_bounce_frac_w || 0) * W, crumb: fm.crumb_frac_w ? fm.crumb_frac_w * W / msz : 1 });
          return api;
        }
        falls.push({ match: match, t0: t0, dur: dur,
                     ease: CK.ease(fm.ease), aease: CK.ease(fm.alpha_ease), dir: up ? -1 : 1,
                     drop: (up ? fm.rise_frac_h : fm.drop_frac_h) * H, spread: (fm.spread_frac_w || 0) * W });
        return api;
      },
      state: function (t) {
        var landed = 0, gone = 0, n = P.length, stride = Math.max(1, Math.floor(n / 160)), origins = [], now = [];
        for (var i = 0; i < n; i++) {
          var q = pos(P[i], t);
          if (q.q >= 1) landed++;
          if (q.a <= 0.01) gone++;
          if (i % stride === 0) { origins.push([Math.round(P[i].sx * 10) / 10, Math.round(P[i].sy * 10) / 10]); now.push([Math.round(q.x * 10) / 10, Math.round(q.y * 10) / 10]); }
        }
        var rs = [], here = rest.filter(function (rp) { return restHere(rp, t); }), rstep = Math.max(1, Math.floor(here.length / 60));
        for (var k2 = 0; k2 < here.length; k2 += rstep) {
          var rp = here[k2];
          rs.push([Math.round(rp.x * 10) / 10, Math.round(rp.y * 10) / 10, Math.round((rp.x + Math.sin(t * restR + rp.ph) * restA) * 10) / 10, rp.y]);
        }
        var left = {};
        o.sources.forEach(function (s) { left[s.id] = Math.round(api.source(s.id, t) * 1000) / 1000; });
        var shapes = falls.filter(function (f) { return f.tg; }).map(function (f) {
          var ids = Object.keys(f.tg), st2 = Math.max(1, Math.floor(ids.length / 240)), pts = [], done = 0;
          var tf = f.t0 + f.dur, fpts = [], off = 0;
          ids.forEach(function (id, j) {
            var p = P[+id], q2 = pos(p, t), q3 = pos(p, tf);
            if (t >= tf - 1e-6) done++;
            if (Math.hypot(q3.x - f.tg[id][0], q3.y - f.tg[id][1]) > 0.006 * W) off++;
            if (j % st2 === 0) { pts.push([Math.round(q2.x * 10) / 10, Math.round(q2.y * 10) / 10]); fpts.push([Math.round(q3.x * 10) / 10, Math.round(q3.y * 10) / 10]); }
          });
          return { word: f.word, t0: f.t0, dur: f.dur, kind: f.shape.kind, n: ids.length,
                   landed: ids.length ? Math.round(done / ids.length * 1000) / 1000 : 0, now: pts,
                   formed: { t: Math.round(tf * 10000) / 10000, now: fpts, outside: off } };
        });
        // частицы в полёте: [x, y, размер px, начало x, y, цель x, y] — px сцены, выборка до 200
        var fl = [], inF = P.filter(function (p) { var q = (t - o.start - p.d) / p.fl; return q > 0 && q < 1; }), fst = Math.max(1, Math.floor(inF.length / 200));
        for (var k3 = 0; k3 < inF.length; k3 += fst) {
          var pp = inF[k3], qq = pos(pp, t), r1 = function (v) { return Math.round(v * 10) / 10; };
          fl.push([r1(qq.x), r1(qq.y), r1(qq.size * msz), r1(pp.sx), r1(pp.sy), r1(pp.tx), r1(pp.ty), Math.round(qq.a * 100) / 100]);
        }
        return { n: n, landed: n ? landed / n : 0, gone: n ? gone / n : 0, origins: origins, now: now, rest: rs, consume: consume,
                 source_left: left, shapes: shapes, flight: fl, in_flight: inF.length };
      }
    };
    return api;
  };

  /* Штриховая запись (материалы stem, wire-light): контур слова идёт слева направо из точки-источника (стебель от листа,
     провод от гирлянды), заливка следом; отдаёт тот же интерфейс, что particleText. */
  CK.strokeText = function (o) {
    var S = size(), m = o.motion, mat = o.material || {}, lines = o.lines, ease = CK.ease(m.ease);
    // контур и заливка: stem — contour_until / fill_from; wire-light — свет идёт за кончиком провода на wire_lead
    var fillEase = CK.ease(m.fill_ease || 'none');
    var contourUntil = m.contour_until != null ? m.contour_until : 1 - m.wire_lead;
    var fillFrom = m.fill_from != null ? m.fill_from : m.wire_lead, r = CK.rng(o.seed || 'stroke');
    var lw = (m.stroke_frac_w != null ? m.stroke_frac_w : m.wire_frac_w) * S.W, falls = [];
    var L = lines.map(function (ln, i) {
      var s = pickSource(o.sources, r), lag = m.key_lag * (ln.key ? 1 : 0) + i * m.line_lag;
      return { ln: ln, src: s, lag: Math.min(lag, m.max_lag) };
    });
    function prog(l, t) { var span = o.dur * (1 - l.lag); return CK.clamp01((t - o.start - o.dur * l.lag) / span); }
    // осыпание слова строки: [{x0, x1, dy, a}] — отрезки строки по x; слово уходит вниз (card_fall) или вверх (card_sparks)
    function segments(l, t) {
      var ln = l.ln, segs = [{ x0: -1e9, x1: 1e9, dy: 0, a: 1 }];
      falls.forEach(function (f) {
        var i = f.word ? ln.text.indexOf(f.word) : 0;
        if (i < 0) return;
        var fk = CK.clamp01((t - f.t0) / f.dur);
        if (fk <= 0) return;
        var wx0 = f.word ? ln.left + measure(ln.font, ln.text.slice(0, i)) : -1e9;
        var wx1 = f.word ? wx0 + measure(ln.font, f.word) : 1e9, out = [];
        segs.forEach(function (sg) {
          if (sg.x1 <= wx0 || sg.x0 >= wx1) { out.push(sg); return; }
          if (sg.x0 < wx0) out.push({ x0: sg.x0, x1: wx0, dy: sg.dy, a: sg.a });
          out.push({ x0: Math.max(sg.x0, wx0), x1: Math.min(sg.x1, wx1), dy: sg.dy + f.dir * f.ease(fk) * f.drop,
                     a: Math.min(sg.a, 1 - f.aease(fk)) });
          if (sg.x1 > wx1) out.push({ x0: wx1, x1: sg.x1, dy: sg.dy, a: sg.a });
        });
        segs = out;
      });
      return segs;
    }
    var api = {
      sources: o.sources, start: o.start, dur: o.dur, material: mat,
      // доля записи строки line в t (0…1); 1 — строка написана и залита
      lineDone: function (line, t) { return L[line] ? prog(L[line], t) : 0; },
      render: function (t, ctx) {
        ctx = ctx || o.canvas.getContext('2d');
        L.forEach(function (l) {
          var p = prog(l, t);
          if (p <= 0) return;
          var ln = l.ln, cp = ease(CK.clamp01(p / contourUntil)), fp = fillEase(CK.clamp01((p - fillFrom) / (1 - fillFrom)));
          var x0 = ln.left - lw * 4, x1 = ln.left + ln.width + lw * 4, xc = CK.lerp(x0, x1, cp);
          segments(l, t).forEach(function (sg) {
          var a = sg.a;
          if (a <= 0.01) return;
          ctx.save(); ctx.beginPath(); ctx.rect(Math.max(sg.x0, -1e5), -1e5, Math.min(sg.x1, 1e5) - Math.max(sg.x0, -1e5), 2e5); ctx.clip();
          ctx.translate(0, sg.dy);
          ctx.save(); ctx.globalAlpha = a;
          ctx.font = ln.font; ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
          // ведущая линия: от источника к кончику записи
          if (cp < 1) {
            ctx.strokeStyle = mat.lead || mat.outline || mat.ink; ctx.lineWidth = lw * 1.4; ctx.lineCap = 'round';
            ctx.beginPath(); ctx.moveTo(l.src.x, l.src.y);
            ctx.quadraticCurveTo((l.src.x + xc) / 2, Math.max(l.src.y, ln.y) + ln.size * 0.5, xc, ln.y - ln.size * 0.3); ctx.stroke();
          }
          ctx.save(); ctx.beginPath(); ctx.rect(x0, ln.y - ln.size * 1.4, xc - x0, ln.size * 2); ctx.clip();
          ctx.lineWidth = lw * 2; ctx.strokeStyle = mat.outline || mat.ink; ctx.lineJoin = 'round';
          ctx.strokeText(ln.text, ln.left, ln.y);
          ctx.restore();
          if (fp > 0) {
            if (mat.glow) { ctx.shadowColor = mat.glow; ctx.shadowBlur = ln.size * 0.25 * fp; }
            ctx.globalAlpha = a * fp; ctx.fillStyle = mat.ink; ctx.fillText(ln.text, ln.left, ln.y);
            ctx.shadowBlur = 0; ctx.globalAlpha = a;
            if (mat.outline) { ctx.lineWidth = lw; ctx.strokeStyle = mat.outline; ctx.strokeText(ln.text, ln.left, ln.y); }
          }
          ctx.restore();
          ctx.restore();
          });
        });
      },
      fall: function (word, t0, dur, mo) {
        if (mo && mo.shape) throw new Error('CardKit.strokeText: осыпание в фигуру — только у particleText (крупинки), у штриха его нет');
        var fm = (mo && mo.motion) || mo || CK.motion('card_fall'), up = 'rise_frac_h' in fm;
        falls.push({ word: word, t0: t0, dur: dur || fm.dur, ease: CK.ease(fm.ease), aease: CK.ease(fm.alpha_ease),
                     dir: up ? -1 : 1, drop: (up ? fm.rise_frac_h : fm.drop_frac_h) * S.H });
        return api;
      },
      // доля источника id, что ещё в нём в t: штрих вытягивается из предмета — 1 − доля записанного контура его строк
      source: function (id, t) {
        var mine = L.filter(function (l) { return l.src.src === id; });
        if (!mine.length) mine = L;            // предмет без своей строки уходит вместе со всей записью
        return mine.reduce(function (s, l) { return s + (1 - CK.clamp01(prog(l, t) / contourUntil)); }, 0) / mine.length;
      },
      at: function () { throw new Error('CardKit.strokeText: частиц нет — положение отдаёт только particleText'); },
      restAt: function () { return []; },
      consume: true,
      state: function (t) {
        var done = 0, left = {};
        L.forEach(function (l) { if (prog(l, t) >= 1) done++; });
        o.sources.forEach(function (s) { left[s.id] = Math.round(api.source(s.id, t) * 1000) / 1000; });
        return { n: L.length, landed: L.length ? done / L.length : 0, gone: 0,
                 origins: L.map(function (l) { return [Math.round(l.src.x * 10) / 10, Math.round(l.src.y * 10) / 10]; }), now: [],
                 consume: true, source_left: left, shapes: [] };
      }
    };
    return api;
  };

  // ------------------------------------------------------------------ letterWindows
  CK.letterWindows = function (o) {
    var S = size(), m = o.motion || CK.motion('card_windows'), ease = CK.ease(m.ease);
    var word = o.word || o.text, font = o.font, left = leftOf(o.text, font, o.x, o.align || 'center');
    var i = o.text.indexOf(word);
    if (i < 0) throw new Error('CardKit.letterWindows: слова «' + word + '» нет в строке «' + o.text + '»');
    var wx = left + measure(font, o.text.slice(0, i)), sz = fontPx(font);
    var api = {
      word: word, x: wx, y: o.y, font: font, size: sz,
      rect: [wx, o.y - sz * 0.8, measure(font, word), sz],
      open: function (t) { return ease(CK.clamp01((t - o.open[0]) / Math.max(1e-6, o.open[1] - o.open[0]))); },
      // прорези на верхнем слое: буквы вырезаются (destination-out), по краю — светлая кромка
      cut: function (t, ctx) {
        var k = api.open(t);
        if (k <= 0) return k;
        ctx = ctx || o.canvas.getContext('2d');
        ctx.save(); ctx.font = font; ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
        ctx.globalCompositeOperation = 'destination-out'; ctx.globalAlpha = k; ctx.fillStyle = '#000';
        ctx.fillText(word, wx, o.y);
        ctx.globalCompositeOperation = 'source-over'; ctx.globalAlpha = k * m.edge_opacity;
        ctx.strokeStyle = CK.color(m.edge_color); ctx.lineWidth = m.edge_frac_w * S.W; ctx.lineJoin = 'round';
        ctx.strokeText(word, wx, o.y);
        ctx.restore();
        return k;
      },
      // тень верхнего слоя внутрь прорезей: цвет и числа card_windows, сила — по раскрытию
      shadow: function (t) {
        var k = api.open(t);
        return { color: m.shadow_color, alpha: m.shadow_alpha * k, dy: m.shadow_dy_frac_w * S.W, blur: m.shadow_blur_frac_w * S.W, open: k,
                 edge: { color: m.edge_color, alpha: m.edge_opacity * k, width: m.edge_frac_w * S.W } };
      }
    };
    return api;
  };

  // ------------------------------------------------------------------ strokePivot
  /* Точка нырка: середина первого штриха буквы charIndex строки text по горизонтали на высоте база − 0,24 кегля
     . Возвращает и то, по чему проверка (V40) сама найдёт штрих: начало буквы, базовую линию, кегль;
     r_in — радиус круга с центром в точке нырка, целиком лежащего в штрихе (px): по нему нырок считает, когда окно
     буквы накрывает кадр. */
  CK.strokePivot = function (text, font, x, y, charIndex, align) {
    var sz = fontPx(font), left = leftOf(text, font, x, align || 'center');
    var cx = left + measure(font, text.slice(0, charIndex)), cw = measure(font, text.charAt(charIndex));
    var pad = Math.ceil(sz * 0.3), w = Math.ceil(cw + 2 * pad), h = Math.ceil(sz * 1.6);
    var cv = document.createElement('canvas'); cv.width = w; cv.height = h;
    var c = cv.getContext('2d', { willReadFrequently: true });
    c.font = font; c.textAlign = 'left'; c.textBaseline = 'alphabetic'; c.fillStyle = '#000';
    var bx = pad, by = Math.round(sz * 1.2);
    c.fillText(text.charAt(charIndex), bx, by);
    var row = Math.round(by - sz * 0.24), d = c.getImageData(0, row, w, 1).data, a = -1, b = -1;
    for (var i = 0; i < w; i++) { var on = d[i * 4 + 3] > 140; if (on && a < 0) a = i; if (!on && a >= 0) { b = i; break; } }
    if (a < 0) throw new Error('CardKit.strokePivot: у буквы «' + text.charAt(charIndex) + '» нет штриха на высоте база − 0,24 кегля');
    if (b < 0) b = w;
    var px = (a + b) / 2, all = c.getImageData(0, 0, w, h).data, rin = 1e9;
    for (var yy = 0; yy < h; yy++) for (var xx = 0; xx < w; xx++) {
      if (all[(yy * w + xx) * 4 + 3] > 140) continue;
      var dd = Math.hypot(xx + 0.5 - px, yy + 0.5 - (row + 0.5));
      if (dd < rin) rin = dd;
    }
    return { x: cx + px - bx, y: y - (by - row), charX: cx, baseline: y, size: sz, ch: text.charAt(charIndex), r_in: Math.max(0, rin - 0.5) };
  };

  // ------------------------------------------------------------------ dive
  /* upper — холст верхнего слоя (с прорезями), lower — fn(ctx, t) нижнего слоя (кадр входа следующей сцены).
     Нырок насквозь — motion.mode = 'through' или o.through (метка: fade 'none' / through): верх не гаснет; масштаб верха
     растёт по логарифму (ровная скорость приближения): кривая log_keys [[доля времени до накрытия, доля пути масштаба], …]
     (монотонный кубический сплайн), иначе — подлёт approach с approach_log пути по approach_ease, на входе в штрих остаётся
     keep_speed скорости, затем разгон through_power. К накрытию (o.fillAt — доля длины, метка cover_by; иначе motion.fill_at)
     окно буквы (круг o.hole px вокруг точки нырка) накрывает кадр с запасом fill_margin и дальше растёт; точка штриха уходит
     к центру кадра на долю center по center_ease. Низ lower_from → 1 по lower_ease к накрытию, без сдвига: последний кадр
     нырка — кадр входа следующей сцены в масштабе 1.
     Иначе (старый режим) — верх 1 → scale_to по ease, гаснет линейно с fade_from; низ lower_from → 1. */
  function monoSpline(keys) {        // [[x, y]] по возрастанию x → f(x), монотонная (Fritsch–Carlson); вне ключей — по крайнему наклону
    var n = keys.length, xs = keys.map(function (k) { return k[0]; }), ys = keys.map(function (k) { return k[1]; }), d = [], mm = [], i;
    for (i = 0; i < n - 1; i++) d.push((ys[i + 1] - ys[i]) / (xs[i + 1] - xs[i]));
    mm.push(d[0]);
    for (i = 1; i < n - 1; i++) mm.push(d[i - 1] * d[i] <= 0 ? 0 : (d[i - 1] + d[i]) / 2);
    mm.push(d[n - 2]);
    for (i = 0; i < n - 1; i++) {
      if (!d[i]) { mm[i] = mm[i + 1] = 0; continue; }
      var a = mm[i] / d[i], b = mm[i + 1] / d[i], h = a * a + b * b;
      if (h > 9) { var tt = 3 / Math.sqrt(h); mm[i] = tt * a * d[i]; mm[i + 1] = tt * b * d[i]; }
    }
    return function (x) {
      if (x <= xs[0]) return ys[0] + mm[0] * (x - xs[0]);
      if (x >= xs[n - 1]) return ys[n - 1] + mm[n - 1] * (x - xs[n - 1]);
      var k = 0;
      while (x > xs[k + 1]) k++;
      var hh = xs[k + 1] - xs[k], t = (x - xs[k]) / hh, t2 = t * t, t3 = t2 * t;
      return (2 * t3 - 3 * t2 + 1) * ys[k] + (t3 - 2 * t2 + t) * hh * mm[k] + (-2 * t3 + 3 * t2) * ys[k + 1] + (t3 - t2) * hh * mm[k + 1];
    };
  }
  CK.dive = function (o) {
    var m = o.motion || CK.motion('card_dive'), through = !!(o.through || m.mode === 'through' || m.log_keys), lo = CK.ease(m.lower_ease);
    if (through && !(o.hole > 0)) throw new Error('CardKit.dive: нырку насквозь нужен o.hole — радиус окна в штрихе (strokePivot r_in)');
    var pf = o.fillAt != null ? o.fillAt : (m.cover_by != null ? m.cover_by : m.fill_at);
    if (through && !(pf > 0 && pf <= 1)) throw new Error('CardKit.dive: нет доли накрытия (cover_by метки или card_dive.fill_at)');
    var up = through ? null : CK.ease(m.ease), fe = through ? null : CK.ease(m.fade_ease);
    var ae = through && m.approach_ease ? CK.ease(m.approach_ease) : null;
    var pc = m.pivot_to_center || null, sf = m.shadow_fade || null;     // [от, до] — доли длины нырка (smoothstep)
    var keys = through && m.log_keys ? monoSpline(m.log_keys) : null;
    function pivotAt(t) { return typeof o.pivot === 'function' ? o.pivot(t) : o.pivot; }
    // доля пути масштаба (в логарифме): 0 в начале, 1 в накрытии, дальше растёт
    function path(p) {
      if (keys) return keys(p);         // log_keys: [доля длины, доля пути масштаба]; 1 — в накрытии
      var x = p / pf;
      var pa = m.approach * pf, la = m.approach_log, w = m.keep_speed;
      var es = p <= pa ? la * ae(p / pa) : la + (1 - la) * Math.pow((p - pa) / (pf - pa), m.through_power);
      return w * x + (1 - w) * es;
    }
    function farOf(P) {
      var S = size();
      return Math.max(Math.hypot(P.x, P.y), Math.hypot(S.W - P.x, P.y), Math.hypot(P.x, S.H - P.y), Math.hypot(S.W - P.x, S.H - P.y));
    }
    // точка штриха на экране: от своего места к центру кадра (доля center к накрытию)
    function screenPivot(P, p) {
      var S = size(), k = pc ? sm01((p - pc[0]) / Math.max(1e-6, pc[1] - pc[0])) : 0;
      return { x: P.x + (S.W / 2 - P.x) * k, y: P.y + (S.H / 2 - P.y) * k };
    }
    var api = {
      pivot: o.pivot, t0: o.t0, dur: o.dur, through: through, hole: o.hole || null, fillAt: through ? pf : null,
      at: function (t) {
        var p = CK.clamp01((t - o.t0) / o.dur), P = pivotAt(t);
        if (through) {
          var Ps = screenPivot(P, p), Pe = screenPivot(P, pf), sEnd = farOf(Pe) / o.hole * m.fill_margin, sc = Math.exp(Math.log(sEnd) * path(p));
          // окно зума низа — card_dive.lower_window [от, до] (доли длины нырка); без ключа — [0, накрытие]
          var lw = m.lower_window || [0, pf], lk = CK.clamp01((p - lw[0]) / Math.max(1e-6, lw[1] - lw[0]));
          return { p: p, active: t >= o.t0, upperScale: sc, upperAlpha: 1, lowerScale: m.lower_from + (1 - m.lower_from) * lo(lk),
                   fill: sc * o.hole / farOf(Ps), P: P, Ps: Ps,
                   // тень верха (в пространстве нижнего слоя) гаснет по shadow_fade
                   shadowK: sf ? 1 - sm01((p - sf[0]) / Math.max(1e-6, sf[1] - sf[0])) : 1 };
        }
        var f = CK.clamp01((p - m.fade_from) / (1 - m.fade_from));
        return { p: p, active: t >= o.t0, upperScale: 1 + (m.scale_to - 1) * up(p), upperAlpha: 1 - fe(f),
                 lowerScale: m.lower_from + (1 - m.lower_from) * lo(p), fill: null, P: P, Ps: P, shadowK: 1 };
      },
      // нижний слой в масштабе нырка вокруг точки нырка (без сдвига: в накрытии — кадр входа как есть)
      drawLower: function (ctx, t) {
        var s = api.at(t);
        ctx.save(); ctx.translate(s.P.x, s.P.y); ctx.scale(s.lowerScale, s.lowerScale); ctx.translate(-s.P.x, -s.P.y);
        o.lower(ctx, t); ctx.restore();
        return s;
      },
      // преобразование верхнего слоя (вектор: сцена рисует верх прямо в нём — кромка окна не растягивается растром)
      upperTransform: function (ctx, t) {
        var s = api.at(t);
        ctx.translate(s.Ps.x, s.Ps.y); ctx.scale(s.upperScale, s.upperScale); ctx.translate(-s.P.x, -s.P.y);
        return s;
      },
      draw: function (ctx, t, shadow) {
        var s = api.drawLower(ctx, t), S = size();
        if (s.upperAlpha <= 0.001) return s;
        ctx.save(); ctx.globalAlpha = s.upperAlpha;
        ctx.translate(s.Ps.x, s.Ps.y); ctx.scale(s.upperScale, s.upperScale); ctx.translate(-s.P.x, -s.P.y);
        if (shadow && shadow.alpha > 0) { ctx.shadowColor = CK.rgba(shadow.color, shadow.alpha); ctx.shadowBlur = shadow.blur; ctx.shadowOffsetY = shadow.dy; }
        ctx.drawImage(o.upper, 0, 0, S.W, S.H);
        ctx.restore();
        return s;
      }
    };
    return api;
  };

  // ------------------------------------------------------------------ бумажная глубина, дрейф, засветка
  CK.paperDepth = function (el, level) {
    var d = DEPTH[Math.max(1, Math.min(3, level | 0))], W = size().W;
    if (el && typeof el.fillRect === 'function') {        // контекст холста: тень следующей фигуры
      el.shadowColor = CK.rgba(DARK, d.a); el.shadowBlur = d.blur * W; el.shadowOffsetY = d.dy * W; el.shadowOffsetX = 0;
      return el;
    }
    el.style.filter = 'drop-shadow(0px ' + (d.dy * W).toFixed(2) + 'px ' + (d.blur * W).toFixed(2) + 'px ' + CK.rgba(DARK, d.a) + ')';
    return el;
  };
  CK.noShadow = function (ctx) { ctx.shadowColor = 'rgba(0,0,0,0)'; ctx.shadowBlur = 0; ctx.shadowOffsetY = 0; ctx.shadowOffsetX = 0; };
  // точка (x, y) под дрейфом d (CardKit.drift): масштаб от центра кадра и сдвиг dy — как мир сцены под камерой
  CK.driftPoint = function (d, x, y) { var S = size(); return { x: (x - S.W / 2) * d.scale + S.W / 2, y: (y - S.H / 2) * d.scale + S.H / 2 + d.dy }; };
  CK.applyDrift = function (ctx, d) { var S = size(); ctx.translate(S.W / 2, S.H / 2 + d.dy); ctx.scale(d.scale, d.scale); ctx.translate(-S.W / 2, -S.H / 2); };
  CK.drift = function (t, t0, t1, m) {
    var p = CK.clamp01((t - t0) / Math.max(1e-6, t1 - t0)), k = Math.pow(Math.sin(Math.PI * p), 2);   // hann: 0 в швах
    return { k: k, scale: 1 + m.drift_scale_pct / 100 * k, dy: -m.drift_pan_pct_h / 100 * size().H * k };
  };
  CK.bloom = function (t, t0, t1, m) {
    var p = CK.clamp01((t - t0) / Math.max(1e-6, t1 - t0)), pk = m.peak, w;
    if (p <= 0 || p >= 1) return 0;
    w = p < pk ? 0.5 - 0.5 * Math.cos(Math.PI * p / pk) : 0.5 + 0.5 * Math.cos(Math.PI * (p - pk) / (1 - pk));
    return m.max_mix * w;
  };

  // ------------------------------------------------------------------ кадры входа
  CK.entry = function (scene, fn) {
    if (fn === undefined) {
      var f = REG.entries[scene];
      if (!f) throw new Error('CardKit.entry: сцена «' + scene + '» не зарегистрировала кадр входа (CardKit.entry в её markup.html)');
      return f;
    }
    if (typeof fn !== 'function') throw new Error('CardKit.entry(' + scene + '): нужна функция (ctx, t)');
    REG.entries[scene] = fn;
    return fn;
  };

  // ------------------------------------------------------------------ промер
  // точки живых предметов, нарисованные в кадре t (L.track): {сцена: {id: {x, y, angle?, alpha?}}} — промер живости 
  CK.tracks = function (t) {
    var out = {}, fps = (window.__FILM__ || {}).fps || 30;
    Object.keys(REG.tracks).forEach(function (sc) {
      Object.keys(REG.tracks[sc]).forEach(function (id) {
        var v = REG.tracks[sc][id];
        if (Math.abs(v.t - t) < 0.5 / fps) (out[sc] = out[sc] || {})[id] = { x: v.x, y: v.y, angle: v.angle, alpha: v.alpha };
      });
    });
    return out;
  };
  CK.state = function (t) {
    var out = [];
    REG.probes.forEach(function (p) { out = out.concat(p(t) || []); });
    return out;
  };
  (window.StagePlugins = window.StagePlugins || []).push(function () {
    return { render: function () {}, probe: function (t) { return { plugin: 'cardkit', items: CK.state(t) }; } };
  });

  // ------------------------------------------------------------------ слой сцены
  var scratch = {};
  function canvasOf(name) {
    var S = size();
    if (!scratch[name]) { var c = document.createElement('canvas'); c.width = S.W; c.height = S.H; scratch[name] = c; }
    return scratch[name];
  }
  CK.scratch = canvasOf;

  /* CardKit.layer({scene, canvas, world(ctx, t, L), over?(ctx, t, L), compose?(ctx, t, L), sources?: {id: {shape, bow}},
     materials?: {<material>: {...}}}) — фраза сцены из её меток act:
       gather (lines, material, order) → particleText (точки — sampleText, источники — рамки objects метки live) или strokeText;
       fall (word, motion) → осыпание; windows (word, reveals) → letterWindows; dive (word, char, line, into) → strokePivot + dive.
     Исполнители меток act (V31): каждый who сцены получает узел-отпечаток <i data-s> внутри холста сцены.
     L.drawUpper(ctx, t) — сцена без своего перехода (это и есть её кадр входа: CardKit.entry(scene, L.drawUpper)). */
  CK.layer = function (o) {
    var L = { scene: o.scene, canvas: o.canvas, built: false, phr: null, win: null, dv: null, extras: {} };
    var sc = null, cues = [], byId = {}, liveCue = null, nextScene = null;
    function sceneRec() {
      if (sc) return sc;
      var F = film();
      F.scenes.forEach(function (s, i) { if (s.id === o.scene) { sc = s; nextScene = F.scenes[i + 1] ? F.scenes[i + 1].id : null; } });
      if (!sc) throw new Error('CardKit.layer: сцены ' + o.scene + ' нет в фильме');
      cues = ((sc.plugins || {}).act || {}).cues || [];
      cues.forEach(function (q) { byId[q.id] = q; if (q.do === 'live') liveCue = q; });
      return sc;
    }
    L.cues = function (filter) { sceneRec(); return cues.filter(function (q) { return !filter || Object.keys(filter).every(function (k) { return q[k] === filter[k]; }); }); };
    L.cue = function (filter) { return L.cues(filter)[0] || null; };
    L.box = function (id) {
      sceneRec();
      var ob = ((liveCue || {}).objects || []).filter(function (x) { return x.id === id; })[0], S = size();
      if (!ob) throw new Error('CardKit.layer ' + o.scene + ': предмета «' + id + '» нет в objects метки live');
      return { id: id, x: ob.box[0] * S.W, y: ob.box[1] * S.H, w: ob.box[2] * S.W, h: ob.box[3] * S.H, spout: ob.spout || null };
    };
    L.until = function (q) { return q.until != null ? q.until : q.t + (q.span || 0); };
    L.span = function () { sceneRec(); return [sc.start, sc.end]; };
    // камера сцены: дрейф card_live (hann по длине сцены, 0 в швах); depth — слой параллакса (0…2, parallax[depth])
    L.drift = function (t, depth) {
      var m = CK.motion('card_live'), sp = L.span(), d = CK.drift(t, sp[0], sp[1], m);
      var k = depth == null ? 1 : m.parallax[depth];
      return { k: d.k, scale: 1 + (d.scale - 1) * k, dy: d.dy * k };
    };
    L.camera = function (ctx, t, depth) { CK.applyDrift(ctx, L.drift(t, depth)); return ctx; };
    L.toScreen = function (x, y, t) { return CK.driftPoint(L.drift(t), x, y); };
    /* фигура осыпания из метки fall раскадровки (to) → px: {shape: 'smiley', center: [x, y] — доли кадра, diameter_frac_w,
       ring: {from, line_frac_w: [от, до]}, eyes: {from, at_r: [[dx, dy], …], size_r: [от, до]}, smile: {from, through_r: [[dx, dy] × 3],
       line_frac_w: [от, до]}} (_r — в радиусах от центра, y вниз; size_r — диаметр глаза) или {shape: 'points', points: [[x, y]] — доли
       кадра, spread_frac_w?}. Шаг крупинки (cell) — размер частицы фразы. */
    L.shape = function (q) {
      var S = size(), kind = q.shape || q.kind, fm0 = ((film().motion || {}).act || {}).card_fall || {};
      var cell = fm0.crumb_frac_w ? fm0.crumb_frac_w * S.W : (L.phr && L.phr.material ? (L.phr.material.size || 4) * 1.15 : 4);
      if (kind === 'points') return { kind: 'points', spread: (q.spread_frac_w || 0) * S.W, points: q.points.map(function (p) { return { x: p[0] * S.W, y: p[1] * S.H }; }) };
      if (kind !== 'smiley') throw new Error('CardKit.layer ' + o.scene + ': фигуры осыпания «' + kind + '» нет (smiley | points)');
      if (!q.center || !q.diameter_frac_w) throw new Error('CardKit.layer ' + o.scene + ': у смайлика нет center или diameter_frac_w');
      var R = q.diameter_frac_w * S.W / 2, W2 = function (a) { return [a[0] * S.W, a[1] * S.W]; }, Rs = function (p) { return [p[0] * R, p[1] * R]; };
      return { kind: 'smiley', x: q.center[0] * S.W, y: q.center[1] * S.H, r: R, cell: cell,
               ring: q.ring ? { from: q.ring.from, line: W2(q.ring.line_frac_w) } : null,
               eyes: q.eyes ? { from: q.eyes.from, at: q.eyes.at_r.map(Rs), size: [q.eyes.size_r[0] * R, q.eyes.size_r[1] * R] } : null,
               smile: q.smile ? { from: q.smile.from, through: q.smile.through_r.map(Rs), line: W2(q.smile.line_frac_w) } : null };
    };
    /* L.track(id, {x, y, angle?, alpha?, space?, depth?}) — точка живого предмета (live.track) в кадре, который сейчас рисуется:
       px кадра после дрейфа; space: 'scene' — px сцены, card-kit сам переводит дрейфом камеры (depth — слой параллакса 0…2). */
    L.track = function (id, v) {
      var t = L.curT, x = v.x, y = v.y;
      if (t == null) return;
      if (v.space === 'scene') { var q = CK.driftPoint(L.drift(t, v.depth), x, y); x = q.x; y = q.y; }
      (REG.tracks[o.scene] = REG.tracks[o.scene] || {})[id] = { t: t, x: Math.round(x * 10) / 10, y: Math.round(y * 10) / 10,
        angle: v.angle != null ? Math.round(v.angle * 1000) / 1000 : undefined, alpha: v.alpha != null ? Math.round(v.alpha * 1000) / 1000 : undefined };
    };
    /* L.source(id, t) — состояние предмета-источника фразы по sources_act метки gather:
         {act 0…1 — доля всего действия [t, until], lift px, tilt_deg, scale — подъём к emit_from и возврат после spent (smoothstep),
          emit 0…1 — доля окна вылета [emit_from, spent], spent 0…1 — сколько ушло (1 − left), back 0…1 — возврат [spent, until],
          left 0…1 — доля материала в предмете}; просыпь из with[] уходит первой — за spill_share окна вылета.
       Предмет без действия — {act 0, lift 0, tilt_deg 0, scale 1, emit 0, spent 1 − left, back 0, left}. */
    function smooth(a, b, t) { if (!(b > a)) return t >= b ? 1 : 0; var x = CK.clamp01((t - a) / (b - a)); return x * x * (3 - 2 * x); }
    L.source = function (id, t) {
      ensure();
      var g = L.cue({ do: 'gather' }), acts = (g && g.sources_act) || [], a = acts.filter(function (x) { return x.id === id; })[0];
      var parent = acts.filter(function (x) { return (x.with || []).indexOf(id) >= 0; })[0], S = size();
      if (!a && parent) {          // просыпь: уходит в начале окна вылета своего предмета
        var share = (g.m && g.m.spill_share) || 0.3, e = smooth(parent.emit_from, parent.emit_from + (parent.spent - parent.emit_from) * share, t);
        return { act: smooth(parent.t, parent.until, t), lift: 0, tilt_deg: 0, scale: 1, emit: e, spent: e, back: 0, left: 1 - e };
      }
      var left = L.phr && L.phr.source ? L.phr.source(id, t) : 1;
      if (!a) return { act: 0, lift: 0, tilt_deg: 0, scale: 1, emit: 0, spent: 1 - left, back: 0, left: left };
      var up = smooth(a.t, a.emit_from, t), back = smooth(a.spent, a.until, t), k = up * (1 - back);
      return { act: CK.clamp01((t - a.t) / Math.max(1e-6, a.until - a.t)), lift: k * (a.lift_frac_w || 0) * S.W, tilt_deg: k * (a.tilt_deg || 0),
               scale: 1 + k * ((a.scale || 1) - 1), emit: CK.clamp01((t - a.emit_from) / Math.max(1e-6, a.spent - a.emit_from)),
               spent: 1 - left, back: back, left: left };
    };
    function lineSpec(ln, idx) {
      var S = size(), px = ln.size_frac_w * S.W, font = CK.font(ln.role, px);
      var left = leftOf(ln.text, font, ln.x * S.W, ln.align || 'center'), width = measure(font, ln.text);
      // рамка плотно по буквам (px сцены, до камеры): метрики строки в её шрифте — для областей текста V37
      var c = mctx(); c.font = font; c.textAlign = 'left'; c.textBaseline = 'alphabetic';
      var mt = c.measureText(ln.text), bl = mt.actualBoundingBoxLeft || 0, br = mt.actualBoundingBoxRight || width;
      var up = mt.actualBoundingBoxAscent || px * 0.8, down = mt.actualBoundingBoxDescent || px * 0.2;
      return { text: ln.text, role: ln.role, font: font, size: px, x: ln.x * S.W, y: ln.y * S.H, align: ln.align || 'center',
               key: ln.key || null, idx: idx, ink: ln.ink, outline: ln.outline, glow: ln.glow, edge: ln.edge,
               left: left, width: width, source: ln.source, tight: [left - bl, ln.y * S.H - up, bl + br, up + down] };
    }
    function inks(ink) { return (Array.isArray(ink) ? ink : [ink]).map(function (r) { return CK.color(r); }); }
    function build() {
      sceneRec();
      var S = size(), g = L.cue({ do: 'gather' });
      var ready = true;
      L.lines = g ? g.lines.map(lineSpec) : [];
      L.lines.forEach(function (ln) { if (!fontReady(ln.font, ln.text)) ready = false; });
      if (g) {
        var names = [];
        L.lines.forEach(function (ln) { (Array.isArray(ln.source) ? ln.source : [ln.source]).forEach(function (n) { if (names.indexOf(n) < 0) names.push(n); }); });
        // действия источников метки gather (sources_act): окно вылета [emit_from, spent], излив spout [x, y] (доли кадра)
        var acts = {};
        (g.sources_act || []).forEach(function (a) { acts[a.id] = a; });
        var srcs = names.map(function (n) {
          var b = L.box(n), sh = (o.sources || {})[n] || {}, a = acts[n] || {}, sp = sh.spout || a.spout || b.spout;
          b.shape = sh.shape || 'rect'; b.bow = sh.bow;
          // излив: [x, y] или {at: [x, y], dir_deg} — из sources[id] разметки, sources_act или objects[] раскадровки;
          // без dir_deg струя смотрит на середину своих букв
          if (sp) {
            var at = Array.isArray(sp) ? sp : sp.at, dir = Array.isArray(sp) ? (a.spout_dir_deg != null ? a.spout_dir_deg : null) : sp.dir_deg;
            b.spout = { x: at[0] * S.W, y: at[1] * S.H, dir_deg: dir == null ? null : dir, jitter: (g.m.spout_jitter_frac_w || 0) * S.W };
          } else b.spout = null;
          b.emit = typeof a.emit_from === 'number' && typeof a.spent === 'number' ? [a.emit_from, a.spent] : null;
          return b;
        });
        var matSpec = (o.materials || {})[g.material] || {};
        // расход: spend 'all' метки gather (или consume в метке, её числах, материале разметки)
        var consume = !!(g.spend === 'all' || g.consume || g.m.consume || matSpec.consume);
        var start = g.t, dur = L.until(g) - g.t;
        if (matSpec.kind === 'stroke') {
          var ln0 = L.lines.map(function (ln) {
            var c = inks(ln.ink);
            return { text: ln.text, font: ln.font, size: ln.size, y: ln.y, left: ln.left, width: ln.width, key: !!ln.key, word: ln.key };
          });
          var ink = inks(L.lines[0].ink)[0];
          L.phr = CK.strokeText({ canvas: o.canvas, lines: ln0, sources: srcs, start: start, dur: dur, motion: g.m, seed: o.scene + '|' + g.id, consume: consume,
            material: { kind: 'stroke', ink: ink, outline: L.lines[0].outline ? CK.color(L.lines[0].outline) : null,
                        glow: L.lines.filter(function (x) { return x.glow; }).map(function (x) { return CK.rgba(x.glow, 0.9); })[0] || null,
                        lead: matSpec.lead ? CK.color(matSpec.lead) : null } });
        } else {
          var targets = [], colorsAll = [], colIdx = {};
          L.lines.forEach(function (ln, li) {
            var step = (ln.role === 'keyword' ? g.m.step_key_frac_w : g.m.step_phrase_frac_w) || (matSpec.step_frac_w || 0.006);
            var pts = CK.sampleText({ text: ln.text, font: ln.font, x: ln.x, y: ln.y, align: ln.align, step: step * S.W, seed: o.scene });
            var ci = inks(ln.ink).map(function (c) { if (colIdx[c] == null) { colIdx[c] = colorsAll.length; colorsAll.push(c); } return colIdx[c]; });
            var kw = ln.key ? ln.text.indexOf(ln.key) : -1, rr = CK.rng(o.scene + '|ink|' + li);
            var own = (Array.isArray(ln.source) ? ln.source : [ln.source]).map(function (n) { return names.indexOf(n); });
            // by_source строки: буквы chars [с, по] — из своего предмета и своими красками
            var bys = (g.lines[li].by_source || []).map(function (b) {
              if (names.indexOf(b.source) < 0) throw new Error('CardKit.layer ' + o.scene + ': by_source «' + b.source + '» нет среди source строки «' + ln.text + '»');
              return { a: b.chars[0], b: b.chars[1], srcs: [names.indexOf(b.source)],
                       ci: b.ink ? inks(b.ink).map(function (c) { if (colIdx[c] == null) { colIdx[c] = colorsAll.length; colorsAll.push(c); } return colIdx[c]; }) : null };
            });
            pts.forEach(function (p) {
              var inKey = kw >= 0 && p.ci >= kw && p.ci < kw + ln.key.length;
              var by = bys.filter(function (b) { return p.ci >= b.a && p.ci <= b.b; })[0], cc = by && by.ci ? by.ci : ci;
              targets.push({ x: p.x, y: p.y, line: li, key: inKey, word: inKey ? ln.key : null, col: cc[Math.floor(rr() * cc.length)], srcs: by ? by.srcs : own });
            });
          });
          L.phr = CK.particleText({ canvas: o.canvas, targets: targets, sources: srcs, start: start, dur: dur, motion: g.m,
            seed: o.scene + '|' + g.id, order: g.order || 'ltr',
            material: { kind: matSpec.kind || 'dust', colors: colorsAll, size: (g.m.particle_frac_w || matSpec.size_frac_w || 0.0047) * S.W,
                        rest: g.m.rest != null ? g.m.rest : (matSpec.rest || 0), consume: consume } });
        }
        L.cues({ do: 'fall', who: g.who }).forEach(function (q) {
          // осыпание в фигуру (to): садится к formed; иначе — card_fall за span
          var to = q.to || q.shape, fd = to && q.formed != null ? q.formed - q.t : (q.span || q.m.dur);
          L.phr.fall(q.word, q.t, fd, to ? { motion: q.m, shape: L.shape(to) } : q.m);
        });
        var w = L.cue({ do: 'windows' });
        if (w) {
          var wl = L.lines.filter(function (ln) { return ln.text.indexOf(w.word) >= 0; })[0];
          L.win = CK.letterWindows({ text: wl.text, word: w.word, font: wl.font, x: wl.x, y: wl.y, align: wl.align,
                                     open: [w.t, w.t + (w.span || w.m.dur)], motion: w.m });
          L.winCue = w;
        }
        var d = L.cue({ do: 'dive' });
        if (d) {
          var dl = L.lines[d.line] || L.lines.filter(function (ln) { return ln.text.indexOf(d.word) >= 0; })[0];
          var ci0 = dl.text.indexOf(d.word) + d.char;
          var pv = CK.strokePivot(dl.text, dl.font, dl.x, dl.y, ci0, dl.align);
          var edge = L.win ? L.win.shadow(1e9).edge.width : 0;     // кромка окна заходит в штрих на половину толщины
          L.pivot = pv; L.diveCue = d; L.diveLine = dl; L.hole = Math.max(0.5, pv.r_in - edge / 2);
          L.dv = CK.dive({ upper: L.upperCanvas(), pivot: function (t) { return L.toScreen(pv.x, pv.y, t); }, t0: d.t, dur: L.until(d) - d.t, motion: d.m,
                           hole: L.hole, through: d.fade === 'none' || !!d.through,
                           fillAt: typeof d.cover_by === 'number' ? (d.cover_by - d.t) / (L.until(d) - d.t) : null,
                           lower: function (ctx, t) { CK.entry(d.into)(ctx, t); } });
        }
      }
      L.built = ready;
    }
    function ensure() { if (!L.built) build(); }
    L.ensure = ensure;
    // сцена без своего перехода: мир (с дрейфом), фраза, предметы поверх — это и кадр входа сцены
    L.drawUpper = function (ctx, t) {
      ensure();
      L.curT = t;
      var S = size();
      ctx.save(); CK.noShadow(ctx); ctx.globalAlpha = 1; ctx.globalCompositeOperation = 'source-over';
      o.world(ctx, t, L);
      ctx.restore();
      if (L.phr) {                       // фраза — под той же камерой, что мир
        ctx.save(); L.camera(ctx, t);
        if (!L.scaled && (ctx.canvas === o.canvas || ctx.canvas === L.upperCanvas())) { L.camT = t; L.camM = ctx.getTransform(); }   // для промера: чем нарисовано
        L.phr.render(t, ctx); ctx.restore();
      }
      if (o.over) { ctx.save(); o.over(ctx, t, L); ctx.restore(); }
    };
    L.upperCanvas = function () { return canvasOf('upper:' + o.scene); };
    /* доля кадра под непрозрачным верхом в каждом кадре нырка : прорези слова под преобразованием нырка и камерой,
       растр 1/10 кадра; [[t, доля]] от кадра начала нырка до кадра перед швом (считается один раз) */
    L.coverUpper = function () {
      if (L.coverCache) return L.coverCache;
      if (!L.dv || !L.win) return null;
      var S = size(), F = film(), w = Math.round(S.W / 10), h = Math.round(S.H / 10), cv = document.createElement('canvas');
      cv.width = w; cv.height = h;
      var cx = cv.getContext('2d', { willReadFrequently: true }), out = [];
      for (var f = Math.round(L.dv.t0 * F.fps); f < Math.round(sc.end * F.fps); f++) {
        var t = f / F.fps;
        cx.setTransform(1, 0, 0, 1, 0, 0); cx.globalCompositeOperation = 'source-over'; cx.globalAlpha = 1; cx.fillStyle = '#000'; cx.fillRect(0, 0, w, h);
        cx.save(); cx.scale(w / S.W, h / S.H);
        if (L.dv.through) L.dv.upperTransform(cx, t);
        else { var a0 = L.dv.at(t); cx.translate(a0.Ps.x, a0.Ps.y); cx.scale(a0.upperScale, a0.upperScale); cx.translate(-a0.P.x, -a0.P.y); }
        L.camera(cx, t); L.win.cut(t, cx); cx.restore();
        var d = cx.getImageData(0, 0, w, h).data, n = 0;
        for (var i = 3; i < d.length; i += 4) if (d[i] > 128) n++;
        out.push([Math.round(t * 10000) / 10000, Math.round(n / (w * h) * 10000) / 10000]);
      }
      if (L.built) L.coverCache = out;       // шрифт ещё не пришёл — не запоминать
      return out;
    };
    L.lowerScale = function (t) { return L.dv ? L.dv.at(t).lowerScale : 1; };
    // кадр сцены: верх с прорезями, в прорезях — кадр входа следующей сцены, тень верха внутрь, нырок
    L.compose = function (ctx, t) {
      ensure();
      var S = size(), win = L.win ? L.win.open(t) : 0, diving = L.dv && t >= L.dv.t0;
      if (!win && !diving) { ctx.clearRect(0, 0, S.W, S.H); L.drawUpper(ctx, t); return; }
      var up = L.upperCanvas(), uc = up.getContext('2d');
      uc.setTransform(1, 0, 0, 1, 0, 0); uc.clearRect(0, 0, S.W, S.H);
      if (diving && L.dv.through) {     // нырок насквозь: верх рисуется сразу в масштабе нырка (кромка окна — вектором), не гаснет
        uc.save(); L.dv.upperTransform(uc, t); L.scaled = true;
        try { L.drawUpper(uc, t); if (L.win) { uc.save(); L.camera(uc, t); L.win.cut(t, uc); uc.restore(); } } finally { L.scaled = false; uc.restore(); }
        ctx.clearRect(0, 0, S.W, S.H);
        var shT = L.win ? L.win.shadow(t) : null, sk = L.dv.at(t).shadowK;
        L.lastShadow = shT; L.lastShadowT = t;
        L.dv.drawLower(ctx, t);
        ctx.save();
        if (shT && shT.alpha * sk > 0) { ctx.shadowColor = CK.rgba(shT.color, shT.alpha * sk); ctx.shadowBlur = shT.blur; ctx.shadowOffsetY = shT.dy; }
        ctx.drawImage(up, 0, 0); ctx.restore();
        return;
      }
      L.drawUpper(uc, t);
      if (L.win) { uc.save(); L.camera(uc, t); L.win.cut(t, uc); uc.restore(); }
      ctx.clearRect(0, 0, S.W, S.H);
      var sh = L.win ? L.win.shadow(t) : null;
      L.lastShadow = sh; L.lastShadowT = t;
      if (L.dv) { L.dv.draw(ctx, t, sh); return; }
      CK.entry(L.winCue.reveals)(ctx, t);
      ctx.save();
      if (sh && sh.alpha > 0) { ctx.shadowColor = CK.rgba(sh.color, sh.alpha); ctx.shadowBlur = sh.blur; ctx.shadowOffsetY = sh.dy; }
      ctx.drawImage(up, 0, 0); ctx.restore();
    };
    // сцена на экране — по номеру кадра (то же округление, что у битов show / hide и рендера), а не по секундам
    L.active = function (t) {
      var s = sceneRec(), F = film(), fr = function (x) { return Math.round(x * F.fps); }, f = fr(t);
      return f >= fr(s.start) && (f < fr(s.end) || fr(s.end) >= fr(F.duration));
    };
    /* Области текста фразы для читаемости по пикселям (V37; lib/stage.js складывает их в window.__textRects):
       [{id: '<сцена>--<who метки gather>:<номер строки>', rect: [x, y, w, h], text, opacity}] — рамка строки плотно по буквам
       в px кадра: под той камерой, которой фраза нарисована в этом t, с запасом в полчастицы (крупинка сидит центром в
       штрихе). opacity 1 — строка читается целиком: собрана (lineDone), сцена на экране, холст виден на 1,0, слово
       строки не осыпается (fall), в ней не открыты окна (windows), нырок не начался (dive: верх уже растёт). Иначе
       меньше 1 — такую строку проверка не мерит. */
    function shownOf(node) {
      var op = 1;
      for (var e = node; e && e.nodeType === 1 && e.id !== 'root'; e = e.parentElement) {
        var cs = getComputedStyle(e);
        if (cs.display === 'none' || cs.visibility === 'hidden') return 0;
        op *= parseFloat(cs.opacity);
      }
      return op;
    }
    L.textRects = function (t) {
      if (!sc) { try { sceneRec(); } catch (e) { return []; } }
      ensure();
      var g = L.cue({ do: 'gather' });
      if (!g || !L.phr || !L.lines.length) return [];
      var root = document.getElementById('root').getBoundingClientRect(), b = o.canvas.getBoundingClientRect();
      var kx = b.width / o.canvas.width, ky = b.height / o.canvas.height, r2 = function (v) { return Math.round(v * 100) / 100; };
      var shown = L.active(t) ? shownOf(o.canvas) : 0, dr = L.drift(t), M = L.camT === t ? L.camM : null;
      var scr = function (x, y) { return M ? { x: M.a * x + M.c * y + M.e, y: M.b * x + M.d * y + M.f } : CK.driftPoint(dr, x, y); };
      var pad = L.phr.particles ? (L.phr.material.size || 0) / 2 : 0, falls = L.cues({ do: 'fall', who: g.who });
      var diving = !!(L.dv && t >= L.dv.t0), winOpen = L.win ? L.win.open(t) : 0;
      return L.lines.map(function (ln) {
        var done = L.phr.lineDone(ln.idx, t), whole = done >= 1 && !diving;
        if (falls.some(function (q) { return t > q.t && (q.word == null || ln.text.indexOf(q.word) >= 0); })) whole = false;
        if (winOpen > 0 && ln.text.indexOf(L.winCue.word) >= 0) whole = false;
        var p0 = scr(ln.tight[0] - pad, ln.tight[1] - pad), p1 = scr(ln.tight[0] + ln.tight[2] + pad, ln.tight[1] + ln.tight[3] + pad);
        return { id: o.scene + '--' + g.who + ':' + ln.idx, text: ln.text, opacity: r2(shown * (whole ? 1 : Math.min(done, 1) * 0.98)),
                 rect: [r2(b.left - root.left + p0.x * kx), r2(b.top - root.top + p0.y * ky), r2((p1.x - p0.x) * kx), r2((p1.y - p0.y) * ky)] };
      });
    };
    // исполнители меток act: отпечаток каждого who — узел <i data-s> внутри холста (V31 видит изменение)
    L.exec = function (states) {      // регистрация — при старте движка (FILM уже есть), до первого кадра
      (window.StagePlugins = window.StagePlugins || []).push(function () { register(states); return null; });
    };
    function register(states) {
      var host = o.canvas.parentNode;
      var whos = {};
      L.cues().forEach(function (q) { if (q.who !== 'cam') whos[q.who] = true; });
      Object.keys(whos).forEach(function (who) {
        var node = document.createElement('i');
        node.setAttribute('data-who', who); node.style.display = 'none';
        host.appendChild(node);
        (window.ActExec = window.ActExec || []).push({ scene: o.scene, who: who, node: node, run: function (t, cs) {
          var on = L.active(t), extra = states && states[who] ? states[who](t, cs, L) : '';
          if (!extra && on && cs.some(function (c) { return c.cue.do === 'live'; })) extra = 'f' + Math.round(t * film().fps);
          node.setAttribute('data-s', (on ? 'on' : 'off') + '|' + cs.map(function (c) { return c.p.toFixed(3); }).join(',') + (extra ? '|' + extra : ''));
        } });
      });
    }
    // промер фразы, окон и нырка (V40)
    REG.probes.push(function (t) {
      if (!sc) { try { sceneRec(); } catch (e) { return []; } }
      ensure();
      var out = [], g = L.cue({ do: 'gather' });
      if (g && L.phr) {
        var st = L.phr.state(t), fallen = 0, dr = L.drift(t), M = L.camT === t ? L.camM : null;
        // точки в кадре: матрицей, которой фраза нарисована в этом t (сцена на экране), иначе — расчётным дрейфом
        var scr = function (x, y) { return M ? { x: M.a * x + M.c * y + M.e, y: M.b * x + M.d * y + M.f } : CK.driftPoint(dr, x, y); };
        st.now = st.now.map(function (q) { var z = scr(q[0], q[1]); return [Math.round(z.x * 10) / 10, Math.round(z.y * 10) / 10]; });
        // остаток в источнике: [начало в сцене x, y, где нарисован в кадре x, y] — под той же камерой, что мир
        var rest = (st.rest || []).map(function (q) { var z = scr(q[2], q[3]); return [q[0], q[1], Math.round(z.x * 10) / 10, Math.round(z.y * 10) / 10]; });
        L.cues({ do: 'fall', who: g.who }).forEach(function (q) { fallen = Math.max(fallen, CK.clamp01((t - q.t) / (q.span || q.m.dur))); });
        // осыпание в фигуру: точки слова в кадре (та же камера) и снимок в formed (дрейф formed)
        var fallCues = L.cues({ do: 'fall', who: g.who });
        var shapes = (st.shapes || []).map(function (sh) {
          var dF = L.drift(sh.formed.t), cq = fallCues.filter(function (q) { return q.word === sh.word && (q.to || q.shape); })[0];
          var r1 = function (z) { return [Math.round(z.x * 10) / 10, Math.round(z.y * 10) / 10]; };
          return { cue: cq ? cq.id : null, word: sh.word, t0: sh.t0, dur: sh.dur, kind: sh.kind, n: sh.n, landed: sh.landed,
                   now: sh.now.map(function (q) { return r1(scr(q[0], q[1])); }),
                   formed: { t: sh.formed.t, outside: sh.formed.outside, now: sh.formed.now.map(function (q) { return r1(CK.driftPoint(dF, q[0], q[1])); }) } };
        });
        var x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
        L.lines.forEach(function (ln) { x0 = Math.min(x0, ln.left); x1 = Math.max(x1, ln.left + ln.width); y0 = Math.min(y0, ln.y - ln.size * 0.8); y1 = Math.max(y1, ln.y + ln.size * 0.3); });
        out.push({ scene: o.scene, cue: g.id, kind: 'phrase', material: g.material, start: g.t, until: L.until(g),
                   text: L.lines.map(function (ln) { return ln.text; }), box: [x0, y0, x1 - x0, y1 - y0].map(Math.round),
                   sources: L.phr.sources.map(function (s) { return { id: s.id, box: [s.x, s.y, s.w, s.h].map(function (v) { return Math.round(v * 10) / 10; }),
                                                                    left: Math.round((L.phr.source ? L.phr.source(s.id, t) : 1) * 1000) / 1000 }; }),
                   // состояние действий источников и просыпей
                   source_acts: (g.sources_act || []).reduce(function (acc, a) {
                     [a.id].concat(a.with || []).forEach(function (id) { var v = L.source(id, t); acc[id] = { act: Math.round(v.act * 1000) / 1000, emit: Math.round(v.emit * 1000) / 1000, left: Math.round(v.left * 1000) / 1000 }; });
                     return acc; }, {}),
                   n: st.n, landed: Math.round(st.landed * 1000) / 1000, readable: Math.round(st.landed * (1 - fallen) * 1000) / 1000,
                   origins: st.origins, now: st.now, rest: rest, drift: { scale: Math.round(dr.scale * 1e5) / 1e5, dy: Math.round(dr.dy * 100) / 100 },
                   active: L.active(t), consume: !!st.consume, source_left: st.source_left || null,
                   // осыпание в фигуру: точки слова в кадре (та же камера), доля севших
                   shapes: shapes, flight: st.flight || [], in_flight: st.in_flight || 0 });
        shapes.forEach(function (sh) { out.push({ scene: o.scene, cue: sh.cue, kind: 'shape', shape: sh.kind, n: sh.n, landed: sh.landed,
                                                  outside: sh.formed.outside, word: sh.word }); });
      }
      if (L.win) {
        // тень — та, с которой кадр нарисован (compose этого t), иначе — расчётная (сцена не на экране)
        var drawn = L.lastShadowT === t, sh = drawn ? L.lastShadow : L.win.shadow(t);
        out.push({ scene: o.scene, cue: L.winCue.id, kind: 'windows', word: L.win.word, open: Math.round(sh.open * 1000) / 1000, drawn: drawn,
                   shadow: sh.alpha > 0 || sh.open <= 0 ? { color: sh.color, alpha: Math.round(sh.alpha * 1000) / 1000, dy: Math.round(sh.dy * 100) / 100,
                   blur: Math.round(sh.blur * 100) / 100 } : null, edge: sh.edge, rect: L.win.rect.map(Math.round), reveals: L.winCue.reveals });
      }
      if (L.dv) {
        var a = L.dv.at(t), pv = L.pivot, F2 = film(), tLast = (Math.round(sc.end * F2.fps) - 1) / F2.fps, e2 = L.dv.at(tLast);
        out.push({ scene: o.scene, cue: L.diveCue.id, kind: 'dive', word: L.diveCue.word, char: L.diveCue.char, ch: pv.ch,
                   role: L.diveLine.role, line: L.diveLine.idx, pivot: [Math.round(pv.x * 100) / 100, Math.round(pv.y * 100) / 100],
                   char_x: Math.round(pv.charX * 100) / 100, baseline: Math.round(pv.baseline * 100) / 100, size: Math.round(pv.size * 100) / 100,
                   upper: { scale: Math.round(a.upperScale * 1000) / 1000, alpha: Math.round(a.upperAlpha * 1000) / 1000 },
                   lower: { scale: Math.round(a.lowerScale * 1000) / 1000 }, into: L.diveCue.into,
                   mode: L.dv.through ? 'through' : 'fade', hole: L.hole != null ? Math.round(L.hole * 100) / 100 : null,
                   fill: a.fill != null ? Math.round(a.fill * 1000) / 1000 : null,
                   // последний кадр сцены (кадр перед швом): масштаб и непрозрачность верха, масштаб низа
                   end: { t: Math.round(tLast * 1000) / 1000, scale: Math.round(e2.upperScale * 1000) / 1000, alpha: Math.round(e2.upperAlpha * 1000) / 1000,
                          lower: Math.round(e2.lowerScale * 10000) / 10000, pivot: [Math.round(e2.Ps.x * 100) / 100, Math.round(e2.Ps.y * 100) / 100] },
                   fill_at: L.dv.fillAt, cover_upper: L.coverUpper(),
                   // кадр накрытия (cover_by метки): масштаб верха и точка штриха на экране
                   cover: typeof L.diveCue.cover_by === 'number' ? (function () { var e3 = L.dv.at(L.diveCue.cover_by);
                     return { t: Math.round(L.diveCue.cover_by * 1000) / 1000, scale: Math.round(e3.upperScale * 1000) / 1000, alpha: e3.upperAlpha,
                              pivot: [Math.round(e3.Ps.x * 100) / 100, Math.round(e3.Ps.y * 100) / 100] }; })() : null });
      }
      return out;
    });
    // кадр — стадия плагинов движка: рисует, только пока сцена на экране
    (window.StagePlugins = window.StagePlugins || []).push(function () {
      return { render: function (t) {
        var ctx = o.canvas.getContext('2d'), host = o.canvas.parentNode;
        ctx.setTransform(1, 0, 0, 1, 0, 0);
        // рисует, пока на экране её .el: видимость ведут биты show / hide (ядро ставит её до плагинов), холст ей следует
        var shown = host && host.style.visibility !== 'hidden' && parseFloat(host.style.opacity || '1') > 0.001;
        if (!shown) { ctx.clearRect(0, 0, o.canvas.width, o.canvas.height); return; }   // вне сцены — пусто, не старый кадр
        if (o.compose) o.compose(ctx, t, L); else L.compose(ctx, t);
        if (o.after) { ctx.save(); o.after(ctx, t, L); ctx.restore(); }
      }, textRects: L.textRects };
    });
    return L;
  };

  window.CardKit = CK;
})();
