/* Плагин act — действия мира: метки раскадровки plugins.act.cues {id, t, who, do, motion?, …}.
   Сборка (build.py act_config) переводит t в секунды, кладёт числа motion из tokens.json motion.act в cue.m и длину
   действия в cue.span; неизвестное motion — отказ сборки. Здесь чисел движения нет.

   Исполнитель — тот, кто рисует мир (разметка сцены, стиль, марионетка, спрайт). Он регистрируется так:
     (window.ActExec = window.ActExec || []).push({scene: '<сцена>', who: '<id>', run: function (t, cues, api) {…}, node?});
   и рисует состояние своего who в момент t по ВСЕМ своим меткам (кадр — чистая функция t, закон 1): cues —
   метки этого who по времени, у каждой {cue, local: t − cue.t, p: доля 0…1 за span, e: доля по кривой m.ease}.
   Исполнитель меняет ВНУТРЕННОСТЬ узла who (дети, атрибуты, свой холст), но не стиль самого .el: непрозрачность и
   трансформацию .el ведут биты (закон 2 — одно свойство двигает один хозяин). node — узел, чьё изменение мерить,
   если who не элемент сцены (например, «world» стиля).

   who «cam» исполняет движок: камера сцены — три вложенные обёртки (#cam--<сцена> > .cam-float > .cam-shake,
   закон 4): сюжетное движение от положения к положению (рамки из разметки .cam-pos), парение (tokens.json
   motion.act.cam_drift: pct — размах в % кадра, period — период, с; без period парения нет), толчок — у любой метки,
   чьё motion несёт shake_px и shake_dur (удар, хлопок). Камера и элементы не делят свойство: обёртки — не .el.

   Промер (probe): у каждой метки — id, время, есть ли исполнитель, отпечаток узла who около метки (до и после
   действия: изменилось ли что-то видимое); у камеры — рамка мира в кадре и парение. Проверка — V31, V32. */
