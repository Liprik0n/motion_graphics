// Где лежит Chrome для промеров — одно правило на все промеры: его зовёт probe_page.mjs (страница для промера —
// сервер, запуск Chrome, ожидание, перемотка), а тот — probe_dom.mjs, probe_frames.mjs, checks/probe_text.mjs и
// styles/_core/probe_style.mjs.
//   import { chromePath } from './chrome_path.mjs';
//   node engine/video/chrome_path.mjs        напечатать найденный путь; Chrome нет — подсказка и код 2
//
// Порядок: переменная CHROME_PATH → кэш HyperFrames (~/.cache/hyperframes/chrome/chrome-headless-shell/<сборка>/,
// самая новая сборка; имя папки платформы не зашито: win64, linux64, mac-arm64, mac-x64) → Chrome системы.
// Chrome в кэш кладёт `hyperframes browser ensure` (его зовёт `<скил>/tools/setup.py install`).
import { existsSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { homedir } from 'node:os';
import { pathToFileURL } from 'node:url';

export const NO_CHROME = 'Нет Chrome для промера: поставь его командой `npx hyperframes browser ensure` из папки общей '
  + 'установки (её делает `python <скил>/tools/setup.py install`) либо задай CHROME_PATH — путь к chrome или '
  + 'chrome-headless-shell';
const SHELL = 'chrome-headless-shell';

// «win64-152.0.7977.30» → [152, 0, 7977, 30]: сборки сравниваются числами, а не строками (99 < 152)
const build = (name) => (name.match(/\d+(?:\.\d+)+/) || ['0'])[0].split('.').map(Number);
function newerFirst(a, b) {
  const x = build(a), y = build(b);
  for (let i = 0; i < Math.max(x.length, y.length); i++) {
    if ((x[i] || 0) !== (y[i] || 0)) return (y[i] || 0) - (x[i] || 0);
  }
  return a < b ? 1 : -1;
}

function cached(home) {
  const base = join(home, '.cache', 'hyperframes', 'chrome', SHELL);
  if (!existsSync(base)) return null;
  for (const v of readdirSync(base).sort(newerFirst)) {
    let inner = [];
    try { inner = readdirSync(join(base, v)); } catch { continue; }
    for (const d of inner.filter((n) => n.startsWith(SHELL)).sort()) {
      for (const exe of [SHELL + '.exe', SHELL]) {
        const p = join(base, v, d, exe);
        if (existsSync(p)) return p;
      }
    }
  }
  return null;
}

function system(env) {
  const tail = ['Google', 'Chrome', 'Application', 'chrome.exe'];
  const list = [env.PROGRAMFILES, env['PROGRAMFILES(X86)'], env.LOCALAPPDATA].filter(Boolean).map((r) => join(r, ...tail));
  list.push('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', '/usr/bin/google-chrome', '/usr/bin/chromium');
  return list.find((p) => existsSync(p)) || null;
}

/** Путь к Chrome или null. CHROME_PATH задан, но файла нет — тоже null: молча взять другой браузер было бы обманом. */
export function findChrome(env = process.env, home = homedir()) {
  if (env.CHROME_PATH) return existsSync(env.CHROME_PATH) ? env.CHROME_PATH : null;
  return cached(home) || system(env);
}

/** Путь к Chrome; нет его — одна строка с командой установки и код 2, без трассировки. */
export function chromePath() {
  const p = findChrome();
  if (p) return p;
  const bad = process.env.CHROME_PATH ? ` (CHROME_PATH=${process.env.CHROME_PATH} — такого файла нет)` : '';
  console.error(NO_CHROME + bad);
  process.exit(2);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) console.log(chromePath());
