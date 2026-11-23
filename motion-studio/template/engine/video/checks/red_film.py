# -*- coding: utf-8 -*-
"""Порчи и образцы проверок глаза (V36 живость по зонам, V37 читаемость по пикселям), годные для ЛЮБОГО фильма, —
рабочий минимум калибровки своего фильма.

    python engine/video/check.py <фильм> --red-init      завести engine/video/checks/red_<фильм>.py (этот минимум + место для своих)
    python engine/video/check.py <фильм> --red           порчи: каждая обязана покраснеть своей строкой
    python engine/video/check.py <фильм> --samples       образцы: законные варианты, обязаны пройти молча

Порчи не знают ни сцен, ни элементов фильма: они рисуют кодом поверх его же кадров (копии во временной папке,
поставка не трогается) — слой, который двигался и замер; фразу «золото на закате» (светлые буквы на светлом
тёплом фоне) в области надписи DOM и в области, объявленной для canvas; образцы — та же фраза с тёмной обводкой
вплотную к светлой заливке и замерший слой с паузой, объявленной в раскадровке (still). Картинок здесь нет.

Пороги — числа проекта, порча их не трогает. «Слой заморожен» строится только в сцене, которая вмещает и движение
density.max_static, и простой дольше него (C.v36_need: при 6,0 с и кадрах через 0,5 с — сцена длиннее 12,5 с). Нет
такой сцены — V36 в фильме слепа: порча даёт MISS с длиной сцены и порогом (Unfit, checks/redrun.py), образец паузы —
SKIP. Что с этим делать, решает проект: длиннее сцена, меньше порог или порча убрана из списка своего файла — но не
порог, уменьшенный на время порчи.

Свои порчи фильма (правка probe.json / film.json в памяти, копии сцен) — в red_<фильм>.py по образцу red_demo.py:
кортеж (имя, порча(ctx, tmp), подстрока строки FAIL); образец — (имя, правка(ctx, tmp)).
"""
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # engine/video
sys.path.insert(0, HERE)
import check as C      # noqa: E402
from checks import redrun            # noqa: E402  прогон порч — один на все файлы порч
from checks.redrun import Unfit      # noqa: E402  порча не строится: проверка на этом фильме слепа

SUNSET = ((112, 52, 92), (226, 120, 70), (250, 190, 96))     # закат сверху вниз: слива → терракота → шафран
GOLD = (255, 214, 120)         # золото букв: на шафране заката его почти не видно
CREAM = (255, 244, 214)        # светлая заливка принятой обводки
DARK = (44, 22, 40)            # тёмная обводка вплотную к заливке
LAYER_BG, LAYER_INK = (236, 232, 224), (52, 70, 120)     # «слой»: плашка на зону и предмет, который по ней едет
PHRASE = 'Тёплый вечер у окна'
PHRASE_ID = 'eye-phrase'


# ---------------------------------------------------------------- рисование кодом
def _font(px):
    from PIL import ImageFont
    p = os.path.join(HERE, 'assets', 'fonts', 'LiberationSansNarrow-Bold.ttf')
    try:
        return ImageFont.truetype(p, px)
    except OSError:
        return ImageFont.load_default(size=px)


def sunset(size):
    """Закатный фон кодом: вертикальный градиент слива → терракота → шафран."""
    from PIL import Image
    w, h = size
    col = Image.new('RGB', (1, max(2, h)))
    px = []
    for y in range(col.size[1]):
        p = y / float(col.size[1] - 1) * (len(SUNSET) - 1)
        i = min(len(SUNSET) - 2, int(p))
        a, b, k = SUNSET[i], SUNSET[i + 1], p - min(len(SUNSET) - 2, int(p))
        px.append(tuple(int(round(a[c] + (b[c] - a[c]) * k)) for c in range(3)))
    col.putdata(px)
    return col.resize((w, h))


