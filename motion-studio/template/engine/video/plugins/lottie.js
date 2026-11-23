/* Плагин lottie — готовая анимация Lottie в сцене: элемент раскадровки {id, kind: "lottie", x, y, w, h, src, at?, speed?,
   loop?}. Сборка (build.py lottie_items) читает файл анимации, отказывает файлу с адресами сети, отдельными картинками
   и выражениями, вшивает его в страницу (item.data) и переводит at в секунды фильма. Проигрыватель — lottie-web
   (window.lottie), тоже вшит в страницу: по сети при рендере ничего не грузится.

   Кадр анимации — чистая функция времени шкалы: кадр = (t − at) · speed · fr файла; до at — первый кадр, после конца —
   последний (loop — по кругу). Проигрыватель не играет сам (autoplay: false) и никогда не слышит часов страницы:
   каждый кадр ролика плагин ставит его в нужный кадр (goToAndStop). Поэтому рендер повторяем, а кадр момента t один
   и тот же, с какого бы места ни начали. Своих чисел движения здесь нет. Адаптер Lottie в рантайме HyperFrames
   анимации не ведёт: плагин прячет от него проигрыватель (см. ниже) — иначе хозяев у кадра было бы два.

   Видимость, вход и уход — у элемента-хозяина, битами сцены. Промер (probe): кадр, в котором проигрыватель стоит на
   самом деле, загружен ли он, число кадров файла; проверка — V39. */
(window.StagePlugins = window.StagePlugins || []).push(function (FILM, api) {
  'use strict';
  var items = [];
  FILM.scenes.forEach(function (sc) {
    (((sc.plugins || {}).lottie || {}).items || []).forEach(function (cfg) { items.push({ sc: sc, c: cfg, anim: null, total: cfg.op - cfg.ip }); });
  });
  if (!items.length) return null;
  if (!window.lottie || typeof window.lottie.loadAnimation !== 'function')
    throw new Error('lottie: на странице нет проигрывателя lottie-web (сборка вшивает его сама: build.py lottie_player)');
  items.forEach(function (it) {
    var host = document.getElementById(it.c.dom);
    if (!host) throw new Error('lottie: нет элемента #' + it.c.dom);
    var box = host.querySelector('.lottie-box') || host;
    it.anim = window.lottie.loadAnimation({ container: box, renderer: 'svg', loop: false, autoplay: false,
      animationData: it.c.data, rendererSettings: { preserveAspectRatio: 'xMidYMid meet' } });
    it.box = box;
  });
  /* У анимации один хозяин — этот плагин (закон 2). Рантайм HyperFrames при рендере сам находит анимации через
     window.lottie.getRegisteredAnimations() и ставит их в кадр по времени от начала ролика — мимо at и speed. Поэтому
     проигрыватель со страницы убирается, как только анимации загружены: объекты анимаций остаются у плагина. */
  try { delete window.lottie; } catch (e) { window.lottie = undefined; }
  if (window.lottie) window.lottie = undefined;

  // кадр файла в момент t: от at со скоростью speed; без круга — в пределах [0, число кадров − 1]
  function frameAt(it, t) {
    var local = t - it.c.at;
    var f = local <= 0 ? 0 : local * it.c.speed * it.c.fr;
    if (it.c.loop) return f % it.total;
    return Math.min(it.total - 1, f);
  }
  function render(t) {
    items.forEach(function (it) { it.anim.goToAndStop(frameAt(it, t), true); });
  }
  function shown(a) { return a.currentRawFrame != null ? a.currentRawFrame : a.currentFrame; }
  function probe(t) {
    return { plugin: 'lottie', items: items.map(function (it) {
      return { scene: it.sc.id, id: it.c.id, frame: Math.round(shown(it.anim) * 1000) / 1000, total: it.anim.totalFrames,
               loaded: it.anim.isLoaded !== false, nodes: it.box.querySelectorAll('*').length };
    }) };
  }
  return { render: render, probe: probe };
});
