# -*- coding: utf-8 -*-
"""Музыка ролика: треки по главам, ducking под речь, эффекты, один микс -16 LUFS / -1 dBTP.

    python engine/audio/music.py <фильм> [--project DIR]          сборка звука фильма
    python engine/audio/music.py <фильм> [--project DIR] --mux    плюс video-music.mp4 (видео копией)
    python engine/audio/music.py --placeholder FILE [--root HZ]   пересоздать пэд-заглушку трека

Читает с диска только `<out>/<фильм>/film.json` (части — по событиям `chapter`, реплики — mp3 и время
из `replies`, эффекты — по `events`) и конфиги проекта; кода сборки видео не импортирует.
Пишет в `<out>/<фильм>/`: `music.wav` (только музыка), `sfx.wav` (только эффекты, с той же поправкой),
`mix.m4a` (речь + музыка + эффекты), `cues.json` (метки частей, сегментов, эффектов — по ним
проверяет `check_mix.py`), с `--mux` — `video-music.mp4`. Пересборка звука не требует перерендера
видео; два прогона дают одинаковые байты (`-bitexact`).

Музыка — файлы проекта, не синтез (демо везёт пэд-заглушку). `project/music.json`:

    tracks[]  {chapter, file, license, gain_db?, start_sec?, loop_in?, loop_out?}
        chapter  id главы из project.json или "*" (любая глава без своего трека);
        file     путь от корня проекта; license — источник и условия, обязательно (пусто — отказ);
        gain_db  поправка трека к общему уровню; start_sec — откуда в треке начинать (пропустить вступление);
        loop_in / loop_out  точки круга, если трек короче части: выход уточняется поиском похожей фразы
                 (волна, иначе огибающая атак) в пределах loop_search_sec.
    xfade_sec         равномощный кроссфейд на стыке частей, середина — на ходе полосы главы (t + dur/2);
    loop_xfade_sec    кроссфейд склейки круга;
    track_lufs        общий уровень треков до огибающей;
    duck_db / duck_min_db   музыка под репликой ниже речи на duck_db (но не выше базы части — без «дыхания»),
                      ни в одной реплике не меньше duck_min_db;
    raise_db / raise_gap_sec   в паузе между сценами (≥ raise_gap_sec) — на raise_db выше базы;
    target_lufs / peak_dbtp / limiter_margin_db   итог: одна статическая поправка, ограничитель на 4×
                      с потолком peak_dbtp − margin (запас под AAC);
    margin_min_db, voice_tol_db, lufs_tol   пороги проверки `check_mix.py`.
"""
import argparse
import array
import math
import os
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config   # noqa: E402
import dsp      # noqa: E402
import sfx      # noqa: E402
import synth    # noqa: E402

SR, ASR = dsp.SR, dsp.ASR
ENV_RATE = 1000         # частота огибающей громкости музыки, дальше ffmpeg передискретизирует
WAVE_RATE = 4000        # частота уточнения круга волной
WAVE_MIN_CORR = 0.5     # ниже — фраза не повторяется дословно, уточнять огибающей атак
DEFAULT_BASE_DB = -30.0     # база части без реплик
TAIL_FADE_FROM_LAST = 0.10  # затухание финала: от конца последней реплики + это, косинусом к нулю
AAC_BITRATE = '192k'
DEFAULTS = {'xfade_sec': 2.5, 'loop_xfade_sec': 3.0, 'first_fade_sec': 0.5, 'loop_search_sec': 0.15,
            'track_lufs': -20.0, 'duck_db': 20.0, 'duck_min_db': 18.0, 'raise_db': 6.0, 'raise_gap_sec': 1.2,
            'target_lufs': -16.0, 'peak_dbtp': -1.0, 'limiter_margin_db': 0.6}


def setting(cfg, key):
    return cfg.get(key, DEFAULTS[key])


# ---------------------------------------------------------------- части по главам

