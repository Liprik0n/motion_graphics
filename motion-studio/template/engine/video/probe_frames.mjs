// Промер кадров собранной страницы — то, что проверки не узнают из DOM-промера: помехи (плагин glitch, V27),
// кадры фильма (film.json stills, V40 и V41) и запросы страницы мимо своих файлов (Lottie без сети, V39).
//   node engine/video/probe_frames.mjs <out/фильм>  →  <out/фильм>/plugin_probe.json, plugin_frames/*.png
//
// Окна помех — film.json glitch_windows [[сцена, from, to]]. Для каждого окна (± 0,5 с):
//   flash — каждый кадр в 1/10 размера (CDP Page.captureScreenshot с clip.scale): яркость для WCAG 2.3.1;
//   det   — три кадра окна (¼, ½, ¾) полного размера: первая загрузка по порядку (a), новая загрузка в обратном
//           порядке с посторонним кадром перед каждым (b); проверка сравнивает a и b попиксельно.
// Кадры фильма — film.json stills (ключ фильма "stills", build.py film_stills) → res.stills:
//   frame0 — кадр 0; seams — пары кадров каждого шва (последний кадр сцены N и первый N+1); windows — кадр с
//   раскрытыми окнами набора букв; det — кадры детерминизма (середины действий act, моменты Lottie): снят в первой
//   загрузке (a) и после перезагрузки в обратном порядке с посторонним кадром перед каждым (b).
// Запросы — res.requests: адреса всего, что страница просила мимо своих файлов (data: и blob: не в счёт).
// Время ставится тем же путём, что рендер и probe_dom.mjs: seek таймлайна window.__timelines.main.
//
// Режим полосы кадров (engine/tools/strip.py):
//   node engine/video/probe_frames.mjs <out/фильм> --strip <задание.json>
//   задание {scale, frames: [{f, file}]} — кадры f страницы в масштабе scale (CDP clip.scale) в файлы file
//   (пути абсолютные); plugin_probe.json и plugin_frames/ в этом режиме не трогаются. Печатает строку {"n": N}.
// Запуск — только под замком Chrome (build.py берёт его сам: engine/chrome_lock.py).
// Сервер страницы, Chrome (chromePath() из chrome_path.mjs), ожидание шрифтов и таймлайна, перемотка — общий модуль
// probe_page.mjs.
import { readFileSync, writeFileSync, mkdirSync, rmSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { serve, launch, openPage, seek as seekTime } from './probe_page.mjs';      // страница для промера — одно правило

const outDir = resolve(process.argv[2] || '.');
const film = JSON.parse(readFileSync(join(outDir, 'film.json'), 'utf8'));
const fps = film.fps;
const frameOf = (t) => Math.floor(t * fps + 0.5 + 5e-3);
const lastFrame = Math.round(film.duration * fps) - 1;
const MARGIN_SEC = 0.5, SCALE = 0.1;

const { server, origin, url } = await serve(outDir);
const stripAt = process.argv.indexOf('--strip');
const stripJob = stripAt > 0 ? JSON.parse(readFileSync(resolve(process.argv[stripAt + 1]), 'utf8')) : null;
const dir = join(outDir, 'plugin_frames');
if (!stripJob) {
  rmSync(dir, { recursive: true, force: true });
  mkdirSync(dir);
}

const browser = await launch();
const errors = [];
const requests = [];           // запросы страницы мимо своих файлов: при рендере по сети ничего не грузится (V39)
const clip = { x: 0, y: 0, width: film.canvas.w, height: film.canvas.h };
const open = () => openPage(browser, url, film.canvas, { errors, listen: (page) => page.on('request', (r) => {
  const u = r.url();
  if (!u.startsWith(origin) && !u.startsWith('data:') && !u.startsWith('blob:') && !requests.includes(u)) requests.push(u);
}) });
const seek = (page, f) => seekTime(page, f / fps);      // кадр f фильма

const res = { film: film.film, fps, windows: [], det: [], errors, requests };
try {
  let page = await open();
  const cdp = page.createCDPSession ? await page.createCDPSession() : await page.target().createCDPSession();
  if (stripJob) {
    for (const { f, file } of stripJob.frames) {
      await seek(page, Math.min(Math.max(0, f), lastFrame));
      const r = await cdp.send('Page.captureScreenshot', { format: 'png', clip: { ...clip, scale: stripJob.scale } });
      writeFileSync(file, Buffer.from(r.data, 'base64'));
    }
    console.log(JSON.stringify({ n: stripJob.frames.length }));
    await page.close();
  } else {
  const detFrames = [];
  for (const [scene, from, to] of film.glitch_windows || []) {
    const f0 = Math.max(0, frameOf(from - MARGIN_SEC)), f1 = Math.min(lastFrame, frameOf(to + MARGIN_SEC));
    for (let f = f0; f <= f1; f++) {
      await seek(page, f);
      const r = await cdp.send('Page.captureScreenshot', { format: 'png', clip: { ...clip, scale: SCALE } });
      writeFileSync(join(dir, `w${res.windows.length}_${String(f).padStart(5, '0')}.png`), Buffer.from(r.data, 'base64'));
    }
    res.windows.push({ scene, from, to, f0, n: f1 - f0 + 1, scale: SCALE,
                       pattern: `plugin_frames/w${res.windows.length}_%05d.png` });
    for (const x of [0.25, 0.5, 0.75]) detFrames.push(frameOf(from + x * (to - from)));
  }
  for (let k = 0; k < detFrames.length; k++) {
    await seek(page, detFrames[k]);
    const a = `det_a_${k}.png`;
    await page.screenshot({ path: join(dir, a), clip });
    res.det.push({ t: detFrames[k] / fps, a: 'plugin_frames/' + a });
  }
  await page.close();
  page = await open();                    // детерминизм: новая загрузка, обратный порядок, посторонний кадр перед каждым
  for (let k = detFrames.length - 1; k >= 0; k--) {
    await seek(page, Math.floor((detFrames[k] + lastFrame / 2) % (lastFrame + 1)));
    await seek(page, detFrames[k]);
    const b = `det_b_${k}.png`;
    await page.screenshot({ path: join(dir, b), clip });
    res.det[k].b = 'plugin_frames/' + b;
  }
  await page.close();
  const st = film.stills;
  if (st) {                               // кадры фильма (V40, V41): кадр 0, пары швов, окна, детерминизм
    res.stills = { frame0: null, seams: [], windows: [], det: [] };
    page = await open();
    const shot = async (f, name) => { await seek(page, f); await page.screenshot({ path: join(dir, name), clip }); return 'plugin_frames/' + name; };
    res.stills.frame0 = await shot(st.frame0, 'still_f0.png');
    for (let k = 0; k < st.seams.length; k++) {
      const s = st.seams[k];
      res.stills.seams.push({ from: s.from, to: s.to, fa: s.a, fb: s.b,
        a: await shot(s.a, `still_seam${k}_a.png`), b: await shot(s.b, `still_seam${k}_b.png`) });
    }
    for (let k = 0; k < (st.windows || []).length; k++) {
      const w = st.windows[k];
      res.stills.windows.push({ scene: w.scene, cue: w.cue, f: w.f, t: w.f / fps, img: await shot(w.f, `still_win${k}.png`) });
    }
    for (let k = 0; k < st.det.length; k++)
      res.stills.det.push({ f: st.det[k], t: st.det[k] / fps, a: await shot(st.det[k], `still_det${k}_a.png`) });
    await page.close();
    page = await open();                  // вторая загрузка: обратный порядок, посторонний кадр перед каждым
    for (let k = st.det.length - 1; k >= 0; k--) {
      await seek(page, Math.floor((st.det[k] + lastFrame / 2) % (lastFrame + 1)));
      res.stills.det[k].b = await shot(st.det[k], `still_det${k}_b.png`);
    }
    await page.close();
  }
  }
} finally {
  if (!stripJob) writeFileSync(join(outDir, 'plugin_probe.json'), JSON.stringify(res, null, 0));
  await browser.close();
  server.close();
}
if (errors.length) { console.error('Ошибки страницы:\n' + errors.join('\n')); process.exitCode = 1; }
