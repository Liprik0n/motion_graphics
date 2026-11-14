# -*- coding: utf-8 -*-
"""Звуковые эффекты ролика: события фильма → синтез → расстановка с уровнями по речи.

    python engine/audio/sfx.py <фильм> [--project DIR]
        → <out>/<фильм>/sfx/*.wav (клипы для прослушки), sfx-cues.json (план и уровни),
          sfx-proba.mp3 (речь + эффекты, без музыки: проба на слух ДО рендера видео)

Слой эффектов сводит `music.py` (план и синтез те же, функциями отсюда): дорожка входит в микс
до итоговой поправки громкости, `sfx.wav` — та же дорожка с той же поправкой, отдельно — по нему
меряет `check_mix.py`. Звуки — только синтез (`synth.py`), без сэмплов и скачивания.

Время — только из `film.json.events` (`{kind, t, scene, ref, …}`): секунд в этом коде нет.
Каталог — `project/sfx.json`:

    events[]  {kind, match?, clip, variants?, gain_db, prio, anchor?, lead_sec?}
        kind    вид события фильма: show hide level emph move seam chapter title;
        match   {поле события: значение | [значения]} — сузить правило (emph + style: ring);
        clip    вид звука из synth.CLIPS;  variants — сколько вариантов по кругу (по умолчанию 3);
        gain_db номинал, дБ относительно речи (ещё ниже предела под речью);
        prio    приоритет при конфликте плотности: младший выпадает, запись — в `sfx_dropped`;
        anchor  start | end | mid — где у события удар (start = t, end = t + dur, mid = t + dur/2);
        lead_sec длина разгона у whoosh / whoosh_click: звук стартует за lead до события.
    min_gap_sec    начала эффектов не ближе;  keep_prio  приоритеты ≥ — не выпадают, конфликт двух
                   таких роняет сборку;
    under_speech_max_db / pause_max_db   предел проверки (под речью ≤ −18, в паузе ≤ −10 дБ к речи);
    under_speech_target_db / pause_target_db   цель сборки, с запасом на ограничитель и AAC.

Материал звука стиля: у сцены со стилем (film.json scenes[].style) клип берёт материал своего вида из
film.json styles[стиль].sfx.clips (поля grit, crackle, lp_hz — synth.material); время удара то же.

Уровень — на эффект, по промеру: максимум RMS скользящего окна 400 мс в каждом куске эффекта
под репликой ≤ RMS реплики + цель, в паузе ≤ среднее RMS соседних реплик + цель.
"""
import array
import math
import os
import shutil
import sys
import tempfile

sys.dont_write_bytecode = True
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config   # noqa: E402
import dsp     # noqa: E402
import synth   # noqa: E402

SR = synth.SR
FRAME = 0.005               # кадр промера уровня, с
WIN = 0.4                   # окно RMS, с
EVENT_KINDS = ('show', 'hide', 'level', 'emph', 'move', 'seam', 'chapter', 'title')
ANCHORS = ('start', 'end', 'mid')
DEFAULT_VARIANTS = 3


# ---------------------------------------------------------------- правила и план

def load_rules(cfg):
    """Правила каталога из sfx.json с проверкой: опечатка в конфиге — ошибка сборки, а не тишина."""
    rules = []
    for i, r in enumerate(cfg.get('events', [])):
        where = 'sfx.json events[%d]' % i
        for key in ('kind', 'clip', 'gain_db', 'prio'):
            if key not in r:
                raise SystemExit('%s: нет поля %s' % (where, key))
        if r['kind'] not in EVENT_KINDS:
            raise SystemExit('%s: вид события %r не знаю (есть: %s)' % (where, r['kind'], ', '.join(EVENT_KINDS)))
        if r['clip'] not in synth.CLIPS:
            raise SystemExit('%s: вид эффекта %r не знаю (есть: %s)' % (where, r['clip'], ', '.join(sorted(synth.CLIPS))))
        if r.get('anchor', 'start') not in ANCHORS:
            raise SystemExit('%s: anchor %r — ждали %s' % (where, r['anchor'], ' | '.join(ANCHORS)))
        if r.get('lead_sec') is not None and r['clip'] not in synth.LEADABLE:
            raise SystemExit('%s: lead_sec есть только у %s' % (where, ', '.join(synth.LEADABLE)))
        if r['gain_db'] > 0:
            raise SystemExit('%s: gain_db — дБ относительно речи, ждали ≤ 0' % where)
        rules.append(dict(r, variants=max(1, int(r.get('variants', DEFAULT_VARIANTS))),
                          anchor=r.get('anchor', 'start'), match=r.get('match') or {}))
    return rules


def rule_for(rules, ev):
    for r in rules:
        if r['kind'] != ev['kind']:
            continue
        if all((ev.get(k) in v) if isinstance(v, list) else (ev.get(k) == v) for k, v in r['match'].items()):
            return r
    return None


