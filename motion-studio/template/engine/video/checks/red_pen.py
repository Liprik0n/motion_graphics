# -*- coding: utf-8 -*-
"""Порчи и образцы фильма «pen» (films/pen.json): буквы «пером» V38, Lottie V39, набор букв и кадры фильма V40–V43.

    python engine/video/check.py pen --red | --samples

Порча правит данные проверки в памяти (промер страницы probe.json, промер кадров plugin_probe.json, копии раскадровок
во временной папке) и обязана покраснеть строкой с названной подстрокой; образец — законный вариант — обязан пройти
молча. Перо, фраза из крупинок и анимация Lottie в фильме настоящие (сцены pen-probe и lottie-probe): порчи V38, V39,
V40, V41, V43 портят их промер. Окон и нырка в фильме нет (им нужна следующая сцена на холсте набора букв): их порчи
дописывают метку в копию раскадровки и кладут в промер запись набора — что проверка скажет, увидев такой промер.
Порча самой страницы (правка кода плагина и новый промер) — engine/video/tests/test_plugins_v2.py.
Доли трека для V42 — файл во временной папке (project.json beats).
Здесь же порча V36 «слой заморожен» и образец «пауза still» (checks/red_film.py) с порогом проекта: сцена pen-probe
(13,4 с) — единственная фикстура шаблона, которая вмещает 6,0 с движения и простой дольше 6,0 с; у демо таких сцен нет.
"""
import copy
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # engine/video
sys.path.insert(0, HERE)
import check as C                    # noqa: E402
from checks import red_film as R     # noqa: E402

SCENE = 'pen-probe'
LOTTIE_SCENE = 'lottie-probe'
STEM, WIRE, GATHER = 'write-stem', 'write-wire', 'gather'
LOTTIE_ID = 'anim'
URL_OUTSIDE = 'https://' + 'example.invalid/player.js'


# ---------------------------------------------------------------- помощники
def _pen(ctx, cue):
    """[(t, запись плагина pen о метке)] по времени."""
    out = []
    for s in sorted(ctx['probe']['samples'], key=lambda x: x['t']):
        for it in C._plugin_items(s, 'pen'):
            if it.get('scene') == SCENE and it.get('cue') == cue:
                out.append((s['t'], it))
    return out


def _kit_items(ctx, kind):
    return [it for s in ctx['probe']['samples'] for it in C._plugin_items(s, 'cardkit') if it.get('kind') == kind]


def _sb_edit(ctx, tmp, fn, scene=SCENE):
    """Раскадровка сцены — в копии сцен фильма во временной папке; проверка читает её оттуда."""
    dst = os.path.join(tmp, 'scenes')
    if not os.path.exists(dst):
        keep = {x['id'] for x in ctx['film']['scenes']}
        shutil.copytree(ctx['scenes_dir'], dst, ignore=lambda d, names: [n for n in names if d == ctx['scenes_dir'] and n not in keep])
    p = os.path.join(dst, scene, 'storyboard.json')
    sb = C.load_json(p)
    fn(sb)
    with open(p, 'w', encoding='utf-8') as fh:
        json.dump(sb, fh, ensure_ascii=False)
    ctx['scenes_dir'] = dst
    ctx.pop('_sbs_raw', None)
    ctx.pop('_sbs', None)
    return sb


def _cues(sb):
    return sb['plugins']['act']['cues']


def _add_plugin(ctx, name, item_at):
    """В каждый кадр промера — запись плагина name: item_at(номер кадра промера, t) → запись или None."""
    for k, s in enumerate(sorted(ctx['probe']['samples'], key=lambda x: x['t'])):
        it = item_at(k, s['t'])
        if it is None:
            continue
        for p in s['plugins']:
            if p and p.get('plugin') == name:
                p['items'].append(it)
                break
        else:
            s['plugins'].append({'plugin': name, 'items': [it]})


# ---------------------------------------------------------------- V38 буквы «пером»
def m_pen_pale_before(ctx, tmp):
    """Прежний дефект: вторая строка бледно видна, пока перо пишет первую."""
    for t, it in _pen(ctx, STEM):
        ln = it['lines'][1]
        if ln['tip'] is None:
            ln['ink'] = 900


def m_pen_ink_ahead(ctx, tmp):
    """Буквы правее пера: заливка не обрезана по перу."""
    for t, it in _pen(ctx, STEM):
        ln = it['lines'][0]
        if ln['tip'] is not None and ln['fill'] < 1:
            ln['ink_ahead'] = 400


def m_pen_reveal_runs(ctx, tmp):
    """Строка открывается быстрее, чем идёт перо по закону tokens: в промере перо сразу у правого края."""
    for t, it in _pen(ctx, WIRE):
        ln = it['lines'][0]
        if ln['tip'] is not None:
            ln['tip'] = ln['rect'][0] + ln['rect'][2]


