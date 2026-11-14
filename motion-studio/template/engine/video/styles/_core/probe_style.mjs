// Промер стиля собранной страницы: то, что check.py (V21–V24) не может узнать из DOM-промера.
//   node engine/video/styles/_core/probe_style.mjs <out/фильм> [--skip flash]  →  <out/фильм>/style_probe.json,
//   style_shots/*.png (кадры полного размера), style_flash/*.png (каждый кадр фильма в 1/10 размера)
//
// Страница та же, время ставится тем же путём, что рендер и probe_dom.mjs: seek таймлайна
// window.__timelines.main. Моменты кадров — середина и конец (−2 кадра) каждой реплики, не больше 8.
//   shots   — в каждый момент: кадр со стилем (a), кадр без стиля (bare: таблицы стилей <style data-style-css>
//             выключены, слои .style-layer скрыты), строки надписей (рамки строк видимых на 1,0 .t);
//   palette — значения --c-<роль> на #root; цвета, заливки, обводки и шрифт каждого узла содержания и
//             каркаса со стилем и без (разница = стиль подменил роль); CSS-фильтры и примитивы SVG-фильтров
//             на узлах содержания и их предках;
//   determinism — страница загружается заново, те же моменты снимаются в обратном порядке с посторонним
//             кадром перед каждым (b); проверка сравнивает a и b попиксельно;
//   flash   — каждый кадр фильма в 1/10 размера (CDP Page.captureScreenshot с clip.scale): яркость для WCAG 2.3.
// Файлы пишутся только в <out/фильм>. Сеть — только локальный сервер страницы.
import { createServer } from 'node:http';
import { readFileSync, writeFileSync, existsSync, readdirSync, mkdirSync, rmSync } from 'node:fs';
import { join, extname, resolve } from 'node:path';
import { homedir } from 'node:os';
import puppeteer from 'puppeteer-core';

const outDir = resolve(process.argv[2] || '.');
const skip = new Set();
for (let i = 3; i < process.argv.length; i++) if (process.argv[i] === '--skip') skip.add(process.argv[++i]);

const film = JSON.parse(readFileSync(join(outDir, 'film.json'), 'utf8'));
const fps = film.fps;
const frameOf = (t) => Math.floor(t * fps + 0.5 + 5e-3);           // одно правило округления со сборкой
const q = (t) => Math.max(0, Math.min(film.duration - 1 / fps, frameOf(t) / fps));
const SHOTS_MAX = 8, FLASH_SCALE = 0.1;

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

const times = [];
for (const r of film.replies) for (const t of [(r.start + r.end) / 2, r.end - 2 / fps]) {
  const x = q(t);
  if (!times.includes(x)) times.push(x);
}
times.sort((a, b) => a - b);
while (times.length > SHOTS_MAX) times.splice(Math.floor(times.length / 2), 1);

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

const shotDir = join(outDir, 'style_shots'), flashDir = join(outDir, 'style_flash');
for (const d of [shotDir, flashDir]) { rmSync(d, { recursive: true, force: true }); mkdirSync(d); }

const browser = await puppeteer.launch({ executablePath: chromePath(), headless: true, protocolTimeout: 1800000,
  args: ['--no-sandbox', '--disable-gpu', '--hide-scrollbars'] });
const errors = [];
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
const seek = (page, t) => page.evaluate((t) => { window.__timelines.main.totalTime(t, false); }, t);
const clip = { x: 0, y: 0, width: film.canvas.w, height: film.canvas.h };

