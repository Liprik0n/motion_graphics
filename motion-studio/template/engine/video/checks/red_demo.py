# -*- coding: utf-8 -*-
"""Порчи и образцы ядра проверок (check.py), калиброванные на демо-фильме шаблона films/demo.json:
сцены demo-a → demo-b, реплики 1–4, элементы step1…step8, bell, legend, band, lead, card1…card4, plaque.

Каждая порча — кортеж (имя, порча, подстрока): засчитана, только если покраснела ИМЕННО строка с этой
подстрокой. Образец — (имя, правка): законный вариант на грани порога, обязан пройти молча (код 0).

    быстрые (RED_FAST, SAMPLES): правка probe.json / film.json / конфигов в памяти или копии сцен — секунды
    медленные (RED_SLOW, SAMPLES_SLOW): копия проекта → правка раскадровки / разметки / rows / text →
    build.py --page на копии (или новый промер копии страницы) → check; поставка не трогается

Литералы тематики (сторож V19) записаны здесь \\u-кодами: сторож сканирует и этот файл.
"""
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # engine/video
sys.path.insert(0, HERE)
import check as C      # noqa: E402
sys.path.insert(0, os.path.dirname(HERE))
import chrome_lock     # noqa: E402  замок безголового Chrome

A, B = 'demo-a', 'demo-b'
# слова тематики для порч сторожа — кодами, чтобы этот файл сам не был находкой
W_NAME_F = '\u0417\u043b\u0430\u0442\u0430'                  # имя ведущей прошлого ролика (вымышленное, checks/theme_guard.json)
W_NAME_M = '\u0422\u0438\u0445\u043e\u043d\u043e\u043c'      # имя ведущего, творительный
W_BRAND = '\u0420\u043e\u043c\u0430\u0448\u043a\u0430-\u0421\u0435\u0440\u0432\u0438\u0441'
W_OBJ = '\u041a\u0421-12'
W_WINTER = '\u043e\u0441\u0435\u043d\u043d\u0438\u0439'      # сезон
W_TREE = '\u0441\u0430\u043c\u043e\u0432\u0430\u0440'      # предмет
W_LAT = 'vo-' + 't' + 'ikhon'


# ---------------------------------------------------------------- помощники
def _rep(ctx, n):
    return C.reply_of(ctx, n)


def _beat(ctx, scene, pred, i=0):
    for s, sb in C.storyboards(ctx):
        if s['id'] == scene:
            for b in sb['beats']:
                if pred(b):
                    return b, C.beat_t(ctx, b, i)
    raise KeyError('нет бита в %s — демо изменилось, обнови порчу' % scene)


def _smp(ctx, t):
    s = C.sample_at(ctx, t)
    if s is None:
        raise KeyError('нет кадра t=%.3f — демо изменилось, обнови порчу' % t)
    return s


def _it(sample, ident):
    it = C.item_of(sample, ident)
    if it is None:
        raise KeyError('нет #%s в t=%.3f — демо изменилось, обнови порчу' % (ident, sample['t']))
    return it


def _items(ctx, ident, t0=-1.0, t1=1e9):
    for s in ctx['probe']['samples']:
        if t0 <= s['t'] <= t1:
            for it in s['items']:
                if it['id'] == ident:
                    yield s, it


def _seam(ctx, which):
    seam = ctx['probe']['seams'][0]
    return [s for s in ctx['probe']['samples'] if abs(s['t'] - seam[which]) < 1e-4][0]


def _seam_t(ctx, frac):
    a, b = ctx['film']['scenes'][0], ctx['film']['scenes'][1]
    return C.q(ctx, a['last'] + frac * (b['first'] - a['last']))


def _scenes_copy(ctx, tmp):
    sd = os.path.join(tmp, 'scenes')
    shutil.copytree(ctx['scenes_dir'], sd)
    ctx['scenes_dir'] = sd
    return sd


def _edit(path, old, new):
    with open(path, encoding='utf-8') as fh:
        txt = fh.read()
    if txt.count(old) != 1:
        raise SystemExit('порча: в %s нет ровно одного «%s» — демо изменилось, обнови порчу' % (path, old[:60]))
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(txt.replace(old, new))


def _sb_edit(sd, scene, fn):
    p = os.path.join(sd, scene, 'storyboard.json')
    sb = C.load_json(p)
    fn(sb)
    with open(p, 'w', encoding='utf-8') as fh:
        json.dump(sb, fh, ensure_ascii=False, indent=1)


def _screen_source(ctx):
    """Текст-источник, собранный из того, что видно на экране демо (надписи по сценам)."""
    out = {}
    for s in ctx['probe']['samples']:
        for it in s['items']:
            if it['opacity'] > C.VISIBLE:
                sc = it['scene'] or s['scene']
                for t in it['texts']:
                    if C.norm(t):
                        out.setdefault(sc, set()).add(C.norm(t))
    return {k: ' ¶ '.join(sorted(v)) for k, v in out.items()}


def _orb(ctx, rect, t0, t1, scene=B, ident='orb', fade=None):
    """Вставить предмет без надписи (иконку) в кадры t0…t1; fade — (t, непрозрачность) после окна."""
    for s in ctx['probe']['samples']:
        op = None
        if t0 <= s['t'] <= t1:
            op = 1.0
        elif fade and t1 < s['t'] <= fade[0]:
            op = fade[1]
        if op is not None:
            s['items'].append({'id': '%s--%s' % (scene, ident), 'kind': 'content', 'segs': [], 'fills': [], 'scene': scene,
                               'rect': list(rect), 'opacity': op, 'z': 2, 'layer': None, 'rot': 0, 'scale': 1,
                               'dash': None, 'texts': []})


# ---------------------------------------------------------------- V1–V3
def m_page_short(ctx, tmp):
    ctx['film']['duration'] -= 0.5


def m_beat_past_end(ctx, tmp):
    sd = _scenes_copy(ctx, tmp)
    _sb_edit(sd, B, lambda sb: sb['beats'].append({'reply': 4, 'at': 1, 'offset': 1.5, 'action': 'emph', 'targets': ['card1']}))


def m_round_bankers(ctx, tmp):
    ctx['probe']['round_rule'] = [[t, round(t * 30) / 30] for t, _ in ctx['probe']['round_rule']]


def m_page_error(ctx, tmp):
    ctx['probe']['errors'] = ['ReferenceError: stagePlugin is not defined']


def m_drop_reply(ctx, tmp):
    ctx['film']['replies'] = [r for r in ctx['film']['replies'] if r['n'] != 2]


def m_stretch_reply(ctx, tmp):
    _rep(ctx, 3)['end'] += 0.2


def m_overlap(ctx, tmp):
    r, a = _rep(ctx, 2), _rep(ctx, 1)
    sh = r['start'] - (a['end'] - 0.3)
    r['start'] -= sh
    r['end'] -= sh


def m_no_frame(ctx, tmp):
    for s in ctx['probe']['samples']:
        if s.get('reply') == 4:
            s['reply'] = None


def m_voice_swap(ctx, tmp):
    _rep(ctx, 1)['voice'] = voice_id(ctx, 1)


def m_off_canvas(ctx, tmp):
    _it(_smp(ctx, _rep(ctx, 2)['end'] - 0.5), A + '--step3')['rect'][0] = 1900


# ---------------------------------------------------------------- V4 текст = источник
def m_src_missing(ctx, tmp):
    src = _screen_source(ctx)
    src[B] = src[B].replace('Ответственный за данные', '')
    ctx['source'] = src


def m_src_title(ctx, tmp):
    ctx['source'] = _screen_source(ctx)
    for s, it in _items(ctx, 'title--' + B):
        it['texts'] = ['Кому сообщить']


def m_src_no_scene(ctx, tmp):
    src = _screen_source(ctx)
    del src[B]
    ctx['source'] = src