def m_pen_lead_pop(ctx, tmp):
    """Прежний дефект: ведущая линия появляется сразу во всю длину."""
    for t, it in _pen(ctx, WIRE):
        ln = it['lines'][0]
        if ln['lead'] > 0:
            ln['lead'], ln['lead_alpha'] = ln['lead_full'], 1.0


def m_pen_lead_cut(ctx, tmp):
    """Прежний дефект: ведущая линия гаснет одним кадром — до последнего кадра она полной длины и яркости."""
    for t, it in _pen(ctx, STEM):
        ln = it['lines'][0]
        if ln['lead'] > 0 and ln['tip'] is not None:
            ln['lead'], ln['lead_alpha'] = ln['lead_full'], 1.0


def m_pen_not_written(ctx, tmp):
    for t, it in _pen(ctx, WIRE):
        it['lines'][0].update(ink=0, ink_ahead=0, fill=0)


def m_pen_text(ctx, tmp):
    for t, it in _pen(ctx, STEM):
        it['lines'][0]['text'] = 'Линию ведёт кисть'


def m_pen_no_plugin(ctx, tmp):
    for s in ctx['probe']['samples']:
        s['plugins'] = [p for p in s['plugins'] if not (p and p.get('plugin') == 'pen')]


def s_pen_edge(ctx, tmp):
    """Сглаживание кромки штриха у пера: несколько пикселей правее границы — не буква."""
    for t, it in _pen(ctx, STEM):
        for ln in it['lines']:
            if ln['tip'] is not None and ln['fill'] < 1:
                ln['ink_ahead'] = C.PEN_INK_PX


def s_pen_lags(ctx, tmp):
    """Строка открывается чуть позже пера (толстый штрих): позади закона — не «видна до пера»."""
    for t, it in _pen(ctx, WIRE):
        ln = it['lines'][0]
        if ln['tip'] is not None:
            ln['tip'] = ln['rect'][0] + (ln['tip'] - ln['rect'][0]) * 0.9


# ---------------------------------------------------------------- V39 Lottie (сцена lottie-probe, настоящий проигрыватель)
def _lottie(ctx):
    """[(номер кадра промера, t, запись плагина lottie об анимации сцены lottie-probe)] по времени."""
    out = []
    for k, s in enumerate(sorted(ctx['probe']['samples'], key=lambda x: x['t'])):
        for it in C._plugin_items(s, 'lottie'):
            if it.get('scene') == LOTTIE_SCENE and it.get('id') == LOTTIE_ID:
                out.append((k, s['t'], it))
    return out


def m_lottie_load_time(ctx, tmp):
    """Время от загрузки: проигрыватель идёт сам с открытия страницы — кадр растёт с номером кадра промера, а не с t."""
    for k, t, it in _lottie(ctx):
        it['frame'] = round(min(it['total'] - 1.0, k * 0.6), 3)


def m_lottie_stands(ctx, tmp):
    for k, t, it in _lottie(ctx):
        it['frame'] = 0.0


def m_lottie_not_loaded(ctx, tmp):
    for k, t, it in _lottie(ctx):
        it['loaded'] = False


def m_lottie_network(ctx, tmp):
    ctx['plugin_probe'] = dict(ctx['plugin_probe'], requests=[URL_OUTSIDE])


def s_lottie_loop(ctx, tmp):
    """Анимация по кругу (loop в копии раскадровки): после конца файла кадр идёт с начала — по той же шкале."""
    def loop(sb):
        for e in sb['elements']:
            if e['id'] == LOTTIE_ID:
                e['loop'] = True
    sb = _sb_edit(ctx, tmp, loop, LOTTIE_SCENE)
    el = [e for e in sb['elements'] if e['id'] == LOTTIE_ID][0]
    data = C.load_json(os.path.join(HERE, el['src']))
    at, total, rate = C.beat_t(ctx, el['at']), float(data['op'] - data['ip']), float(data['fr'])
    for k, t, it in _lottie(ctx):
        it['frame'] = round((max(0.0, (t - at) * rate * float(el.get('speed', 1)))) % total, 3)


# ---------------------------------------------------------------- V40, V43 набор букв
def m_kit_no_source(ctx, tmp):
    """Текст из воздуха: частицы фразы начинают не в банке."""
    for it in _kit_items(ctx, 'phrase'):
        it['origins'] = [[p[0] + 600, p[1] - 500] for p in it['origins']]


def m_kit_no_probe(ctx, tmp):
    for s in ctx['probe']['samples']:
        s['plugins'] = [p for p in s['plugins'] if not (p and p.get('plugin') == 'cardkit')]


def m_kit_text(ctx, tmp):
    for it in _kit_items(ctx, 'phrase'):
        it['text'] = ['буквы из песка']


