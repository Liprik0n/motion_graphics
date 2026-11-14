/* Плагин glitch — помехи на картинке элемента сцены («сигнал прервался»): разрыв строк (полосы кадра
   сдвигаются вбок), сдвиг каналов (красный и синий расходятся), дрожь всего кадра. Включается полем раскадровки
   plugins.glitch (engine/video/plugins/README.md): окно from…to, зерно seed и числа помех — все из раскадровки
   или tokens.json motion.glitch, запасных чисел в коде нет.

   Детерминизм (закон 1): вспышки помех расписаны один раз от seed, рисунок кадра — генератор от seed и НОМЕРА
   кадра (без остатка от деления); ни Math.random, ни времени, ни памяти прошлого кадра — кадры рендерятся
   кусками в любом порядке. Вспышки: между началами — не меньше burst_gap[0] с; check.py V27 считает их по
   пикселям (не больше legibility.flash_max_per_sec в секунду, WCAG 2.3.1).

   Рисует холст поверх элемента-источника (по умолчанию «start-image» — картинка-кадр сцены) в том же слое:
   выше картинки, ниже остального содержания сцены; трансформация и непрозрачность — источника. Пиксели
   картинки не читаются (getImageData не нужен): каналы разводятся наложением multiply / lighter. */
(window.StagePlugins = window.StagePlugins || []).push(function (FILM, api) {
  'use strict';
  var FPS = FILM.fps, items = [];
  FILM.scenes.forEach(function (sc) {
    var c = (sc.plugins || {}).glitch;
    if (!c) return;
    var src = document.getElementById(sc.id + '--' + c.source);
    if (!src) throw new Error('glitch: нет элемента #' + sc.id + '--' + c.source);
    var img = src.querySelector('img');
    if (!img) throw new Error('glitch: в #' + src.id + ' нет картинки (тег img) — помехам нечего рвать');
    var W = Math.round(parseFloat(src.style.width)), H = Math.round(parseFloat(src.style.height));
    var cv = document.createElement('canvas');
    cv.width = W; cv.height = H;
    cv.className = 'glitch-canvas';
    cv.setAttribute('data-glitch', sc.id);
    cv.style.cssText = 'position:absolute;left:' + src.style.left + ';top:' + src.style.top + ';width:' + W + 'px;height:' +
      H + 'px;z-index:1;pointer-events:none;visibility:hidden;transform-origin:0 0;';
    src.parentNode.insertBefore(cv, src.nextSibling);
    // расписание вспышек: кадры [начало, конец) — один раз от seed
    var rs = api.mulberry32(c.seed | 0), bursts = [];
    var f = api.frameOf(c.from + rs() * c.burst_gap[0]), fEnd = api.frameOf(c.to);
    while (f < fEnd) {
      var n = c.burst_frames[0] + Math.floor(rs() * (c.burst_frames[1] - c.burst_frames[0] + 1));
      bursts.push([f, f + n]);
      f += n + Math.max(1, Math.round((c.burst_gap[0] + rs() * (c.burst_gap[1] - c.burst_gap[0])) * FPS) - n);
    }
    items.push({ sc: sc, c: c, src: src, img: img, cv: cv, ctx: cv.getContext('2d'), W: W, H: H, bursts: bursts, ready: false });
  });
  if (!items.length) return null;

  function layer(it) { var x = document.createElement('canvas'); x.width = it.W; x.height = it.H; return x; }
  function prepare(it) {               // каналы картинки — один раз, когда она загружена
    if (it.ready) return true;
    if (!it.img.complete || !it.img.naturalWidth) return false;
    it.chan = ['#ff0000', '#00ff00', '#0000ff'].map(function (col) {
      var x = layer(it), g = x.getContext('2d');
      g.drawImage(it.img, 0, 0, it.W, it.H);
      g.globalCompositeOperation = 'multiply';
      g.fillStyle = col;
      g.fillRect(0, 0, it.W, it.H);
      return x;
    });
    it.tmp = layer(it);
    it.ready = true;
    return true;
  }
  // сила помех 0…1 в кадре: вне окна 0; в окне — calm, во вспышке 1; края окна — рампа edge
  function power(it, t) {
    var c = it.c;
    if (t < c.from || t >= c.to) return 0;
    var env = c.edge > 0 ? Math.min(1, (t - c.from) / c.edge, (c.to - t) / c.edge) : 1;
    var fr = api.frameOf(t), v = c.calm;
    for (var i = 0; i < it.bursts.length; i++) if (fr >= it.bursts[i][0] && fr < it.bursts[i][1]) { v = 1; break; }
    return env * v;
  }
  function draw(it, t, k) {
    var c = it.c, W = it.W, H = it.H, g = it.ctx, fr = api.frameOf(t);
    var r = api.mulberry32((c.seed | 0) * 1000003 + fr * 7919);
    var jx = Math.round((r() * 2 - 1) * c.jitter_px * k), jy = Math.round((r() * 2 - 1) * c.jitter_px * k * 0.5);
    var sr = Math.round(c.rgb_px * k * (0.5 + 0.5 * r()));
    g.globalCompositeOperation = 'source-over';
    g.fillStyle = '#000000';
    g.fillRect(0, 0, W, H);
    g.globalCompositeOperation = 'lighter';
    g.drawImage(it.chan[0], jx + sr, jy);
    g.drawImage(it.chan[1], jx, jy);
    g.drawImage(it.chan[2], jx - sr, jy);
    g.globalCompositeOperation = 'source-over';
    var nb = Math.round((c.bands[0] + r() * (c.bands[1] - c.bands[0])) * k);
    if (nb > 0) {
      var tg = it.tmp.getContext('2d');
      tg.clearRect(0, 0, W, H);
      tg.drawImage(it.cv, 0, 0);
      for (var b = 0; b < nb; b++) {
        var y = Math.floor(r() * H), h = Math.max(1, Math.round(c.band_h[0] + r() * (c.band_h[1] - c.band_h[0])));
        var dx = Math.round((r() * 2 - 1) * c.tear_px * k);
        if (!dx) continue;
        g.drawImage(it.tmp, 0, y, W, h, dx, y, W, h);
        g.drawImage(it.tmp, 0, y, W, h, dx - (dx > 0 ? W : -W), y, W, h);     // разрыв заворачивается с края
      }
    }
  }
  function render(t) {
    items.forEach(function (it) {
      var k = power(it, t);
      var on = k > 0 && prepare(it);
      api.setStyle(it.cv, 'visibility', on ? 'visible' : 'hidden');
      if (!on) return;
      api.setStyle(it.cv, 'transform', it.src.style.transform || 'none');
      api.setStyle(it.cv, 'opacity', it.src.style.opacity || '1');
      draw(it, t, k);
    });
  }
  function probe(t) {
    return { plugin: 'glitch', items: items.map(function (it) {
      var k = power(it, t);
      return { scene: it.sc.id, power: Math.round(k * 1000) / 1000, drawn: k > 0 && it.ready,
               bursts: it.bursts.length };
    }) };
  }
  return { render: render, probe: probe };
});