def s_src_full(ctx, tmp):
    ctx['source'] = _screen_source(ctx)


def s_src_wider(ctx, tmp):
    """Источник длиннее экрана: надпись — дословный фрагмент абзаца."""
    src = _screen_source(ctx)
    ctx['source'] = {k: 'Вступление абзаца. ' + v + ' И ещё фраза источника.' for k, v in src.items()}


# ---------------------------------------------------------------- V5 стык
def m_state(ctx, tmp):
    ctx['film']['scenes'][1]['start_state'] = {'layout': 'big'}


def m_state_stale(ctx, tmp):
    ctx['film']['scenes'][0]['end_state'] = {'layout': 'side'}
    ctx['film']['scenes'][1]['start_state'] = {'layout': 'side'}


def m_frame_moved(ctx, tmp):
    _it(_seam(ctx, 'first'), 'fr-footer')['rect'][1] += 5


def m_frame_gone(ctx, tmp):
    s = _seam(ctx, 'last')
    s['items'] = [i for i in s['items'] if i['id'] != 'tr-2']


# ---------------------------------------------------------------- V6 раскадровка
def _move_end(ctx, tg):
    b, t0 = _beat(ctx, A, lambda b: b['action'] == 'move' and b['targets'] == [tg])
    return _smp(ctx, t0 + b.get('dur', 0.7) + 2 * C.FR(ctx))['anchors'][A + ':' + tg]


def m_move_off(ctx, tmp):
    _move_end(ctx, 'step1.text')['rect'][0] += 8


def m_move_color(ctx, tmp):
    _move_end(ctx, 'step1.text')['color'] = 'rgb(56, 59, 62)'


def m_move_stuck(ctx, tmp):
    m = [x for x in ctx['probe']['moves'] if x['node'] == A + ':bell'][0]
    _move_end(ctx, 'bell')['rect'] = list(m['anchor0'])


def m_move_size(ctx, tmp):
    _move_end(ctx, 'band')['rect'][3] *= 1.1


def m_move_two_lines(ctx, tmp):
    b, t0 = _beat(ctx, A, lambda b: b['action'] == 'move' and b['targets'] == ['step1.text'])
    m = [x for x in ctx['probe']['moves'] if x['node'] == A + ':step1.text'][0]
    a = m['anchor0']
    m['anchor0'] = [a[0], a[1], a[2] * 0.55, a[3] * 2]
    _move_end(ctx, 'step1.text')['rect'] = C.move_expect(ctx, b, m)


def m_lift_flat(ctx, tmp):
    b, t0 = _beat(ctx, A, lambda b: b['action'] == 'hide' and 'step2' in b['targets'], i=6)
    base = _it(_smp(ctx, t0 - C.FR(ctx)), A + '--step2')['rect'][1]
    _it(_smp(ctx, t0 + 0.8 * C.anim_dur(ctx, 'lift')), A + '--step2')['rect'][1] = base


def m_cut_fades(ctx, tmp):
    b, t0 = _beat(ctx, A, lambda b: b.get('anim') == 'cut')
    s = _smp(ctx, t0 + C.FR(ctx))
    it = copy.deepcopy(_it(_smp(ctx, t0 - C.FR(ctx)), A + '--step1'))
    it['opacity'] = 0.5
    s['items'] = [i for i in s['items'] if i['id'] != it['id']] + [it]


def m_show_cut_late(ctx, tmp):
    b, t0 = _beat(ctx, B, lambda b: b.get('anim') == 'cut')
    s = _smp(ctx, t0 + C.FR(ctx))
    s['items'] = [i for i in s['items'] if i['id'] != B + '--bell']


def m_level_wrong(ctx, tmp):
    b, t0 = _beat(ctx, B, lambda b: b['action'] == 'level' and b['value'] == 0.45)
    _it(_smp(ctx, t0 + 0.5 + 2 * C.FR(ctx)), B + '--card1')['opacity'] = 0.8


def m_show_level_ink(ctx, tmp):
    b, t0 = _beat(ctx, B, lambda b: b['action'] == 'show' and b.get('level') == 0.2, i=1)
    _it(_smp(ctx, t0 + C.anim_dur(ctx, 'rise') + 2 * C.FR(ctx)), B + '--card2')['opacity'] = 1.0


def m_ring_still(ctx, tmp):
    b, t0 = _beat(ctx, A, lambda b: b.get('style') == 'ring')
    _it(_smp(ctx, t0 + 0.2 * b.get('dur', 0.8)), A + '--bell')['rot'] = 0.0


def m_pulse_amp(ctx, tmp):
    b, t0 = _beat(ctx, B, lambda b: b['action'] == 'emph' and b['targets'] == ['plaque'])
    _it(_smp(ctx, t0 + 0.5 * b.get('dur', 0.8)), B + '--plaque')['scale'] = 1.06


def m_breathe_flat(ctx, tmp):
    b, t0 = _beat(ctx, B, lambda b: b.get('style') == 'breathe')
    _it(_smp(ctx, t0 + C.mo(ctx, 'breathe')['period'] / 2), B + '--card1')['scale'] = 1.0


def m_title_early(ctx, tmp):
    for s, sb in C.storyboards(ctx):
        if sb.get('title_at'):
            smp = _smp(ctx, C.beat_t(ctx, sb['title_at']) - C.FR(ctx))
            it = next(x for _, x in _items(ctx, 'title--' + s['id']) if x['opacity'] >= C.FULL)
            smp['items'].append(dict(copy.deepcopy(it), opacity=1.0))
            return


def m_chapter_stays(ctx, tmp):
    for s, sb in C.storyboards(ctx):
        if sb.get('chapter_at'):
            smp = _smp(ctx, C.beat_t(ctx, sb['chapter_at']) + C.mo(ctx, 'chapter_dur') + 2 * C.FR(ctx))
            k = C.chapter_index(ctx, sb['chapter_from'])
            smp['tracker'][k] = dict(smp['tracker'][k], opacity=1.0, fill=[0.0, 100.0])
            return


def m_chapter_fade(ctx, tmp):
    for s, sb in C.storyboards(ctx):
        if sb.get('chapter_at'):
            smp = _smp(ctx, C.beat_t(ctx, sb['chapter_at']) + C.mo(ctx, 'chapter_dur') / 2)
            for x in smp['tracker']:
                if x['opacity'] > C.VISIBLE:
                    x['opacity'] = 0.5
            return


# ---------------------------------------------------------------- V7–V9
def m_seam_empty(ctx, tmp):
    s = _smp(ctx, _seam_t(ctx, 0.5))
    s['items'] = [i for i in s['items'] if i['kind'] != 'content']


def m_seam_no_frame(ctx, tmp):
    t = _seam_t(ctx, 0.3)
    ctx['probe']['samples'] = [s for s in ctx['probe']['samples'] if abs(s['t'] - t) > 1e-3]


def m_layer_flat(ctx, tmp):
    for s, it in _items(ctx, A + '--band'):
        it['z'] = 2


def m_layer_markup(ctx, tmp):
    sd = _scenes_copy(ctx, tmp)
    _edit(os.path.join(sd, A, 'markup.html'), 'id="legend"', 'id="legend" data-layer="under"')


def _last(ctx, scene):
    s = [x for x in ctx['film']['scenes'] if x['id'] == scene][0]
    return _smp(ctx, s['last'])


def m_under_left(ctx, tmp):
    s = _last(ctx, A)
    band = copy.deepcopy(next(it for _, it in _items(ctx, A + '--band')))
    band['opacity'] = 0.6
    s['items'] = [i for i in s['items'] if i['id'] != band['id']] + [band]


def m_dim_end(ctx, tmp):
    _it(_last(ctx, B), B + '--card2')['opacity'] = 0.45


def m_text_gone_end(ctx, tmp):
    s = _last(ctx, B)
    s['items'] = [i for i in s['items'] if i['id'] != B + '--plaque']