def m_kit_window_flat(ctx, tmp):
    """Окна-буквы без тени верхнего слоя: метка windows в копии раскадровки, в промере окно раскрыто, тени нет."""
    _sb_edit(ctx, tmp, lambda sb: _cues(sb).append({'id': 'win', 't': {'reply': 6, 'at': 0.6}, 'who': 'phrase', 'do': 'windows',
                                                    'motion': 'card_windows', 'word': 'буквы', 'reveals': SCENE}))
    _add_plugin(ctx, 'cardkit', lambda k, t: {'scene': SCENE, 'cue': 'win', 'kind': 'windows', 'word': 'буквы', 'open': 1.0,
                                               'drawn': True, 'shadow': None, 'rect': [0, 0, 10, 10], 'reveals': SCENE})


def m_kit_dive_other_letter(ctx, tmp):
    """Нырок не в ту букву: по раскадровке — первая буква слова, в промере набора — другая."""
    _sb_edit(ctx, tmp, lambda sb: _cues(sb).append({'id': 'dive', 't': {'reply': 6, 'at': 0.7}, 'who': 'phrase', 'do': 'dive',
                                                    'motion': 'card_dive', 'word': 'буквы', 'char': 0, 'line': 0, 'into': SCENE}))
    W, H = C.canvas(ctx)
    ln = [c for c in _cues(C.load_json(os.path.join(ctx['scenes_dir'], SCENE, 'storyboard.json'))) if c['id'] == GATHER][0]['lines'][0]
    _add_plugin(ctx, 'cardkit', lambda k, t: {'scene': SCENE, 'cue': 'dive', 'kind': 'dive', 'word': 'буквы', 'char': 0, 'ch': 'у',
                                               'pivot': [ln['x'] * W, ln['y'] * H], 'size': ln['size_frac_w'] * W,
                                               'baseline': ln['y'] * H, 'upper': {'scale': 1, 'alpha': 1}, 'lower': {'scale': 1}})


# ---------------------------------------------------------------- V41 кадры фильма
def _stills(ctx):
    return ctx['plugin_probe']['stills']


