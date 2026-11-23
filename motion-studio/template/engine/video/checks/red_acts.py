# -*- coding: utf-8 -*-
"""Порчи и образцы проверок, калиброванные на фильмах-фикстурах films/acts.json (act-stage — с каркасом: часы,
метки act, камера, толчок, немая строка 901 · act-sign — без каркаса: тусклая вывеска, строки для hide) и
films/acts-hide.json (та же act-sign, ключ hide: head, when).

    python engine/video/check.py acts --red [подстрока]       быстрые порчи (правка промера и конфигов в памяти)
    python engine/video/check.py acts --samples [подстрока]   законные варианты — молча
    python engine/video/check.py acts --red-slow [подстрока]  копия проекта → правка → build.py --page

Порча — (имя, порча, подстрока[, фильм]): засчитана, только если покраснела строка именно с этой подстрокой.
Условия: V30 часы, V31 действия мира, V32 камера, V33 hide, V34 сторож текста проекта, V35 тусклая вывеска; плюс
V26 на стыке сцены с каркасом и без, V2 (немая строка), V3 (надпись за кадром в сцене с камерой) и V9 (исключение
из читаемости — только у названного элемента). Страницу варианта acts-hide порчи собирают сами, если её нет.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # engine/video
sys.path.insert(0, HERE)
import check as C      # noqa: E402
from checks import redrun            # noqa: E402  прогон порч — один на все файлы порч

FILM, HIDE_FILM = 'acts', 'acts-hide'
ST, SG = 'act-stage', 'act-sign'
SILENT = 901                     # немая строка фильма acts


# ---------------------------------------------------------------- помощники
def _plug(smp, name, scene):
    for p in smp.get('plugins') or []:
        if p and p.get('plugin') == name:
            for it in p['items']:
                if it['scene'] == scene:
                    return it
    return None


def _cue_t(ctx, cid):
    sb = C.sb_of(ctx, ST)
    c = [x for x in sb['plugins']['act']['cues'] if x['id'] == cid][0]
    return C.beat_t(ctx, c['t']), c


def _cue_recs(ctx, cid):
    out = []
    for s in ctx['probe']['samples']:
        it = _plug(s, 'act', ST)
        if it:
            out += [c for c in it['cues'] if c['id'] == cid]
    return out


def _span_end(ctx, cid):
    t, c = _cue_t(ctx, cid)
    rec = _cue_recs(ctx, cid)[0]
    return t, t + rec['span'] + 2 * C.FR(ctx)


def _items(ctx, dom):
    return [it for s in ctx['probe']['samples'] for it in s['items'] if it['id'] == dom]


def _say(ctx, dom, text):
    """Надпись text у видимого элемента dom во всех кадрах (как если бы её нарисовала разметка)."""
    for it in _items(ctx, dom):
        it['texts'] = it['texts'] + [text]


def _scenes_copy(ctx, tmp, scene, fn):
    d = os.path.join(tmp, 'scenes')
    shutil.copytree(ctx['scenes_dir'], d)
    p = os.path.join(d, scene, 'markup.html')
    with open(p, encoding='utf-8') as fh:
        txt = fh.read()
    new = fn(txt)
    if new == txt:
        raise KeyError('порча разметки %s ничего не изменила — фикстура изменилась, обнови порчу' % scene)
    with open(p, 'w', encoding='utf-8') as fh:
        fh.write(new)
    ctx['scenes_dir'] = d
    ctx.pop('_sbs', None)
    ctx.pop('_sbs_raw', None)


def _seam(ctx):
    """(время стыка act-stage → act-sign, полуширина наплыва каркаса)."""
    sc = [s for s in ctx['film']['scenes'] if s['id'] == SG][0]
    return sc['start'], float(ctx['project']['frame']['seam_half'])


def _frame_items(smp):
    return [it for it in smp['items'] if it['kind'] == 'frame' and not it.get('scene')]


# ---------------------------------------------------------------- V26 стык сцены с каркасом и без
def f_frame_stays(ctx, tmp):
    """Каркас не погас в сцене без каркаса: после окна шва его узлы всё ещё в кадре."""
    edge, half = _seam(ctx)
    src = [s for s in ctx['probe']['samples'] if s['scene'] == ST][5]
    for s in ctx['probe']['samples']:
        if s['scene'] == SG and s['t'] > edge + half + 0.2:
            s['items'] = s['items'] + [dict(it) for it in _frame_items(src)]


def f_frame_dies(ctx, tmp):
    """Каркас погас в сцене с каркасом задолго до шва."""
    edge, half = _seam(ctx)
    for s in ctx['probe']['samples']:
        if s['scene'] == ST and 2.0 < s['t'] < edge - half - 0.2:
            for it in _frame_items(s):
                it['opacity'] = 0.0


# ---------------------------------------------------------------- V2 немая строка
def n_speaks(ctx, tmp):
    r = [x for x in ctx['film']['replies'] if x['n'] == SILENT][0]
    ink = C._rgb_css(ctx['tokens']['palette'][ctx['project']['voice_bars']['ink']])
    for s in ctx['probe']['samples']:
        if s.get('reply') == SILENT and r['start'] <= s['t'] < r['end']:
            s['voice'][r['voice']]['name'] = ink


def n_bars_move(ctx, tmp):
    r = [x for x in ctx['film']['replies'] if x['n'] == SILENT][0]
    for s in ctx['probe']['samples']:
        if s.get('reply') == SILENT and r['start'] <= s['t'] < r['end']:
            s['voice'][r['voice']]['bars'] = [12.0, 20.0, 9.0]


def n_length(ctx, tmp):
    for x in ctx['film']['replies']:
        if x['n'] == SILENT:
            x['end'] = x['end'] + 0.3


def n_flag_lost(ctx, tmp):
    for x in ctx['film']['replies']:
        if x['n'] == SILENT:
            x['silent'] = False


def n_has_file(ctx, tmp):
    for x in ctx['film']['replies']:
        if x['n'] == SILENT:
            x['file'] = 'demo-audio/131.mp3'


# ---------------------------------------------------------------- V30 часы
def m_clock_start_moved(ctx, tmp):
    ctx['project']['wall_clock']['start'] = '2030-01-15T18:05:00+03:00'


def m_clock_lead_moved(ctx, tmp):
    ctx['project']['wall_clock']['lead_sec'] = ctx['project']['wall_clock']['lead_sec'] + 60.0


def m_clock_offset_moved(ctx, tmp):
    ctx['fdef']['timeline_offset_sec'] = float(ctx['fdef'].get('timeline_offset_sec', 0.0)) + 3.0


def m_clock_digits_markup(ctx, tmp):
    _scenes_copy(ctx, tmp, ST, lambda t: t.replace('height:80px; background:var(--c-ink);"></div>',
                                                   'height:80px; background:var(--c-ink);">18:10:32</div>', 1))


def m_clock_digits_dom(ctx, tmp):
    for s in ctx['probe']['samples']:
        it = _plug(s, 'clock', ST)
        if it:
            it['own'] = '18:10'


def m_clock_frozen(ctx, tmp):
    first = None
    for s in sorted(ctx['probe']['samples'], key=lambda x: x['t']):
        it = _plug(s, 'clock', ST)
        if it:
            first = first or it['text']
            it['text'] = first


def m_clock_no_probe(ctx, tmp):
    for s in ctx['probe']['samples']:
        s['plugins'] = [p for p in s.get('plugins') or [] if not (p and p.get('plugin') == 'clock')]


# ---------------------------------------------------------------- V31 действия мира
def m_act_no_exec(ctx, tmp):
    for c in _cue_recs(ctx, 'c02'):
        c['exec'] = False


def m_act_no_change(ctx, tmp):
    t, end = _span_end(ctx, 'c03')
    before = [c for c in _plug(C.sample_at(ctx, t - C.FR(ctx)), 'act', ST)['cues'] if c['id'] == 'c03'][0]['sig']
    for c in _plug(C.sample_at(ctx, end), 'act', ST)['cues']:
        if c['id'] == 'c03':
            c['sig'] = before


def m_act_missing(ctx, tmp):
    for s in ctx['probe']['samples']:
        it = _plug(s, 'act', ST)
        if it:
            it['cues'] = [c for c in it['cues'] if c['id'] != 'c02']


def m_act_late(ctx, tmp):
    for c in _cue_recs(ctx, 'c01'):
        c['t'] = c['t'] + 0.1


def m_act_unknown_motion(ctx, tmp):
    del ctx['tokens']['motion']['act']['gesture']


# ---------------------------------------------------------------- V32 камера и V3 в сцене с камерой
def m_cam_short(ctx, tmp):
    t, end = _span_end(ctx, 'c01')
    _plug(C.sample_at(ctx, end), 'act', ST)['cam']['rect'] = [40.0, 22.5, 1840.0, 1035.0]


def m_cam_drift(ctx, tmp):
    for s in ctx['probe']['samples']:
        it = _plug(s, 'act', ST)
        if it and it.get('cam'):
            it['cam']['drift'] = 2.0


def m_cam_no_probe(ctx, tmp):
    for s in ctx['probe']['samples']:
        it = _plug(s, 'act', ST)
        if it:
            it['cam'] = None


def m_cam_is_element(ctx, tmp):
    p = os.path.join(tmp, 'index.html')
    with open(ctx['page'], encoding='utf-8') as fh:
        page = fh.read()
    with open(p, 'w', encoding='utf-8') as fh:
        fh.write(page.replace('<div class="cam" id="cam--%s"' % ST, '<div class="cam el" id="cam--%s"' % ST, 1))
    ctx['page'] = p


def m_cam_text_out(ctx, tmp):
    for it in _items(ctx, '%s--label' % ST):
        if it['segs']:
            it['segs'][0][0] = 1800.0
            break


# ---------------------------------------------------------------- V33 hide (фильм acts-hide)
def h_hidden_seen(ctx, tmp):
    for s in ctx['probe']['samples']:
        s['items'].append({'id': '%s--head' % SG, 'kind': 'content', 'segs': [], 'fills': [], 'scene': SG,
                           'rect': [360, 300, 1200, 100], 'opacity': 1.0, 'z': 2, 'layer': None, 'rot': 0, 'scale': 1,
                           'dash': None, 'texts': ['ОТКРЫТО'], 'cam': False})
        break


def h_stale_build(ctx, tmp):
    ctx['film']['hidden'] = ['%s--head' % SG]


def h_unknown(ctx, tmp):
    ctx['fdef']['hide'] = list(ctx['fdef']['hide']) + ['nope']


# ---------------------------------------------------------------- V34 сторож текста проекта
def g_placeholder_frame(ctx, tmp):
    _say(ctx, '%s--head' % SG, 'Lorem ipsum')


def g_placeholder_markup(ctx, tmp):
    _scenes_copy(ctx, tmp, SG, lambda t: t.replace('>подпись внизу кадра<', '>TODO<', 1))


def g_time_frame(ctx, tmp):
    _say(ctx, '%s--label' % ST, '18:10:32')


def g_time_storyboard_text(ctx, tmp):
    """Время цифрами в тексте элемента раскадровки (elements[].text) сцены с часами."""
    d = os.path.join(tmp, 'scenes')
    shutil.copytree(ctx['scenes_dir'], d)
    p = os.path.join(d, ST, 'storyboard.json')
    sb = C.load_json(p)
    sb.setdefault('elements', []).append({'id': 'stub', 'kind': 'text', 'x': 1.25, 'y': 9.0, 'w': 4.0, 'h': 0.5,
                                          'text': 'начало в 18:30'})
    with open(p, 'w', encoding='utf-8') as fh:
        json.dump(sb, fh, ensure_ascii=False, indent=1)
    ctx['scenes_dir'] = d
    ctx.pop('_sbs', None)
    ctx.pop('_sbs_raw', None)


# ---------------------------------------------------------------- V35 тусклая вывеска; исключение — только у названного
def d_bright(ctx, tmp):
    for it in _items(ctx, '%s--sign-dim' % SG):
        it['opacity'] = 0.45


def d_flicker_bright(ctx, tmp):
    """Буквы внутри вывески вспыхивают до 0,45 — выше трети: V35 мерит и строки, а не только элемент."""
    for it in _items(ctx, '%s--sign-dim' % SG):
        for g in it['segs']:
            g[4] = 0.45


def d_short(ctx, tmp):
    seen = 0
    for s in sorted(ctx['probe']['samples'], key=lambda x: x['t']):
        for it in s['items']:
            if it['id'] == '%s--sign-dim' % SG and it['opacity'] > 0.05:
                seen += 1
                if seen > 2:
                    it['opacity'] = 0.0
                    for g in it['segs']:
                        g[4] = 0.0


def d_unknown(ctx, tmp):
    ctx['project']['legibility_except'] = list(ctx['project']['legibility_except']) + [
        {'el': '%s:nope' % SG, 'max_opacity': 0.3, 'min_visible': 0.05, 'min_visible_sec': 2.0}]


def d_wrong_name(ctx, tmp):
    for e in ctx['project']['legibility_except']:
        if e['el'] == '%s:sign-dim' % SG:
            e['el'] = '%s:site' % SG


# ---------------------------------------------------------------- образцы (законные, молча)
def s_frame_in_seam(ctx, tmp):
    """Каркас целиком виден внутри окна шва по обе стороны стыка — это и есть наплыв."""
    edge, half = _seam(ctx)
    for s in ctx['probe']['samples']:
        if abs(s['t'] - edge) < half - 0.02:
            for it in _frame_items(s):
                it['opacity'] = 1.0


def s_legit_texts(ctx, tmp):
    _say(ctx, '%s--label' % ST, 'сверка в 00:00')        # законная строка правила «время цифрами» (except)
    _say(ctx, '%s--head' % SG, 'приём до 18:30')         # правило действует только в сцене с часами


def s_dim_flicker(ctx, tmp):
    """Исполнитель моргает буквами внутри вывески (неровный контакт): строки на 0,3 и 0,1, ни разу выше трети."""
    k = 0
    for s in sorted(ctx['probe']['samples'], key=lambda x: x['t']):
        for it in s['items']:
            if it['id'] == '%s--sign-dim' % SG and it['opacity'] > 0.05:
                for g in it['segs']:
                    g[4] = 0.3 if k % 2 else 0.1
                k += 1


def s_clock_day_before(ctx, tmp):
    """Старт на сутки раньше — то же время суток: часам важно время, а не дата."""
    ctx['project']['wall_clock']['start'] = '2030-01-14T18:00:00+03:00'


def s_clock_lead_into_start(ctx, tmp):
    """То же настенное время кадра, записанное иначе: предыстория 0 с, старт на 10 минут позже."""
    wc = ctx['project']['wall_clock']
    wc['start'], wc['lead_sec'] = '2030-01-15T18:10:00+03:00', 0.0


def s_drift_at_limit(ctx, tmp):
    pct = float(ctx['tokens']['motion']['act']['cam_drift']['pct'])
    for s in ctx['probe']['samples']:
        it = _plug(s, 'act', ST)
        if it and it.get('cam'):
            it['cam']['drift'] = pct


def s_silent_bars_noise(ctx, tmp):
    """Полоски немой строки стоят с дрожью меньше допуска."""
    r = [x for x in ctx['film']['replies'] if x['n'] == SILENT][0]
    for s in ctx['probe']['samples']:
        if s.get('reply') == SILENT and r['start'] <= s['t'] < r['end']:
            v = s['voice'][r['voice']]
            v['bars'] = [b + 0.03 for b in v['bars']]


RED_FAST = [
    ('каркас не погас в сцене без каркаса', f_frame_stays, 'V26 без каркаса: #fr-footer виден в сцене act-sign'),
    ('каркас погас в сцене с каркасом', f_frame_dies, 'V26 каркас погас: в сцене с каркасом act-stage'),
    ('немая строка: подпись голоса горит', n_speaks, 'V2 немая строка №901: в t='),
    ('немая строка: полоски голоса ходят', n_bars_move, 'V2 немая строка №901: в t='),
    ('немая строка длиннее ms', n_length, 'V2 немая строка №901: в ролике'),
    ('немая строка: сборка потеряла признак', n_flag_lost, 'V2 немая строка №901: в звуке фильма silent=True'),
    ('немая строка с файлом звука', n_has_file, 'V2 немая строка №901: у неё файл звука'),
    ('часы: старт сдвинут, кусок старый', m_clock_start_moved, 'V30 часы act-stage: в t='),
    ('часы: предыстория длиннее, кусок старый', m_clock_lead_moved, 'V30 часы act-stage: в t='),
    ('часы: смещение куска сдвинуто', m_clock_offset_moved, 'V30 часы act-stage: в t='),
    ('часы: цифры вписаны в разметку руками', m_clock_digits_markup, 'V30 часы act-stage: в разметке у хозяина «clock» цифры'),
    ('часы: у хозяина свои цифры в кадре', m_clock_digits_dom, 'V30 часы act-stage: у хозяина «clock» в кадре свои цифры'),
    ('часы: секунды стоят', m_clock_frozen, 'V30 часы act-stage: секунды не идут'),
    ('часы: нет промера', m_clock_no_probe, 'V30 часы act-stage: нет промера часов'),
    ('act: метка без исполнителя', m_act_no_exec, 'V31 act act-stage:c02: метка без исполнителя'),
    ('act: нет видимого изменения', m_act_no_change, 'V31 act act-stage:c03: у «lid» нет видимого изменения'),
    ('act: метки нет в промере', m_act_missing, 'V31 act act-stage:c02: метки нет в промере'),
    ('act: метка не вовремя', m_act_late, 'V31 act act-stage:c01: в сборке'),
    ('act: неизвестное motion', m_act_unknown_motion, 'V31 act act-stage:c02: motion «gesture» нет в tokens.json motion.act'),
    ('камера не доехала', m_cam_short, 'V32 камера act-stage: после метки c01'),
    ('камера парит сильнее порога', m_cam_drift, 'V32 камера act-stage: парение 2.00 %'),
    ('нет промера камеры', m_cam_no_probe, 'V32 камера act-stage: нет промера камеры'),
    ('обёртка камеры — элемент', m_cam_is_element, 'V32 камера act-stage: обёртка камеры — элемент .el'),
    ('надпись за кадром при камере', m_cam_text_out, 'V3 полотно: #act-stage--label'),
    ('hide: скрытый элемент виден', h_hidden_seen, 'V33 hide: #act-sign--head виден', HIDE_FILM),
    ('hide: сборка устарела', h_stale_build, 'V33 hide: сборка скрыла', HIDE_FILM),
    ('hide: неизвестный элемент', h_unknown, 'V33 hide: «nope» нет ни в одной сцене', HIDE_FILM),
    ('сторож: заглушка текста в кадре', g_placeholder_frame, 'V34 сторож текста [текст-заглушка]: в кадре сцены act-sign'),
    ('сторож: заглушка текста в разметке', g_placeholder_markup, 'V34 сторож текста [текст-заглушка]: в разметке сцены act-sign'),
    ('сторож: время цифрами в сцене с часами', g_time_frame, 'V34 сторож текста [время цифрами]: в кадре сцены act-stage'),
    ('сторож: время цифрами в тексте раскадровки', g_time_storyboard_text, 'V34 сторож текста [время цифрами]: в разметке сцены act-stage'),
    ('вывеска ярче трети', d_bright, 'V35 тусклая вывеска #act-sign--sign-dim: непрозрачность 0.45'),
    ('буквы вывески вспыхивают ярче трети', d_flicker_bright, 'V35 тусклая вывеска #act-sign--sign-dim: непрозрачность 0.45'),
    ('вывеска видна меньше 2 с', d_short, 'V35 тусклая вывеска #act-sign--sign-dim: видна'),
    ('исключение на неизвестный элемент', d_unknown, 'V35 исключение «act-sign:nope»: такого элемента'),
    ('исключение не на ту вывеску', d_wrong_name, 'V9 последний кадр act-sign: #act-sign--sign-dim на 0.20'),
]

SAMPLES = [
    ('каркас виден внутри окна шва', s_frame_in_seam),
    ('законные надписи: строка-исключение и время вне сцены с часами', s_legit_texts),
    ('тусклая вывеска мигает до 0,3', s_dim_flicker),
    ('часы: старт на сутки раньше — то же время', s_clock_day_before),
    ('часы: предыстория внесена в старт — то же время', s_clock_lead_into_start),
    ('камера: парение ровно на пороге', s_drift_at_limit),
    ('немая строка: дрожь полосок меньше допуска', s_silent_bars_noise),
]


# ---------------------------------------------------------------- медленные: копия проекта, пересборка страницы
def _json_edit(path, fn):
    data = C.load_json(path)
    fn(data)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)


def _sb_edit(pd, scene, fn):
    _json_edit(os.path.join(pd, 'scenes', scene, 'storyboard.json'), fn)


def p_unknown_motion(pd):
    _sb_edit(pd, ST, lambda sb: sb['plugins']['act']['cues'][1].__setitem__('motion', 'nope'))


def p_cam_pos_missing(pd):
    p = os.path.join(pd, 'scenes', ST, 'markup.html')
    with open(p, encoding='utf-8') as fh:
        txt = fh.read()
    with open(p, 'w', encoding='utf-8') as fh:
        fh.write(re.sub(r'<div class="cam-pos" data-cam="wide"[^>]*></div>', '', txt))


def p_cam_pos_aspect(pd):
    p = os.path.join(pd, 'scenes', ST, 'markup.html')
    with open(p, encoding='utf-8') as fh:
        txt = fh.read()
    with open(p, 'w', encoding='utf-8') as fh:
        fh.write(txt.replace('width:1440px; height:810px;', 'width:1440px; height:600px;', 1))


def p_cue_twice(pd):
    _sb_edit(pd, ST, lambda sb: sb['plugins']['act']['cues'][2].__setitem__('id', 'c02'))


def p_hide_unknown(pd):
    _json_edit(os.path.join(pd, 'films', HIDE_FILM + '.json'), lambda f: f.__setitem__('hide', f['hide'] + ['nope']))


def p_silent_with_file(pd):
    def fn(f):
        for r in f['replies']:
            if r.get('silent'):
                r['file'] = 'demo-audio/131.mp3'
    _json_edit(os.path.join(pd, 'films', FILM + '.json'), fn)


def p_silent_no_ms(pd):
    def fn(f):
        for r in f['replies']:
            if r.get('silent'):
                r.pop('ms')
    _json_edit(os.path.join(pd, 'films', FILM + '.json'), fn)


def p_frameless_first(pd):
    """Обратный стык: сцена без каркаса раньше сцены с каркасом — каркас наплывает на шве, проверка зелёная."""
    def fn(f):
        f['scenes'] = [SG, ST]
        f['replies'] = [r for r in f['replies'] if r['scene'] == SG] + [r for r in f['replies'] if r['scene'] == ST]
    _json_edit(os.path.join(pd, 'films', FILM + '.json'), fn)
    _sb_edit(pd, SG, lambda sb: sb['beats'][0].__setitem__('offset', -0.3))      # первая сцена: до начала фильма не войти

    def second(sb):          # вторая сцена: подпись входит в паузе шва (V7), часы — после ухода строк первой (V10)
        sb['beats'][0].update(offset=-1.55, targets=['label'])
        sb['beats'].insert(1, {'reply': 1, 'at': 0, 'offset': -0.3, 'action': 'show', 'targets': ['clock'], 'anim': 'fade'})
    _sb_edit(pd, ST, second)


def p_start_later(pd):
    _json_edit(os.path.join(pd, 'project.json'), lambda p: p['wall_clock'].__setitem__('start', '2030-01-15T18:10:00+03:00'))


RED_SLOW = [
    ('неизвестное motion — отказ сборки', p_unknown_motion, 'motion «nope» нет в tokens.json motion.act', FILM),
    ('положения камеры нет в разметке', p_cam_pos_missing, 'камера — положений wide нет в разметке сцены', FILM),
    ('положение камеры не в пропорциях кадра', p_cam_pos_aspect, 'не в пропорциях кадра', FILM),
    ('метка act повторяется', p_cue_twice, 'act — метка c02 повторяется', FILM),
    ('hide на неизвестный элемент — отказ', p_hide_unknown, 'films "hide": элемента «nope» нет ни в одной сцене', HIDE_FILM),
    ('немая строка с файлом — отказ сборки', p_silent_with_file, 'Немая строка 901', FILM),
    ('немая строка без ms — отказ сборки', p_silent_no_ms, 'Немая строка 901', FILM),
]
SAMPLES_SLOW = [
    ('старт +10 мин: часы пересчитаны', p_start_later, 'OK   V30', FILM),
    ('сцена без каркаса раньше сцены с каркасом', p_frameless_first, 'OK   V26', FILM),
]


# ---------------------------------------------------------------- прогон
def _calibrated(film, only):
    if film != FILM or only:
        print('Порчи калиброваны на фильме-фикстуре целиком: check.py %s --red | --samples | --red-slow' % FILM)
        return False
    return True


def _bases(root, out_dir):
    hide_dir = os.path.join(os.path.dirname(out_dir), HIDE_FILM)
    if not os.path.exists(os.path.join(hide_dir, 'probe.json')):      # вариант ещё не собран — собрать его страницу
        print('страницы %s нет — собираю: build.py %s --page' % (HIDE_FILM, HIDE_FILM))
        r = subprocess.run([sys.executable, os.path.join(HERE, 'build.py'), HIDE_FILM, '--page', '--project', str(root)],
                           capture_output=True, text=True, encoding='utf-8', errors='replace')
        if r.returncode or not os.path.exists(os.path.join(hide_dir, 'probe.json')):
            print('сборка %s упала: %s' % (HIDE_FILM, (r.stdout + r.stderr).strip()[-400:]))
            return None
    a = redrun.base(root, out_dir, 'Исходный фильм %s' % os.path.basename(out_dir))
    b = redrun.base(root, hide_dir, 'Исходный фильм %s' % os.path.basename(hide_dir))
    return None if a is None or b is None else {FILM: a, HIDE_FILM: b}


def red_fast(root, out_dir, film, only, filt=None):
    if not _calibrated(film, only):
        return 1
    bases = _bases(root, out_dir)
    if bases is None:
        return 1
    return redrun.fast(RED_FAST, lambda row: bases[row[3] if len(row) > 3 else FILM], filt)


def samples(root, out_dir, film, only, filt=None):
    if not _calibrated(film, only):
        return 1
    bases = _bases(root, out_dir)
    if bases is None:
        return 1
    return redrun.samples(SAMPLES, bases[FILM], filt)


def _copy_project(root, dst):
    shutil.copytree(root, dst, ignore=shutil.ignore_patterns('out', 'node_modules', '.env', '__pycache__', 'music', 'director'))


def _slow_build(root, fn, film):
    tmp = tempfile.mkdtemp(prefix='motion_slow_')
    try:
        pd = os.path.join(tmp, 'project')
        _copy_project(root, pd)
        fn(pd)
        od = os.path.join(pd, 'out', film)
        r = subprocess.run([sys.executable, os.path.join(HERE, 'build.py'), film, '--page', '--project', pd, '--out-dir', od],
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
    return redrun.slow(RED_SLOW, SAMPLES_SLOW, lambda row: _slow_build(root, row[1], row[3]), lambda row: row[2], filt)
