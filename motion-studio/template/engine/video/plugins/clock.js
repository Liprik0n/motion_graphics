/* Плагин clock — настенные часы на табло сцены: что показывали бы часы на стене в тот момент, когда кадр на экране.
   Сборка кладёт в данные base — секунды от полуночи (пояс project.json wall_clock.start) в кадр 0 куска:
   wall_clock.start + wall_clock.lead_sec + films/<f>.json timeline_offset_sec (engine/video/wallclock.py
   clock_seconds). Здесь — только прибавка времени кадра и формат: секунды вниз, через полночь по кругу; кадр —
   чистая функция t.

   Внутри элемента-хозяина (host) — одна строка цифр. Цифры — не надпись .t: значение считает сборка, а не
   источник текста (V4); вписать их в разметку руками — провал V30. Видимость, вход и уход — у хозяина, битами
   сцены. Вид — tokens.json motion.clock: mode, format, digits_px, color (роль палитры), font (роль шрифта). */
(window.StagePlugins = window.StagePlugins || []).push(function (FILM, api) {
  'use strict';
  var items = [];
  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function text(c, t) {
    var s = ((Math.floor(c.base + t + 1e-6) % 86400) + 86400) % 86400;
    var hh = Math.floor(s / 3600), mm = Math.floor((s - hh * 3600) / 60), ss = s - hh * 3600 - mm * 60;
    return c.format === 'HH:MM' ? pad(hh) + ':' + pad(mm) : pad(hh) + ':' + pad(mm) + ':' + pad(ss);
  }
  FILM.scenes.forEach(function (sc) {
    var c = (sc.plugins || {}).clock;
    if (!c) return;
    var host = document.getElementById(sc.id + '--' + c.host);
    if (!host) throw new Error('clock: нет элемента #' + sc.id + '--' + c.host);
    var n = document.createElement('div');
    n.className = 'clk-digits';
    n.style.cssText = 'position:absolute;left:0;top:0;width:100%;height:100%;display:flex;align-items:center;' +
      'justify-content:center;white-space:nowrap;line-height:1;font-variant-numeric:tabular-nums;font-family:' + c.font +
      ';font-size:' + c.digits_px + 'px;color:' + c.color + ';';
    n.textContent = text(c, 0);
    host.appendChild(n);
    items.push({ sc: sc, c: c, host: host, n: n, shown: n.textContent });
  });
  if (!items.length) return null;
  function render(t) {
    items.forEach(function (it) {
      var v = text(it.c, t);
      if (v !== it.shown) { it.shown = v; it.n.textContent = v; }
    });
  }
  // промер: что НАПИСАНО в кадре (из DOM) и есть ли у хозяина свои цифры помимо табло (вписаны руками)
  function probe() {
    return { plugin: 'clock', items: items.map(function (it) {
      var own = [].filter.call(it.host.childNodes, function (x) { return x !== it.n; })
        .map(function (x) { return x.textContent || ''; }).join('');
      return { scene: it.sc.id, text: it.n.textContent, format: it.c.format, own: own.replace(/\s+/g, ' ').trim() };
    }) };
  }
  return { render: render, probe: probe };
});
