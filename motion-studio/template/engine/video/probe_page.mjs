// Страница фильма для промера — одно место на все промеры: probe_dom.mjs, probe_frames.mjs, checks/probe_text.mjs,
// styles/_core/probe_style.mjs. Сервер файлов страницы, запуск Chrome, ожидание шрифтов и таймлайна, перемотка.
//   import { serve, launch, openPage, seek } from './probe_page.mjs';
//
//   const site = await serve(outDir);                    // локальный сервер папки страницы: {server, origin, url}
//   const browser = await launch();                      // безголовый Chrome (chromePath() из chrome_path.mjs)
//   const page = await openPage(browser, site.url, film.canvas, { errors, listen });
//   await seek(page, t);                                 // время — тем же путём, что рендер: seek таймлайна
//
// Промер отличается от промера только тем, что он читает со страницы; как страница открыта и как на ней ставится
// время — одно правило: иначе один промер ждёт шрифты, а другой нет, и кадры момента t у них разные.
// Запуск — только под замком Chrome (его берёт вызывающий: build.py, check.py, strip.py).
import { createServer } from 'node:http';
import { readFileSync, existsSync } from 'node:fs';
import { join, extname } from 'node:path';
import puppeteer from 'puppeteer-core';
import { chromePath } from './chrome_path.mjs';      // где лежит Chrome — одно правило на все промеры

const MIME = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.png': 'image/png',
  '.svg': 'image/svg+xml', '.ttf': 'font/ttf', '.otf': 'font/otf', '.woff2': 'font/woff2', '.css': 'text/css' };
const TIMELINE_WAIT_MS = 10000;      // сколько ждать, пока страница зарегистрирует таймлайн (lib/stage.js)

/** Локальный сервер папки страницы (только её файлы): {server, origin: 'http://127.0.0.1:<порт>/', url: …index.html}. */
export async function serve(outDir) {
  const server = createServer((req, res) => {
    const p = join(outDir, decodeURIComponent(req.url.split('?')[0]).replace(/^\/+/, '') || 'index.html');
    if (!p.startsWith(outDir) || !existsSync(p)) { res.writeHead(404); res.end(); return; }
    res.writeHead(200, { 'Content-Type': MIME[extname(p)] || 'application/octet-stream' });
    res.end(readFileSync(p));
  });
  await new Promise((ok) => server.listen(0, '127.0.0.1', ok));
  const origin = `http://127.0.0.1:${server.address().port}/`;
  return { server, origin, url: origin + 'index.html' };
}

/** Безголовый Chrome промеров: тот же, что у HyperFrames (chrome_path.mjs), без GPU и полос прокрутки. */
export function launch() {
  return puppeteer.launch({ executablePath: chromePath(), headless: true, protocolTimeout: 1800000,
    args: ['--no-sandbox', '--disable-gpu', '--hide-scrollbars'] });
}

/** Открытая страница фильма, готовая к промеру: полотно canvas {w, h}, шрифты загружены, таймлайн зарегистрирован.
 *  errors — массив, куда пишутся ошибки страницы (pageerror, console.error); listen(page) — свои слушатели страницы,
 *  ставятся до загрузки (запросы, сбои запросов). Таймлайна нет — ошибка с ошибками страницы. */
export async function openPage(browser, url, canvas, { errors = [], listen = null } = {}) {
  const page = await browser.newPage();
  await page.setViewport({ width: canvas.w, height: canvas.h, deviceScaleFactor: 1 });
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  if (listen) listen(page);
  await page.goto(url, { waitUntil: 'load' });
  await page.evaluate(() => document.fonts.ready);
  try {
    await page.waitForFunction(() => !!(window.__timelines && window.__timelines.main), { timeout: TIMELINE_WAIT_MS, polling: 100 });
  } catch (e) {
    throw new Error('Таймлайн не зарегистрирован: ' + e.message + '\nОшибки страницы:\n' + errors.join('\n'));
  }
  return page;
}

/** Поставить время страницы t (секунды фильма) — тем же путём, что рендер: seek таймлайна window.__timelines.main. */
export const seek = (page, t) => page.evaluate((t) => { window.__timelines.main.totalTime(t, false); }, t);