def style_materials(film):
    """{сцена: {вид клипа: материал}} — материал звука стиля сцены из film.json (scenes[].style,
    styles[имя].sfx.clips; пишет engine/video/build.py из styles/<имя>/style.json). Нет стиля — {}."""
    st = (film or {}).get('styles') or {}
    return {s['id']: ((st.get(s.get('style')) or {}).get('sfx') or {}).get('clips') or {}
            for s in (film or {}).get('scenes', [])}


def plan(events, cfg, film=None):
    """События фильма → (эффекты, выпавшие по плотности).

    Эффект: {id, event{kind,ref,t,scene}, clip, variant, prio, hit, onset, lead, rule, material?}.
    hit — момент удара (событие + anchor), onset — начало звука (hit − разгон клипа); material — материал
    звука стиля сцены события (style_materials), если стиль его задаёт для этого вида клипа."""
    mats = style_materials(film)
    rules = load_rules(cfg)
    min_gap = float(cfg.get('min_gap_sec', 1.5))
    keep = int(cfg.get('keep_prio', 9))
    cues = []
    for e in sorted(events, key=lambda x: (x['t'], x['kind'], str(x.get('ref')))):
        r = rule_for(rules, e)
        if r is None:
            continue
        shift = {'start': 0.0, 'end': e.get('dur', 0.0), 'mid': e.get('dur', 0.0) / 2}[r['anchor']]
        hit = e['t'] + shift
        lead = synth.lead_of(r['clip'], r.get('lead_sec'))
        if hit - lead < -1e-9:
            raise SystemExit('эффект %s на событии %s %s (t=%.3f) начинается раньше начала фильма (%.3f с): '
                             'сдвинь событие или укороти lead_sec' % (r['clip'], e['kind'], e.get('ref'), e['t'], hit - lead))
        cues.append({'event': {k: e.get(k) for k in ('kind', 'ref', 't', 'scene')}, 'clip': r['clip'],
                     'prio': r['prio'], 'hit': round(hit, 4), 'onset': round(hit - lead, 4), 'lead': lead, 'rule': r,
                     'material': mats.get(e.get('scene'), {}).get(r['clip'])})
    cues.sort(key=lambda c: (c['onset'], c['event']['kind'], str(c['event']['ref'])))
    count = {}
    for c in cues:
        c['variant'] = count.get(c['clip'], 0) % c['rule']['variants']
        count[c['clip']] = count.get(c['clip'], 0) + 1
    kept, dropped = [], []

    def drop(c, by):
        dropped.append({'event': '%s:%s' % (c['event']['kind'], c['event']['ref']), 'kind': c['event']['kind'],
                        'onset': c['onset'], 'hit': c['hit'],
                        'reason': 'ближе %.2f с к %s:%s' % (abs(c['onset'] - by['onset']), by['event']['kind'],
                                                           by['event']['ref'])})

    for c in cues:
        lost = False
        while kept and c['onset'] - kept[-1]['onset'] < min_gap:
            prev = kept[-1]
            if min(c['prio'], prev['prio']) >= keep:
                raise SystemExit('плотность: %s:%s и %s:%s ближе %.1f с (%.2f с) — выбрать некого (приоритеты %d и %d, '
                                 'неприкосновенные от %d)' % (prev['event']['kind'], prev['event']['ref'],
                                                              c['event']['kind'], c['event']['ref'], min_gap,
                                                              c['onset'] - prev['onset'], prev['prio'], c['prio'], keep))
            if c['prio'] > prev['prio']:
                drop(prev, c)
                kept.pop()
            else:
                drop(c, prev)
                lost = True
                break
        if not lost:
            kept.append(c)
    for i, c in enumerate(kept):
        c['id'] = 'fx%02d' % (i + 1)
    return kept, dropped


# ---------------------------------------------------------------- клипы

def seed_of(c):
    return sum(map(ord, '%s:%s' % (c['event']['kind'], c['event']['ref']))) * 7 + c['variant']


def clip_name(c):
    return '%s-%s-v%d.wav' % (c['id'], c['clip'], c['variant'])


def render(cues):
    """Синтез клипов → {id: [float]}; заполняет c['end'] и c['file']."""
    clips = {}
    for c in cues:
        x, hit = synth.synth(c['clip'], seed_of(c), c['variant'], c['rule'].get('lead_sec'), c.get('material'))
        if abs(hit - c['lead']) > 1e-6:
            raise SystemExit('синтез %s: удар на %.3f с, планировщик ждал %.3f' % (c['clip'], hit, c['lead']))
        clips[c['id']] = x
        c['file'] = clip_name(c)
        c['end'] = round(c['onset'] + len(x) / SR, 4)
    return clips


# ---------------------------------------------------------------- уровни