(window.StagePlugins = window.StagePlugins || []).push(function (FILM, api) {
  'use strict';
  var FPS = FILM.fps, F = 1 / FPS;
  var root = document.getElementById('root'), W = root.clientWidth, H = root.clientHeight;
  var scenes = [];
  FILM.scenes.forEach(function (sc) {
    var c = (sc.plugins || {}).act;
    if (!c) return;
    var it = { sc: sc, cues: c.cues, cam: null };
    if (c.camera) {
      var wrap = document.getElementById('cam--' + sc.id);
      if (!wrap) throw new Error('act: у сцены ' + sc.id + ' нет обёртки камеры #cam--' + sc.id);
      var cams = c.cues.filter(function (q) { return q.who === 'cam'; });
      var full = [0, 0, W, H], P = c.camera.pos;
      var start = c.camera.start ? P[c.camera.start] : full;
      var startRect = [];
      cams.forEach(function (q, k) { startRect.push(k ? camAt(cams, startRect, start, P, q.t, k) : start); });
      it.cam = { wrap: wrap, float: wrap.firstElementChild, shake: wrap.firstElementChild.firstElementChild,
                 cues: cams, startRect: startRect, start: start, P: P, drift: c.camera.drift || {},
                 shakes: c.cues.filter(function (q) { return q.m && q.m.shake_px && q.m.shake_dur; }) };
    }
    scenes.push(it);
  });
  if (!scenes.length) return null;

  function easeOf(m) { return api.powerEase(m && m.ease ? m.ease : 'none'); }
  function state(q, t) {
    var local = t - q.t, p = q.span > 0 ? api.clamp01(local / q.span) : (local >= 0 ? 1 : 0);
    return { cue: q, local: local, p: p, e: easeOf(q.m)(p) };
  }
  function lerpRect(a, b, e) { return [0, 1, 2, 3].map(function (k) { return api.lerp(a[k], b[k], e); }); }
  // рамка мира в кадре в момент t по первым n меткам камеры: каждая едет от того, где камера была в её начало
  function camAt(cams, startRect, start, P, t, n) {
    var r = start;
    for (var k = 0; k < n; k++) {
      var q = cams[k];
      if (q.t > t) break;
      r = lerpRect(startRect[k], P[q.to], state(q, t).e);
    }
    return r;
  }
  function renderCam(it, t) {
    var C = it.cam;
    var r = camAt(C.cues, C.startRect, C.start, C.P, t, C.cues.length), k = W / r[2];
    api.setStyle(C.wrap, 'transform', 'matrix(' + [k, 0, 0, k, -k * r[0], -k * r[1]].map(function (v) { return v.toFixed(5); }).join(',') + ')');
    var d = C.drift, dz = 0;
    if (d.pct && d.period) dz = d.pct / 100 * Math.sin(2 * Math.PI * t / d.period);   // парение: масштаб 1 ± pct %
    api.setStyle(C.float, 'transform', dz ? 'matrix(' + (1 + dz).toFixed(5) + ',0,0,' + (1 + dz).toFixed(5) + ',' +
      (-dz * W / 2).toFixed(3) + ',' + (-dz * H / 2).toFixed(3) + ')' : 'none');
    var sx = 0, sy = 0;
    C.shakes.forEach(function (q) {
      var local = t - q.t;
      if (local < 0 || local >= q.m.shake_dur) return;
      var fall = 1 - local / q.m.shake_dur, rnd = api.mulberry32(hash(q.id) + api.frameOf(t));   // зерно: метка и кадр
      sx += (rnd() * 2 - 1) * q.m.shake_px * fall; sy += (rnd() * 2 - 1) * q.m.shake_px * fall;
    });
    api.setStyle(C.shake, 'transform', sx || sy ? 'translate(' + sx.toFixed(3) + 'px,' + sy.toFixed(3) + 'px)' : 'none');
    C.now = { rect: r.map(function (v) { return Math.round(v * 100) / 100; }), drift: Math.abs(dz) * 100,
              shake: Math.round(Math.hypot(sx, sy) * 100) / 100 };
  }
  function hash(s) { var h = 2166136261; for (var i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return h | 0; }

  // исполнители: window.ActExec — всё, что разметка и стили положили до первого кадра (и после — читается заново)
  var execN = -1, execBy = {};
  function executors() {
    var list = window.ActExec || [];
    if (list.length !== execN) {
      execN = list.length; execBy = {};
      list.forEach(function (x) { (execBy[x.scene + '|' + x.who] = execBy[x.scene + '|' + x.who] || []).push(x); });
    }
    return execBy;
  }
  function render(t) {
    var by = executors();
    scenes.forEach(function (it) {
      if (it.cam) renderCam(it, t);
      var groups = {};
      it.cues.forEach(function (q) { if (q.who !== 'cam') (groups[q.who] = groups[q.who] || []).push(q); });
      Object.keys(groups).forEach(function (who) {
        (by[it.sc.id + '|' + who] || []).forEach(function (x) {
          x.run(t, groups[who].map(function (q) { return state(q, t); }), api);
        });
      });
    });
  }
  // отпечаток узла who: внутренность .el (её меняет исполнитель), у камеры — её трансформация
  function nodeOf(it, q) {
    if (q.who === 'cam') return it.cam ? it.cam.wrap : null;
    var x = (executors()[it.sc.id + '|' + q.who] || []).filter(function (e) { return e.node; })[0];
    return x ? x.node : document.getElementById(it.sc.id + '--' + q.who);
  }
  function sig(it, q) {
    var n = nodeOf(it, q);
    if (!n) return null;
    if (q.who === 'cam') return n.style.transform || 'none';
    var s = n.classList && n.classList.contains('el') ? n.innerHTML : n.outerHTML;
    return String(hash(s)) + ':' + s.length;
  }
  function probe(t) {
    var by = executors();
    return { plugin: 'act', items: scenes.map(function (it) {
      return { scene: it.sc.id, cam: it.cam ? it.cam.now || null : null,
        cues: it.cues.map(function (q) {
          var near = t >= q.t - 2 * F - 1e-6 && t <= q.t + q.span + 3 * F + 1e-6;
          return { id: q.id, t: q.t, who: q.who, do: q.do, span: q.span,
                   exec: q.who === 'cam' ? !!it.cam : !!(by[it.sc.id + '|' + q.who] || []).length,
                   sig: near ? sig(it, q) : null };
        }) };
    }) };
  }
  return { render: render, probe: probe };
});
