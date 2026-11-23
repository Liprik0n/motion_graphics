# -*- coding: utf-8 -*-
"""Проверка собранного ролика — ядро условий, общее для любого фильма.

Читает только результат с диска: <out>/<фильм>/film.json (времена реплик и сцен), probe.json (промер DOM
в моменты t), index.html (палитра), video.mp4 (промер ffmpeg), mp3 реплик (промер ffmpeg), раскадровки
и разметку сцен, конфиги проекта (project.json, tokens.json, films/<фильм>.json, rows.json) и текст-
источник сцен (project.json paths.text). Сборку не импортирует и ничего за неё не пересчитывает её
способом: длительности — промером звука, геометрия — промером DOM, ожидания — числа конфигов.

    python engine/video/check.py demo --page          страница без рендера (build.py demo --page): видео не смотрим
    python engine/video/check.py demo                 ролик целиком: + video.mp4 (V1 красная, если ролик снят не с
                                                      нынешней страницы: отметка кадров, engine/video/stamp.py)
    python engine/video/check.py film --only a,b --page   пара сцен — шов без рендера
    python engine/video/check.py demo --red [подстрока]       быстрые порчи (probe.json и копии данных), секунды
    python engine/video/check.py demo --red-slow [подстрока]  медленные порчи: копия проекта, пересборка страницы
    python engine/video/check.py demo --samples [подстрока]   законные варианты на грани порога — молча
    python engine/video/check.py <фильм> --red-init           завести порчи своего фильма: checks/red_<фильм>.py с рабочим
                                                              минимумом (порчи глаза V36, V37 — checks/red_film.py)
    python engine/video/check.py demo --page --style glass    проход фильма в стиле (build.py demo --page --style glass
                                                              → <out>/demo/glass/; то же, что check.py demo/glass --page);
                                                              с --red / --samples — порчи «стиль на фильме роняет
                                                              контраст подписи» (checks/red_styles.py FILM_RED)
    --project DIR   корень проекта: --project → MOTION_PROJECT → <шаблон>/project (engine/project_root.py)
    --out-dir DIR   собранная страница не в <out>/<фильм>

Код выхода 0 — всё зелёное, 1 — хоть один провал (или порча не покраснела своей строкой).
Условия V1–V37 и их карта на условия прошлого ролика и классы дефектов — engine/video/CHECKS.md.
V36 и V37 (живость по зонам, читаемость по пикселям) при первом запуске на странице снимают её кадры (Chrome под
замком, engine/tools/strip.py) в <out>/<фильм>/strips/_cache/; дальше берут их оттуда, пока страница та же
(отпечаток stamp.page_print: index.html, film.json и каждый файл assets/).
"""
import copy
import json
import math
import os
import re
import subprocess
import sys

sys.dont_write_bytecode = True
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

HERE = os.path.dirname(os.path.abspath(__file__))           # <шаблон>/engine/video
ENGINE = os.path.dirname(HERE)                               # <шаблон>/engine
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import stamp      # noqa: E402  отпечаток страницы и отметка кадров: одно правило «та же ли это страница» со сборкой

# ---------------------------------------------------------------- пороги проверки (замер прошлого ролика, не конфиг проекта)
EDGE_TOL = 0.5            # px: допуск округления прямоугольников
VISIBLE = 0.02            # непрозрачность, с которой элемент считается видимым
FRAME_TOL = 0.5           # px: каркас в последнем кадре N и первом N+1 стоит там же
TEXT_SEEN = 0.3           # надпись с такой непрозрачностью уже читается (обычный наплыв — ниже)
TEXT_SHRINK = 1.0         # px, на которые сжимается рамка строки — касание строк не нахлёст
TEXT_AREA_MIN = 4.0       # px² пересечения сжатых строк, с которых это нахлёст
FULL = 0.99               # «на 1,0»
SEAM_TEXT_SEEN = 0.25     # на шве надпись читается уже с 0,25 (уходящая колонка, мост)
SEAM_TEXT_UNDER = 0.05    # на шве и строка-тень под ней (тень 0,2 входит) — тоже надпись
SEAM_TAIL = 0.5           # с: пауза стыка — от конца реплик N до 0,5 с после первой реплики N+1
SAT_TOL = 1.0             # px: центр спутника в системе своей надписи стоит на месте
SAT_SEEN = 0.05           # спутник и надпись видны оба — с этой непрозрачности
ICON_ROW_MAX_H = 0.8      # ″: иконка строки не выше; крупнее — эмблема, не спутник
ICON_ROW_GAP = 0.5        # ″: от иконки до надписи на её строке
MOVE_TOL = 1.5            # px: якорь move в конце против цели
LEVEL_TOL = 0.03          # непрозрачность в конце действия против ожидания
TILT_TOL = 1.0            # °: наклон после посадки / в середине полёта
TEXT_FIT_TOL = 0.05       # move to_text: ширина приехавшего текста против подстроки
SCALE_TOL = 0.004         # масштаб пульса и дыхания против контракта
HANG_MAX = 1.0            # с: предмет без опоры дольше этого — провал (класс дефектов 2)
SUPPORT_PAD = 0.10        # ″: предмет касается опоры с этим зазором
TWIN_TOL = 1.0            # px: копия и оригинал видны вместе только точно друг на друге
TWIN_SEEN = 0.05          # двойник «виден» с этой непрозрачности
ORDER_TOL = 0.05          # с: пункты одного бита с одним временем — порядок не нарушен
VANISH_SEEN = 0.5         # VANISH: элемент был виден на столько и пропал за кадр
COVER_SHARE = 0.5         # VANISH: подмена закрывает не меньше этой доли пропавшего
MOVING_PX = 2.0           # VANISH: сдвиг за кадр, при котором элемент «под движением»
FLICKER_SEC = 1.0         # FLICKER: виден → не виден → виден быстрее этого
PX_PER_IN_SUPPORTED = 96  # движок верстает страницу в px при 96 px на дюйм (engine/video/config.py)
# Обязательные ключи конфигов, которые читает проверка (запасных чисел в коде нет)
REQUIRED_KEYS = (
    ('project', ('fps', 'canvas.w', 'canvas.h', 'canvas.px_per_in', 'tail_sec', 'paths.out')),
    ('tokens', ('density.max_opacity_step', 'density.words_per_chunk', 'motion.level_shade', 'motion.level_mid',
                'motion.level_step', 'motion.level_gap', 'motion.ink_dur', 'motion.breathe.scale',
                'motion.breathe.period', 'motion.breathe.edge', 'motion.title_in', 'motion.chapter_dur',
                'motion.emph_dur', 'motion.move_dur', 'motion.beat_tail', 'motion.pulse_amp', 'motion.ring_amp',
                'motion.flash_dur', 'motion.anim_dur')),
)

_mp3_cache = {}


# ---------------------------------------------------------------- чтение
def load_json(p):
    with open(p, encoding='utf-8') as fh:
        return json.load(fh)




def ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def _null_decode(args):
    r = subprocess.run([ffmpeg(), '-hide_banner', '-nostats', '-progress', 'pipe:2'] + args + ['-f', 'null', '-'],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return r.stderr


def mp3_seconds(path):
    if path not in _mp3_cache:
        if not os.path.exists(path):
            _mp3_cache[path] = None
        else:
            m = re.findall(r'out_time_us=(\d+)', _null_decode(['-i', path]))
            _mp3_cache[path] = int(m[-1]) / 1e6 if m else None
    return _mp3_cache[path]


def mp4_streams(path, fps):
    """(секунды видео по числу кадров, секунды звука по декодированию); кэш по пути, размеру и времени файла."""
    st = os.stat(path)
    key = (path, st.st_size, st.st_mtime, fps)
    if key not in _mp3_cache:
        v = _null_decode(['-i', path, '-map', '0:v:0'])
        frames = re.findall(r'^frame=(\d+)', v, re.M)
        a = _null_decode(['-i', path, '-map', '0:a:0'])
        au = re.findall(r'out_time_us=(\d+)', a)
        _mp3_cache[key] = (int(frames[-1]) / fps if frames else None), (int(au[-1]) / 1e6 if au else None)
    return _mp3_cache[key]


def norm(s):
    return re.sub(r'\s+', ' ', s.replace('\xa0', ' ').replace('­', '')).strip()


def area(a, b):
    w = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
    h = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
    return max(0.0, w) * max(0.0, h)


def _shrunk(r):
    return [r[0] + TEXT_SHRINK, r[1] + TEXT_SHRINK, r[2] - 2 * TEXT_SHRINK, r[3] - 2 * TEXT_SHRINK]


def _outside_own(g, r):
    return (g[0] < r[0] - EDGE_TOL or g[1] < r[1] - EDGE_TOL
            or g[0] + g[2] > r[0] + r[2] + EDGE_TOL or g[1] + g[3] > r[1] + r[3] + EDGE_TOL)


def hex_rgb(h):
    h = h.lstrip('#')
    return 'rgb(%d, %d, %d)' % (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


class Ctx(dict):
    """Всё, что проверка прочла с диска. Порчи правят копию в памяти (deepcopy) или подставляют пути."""


def make_ctx(root, out_dir, page_only=False):
    root = os.path.abspath(root)
    pj = load_json(os.path.join(root, 'project.json'))
    tk = load_json(os.path.join(root, 'tokens.json'))
    film = load_json(os.path.join(out_dir, 'film.json'))
    probe = load_json(os.path.join(out_dir, 'probe.json'))
    films_dir = os.path.join(root, pj.get('paths', {}).get('films', 'films'))
    fdef = load_json(os.path.join(films_dir, film['film'] + '.json'))
    sd = film.get('scenes_dir') or pj.get('paths', {}).get('scenes', 'scenes')
    ctx = Ctx(root=root, project=pj, tokens=tk, film=film, probe=probe, fdef=fdef, out_dir=out_dir,
              scenes_dir=os.path.normpath(os.path.join(root, sd)), page=os.path.join(out_dir, 'index.html'),
              mp4=os.path.join(out_dir, 'video.mp4'), page_only=page_only)
    sp = os.path.join(out_dir, 'style_probe.json')
    ctx['style_probe'] = load_json(sp) if os.path.exists(sp) else None
    pp = os.path.join(out_dir, 'plugin_probe.json')
    ctx['plugin_probe'] = load_json(pp) if os.path.exists(pp) else None
    for fname, keys in REQUIRED_KEYS:          # нет ключа — отказ до проверки, с именем поля
        for k in keys:
            cfg_need(ctx, fname, k)
    PX(ctx)                                    # px_per_in ≠ 96 — отказ с объяснением
    return ctx


def fresh(base):
    """Копия контекста для одной порчи: данные — deepcopy, кэши — заново."""
    keep = {k: v for k, v in base.items() if not k.startswith('_')}
    return Ctx(copy.deepcopy(keep))


# ---------------------------------------------------------------- константы из конфигов
def cfg_need(ctx, fname, dotted):
    """Обязательное значение конфига (fname: 'project' | 'tokens') по пути через точку. Запасного числа нет:
    нет ключа — отказ с именем поля, а не проверка против числа, которого никто не выбирал."""
    cur = ctx[fname]
    for part in dotted.split('.'):
        if not isinstance(cur, dict) or cur.get(part) is None:
            raise SystemExit('%s.json: нет обязательного поля %s' % (fname, dotted))
        cur = cur[part]
    return cur


def fps(ctx):
    return int(cfg_need(ctx, 'project', 'fps'))


def FR(ctx):
    return 1.0 / fps(ctx)


def PX(ctx):
    v = float(cfg_need(ctx, 'project', 'canvas.px_per_in'))
    if v != PX_PER_IN_SUPPORTED:
        raise SystemExit('project.json canvas.px_per_in = %s: движок поддерживает только %d — размеры страницы '
                         '(stage.css, разметка сцен) записаны в px при %d px на дюйм' % (v, PX_PER_IN_SUPPORTED, PX_PER_IN_SUPPORTED))
    return v


def canvas(ctx):
    return float(cfg_need(ctx, 'project', 'canvas.w')), float(cfg_need(ctx, 'project', 'canvas.h'))


def mo(ctx, key):
    return cfg_need(ctx, 'tokens', 'motion.' + key)


def anim_dur(ctx, anim):
    return float(mo(ctx, 'anim_dur.' + anim))


def frame_of(ctx, t):
    """Правило округления времени в кадр — одно с промером и сборкой: floor(t·fps + 0,5 + 0,005).
    Python round() — банковское и с JS Math.floor(x + 0,5) расходится на половинках."""
    return math.floor(t * fps(ctx) + 0.5 + 5e-3)


def q(ctx, t):
    return frame_of(ctx, t) / fps(ctx)


def level_cross_dur(ctx):
    """Смена через полосу тени (тень ↔ чернила): две ступени level_step, вторая — через level_gap."""
    return float(mo(ctx, 'level_gap')) + float(mo(ctx, 'level_step'))


def level_default_dur(ctx, sb, tg, t0, value):
    prev, pt = 1, -1.0
    for b in sb['beats']:
        if b['action'] not in ('show', 'level') or tg not in b.get('targets', []):
            continue
        t = beat_t(ctx, b, b['targets'].index(tg))
        if t is None or t >= t0 - 1e-6 or t < pt:
            continue
        pt, prev = t, (b.get('level', 1) if b['action'] == 'show' else b['value'])
    lo, hi = min(prev, value), max(prev, value)
    if lo <= float(mo(ctx, 'level_shade')) and hi > float(mo(ctx, 'level_mid')):
        return level_cross_dur(ctx)
    return float(mo(ctx, 'level_step'))


def chapter_index(ctx, cid):
    for k, c in enumerate(ctx['project'].get('chapters', [])):
        if c['id'] == cid:
            return k
    return -1


# ---------------------------------------------------------------- промер
def sample_at(ctx, t):
    """Замер кадра, в который попадает t; None — такого кадра в промере нет."""
    idx = ctx.get('_by_t')
    if idx is None or ctx.get('_by_t_n') != len(ctx['probe']['samples']):
        idx = {round(s['t'], 3): s for s in ctx['probe']['samples']}
        ctx['_by_t'], ctx['_by_t_n'] = idx, len(ctx['probe']['samples'])
    # то же правило, что у промера (probe_dom.mjs q): кадры фильма 0…N−1, момент не позже последнего кадра —
    # у куска без хвоста (tail_sec 0) конец последней сцены = длина фильма, это последний кадр, а не «нет промера»
    last = (frame_of(ctx, float(ctx['film']['duration'])) - 1) / fps(ctx)
    return idx.get(round(max(0.0, min(q(ctx, t), last)), 3))


def item_of(sample, ident):
    for it in sample['items']:
        if it['id'] == ident:
            return it
    return None


def opacity_of(sample, ident):
    it = item_of(sample, ident)
    return it['opacity'] if it else 0.0


def storyboards(ctx, raw=False):
    """[(сцена film.json, раскадровка)]. Ключ фильма "hide" (вариант ролика) снимает биты со скрытых элементов,
    как сборка: проверка ждёт исполнения только тех битов, что остались (raw=True — раскадровки как на диске)."""
    if '_sbs_raw' not in ctx:
        ctx['_sbs_raw'] = [(s, load_json(os.path.join(ctx['scenes_dir'], s['id'], 'storyboard.json')))
                           for s in ctx['film']['scenes']]
    if raw:
        return ctx['_sbs_raw']
    if '_sbs' not in ctx:
        hide = ctx['fdef'].get('hide') or []
        out = []
        for s, sb in ctx['_sbs_raw']:
            if hide:
                gone = {h.rpartition(':')[2] for h in hide if h.rpartition(':')[0] in ('', s['id'])}
                sb = copy.deepcopy(sb)
                for b in sb['beats']:
                    b['targets'] = [t for t in b['targets'] if t.split('.')[0] not in gone]
                sb['beats'] = [b for b in sb['beats'] if b['targets']]
            out.append((s, sb))
        ctx['_sbs'] = out
    return ctx['_sbs']


def reply_of(ctx, n):
    for r in ctx['film']['replies']:
        if r['n'] == n:
            return r
    return None


def beat_t(ctx, b, i=0):
    r = reply_of(ctx, b['reply'])
    if r is None:
        return None          # реплики нет в этой сборке — мерить нечем (провал C2, если она обязана быть)
    return r['start'] + b['at'] * (r['end'] - r['start']) + b.get('offset', 0.0) + i * b.get('stagger', 0.0)


def target_events(ctx):
    """{(сцена, цель): [время событий]} — не мерить там, где событие перебито следующим."""
    if '_ev' not in ctx:
        ev = {}
        for s, sb in storyboards(ctx):
            for b in sb['beats']:
                for i, tg in enumerate(b.get('targets', [])):
                    t = beat_t(ctx, b, i)
                    if t is not None:
                        ev.setdefault((s['id'], tg), []).append(t)
        ctx['_ev'] = ev
    return ctx['_ev']


def _busy(ctx, key, t0, t1):
    return any(t0 + 1e-6 < x <= t1 for x in target_events(ctx).get(key, []))


_EL_RE = re.compile(r'<\w+\b([^>]*\bclass="[^"]*\bel\b[^"]*"[^>]*)>')


def markup_els(ctx, s, sb):
    """[(id, атрибуты, есть ли надпись .t)] верхних узлов разметки сцены — своим разбором файла."""
    if not sb.get('markup'):
        return []
    with open(os.path.join(ctx['scenes_dir'], s['id'], sb['markup']), encoding='utf-8') as fh:
        txt = fh.read()
    ms = list(_EL_RE.finditer(txt))
    out = []
    for k, m in enumerate(ms):
        i = re.search(r'\bid="([a-z0-9-]+)"', m.group(1))
        body = txt[m.end():ms[k + 1].start() if k + 1 < len(ms) else len(txt)]
        if i:
            out.append((i.group(1), m.group(1), bool(re.search(r'class="[^"]*\bt\b', body))))
    return out


def markup_boxes(ctx, s, sb):
    """[(id, (left, top, width, height) px)] верхних узлов разметки с надписью .t."""
    out = []
    for mid, attrs, has_t in markup_els(ctx, s, sb):
        st = re.search(r'\bstyle="([^"]*)"', attrs)
        vals = dict(re.findall(r'(left|top|width|height)\s*:\s*([\d.]+)px', st.group(1))) if st else {}
        if has_t and len(vals) == 4:
            out.append((mid, tuple(float(vals[k]) for k in ('left', 'top', 'width', 'height'))))
    return out


def declared_layers(ctx):
    """{dom-id: 'under'|'over'|None} по раскадровкам и разметке с диска."""
    if '_decl' not in ctx:
        out = {}
        for s, sb in storyboards(ctx):
            for e in sb.get('elements', []):
                out['%s--%s' % (s['id'], e['id'])] = e.get('layer')
            for mid, attrs, _ in markup_els(ctx, s, sb):
                lay = re.search(r'\bdata-layer="([^"]*)"', attrs)
                out['%s--%s' % (s['id'], mid)] = lay.group(1) if lay else None
        ctx['_decl'] = out
    return ctx['_decl']


def seam_windows(ctx):
    """[(начало, конец, «a → b»)] пауз стыков: от конца реплик N до 0,5 с после первой реплики N+1."""
    if '_seams' not in ctx:
        sc = ctx['film']['scenes']
        ctx['_seams'] = [(q(ctx, a['last']), b['first'] + SEAM_TAIL + 1e-6, '%s → %s' % (a['id'], b['id']))
                         for a, b in zip(sc, sc[1:])]
    return ctx['_seams']


def seam_of(ctx, t):
    for a, b, name in seam_windows(ctx):
        if a - 1e-6 <= t <= b:
            return name
    return None


def work_zone(ctx):
    z, k = ctx['project'].get('work_zone', {}), PX(ctx)
    return (z['x0'] * k, z['y0'] * k, (z['x1'] - z['x0']) * k, (z['y1'] - z['y0']) * k)


def manifest_rows(ctx):
    """Строки звука фильма: replies прямо в фильме или манифест озвучки (путь от корня проекта)."""
    fd = ctx['fdef']
    if fd.get('replies') is not None:
        return fd['replies']
    if fd.get('manifest'):
        p = os.path.join(ctx['root'], fd['manifest'])
        if os.path.exists(p):
            return load_json(p)
    return None


# ================================================================= условия
def v1_duration(ctx):
    """V1: видео = звук ±1 кадр; длина = конец последней реплики + хвост (или конец последнего
    бита + beat_tail); промер и проверка округляют время в кадр одним правилом; страница без ошибок. Без --page —
    ролик снят с нынешней страницы: отметка его кадров не устарела (stamp.stale пуст)."""
    f, film, F = [], ctx['film'], FR(ctx)
    tail = ctx['fdef']['tail_sec'] if 'tail_sec' in ctx['fdef'] else cfg_need(ctx, 'project', 'tail_sec')
    if ctx.get('page_only'):
        vid = film['duration']
    else:
        if not os.path.exists(ctx['mp4']):
            return ['V1 длительность: нет %s — собери ролик или проверяй с --page' % ctx['mp4']]
        # ролик снят с кадров frames/, а страницу после рендера могли пересобрать другой: правка сцены → --page →
        # зелёная проверка страницы → в сдаче прежняя картинка. Отметку кадров пишет каждый полный рендер (stamp.py)
        why = stamp.stale(ctx['out_dir'])
        if why:
            f.append('V1 ролик: %s снят не с нынешней страницы — %s. Проверка мерит страницу, а в сдачу уйдёт прежняя '
                     'картинка; перерендерь: build.py %s' % (os.path.basename(ctx['mp4']), '; '.join(why),
                                                            re.split(r'[\\/]', str(film['film']))[0]))
        vid, aud = mp4_streams(ctx['mp4'], fps(ctx))
        if vid is None or aud is None:
            return ['V1 длительность: в %s нет видео- или звуковой дорожки' % ctx['mp4']]
        if abs(vid - aud) > F + 1e-6:
            f.append('V1 длительность: видео %.3f с ≠ звук %.3f с (допуск 1 кадр)' % (vid, aud))
    ends = []
    for r in film['replies']:
        sec = mp3_seconds(os.path.join(ctx['root'], r['file'])) if (r.get('file') and not film.get('estimate')) else None
        ends.append(r['start'] + (sec if sec is not None else r['end'] - r['start']))
    if not ends:
        return f + ['V1 длительность: в фильме нет реплик']
    expected = max(ends) + tail
    lb = last_beat_end(ctx)
    bt = float(mo(ctx, 'beat_tail'))
    if lb is not None and lb + bt > expected:
        expected = math.ceil((lb + bt) * fps(ctx) - 1e-6) / fps(ctx)
        if abs(vid - expected) > F + 1e-6:
            f.append('V1 длительность: видео %.3f с, а последний бит раскадровки кончается в %.3f с + хвост %.1f с'
                     % (vid, lb, bt))
    elif abs(vid - expected) > F + 1e-6:
        f.append('V1 длительность: видео %.3f с, а последняя реплика кончается в %.3f с + хвост %.1f с'
                 % (vid, max(ends), tail))
    rr = ctx['probe'].get('round_rule')
    if not rr:
        f.append('V1 время: в промере нет таблицы правила округления (round_rule) — пересобери промер')
    else:
        for t, got in rr:
            if abs(got - q(ctx, t)) > 1e-6:
                f.append('V1 время: промер и проверка округляют время в кадр по-разному (t=%.4f: промер %.4f, проверка %.4f)'
                         % (t, got, q(ctx, t)))
                break
    for e in ctx['probe'].get('errors') or []:
        f.append('V1 страница: ошибка в промере страницы: %s' % str(e)[:200])
    return f


def last_beat_end(ctx):
    """Конец последнего бита содержания: время бита + stagger последней цели + длительность действия
    (числа tokens.json motion). None — битов нет."""
    ends = []
    for s, sb in storyboards(ctx):
        for k, d in (('title_at', mo(ctx, 'title_in')), ('chapter_at', mo(ctx, 'chapter_dur')),
                     ('num_at', mo(ctx, 'title_in'))):
            if sb.get(k) and beat_t(ctx, sb[k]) is not None:
                ends.append(beat_t(ctx, sb[k]) + d)
        for b in sb['beats']:
            act = b['action']
            t = beat_t(ctx, b, len(b.get('targets', [None])) - 1)
            if t is None:
                continue
            if act == 'show':
                d = b['dur'] if b.get('dur') is not None else anim_dur(ctx, b.get('anim', 'rise'))
            elif act == 'hide':
                d = b['dur'] if b.get('dur') is not None else anim_dur(ctx, b.get('anim', 'fade'))
            elif act == 'level':
                d = b.get('dur', mo(ctx, 'ink_dur'))
            elif act == 'emph' and b.get('style') == 'breathe':
                continue
            elif act == 'emph':
                d = b.get('dur', mo(ctx, 'flash_dur') if b.get('style') == 'flash' else mo(ctx, 'emph_dur'))
            elif act == 'move':
                d = b.get('dur', mo(ctx, 'move_dur'))
            else:
                continue
            ends.append(t + d)
    return max(ends) if ends else None


def v2_replies(ctx):
    """V2 (C2): каждая реплика звука фильма в ролике, длина = mp3 ±1 кадр, голос тот же, без наложений,
    внутри ролика, и есть кадр промера, где она звучит. Немая строка (silent: опора времени для действия без
    речи): звука нет, длина = ms ±1 кадр, в её кадрах никто не говорит — полоски голоса стоят, подпись не горит."""
    f, film, probe, F = [], ctx['film'], ctx['probe'], FR(ctx)
    scenes = {s['id'] for s in film['scenes']}
    rows = manifest_rows(ctx)
    in_film = {r['n']: r for r in film['replies']}
    if rows is None and not film.get('estimate'):
        f.append('V2 реплики: у фильма %s нет ни replies, ни манифеста звука' % film['film'])
    want = {r['n']: r for r in (rows or []) if r.get('scene') in scenes}
    for n in sorted(set(want) - set(in_film)):
        f.append('V2 реплика №%d из звука фильма не попала в ролик' % n)
    if rows is not None:
        for n in sorted(set(in_film) - set(want)):
            f.append('V2 реплика №%d есть в ролике, но нет в звуке фильма' % n)
    for n in sorted(set(want) & set(in_film)):
        if want[n].get('voice') and want[n]['voice'] != in_film[n].get('voice'):
            f.append('V2 реплика №%d: в ролике голос %s, а в звуке фильма %s' % (n, in_film[n].get('voice'), want[n]['voice']))
    reps = sorted(film['replies'], key=lambda r: r['start'])
    for a, b in zip(reps, reps[1:]):
        if b['start'] < a['end'] - 1e-6:
            f.append('V2 реплики №%d и №%d накладываются' % (a['n'], b['n']))
    for r in reps:
        if r['start'] < 0 or r['end'] > film['duration'] + 1e-6:
            f.append('V2 реплика №%d за пределами ролика' % r['n'])
        if r.get('file') and not film.get('estimate'):
            sec = mp3_seconds(os.path.join(ctx['root'], r['file']))
            if sec is None or abs((r['end'] - r['start']) - sec) > F + 1e-6:
                f.append('V2 реплика №%d: в ролике %.3f с, а mp3 %s с'
                         % (r['n'], r['end'] - r['start'], 'не читается' if sec is None else '%.3f' % sec))
        if not any(r['start'] <= s['t'] < r['end'] and s.get('reply') == r['n'] for s in probe['samples']):
            f.append('V2 реплика №%d: нет ни одного кадра, где она звучит' % r['n'])
    f += silent_rows(ctx, want, in_film)
    return f


VOICE_REST_TOL = 0.05     # px: высота полоски голоса в покое против voice_bars.min


def _rgb_css(hex_):
    h = hex_.lstrip('#')
    return 'rgb(%d, %d, %d)' % (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def silent_rows(ctx, want, in_film):
    """Немые строки фильма (silent: true): в сборке помечены, файла звука нет, длина = ms ±1 кадр; в кадрах строки
    полоски каждого голоса стоят на voice_bars.min, подпись — цветом покоя voice_bars.mute (если полоски в кадре)."""
    f, F = [], FR(ctx)
    for n in sorted(set(want) & set(in_film)):
        src, r = want[n], in_film[n]
        if bool(src.get('silent')) != bool(r.get('silent')):
            f.append('V2 немая строка №%d: в звуке фильма silent=%s, а в сборке %s — пересобери страницу'
                     % (n, bool(src.get('silent')), bool(r.get('silent'))))
            continue
        if not r.get('silent'):
            continue
        if r.get('file'):
            f.append('V2 немая строка №%d: у неё файл звука %s — немая строка молчит' % (n, r['file']))
        if src.get('ms') is None or abs((r['end'] - r['start']) - float(src['ms']) / 1000.0) > F + 1e-6:
            f.append('V2 немая строка №%d: в ролике %.3f с, а ms строки — %s' % (n, r['end'] - r['start'], src.get('ms')))
        vb = ctx['project'].get('voice_bars') or {}
        if not ctx['film'].get('voice_bars'):
            continue
        rest = float(vb['min']) * float(cfg_need(ctx, 'project', 'canvas.px_per_in'))
        mute = _rgb_css(ctx['tokens']['palette'][vb['mute']])
        for s in ctx['probe']['samples']:
            if s.get('reply') != n or not (r['start'] <= s['t'] < r['end']):
                continue
            loud = [v for v, rec in sorted((s.get('voice') or {}).items())
                    if max(rec.get('bars') or [0]) > rest + VOICE_REST_TOL or rec.get('name') != mute]
            if loud:
                f.append('V2 немая строка №%d: в t=%.2f с голос %s «говорит» (полоски или подпись не в покое), а строка молчит'
                         % (n, s['t'], ', '.join(loud)))
                break
    return f


def v3_canvas(ctx):
    """V3 (C3): ни один видимый элемент не выходит за полотно. В сцене с камерой (plugins.act, метки «cam»; элемент
    внутри обёртки камеры — item cam) мир больше кадра: целиком в кадре обязана быть каждая видимая строка надписи
    при любом положении камеры."""
    f, seen = [], set()
    W, H = canvas(ctx)
    for s in ctx['probe']['samples']:
        for it in s['items']:
            if it.get('cam'):
                for g in it.get('segs') or []:
                    if g[4] > VISIBLE and (g[0] < -EDGE_TOL or g[1] < -EDGE_TOL or g[0] + g[2] > W + EDGE_TOL
                                           or g[1] + g[3] > H + EDGE_TOL) and it['id'] not in seen:
                        seen.add(it['id'])
                        f.append('V3 полотно: #%s в t=%.2f с: строка надписи %s выходит за %d × %d (камера сцены)'
                                 % (it['id'], s['t'], g[:4], W, H))
                continue
            r = it['rect']
            out = r[0] < -EDGE_TOL or r[1] < -EDGE_TOL or r[0] + r[2] > W + EDGE_TOL or r[1] + r[3] > H + EDGE_TOL
            if it['opacity'] > VISIBLE and out and it['id'] not in seen:
                seen.add(it['id'])
                f.append('V3 полотно: #%s в t=%.2f с: %s выходит за %d × %d' % (it['id'], s['t'], r, W, H))
    return f


def source_texts(ctx):
    """{сцена: нормализованный текст-источник} из project.json paths.text (<сцена>.txt); None — источника нет."""
    if 'source' in ctx:
        return ctx['source']
    d = os.path.join(ctx['root'], ctx['project'].get('paths', {}).get('text', 'text'))
    if not os.path.isdir(d):
        return None
    out = {}
    for s in ctx['film']['scenes']:
        p = os.path.join(d, s['id'] + '.txt')
        if os.path.exists(p):
            with open(p, encoding='utf-8') as fh:
                out[s['id']] = norm(fh.read())
    return out


def config_texts(ctx):
    """Надписи каркаса, которые задаёт сам проект: футер, подписи голоса, номера сцен."""
    pj = ctx['project']
    out = {norm(pj.get('footer', ''))}
    out |= {norm(v.get('label', '')) for v in (pj.get('voice_bars') or {}).get('voices', [])}
    out |= {'%02d' % s['number'] for s in ctx['film']['scenes'] if s.get('number') is not None}
    return {x for x in out if x}


def _in_text(t, src):
    i = src.find(t)
    while i >= 0:
        a, b = src[i - 1:i], src[i + len(t):i + len(t) + 1]
        if not (a.isalnum() or b.isalnum()):
            return True
        i = src.find(t, i + 1)
    return False


def v4_text(ctx):
    """V4 (C5): каждая надпись на экране дословно есть в тексте-источнике своей сцены (paths.text/<сцена>.txt).
    Источника нет вовсе — условие не проверено (строка SKIP)."""
    src = source_texts(ctx)
    if src is None:
        return None
    f, seen = [], set()
    allowed = config_texts(ctx)
    for s in ctx['probe']['samples']:
        for it in s['items']:
            if it['opacity'] <= VISIBLE:
                continue
            sc = it['scene'] or s['scene']
            for t in it['texts']:
                t = norm(t)
                if not t or t in allowed or (t, sc) in seen:
                    continue
                if sc not in src:
                    seen.add((t, sc))
                    f.append('V4 текст: у сцены %s нет источника %s.txt' % (sc, sc))
                    continue
                if not _in_text(t, src[sc]):
                    seen.add((t, sc))
                    f.append('V4 текст: «%s» (#%s) нет в источнике сцены %s' % (t, it['id'], sc))
    return f


def v5_seams(ctx):
    """V5 (C6): контракт стыка (end_state N = start_state N+1, состояния в сборке не устарели);
    в последнем кадре N и первом N+1 каркас стоит на месте ±0,5 px и не пропадает."""
    f = []
    film, probe = ctx['film'], ctx['probe']
    sc = film['scenes']
    for a, b in zip(sc, sc[1:]):
        if a.get('end_state') != b.get('start_state'):
            f.append('V5 стык %s → %s: конец %s ≠ начало %s' % (a['id'], b['id'], a.get('end_state'), b.get('start_state')))
    for s, sb in storyboards(ctx):
        if sb.get('start_state') != s.get('start_state') or sb.get('end_state') != s.get('end_state'):
            f.append('V5 раскадровка %s: состояния в сборке устарели — пересобери ролик' % s['id'])
    by_t = {round(x['t'], 4): x for x in probe['samples']}
    for seam in probe.get('seams', []):
        name = '%s → %s' % (seam['from'], seam['to'])
        a, b = by_t.get(round(seam['last'], 4)), by_t.get(round(seam['first'], 4))
        if a is None or b is None:
            f.append('V5 стык %s: в промере нет последнего или первого кадра' % name)
            continue
        if abs((seam['first'] - seam['last']) - FR(ctx)) > 1e-3:
            f.append('V5 стык %s: кадры стыка не соседние' % name)
        fa = {i['id']: i for i in a['items'] if i['kind'] == 'frame' and not i['scene']}
        fb = {i['id']: i for i in b['items'] if i['kind'] == 'frame' and not i['scene']}
        for k in sorted(set(fa) | set(fb)):
            if k not in fa or k not in fb:
                f.append('V5 стык %s: каркас #%s пропал на стыке' % (name, k))
            elif max(abs(x - y) for x, y in zip(fa[k]['rect'], fb[k]['rect'])) > FRAME_TOL:
                f.append('V5 стык %s: каркас #%s сдвинулся %s → %s' % (name, k, fa[k]['rect'], fb[k]['rect']))
    if not probe.get('seams') and len(sc) > 1:
        f.append('V5 стык: сцен %d, а стыков в промере нет' % len(sc))
    return f


def sat_bindings(ctx):
    """{(сцена, id): [(t или None, dur, id хозяина или None)]} — привязки спутников по раскадровкам:
    with / data-with — с начала сцены; move to_text на надпись своей сцены — с этого move; move к элементу
    другой сцены (мост) — отвязка."""
    if '_sats' in ctx:
        return ctx['_sats']
    sbs = storyboards(ctx)
    in_film = {s['id'] for s, _ in sbs}
    out = {}
    for s, sb in sbs:
        sc = s['id']
        for e in sb.get('elements', []):
            if e.get('with'):
                out[(sc, e['id'])] = [(None, 0.0, e['with'])]
        for mid, attrs, _ in markup_els(ctx, s, sb):
            w = re.search(r'\bdata-with="([a-z0-9-]+)"', attrs)
            if w:
                out[(sc, mid)] = [(None, 0.0, w.group(1))]
        moves = []
        for b in sb['beats']:
            if b['action'] != 'move':
                continue
            ref = (b.get('to_text') or {}).get('el') or b.get('to_el')
            for i, tg in enumerate(b['targets']):
                t = beat_t(ctx, b, i)
                if '.' in tg or t is None or not ref:
                    continue
                dsc, _, did = ref.rpartition(':')
                if dsc and dsc != sc:
                    if dsc in in_film:
                        moves.append((t, tg, b.get('dur', mo(ctx, 'move_dur')), None))
                elif 'to_text' in b and did != tg:
                    moves.append((t, tg, b.get('dur', mo(ctx, 'move_dur')), did))
        for t, tg, d, host in sorted(moves, key=lambda x: x[0]):
            fl = out.get((sc, tg), [])
            if host is None and not (fl and fl[-1][2]):
                continue
            out[(sc, tg)] = fl + [(t, d, host)]
    ctx['_sats'] = out
    return out


def sat_host_at(ctx, sc, tg, t):
    h = None
    for t0, _, host in sat_bindings(ctx).get((sc, tg), []):
        if t0 is None or t0 <= t + 1e-6:
            h = host
    return h


def _host_scale(ctx, smp, sc, tg):
    h = sat_host_at(ctx, sc, tg, smp['t']) if '.' not in tg else None
    it = item_of(smp, '%s--%s' % (sc, h)) if h else None
    return it['scale'] if it else 1.0


def _inout(x):
    return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


def breath_scale(ctx, sc, tg, t):
    """Множитель дыхания цели в момент t по контракту tokens.json motion.breathe."""
    br = mo(ctx, 'breathe')
    period, edge, amp0 = float(br['period']), float(br['edge']), float(br['scale'])
    k = 1.0
    for s, sb in storyboards(ctx):
        if s['id'] != sc:
            continue
        for b in sb['beats']:
            if b['action'] != 'emph' or b.get('style') != 'breathe' or tg not in b['targets']:
                continue
            i = b['targets'].index(tg)
            t0, until = beat_t(ctx, b, i), beat_t(ctx, b['until'])
            if t0 is None or until is None:
                continue
            until += i * b.get('stagger', 0.0)
            if not (t0 < t < until + edge):
                continue
            ein = _inout(min(1.0, (t - t0) / edge))
            eout = _inout(min(1.0, max(0.0, (t - until) / edge)))
            k *= 1 + b.get('amp', amp0) * min(ein, 1 - eout) * (0.5 - 0.5 * math.cos(2 * math.pi * (t - t0) / period))
    return k


def pulse_scale(ctx, sc, tg, t, it):
    """Множитель пульсов цели в момент t (контракт emph pulse: синус, рост ≤ 24 px на сторону)."""
    k, w = 1.0, it['rect'][2] / it['scale']
    for s, sb in storyboards(ctx):
        if s['id'] != sc:
            continue
        for b in sb['beats']:
            if b['action'] != 'emph' or b.get('style', 'pulse') != 'pulse' or tg not in b['targets']:
                continue
            t0 = beat_t(ctx, b, b['targets'].index(tg))
            d = b.get('dur', mo(ctx, 'emph_dur'))
            if t0 is not None and t0 < t < t0 + d:
                k *= 1 + min(b.get('amp', mo(ctx, 'pulse_amp')), 24.0 / w) * math.sin(math.pi * (t - t0) / d)
    return k


def move_expect(ctx, b, m):
    """Рамка якоря в конце move по контракту полей fit / anchor / self / dx / dy / size / pad."""
    k0 = PX(ctx)
    S, D = m['anchor0'], m['dest']
    pd = [v * k0 for v in b.get('pad', [0, 0])]
    if len(pd) == 2:
        pd = pd + pd
    D = [D[0] - pd[0], D[1] - pd[1], D[2] + pd[0] + pd[2], D[3] + pd[1] + pd[3]]
    fit = b.get('fit', 'text' if 'to_text' in b else 'box')
    if fit == 'text':
        k = (b['size'] * k0 / 72 / m['fontPx']) if (b.get('size') and m['fontPx']) else D[3] / S[3]
        kx = ky = k
    elif fit == 'box':
        kx, ky = D[2] / S[2], D[3] / S[3]
    else:
        kx = ky = 1.0
    a = b.get('anchor', [0.5, 0.5] if fit == 'none' else [0, 0])
    s = b.get('self', a)
    w, h = S[2] * kx, S[3] * ky
    return [D[0] + a[0] * D[2] + b.get('dx', 0) * k0 - s[0] * w, D[1] + a[1] * D[3] + b.get('dy', 0) * k0 - s[1] * h, w, h]


def v6_storyboard(ctx):
    """V6 (C7): раскадровка исполнена — каждый бит виден в промере: title_at, num_at, chapter_at (заливка
    едет), tracker_emph, show/hide lift и cut, наплыв с dur, draw, show level, level, emph (ring, pulse,
    breathe, flip, spin), move (якорь в конце = цель по fit/anchor/self/dx/dy/size, цвет, наклон)."""
    f = []
    F = FR(ctx)
    sbs = storyboards(ctx)
    in_film = {s['id'] for s, _ in sbs}
    pmoves = ctx['probe'].get('moves', [])
    title_in, ch_dur = float(mo(ctx, 'title_in')), float(mo(ctx, 'chapter_dur'))
    emph_dur, move_dur = float(mo(ctx, 'emph_dur')), float(mo(ctx, 'move_dur'))
    br = mo(ctx, 'breathe')
    b_period, b_edge, b_amp = float(mo(ctx, 'breathe.period')), float(mo(ctx, 'breathe.edge')), float(mo(ctx, 'breathe.scale'))

    def need(t, what):
        s = sample_at(ctx, t)
        if s is None:
            f.append('V6 %s: нет промера кадра t=%.3f с' % (what, t))
        return s
    for s, sb in sbs:
        sc = s['id']
        if sb.get('title_at') and beat_t(ctx, sb['title_at']) is not None:
            t0 = beat_t(ctx, sb['title_at'])
            tid = 'title--' + sc
            a, b = need(t0 - F, 'title_at %s' % sc), need(t0 + title_in + 2 * F, 'title_at %s' % sc)
            if a and opacity_of(a, tid) > VISIBLE:
                f.append('V6 title_at %s: заголовок виден до своего бита (t=%.2f с, %.2f)' % (sc, a['t'], opacity_of(a, tid)))
            if b and opacity_of(b, tid) < FULL:
                f.append('V6 title_at %s: заголовок не вошёл за %.2f с после бита (t=%.2f с, %.2f)'
                         % (sc, title_in, b['t'], opacity_of(b, tid)))
        if sb.get('num_at') and beat_t(ctx, sb['num_at']) is not None:
            t0 = beat_t(ctx, sb['num_at'])
            a = need(t0 - F, 'num_at %s' % sc)
            if a and opacity_of(a, 'num--' + sc) > VISIBLE:
                f.append('V6 num_at %s: номер виден до своего бита (t=%.2f с)' % (sc, a['t']))
            b = need(t0 + title_in + 2 * F, 'num_at %s' % sc)
            if b and opacity_of(b, 'num--' + sc) < FULL:
                f.append('V6 num_at %s: номер не вошёл за %.2f с после бита (t=%.2f с)' % (sc, title_in, b['t']))
        if sb.get('chapter_at') and beat_t(ctx, sb['chapter_at']) is not None:
            t0 = beat_t(ctx, sb['chapter_at'])
            for when, ch in ((t0 - F, sb['chapter_from']), (t0 + ch_dur + 2 * F, sb['chapter'])):
                smp = need(when, 'chapter_at %s' % sc)
                if not smp:
                    continue
                lit = [x['id'] for x in smp.get('tracker', []) if x['opacity'] > 0.5 and x['fill'][1] - x['fill'][0] > 1]
                if lit != ['tr-on-%d' % chapter_index(ctx, ch)]:
                    f.append('V6 chapter_at %s: в t=%.2f с горит %s, а ждали %s' % (sc, smp['t'], lit, ch))
            mid = need(t0 + ch_dur / 2, 'chapter_at %s' % sc)
            if mid:
                vis = [x for x in mid.get('tracker', []) if x['opacity'] > VISIBLE]
                if any(x['opacity'] < FULL for x in vis):
                    f.append('V6 chapter_at %s: на полпути заливка наплывает (непрозрачность %s), а должна ехать'
                             % (sc, [x['opacity'] for x in vis]))
        for w in sb.get('tracker_emph', []) or []:
            t0 = beat_t(ctx, w)
            if t0 is None:
                continue
            smp = need(t0 + emph_dur / 2, 'tracker_emph %s' % sc)
            if not smp:
                continue
            ch = sb.get('chapter')
            if sb.get('chapter_at') and t0 < beat_t(ctx, sb['chapter_at']) + ch_dur / 2:
                ch = sb.get('chapter_from')
            it = item_of(smp, 'tr-%d' % chapter_index(ctx, ch))
            amp = float(mo(ctx, 'pulse_amp'))
            if not it or abs(it['scale'] - (1 + amp)) > SCALE_TOL:
                f.append('V6 tracker_emph %s: в t=%.2f с плашка %s в масштабе %s, а ждали %.2f'
                         % (sc, smp['t'], ch, it and it['scale'], 1 + amp))
        for b in sb['beats']:
            act = b['action']
            for i, tg in enumerate(b.get('targets', [])):
                t0 = beat_t(ctx, b, i)
                if t0 is None:
                    continue
                key, dom = (sc, tg), '%s--%s' % (sc, tg)
                whole = '.' not in tg
                if act in ('show', 'hide') and whole and b.get('anim') in ('lift', 'cut'):
                    anim = b['anim']
                    d = anim_dur(ctx, anim)
                    if _busy(ctx, key, t0, t0 + d + 2 * F):
                        continue
                    lvl = b.get('level', 1) if act == 'show' else 0
                    end = need(t0 + (F if anim == 'cut' else d + 2 * F), '%s %s #%s' % (anim, act, dom))
                    if end and abs(opacity_of(end, dom) - lvl) > LEVEL_TOL:
                        f.append('V6 %s %s #%s: в t=%.2f с непрозрачность %.3f, а ждали %.2f'
                                 % (anim, act, dom, end['t'], opacity_of(end, dom), lvl))
                    if anim == 'lift' and not sat_host_at(ctx, sc, tg, t0):
                        pre = need(t0 - F if act == 'hide' else t0 + d + 2 * F, 'lift #%s' % dom)
                        mid = need(t0 + (0.8 if act == 'hide' else 0.2) * d, 'lift #%s' % dom)
                        ref, cur = (item_of(pre, dom) if pre else None), (item_of(mid, dom) if mid else None)
                        if ref and cur:
                            shift = cur['rect'][1] - ref['rect'][1]
                            want = -1 if act == 'hide' else 1
                            if shift * want < 2:
                                f.append('V6 lift %s #%s: в пути сдвиг по y %.1f px, а ждали %s'
                                         % (act, dom, shift, 'вверх' if act == 'hide' else 'снизу вверх'))
                elif act in ('show', 'hide') and whole and b.get('dur') is not None:
                    d = b['dur']
                    if _busy(ctx, key, t0, t0 + d + 2 * F):
                        continue
                    lvl = b.get('level', 1) if act == 'show' else 0
                    mid, end = need(t0 + d / 2, '%s dur #%s' % (act, dom)), need(t0 + d + 2 * F, '%s dur #%s' % (act, dom))
                    if mid and not 0.05 < opacity_of(mid, dom) < 0.95:
                        f.append('V6 %s dur #%s: на середине наплыва %.2f с (t=%.2f с) непрозрачность %.3f'
                                 % (act, dom, d, mid['t'], opacity_of(mid, dom)))
                    if end and abs(opacity_of(end, dom) - lvl) > LEVEL_TOL:
                        f.append('V6 %s dur #%s: через %.2f с (t=%.2f с) непрозрачность %.3f, а ждали %.2f'
                                 % (act, dom, d, end['t'], opacity_of(end, dom), lvl))
                elif act == 'show' and whole and b.get('anim') == 'draw':
                    d = anim_dur(ctx, 'draw')
                    if _busy(ctx, key, t0, t0 + d + 2 * F):
                        continue
                    mid, end = need(t0 + d / 2, 'draw #%s' % dom), need(t0 + d + 2 * F, 'draw #%s' % dom)
                    a, c = (item_of(mid, dom) if mid else None), (item_of(end, dom) if end else None)
                    if a is not None and not (a.get('dash') is not None and 0.05 < a['dash'] < 0.95):
                        f.append('V6 draw #%s: в середине прорисовки (t=%.2f с) штрих %s, а ждали нарисованный частично'
                                 % (dom, mid['t'], a.get('dash')))
                    if c is not None and c.get('dash') not in (None, 0):
                        f.append('V6 draw #%s: после прорисовки (t=%.2f с) штрих не дорисован (%s)' % (dom, end['t'], c.get('dash')))
                elif act == 'show' and whole and 'level' in b:
                    d = anim_dur(ctx, b.get('anim', 'rise'))
                    if _busy(ctx, key, t0, t0 + d + 2 * F):
                        continue
                    end = need(t0 + d + 2 * F, 'show level #%s' % dom)
                    if end and abs(opacity_of(end, dom) - b['level']) > LEVEL_TOL:
                        f.append('V6 show level #%s: в t=%.2f с непрозрачность %.3f, а ждали %.2f'
                                 % (dom, end['t'], opacity_of(end, dom), b['level']))
                elif act == 'level' and whole:
                    d = b.get('dur', level_default_dur(ctx, sb, tg, t0, b['value']))
                    if _busy(ctx, key, t0, t0 + d + 2 * F):
                        continue
                    end = need(t0 + d + 2 * F, 'level #%s' % dom)
                    if end and abs(opacity_of(end, dom) - b['value']) > LEVEL_TOL:
                        f.append('V6 level #%s: в t=%.2f с непрозрачность %.3f, а ждали %.2f'
                                 % (dom, end['t'], opacity_of(end, dom), b['value']))
                elif act == 'emph' and whole and b.get('style') == 'breathe':
                    amp = b.get('amp', b_amp)
                    until = beat_t(ctx, b['until'], i) if beat_t(ctx, b['until']) is not None else None
                    if until is None:
                        continue
                    if until - t0 >= b_period / 2 + b_edge:
                        smp = need(t0 + b_period / 2, 'breathe #%s' % dom)
                        it = item_of(smp, dom) if smp else None
                        if it:
                            want = breath_scale(ctx, sc, tg, smp['t']) * pulse_scale(ctx, sc, tg, smp['t'], it)
                            want *= _host_scale(ctx, smp, sc, tg)
                            if abs(it['scale'] - want) > 0.003 or it['scale'] < 1 + 0.5 * amp:
                                f.append('V6 breathe #%s: на вдохе t=%.2f с масштаб %.4f, а ждали %.4f'
                                         % (dom, smp['t'], it['scale'], want))
                    for lag in (0.0, b_period / 4):
                        tt = until + b_edge + 2 * F + lag
                        if _busy(ctx, key, until, tt):
                            break
                        smp = need(tt, 'breathe #%s' % dom)
                        it = item_of(smp, dom) if smp else None
                        if not it:
                            continue
                        want = breath_scale(ctx, sc, tg, smp['t']) * pulse_scale(ctx, sc, tg, smp['t'], it)
                        want *= _host_scale(ctx, smp, sc, tg)
                        if abs(it['scale'] - want) > 0.003:
                            f.append('V6 breathe #%s: фокус ушёл, а в t=%.2f с масштаб %.4f (ждали %.4f)'
                                     % (dom, smp['t'], it['scale'], want))
                            break
                elif act == 'emph' and whole and b.get('style') == 'flip':
                    d = b.get('dur', emph_dur)
                    full, mid = need(t0 + d + 2 * F, 'flip #%s' % dom), need(t0 + d / 2, 'flip #%s' % dom)
                    a, c = (item_of(full, dom) if full else None), (item_of(mid, dom) if mid else None)
                    if a and c and c['rect'][2] > 0.35 * a['rect'][2]:
                        f.append('V6 flip #%s: в середине разворота (t=%.2f с) ширина %.1f px — не ребром (во всю %.1f px)'
                                 % (dom, mid['t'], c['rect'][2], a['rect'][2]))
                elif act == 'emph' and whole and b.get('style') == 'spin':
                    d, dr = b.get('dur', emph_dur), b.get('dir', 1)
                    for frac in (0.25, 0.5):
                        smp = need(t0 + frac * d, 'spin #%s' % dom)
                        it = item_of(smp, dom) if smp else None
                        if not it:
                            continue
                        x = min(1.0, max(0.0, (smp['t'] - t0) / d))
                        want = dr * 360 * _inout(x)
                        if abs((it['rot'] - want + 180) % 360 - 180) > 2.0:
                            f.append('V6 spin #%s: в t=%.2f с поворот %.1f°, а ждали %.1f°' % (dom, smp['t'], it['rot'], want))
                            break
                elif act == 'emph' and whole and b.get('style') != 'flash':
                    d = b.get('dur', emph_dur)
                    ring = b.get('style') == 'ring'
                    smp = need(t0 + (0.2 if ring else 0.5) * d, 'emph #%s' % dom)
                    it = item_of(smp, dom) if smp else None
                    if not it:
                        continue
                    if ring:
                        amp = b.get('amp', mo(ctx, 'ring_amp'))
                        if abs(abs(it['rot']) - amp) > 0.15 * amp:
                            f.append('V6 ring #%s: в t=%.2f с поворот %.1f°, а ждали ±%.1f°' % (dom, smp['t'], it['rot'], amp))
                    else:
                        amp = b.get('amp', mo(ctx, 'pulse_amp'))
                        hs = _host_scale(ctx, smp, sc, tg)
                        w = it['rect'][2] / it['scale']
                        want = (1 + min(amp, 24.0 / w)) * breath_scale(ctx, sc, tg, smp['t']) * hs
                        if abs(it['scale'] - want) > SCALE_TOL:
                            f.append('V6 pulse #%s: в t=%.2f с масштаб %.4f, а ждали %.4f' % (dom, smp['t'], it['scale'], want))
                elif act == 'move':
                    ref = b.get('to_el') or (b.get('to_text') or {}).get('el') or ''
                    if ':' in ref and ref.split(':')[0] not in in_film:
                        continue
                    node = '%s:%s' % (sc, tg)
                    info = [m for m in pmoves if m['node'] == node and abs(m['t'] - round(t0, 4)) < 2e-3]
                    name = '#%s--%s' % (sc, tg)
                    if not info or info[0]['dest'] is None:
                        f.append('V6 move %s: в промере нет цели движения' % name)
                        continue
                    m = info[0]
                    d = b.get('dur', move_dur)
                    if 'to_text' in b and b.get('fit', 'text') == 'text' and not b.get('size') and m['dest'][2] > 0:
                        k = m['dest'][3] / m['anchor0'][3]
                        if abs(m['anchor0'][2] * k - m['dest'][2]) > TEXT_FIT_TOL * m['dest'][2]:
                            f.append('V6 move %s: текст не лёг буквы на буквы — ширина %.0f px против %.0f px подстроки'
                                     ' (строк у текста и у цели разное число?)' % (name, m['anchor0'][2] * k, m['dest'][2]))
                    if _busy(ctx, key, t0, t0 + d + 2 * F):
                        continue
                    end = need(max(F, t0 + d + 2 * F), 'move %s' % name)
                    if not end:
                        continue
                    got = end.get('anchors', {}).get(node)
                    srec = (end.get('sats') or {}).get(node)
                    if got and srec and srec.get('host') and sat_host_at(ctx, sc, tg, end['t']):
                        got = dict(got, rect=srec['local'])
                    want = move_expect(ctx, b, m)
                    if got and abs(got.get('rot', 0)) > TILT_TOL and not _busy(ctx, key, t0 + d, t0 + d + 2 * F):
                        f.append('V6 move %s: после посадки (t=%.2f с) наклон %.1f°, а ждали 0' % (name, end['t'], got['rot']))
                    if not got or max(abs(x - y) for x, y in zip(got['rect'], want)) > MOVE_TOL:
                        f.append('V6 move %s: в t=%.2f с якорь %s, а цель %s'
                                 % (name, end['t'], got and got['rect'], [round(v, 2) for v in want]))
                    if b.get('tilt') and t0 + d / 2 >= 0:
                        mid = need(t0 + d / 2, 'move tilt %s' % name)
                        a = mid and mid.get('anchors', {}).get(node)
                        if a is not None and abs(a.get('rot', 0) - b['tilt']) > TILT_TOL:
                            f.append('V6 move %s: в середине полёта (t=%.2f с) наклон %.1f°, а ждали %.1f°'
                                     % (name, mid['t'], a.get('rot', 0), b['tilt']))
                    if b.get('color') and got:
                        hx = ctx['tokens']['palette'].get(b['color'], b['color'])
                        rgb = hex_rgb(hx) if hx.startswith('#') else hx
                        if got['color'] != rgb:
                            f.append('V6 move %s: цвет в конце %s, а ждали %s (%s)' % (name, got['color'], rgb, b['color']))
    return f


def v7_seam_frames(ctx):
    """V7 (C8): шов без пустого кадра — в каждом кадре паузы и 0,5 с после первой реплики N+1
    в рабочей зоне (project.json work_zone) виден хотя бы один элемент содержания."""
    f, sc, W = [], ctx['film']['scenes'], work_zone(ctx)
    for a, b in zip(sc, sc[1:]):
        name = '%s → %s' % (a['id'], b['id'])
        missing, empty = [], []
        fr = frame_of(ctx, a['last'])
        while fr / fps(ctx) <= b['first'] + SEAM_TAIL + 1e-6:
            t = fr / fps(ctx)
            fr += 1
            s = sample_at(ctx, t)
            if s is None:
                missing.append(t)
                continue
            if not any(it['kind'] == 'content' and it['opacity'] > VISIBLE and area(it['rect'], W) > 0 for it in s['items']):
                empty.append(t)
        if missing:
            f.append('V7 шов %s: нет промера %d кадр(ов) паузы, первый t=%.3f с' % (name, len(missing), missing[0]))
        if empty:
            f.append('V7 шов %s: рабочая зона пуста в %d кадр(ах), первый t=%.3f с' % (name, len(empty), empty[0]))
    return f


def v8_layers(ctx):
    """V8 (C9): слой under — под обычными элементами сцены, over — над ними (z промера против объявления)."""
    f, decl, z = [], declared_layers(ctx), {}
    for s in ctx['probe']['samples']:
        for it in s['items']:
            if it['kind'] == 'content':
                z.setdefault(it['id'], it.get('z', 0))
    for sc in ctx['film']['scenes']:
        mine = {i: v for i, v in z.items() if i.startswith(sc['id'] + '--') and i in decl}
        normal = [i for i in mine if decl[i] is None]
        for i in sorted(mine):
            if decl[i] == 'under' and normal and mine[i] >= min(mine[n] for n in normal):
                n = min(normal, key=lambda k: mine[k])
                f.append('V8 слои %s: #%s (under, z=%d) не под #%s (z=%d)' % (sc['id'], i, mine[i], n, mine[n]))
            if decl[i] == 'over' and normal and mine[i] <= max(mine[n] for n in normal):
                n = max(normal, key=lambda k: mine[k])
                f.append('V8 слои %s: #%s (over, z=%d) не над #%s (z=%d)' % (sc['id'], i, mine[i], n, mine[n]))
    return f


def removed_by_storyboard(ctx, sb, sc, t):
    """id элементов сцены, последнее событие show/hide которых к моменту t — hide."""
    last = {}
    for b in sb['beats']:
        if b['action'] not in ('show', 'hide'):
            continue
        for i, tg in enumerate(b['targets']):
            if '.' in tg:
                continue
            bt = beat_t(ctx, b, i)
            if bt is not None and bt <= t + 1e-6 and (tg not in last or bt >= last[tg][0]):
                last[tg] = (bt, b['action'])
    return {'%s--%s' % (sc, k) for k, (_, a) in last.items() if a == 'hide'}


def legibility_except(ctx):
    """{dom-id: запись} именованных исключений из читаемости — project.json legibility_except [{el: "сцена:id",
    max_opacity, min_visible, min_visible_sec}] (намеренно тусклая надпись: вывеска, водяной знак). Не мерятся V21 и правилом
    «всё на 1,0» V9; взамен V35. Только названный элемент: имя без сцены — отказ."""
    out = {}
    for e in ctx['project'].get('legibility_except') or []:
        sc, _, el = str(e.get('el', '')).partition(':')
        if not sc or not el:
            raise SystemExit('project.json legibility_except: el «%s» — нужно «сцена:id»' % e.get('el'))
        out['%s--%s' % (sc, el)] = e
    return out


def v9_scene_end(ctx):
    """V9 (C10): в последнем кадре сцены (конец её последней реплики) каждая надпись сцены видна на 1,0,
    ничто не стоит ниже 1 (тень, приглушение), слой under снят; кроме убранного раскадровкой (hide) и
    именованной тусклой вывески (project.json legibility_except — её мерит V35)."""
    f, decl, texted = [], declared_layers(ctx), set()
    dim = legibility_except(ctx)
    for s in ctx['probe']['samples']:
        for it in s['items']:
            if it['kind'] == 'content' and any(norm(x) for x in it['texts']):
                texted.add(it['id'])
    for s, sb in storyboards(ctx):
        sc = s['id']
        t = q(ctx, s['last'])
        smp = sample_at(ctx, t)
        if smp is None:
            f.append('V9 последний кадр %s: нет промера t=%.3f с' % (sc, t))
            continue
        gone = removed_by_storyboard(ctx, sb, sc, t)
        mine = {it['id']: it for it in smp['items'] if it['kind'] == 'content' and it['id'].startswith(sc + '--')}
        for i, it in sorted(mine.items()):
            if it['opacity'] <= VISIBLE:
                continue
            if decl.get(i) == 'under':
                f.append('V9 последний кадр %s: #%s (слой under — фокус или тень) не снят, %.2f (t=%.2f с)'
                         % (sc, i, it['opacity'], smp['t']))
            elif it['opacity'] < FULL and i not in gone and i not in dim:
                f.append('V9 последний кадр %s: #%s на %.2f, а в итоге сцены всё на 1,0 (t=%.2f с)'
                         % (sc, i, it['opacity'], smp['t']))
        for i in sorted(texted):
            if i.startswith(sc + '--') and i not in gone and decl.get(i) != 'under' and \
                    (i not in mine or mine[i]['opacity'] <= VISIBLE):
                f.append('V9 последний кадр %s: надписи #%s нет в кадре (t=%.2f с)' % (sc, i, smp['t']))
    return f


def flight_windows(ctx):
    """{dom-id: [(начало, конец)]} движений целых элементов без текста (иконки; кроме слоя under)."""
    if '_flying' not in ctx:
        decl, out = declared_layers(ctx), {}
        for s, sb in storyboards(ctx):
            for b in sb['beats']:
                if b['action'] != 'move':
                    continue
                for i, tg in enumerate(b['targets']):
                    dom = '%s--%s' % (s['id'], tg)
                    if '.' in tg or decl.get(dom) == 'under':
                        continue
                    t0 = beat_t(ctx, b, i)
                    if t0 is not None:
                        out.setdefault(dom, []).append((t0, t0 + b.get('dur', mo(ctx, 'move_dur'))))
        ctx['_flying'] = out
    return ctx['_flying']


def v10_text_boxes(ctx):
    """V10 (C11): нет двух читаемых (> 0,3) надписей разных элементов, чьи строки пересекаются, нет строки
    за рамкой своего элемента (кроме едущей move); иконка в полёте и группы голоса не закрывают строк.
    На шве строже: читаемая (> 0,25) строка не пересекает видимую (> 0,05) строку другого элемента,
    строки моста не сталкиваются, читаемая строка не уходит под чужую заливку выше неё."""
    f, seen = [], set()
    flying = flight_windows(ctx)
    for s in ctx['probe']['samples']:
        lines = []
        for it in s['items']:
            for g in it.get('segs', []):
                if g[4] <= TEXT_SEEN:
                    continue
                lines.append((it, g))
                if not g[5] and _outside_own(g, it['rect']) and ('out', it['id']) not in seen:
                    seen.add(('out', it['id']))
                    f.append('V10 надписи: #%s: строка %s за рамкой своего элемента %s (t=%.2f с)'
                             % (it['id'], [round(v) for v in g[:4]], [round(v) for v in it['rect']], s['t']))
        for it in s['items']:
            is_vo = it['id'].startswith('vo-')
            if it['opacity'] <= TEXT_SEEN:
                continue
            if not is_vo and (it.get('segs') or not any(a < s['t'] < b for a, b in flying.get(it['id'], ()))):
                continue
            for other, g in lines:
                if other['id'] == it['id']:
                    continue
                ar = area(_shrunk(it['rect']), _shrunk(g))
                key = ('fly', it['id'], other['id'])
                if ar > TEXT_AREA_MIN and key not in seen:
                    seen.add(key)
                    f.append('V10 надписи: #%s (%s) закрывает строку #%s на %.0f px² (t=%.2f с)'
                             % (it['id'], 'группа голоса' if is_vo else 'в полёте', other['id'], ar, s['t']))
        for k, (a, ga) in enumerate(lines):
            for b, gb in lines[k + 1:]:
                if a['id'] == b['id']:
                    continue
                ar = area(_shrunk(ga), _shrunk(gb))
                if ar <= TEXT_AREA_MIN:
                    continue
                (x, gx), (y, gy) = sorted(((a, ga), (b, gb)), key=lambda p: p[0]['id'])
                key = (x['id'], y['id'])
                if key not in seen:
                    seen.add(key)
                    f.append('V10 надписи: #%s и #%s: строки пересекаются на %.0f px² (t=%.2f с, видны на %.2f и %.2f)'
                             % (x['id'], y['id'], ar, s['t'], gx[4], gy[4]))
        seam = seam_of(ctx, s['t'])
        if seam:
            _v10_seam_frame(s, seam, f, seen)
    return f


def _v10_seam_frame(s, seam, f, seen):
    order = {it['id']: (it.get('z', 0), k) for k, it in enumerate(s['items'])}
    lines = [(it, g) for it in s['items'] for g in it.get('segs', []) if g[4] > SEAM_TEXT_UNDER]
    for k, (a, ga) in enumerate(lines):
        for b, gb in lines[k + 1:]:
            if max(ga[4], gb[4]) <= SEAM_TEXT_SEEN:
                continue
            same = a['id'] == b['id']
            if same and (not (ga[5] or gb[5]) or max(abs(x - y) for x, y in zip(ga[:4], gb[:4])) <= EDGE_TOL * 2):
                continue
            ar = area(_shrunk(ga), _shrunk(gb))
            if ar <= TEXT_AREA_MIN:
                continue
            if same:
                key = ('seam-self', seam, a['id'])
                msg = ('V10 шов %s: #%s: строки моста сталкиваются (между собой или со своим текстом) на %.0f px² (t=%.2f с)'
                       % (seam, a['id'], ar, s['t']))
            else:
                (x, gx), (y, gy) = sorted(((a, ga), (b, gb)), key=lambda p: p[0]['id'])
                key = ('seam', seam, x['id'], y['id'])
                msg = ('V10 шов %s: #%s и #%s: строки пересекаются на %.0f px² (t=%.2f с, видны на %.2f и %.2f)'
                       % (seam, x['id'], y['id'], ar, s['t'], gx[4], gy[4]))
            if key not in seen:
                seen.add(key)
                f.append(msg)
    for a, ga in lines:
        if ga[4] <= SEAM_TEXT_SEEN:
            continue
        for b in s['items']:
            if b['id'] == a['id'] or b['kind'] != 'content' or order[b['id']] <= order[a['id']]:
                continue
            key = ('seam-fill', seam, a['id'], b['id'])
            if key in seen:
                continue
            for fb in b.get('fills', []):
                ar = area(_shrunk(ga), fb[:4])
                if max(abs(x - y) for x, y in zip(fb[:4], a['rect'])) <= 2.0:
                    continue    # мост-форма: заливка N легла рамка в рамку на блок N+1 и растворяется над ним
                if fb[4] > VISIBLE and ar > TEXT_AREA_MIN:
                    seen.add(key)
                    f.append('V10 шов %s: строка #%s (%.2f) под заливкой #%s (%.2f) на %.0f px² (t=%.2f с)'
                             % (seam, a['id'], ga[4], b['id'], fb[4], ar, s['t']))
                    break


def v11_font(ctx):
    """V11 (C12): каждый шрифт tokens.json fonts на странице — loaded (Chrome не отверг файл);
    синтез начертаний выключен (font-synthesis: none) — синтетический жирный шире настоящего."""
    f = []
    fonts = ctx['probe'].get('fonts')
    if fonts is None:
        return ['V11 шрифт: в промере нет статуса document.fonts — пересобери страницу']
    for fd in list(ctx['tokens'].get('fonts') or []) + list(ctx['project'].get('fonts') or []):
        fam = fd['family']
        st = [x['status'] for x in fonts if x['family'] == fam]
        if not st:
            f.append('V11 шрифт: %s не объявлен на странице (document.fonts: %s)' % (fam, sorted({x['family'] for x in fonts})))
        elif any(x != 'loaded' for x in st):
            f.append('V11 шрифт: %s — статус %s, а нужен loaded (Chrome отверг файл — страница рисуется запасным)'
                     % (fam, ', '.join(st)))
    syn = {v.get('synthesis') for v in (ctx['probe'].get('frameStyle') or {}).values()}
    if not syn and not any(s.get('frame', True) for s in ctx['film']['scenes']):
        # все сцены без каркаса: узлов .fr нет, синтез начертаний — по корню страницы
        rs = (ctx['probe'].get('rootStyle') or {}).get('synthesis')
        syn = {rs} if rs else set()
    if not syn:
        f.append('V11 шрифт: в промере нет frameStyle — пересобери страницу')
    elif syn != {'none'}:
        f.append('V11 шрифт: font-synthesis %s, а нужен none (синтетический жирный)' % ', '.join(sorted(str(x) for x in syn)))
    return f


_RGB_RE = re.compile(r'rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)')


def v12_palette(ctx):
    """V12 (C16): цвета содержания — только палитра tokens.json: hex в слое содержания страницы (виды,
    иконки после перекраски, разметка) и заливки, цвет текста и обводки частей видов по промеру DOM."""
    p = ctx.get('page')
    if not p or not os.path.exists(p):
        return ['V12 палитра: нет страницы %s' % p]
    with open(p, encoding='utf-8') as fh:
        page = fh.read()
    pal = {v.upper() for v in ctx['tokens']['palette'].values()}
    pal_rgb = {hex_rgb(v) for v in pal}
    a, b = page.find('<div id="content"'), page.find('<script>window.__FILM__')
    if a < 0 or b < a:
        return ['V12 палитра: в странице нет слоя содержания']
    out = []
    bad = sorted({c.upper() for c in re.findall(r'#[0-9A-Fa-f]{6}\b', page[a:b])} - pal)
    if bad:
        out.append('V12 палитра: в содержании страницы цвета вне палитры tokens.json: %s' % ', '.join(bad))
    badr = set()
    for m in _RGB_RE.finditer(page[a:b]):
        c = 'rgb(%s, %s, %s)' % m.group(1, 2, 3)
        if c not in pal_rgb and not (m.group(4) is not None and float(m.group(4)) == 0):
            badr.add(c)
    seen = set()
    for s in ctx['probe']['samples']:
        for it in s['items']:
            if it['kind'] != 'content':
                continue
            for fl in it.get('fills', []):
                if fl[5] not in pal_rgb and (it['id'], fl[5]) not in seen:
                    seen.add((it['id'], fl[5]))
                    out.append('V12 палитра: заливка #%s %s вне палитры (t=%.2f с)' % (it['id'], fl[5], s['t']))
    for dom, k in sorted((ctx['probe'].get('kinds') or {}).items()):
        for pn, part in sorted(k.get('parts', {}).items()):
            for what in ('color', 'bg', 'borderColor'):
                v = part.get(what) or ''
                m = _RGB_RE.match(v)
                if not m or (m.group(4) is not None and float(m.group(4)) == 0):
                    continue
                if what == 'borderColor' and not part.get('border'):
                    continue
                c = 'rgb(%s, %s, %s)' % m.group(1, 2, 3)
                if c not in pal_rgb:
                    out.append('V12 палитра: #%s.%s %s %s вне палитры' % (dom, pn, what, c))
    if badr:
        out.append('V12 палитра: в содержании страницы rgb вне палитры tokens.json: %s' % ', '.join(sorted(badr)))
    return out


def v13_satellites(ctx):
    """V13 (C19): спутники (with / data-with / move to_text на надпись своей сцены) едут со своей надписью:
    пока оба видны и спутник не едет сам, его центр в системе надписи стоит ±1 px; иконка на строке
    надписи (≤ 0,8″, ≤ 0,5″ до надписи, не между двумя) объявлена спутником."""
    f, F, k0 = [], FR(ctx), PX(ctx)
    sbs = storyboards(ctx)
    binds = sat_bindings(ctx)
    samples = ctx['probe']['samples']
    for s, sb in sbs:
        sc = s['id']
        texts = [(e['id'], (e['x'], e['y'], e['w'], e['h'])) for e in sb.get('elements', []) if e.get('text')]
        texts += [(mid, tuple(v / k0 for v in box)) for mid, box in markup_boxes(ctx, s, sb) if box]
        for e in sb.get('elements', []):
            if e['kind'] != 'icon' or e['h'] > ICON_ROW_MAX_H:
                continue
            cx = e['x'] + e['w'] / 2
            near = {'l': [], 'r': []}
            for tid, (x, y, w, h) in texts:
                ov = min(e['y'] + e['h'], y + h) - max(e['y'], y)
                gap = max(0.0, x - (e['x'] + e['w']), e['x'] - (x + w))
                if ov >= 0.5 * e['h'] and gap <= ICON_ROW_GAP:
                    near['l' if x + w / 2 < cx else 'r'].append(tid)
            if near['l'] and near['r'] or not (near['l'] or near['r']):
                continue
            hosts = {b[2] for b in binds.get((sc, e['id']), [])}
            if not hosts & set(near['l'] + near['r']):
                f.append('V13 спутники: иконка #%s--%s стоит на строке #%s--%s, а спутником не объявлена (with)'
                         % (sc, e['id'], sc, (near['l'] + near['r'])[0]))
    for (sc, tg), fl in sorted(binds.items(), key=lambda x: (x[0][0], x[0][1])):
        sb = [b for x, b in sbs if x['id'] == sc][0]
        node, dom = '%s:%s' % (sc, tg), '%s--%s' % (sc, tg)
        own = []
        for b in sb['beats']:
            for i, x in enumerate(b.get('targets', [])):
                if x != tg:
                    continue
                t = beat_t(ctx, b, i)
                if t is None:
                    continue
                if b['action'] == 'move':
                    own.append((t - F, t + b.get('dur', mo(ctx, 'move_dur')) + 2 * F))
                elif b['action'] == 'emph' and b.get('style') == 'ring':
                    own.append((t - F, t + b.get('dur', mo(ctx, 'emph_dur')) + 2 * F))
                elif b['action'] == 'show' and b.get('anim') == 'pop':
                    own.append((t - F, t + anim_dur(ctx, 'pop') + 2 * F))
        edges = [b[0] if b[0] is not None else -1e9 for b in fl] + [1e9]
        for k, (t0, _, host) in enumerate(fl):
            if host is None:
                continue
            hdom = '%s--%s' % (sc, host)
            seg, segs, missing, wrong = [], [], None, None
            for smp in samples:
                if not (edges[k] <= smp['t'] < edges[k + 1]):
                    continue
                if any(a <= smp['t'] <= b for a, b in own):
                    if seg:
                        segs.append(seg)
                        seg = []
                    continue
                rec = (smp.get('sats') or {}).get(node)
                if rec is None or rec.get('host') != hdom:
                    if opacity_of(smp, dom) > SAT_SEEN and opacity_of(smp, hdom) > SAT_SEEN:
                        if rec is None:
                            missing = missing or smp['t']
                        else:
                            wrong = wrong or (smp['t'], rec.get('host'))
                    continue
                if rec['op'] > SAT_SEEN and rec['hop'] > SAT_SEEN and not rec.get('own'):
                    r = rec['local']
                    seg.append((smp['t'], r[0] + r[2] / 2, r[1] + r[3] / 2))
            if seg:
                segs.append(seg)
            if missing is not None:
                f.append('V13 спутники: #%s — нет промера в системе надписи #%s (t=%.2f с): привязка не дошла до страницы'
                         % (dom, hdom, missing))
            if wrong is not None:
                f.append('V13 спутники: #%s в t=%.2f с привязан к #%s, а по раскадровке — к #%s' % (dom, wrong[0], wrong[1], hdom))
            for sg in segs:
                xs, ys = sorted(p[1] for p in sg), sorted(p[2] for p in sg)
                mx, my = xs[len(xs) // 2], ys[len(ys) // 2]
                worst = max(sg, key=lambda p: math.hypot(p[1] - mx, p[2] - my))
                d = math.hypot(worst[1] - mx, worst[2] - my)
                if d > SAT_TOL:
                    f.append('V13 спутники: #%s уходит от своей надписи #%s на %.1f px в t=%.2f с (допуск %.0f px)'
                             % (dom, hdom, d, worst[0], SAT_TOL))
    return f


def _has_text(ctx, s, sb, el):
    for e in sb.get('elements', []):
        if e['id'] == el:
            return bool(e.get('text'))
    for i, attrs, has_t in markup_els(ctx, s, sb):
        if i == el:
            return has_t
    return False


def v14_level_smooth(ctx):
    """V14 (C30): смена уровня без скачка — в окне каждого бита level вне пауз стыков непрозрачность любого
    держателя текста узла меняется за кадр не больше tokens.json density.max_opacity_step; бит level цели
    с текстом без промера кадров (levelTrace) — тоже провал."""
    f, tr = [], ctx['probe'].get('levelTrace')
    if tr is None:
        return ['V14 смена уровня: в probe.json нет levelTrace — промер кадров уровней не снят']
    step_max = float(cfg_need(ctx, 'tokens', 'density.max_opacity_step'))
    cover = {}
    for x in tr:
        cover.setdefault((x['dom'], x['part']), set()).update(range(x['f0'], x['f0'] + len(x['ops'])))
    for s, sb in storyboards(ctx):
        for b in sb['beats']:
            if b['action'] != 'level':
                continue
            for i, tg in enumerate(b['targets']):
                t0 = beat_t(ctx, b, i)
                if t0 is None or seam_of(ctx, t0):
                    continue
                el, _, part = tg.partition('.')
                key = ('%s--%s' % (s['id'], el), part or None)
                d = b.get('dur', float(mo(ctx, 'level_step')))
                need = set(range(frame_of(ctx, t0), frame_of(ctx, t0 + d) + 1))
                if key not in cover:
                    if part in ('', None) and _has_text(ctx, s, sb, el) or part == 'text':
                        f.append('V14 смена уровня: #%s%s в t=%.2f с — нет промера кадров (levelTrace)'
                                 % (key[0], '.' + part if part else '', t0))
                    continue
                miss = need - cover[key]
                if miss:
                    f.append('V14 смена уровня: #%s%s в t=%.2f с — промер не покрывает %d кадров окна'
                             % (key[0], '.' + part if part else '', t0, len(miss)))
    seen = set()
    for x in tr:
        ops = x['ops']
        for k in range(1, len(ops)):
            t = (x['f0'] + k) / fps(ctx)
            if seam_of(ctx, t) or seam_of(ctx, t - FR(ctx)):
                continue
            jump = max(abs(a - b) for a, b in zip(ops[k], ops[k - 1]))
            if jump > step_max + 1e-9 and (x['dom'], x['part']) not in seen:
                seen.add((x['dom'], x['part']))
                f.append('V14 смена уровня: #%s%s — текст скачет на %.3f за кадр (t=%.2f с, > %.2f)'
                         % (x['dom'], '.' + x['part'] if x['part'] else '', jump, t, step_max))
    return f


# ---------------------------------------------------------------- новые классы дефектов (checklists/defect-classes.md)
def _supports(ctx, smp, it):
    """Опора предмета в кадре: видимый хозяин-надпись (спутник) или видимый элемент с надписью / заливкой /
    линия каркаса, которого рамка предмета касается с зазором SUPPORT_PAD."""
    pad = SUPPORT_PAD * PX(ctx)
    r = it['rect']
    big = [r[0] - pad, r[1] - pad, r[2] + 2 * pad, r[3] + 2 * pad]
    for o in smp['items']:
        if o['id'] == it['id'] or o['opacity'] <= TEXT_SEEN:
            continue
        if not (o.get('segs') or o.get('fills') or o['kind'] == 'frame'):
            continue                  # другой предмет без надписи и заливки — не опора
        if area(big, o['rect']) > 0:
            return True
    return False


def _whole_canvas(ctx, r):
    W, H = canvas(ctx)
    return r[0] <= 0.5 and r[1] <= 0.5 and r[0] + r[2] >= W - 0.5 and r[1] + r[3] >= H - 0.5


def v15_hanging(ctx):
    """V15 (новое, ретро класс 2 «висит в пустоте»): предмет — видимый элемент содержания без надписи
    (иконка, фигура; кроме слоя under и хозяина букв «пером» — его надпись пишет плагин pen) — не дольше HANG_MAX
    подряд без опоры: ни рядом с надписью,
    заливкой или линией каркаса, ни при видимом хозяине-надписи (спутник)."""
    f, decl = [], declared_layers(ctx)
    pen_hosts = {'%s--%s' % (sc, c.get('who')) for sc, _sb, c in _act_cues(ctx, PEN_DO)}     # хозяин букв «пером» — надпись, не предмет
    runs = {}                      # id → [начало, последний t без опоры]
    worst = {}
    for smp in sorted(ctx['probe']['samples'], key=lambda s: s['t']):
        seen_now = set()
        for it in smp['items']:
            if it['kind'] != 'content' or it['opacity'] <= TEXT_SEEN or it.get('segs') or any(norm(x) for x in it['texts']):
                continue
            if decl.get(it['id']) == 'under' or (it.get('layer') or '') == 'under' or it['id'] in pen_hosts:
                continue
            if _whole_canvas(ctx, it['rect']):
                continue                  # во всё полотно — мир сцены (холст), а не предмет: висеть ему негде
            if _supports(ctx, smp, it):
                continue
            seen_now.add(it['id'])
            r = runs.setdefault(it['id'], [smp['t'], smp['t']])
            r[1] = smp['t']
            if r[1] - r[0] > HANG_MAX and it['id'] not in worst:
                worst[it['id']] = (r[0], it['rect'])
        for k in list(runs):
            if k not in seen_now:
                del runs[k]
    for i, (t0, rect) in sorted(worst.items()):
        f.append('V15 без опоры: #%s висит без опоры дольше %.1f с с t=%.2f с (рамка %s): ни надписи, ни заливки, ни линии рядом'
                 % (i, HANG_MAX, t0, [round(v) for v in rect]))
    return f


def bridges(ctx):
    """Мосты между сценами: move to_text / to_el на элемент другой сцены этой сборки —
    [(узел, dom цели, подстрока или None, t, dur)]."""
    out = []
    for s, sb in storyboards(ctx):
        in_film = {x['id'] for x, _ in storyboards(ctx)}
        for b in sb['beats']:
            if b['action'] != 'move':
                continue
            ref = (b.get('to_text') or {}).get('el') or b.get('to_el')
            if not ref or ':' not in ref:
                continue
            dsc, _, did = ref.rpartition(':')
            if dsc == s['id'] or dsc not in in_film:
                continue
            for i, tg in enumerate(b['targets']):
                t = beat_t(ctx, b, i)
                if t is not None:
                    out.append(('%s:%s' % (s['id'], tg), '%s--%s' % (dsc, did), (b.get('to_text') or {}).get('sub'),
                                t, b.get('dur', mo(ctx, 'move_dur'))))
    return out


def v16_twins(ctx):
    """V16 (новое, ретро класс 5 «двойник на шве»): мост (move на элемент или подстроку другой сцены) и его
    цель ни в одном кадре не видны одновременно со сдвигом больше TWIN_TOL: подмена — только кадр-в-кадр."""
    f, seen = [], set()
    pm = {m['node']: m for m in ctx['probe'].get('moves', [])}
    for node, ddom, sub, t0, d in bridges(ctx):
        m = pm.get(node)
        dest = m and m.get('dest')
        for smp in ctx['probe']['samples']:
            a = (smp.get('anchors') or {}).get(node)
            if not a or a['opacity'] <= TWIN_SEEN:
                continue
            it = item_of(smp, ddom)
            if not it or it['opacity'] <= TWIN_SEEN:
                continue
            if sub is None:
                twin, op = it['rect'], it['opacity']
            else:
                if not dest:
                    continue
                cand = [g for g in it.get('segs', []) if g[4] > TWIN_SEEN and area(g[:4], dest) > 0.5 * g[2] * g[3]]
                if not cand:
                    continue
                twin, op = cand[0][:4], cand[0][4]
            off = max(abs(a['rect'][0] - twin[0]), abs(a['rect'][1] - twin[1]))
            if off > TWIN_TOL and (node, ddom) not in seen:
                seen.add((node, ddom))
                f.append('V16 двойник на шве: #%s и его цель #%s%s видны вместе (%.2f и %.2f) со сдвигом %.1f px (t=%.2f с)'
                         % (node.replace(':', '--'), ddom, ' «%s»' % sub if sub else '', a['opacity'], op, off, smp['t']))
    return f


_WORD_RE = re.compile(r'[0-9A-Za-zА-Яа-яЁё]+')


def _stems(text):
    """Значимые слова (≥ 4 букв) → основа: первые max(4, длина − 2) букв, ё = е, нижний регистр."""
    out = []
    for w in _WORD_RE.findall(text.lower().replace('ё', 'е')):
        if len(w) >= 4:
            out.append(w[:max(4, len(w) - 2)])
    return out


def speech_rows(ctx):
    """{n: текст речи} — строки озвучки фильма: манифест / replies фильма с text, иначе rows.json проекта."""
    if 'rows' in ctx:
        return ctx['rows']
    out = {}
    for r in manifest_rows(ctx) or []:
        if r.get('text'):
            out[r['n']] = r['text']
    p = os.path.join(ctx['root'], 'rows.json')
    if os.path.exists(p):
        for r in load_json(p):
            out.setdefault(r['n'], r.get('text', ''))
    return out


def mention_pos(key, words):
    """Первое место в речи, где подряд (через ≤ 2 слова) стоят основы ключа; None — не названо."""
    for i, w in enumerate(words):
        if not w.startswith(key[0]):
            continue
        j, ok = i, True
        for k in key[1:]:
            nxt = [x for x in range(j + 1, min(len(words), j + 4)) if words[x].startswith(k)]
            if not nxt:
                ok = False
                break
            j = nxt[0]
        if ok:
            return i
    return None


def v17_speech_order(ctx):
    """V17 (новое, ретро класс 14 «порядок на экране ≠ порядку в речи»): пункты сцены, которые речь называет
    (две первые значимые основы надписи подряд в тексте реплик сцены), становятся читаемыми (> 0,3) в том же
    порядке, в каком их называет речь. Фильм без речи (все строки немые, silent) — SKIP."""
    if ctx['film'].get('replies') and all(r.get('silent') for r in ctx['film']['replies']):
        return None
    f = []
    rows = speech_rows(ctx)
    appear = {}
    for smp in sorted(ctx['probe']['samples'], key=lambda s: s['t']):
        for it in smp['items']:
            if it['kind'] == 'content' and it['opacity'] > TEXT_SEEN and it['id'] not in appear \
                    and any(g[4] > TEXT_SEEN for g in it.get('segs', [])):
                appear[it['id']] = (smp['t'], ' '.join(norm(x) for x in it['texts']))
    for s in ctx['film']['scenes']:
        nums = [r['n'] for r in s.get('replies', [])] or [r['n'] for r in ctx['film']['replies'] if r.get('scene') == s['id']]
        words = []
        for n in sorted(nums):
            words += _stems(rows.get(n, '') or '')
        named = []
        for dom, (t, text) in appear.items():
            if not dom.startswith(s['id'] + '--'):
                continue
            key = _stems(text)[:2]
            if not key:
                continue
            pos = mention_pos(key, words)
            if pos is not None:
                named.append((pos, t, dom))
        named.sort()
        for k, (pa, ta, da) in enumerate(named):
            for pb, tb, db in named[k + 1:]:
                if pb > pa and tb < ta - ORDER_TOL:
                    f.append('V17 порядок = речь: #%s стал читаемым в t=%.2f с, раньше #%s (t=%.2f с), а речь называет его позже'
                             % (db, tb, da, ta))
    return f


def v18_text_chunks(ctx):
    """V18 (новое, ретро класс 13 «текст > N слов — кусками под голос»): надпись длиннее tokens.json
    density.words_per_chunk слов не становится читаемой скачком: прирост читаемых (> 0,3) слов элемента между
    соседними замерами — не больше N (доля слов ≈ доля читаемых строк). Ловит и первое появление целиком,
    и «одна строка кадром раньше, остальное разом»."""
    f = []
    n_max = int(cfg_need(ctx, 'tokens', 'density.words_per_chunk'))
    smps = sorted(ctx['probe']['samples'], key=lambda s: s['t'])

    def lines_of(it):
        if it['kind'] != 'content' or it['opacity'] <= TEXT_SEEN:
            return 0
        return sum(1 for g in it.get('segs', []) if g[4] > TEXT_SEEN)
    most = {}
    for smp in smps:
        for it in smp['items']:
            most[it['id']] = max(most.get(it['id'], 0), lines_of(it))
    prev, seen = {}, set()
    for smp in smps:
        now = {}
        for it in smp['items']:
            n = lines_of(it)
            if not n:
                continue
            words = sum(len(_WORD_RE.findall(x)) for x in it['texts'])
            now[it['id']] = words * n / most[it['id']]
            jump = now[it['id']] - prev.get(it['id'], 0.0)
            if jump > n_max + 1e-6 and it['id'] not in seen:
                seen.add(it['id'])
                f.append('V18 текст кусками: #%s — %d слов стали читаемы одним скачком в t=%.2f с (больше %d: дели под голос)'
                         % (it['id'], round(jump), smp['t'], n_max))
        prev = now
    return f


GUARD_EXT = ('.py', '.js', '.mjs', '.css', '.html', '.htm', '.json', '.txt', '.md', '.cs', '.svg', '.csv')
GUARD_SKIP_DIRS = {'node_modules', 'out', '__pycache__', 'cache', '.git'}


def guard_patterns(ctx):
    """Запрещённые литералы тематики (engine/video/checks/theme_guard.json) минус project.json theme_allow."""
    d = load_json(os.path.join(HERE, 'checks', 'theme_guard.json'))
    allow = set(ctx['project'].get('theme_allow', []))
    return [(p['name'], re.compile(p['re'], re.I)) for p in d['patterns'] if p['name'] not in allow]


def guard_files(roots):
    for root in roots:
        if os.path.isfile(root):
            yield root
            continue
        for dp, dns, fns in os.walk(root, followlinks=False):
            dns[:] = [x for x in dns if x not in GUARD_SKIP_DIRS
                      and not os.path.islink(os.path.join(dp, x))
                      and not (hasattr(os.path, 'isjunction') and os.path.isjunction(os.path.join(dp, x)))]
            for fn in fns:
                if fn.startswith('.env') and fn != '.env.example':
                    continue                     # значения .env не читаем никогда
                if fn.lower().endswith(GUARD_EXT):
                    yield os.path.join(dp, fn)


def v19_theme_guard(ctx):
    """V19: чистота ШАБЛОНА — в коде движка (engine/**) всегда, а в данных проекта (конфиги,
    раскадровки, разметка, фильмы, тексты) только у демо шаблона (project.json "template_demo": true) нет
    литералов прошлого ролика. Список — engine/video/checks/theme_guard.json; .json проверяется и по тексту
    файла, и по строкам значений после разбора (\\u-коды не прячут литерал). Снять запрет по имени —
    project.json theme_allow. Файлы .env не читаются никогда."""
    f, pats = [], guard_patterns(ctx)
    proj = ctx.get('guard_project', ctx['root'])
    pj = ctx['project'] if proj == ctx['root'] else _guard_pj(proj, ctx['project'])
    roots = ctx.get('guard_roots') or ([ENGINE] + ([proj] if pj.get('template_demo') else []))
    own = os.path.normcase(os.path.abspath(GUARD_LIST))
    seen = set()
    for p in guard_files(roots):
        if os.path.normcase(os.path.abspath(p)) == own:
            continue                     # сам список запретов: его значения — и есть литералы
        try:
            with open(p, encoding='utf-8-sig') as fh:      # BOM (PowerShell 5.1 Out-File) снимается
                txt = fh.read()
        except (UnicodeDecodeError, OSError) as e:
            if p.lower().endswith('.json'):
                f.append('V19 сторож тематики: не разобран JSON: %s (%s) — чистоту значений доказать нельзя'
                         % (p, str(e)[:80]))
            continue
        texts = [(txt, None)]
        if p.lower().endswith('.json'):
            try:
                texts.append(('\n'.join(_json_strings(json.loads(txt))), 'значение JSON'))
            except ValueError as e:
                rel = os.path.relpath(p, os.path.dirname(ENGINE)) if p.startswith(os.path.dirname(ENGINE)) else p
                f.append('V19 сторож тематики: не разобран JSON: %s (%s) — чистоту значений доказать нельзя'
                         % (rel, str(e)[:80]))
        for name, rx in pats:
            if (p, name) in seen:
                continue
            for body, where in texts:
                m = rx.search(body)
                if not m:
                    continue
                seen.add((p, name))
                at = where or 'строка %d' % (body.count('\n', 0, m.start()) + 1)
                rel = os.path.relpath(p, os.path.dirname(ENGINE)) if p.startswith(os.path.dirname(ENGINE)) else p
                f.append('V19 сторож тематики: «%s» в %s, %s («%s»); снять: project.json theme_allow: ["%s"]'
                         % (name, rel, at, m.group(0), name))
                break
    return f


GUARD_LIST = os.path.join(HERE, 'checks', 'theme_guard.json')


def _guard_pj(proj, default):
    p = os.path.join(proj, 'project.json')
    try:
        return load_json(p) if os.path.exists(p) else default
    except ValueError:
        return default


def _json_strings(v):
    """Все строки JSON — ключи и значения, рекурсивно."""
    if isinstance(v, str):
        yield v
    elif isinstance(v, dict):
        for k, x in v.items():
            yield k
            yield from _json_strings(x)
    elif isinstance(v, list):
        for x in v:
            yield from _json_strings(x)


def v20_transitions(ctx):
    """V20 (класс дефектов 15): VANISH — элемент, видимый на 0,5+, пропал за один кадр без движения
    и без подмены (на его месте в следующем кадре нет другого видимого элемента); FLICKER — элемент
    виден → не виден → снова виден быстрее чем за FLICKER_SEC. Кадры подряд — паузы стыков и края событий."""
    f, seen, F = [], set(), FR(ctx)
    smps = sorted(ctx['probe']['samples'], key=lambda s: s['t'])
    in_film = {s['id'] for s in ctx['film']['scenes']}
    away = set()                     # мост в сцену вне этой сборки (--only): подмена — в той сцене, здесь её не видно
    for s, sb in storyboards(ctx):
        for b in sb['beats']:
            ref = (b.get('to_text') or {}).get('el') or b.get('to_el') or ''
            if b['action'] == 'move' and ':' in ref and ref.split(':')[0] not in in_film:
                away |= {'%s--%s' % (s['id'], tg.split('.')[0]) for tg in b['targets']}
    for k in range(1, len(smps)):
        a, b = smps[k - 1], smps[k]
        if abs(b['t'] - a['t'] - F) > 1e-3:
            continue
        prev = smps[k - 2] if k >= 2 and abs(a['t'] - smps[k - 2]['t'] - F) < 1e-3 else None
        nb = {it['id']: it for it in b['items']}
        for it in a['items']:
            if it['kind'] != 'content' or it['opacity'] <= VANISH_SEEN or it['id'] in away:
                continue
            nx = nb.get(it['id'])
            if nx is not None and nx['opacity'] > VISIBLE:
                continue
            if prev is not None:
                pi = item_of(prev, it['id'])
                if pi and max(abs(x - y) for x, y in zip(pi['rect'][:2], it['rect'][:2])) > MOVING_PX:
                    continue             # под движением
            ink = [g[:4] for g in it.get('segs', []) if g[4] > TEXT_SEEN] or [it['rect']]
            total = sum(g[2] * g[3] for g in ink) or 1.0
            cover = 0.0
            for g in ink:
                best = 0.0
                for o in b['items']:
                    if o['id'] == it['id'] or o['opacity'] <= VANISH_SEEN:
                        continue
                    rs = [x[:4] for x in o.get('segs', []) if x[4] > TEXT_SEEN] if it.get('segs') else [o['rect']]
                    best = max([best] + [area(g, r) for r in rs])
                cover += best
            if cover < COVER_SHARE * total and ('v', it['id']) not in seen:
                seen.add(('v', it['id']))
                f.append('V20 переходы: VANISH #%s — был виден на %.2f и пропал за кадр без движения и без подмены (t=%.2f → %.2f с)'
                         % (it['id'], it['opacity'], a['t'], b['t']))
    state = {}                       # id → (t видимого, t невидимого после него)
    for smp in smps:
        ops = {it['id']: it['opacity'] for it in smp['items'] if it['kind'] == 'content'}
        for i in set(ops) | set(state):
            o = ops.get(i, 0.0)
            st = state.get(i)
            if o > TEXT_SEEN:
                if st and st[1] is not None and smp['t'] - st[0] <= FLICKER_SEC and ('f', i) not in seen:
                    seen.add(('f', i))
                    f.append('V20 переходы: FLICKER #%s — виден (t=%.2f с) → не виден (t=%.2f с) → снова виден (t=%.2f с)'
                             % (i, st[0], st[1], smp['t']))
                state[i] = (smp['t'], None)
            elif o <= VISIBLE and st and st[1] is None:
                state[i] = (st[0], smp['t'])
    return f


# ---------------------------------------------------------------- стиль (V21–V24): style_probe.json, styles/_core/probe_style.mjs
# Пороги — tokens.json legibility (проект выбирает), кроме допусков самой проверки:
DET_PIX = 0               # пикселей, которые вправе разойтись у двух промеров одного кадра: ноль — замер (Chrome без GPU)
FLASH_FILM_SEC = 1.0      # окно счёта вспышек, с (WCAG 2.3.1: «в любую секунду»)
_SRGB = [((c / 255.0) / 12.92 if c / 255.0 <= 0.04045 else ((c / 255.0 + 0.055) / 1.055) ** 2.4) for c in range(256)]


def styled(ctx):
    return any(s.get('style') for s in ctx['film']['scenes'])


def style_need(ctx, what):
    """(style_probe или None, строка провала или None). Нет стиля — None, None (SKIP)."""
    if not styled(ctx):
        return None, None
    sp = ctx.get('style_probe')
    if sp is None:
        return None, '%s: у фильма есть стиль, а промера стиля нет (style_probe.json) — пересобери страницу' % what
    return sp, None


def leg(ctx, key):
    return cfg_need(ctx, 'tokens', 'legibility.' + key)


def _lin_lum(img):
    """Изображение → 'F'-карта относительной яркости WCAG (0…1) по линейным каналам sRGB."""
    from PIL import Image
    r, g, b = img.convert('RGB').split()
    lut = [round(v * 65535) for v in _SRGB]
    ch = [c.point(lambda v, lut=lut: lut[v], 'I') for c in (r, g, b)]
    out = Image.new('F', img.size)
    out.putdata([(0.2126 * x + 0.7152 * y + 0.0722 * z) / 65535.0 for x, y, z in zip(*(_pixels(c) for c in ch))])
    return out


def _pixels(im):
    return list(im.get_flattened_data() if hasattr(im, 'get_flattened_data') else im.getdata())


def contrast_of(img, rect):
    """Контраст строки по пикселям кадра img: фон — медиана рамки строки, буквы — 2-й процентиль в сторону от фона."""
    W, H = img.size
    x0, y0 = max(0, int(rect[0])), max(0, int(rect[1]))
    x1, y1 = min(W, int(math.ceil(rect[0] + rect[2]))), min(H, int(math.ceil(rect[1] + rect[3])))
    if x1 - x0 < 3 or y1 - y0 < 3:
        return None
    crop = _lin_lum(img.crop((x0, y0, x1, y1)))
    w, h = crop.size
    px_ = _pixels(crop)
    edge = sorted(px_[:w] + px_[-w:] + [px_[k * w] for k in range(h)] + [px_[k * w + w - 1] for k in range(h)])
    bg = edge[len(edge) // 2]
    s = sorted(px_)
    lo, hi = s[int(0.02 * (len(s) - 1))], s[int(0.98 * (len(s) - 1))]
    ink = lo if abs(bg - lo) >= abs(hi - bg) else hi
    a, b = max(bg, ink), min(bg, ink)
    return (a + 0.05) / (b + 0.05)


def v21_contrast(ctx):
    """V21 (новое, WCAG 1.4.3): текст в стиле читается. По кадрам промера стиля (середина и конец реплик) каждая
    строка надписи, видимая на 1,0 и не закрытая в кадре без стиля, мерится в кадре со стилем — какой бы
    непрозрачности стиль её ни сделал: контраст букв к фону по пикселям ≥ legibility.contrast_min либо
    ≥ contrast_keep × контраст той же строки без стиля (бледная роль бренда — не вина стиля). Строка, которой
    со стилем нет (display: none, пустой текст), — провал."""
    sp, miss = style_need(ctx, 'V21 текст читается')
    if miss:
        return [miss]
    if sp is None:
        return None
    from PIL import Image
    cmin, keep = float(leg(ctx, 'contrast_min')), float(leg(ctx, 'contrast_keep'))
    worst, gone, n = {}, {}, 0
    dim = legibility_except(ctx)             # тусклая вывеска по имени — её мерит V35
    for sh in sp['shots']:
        if not sh.get('style'):
            continue
        la = Image.open(os.path.join(ctx['out_dir'], sh['a'])).convert('RGB')
        lb = Image.open(os.path.join(ctx['out_dir'], sh['bare'])).convert('RGB')
        styled = {(ln['id'], ln['k']): ln for ln in sh['lines']}
        for bl in sh.get('bare_lines', []):
            if bl['o'] < FULL or bl['covered'] or bl['id'] in dim:
                continue
            ln = styled.get((bl['id'], bl['k']))
            if ln is None or ln['o'] <= 0:
                gone.setdefault(bl['id'], (sh['t'], bl['text'], sh['style']))
                continue
            ca, cb = contrast_of(la, ln['rect']), contrast_of(lb, bl['rect'])
            if ca is None or cb is None:
                continue
            n += 1
            if ca < cmin and ca < keep * cb:
                k = bl['id']
                if k not in worst or ca < worst[k][0]:
                    worst[k] = (ca, cb, sh['t'], bl['text'], sh['style'], ln['o'])
    if not n and not gone:
        return ['V21 текст читается: в кадрах промера стиля нет ни одной строки надписи на 1,0 — нечего мерить']
    out = ['V21 текст читается: #%s «%s» в стиле %s — контраст %.2f (без стиля %.2f, непрозрачность со стилем %.2f), нужно ≥ %.1f '
           'или ≥ %.0f %% бренда (t=%.2f с)' % (k, v[3], v[4], v[0], v[1], v[5], cmin, keep * 100, v[2]) for k, v in sorted(worst.items())]
    out += ['V21 текст читается: #%s «%s» в стиле %s — строки нет в кадре (без стиля видна на 1,0, t=%.2f с)' % (k, v[1], v[2], v[0])
            for k, v in sorted(gone.items())]
    return out


COLOR_FILTERS = ('sepia', 'hue-rotate', 'saturate', 'grayscale', 'invert', 'contrast', 'brightness')
SVG_PRIMS_OK = {'feTurbulence', 'feDisplacementMap', 'feGaussianBlur', 'feOffset', 'feMerge', 'feMergeNode', 'feComposite'}


def style_json(ctx, name):
    """style.json стиля так, как его ищет сборка: <проект>/styles/<имя>, иначе engine/video/styles/<имя>."""
    for d in (os.path.join(ctx['root'], 'styles'), os.path.join(HERE, 'styles')):
        p = os.path.join(d, name, 'style.json')
        if os.path.exists(p):
            return load_json(p)
    return None


def _rgb(v):
    """'rgb(…)'/'rgba(…)' → 'rgb(r, g, b)' или None (прозрачный, не цвет)."""
    m = _RGB_RE.match(v or '')
    if not m or (m.group(4) is not None and float(m.group(4)) == 0):
        return None
    return 'rgb(%s, %s, %s)' % m.group(1, 2, 3)


PROP_NAME = {'bg': 'background', 'font': 'font-family', 'weight': 'font-weight', 'style': 'font-style', 'color': 'color',
             'border': 'border'}


def v22_brand(ctx):
    """V22 (catalog/styles.md «Бренд главнее»). Всегда: --c-<роль>
    на странице = tokens.json palette; на содержании и его предках нет перекрашивающих фильтров (sepia,
    hue-rotate, saturate, grayscale, invert, contrast, brightness; в SVG-фильтре — только смещение, шум и
    размытие) и режима смешения.
    Мир (по умолчанию): цвета, заливки и обводки узлов содержания и каркаса — из палитры бренда ∪ decor стиля;
    цвет текста — только роль бренда; шрифт основного текста, жирность и начертание = без стиля; шрифт
    заголовка каркаса — свой или шрифт заголовка стиля (fonts.title), и он загружен.
    Замок (project.json style_brand_lock: true): «только фактура» — каждый цвет, шрифт, жирность и начертание
    узла со стилем = без стиля (таблицы стиля выключены)."""
    sp, miss = style_need(ctx, 'V22 палитра бренда')
    if miss:
        return [miss]
    if sp is None:
        return None
    pal = {k: v.upper() for k, v in ctx['tokens']['palette'].items()}
    brand = {hex_rgb(v) for v in pal.values()}
    lock = bool(ctx['project'].get('style_brand_lock', False))
    fstyles = ctx['film'].get('styles') or {}
    f, seen = [], set()

    def once(key, line):
        if key not in seen:
            seen.add(key)
            f.append(line)
    decor = {}
    for name in fstyles:
        sj = style_json(ctx, name)
        if sj is None:
            once(('sj', name), 'V22 палитра бренда: нет style.json стиля %s ни в <проект>/styles, ни в engine/video/styles' % name)
            continue
        decor[name] = {hex_rgb(v) for v in (sj.get('decor') or {}).values()}
        fam = ((fstyles[name].get('fonts') or {}).get('title'))
        if fam and fam != 'code' and not lock:
            # шрифт заголовка мира обязан стоять на заголовке каркаса (world.css) — и тогда он загружен
            titled = [n for k2, rec in enumerate(sp['palette']) for n in (rec.get('nodes') or {}).values()
                      if n.get('title') and n.get('text') and k2 < len(sp['shots']) and sp['shots'][k2].get('style') == name]
            if titled and not any(n['font'].split(',')[0].strip(' "\'') == fam for n in titled):
                once(('fontuse', name), 'V22 палитра бренда: шрифт заголовка стиля %s (%s) не стоит на заголовке каркаса — '
                     'нужно правило в world.css: #root[data-style="%s"] .fr-title { font-family: var(--%s); }' % (name, fam, name, fam))
            else:
                st = [x['status'] for x in ctx['probe'].get('fonts', []) if x['family'] == fam]
                if not st or any(x != 'loaded' for x in st):
                    once(('font', name), 'V22 палитра бренда: шрифт заголовка стиля %s (%s) не загружен: %s' % (name, fam, st or 'не объявлен'))
    for k, rec in enumerate(sp['palette']):
        sname = (sp['shots'][k].get('style') if k < len(sp['shots']) else None) or ''
        allowed = brand | decor.get(sname, set())
        for role, want in sorted(pal.items()):
            got = (rec['vars'].get(role) or '').strip().upper()
            if got != want:
                once(('var', role), 'V22 палитра бренда: --c-%s на странице %s, в tokens.json %s (t=%.2f с)'
                     % (role, got or '(нет)', want, rec['t']))
        for d in rec['diffs']:
            node = d['node'].split('|')[0]
            if not lock:
                if d['prop'] in ('color', 'bg', 'border'):
                    continue                       # цвета мира проверяются ниже: палитра бренда ∪ decor
                if d['prop'] == 'font' and d.get('title'):
                    if d['styled'].split(',')[0].strip(' "\'') == 'sty-%s-title' % sname:
                        continue
                    once(('tf', node), 'V22 палитра бренда: шрифт заголовка #%s — %s, а не шрифт заголовка стиля %s (t=%.2f с)'
                         % (node, d['styled'], sname, rec['t']))
                    continue
                if not d.get('text'):
                    continue                       # шрифт узла без своего текста ничего не рисует
            once(('d', node, d['prop']), 'V22 палитра бренда: #%s %s со стилем %s, без стиля %s (t=%.2f с)%s'
                 % (node, PROP_NAME.get(d['prop'], d['prop']), d['styled'], d['bare'], rec['t'],
                    ' — замок бренда: только фактура' if lock else ''))
        if not lock:
            for key, n in sorted((rec.get('nodes') or {}).items()):
                node = key.split('|')[0]
                for prop in ('color', 'bg', 'border'):
                    c = _rgb(n.get(prop))
                    if c is None:
                        continue
                    if prop == 'color' and n.get('text') and c not in brand:
                        once(('tc', node), 'V22 палитра бренда: цвет текста #%s %s — не роль палитры бренда (стиль %s, t=%.2f с)'
                             % (node, c, sname, rec['t']))
                    elif c not in allowed:
                        once(('c', node, prop), 'V22 палитра бренда: #%s %s %s — вне палитры бренда и decor стиля %s (t=%.2f с)'
                             % (node, PROP_NAME[prop], c, sname, rec['t']))
        for ov in rec.get('over') or []:           # слой стиля над содержанием перекрашивает то, что под ним
            bad = []
            if ov.get('blend') and ov['blend'] != 'normal':
                bad.append('mix-blend-mode: %s' % ov['blend'])
            if ov.get('backdrop') and ov['backdrop'] != 'none':
                bad.append('backdrop-filter: %s' % ov['backdrop'][:60])
            fc = [c for c in COLOR_FILTERS if re.search(r'\b%s\(' % c, ov.get('filter') or '')]
            if fc:
                bad.append('filter: %s' % ', '.join(fc))
            if bad:
                once(('ov', ov['id']), 'V22 палитра бренда: слой стиля поверх содержания #%s перекрашивает его: %s — '
                     'перекраска мира только под содержанием (слой back)' % (ov['id'], '; '.join(bad)))
        tf = ((fstyles.get(sname) or {}).get('fonts') or {}).get('title')
        if tf == 'code' and not lock and k < len(sp['shots']):
            tit = sp['shots'][k].get('titles') or {}
            for fr in tit.get('frame', []):
                if fr['o'] < FULL:
                    continue
                code = [c for c in tit.get('code', []) if c['scene'] == fr['scene']]
                if not code:
                    once(('ct', fr['id']), 'V22 палитра бренда: заголовок кодом #%s не нарисован (стиль %s, fonts.title.kind code)' % (fr['id'], sname))
                    continue
                c = code[0]
                if norm(c['text'] or '') != norm(fr['text']):
                    once(('ctt', fr['id']), 'V22 палитра бренда: заголовок кодом «%s» ≠ заголовку сцены «%s» (#%s)' % (c['text'], fr['text'], fr['id']))
                r, q = c['rect'], fr['rect']
                if r[0] < q[0] - 2 or r[1] < q[1] - 2 or r[0] + r[2] > q[0] + q[2] + 2 or r[1] + r[3] > q[1] + q[3] + 2:
                    once(('ctr', fr['id']), 'V22 палитра бренда: заголовок кодом за рамкой заголовка #%s: %s вне %s' % (fr['id'], r, q))
        for fl in rec['filters']:
            if fl.get('blend'):
                once(('b', fl['id']), 'V22 палитра бренда: фильтр — #%s смешивается с фоном (mix-blend-mode: %s)' % (fl['id'], fl['blend']))
                continue
            bad = [c for c in COLOR_FILTERS if re.search(r'\b%s\(' % c, fl['filter'])]
            bad += sorted(set(fl['prims']) - SVG_PRIMS_OK)
            if bad:
                once(('f', fl['id']), 'V22 палитра бренда: фильтр на #%s перекрашивает содержание: %s (%s)'
                     % (fl['id'], ', '.join(bad), fl['filter'][:80]))
    return f


def flash_series(ctx, sp):
    """Покадровая яркость клеток сетки legibility.flash_grid: [[яркость клетки…] на кадр]."""
    from PIL import Image
    gx, gy = cfg_need(ctx, 'tokens', 'legibility.flash_grid')
    out = []
    for fr in range(sp['flash']['frames']):
        p = os.path.join(ctx['out_dir'], sp['flash']['pattern'] % fr)
        out.append(_pixels(_lin_lum(Image.open(p)).resize((gx, gy), Image.BOX)))
    return out


def flash_legs(series, delta, dark):
    """Перепады яркости одной клетки (зигзаг с порогом delta): [(кадр конца, от, до)] — только те, у которых
    тёмная сторона < dark. Соседние перепады встречные по построению; вспышка — пара перепадов."""
    legs = []
    if not series:
        return legs
    lo = hi = series[0]
    lo_f = hi_f = 0
    d, piv, ext, ext_f = 0, None, None, 0
    for f, v in enumerate(series):
        if d == 0:
            if v < lo:
                lo, lo_f = v, f
            if v > hi:
                hi, hi_f = v, f
            if v - lo >= delta:
                d, piv, ext, ext_f = 1, lo, v, f
            elif hi - v >= delta:
                d, piv, ext, ext_f = -1, hi, v, f
            continue
        if (d == 1 and v >= ext) or (d == -1 and v <= ext):
            ext, ext_f = v, f
            continue
        if abs(v - ext) >= delta:            # разворот: перепад piv → ext закончен
            if min(piv, ext) < dark:
                legs.append((ext_f, piv, ext))
            piv, d, ext, ext_f = ext, -d, v, f
    if d and min(piv, ext) < dark:
        legs.append((ext_f, piv, ext))
    return legs


def v23_flashes(ctx):
    """V23 (новое, WCAG 2.3.1): вспышек не больше legibility.flash_max_per_sec в любую секунду. Каждый кадр
    фильма (промер стиля, 1/10 размера) → относительная яркость клеток сетки flash_grid; вспышка — пара
    встречных перепадов ≥ flash_delta с тёмной стороной < flash_dark_max."""
    sp, miss = style_need(ctx, 'V23 вспышки')
    if miss:
        return [miss]
    if sp is None:
        return None
    if not sp.get('flash'):
        return ['V23 вспышки: в промере стиля нет покадровой яркости (промер с --skip flash) — пересобери страницу']
    fps_ = fps(ctx)
    ser = flash_series(ctx, sp)
    delta, dark, mx = float(leg(ctx, 'flash_delta')), float(leg(ctx, 'flash_dark_max')), int(leg(ctx, 'flash_max_per_sec'))
    win = int(round(FLASH_FILM_SEC * fps_))
    gx = cfg_need(ctx, 'tokens', 'legibility.flash_grid')[0]
    f, worst = [], None
    for c in range(len(ser[0])):
        legs = flash_legs([row[c] for row in ser], delta, dark)
        ends = [x[0] for x in legs]
        for i in range(len(ends)):
            j = i
            while j + 1 < len(ends) and ends[j + 1] - ends[i] < win:
                j += 1
            flashes = (j - i + 1) // 2
            if flashes > mx and (worst is None or flashes > worst[0]):
                worst = (flashes, c, ends[i])
    if worst:
        fl, c, f0 = worst
        f.append('V23 вспышки: %d в секунду с t=%.2f с в клетке %d×%d (столбец %d, строка %d) — больше %d (WCAG 2.3.1)'
                 % (fl, f0 / fps_, *cfg_need(ctx, 'tokens', 'legibility.flash_grid'), c % gx + 1, c // gx + 1, mx))
    return f


def v24_determinism(ctx):
    """V24: стиль детерминирован — кадр t из первой загрузки страницы
    и тот же кадр после перезагрузки, снятый в обратном порядке после постороннего кадра, совпадают попиксельно
    (допуск DET_PIX). Случайность стиля — только сид от номера кадра и id, не Math.random и не время."""
    sp, miss = style_need(ctx, 'V24 детерминизм стиля')
    if miss:
        return [miss]
    if sp is None:
        return None
    from PIL import Image, ImageChops
    f = []
    for sh in sp['shots']:
        if not sh.get('b'):
            f.append('V24 детерминизм стиля: у кадра t=%.2f с нет второго промера' % sh['t'])
            continue
        a = Image.open(os.path.join(ctx['out_dir'], sh['a'])).convert('RGB')
        b = Image.open(os.path.join(ctx['out_dir'], sh['b'])).convert('RGB')
        d = ImageChops.difference(a, b).convert('L').point(lambda v: 255 if v else 0)
        n = d.histogram()[255]
        if n > DET_PIX:
            box = d.getbbox()
            f.append('V24 детерминизм стиля: кадр t=%.2f с дважды снят по-разному — %d пикселей разошлись, область %s'
                     % (sh['t'], n, list(box) if box else '?'))
    return f


LIMB_POS = ('up', 'down')


def v25_pose(ctx):
    """V25 поза героя (класс дефектов 35 «лишняя часть тела в позе»): при поднятой конечности опущенная той же
    стороны скрыта — иначе в кадре третья рука. Данные — промер DOM, поле limbs: узлы рисунка героя с
    data-limb="<герой>:<сторона>:<up|down>" (StyleCore.limb или атрибут в разметке) и видны ли они в кадре.
    Объявлена поднятая конечность, а кадра с ней в промере нет — провал: условие не проверено (жест ставится на
    якорь бита раскадровки, тогда его момент попадает в промер). Конечностей не размечено — None (SKIP)."""
    f, declared, ups, both, bad = [], {}, set(), set(), set()
    for smp in sorted(ctx['probe']['samples'], key=lambda s: s['t']):
        cur = {}
        for l in smp.get('limbs') or []:
            if not l.get('who') or not l.get('side') or l.get('pos') not in LIMB_POS:
                tag = '%s:%s:%s' % (l.get('who'), l.get('side'), l.get('pos'))
                if tag not in bad:
                    bad.add(tag)
                    f.append('V25 поза: разметка data-limb="%s" (#%s) — нужно "<герой>:<сторона>:<up|down>"' % (tag, l.get('el')))
                continue
            key = (l.get('scene'), l['who'], l['side'])
            declared.setdefault(key, set()).add(l['pos'])
            if l.get('seen'):
                cur.setdefault(key, set()).add(l['pos'])
        for key, pos in cur.items():
            if 'up' in pos:
                ups.add(key)
            if len(pos) == 2 and key not in both:
                both.add(key)
                f.append('V25 поза: %s — у «%s» видны и поднятая, и опущенная конечность стороны %s: в кадре третья рука '
                         '(t=%.2f с); при поднятой опущенную той же стороны скрыть' % (key[0], key[1], key[2], smp['t']))
    if not declared and not bad:
        return None
    for key, pos in sorted(declared.items(), key=lambda kv: tuple(str(x) for x in kv[0])):
        if 'up' in pos and key not in ups:
            f.append('V25 поза: %s — у «%s» объявлена поднятая конечность стороны %s, а кадра с ней в промере нет: условие '
                     'не проверено — поставь бит раскадровки на якорь жеста' % key)
    return f


# ---------------------------------------------------------------- без каркаса, помехи, картинка-кадр, таймер (V26–V29)
START_IMAGE = 'start-image'
CHANGE_MIN = 1.0          # V27: средняя разница яркости (0…255) кадра окна против кадра до окна — помехи видны


def sb_of(ctx, scene):
    for s, sb in storyboards(ctx):
        if s['id'] == scene:
            return sb
    return None


def v26_frameless(ctx):
    """V26: сцена без каркаса (storyboard "frame": false) — в её кадрах не видно ни одного узла
    каркаса (.fr: трекер, линии, футер, голос), кроме наплыва ± frame.seam_half на стыке со сценой с каркасом;
    на странице нет её заголовка и номера; все сцены без каркаса — на странице нет каркаса вовсе. Обратная
    сторона: в сцене с каркасом того же фильма общий каркас не погас (вне того же наплыва хоть один его узел на 1,0)."""
    sbs = storyboards(ctx)
    bare = {s['id'] for s, sb in sbs if sb.get('frame') is False}
    if not bare:
        return None
    f, seen = [], set()
    half = float(cfg_need(ctx, 'project', 'frame.seam_half'))
    sc = ctx['film']['scenes']
    mixed_edges = [b['start'] for a, b in zip(sc, sc[1:])
                   if (a['id'] in bare) != (b['id'] in bare)]
    for smp in ctx['probe']['samples']:
        if smp['scene'] not in bare or any(abs(smp['t'] - e) < half + 1e-6 for e in mixed_edges):
            continue
        for it in smp['items']:
            if it['kind'] == 'frame' and it['opacity'] > VISIBLE and (it['id'], smp['scene']) not in seen:
                seen.add((it['id'], smp['scene']))
                f.append('V26 без каркаса: #%s виден в сцене %s (t=%.2f с, %.2f), а она frame: false'
                         % (it['id'], smp['scene'], smp['t'], it['opacity']))
    dimmed = set()
    for smp in ctx['probe']['samples']:
        if smp['scene'] in bare or smp['scene'] in dimmed or any(abs(smp['t'] - e) < half + 1e-6 for e in mixed_edges):
            continue
        glob = [it['opacity'] for it in smp['items'] if it['kind'] == 'frame' and not it.get('scene')]
        if glob and max(glob) < FULL:
            dimmed.add(smp['scene'])
            f.append('V26 каркас погас: в сцене с каркасом %s общий каркас на %.2f (t=%.2f с) — гаснуть ему можно только в '
                     'сцене frame: false и на её стыке' % (smp['scene'], max(glob), smp['t']))
    p = ctx.get('page')
    page = open(p, encoding='utf-8').read() if p and os.path.exists(p) else ''
    for s in sorted(bare):
        if 'id="title--%s"' % s in page or 'id="num--%s"' % s in page:
            f.append('V26 без каркаса: на странице заголовок или номер сцены %s, а она frame: false' % s)
    if len(bare) == len(sbs) and re.search(r'class="fr[ "]', page):
        f.append('V26 без каркаса: все сцены frame: false, а на странице есть узлы каркаса .fr')
    return f


_IMG_CACHE = {}


def _rgb_cached(path):
    """Кадр промера (RGB) — один раз на путь и время файла: порчи V27 перечитывают сотни кадров."""
    from PIL import Image
    st = os.stat(path)
    key = (path, st.st_mtime_ns, st.st_size)
    if key not in _IMG_CACHE:
        _IMG_CACHE[key] = Image.open(path).convert('RGB')
    return _IMG_CACHE[key]


def _lum_grid_cached(path, gx, gy):
    from PIL import Image
    st = os.stat(path)
    key = ('lum', path, st.st_mtime_ns, st.st_size, gx, gy)
    if key not in _IMG_CACHE:
        _IMG_CACHE[key] = _pixels(_lin_lum(_rgb_cached(path)).resize((gx, gy), Image.BOX))
    return _IMG_CACHE[key]


def v27_glitch(ctx):
    """V27 (WCAG 2.3.1, закон 17): помехи (plugins.glitch) — по кадрам окна ± 0,5 с (промер
    probe_frames.mjs, 1/10 размера): вспышек не больше legibility.flash_max_per_sec в любую секунду (то же правило,
    что V23); помехи видны (кадр окна отличается от кадра до окна); кадр, снятый дважды в разном порядке после
    перезагрузки, совпадает попиксельно (зерно, а не случай)."""
    wins = [(s['id'], sb['plugins']['glitch']) for s, sb in storyboards(ctx) if (sb.get('plugins') or {}).get('glitch')]
    if not wins:
        return None
    pp = ctx.get('plugin_probe')
    if not pp:
        return ['V27 помехи: нет промера помех (plugin_probe.json) — пересобери страницу build.py --page']
    from PIL import Image, ImageChops, ImageStat
    f = []
    fps_ = fps(ctx)
    delta, dark, mx = float(leg(ctx, 'flash_delta')), float(leg(ctx, 'flash_dark_max')), int(leg(ctx, 'flash_max_per_sec'))
    gx, gy = cfg_need(ctx, 'tokens', 'legibility.flash_grid')
    win = int(round(FLASH_FILM_SEC * fps_))
    by_scene = {w['scene']: w for w in pp.get('windows') or []}
    for scene, cfg in wins:
        w = by_scene.get(scene)
        if not w:
            f.append('V27 помехи: в промере нет окна помех сцены %s — пересобери страницу' % scene)
            continue
        paths = [os.path.join(ctx['out_dir'], w['pattern'] % (w['f0'] + k)) for k in range(w['n'])]
        imgs = [_rgb_cached(x) for x in paths]
        ser = [_lum_grid_cached(x, gx, gy) for x in paths]
        worst = None
        for c in range(len(ser[0])):
            ends = [x[0] for x in flash_legs([row[c] for row in ser], delta, dark)]
            for i in range(len(ends)):
                j = i
                while j + 1 < len(ends) and ends[j + 1] - ends[i] < win:
                    j += 1
                n = (j - i + 1) // 2
                if n > mx and (worst is None or n > worst[0]):
                    worst = (n, c, ends[i])
        if worst:
            n, c, k = worst
            f.append('V27 помехи: %d вспышек в секунду с t=%.2f с в клетке %d×%d (столбец %d, строка %d), сцена %s — '
                     'больше %d (WCAG 2.3.1)' % (n, (w['f0'] + k) / fps_, gx, gy, c % gx + 1, c // gx + 1, scene, mx))
        b0 = beat_t(ctx, cfg['from']) if isinstance(cfg.get('from'), dict) else None
        k0 = 0 if b0 is None else max(0, min(w['n'] - 1, frame_of(ctx, b0) - w['f0'] - 1))
        ref = imgs[k0]
        moved = 0.0
        for im in imgs:                        # первый же кадр с заметной разницей — помехи видны
            moved = max(moved, sum(ImageStat.Stat(ImageChops.difference(ref, im)).mean) / 3)
            if moved >= CHANGE_MIN:
                break
        if moved < CHANGE_MIN:
            f.append('V27 помехи: в окне сцены %s кадр не меняется (средняя разница %.2f < %.1f) — помех не видно'
                     % (scene, moved, CHANGE_MIN))
    for d in pp.get('det') or []:
        if not d.get('b'):
            f.append('V27 помехи: у кадра t=%.2f с нет второго промера' % d['t'])
            continue
        a = Image.open(os.path.join(ctx['out_dir'], d['a'])).convert('RGB')
        b = Image.open(os.path.join(ctx['out_dir'], d['b'])).convert('RGB')
        diff = ImageChops.difference(a, b).convert('L').point(lambda v: 255 if v else 0)
        n = diff.histogram()[255]
        if n > DET_PIX:
            f.append('V27 помехи: кадр t=%.2f с дважды снят по-разному — %d пикселей разошлись (помехи не от зерна)'
                     % (d['t'], n))
    if not pp.get('det'):
        f.append('V27 помехи: в промере нет кадров детерминизма')
    return f


def _plugin_item(smp, name, scene):
    for p in (smp or {}).get('plugins') or []:
        if p and p.get('plugin') == name:
            for it in p.get('items', []):
                if it.get('scene') == scene:
                    return it
    return None


def v28_start_image(ctx):
    """V28: сцена с картинкой-кадром (storyboard start_image) в первом кадре — картинка во всё
    полотно на 1,0, без сдвига, поворота и масштаба; поверх неё ничего не видно (ни содержания сцены, ни каркаса);
    помехи ещё не идут. Пиксели первого кадра против PNG — тест рендера (engine/video/tests/test_start_frame.py)."""
    scenes = [(s, sb) for s, sb in storyboards(ctx) if sb.get('start_image')]
    if not scenes:
        return None
    f = []
    W, H = canvas(ctx)
    for s, sb in scenes:
        sc = s['id']
        smp = sample_at(ctx, s['start'])
        if smp is None:
            f.append('V28 стартовый кадр %s: нет промера первого кадра t=%.3f с' % (sc, s['start']))
            continue
        dom = '%s--%s' % (sc, START_IMAGE)
        it = item_of(smp, dom)
        if it is None or it['opacity'] < FULL:
            f.append('V28 стартовый кадр %s: картинка на %.2f, а в первом кадре — 1,0' % (sc, it['opacity'] if it else 0.0))
        elif max(abs(a - b) for a, b in zip(it['rect'], [0, 0, W, H])) > EDGE_TOL or abs(it['scale'] - 1) > 1e-4 or abs(it['rot']) > 1e-3:
            f.append('V28 стартовый кадр %s: картинка не во всё полотно — рамка %s, масштаб %s, поворот %s'
                     % (sc, it['rect'], it['scale'], it['rot']))
        for o in smp['items']:
            if o['id'] != dom and o['opacity'] > VISIBLE and (o['kind'] == 'frame' or (o.get('scene') or '') == sc):
                f.append('V28 стартовый кадр %s: поверх картинки #%s (%.2f) — первый кадр не равен картинке'
                         % (sc, o['id'], o['opacity']))
        g = _plugin_item(smp, 'glitch', sc)
        if g and g.get('power', 0) > 0:
            f.append('V28 стартовый кадр %s: помехи уже идут (сила %.2f) — первый кадр не равен картинке' % (sc, g['power']))
    return f


def _timer_text(sec):
    s = int(math.floor(sec + 1e-6))
    return '%d д %02d:%02d:%02d' % (s // 86400, s % 86400 // 3600, s % 3600 // 60, s % 60)


def _iso(v, what):
    from datetime import datetime
    d = datetime.fromisoformat(str(v))
    if d.tzinfo is None:
        raise SystemExit('project.json %s: время без пояса — %r' % (what, v))
    return d


def _wall_clock(ctx, keys):
    """project.json wall_clock — настенное время ролика: start (когда начинают смотреть, ISO с поясом), lead_sec
    (сколько секунд идёт до первого кадра склейки), event (момент события, к которому считает таймер).
    Нет ключа — отказ с его именем: запасных значений нет."""
    wc = ctx['project'].get('wall_clock') or {}
    for k in keys:
        if wc.get(k) is None:
            raise SystemExit('project.json: нет обязательного поля wall_clock.%s (плагины timer, clock)' % k)
    return wc


def v29_timer(ctx):
    """V29: таймер (plugins.timer) показывает время до события project.json wall_clock.event от момента, когда
    он в кадре: wall_clock.start + wall_clock.lead_sec + films/<f>.json timeline_offset_sec + момент at сцены — в
    момент at и дальше по кадрам (секунды идут вниз по времени фильма); подписи — labels (tokens.json motion.timer
    или сцена). Ожидание считается здесь из конфигов, не из сборки. mode "date" — строка date_text."""
    from datetime import timedelta
    scenes = [(s, sb) for s, sb in storyboards(ctx) if (sb.get('plugins') or {}).get('timer')]
    if not scenes:
        return None
    f = []
    fcfg = (ctx['fdef'].get('plugin_config') or {}).get('timer') or {}
    for s, sb in scenes:
        sc = s['id']
        cfg = dict((ctx['tokens'].get('motion') or {}).get('timer') or {})
        cfg.update(sb['plugins']['timer'])
        cfg.update(fcfg)
        t_at = beat_t(ctx, cfg['at'])
        if t_at is None:
            f.append('V29 таймер %s: момента at нет в этой сборке' % sc)
            continue
        smps = [x for x in ctx['probe']['samples'] if x['t'] >= q(ctx, t_at) - 1e-6 and x['scene'] == sc]
        got = [(x['t'], _plugin_item(x, 'timer', sc)) for x in smps]
        if not got or any(it is None for _, it in got):
            f.append('V29 таймер %s: нет промера таймера в кадрах после at — плагин не дошёл до страницы' % sc)
            continue
        if cfg.get('mode') == 'date':
            bad = [(t, it['text']) for t, it in got if it['text'] != cfg.get('date_text')]
            if bad:
                f.append('V29 таймер %s: в t=%.2f с написано «%s», а ждали «%s»' % (sc, bad[0][0], bad[0][1], cfg.get('date_text')))
            continue
        want_labels = cfg.get('labels')
        if got[0][1].get('labels') != want_labels:
            f.append('V29 таймер %s: подписи %s, а ждали %s' % (sc, got[0][1].get('labels'), want_labels))
        wc = _wall_clock(ctx, ('start', 'lead_sec', 'event'))
        offset = float(ctx['fdef'].get('timeline_offset_sec', 0.0))
        on_screen = _iso(wc['start'], 'wall_clock.start') + timedelta(seconds=float(wc['lead_sec']) + offset + t_at)
        left_at = (_iso(wc['event'], 'wall_clock.event') - on_screen).total_seconds()
        for t, it in got:
            want = _timer_text(left_at - max(0.0, t - t_at))
            if it['text'] != want:
                f.append('V29 таймер %s: в t=%.2f с показывает %s, а по project.json wall_clock (start %s, lead_sec %s, кусок с %.2f с) — %s'
                         % (sc, t, it['text'], wc['start'], wc['lead_sec'], offset, want))
                break
        one = [it['text'] for t, it in got if abs(t - (q(ctx, t_at) + 1.0)) < 0.5 / fps(ctx)]
        if one and one[0] == got[0][1]['text']:
            f.append('V29 таймер %s: секунды не идут — в t=%.2f и через 1 с одно и то же %s' % (sc, got[0][0], one[0]))
    return f


# ---------------------------------------------------------------- часы, действия мира, камера, hide, сторож текста, тусклая вывеска (V30–V35)
CLOCK_FMT = {'HH:MM:SS': '%02d:%02d:%02d', 'HH:MM': '%02d:%02d'}
CAM_TOL = 1.0             # px: рамка мира в кадре после метки камеры против положения из разметки
_CAM_RE = re.compile(r'<\w+\b([^>]*\bclass="[^"]*\bcam-pos\b[^"]*"[^>]*)>')


def _plugin_cfg(ctx, sb, name):
    """Настройки плагина сцены так, как их собирает сборка: tokens.json motion.<имя> ← раскадровка ← plugin_config
    фильма (своим чтением конфигов, без кода сборки)."""
    cfg = dict((ctx['tokens'].get('motion') or {}).get(name) or {})
    cfg.update((sb.get('plugins') or {}).get(name) or {})
    cfg.update((ctx['fdef'].get('plugin_config') or {}).get(name) or {})
    return cfg


def _markup_text(ctx, s, sb):
    if not sb.get('markup'):
        return ''
    p = os.path.join(ctx['scenes_dir'], s['id'], sb['markup'])
    return open(p, encoding='utf-8').read() if os.path.exists(p) else ''


def _markup_bodies(txt):
    """{id: тело} верхних узлов .el разметки (до следующего .el)."""
    ms, out = list(_EL_RE.finditer(txt)), {}
    for k, m in enumerate(ms):
        i = re.search(r'\bid="([a-z0-9-]+)"', m.group(1))
        if i:
            out[i.group(1)] = txt[m.end():ms[k + 1].start() if k + 1 < len(ms) else len(txt)]
    return out


def _plain(html_text):
    """Текст разметки, который может оказаться в кадре: без комментариев, скриптов, стилей и тегов."""
    t = re.sub(r'<!--.*?-->', ' ', html_text, flags=re.S)
    t = re.sub(r'<(script|style)\b.*?</\1>', ' ', t, flags=re.S | re.I)
    t = re.sub(r'<[^>]+>', ' ', t)
    return re.sub(r'\s+', ' ', t.replace('&nbsp;', ' ')).strip()


def _clock_want(ctx, t, fmt):
    from datetime import timedelta
    wc = _wall_clock(ctx, ('start', 'lead_sec'))
    on = _iso(wc['start'], 'wall_clock.start') + timedelta(
        seconds=float(wc['lead_sec']) + float(ctx['fdef'].get('timeline_offset_sec', 0.0)) + t)
    sec = int(math.floor((on - on.replace(hour=0, minute=0, second=0, microsecond=0)).total_seconds() + 1e-6)) % 86400
    v = (sec // 3600, sec % 3600 // 60, sec % 60)
    return CLOCK_FMT[fmt] % (v if fmt == 'HH:MM:SS' else v[:2])


def v30_clock(ctx):
    """V30: настенные часы (plugins.clock) в каждом кадре промера показывают wall_clock.start +
    wall_clock.lead_sec + timeline_offset_sec + t (project.json, films/<f>.json; считает проверка,
    не сборка), секунды вниз и идут; у хозяина нет своих цифр — ни в разметке, ни в кадре (значение не вписано руками)."""
    scenes = [(s, sb) for s, sb in storyboards(ctx) if (sb.get('plugins') or {}).get('clock')]
    if not scenes:
        return None
    f = []
    for s, sb in scenes:
        sc, cfg = s['id'], _plugin_cfg(ctx, sb, 'clock')
        fmt = cfg.get('format')
        if fmt not in CLOCK_FMT:
            f.append('V30 часы %s: формат %r — есть только %s' % (sc, fmt, ', '.join(CLOCK_FMT)))
            continue
        body = _markup_bodies(_markup_text(ctx, s, sb)).get(cfg.get('host'), '')
        if re.search(r'\d', _plain(body)):
            f.append('V30 часы %s: в разметке у хозяина «%s» цифры «%s» — значение вписано руками, а его считает плагин'
                     % (sc, cfg.get('host'), _plain(body)[:40]))
        got = [(x['t'], _plugin_item(x, 'clock', sc)) for x in ctx['probe']['samples'] if x['scene'] == sc]
        got = [(t, it) for t, it in got if it is not None]
        if not got:
            f.append('V30 часы %s: нет промера часов в кадрах сцены — плагин не дошёл до страницы' % sc)
            continue
        own = [(t, it['own']) for t, it in got if re.search(r'\d', it.get('own') or '')]
        if own:
            f.append('V30 часы %s: у хозяина «%s» в кадре свои цифры «%s» (t=%.2f с) — значение вписано руками'
                     % (sc, cfg.get('host'), own[0][1][:40], own[0][0]))
        for t, it in got:
            want = _clock_want(ctx, t, fmt)
            if it['text'] != want:
                wc = _wall_clock(ctx, ('start', 'lead_sec'))
                f.append('V30 часы %s: в t=%.2f с показывают %s, а по project.json wall_clock (start %s, lead_sec %s, кусок с %.2f с) — %s'
                         % (sc, t, it['text'], wc['start'], wc['lead_sec'],
                            float(ctx['fdef'].get('timeline_offset_sec', 0.0)), want))
                break
        if fmt == 'HH:MM:SS':
            t0 = got[0][0]
            later = [it['text'] for t, it in got if t >= t0 + 1.0 - 1e-6]
            if later and later[0] == got[0][1]['text']:
                f.append('V30 часы %s: секунды не идут — в t=%.2f и через 1 с одно и то же %s' % (sc, t0, later[0]))
    return f


def _act_span(m):
    """Длина действия по числам motion.act.<motion> — правило plugins/README.md (act): dur, иначе in + hold + out,
    иначе spinup, roll, min; иначе 0 (мгновенная смена)."""
    if 'dur' in m:
        return float(m['dur'])
    if 'in' in m:
        return float(m['in']) + float(m.get('hold', 0)) + float(m.get('out', 0))
    for k in ('spinup', 'roll', 'min'):
        if k in m:
            return float(m[k])
    return 0.0


def _act_rec(smp, sc, cid):
    it = _plugin_item(smp, 'act', sc)
    if not it:
        return None
    for c in it.get('cues') or []:
        if c['id'] == cid:
            return c
    return None


def _sample_near(ctx, t):
    """Замер кадра t; за краем фильма — последний кадр промера."""
    smp = sample_at(ctx, t)
    if smp is None and t >= ctx['film']['duration'] - FR(ctx):
        smp = max(ctx['probe']['samples'], key=lambda x: x['t'])
    return smp


def v31_act(ctx):
    """V31: каждая метка plugins.act.cues есть в промере — id, время ± 1 кадр (время
    считает проверка из раскадровки), у неё есть исполнитель (who «cam» — движок), и у узла who видно изменение
    за действие (отпечаток до метки ≠ отпечаток после её длины + 2 кадра). motion — имя из tokens.json motion.act."""
    scenes = [(s, sb) for s, sb in storyboards(ctx) if (sb.get('plugins') or {}).get('act')]
    if not scenes:
        return None
    f, F = [], FR(ctx)
    table = (ctx['tokens'].get('motion') or {}).get('act') or {}
    for s, sb in scenes:
        sc = s['id']
        for c in sb['plugins']['act'].get('cues') or []:
            key = '%s:%s' % (sc, c.get('id'))
            m = {}
            if c.get('motion') is not None:
                if not isinstance(table.get(c['motion']), dict):
                    f.append('V31 act %s: motion «%s» нет в tokens.json motion.act' % (key, c['motion']))
                    continue
                m = table[c['motion']]
            t = beat_t(ctx, c['t']) if isinstance(c.get('t'), dict) else None
            if t is None:
                continue
            smp = sample_at(ctx, t)
            rec = _act_rec(smp, sc, c['id']) if smp else None
            if rec is None:
                f.append('V31 act %s: метки нет в промере (t=%.3f с) — плагин act не дошёл до страницы' % (key, t))
                continue
            if abs(rec['t'] - t) > F + 1e-6:
                f.append('V31 act %s: в сборке %.3f с, а по раскадровке %.3f с — больше кадра' % (key, rec['t'], t))
            if not rec.get('exec'):
                f.append('V31 act %s: метка без исполнителя (who «%s», do «%s») — его рисует разметка, стиль или марионетка '
                         '(window.ActExec)' % (key, c['who'], c['do']))
                continue
            span = _act_span(m)
            a, b = _sample_near(ctx, t - F), _sample_near(ctx, t + span + 2 * F)
            ra, rb = (_act_rec(a, sc, c['id']) if a else None), (_act_rec(b, sc, c['id']) if b else None)
            if not ra or not rb or ra.get('sig') is None or rb.get('sig') is None:
                f.append('V31 act %s: нет отпечатка узла «%s» до или после действия — пересобери страницу' % (key, c['who']))
            elif ra['sig'] == rb['sig']:
                f.append('V31 act %s: у «%s» нет видимого изменения за действие %s (t=%.2f…%.2f с)'
                         % (key, c['who'], c['do'], a['t'], b['t']))
    return f


def v32_camera(ctx):
    """V32 (закон 4): камера сцены (метки who «cam») — после каждой метки рамка мира в
    кадре = положение to из разметки (.cam-pos) ± 1 px; парение не больше tokens.json motion.act.cam_drift.pct %
    кадра в любом кадре; обёртки камеры не элементы .el (камера и элемент не делят свойство, закон 2).
    Надписи целиком в кадре при любом положении камеры — V3."""
    scenes = [(s, sb) for s, sb in storyboards(ctx)
              if any(c.get('who') == 'cam' for c in ((sb.get('plugins') or {}).get('act') or {}).get('cues') or [])]
    if not scenes:
        return None
    f, F = [], FR(ctx)
    pct = float(cfg_need(ctx, 'tokens', 'motion.act.cam_drift.pct'))
    table = (ctx['tokens'].get('motion') or {}).get('act') or {}
    page = open(ctx['page'], encoding='utf-8').read() if os.path.exists(ctx['page']) else ''
    for s, sb in scenes:
        sc = s['id']
        if re.search(r'<div class="[^"]*\bcam\b[^"]*\bel\b[^"]*" id="cam--%s"|<div class="[^"]*\bel\b[^"]*\bcam\b[^"]*" id="cam--%s"'
                     % (sc, sc), page):
            f.append('V32 камера %s: обёртка камеры — элемент .el: её двигали бы и биты, и камера (закон 2)' % sc)
        pos = {}
        for m in _CAM_RE.finditer(_markup_text(ctx, s, sb)):
            nm = re.search(r'\bdata-cam="([a-z0-9-]+)"', m.group(1))
            st = re.search(r'\bstyle="([^"]*)"', m.group(1))
            vals = dict(re.findall(r'(left|top|width|height)\s*:\s*(-?[\d.]+)px', st.group(1))) if st else {}
            if nm and len(vals) == 4:
                pos[nm.group(1)] = [float(vals[k]) for k in ('left', 'top', 'width', 'height')]
        cams = [x for x in ctx['probe']['samples'] if x['scene'] == sc]
        got = [(x['t'], (_plugin_item(x, 'act', sc) or {}).get('cam')) for x in cams]
        if not got or any(c is None for _, c in got):
            f.append('V32 камера %s: нет промера камеры в кадрах сцены — пересобери страницу' % sc)
            continue
        worst = max(got, key=lambda tc: tc[1].get('drift') or 0)
        if (worst[1].get('drift') or 0) > pct + 1e-6:
            f.append('V32 камера %s: парение %.2f %% кадра (t=%.2f с) больше tokens.json motion.act.cam_drift.pct %.2f %%'
                     % (sc, worst[1]['drift'], worst[0], pct))
        for c in sb['plugins']['act']['cues']:
            if c.get('who') != 'cam':
                continue
            if c.get('to') not in pos:
                f.append('V32 камера %s: положения «%s» нет в разметке сцены' % (sc, c.get('to')))
                continue
            t = beat_t(ctx, c['t'])
            if t is None:
                continue
            smp = _sample_near(ctx, t + _act_span(table.get(c.get('motion')) or {}) + 2 * F)
            cam = (_plugin_item(smp, 'act', sc) or {}).get('cam') if smp else None
            if not cam:
                f.append('V32 камера %s: нет промера камеры после метки %s' % (sc, c['id']))
                continue
            if max(abs(a - b) for a, b in zip(cam['rect'], pos[c['to']])) > CAM_TOL:
                f.append('V32 камера %s: после метки %s рамка %s, а положение «%s» — %s (t=%.2f с)'
                         % (sc, c['id'], cam['rect'], c['to'], pos[c['to']], smp['t']))
    return f


def hidden_doms(ctx):
    """dom-id элементов, которые фильм скрывает ключом "hide" (своим разбором раскадровок и разметки);
    неизвестные имена — отдельным списком."""
    out, lost = set(), []
    for h in ctx['fdef'].get('hide') or []:
        sc, _, el = h.rpartition(':')
        hit = False
        for s, sb in storyboards(ctx, raw=True):
            if sc and s['id'] != sc:
                continue
            ids = {e['id'] for e in sb.get('elements', [])} | {i for i, _, _ in markup_els(ctx, s, sb)}
            if el in ids:
                out.add('%s--%s' % (s['id'], el))
                hit = True
        if not hit:
            lost.append(h)
    return out, lost


def v33_hide(ctx):
    """V33: элементы из films/<f>.json "hide" не видны ни в одном кадре промера;
    имя — элемент сцены фильма; сборка скрыла ровно их (film.json hidden — не устарела)."""
    if not ctx['fdef'].get('hide'):
        return None
    f = []
    doms, lost = hidden_doms(ctx)
    for h in lost:
        f.append('V33 hide: «%s» нет ни в одной сцене фильма' % h)
    built = set(ctx['film'].get('hidden') or [])
    if built != doms:
        f.append('V33 hide: сборка скрыла %s, а фильм просит %s — пересобери страницу' % (sorted(built), sorted(doms)))
    seen = set()
    for smp in ctx['probe']['samples']:
        for it in smp['items']:
            if it['id'] in doms and it['opacity'] > VISIBLE and it['id'] not in seen:
                seen.add(it['id'])
                f.append('V33 hide: #%s виден в t=%.2f с (%.2f), а фильм его скрывает' % (it['id'], smp['t'], it['opacity']))
    return f


def v34_text_guard(ctx):
    """V34: сторож текста проекта — правила project.json text_guard.rules {name, re,
    scenes?, els?, except?} по тексту кадра (надписи видимых элементов промера) и по разметке сцен фильма (текст без
    тегов, комментариев и скриптов). Строка FAIL называет правило, сцену и где найдено."""
    tg = ctx['project'].get('text_guard')
    if not tg:
        return None
    f, seen = [], set()
    sbs = storyboards(ctx)
    for r in tg.get('rules') or []:
        rx = re.compile(r['re'])
        scope, els = set(r.get('scenes') or [s['id'] for s, _ in sbs]), set(r.get('els') or [])

        def hit(text):
            for ex in r.get('except') or []:
                text = text.replace(ex, ' ')
            m = rx.search(text)
            return m.group(0) if m else None
        for smp in ctx['probe']['samples']:
            for it in smp['items']:
                sc = it.get('scene') or smp['scene']
                if it['opacity'] <= VISIBLE or sc not in scope:
                    continue
                if els and it['id'].split('--', 1)[-1] not in els:
                    continue
                for t in it['texts']:
                    w = hit(t)
                    if w and (r['name'], sc, 'кадр') not in seen:
                        seen.add((r['name'], sc, 'кадр'))
                        f.append('V34 сторож текста [%s]: в кадре сцены %s «%s» (#%s, t=%.2f с)' % (r['name'], sc, w, it['id'], smp['t']))
        for s, sb in sbs:
            if s['id'] not in scope:
                continue
            txt = _markup_text(ctx, s, sb)
            parts = [_plain(b) for i, b in _markup_bodies(txt).items() if not els or i in els]
            parts += [e.get('text', '') for e in sb.get('elements', []) if not els or e['id'] in els]
            if not els:
                parts.append(_plain(txt))
            for p in parts:
                w = hit(p)
                if w and (r['name'], s['id'], 'разметка') not in seen:
                    seen.add((r['name'], s['id'], 'разметка'))
                    f.append('V34 сторож текста [%s]: в разметке сцены %s «%s»' % (r['name'], s['id'], w))
    return f


def v35_dim_sign(ctx):
    """V35: тусклая вывеска из project.json legibility_except (V21 и V9 её не мерят) —
    в каждом кадре промера её непрозрачность не выше max_opacity, видна (> min_visible) не меньше min_visible_sec
    (сумма промежутков между соседними кадрами промера, где она видна в обоих); имя — элемент сцены. Непрозрачность —
    наибольшая из элемента и строк его надписи: моргание буквами внутри элемента тоже меряется."""
    exc = legibility_except(ctx)
    films = {s['id']: (s, sb) for s, sb in storyboards(ctx)}
    mine = {d: e for d, e in exc.items() if d.split('--', 1)[0] in films}
    if not mine:
        return None
    f = []
    for dom, e in sorted(mine.items()):
        sc, el = dom.split('--', 1)
        s, sb = films[sc]
        ids = {x['id'] for x in sb.get('elements', [])} | {i for i, _, _ in markup_els(ctx, s, sb)}
        if el not in ids:
            f.append('V35 исключение «%s:%s»: такого элемента в сцене нет — исключение ни на что не действует' % (sc, el))
            continue
        mx, lo, need = float(e['max_opacity']), float(e['min_visible']), float(e['min_visible_sec'])
        ser = []
        for smp in sorted(ctx['probe']['samples'], key=lambda x: x['t']):
            if smp['scene'] != sc:
                continue
            it = item_of(smp, dom)
            # видимость — элемент и строки его надписи (исполнитель моргает буквами внутри элемента)
            ser.append((smp['t'], max([it['opacity']] + [g[4] for g in it.get('segs') or []]) if it else 0.0))
        top = max(ser, key=lambda x: x[1]) if ser else (0, 0)
        if top[1] > mx + 1e-6:
            f.append('V35 тусклая вывеска #%s: непрозрачность %.2f (t=%.2f с) выше %.2f' % (dom, top[1], top[0], mx))
        seen = sum(b[0] - a[0] for a, b in zip(ser, ser[1:]) if a[1] > lo and b[1] > lo)
        if seen < need - 1e-6:
            f.append('V35 тусклая вывеска #%s: видна %.2f с, а нужно не меньше %.1f с' % (dom, seen, need))
    return f


# ---------------------------------------------------------------- глаз (V36, V37): кадры полосы и области текста
# Пороги — tokens.json density.max_static, density.zones, legibility.pixel (их выбирает проект); здесь — только
# устройство промера:
EYE_SCALE = 1.0           # кадры полосы — в полный размер холста: штрих буквы обязан остаться штрихом
EYE_ZONE_W = 480          # px: к этой ширине уменьшается кадр для разности зон (усреднение гасит дрожь сглаживания)
EYE_INK_TAIL = 0.02       # V37: светлый и тёмный край клетки строки — 98-й и 2-й процентили яркости её пикселей
EYE_MIN_PX = 10           # px кадра полосы: строка ниже или уже этого не мерится (штрих тоньше пикселя)
EYE_TEXT_FILE = 'text.json'
EYE_OFF = 'не мерено — кадры полосы для этой порчи не снимались'


def eye(ctx):
    """Что видит глаз, для V36 и V37: {step, scale, frames: [{t, file, text: [строка, …]}]} — кадры страницы через
    density.zones.step_sec секунд (engine/tools/strip.py frames, полный размер) и строки текста в каждом из них
    (checks/probe_text.mjs): надписи DOM {src: 'dom', id, k, scene, o, covered, text, rect} и области, которые сцена
    объявила сама, {src: 'canvas', id, text, rect, opacity} (window.__textRects, lib/stage.js). Снимается один раз
    на страницу: кэш полосы <out>/<фильм>/strips/_cache/ по отпечатку страницы (stamp.page_print), второй запуск
    Chrome не зовёт.
    Порчи и образцы подменяют кадры и строки в своей копии ctx['eye']; ctx['eye'] = False выключает промер (None)
    — V36 и V37 тогда пишут SKIP «не мерено»: так делают медленные порчи других проверок на копии страницы."""
    if ctx.get('eye') is False:           # медленная порча другой проверки на копии страницы: кадры не снимаются
        return None
    if ctx.get('eye') is None:
        ctx['eye'] = eye_probe(ctx)
    return ctx['eye']


def eye_probe(ctx):
    """Снять кадры и области текста страницы (или взять снятые). Замок Chrome берётся один раз на оба промера и
    только когда снимать есть что: отметка <out>/<фильм>/strips/_cache/eye-<отпечаток страницы>.json называет файлы
    прошлого промера этой же страницы с тем же шагом. «Та же страница» — отпечаток stamp.page_print: index.html,
    film.json и каждый файл assets/ (картинка-кадр или шрифт, заменённые под тем же именем, кадр меняют)."""
    import hashlib
    import tempfile
    for d in (ENGINE, os.path.join(ENGINE, 'tools')):
        if d not in sys.path:
            sys.path.append(d)
    import chrome_lock
    import strip
    film = ctx['film']
    step = float(cfg_need(ctx, 'tokens', 'density.zones.step_sec'))
    if step <= 0:
        raise SystemExit('tokens.json density.zones.step_sec = %s: шаг кадров — положительное число секунд' % step)
    name = str(film['film']).replace('\\', '/').split('/')[0]
    film_fps = float(film['fps'])
    page = stamp.page_print(ctx['out_dir'])
    if page is None:
        raise SystemExit('ОШИБКА: в %s нет собранной страницы (index.html, film.json) — кадры для V36 и V37 снимать не с чего'
                         % ctx['out_dir'])
    sha = hashlib.sha256(json.dumps(page, sort_keys=True).encode('utf-8'))
    cache = os.path.join(str(strip.out_root(ctx['root'])[1]), name, 'strips', '_cache')
    mark = os.path.join(cache, 'eye-%s-%s-%s.json' % (sha.hexdigest()[:20], step, EYE_SCALE))
    got = load_json(mark) if os.path.exists(mark) else None
    if not got or not all(os.path.exists(x) for x in got['frames'] + [got['text']]):
        with chrome_lock.held('check.py V36/V37 кадры и текст %s' % ctx['out_dir']):
            paths = strip.frames(ctx['root'], name, 0.0, float(film['duration']), 1.0 / step, EYE_SCALE, page=ctx['out_dir'])
            text_file = os.path.join(os.path.dirname(paths[0]), EYE_TEXT_FILE)
            if not os.path.exists(text_file):                 # иначе области этой полосы уже сняты
                fd, job_path = tempfile.mkstemp(prefix='eye-job-', suffix='.json')
                tmp_out = text_file + '.part'
                try:
                    with os.fdopen(fd, 'w', encoding='utf-8') as fh:
                        json.dump({'frames': [frame_of(ctx, k * step) for k in range(len(paths))], 'file': tmp_out}, fh)
                    r = subprocess.run(['node', os.path.join(HERE, 'checks', 'probe_text.mjs'), ctx['out_dir'], job_path],
                                       capture_output=True, text=True, encoding='utf-8', errors='replace')
                    if r.returncode != 0 or not os.path.exists(tmp_out):
                        raise SystemExit('ОШИБКА: промер областей текста не удался (probe_text.mjs, код %d): %s'
                                         % (r.returncode, (r.stderr or r.stdout).strip()[-400:]))
                    os.replace(tmp_out, text_file)
                finally:
                    os.remove(job_path)
                    if os.path.exists(tmp_out):
                        os.remove(tmp_out)
        got = {'frames': paths, 'text': text_file}
        with open(mark, 'w', encoding='utf-8') as fh:
            json.dump(got, fh, ensure_ascii=False)
    paths, data = got['frames'], load_json(got['text'])
    if len(data.get('frames') or []) != len(paths):
        raise SystemExit('ОШИБКА: промер областей текста (%s) не сходится с полосой кадров: %d против %d — удали '
                         'папку %s и повтори' % (got['text'], len(data.get('frames') or []), len(paths), cache))
    frames = []
    for k, (p, fr) in enumerate(zip(paths, data['frames'])):
        text = [dict(ln, src='dom') for ln in fr.get('dom') or []]
        if fr.get('canvas_error'):
            text.append({'src': 'canvas', 'error': fr['canvas_error']})
        for ln in fr.get('canvas') or []:
            text.append(dict(ln, src='canvas') if isinstance(ln, dict) else {'src': 'canvas', 'error': 'не объект: %r' % (ln,)})
        frames.append({'t': round(k * step, 4), 'file': p, 'text': text})
    return {'step': step, 'scale': EYE_SCALE, 'frames': frames}


def note(ctx, code, text):
    """Приписка к строке OK проверки: что она не мерила и почему (сцена, где нечего мерить)."""
    ctx.setdefault('_notes', {})[code] = text


def when_t(ctx, w):
    """Секунды фильма для момента раскадровки {reply, at, offset}; None — реплики нет в этой сборке."""
    r = reply_of(ctx, w['reply'])
    if r is None:
        return None
    return r['start'] + float(w['at']) * (r['end'] - r['start']) + float(w.get('offset', 0.0))


def still_spans(ctx):
    """({сцена: [(t0, t1, зачем)]}, [строки провала]) — законные паузы раскадровок: поле still {from, to, why}
    (одна пауза объектом или список). Пауза, у которой конец не позже начала, — провал: она ничего не объявляет."""
    spans, bad = {}, []
    for s, sb in storyboards(ctx, raw=True):
        st = sb.get('still')
        for sp in ([st] if isinstance(st, dict) else st or []):
            t0, t1 = when_t(ctx, sp['from']), when_t(ctx, sp['to'])
            if t0 is None or t1 is None:
                continue
            if t1 <= t0:
                bad.append('V36 живость %s: пауза still «%s» кончается (%.2f с) не позже, чем начинается (%.2f с)'
                           % (s['id'], sp.get('why', ''), t1, t0))
                continue
            spans.setdefault(s['id'], []).append((t0, t1, sp.get('why', '')))
    return spans, bad


def _eye_gray(path):
    """Кадр полосы серым, уменьшенный до EYE_ZONE_W по ширине, — один раз на путь и время файла."""
    from PIL import Image
    st = os.stat(path)
    key = ('gray', path, st.st_mtime_ns, st.st_size)
    if key not in _IMG_CACHE:
        im = Image.open(path).convert('L')
        if im.size[0] > EYE_ZONE_W:
            im = im.resize((EYE_ZONE_W, max(1, int(round(im.size[1] * EYE_ZONE_W / float(im.size[0]))))), Image.BOX)
        _IMG_CACHE[key] = im
    return _IMG_CACHE[key]


def zone_shares(path_a, path_b, gx, gy, delta):
    """Доля пикселей каждой зоны сетки gx×gy (по строкам, слева направо), у которых яркость между двумя кадрами
    сменилась больше чем на delta полной шкалы."""
    from PIL import ImageChops
    key = ('zones', path_a, os.stat(path_a).st_mtime_ns, path_b, os.stat(path_b).st_mtime_ns, gx, gy, delta)
    if key not in _IMG_CACHE:
        a, b = _eye_gray(path_a), _eye_gray(path_b)
        cut = int(math.floor(delta * 255)) + 1
        d = ImageChops.difference(a, b).point(lambda v, cut=cut: 255 if v >= cut else 0)
        w, h = d.size
        out = []
        if d.getbbox() is None:                 # кадры одинаковы — зоны не режем
            out = [0.0] * (gx * gy)
        else:
            for j in range(gy):
                for i in range(gx):
                    box = (i * w // gx, j * h // gy, (i + 1) * w // gx, (j + 1) * h // gy)
                    n = max(1, (box[2] - box[0]) * (box[3] - box[1]))
                    out.append(d.crop(box).histogram()[255] / float(n))
        _IMG_CACHE[key] = out
    return _IMG_CACHE[key]


def v36_need(limit, step):
    """Сколько пар соседних кадров нужно зоне, чтобы V36 могла покраснеть: (пар движения, пар простоя). Слой — зона,
    ехавшая без остановки не меньше limit; заморожен — после этого стоит дольше limit. Сцена, где пар кадров
    меньше суммы, покраснеть не может при любой картинке: её называет строка V36."""
    return int(math.ceil((limit - 1e-6) / step)), int(math.floor((limit + 1e-6) / step)) + 1


def v36_alive_zones(ctx):
    """V36 (новое, закон 8; ретро открытки B): живость по зонам — по кадрам страницы через density.zones.step_sec
    секунд. Кадр режется сеткой density.zones.grid; зона сдвинулась между соседними кадрами, если яркость сменилась
    больше чем на density.zones.delta хотя бы у доли min_share её пикселей. Зона, которая в сцене двигалась без
    остановки не меньше density.max_static секунд, — движущийся слой; после этого ей нельзя стоять внутри сцены
    дольше max_static: слой заморожен. Простой до первого такого движения не считается (зона ещё пуста или ждёт
    своего входа). Законная пауза — поле раскадровки still {from, to, why} — простоем не считается.
    Сцена, где ни одна зона так долго не двигалась (слайд, титр, сцена без героя), — нечего мерить.
    Сцена короче двух порогов (v36_need) покраснеть не может вовсе — строка отчёта называет её и нужную длину."""
    limit = float(cfg_need(ctx, 'tokens', 'density.max_static'))
    gx, gy = [int(v) for v in cfg_need(ctx, 'tokens', 'density.zones.grid')]
    share = float(cfg_need(ctx, 'tokens', 'density.zones.min_share'))
    delta = float(cfg_need(ctx, 'tokens', 'density.zones.delta'))
    ey = eye(ctx)
    if ey is None:
        note(ctx, 'V36', EYE_OFF)
        return None
    step, fr = float(ey['step']), ey['frames']
    spans, f = still_spans(ctx)
    idle, blind, measured = [], [], 0
    need = sum(v36_need(limit, step))
    for s in ctx['film']['scenes']:
        ks = [k for k, x in enumerate(fr) if s['start'] - 1e-6 <= x['t'] < s['end'] - 1e-6]
        pairs = list(zip(ks, ks[1:]))
        if len(pairs) < need:
            blind.append('%s (%.1f с)' % (s['id'], s['end'] - s['start']))
        moves = [zone_shares(fr[a]['file'], fr[b]['file'], gx, gy, delta) for a, b in pairs]
        paused = [any(t0 - 1e-6 <= (fr[a]['t'] + fr[b]['t']) / 2 <= t1 + 1e-6 for t0, t1, _ in spans.get(s['id'], []))
                  for a, b in pairs]
        found = {}
        live = False
        for z in range(gx * gy):
            alive = [m[z] >= share for m in moves]
            run = best = 0
            since = None                         # пара кадров, с которой зона — слой: первое движение не короче порога
            for i, v in enumerate(alive):
                run = run + 1 if v else 0
                best = max(best, run)
                if since is None and run * step >= limit - 1e-6:
                    since = i + 1
            if since is None:
                continue                         # зона так долго не двигалась — не слой
            live = True
            i = since
            while i < len(alive):                # простои: пары кадров подряд без движения и вне объявленной паузы
                if alive[i] or paused[i]:
                    i += 1
                    continue
                j = i
                while j < len(alive) and not alive[j] and not paused[j]:
                    j += 1
                if (j - i) * step > limit + 1e-6:
                    found.setdefault((fr[pairs[i][0]]['t'], fr[pairs[j - 1][1]]['t']), []).append((z, best * step))
                i = j
        if not live:
            if len(pairs) >= need:
                idle.append(s['id'])
            continue
        measured += 1
        for (t0, t1), zs in sorted(found.items()):
            names = ', '.join('%d×%d' % (z % gx + 1, z // gx + 1) for z, _ in zs)
            f.append('V36 живость %s: зона %s (столбец×строка сетки %d×%d) стоит %.1f с, t=%.1f…%.1f с, — дольше '
                     'density.max_static %.1f с, а до того двигалась без остановки %.1f с: слой заморожен? Законная '
                     'пауза — поле раскадровки still {from, to, why}'
                     % (s['id'], names, gx, gy, t1 - t0, t0, t1, limit, max(r for _, r in zs)))
    notes = []
    if blind:
        notes.append('покраснеть не может: %s — сцена короче %.1f с не успеет и двигаться density.max_static %.1f с, и '
                     'простоять дольше' % (', '.join(blind), need * step, limit))
    if idle and (measured or f or blind):
        notes.append('нечего мерить: %s — нет слоя, который движется дольше %.1f с' % (', '.join(idle), limit))
    if notes:
        note(ctx, 'V36', '; '.join(notes))
    if not measured and not f:
        return None
    return f


_Y_LUT = [int(round(v * 255)) for v in _SRGB] * 3


def _hist_level(hist, share):
    """Уровень 0…255, ниже или на котором лежит доля share пикселей гистограммы."""
    need, acc = share * sum(hist), 0
    for v, n in enumerate(hist):
        acc += n
        if acc >= need and n:
            return v
    return 255


def line_cells(img, rect, scale):
    """Контрасты клеток строки по пикселям кадра img: строка (rect в px холста) режется на клетки шириной в свою
    высоту; контраст клетки — WCAG между светлым и тёмным краем её яркости (процентили EYE_INK_TAIL): заливка буквы
    против обводки или фона под ней. None — строка в кадре мельче EYE_MIN_PX (или за кадром)."""
    W, H = img.size
    x0, y0 = max(0, int(math.floor(rect[0] * scale))), max(0, int(math.floor(rect[1] * scale)))
    x1, y1 = min(W, int(math.ceil((rect[0] + rect[2]) * scale))), min(H, int(math.ceil((rect[1] + rect[3]) * scale)))
    w, h = x1 - x0, y1 - y0
    if w < EYE_MIN_PX or h < EYE_MIN_PX:
        return None
    # относительная яркость WCAG: каналы в линейный свет (таблица), затем веса 0,2126 / 0,7152 / 0,0722
    lum = img.crop((x0, y0, x1, y1)).convert('RGB').point(_Y_LUT).convert('L', (0.2126, 0.7152, 0.0722, 0))
    n = max(1, int(round(w / float(h))))
    out = []
    for i in range(n):
        hist = lum.crop((i * w // n, 0, (i + 1) * w // n, h)).histogram()
        lo, hi = _hist_level(hist, EYE_INK_TAIL), _hist_level(hist, 1.0 - EYE_INK_TAIL)
        out.append((hi / 255.0 + 0.05) / (lo / 255.0 + 0.05))
    return out


def kept_contrast(cells, keep):
    """Контраст, который держит доля keep клеток строки: худшие (1 − keep) клеток прощаются."""
    s = sorted(cells)
    return s[min(len(s) - 1, int(math.floor((1.0 - keep) * len(s) + 1e-9)))]


def v37_text_pixels(ctx):
    """V37 (новое, WCAG 1.4.3; ретро открытки B): текст читается на своём фоне — по пикселям, при любом стиле и без
    него. В каждом кадре полосы (через density.zones.step_sec секунд, полный размер) каждая строка, видимая на 1,0:
    надпись DOM (.t содержания и заголовок; не закрытая, не исключение legibility_except — его мерит V35) и область,
    которую сцена объявила для текста на canvas (window.__textRects). Строка режется на клетки шириной в свою
    высоту, контраст клетки — светлый край яркости к тёмному; доля legibility.pixel.keep клеток обязана держать
    контраст ≥ legibility.pixel.contrast_min. Провал называет худший кадр строки и измеренный контраст."""
    cmin = float(cfg_need(ctx, 'tokens', 'legibility.pixel.contrast_min'))
    keep = float(cfg_need(ctx, 'tokens', 'legibility.pixel.keep'))
    ey = eye(ctx)
    if ey is None:
        note(ctx, 'V37', EYE_OFF)
        return None
    scale = float(ey['scale'])
    dim = legibility_except(ctx)
    worst, f, seen, broken = {}, [], set(), set()
    for fr in ey['frames']:
        img = None
        scene = next((s['id'] for s in ctx['film']['scenes'] if s['start'] - 1e-6 <= fr['t'] < s['end'] - 1e-6), None)
        for ln in fr['text']:
            canvas = ln.get('src') == 'canvas'
            if canvas:
                rect = ln.get('rect')
                if ln.get('error') or not (isinstance(rect, list) and len(rect) == 4
                                           and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in rect)):
                    why = ln.get('error') or 'rect = %r' % (rect,)
                    if why not in broken:
                        broken.add(why)
                        f.append('V37 читаемость: window.__textRects(t) в кадре t=%.2f с отдала не область текста (%s) — нужно '
                                 '[{id, rect: [x, y, w, h], text, opacity}], числа в px кадра' % (fr['t'], str(why)[:160]))
                    continue
                if float(ln.get('opacity', 1)) < FULL:
                    continue
                key, sc = ('canvas', str(ln.get('id', '?')), str(ln.get('text', ''))), scene
            else:
                if float(ln.get('o', 0)) < FULL or ln.get('covered') or ln['id'] in dim or not _WORD_RE.search(ln.get('text') or ''):
                    continue
                rect, key, sc = ln['rect'], ('dom', ln['id'], '%s|%s' % (ln.get('k', 0), ln.get('text', ''))), ln.get('scene') or scene
            st = os.stat(fr['file'])
            ck = ('cells', fr['file'], st.st_mtime_ns, st.st_size, tuple(rect), scale)
            if ck not in _IMG_CACHE:
                if img is None:
                    from PIL import Image
                    img = Image.open(fr['file']).convert('RGB')
                _IMG_CACHE[ck] = line_cells(img, rect, scale)
            cells = _IMG_CACHE[ck]
            if cells is None:
                continue
            seen.add(sc)
            c = kept_contrast(cells, keep)
            w = worst.get(key)
            worst[key] = (min(c, w[0]) if w else c, fr['t'] if not w or c < w[0] else w[1], (w[2] if w else 0) + 1, len(cells))
    if not worst and not f:
        return None
    for key, (c, t, n, cells) in sorted(worst.items()):
        if c >= cmin:
            continue
        who = ('canvas «%s»' % key[1]) if key[0] == 'canvas' else '#%s' % key[1]
        text = key[2] if key[0] == 'canvas' else key[2].split('|', 1)[1]
        f.append('V37 читаемость: %s «%s» — контраст букв с пикселями под ними %.2f в кадре t=%.2f с (худший из %d кадров, '
                 'где строка видна на 1,0), нужно ≥ %.1f на доле %.2f строки (legibility.pixel; клеток в строке %d)'
                 % (who, text[:40], c, t, n, cmin, keep, cells))
    blank = [s['id'] for s in ctx['film']['scenes'] if s['id'] not in seen]
    if blank and seen:
        note(ctx, 'V37', 'нечего мерить: %s — текста на 1,0 в кадрах нет' % ', '.join(blank))
    return f


# ---------------------------------------------------------------- V38 буквы «пером», V39 Lottie, V40–V43 набор букв
PEN_DO = 'write'          # действие метки act, которое исполняет плагин pen
PEN_INK_PX = 12           # V38: столько пикселей краски правее пера — сглаживание кромки штриха, не буква
PEN_TIP_TOL = 0.02        # V38: доля ширины строки, на которую открытая часть вправе опережать закон пера
PEN_LEAD_PX = 2.0         # V38: ведущая линия короче этого (px × непрозрачность) — её в кадре нет
PEN_LEAD_STEP = 0.5       # V38: за кадр линия не появляется и не гаснет больше чем на половину своей длины
LOTTIE_FRAME_TOL = 0.02   # V39: кадр анимации в промере против расчёта по шкале, кадров файла
LOTTIE_MIN_FRAMES = 3     # V39: промер застал не меньше трёх разных кадров анимации — иначе мерить нечем


def _power_ease(name):
    """Кривые GSAP none и power<N>.in / out / inOut по их определению (степень N + 1) — как api.powerEase в lib/stage.js."""
    m = re.match(r'^power(\d)\.(in|out|inOut)$', str(name or 'none'))
    if not m:
        return lambda x: x
    n, kind = int(m.group(1)) + 1, m.group(2)
    if kind == 'in':
        return lambda x: x ** n
    if kind == 'out':
        return lambda x: 1 - (1 - x) ** n
    return lambda x: (2 ** (n - 1)) * x ** n if x < 0.5 else 1 - (-2 * x + 2) ** n / 2.0


def _act_cues(ctx, do=None):
    """[(id сцены, раскадровка, метка)] — метки act сцен фильма (do — только с таким действием)."""
    out = []
    for s, sb in storyboards(ctx):
        for c in ((sb.get('plugins') or {}).get('act') or {}).get('cues') or []:
            if do is None or c.get('do') == do:
                out.append((s['id'], sb, c))
    return out


def _plugin_items(smp, name):
    for p in (smp or {}).get('plugins') or []:
        if p and p.get('plugin') == name:
            return p.get('items') or []
    return []


def v38_pen_hidden(ctx):
    """V38 буквы «пером» (плагин pen, метки act do «write»). Закон — из раскадровки и tokens.json motion.act.<motion>,
    не из плагина: строка i начинает в t + i · line_lag · L, L = (until − t) / (1 + (N − 1) · line_lag); в доле p своей
    длины перо прошло ease((p − lead_in) / (contour_until − lead_in)) строки. По промеру плагина (краска слоя букв,
    считанная с холста, перо, ведущая линия):
      строка не видна до пера — пока перо не дошло до строки, краски в ней нет; правее пера краски нет; открытая
        часть строки не опережает закон пера; текст строки на экране — дословно из раскадровки;
      строка написана — после записи в ней есть краска и заливка дошла до конца;
      ведущая линия растёт и гаснет не за кадр — между соседними кадрами её видимая длина не меняется от нуля и до
        нуля больше чем на половину полной длины."""
    cues = _act_cues(ctx, PEN_DO)
    if not cues:
        return None
    table = cfg_need(ctx, 'tokens', 'motion.act')
    samples = sorted(ctx['probe']['samples'], key=lambda s: s['t'])
    F = FR(ctx)
    f = []
    for sc, sb, c in cues:
        key = '%s:%s' % (sc, c.get('id'))
        m = table.get(c.get('motion')) or {}
        lines = c.get('lines') or []
        t0 = beat_t(ctx, c['t']) if isinstance(c.get('t'), dict) else None
        if t0 is None or not lines or any(m.get(k) is None for k in ('ease', 'lead_in', 'contour_until', 'line_lag')):
            f.append('V38 перо %s: у метки нет момента t, строк lines или чисел motion.act.%s — закон записи не посчитать'
                     % (key, c.get('motion')))
            continue
        until = beat_t(ctx, c['until']) if isinstance(c.get('until'), dict) else t0 + float(m.get('dur') or 0)
        span = (until - t0) / (1 + (len(lines) - 1) * float(m['line_lag']))
        li, cu, ease = float(m['lead_in']), float(m['contour_until']), _power_ease(m['ease'])
        recs = [(s['t'], it) for s in samples for it in _plugin_items(s, 'pen') if it.get('scene') == sc and it.get('cue') == c.get('id')]
        if not recs:
            f.append('V38 перо %s: метки нет в промере плагина pen — буквы пишет не он' % key)
            continue
        for i, ln in enumerate(lines):
            lk = '%s строка %d' % (key, i + 1)
            start = t0 + i * float(m['line_lag']) * span
            series = [(t, it['lines'][i]) for t, it in recs if i < len(it.get('lines') or [])]
            if not series:
                f.append('V38 перо %s: строки нет в промере плагина pen' % lk)
                continue
            if series[0][1].get('text') != ln.get('text'):
                f.append('V38 перо %s: на экране «%s», а в раскадровке «%s» — текст фразы ≠ раскадровке'
                         % (lk, series[0][1].get('text'), ln.get('text')))
            early = None
            for t, r in series:
                p = min(1.0, max(0.0, (t - start) / span))
                if p <= li + 1e-9:
                    if r.get('ink', 0) > PEN_INK_PX:
                        early = 't=%.3f с: перо ещё не дошло до строки, а в ней %d px краски' % (t, r['ink'])
                else:
                    e = ease(min(1.0, (p - li) / (cu - li)))
                    rect = r.get('rect') or [0, 0, 1, 1]
                    got = ((r['tip'] - rect[0]) / rect[2]) if r.get('tip') is not None else 0.0
                    if r.get('ink_ahead', 0) > PEN_INK_PX:
                        early = 't=%.3f с: правее пера %d px краски' % (t, r['ink_ahead'])
                    elif got > e + PEN_TIP_TOL:
                        early = 't=%.3f с: открыто %.0f %% строки, а перо по закону прошло %.0f %%' % (t, got * 100, e * 100)
                if early:
                    break
            if early:
                f.append('V38 перо %s: строка видна до пера (%s)' % (lk, early))
            done = [r for t, r in series if t >= start + span + F - 1e-6]
            if not done:
                f.append('V38 перо %s: нет кадра промера после записи (t ≥ %.2f с) — написана ли строка, не видно' % (lk, start + span + F))
            elif done[-1].get('ink', 0) <= PEN_INK_PX or float(done[-1].get('fill') or 0) < 1 - 1e-3:
                f.append('V38 перо %s: строка не написана — после записи в ней %d px краски, заливка дошла до %.0f %%'
                         % (lk, done[-1].get('ink', 0), float(done[-1].get('fill') or 0) * 100))

            def lead(r):
                return float(r.get('lead') or 0) * float(r.get('lead_alpha') if r.get('lead_alpha') is not None else 1)
            if not any(lead(r) > PEN_LEAD_PX for _, r in series):
                f.append('V38 перо %s: ведущей линии нет ни в одном кадре промера — перо не ведёт линию к строке' % lk)
            for (ta, a), (tb, b) in zip(series, series[1:]):
                if tb - ta > 1.5 * F:
                    continue
                full = max(float(a.get('lead_full') or 0), float(b.get('lead_full') or 0), 1.0)
                if lead(a) <= PEN_LEAD_PX and lead(b) > PEN_LEAD_STEP * full:
                    f.append('V38 перо %s: ведущая линия появилась сразу во всю длину (кадр %.3f → %.3f с: 0 → %.0f px из %.0f)'
                             % (lk, ta, tb, lead(b), full))
                    break
                if lead(b) <= PEN_LEAD_PX and lead(a) > PEN_LEAD_STEP * full:
                    f.append('V38 перо %s: ведущая линия погасла одним кадром (кадр %.3f → %.3f с: %.0f px из %.0f → 0)'
                             % (lk, ta, tb, lead(a), full))
                    break
    return f


def _lottie_elements(ctx):
    """[(id сцены, элемент раскадровки kind «lottie»)] фильма."""
    return [(s['id'], e) for s, sb in storyboards(ctx, raw=True) for e in sb.get('elements') or [] if e.get('kind') == 'lottie']


def v39_lottie_time(ctx):
    """V39 Lottie (плагин lottie, элементы kind «lottie») — анимация идёт по времени шкалы, а не загрузки страницы.
    Ожидание — из раскадровки и самого файла анимации: кадр в момент t = (t − at) · speed · fr (at — якорь элемента,
    без него — начало сцены); до at — первый кадр, после конца — последний (loop — по кругу). По промеру плагина —
    кадр, в котором проигрыватель стоит на самом деле: в каждом кадре промера он равен расчёту, анимация загружена.
    Кадры детерминизма (film.json stills, если фильм их снимает) сверяет V41; запросы страницы мимо своих файлов
    (plugin_probe.json requests) — здесь: при рендере по сети ничего не грузится."""
    els = _lottie_elements(ctx)
    if not els:
        return None
    f = []
    samples = sorted(ctx['probe']['samples'], key=lambda s: s['t'])
    for sc, e in els:
        key = '%s:%s' % (sc, e.get('id'))
        path = None
        for base in (ctx['root'], HERE):
            p = os.path.join(base, e.get('src') or '')
            if os.path.isfile(p):
                path = p
                break
        if not path:
            f.append('V39 Lottie %s: нет файла анимации %s' % (key, e.get('src')))
            continue
        data = load_json(path)
        total, rate = float(data['op'] - data['ip']), float(data['fr'])
        sc_rec = [x for x in ctx['film']['scenes'] if x['id'] == sc][0]
        at = beat_t(ctx, e['at']) if isinstance(e.get('at'), dict) else sc_rec['start']
        if at is None:
            f.append('V39 Lottie %s: момент at ссылается на реплику, которой нет в сборке' % key)
            continue
        speed, loop = float(e.get('speed', 1)), bool(e.get('loop'))
        recs = [(s['t'], it) for s in samples for it in _plugin_items(s, 'lottie') if it.get('scene') == sc and it.get('id') == e.get('id')]
        if not recs:
            f.append('V39 Lottie %s: элемента нет в промере плагина lottie — анимацию играет не он' % key)
            continue
        seen, bad = set(), None
        for t, r in recs:
            want = max(0.0, (t - at) * speed * rate)
            want = (want % total) if loop else min(total - 1, want)
            seen.add(int(round(want)))
            if not r.get('loaded'):
                bad = 't=%.3f с: анимация ещё не загружена' % t
            elif abs(float(r.get('frame', -1)) - want) > LOTTIE_FRAME_TOL and not (loop and abs(abs(float(r['frame']) - want) - total) <= LOTTIE_FRAME_TOL):
                bad = 't=%.3f с: показан кадр %.2f, а по шкале — %.2f' % (t, float(r.get('frame', -1)), want)
            if bad:
                break
        if bad:
            f.append('V39 Lottie %s: время анимации не от шкалы (%s) — кадр зависит от загрузки страницы, рендер не повторится' % (key, bad))
        elif len(seen) < LOTTIE_MIN_FRAMES:
            f.append('V39 Lottie %s: промер застал только %d разных кадров анимации — она не играет в своей сцене (at, speed?)'
                     % (key, len(seen)))
    req = (ctx.get('plugin_probe') or {}).get('requests')
    if req:
        f.append('V39 Lottie: при показе страницы были запросы мимо её файлов (%d): %s — при рендере по сети ничего не грузится'
                 % (len(req), ', '.join(str(u) for u in req[:3])))
    return f


def _kit():
    """Проверки набора букв — модуль checks/card_kit.py (V40–V43). Грузится при первом вызове: ему нужны помощники
    этого файла, а этот файл при запуске командой зовётся __main__."""
    import importlib
    sys.modules.setdefault('check', sys.modules[__name__])
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    return importlib.import_module('checks.card_kit')


def v40_card_kit(ctx):
    """V40 набор букв: частицы фразы — из своего предмета, окна-буквы с тенью верхнего слоя, нырок в штрих буквы."""
    return _kit().v40_card_kit(ctx)


def v41_card_frames(ctx):
    """V41 кадры фильма (stills): кадр 0 по правилу фильма, швы без скачка, детерминизм кадров действий."""
    return _kit().v41_card_frames(ctx)


def v42_beatsync(ctx):
    """V42 ключевые события меток — на долях трека (project.json beats)."""
    return _kit().v42_beatsync(ctx)


def v43_card_texts(ctx):
    """V43 текст фразы набора букв на экране — дословно из раскадровки."""
    return _kit().v43_card_texts(ctx)


CHECKS = [('V1', 'длительность и время', v1_duration), ('V2', 'реплики', v2_replies), ('V3', 'полотно', v3_canvas),
          ('V4', 'текст = источник', v4_text), ('V5', 'стык', v5_seams), ('V6', 'раскадровка исполнена', v6_storyboard),
          ('V7', 'шов без пустого кадра', v7_seam_frames), ('V8', 'слои', v8_layers), ('V9', 'итог сцены', v9_scene_end),
          ('V10', 'надписи не наезжают', v10_text_boxes), ('V11', 'шрифт', v11_font), ('V12', 'палитра', v12_palette),
          ('V13', 'спутники едут со своей надписью', v13_satellites), ('V14', 'смена уровня без скачка', v14_level_smooth),
          ('V15', 'предмет без опоры не дольше 1 с', v15_hanging), ('V16', 'двойник на шве', v16_twins),
          ('V17', 'порядок появления = порядок в речи', v17_speech_order), ('V18', 'текст кусками', v18_text_chunks),
          ('V19', 'сторож тематики', v19_theme_guard), ('V20', 'переходы: VANISH / FLICKER', v20_transitions),
          ('V21', 'текст в стиле читается', v21_contrast), ('V22', 'палитра бренда в стиле', v22_brand),
          ('V23', 'вспышки ≤ порога в секунду', v23_flashes), ('V24', 'детерминизм стиля', v24_determinism),
          ('V25', 'поза: при поднятой руке опущенная скрыта', v25_pose),
          ('V26', 'сцена без каркаса', v26_frameless), ('V27', 'помехи: вспышки, видимость, зерно', v27_glitch),
          ('V28', 'стартовый кадр = картинка', v28_start_image), ('V29', 'таймер = настенное время события', v29_timer),
          ('V30', 'часы = настенное время кадра', v30_clock), ('V31', 'действия мира исполнены', v31_act),
          ('V32', 'камера сцены', v32_camera), ('V33', 'скрытые элементы варианта (hide)', v33_hide),
          ('V34', 'сторож текста проекта', v34_text_guard), ('V35', 'тусклая вывеска', v35_dim_sign),
          ('V36', 'живость по зонам', v36_alive_zones), ('V37', 'текст читается по пикселям', v37_text_pixels),
          ('V38', 'буквы пером: строка не видна до пера', v38_pen_hidden), ('V39', 'Lottie: время от шкалы', v39_lottie_time),
          ('V40', 'набор букв: частицы, окна, нырок', v40_card_kit), ('V41', 'кадры фильма: швы и детерминизм', v41_card_frames),
          ('V42', 'набор букв: события на долях трека', v42_beatsync), ('V43', 'набор букв: текст = раскадровка', v43_card_texts)]
SKIP_WHY = {'V25': 'у героев нет размеченных конечностей (data-limb)',
            'V17': 'в фильме нет речи: все строки немые (silent) — порядок появления не с чем сравнивать',
            'V26': 'в фильме нет сцен frame: false', 'V27': 'в фильме нет помех (plugins.glitch)',
            'V28': 'в фильме нет картинки-кадра (start_image)', 'V29': 'в фильме нет таймера (plugins.timer)',
            'V30': 'в фильме нет часов (plugins.clock)', 'V31': 'в фильме нет меток действий (plugins.act)',
            'V32': 'в фильме нет камеры (метки who «cam»)', 'V33': 'у фильма нет ключа hide',
            'V34': 'у проекта нет project.json text_guard', 'V35': 'в фильме нет тусклой вывески (legibility_except)',
            'V36': 'нечего мерить — ни в одной сцене нет слоя, который движется без остановки дольше density.max_static',
            'V37': 'нечего мерить — в кадрах нет ни одной строки текста, видимой на 1,0',
            'V38': 'в фильме нет букв пером (метки act do «write»)',
            'V39': 'в фильме нет анимации Lottie (элементы kind «lottie»)',
            'V40': 'в фильме нет набора букв (метки act gather, windows, dive)',
            'V41': 'у фильма нет ключа stills (кадры швов и детерминизма не снимаются)',
            'V42': 'у проекта нет project.json beats или в фильме нет меток act',
            'V43': 'в фильме нет фраз набора букв (метки act gather со строками)'}


def run(ctx, quiet=False):
    lines, bad = [], 0
    ctx.pop('_notes', None)
    for code, name, fn in CHECKS:
        fails = fn(ctx)
        if fails is None:
            why = 'у фильма нет стиля' if code in ('V21', 'V22', 'V23', 'V24') else SKIP_WHY.get(code, 'не проверено — нет данных (см. CHECKS.md)')
            why = (ctx.get('_notes') or {}).get(code) or why
            lines.append('SKIP %s %s: %s' % (code, name, why))
        elif fails:
            bad += len(fails)
            lines += ['FAIL ' + x for x in fails]
        elif code == 'V1' and ctx.get('page_only'):
            lines.append('OK   V1 длительность и время (--page: длина страницы, видео не смотрим)')
        else:
            extra = (ctx.get('_notes') or {}).get(code)
            lines.append('OK   %s %s%s' % (code, name, ' (%s)' % extra if extra else ''))
    if not quiet:
        print('\n'.join(lines))
    return bad, lines


# ---------------------------------------------------------------- вход
def out_dir_of(root, film, only):
    pj = load_json(os.path.join(root, 'project.json'))
    if not (pj.get('paths') or {}).get('out'):
        raise SystemExit('project.json: нет обязательного поля paths.out')
    out = os.path.join(root, pj['paths']['out'])
    return os.path.join(out, film + ('--' + only if only else ''))


def film_passes(root, film, out_dir):
    """[(стиль, каталог)] фильма с проходами по стилям, если в out_dir нет собственной страницы; иначе []."""
    if os.path.exists(os.path.join(out_dir, 'probe.json')):
        return []
    pj = load_json(os.path.join(root, 'project.json'))
    fp = os.path.join(root, (pj.get('paths') or {}).get('films', 'films'), film + '.json')
    if not os.path.exists(fp):
        return []
    sts = load_json(fp).get('styles') or []
    return [(st, os.path.join(out_dir, st)) for st in sts if os.path.exists(os.path.join(out_dir, st, 'probe.json'))]


def main():
    sys.path.append(ENGINE)
    import PIL  # noqa: F401  проверка без Pillow не идёт (V36, V37 мерят пиксели): нехватка — строкой от deps.run
    import project_root as pr
    root, argv = pr.split_argv(sys.argv[1:])       # --project → MOTION_PROJECT → <шаблон>/project
    root = str(root)

    def opt(name):
        if name in argv:
            i = argv.index(name)
            v = argv[i + 1] if i + 1 < len(argv) else None
            del argv[i:i + 2]
            return v
        return None
    style_given = '--style' in argv
    out_dir, only, style = opt('--out-dir'), opt('--only'), opt('--style')
    flags = {a for a in argv if a.startswith('--')}
    args = [a for a in argv if not a.startswith('--')]
    if not args:
        raise SystemExit(__doc__)
    film = args[0]
    if '--red-init' in flags:
        # калибровка порч своего фильма: checks/red_<фильм>.py с рабочим минимумом (порчи глаза V36, V37)
        sys.path.insert(0, HERE)
        from checks import red_film
        dst, made = red_film.init(root, film)
        print(('порчи фильма заведены: %s\nдальше: check.py %s --red и --samples (страница — build.py %s --page); свои порчи '
               'дописывай в списки этого файла' % (dst, film, film)) if made else
              'порчи фильма уже есть: %s — файл не тронут' % dst)
        sys.exit(0)
    if style_given:
        # --style X: проход фильма в стиле X — каталог <out>/<фильм>/X/ (его кладёт build.py <фильм> --style X)
        if not style or style.startswith('--'):
            raise SystemExit('--style без имени стиля: check.py %s --page --style <стиль> (или check.py %s/<стиль> --page)'
                             % (film, film))
        if '/' in film or '\\' in film:
            raise SystemExit('Стиль назван дважды: %s и --style %s — оставь одно: check.py %s/%s --page'
                             % (film, style, film.replace('\\', '/').split('/')[0], style))
        film = film + '/' + style
        od = os.path.join(out_dir or out_dir_of(root, film.split('/')[0], only), style)
        if not os.path.exists(os.path.join(od, 'probe.json')):
            raise SystemExit('Нет прохода в стиле %s: %s. Сначала build.py %s --page --style %s; проверка — '
                             'check.py %s --page (то же, что --style %s)' % (style, od, film.split('/')[0], style, film, style))
        out_dir = od
    out_dir = out_dir or out_dir_of(root, film, only)
    passes = film_passes(root, film, out_dir)
    if passes and not flags & {'--red', '--red-slow', '--samples'}:
        # фильм с проходами по стилям (films/<f>.json "styles"): каждый проход — свой каталог <out>/<f>/<стиль>/
        total = 0
        for st, od in passes:
            print('== стиль %s: %s' % (st, od))
            ctx = make_ctx(root, od, page_only='--page' in flags)
            bad, _ = run(ctx)
            total += bad
        print('итог: %s' % ('зелёный (%d проходов)' % len(passes) if not total else 'КРАСНЫЙ, провалов %d' % total))
        sys.exit(1 if total else 0)
    if not os.path.exists(os.path.join(out_dir, 'probe.json')) and not passes:
        raise SystemExit('Нет %s: сначала build.py %s%s --page' % (os.path.join(out_dir, 'probe.json'), film,
                                                                  ' --only ' + only if only else ''))
    filt = args[1] if len(args) > 1 else None
    if flags & {'--red', '--red-slow', '--samples'}:
        sys.path.insert(0, HERE)
        import importlib
        # порчи калиброваны на свой фильм: checks/red_<фильм>.py; у демо — red_demo.py; у фильма без своего файла —
        # рабочий минимум, годный для любого фильма (red_film.py: порчи глаза V36, V37; свой файл заводит --red-init)
        base = film.split('/')[0].split('\\')[0]
        mod = ('red_' + base if os.path.exists(os.path.join(HERE, 'checks', 'red_%s.py' % base))
               else 'red_demo' if base == 'demo' else 'red_film')
        if mod == 'red_film':
            print('у фильма %s нет своих порч (checks/red_%s.py) — иду по общему минимуму checks/red_film.py; '
                  'свой файл заводит check.py %s --red-init' % (base, base, base))
        red_demo = importlib.import_module('checks.' + mod)
        code = 0
        parts = film.replace('\\', '/').split('/')
        if len(parts) > 1 and base != 'styles' and flags & {'--red', '--samples'}:
            # проход фильма в стиле (<фильм>/<стиль> или --style): порчи «стиль на фильме роняет контраст подписи»
            rs = importlib.import_module('checks.red_styles')
            if '--samples' in flags:
                code |= rs.samples_film(root, out_dir, film, only, filt)
            if '--red' in flags:
                code |= rs.red_film(root, out_dir, film, only, filt)
            sys.exit(code)
        if '--samples' in flags:
            code |= red_demo.samples(root, out_dir, film, only, filt)
        if '--red' in flags:
            code |= red_demo.red_fast(root, out_dir, film, only, filt)
        if '--red-slow' in flags:
            code |= red_demo.red_slow(root, out_dir, film, only, filt)
        sys.exit(code)
    ctx = make_ctx(root, out_dir, page_only='--page' in flags)
    bad, _ = run(ctx)
    print('итог: %s' % ('зелёный' if not bad else 'КРАСНЫЙ, провалов %d' % bad))
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    sys.path.append(ENGINE)
    import deps      # нехватка пакета или программы, истёкшее ожидание замка Chrome — строкой и кодом 2, не трассировкой
    sys.exit(deps.run(main))