# ---------------------------------------------------------------- V10 надписи
def _mid4(ctx):
    r = _rep(ctx, 4)
    return _smp(ctx, (r['start'] + r['end']) / 2)


def m_text_overlap(ctx, tmp):
    s = _mid4(ctx)
    g1 = _it(s, B + '--card1')['segs'][0]
    c2 = _it(s, B + '--card2')
    c2['segs'][0][:4] = [g1[0] + 10, g1[1], g1[2], g1[3]]


def m_line_out(ctx, tmp):
    s = _mid4(ctx)
    it = _it(s, B + '--card3')
    it['segs'][0][0] = it['rect'][0] + it['rect'][2] - 20


def m_fly_covers(ctx, tmp):
    b, t0 = _beat(ctx, A, lambda b: b['action'] == 'move' and b['targets'] == ['bell'])
    s = _smp(ctx, t0 + 0.3)
    g = _it(s, A + '--step1')['segs']
    mv = [x for x in g if x[5]][0]
    _it(s, A + '--bell')['rect'] = [mv[0] + 20, mv[1], 42.0, 30.0]


def voice_id(ctx, i):
    """id голоса рамки — project.json voice_bars.voices[i].id: порча не знает имён голосов проекта."""
    vs = (ctx['project'].get('voice_bars') or {}).get('voices') or []
    if len(vs) <= i:
        raise KeyError('в project.json voice_bars.voices нет голоса №%d — порче не на чем стоять' % i)
    return vs[i]['id']


def voice0(ctx):
    return voice_id(ctx, 0)


def expect_of(ctx, expect):
    """Ожидаемая подстрока с подстановкой {voice0}, {voice1} — id голосов из конфига проекта."""
    for i in (0, 1):
        tag = '{voice%d}' % i
        if tag in expect:
            expect = expect.replace(tag, voice_id(ctx, i))
    return expect


def m_voice_covers(ctx, tmp):
    x, y, w, h = ctx['project']['frame']['footer']['box']
    k = C.PX(ctx)
    hit = 0
    for s, it in _items(ctx, 'vo-' + voice0(ctx)):
        it['rect'] = [x * k + 10.0, y * k, 148.8, h * k - 0.0]     # группа голоса — на строке футера
        it['segs'] = []
        hit += 1
    if not hit:
        raise KeyError('в промере нет #vo-%s — демо изменилось, обнови порчу' % voice0(ctx))


def m_seam_under_fill(ctx, tmp):
    s = _smp(ctx, _seam_t(ctx, 0.8))
    g = [x for x in _it(s, A + '--step1')['segs'] if x[4] > 0.5][-1]
    _it(s, B + '--card1')['fills'].append([g[0], g[1] - 5, g[2], g[3] + 10, 0.8, 'rgb(47, 111, 168)'])


def m_seam_shade_line(ctx, tmp):
    t = C.beat_t(ctx, {'reply': 3, 'at': 0.0, 'offset': -0.25}) + 0.1
    s = _smp(ctx, t)
    g = [x for x in _it(s, B + '--lead')['segs'] if x[4] > 0.5][0]
    _it(s, B + '--card1')['segs'].append([g[0] + 5, g[1], 80.0, g[3], 0.2, 0])


# ---------------------------------------------------------------- V11–V12
def m_font_error(ctx, tmp):
    for f in ctx['probe']['fonts']:
        f['status'] = 'error'


def m_font_absent(ctx, tmp):
    ctx['probe']['fonts'] = [{'family': 'Times New Roman', 'weight': '400', 'status': 'loaded'}]


def m_font_synth(ctx, tmp):
    for v in ctx['probe']['frameStyle'].values():
        v['synthesis'] = 'weight style'


def m_page_hex(ctx, tmp):
    p = os.path.join(tmp, 'index.html')
    shutil.copyfile(ctx['page'], p)
    _edit(p, 'id="demo-a--legend"', 'id="demo-a--legend" data-x="1" style2="color:#FF00FF"')
    ctx['page'] = p


def m_fill_color(ctx, tmp):
    for s, it in _items(ctx, B + '--card1'):
        for fl in it['fills']:
            fl[5] = 'rgb(255, 0, 0)'


def m_kind_color(ctx, tmp):
    ctx['probe']['kinds'][A + '--step1']['parts']['text']['color'] = 'rgb(17, 17, 17)'


# ---------------------------------------------------------------- V13 спутники
def _sat_quiet(ctx, node, t0, t1):
    for s in ctx['probe']['samples']:
        rec = (s.get('sats') or {}).get(node)
        if t0 <= s['t'] <= t1 and rec and rec['op'] > 0.5 and rec['hop'] > 0.5 and not rec['own']:
            return s, rec
    raise KeyError('нет спокойного кадра спутника %s' % node)


def m_sat_drift(ctx, tmp):
    s, rec = _sat_quiet(ctx, A + ':bell', 10.0, 11.0)
    rec['local'][0] += 3


def m_sat_missing(ctx, tmp):
    s, rec = _sat_quiet(ctx, B + ':bell', 15.0, 18.0)
    del s['sats'][B + ':bell']


def m_sat_wrong(ctx, tmp):
    s, rec = _sat_quiet(ctx, B + ':bell', 15.0, 18.0)
    rec['host'] = B + '--card1'


def m_sat_undeclared(ctx, tmp):
    sd = _scenes_copy(ctx, tmp)
    _sb_edit(sd, A, lambda sb: [e.pop('with') for e in sb['elements'] if e['id'] == 'bell'])


# ---------------------------------------------------------------- V14 уровень
def _trace(ctx, dom):
    return [x for x in ctx['probe']['levelTrace'] if x['dom'] == dom]


def m_level_jump(ctx, tmp):
    x = _trace(ctx, A + '--step1')[0]
    k = len(x['ops']) // 2
    x['ops'][k] = [min(1.0, v + 0.3) for v in x['ops'][k]]


def m_trace_missing(ctx, tmp):
    ctx['probe']['levelTrace'] = [x for x in ctx['probe']['levelTrace'] if x['dom'] != B + '--card1']


def m_trace_short(ctx, tmp):
    x = _trace(ctx, B + '--card2')[0]
    x['ops'] = x['ops'][:3]


# ---------------------------------------------------------------- V15 без опоры
def m_hang_orb(ctx, tmp):
    _orb(ctx, [1400.0, 330.0, 40.0, 40.0], 15.0, 16.6)


def m_hang_host_gone(ctx, tmp):
    for s, it in _items(ctx, A + '--step1', 10.1, 11.4):
        it['opacity'] = 0.0
        for g in it['segs']:
            g[4] = 0.0
        it['fills'] = []


def s_hang_short(ctx, tmp):
    """Предмет без опоры 0,8 с (порог 1 с) и уходит наплывом."""
    _orb(ctx, [1400.0, 330.0, 40.0, 40.0], 15.0, 15.8, fade=(16.0, 0.25))


def s_hang_on_plaque(ctx, tmp):
    """Предмет 1,6 с стоит на плашке — опора есть."""
    pl = _it(_mid4(ctx), B + '--plaque')['rect']
    _orb(ctx, [pl[0] + pl[2] - 60, pl[1] + 20, 40.0, 40.0], _rep(ctx, 4)['start'], 99.0)


# ---------------------------------------------------------------- V25 поза
def _limbs(ctx, raised_from, down_hidden=True, up_ever=True):
    """Герой сцены B с размеченной правой рукой: до raised_from рука опущена, после — поднята.
    down_hidden — опущенная скрыта, пока поднята другая; up_ever — поднятая хоть раз видна."""
    for smp in ctx['probe']['samples']:
        raised = smp['t'] >= raised_from
        smp['limbs'] = [
            {'who': 'geroj', 'side': 'right', 'pos': 'up', 'el': B + '--card1', 'scene': B, 'seen': raised and up_ever},
            {'who': 'geroj', 'side': 'right', 'pos': 'down', 'el': B + '--card1', 'scene': B, 'seen': (not raised) or not down_hidden},
            {'who': 'geroj', 'side': 'left', 'pos': 'down', 'el': B + '--card1', 'scene': B, 'seen': True}]