// узлы, чьи цвета и шрифт стиль не вправе менять: содержание и каркас; их фильтры и смешение
function readNodes() {
  const out = {}, filters = [], vars = {};
  const rootCs = getComputedStyle(document.getElementById('root'));
  for (const k of window.__FILM_PALETTE__ || []) vars[k] = rootCs.getPropertyValue('--c-' + k).trim();
  const nodes = [...document.querySelectorAll('#content .el, #content .el *, #frame .fr, #frame .fr *')];
  nodes.forEach((n, i) => {
    if (n instanceof SVGElement && n.tagName.toLowerCase() !== 'svg') return;
    const cs = getComputedStyle(n), host = n.closest('.el, .fr');
    const key = (host ? host.id : '?') + '|' + (n === host ? '' : (n.getAttribute('data-part') || n.className.baseVal || n.className || n.tagName) + '#' + i);
    const own = [...n.childNodes].some((c) => c.nodeType === 3 && c.nodeValue.trim());
    out[key] = { color: cs.color, bg: cs.backgroundColor, border: cs.borderTopWidth !== '0px' ? cs.borderTopColor : '',
                 font: cs.fontFamily, weight: cs.fontWeight, style: cs.fontStyle,
                 text: own, title: !!n.closest('.fr-title') };
  });
  const chain = new Set(nodes);
  for (let n = document.getElementById('content'); n; n = n.parentElement) chain.add(n);
  document.querySelectorAll('#content .scene').forEach((s) => chain.add(s));
  for (const n of chain) {
    const cs = getComputedStyle(n), id = n.id || (n.closest('[id]') || {}).id || n.tagName;
    if (cs.filter && cs.filter !== 'none') {
      const prims = [];
      for (const m of cs.filter.matchAll(/url\("?#([^")]+)"?\)/g)) {
        const f = document.getElementById(m[1]);
        prims.push(...(f ? [...f.children].map((c) => c.tagName) : ['(нет фильтра #' + m[1] + ')']));
      }
      filters.push({ id, filter: cs.filter, prims });
    }
    if (cs.mixBlendMode && cs.mixBlendMode !== 'normal') filters.push({ id, blend: cs.mixBlendMode, filter: '', prims: [] });
  }
  // слои стиля над содержанием (.style-over) и всё внутри: перекраска содержания смешением, фильтром, backdrop-filter
  const over = [];
  document.querySelectorAll('.style-over, .style-over *').forEach((n) => {
    const cs = getComputedStyle(n), id = n.id || (n.closest('[id]') || {}).id || n.tagName;
    const bd = cs.backdropFilter || cs.webkitBackdropFilter || 'none';
    if ((cs.mixBlendMode && cs.mixBlendMode !== 'normal') || (cs.filter && cs.filter !== 'none') || bd !== 'none')
      over.push({ id, blend: cs.mixBlendMode, filter: cs.filter, backdrop: bd });
  });
  return { nodes: out, filters, vars, over };
}
function readTitles() {
  const root = document.getElementById('root').getBoundingClientRect();
  const rr = (r) => [r.left - root.left, r.top - root.top, r.width, r.height].map((v) => Math.round(v * 10) / 10);
  return {
    code: [...document.querySelectorAll('[data-style-title]')].map((g) => ({ scene: g.getAttribute('data-style-title'),
      text: g.getAttribute('data-text'), rect: rr(g.getBoundingClientRect()), o: parseFloat(getComputedStyle(g).opacity) })),
    frame: [...document.querySelectorAll('.fr-title')].map((f) => ({ id: f.id, scene: f.getAttribute('data-scene'),
      text: f.textContent.replace(/\s+/g, ' ').trim(), rect: rr(f.getBoundingClientRect()), o: parseFloat(f.style.opacity) || 0 })),
  };
}
function setBare(on) {
  document.querySelectorAll('style[data-style-css]').forEach((s) => { s.sheet.disabled = on; });
  document.querySelectorAll('.style-layer').forEach((l) => { l.style.visibility = on ? 'hidden' : ''; });
}
// строки надписей: рамка строки в px полотна, номер строки в элементе k, непрозрачность o, закрыта ли другим .el.
// k — сквозной по ВСЕМ надписям .t элемента (у строки шага три .t: номер, текст, метка), а не по одной .t:
// check.py V21 сопоставляет строку со стилем и без по (id, k), и общий k=0 у трёх надписей сравнивал бы номер
// без стиля с меткой со стилем (так сцена-проба этого не показывала: там у элемента одна .t).
function readLines() {
  const root = document.getElementById('root').getBoundingClientRect(), out = [], kOf = {};
  function opacityOf(el) {
    let o = 1;
    for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
      const cs = getComputedStyle(n);
      if (cs.display === 'none' || cs.visibility === 'hidden') return 0;
      o *= parseFloat(cs.opacity);
      const fo = /opacity\(([\d.]+)\)/.exec(cs.filter || '');
      if (fo) o *= parseFloat(fo[1]);
    }
    return o;
  }
  document.querySelectorAll('#content .el .t, #frame .fr-title .t').forEach((t) => {
    const host = t.closest('.el, .fr'), op = opacityOf(t);
    const w = document.createTreeWalker(t, NodeFilter.SHOW_TEXT, null);
    let x; const rects = [];
    while ((x = w.nextNode())) {
      if (!x.nodeValue.trim()) continue;
      if (x.parentElement.closest('.t') !== t) continue;          // текст вложенной .t — её строки
      const rg = document.createRange(); rg.selectNodeContents(x);
      for (const r of rg.getClientRects()) if (r.width > 2 && r.height > 2) rects.push(r);
    }
    const lines = [];
    for (const r of rects) {                                        // куски одной строки — в одну рамку
      const l = lines.find((m) => Math.abs(m.top - r.top) < 2 && Math.abs(m.bottom - r.bottom) < 2);
      if (l) { l.left = Math.min(l.left, r.left); l.right = Math.max(l.right, r.right); }
      else lines.push({ left: r.left, right: r.right, top: r.top, bottom: r.bottom });
    }
    lines.forEach((l) => {
      const k = kOf[host.id] = (kOf[host.id] == null ? 0 : kOf[host.id] + 1);
      const cx = (l.left + l.right) / 2, cy = (l.top + l.bottom) / 2, hit = document.elementFromPoint(cx, cy);
      const covered = !!(hit && hit.closest && hit.closest('.el, .fr') && hit.closest('.el, .fr') !== host);
      out.push({ id: host.id, k, o: Math.round(op * 1000) / 1000, covered, text: t.textContent.replace(/\s+/g, ' ').trim().slice(0, 60),
                 rect: [l.left - root.left, l.top - root.top, l.right - l.left, l.bottom - l.top].map((v) => Math.round(v * 10) / 10) });
    });
  });
  return out;
}

