# -*- coding: utf-8 -*-
"""Пакет на рендер для другой машины и проверка вернувшегося результата.

    python engine/tools/render_pack.py make <фильм> --to <папка> [--exclude <шаблон>]... [--project DIR]
    python engine/tools/render_pack.py install [--dry-run]            (на той машине: ставит нужное)
    python engine/tools/render_pack.py run <фильм> [--reuse]          (на той машине: рендер и отчёт)
    python engine/tools/render_pack.py verify <report.json> <видео> [--expect <expect.json>]

make — собирает папку: engine/, project/ (без out/, .env и секретов, node_modules, кэшей), RENDER.md (три шага для
того, кто рендерит), FILES.md (какие файлы заказчика уезжают, с размерами и контрольными суммами) и expect.json
(что должно получиться: размер кадра, частота, длительность, число кадров, контрольная сумма страницы — отпечаток
index.html, film.json и файлов assets/ страницы, — полосы кадров швов со страницы). Страницу для ожиданий собирает
build.py --page (Chrome, под замком). Папка не пишется в непустое место, секретов в пакет не берёт: найденный ключ —
отказ с указанием файла и строки (значение не печатается). На этой машине make оставляет запись
`<out>/<фильм>/render_pack.json` с sha256 своего expect.json (в пакет она не едет: out/ не берётся).

run — внутри пакета: build.py <фильм> (финальный рендер) → return/video.mp4, return/report.json (размер, частота,
длительность, число кадров, контрольные суммы, сведения о машине, полосы кадров швов из готового видео),
return/expect.json и return/render.log. Возвращать нужно папку return/ целиком.

verify — здесь, в проекте, из которого собран пакет (или --project): сверяет отчёт и видео с ожидаемым. Ожидаемому
верит, только если sha256 файла expect.json (рядом с отчётом либо --expect) совпал с записью make на этой машине:
expect.json из return/ побывал на чужой стороне, и поправленный там файл даёт красное, а не зелёное. Нет записи —
тоже красное. Каждое расхождение — своя строка, код выхода 1. Картинка с другой
машины (видеокарта, драйвер, версия Chrome и кодека) может отличаться в пикселях, поэтому кадры сравниваются по
полосам швов — яркость 16×9 на кадр с допуском, а не побайтно. Для verify нужны только Pillow и ffmpeg, без Chrome.

Ничего не ставит и в сеть не ходит, кроме `install` на той стороне (npm ci по package-lock.json и pip).
"""
import os
import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE))
sys.path.insert(0, str(ENGINE / 'tools'))
import deps             # noqa: E402
deps.need('PIL', 'imageio_ffmpeg')

import argparse         # noqa: E402
import fnmatch          # noqa: E402
import hashlib          # noqa: E402
import json             # noqa: E402
import platform         # noqa: E402
import re               # noqa: E402
import shutil           # noqa: E402
import subprocess       # noqa: E402
import tempfile         # noqa: E402
import time             # noqa: E402

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')
sys.dont_write_bytecode = True
import project_root   # noqa: E402
import strip          # noqa: E402  seam_span, _frame_of, frames — тот же способ добыть кадр, что у всех проверок

VIDEO = ENGINE / 'video'
FORMAT = 1
RECORD = 'render_pack.json'          # запись make на этой машине: <out>/<фильм>/render_pack.json
RECORD_KEEP = 50                     # столько последних пакетов фильма помнит запись
SIG_W, SIG_H = 16, 9                 # подпись кадра: яркость сеткой 16×9
STRIP_FPS = 10                       # кадров в секунду у полосы шва
STRIP_SCALE = 0.25                   # размер кадра полосы — четверть холста
FRAME_MAD = 14                       # допуск полосы: средняя разница яркости подписи кадра, из 255
BAD_SHARE = 0.10                     # столько кадров полосы может выйти за допуск (кодек, другой драйвер)
SAME_VIDEO_MAD = 3                   # подпись кадра из того же видео на той же стороне почти не отличается
DURATION_SLACK_FRAMES = 1            # длительность и число кадров — плюс-минус кадр
SKIP_DIRS = {'node_modules', '__pycache__', '.git', '.hg', '.svn'}
SECRET_FILES = ('.env', '.env.*', '*.pem', '*.key', '*.p12', '*.pfx', 'secrets*', 'credentials*', 'id_rsa*')
TEXT_EXT = {'.json', '.md', '.txt', '.ini', '.cfg', '.toml', '.yml', '.yaml', '.js', '.mjs', '.py', '.html', '.css',
            '.csv', '.env', ''}
SECRET_LINE = re.compile(r'''^\s*["']?[A-Za-z0-9_]*(API_?KEY|SECRET|TOKEN|PASSWORD|GROUP_?ID)["']?\s*[=:]\s*'''
                         r'''["']?[A-Za-z0-9_\-./+=]{8,}''', re.I)
