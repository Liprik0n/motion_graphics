// Промер помех (плагин glitch) собранной страницы — то, что проверка (V27) не узнает из DOM-промера.
//   node engine/video/probe_frames.mjs <out/фильм>  →  <out/фильм>/plugin_probe.json, plugin_frames/*.png
//
// Окна помех — film.json glitch_windows [[сцена, from, to]]. Для каждого окна (± 0,5 с):
//   flash — каждый кадр в 1/10 размера (CDP Page.captureScreenshot с clip.scale): яркость для WCAG 2.3.1;
//   det   — три кадра окна (¼, ½, ¾) полного размера: первая загрузка по порядку (a), новая загрузка в обратном
//           порядке с посторонним кадром перед каждым (b); проверка сравнивает a и b попиксельно.
// Время ставится тем же путём, что рендер и probe_dom.mjs: seek таймлайна window.__timelines.main.
// Запуск — только под замком Chrome (build.py берёт его сам: engine/chrome_lock.py).
import { createServer } from 'node:http';
import { readFileSync, writeFileSync, existsSync, readdirSync, mkdirSync, rmSync } from 'node:fs';
import { join, extname, resolve } from 'node:path';
import { homedir } from 'node:os';
import puppeteer from 'puppeteer-core';

const outDir = resolve(process.argv[2] || '.');
const film = JSON.parse(readFileSync(join(outDir, 'film.json'), 'utf8'));
const fps = film.fps;
const frameOf = (t) => Math.floor(t * fps + 0.5 + 5e-3);
const lastFrame = Math.round(film.duration * fps) - 1;
const MARGIN_SEC = 0.5, SCALE = 0.1;

function chromePath() {
  if (process.env.CHROME_PATH) return process.env.CHROME_PATH;
  const base = join(homedir(), '.cache', 'hyperframes', 'chrome', 'chrome-headless-shell');
  if (existsSync(base)) {
    for (const v of readdirSync(base).sort().reverse()) {
      for (const [dir, exe] of [['chrome-headless-shell-win64', 'chrome-headless-shell.exe'],
        ['chrome-headless-shell-linux64', 'chrome-headless-shell'], ['chrome-headless-shell-mac-arm64', 'chrome-headless-shell'],
        ['chrome-headless-shell-mac-x64', 'chrome-headless-shell']]) {
        const p = join(base, v, dir, exe);
        if (existsSync(p)) return p;
      }
    }
  }
  const sys = join(process.env.PROGRAMFILES || '', 'Google', 'Chrome', 'Application', 'chrome.exe');
  if (existsSync(sys)) return sys;
  throw new Error('Нет Chrome: npx hyperframes browser ensure (в engine/video) или задай CHROME_PATH');
}

const MIME = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.png': 'image/png',
  '.svg': 'image/svg+xml', '.ttf': 'font/ttf', '.otf': 'font/otf', '.woff2': 'font/woff2', '.css': 'text/css' };
const server = createServer((req, res) => {
  const p = join(outDir, decodeURIComponent(req.url.split('?')[0]).replace(/^\/+/, '') || 'index.html');
  if (!p.startsWith(outDir) || !existsSync(p)) { res.writeHead(404); res.end(); return; }
  res.writeHead(200, { 'Content-Type': MIME[extname(p)] || 'application/octet-stream' });
  res.end(readFileSync(p));
});
await new Promise((ok) => server.listen(0, '127.0.0.1', ok));
const url = `http://127.0.0.1:${server.address().port}/index.html`;
const dir = join(outDir, 'plugin_frames');
rmSync(dir, { recursive: true, force: true });
mkdirSync(dir);

const browser = await puppeteer.launch({ executablePath: chromePath(), headless: true, protocolTimeout: 1800000,
  args: ['--no-sandbox', '--disable-gpu', '--hide-scrollbars'] });
const errors = [];
const clip = { x: 0, y: 0, width: film.canvas.w, height: film.canvas.h };
async function open() {
  const page = await browser.newPage();
  await page.setViewport({ width: film.canvas.w, height: film.canvas.h, deviceScaleFactor: 1 });
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  await page.goto(url, { waitUntil: 'load' });
  await page.evaluate(() => document.fonts.ready);
  await page.waitForFunction(() => !!(window.__timelines && window.__timelines.main), { timeout: 10000, polling: 100 });
  return page;
}
const seek = (page, f) => page.evaluate((t) => { window.__timelines.main.totalTime(t, false); }, f / fps);

const res = { film: film.film, fps, windows: [], det: [], errors };
try {
  let page = await open();
  const cdp = page.createCDPSession ? await page.createCDPSession() : await page.target().createCDPSession();
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
} finally {
  writeFileSync(join(outDir, 'plugin_probe.json'), JSON.stringify(res, null, 0));
  await browser.close();
  server.close();
}
if (errors.length) { console.error('Ошибки страницы:\n' + errors.join('\n')); process.exitCode = 1; }
