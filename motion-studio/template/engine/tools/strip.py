# -*- coding: utf-8 -*-
"""Полоса кадров, лист с таймкодами и короткое видео сцены, шва, момента или отрезка — со страницы, без рендера.

    python engine/tools/strip.py <фильм> (--scene <id> | --seam <a>:<b> | --at <реплика>:<доля>[:<смещение>]
                                          | --range <t0>:<t1>) [--fps 10] [--height 270] [--video] [--gif]
                                         [--pair <папка прежней полосы>] [--name <имя>] [--no-build] [--project DIR]

Страницу фильма собирает `build.py <фильм> --page` (шов — `--only a,b --page`: пара сцен, кадр входа соседа на
месте), кадры снимает `engine/video/probe_frames.mjs --strip` тем же путём, что рендер и промер DOM: seek
таймлайна window.__timelines.main. Результат — `<out>/<фильм>/strips/<имя>/`:
  strip.png    кадры в ряд (при длинном отрезке — каждый N-й, чтобы ряд не был шире 12000 px; N в strip.json)
  sheet.png    все кадры сеткой с таймкодами
  frames/NNNN.png, strip.json {film, kind, id, t0, t1, fps, scale, frames[], page_sha256, ...}
  clip.mp4     при --video, длится столько же, сколько отрезок; clip.gif — при --gif
  pair.png     при --pair: прежняя полоса над новой по тем же таймкодам (отрезки обязаны совпасть). Прежняя
               читается до первой записи, поэтому --pair можно дать и на папку с тем же именем, что у новой
               полосы: «было» над «стало», затем папка переписывается новой полосой
Имя по умолчанию: scene-<id>, seam-<a>-<b>, at-<реплика>-<доля>, range-<t0>-<t1>. --name — одна часть пути внутри
strips/: без косых черт и двоеточия, не «.», не «..», не «_cache»; иначе отказ до первой записи (папка полосы перед записью
стирается — имя с частями пути стёрло бы чужое).

Время кадров — от начала отрезка: t0 + k/fps, k < round((t1 − t0)·fps); кадр с временем t — кадр фильма в момент t
при любой частоте полосы (номер кадра считается по частоте фильма). Для шва t0 и t1 — в времени страницы пары
(там первая сцена начинается с нуля). Момент по якорю — как в раскадровке: старт реплики + доля·длина + смещение, с;
вокруг него берётся окно ±AT_HALF_SEC. Допустимые сцены, швы и реплики назвала бы ошибка, если указано не то.

Из проверок: `strip.frames(project, film, t0, t1, fps, scale)` → пути кадров; на тех же аргументах и той же странице
Chrome второй раз не запускается (кадры лежат в `<out>/<фильм>/strips/_cache/`). «Та же страница» — тот же отпечаток
`stamp.page_print`: index.html, film.json и каждый файл assets/ страницы; картинка или шрифт, заменённые под тем же
именем, кадры переснимают. Этот же отпечаток одной строкой (`page_sha`) — поле page_sha256 в strip.json.

Замок Chrome берётся здесь же (chrome_lock.held, предел ожидания — MOTION_CHROME_LOCK_TIMEOUT); внутри check_all
или with_chrome_lock замок уже чей-то и второй раз не берётся. В проект пишется только `<out>/<фильм>/strips/`
(и страница, которую собирает build.py, — в свой out/).
"""
import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')
sys.dont_write_bytecode = True
ENGINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ENGINE)
sys.path.insert(0, os.path.join(ENGINE, 'video'))
import chrome_lock   # noqa: E402
import deps          # noqa: E402
import project_root  # noqa: E402
import stamp         # noqa: E402  отпечаток страницы — один на рендер, проверки и полосы

VIDEO = os.path.join(ENGINE, 'video')
AT_HALF_SEC = 1.0           # окно вокруг момента по якорю: ±1 с
SEAM_PAD_SEC = 0.5          # шов: от конца последней реплики a до 0,5 с после первой реплики b (как у проверок)
STRIP_MAX_W = 12000         # шире ряд не делаем: картинка не откроется в просмотрщике
SHEET_COLS = 6
EPS = 1e-6
CACHE_DIR = '_cache'        # кэш кадров рядом с папками полос: именем полосы быть не может
NAME_BAD_CHARS = '/\\:*?"<>|'


