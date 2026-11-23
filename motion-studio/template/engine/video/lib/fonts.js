/* Правило «шрифт загружен» — одно на движок: window.StageFonts. Сборка кладёт его первым скриптом страницы (build.py),
   до библиотек фильма (ключ libs): набор букв спрашивает о шрифте уже при разборе разметки сцен.

   Смотрит само начертание — @font-face страницы: семейство, вес и его состояние (FontFace.status: unloaded, loading,
   loaded, error). Общему ответу страницы (свойство status и метод check набора шрифтов документа) верить нельзя: он
   «loaded» и «да», пока ни один шрифт не грузится, — в том числе до того, как браузер начал грузить начертание,
   которого ещё нет. Геометрия букв, запомненная в этот момент, — геометрия запасного шрифта.

     StageFonts.face(family, weight?)   у страницы есть начертание семейства family (и веса weight, если он назван)
                                        в состоянии loaded: буквы этим шрифтом можно мерить и запоминать;
     StageFonts.all()                   каждое объявленное начертание пришло (loaded) или отвергнуто браузером (error):
                                        ни одно не ждёт загрузки — геометрию страницы можно запоминать. Начертание,
                                        объявленное дважды, считается одним.
   Кто спрашивает: lib/stage.js (геометрия узлов), styles/_core/core.js (StyleCore.fontsReady — надписи кодом),
   plugins/pen.js (строки букв «пером»), libs/card-kit.js (точки букв фразы). Промеры и рендер ждут готовности шрифтов
   страницы, поэтому кадр фильма — всегда с загруженными шрифтами; правило нужно до этого момента. */
window.StageFonts = (function () {
  'use strict';
  function bare(name) { return String(name).replace(/["']/g, ''); }
  function each(fn) { if (document.fonts) document.fonts.forEach(fn); }
  function face(family, weight) {
    if (!document.fonts) return true;
    var fam = bare(family), ok = false;
    each(function (f) {
      if (bare(f.family) === fam && (weight == null || String(f.weight) === String(weight)) && f.status === 'loaded') ok = true;
    });
    return ok;
  }
  function all() {
    var settled = {};
    each(function (f) {
      var key = bare(f.family) + '|' + f.weight + '|' + f.style;
      settled[key] = settled[key] || f.status === 'loaded' || f.status === 'error';
    });
    return Object.keys(settled).every(function (key) { return settled[key]; });
  }
  return { face: face, all: all };
})();
