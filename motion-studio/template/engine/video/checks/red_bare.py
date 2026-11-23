# -*- coding: utf-8 -*-
"""Порчи и образцы проверок, калиброванные на фильме-фикстуре films/bare.json: сцены bare-start (без каркаса,
картинка-кадр start_image, помехи plugins.glitch) → bare-timer (без каркаса, таймер plugins.timer в элементе timer),
реплики 1–4, элементы note, head, timer, caption; роль шрифта проекта digits (цифры таймера).

    python engine/video/check.py bare --red [подстрока]       быстрые порчи (секунды)
    python engine/video/check.py bare --samples [подстрока]   законные варианты — молча
    python engine/video/check.py bare --red-slow [подстрока]  копия проекта → правка → build.py --page

Порча — (имя, порча, подстрока): засчитана, только если покраснела строка именно с этой подстрокой. Первые —
условия V26–V29 (без каркаса, помехи, картинка-кадр, таймер) и V11 (роль шрифта проекта), дальше — условия ядра на
фильме без каркаса: они обязаны краснеть и здесь (каркас выключен — охрана нет).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # engine/video
sys.path.insert(0, HERE)
import check as C      # noqa: E402
from checks import redrun            # noqa: E402  прогон порч — один на все файлы порч

FILM = 'bare'
S1, S2 = 'bare-start', 'bare-timer'
ROLE_FONT = 'Demo Digits'        # project.json fonts, роль digits


# ---------------------------------------------------------------- помощники
def _samples_of(ctx, scene):
    return [s for s in ctx['probe']['samples'] if s['scene'] == scene]


def _first(ctx, scene):
    sc = [s for s in ctx['film']['scenes'] if s['id'] == scene][0]
    return C.sample_at(ctx, sc['start'])


def _timer_t(ctx):
    sb = [b for s, b in C.storyboards(ctx) if s['id'] == S2][0]
    return C.beat_t(ctx, sb['plugins']['timer']['at'])


def _timer_item(smp):
    for p in smp.get('plugins') or []:
        if p and p.get('plugin') == 'timer':
            return p['items'][0]
    raise KeyError('нет промера таймера в t=%.3f — фикстура изменилась, обнови порчу' % smp['t'])


def _glitch_item(smp):
    for p in smp.get('plugins') or []:
        if p and p.get('plugin') == 'glitch':
            return p['items'][0]
    raise KeyError('нет промера помех в t=%.3f' % smp['t'])


def _window_frames(ctx, tmp, painter):
    """Копия кадров окна помех в tmp, painter(k, img) → новый кадр; шаблон окна указывает на копию."""
    from PIL import Image
    w = ctx['plugin_probe']['windows'][0]
    d = os.path.join(tmp, 'pf')
    os.makedirs(d)
    for k in range(w['n']):
        src = os.path.join(ctx['out_dir'], w['pattern'] % (w['f0'] + k))
        im = painter(k, Image.open(src).convert('RGB'))
        im.save(os.path.join(d, 'f_%05d.png' % (w['f0'] + k)))
    w['pattern'] = os.path.join(d, 'f_%05d.png')


def _solid(img, v):
    from PIL import Image
    return Image.new('RGB', img.size, (v, v, v))


def _flashes(ctx, per_sec):
    """Кадры, где весь кадр меняет яркость белый ↔ чёрный: per_sec вспышек в секунду (пара перепадов = вспышка)."""
    fps = int(ctx['film']['fps'])

    def paint(k, img):
        period = int(round(fps / per_sec))
        return _solid(img, 255 if (k % period) < period // 2 else 0)
    return paint


# ---------------------------------------------------------------- V26 без каркаса
def m_frame_in_frameless(ctx, tmp):
    for s in _samples_of(ctx, S1):
        s['items'].append({'id': 'fr-footer', 'kind': 'frame', 'segs': [], 'fills': [], 'scene': None,
                           'rect': [120, 996, 768, 40], 'opacity': 1.0, 'z': 0, 'layer': None, 'rot': 0, 'scale': 1,
                           'dash': None, 'texts': ['Футер']})


def m_title_on_page(ctx, tmp):
    p = os.path.join(tmp, 'index.html')
    with open(ctx['page'], encoding='utf-8') as fh:
        page = fh.read()
    page = page.replace('<div id="content" class="layer">',
                        '<div class="fr fr-title" id="title--%s" data-scene="%s"><span class="t">Таймер</span></div>\n'
                        '<div id="content" class="layer">' % (S2, S2), 1)
    with open(p, 'w', encoding='utf-8') as fh:
        fh.write(page)
    ctx['page'] = p


def m_frame_nodes_on_page(ctx, tmp):
    p = os.path.join(tmp, 'index.html')
    with open(ctx['page'], encoding='utf-8') as fh:
        page = fh.read()
    page = page.replace('<div id="content" class="layer">',
                        '<div class="fr fr-line" id="fr-line-0"></div>\n<div id="content" class="layer">', 1)
    with open(p, 'w', encoding='utf-8') as fh:
        fh.write(page)
    ctx['page'] = p


# ---------------------------------------------------------------- V27 помехи
def m_glitch_flashes(ctx, tmp):
    _window_frames(ctx, tmp, _flashes(ctx, 6))


def m_glitch_flat(ctx, tmp):
    _window_frames(ctx, tmp, lambda k, img: _solid(img, 128))


def m_glitch_nondet(ctx, tmp):
    from PIL import Image
    d = ctx['plugin_probe']['det'][1]
    a = Image.open(os.path.join(ctx['out_dir'], d['a'])).convert('RGB')
    a.putpixel((10, 10), (0, 0, 0) if a.getpixel((10, 10)) != (0, 0, 0) else (255, 255, 255))
    p = os.path.join(tmp, 'b.png')
    a.save(p)
    d['b'] = p


def m_glitch_no_probe(ctx, tmp):
    ctx['plugin_probe'] = None


# ---------------------------------------------------------------- V28 стартовый кадр
def m_start_dim(ctx, tmp):
    for it in _first(ctx, S1)['items']:
        if it['id'] == '%s--start-image' % S1:
            it['opacity'] = 0.6


def m_start_moved(ctx, tmp):
    for it in _first(ctx, S1)['items']:
        if it['id'] == '%s--start-image' % S1:
            it['rect'] = [24.0, 0.0, 1920.0, 1080.0]


def m_start_covered(ctx, tmp):
    _first(ctx, S1)['items'].append({'id': '%s--note' % S1, 'kind': 'content', 'segs': [], 'fills': [], 'scene': S1,
                                     'rect': [576, 880, 768, 96], 'opacity': 0.4, 'z': 2, 'layer': None, 'rot': 0,
                                     'scale': 1, 'dash': None, 'texts': ['Сигнал прерван']})


def m_start_glitch_on(ctx, tmp):
    _glitch_item(_first(ctx, S1))['power'] = 0.2


# ---------------------------------------------------------------- V29 таймер
def m_timer_start_moved(ctx, tmp):
    ctx['project']['wall_clock']['start'] = '2030-01-15T18:05:00+03:00'      # конфиг сдвинут, кусок не пересобран


def m_timer_event_moved(ctx, tmp):
    ctx['project']['wall_clock']['event'] = '2030-01-16T01:00:00+03:00'


def m_timer_lead_moved(ctx, tmp):
    ctx['project']['wall_clock']['lead_sec'] = ctx['project']['wall_clock']['lead_sec'] + 60.0


def m_timer_offset_moved(ctx, tmp):
    ctx['fdef']['timeline_offset_sec'] = ctx['fdef']['timeline_offset_sec'] + 3.0


def m_timer_frozen(ctx, tmp):
    t0 = _timer_t(ctx)
    frozen = _timer_item(C.sample_at(ctx, t0))['text']
    for s in ctx['probe']['samples']:
        if s['t'] > t0:
            for p in s.get('plugins') or []:
                if p and p.get('plugin') == 'timer':
                    p['items'][0]['text'] = frozen


def m_timer_labels(ctx, tmp):
    for s in ctx['probe']['samples']:
        for p in s.get('plugins') or []:
            if p and p.get('plugin') == 'timer':
                p['items'][0]['labels'] = ['ДНИ', 'ЧАСЫ', 'МИНУТЫ', 'СЕКУНДЫ']


def m_timer_no_probe(ctx, tmp):
    for s in ctx['probe']['samples']:
        s['plugins'] = [p for p in s.get('plugins') or [] if not (p and p.get('plugin') == 'timer')]


# ---------------------------------------------------------------- V11 роль шрифта проекта
def m_role_font_unloaded(ctx, tmp):
    for x in ctx['probe']['fonts']:
        if x['family'] == ROLE_FONT:
            x['status'] = 'unloaded'


def m_role_font_absent(ctx, tmp):
    ctx['probe']['fonts'] = [x for x in ctx['probe']['fonts'] if x['family'] != ROLE_FONT]


# ---------------------------------------------------------------- ядро на фильме без каркаса
def m_page_short(ctx, tmp):
    ctx['film']['duration'] -= 0.5


def m_drop_reply(ctx, tmp):
    ctx['film']['replies'] = [r for r in ctx['film']['replies'] if r['n'] != 3]


def m_off_canvas(ctx, tmp):
    for s in ctx['probe']['samples']:
        for it in s['items']:
            if it['id'] == '%s--caption' % S2:
                it['rect'][0] = 1500.0


def m_text_overlap(ctx, tmp):
    for s in ctx['probe']['samples']:
        for it in s['items']:
            if it['id'] == '%s--head' % S2:
                cap = [x for x in s['items'] if x['id'] == '%s--caption' % S2]
                if cap and cap[0]['segs'] and it['segs']:
                    it['segs'][0][:4] = cap[0]['segs'][0][:4]


def m_hang(ctx, tmp):
    for s in _samples_of(ctx, S2):
        s['items'].append({'id': '%s--orb' % S2, 'kind': 'content', 'segs': [], 'fills': [], 'scene': S2,
                           'rect': [1700, 60, 80, 80], 'opacity': 1.0, 'z': 2, 'layer': None, 'rot': 0, 'scale': 1,
                           'dash': None, 'texts': []})


def m_page_hex(ctx, tmp):
    p = os.path.join(tmp, 'index.html')
    with open(ctx['page'], encoding='utf-8') as fh:
        page = fh.read()
    page = page.replace('background:var(--c-ink);', 'background:#FF00FF;', 1)
    with open(p, 'w', encoding='utf-8') as fh:
        fh.write(page)
    ctx['page'] = p


def m_font_synth(ctx, tmp):
    ctx['probe']['rootStyle'] = {'synthesis': 'weight style'}


# ---------------------------------------------------------------- образцы (законные, молча)
def s_three_flashes(ctx, tmp):
    _window_frames(ctx, tmp, _flashes(ctx, 3))


def s_timer_same_instant(ctx, tmp):
    wc = ctx['project']['wall_clock']
    wc['start'], wc['event'] = '2030-01-15T16:00:00+01:00', '2030-01-15T22:00:00+01:00'      # те же моменты в другом поясе


def s_timer_lead_into_start(ctx, tmp):
    """То же настенное время кадра, записанное иначе: предыстория 0 с, старт на 10 минут позже."""
    wc = ctx['project']['wall_clock']
    wc['start'], wc['lead_sec'] = '2030-01-15T18:10:00+03:00', 0.0


RED_FAST = [
    ('каркас в сцене без каркаса', m_frame_in_frameless, 'V26 без каркаса: #fr-footer виден в сцене bare-start'),
    ('заголовок у сцены без каркаса', m_title_on_page, 'V26 без каркаса: на странице заголовок или номер сцены bare-timer'),
    ('узел каркаса на странице без каркаса', m_frame_nodes_on_page, 'V26 без каркаса: все сцены frame: false, а на странице есть узлы каркаса'),
    ('помехи мигают 6 раз в секунду', m_glitch_flashes, 'V27 помехи: 6 вспышек в секунду'),
    ('помех не видно', m_glitch_flat, 'V27 помехи: в окне сцены bare-start кадр не меняется'),
    ('помехи недетерминированы', m_glitch_nondet, 'V27 помехи: кадр t='),
    ('нет промера помех', m_glitch_no_probe, 'V27 помехи: нет промера помех'),
    ('картинка-кадр приглушена', m_start_dim, 'V28 стартовый кадр bare-start: картинка на 0.60'),
    ('картинка-кадр сдвинута', m_start_moved, 'V28 стартовый кадр bare-start: картинка не во всё полотно'),
    ('поверх картинки-кадра', m_start_covered, 'V28 стартовый кадр bare-start: поверх картинки #bare-start--note'),
    ('помехи в первом кадре', m_start_glitch_on, 'V28 стартовый кадр bare-start: помехи уже идут'),
    ('старт сдвинут, кусок старый', m_timer_start_moved, 'V29 таймер bare-timer: в t='),
    ('событие сдвинуто, кусок старый', m_timer_event_moved, 'V29 таймер bare-timer: в t='),
    ('предыстория длиннее, кусок старый', m_timer_lead_moved, 'V29 таймер bare-timer: в t='),
    ('смещение куска сдвинуто', m_timer_offset_moved, 'V29 таймер bare-timer: в t='),
    ('секунды не тикают', m_timer_frozen, 'V29 таймер bare-timer: секунды не идут'),
    ('подписи таймера не те', m_timer_labels, 'V29 таймер bare-timer: подписи'),
    ('нет промера таймера', m_timer_no_probe, 'V29 таймер bare-timer: нет промера'),
    ('шрифт роли проекта не загружен', m_role_font_unloaded, 'V11 шрифт: %s — статус unloaded' % ROLE_FONT),
    ('шрифта роли проекта нет на странице', m_role_font_absent, 'V11 шрифт: %s' % ROLE_FONT),
    ('страница короче звука', m_page_short, 'а последняя реплика кончается'),
    ('реплика выпала', m_drop_reply, 'V2 реплика №3 из звука фильма не попала в ролик'),
    ('подпись за полотном', m_off_canvas, 'V3 полотно: #bare-timer--caption'),
    ('строки наехали', m_text_overlap, 'V10 надписи: #bare-timer--caption и #bare-timer--head'),
    ('предмет без опоры', m_hang, 'V15 без опоры: #bare-timer--orb'),
    ('цвет вне палитры', m_page_hex, 'V12 палитра: в содержании страницы цвета вне палитры'),
    ('синтез начертаний без каркаса', m_font_synth, 'V11 шрифт: font-synthesis'),
]

SAMPLES = [
    ('ровно 3 вспышки в секунду', s_three_flashes),
    ('старт и событие в другом поясе — те же моменты', s_timer_same_instant),
    ('предыстория внесена в старт — то же время кадра', s_timer_lead_into_start),
]


# ---------------------------------------------------------------- медленные: копия проекта, пересборка страницы
def _json_edit(path, fn):
    data = C.load_json(path)
    fn(data)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)


def _sb_edit(pd, scene, fn):
    _json_edit(os.path.join(pd, 'scenes', scene, 'storyboard.json'), fn)


def p_glitch_storm(pd):
    """Помехи без пауз: вспышка каждые 2 кадра всё окно — пиксели обязаны покраснеть (V27 по кадрам, не по конфигу)."""
    def fn(sb):
        sb['plugins']['glitch'].update(burst_gap=[0.07, 0.07], burst_frames=[1, 1], calm=0.0, rgb_px=60, tear_px=400,
                                       bands=[12, 16], band_h=[60, 160], jitter_px=40)
    _sb_edit(pd, S1, fn)


def p_title_in_frameless(pd):
    _sb_edit(pd, S2, lambda sb: sb.__setitem__('title_at', {'reply': 3, 'at': 0.1}))


def p_start_image_small(pd):
    from PIL import Image
    Image.new('RGB', (960, 540), (255, 255, 255)).save(os.path.join(pd, 'assets', 'start-frame.png'))


def p_glitch_number_missing(pd):
    _json_edit(os.path.join(pd, 'tokens.json'), lambda t: t['motion']['glitch'].pop('tear_px'))


def p_timer_labels_missing(pd):
    _json_edit(os.path.join(pd, 'tokens.json'), lambda t: t['motion']['timer'].pop('labels'))


def p_wall_clock_no_zone(pd):
    _json_edit(os.path.join(pd, 'project.json'), lambda p: p['wall_clock'].__setitem__('start', '2030-01-15T18:00:00'))


def p_role_repeats_brand(pd):
    _json_edit(os.path.join(pd, 'project.json'), lambda p: p['fonts'][0].__setitem__('role', 'brand'))


def p_role_font_file_missing(pd):
    _json_edit(os.path.join(pd, 'project.json'),
               lambda p: p['fonts'][0].__setitem__('files', {'700': 'assets/fonts/net-takogo.ttf'}))


def p_start_later(pd):
    """Сдвиг старта в project.json → пересборка без правки сцен → таймер другой, проверка зелёная."""
    _json_edit(os.path.join(pd, 'project.json'), lambda p: p['wall_clock'].__setitem__('start', '2030-01-15T18:10:00+03:00'))


RED_SLOW = [
    ('помехи без пауз (по пикселям)', p_glitch_storm, 'V27 помехи:'),
    ('title_at у сцены без каркаса', p_title_in_frameless, 'сцена без каркаса (frame: false), а в раскадровке title_at'),
    ('картинка-кадр не размером с полотно', p_start_image_small, 'start_image assets/start-frame.png — 960 × 540'),
    ('нет числа помех — отказ сборки', p_glitch_number_missing, 'плагин glitch — нет обязательных полей tear_px'),
    ('нет подписей таймера — отказ сборки', p_timer_labels_missing, 'плагин timer — нет обязательных полей labels'),
    ('старт без пояса — отказ сборки', p_wall_clock_no_zone, 'время без пояса'),
    ('роль шрифта повторяет brand', p_role_repeats_brand, 'fonts: роль «brand» уже есть'),
    ('нет файла шрифта роли', p_role_font_file_missing, 'Шрифт роли digits'),
]
SAMPLES_SLOW = [
    ('старт +10 мин: только конфиг', p_start_later, 'OK   V29'),
]


# ---------------------------------------------------------------- прогон
def _calibrated(film, only):
    if film != FILM or only:
        print('Порчи калиброваны на фильме-фикстуре целиком: check.py %s --red | --samples | --red-slow' % FILM)
        return False
    return True


def red_fast(root, out_dir, film, only, filt=None):
    if not _calibrated(film, only):
        return 1
    base = redrun.base(root, out_dir)
    if base is None:
        return 1
    return redrun.fast(RED_FAST, lambda row: base, filt)


def samples(root, out_dir, film, only, filt=None):
    if not _calibrated(film, only):
        return 1
    base = redrun.base(root, out_dir)
    if base is None:
        return 1
    return redrun.samples(SAMPLES, base, filt)


def _copy_project(root, dst):
    shutil.copytree(root, dst, ignore=shutil.ignore_patterns('out', 'node_modules', '.env', '__pycache__', 'music', 'director'))


def _slow_build(root, fn):
    """Копия проекта (сборка — этим движком через --project) → правка → build.py --page → строки check
    (или последняя строка отказа сборки, если страница не собралась)."""
    tmp = tempfile.mkdtemp(prefix='motion_slow_')
    try:
        pd = os.path.join(tmp, 'project')
        _copy_project(root, pd)
        fn(pd)
        od = os.path.join(pd, 'out', FILM)
        r = subprocess.run([sys.executable, os.path.join(HERE, 'build.py'), FILM, '--page', '--project', pd, '--out-dir', od],
                           capture_output=True, text=True, encoding='utf-8', errors='replace')
        if r.returncode or not os.path.exists(os.path.join(od, 'probe.json')):
            return ['FAIL сборка порченой страницы упала: ' + (r.stdout + r.stderr).strip()[-400:]]
        ctx = C.make_ctx(pd, od, page_only=True)
        ctx['eye'] = False                      # порча не про V36/V37: кадры полосы копии не снимаем
        _, lines = C.run(ctx, quiet=True)
        return lines
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def red_slow(root, out_dir, film, only, filt=None):
    if not _calibrated(film, only):
        return 1
    return redrun.slow(RED_SLOW, SAMPLES_SLOW, lambda row: _slow_build(root, row[1]), lambda row: row[2], filt)