def m_pose_third_arm(ctx, tmp):
    """Рука поднята, а опущенная той же стороны осталась нарисованной — третья рука."""
    _limbs(ctx, _rep(ctx, 4)['start'], down_hidden=False)


def m_pose_never_up(ctx, tmp):
    """Поднятая рука объявлена, но ни в одном кадре промера её нет: жест не попал в промер."""
    _limbs(ctx, _rep(ctx, 4)['start'], up_ever=False)


def m_pose_bad_tag(ctx, tmp):
    """Разметка конечности без положения."""
    _limbs(ctx, _rep(ctx, 4)['start'])
    for smp in ctx['probe']['samples']:
        smp['limbs'][0]['pos'] = 'vverh'


def s_pose_two_arms(ctx, tmp):
    """Рука поднята — опущенная той же стороны скрыта; левая всё время опущена: рук две."""
    _limbs(ctx, _rep(ctx, 4)['start'])


# ---------------------------------------------------------------- V16 двойник
def m_twin_text(ctx, tmp):
    b, t0 = _beat(ctx, A, lambda b: b['action'] == 'move' and b['targets'] == ['step1.text'])
    s = _smp(ctx, t0 + b['dur'] + 4 * C.FR(ctx))
    a = s['anchors'][A + ':step1.text']
    m = [x for x in ctx['probe']['moves'] if x['node'] == A + ':step1.text'][0]
    d = m['dest']
    _it(s, B + '--lead')['segs'].append([d[0], d[1], d[2], d[3], 1.0, 0])
    a['rect'][0] += 6


def m_twin_bell(ctx, tmp):
    s = _smp(ctx, _seam_t(ctx, 0.4))
    a = s['anchors'][A + ':bell']
    bell = copy.deepcopy(_it(s, A + '--bell'))
    bell.update(id=B + '--bell', scene=B, rect=[a['rect'][0] + 5, a['rect'][1], a['rect'][2], a['rect'][3]], opacity=1.0)
    s['items'] = [i for i in s['items'] if i['id'] != bell['id']] + [bell]


def s_twin_aligned(ctx, tmp):
    """Подмена кадр-в-кадр: цель видна вместе с мостом на кадр раньше, но точно на нём (сдвиг 0,6 px)."""
    s = _smp(ctx, _beat(ctx, B, lambda b: b.get('anim') == 'cut')[1] - C.FR(ctx))
    a = s['anchors'][A + ':bell']
    bell = copy.deepcopy(_it(s, A + '--bell'))
    bell.update(id=B + '--bell', scene=B, rect=[a['rect'][0] + 0.6, a['rect'][1], a['rect'][2], a['rect'][3]], opacity=1.0)
    s['items'] = [i for i in s['items'] if i['id'] != bell['id']] + [bell]


# ---------------------------------------------------------------- V17 порядок = речь
def _rows(ctx):
    return {n: t for n, t in C.speech_rows(ctx).items()}


def m_order_reversed(ctx, tmp):
    rows = _rows(ctx)
    rows[1] = 'Сначала разбор итогов, потом проверка данных.'
    ctx['rows'] = rows


def m_order_cards(ctx, tmp):
    rows = _rows(ctx)
    rows[3] = 'Сообщаете редактору, а уже потом руководителю группы.'
    ctx['rows'] = rows


def s_order_same(ctx, tmp):
    rows = _rows(ctx)
    rows[1] = 'Сначала проверка данных, потом согласование правок, затем сверка с источником.'
    ctx['rows'] = rows


def s_order_one_beat(ctx, tmp):
    """Пункты одного бита в одном кадре — порядок не нарушен, как бы их ни назвали."""
    rows = _rows(ctx)
    rows[2] = 'Повторная проверка и передача результата.'
    ctx['rows'] = rows
    t = None
    for s, it in _items(ctx, A + '--step6'):
        if it['opacity'] > C.TEXT_SEEN:
            t = s['t']
            break
    for s, it in _items(ctx, A + '--step7'):
        if s['t'] >= t - 1e-6:
            it['opacity'] = max(it['opacity'], 0.31)
            for g in it['segs']:
                g[4] = max(g[4], 0.31)


# ---------------------------------------------------------------- V18 текст кусками
def _card4_text(ctx, n):
    words = ('участники проекта работают с данными каждый день и отвечают за их сохранность ' * 4).split()[:n]
    for s, it in _items(ctx, B + '--card4'):
        it['texts'] = [' '.join(words)]


def m_chunk_30(ctx, tmp):
    _card4_text(ctx, 30)


def s_chunk_25(ctx, tmp):
    _card4_text(ctx, 25)


def m_chunk_line_then_rest(ctx, tmp):
    """40 слов в четырёх строках: кадром раньше видна одна строка (10 слов), затем остальные 30 разом."""
    _card4_text(ctx, 40)
    first = True
    for s, it in sorted(_items(ctx, B + '--card4'), key=lambda x: x[0]['t']):
        g = it['segs'][0] if it['segs'] else None
        if g is None:
            continue
        it['segs'] = [list(g[:1]) + [g[1] + k * 34.0] + list(g[2:]) for k in range(4)]
        if first and it['opacity'] > C.TEXT_SEEN and g[4] > C.TEXT_SEEN:
            it['segs'] = it['segs'][:1]
            first = False


def s_chunk_parts(ctx, tmp):
    """40 слов, но в кадре первого чтения видна одна строка из двух — кусками."""
    _card4_text(ctx, 40)
    for s, it in sorted(_items(ctx, B + '--card4'), key=lambda x: x[0]['t']):
        if it['opacity'] > C.TEXT_SEEN and any(g[4] > C.TEXT_SEEN for g in it['segs']):
            it['segs'] = it['segs'][:1]
            break


# ---------------------------------------------------------------- V19 сторож тематики
def _guard_file(ctx, tmp, name, text):
    d = os.path.join(tmp, 'guard')
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, name), 'w', encoding='utf-8') as fh:
        fh.write(text)
    ctx['guard_roots'] = [d]


def m_guard_name(ctx, tmp):
    _guard_file(ctx, tmp, 'markup.html', '<div class="el" id="host"><span class="t">%s</span></div>' % W_NAME_F)


def m_guard_name_m(ctx, tmp):
    _guard_file(ctx, tmp, 'rows.json', '[{"n": 1, "text": "Спроси у %s."}]' % W_NAME_M)


def m_guard_brand(ctx, tmp):
    _guard_file(ctx, tmp, 'project.json', '{"footer": "%s"}' % W_BRAND)


def m_guard_obj(ctx, tmp):
    _guard_file(ctx, tmp, 'notes.md', 'Объект %s.' % W_OBJ)


def m_guard_winter(ctx, tmp):
    _guard_file(ctx, tmp, 'stage.js', '// %s фон по умолчанию\nvar bg = 1;\n' % W_WINTER)


def m_guard_tree(ctx, tmp):
    _guard_file(ctx, tmp, 'tokens.json', '{"icon": "%s.svg"}' % W_TREE)


def m_guard_latin(ctx, tmp):
    _guard_file(ctx, tmp, 'build.py', "VOICE = '%s'\n" % W_LAT)


def m_guard_engine(ctx, tmp):
    """Литерал в копии движка: сторож обходит подпапки (lib/), а не только корень."""
    d = os.path.join(tmp, 'engine', 'video', 'lib')
    os.makedirs(d)
    shutil.copyfile(os.path.join(HERE, 'lib', 'stage.js'), os.path.join(d, 'stage.js'))
    with open(os.path.join(d, 'stage.js'), 'a', encoding='utf-8') as fh:
        fh.write('\n// %s\n' % W_TREE)
    ctx['guard_roots'] = [os.path.join(tmp, 'engine'), ctx['root']]


