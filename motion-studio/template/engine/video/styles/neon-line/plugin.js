/* neon-line — мир нарисован светом: неоновые трубки на тёмном (engine/video/styles/README.md, «Миры с набором сцены»).
   Мир (cfg.world) — в слое 'back': фон decor.bg и тихое зарево у пола (дышит). В сцене с каркасом: светлые окна под
   текстом (StyleCore.textWindows) и в каждой зоне decor_zones — вывеска без слов: рама и три трубки разгораются с
   дрожью и дышат, под ними пятно отсвета, по рейке бежит свет. Заливки цветом нет; трубка — штрихи одной линии
   (ореолы, жила, раскалённая сердцевина), пятна света — градиенты; фильтров, размытия и mix-blend-mode нет.

   Сцене стиль даёт набор window.NeonKit:
     neon(parent, tag, attrs, color, w, o)   трубка: {g, set(attrs), draw(p), light(core, halo), glow(k), color(c)};
                                             o.fill — тёмная заливка фоном, o.lx — где линия в мире, o.fine — тонкая
                                             деталь, o.hot: false — негорящая, o.inherit — цвет от группы
     drawIn(list, t0, pps)                   «линия рисуется, а не появляется»: волна слева направо со скоростью pps
     Живой свет (числа — style.json params.light):
     strike(seed, o)                         разгорание трубки: 2–4 вспышки-дрожи и ровный свет; at(dt) → {c, h}
     breath(seed)                            дыхание ореола: f(t) около единицы, период и фаза — от зерна
     flow(parent, d, color, w, o)            бегущий свет по линии: set(x, k), x() — голова в DOM
     pool(root, parent, cx, cy, rx, ry, color, alpha), beam(root, parent, d, color, a0, a1)   пятно и луч отсвета
     mix(rgbA, rgbB, k), hueMix(…) → [r,g,b]  смесь цветов по каналам и по цветовому кругу
     talk(voice, t)                          рот героя по огибающей реплики, 0…1
     ik(sx, sy, tx, ty, l1, l2, bend)        два звена до цели: плечо → локоть → кисть (фигура контуром)
     limbPath(p0, p1, p2, w0, w1, w2, cap)   контур конечности вокруг двух звеньев (рукав, штанина)
     at({reply, at, offset})                 якорь времени → секунды; track, events, scene, rng, hash, decor
   Сцена подключается из своей разметки: (window.NeonScenes = window.NeonScenes || []).push({scene, setup});
   setup(kit, FILM, api) → {frame(t), probe(t)?} — frame зовётся на каждый кадр, probe отдаёт промеру свет сцены
   (поле light промера плагина). Героя, слов вывесок и времени в стиле нет — они в данных проекта: фигуру героя
   сцена рисует трубками (neon, o.inherit) на звеньях ik / limbPath, конечности размечает StyleCore.limb (V25).
   Замок бренда (cfg.world = false): фона, зарева и вывесок нет. Кадр — чистая функция t. */