def paint_phrase(im, box, text, fill, stroke=None, lower=True):
    """Закат в рамке box (px кадра) и фраза на нём; возвращает плотную рамку нарисованной строки (px кадра).
    lower — буквы в нижней, светлой части заката (золото там тонет); обводка stroke — вплотную к заливке."""
    from PIL import ImageDraw
    x0, y0, x1, y1 = [int(round(v)) for v in box]
    im.paste(sunset((x1 - x0, y1 - y0)), (x0, y0))
    dr = ImageDraw.Draw(im)
    px = max(12, int((y1 - y0) * 0.32))
    sw = max(2, px // 9) if stroke else 0
    font = _font(px)
    while px > 12 and dr.textbbox((0, 0), text, font=font, stroke_width=sw)[2] > (x1 - x0) * 0.9:
        px -= 2
        font = _font(px)
    bb = dr.textbbox((0, 0), text, font=font, stroke_width=sw)
    tx = x0 + (x1 - x0 - (bb[2] - bb[0])) // 2 - bb[0]
    ty = (y1 - (bb[3] - bb[1]) - int((y1 - y0) * 0.06) - bb[1]) if lower else (y0 + int((y1 - y0) * 0.06) - bb[1])
    dr.text((tx, ty), text, font=font, fill=fill, stroke_width=sw, stroke_fill=stroke)
    return dr.textbbox((tx, ty), text, font=font, stroke_width=sw)


def _save(im, tmp, fr, tag):
    p = os.path.join(tmp, '%s_%s' % (tag, os.path.basename(fr['file'])))
    im.save(p, compress_level=1)
    fr['file'] = p


def _open(fr):
    from PIL import Image
    return Image.open(fr['file']).convert('RGB')


def _cover(fr, box, scale, keep=None):
    """Нарисованное закрыло всё, что стояло в рамке box (px кадра): строки текста под ним больше не видны — как у
    настоящего слоя поверх надписи (промер пометил бы их covered). keep — строка, которую порча красит сама."""
    x0, y0, x1, y1 = [v / scale for v in box]
    for ln in fr['text']:
        r = ln.get('rect')
        if ln is keep or not isinstance(r, list) or len(r) != 4:
            continue
        if r[0] < x1 and r[0] + r[2] > x0 and r[1] < y1 and r[1] + r[3] > y0:
            if ln.get('src') == 'canvas':
                ln['opacity'] = 0
            else:
                ln['covered'] = True


# ---------------------------------------------------------------- V36: слой заморожен
def _scene_frames(ctx, ey, s):
    return [k for k, fr in enumerate(ey['frames']) if s['start'] - 1e-6 <= fr['t'] < s['end'] - 1e-6]


def _layer(ctx, tmp, frozen=True):
    """Слой в левой верхней зоне самой длинной сцены: плашка на всю зону и предмет, который едет по ней
    density.max_static без остановки, а потом (frozen) стоит дольше max_static. Порог — число проекта, порча его не
    трогает: в фильме, где ни одна сцена не вмещает и движение, и простой (C.v36_need), V36 покраснеть не может —
    Unfit с длиной сцены и порогом (прогон пишет MISS). → (сцена, время остановки, время последнего кадра сцены)."""
    from PIL import ImageDraw
    ey = C.eye(ctx)
    step = float(ey['step'])
    s = max(ctx['film']['scenes'], key=lambda x: len(_scene_frames(ctx, ey, x)))
    ks = _scene_frames(ctx, ey, s)
    pairs = len(ks) - 1
    limit = float(C.cfg_need(ctx, 'tokens', 'density.max_static'))
    move, stand = C.v36_need(limit, step)              # пар кадров движения и простоя, с которых V36 краснеет
    if frozen and pairs < move + stand:
        raise Unfit('ни одна сцена не может покраснеть: самая длинная %s — %.1f с (%d пар кадров через %.1f с), а при '
                    'density.max_static %.1f с зоне нужно ехать %d пар и стоять %d — сцена длиннее %.1f с. V36 в этом '
                    'фильме слепа: порог порча не меняет'
                    % (s['id'], s['end'] - s['start'], max(0, pairs), step, limit, move, stand, (move + stand) * step))
    if pairs < move:
        raise Unfit('самая длинная сцена %s — %.1f с: слой, который едет всю сцену, не наберёт density.max_static %.1f с '
                    'движения — V36 его слоем не считает' % (s['id'], s['end'] - s['start'], limit))
    gx, gy = C.cfg_need(ctx, 'tokens', 'density.zones.grid')
    for n, k in enumerate(ks):
        fr = ey['frames'][k]
        im = _open(fr)
        zw, zh = im.size[0] / float(gx), im.size[1] / float(gy)
        dr = ImageDraw.Draw(im)
        dr.rectangle([0, 0, int(zw) - 1, int(zh) - 1], fill=LAYER_BG)
        r = zh * 0.22
        pos = min(n, move) if frozen else n
        cx = zw * 0.2 + (zw * 0.6) * ((pos * 0.07) % 1.0)
        dr.ellipse([cx - r, zh / 2 - r, cx + r, zh / 2 + r], fill=LAYER_INK)
        _save(im, tmp, fr, 'layer')
        _cover(fr, (0, 0, zw, zh), float(ey['scale']))
    return s, ey['frames'][ks[move]]['t'], ey['frames'][ks[-1]]['t']


def m_layer_frozen(ctx, tmp):
    """Слой заморожен: зона двигалась без остановки дольше max_static и встала дольше max_static."""
    _layer(ctx, tmp, frozen=True)


def expect_layer_frozen(ctx):
    ey = C.eye(ctx)
    s = max(ctx['film']['scenes'], key=lambda x: len(_scene_frames(ctx, ey, x)))
    return 'V36 живость %s: зона 1×1' % s['id']


def _anchor(ctx, s, t):
    """Момент t сцены якорем раскадровки {reply, at, offset}; None — у сцены нет реплики рядом (сдвиг больше 2 с)."""
    best = None
    for r in ctx['film']['replies']:
        if not (s['start'] - 1e-6 <= r['start'] < s['end']):
            continue
        at = min(1.0, max(0.0, (t - r['start']) / max(1e-6, r['end'] - r['start'])))
        off = t - (r['start'] + at * (r['end'] - r['start']))
        if best is None or abs(off) < abs(best[2]):
            best = (r['n'], at, off)
    if best is None or abs(best[2]) > 2.0:
        return None
    return {'reply': best[0], 'at': round(best[1], 4), 'offset': round(best[2], 3)}


def s_layer_still(ctx, tmp):
    """Тот же замерший слой, но пауза объявлена в раскадровке (still): законный стоп-кадр — молча."""
    s, t_stop, t_end = _layer(ctx, tmp, frozen=True)
    a, b = _anchor(ctx, s, t_stop), _anchor(ctx, s, t_end)
    if a is None or b is None:
        _layer(ctx, tmp, frozen=False)                 # у сцены нет реплик — паузу якорем не объявить: слой просто едет
        return
    sd = os.path.join(tmp, 'scenes')
    shutil.copytree(ctx['scenes_dir'], sd)
    ctx['scenes_dir'] = sd
    p = os.path.join(sd, s['id'], 'storyboard.json')
    sb = C.load_json(p)
    sb['still'] = {'from': a, 'to': b, 'why': 'образец: стоп-кадр по замыслу'}
    with open(p, 'w', encoding='utf-8') as fh:
        json.dump(sb, fh, ensure_ascii=False, indent=1)


def s_layer_moving(ctx, tmp):
    """Слой едет всю сцену без остановки — живой, молча."""
    _layer(ctx, tmp, frozen=False)


# ---------------------------------------------------------------- V37: золото на закате
def _dom_line(ctx, ident=None):
    """(кадр, строка) — первая строка надписи DOM, которую V37 мерит (на 1,0, не закрыта, с буквами)."""
    ey = C.eye(ctx)
    sc = float(ey['scale'])
    for fr in ey['frames']:
        for ln in fr['text']:
            if ln.get('src') != 'dom' or ln.get('covered') or float(ln.get('o', 0)) < C.FULL:
                continue
            if ident and ln['id'] != ident:
                continue
            if ln['rect'][3] * sc < 2 * C.EYE_MIN_PX or ln['rect'][2] < 3 * ln['rect'][3] or not C._WORD_RE.search(ln.get('text') or ''):
                continue
            return fr, ln
    return None, None


def m_gold_dom(ctx, tmp, ident=None):
    """Золото на закате, DOM: под строкой надписи — светлый закат, буквы — золото (светлое на светлом)."""
    fr, ln = _dom_line(ctx, ident)
    if ln is None:
        raise SystemExit('порча «золото на закате, DOM»: в кадрах фильма нет строки надписи на 1,0 — у фильма без '
                         'текста DOM эту порчу убери из RED_FAST')
    sc = float(C.eye(ctx)['scale'])
    x, y, w, h = [v * sc for v in ln['rect']]
    im = _open(fr)
    box = (max(0, x - h), max(0, y - 2.2 * h), min(im.size[0], x + w + h), min(im.size[1], y + h))
    paint_phrase(im, box, 'ЗОЛОТО НА ЗАКАТЕ', GOLD)      # буквы — в нижней трети заката, то есть в рамке строки
    _save(im, tmp, fr, 'gold')
    _cover(fr, box, sc, keep=ln)


def expect_gold_dom(ctx, ident=None):
    _, ln = _dom_line(ctx, ident)
    return 'V37 читаемость: #%s' % (ln['id'] if ln else '?')


def _canvas_phrase(ctx, tmp, fill, stroke=None):
    """Фраза на закате в середине кадра самой длинной сцены и её область, объявленная как у canvas-сцены."""
    ey = C.eye(ctx)
    sc = float(ey['scale'])
    s = max(ctx['film']['scenes'], key=lambda x: len(_scene_frames(ctx, ey, x)))
    ks = _scene_frames(ctx, ey, s) or [0]
    fr = ey['frames'][ks[len(ks) // 2]]
    im = _open(fr)
    W, H = im.size
    box = (W * 0.1, H * 0.3, W * 0.9, H * 0.75)
    bb = paint_phrase(im, box, PHRASE, fill, stroke)
    _save(im, tmp, fr, 'phrase')
    _cover(fr, box, sc)
    fr['text'].append({'src': 'canvas', 'id': PHRASE_ID, 'text': PHRASE, 'opacity': 1,
                       'rect': [bb[0] / sc, bb[1] / sc, (bb[2] - bb[0]) / sc, (bb[3] - bb[1]) / sc]})


def m_gold_canvas(ctx, tmp):
    """Золото на закате, canvas: область объявлена сценой (window.__textRects), буквы — золото на шафране."""
    _canvas_phrase(ctx, tmp, GOLD)


def s_outline_canvas(ctx, tmp):
    """Принятая обводка: светлая заливка, сразу тёмная обводка, на том же закате — читается, молча."""
    _canvas_phrase(ctx, tmp, CREAM, DARK)


# (имя, порча, подстрока строки FAIL или функция ctx → подстрока)
RED_FAST = [
    ('слой заморожен', m_layer_frozen, expect_layer_frozen),
    ('золото на закате: надпись DOM', m_gold_dom, expect_gold_dom),
    ('золото на закате: текст на canvas', m_gold_canvas, 'V37 читаемость: canvas «%s»' % PHRASE_ID),
]
SAMPLES = [
    ('замерший слой с объявленной паузой (still)', s_layer_still),
    ('слой едет без остановки', s_layer_moving),
    ('светлая заливка с тёмной обводкой на закате', s_outline_canvas),
]


# ---------------------------------------------------------------- прогон: checks/redrun.py (один на все файлы порч)
def _has_dom_text(base):
    return _dom_line(base)[1] is not None


def _skip(row, base):
    if row[1] is m_gold_dom and not _has_dom_text(base):
        return 'в кадрах фильма нет надписей DOM на 1,0'
    return None


def run_red(root, out_dir, film, only, filt=None, red=None):
    base = redrun.base(root, out_dir)
    if base is None:
        return 1
    return redrun.fast(RED_FAST if red is None else red, lambda row: base, filt, skip=_skip, width=44)


def run_samples(root, out_dir, film, only, filt=None, samples=None):
    base = redrun.base(root, out_dir)
    if base is None:
        return 1
    return redrun.samples(SAMPLES if samples is None else samples, base, filt, width=44)


def red_fast(root, out_dir, film, only, filt=None):
    return run_red(root, out_dir, film, only, filt)


def samples(root, out_dir, film, only, filt=None):
    return run_samples(root, out_dir, film, only, filt)


def red_slow(root, out_dir, film, only, filt=None):
    print('медленных порч у фильма %s нет: свои (копия проекта, правка сцены, пересборка) — в checks/red_%s.py '
          'по образцу RED_SLOW в red_demo.py' % (film, film))
    return 0


# ---------------------------------------------------------------- файл порч своего фильма
RED_FILE = '''# -*- coding: utf-8 -*-
"""Порчи и образцы фильма «%(film)s» (завёл check.py %(film)s --red-init).

    python engine/video/check.py %(film)s --red | --samples | --red-slow

Рабочий минимум — порчи глаза, годные для любого фильма (checks/red_film.py): слой заморожен (V36), золото на
закате в надписи DOM и в тексте на canvas (V37); образцы — пауза по раскадровке и обводка на закате. Порча «слой
заморожен» идёт с порогом проекта: MISS «ни одна сцена не может покраснеть» значит, что V36 в этом фильме слепа
(сцены короче двух порогов density.max_static) — реши это в проекте или убери порчу из RED_FAST ниже. Свои порчи
дописывай в списки ниже по образцу checks/red_demo.py: порча правит ctx (probe.json, film.json, копии сцен) в памяти
и обязана покраснеть строкой с названной подстрокой; образец обязан пройти молча.
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # engine/video
sys.path.insert(0, HERE)
import check as C                    # noqa: E402,F401
from checks import red_film as R     # noqa: E402

# (имя, порча(ctx, tmp), подстрока строки FAIL)
RED_FAST = list(R.RED_FAST) + [
]
# (имя, правка(ctx, tmp))
SAMPLES = list(R.SAMPLES) + [
]


def red_fast(root, out_dir, film, only, filt=None):
    return R.run_red(root, out_dir, film, only, filt, RED_FAST)


def samples(root, out_dir, film, only, filt=None):
    return R.run_samples(root, out_dir, film, only, filt, SAMPLES)


def red_slow(root, out_dir, film, only, filt=None):
    return R.red_slow(root, out_dir, film, only, filt)
'''


def init(root, film):
    """Завести checks/red_<фильм>.py; (путь, создан ли). Существующий файл не трогается."""
    pj = C.load_json(os.path.join(root, 'project.json'))
    fp = os.path.join(root, (pj.get('paths') or {}).get('films', 'films'), film + '.json')
    if not os.path.exists(fp):
        raise SystemExit('ОШИБКА: нет фильма %s — порчи заводятся для своего фильма (имя файла в films/ без .json)' % fp)
    dst = os.path.join(HERE, 'checks', 'red_%s.py' % film)
    if os.path.exists(dst):
        return dst, False
    with open(dst, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(RED_FILE % {'film': film})
    return dst, True