def frame_energy(xs, i0_abs):
    """Энергия кадров 5 мс на сетке фильма: {номер кадра: средний квадрат}."""
    fs = FRAME * SR             # 220,5 отсчёта: кадр считается делением, а не округлённым шагом
    out = {}
    for i, v in enumerate(xs):
        j = int((i0_abs + i) / fs)
        out[j] = out.get(j, 0.0) + v * v
    return {j: e / fs for j, e in out.items()}


def max_win_db(fr, t0, t1):
    """Максимум RMS окна min(400 мс, куска) внутри [t0, t1] по кадрам 5 мс, дБ (полная шкала = 1)."""
    j0, j1 = int(math.ceil(t0 / FRAME - 1e-9)), int(math.floor(t1 / FRAME + 1e-9))
    n = j1 - j0
    if n <= 0:
        return -200.0
    w = max(1, min(int(round(WIN / FRAME)), n))
    vals = [fr.get(j, 0.0) for j in range(j0, j1)]
    s = sum(vals[:w])
    best = s
    for i in range(w, n):
        s += vals[i] - vals[i - w]
        best = max(best, s)
    return 10 * math.log10(best / w + 1e-20)


def segments(replies, speech_db, t0, t1, dur, under_target, pause_target):
    """Куски [a, b] внутри [t0, t1] с опорой: (a, b, подпись, дБ речи, цель)."""
    out = []
    edges = [0.0]
    for r in replies:
        edges += [r['start'], r['end']]
    edges.append(dur)
    pts = sorted(set([t0, t1] + [e for e in edges if t0 < e < t1]))
    for a, b in zip(pts, pts[1:]):
        mid = (a + b) / 2
        r = next((r for r in replies if r['start'] <= mid < r['end']), None)
        if r:
            out.append((a, b, 'реплика %d' % r['num'], speech_db[r['num']], under_target))
        else:
            prv = [x for x in replies if x['end'] <= mid]
            nxt = [x for x in replies if x['start'] >= mid]
            ref = [speech_db[x['num']] for x in ([prv[-1]] if prv else []) + ([nxt[0]] if nxt else [])]
            out.append((a, b, 'пауза', sum(ref) / len(ref), pause_target))
    return out


def place(cues, clips, replies, speech_db, dur, cfg):
    """Уровень каждого эффекта (дБ к клипу) и дорожка фильма array('f') — до итоговой поправки."""
    under = float(cfg.get('under_speech_target_db', -21.0))
    pause = float(cfg.get('pause_target_db', -12.0))
    n = int(round(dur * SR))
    track = array.array('f', bytes(4 * n))
    for c in cues:
        x = clips[c['id']]
        i0 = int(round(c['onset'] * SR))
        fr = frame_energy(x, i0)
        segs = segments(replies, speech_db, c['onset'], c['end'], dur, under, pause)
        g = None
        for a, b, what, ref, lim in segs:
            m = max_win_db(fr, a, b)
            if m < -150:
                continue
            want = min(ref + lim, ref + c['rule']['gain_db']) - m
            g = want if g is None else min(g, want)
        if g is None:
            raise SystemExit('эффект %s (%s) звучит вне фильма: onset %.3f, длина фильма %.3f' % (c['id'], c['clip'], c['onset'], dur))
        c['gain_db'] = round(g, 2)
        k = 10 ** (g / 20)
        lv = [(max_win_db(fr, a, b) + g - ref, what) for a, b, what, ref, lim in segs if max_win_db(fr, a, b) > -150]
        worst = max(lv)
        c['level'] = {'rel_db': round(worst[0], 1), 'where': 'пауза' if worst[1] == 'пауза' else 'реплика',
                      'at': worst[1]}
        for i, v in enumerate(x):
            j = i0 + i
            if 0 <= j < n:
                track[j] += k * v
    return track


def cue_record(c):
    """Метка эффекта для cues.json: без внутренностей правила."""
    return {'id': c['id'], 'event': c['event'], 'clip': c['clip'], 'variant': c['variant'], 'prio': c['prio'],
            'onset': c['onset'], 'hit': c['hit'], 'end': c['end'], 'file': c['file'], 'gain_db': c['gain_db'],
            'level': c['level'], 'material': c.get('material')}


def build_track(audio, film, replies, speech_db):
    """План → синтез → уровни: (дорожка до поправки микса, эффекты, выпавшие, клипы)."""
    cues, dropped = plan(film.get('events', []), audio.sfx, film)
    clips = render(cues)
    track = place(cues, clips, replies, speech_db, film['duration'], audio.sfx)
    return track, cues, dropped, clips


# ---------------------------------------------------------------- проба