(window.StagePlugins = window.StagePlugins || []).push(function (FILM, api) {
  'use strict';
  var NAME = 'neon-line', cfg = api.styleConfig(NAME);
  if (!cfg) return null;
  var C = window.StyleCore, D = cfg.decor, P = cfg.params || {};
  var root = document.getElementById('root'), W = root.clientWidth, H = root.clientHeight;
  var ids = api.styleScenes(NAME);
  var layer = api.addLayer('neon-line-back', 'back');
  var haze = null;
  if (cfg.world) {
    layer.style.background = D[P.bg_role];
    if (P.haze) {                       // зарево у пола: углы кадра остаются чистым фоном
      var c = C.rgbOf(D[P.haze.role]);
      haze = document.createElement('div');
      haze.style.cssText = 'position:absolute;left:' + (W / 2 - P.haze.rx) + 'px;top:' + (P.haze.y - P.haze.ry) + 'px;width:' + 2 * P.haze.rx +
        'px;height:' + 2 * P.haze.ry + 'px;border-radius:50%;background:radial-gradient(ellipse,rgba(' + c.join(',') + ',' + P.haze.alpha +
        ') 0%,rgba(' + c.join(',') + ',0) 68%);';
      layer.appendChild(haze);
    }
  }

  var svg = C.svg, RAD = Math.PI / 180;
  function f1(v) { return (Math.round(v * 10) / 10).toString(); }
  function track(v0, keys) {            // дорожка ключей {t, v, d, e}: каждый едет от того, куда доехал предыдущий
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

  // ------------------------------------------------------------------ светящаяся линия
  /* Трубка — штрихи одной линии: ореолы (широкие, прозрачные), жила (цвет трубки) и раскалённая сердцевина (светлая,
     тонкая). o.fine — тонкая деталь: один ближний ореол; o.hot === false — без сердцевины (негорящая трубка);
     o.inherit — цвет берётся у родителя: жила — атрибут stroke группы, ореол — её атрибут color (currentColor): контур
     фигуры перекрашивается двумя атрибутами, жила и ореол — порознь. */
  var GL = P.glow || [[6, 0.1], [2.6, 0.28]], FINE = P.glow_fine || [[3, 0.2]], HOT = P.hot || { w: 0.42, o: 0.55 };
  function neon(parent, tag, attrs, color, w, o) {
    o = o || {};
    var g = svg('g', {}, parent), parts = [], base = [], fill = null;
    if (o.fill) { fill = svg(tag, attrs, g); fill.setAttribute('fill', o.fill); fill.setAttribute('stroke', 'none'); }
    function part(width, op, col, dash) {
      var n = svg(tag, attrs, g);
      n.setAttribute('fill', 'none'); if (col) n.setAttribute('stroke', col); n.setAttribute('stroke-width', f1(width));
      n.setAttribute('stroke-opacity', String(op)); n.setAttribute('stroke-linecap', 'round'); n.setAttribute('stroke-linejoin', 'round');
      if (dash) n.setAttribute('stroke-dasharray', dash);
      parts.push(n); base.push(op);
    }
    var halos = o.fine ? FINE : GL, nH = halos.length, c0 = o.inherit ? null : color;
    halos.forEach(function (q) { part(w * q[0], q[1], o.inherit ? 'currentColor' : color); });
    part(w, 1, c0, o.dash);
    var hasHot = o.hot !== false && w >= 1.5;
    if (hasHot) part(Math.max(0.6, w * HOT.w), HOT.o, D.hi, o.dash);
    var all = fill ? [fill].concat(parts) : parts;
    function light(core, halo) {        // core — жила и сердцевина (выше 1 — перекал: сердцевина белее), halo — ореолы
      parts.forEach(function (n, i) {
        var v = i < nH ? base[i] * halo : i === nH ? core : HOT.o * core * core;
        api.setAttr(n, 'stroke-opacity', Math.max(0, Math.min(1, v)).toFixed(3));
      });
    }
    return { g: g, lx: o.lx == null ? 0 : o.lx, len: o.len || 0, core: parts[nH],
      set: function (a) { Object.keys(a).forEach(function (k) { all.forEach(function (n) { api.setAttr(n, k, a[k]); }); }); },
      color: function (col) { parts.forEach(function (n, i) { if (!(hasHot && i === parts.length - 1)) api.setAttr(n, 'stroke', col); }); },
      light: light,
      glow: function (k) { light(Math.min(1, k), k); },
      draw: function (p) {              // доля нарисованного 0…1: штрих бежит по длине линии
        parts.forEach(function (n) {
          if (!n.getAttribute('pathLength')) n.setAttribute('pathLength', '1');
          api.setAttr(n, 'stroke-dasharray', p >= 1 ? 'none' : '1 1');
          api.setAttr(n, 'stroke-dashoffset', p >= 1 ? '0' : (1 - p).toFixed(4));
        });
        if (fill) api.setAttr(fill, 'visibility', p > 0 ? 'inherit' : 'hidden');
      } };
  }

  // ------------------------------------------------------------------ живой свет (числа — style.json params.light)
  var LT = P.light || {}, FR = 1 / FILM.fps;
  function mix(a, b, k) {               // смесь двух цветов [r, g, b] → строка rgb()
    return 'rgb(' + [0, 1, 2].map(function (i) { return Math.round(a[i] + (b[i] - a[i]) * k); }).join(',') + ')';
  }
  /* Смесь по цветовому кругу (короткой дугой): между пурпуром и золотом — розовый и оранжевый, а не серо-бежевый,
     как у смеси по каналам. Возвращает [r, g, b]. */
  function hueMix(a, b, k) {
    function hsl(c) {
      var r = c[0] / 255, g = c[1] / 255, bl = c[2] / 255, mx = Math.max(r, g, bl), mn = Math.min(r, g, bl), l = (mx + mn) / 2, d = mx - mn, h = 0, sa = 0;
      if (d > 1e-6) { sa = d / (1 - Math.abs(2 * l - 1)); h = mx === r ? ((g - bl) / d + 6) % 6 : mx === g ? (bl - r) / d + 2 : (r - g) / d + 4; }
      return [h * 60, sa, l];
    }
    var A = hsl(a), B = hsl(b), dh = ((B[0] - A[0] + 540) % 360) - 180, h = (A[0] + dh * k + 360) % 360, sa = A[1] + (B[1] - A[1]) * k, l = A[2] + (B[2] - A[2]) * k;
    var c = (1 - Math.abs(2 * l - 1)) * sa, x = c * (1 - Math.abs((h / 60) % 2 - 1)), m = l - c / 2, i = Math.floor(h / 60) % 6;
    var q = [[c, x, 0], [x, c, 0], [0, c, x], [0, x, c], [x, 0, c], [c, 0, x]][i];
    return [(q[0] + m) * 255, (q[1] + m) * 255, (q[2] + m) * 255];
  }
  /* Разгорание газовой трубки: n коротких вспышек-дрожи (каждая — целое число кадров: ни одна не теряется между
     кадрами), между ними трубка не гаснет в ноль (послесвечение), затем ровный свет с перекалом, который оседает.
     at(dt) → {c — жила, h — ореол}: ореол во вспышках слабее жилы и «расцветает» уже после того, как трубка встала.
     Расписание — от зерна (id трубки): у каждой своё, от прогона к прогону одно и то же. */
  function strike(seed, o) {
    var L = LT.strike, r = C.rng(C.hash('strike' + seed)), segs = [], t = 0, i;
    o = o || {};
    function fr(a) { return Math.max(1, Math.round((a[0] + r() * (a[1] - a[0])) * FILM.fps)) * FR; }
    var fl = o.flashes || L.flashes, n = fl[0] + Math.floor(r() * (fl[1] - fl[0] + 1));
    for (i = 0; i < n; i++) {
      var on = fr(L.on), pk = api.lerp(L.peak[0], L.peak[1], n > 1 ? i / (n - 1) : 1) * (0.9 + 0.2 * r());
      segs.push([t + on, pk]); t += on;
      var off = fr(L.off); segs.push([t + off, L.dark[0] + r() * (L.dark[1] - L.dark[0])]); t += off;
    }
    var tOn = t, end = tOn + L.settle;
    function core(dt) {
      if (dt < 0) return 0;
      for (var k = 0; k < segs.length; k++) if (dt < segs[k][0] - 1e-6) return segs[k][1];
      return 1 + (L.over - 1) * Math.exp(-5 * (dt - tOn) / L.settle);
    }
    return { n: n, on: tOn, end: end, core: core,
      at: function (dt) {
        var c = core(dt);
        return { c: c, h: dt < tOn ? c * L.halo_strike : c * (1 - (1 - L.halo_strike) * Math.exp(-(dt - tOn) / L.bloom)) };
      } };
  }
  /* Дыхание горящей трубки: ореол медленно ходит вокруг единицы; период и фаза — от зерна трубки. */
  function breath(seed) {
    var B = LT.breath, r = C.rng(C.hash('breath' + seed)), per = B.period[0] + r() * (B.period[1] - B.period[0]), ph = r();
    return function (t) { return 1 + B.amp * Math.sin(2 * Math.PI * (t / per + ph)); };
  }
  /* Пятно света: эллипс с радиальным градиентом (без размытия и фильтров). set(k) — яркость 0…1. */
  var gradN = 0;
  function defsOf(root) { return root.querySelector('defs') || svg('defs', {}, root); }
  function pool(root, parent, cx, cy, rx, ry, color, alpha) {
    var id = 'nl-pool-' + (gradN++), gr = svg('radialGradient', { id: id }, defsOf(root));
    svg('stop', { offset: '0', 'stop-color': color, 'stop-opacity': String(alpha) }, gr);
    svg('stop', { offset: '0.42', 'stop-color': color, 'stop-opacity': String(alpha * 0.42) }, gr);
    svg('stop', { offset: '1', 'stop-color': color, 'stop-opacity': '0' }, gr);
    var el = svg('ellipse', { cx: f1(cx), cy: f1(cy), rx: f1(rx), ry: f1(ry), fill: 'url(#' + id + ')', opacity: '0' }, parent);
    return { el: el, set: function (k) { api.setAttr(el, 'opacity', Math.max(0, Math.min(1, k)).toFixed(3)); },
             at: function (x, y) { api.setAttr(el, 'cx', f1(x)); if (y != null) api.setAttr(el, 'cy', f1(y)); } };
  }
  /* Луч-отражение: фигура с линейным градиентом сверху вниз (a0 → a1). */
  function beam(root, parent, d, color, a0, a1) {
    var id = 'nl-beam-' + (gradN++), gr = svg('linearGradient', { id: id, x1: '0', y1: '0', x2: '0', y2: '1' }, defsOf(root));
    svg('stop', { offset: '0', 'stop-color': color, 'stop-opacity': String(a0) }, gr);
    svg('stop', { offset: '1', 'stop-color': color, 'stop-opacity': String(a1 || 0) }, gr);
    var el = svg('path', { d: d, fill: 'url(#' + id + ')', opacity: '0' }, parent);
    return { el: el, set: function (k) { api.setAttr(el, 'opacity', Math.max(0, Math.min(1, k)).toFixed(3)); } };
  }
  /* Бегущий свет по линии d: «комета» — длинный слабый хвост, середина, короткая белая голова; повторяется с шагом
     period. set(x, k): голова в x px от начала линии, яркость k. x() — где голова стоит в DOM (для промера). */
  function flow(parent, d, color, w, o) {
    o = o || {};
    var F = LT.flow, per = o.period || F.period, g = svg('g', { opacity: '0' }, parent);
    var lay = [[F.tail, w * 6, 0.2, color], [F.mid, w * 3, 0.5, color], [F.head, w * 1.5, 1, D.hi]];
    var parts = lay.map(function (q) {
      var n = svg('path', { d: d, fill: 'none', stroke: q[3], 'stroke-width': f1(q[1]), 'stroke-opacity': String(q[2]), 'stroke-linecap': 'round',
                            'stroke-dasharray': q[0] + ' ' + (per - q[0]) }, g);
      return n;
    });
    return { g: g, period: per,
      set: function (x, k) {
        x = ((x % per) + per) % per;
        parts.forEach(function (n, i) { api.setAttr(n, 'stroke-dashoffset', f1(lay[i][0] - x)); });
        api.setAttr(g, 'opacity', Math.max(0, Math.min(1, k)).toFixed(3));
      },
      x: function () { return lay[2][0] - parseFloat(parts[2].getAttribute('stroke-dashoffset') || '0'); },
      k: function () { return parseFloat(g.getAttribute('opacity') || '0'); } };
  }
  /* Раскрыт ли рот героя в кадре t: уровень 0…1 огибающей её реплики (FILM.replies[].mouth), немая опора — 0. */
  function talk(voice, t) {
    var r = FILM.replies;
    for (var i = 0; i < r.length; i++) {
      if (r[i].voice !== voice || r[i].silent || !r[i].mouth || t < r[i].start || t >= r[i].end) continue;
      return (+(r[i].mouth.charAt(Math.floor((t - r[i].start) * FILM.fps + 1e-6)) || 0)) / 9;
    }
    return 0;
  }
  /* Волна рисования: линия начинает рисоваться, когда «перо» (скорость pps, старт t0) дошло до её левого края lx,
     и рисуется со скоростью pps по своей длине len. Возвращает render(t). */
  function drawIn(list, t0, pps, minDur) {
    return function (t) {
      list.forEach(function (ln) {
        var dur = Math.max(minDur || 0, (ln.len || 1) / pps);
        ln.draw(api.clamp01((t - t0 - ln.lx / pps) / dur));
      });
    };
  }

  // ------------------------------------------------------------------ фигура контуром: звенья и конечность
  function ik(sx, sy, tx, ty, l1, l2, bend) {     // два звена: плечо → локоть → кисть
    var dx = tx - sx, dy = ty - sy, d = Math.sqrt(dx * dx + dy * dy);
    var dd = Math.max(Math.abs(l1 - l2) + 1, Math.min(l1 + l2 - 0.5, d)), a = Math.atan2(dy, dx);
    var ca = Math.max(-1, Math.min(1, (l1 * l1 + dd * dd - l2 * l2) / (2 * l1 * dd))), b = a + bend * Math.acos(ca);
    var ex = sx + l1 * Math.cos(b), ey = sy + l1 * Math.sin(b);
    return [ex, ey, sx + dd * Math.cos(a), sy + dd * Math.sin(a)];
  }
  /* Конечность — замкнутый контур вокруг двух звеньев p0 → p1 → p2 с полуширинами w0, w1, w2 (рукав, штанина);
     cap — скруглить начало (плечо). */
  function limb(p0, p1, p2, w0, w1, w2, cap) {
    function nr(a, b) { var dx = b[0] - a[0], dy = b[1] - a[1], l = Math.sqrt(dx * dx + dy * dy) || 1; return [-dy / l, dx / l]; }
    var n0 = nr(p0, p1), n1 = nr(p1, p2), mx = n0[0] + n1[0], my = n0[1] + n1[1], ml = Math.sqrt(mx * mx + my * my) || 1, nm = [mx / ml, my / ml];
    var wk = w1 / Math.max(0.6, n0[0] * nm[0] + n0[1] * nm[1]);          // на сгибе контур не сужается
    function pt(p, n, w) { return f1(p[0] + n[0] * w) + ' ' + f1(p[1] + n[1] * w); }
    return 'M' + pt(p0, n0, w0) + 'L' + pt(p1, nm, wk) + 'L' + pt(p2, n1, w2) + 'L' + pt(p2, n1, -w2) + 'L' + pt(p1, nm, -wk) + 'L' + pt(p0, n0, -w0) +
           (cap ? 'A' + f1(w0) + ' ' + f1(w0) + ' 0 0 0 ' + pt(p0, n0, w0) : '') + 'Z';
  }
  var kit = { decor: D, params: P, svg: svg, neon: neon, drawIn: drawIn, strike: strike, breath: breath, flow: flow, pool: pool, beam: beam, mix: mix, hueMix: hueMix, talk: talk, ik: ik, limbPath: limb, track: track,
              rng: C.rng, hash: C.hash, rgb: C.rgbOf, W: W, H: H,
              at: function (anchor) { return C.when(FILM, anchor); },      // якорь {reply, at, offset} → секунды фильма
              cues: function (scene) { return C.cues(FILM, scene); },      // метки act сцены: {id, t, who, do, m, span}
              events: function (dom) { return FILM.elements.filter(function (e) { return e.dom === dom && !e.part; })[0]; },
              scene: function (id) { return FILM.scenes.filter(function (x) { return x.id === id; })[0]; } };
  window.NeonKit = kit;

  // ------------------------------------------------------------------ сцена с каркасом: вывески в зонах и окна под текстом
  var FRAMED = FILM.scenes.some(function (sc) { return sc.style === NAME && sc.frame !== false; });
  var signs = [];
  if (cfg.world && FRAMED) {
    var sroot = svg('svg', { width: String(W), height: String(H), viewBox: '0 0 ' + W + ' ' + H }, layer);
    sroot.style.position = 'absolute'; sroot.style.left = '0'; sroot.style.top = '0';
    FILM.scenes.forEach(function (sc, i) {
      if (sc.style !== NAME || sc.frame === false) return;
      (sc.decor_zones || []).forEach(function (z, zi) {
        var g = svg('g', {}, sroot), x = z[0] + 24, y = z[1] + 24, w = z[2] - 48, h = z[3] - 48, id = sc.id + '-' + zi;
        var col = zi % 2 ? D.gold_warm : D.violet_soft, fh = h * 0.62;
        var glow = pool(sroot, g, x + w / 2, y + h * 0.92, w * 0.55, h * 0.3, col, 0.22);
        var tubes = [neon(g, 'rect', { x: f1(x), y: f1(y), width: f1(w), height: f1(fh), rx: '18' }, col, 3)];
        [0.25, 0.5, 0.75].forEach(function (q, n) {             // три трубки в раме — «строки» вывески без слов
          tubes.push(neon(g, 'path', { d: 'M' + f1(x + w * 0.12) + ' ' + f1(y + fh * q) + 'L' + f1(x + w * (0.88 - 0.18 * n)) + ' ' + f1(y + fh * q) },
                          n === 1 ? D.hi : col, 2.2, { fine: n !== 1 }));
        });
        var line = 'M' + f1(z[0] + 8) + ' ' + f1(y + h) + 'L' + f1(z[0] + z[2] - 8) + ' ' + f1(y + h);
        neon(g, 'path', { d: line }, D.dim, 1.6, { hot: false, fine: true });      // рейка: по ней бежит свет
        signs.push({ i: i, g: g, tubes: tubes, st: tubes.map(function (q, n) { return strike(id + '-' + n); }), br: breath(id),
                     glow: glow, run: flow(g, line, col, 1.4), t0: sc.start + P.sign_at });
      });
    });
  }
  // окна под текстом — последними в слое: поверх зарева, вывесок и пятен отсвета
  var wins = cfg.world && FRAMED ? C.textWindows(api, FILM, NAME, { parent: layer, pad: P.win_pad_px,
                                                                    css: { borderRadius: '6px', boxShadow: '0 0 0 2px ' + D.violet_soft } }) : null;

  var frames = [];
  if (cfg.world) {
    ids.forEach(function (id) {         // роли decor — переменными --d-<роль> на секции сцены
      var sec = document.getElementById('scene--' + id);
      if (sec) Object.keys(D).forEach(function (role) { sec.style.setProperty('--d-' + role, D[role]); });
    });
    (window.NeonScenes || []).forEach(function (s) {
      if (ids.indexOf(s.scene) >= 0) frames.push(s.setup(kit, FILM, api));
    });
  }

  return {
    render: function (t) {
      var w = api.styleWeight(NAME, t);
      api.setStyle(layer, 'opacity', api.styleOpacity(NAME, t, layer).toFixed(3));
      api.setStyle(layer, 'visibility', w > 0.001 ? 'visible' : 'hidden');
      frames.forEach(function (f) { if (f && f.frame) f.frame(t); });
      if (w > 0.001) {
        if (wins) wins.render(t);
        signs.forEach(function (sg) {
          var sw = api.sceneWeight(sg.i, t);
          api.setAttr(sg.g, 'opacity', sw.toFixed(3));
          if (sw <= 0.001) return;
          var b = sg.br(t), on = 0;
          sg.tubes.forEach(function (tube, n) {                 // трубки разгораются по очереди, затем дышат вместе
            var q = sg.st[n].at(t - sg.t0 - n * P.sign_gap);
            tube.light(q.c, q.h * b); on = Math.max(on, Math.min(1, q.c));
          });
          sg.glow.set(on * b);
          sg.run.set(Math.max(0, t - sg.t0) * LT.flow.speed, on);
        });
      }
      if (haze && w > 0.001) api.setStyle(haze, 'opacity', (0.75 + 0.25 * Math.sin(2 * Math.PI * t / P.haze.period)).toFixed(3));
    },
    probe: function (t) {
      var o = { style: NAME, weight: api.styleWeight(NAME, t), world: cfg.world };
      frames.forEach(function (f) { if (f && f.probe) o.light = f.probe(t); });
      return o;
    }
  };
});