def _spoil_image(ctx, tmp, rel, name):
    """Копия кадра с чёрной плашкой посередине → путь."""
    from PIL import Image, ImageDraw
    im = Image.open(os.path.join(ctx['out_dir'], rel)).convert('RGB')
    w, h = im.size
    ImageDraw.Draw(im).rectangle([w // 3, h // 3, w // 2, h // 2], fill=(0, 0, 0))
    p = os.path.join(tmp, name)
    im.save(p, compress_level=1)
    return p


def m_frames_det(ctx, tmp):
    """Кадр действия после перезагрузки страницы снят по-другому (случайность не от зерна, время от загрузки)."""
    d = _stills(ctx)['det'][0]
    d['b'] = _spoil_image(ctx, tmp, d['a'], 'det_b.png')


def m_frames_seam(ctx, tmp):
    """Шов со скачком: первый кадр сцены lottie-probe — не та картинка, что последний кадр pen-probe."""
    sm = _stills(ctx)['seams'][0]
    sm['b'] = _spoil_image(ctx, tmp, sm['a'], 'seam_b.png')


def m_frames_lost(ctx, tmp):
    ctx['plugin_probe'] = dict(ctx['plugin_probe'], stills=None)


def m_frame0_empty(ctx, tmp):
    """Фильм объявил правило кадра 0 (превью в мессенджере не пустое), а кадр 0 — почти чистая бумага."""
    ctx['fdef']['stills'] = {'frame0': {'lum': [0.6, 0.98], 'sigma': 0.02}}


def s_frame0_rule_met(ctx, tmp):
    ctx['fdef']['stills'] = {'frame0': {'lum': [0.5, 1.0], 'sigma': 0.0}}


# ---------------------------------------------------------------- V42 доли трека
def _beats(ctx, tmp, first, period, n=8):
    p = os.path.join(tmp, 'beats.json')
    with open(p, 'w', encoding='utf-8') as fh:
        json.dump({'segment': {'start': 0.0}, 'beats': [round(first + period * k, 4) for k in range(n)]}, fh)
    ctx['project'] = dict(copy.deepcopy(ctx['project']), beats=p)


def m_beats_off_grid(ctx, tmp):
    """Доли трека каждые 2 с от 0,35 с: метки на 0,6 с и дальше через такт стоят в четверти секунды от сетки."""
    _beats(ctx, tmp, 0.35, 2.0)


def m_beats_key_off(ctx, tmp):
    """Ключевое событие (фраза собрана, key phrase) — между долями: сетка шестнадцатых цела, доля — нет."""
    _sb_edit(ctx, tmp, lambda sb: [c.update(key='phrase') for c in _cues(sb) if c['id'] == GATHER])
    _beats(ctx, tmp, 0.6, 2.0)


def s_beats_on_grid(ctx, tmp):
    """Доли каждые 2 с от 0,6 с — такты немых строк фильма: все метки на сетке."""
    _beats(ctx, tmp, 0.6, 2.0)


# (имя, порча(ctx, tmp), подстрока строки FAIL)
RED_FAST = [
    # V36 с числом проекта: сцена pen-probe (13,4 с) вмещает 6,0 с движения и простой дольше 6,0 с; у демо таких сцен нет
    ('V36 слой заморожен', R.m_layer_frozen, 'V36 живость %s: зона 1×1' % SCENE),
    ('V38 строка бледно видна до пера', m_pen_pale_before, 'V38 перо %s:%s строка 2: строка видна до пера' % (SCENE, STEM)),
    ('V38 краска правее пера', m_pen_ink_ahead, 'правее пера 400 px краски'),
    ('V38 строка открыта быстрее пера', m_pen_reveal_runs, 'V38 перо %s:%s строка 1: строка видна до пера' % (SCENE, WIRE)),
    ('V38 ведущая линия сразу во всю длину', m_pen_lead_pop, 'ведущая линия появилась сразу во всю длину'),
    ('V38 ведущая линия гаснет одним кадром', m_pen_lead_cut, 'ведущая линия погасла одним кадром'),
    ('V38 строка не написана', m_pen_not_written, 'V38 перо %s:%s строка 1: строка не написана' % (SCENE, WIRE)),
    ('V38 текст фразы не из раскадровки', m_pen_text, 'текст фразы ≠ раскадровке'),
    ('V38 буквы пишет не плагин', m_pen_no_plugin, 'метки нет в промере плагина pen'),
    ('V39 время от загрузки', m_lottie_load_time, 'V39 Lottie %s:%s: время анимации не от шкалы' % (LOTTIE_SCENE, LOTTIE_ID)),
    ('V39 анимация стоит на первом кадре', m_lottie_stands, 'время анимации не от шкалы'),
    ('V39 анимация не загружена', m_lottie_not_loaded, 'анимация ещё не загружена'),
    ('V39 запрос в сеть при показе', m_lottie_network, 'V39 Lottie: при показе страницы были запросы мимо её файлов'),
    ('V40 частицы фразы без источника', m_kit_no_source, 'V40 card-kit %s:%s: частицы текста без источника' % (SCENE, GATHER)),
    ('V40 фраза не из набора букв', m_kit_no_probe, 'V40 card-kit %s:%s: метки нет в промере card-kit' % (SCENE, GATHER)),
    ('V40 окно без тени', m_kit_window_flat, 'V40 card-kit %s:win: окно без тени верхнего слоя' % SCENE),
    ('V40 нырок не в ту букву', m_kit_dive_other_letter, 'V40 card-kit %s:dive: нырок в «у», а по раскадровке в «б»' % SCENE),
    ('V41 кадр действия не повторился', m_frames_det, 'V41 детерминизм: кадр'),
    ('V41 шов со скачком', m_frames_seam, 'V41 шов %s → %s' % (SCENE, LOTTIE_SCENE)),
    ('V41 кадры не сняты', m_frames_lost, 'V41 кадры фильма: нет промера кадров'),
    ('V41 кадр 0 пуст по правилу фильма', m_frame0_empty, 'V41 кадр 0 пуст'),
    ('V42 метки мимо сетки долей', m_beats_off_grid, 'не на сетке шестнадцатых'),
    ('V42 ключевое событие мимо доли', m_beats_key_off, 'V42 BEATSYNC %s:%s: ключевое событие phrase' % (SCENE, GATHER)),
    ('V43 текст фразы набора не из раскадровки', m_kit_text, 'V43 тексты %s:%s' % (SCENE, GATHER)),
]
# (имя, правка(ctx, tmp))
SAMPLES = [
    ('V36 замерший слой с объявленной паузой (still)', R.s_layer_still),
    ('V38 сглаживание кромки у пера', s_pen_edge),
    ('V38 строка открывается чуть позже пера', s_pen_lags),
    ('V39 анимация по кругу', s_lottie_loop),
    ('V41 правило кадра 0 выполнено', s_frame0_rule_met),
    ('V42 метки на сетке долей', s_beats_on_grid),
]


def red_fast(root, out_dir, film, only, filt=None):
    return R.run_red(root, out_dir, film, only, filt, RED_FAST)


def samples(root, out_dir, film, only, filt=None):
    return R.run_samples(root, out_dir, film, only, filt, SAMPLES)


def red_slow(root, out_dir, film, only, filt=None):
    print('медленные порчи фильма pen — правка кода плагина в собранной странице и новый промер: '
          'engine/video/tests/test_plugins_v2.py (V38 «бледная строка до пера», V39 «время от загрузки»)')
    return 0