def s_guard_lookalikes(ctx, tmp):
    """Законные слова, внутри которых стоят запрещённые буквы: Златоуст, тихонько, ромашковый, такси-12, сосен,
    Zlatan, tikhonov — граница слова держит."""
    _guard_file(ctx, tmp, 'notes.md', 'город Златоуст; тихонько; ромашковый чай; такси-12; среди сосен; '
                'Zlatan; tikhonov; не трачим время\n')


def _esc_u(word):
    """Слово \\u-кодами JSON, как его пишет json.dumps(ensure_ascii=True)."""
    return ''.join(chr(92) + 'u%04x' % ord(c) for c in word)


def m_guard_json_escaped(ctx, tmp):
    """Литерал в rows.json записан \\u-кодами — по тексту файла не виден, по значению после разбора виден."""
    _guard_file(ctx, tmp, 'rows.json', '[{"n": 1, "text": "%s, %s"}]' % (_esc_u(W_NAME_F), _esc_u('коллега')))


# склейкой, чтобы сам этот файл (он под сторожем движка) не содержал слов подряд
def _guard_bom(ctx, tmp, text):
    d = os.path.join(tmp, 'guard', 'scenes', 'demo-a')
    os.makedirs(d)
    with open(os.path.join(d, 'notes.json'), 'w', encoding='utf-8-sig') as fh:     # с BOM, как PowerShell 5.1
        fh.write(text)
    ctx['guard_roots'] = [os.path.join(tmp, 'guard')]


def m_guard_json_bom(ctx, tmp):
    """Литерал \\u-кодами в .json с BOM: разбор по значениям обязан пройти, а не упасть молча."""
    _guard_bom(ctx, tmp, '{"host": "%s"}' % _esc_u(W_NAME_F))


def m_guard_json_broken(ctx, tmp):
    """.json, который не разбирается, — сторож не может доказать чистоту: красное, а не пропуск."""
    _guard_bom(ctx, tmp, '{"host": "%s",}' % _esc_u('ведущая'))


def s_guard_json_bom_clean(ctx, tmp):
    _guard_bom(ctx, tmp, '{"host": "%s"}' % _esc_u('ведущая'))


NEW_PROJECT_ROWS = ('[{"n": 1, "text": "' + 'Ос' + 'енние шины меняет мастер ' + 'Тих' + 'он."}, '
                    '{"n": 2, "text": "Чай заваривают в ' + 'сам' + 'оваре."}]')


def _new_project(ctx, tmp, demo):
    d = os.path.join(tmp, 'newproj')
    os.makedirs(d)
    with open(os.path.join(d, 'project.json'), 'w', encoding='utf-8') as fh:
        fh.write('{"title": "Новый ролик", "template_demo": %s}' % ('true' if demo else 'false'))
    with open(os.path.join(d, 'rows.json'), 'w', encoding='utf-8') as fh:
        fh.write(NEW_PROJECT_ROWS)
    ctx['guard_project'] = d


def s_guard_new_project(ctx, tmp):
    """Новый проект (template_demo false): законная лексика его роликов в данных — не дело сторожа шаблона."""
    _new_project(ctx, tmp, demo=False)


def m_guard_demo_data(ctx, tmp):
    """Те же данные с template_demo true — это демо шаблона, сторож смотрит и их."""
    _new_project(ctx, tmp, demo=True)


def s_guard_env(ctx, tmp):
    """Файл .env не читается никогда, даже если в нём литерал."""
    _guard_file(ctx, tmp, '.env', 'MINIMAX_VOICE_A=%s\n' % W_NAME_F)


def s_guard_allow(ctx, tmp):
    """Проект снял запрет по имени (project.json theme_allow) — слово по делу проходит."""
    _guard_file(ctx, tmp, 'storyboard.json', '{"notes": "%s пейзаж"}' % W_WINTER)
    ctx['project']['theme_allow'] = ['сезон прошлого ролика']


# ---------------------------------------------------------------- V20 переходы
def m_vanish(ctx, tmp):
    b, t0 = _beat(ctx, A, lambda b: b['action'] == 'move' and b['targets'] == ['step1.text'])
    t_cut = _beat(ctx, A, lambda b: b.get('anim') == 'cut')[1]
    for s in ctx['probe']['samples']:
        if t0 + b['dur'] + 2 * C.FR(ctx) < s['t'] < t_cut - C.FR(ctx):
            s['items'] = [i for i in s['items'] if i['id'] != A + '--step1']


def m_flicker(ctx, tmp):
    r = _rep(ctx, 4)
    s = _smp(ctx, r['start'] + 0.5 * (r['end'] - r['start']))
    _it(s, B + '--card2')['opacity'] = 0.0


def s_vanish_moving(ctx, tmp):
    """Метка-легенда уходит lift и обрывается на 80 % подъёма (едет > 2 px за кадр, видна на 0,57):
    исчезает под движением — законно."""
    b, t0 = _beat(ctx, A, lambda b: b['action'] == 'hide' and 'legend' in b['targets'], i=1)
    for s in ctx['probe']['samples']:
        if s['t'] > t0 + 0.8 * C.anim_dur(ctx, 'lift') + 1e-6 and s['t'] < t0 + 1.0:
            s['items'] = [i for i in s['items'] if i['id'] != A + '--legend']


def s_flicker_dip(ctx, tmp):
    """Провал непрозрачности до 0,5 — элемент не пропадал: не FLICKER."""
    r = _rep(ctx, 4)
    s = _smp(ctx, r['start'] + 0.5 * (r['end'] - r['start']))
    _it(s, B + '--card2')['opacity'] = 0.5