INSTALL_PIP = ['Pillow', 'imageio-ffmpeg', 'fonttools']
NOTE_PIXELS = ('Картинка, снятая на другой машине (видеокарта, драйвер, версия Chrome и кодека), может отличаться в '
               'пикселях: кадры сравниваются по полосам швов (яркость %dx%d на кадр, допуск %d из 255), не побайтно.'
               % (SIG_W, SIG_H, FRAME_MAD))


def fail(msg):
    raise SystemExit('ОШИБКА: ' + msg)


def load_json(path, what):
    try:
        with open(path, encoding='utf-8-sig') as fh:
            return json.load(fh)
    except OSError as e:
        fail('не открыть %s (%s): %s' % (what, path, e.strerror or e))
    except ValueError as e:
        fail('%s (%s) не читается как JSON: %s' % (what, path, e))


def write_json(path, data):
    with open(path, 'w', encoding='utf-8', newline='\n') as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
        fh.write('\n')


def sha256_file(path):
    return strip.sha256_file(str(path))


def ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def _env():
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    env.pop('MOTION_PROJECT', None)
    return env


# ------------------------------------------------------------------ видео: сведения и кадры

def probe_video(path):
    """Что за видео: {file, size_bytes, sha256, width, height, fps, frames, duration_sec, container_sec, audio}.
    Кадры считаются без декодирования (stream copy), длительность видео — кадры / частота."""
    path = str(path)
    if not os.path.isfile(path):
        fail('нет видеофайла %s' % path)
    info = subprocess.run([ffmpeg(), '-hide_banner', '-i', path], capture_output=True, text=True, encoding='utf-8',
                          errors='replace').stderr
    v = re.search(r'Stream #\d+:\d+[^\n]*Video:[^\n]*?,\s*(\d{2,5})x(\d{2,5})[^\n]*?,\s*([\d.]+) fps', info)
    if not v:
        fail('в %s нет видеопотока, который можно прочесть (ffmpeg не показал размер и частоту)' % path)
    d = re.search(r'Duration:\s*(\d+):(\d+):([\d.]+)', info)
    run = subprocess.run([ffmpeg(), '-hide_banner', '-i', path, '-map', '0:v:0', '-c', 'copy', '-f', 'null', '-'],
                         capture_output=True, text=True, encoding='utf-8', errors='replace').stderr
    fr = re.findall(r'frame=\s*(\d+)', run)
    fps = float(v.group(3))
    frames = int(fr[-1]) if fr else 0
    return {'file': os.path.basename(path), 'size_bytes': os.path.getsize(path), 'sha256': sha256_file(path),
            'width': int(v.group(1)), 'height': int(v.group(2)), 'fps': fps, 'frames': frames,
            'duration_sec': round(frames / fps, 4) if fps else 0.0,
            'container_sec': round(int(d.group(1)) * 3600 + int(d.group(2)) * 60 + float(d.group(3)), 4) if d else None,
            'audio': bool(re.search(r'Stream #\d+:\d+[^\n]*Audio:', info))}


def signature(png):
    """Подпись кадра: яркость сеткой SIG_W×SIG_H (список из 144 чисел 0…255)."""
    from PIL import Image
    with Image.open(png) as im:
        return list(im.convert('L').resize((SIG_W, SIG_H), Image.BOX).getdata())


def video_frames(video, numbers, size, dest):
    """Кадры видео с этими номерами (с нуля), уменьшенные до size → {номер: путь PNG}. Номеров за концом видео
    в ответе нет."""
    nums = sorted(set(int(n) for n in numbers))
    if not nums:
        return {}
    sel = '+'.join('eq(n\\,%d)' % n for n in nums)
    cmd = [ffmpeg(), '-hide_banner', '-loglevel', 'error', '-i', str(video), '-map', '0:v:0',
           '-vf', 'select=%s,scale=%d:%d:flags=area' % (sel, size[0], size[1]), '-vsync', '0',
           os.path.join(dest, 'f%06d.png')]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
    got = sorted(f for f in os.listdir(dest) if f.startswith('f') and f.endswith('.png'))
    if r.returncode != 0 and not got:
        fail('ffmpeg не снял кадры из %s: %s' % (video, r.stderr.strip()[-300:]))
    return {n: os.path.join(dest, f) for n, f in zip(nums, got)}