def fail(msg):
    raise SystemExit('ОШИБКА: ' + msg)


def _num(x, what):
    try:
        return float(x)
    except ValueError:
        fail('%s: «%s» — не число' % (what, x))


def out_root(project):
    """<проект>/out (project.json paths.out, по умолчанию out)."""
    root = project_root.resolve(project)
    pj = root / 'project.json'
    if not pj.exists():
        fail('нет %s (корень проекта: %s)' % (pj, project_root.RULE))
    with open(pj, encoding='utf-8-sig') as fh:
        rel = ((json.load(fh).get('paths') or {}).get('out')) or 'out'
    return root, (root / rel).resolve()


def _fmt(t):
    return ('%.3f' % t).rstrip('0').rstrip('.')


def slug(t):
    return _fmt(t).replace('.', '_')


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def page_sha(page):
    """Отпечаток страницы одной строкой: sha256 от stamp.page_print(page) — index.html, film.json и каждый файл
    assets/ страницы (JSON с ключами по алфавиту). Ключ кэша кадров и поле page_sha256 в strip.json и в пакете."""
    pp = stamp.page_print(str(page))
    if pp is None:
        fail('нет страницы %s (index.html и film.json): build.py <фильм> --page' % page)
    return hashlib.sha256(json.dumps(pp, sort_keys=True).encode('utf-8')).hexdigest()


def strip_name(name):
    """Имя папки полосы внутри strips/ — одна часть пути; иначе отказ. Windows срезает у имени папки точки и
    пробелы в конце и не различает регистр: «keep.», « » и «_CACHE» — те же «keep», «strips/» и «_cache»."""
    bad = (not name or name != name.strip() or name.endswith('.') or name.lower() == CACHE_DIR
           or any(c in NAME_BAD_CHARS or ord(c) < 32 for c in name))
    if bad:
        fail('--name «%s» не годится: имя папки полосы — одна часть пути, без «/», «\\» и «:», не «.», не «..», не «%s», '
             'без точки и пробела по краям (полоса кладётся в <out>/<фильм>/strips/<имя>/)' % (name, CACHE_DIR))
    return name


def read_film(page):
    p = os.path.join(page, 'film.json')
    if not os.path.exists(p):
        fail('нет %s: страницу собирает build.py <фильм> --page' % p)
    with open(p, encoding='utf-8') as fh:
        return json.load(fh)


# ---------- кадры ----------

def frame_times(t0, t1, fps):
    """Времена кадров отрезка: t0 + k/fps, k < round((t1 − t0)·fps), не меньше одного."""
    n = max(1, int(round((t1 - t0) * fps)))
    return [t0 + k / fps for k in range(n)]


def _frame_of(t, fps):
    """Номер кадра ФИЛЬМА в момент t: fps — частота фильма (film.json), а не полосы. Промер ставит время как
    номер / fps фильма, поэтому по частоте полосы кадр «t» снимался бы в момент t · (fps полосы / fps фильма)."""
    return int(math.floor(t * fps + 0.5 + 5e-3))        # то же правило, что у рендера и probe_frames.mjs


def _node(args):
    return subprocess.run(['node', os.path.join(VIDEO, 'probe_frames.mjs')] + args, capture_output=True, text=True,
                          encoding='utf-8', errors='replace')


