/* Плагин timer — таймер обратного отсчёта до события внутри элемента сцены: четыре группы «число над подписью»
   (дни, часы, минуты, секунды). Включается полем раскадровки plugins.timer (engine/video/plugins/README.md);
   сборка кладёт в данные left_at — сколько секунд осталось до события в момент at (engine/video/wallclock.py
   seconds_left от project.json wall_clock: start, lead_sec, event — и смещения куска в склейке). Здесь — только
   вычитание времени кадра: секунды тикают по времени фильма, кадр — чистая функция t (рендер кусками = цельному).

   В элементе-хозяине (host) — группы и разделители. Подписи (labels — четыре строки из tokens.json motion.timer
   или раскадровки) — надписи (.t): их видят проверки текста (V4, V10, V18); числа — не .t (меняются каждую секунду).
   Видимость, вход и уход — у хозяина, битами сцены. mode "date" — вместо отсчёта строка date_text (вариант ролика
   без отсчёта). */
(window.StagePlugins = window.StagePlugins || []).push(function (FILM, api) {
  'use strict';
  var items = [];
  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function el(tag, cls, css, text) {
    var n = document.createElement(tag);
    n.className = cls;
    n.style.cssText = css;
    if (text != null) n.textContent = text;
    return n;
  }
  FILM.scenes.forEach(function (sc) {
    var c = (sc.plugins || {}).timer;
    if (!c) return;
    var host = document.getElementById(sc.id + '--' + c.host);
    if (!host) throw new Error('timer: нет элемента #' + sc.id + '--' + c.host);
    var wrap = el('div', 'tm-wrap', 'position:absolute;left:0;top:0;width:100%;height:100%;display:flex;' +
      'align-items:center;justify-content:center;white-space:nowrap;');
    var it = { sc: sc, c: c, host: host, nums: [], shown: [] };
    var labCss = 'font-family:' + c.labels_font + ';font-size:' + c.labels_px + 'px;color:' + c.labels_color +
      ';line-height:1.2;text-align:center;white-space:nowrap;';
    if (c.mode === 'date') {
      wrap.appendChild(el('div', 't tm-date', labCss, c.date_text));
    } else {
      if (!c.labels || c.labels.length !== 4) throw new Error('timer: подписей должно быть 4 (дни, часы, минуты, секунды)');
      wrap.style.gap = c.gap_px + 'px';
      var numCss = 'font-family:' + c.digits_font + ';font-size:' + c.digits_px + 'px;color:' + c.digits_color +
        ';line-height:1;font-variant-numeric:tabular-nums;text-align:center;';
      c.labels.forEach(function (lab, k) {
        if (k) wrap.appendChild(el('div', 'tm-sep', numCss + 'align-self:flex-start;', c.sep));
        var g = el('div', 'tm-group', 'display:flex;flex-direction:column;align-items:center;gap:' + c.label_gap_px + 'px;');
        var n = el('div', 'tm-num', numCss, '00');
        g.appendChild(n);
        g.appendChild(el('div', 't tm-lab', labCss, lab));
        wrap.appendChild(g);
        it.nums.push(n);
        it.shown.push('00');
      });
    }
    host.appendChild(wrap);
    items.push(it);
  });
  if (!items.length) return null;

  // остаток в момент t: от left_at в момент at вниз по времени кадра; до at — значение at (хозяин ещё не виден)
  function partsAt(it, t) {
    var left = it.c.left_at - Math.max(0, t - it.c.at);
    var s = Math.max(0, Math.floor(left + 1e-6));
    return [Math.floor(s / 86400), Math.floor((s - Math.floor(s / 86400) * 86400) / 3600),
            Math.floor((s - Math.floor(s / 3600) * 3600) / 60), s - Math.floor(s / 60) * 60];
  }
  function render(t) {
    items.forEach(function (it) {
      if (it.c.mode === 'date') return;
      var p = partsAt(it, t);
      it.nums.forEach(function (n, k) {
        var v = pad(p[k]);
        if (it.shown[k] !== v) { it.shown[k] = v; n.textContent = v; }
      });
    });
  }
  // промер: что НАПИСАНО в кадре (читается из DOM), в формате wallclock.timer_at «Д д ЧЧ:ММ:СС»
  function probe(t) {
    return { plugin: 'timer', items: items.map(function (it) {
      var text;
      if (it.c.mode === 'date') text = it.host.querySelector('.tm-date').textContent;
      else {
        var v = it.nums.map(function (n) { return parseInt(n.textContent, 10); });
        text = v[0] + ' д ' + pad(v[1]) + ':' + pad(v[2]) + ':' + pad(v[3]);
      }
      return { scene: it.sc.id, mode: it.c.mode, text: text,
               labels: [].map.call(it.host.querySelectorAll('.tm-lab'), function (n) { return n.textContent; }) };
    }) };
  }
  return { render: render, probe: probe };
});