def chapter_timeline(film):
    """[(момент, глава)]: начальная глава и смены по событиям chapter (момент — середина хода полосы)."""
    sc = film['scenes'][0]
    cur = sc.get('chapter_from') or sc.get('chapter')
    if cur is None:
        raise SystemExit('film.json: у первой сцены нет chapter_from/chapter — не знаю, какая глава на старте')
    out = [(0.0, cur)]
    for e in sorted((e for e in film.get('events', []) if e['kind'] == 'chapter'), key=lambda e: e['t']):
        if e['ref'] != cur:
            cur = e['ref']
            out.append((round(e['t'] + e.get('dur', 0.0) / 2, 4), cur))
    return out


def track_for(cfg, chapter):
    tracks = cfg['tracks']
    for i, t in enumerate(tracks):
        if t['chapter'] == chapter:
            return i
    for i, t in enumerate(tracks):
        if t['chapter'] == '*':
            return i
    raise SystemExit('music.json: нет трека для главы %s (добавь запись с chapter "%s" или запасную "*")'
                     % (chapter, chapter))


def resolve_parts(film, cfg):
    """Главы фильма → части музыки: [{index, chapters, track, start_sec, from, to}].
    Соседние главы с одним треком сливаются в одну часть."""
    for i, t in enumerate(cfg.get('tracks', [])):
        for key in ('chapter', 'file', 'license'):
            if not str(t.get(key, '')).strip():
                raise SystemExit('music.json tracks[%d]: пустое поле %s (у трека обязательны chapter, file, license — '
                                 'источник и условия использования)' % (i, key))
    if not cfg.get('tracks'):
        raise SystemExit('music.json: нет ни одного трека')
    tl = chapter_timeline(film)
    parts = []
    for k, (t0, ch) in enumerate(tl):
        ti = track_for(cfg, ch)
        end = tl[k + 1][0] if k + 1 < len(tl) else film['duration']
        if parts and parts[-1]['track'] == ti:
            parts[-1]['chapters'].append(ch)
            parts[-1]['to'] = end
        else:
            parts.append({'chapters': [ch], 'track': ti, 'start_sec': float(cfg['tracks'][ti].get('start_sec', 0.0)),
                          'from': t0, 'to': end})
    for i, p in enumerate(parts):
        p['index'] = i
    return parts


# ---------------------------------------------------------------- круг трека по фразе

def onset_env(a, rate=ASR, hop_sec=0.01):
    """Огибающая атак: положительный прирост лог-энергии по кадрам 10 мс."""
    hop = int(rate * hop_sec)
    en = []
    for i in range(0, len(a) - hop, hop):
        s = sum(x * x for x in a[i:i + hop])
        en.append(math.log10(s / hop + 1.0))
    return [max(0.0, en[i] - en[i - 1]) if i else 0.0 for i in range(len(en))]


def corr(x, y):
    n = min(len(x), len(y))
    if n < 2:
        return 0.0
    mx, my = sum(x[:n]) / n, sum(y[:n]) / n
    sxy = sum((x[i] - mx) * (y[i] - my) for i in range(n))
    sxx = sum((x[i] - mx) ** 2 for i in range(n))
    syy = sum((y[i] - my) ** 2 for i in range(n))
    return sxy / math.sqrt(sxx * syy) if sxx > 0 and syy > 0 else 0.0