# (имя, порча, подстрока, которой обязана покраснеть проверка)
RED_FAST = [
    ('страница короче звука', m_page_short, 'а последняя реплика кончается'),
    ('хвост не дотянут до бита', m_beat_past_end, 'а последний бит раскадровки кончается'),
    ('округление промера банковское', m_round_bankers, 'округляют время в кадр по-разному'),
    ('ошибка на странице', m_page_error, 'V1 страница: ошибка в промере страницы'),
    ('реплика выпала', m_drop_reply, 'V2 реплика №2 из звука фильма не попала в ролик'),
    ('реплика длиннее mp3', m_stretch_reply, 'V2 реплика №3: в ролике'),
    ('реплики наложились', m_overlap, 'V2 реплики №1 и №2 накладываются'),
    ('у реплики нет кадра', m_no_frame, 'V2 реплика №4: нет ни одного кадра'),
    ('чужой голос', m_voice_swap, 'V2 реплика №1: в ролике голос {voice1}'),
    ('элемент за полотном', m_off_canvas, 'V3 полотно: #demo-a--step3'),
    ('надписи нет в источнике', m_src_missing, 'V4 текст: «Ответственный за данные» (#demo-b--card2) нет в источнике'),
    ('заголовок не из источника', m_src_title, 'V4 текст: «Кому сообщить»'),
    ('у сцены нет источника', m_src_no_scene, 'V4 текст: у сцены demo-b нет источника'),
    ('конец ≠ начало', m_state, 'V5 стык demo-a → demo-b: конец'),
    ('состояния устарели', m_state_stale, 'V5 раскадровка demo-a: состояния в сборке устарели'),
    ('каркас сдвинулся', m_frame_moved, 'V5 стык demo-a → demo-b: каркас #fr-footer сдвинулся'),
    ('каркас пропал', m_frame_gone, 'V5 стык demo-a → demo-b: каркас #tr-2 пропал'),
    ('move: текст мимо подстроки', m_move_off, 'V6 move #demo-a--step1.text: в t='),
    ('move: цвет не доехал', m_move_color, 'V6 move #demo-a--step1.text: цвет в конце'),
    ('move: колокольчик не поехал', m_move_stuck, 'V6 move #demo-a--bell: в t='),
    ('move: рамка не того размера', m_move_size, 'V6 move #demo-a--band: в t='),
    ('move: текст в две строки', m_move_two_lines, 'V6 move #demo-a--step1.text: текст не лёг буквы на буквы'),
    ('lift без подъёма', m_lift_flat, 'V6 lift hide #demo-a--step2'),
    ('cut наплывом', m_cut_fades, 'V6 cut hide #demo-a--step1'),
    ('show cut опоздал', m_show_cut_late, 'V6 cut show #demo-b--bell'),
    ('level не тот', m_level_wrong, 'V6 level #demo-b--card1'),
    ('тень вошла чернилами', m_show_level_ink, 'V6 show level #demo-b--card2'),
    ('звон без качания', m_ring_still, 'V6 ring #demo-a--bell'),
    ('пульс со старой амплитудой', m_pulse_amp, 'V6 pulse #demo-b--plaque'),
    ('дыхание без вдоха', m_breathe_flat, 'V6 breathe #demo-b--card1: на вдохе'),
    ('заголовок раньше бита', m_title_early, 'V6 title_at demo-a: заголовок виден до своего бита'),
    ('глава не сменилась', m_chapter_stays, 'V6 chapter_at demo-a: в t='),
    ('заливка главы наплывом', m_chapter_fade, 'V6 chapter_at demo-a: на полпути заливка наплывает'),
    ('пустой кадр на шве', m_seam_empty, 'V7 шов demo-a → demo-b: рабочая зона пуста'),
    ('кадр шва не промерен', m_seam_no_frame, 'V7 шов demo-a → demo-b: нет промера'),
    ('слой under не применён', m_layer_flat, 'V8 слои demo-a: #demo-a--band (under'),
    ('слой объявлен в разметке, а не применён', m_layer_markup, 'V8 слои demo-a: #demo-a--legend (under'),
    ('фокус не снят к концу сцены', m_under_left, 'V9 последний кадр demo-a: #demo-a--band (слой under'),
    ('приглушение к концу сцены', m_dim_end, 'V9 последний кадр demo-b: #demo-b--card2 на 0.45'),
    ('надпись пропала к концу сцены', m_text_gone_end, 'V9 последний кадр demo-b: надписи #demo-b--plaque нет в кадре'),
    ('строки двух карточек пересеклись', m_text_overlap, 'V10 надписи: #demo-b--card1 и #demo-b--card2: строки пересекаются'),
    ('строка за рамкой', m_line_out, 'V10 надписи: #demo-b--card3: строка'),
    ('иконка в полёте на тексте', m_fly_covers, 'V10 надписи: #demo-a--bell (в полёте) закрывает строку #demo-a--step1'),
    ('голос на футере', m_voice_covers, 'V10 надписи: #vo-{voice0} (группа голоса) закрывает строку #fr-footer'),
    ('на шве строка под заливкой', m_seam_under_fill, 'V10 шов demo-a → demo-b: строка #demo-a--step1'),
    ('на шве тень на тексте', m_seam_shade_line, 'V10 шов demo-a → demo-b: #demo-b--card1 и #demo-b--lead: строки пересекаются'),
    ('шрифт отвергнут', m_font_error, 'V11 шрифт: Liberation Sans Narrow — статус error'),
    ('шрифт не объявлен', m_font_absent, 'V11 шрифт: Liberation Sans Narrow не объявлен на странице'),
    ('синтетический жирный', m_font_synth, 'V11 шрифт: font-synthesis'),
    ('hex вне палитры в разметке', m_page_hex, 'V12 палитра: в содержании страницы цвета вне палитры tokens.json: #FF00FF'),
    ('заливка вне палитры', m_fill_color, 'V12 палитра: заливка #demo-b--card1 rgb(255, 0, 0)'),
    ('цвет текста вида вне палитры', m_kind_color, 'V12 палитра: #demo-a--step1.text color rgb(17, 17, 17)'),
    ('спутник отстал', m_sat_drift, 'V13 спутники: #demo-a--bell уходит от своей надписи #demo-a--step1'),
    ('спутник без промера', m_sat_missing, 'V13 спутники: #demo-b--bell — нет промера в системе надписи #demo-b--lead'),
    ('спутник не у той надписи', m_sat_wrong, 'V13 спутники: #demo-b--bell в t='),
    ('иконка строки без with', m_sat_undeclared, 'V13 спутники: иконка #demo-a--bell стоит на строке #demo-a--step1'),
    ('уровень скачком', m_level_jump, 'V14 смена уровня: #demo-a--step1 — текст скачет'),
    ('уровень без промера', m_trace_missing, 'V14 смена уровня: #demo-b--card1 в t='),
    ('промер уровня короче окна', m_trace_short, 'промер не покрывает'),
    ('предмет висит 1,6 с', m_hang_orb, 'V15 без опоры: #demo-b--orb'),
    ('спутник без хозяина', m_hang_host_gone, 'V15 без опоры: #demo-a--bell'),
    ('двойник текста на шве', m_twin_text, 'V16 двойник на шве: #demo-a--step1.text и его цель #demo-b--lead «проверка данных»'),
    ('двойник колокольчика', m_twin_bell, 'V16 двойник на шве: #demo-a--bell и его цель #demo-b--bell'),
    ('речь называет пункты наоборот', m_order_reversed, 'V17 порядок = речь: #demo-a--step1 стал читаемым'),
    ('карточки не в порядке речи', m_order_cards, 'V17 порядок = речь: #demo-b--card1 стал читаемым'),
    ('30 слов одним куском', m_chunk_30, 'V18 текст кусками: #demo-b--card4 — 30 слов'),
    ('строка кадром раньше, остальное разом', m_chunk_line_then_rest, 'V18 текст кусками: #demo-b--card4 — 30 слов'),
    ('имя ведущей в разметке', m_guard_name, 'V19 сторож тематики: «имя ведущей прошлого ролика»'),
    ('имя ведущего в строках', m_guard_name_m, 'V19 сторож тематики: «имя ведущего прошлого ролика»'),
    ('бренд в футере', m_guard_brand, 'V19 сторож тематики: «бренд заказчика прошлого ролика»'),
    ('код объекта в заметке', m_guard_obj, 'V19 сторож тематики: «код объекта прошлого ролика»'),
    ('сезон в коде', m_guard_winter, 'V19 сторож тематики: «сезон прошлого ролика»'),
    ('предмет в токенах', m_guard_tree, 'V19 сторож тематики: «предмет прошлого ролика»'),
    ('имя латиницей в id', m_guard_latin, 'V19 сторож тематики: «имена прошлого ролика латиницей»'),
    ('литерал в подпапке движка', m_guard_engine, 'engine\\video\\lib\\stage.js'),
    ('имя u-кодами в rows.json', m_guard_json_escaped, 'V19 сторож тематики: «имя ведущей прошлого ролика» в '),
    ('данные демо шаблона под сторожем', m_guard_demo_data, 'newproj\\rows.json'),
    ('литерал u-кодами в .json с BOM', m_guard_json_bom, 'V19 сторож тематики: «имя ведущей прошлого ролика» в '),
    ('.json не разбирается', m_guard_json_broken, 'V19 сторож тематики: не разобран JSON:'),
    ('элемент пропал без подмены', m_vanish, 'V20 переходы: VANISH #demo-a--step1'),
    ('элемент мигнул', m_flicker, 'V20 переходы: FLICKER #demo-b--card2'),
    ('третья рука: поднята, а опущенная видна', m_pose_third_arm, 'V25 поза: demo-b — у «geroj» видны и поднятая, и опущенная конечность стороны right'),
    ('жест не попал в промер', m_pose_never_up, 'V25 поза: demo-b — у «geroj» объявлена поднятая конечность стороны right, а кадра с ней в промере нет'),
    ('разметка конечности без положения', m_pose_bad_tag, 'V25 поза: разметка data-limb="geroj:right:vverh"'),
]