def proba(audio, film, replies, cues, track, tmp):
    """sfx-proba.mp3: речь + эффекты, без музыки, только куски вокруг эффектов (до sfx.json proba.max_sec)."""
    pr = audio.sfx.get('proba') or {}
    pad, max_sec, xf = float(pr.get('pad_sec', 2.0)), float(pr.get('max_sec', 40.0)), 0.05
    dur = film['duration']
    wins = []
    for c in cues:
        a, b = max(0.0, c['onset'] - pad), min(dur, c['end'] + pad)
        if wins and a <= wins[-1][1]:
            wins[-1][1] = max(wins[-1][1], b)
        else:
            wins.append([a, b])
    total, take = 0.0, []
    for a, b in wins:
        if take and total + (b - a) > max_sec:
            break
        take.append((a, min(b, a + max_sec)))
        total += take[-1][1] - take[-1][0]
    raw = os.path.join(tmp, 'sfx-proba.raw')
    with open(raw, 'wb') as fh:
        fh.write(track.tobytes())
    ins, ch = dsp.speech_graph(audio, replies, 0)
    n_sp = len(replies)
    ch.append('[%d:a]apad,atrim=end_sample=%d,pan=stereo|c0=c0|c1=c0[fx]' % (n_sp, int(round(dur * SR))))
    ch.append('[sp][fx]amix=inputs=2:normalize=0:dropout_transition=0,atrim=end_sample=%d[all]' % int(round(dur * SR)))
    fc = os.path.join(tmp, 'proba.txt')
    with open(fc, 'w', encoding='utf-8') as fh:
        fh.write(';'.join(ch))
    wav = os.path.join(tmp, 'proba-all.wav')
    dsp.run([dsp.FF, '-v', 'error', '-y'] + ins + ['-f', 'f32le', '-ar', str(SR), '-ac', '1', '-i', raw,
                                                   '-filter_complex_script', fc, '-map', '[all]',
                                                   '-c:a', 'pcm_f32le', '-f', 'wav', wav])
    i0, _ = dsp.lufs(['-i', wav])
    gain = float(audio.music.get('target_lufs', -16.0)) - i0
    k = len(take)
    parts = ['[0:a]volume=%.3fdB,asplit=%d%s' % (gain, k, ''.join('[p%d]' % i for i in range(k)))]
    for i, (a, b) in enumerate(take):
        parts.append('[p%d]atrim=%.4f:%.4f,asetpts=PTS-STARTPTS,afade=t=in:d=%.3f,afade=t=out:st=%.4f:d=%.3f[q%d]'
                     % (i, a, b, xf, max(0.0, b - a - xf), xf, i))
    parts.append('%sconcat=n=%d:v=0:a=1,alimiter=limit=0.8[o]' % (''.join('[q%d]' % i for i in range(k)), k))
    tmp_mp3 = str(audio.proba) + '.tmp'
    dsp.run([dsp.FF, '-v', 'error', '-y', '-i', wav, '-filter_complex', ';'.join(parts), '-map', '[o]',
             '-c:a', 'libmp3lame', '-b:a', '192k'] + dsp.BITEXACT + ['-f', 'mp3', tmp_mp3])
    os.replace(tmp_mp3, str(audio.proba))
    return take, total


def print_plan(cues, dropped):
    for c in cues:
        print('  %s %-12s v%d  удар %8.3f  начало %8.3f  %-8s %-24s %+6.1f дБ к речи (%s)'
              % (c['id'], c['clip'], c['variant'], c['hit'], c['onset'], c['event']['kind'], c['event']['ref'],
                 c['level']['rel_db'], c['level']['at']))
    for d in dropped:
        print('  выпал %s %.3f: %s' % (d['event'], d['hit'], d['reason']))


def main():
    film_name, pdir, _ = config.parse_cli(sys.argv[1:])
    audio = config.Audio(pdir, film_name)
    film = audio.film()
    replies = audio.replies(film)
    speech_db = dsp.speech_levels(audio, replies)
    track, cues, dropped, clips = build_track(audio, film, replies, speech_db)
    sdir = audio.out / 'sfx'
    os.makedirs(sdir, exist_ok=True)
    for f in os.listdir(sdir):
        if f.endswith('.wav'):
            os.remove(sdir / f)
    for c in cues:
        synth.write_wav(sdir / c['file'], clips[c['id']])
    config.write_json(audio.out / 'sfx-cues.json', {'film': film_name, 'sfx': [cue_record(c) for c in cues],
                                                    'sfx_dropped': dropped})
    print_plan(cues, dropped)
    if not cues:
        raise SystemExit('в фильме нет событий каталога sfx.json — пробы нет')
    tmp = tempfile.mkdtemp(prefix='motion-sfx-')
    try:
        take, total = proba(audio, film, replies, cues, track, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print('  проба: %d кусков, %.1f с → %s' % (len(take), total, audio.proba))
    print('  →', sdir, '·', audio.out / 'sfx-cues.json')


if __name__ == '__main__':
    main()