def frames(project, film, t0, t1, fps, scale, page=None):
    """Кадры отрезка [t0, t1) страницы фильма как пути PNG (в порядке времени).

    project — корень проекта (или None: правило --project → MOTION_PROJECT → шаблон), film — имя фильма;
    page — папка страницы (по умолчанию <out>/<фильм>; для шва — <out>/<фильм>--a,b). Страница должна быть собрана
    (build.py <фильм> --page). scale — доля размера холста (0,25 → 480×270 для 1920×1080). Кадры лежат в
    <out>/<фильм>/strips/_cache/<ключ>/; ключ — отпечаток страницы и аргументов, поэтому те же аргументы на той же
    странице Chrome не запускают. Замок Chrome берётся здесь (вложенный — не ждёт)."""
    _, out = out_root(project)
    page = os.path.abspath(page or out / film)
    index = os.path.join(page, 'index.html')
    if not os.path.exists(index):
        fail('нет страницы %s: build.py %s --page' % (index, film))
    meta = read_film(page)
    if not (fps > 0 and scale > 0 and t1 > t0 - EPS):
        fail('отрезок %s…%s с, %s кадр/с, масштаб %s — так кадры не сосчитать' % (t0, t1, fps, scale))
    if t0 < -EPS or t0 >= meta['duration'] - EPS:
        fail('отрезок %s…%s с вне фильма (длится 0…%s с)' % (_fmt(t0), _fmt(t1), _fmt(meta['duration'])))
    sha = page_sha(page)        # страница целиком: файл assets/, заменённый под тем же именем, кадры переснимает
    # «t2» в ключе: кадры сняты по частоте фильма; кэш прежнего счёта (по частоте полосы — не то время) не берётся
    key = hashlib.sha256(('t2|%s|%s|%s|%s|%s' % (sha, _fmt(t0), _fmt(t1), fps, scale)).encode()).hexdigest()[:20]
    cache = out / film / 'strips' / CACHE_DIR / key
    times = frame_times(t0, t1, fps)
    want = [str(cache / ('%04d.png' % (k + 1))) for k in range(len(times))]
    if all(os.path.exists(p) for p in want):
        return want
    shutil.rmtree(cache, ignore_errors=True)
    cache.mkdir(parents=True)
    film_fps = float(meta['fps'])                       # время кадра полосы → номер кадра фильма
    job = {'scale': scale, 'frames': [{'f': _frame_of(t, film_fps), 'file': p} for t, p in zip(times, want)]}
    fd, job_path = tempfile.mkstemp(prefix='strip-job-', suffix='.json')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            json.dump(job, fh)
        with chrome_lock.held('strip.py %s %s…%s' % (film, _fmt(t0), _fmt(t1))):
            r = _node([page, '--strip', job_path])
    finally:
        os.remove(job_path)
    if r.returncode != 0 or not all(os.path.exists(p) for p in want):
        shutil.rmtree(cache, ignore_errors=True)
        fail('промер кадров не снял полосу (код %d): %s' % (r.returncode, (r.stderr or r.stdout).strip()[-400:]))
    return want


# ---------- что снимать ----------

def resolve_span(meta, scenes_order, a):
    """(вид, id, t0, t1, имя по умолчанию, пара сцен или None) по флагу."""
    dur = meta['duration']
    ids = [s['id'] for s in meta['scenes']]
    if a.scene:
        if a.scene not in ids:
            fail('сцены «%s» нет в фильме; есть: %s' % (a.scene, ', '.join(ids)))
        s = [x for x in meta['scenes'] if x['id'] == a.scene][0]
        return 'scene', a.scene, s['start'], s['end'], 'scene-' + a.scene, None
    if a.seam:
        parts = a.seam.split(':')
        if len(parts) != 2 or not all(parts):
            fail('--seam <a>:<b> — две соседние сцены через двоеточие; швы фильма: %s'
                 % ', '.join('%s:%s' % (x, y) for x, y in zip(ids, ids[1:])))
        x, y = parts
        for n in (x, y):
            if n not in ids:
                fail('сцены «%s» нет в фильме; есть: %s' % (n, ', '.join(ids)))
        if ids.index(y) != ids.index(x) + 1:
            fail('сцены %s и %s не соседние (шов — соседи по порядку фильма); швы: %s'
                 % (x, y, ', '.join('%s:%s' % (p, q) for p, q in zip(ids, ids[1:]))))
        return 'seam', a.seam, None, None, 'seam-%s-%s' % (x, y), (x, y)
    if a.at:
        parts = a.at.split(':')
        if len(parts) not in (2, 3):
            fail('--at <реплика>:<доля>[:<смещение, с>], например --at 1:0.5')
        reps = {str(r['num']): r for r in meta['replies']}
        if parts[0] not in reps:
            fail('реплики «%s» нет в фильме; есть: %s' % (parts[0], ', '.join(reps)))
        share = _num(parts[1], 'доля')
        off = _num(parts[2], 'смещение') if len(parts) == 3 else 0.0
        r = reps[parts[0]]
        t = r['start'] + share * (r['end'] - r['start']) + off
        if t < -EPS or t > dur + EPS:
            fail('момент %s с вне фильма (длится 0…%s с)' % (_fmt(t), _fmt(dur)))
        return 'at', a.at, max(0.0, t - AT_HALF_SEC), min(dur, t + AT_HALF_SEC), 'at-%s-%s' % (parts[0], parts[1].replace('.', '_')), None
    parts = a.range.split(':')
    if len(parts) != 2:
        fail('--range <t0>:<t1> — секунды через двоеточие, например --range 2:5.5')
    t0, t1 = _num(parts[0], 't0'), _num(parts[1], 't1')
    if not 0 <= t0 < t1 <= dur + EPS:
        fail('отрезок %s…%s вне фильма: допустимо 0 ≤ t0 < t1 ≤ %s с' % (_fmt(t0), _fmt(t1), _fmt(dur)))
    return 'range', a.range, t0, t1, 'range-%s-%s' % (slug(t0), slug(t1)), None