SAMPLES = [
    ('источник полный', s_src_full),
    ('надпись — фрагмент абзаца источника', s_src_wider),
    ('предмет без опоры 0,8 с', s_hang_short),
    ('рук две: поднятая вместо опущенной', s_pose_two_arms),
    ('предмет на плашке', s_hang_on_plaque),
    ('подмена точно на месте', s_twin_aligned),
    ('речь в порядке экрана', s_order_same),
    ('пункты одного бита', s_order_one_beat),
    ('25 слов одним куском', s_chunk_25),
    ('40 слов кусками', s_chunk_parts),
    ('похожие законные слова', s_guard_lookalikes),
    ('литерал только в .env', s_guard_env),
    ('новый проект с законной лексикой', s_guard_new_project),
    ('чистый .json с BOM', s_guard_json_bom_clean),
    ('запрет снят проектом', s_guard_allow),
    ('уход под движением', s_vanish_moving),
    ('провал до 0,5 — не мигание', s_flicker_dip),
]


# ---------------------------------------------------------------- медленные: копия проекта, пересборка
def p_twin_early(pd):
    _edit(os.path.join(pd, 'scenes', B, 'storyboard.json'),
          '"offset": -0.25, "action": "show", "targets": ["bell", "lead.slot"]',
          '"offset": -0.6, "action": "show", "targets": ["bell", "lead.slot"]')


def p_no_handoff(pd):
    _edit(os.path.join(pd, 'scenes', B, 'storyboard.json'),
          '"offset": -0.25, "action": "show", "targets": ["bell", "lead.slot"]',
          '"offset": 0.4, "action": "show", "targets": ["bell", "lead.slot"]')


def p_no_with(pd):
    _edit(os.path.join(pd, 'scenes', A, 'storyboard.json'), ', "with": "step1"}', '}')


def p_band_stays(pd):
    _sb_edit(os.path.join(pd, 'scenes'), A, lambda sb: sb.__setitem__('beats', [
        b for b in sb['beats'] if not (b['action'] == 'hide' and b['targets'] == ['band'])]))


def p_level_abrupt(pd):
    _edit(os.path.join(pd, 'scenes', A, 'storyboard.json'),
          '"action": "level", "targets": ["step1", "step5"], "value": 1,',
          '"action": "level", "targets": ["step1", "step5"], "value": 1, "dur": 0.1,')


def p_long_text(pd):
    _edit(os.path.join(pd, 'scenes', B, 'storyboard.json'),
          '"text": "Все участники проекта, которые работают с этими данными"',
          '"text": "Все участники проекта, которые работают с этими данными каждый день, отвечают за их сохранность, '
          'сверяют версии, передают результат дальше без задержки и сообщают руководителю группы о каждом найденном расхождении"')


def p_two_lines(pd):
    _edit(os.path.join(pd, 'scenes', A, 'storyboard.json'), '"tag_x": 5.90}', '"tag_x": 3.30}')


def p_rows_order(pd):
    p = os.path.join(pd, 'rows.json')
    rows = C.load_json(p)
    rows[0]['text'] = 'Сначала разбор итогов, потом проверка данных.'
    with open(p, 'w', encoding='utf-8') as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=1)


def _text_dir(pd, base, drop=None):
    d = os.path.join(pd, 'text')
    os.makedirs(d, exist_ok=True)
    for sc, txt in _screen_source(base).items():
        if drop:
            txt = txt.replace(drop, '')
        with open(os.path.join(d, sc + '.txt'), 'w', encoding='utf-8') as fh:
            fh.write(txt.replace(' ¶ ', '\n'))


def p_text_missing(pd, base):
    _text_dir(pd, base, drop='Руководитель группы')


def p_text_full(pd, base):
    _text_dir(pd, base)


def p_theme_in_demo(pd):
    """Литерал в данных демо шаблона. Копия проекта помечается демо шаблона (template_demo true) самой порчей:
    в новом проекте флаг false, сторож его данные не смотрит, и порча без этого не покраснела бы."""
    _edit(os.path.join(pd, 'scenes', B, 'markup.html'), '<!-- Своя разметка сцены: лид.',
          '<!-- %s. Своя разметка сцены: лид.' % W_NAME_F)
    p = os.path.join(pd, 'project.json')
    pj = C.load_json(p)
    pj['template_demo'] = True
    with open(p, 'w', encoding='utf-8') as fh:
        json.dump(pj, fh, ensure_ascii=False, indent=1)


def p_theme_allowed(pd):
    _edit(os.path.join(pd, 'scenes', B, 'markup.html'), '<!-- Своя разметка сцены: лид.',
          '<!-- %s пейзаж. Своя разметка сцены: лид.' % W_WINTER)
    p = os.path.join(pd, 'project.json')
    pj = C.load_json(p)
    pj['theme_allow'] = ['сезон прошлого ролика']
    with open(p, 'w', encoding='utf-8') as fh:
        json.dump(pj, fh, ensure_ascii=False, indent=1)


def v_trim(od, dst):
    """Видео на полсекунды короче звука: картинка обрезана, звук целиком."""
    src = os.path.join(od, 'video.mp4')
    dur = C.load_json(os.path.join(od, 'film.json'))['duration']
    subprocess.run([C.ffmpeg(), '-v', 'error', '-y', '-t', '%.3f' % (dur - 0.5), '-i', src, '-i', src,
                    '-map', '0:v', '-map', '1:a', '-c', 'copy', dst], check=True)


def v_both_short(od, dst):
    """Видео и звук вместе короче ролика на секунду: последняя реплика обрезана."""
    src = os.path.join(od, 'video.mp4')
    dur = C.load_json(os.path.join(od, 'film.json'))['duration']
    subprocess.run([C.ffmpeg(), '-v', 'error', '-y', '-i', src, '-t', '%.3f' % (dur - 1.0), '-c', 'copy', dst], check=True)


def v_same(od, dst):
    shutil.copyfile(os.path.join(od, 'video.mp4'), dst)


def pp_font_broken(od):
    for fn in os.listdir(os.path.join(od, 'assets', 'fonts')):
        with open(os.path.join(od, 'assets', 'fonts', fn), 'wb') as fh:
            fh.write(b'not a font')


# (имя, вид, правка, подстрока): scenes — правка копии проекта и build.py --page на ней;
# project — правка конфигов копии без пересборки (страница та же); page — правка копии страницы и новый промер
RED_SLOW = [
    ('подстрока лида раньше моста', 'scenes', p_twin_early, 'V16 двойник на шве: #demo-a--'),
    ('подмены на шве нет', 'scenes', p_no_handoff, 'V20 переходы: VANISH #demo-a--'),
    ('колокольчик без with', 'scenes', p_no_with, 'V13 спутники: иконка #demo-a--bell стоит на строке'),
    ('фокус-плашка не снята', 'scenes', p_band_stays, 'V9 последний кадр demo-a: #demo-a--band (слой under'),
    ('уровень за 0,1 с', 'scenes', p_level_abrupt, 'V14 смена уровня: #demo-a--step1 — текст скачет'),
    ('длинный текст карточки одним куском', 'scenes', p_long_text, 'V18 текст кусками: #demo-b--card4'),
    ('текст шага в две строки', 'scenes', p_two_lines, 'V6 move #demo-a--step1.text: текст не лёг буквы на буквы'),
    ('rows.json называет пункты наоборот', 'project', p_rows_order, 'V17 порядок = речь: #demo-a--step1'),
    ('в text/ нет надписи', 'project+', p_text_missing, 'V4 текст: «Руководитель группы» (#demo-b--card1) нет в источнике'),
    ('имя ведущей в демо-разметке', 'project', p_theme_in_demo, 'V19 сторож тематики: «имя ведущей прошлого ролика» в '),
    ('файл шрифта битый', 'page', pp_font_broken, 'V11 шрифт: Liberation Sans Narrow — статус error'),
    ('видео короче звука', 'video', v_trim, 'V1 длительность: видео'),
    ('ролик обрезан вместе со звуком', 'video', v_both_short, 'а последняя реплика кончается'),
]

