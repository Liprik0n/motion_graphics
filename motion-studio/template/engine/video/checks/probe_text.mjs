// Промер областей текста собранной страницы — то, чего проверке читаемости по пикселям (check.py V37) не хватает
// к кадрам полосы: где в каждом кадре стоят строки надписей.
//   node engine/video/checks/probe_text.mjs <out/фильм> <задание.json>
//   задание {frames: [f, …], file: <куда писать>}  →  файл {fps, frames: [{f, t, dom: […], canvas: […] | null,
//   canvas_error}], errors}
//
// Время ставится тем же путём, что рендер, probe_dom.mjs и полоса кадров (probe_frames.mjs --strip): seek таймлайна
// window.__timelines.main в кадр f. В каждом кадре:
//   dom    — строки надписей .t содержания и заголовка (тот же отбор, что у промера стиля): рамка строки в px кадра,
//            итоговая непрозрачность o, закрыта ли другим элементом (covered), сцена, текст надписи;
//   canvas — то, что вернула window.__textRects(t) (lib/stage.js): области текста, нарисованного мимо DOM.
// Страницу не меняет, в <out/фильм> не пишет. Запуск — только под замком Chrome (check.py берёт его сам).
// Сервер страницы, Chrome (chromePath() из chrome_path.mjs), ожидание шрифтов и таймлайна, перемотка — общий модуль
// probe_page.mjs.
import { readFileSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { serve, launch, openPage, seek } from '../probe_page.mjs';      // страница для промера — одно правило на все промеры

const outDir = resolve(process.argv[2] || '.');
const job = JSON.parse(readFileSync(resolve(process.argv[3]), 'utf8'));
const film = JSON.parse(readFileSync(join(outDir, 'film.json'), 'utf8'));
const fps = film.fps;
const lastFrame = Math.round(film.duration * fps) - 1;

const { server, url } = await serve(outDir);

function readText(t) {
  const root = document.getElementById('root').getBoundingClientRect(), dom = [], kOf = {};
  const r1 = (v) => Math.round(v * 10) / 10;
  function opacityOf(el) {
    let o = 1;
    for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
      const cs = getComputedStyle(n);
      if (cs.display === 'none' || cs.visibility === 'hidden') return 0;
      o *= parseFloat(cs.opacity);
      const fo = /opacity\(([\d.]+)\)/.exec(cs.filter || '');     // множитель надписи в тени насыщенного блока
      if (fo) o *= parseFloat(fo[1]);
    }
    return o;
  }
  document.querySelectorAll('#content .el .t, #frame .fr-title .t').forEach((tn) => {
    const host = tn.closest('.el, .fr'), op = opacityOf(tn);
    const w = document.createTreeWalker(tn, NodeFilter.SHOW_TEXT, null);
    let x; const rects = [];
    while ((x = w.nextNode())) {
      if (!x.nodeValue.trim()) continue;
      if (x.parentElement.closest('.t') !== tn) continue;          // текст вложенной .t — её строки
      const rg = document.createRange(); rg.selectNodeContents(x);
      for (const r of rg.getClientRects()) if (r.width > 2 && r.height > 2) rects.push(r);
    }
    const lines = [];
    for (const r of rects) {                                        // куски одной строки — в одну рамку
      const l = lines.find((m) => Math.abs(m.top - r.top) < 2 && Math.abs(m.bottom - r.bottom) < 2);
      if (l) { l.left = Math.min(l.left, r.left); l.right = Math.max(l.right, r.right); }
      else lines.push({ left: r.left, right: r.right, top: r.top, bottom: r.bottom });
    }
    const scene = host.getAttribute('data-scene') || (host.id.indexOf('--') > 0 ? host.id.split('--')[0] : null);
    lines.forEach((l) => {
      const k = kOf[host.id] = (kOf[host.id] == null ? 0 : kOf[host.id] + 1);
      if (op <= 0.001) return;
      const cx = (l.left + l.right) / 2, cy = (l.top + l.bottom) / 2, hit = document.elementFromPoint(cx, cy);
      const other = hit && hit.closest ? hit.closest('.el, .fr') : null;
      dom.push({ id: host.id, k, scene, o: Math.round(op * 1000) / 1000, covered: !!(other && other !== host),
                 text: tn.textContent.replace(/\s+/g, ' ').trim().slice(0, 60),
                 rect: [l.left - root.left, l.top - root.top, l.right - l.left, l.bottom - l.top].map(r1) });
    });
  });
  let canvas = null, canvasError = null;
  if (typeof window.__textRects === 'function') {
    try {
      canvas = JSON.parse(JSON.stringify(window.__textRects(t) || []));
    } catch (e) { canvasError = String(e); }
  }
  return { dom, canvas, canvas_error: canvasError };
}

const browser = await launch();
const errors = [];
const res = { film: film.film, fps, frames: [], errors };
try {
  const page = await openPage(browser, url, film.canvas, { errors });
  for (const f0 of job.frames) {
    const f = Math.min(Math.max(0, f0), lastFrame), t = f / fps;
    await seek(page, t);
    res.frames.push({ f, t, ...(await page.evaluate(readText, t)) });
  }
  await page.close();
  writeFileSync(resolve(job.file), JSON.stringify(res));
  console.log(JSON.stringify({ n: res.frames.length }));
} finally {
  await browser.close();
  server.close();
}
// ошибки страницы — не отказ промера: их показывает V1 (probe.json errors); здесь они в поле errors