def seam_span(meta, x, y):
    """Окно шва на странице пары: от конца последней реплики x до 0,5 с после первой реплики y; границу сцен
    окно всегда содержит с запасом в полсекунды в обе стороны."""
    sc = {s['id']: s for s in meta['scenes']}
    a, b = sc[x], sc[y]
    t0 = min(a['last'], a['end'] - SEAM_PAD_SEC)
    t1 = max(b['first'] + SEAM_PAD_SEC, b['start'] + SEAM_PAD_SEC)
    return max(a['start'], t0), min(meta['duration'], t1)


# ---------- сборка файлов ----------

def _font(size):
    from PIL import ImageFont
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def make_strip(paths, times, step, dest):
    from PIL import Image
    picks = list(range(0, len(paths), step))
    ims = [Image.open(paths[k]).convert('RGB') for k in picks]
    w, h = ims[0].size
    row = Image.new('RGB', (w * len(ims), h))
    for i, im in enumerate(ims):
        row.paste(im, (i * w, 0))
    row.save(dest)
    return row


def make_sheet(paths, times, dest):
    from PIL import Image, ImageDraw
    ims = [Image.open(p).convert('RGB') for p in paths]
    w, h = ims[0].size
    bar = 22
    cols = min(SHEET_COLS, len(ims))
    rows = (len(ims) + cols - 1) // cols
    sheet = Image.new('RGB', (cols * w, rows * (h + bar)), (24, 24, 24))
    dr = ImageDraw.Draw(sheet)
    font = _font(15)
    for i, (im, t) in enumerate(zip(ims, times)):
        x, y = (i % cols) * w, (i // cols) * (h + bar)
        sheet.paste(im, (x, y + bar))
        dr.text((x + 6, y + 3), '%s s' % _fmt(round(t, 3)), fill=(255, 255, 255), font=font)
    sheet.save(dest)


def make_pair(top, old_meta, new_png, dest):
    """top — картинка прежней полосы, прочитанная до записи новой (её папка могла быть переписана)."""
    from PIL import Image, ImageDraw
    low = Image.open(new_png).convert('RGB')
    w = max(top.width, low.width)
    bar = 22
    out = Image.new('RGB', (w, top.height + low.height + 2 * bar), (24, 24, 24))
    dr = ImageDraw.Draw(out)
    font = _font(15)
    dr.text((6, 3), 'before: %s' % old_meta.get('id', ''), fill=(255, 200, 120), font=font)
    out.paste(top, (0, bar))
    dr.text((6, bar + top.height + 3), 'after', fill=(140, 230, 160), font=font)
    out.paste(low, (0, 2 * bar + top.height))
    out.save(dest)


def make_clip(frames_dir, n, fps, dest, gif=False):
    import lipsync
    ff = lipsync.ffmpeg_exe()
    src = os.path.join(frames_dir, '%04d.png')
    if gif:
        cmd = [ff, '-v', 'error', '-y', '-framerate', str(fps), '-i', src, '-frames:v', str(n),
               '-vf', 'split[a][b];[a]palettegen[p];[b][p]paletteuse', '-loop', '0', dest]
    else:
        cmd = [ff, '-v', 'error', '-y', '-framerate', str(fps), '-i', src, '-frames:v', str(n),
               '-vf', 'scale=trunc(iw/2)*2:trunc(ih/2)*2', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '20',
               '-r', str(fps), '-movflags', '+faststart', dest]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if r.returncode != 0:
        fail('ffmpeg не собрал %s: %s' % (os.path.basename(dest), r.stderr.strip()[-300:]))


# ---------- команда ----------

def build_page(root, film, only=None):
    """Страница без рендера: build.py <фильм> [--only a,b] --page. Возвращает папку страницы."""
    cmd = [sys.executable, os.path.join(VIDEO, 'build.py'), film, '--page', '--project', str(root)]
    if only:
        cmd[3:3] = ['--only', only]
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    env.pop('MOTION_PROJECT', None)
    r = subprocess.run(cmd, env=env, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if r.returncode != 0:
        fail('страница не собралась (build.py, код %d): %s' % (r.returncode, (r.stdout + r.stderr).strip()[-500:]))
    return None


def main(argv):
    root, rest = project_root.split_argv(argv)
    ap = argparse.ArgumentParser(description='Полоса кадров, лист и короткое видео сцены, шва, момента, отрезка.')
    ap.add_argument('film', help='имя файла в films/ без .json')
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--scene', help='id сцены')
    g.add_argument('--seam', help='шов: две соседние сцены <a>:<b>')
    g.add_argument('--at', help='момент: <реплика>:<доля>[:<смещение, с>]')
    g.add_argument('--range', help='отрезок: <t0>:<t1> в секундах')
    ap.add_argument('--fps', type=float, default=10, help='кадров в секунду полосы (10)')
    ap.add_argument('--height', type=int, default=270, help='высота кадра полосы, px (270)')
    ap.add_argument('--video', action='store_true', help='положить clip.mp4')
    ap.add_argument('--gif', action='store_true', help='положить clip.gif')
    ap.add_argument('--pair', help='папка прежней полосы: положить pair.png (она над новой)')
    ap.add_argument('--name', help='имя папки полосы (иначе scene-<id>, seam-<a>-<b>, at-…, range-…)')
    ap.add_argument('--no-build', action='store_true', help='не собирать страницу: взять готовую из out/')
    a = ap.parse_args(rest)
    if a.fps <= 0 or a.height <= 0:
        fail('--fps и --height — положительные числа')
    if a.name is not None:
        strip_name(a.name)             # до страницы, сборки и замка: негодное имя ничего не запускает и не стирает
    root, out = out_root(root)
    if not (root / 'films' / (a.film + '.json')).exists():
        fail('нет фильма %s' % (root / 'films' / (a.film + '.json')))
    with open(root / 'films' / (a.film + '.json'), encoding='utf-8-sig') as fh:
        order = json.load(fh).get('scenes') or []
    old = old_strip = None
    if a.pair:
        old_dir = os.path.abspath(a.pair)
        if not os.path.exists(os.path.join(old_dir, 'strip.json')):
            fail('в %s нет strip.json: --pair берёт папку прежней полосы' % old_dir)
        with open(os.path.join(old_dir, 'strip.json'), encoding='utf-8') as fh:
            old = json.load(fh)
        if not os.path.exists(os.path.join(old_dir, 'strip.png')):
            fail('в %s нет strip.png: --pair берёт папку прежней полосы' % old_dir)
        from PIL import Image
        with Image.open(os.path.join(old_dir, 'strip.png')) as im:
            old_strip = im.convert('RGB')      # сейчас, целиком в память: папка прежней полосы может оказаться
                                               # папкой новой (то же имя) и будет стёрта перед записью
    if a.seam:                         # шов — страница пары сцен; соседство проверяем до сборки
        sp = a.seam.split(':')
        if len(sp) == 2 and all(n in order for n in sp) and order.index(sp[1]) != order.index(sp[0]) + 1:
            fail('сцены %s и %s не соседние (шов — соседи по порядку фильма); швы: %s'
                 % (sp[0], sp[1], ', '.join('%s:%s' % (p, q) for p, q in zip(order, order[1:]))))
    label = 'strip.py %s' % a.film
    with chrome_lock.held(label):
        if a.seam and len(a.seam.split(':')) == 2:
            pair = a.seam.split(':')
            page = out / (a.film + '--' + ','.join(pair))
            if not a.no_build:
                build_page(root, a.film, ','.join(pair))
        else:
            page = out / a.film
            if not a.no_build:
                build_page(root, a.film)
        meta = read_film(str(page)) if os.path.exists(page / 'film.json') else fail('нет страницы %s' % page)
        kind, sid, t0, t1, name, pair = resolve_span(meta, order, a)
        if kind == 'seam':
            t0, t1 = seam_span(meta, *pair)
        name = strip_name(a.name or name)
        scale = a.height / meta['canvas']['h']
        paths = frames(root, a.film, t0, t1, a.fps, scale, page=str(page))
        times = frame_times(t0, t1, a.fps)
        if old is not None:
            same = (abs(old['t0'] - t0) < 1e-3 and abs(old['t1'] - t1) < 1e-3 and old['fps'] == a.fps
                    and abs(old['scale'] - scale) < 1e-9)
            if not same:
                fail('прежняя полоса %s…%s с, %s кадр/с, масштаб %s; новая %s…%s с, %s кадр/с, масштаб %s — '
                     'пара строится по тем же таймкодам: снимите новую с теми же аргументами'
                     % (_fmt(old['t0']), _fmt(old['t1']), old['fps'], round(old['scale'], 4),
                        _fmt(t0), _fmt(t1), a.fps, round(scale, 4)))
        strips = out / a.film / 'strips'
        dest = strips / name
        if dest.resolve().parent != strips.resolve():
            fail('папка полосы %s выходит за %s — имя «%s» не годится' % (dest, strips, name))
        shutil.rmtree(dest, ignore_errors=True)
        (dest / 'frames').mkdir(parents=True)
        rels = []
        for k, (p, t) in enumerate(zip(paths, times)):
            rel = 'frames/%04d.png' % (k + 1)
            shutil.copyfile(p, dest / rel)
            rels.append({'t': round(t, 4), 'file': rel})
        from PIL import Image
        w = Image.open(paths[0]).size[0]
        step = max(1, math.ceil(len(paths) * w / STRIP_MAX_W))
        make_strip(paths, times, step, str(dest / 'strip.png'))
        make_sheet(paths, times, str(dest / 'sheet.png'))
        if a.video:
            make_clip(str(dest / 'frames'), len(paths), a.fps, str(dest / 'clip.mp4'))
        if a.gif:
            make_clip(str(dest / 'frames'), len(paths), a.fps, str(dest / 'clip.gif'), gif=True)
        if old is not None:
            make_pair(old_strip, old, str(dest / 'strip.png'), str(dest / 'pair.png'))
        info = {'film': a.film, 'kind': kind, 'id': sid, 't0': round(t0, 4), 't1': round(t1, 4), 'fps': a.fps,
                'scale': scale, 'frames': rels, 'page_sha256': page_sha(page),
                'strip_step': step, 'page': str(page)}
        with open(dest / 'strip.json', 'w', encoding='utf-8') as fh:
            json.dump(info, fh, ensure_ascii=False, indent=1)
    print('полоса: %s · %d кадров, %s…%s с, %s кадр/с' % (dest, len(rels), _fmt(t0), _fmt(t1), _fmt(a.fps)))
    return 0


if __name__ == '__main__':
    sys.exit(deps.run(main, sys.argv[1:]))
