/* Рантайм ролика. Кадр — чистая функция времени: render(t) ставит каждый элемент и каркас
   в состояние момента t и ничего не помнит между кадрами. Поэтому рендер повторяем, кадры
   можно снимать в любом порядке, а кусок рендера совпадает с цельным рендером бит в бит.
   С движком HyperFrames связь одна: GSAP-таймлайн из одного твина «часов», свойство-функция
   которого зовёт render(t) при каждом seek.

   Данные — window.__FILM__ (пишет engine/video/build.py): времена реплик, огибающие голоса,
   события элементов в абсолютных секундах, умолчания движения из tokens.json (FILM.motion),
   геометрия каркаса из project.json (FILM.frame). Раскадровка в рантайм не попадает.

   Плагины (живой фон, история в каркасе и т. п.) — window.StagePlugins: [function (FILM, api) →
   {render(t), probe(t)?}]; ядро зовёт их после элементов. Стили (engine/video/styles/<имя>/plugin.js) —
   такие же плагины; для них в api есть frameOf, stepTime, styleAt, styleWeight, styleConfig, styleScenes,
   addLayer (см. раздел «стили» ниже и styles/README.md). Образцы плагинов —
   engine/video/plugins/ (README.md там же). */
(function () {
  'use strict';
  var FILM = window.__FILM__;
  var FPS = FILM.fps;
  var M = FILM.motion;

  // ---------------------------------------------------------------- утилиты
  function clamp01(x) { return x < 0 ? 0 : x > 1 ? 1 : x; }
  function lerp(a, b, p) { return a + (b - a) * p; }
  function prog(t, t0, dur) { return dur <= 0 ? (t >= t0 ? 1 : 0) : clamp01((t - t0) / dur); }
  var ease = {
    inOut: function (x) { return x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2; },
    out: function (x) { return 1 - Math.pow(1 - x, 3); },
    back: function (x) { var c = 1.70158, c3 = c + 1; return 1 + c3 * Math.pow(x - 1, 3) + c * Math.pow(x - 1, 2); }
  };
  function mulberry32(a) {
    return function () {
      a |= 0; a = a + 0x6D2B79F5 | 0;
      var t = Math.imul(a ^ a >>> 15, 1 | a);
      t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
      return ((t ^ t >>> 14) >>> 0) / 4294967296;
    };
  }
  function hashStr(s) { var h = 2166136261; for (var i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return h | 0; }
  var cache = new WeakMap();
  function setStyle(el, prop, val) {   // пишет в DOM только изменения
    var c = cache.get(el); if (!c) { c = {}; cache.set(el, c); }
    if (c[prop] !== val) { c[prop] = val; el.style[prop] = val; }
  }
  function setAttr(el, name, val) {
    var c = cache.get(el); if (!c) { c = {}; cache.set(el, c); }
    var k = '@' + name;
    if (c[k] !== val) { c[k] = val; el.setAttribute(name, val); }
  }
  function powerEase(name) {
    if (!name || name === 'none') return function (x) { return x; };
    var m = /^power(\d)\.(in|out|inOut)$/.exec(name), n = m ? +m[1] + 1 : 3, kind = m ? m[2] : 'inOut';
    if (kind === 'in') return function (x) { return Math.pow(x, n); };
    if (kind === 'out') return function (x) { return 1 - Math.pow(1 - x, n); };
    return function (x) { return x < 0.5 ? Math.pow(2, n - 1) * Math.pow(x, n) : 1 - Math.pow(-2 * x + 2, n) / 2; };
  }
  function hexRgb(h) { return [parseInt(h.substr(1, 2), 16), parseInt(h.substr(3, 2), 16), parseInt(h.substr(5, 2), 16)]; }
  function cssRgb(s) { var m = /rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)/.exec(s || ''); return m ? [+m[1], +m[2], +m[3]] : [0, 0, 0]; }
  function mixRgb(a, b, p) { return 'rgb(' + [0, 1, 2].map(function (c) { return Math.round(lerp(a[c], b[c], p)); }).join(',') + ')'; }

  // ---------------------------------------------------------------- стили (engine/video/styles/README.md)
  /* FILM.styles: {имя: {params, motion}} — style.json стилей, которые есть в фильме; FILM.scenes[i].style —
     стиль сцены или null. Ядро даёт стилю: номер кадра (одно правило округления со сборкой), ступенчатое
     время, вес стиля в момент t (смена стиля на стыке — наплыв ± seam_half), слой под всем кадром
     (addLayer 'back') или над содержанием ('over'), атрибут #root[data-style] — стиль текущей сцены. */
  var STYLES = FILM.styles || {};
  function frameOf(t) { return Math.floor(t * FPS + 0.5 + 0.005); }
  function stepTime(t, n) {
    if (!n || n <= 1) return t;
    var f = frameOf(t);
    return (f - f % n) / FPS;
  }
  function styleOfScene(i) { return FILM.scenes[i].style || null; }
  function styleAt(t) { return styleOfScene(sceneAt(t)); }
  function styleConfig(name) { return STYLES[name] || null; }
  function styleScenes(name) { return FILM.scenes.filter(function (s) { return s.style === name; }).map(function (s) { return s.id; }); }
  function styleMotion(sceneId) {
    for (var i = 0; i < FILM.scenes.length; i++)
      if (FILM.scenes[i].id === sceneId && FILM.scenes[i].style) return (STYLES[FILM.scenes[i].style] || {}).motion || null;
    return null;
  }
  function styleWeight(name, t) {
    var s = FILM.scenes;
    for (var k = 1; k < s.length; k++) {
      var b = s[k].start;
      if (Math.abs(t - b) < SEAM_HALF && styleOfScene(k - 1) !== styleOfScene(k)) {
        var p = ease.inOut(prog(t, b - SEAM_HALF, 2 * SEAM_HALF));
        return lerp(styleOfScene(k - 1) === name ? 1 : 0, styleOfScene(k) === name ? 1 : 0, p);
      }
    }
    return styleAt(t) === name ? 1 : 0;
  }
  /* Непрозрачность слоя мира стиля: на шве двух стилей нижний слой (раньше в DOM — рисуется первым) стоит на 1,
     верхний наплывает своим весом — кадр = смесь двух миров. Если оба слоя гасить весами, на середине шва
     сквозь них просвечивает фон страницы (paper) и мир «вспыхивает» светлым (замер: синий + сумерки на шве давали
     кадр светлее обоих). Слой регистрируется первым вызовом. Вне шва — тот же вес, что styleWeight. */
  var STYLE_LAYERS = {};
  function styleOpacity(name, t, layer) {
    if (layer) STYLE_LAYERS[name] = layer;
    var w = styleWeight(name, t), s = FILM.scenes;
    if (w <= 0 || w >= 1) return w;
    for (var k = 1; k < s.length; k++) {
      if (Math.abs(t - s[k].start) >= SEAM_HALF) continue;
      var a = styleOfScene(k - 1), b = styleOfScene(k), other = name === a ? b : name === b ? a : null;
      var me = STYLE_LAYERS[name], ot = other && STYLE_LAYERS[other];
      if (!me || !ot) return w;
      return (me.compareDocumentPosition(ot) & Node.DOCUMENT_POSITION_FOLLOWING) ? 1 : w;
    }
    return w;
  }
  function addLayer(id, where) {
    var root = document.getElementById('root'), d = document.createElement('div');
    d.id = id; d.className = 'layer style-layer style-' + (where === 'over' ? 'over' : 'back');
    if (where === 'over') root.appendChild(d); else root.insertBefore(d, root.firstChild);
    return d;
  }

  // ---------------------------------------------------------------- сцены и стыки
  function sceneAt(t) {
    var s = FILM.scenes;
    for (var i = 0; i < s.length; i++) if (t < s[i].end) return i;
    return s.length - 1;
  }
  var SEAM_HALF = FILM.frame.seam_half;   // заголовок и номер: старый уходит за SEAM_HALF до стыка, новый входит SEAM_HALF после
  var SEAM_DUR = FILM.frame.seam_dur;     // трекер: плавная смена вокруг стыка, только если глава меняется
  function sceneWeight(i, t) {
    var sc = FILM.scenes[i];
    var a = i === 0 ? 1 : ease.inOut(prog(t, sc.start, SEAM_HALF));
    var b = i === FILM.scenes.length - 1 ? 0 : ease.inOut(prog(t, sc.end - SEAM_HALF, SEAM_HALF));
    return Math.min(a, 1 - b);
  }
  // номер: по стыку, а с num_at следующей сцены — вокруг её бита
  function numWeight(i, t) {
    var s = FILM.scenes, sc = s[i], nx = s[i + 1];
    var a = i === 0 ? 1 : ease.inOut(prog(t, sc.num_at != null ? sc.num_at : sc.start, SEAM_HALF));
    var b = !nx ? 0 : ease.inOut(prog(t, (nx.num_at != null ? nx.num_at : sc.end) - SEAM_HALF, SEAM_HALF));
    return Math.min(a, 1 - b);
  }
  // заголовок: с title_at входит на бите, до него пуст
  function titleWeight(i, t) {
    var sc = FILM.scenes[i];
    if (sc.title_at == null) return sceneWeight(i, t);
    var b = i === FILM.scenes.length - 1 ? 0 : ease.inOut(prog(t, sc.end - SEAM_HALF, SEAM_HALF));
    return Math.min(ease.inOut(prog(t, sc.title_at, M.title_in)), 1 - b);
  }

  // ---------------------------------------------------------------- каркас: заголовок, номер, трекер глав
  var frameEls = {}, trOn = [], trBox = [], trPlq = [];
  function rootXY() { var r = document.getElementById('root').getBoundingClientRect(); return [r.left, r.top]; }
  function initFrame() {
    FILM.scenes.forEach(function (sc) {     // у сцены без каркаса заголовка и номера на странице нет — null
      frameEls[sc.id] = { title: document.getElementById('title--' + sc.id), num: document.getElementById('num--' + sc.id) };
    });
    FILM.chapters.forEach(function (ch, k) {
      var n = document.getElementById('tr-on-' + k);
      if (!n) return;
      trOn.push(n);
      trPlq.push(document.getElementById('tr-' + k));
      var r = n.getBoundingClientRect(), o = rootXY();
      trBox.push([r.left - o[0], r.width]);
    });
  }
  function trackerPulse(t) {           // tracker_emph: 1 → 1 + pulse_amp → 1 за emph_dur, синус
    var sc = FILM.scenes[sceneAt(t)], s = 1;
    (sc.tracker_emph || []).forEach(function (t0) {
      if (t > t0 && t < t0 + M.emph_dur) s *= 1 + M.pulse_amp * Math.sin(Math.PI * (t - t0) / M.emph_dur);
    });
    return s;
  }
  function chapterStart(sc) { return sc.chapter_from != null ? sc.chapter_from : sc.chapter; }
  function trackerState(t) {           // (глава-откуда, глава-куда, доля пути заливки)
    var s = FILM.scenes, i = sceneAt(t), cur = s[i];
    if (i > 0 && t < cur.start + SEAM_DUR / 2)
      return [s[i - 1].chapter, chapterStart(cur), ease.inOut(prog(t, cur.start - SEAM_DUR / 2, SEAM_DUR))];
    if (i < s.length - 1 && t >= cur.end - SEAM_DUR / 2)
      return [cur.chapter, chapterStart(s[i + 1]), ease.inOut(prog(t, cur.end - SEAM_DUR / 2, SEAM_DUR))];
    if (cur.chapter_at != null) return [cur.chapter_from, cur.chapter, ease.inOut(prog(t, cur.chapter_at, M.chapter_dur))];
    return [cur.chapter, cur.chapter, 0];
  }
  /* Копия трекера в сцене — элемент с id «chapter»: пока она видна, подписи трекера каркаса погашены,
     иначе две подписи разного растра двоятся (урок прошлого ролика). */
  var chapterEls = null, trLabs = null;
  function chapterShown(t) {
    if (!chapterEls) chapterEls = FILM.elements.filter(function (e) { return !e.part && /--chapter$/.test(e.dom); });
    return chapterEls.some(function (e) {
      var ev = null;
      for (var i = 0; i < e.events.length; i++) if (e.events[i].t <= t) ev = e.events[i];
      return ev ? ev.type === 'show' : e.initial > 0;
    });
  }
  function chapterIndex(id) { for (var k = 0; k < FILM.chapters.length; k++) if (FILM.chapters[k].id === id) return k; return -1; }
  function renderTracker(t) {
    if (!trOn.length) return;
    if (!trLabs) trLabs = [].slice.call(document.querySelectorAll('.tr-lab'));
    var labOp = chapterShown(t) ? '0' : '1';
    trLabs.forEach(function (n) { setStyle(n, 'opacity', labOp); });
    var st = trackerState(t), a = chapterIndex(st[0]), b = chapterIndex(st[1]), p = st[2];
    var act = p < 0.5 ? a : b, ps = trackerPulse(t);
    trPlq.forEach(function (n, k) {
      setStyle(n, 'transform', k === act && ps !== 1 ? 'scale(' + ps.toFixed(5) + ')' : 'none');
    });
    if (a < 0 || b < 0) {          // одна из сторон без активной плашки — наплыв
      trOn.forEach(function (n, k) {
        var on = (1 - p) * (k === a ? 1 : 0) + p * (k === b ? 1 : 0);
        setStyle(n, 'opacity', on.toFixed(3)); setStyle(n, 'clipPath', 'none');
      });
      return;
    }
    // заливка едет: отрезок [x0, x1] между плашками; каждая плашка показывает свою часть заливки
    var x0 = lerp(trBox[a][0], trBox[b][0], p), x1 = lerp(trBox[a][0] + trBox[a][1], trBox[b][0] + trBox[b][1], p);
    trOn.forEach(function (n, k) {
      var l = trBox[k][0], r = l + trBox[k][1], il = Math.max(l, x0), ir = Math.min(r, x1);
      if (ir - il < 0.5) { setStyle(n, 'opacity', '0.000'); setStyle(n, 'clipPath', 'none'); return; }
      setStyle(n, 'opacity', '1.000');
      var cl = il - l, cr = r - ir;
      setStyle(n, 'clipPath', cl < 0.05 && cr < 0.05 ? 'none' : 'inset(0px ' + cr.toFixed(2) + 'px 0px ' + cl.toFixed(2) + 'px)');
    });
  }

  // ---------------------------------------------------------------- голос внизу кадра
  /* У каждого голоса из project.json voice_bars — полоски громкости по огибающей реплики и подпись.
     У говорящего подпись темнеет и полоски его цвета живут, у молчащего — цвет «mute» и точки. */
  var voice = {}, VOICE_LAG = [0, 2, 4];
  function initVoice() {
    (FILM.voice.ids || []).forEach(function (id) {
      var g = document.getElementById('vo-' + id);
      if (g) voice[id] = { g: g, name: g.querySelector('.vo-name'), bars: [].slice.call(g.querySelectorAll('.vo-bar')) };
    });
  }
  function voiceLevel(r, t, lag) {        // огибающая реплики 0…1 в кадре t − lag, сглажено по 3 кадрам
    var i = Math.floor((t - r.start) * FPS) - lag, sum = 0, n = 0;
    for (var k = i - 2; k <= i; k++) if (k >= 0 && k < r.mouth.length) { sum += +r.mouth.charAt(k); n++; }
    return n ? sum / n / 9 : 0;
  }
  function renderVoice(t) {
    var V = FILM.voice;
    Object.keys(voice).forEach(function (id) {
      var v = voice[id], on = 0, cur = null;
      FILM.replies.forEach(function (r) {
        if (r.voice !== id || r.silent) return;      // немая строка — опора времени: голос не говорит, подпись не горит
        var w = Math.min(prog(t, r.start - 0.15, 0.2), 1 - prog(t, r.end, 0.25));
        if (w > on) { on = w; cur = r; }
      });
      var mute = hexRgb(V.mute);
      setStyle(v.name, 'color', mixRgb(mute, hexRgb(V.ink), on));
      setStyle(v.g, 'color', mixRgb(mute, hexRgb(V.colors[id]), on));
      setAttr(v.g, 'data-on', on.toFixed(3));
      v.bars.forEach(function (b, k) {
        var lv = cur && on > 0 ? on * voiceLevel(cur, t, VOICE_LAG[k % VOICE_LAG.length]) : 0;
        setStyle(b, 'height', (V.min + (V.max - V.min) * lv).toFixed(2) + 'px');
      });
    });
  }
  /* Сцена без каркаса (storyboard "frame": false): общая часть каркаса #frame-global (трекер, линии, футер,
     голос) гаснет в ней и наплывает обратно на стыке со сценой с каркасом (± SEAM_HALF, как стиль). */
  var frameGlobal = null;
  function framedAt(i) { return FILM.scenes[i].frame !== false; }
  function frameWeight(t) {
    var s = FILM.scenes;
    for (var k = 1; k < s.length; k++) {
      var b = s[k].start;
      if (Math.abs(t - b) < SEAM_HALF && framedAt(k - 1) !== framedAt(k))
        return lerp(framedAt(k - 1) ? 1 : 0, framedAt(k) ? 1 : 0, ease.inOut(prog(t, b - SEAM_HALF, 2 * SEAM_HALF)));
    }
    return framedAt(sceneAt(t)) ? 1 : 0;
  }
  function renderFrame(t) {
    if (FILM.frame_mixed) {
      if (!frameGlobal) frameGlobal = document.getElementById('frame-global');
      if (frameGlobal) setStyle(frameGlobal, 'opacity', frameWeight(t).toFixed(3));
    }
    FILM.scenes.forEach(function (sc, i) {
      var f = frameEls[sc.id];
      if (f.title) setStyle(f.title, 'opacity', titleWeight(i, t).toFixed(3));
      if (f.num) setStyle(f.num, 'opacity', numWeight(i, t).toFixed(3));
    });
    renderTracker(t);
    renderVoice(t);
  }

  // ---------------------------------------------------------------- геометрия (промер DOM)
  /* Узел — элемент (.el) или его часть ([data-part]). Движению нужны рамки без трансформаций:
     своя (L), своего текста (S, для fit text) и целей. Промер — один раз, когда шрифты загружены
     (до того — заново на каждом кадре): трансформации на время промера снимаются. */
  var NODES = [], geom = null;
  function rel(r, o) { return { x: r.left - o[0], y: r.top - o[1], w: r.width, h: r.height }; }
  function textNodes(n) {
    var w = document.createTreeWalker(n, NodeFilter.SHOW_TEXT, null), out = [], x;
    while ((x = w.nextNode())) if (x.nodeValue.length) out.push(x);
    return out;
  }
  function textRange(n, sub, nth) {   // Range подстроки sub (вхождение nth) в тексте узла; без sub — весь текст
    var tn = textNodes(n);
    if (!tn.length) return null;
    var whole = tn.map(function (x) { return x.nodeValue; }).join(''), from = 0, to = whole.length;
    if (sub != null) {
      var at = -1;
      for (var k = 0; k < (nth || 1); k++) { at = whole.indexOf(sub, at + 1); if (at < 0) break; }
      if (at < 0) throw new Error('move: в #' + n.id + ' нет подстроки «' + sub + '» (вхождение ' + (nth || 1) + ')');
      from = at; to = at + sub.length;
    } else {
      while (from < to && /\s/.test(whole.charAt(from))) from++;
      while (to > from && /\s/.test(whole.charAt(to - 1))) to--;
    }
    // края — внутри текстовых узлов: край на стыке двух узлов захватил бы рамку строки чужого inline-block
    var rg = document.createRange(), pos = 0, sSet = false, eSet = false;
    tn.forEach(function (x) {
      var len = x.nodeValue.length;
      if (!sSet && from < pos + len) { rg.setStart(x, from - pos); sSet = true; }
      if (!eSet && to > pos && to <= pos + len) { rg.setEnd(x, to - pos); eSet = true; }
      pos += len;
    });
    return rg;
  }
  function measure() {
    var saved = NODES.map(function (nd) { var s = nd.node.style.transform; nd.node.style.transform = 'none'; return s; });
    var o = rootXY(), g = { nodes: [], dest: {} };
    NODES.forEach(function (nd, i) {
      var L = rel(nd.node.getBoundingClientRect(), o), S = L, fontPx = 0, color = null;
      if (nd.moves.length || nd.flash) {
        var rg = textRange(nd.node);
        if (rg) {
          S = rel(rg.getBoundingClientRect(), o);
          fontPx = parseFloat(getComputedStyle(textNodes(nd.node)[0].parentNode).fontSize);
        }
        color = getComputedStyle(nd.node).color;
        if (nd.flash && !rg) throw new Error('emph flash: у #' + nd.node.id + ' нет текста — вспышка цвета только у надписи');
        nd.moves.forEach(function (mv, j) {
          var d = mv.dest, key = i + ':' + j, D;
          if (d.kind === 'box') D = { x: d.box[0], y: d.box[1], w: d.box[2], h: d.box[3] };
          else {
            var tn = document.getElementById(d.dom);
            if (!tn) throw new Error('move: нет цели #' + d.dom);
            D = d.kind === 'el' ? rel(tn.getBoundingClientRect(), o) : rel(textRange(tn, d.sub, d.nth).getBoundingClientRect(), o);
          }
          var pd = d.pad || [0, 0, 0, 0];
          D = { x: D.x - pd[0], y: D.y - pd[1], w: D.w + pd[0] + pd[2], h: D.h + pd[1] + pd[3] };
          g.dest[key] = D;
        });
      }
      g.nodes.push({ L: L, S: S, fontPx: fontPx, color: color });
    });
    NODES.forEach(function (nd, i) { nd.node.style.transform = saved[i]; });
    g.final = window.StageFonts.all();      // пока начертания страницы не пришли, геометрия мерится заново (lib/fonts.js)
    return g;
  }
  function G() { if (!geom || !geom.final) geom = measure(); return geom; }

  // ---------------------------------------------------------------- элементы
  var ANIM_DUR = M.anim_dur;
  var LIFT_PX = M.lift_in * FILM.px;
  var p2in = powerEase(M.ease_in), p2out = powerEase(M.ease_out), p2io = powerEase('power2.inOut'), p1io = powerEase('power1.inOut');
  /* Рамки элементов — на целые пиксели: каждый край округляется порознь, ширина — разность
     округлённых краёв (общий край остаётся стык в стык, строка у края не ложится полосой сглаживания). */
  function snapBoxes() {
    var list = document.querySelectorAll('#content .el');
    for (var i = 0; i < list.length; i++) {
      var st = list[i].style;
      ['left', 'top'].forEach(function (k, j) {
        var a = parseFloat(st[k]), size = parseFloat(st[j ? 'height' : 'width']);
        if (isNaN(a)) return;
        var a2 = Math.round(a);
        st[k] = a2 + 'px';
        if (!isNaN(size)) st[j ? 'height' : 'width'] = (Math.round(a + size) - a2) + 'px';
      });
    }
  }
  function initElements() {
    snapBoxes();
    FILM.elements.forEach(function (e) {
      var host = document.getElementById(e.dom), n = host;
      if (!host) throw new Error('Нет элемента #' + e.dom);
      if (e.part) {
        n = host.querySelector('[data-part="' + e.part + '"]');
        if (!n) throw new Error('У #' + e.dom + ' нет части data-part="' + e.part + '"');
      }
      n.style.transformOrigin = '0 0';
      var nd = { e: e, node: n, moves: e.moves, flash: e.emph.some(function (em) { return em.style === 'flash'; }) };
      /* Движение стиля (style.json motion, styles/README.md «Движение»). Иконка (svg без текста, не спутник):
         icon_step_frames, icon_overshoot. Любой узел сцены стиля (плашка, надпись целиком, часть): step_frames —
         форма «на N», grid_px — сдвиг по сетке, overshoot — перелёт входа, move_overshoot — перелёт move,
         jitter_px — дрожь рисунка. Непрозрачность всегда плавная; текст двигается только целиком. */
      var sm = styleMotion(e.scene);
      if (sm) {
        var icon = !e.part && !e.follow && n.querySelector('svg') && !textNodes(n).some(function (x) { return /\S/.test(x.nodeValue); });
        nd.sm = {
          step: Math.max(sm.step_frames || 1, icon ? sm.icon_step_frames || 1 : 1),
          over: icon && sm.icon_overshoot ? sm.icon_overshoot : (sm.overshoot || 0),
          moveOver: sm.move_overshoot || 0, grid: sm.grid_px || 0, jitter: sm.jitter_px || 0,
          seed: hashStr(e.key || e.dom)
        };
        if (nd.sm.step <= 1 && !nd.sm.over && !nd.sm.moveOver && !nd.sm.grid && !nd.sm.jitter) delete nd.sm;
      }
      NODES.push(nd);
    });
    initShadeText();
  }
  /* Тень насыщенного блока: у целого элемента, чью рамку не меньше чем наполовину покрывает заливка
     цвета tokens.json kinds.shade_text.fill, надписи (.t) идут множителем к его непрозрачности o:
     0 до lo (тень), 1 с hi, линейно между. Светлый текст на насыщенной заливке в тени иначе читается. */
  var SH = FILM.shade, shadeText = [];
  function initShadeText() {
    if (!SH) return;
    var want = hexRgb(SH.fill);
    NODES.forEach(function (nd, i) {
      if (nd.e.part) return;
      var el = nd.node, r = el.getBoundingClientRect(), area = r.width * r.height, cov = 0;
      if (!area) return;
      [el].concat([].slice.call(el.querySelectorAll('*'))).forEach(function (n) {
        if (n instanceof SVGElement) return;
        var c = /rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)(?:,\s*([\d.]+))?/.exec(getComputedStyle(n).backgroundColor || '');
        if (c && (c[4] == null || +c[4] === 1) && +c[1] === want[0] && +c[2] === want[1] && +c[3] === want[2]) {
          var q = n.getBoundingClientRect(); cov += q.width * q.height;
        }
      });
      if (cov < 0.5 * area) return;
      var texts = [].slice.call(el.querySelectorAll('.t'));
      if (texts.length) shadeText.push({ i: i, texts: texts });
    });
  }
  function renderShadeText() {
    shadeText.forEach(function (b) {
      var o = parseFloat(NODES[b.i].node.style.opacity) || 0, m = clamp01((o - SH.lo) / (SH.hi - SH.lo));
      var v = m >= 0.999 ? 'none' : 'opacity(' + m.toFixed(3) + ')';
      b.texts.forEach(function (tn) { setStyle(tn, 'filter', v); });
    });
  }
  // видимость по show/hide: {o, y, s, clip}; over — перелёт входа стиля (0 — как в ядре)
  function backEase(c) { var c3 = c + 1; return function (x) { return 1 + c3 * Math.pow(x - 1, 3) + c * Math.pow(x - 1, 2); }; }
  function visState(e, t, over) {
    var st = { o: e.initial, y: 0, s: 1, clip: 0 };
    var ev = null;
    for (var i = 0; i < e.events.length; i++) if (e.events[i].t <= t) ev = e.events[i];
    if (!ev) return st;
    var anim = ev.anim || 'rise', d = ev.dur != null ? ev.dur : (ANIM_DUR[anim] != null ? ANIM_DUR[anim] : 0.5), p = prog(t, ev.t, d);
    if (ev.type === 'show') {
      var q = over ? backEase(over)(p) : ease.out(p);
      st.o = clamp01(p * 1.6);
      if (anim === 'rise') st.y = lerp(M.rise_px, 0, q);
      if (anim === 'pop') st.s = lerp(0.82, 1, over ? backEase(over)(p) : ease.back(p));
      if (anim === 'wipe') { st.o = 1; st.clip = 1 - q; }
      if (anim === 'lift') { st.o = p2out(p); st.y = LIFT_PX * (1 - p2out(p)); }
      if (anim === 'cut') st.o = 1;
      if (anim === 'draw') st.o = clamp01(p * 4);
    } else {
      st.o = 1 - ease.inOut(p);
      if (anim === 'lift') { st.o = 1 - p2in(p); st.y = -LIFT_PX * p2in(p); }
      if (anim === 'cut') st.o = 0;
    }
    return st;
  }
  // уровень непрозрачности (тень / приглушён / чернила) — множитель к видимости
  function levelAt(e, t) {
    var prev = null, from = 1;
    for (var i = 0; i < e.levels.length; i++) {
      var lv = e.levels[i];
      if (lv.t > t) break;
      var f = prev ? valueAt(prev, from, lv.t) : 1;      // старт — с того значения, куда успел доехать предыдущий
      prev = lv; from = f;
    }
    return prev ? valueAt(prev, from, t) : 1;
  }
  function valueAt(lv, from, t) { return lerp(from, lv.value, powerEase(lv.ease)(prog(t, lv.t, lv.dur))); }
  function moveTarget(nd, g, i, j) {
    var mv = nd.moves[j], gn = g.nodes[i], L = gn.L, D = g.dest[i + ':' + j];
    var S = mv.fit === 'text' ? gn.S : L, kx = 1, ky = 1;
    if (mv.fit === 'text') kx = ky = (mv.size && gn.fontPx) ? (mv.size * FILM.px / 72) / gn.fontPx : D.h / S.h;
    else if (mv.fit === 'box') { kx = D.w / S.w; ky = D.h / S.h; }
    var px_ = S.x + mv.self[0] * S.w, py_ = S.y + mv.self[1] * S.h;
    var qx = D.x + mv.anchor[0] * D.w + mv.dx, qy = D.y + mv.anchor[1] * D.h + mv.dy;
    return { kx: kx, ky: ky, dx: qx - L.x - kx * (px_ - L.x), dy: qy - L.y - ky * (py_ - L.y),
             col: mv.color ? hexRgb(mv.color) : null };
  }
  function chainAt(nd, g, i, count, t) {   // состояние после первых count движений к моменту t
    var st = { kx: 1, ky: 1, dx: 0, dy: 0, col: cssRgb(g.nodes[i].color) };
    var j = -1;
    for (var k = 0; k < count; k++) if (nd.moves[k].t <= t) j = k;
    if (j < 0) return st;
    var mv = nd.moves[j], a = chainAt(nd, g, i, j, mv.t), b = moveTarget(nd, g, i, j);
    var p = (nd.sm && nd.sm.moveOver ? backEase(nd.sm.moveOver) : powerEase(mv.ease))(prog(t, mv.t, mv.dur));
    return { kx: lerp(a.kx, b.kx, p), ky: lerp(a.ky, b.ky, p), dx: lerp(a.dx, b.dx, p), dy: lerp(a.dy, b.dy, p),
             col: b.col ? [0, 1, 2].map(function (c) { return lerp(a.col[c], b.col[c], p); }) : a.col };
  }
  function tiltAt(nd, t) {     // наклон в полёте: к середине пути tilt, к посадке 0
    var r = 0;
    nd.moves.forEach(function (mv) {
      if (mv.tilt && t > mv.t && t < mv.t + mv.dur) r += mv.tilt * Math.sin(Math.PI * powerEase(mv.ease)(prog(t, mv.t, mv.dur)));
    });
    return r;
  }
  // дыхание в фокусе: масштаб 1 → 1 + amp → 1 с периодом breathe.period, вход и выход breathe.edge
  var BREATH_PERIOD = M.breathe.period, BREATH_EDGE = M.breathe.edge;
  function breathAt(em, t) {
    if (t <= em.t || t >= em.until + BREATH_EDGE) return 0;
    var env = Math.min(ease.inOut(prog(t, em.t, BREATH_EDGE)), 1 - ease.inOut(prog(t, em.until, BREATH_EDGE)));
    return em.amp * env * (0.5 - 0.5 * Math.cos(2 * Math.PI * (t - em.t) / BREATH_PERIOD));
  }
  // звон: качание вокруг верхней точки −1, +11/14, −1/2, +3/14, 0 (доли амплитуды), сглаженно
  var RING = [0, -1, 11 / 14, -0.5, 3 / 14, 0];
  function ringAngle(x) {
    if (x <= 0 || x >= 1) return 0;
    var f = x * 5, k = Math.floor(f), u = f - k;
    return lerp(RING[k], RING[k + 1], u * u * (3 - 2 * u));
  }
  function mul(m, n) {         // матрица [a,b,c,d,e,f]: x' = a x + c y + e, y' = b x + d y + f
    return [m[0] * n[0] + m[2] * n[1], m[1] * n[0] + m[3] * n[1], m[0] * n[2] + m[2] * n[3], m[1] * n[2] + m[3] * n[3],
            m[0] * n[4] + m[2] * n[5] + m[4], m[1] * n[4] + m[3] * n[5] + m[5]];
  }
  function T(x, y) { return [1, 0, 0, 1, x, y]; }
  var I6 = [1, 0, 0, 1, 0, 0];
  /* Спутники: подчёркивание, иконка у строки, точка легенды едут со своей надписью ВСЁ время привязки,
     а не разово. Узел со списком follow ([{t, dur, ease, host}], сборка) берёт трансформацию хозяина —
     его move, пульс, дыхание, звон, подъём — и кладёт поверх своей: M = T(−Ls) · A_host · T(Ls) · M_own.
     Свой сдвиг входа и ухода спутник не берёт — едет сдвигом хозяина; непрозрачность, свои move и emph — свои.
     Смена хозяина перетекает за время move. Спутники считаются после всех остальных узлов. */
  function lerp6(a, b, p) { return a.map(function (v, k) { return lerp(v, b[k], p); }); }
  function hostMatrix(nd, t, A) {
    var fl = nd.e.follow, cur = -1;
    for (var k = 0; k < fl.length; k++) if (fl[k].t == null || fl[k].t <= t) cur = k;
    if (cur < 0) return I6;
    var b = fl[cur], H = b.host ? (A[b.host] || I6) : I6;
    if (b.t != null && b.dur > 0 && t < b.t + b.dur) {
      var a = cur > 0 && fl[cur - 1].host ? (A[fl[cur - 1].host] || I6) : I6;
      H = lerp6(a, H, powerEase(b.ease)(prog(t, b.t, b.dur)));
    }
    return H;
  }
  function flipAngle(e, t) {   // разворот: до бита элемент зеркален, за dur смотрит прямо
    var a = 0;
    e.emph.forEach(function (em) { if (em.style === 'flip') a += 180 * (1 - p2io(prog(t, em.t, em.dur))); });
    return a % 360;
  }
  var drawShapes = new Map();
  function drawProgress(e, t) {
    var ev = null;
    for (var i = 0; i < e.events.length; i++) if (e.events[i].t <= t) ev = e.events[i];
    if (!ev || ev.type !== 'show' || ev.anim !== 'draw') return 1;
    return p2out(prog(t, ev.t, ANIM_DUR.draw));
  }
  function renderDraw(nd, t) {
    if (!nd.e.events.some(function (ev) { return ev.anim === 'draw'; })) return;
    var sh = drawShapes.get(nd.node);
    if (!sh) {
      sh = [].slice.call(nd.node.querySelectorAll('path, line, polyline, polygon, circle, ellipse, rect'));
      sh.forEach(function (s) { s.setAttribute('pathLength', '1'); });
      drawShapes.set(nd.node, sh);
    }
    var q = drawProgress(nd.e, t);
    sh.forEach(function (s) {
      setStyle(s, 'strokeDasharray', q >= 1 ? 'none' : '1 1');
      setStyle(s, 'strokeDashoffset', q >= 1 ? '0' : (1 - q).toFixed(4));
    });
  }
  var FLASH_IN = 0.15 / 1.55, FLASH_HOLD = 0.80 / 1.55;     // вспышка цвета: доли входа и удержания
  function flashMix(em, t) {
    var x = t - em.t, a = em.dur * FLASH_IN, h = em.dur * FLASH_HOLD, b = em.dur - a - h;
    if (x <= 0 || x >= em.dur) return 0;
    if (x < a) return p2out(x / a);
    if (x < a + h) return 1;
    return 1 - p1io((x - a - h) / b);
  }
  function renderElements(t) {
    var g = G(), A = {};
    NODES.forEach(function (nd, i) { if (!nd.e.follow) renderNode(nd, i, t, g, A); });
    NODES.forEach(function (nd, i) { if (nd.e.follow) renderNode(nd, i, t, g, A); });
  }
  function renderNode(nd, i, t0, g, A) {
    if (nd.e.hidden) {          // films/<f>.json "hide": элемент варианта ролика не виден ни в одном кадре
      setStyle(nd.node, 'opacity', '0.000'); setStyle(nd.node, 'visibility', 'hidden');
      return;
    }
    // декоративный узел стиля: форма — по ступенчатому времени, непрозрачность — по настоящему (без мигания)
    var SM = nd.sm, t = SM ? stepTime(t0, SM.step) : t0;
    var e = nd.e, n = nd.node, gn = g.nodes[i], st = visState(e, t, SM ? SM.over : 0);
    if (SM) st.o = visState(e, t0).o;
    var o = st.o * levelAt(e, t0);
    setStyle(n, 'opacity', o.toFixed(3));
    setStyle(n, 'visibility', o > 0.001 ? 'visible' : 'hidden');
    var mv = nd.moves.length ? chainAt(nd, g, i, nd.moves.length, t) : null;
    var kx = mv ? mv.kx : 1, ky = mv ? mv.ky : 1, dx = mv ? mv.dx : 0, dy = mv ? mv.dy : 0;
    var w = gn.L.w, h = gn.L.h;
    var s = st.s, rot = 0, spin = 0;
    e.emph.forEach(function (em) {
      var x = prog(t, em.t, em.dur);
      if (em.style === 'ring') rot += em.amp * ringAngle(x);
      else if (em.style === 'spin') { if (x > 0 && x < 1) spin += (em.dir || 1) * 360 * p2io(x); }
      else if (em.style === 'breathe') s *= 1 + breathAt(em, t);
      else if (em.style === 'flip' || em.style === 'flash') return;
      else s *= 1 + Math.min(em.amp, 24 / Math.max(1, w * kx)) * Math.sin(Math.PI * x);   // пульс: рост ≤ 24 px
    });
    var Mx = [kx, 0, 0, ky, dx, dy];
    var cx = dx + kx * w / 2, cy = dy + ky * h / 2;
    if (s !== 1) Mx = mul(mul(mul(T(cx, cy), [s, 0, 0, s, 0, 0]), T(-cx, -cy)), Mx);
    var tl = (nd.moves.length ? tiltAt(nd, t) : 0) + spin;
    if (tl) {
      var ta = tl * Math.PI / 180;
      Mx = mul(mul(mul(T(cx, cy), [Math.cos(ta), Math.sin(ta), -Math.sin(ta), Math.cos(ta), 0, 0]), T(-cx, -cy)), Mx);
    }
    if (rot) {
      var top = cy - s * ky * h / 2, a = rot * Math.PI / 180;
      Mx = mul(mul(mul(T(cx, top), [Math.cos(a), Math.sin(a), -Math.sin(a), Math.cos(a), 0, 0]), T(-cx, -top)), Mx);
    }
    if (e.follow) {            // спутник: сдвиг входа — хозяина, поверх — трансформация хозяина
      var Ls = gn.L;
      Mx = mul(mul(mul(T(-Ls.x, -Ls.y), hostMatrix(nd, t, A)), T(Ls.x, Ls.y)), Mx);
    } else Mx = mul(T(0, st.y), Mx);
    if (SM && !e.follow && (SM.jitter || SM.grid)) {      // дрожь рисунка (сид — узел и номер рисунка) и сдвиг по сетке
      if (SM.jitter) {
        var jr = mulberry32(SM.seed + Math.floor(frameOf(t0) / SM.step) * 7919);
        Mx[4] += (jr() * 2 - 1) * SM.jitter; Mx[5] += (jr() * 2 - 1) * SM.jitter;
      }
      if (SM.grid) {                         // позиция узла (его левый верхний угол) — на сетку grid_px
        Mx[4] = Math.round((gn.L.x + Mx[4]) / SM.grid) * SM.grid - gn.L.x;
        Mx[5] = Math.round((gn.L.y + Mx[5]) / SM.grid) * SM.grid - gn.L.y;
      }
    }
    if (!e.part) A[e.dom] = mul(mul(T(gn.L.x, gn.L.y), Mx), T(-gn.L.x, -gn.L.y));
    var tf = 'matrix(' + Mx.map(function (v) { return v.toFixed(5); }).join(',') + ')';
    var fa = e.emph.length ? flipAngle(e, t) : 0;
    if (fa > 0.001) tf += ' translate(' + (w / 2).toFixed(2) + 'px,' + (h / 2).toFixed(2) + 'px) perspective('
      + (4 * Math.max(w, h)).toFixed(1) + 'px) rotateY(' + fa.toFixed(3) + 'deg) translate(' + (-w / 2).toFixed(2) + 'px,'
      + (-h / 2).toFixed(2) + 'px)';
    setStyle(n, 'transform', tf);
    setStyle(n, 'clipPath', st.clip > 0 ? 'inset(0 ' + (st.clip * 100).toFixed(2) + '% 0 0)' : 'none');
    renderDraw(nd, t);
    var col = mv && mv.col && nd.moves.some(function (m) { return m.color; }) ? mv.col : null;
    if (nd.flash) {
      var base = col || cssRgb(gn.color), mix = 0, fc = null;
      e.emph.forEach(function (em) { if (em.style === 'flash') { var k = flashMix(em, t); if (k > mix) { mix = k; fc = hexRgb(em.color); } } });
      col = fc ? [0, 1, 2].map(function (c) { return lerp(base[c], fc[c], mix); }) : base;
    }
    if (col) setStyle(n, 'color', 'rgb(' + col.map(function (c) { return Math.round(c); }).join(',') + ')');
  }

  function replyAt(t) {
    var r = FILM.replies;
    for (var i = 0; i < r.length; i++) if (t >= r[i].start && t < r[i].end) return r[i];
    return null;
  }

  // ---------------------------------------------------------------- плагины
  var API = { prog: prog, lerp: lerp, clamp01: clamp01, powerEase: powerEase, mulberry32: mulberry32,
              setStyle: setStyle, setAttr: setAttr, sceneAt: sceneAt,
              frameOf: frameOf, stepTime: stepTime, styleAt: styleAt, styleWeight: styleWeight,
              styleConfig: styleConfig, styleScenes: styleScenes, addLayer: addLayer, sceneWeight: sceneWeight,
              styleOpacity: styleOpacity };
  var PLUGINS = (window.StagePlugins || []).map(function (f) { return f(FILM, API); });

  // ---------------------------------------------------------------- текст не из DOM (проверка читаемости V37)
  /* Надпись, нарисованную на canvas (или иначе мимо .t), проверка сама не найдёт: сцена объявляет её области.
     window.__textRects(t) → [{id, rect: [x, y, w, h], text, opacity}] — рамка каждой строки в px кадра (плотно по
     строке), t — секунды фильма; opacity (0…1, без поля — 1) — насколько строка видна: мерится только видимая
     на 1,0. Объявить можно двумя путями, они складываются: сцена до stage.js пишет window.__textRects = function (t) {…};
     плагин сцены (window.StagePlugins) возвращает метод textRects(t) — так у каждой сцены свои области.
     Промер зовёт функцию в каждом кадре полосы после render(t). */
  var declaredTextRects = typeof window.__textRects === 'function' ? window.__textRects : null;
  window.__textRects = function (t) {
    var out = declaredTextRects ? (declaredTextRects(t) || []).slice() : [];
    PLUGINS.forEach(function (p) { if (p && typeof p.textRects === 'function') out = out.concat(p.textRects(t) || []); });
    return out;
  };

  // ---------------------------------------------------------------- кадр целиком
  function render(t) {
    t = Math.max(0, Math.min(FILM.duration, t));
    renderFrame(t);
    renderElements(t);
    renderShadeText();
    PLUGINS.forEach(function (p) { if (p && p.render) p.render(t); });
    var root = document.getElementById('root');
    setAttr(root, 'data-scene', FILM.scenes[sceneAt(t)].id);
    setAttr(root, 'data-style', styleAt(t) || '');
    var rep = replyAt(t);
    setAttr(root, 'data-reply', rep ? String(rep.num) : '');
  }
  initFrame(); initElements(); initVoice();
  render(0);

  // ---------------------------------------------------------------- связь с HyperFrames
  /* Кусок фильма (рендер по частям): window.__CHUNK__ = {frame0, frames}. Страница куска длится frames
     кадров; её кадр j — кадр frame0 + j фильма, время — тем же делением номера кадра на fps, что у
     HyperFrames: кадр куска совпадает с кадром цельного рендера бит в бит. */
  var CHUNK = window.__CHUNK__ || null;
  var LEN = CHUNK ? CHUNK.frames / FPS : FILM.duration;
  function filmTime(v) { return CHUNK ? (CHUNK.frame0 + Math.round(v * FPS)) / FPS : v; }
  var lastT = 0;
  var clock = { t: function (v) { if (arguments.length) { lastT = v; render(filmTime(v)); return; } return lastT; } };
  var tl = gsap.timeline({ paused: true });
  tl.fromTo(clock, { t: 0 }, { t: LEN, duration: LEN, ease: 'none' }, 0);
  window.__timelines = window.__timelines || {};
  window.__timelines.main = tl;
  window.__stage = { render: render, film: FILM, sceneAt: sceneAt, plugins: PLUGINS };
})();