const res = { film: film.film, fps, duration: film.duration, styles: film.scenes.map((s) => ({ id: s.id, style: s.style || null })),
              times, shots: [], palette: [], flash: null, errors };
try {
  const pal = JSON.parse(readFileSync(join(outDir, 'film.json'), 'utf8')).palette_roles || null;
  let page = await open();
  await page.evaluate((p) => { window.__FILM_PALETTE__ = p; }, pal || []);
  for (let k = 0; k < times.length; k++) {
    const t = times[k];
    await seek(page, t);
    const a = `a_${String(k).padStart(2, '0')}.png`, bare = `bare_${String(k).padStart(2, '0')}.png`;
    await page.screenshot({ path: join(shotDir, a), clip });
    const lines = await page.evaluate(readLines);
    const styled = await page.evaluate(readNodes);
    await page.evaluate(setBare, true);
    const plain = await page.evaluate(readNodes);
    const bareLines = await page.evaluate(readLines);
    await page.screenshot({ path: join(shotDir, bare), clip });
    await page.evaluate(setBare, false);
    const diffs = [];
    for (const [key, v] of Object.entries(styled.nodes)) {
      const b = plain.nodes[key];
      if (!b) continue;
      for (const prop of ['color', 'bg', 'border', 'font', 'weight', 'style'])
        if (v[prop] !== b[prop]) diffs.push({ node: key, prop, styled: v[prop], bare: b[prop], text: v.text, title: v.title });
    }
    res.shots.push({ t, a: 'style_shots/' + a, bare: 'style_shots/' + bare, lines, bare_lines: bareLines,
                     titles: await page.evaluate(readTitles),
                     scene: await page.evaluate(() => document.getElementById('root').getAttribute('data-scene')),
                     style: await page.evaluate(() => document.getElementById('root').getAttribute('data-style')) });
    res.palette.push({ t, vars: styled.vars, diffs: diffs.slice(0, 60), filters: styled.filters, nodes: styled.nodes, over: styled.over });
  }
  await page.close();
  // детерминизм: новая загрузка, обратный порядок, перед каждым моментом — посторонний кадр
  page = await open();
  for (let k = times.length - 1; k >= 0; k--) {
    await seek(page, q((times[k] + film.duration / 2) % film.duration));
    await seek(page, times[k]);
    const b = `b_${String(k).padStart(2, '0')}.png`;
    await page.screenshot({ path: join(shotDir, b), clip });
    res.shots[k].b = 'style_shots/' + b;
  }
  if (!skip.has('flash')) {
    const cdp = page.createCDPSession ? await page.createCDPSession() : await page.target().createCDPSession();
    const n = Math.round(film.duration * fps);
    for (let f = 0; f < n; f++) {
      await seek(page, f / fps);
      const r = await cdp.send('Page.captureScreenshot', { format: 'png', clip: { ...clip, scale: FLASH_SCALE } });
      writeFileSync(join(flashDir, `f_${String(f).padStart(5, '0')}.png`), Buffer.from(r.data, 'base64'));
    }
    res.flash = { frames: n, scale: FLASH_SCALE, pattern: 'style_flash/f_%05d.png' };
  }
  await page.close();
} finally {
  writeFileSync(join(outDir, 'style_probe.json'), JSON.stringify(res, null, 0));
  await browser.close();
  server.close();
}
if (errors.length) { console.error('Ошибки страницы:\n' + errors.join('\n')); process.exitCode = 1; }