def seam_strips(video, strips, size):
    """Подписи кадров видео по описанию полос из expect.json → [{id, t0, t1, fps, frames: [{t, f, sig, sha256}]}]
    (кадр, которого в видео нет, — без sig). Контрольная сумма — у картинки уменьшенного кадра."""
    out = []
    with tempfile.TemporaryDirectory(prefix='render_pack_') as tmp:
        for k, s in enumerate(strips):
            d = os.path.join(tmp, 'strip%d' % k)
            os.makedirs(d)
            files = video_frames(video, [fr['f'] for fr in s['frames']], size, d)
            frs = []
            for fr in s['frames']:
                p = files.get(fr['f'])
                rec = {'t': fr['t'], 'f': fr['f']}
                if p:
                    rec['sig'] = signature(p)
                    rec['sha256'] = sha256_file(p)
                frs.append(rec)
            out.append({'id': s['id'], 't0': s['t0'], 't1': s['t1'], 'fps': s['fps'], 'frames': frs})
    return out


def strip_distance(a, b):
    """Средняя разница яркости двух подписей, из 255."""
    return sum(abs(x - y) for x, y in zip(a, b)) / float(len(a))


# ------------------------------------------------------------------ make

def record_path(root, film):
    """Где лежит запись make: <out>/<фильм>/render_pack.json; нет project.json или имя фильма — не имя — None."""
    root = Path(root)
    if not isinstance(film, str) or not film or os.path.basename(film) != film or film in ('.', '..'):
        return None
    if not (root / 'project.json').exists():
        return None
    _, out = strip.out_root(root)
    return out / film / RECORD


def known_packs(root, film):
    """Пакеты фильма, собранные make на этой машине: [{made_at, to, expect_sha256}], последний — в конце."""
    path = record_path(root, film)
    if path is None or not path.exists():
        return []
    try:
        with open(path, encoding='utf-8-sig') as fh:
            packs = json.load(fh).get('packs')
    except (OSError, ValueError, AttributeError):
        return []
    return [p for p in packs or [] if isinstance(p, dict) and p.get('expect_sha256')]