SAMPLES_SLOW = [
    ('text/ полный — V4 зелёный, не SKIP', 'project+', p_text_full, 'OK   V4'),
    ('запрет снят в project.json', 'project', p_theme_allowed, 'OK   V19'),
    ('видео как есть — V1 по mp4', 'video', v_same, 'OK   V1 длительность и время'),
]


# ---------------------------------------------------------------- прогон
def _calibrated(film, only):
    if film != 'demo' or only:
        print('Порчи и образцы калиброваны на демо-фильме шаблона целиком: check.py demo --red | --red-slow | --samples. '
              'Для своего фильма — свои порчи рядом (engine/video/checks/), по образцу этого файла.')
        return False
    return True


def _base(root, out_dir):
    # порчи промера калиброваны на страницу: длина — film.json; видео (если оно есть) мерит порча вида video
    base = C.make_ctx(root, out_dir, page_only=True)
    bad, lines = C.run(base, quiet=True)
    if bad:
        print('Исходный фильм уже красный — порчи бессмысленны:\n' + '\n'.join(l for l in lines if l.startswith('FAIL')))
        return None
    return base


def _verdict(name, lines, expect):
    hit = [l for l in lines if l.startswith('FAIL') and expect in l]
    if hit:
        print('RED  %-40s → %s' % (name, hit[0][5:]))
        return 0
    got = [l for l in lines if l.startswith('FAIL')] or ['(всё зелёное)']
    print('MISS %-40s ждали «%s», получили: %s' % (name, expect, ' | '.join(got)[:600]))
    return 1


def red_fast(root, out_dir, film, only, filt=None):
    if not _calibrated(film, only):
        return 1
    t_start = time.time()
    base = _base(root, out_dir)
    if base is None:
        return 1
    failed = n = 0
    for name, fn, expect in RED_FAST:
        if filt and filt not in name:
            continue
        n += 1
        ctx = C.fresh(base)
        tmp = tempfile.mkdtemp(prefix='motion_red_')
        try:
            fn(ctx, tmp)
            _, lines = C.run(ctx, quiet=True)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        failed += _verdict(name, lines, expect_of(ctx, expect))
    print('быстрые порчи: %d, не покраснело своей строкой: %d · %.0f с' % (n, failed, time.time() - t_start))
    return 1 if failed else 0


def samples(root, out_dir, film, only, filt=None):
    if not _calibrated(film, only):
        return 1
    base = _base(root, out_dir)
    if base is None:
        return 1
    failed = n = 0
    for name, fn in SAMPLES:
        if filt and filt not in name:
            continue
        n += 1
        ctx = C.fresh(base)
        tmp = tempfile.mkdtemp(prefix='motion_smp_')
        try:
            fn(ctx, tmp)
            bad, lines = C.run(ctx, quiet=True)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        if bad:
            failed += 1
            print('MISS образец «%s» покраснел: %s' % (name, ' | '.join(l for l in lines if l.startswith('FAIL'))[:600]))
        else:
            print('ok   образец %-40s — молча' % name)
    print('образцы: %d, покраснело: %d' % (n, failed))
    return 1 if failed else 0


def _copy_project(root, dst):
    shutil.copytree(root, dst, ignore=shutil.ignore_patterns('out', 'node_modules', '.env', '__pycache__'))


def _slow_one(base, root, out_dir, film, kind, fn):
    """→ строки отчёта check по порченой копии. Поставка (проект и его out/) не трогается."""
    tmp = tempfile.mkdtemp(prefix='motion_slow_')
    try:
        pd = os.path.join(tmp, 'project')
        if kind.startswith('project') or kind == 'scenes':
            _copy_project(root, pd)
            fn(pd, base) if kind == 'project+' else fn(pd)
        if kind == 'scenes':
            od = os.path.join(pd, 'out', film)
            r = subprocess.run([sys.executable, os.path.join(HERE, 'build.py'), film, '--page', '--project', pd,
                                '--out-dir', od], capture_output=True, text=True, encoding='utf-8', errors='replace')
            if r.returncode or not os.path.exists(os.path.join(od, 'probe.json')):
                return ['FAIL сборка порченой страницы упала: ' + (r.stdout + r.stderr).strip()[-400:]]
            ctx = C.make_ctx(pd, od, page_only=True)
        elif kind.startswith('project'):
            ctx = C.make_ctx(pd, out_dir, page_only=True)
            ctx['scenes_dir'] = os.path.join(pd, 'scenes')
        elif kind == 'video':                   # ролик собран: правка копии mp4, V1 смотрит видео
            ctx = C.make_ctx(root, out_dir, page_only=False)
            ctx['mp4'] = os.path.join(tmp, 'video.mp4')
            fn(out_dir, ctx['mp4'])
        else:                                   # page: копия страницы, правка, новый промер
            od = os.path.join(tmp, 'out')
            os.makedirs(od)
            for n_ in ('index.html', 'film.json'):
                shutil.copyfile(os.path.join(out_dir, n_), os.path.join(od, n_))
            shutil.copytree(os.path.join(out_dir, 'assets'), os.path.join(od, 'assets'))
            fn(od)
            with chrome_lock.held('red_demo probe_dom %s' % od):
                r = subprocess.run(['node', os.path.join(HERE, 'probe_dom.mjs'), od], capture_output=True, text=True,
                                   encoding='utf-8', errors='replace')
            if not os.path.exists(os.path.join(od, 'probe.json')):
                return ['FAIL промер порченой страницы не дал probe.json: ' + (r.stdout + r.stderr).strip()[-400:]]
            ctx = C.make_ctx(root, od, page_only=True)
        _, lines = C.run(ctx, quiet=True)
        return lines
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def red_slow(root, out_dir, film, only, filt=None):
    if not _calibrated(film, only):
        return 1
    t_start = time.time()
    base = _base(root, out_dir)
    if base is None:
        return 1
    failed = n = 0
    has_video = os.path.exists(os.path.join(out_dir, 'video.mp4'))
    for name, kind, fn, expect in RED_SLOW:
        if filt and filt not in name:
            continue
        if kind == 'video' and not has_video:
            print('SKIP %-40s ролик не отрендерен (нет video.mp4) — сначала build.py demo на копии проекта' % name)
            continue
        n += 1
        failed += _verdict(name, _slow_one(base, root, out_dir, film, kind, fn), expect)
    for name, kind, fn, expect in SAMPLES_SLOW:
        if filt and filt not in name:
            continue
        if kind == 'video' and not has_video:
            print('SKIP образец %-33s ролик не отрендерен (нет video.mp4)' % name)
            continue
        n += 1
        lines = _slow_one(base, root, out_dir, film, kind, fn)
        bad = [l for l in lines if l.startswith('FAIL')]
        if bad or not any(l.startswith(expect) for l in lines):
            failed += 1
            print('MISS образец «%s»: ждали «%s» и ни одного FAIL, получили: %s'
                  % (name, expect, ' | '.join(bad or [l for l in lines if 'V4' in l or 'V19' in l])[:600]))
        else:
            print('ok   образец %-40s — молча (%s)' % (name, expect.strip()))
    print('медленные порчи и образцы: %d, не так, как ждали: %d · %.0f с' % (n, failed, time.time() - t_start))
    return 1 if failed else 0
