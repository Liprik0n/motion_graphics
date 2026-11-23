# -*- coding: utf-8 -*-
"""Проверки глаза: живость по зонам (V36) и читаемость текста по пикселям (V37) — engine/video/check.py.

    python engine/video/tests/test_checks_eye.py        (секунды, без браузера: кадры рисует сам тест)

Ожидания — из задания на проверки глаза и посчитаны руками, не списаны с кода.
Кадр теста 480×270, сетка зон 4×3 (зона 120×90 px), кадры через 0,5 с.
  Живость. Кружок едет в зоне «столбец 2, строка 1» восемь шагов (t = 0…4,0 с) и стоит ещё восемь (4,0…8,0 с):
  при max_static 3,0 с зона — движущийся слой (ехала 4,0 ≥ 3,0) и стоит 4,0 > 3,0 — провал с сценой s1, зоной 2×1
  и отрезком 4.0…8.0; при max_static 4,0 стоит не дольше порога — молчит; при 5,0 слоёв, ехавших так долго, нет —
  «нечего мерить». Пауза still на 4,0…8,0 с снимает провал; пауза только до 4,5 с оставляет 3,5 с > 3,0 — провал.
  Простой до первого долгого движения (зона ещё пуста) — не замерший слой.
  Читаемость. Контраст WCAG = (Lсветл + 0,05) / (Lтёмн + 0,05), L — относительная яркость sRGB. Золото (255, 214, 120)
  на шафране (244, 178, 96): L = 0,7071 и 0,5192 → 0,7571 / 0,5692 = 1,33 — провал; тёмные буквы (40, 30, 50) на том
  же фоне: L = 0,0161 → 0,5692 / 0,0661 = 8,6 — читается. Кремовая заливка (255, 244, 214) с тёмной обводкой
  (44, 22, 40) вплотную: 15,3 — читается на любом закате, хотя заливка к шафрану даёт всего 1,5–1,7.
  Порог порчи. V36 краснеет, только если зона ехала ≥ max_static и потом стояла > max_static в той же сцене: при
  шаге 0,5 с и пороге 6,0 с это 12 + 13 пар кадров — сцена не короче 12,5 с. Порча «слой заморожен» идёт с числом
  проекта; в фильме, где такой сцены нет, она — MISS с длиной сцены и порогом, а строка V36 называет слепые сцены.
Ещё: вход check.py под deps.run — без Pillow одна строка с именем пакета и командой, код 2 (ревью фундамента);
check.py <фильм> --red-init заводит файл порч своего фильма; общие порчи (checks/red_film.py) краснеют на фильме,
где сами проверки пишут «нечего мерить».
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

VIDEO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(VIDEO.parent / 'tests'))
from _util import ENGINE, PY, check, run_module   # noqa: E402

sys.path.insert(0, str(VIDEO))
import check as C   # noqa: E402

W, H, STEP = 480, 270, 0.5
PAPER, INK = (240, 240, 235), (40, 60, 120)
SAFFRON, GOLD, DARK_TEXT = (244, 178, 96), (255, 214, 120), (40, 30, 50)
CREAM, OUTLINE = (255, 244, 214), (44, 22, 40)
_tmp = []


def _dir():
    d = tempfile.mkdtemp(prefix='eye_test_')
    _tmp.append(d)
    return d


def _font(px):
    from PIL import ImageFont
    return ImageFont.truetype(str(VIDEO / 'assets' / 'fonts' / 'LiberationSansNarrow-Bold.ttf'), px)


def wcag(a, b):
    """Контраст двух цветов sRGB по формуле WCAG 2 — своя запись формулы, не код проверки."""
    def lum(c):
        ch = [(v / 255.0) / 12.92 if v / 255.0 <= 0.04045 else ((v / 255.0 + 0.055) / 1.055) ** 2.4 for v in c]
        return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]
    hi, lo = max(lum(a), lum(b)), min(lum(a), lum(b))
    return (hi + 0.05) / (lo + 0.05)


def _ctx(frames, scenes=None, still=None, **tokens):
    """Контекст проверки без страницы: кадры и строки текста теста лежат в ctx['eye'], как у порч."""
    d = _dir()
    dur = len(frames) * STEP
    scenes = scenes or [('s1', 0.0, dur)]
    for sid, _, _ in scenes:
        os.makedirs(os.path.join(d, 'scenes', sid))
        sb = {'scene': sid, 'title': 'T', 'start_state': {}, 'end_state': {}, 'beats': []}
        if still and sid in still:
            sb['still'] = still[sid]
        with open(os.path.join(d, 'scenes', sid, 'storyboard.json'), 'w', encoding='utf-8') as fh:
            json.dump(sb, fh, ensure_ascii=False)
    out = []
    for k, (im, text) in enumerate(frames):
        p = os.path.join(d, '%04d.png' % (k + 1))
        im.save(p)
        out.append({'t': k * STEP, 'file': p, 'text': text})
    zones = {'grid': [4, 3], 'min_share': 0.002, 'delta': 0.02, 'step_sec': STEP}
    zones.update({k: v for k, v in tokens.items() if k in zones})
    tk = {'density': {'max_static': tokens.get('max_static', 3.0), 'zones': zones},
          'legibility': {'pixel': {'contrast_min': tokens.get('contrast_min', 3.0), 'keep': tokens.get('keep', 0.8)}}}
    film = {'film': 't', 'fps': 30, 'duration': dur,
            'scenes': [{'id': sid, 'start': a, 'end': b, 'first': a, 'last': b} for sid, a, b in scenes],
            'replies': [{'n': i + 1, 'num': i + 1, 'start': a, 'end': b} for i, (sid, a, b) in enumerate(scenes)]}
    return C.Ctx(root=d, project={'fps': 30, 'canvas': {'w': W, 'h': H, 'px_per_in': 96}}, tokens=tk, film=film,
                 probe={'samples': []}, fdef={}, out_dir=d, scenes_dir=os.path.join(d, 'scenes'), page_only=True,
                 eye={'step': STEP, 'scale': 1.0, 'frames': out})


def _only(ctx, code):
    """Отчёт одной проверки строками run() — как её видит пользователь."""
    old = C.CHECKS
    C.CHECKS = [c for c in old if c[0] == code]
    try:
        return C.run(ctx, quiet=True)[1]
    finally:
        C.CHECKS = old


# ---------------------------------------------------------------- V36
def _layer_frames(n=17, stop=8, at=(150, 45), dx=4):
    """Кружок в зоне 2×1 (x 120…240, y 0…90) едет stop шагов по dx px и стоит до конца."""
    from PIL import Image, ImageDraw
    out = []
    for k in range(n):
        im = Image.new('RGB', (W, H), PAPER)
        x = at[0] + dx * min(k, stop)
        ImageDraw.Draw(im).ellipse([x - 20, at[1] - 20, x + 20, at[1] + 20], fill=INK)
        out.append((im, []))
    return out


def test_v36_frozen_layer_names_scene_zone_and_span():
    f = C.v36_alive_zones(_ctx(_layer_frames()))
    check(f and len(f) == 1, 'слой ехал 4 с и стоит 4 с при max_static 3,0 — ждали один провал V36, получили: %s' % (f,))
    line = f[0]
    check(line.startswith('V36') and 's1' in line and '2×1' in line, 'провал не называет сцену s1 и зону 2×1: %s' % line)
    check('4.0' in line and '8.0' in line, 'провал не называет отрезок 4.0…8.0 с: %s' % line)


def test_v36_declared_still_is_silent():
    whole = {'s1': {'from': {'reply': 1, 'at': 4.0 / 8.5}, 'to': {'reply': 1, 'at': 1}, 'why': 'стоп-кадр по замыслу'}}
    f = C.v36_alive_zones(_ctx(_layer_frames(), still=whole))
    check(f == [], 'пауза still на весь простой — ждали молчание (пустой список), получили: %s' % (f,))
    short = {'s1': [{'from': {'reply': 1, 'at': 4.0 / 8.5}, 'to': {'reply': 1, 'at': 4.5 / 8.5}, 'why': 'короткая пауза'}]}
    f = C.v36_alive_zones(_ctx(_layer_frames(), still=short))
    check(f and '4.5' in f[0] and '8.0' in f[0], 'пауза до 4,5 с оставляет простой 4.5…8.0 (3,5 с > 3,0) — ждали провал, получили: %s' % (f,))


def test_v36_still_before_first_motion_is_not_a_frozen_layer():
    """Зона стоит 4 с (ещё пуста), потом кружок едет 4 с: простой до первого движения — не замерший слой."""
    from PIL import Image, ImageDraw
    frames = []
    for k in range(17):
        im = Image.new('RGB', (W, H), PAPER)
        if k >= 8:
            x = 150 + 4 * (k - 8)
            ImageDraw.Draw(im).ellipse([x - 20, 25, x + 20, 65], fill=INK)
        frames.append((im, []))
    f = C.v36_alive_zones(_ctx(frames))
    check(f == [], 'простой до первого движения слоя — ждали молчание (зона мерится, провала нет), получили: %s' % (f,))


def test_v36_thresholds_come_from_tokens():
    check(C.v36_alive_zones(_ctx(_layer_frames(), max_static=4.0)) == [],
          'max_static 4,0: слой ехал 4,0 с и стоит ровно 4,0 с — не дольше порога, ждали молчание')
    check(C.v36_alive_zones(_ctx(_layer_frames(), max_static=5.0)) is None,
          'max_static 5,0: слоя, ехавшего 5 с без остановки, нет — ждали «нечего мерить» (None)')
    check(C.v36_alive_zones(_ctx(_layer_frames(), delta=0.9)) is None,
          'delta 0,9: кружок темнее бумаги меньше чем на 0,9 шкалы — движения не видно, ждали None')
    check(C.v36_alive_zones(_ctx(_layer_frames(), min_share=0.5)) is None,
          'min_share 0,5: кружок меняет меньше половины зоны — движения нет, ждали None')
    f = C.v36_alive_zones(_ctx(_layer_frames(), grid=[2, 1]))
    check(f and '1×1' in f[0], 'сетка 2×1: кружок в левой половине — ждали зону 1×1, получили: %s' % (f,))


def test_v36_scene_without_moving_layers_says_nothing_to_measure():
    from PIL import Image
    still = [(Image.new('RGB', (W, H), PAPER), []) for _ in range(17)]
    ctx = _ctx(still)
    check(C.v36_alive_zones(ctx) is None, 'сцена без движения: ждали None (нечего мерить), а не провал')
    line = _only(ctx, 'V36')[0]
    check(line.startswith('SKIP V36') and 'нечего мерить' in line, 'строка отчёта не говорит «нечего мерить»: %s' % line)
    # две сцены: в первой слой едет всё время, вторая стоит — проверка проходит и называет сцену, где мерить нечего
    two = _layer_frames(n=17, stop=99) + still
    ctx = _ctx(two, scenes=[('s1', 0.0, 8.5), ('s2', 8.5, 17.0)])
    lines = _only(ctx, 'V36')
    check(lines[0].startswith('OK   V36') and 'нечего мерить' in lines[0] and 's2' in lines[0],
          'живая сцена + сцена без слоёв: ждали OK с припиской про s2, получили: %s' % lines)


# ---------------------------------------------------------------- V37
def _phrase(bg, fill, stroke=None, text='ТЁПЛЫЙ ВЕЧЕР', gradient=False, src='dom', o=1, covered=False):
    """Кадр со строкой text в (40, 150) кеглем 44 px и её строка промера (плотная рамка букв)."""
    from PIL import Image, ImageDraw
    im = Image.new('RGB', (W, H), bg)
    if gradient:                     # закат: слива (112, 52, 92) сверху → шафран (250, 190, 96) снизу
        px = []
        for y in range(H):
            k = y / float(H - 1)
            px.append(tuple(int(round(a + (b - a) * k)) for a, b in zip((112, 52, 92), (250, 190, 96))))
        col = Image.new('RGB', (1, H))
        col.putdata(px)
        im = col.resize((W, H))
    dr = ImageDraw.Draw(im)
    sw = 4 if stroke else 0
    dr.text((40, 150), text, font=_font(44), fill=fill, stroke_width=sw, stroke_fill=stroke)
    bb = dr.textbbox((40, 150), text, font=_font(44), stroke_width=sw)
    ln = {'src': src, 'id': 'phrase', 'text': text, 'rect': [bb[0], bb[1], bb[2] - bb[0], bb[3] - bb[1]]}
    if src == 'dom':
        ln.update(k=0, scene='s1', o=o, covered=covered)
    else:
        ln['opacity'] = o
    return im, [ln]


def _contrast_in(line):
    m = re.search(r'контраст\D*(\d+[.,]\d+)', line)
    check(m, 'в строке провала нет измеренного контраста: %s' % line)
    return float(m.group(1).replace(',', '.'))


def test_v37_gold_on_sunset_dom_names_worst_frame_and_contrast():
    frames = [_phrase(SAFFRON, DARK_TEXT), _phrase(SAFFRON, DARK_TEXT), _phrase(SAFFRON, GOLD), _phrase(SAFFRON, DARK_TEXT)]
    ctx = _ctx(frames)
    check(not C.styled(ctx), 'фильм теста — без стиля (V21 такой пропускает)')
    f = C.v37_text_pixels(ctx)
    check(f and len(f) == 1, 'золото на шафране в кадре t=1,0 — ждали один провал V37, получили: %s' % (f,))
    line = f[0]
    check(line.startswith('V37') and '#phrase' in line, 'провал не называет надпись #phrase: %s' % line)
    check('t=1.00' in line, 'худший кадр — t=1.00 с (в остальных буквы тёмные): %s' % line)
    want = wcag(GOLD, SAFFRON)
    check(abs(_contrast_in(line) - want) <= 0.1, 'контраст в строке %.2f, по формуле WCAG %.2f' % (_contrast_in(line), want))


def test_v37_dark_text_is_readable():
    f = C.v37_text_pixels(_ctx([_phrase(SAFFRON, DARK_TEXT)] * 2))
    check(f == [], 'тёмные буквы на шафране (контраст %.1f) — ждали молчание, получили: %s' % (wcag(DARK_TEXT, SAFFRON), f))


def test_v37_gold_on_sunset_canvas():
    f = C.v37_text_pixels(_ctx([_phrase(SAFFRON, GOLD, src='canvas')] * 2))
    check(f and 'canvas' in f[0] and 'phrase' in f[0], 'золото на закате в области canvas — ждали провал с «canvas» и id, получили: %s' % (f,))
    check(_contrast_in(f[0]) < 3.0, 'измеренный контраст не ниже порога: %s' % f[0])


def test_v37_outline_on_sunset_passes_and_bare_gold_does_not():
    f = C.v37_text_pixels(_ctx([_phrase(None, CREAM, OUTLINE, gradient=True, src='canvas')] * 2))
    check(f == [], 'светлая заливка с тёмной обводкой на закате — ждали молчание, получили: %s' % (f,))
    f = C.v37_text_pixels(_ctx([_phrase(None, GOLD, gradient=True, src='canvas')] * 2))
    check(f, 'то же золото без обводки на том же закате — ждали провал: обводка и есть то, что читается')


def test_v37_measures_only_text_at_full_opacity():
    check(C.v37_text_pixels(_ctx([_phrase(SAFFRON, GOLD)] * 2)), 'та же надпись на 1,0 и не закрытая — провал (иначе тест ничего не мерит)')
    for kw, why in (({'o': 0.5}, 'надпись на 0,5 — в наплыве'), ({'covered': True}, 'надпись закрыта другим элементом')):
        ctx = _ctx([_phrase(SAFFRON, GOLD, **kw)] * 2)
        check(C.v37_text_pixels(ctx) is None, '%s: не мерится, ждали None (нечего мерить)' % why)


def test_v37_keep_share_comes_from_tokens():
    """Строка режется на клетки шириной в свою высоту (их n = ширина / высота, здесь не меньше пяти); последняя клетка
    залита фоном (блик закрыл буквы): при keep 0,8 одна клетка из n прощается — молча, при keep 1,0 — провал.
    Порог contrast_min 12 (выше 8,6 тёмных букв) — провал и у чистой строки."""
    from PIL import ImageDraw
    im, text = _phrase(SAFFRON, DARK_TEXT)
    x, y, w, h = text[0]['rect']
    n = int(round(w / float(h)))
    check(n >= 5, 'строка теста короче пяти клеток (%d): keep 0,8 не простит ни одной' % n)
    ImageDraw.Draw(im).rectangle([x + w * (n - 1) // n, y, x + w, y + h], fill=SAFFRON)
    check(C.v37_text_pixels(_ctx([(im, text)] * 2, keep=0.8)) == [], 'keep 0,8: хвост строки под бликом прощается — ждали молчание')
    check(C.v37_text_pixels(_ctx([(im, text)] * 2, keep=1.0)), 'keep 1,0: каждая клетка обязана читаться — ждали провал')
    check(C.v37_text_pixels(_ctx([_phrase(SAFFRON, DARK_TEXT)] * 2, contrast_min=12.0)), 'contrast_min 12: буквы 8,9 — ждали провал')


def test_scene_without_text_and_hero_breaks_nothing():
    from PIL import Image
    ctx = _ctx([(Image.new('RGB', (W, H), PAPER), []) for _ in range(6)])
    check(C.v37_text_pixels(ctx) is None and C.v36_alive_zones(ctx) is None, 'пустая сцена: обе проверки — None, без провала')
    line = _only(ctx, 'V37')[0]
    check(line.startswith('SKIP V37') and 'нечего мерить' in line, 'строка отчёта V37 не говорит «нечего мерить»: %s' % line)
    # сцена с текстом + сцена без текста: проходит и называет сцену без текста
    blank = (Image.new('RGB', (W, H), PAPER), [])
    ctx = _ctx([_phrase(SAFFRON, DARK_TEXT)] * 2 + [blank] * 2, scenes=[('s1', 0.0, 1.0), ('s2', 1.0, 2.0)])
    lines = _only(ctx, 'V37')
    check(lines[0].startswith('OK   V37') and 'нечего мерить' in lines[0] and 's2' in lines[0],
          'сцена без текста рядом со сценой с текстом: ждали OK с припиской про s2, получили: %s' % lines)


def test_v37_broken_canvas_declaration_is_named():
    from PIL import Image
    ctx = _ctx([(Image.new('RGB', (W, H), PAPER), [{'src': 'canvas', 'id': 'phrase', 'rect': [10, 10, 'x', 5]}])] * 2)
    f = C.v37_text_pixels(ctx)
    check(f and '__textRects' in f[0], 'область canvas с нечисловой рамкой — ждали провал с именем __textRects, получили: %s' % (f,))


# ---------------------------------------------------------------- общие порчи: любой фильм
def test_generic_red_works_on_film_with_nothing_to_measure():
    from PIL import Image
    from checks import red_film as R
    blank = [(Image.new('RGB', (W, H), PAPER), []) for _ in range(40)]       # 20 с пустого кадра: мерить нечего
    base = _ctx(blank, max_static=6.0)
    check(C.v36_alive_zones(base) is None and C.v37_text_pixels(base) is None, 'пустой фильм: обе проверки — нечего мерить')
    for name, fn, expect in R.RED_FAST:
        if fn is R.m_gold_dom:
            continue                              # у пустого фильма нет надписей DOM — прогон её пропускает сам
        ctx, tmp = C.fresh(base), _dir()
        want = expect(ctx) if callable(expect) else expect
        fn(ctx, tmp)
        got = (C.v36_alive_zones(ctx) or []) + (C.v37_text_pixels(ctx) or [])
        check(any(want in l for l in got), 'порча «%s» не покраснела строкой «%s»: %s' % (name, want, got))
    for name, fn in R.SAMPLES:
        ctx, tmp = C.fresh(base), _dir()
        fn(ctx, tmp)
        got = (C.v36_alive_zones(ctx) or []) + (C.v37_text_pixels(ctx) or [])
        check(not got, 'образец «%s» покраснел: %s' % (name, got))
    # надпись DOM: порча красит закат и золото поверх читаемой строки
    ctx, tmp = C.fresh(_ctx([_phrase(PAPER, DARK_TEXT)] * 3)), _dir()
    R.m_gold_dom(ctx, tmp)
    got = C.v37_text_pixels(ctx) or []
    check(any(R.expect_gold_dom(ctx) in l for l in got), 'порча «золото на закате, DOM» не покраснела: %s' % got)


def test_generic_samples_stay_silent_over_film_text():
    """Образцы рисуют поверх кадров фильма с текстом: надпись под нарисованным слоем или закатом закрыта им — она не
    должна покраснеть вместо образца. Строка «заголовка» стоит в левой верхней зоне и в середине кадра."""
    from PIL import Image, ImageDraw
    from checks import red_film as R
    frames = []
    for _ in range(40):
        im = Image.new('RGB', (W, H), PAPER)
        dr = ImageDraw.Draw(im)
        text = []
        for i, (x, y) in enumerate(((20, 30), (120, 130))):
            dr.text((x, y), 'ЗАГОЛОВОК СЦЕНЫ', font=_font(30), fill=DARK_TEXT)
            bb = dr.textbbox((x, y), 'ЗАГОЛОВОК СЦЕНЫ', font=_font(30))
            text.append({'src': 'dom', 'id': 'title-%d' % i, 'k': 0, 'scene': 's1', 'o': 1, 'covered': False,
                         'text': 'ЗАГОЛОВОК СЦЕНЫ', 'rect': [bb[0], bb[1], bb[2] - bb[0], bb[3] - bb[1]]})
        frames.append((im, text))
    base = _ctx(frames, max_static=6.0)
    check(C.v37_text_pixels(base) == [], 'исходный фильм с тёмным заголовком читается')
    for name, fn in R.SAMPLES:
        ctx, tmp = C.fresh(base), _dir()
        fn(ctx, tmp)
        got = (C.v36_alive_zones(ctx) or []) + (C.v37_text_pixels(ctx) or [])
        check(not got, 'образец «%s» поверх фильма с текстом покраснел: %s' % (name, got))


def _printed(fn, *args, **kw):
    """(результат, что функция напечатала) — прогон порч говорит с пользователем строками."""
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        res = fn(*args, **kw)
    return res, buf.getvalue()


def test_frozen_layer_red_runs_with_project_threshold():
    """Сцена 14 с (28 кадров через 0,5 с), max_static проекта 6,0: слой едет 12 пар кадров (t = 0…6,0 с) и стоит с
    6,0 до последнего кадра 13,5 с — 7,5 с > 6,0. Порог порча не трогает: в строке провала — число проекта."""
    from PIL import Image
    from checks import red_film as R
    ctx, tmp = C.fresh(_ctx([(Image.new('RGB', (W, H), PAPER), []) for _ in range(28)], max_static=6.0)), _dir()
    R.m_layer_frozen(ctx, tmp)
    check(ctx['tokens']['density']['max_static'] == 6.0, 'порча поменяла порог проекта: max_static стал %s' % ctx['tokens']['density']['max_static'])
    got = C.v36_alive_zones(ctx) or []
    check(len(got) == 1 and 'V36' in got[0] and '1×1' in got[0], 'ждали один провал V36 в зоне 1×1, получили: %s' % got)
    check('6.0…13.5' in got[0] and 'стоит 7.5 с' in got[0] and 'max_static 6.0' in got[0],
          'провал не называет отрезок 6.0…13.5 с, простой 7.5 с и порог проекта 6.0: %s' % got[0])


def test_frozen_layer_red_is_a_miss_when_no_scene_can_go_red():
    """Сцена 10 с при пороге проекта 6,0 с: чтобы V36 покраснела, зоне нужно ехать 12 пар кадров (6,0 с) и стоять
    13 пар (дольше 6,0 с) — 25 пар, то есть от первого кадра сцены до последнего 12,5 с. В сцене 20 кадров — 19 пар.
    Порча порог не уменьшает: прогон пишет MISS с длиной сцены и порогом и выходит с кодом 1."""
    from PIL import Image
    from checks import red_film as R
    from checks import redrun
    base = _ctx([(Image.new('RGB', (W, H), PAPER), []) for _ in range(20)], max_static=6.0)
    ctx, tmp = C.fresh(base), _dir()
    try:
        R.m_layer_frozen(ctx, tmp)
        check(False, 'порча «слой заморожен» построилась в сцене 10 с при пороге 6,0 с — она не может там покраснеть честно')
    except redrun.Unfit as e:
        check(ctx['tokens']['density']['max_static'] == 6.0, 'порча поменяла порог проекта: %s' % ctx['tokens']['density']['max_static'])
        for word in ('s1', '10.0', '6.0', '12.5'):
            check(word in str(e), 'отказ порчи не называет «%s» (сцена, её длина, порог, нужная длина): %s' % (word, e))
    code, text = _printed(redrun.fast, [r for r in R.RED_FAST if r[1] is R.m_layer_frozen], lambda row: base)
    line = next((l for l in text.splitlines() if 'слой заморожен' in l), '')
    check(code == 1 and line.startswith('MISS') and '10.0' in line and '6.0' in line,
          'прогон порчи на фильме, где V36 покраснеть не может: ждали код 1 и MISS с длиной сцены 10.0 с и порогом 6.0 с, '
          'получили код %s: %s' % (code, text))
    for name, fn in R.SAMPLES:
        if fn is R.s_layer_still:              # образец «пауза still» на таком фильме ничего не доказывает — SKIP, не «молча»
            code, text = _printed(redrun.samples, [(name, fn)], base)
            check(code == 0 and 'SKIP' in text and 'молча' not in text, 'образец паузы в слепой сцене: ждали SKIP, получили: %s' % text)


def test_v36_line_names_scenes_that_cannot_go_red():
    """Строка V36 называет сцены, где она покраснеть не может при пороге проекта: s2 длиной 6 с при max_static 6,0
    (нужно больше 12,5 с). В s1 (14 с) слой едет всю сцену — она мерится."""
    from PIL import Image
    blank = [(Image.new('RGB', (W, H), PAPER), []) for _ in range(12)]
    ctx = _ctx(_layer_frames(n=28, stop=99) + blank, scenes=[('s1', 0.0, 14.0), ('s2', 14.0, 20.0)], max_static=6.0)
    line = _only(ctx, 'V36')[0]
    check(line.startswith('OK   V36'), 'живая сцена и короткая сцена: ждали OK, получили: %s' % line)
    tail = line.split('покраснеть не может', 1)
    check(len(tail) == 2 and 's2' in tail[1] and '6.0 с' in tail[1] and '12.5' in tail[1] and 's1' not in tail[1],
          'строка V36 не называет короткую сцену s2 (6.0 с при нужных 12.5 с) или называет лишнюю: %s' % line)
    ctx = _ctx([(Image.new('RGB', (W, H), PAPER), []) for _ in range(20)], max_static=6.0)
    line = _only(ctx, 'V36')[0]
    check(line.startswith('SKIP V36') and 'покраснеть не может' in line and 's1' in line and '10.0 с' in line,
          'фильм из одной сцены 10 с: ждали SKIP V36 с именем сцены и её длиной, получили: %s' % line)


# ---------------------------------------------------------------- вход команды
def _engine_copy():
    d = _dir()
    shutil.copytree(ENGINE, os.path.join(d, 'engine'), ignore=shutil.ignore_patterns('node_modules', '__pycache__', 'tests'))
    proj = os.path.join(d, 'project')
    os.makedirs(os.path.join(proj, 'films'))
    with open(os.path.join(proj, 'project.json'), 'w', encoding='utf-8') as fh:
        json.dump({'title': 'T', 'paths': {'out': 'out'}}, fh)
    with open(os.path.join(proj, 'films', 'own-film.json'), 'w', encoding='utf-8') as fh:
        json.dump({'title': 'Свой фильм', 'scenes': []}, fh)
    return d, proj


def _check_py(d, *args, py_args=()):
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    env.pop('MOTION_PROJECT', None)
    return subprocess.run([PY] + list(py_args) + [os.path.join(d, 'engine', 'video', 'check.py')] + list(args), env=env,
                          capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120)


def test_check_without_pillow_is_one_line_code_2():
    """Питон без site-packages (-S) — машина, где Pillow не поставлен: строка с пакетом и командой, код 2."""
    d, proj = _engine_copy()
    r = _check_py(d, 'own-film', '--page', '--project', proj, py_args=('-S',))
    out = r.stdout + r.stderr
    check(r.returncode == 2, 'без Pillow код выхода %d, ждали 2: %s' % (r.returncode, out[-300:]))
    check('Pillow' in out and 'pip install Pillow' in out, 'не названы пакет и команда установки: %s' % out[-300:])
    check('Traceback' not in out, 'нехватка Pillow — трассировкой: %s' % out[-400:])


def test_red_init_creates_film_red_file_once():
    d, proj = _engine_copy()
    dst = os.path.join(d, 'engine', 'video', 'checks', 'red_own-film.py')
    r = _check_py(d, 'own-film', '--red-init', '--project', proj)
    check(r.returncode == 0 and os.path.exists(dst), '--red-init не завёл %s (код %d): %s' % (dst, r.returncode, (r.stdout + r.stderr)[-300:]))
    with open(dst, encoding='utf-8') as fh:
        txt = fh.read()
    for word in ('RED_FAST', 'SAMPLES', 'def red_fast', 'def samples', 'def red_slow', 'own-film'):
        check(word in txt, 'в файле порч нет «%s»' % word)
    with open(dst, 'a', encoding='utf-8') as fh:
        fh.write('# своя порча\n')
    r = _check_py(d, 'own-film', '--red-init', '--project', proj)
    with open(dst, encoding='utf-8') as fh:
        check('# своя порча' in fh.read(), 'повторный --red-init затёр файл со своими порчами')
    check(r.returncode == 0 and 'уже есть' in r.stdout, 'повторный --red-init не сказал, что файл уже есть: %s' % r.stdout[-200:])
    r = _check_py(d, 'no-such-film', '--red-init', '--project', proj)
    check(r.returncode != 0 and 'no-such-film' in (r.stdout + r.stderr) and 'Traceback' not in r.stderr,
          '--red-init для несуществующего фильма должен отказать строкой: %s' % (r.stdout + r.stderr)[-300:])
    # файл порч своего фильма загружается и несёт рабочий минимум: хотя бы по порче на V36 и V37
    code = ("import sys, importlib; sys.path.insert(0, r'%s'); m = importlib.import_module('checks.red_own-film'); "
            "print(' '.join(n for n, _, _ in m.RED_FAST)); print(len(m.SAMPLES))" % os.path.join(d, 'engine', 'video'))
    r = subprocess.run([PY, '-c', code], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60,
                       env=dict(os.environ, PYTHONIOENCODING='utf-8'))
    check(r.returncode == 0 and 'слой заморожен' in r.stdout and 'золото на закате' in r.stdout,
          'файл порч не загрузился или в нём нет порч V36 и V37: %s' % (r.stdout + r.stderr)[-300:])


def test_cleanup():
    for d in _tmp:
        shutil.rmtree(d, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(run_module(globals()))