def remember_pack(root, film, expect_path, to):
    """Записать sha256 expect.json собранного пакета — по этой записи verify узнаёт своё ожидаемое."""
    path = record_path(root, film)
    sha = sha256_file(expect_path)
    packs = [p for p in known_packs(root, film) if p['expect_sha256'] != sha]
    packs.append({'made_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'to': str(to), 'expect_sha256': sha})
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    write_json(tmp, {'format': FORMAT, 'film': film, 'packs': packs[-RECORD_KEEP:]})
    os.replace(tmp, path)
    return path


def distrust(root, film, expect_path):
    """None, если expect.json — тот, что записал make на этой машине; иначе строка, почему ему нельзя верить."""
    packs = known_packs(root, film)
    if not packs:
        where = record_path(root, film) or (Path(root) / 'project.json')
        return ('нет записи make для фильма «%s» на этой машине (%s): expect.json нечем подтвердить, а тот, что пришёл с '
                'чужой стороны, мог быть там поправлен. Запусти verify в проекте, из которого собран пакет '
                '(--project <папка project>); записи нет и там — собери пакет заново (make) и дай его expect.json '
                'ключом --expect: пока проект не менялся, ожидаемое в нём то же' % (film, where))
    sha = sha256_file(expect_path)
    if any(p['expect_sha256'] == sha for p in packs):
        return None
    last = packs[-1]
    return ('%s — не тот expect.json, что записал make на этой машине (sha256 %s…, в записи %s): его правили на той '
            'стороне, или он от другого пакета. Ожидаемое лежит в пакете на этой машине: --expect %s'
            % (expect_path, sha[:12], ', '.join(p['expect_sha256'][:12] + '…' for p in packs[-3:]),
               Path(last.get('to') or '<папка пакета>') / 'expect.json'))


def _excluded(rel, patterns):
    return any(fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(os.path.basename(rel), p) or rel.startswith(p.rstrip('/') + '/')
               for p in patterns)


def collect_project(root, out_rel, exclude):
    """Файлы проекта, которые уедут: [(путь от корня проекта с '/', абсолютный)] и что отброшено по группам."""
    keep, dropped = [], {'out': 0, 'секреты': 0, 'кэши': 0, 'по --exclude': 0}
    out_rel = out_rel.strip('/')
    for base, dirs, files in os.walk(root):
        rel_dir = os.path.relpath(base, root).replace(os.sep, '/')
        rel_dir = '' if rel_dir == '.' else rel_dir
        keep_dirs = []
        for d in sorted(dirs):
            rel = (rel_dir + '/' + d).lstrip('/')
            if d in SKIP_DIRS:
                dropped['кэши'] += 1
            elif rel == out_rel:
                dropped['out'] += 1
            elif _excluded(rel, exclude):
                dropped['по --exclude'] += 1
            else:
                keep_dirs.append(d)
        dirs[:] = keep_dirs
        for f in sorted(files):
            rel = (rel_dir + '/' + f).lstrip('/')
            if f.endswith('.pyc'):
                dropped['кэши'] += 1
            elif any(fnmatch.fnmatch(f.lower(), p) for p in SECRET_FILES):
                dropped['секреты'] += 1
            elif _excluded(rel, exclude):
                dropped['по --exclude'] += 1
            else:
                keep.append((rel, os.path.join(base, f)))
    return keep, dropped


def scan_secrets(files):
    """Строки вида КЛЮЧ=значение в текстовых файлах проекта: [(путь, номер строки, имя ключа)] — значение не берётся."""
    found = []
    for rel, p in files:
        if os.path.splitext(rel)[1].lower() not in TEXT_EXT or os.path.getsize(p) > 2_000_000:
            continue
        try:
            with open(p, encoding='utf-8', errors='replace') as fh:
                for n, line in enumerate(fh, 1):
                    m = SECRET_LINE.match(line)
                    if m:
                        found.append((rel, n, line.split('=')[0].split(':')[0].strip(' "\'\t')[:60]))
        except OSError:
            continue
    return found


def film_files(root, film):
    """Файлы, которые называет фильм: [(что, путь от корня проекта)] — озвучка реплик, манифест, сцены."""
    fp = Path(root) / 'films' / (film + '.json')
    if not fp.exists():
        fail('нет фильма %s' % fp)
    data = load_json(fp, 'фильм')
    need = [('фильм', 'films/%s.json' % film)]
    for s in data.get('scenes') or []:
        need.append(('сцена %s' % s, 'scenes/%s/storyboard.json' % s))
    for r in data.get('replies') or []:
        if r.get('file'):
            need.append(('озвучка реплики %s' % r.get('n', '?'), str(r['file']).replace('\\', '/')))
    if data.get('manifest'):
        need.append(('манифест звука', str(data['manifest']).replace('\\', '/')))
    return need


def human(n):
    for unit in ('Б', 'КБ', 'МБ', 'ГБ'):
        if n < 1024 or unit == 'ГБ':
            return ('%d %s' % (n, unit)) if unit == 'Б' else ('%.1f %s' % (n, unit))
        n /= 1024.0


def files_md(film, rows, dropped, total):
    top = {}
    for rel, size, _ in rows:
        key = rel.split('/')[0] if '/' in rel else '(корень проекта)'
        c = top.setdefault(key, [0, 0])
        c[0] += 1
        c[1] += size
    lines = ['# Файлы заказчика, которые уезжают с пакетом', '',
             'Фильм: `%s`. Всего %d файлов, %s. Это всё содержимое `project/` пакета: сцены, картинки, шрифты, звук, '
             'настройки. Секреты (`.env`, ключи) и папка `out/` не берутся никогда.' % (film, len(rows), human(total)), '',
             'Что уезжает, решает заказчик по каждому проекту: не нужное для рендера — исключить ключом '
             '`--exclude <шаблон>` при сборке пакета и собрать заново.', '',
             'Отброшено при сборке: ' + ', '.join('%s — %d' % (k, v) for k, v in dropped.items() if v) if any(dropped.values())
             else 'Отброшено при сборке: ничего.', '',
             '## По папкам', '', '| Папка | Файлов | Размер |', '|---|---|---|']
    for key in sorted(top):
        lines.append('| `%s` | %d | %s |' % (key, top[key][0], human(top[key][1])))
    lines += ['', '## Все файлы', '', '| Файл | Размер | sha256 |', '|---|---|---|']
    for rel, size, sha in rows:
        lines.append('| `%s` | %s | %s |' % (rel, human(size), sha[:16]))
    return '\n'.join(lines) + '\n'


def render_md(film, expect):
    v = expect['video']
    return """# Пакет на рендер: фильм `%(film)s`

Это готовая папка проекта. Рендерит тот, у кого она оказалась: человек, агент по командам заказчика или Claude Code
при прямом доступе. Нужна Windows 10 или новее, Python %(py)s+, интернет только для первого шага. Секретов в пакете нет и
не нужно: озвучка уже лежит файлами, ничего платного не вызывается.

Все команды — из этой папки (где лежит этот файл).

## 1. Установка (один раз, одной командой)

    python engine/tools/render_pack.py install

Ставит пакеты Python (Pillow, imageio-ffmpeg, fonttools), набор Node по `engine/video/package-lock.json`
(`npm ci`) и Chrome для рендера (`hyperframes browser ensure`). Node.js %(node)d или новее с npm должен быть на машине
заранее: `winget install OpenJS.NodeJS.LTS`. `--dry-run` показывает, что будет сделано, ничего не ставя. Если команда
`python` на машине не та или её нет — вместо `python` в командах ниже писать полный путь к python.exe.

## 2. Рендер

    python engine/tools/render_pack.py run %(film)s

Идёт долго (по ядрам машины, видеокарта не обязательна); тишина в консоли — не зависание. Другие браузеры на этой
машине на время рендера лучше закрыть. Итог: папка `return/` с `video.mp4`, `report.json`, `expect.json` и `render.log`.
Если команда остановилась с ошибкой — вернуть её последние строки, ничего не править в пакете.

## 3. Что вернуть

Папку `return/` целиком. Ничего другого возвращать не нужно: пакет остаётся на той машине.

## Что должно получиться (проверяется на стороне заказчика командой `verify`)

- кадр %(w)dx%(h)d, %(fps)s кадр/с, %(frames)d кадров, около %(dur)s с;
- страница фильма с контрольной суммой `%(sha)s`;
- кадры швов фильма совпадают с ожидаемыми по полосам: пиксели на другой машине могут чуть отличаться, это нормально.
""" % {'film': film, 'w': v['width'], 'h': v['height'], 'fps': ('%g' % v['fps']), 'frames': v['frames'],
       'dur': '%.1f' % v['duration_sec'], 'sha': expect['page_sha256'][:16] + '…',
       'py': '%d.%d' % deps.PYTHON_MIN, 'node': deps.NODE_MIN}


def build_page(root, film):
    cmd = [sys.executable, str(VIDEO / 'build.py'), film, '--page', '--project', str(root)]
    r = subprocess.run(cmd, env=_env(), capture_output=True, text=True, encoding='utf-8', errors='replace')
    if r.returncode != 0:
        fail('страница не собралась (build.py, код %d): %s' % (r.returncode, (r.stdout + r.stderr).strip()[-500:]))


def make_expect(root, film):
    """expect.json: что должно получиться — по странице фильма (build.py --page) и полосам швов со страницы."""
    build_page(root, film)
    _, out = strip.out_root(root)
    page = out / film
    meta = strip.read_film(str(page))
    fps = float(meta['fps'])
    canvas = meta['canvas']
    nframes = _frame_count(meta['duration'], fps)
    spans = []
    ids = [s['id'] for s in meta['scenes']]
    for x, y in zip(ids, ids[1:]):
        t0, t1 = strip.seam_span(meta, x, y)
        spans.append(('%s:%s' % (x, y), t0, t1))
    if not spans:                                   # один кадр-сцена: шва нет — берём начало и конец ролика
        d = meta['duration']
        spans = [('start', 0.0, min(1.0, d)), ('end', max(0.0, d - 1.0), d)]
    strips, size = [], None
    for sid, t0, t1 in spans:
        paths = strip.frames(root, film, t0, t1, STRIP_FPS, STRIP_SCALE, page=str(page))
        times = strip.frame_times(t0, t1, STRIP_FPS)
        if size is None:
            from PIL import Image
            with Image.open(paths[0]) as im:
                size = list(im.size)
        strips.append({'id': sid, 't0': round(t0, 4), 't1': round(t1, 4), 'fps': STRIP_FPS,
                       'frames': [{'t': round(t, 4), 'f': strip._frame_of(t, fps), 'sig': signature(p)}
                                  for p, t in zip(paths, times)]})
    return {'format': FORMAT, 'film': film, 'page_sha256': strip.page_sha(page),
            'video': {'width': int(canvas['w']), 'height': int(canvas['h']), 'fps': fps, 'frames': nframes,
                      'duration_sec': round(nframes / fps, 4), 'film_duration_sec': round(float(meta['duration']), 4)},
            'strip_size': size, 'sig_grid': [SIG_W, SIG_H],
            'tolerance': {'frame_mad': FRAME_MAD, 'bad_share': BAD_SHARE, 'frames': DURATION_SLACK_FRAMES},
            'strips': strips}


def _frame_count(duration, fps):
    raw = duration * fps                    # как у build.frame_count: HyperFrames, eps 1e-3
    near = round(raw)
    return int(near if abs(raw - near) <= 1e-3 else int(raw) + 1)


def cmd_make(a, root):
    to = Path(a.to).resolve()
    root = Path(root).resolve()
    if not (root / 'project.json').exists():
        fail('в %s нет project.json: корень проекта — %s' % (root, project_root.RULE))
    if to == root or root in to.parents or to in root.parents:
        fail('пакет нельзя класть внутрь проекта или над ним (%s): возьми новую папку рядом' % to)
    if to.exists() and (not to.is_dir() or any(to.iterdir())):
        fail('папка %s не пуста — ничего не тронуто. Возьми новую или пустую' % to)
    pj = load_json(root / 'project.json', 'project.json')
    out_rel = ((pj.get('paths') or {}).get('out')) or 'out'
    keep, dropped = collect_project(root, out_rel, a.exclude or [])
    present = {rel for rel, _ in keep}
    for what, rel in film_files(root, a.film):
        if rel not in present:
            hint = (' (лежит в %s/, а он в пакет не берётся: положи копию вне него и поправь путь)' % out_rel
                    if rel.startswith(out_rel.strip('/') + '/') else '')
            fail('фильму %s нужен файл «%s» — %s, а в пакет он не попал%s' % (a.film, rel, what, hint))
    leaks = scan_secrets(keep)
    if leaks:
        fail('в проекте найдены похожие на секрет строки — пакет не собран, значения не печатаю:\n  '
             + '\n  '.join('%s:%d — %s' % x for x in leaks[:10]) + '\nУбери ключи из этих файлов или исключи их (--exclude).')
    expect = make_expect(root, a.film)             # страница и кадры — до копирования: нет Chrome — нет и папки
    to.mkdir(parents=True, exist_ok=True)
    shutil.copytree(ENGINE, to / 'engine', ignore=_ignore_engine)
    rows, total = [], 0
    for rel, src in keep:
        dst = to / 'project' / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        size = os.path.getsize(src)
        rows.append((rel, size, sha256_file(src)))
        total += size
    (to / 'project' / out_rel).mkdir(exist_ok=True)         # пустая out/: сюда пойдёт рендер
    write_json(to / 'expect.json', expect)
    (to / 'RENDER.md').write_text(render_md(a.film, expect), encoding='utf-8', newline='\n')
    (to / 'FILES.md').write_text(files_md(a.film, rows, dropped, total), encoding='utf-8', newline='\n')
    record = remember_pack(root, a.film, to / 'expect.json', to)
    print('пакет: %s · %d файлов проекта, %s' % (to, len(rows), human(total)))
    print('  дальше: на той машине RENDER.md; вернувшееся — здесь, в этом проекте: "%s" engine/tools/render_pack.py verify '
          '<return>/report.json <return>/video.mp4' % deps.PYTHON)
    print('  ожидаемое записано: %s — по этой записи verify отличает свой expect.json от поправленного' % record)
    print('  что уезжает из материалов заказчика — %s (решает заказчик по каждому проекту)' % (to / 'FILES.md'))
    return 0


def _ignore_engine(_dir, names):
    return [n for n in names if n in SKIP_DIRS or n == 'out' or n.endswith('.pyc')]


# ------------------------------------------------------------------ install / run

def install_steps():
    """Что ставит install: [(описание, команда)]."""
    steps = [('пакеты Python', [sys.executable, '-m', 'pip', 'install'] + INSTALL_PIP)]
    npm = shutil.which('npm') or 'npm'
    steps.append(('набор Node по package-lock.json (npm ci)', [npm, 'ci', '--no-audit', '--no-fund']))
    hf = ['node', os.path.join('node_modules', 'hyperframes', 'bin', 'hyperframes.mjs'), 'browser', 'ensure']
    steps.append(('Chrome для рендера', hf))
    return steps


def cmd_install(a):
    steps = install_steps()
    for what, cmd in steps:
        print('%s: %s' % (what, ' '.join(cmd)))
    if a.dry_run:
        print('(--dry-run: ничего не поставлено)')
        return 0
    node = deps.node_version()
    if node is None or not shutil.which('npm'):
        fail('нужен Node.js %d или новее с npm: %s' % (deps.NODE_MIN, deps.NODE_INSTALL))
    for what, cmd in steps:
        cwd = str(VIDEO) if cmd[0] != sys.executable else None
        print('— %s' % what, flush=True)
        if subprocess.run(cmd, cwd=cwd).returncode != 0:
            fail('шаг «%s» не вышел; повтори команду, она ничего не ломает. Вернуть вывод — тому, кто прислал пакет' % what)
    print('установка закончена: дальше шаг 2 из RENDER.md')
    return 0


def machine_info():
    """Сведения о машине: система, ядра, версии Python, Node, HyperFrames, ffmpeg, видеокарты (если удалось узнать)."""
    gpus = []
    if os.name == 'nt':
        try:
            r = subprocess.run(['powershell', '-NoProfile', '-Command',
                                '(Get-CimInstance Win32_VideoController).Name -join "|"'],
                               capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30)
            gpus = [x.strip() for x in r.stdout.strip().split('|') if x.strip()]
        except (OSError, subprocess.TimeoutExpired):
            pass
    ff = subprocess.run([ffmpeg(), '-version'], capture_output=True, text=True, encoding='utf-8', errors='replace')
    return {'platform': platform.platform(), 'machine': platform.machine(), 'cores': os.cpu_count(),
            'python': platform.python_version(), 'node': deps.node_version(),
            'hyperframes': deps.package_version(deps.NODE_MODULES, 'hyperframes'),
            'ffmpeg': (ff.stdout.splitlines() or [''])[0], 'gpu': gpus or None}


def cmd_run(a, root):
    root = Path(root).resolve()
    exp_path = root.parent / 'expect.json'
    if not exp_path.exists():
        fail('нет %s: команда запускается внутри пакета, который собрал `make`' % exp_path)
    expect = load_json(exp_path, 'expect.json')
    film = a.film
    if film != expect.get('film'):
        fail('пакет собран для фильма «%s», а запрошен «%s»' % (expect.get('film'), film))
    lost = deps.missing(chrome=True)
    if lost:
        print('\n'.join(deps.report(lost)), file=sys.stderr)
        print('всё разом: "%s" engine/tools/render_pack.py install' % deps.PYTHON, file=sys.stderr)
        return 2
    _, out = strip.out_root(root)
    video = out / film / 'video.mp4'
    t0 = time.time()
    if not a.reuse:
        print('рендер: build.py %s (долго; тишина — не зависание)' % film, flush=True)
        r = subprocess.run([sys.executable, str(VIDEO / 'build.py'), film, '--project', str(root)], env=_env())
        if r.returncode != 0:
            fail('рендер не прошёл (build.py, код %d): вернуть последние строки вывода' % r.returncode)
    elif not video.exists():
        fail('--reuse: нет готового %s' % video)
    if not video.exists():
        fail('рендер закончился без %s' % video)
    elapsed = time.time() - t0
    ret = root.parent / 'return'
    shutil.rmtree(ret, ignore_errors=True)
    ret.mkdir()
    shutil.copyfile(video, ret / 'video.mp4')
    for name in ('render.log',):
        if (out / film / name).exists():
            shutil.copyfile(out / film / name, ret / name)
    shutil.copyfile(exp_path, ret / 'expect.json')
    info = probe_video(ret / 'video.mp4')
    page_sha = strip.page_sha(out / film)
    size = expect.get('strip_size') or [480, 270]
    report = {'format': FORMAT, 'film': film, 'made_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
              'render_sec': None if a.reuse else round(elapsed, 1), 'page_sha256': page_sha,
              'film_json_sha256': sha256_file(out / film / 'film.json'), 'video': info,
              'machine': machine_info(), 'strip_size': size, 'strips': seam_strips(ret / 'video.mp4', expect['strips'], size)}
    write_json(ret / 'report.json', report)
    same = 'совпала с ожидаемой' if page_sha == expect['page_sha256'] else 'НЕ совпала с ожидаемой — вернуть как есть'
    print('готово: %s · %dx%d, %g кадр/с, %d кадров, %.2f с · страница %s' % (
        ret, info['width'], info['height'], info['fps'], info['frames'], info['duration_sec'], same))
    print('вернуть папку return/ целиком')
    return 0


# ------------------------------------------------------------------ verify

def compare(expect, report, actual, actual_strips):
    """Расхождения: список строк. actual — probe_video присланного видео, actual_strips — seam_strips из него же."""
    bad = []
    ev = expect['video']
    slack = int(expect.get('tolerance', {}).get('frames', DURATION_SLACK_FRAMES))
    if report.get('film') != expect.get('film'):
        bad.append('отчёт от другого фильма: «%s», ждали «%s»' % (report.get('film'), expect.get('film')))
    if report.get('page_sha256') != expect.get('page_sha256'):
        bad.append('отчёт от другой страницы: контрольная сумма %s…, ждали %s… — отрендерено не то, что отправлено'
                   % (str(report.get('page_sha256'))[:12], expect['page_sha256'][:12]))
    if (actual['width'], actual['height']) != (ev['width'], ev['height']):
        bad.append('видео другого размера: %dx%d, ждали %dx%d' % (actual['width'], actual['height'], ev['width'], ev['height']))
    if abs(actual['fps'] - ev['fps']) > 0.01:
        bad.append('видео другой частоты: %g кадр/с, ждали %g' % (actual['fps'], ev['fps']))
    if abs(actual['frames'] - ev['frames']) > slack:
        bad.append('видео другой длины: %d кадров (%.2f с), ждали %d (%.2f с)'
                   % (actual['frames'], actual['duration_sec'], ev['frames'], ev['duration_sec']))
    rv = report.get('video') or {}
    if rv.get('sha256') != actual['sha256']:
        bad.append('видео не то, что описано в отчёте: контрольная сумма файла %s…, в отчёте %s…'
                   % (actual['sha256'][:12], str(rv.get('sha256'))[:12]))
    if (rv.get('width'), rv.get('height'), rv.get('frames')) != (actual['width'], actual['height'], actual['frames']):
        bad.append('размер или число кадров в отчёте (%sx%s, %s) не совпадают с присланным видео (%dx%d, %d)'
                   % (rv.get('width'), rv.get('height'), rv.get('frames'), actual['width'], actual['height'], actual['frames']))
    tol = expect.get('tolerance') or {}
    mad, share = float(tol.get('frame_mad', FRAME_MAD)), float(tol.get('bad_share', BAD_SHARE))
    reported = {s['id']: s for s in report.get('strips') or []}
    for want, got in zip(expect['strips'], actual_strips):
        n = len(want['frames'])
        over, missing = [], 0
        for w, g in zip(want['frames'], got['frames']):
            if 'sig' not in g:
                missing += 1
            elif strip_distance(w['sig'], g['sig']) > mad:
                over.append(w['t'])
        if missing:
            bad.append('полоса шва %s: в видео нет %d из %d кадров' % (want['id'], missing, n))
        if len(over) > share * n:
            bad.append('полоса шва %s: %d из %d кадров вне допуска %g (кадры на %s с) — картинка не та'
                       % (want['id'], len(over), n, mad, ', '.join('%g' % t for t in over[:4])))
        rs = reported.get(want['id'])
        if rs is None:
            bad.append('в отчёте нет полосы шва %s' % want['id'])
        else:
            far = sum(1 for r, g in zip(rs.get('frames', []), got['frames'])
                      if 'sig' in g and ('sig' not in r or strip_distance(r['sig'], g['sig']) > SAME_VIDEO_MAD))
            if far > share * n:
                bad.append('полоса шва %s в отчёте не из присланного видео: %d из %d кадров расходятся' % (want['id'], far, n))
    return bad


def cmd_verify(a, root):
    report = load_json(a.report, 'отчёт')
    exp_path = Path(a.expect) if a.expect else Path(a.report).resolve().parent / 'expect.json'
    if not exp_path.exists():
        fail('нет expect.json рядом с отчётом (%s): он лежит в пакете, собранном `make`, и в return/; '
             'или укажи --expect <путь>' % exp_path)
    expect = load_json(exp_path, 'expect.json')
    for key in ('film', 'page_sha256', 'video', 'strips', 'strip_size'):
        if key not in expect:
            fail('в %s нет «%s»: это не expect.json пакета' % (exp_path, key))
    if report.get('format') != FORMAT or 'video' not in report or 'page_sha256' not in report:
        fail('%s не похож на report.json этой версии (format %s, нужен %d)' % (a.report, report.get('format'), FORMAT))
    why = distrust(root, expect.get('film'), exp_path)
    if why:                                # до сверки: по неподтверждённому ожидаемому зелёного не бывает
        print('КРАСНОЕ: ' + why)
        print('verify: ожидаемое не подтверждено — видео не сверялось')
        return 1
    actual = probe_video(a.video)
    actual_strips = seam_strips(a.video, expect['strips'], expect['strip_size'])
    bad = compare(expect, report, actual, actual_strips)
    mach = report.get('machine') or {}
    print('машина отчёта: %s · %s ядер · HyperFrames %s · видеокарты: %s' % (
        mach.get('platform', '?'), mach.get('cores', '?'), mach.get('hyperframes', '?'),
        ', '.join(mach.get('gpu') or []) or 'нет данных'))
    print(NOTE_PIXELS)
    if bad:
        for line in bad:
            print('КРАСНОЕ: ' + line)
        print('verify: %d расхождений' % len(bad))
        return 1
    print('verify: зелёное — %dx%d, %g кадр/с, %d кадров, страница и полосы швов (%d) совпали'
          % (actual['width'], actual['height'], actual['fps'], actual['frames'], len(expect['strips'])))
    return 0


# ------------------------------------------------------------------ вход

def main(argv):
    root, rest = project_root.split_argv(argv)
    ap = argparse.ArgumentParser(description='Пакет на рендер для другой машины и проверка результата.')
    sub = ap.add_subparsers(dest='cmd', required=True)
    m = sub.add_parser('make', help='собрать папку-пакет')
    m.add_argument('film', help='имя файла в films/ без .json')
    m.add_argument('--to', required=True, help='новая или пустая папка')
    m.add_argument('--exclude', action='append', help='не брать файл или папку проекта (шаблон, от корня проекта)')
    i = sub.add_parser('install', help='на той машине: поставить нужное')
    i.add_argument('--dry-run', action='store_true', help='показать шаги, ничего не ставить')
    r = sub.add_parser('run', help='на той машине: рендер и отчёт в return/')
    r.add_argument('film')
    r.add_argument('--reuse', action='store_true', help='не рендерить: взять готовое out/<фильм>/video.mp4')
    v = sub.add_parser('verify', help='сверить отчёт и видео с ожидаемым')
    v.add_argument('report')
    v.add_argument('video')
    v.add_argument('--expect', help='expect.json (по умолчанию рядом с отчётом); любой сверяется с записью make '
                                    'на этой машине')
    a = ap.parse_args(rest)
    if a.cmd == 'make':
        return cmd_make(a, root)
    if a.cmd == 'install':
        return cmd_install(a)
    if a.cmd == 'run':
        return cmd_run(a, root)
    return cmd_verify(a, root)


if __name__ == '__main__':
    sys.exit(deps.run(main, sys.argv[1:]))