def refine_loop(path, a, b, dur, loop_xf, search):
    """Точка выхода b' в [b ± search], где музыка после b' совпадает с музыкой после a:
    волной (окно 1 с с a), если повтор дословный, иначе огибающей атак (окно −1,5…+3 с)."""
    if search <= 0:
        return b, 0.0, 'без уточнения'
    if b + loop_xf / 2 + search > dur:
        return b, 0.0, 'нет места'
    w = dsp.decode_mono(path, WAVE_RATE)
    ref = w[int(a * WAVE_RATE): int(a * WAVE_RATE) + WAVE_RATE]
    best, best_b = -2.0, b
    lag_max = int(search * WAVE_RATE)
    i0 = int(b * WAVE_RATE)
    for lag in range(-lag_max, lag_max + 1):
        c = corr(ref, w[i0 + lag: i0 + lag + WAVE_RATE])
        if c > best + 1e-12:
            best, best_b = c, (i0 + lag) / WAVE_RATE
    if best >= WAVE_MIN_CORR:
        return round(best_b, 4), round(best, 3), 'волна'
    env = onset_env(dsp.decode_mono(path))
    n = 300
    ia = int(a / 0.01)
    ref = env[ia - n // 2: ia + n]
    best, best_b = -2.0, b
    for ib in range(int((b - search) / 0.01), int((b + search) / 0.01) + 1):
        c = corr(ref, env[ib - n // 2: ib + n])
        if c > best + 1e-12:
            best, best_b = c, ib * 0.01
    return round(best_b, 2), round(best, 3), 'атаки'


# ---------------------------------------------------------------- раскладка сегментов

def layout(parts, tracks, film_dur, xf, loop_xf, first_fade):
    """Части → сегменты {track, src0, src1, at, fade_in, fade_out, part}. tracks[i] = {a, b, dur?}:
    трек короче части идёт по кругу от a к b (b + loop_xf/2 → снова a − loop_xf/2)."""
    segs = []
    for k, p in enumerate(parts):
        tr = tracks[p['track']]
        last = k == len(parts) - 1
        t = 0.0 if k == 0 else p['from'] - xf / 2
        end_t = film_dur if last else p['to'] + xf / 2
        s = p['start_sec']
        fade_in = first_fade if k == 0 else xf
        while True:
            remain = end_t - t
            if tr.get('b') is None:
                if tr.get('dur') is not None and s + remain > tr['dur'] + 1e-9:
                    raise SystemExit('трек %s короче части %d (%.1f с из %.1f с): задай loop_in/loop_out в music.json'
                                     % (tr.get('file', p['track']), k, tr['dur'] - s, remain))
                segs.append(dict(track=p['track'], src0=s, src1=s + remain, at=t, fade_in=fade_in,
                                 fade_out=0.0 if last else xf, part=p['index']))
                break
            if s + remain <= tr['b'] + loop_xf / 2:
                segs.append(dict(track=p['track'], src0=s, src1=s + remain, at=t, fade_in=fade_in,
                                 fade_out=0.0 if last else xf, part=p['index']))
                break
            segs.append(dict(track=p['track'], src0=s, src1=tr['b'] + loop_xf / 2, at=t, fade_in=fade_in,
                             fade_out=loop_xf, part=p['index']))
            t = t + (tr['b'] - s) - loop_xf / 2
            s = tr['a'] - loop_xf / 2
            fade_in = loop_xf
    return segs


def seg_chain(i, seg, tracks, rate, stereo=True):
    tr = tracks[seg['track']]
    n0 = int(round(seg['src0'] * rate))
    n1 = int(round(seg['src1'] * rate))
    ln = (n1 - n0) / rate
    at = int(round(seg['at'] * rate))
    c = ['aresample=%d' % rate,
         'aformat=sample_fmts=fltp:channel_layouts=%s' % ('stereo' if stereo else 'mono'),
         'atrim=start_sample=%d:end_sample=%d' % (n0, n1), 'asetpts=PTS-STARTPTS',
         'volume=%.4fdB' % tr['norm_db']]
    if seg['fade_in'] > 0:
        c.append('afade=t=in:st=0:d=%.4f:curve=qsin' % seg['fade_in'])
    if seg['fade_out'] > 0:
        c.append('afade=t=out:st=%.4f:d=%.4f:curve=qsin' % (ln - seg['fade_out'], seg['fade_out']))
    c.append('adelay=delays=%dS:all=1' % at)
    return '[%d:a]%s[m%d]' % (i, ','.join(c), i)


def bed_graph(segs, tracks, rate, stereo):
    inputs, chains = [], []
    for j, seg in enumerate(segs):
        inputs += ['-i', tracks[seg['track']]['path']]
        chains.append(seg_chain(j, seg, tracks, rate, stereo))
    mix = ''.join('[m%d]' % j for j in range(len(segs)))
    chains.append('%samix=inputs=%d:normalize=0:dropout_transition=0,apad[bed]' % (mix, len(segs)))
    return inputs, chains


# ---------------------------------------------------------------- огибающая

def envelope_points(replies, base_of, duck_of, raise_db, raise_gap, ramp_up=(0.10, 0.60), ramp_down=0.50):
    """Ключевые точки (t, dB) огибающей музыки; между ними — линейно в дБ."""
    pts = [(0.0, duck_of[replies[0]['num']])]
    for i, r in enumerate(replies):
        g = duck_of[r['num']]
        pts.append((r['start'], g))
        pts.append((r['end'], g))
        if i + 1 < len(replies):
            nx = replies[i + 1]
            gn = duck_of[nx['num']]
            gap = nx['start'] - r['end']
            if gap >= raise_gap:
                up = max(base_of(r['end']), base_of(nx['start'])) + raise_db
                pts.append((r['end'] + ramp_up[0], g))
                pts.append((r['end'] + ramp_up[1], up))
                pts.append((nx['start'] - ramp_down, up))
                pts.append((nx['start'] - 0.05, gn))
            else:
                pts.append((r['end'] + 0.05, g))
                pts.append((nx['start'] - 0.05, gn))
    return pts


def envelope_samples(pts, tail_t0, film_dur):
    n = int(math.ceil(film_dur * ENV_RATE)) + ENV_RATE
    out = array.array('f', bytes(4 * n))
    j = 0
    for k in range(n):
        t = k / ENV_RATE
        while j + 1 < len(pts) and pts[j + 1][0] <= t:
            j += 1
        if j + 1 < len(pts):
            (t0, d0), (t1, d1) = pts[j], pts[j + 1]
            d = d0 + (d1 - d0) * ((t - t0) / (t1 - t0) if t1 > t0 else 1.0)
        else:
            d = pts[-1][1]
        g = 10 ** (d / 20)
        if t >= tail_t0:   # затухание финала: косинус к нулю в конце фильма
            x = min(1.0, (t - tail_t0) / max(1e-6, film_dur - tail_t0))
            g *= math.cos(math.pi / 2 * x)
        out[k] = g
    return out


# ---------------------------------------------------------------- сборка

def atomic_out(path):
    d, b = os.path.split(str(path))
    return os.path.join(d, '.tmp-' + b)


def prepare_tracks(audio, cfg, parts, span_len):
    """Только используемые треки: путь, длина, громкость, поправка к track_lufs, точки круга."""
    loop_xf = setting(cfg, 'loop_xfade_sec')
    tracks = {}
    for ti in sorted({p['track'] for p in parts}):
        t = cfg['tracks'][ti]
        path = audio.dir / t['file']
        if not path.exists():
            raise SystemExit('music.json: нет файла трека %s (положи трек с лицензией или `music.py --placeholder`)' % path)
        dur = len(dsp.decode_mono(path, 8000)) / 8000.0
        i, _ = dsp.lufs(['-i', str(path)])
        norm = setting(cfg, 'track_lufs') + float(t.get('gain_db', 0.0)) - i
        a, b = t.get('loop_in'), t.get('loop_out')
        how, c = 'нет круга', 0.0
        need = any(p['track'] == ti and span_len[p['index']] > (b if b is not None else dur) + loop_xf / 2 - p['start_sec']
                   for p in parts)
        if (a is None) != (b is None):
            raise SystemExit('music.json tracks[%d]: loop_in и loop_out задаются вместе' % ti)
        if b is not None:
            if need:
                b, c, how = refine_loop(str(path), a, b, dur, loop_xf, setting(cfg, 'loop_search_sec'))
            else:
                how = 'круг не нужен'
        tracks[ti] = dict(path=str(path), file=t['file'], dur=dur, lufs=i, norm_db=norm, a=a, b=b, loop_corr=c,
                          loop_by=how)
        print('  трек %-34s %6.2f с  %6.1f LUFS → %+5.1f дБ  круг: %s' % (t['file'], dur, i, norm, how))
    return tracks


def build(audio, tmp):
    cfg = audio.music
    film = audio.film()
    dur = film['duration']
    replies = audio.replies(film)
    parts = resolve_parts(film, cfg)
    xf, loop_xf = setting(cfg, 'xfade_sec'), setting(cfg, 'loop_xfade_sec')
    span_len = {p['index']: (dur if p['index'] == len(parts) - 1 else p['to'] + xf / 2) - (0.0 if p['index'] == 0 else p['from'] - xf / 2)
                for p in parts}
    tracks = prepare_tracks(audio, cfg, parts, span_len)
    segs = layout(parts, tracks, dur, xf, loop_xf, setting(cfg, 'first_fade_sec'))

    # проход 1: постель без огибающей на частоте промера → RMS музыки в интервалах реплик
    ins, ch = bed_graph(segs, tracks, ASR, stereo=False)
    fc = os.path.join(tmp, 'bed.txt')
    with open(fc, 'w', encoding='utf-8') as fh:
        fh.write(';'.join(ch))
    bed_raw = os.path.join(tmp, 'bed.raw')
    dsp.run([dsp.FF, '-v', 'error', '-y'] + ins + ['-filter_complex_script', fc, '-map', '[bed]',
            '-t', '%.4f' % dur, '-ac', '1', '-ar', str(ASR), '-f', 's16le', bed_raw])
    bed = array.array('h')
    with open(bed_raw, 'rb') as fh:
        bed.frombytes(fh.read())

    def part_of(t):
        for p in parts:
            if p['from'] <= t < p['to']:
                return p['index']
        return parts[-1]['index']

    # уровень реплики: музыка на duck_db ниже речи (речь — с поправкой голоса), база части — медиана
    speech_db = dsp.speech_levels(audio, replies)
    music_db = {r['num']: dsp.rms_db(bed, int(r['start'] * ASR), int(r['end'] * ASR)) for r in replies}
    want = {n: speech_db[n] - setting(cfg, 'duck_db') - music_db[n] for n in speech_db}
    base = {}
    for p in parts:
        v = sorted(want[r['num']] for r in replies if part_of(r['start']) == p['index'])
        base[p['index']] = v[len(v) // 2] if v else DEFAULT_BASE_DB
    duck = {r['num']: min(base[part_of(r['start'])], speech_db[r['num']] - setting(cfg, 'duck_min_db') - music_db[r['num']])
            for r in replies}

    # эффекты: план по событиям фильма, синтез, уровень по речи — до поправки микса
    sfx_track, sfx_cues, sfx_dropped, _ = sfx.build_track(audio, film, replies, speech_db)
    sfx_raw = os.path.join(tmp, 'sfx.raw')
    with open(sfx_raw, 'wb') as fh:
        fh.write(sfx_track.tobytes())
    del sfx_track

    pts = envelope_points(replies, lambda t: base[part_of(t)], duck, setting(cfg, 'raise_db'),
                          setting(cfg, 'raise_gap_sec'))
    env = envelope_samples(pts, replies[-1]['end'] + TAIL_FADE_FROM_LAST, dur)
    env_raw = os.path.join(tmp, 'env.raw')
    with open(env_raw, 'wb') as fh:
        fh.write(env.tobytes())
    ceil_db = setting(cfg, 'peak_dbtp') - setting(cfg, 'limiter_margin_db')
    n_end = int(round(dur * SR))

    def graph(gain_db, final=False):
        ins_b, ch_b = bed_graph(segs, tracks, SR, stereo=True)
        n_b = len(segs)
        ins_s, ch_s = dsp.speech_graph(audio, replies, n_b + 1)
        n_fx = n_b + 1 + len(replies)
        ins = (ins_b + ['-f', 'f32le', '-ar', str(ENV_RATE), '-ac', '1', '-i', env_raw] + ins_s
               + ['-f', 'f32le', '-ar', str(SR), '-ac', '1', '-i', sfx_raw])
        ch = ch_b + ch_s + [
            '[%d:a]apad,atrim=end_sample=%d,volume=%.4fdB,asplit=2[fx][fx1]' % (n_fx, n_end, gain_db),
            '[fx1]pan=stereo|c0=c0|c1=c0[fx2]',
            '[%d:a]aresample=%d,pan=stereo|c0=c0|c1=c0[env]' % (n_b, SR),
            '[bed][env]amultiply,atrim=end_sample=%d,volume=%.4fdB,asplit=2[mus][mus2]' % (n_end, gain_db),
            '[sp]volume=%.4fdB[sp2]' % gain_db,
            '[sp2][mus2][fx2]amix=inputs=3:normalize=0:dropout_transition=0,atrim=end_sample=%d,'
            'aresample=%d,alimiter=limit=%.6f:attack=2:release=60:level=false:latency=true,'
            'aresample=%d[mix]' % (n_end, SR * 4, 10 ** (ceil_db / 20), SR),
        ]
        if not final:
            ch.append('[mus]anullsink')
            ch.append('[fx]anullsink')
        fcp = os.path.join(tmp, 'mix.txt')
        with open(fcp, 'w', encoding='utf-8') as fh:
            fh.write(';'.join(ch))
        return ins, fcp

    # проход 2: громкость микса без поправки → статическая поправка до target_lufs
    target = setting(cfg, 'target_lufs')
    ins, fcp = graph(0.0)
    probe = os.path.join(tmp, 'probe.wav')
    dsp.run([dsp.FF, '-v', 'error', '-y'] + ins + ['-filter_complex_script', fcp, '-map', '[mix]',
            '-c:a', 'pcm_f32le', '-f', 'wav', probe])
    i0, _ = dsp.lufs(['-i', probe])
    gain = target - i0
    for _ in range(3):
        # ограничитель срезает пики после поправки — уточнить по факту
        ins, fcp = graph(gain)
        dsp.run([dsp.FF, '-v', 'error', '-y'] + ins + ['-filter_complex_script', fcp, '-map', '[mix]',
                '-c:a', 'pcm_f32le', '-f', 'wav', probe])
        i1, _ = dsp.lufs(['-i', probe])
        if abs(i1 - target) < 0.15:
            break
        gain += target - i1
    gain = round(gain, 2)

    # финал: music.wav, sfx.wav и mix.m4a — атомарно
    os.makedirs(audio.out, exist_ok=True)
    ins, fcp = graph(gain, final=True)
    tw, tx, tm = atomic_out(audio.music_wav), atomic_out(audio.sfx_wav), atomic_out(audio.mix_m4a)
    dsp.run([dsp.FF, '-v', 'error', '-y'] + ins + ['-filter_complex_script', fcp,
            '-map', '[mus]', '-c:a', 'pcm_s16le', '-ar', str(SR)] + dsp.BITEXACT + ['-f', 'wav', tw,
            '-map', '[fx]', '-c:a', 'pcm_s16le', '-ar', str(SR)] + dsp.BITEXACT + ['-f', 'wav', tx,
            '-map', '[mix]', '-c:a', 'aac', '-b:a', AAC_BITRATE, '-ar', str(SR)] + dsp.BITEXACT
            + ['-movflags', '+faststart', '-f', 'ipod', tm])
    os.replace(tw, audio.music_wav)
    os.replace(tx, audio.sfx_wav)
    os.replace(tm, audio.mix_m4a)

    i_mix, tp_mix = dsp.lufs(['-i', str(audio.mix_m4a)])
    cues = {
        'film': audio.film_name, 'film_duration': dur,
        'parts': [{'part': p['index'], 'chapters': p['chapters'], 'track': cfg['tracks'][p['track']]['file'],
                   'license': cfg['tracks'][p['track']]['license'], 'from': round(p['from'], 4), 'to': round(p['to'], 4)}
                  for p in parts],
        'segments': [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in dict(s, track=tracks[s['track']]['file']).items()}
                     for s in segs],
        'tracks': {t['file']: {'lufs': round(t['lufs'], 2), 'norm_db': round(t['norm_db'], 2), 'loop_in': t['a'],
                               'loop_out': t['b'], 'loop_corr': t['loop_corr'], 'loop_by': t['loop_by']}
                   for t in tracks.values()},
        'part_base_db': {str(k): round(v, 2) for k, v in base.items()},
        'voice_gain_db': {r['voice']: audio.voice_gain_db(r['voice']) for r in replies},
        'mix_gain_db': gain, 'mix_lufs': i_mix, 'mix_true_peak': tp_mix,
        'sfx': [sfx.cue_record(c) for c in sfx_cues], 'sfx_dropped': sfx_dropped,
        'sha1': {'music.wav': dsp.sha1(audio.music_wav), 'mix.m4a': dsp.sha1(audio.mix_m4a),
                 'sfx.wav': dsp.sha1(audio.sfx_wav)},
    }
    config.write_json(audio.cues, cues)
    print('  части: %s' % '; '.join('%s → %s' % ('+'.join(p['chapters']), cfg['tracks'][p['track']]['file']) for p in parts))
    print('  база частей, дБ к нормированному треку:', cues['part_base_db'])
    print('  поправка микса %+.2f дБ → %.1f LUFS, true peak %.1f dBTP' % (gain, i_mix, tp_mix))
    print('  эффекты: %d, выпало по плотности %d' % (len(sfx_cues), len(sfx_dropped)))
    sfx.print_plan(sfx_cues, sfx_dropped)
    print('  →', audio.music_wav, '·', audio.sfx_wav, '·', audio.mix_m4a)
    for c in cues['parts']:
        if str(c['license']).upper().startswith('ЗАГЛУШКА'):
            print('  ВНИМАНИЕ: трек %s — заглушка; заменить треком с лицензией (music.json tracks[].license)' % c['track'])


def mux(audio):
    for p in (audio.video, audio.mix_m4a):
        if not p.exists():
            raise SystemExit('нет %s — %s' % (p, 'фильм ещё не отрендерен (build.py без --page)' if p == audio.video
                                               else 'сначала сборка микса'))
    dur = audio.film()['duration']
    r = subprocess.run([dsp.FF, '-v', 'error', '-i', str(audio.video), '-map', '0:v', '-c', 'copy', '-f', 'null', '-'],
                           capture_output=True)
    if r.returncode:
        raise SystemExit('video.mp4 не читается (рендер ещё пишет?): %s' % r.stderr.decode('utf-8', 'replace')[-400:])
    tv = atomic_out(audio.video_music)
    dsp.run([dsp.FF, '-v', 'error', '-y', '-i', str(audio.video), '-i', str(audio.mix_m4a), '-map', '0:v:0',
             '-map', '1:a:0', '-c', 'copy', '-t', '%.4f' % dur, '-movflags', '+faststart'] + dsp.BITEXACT
            + ['-f', 'mp4', tv])
    os.replace(tv, audio.video_music)
    print('  →', audio.video_music)


def main():
    ap = argparse.ArgumentParser(description='Музыка и микс ролика (engine/audio)')
    ap.add_argument('film', nargs='?', help='имя фильма — папка в <out>/')
    ap.add_argument('--mux', action='store_true', help='собрать video-music.mp4: видео копией, звук — mix.m4a')
    ap.add_argument('--placeholder', metavar='FILE', help='записать пэд-заглушку трека и выйти')
    ap.add_argument('--root', type=int, default=220, help='основной тон пэда-заглушки, Гц (целое)')
    pdir, argv = config.project_root.split_argv(sys.argv[1:])    # --project → MOTION_PROJECT → <шаблон>/project
    args = ap.parse_args(argv)
    if args.placeholder:
        synth.make_pad(args.placeholder, root_hz=args.root)
        print('  →', args.placeholder, '(заглушка: заменить треком с лицензией)')
        return
    if not args.film:
        ap.error('нужен фильм (или --placeholder FILE)')
    audio = config.Audio(pdir, args.film)
    tmp = tempfile.mkdtemp(prefix='motion-music-')
    try:
        build(audio, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if args.mux:
        mux(audio)


if __name__ == '__main__':
    main()
