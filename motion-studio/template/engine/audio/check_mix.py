# -*- coding: utf-8 -*-
"""Проверка звука ролика: построчно, код 0 — всё зелёное, 1 — есть красное.

    python engine/audio/check_mix.py <фильм> [--project DIR] [--final]
    python engine/audio/check_mix.py <фильм> [--project DIR] --red [подстрока ...]   порчи
    python engine/audio/check_mix.py <фильм> [--project DIR] --samples [подстрока ...]  законные варианты

Читает только результат на диске (`<out>/<фильм>/`: film.json, music.wav, sfx.wav, mix.m4a, cues.json,
video.mp4, video-music.mp4) и конфиги проекта (music.json, sfx.json, project.json) как спецификацию;
код сборки (`music.py`, `sfx.py`) не импортирует — ожидаемое выводится здесь своим способом. Для порчи M4
(двухтрековый фикстур) `--red` запускает `music.py` подпроцессом на копии проекта во временной папке.
`--final` — перед показом пользователю: трек-заглушка (license начинается с «ЗАГЛУШКА») краснеет.

Условия без тематических констант (план треков и каталог событий берутся из music.json / sfx.json
и film.json):

  M1  длины music.wav, mix.m4a, sfx.wav и звука video-music.mp4 = фильм ± 1 кадр
  M2  части и треки по плану (главы фильма × music.json); у каждого трека указана лицензия
  M3  на каждой части звучит свой трек: волна music.wav коррелирует с исходником в трёх точках
  M4  стык треков — на ходе полосы главы ± 0,5 с (МНК-разложение волны на оба исходника)
  M5  во всех репликах музыка ниже речи не меньше margin_min_db (RMS интервала: микс против музыки)
  M6  клиппинга нет: true peak микса ≤ peak_dbtp, пик music.wav < 0 dBFS
  M7  громкость микса target_lufs ± lufs_tol
  M8  video-music.mp4: видеопоток бит в бит из video.mp4 (хеш пакетов), звук — микс
  M9  голоса ровно: медианы громкости реплик каждого голоса в готовом миксе расходятся ≤ voice_tol_db
  M10 события фильма (film.json.events × sfx.json) ↔ эффекты (метки) ↔ звук sfx.wav, ± 1 кадр, в обе стороны
  M11 под речью эффект ≤ under_speech_max_db к реплике, в паузе ≤ pause_max_db к соседней речи
  M12 начала эффектов не ближе min_gap_sec
  M13 выше hf_cut_hz эффект не громче музыки (или тише порога слышимости)
  M14 эффекты дошли до микса: в паузе волна микса = музыка + эффекты (МНК, вес 1,0 ± 0,3)
"""
import array
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from operator import mul
from pathlib import Path

sys.dont_write_bytecode = True
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

import imageio_ffmpeg

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE.parents[1]
FF = imageio_ffmpeg.get_ffmpeg_exe()

# ---- техника промера (калибровка на прошлом ролике; не цели сборки)
JUNCTION_TOL = 0.5      # стык треков — в пределах ± от хода полосы главы
WAVE_RATE = 8000
WAVE_LOWPASS = 1000     # волна сверяется ниже 1 кГц: сдвиг до половины отсчёта на 2 кГц съедал корреляцию
WAVE_MIN_CORR = 0.8     # волна той же записи после двух передискретизаций — ≥ 0,95 на образце
LAG_SEC = 0.002
WAVE_WIN = 3.0          # тихие места трека в моно-сумме шумят: окно в 1 с давало 0,69
WAVE_SUB = 0.5          # подокно: усиление огибающей в нём почти постоянно
RMS_RATE = 8000
SFX_RATE = 22050        # промер эффектов: до 11 кГц — синтез выше 6,5 кГц не идёт, полоса 8+ кГц видна
SFX_FRAME = 110         # кадр 5 мс на SFX_RATE
SFX_WIN_FRAMES = 80     # окно RMS 400 мс
HF_FLOOR_DB = -75.0     # тише этого (dBFS) полоса выше hf_cut_hz не слышна и не сравнивается
SFX_WEIGHT, SFX_WEIGHT_TOL = 1.0, 0.3
ONSET_RISE_DB = 9.0     # удар: кадр 5 мс громче максимума 4 предыдущих на столько
ONSET_FLOOR_DB = -80.0  # и не тише этого (dBFS)
SILENCE_FRAMES = 60     # начало из тишины: перед ним ≥ 0,3 с цифрового нуля
MARK_MERGE = 0.04       # отметки ближе — одна
PLACEHOLDER = 'ЗАГЛУШКА'

_cache = {}


def ff(cmd):
    r = subprocess.run([FF] + cmd, capture_output=True)
    if r.returncode:
        raise RuntimeError(r.stderr.decode('utf-8', 'replace')[-600:])
    return r


def read_json(path):
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def decode(path, rate, lowpass=None):
    st = os.stat(path)
    key = (str(path), rate, lowpass, st.st_size, st.st_mtime_ns)
    if key not in _cache:
        af = ['-af', 'lowpass=f=%d' % lowpass] if lowpass else []
        r = ff(['-v', 'error', '-i', str(path), '-map', '0:a:0'] + af + ['-ac', '1', '-ar', str(rate), '-f', 's16le', '-'])
        a = array.array('h')
        a.frombytes(r.stdout)
        _cache[key] = a
    return _cache[key]


def decode_hp(path, rate, cut):
    st = os.stat(path)
    key = ('hp', str(path), rate, cut, st.st_size, st.st_mtime_ns)
    if key not in _cache:
        r = ff(['-v', 'error', '-i', str(path), '-map', '0:a:0', '-af', 'highpass=f=%d,highpass=f=%d' % (cut, cut),
                '-ac', '1', '-ar', str(rate), '-f', 's16le', '-'])
        a = array.array('h')
        a.frombytes(r.stdout)
        _cache[key] = a
    return _cache[key]


def loud(path):
    st = os.stat(path)
    key = ('loud', str(path), st.st_size, st.st_mtime_ns)
    if key not in _cache:
        e = ff(['-hide_banner', '-nostats', '-i', str(path), '-map', '0:a:0', '-af', 'ebur128=peak=true+sample',
                '-f', 'null', '-']).stderr.decode('utf-8', 'replace')
        s = e[e.rfind('Summary:'):]
        num = r'(-?[\d.]+|-inf)'
        i = float(re.search(r'I:\s+' + num + ' LUFS', s).group(1))
        pk = re.findall(r'Peak:\s+' + num + ' dBFS', s)
        _cache[key] = (i, float(pk[0]), float(pk[1]))   # I, true peak, sample peak
    return _cache[key]


def voice_loudness(path, replies):
    """{голос: [громкость реплики, LUFS]} по готовому миксу. Один проход ebur128 с журналом кадров:
    M каждые 100 мс — громкость окна 400 мс, заканчивающегося в t (блок BS.1770). Реплика — блоки целиком
    внутри [start, end], абсолютный строб −70, относительный −10."""
    st = os.stat(path)
    key = ('voices', str(path), st.st_size, st.st_mtime_ns)
    if key not in _cache:
        e = ff(['-hide_banner', '-nostats', '-v', 'verbose', '-i', str(path), '-map', '0:a:0',
                '-af', 'ebur128=framelog=verbose', '-f', 'null', '-']).stderr.decode('utf-8', 'replace')
        _cache[key] = [(float(t), float(m)) for t, m in
                       re.findall(r't:\s*([\d.]+)\s+TARGET:\S+\s+LUFS\s+M:\s*(-?[\d.]+)', e)]
    blocks = _cache[key]
    out = {}
    for r in replies:
        ms = [m for t, m in blocks if t - 0.4 >= r['start'] - 1e-6 and t <= r['end'] + 1e-6 and m > -70.0]
        if not ms:
            continue
        rel = 10 * math.log10(sum(10 ** (m / 10) for m in ms) / len(ms)) - 10.0
        ms = [m for m in ms if m > rel]
        out.setdefault(r['voice'], []).append(10 * math.log10(sum(10 ** (m / 10) for m in ms) / len(ms)))
    return out


def median(v):
    v = sorted(v)
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2


def rms_db(a, i0, i1):
    i0, i1 = max(0, i0), min(len(a), i1)
    if i1 <= i0:
        return -120.0
    return 10 * math.log10(sum(x * x for x in a[i0:i1]) / (i1 - i0) / 32768.0 ** 2 + 1e-12)


def edb(e):
    return 10 * math.log10(e / 32768.0 ** 2 + 1e-20)


def corr(x, y):
    n = min(len(x), len(y))
    if n < 2:
        return 0.0
    x, y = x[:n], y[:n]
    mx, my = sum(x) / n, sum(y) / n
    sxy = sum(map(mul, x, y)) - n * mx * my
    sxx = sum(map(mul, x, x)) - n * mx * mx
    syy = sum(map(mul, y, y)) - n * my * my
    return sxy / math.sqrt(sxx * syy) if sxx > 1e-9 and syy > 1e-9 else 0.0


def best_lag(m, src, i_m, i_s, n, lag, sub=None):
    """Корреляция окна музыки [i_m, i_m+n) с исходником около i_s, сдвиг ± lag отсчётов.
    sub — подокно: огибающая громкости под репликами меняет усиление внутри окна, поэтому корреляция
    считается по подокнам (усиление в них почти постоянно) и берётся медиана."""
    sub = sub or n
    best = (-2.0, 0)
    for d in range(-lag, lag + 1):
        if i_s + d < 0:
            continue
        cs = sorted(corr(m[i_m + k:i_m + k + sub], src[i_s + d + k:i_s + d + k + sub])
                    for k in range(0, n - sub + 1, sub))
        c = cs[len(cs) // 2]
        if c > best[0]:
            best = (c, d)
    return best


# ---------------------------------------------------------------- спецификация из конфигов и фильма

def expected_parts(film, mcfg):
    """Части музыки по главам фильма и music.json — свой вывод проверки: [(главы, файл, момент начала)]."""
    sc = film['scenes'][0]
    cur = sc.get('chapter_from') or sc.get('chapter')
    tl = [(0.0, cur)]
    for e in sorted((e for e in film.get('events', []) if e['kind'] == 'chapter'), key=lambda e: e['t']):
        if e['ref'] != cur:
            cur = e['ref']
            tl.append((e['t'] + e.get('dur', 0.0) / 2, cur))

    def file_of(ch):
        tr = mcfg['tracks']
        for t in tr:
            if t['chapter'] == ch:
                return t['file']
        for t in tr:
            if t['chapter'] == '*':
                return t['file']
        return None
    parts = []
    for t0, ch in tl:
        f = file_of(ch)
        if parts and parts[-1][1] == f:
            parts[-1][0].append(ch)
        else:
            parts.append([[ch], f, t0])
    return [(p[0], p[1], p[2]) for p in parts]


def expected_events(film, scfg):
    """Каталог sfx.json × события film.json: [(клип, момент удара, приоритет, подпись)]. Первое подходящее правило."""
    out = []
    for e in film.get('events', []):
        for r in scfg['events']:
            if r['kind'] != e['kind']:
                continue
            if any((e.get(k) not in v) if isinstance(v, list) else (e.get(k) != v) for k, v in (r.get('match') or {}).items()):
                continue
            shift = {'start': 0.0, 'end': e.get('dur', 0.0), 'mid': e.get('dur', 0.0) / 2}[r.get('anchor', 'start')]
            out.append((r['clip'], e['t'] + shift, r['prio'], '%s %s' % (e['kind'], e.get('ref'))))
            break
    return out


# ---------------------------------------------------------------- отметки звука эффектов

def frames(path):
    """sfx.wav → (энергия кадров 5 мс, максимум модуля кадра, индекс первого ненулевого отсчёта кадра)."""
    st = os.stat(path)
    key = ('frames', str(path), st.st_size, st.st_mtime_ns)
    if key not in _cache:
        a = decode(path, SFX_RATE)
        en, pk, first = [], [], []
        for i in range(0, len(a) - SFX_FRAME + 1, SFX_FRAME):
            seg = a[i:i + SFX_FRAME]
            en.append(sum(x * x for x in seg) / SFX_FRAME)
            m, n = max(seg), min(seg)
            pk.append(max(m, -n))
            first.append(next(k for k, x in enumerate(seg) if x) if (m or n) else None)
        _cache[key] = (en, pk, first)
    return _cache[key]


def audio_marks(path):
    """Отметки звука эффектов: начала из тишины и удары, слитые ближе MARK_MERGE."""
    en, pk, first = frames(path)
    dt = SFX_FRAME / SFX_RATE
    marks, quiet = [], SILENCE_FRAMES
    for i in range(len(en)):
        if pk[i] == 0:
            quiet += 1
            continue
        if quiet >= SILENCE_FRAMES:
            marks.append(('начало', (i * SFX_FRAME + first[i]) / SFX_RATE))
        elif i >= 4:
            e = edb(en[i])
            prev = max(edb(en[j]) for j in range(i - 4, i))
            if e >= ONSET_FLOOR_DB and e - prev >= ONSET_RISE_DB:
                marks.append(('удар', i * dt))
        quiet = 0
    out = []
    for kind, t in marks:
        if out and t - out[-1][1] < MARK_MERGE:
            continue
        out.append((kind, t))
    return out


def cue_marks(cues):
    ts = sorted(set([c['onset'] for c in cues] + [c['hit'] for c in cues]))
    out = []
    for t in ts:
        if out and t - out[-1] < MARK_MERGE:
            continue
        out.append(t)
    return out


# ---------------------------------------------------------------- проверка

def check(paths, log=print, final=False):
    fails = []

    def ok(cond, line):
        log(('  ok  ' if cond else '  ПРОВАЛ  ') + line)
        if not cond:
            fails.append(line)
        return cond

    film = read_json(paths['film'])
    mcfg, scfg = read_json(paths['music_cfg']), read_json(paths['sfx_cfg'])
    pcfg = read_json(paths['project_cfg'])
    root = Path(paths['root'])
    if pcfg.get('fps') is None:
        raise SystemExit('project.json: нет обязательного поля fps')
    fps = int(pcfg['fps'])
    dur = film['duration']
    frame = 1.0 / fps
    lufs_target, lufs_tol = mcfg.get('target_lufs', -16.0), mcfg.get('lufs_tol', 1.0)
    tp_max = mcfg.get('peak_dbtp', -1.0)
    margin_min, voice_tol = mcfg.get('margin_min_db', 15.0), mcfg.get('voice_tol_db', 0.5)
    label = {'music': 'music.wav', 'mix': 'mix.m4a'}
    for key in ('music', 'mix'):
        if not ok(os.path.exists(paths[key]), 'M1 есть %s' % label[key]):
            return fails
    if not ok(os.path.exists(paths['cues']), 'M2 есть cues.json (метки сборки)'):
        return fails
    cues = read_json(paths['cues'])

    # M1 длина
    for key in ('music', 'mix'):
        d = len(decode(paths[key], RMS_RATE)) / RMS_RATE
        ok(abs(d - dur) <= frame, 'M1 длина %s %.3f с, фильм %.3f с (± 1 кадр)' % (label[key], d, dur))

    # M2 метки по плану
    want = expected_parts(film, mcfg)
    parts = cues.get('parts', [])
    got = [(p['chapters'], p['track']) for p in parts]
    plan = [(w[0], w[1]) for w in want]
    ok(got == plan, 'M2 части и треки по плану: %s' % ('да, частей %d' % len(plan) if got == plan else '%s вместо %s' % (got, plan)))
    if got == plan:
        off = [(p['part'], p['from'], w[2]) for p, w in zip(parts, want) if abs(p['from'] - w[2]) > frame]
        ok(not off, 'M2 границы частей на ходе полосы главы (± 1 кадр)%s' % (': сдвинуты %s' % off if off else ''))
    lic = [t['file'] for t in mcfg['tracks'] if not str(t.get('license', '')).strip()]
    ok(not lic, 'M2 лицензия указана у каждого трека%s' % (': нет у %s' % lic if lic else ''))
    stubs = [t['file'] for t in mcfg['tracks'] if str(t.get('license', '')).upper().startswith(PLACEHOLDER)]
    if final:
        ok(not stubs, 'M2 лицензия: нет треков-заглушек для показа%s' % (': %s' % stubs if stubs else ''))
    elif stubs:
        log('  --  M2 лицензия: трек-заглушка %s — заменить треком с лицензией до показа (--final краснеет)' % ', '.join(stubs))

    # M3 свой трек на каждой части — волной по меткам
    m4 = decode(paths['music'], WAVE_RATE, WAVE_LOWPASS)
    segs = cues.get('segments', [])
    tracks = {}
    lag = int(LAG_SEC * WAVE_RATE)

    def src(f):
        if f not in tracks:
            tracks[f] = decode(root / f, WAVE_RATE, WAVE_LOWPASS)
        return tracks[f]
    for k, p in enumerate(parts):
        p0, p1 = p['from'], p['to']
        mine = [s for s in segs if s['part'] == p['part']]
        if not ok((root / p['track']).exists() and bool(mine), 'M3 часть %d: есть файл трека %s и сегменты в метках' % (k, p['track'])):
            continue
        cs = []
        for frac in (0.25, 0.5, 0.75):
            t = p0 + (p1 - p0) * frac
            sg = [s for s in mine if s['at'] + s['fade_in'] + 0.5 <= t
                  and t + WAVE_WIN + 0.5 <= s['at'] + (s['src1'] - s['src0']) - s['fade_out']]
            if not sg:      # точка попала в склейку круга или часть короче окна — к середине ближайшего сегмента
                s = min(mine, key=lambda s: abs(s['at'] + (s['src1'] - s['src0']) / 2 - t))
                t = s['at'] + (s['src1'] - s['src0']) / 2
            else:
                s = sg[0]
            src_t = s['src0'] + (t - s['at'])
            c, _ = best_lag(m4, src(p['track']), round(t * WAVE_RATE), round(src_t * WAVE_RATE),
                            int(WAVE_WIN * WAVE_RATE), lag, int(WAVE_SUB * WAVE_RATE))
            cs.append(c)
        ok(min(cs) >= WAVE_MIN_CORR, 'M3 часть %d (%s) звучит %s: корреляция волны %s (≥ %.2f)'
           % (k, '+'.join(p['chapters']), p['track'], ' / '.join('%.2f' % c for c in cs), WAVE_MIN_CORR))

    # M4 стыки у полос глав
    if len(parts) < 2:
        log('  --  M4 стыков нет: одна часть (один трек на весь фильм)')
    for k in range(1, len(parts)):
        if not all((root / parts[j]['track']).exists() for j in (k - 1, k)):
            ok(False, 'M4 стык части %d → %d: нет файла трека' % (k - 1, k))
            continue
        b = want[k][2] if k < len(want) else parts[k]['from']
        old = [s for s in segs if s['part'] == parts[k - 1]['part']][-1]
        new = [s for s in segs if s['part'] == parts[k]['part']][0]
        xo, xn = src(parts[k - 1]['track']), src(parts[k]['track'])
        db_o, db_n = loud(root / parts[k - 1]['track'])[0], loud(root / parts[k]['track'])[0]
        n = int(0.25 * WAVE_RATE)
        cross, t = None, b - 3.0
        while t <= b + 3.0:
            im = round(t * WAVE_RATE)
            io = round((old['src0'] + t - old['at']) * WAVE_RATE)
            inn = round((new['src0'] + t - new['at']) * WAVE_RATE)
            m = m4[im:im + n]
            zero = array.array('h', bytes(2 * n))
            # исходник участвует только там, где его сегмент по меткам лежит на шкале
            on_o = t + 0.25 <= old['at'] + old['src1'] - old['src0']
            on_n = t >= new['at']
            x = xo[io:io + n] if on_o and 0 <= io and io + n <= len(xo) else zero
            y = xn[inn:inn + n] if on_n and 0 <= inn and inn + n <= len(xn) else zero
            if len(x) < n:
                x = zero
            if len(y) < n:
                y = zero
            sxx = sum(v * v for v in x)
            syy = sum(v * v for v in y)
            sxy = sum(x[i] * y[i] for i in range(n))
            sxm = sum(x[i] * m[i] for i in range(min(n, len(m))))
            sym = sum(y[i] * m[i] for i in range(min(n, len(m))))
            det = sxx * syy - sxy * sxy
            if det > 0:
                al, be = (sxm * syy - sym * sxy) / det, (sym * sxx - sxm * sxy) / det
            else:
                al, be = (sxm / sxx if sxx else 0.0), (sym / syy if syy else 0.0)
            # усиление, приведённое к громкости исходника: равны — значит треки слышны поровну
            go, gn = abs(al) * 10 ** (db_o / 20), abs(be) * 10 ** (db_n / 20)
            if cross is None and gn >= go and gn > 0:
                cross = t + 0.125
            t += 0.05
        ok(cross is not None and abs(cross - b) <= JUNCTION_TOL,
           'M4 стык части %d → %d: в звуке %s, полоса главы %.2f (± %.1f с)'
           % (k - 1, k, '%.2f' % cross if cross is not None else 'не найден', b, JUNCTION_TOL))

    # M5 музыка ниже речи в каждой реплике
    mu, mx = decode(paths['music'], RMS_RATE), decode(paths['mix'], RMS_RATE)
    voiced = [r for r in film['replies'] if r.get('file')]
    worst, bad, margins = None, [], []
    for r in voiced:
        i0, i1 = int(r['start'] * RMS_RATE), int(r['end'] * RMS_RATE)
        margin = rms_db(mx, i0, i1) - rms_db(mu, i0, i1)
        margins.append(margin)
        if worst is None or margin < worst[0]:
            worst = (margin, r['num'])
        if margin < margin_min:
            bad.append('%d (%.1f дБ)' % (r['num'], margin))
    margins.sort()
    ok(not bad, 'M5 музыка ниже речи ≥ %.0f дБ во всех репликах: худшая реплика %d — %.1f дБ, медиана %.1f дБ%s'
       % (margin_min, worst[1], worst[0], margins[len(margins) // 2], ('; ниже порога: ' + ', '.join(bad[:8])) if bad else ''))

    # M6 клиппинг, M7 громкость
    i_mix, tp_mix, sp_mix = loud(paths['mix'])
    _, _, sp_mus = loud(paths['music'])
    ok(tp_mix <= tp_max and sp_mix < 0, 'M6 нет клиппинга: микс true peak %.1f dBTP (≤ %.1f), пик %.1f dBFS'
       % (tp_mix, tp_max, sp_mix))
    ok(sp_mus < -0.1, 'M6 нет клиппинга: music.wav пик %.1f dBFS' % sp_mus)
    ok(abs(i_mix - lufs_target) <= lufs_tol, 'M7 громкость микса %.1f LUFS (%.0f ± %.0f)' % (i_mix, lufs_target, lufs_tol))

    # M9 голоса ровно — по миксу
    vl = voice_loudness(paths['mix'], voiced)
    have = {r['voice'] for r in voiced}
    if ok(set(vl) == have, 'M9 в миксе промерены все голоса: %s' % ', '.join('%s %d' % (k, len(v)) for k, v in sorted(vl.items()))):
        med = {k: median(v) for k, v in vl.items()}
        if len(med) < 2:
            log('  --  M9 голос один — сравнивать не с чем')
        else:
            spread = max(med.values()) - min(med.values())
            ok(spread <= voice_tol, 'M9 голоса ровно: медианы %s LUFS, разброс %.2f дБ (≤ %.1f)'
               % (', '.join('%s %.2f' % kv for kv in sorted(med.items())), spread, voice_tol))

    # M1, M10–M14 звуковые эффекты
    if ok(os.path.exists(paths['sfx']), 'M1 есть sfx.wav'):
        d = len(decode(paths['sfx'], RMS_RATE)) / RMS_RATE
        ok(abs(d - dur) <= frame, 'M1 длина sfx.wav %.3f с, фильм %.3f с (± 1 кадр)' % (d, dur))
        check_sfx(paths, film, scfg, cues, ok, mx, frame, log, voiced)

    # M8 video-music.mp4
    vm = paths['video_music']
    if os.path.exists(vm):
        def vhash(p):
            return ff(['-v', 'error', '-i', str(p), '-map', '0:v:0', '-c', 'copy', '-f', 'streamhash',
                       '-hash', 'md5', '-']).stdout.decode().strip()
        if ok(os.path.exists(paths['video']), 'M8 есть video.mp4 для сверки'):
            hv, hm = vhash(paths['video']), vhash(vm)
            ok(hv == hm, 'M8 видео video-music.mp4 скопировано из video.mp4 без перекодирования: %s'
               % ('хеши пакетов равны' if hv == hm else 'хеши пакетов разные'))
        da = len(decode(vm, RMS_RATE)) / RMS_RATE
        ok(abs(da - dur) <= frame, 'M1 длина звука video-music.mp4 %.3f с, фильм %.3f с' % (da, dur))
        a1 = decode(vm, RMS_RATE)
        ok(len(a1) == len(mx) and corr(a1[::50], mx[::50]) > 0.999, 'M8 звук video-music.mp4 — микс mix.m4a')
    else:
        log('  --  M8 video-music.mp4 нет — пропущено (нужен music.py --mux после рендера video.mp4)')
    return fails


def check_sfx(paths, film, scfg, cues, ok, mx, frame, log, voiced):
    fx = cues.get('sfx', [])
    dropped = cues.get('sfx_dropped', [])
    min_gap = scfg.get('min_gap_sec', 1.5)
    under_max, pause_max = scfg.get('under_speech_max_db', -18.0), scfg.get('pause_max_db', -10.0)
    hf_cut = scfg.get('hf_cut_hz', 8000)

    # M10 привязка к фильму
    ev = expected_events(film, scfg)
    bound, missing = set(), []
    for clip, hit, prio, title in ev:
        c = [c for c in fx if c['clip'] == clip and abs(c['hit'] - hit) <= frame]
        if c:
            bound.add(c[0]['id'])
            continue
        dr = [d for d in dropped if abs(d['hit'] - hit) <= frame]
        if dr and any(abs(c['onset'] - dr[0]['onset']) < min_gap and c['prio'] >= prio for c in fx):
            continue
        missing.append('%s %.2f' % (title, hit))
    ok(not missing, 'M10 события фильма → эффекты: событий каталога %d, эффектов %d, выпало по плотности %d%s'
       % (len(ev), len(fx), len(dropped), ('; без эффекта: ' + ', '.join(missing[:6])) if missing else ''))
    extra = ['%s %s %.2f' % (c['id'], c['clip'], c['hit']) for c in fx if c['id'] not in bound]
    ok(not extra, 'M10 эффекты без события фильма: %s' % (', '.join(extra[:6]) if extra else 'нет'))

    # M10 звук ↔ метки
    am = audio_marks(paths['sfx'])
    cm = cue_marks(fx)
    lone = ['%s %.3f' % (k, t) for k, t in am if not any(abs(t - x) <= frame for x in cm)]
    mute = ['%.3f' % x for x in cm if not any(abs(t - x) <= frame for _, t in am)]
    ok(not lone and not mute, 'M10 звук ↔ метки: отметок в sfx.wav %d, в метках %d (± 1 кадр)%s%s'
       % (len(am), len(cm), ('; звук без метки: ' + ', '.join(lone[:6])) if lone else '',
          ('; метка без звука: ' + ', '.join(mute[:6])) if mute else ''))

    # M11 уровень: реплики и паузы
    en, pk, first = frames(paths['sfx'])
    dt = SFX_FRAME / SFX_RATE

    def win_db(t0, t1):
        j0, j1 = int(math.ceil(t0 / dt - 1e-9)), min(len(en), int(math.floor(t1 / dt + 1e-9)))
        n = j1 - j0
        if n <= 0:
            return None
        w = max(1, min(SFX_WIN_FRAMES, n))
        s = sum(en[j0:j0 + w])
        best = s
        for i in range(j0 + w, j1):
            s += en[i] - en[i - w]
            best = max(best, s)
        return None if best <= 0 else edb(best / w)
    sp = {r['num']: rms_db(mx, int(r['start'] * RMS_RATE), int(r['end'] * RMS_RATE)) for r in voiced}
    under, pause = [], []
    for i, r in enumerate(voiced):
        m = win_db(r['start'], r['end'])
        if m is not None:
            under.append((m - sp[r['num']], 'реплика %d' % r['num']))
        a = voiced[i - 1]['end'] if i else 0.0
        if r['start'] > a:
            m = win_db(a, r['start'])
            if m is not None:
                ref = (sp[r['num']] + sp[voiced[i - 1]['num']]) / 2 if i else sp[r['num']]
                pause.append((m - ref, 'пауза %.1f–%.1f' % (a, r['start'])))
    m = win_db(voiced[-1]['end'], film['duration'])
    if m is not None:
        pause.append((m - sp[voiced[-1]['num']], 'хвост фильма'))
    wu = max(under) if under else (-200.0, '—')
    wp = max(pause) if pause else (-200.0, '—')
    bad_u = ['%s %+.1f' % (w, d) for d, w in under if d > under_max]
    bad_p = ['%s %+.1f' % (w, d) for d, w in pause if d > pause_max]
    ok(not bad_u, 'M11 эффекты под речью ≤ %+.0f дБ к реплике: реплик с эффектом %d, худшая %s %+.1f дБ%s'
       % (under_max, len(under), wu[1], wu[0], ('; громче: ' + ', '.join(bad_u[:6])) if bad_u else ''))
    ok(not bad_p, 'M11 эффекты в паузах ≤ %+.0f дБ к соседней речи: пауз с эффектом %d, худшая %s %+.1f дБ%s'
       % (pause_max, len(pause), wp[1], wp[0], ('; громче: ' + ', '.join(bad_p[:6])) if bad_p else ''))

    # M12 плотность
    on = sorted((c['onset'], c['id']) for c in fx)
    gaps = [(b[0] - a[0], a[1], b[1]) for a, b in zip(on, on[1:])]
    close = ['%s–%s %.2f с' % (a, b, g) for g, a, b in gaps if g < min_gap]
    ok(not close, 'M12 плотность: начала эффектов не ближе %.1f с, наименьший промежуток %s%s'
       % (min_gap, '%.2f с' % min(gaps)[0] if gaps else '—', ('; ближе: ' + ', '.join(close[:6])) if close else ''))

    # M13 спектр выше hf_cut
    hs_, hm = decode_hp(paths['sfx'], SFX_RATE, hf_cut), decode_hp(paths['music'], SFX_RATE, hf_cut)
    loud_hf, worst = [], None
    for c in fx:
        i0, i1 = int(c['onset'] * SFX_RATE), int(c['end'] * SFX_RATE)
        e = edb(sum(x * x for x in hs_[i0:i1]) / max(1, i1 - i0))
        mu = edb(sum(x * x for x in hm[i0:i1]) / max(1, i1 - i0))
        d = e - max(mu, HF_FLOOR_DB)
        if worst is None or d > worst[0]:
            worst = (d, c['id'], e, mu)
        if d > 0:
            loud_hf.append('%s %.1f dBFS при музыке %.1f' % (c['id'], e, mu))
    ok(not loud_hf, 'M13 спектр: выше %d Гц эффекты не громче музыки (или тише %.0f dBFS): худший %s'
       % (hf_cut, HF_FLOOR_DB, '%s %.1f dBFS, музыка %.1f' % (worst[1], worst[2], worst[3]) if worst else '—')
       + (('; громче: ' + ', '.join(loud_hf[:4])) if loud_hf else ''))

    # M14 эффекты в миксе: МНК в паузах, где эффект громче всего
    sx, mm, xm = (decode(paths['sfx'], SFX_RATE), decode(paths['music'], SFX_RATE), decode(paths['mix'], SFX_RATE))
    ws = []
    for c in fx:
        if c['level']['where'] != 'пауза':
            continue
        i0, i1 = int((c['hit'] - 0.02) * SFX_RATE), int((c['hit'] + 0.30) * SFX_RATE)
        x, y, m = mm[i0:i1], sx[i0:i1], xm[i0:i1]
        sxx, syy = sum(v * v for v in x), sum(v * v for v in y)
        sxy = sum(a * b for a, b in zip(x, y))
        sxm, sym = sum(a * b for a, b in zip(x, m)), sum(a * b for a, b in zip(y, m))
        det = sxx * syy - sxy * sxy
        if det > 0 and syy > 0:
            ws.append((sym * sxx - sxm * sxy) / det)
    if not ws and not any(c['level']['where'] == 'пауза' for c in fx):
        log('  --  M14 эффектов в паузах нет — вес эффектов в миксе не промерен')
        return
    wmed = median(ws) if ws else None
    ok(wmed is not None and abs(wmed - SFX_WEIGHT) <= SFX_WEIGHT_TOL,
       'M14 эффекты в миксе: вес эффектов в волне микса (МНК, %d пауз) %s (%.1f ± %.1f)'
       % (len(ws), '%.2f' % wmed if wmed is not None else 'не промерен', SFX_WEIGHT, SFX_WEIGHT_TOL))


# ---------------------------------------------------------------- порчи и образцы

def make_paths(pdir, film_name):
    pdir = Path(pdir).resolve()
    pj = read_json(pdir / 'project.json')
    if not (pj.get('paths') or {}).get('out'):
        raise SystemExit('project.json: нет обязательного поля paths.out')
    out = pdir / pj['paths']['out'] / film_name
    return {'root': str(pdir), 'project_cfg': str(pdir / 'project.json'), 'music_cfg': str(pdir / 'music.json'),
            'sfx_cfg': str(pdir / 'sfx.json'), 'film': str(out / 'film.json'), 'cues': str(out / 'cues.json'),
            'music': str(out / 'music.wav'), 'sfx': str(out / 'sfx.wav'), 'mix': str(out / 'mix.m4a'),
            'video': str(out / 'video.mp4'), 'video_music': str(out / 'video-music.mp4')}


def two_track_fixture(paths, film_name, tmp):
    """Копия проекта с двумя треками (глава steps — свой, остальные — запасной): music.py строит её подпроцессом.
    Нужна порчам M3/M4: в демо один трек, стыков нет. Возвращает paths фикстура."""
    src = Path(paths['root'])
    dst = Path(tmp) / 'fx-proj'
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns('out', '.env', 'scenes', 'director'))
    out = dst / 'out' / film_name
    out.mkdir(parents=True)
    film = read_json(paths['film'])
    shutil.copy(paths['film'], out / 'film.json')
    subprocess.run([sys.executable, str(HERE / 'music.py'), '--placeholder', str(dst / 'music' / 'pad-b.wav'),
                    '--root', '262'], check=True, capture_output=True)
    mc = read_json(dst / 'music.json')
    base = mc['tracks'][0]
    chapters = [e['ref'] for e in film['events'] if e['kind'] == 'chapter']
    mc['tracks'] = [dict(base, chapter=chapters[-1], file='music/pad-b.wav', start_sec=18.0), dict(base)]
    (dst / 'music.json').write_text(json.dumps(mc, ensure_ascii=False, indent=1), encoding='utf-8')
    r = subprocess.run([sys.executable, str(HERE / 'music.py'), film_name, '--project', str(dst)], capture_output=True)
    if r.returncode:
        raise RuntimeError('фикстур не собрался: %s' % r.stdout.decode('utf-8', 'replace')[-600:])
    return make_paths(dst, film_name)


def red(pdir, film_name, only=(), mode='all'):
    """only — подстроки: прогнать порчи и образцы, где подстрока есть в названии или ожидаемой строке."""
    paths0 = make_paths(pdir, film_name)
    tmp = tempfile.mkdtemp(prefix='check-mix-red-')
    try:
        film = read_json(paths0['film'])
        dur = film['duration']
        quiet = lambda *a, **k: None   # noqa: E731
        cues0 = read_json(paths0['cues'])
        fx0 = cues0['sfx']
        voiced = [r for r in film['replies'] if r.get('file')]

        def conv(name, af, src, codec):
            p = os.path.join(tmp, name)
            ff(['-v', 'error', '-y', '-i', src, '-af', af] + codec + [p])
            return p
        wav = lambda name, af, src=paths0['music']: conv(name, af, src, ['-c:a', 'pcm_s16le'])   # noqa: E731
        m4a = lambda name, af, src=paths0['mix']: conv(name, af, src, ['-c:a', 'aac', '-b:a', '192k'])  # noqa: E731

        def edit_json(src, fn, name):
            data = read_json(src)
            fn(data)
            p = os.path.join(tmp, name)
            with open(p, 'w', encoding='utf-8') as fh:
                json.dump(data, fh, ensure_ascii=False)
            return p

        def cues_with(fn):
            return edit_json(paths0['cues'], fn, 'cues-%d.json' % id(fn))

        def voice_shift(voice, db):
            """Микс, где реплики голоса voice громче на db дБ (отрицательное — тише)."""
            spans = [(r['start'], r['end']) for r in voiced if r['voice'] == voice]
            en = '+'.join('between(t,%.3f,%.3f)' % sp for sp in spans)
            return lambda: {'mix': m4a('voice-%s-%d.m4a' % (voice, round(db * 100)),
                                       "volume=enable='%s':volume=%.2fdB" % (en, db))}

        by_clip = lambda clip, k=0: [c for c in fx0 if c['clip'] == clip][k]   # noqa: E731
        seam = [c for c in fx0 if c['event']['kind'] == 'seam'][0]
        ping1, ping2 = by_clip('ping'), by_clip('ping', 1)
        under_c = [c for c in fx0 if c['event']['kind'] == 'chapter'][0]   # самый громкий эффект под репликой
        spread0, hi_voice, lo_voice = voice_spread(paths0, voiced)
        pause_c = seam                        # эффект в паузе между сценами
        lone_t = 15.0                         # место без событий каталога рядом
        rep = voiced[len(voiced) // 2]
        gap_g = voice_gap(film, cues0) or 2.0

        def sfx_fc(name, graph, extra=()):
            p = os.path.join(tmp, name)
            ff(['-v', 'error', '-y', '-i', paths0['sfx']] + list(extra) + ['-filter_complex', graph, '-map', '[o]',
                                                                          '-c:a', 'pcm_s16le', '-ar', '44100', p])
            return p

        def moved(c, d, keep=False, name='moved.wav'):
            """Звук эффекта c переехал на d с (keep — оригинал остаётся: копия)."""
            a, b = c['onset'] - 0.01, c['end'] + 0.01
            g = ("[0:a]asetnsamples=n=32,asplit=2[a][b];[a]volume=enable='between(t,%.4f,%.4f)':volume=%d[a1];"
                 "[b]atrim=%.4f:%.4f,asetpts=PTS-STARTPTS,adelay=delays=%dS:all=1[b1];"
                 "[a1][b1]amix=inputs=2:normalize=0:duration=first[o]"
                 % (a, b, 1 if keep else 0, a, b, int(round((a + d) * 44100))))
            return sfx_fc(name, g)

        def louder(c, db, name):
            # enable считается на кадр звука (до 4096 отсчётов): кадр 32 отсчёта — окно ровно по эффекту
            return sfx_fc(name, "[0:a]asetnsamples=n=32,volume=enable='between(t,%.4f,%.4f)':volume=%.1fdB[o]"
                          % (c['onset'] - 0.01, c['end'] + 0.01, db))

        def cue_copy(c, d):
            def fn(cu):
                cu['sfx'].append(dict(c, id='fx99', onset=round(c['onset'] + d, 4), end=round(c['end'] + d, 4),
                                      hit=round(c['hit'] + d, 4)))
            return fn

        def shift_cue(c, d):
            def fn(cu):
                for x in cu['sfx']:
                    if x['id'] == c['id']:
                        x['onset'] = round(x['onset'] + d, 4)
                        x['hit'] = round(x['hit'] + d, 4)
            return fn

        def hf_burst():
            t = ping1['hit']
            return {'sfx': sfx_fc('hf.wav', "[1:a]volume=-34dB,adelay=delays=%dS:all=1[s];"
                                            "[0:a][s]amix=inputs=2:normalize=0:duration=first[o]" % int(round((t + 0.02) * 44100)),
                                  ['-f', 'lavfi', '-i', 'sine=frequency=10000:duration=0.3:sample_rate=44100'])}

        def mix_without_sfx():
            p = os.path.join(tmp, 'nosfx.m4a')
            ff(['-v', 'error', '-y', '-i', paths0['mix'], '-i', paths0['sfx'], '-filter_complex',
                '[1:a]pan=stereo|c0=c0|c1=c0,volume=-1[n];[0:a][n]amix=inputs=2:normalize=0:duration=first[o]',
                '-map', '[o]', '-c:a', 'aac', '-b:a', '192k', p])
            return {'mix': p}

        def no_license():
            return {'music_cfg': edit_json(paths0['music_cfg'], lambda m: m['tracks'][0].update(license=' '), 'nolic.json')}

        def drop_event_rule():
            """Из каталога убрали правило chapter — а эффект главы в метках остался."""
            return {'sfx_cfg': edit_json(paths0['sfx_cfg'], lambda s: s.update(
                events=[r for r in s['events'] if r['kind'] != 'chapter']), 'norule.json')}

        cases = [
            ('music.wav короче фильма на 0,2 с', lambda: {'music': wav('short.wav', 'atrim=0:%.3f' % (dur - 0.2))}, 'M1 длина music.wav'),
            ('mix.m4a длиннее на 0,5 с', lambda: {'mix': m4a('long.m4a', 'apad=pad_dur=0.5')}, 'M1 длина mix.m4a'),
            ('метки: часть играет не тот трек', lambda: {'cues': cues_with(
                lambda c: c['parts'][0].update(track='music/другой.wav'))}, 'M2 части и треки по плану'),
            ('метки: часть начинается на 1 с позже хода главы', lambda: {'cues': cues_with(
                lambda c: c['parts'][-1].update(**{'from': round(c['parts'][-1]['from'] + 1.0, 4)}))}, 'M2 границы частей'),
            ('у трека пустая лицензия', no_license, 'M2 лицензия указана'),
            ('музыка не приглушена под речью: +14 дБ в реплике %d' % rep['num'], lambda: {'music': wav(
                'loud.wav', "volume=enable='between(t,%.3f,%.3f)':volume=14dB" % (rep['start'], rep['end']))}, 'M5 музыка ниже речи'),
            ('микс +12 дБ — перегруз', lambda: {'mix': m4a('clip.m4a', 'volume=12dB')}, 'M6 нет клиппинга: микс'),
            ('music.wav +30 дБ — перегруз', lambda: {'music': wav('clipm.wav', 'volume=30dB')}, 'M6 нет клиппинга: music.wav'),
            ('микс −3 дБ', lambda: {'mix': m4a('quiet.m4a', 'volume=-3dB')}, 'M7 громкость микса'),
            ('голоса разошлись: поправка снята, голос b на %.1f дБ тише' % gap_g, voice_shift(second_voice(voiced), -gap_g),
             'M9 голоса ровно'),
            ('голоса разошлись: первый голос на 1 дБ громче', voice_shift(first_voice(voiced), 1.0), 'M9 голоса ровно'),
            ('sfx.wav короче фильма на 0,2 с', lambda: {'sfx': wav('sfx-short.wav', 'atrim=0:%.3f' % (dur - 0.2), src=paths0['sfx'])},
             'M1 длина sfx.wav'),
            ('звук шва сдвинут на 0,2 с', lambda: {'sfx': moved(seam, 0.2)}, 'M10 звук ↔ метки'),
            ('лишний «пинг» на %.0f с без события и без метки' % lone_t,
             lambda: {'sfx': moved(ping1, lone_t - ping1['onset'], keep=True, name='lone.wav')}, 'M10 звук ↔ метки'),
            ('пинг выпал из sfx.wav', lambda: {'sfx': louder(ping2, -120, 'noping.wav')}, 'M10 звук ↔ метки'),
            ('метки: шов на 0,3 с позже события (звук там же)', lambda: {'cues': cues_with(shift_cue(seam, 0.3))},
             'M10 события фильма'),
            ('метки и звук: «пинг» на %.0f с без события фильма' % lone_t,
             lambda: {'cues': cues_with(cue_copy(ping1, lone_t - ping1['onset'])),
                      'sfx': moved(ping1, lone_t - ping1['onset'], keep=True, name='lone2.wav')}, 'M10 эффекты без события'),
            ('в каталоге нет правила для главы, а эффект в метках остался', drop_event_rule, 'M10 эффекты без события'),
            ('эффект громче речи: смена главы +6 дБ под репликой',
             lambda: {'sfx': louder(under_c, 6, 'under6.wav')}, 'M11 эффекты под речью'),
            ('эффект громче речи: шов +8 дБ в паузе', lambda: {'sfx': louder(pause_c, 8, 'pause8.wav')}, 'M11 эффекты в паузах'),
            ('два эффекта ближе min_gap: копия пинга через 1,0 с (метка и звук)',
             lambda: {'cues': cues_with(cue_copy(ping1, 1.0)), 'sfx': moved(ping1, 1.0, keep=True, name='ping2.wav')},
             'M12 плотность'),
            ('писк 10 кГц на пинге', hf_burst, 'M13 спектр'),
            ('в миксе нет эффектов', mix_without_sfx, 'M14 эффекты в миксе'),
        ]
        if os.path.exists(paths0['video_music']):
            def recut():
                p = os.path.join(tmp, 'vm.mp4')
                ff(['-v', 'error', '-y', '-i', paths0['video_music'], '-map', '0', '-c', 'copy', '-t', '10', p])
                return {'video_music': p}
            cases.append(('video-music.mp4 обрезан до 10 с', recut, 'M8 видео'))
        samples = [
            ('разброс голосов 0,4 дБ за счёт громкого голоса — в допуске M9', voice_shift(hi_voice, 0.4 - spread0), 'M9'),
            ('разброс голосов 0,4 дБ за счёт тихого голоса — в допуске M9', voice_shift(lo_voice, -(0.4 - spread0)), 'M9'),
            ('пинг +3 дБ — в пределах', lambda: {'sfx': louder(ping1, 3, 'ping3.wav')}, 'M11'),
            ('весь sfx.wav позже на 15 мс — меньше кадра',
             lambda: {'sfx': sfx_fc('late15.wav', '[0:a]adelay=delays=%dS:all=1,atrim=end_sample=%d[o]'
                                    % (int(0.015 * 44100), int(round(dur * 44100))))}, 'M10'),
            ('копия пинга через 1,6 с — плотность соблюдена',
             lambda: {'cues': cues_with(cue_copy(ping2, 1.6)), 'sfx': moved(ping2, 1.6, keep=True, name='ping16.wav')}, 'M12'),
        ]
        # двухтрековый фикстур: M3, M4 (в демо стыков нет)
        fixture = None
        if (not only) or any(o in 'M3 M4 двухтрековый фикстур' for o in only):
            fixture = two_track_fixture(paths0, film_name, tmp)
            fcues = read_json(fixture['cues'])
            fparts = fcues['parts']
            mid = fparts[1]
            swap_src = os.path.join(Path(fixture['root']), 'music', 'placeholder-pad.wav')

            def swap_track():
                p = os.path.join(tmp, 'swap.wav')
                a, b = mid['from'] + 1.5, mid['to'] - 1.5
                ff(['-v', 'error', '-y', '-i', fixture['music'], '-i', swap_src, '-filter_complex',
                    "[0:a]volume=enable='between(t,%.3f,%.3f)':volume=0[a];"
                    "[1:a]aresample=44100,aformat=channel_layouts=stereo,volume=-30dB,atrim=0:%.3f,"
                    "adelay=delays=%dS:all=1[b];[a][b]amix=inputs=2:normalize=0:duration=first[o]"
                    % (a, b, b - a, int(a * 44100)), '-map', '[o]', '-c:a', 'pcm_s16le', p])
                return {'music': p}
            fx_cases = [
                ('двухтрековый фикстур: в части звучит чужой трек', swap_track, 'M3 часть 1'),
                ('двухтрековый фикстур: полоса главы на 1,2 с позже стыка', lambda: {'film': edit_json(
                    fixture['film'], lambda f: [e.update(t=round(e['t'] + 1.2, 4)) for e in f['events'] if e['kind'] == 'chapter'],
                    'film-late.json')}, 'M4 стык'),
            ]
            fx_samples = [('двухтрековый фикстур как есть: части и стыки', lambda: {}, 'M3'),
                          ('двухтрековый фикстур как есть: стык', lambda: {}, 'M4'),
                          ('двухтрековый фикстур: события главы сдвинуты на 0,02 с — в пределах кадра',
                           lambda: {'film': edit_json(fixture['film'], lambda f: [e.update(t=round(e['t'] + 0.02, 4))
                                                      for e in f['events'] if e['kind'] == 'chapter'], 'film-02.json')}, 'M4')]
        else:
            fx_cases, fx_samples = [], []
        if only:
            cases = [c for c in cases if any(o in c[0] or o in c[2] for o in only)]
            samples = [c for c in samples if any(o in c[0] or o in c[2] for o in only)]
            fx_cases = [c for c in fx_cases if any(o in c[0] or o in c[2] for o in only)]
            fx_samples = [c for c in fx_samples if any(o in c[0] or o in c[2] for o in only)]
        bad = 0
        total = 0
        if mode in ('all', 'red'):
            for base, lst in ((paths0, cases), (fixture, fx_cases)):
                for title, make, want in lst:
                    total += 1
                    over = make()
                    fails = check(dict(base, **over), log=quiet)
                    hit = [f for f in fails if want in f]
                    if hit:
                        print('  ok  порча «%s» → %s' % (title, hit[0]))
                    else:
                        bad += 1
                        print('  ПРОВАЛ  порча «%s» не покраснела строкой «%s»; провалы: %s' % (title, want, fails))
        passed, n_samples = 0, 0
        if mode in ('all', 'samples'):
            for base, lst in ((paths0, samples), (fixture, fx_samples)):
                for title, make, quiet_on in lst:
                    n_samples += 1
                    fails = check(dict(base, **make()), log=quiet)
                    hit = [f for f in fails if f.startswith(quiet_on)]
                    if hit:
                        print('  ПРОВАЛ  образец «%s» покраснел: %s' % (title, hit[0]))
                    else:
                        passed += 1
                        print('  ok  образец «%s» прошёл %s молча' % (title, quiet_on))
        if not os.path.exists(paths0['video_music']):
            print('  --  порча M8 пропущена: video-music.mp4 нет')
        print('порчи: %d из %d покраснели своей строкой; образцы: %d из %d прошли молча'
              % (total - bad, total, passed, n_samples))
        return 1 if bad or passed < n_samples or not (total or n_samples) else 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def voice_spread(paths, voiced):
    """Разброс медиан громкости голосов в готовом миксе: (дБ, голос громче, голос тише) — для образцов M9."""
    med = {k: median(v) for k, v in voice_loudness(paths['mix'], voiced).items()}
    hi, lo = max(med, key=med.get), min(med, key=med.get)
    return med[hi] - med[lo], hi, lo


def first_voice(voiced):
    return voiced[0]['voice']


def second_voice(voiced):
    return next((r['voice'] for r in voiced if r['voice'] != voiced[0]['voice']), voiced[0]['voice'])


def voice_gap(film, cues):
    """Поправка, которую порча «поправка снята» убирает: разброс gain_db между голосами, дБ."""
    g = cues.get('voice_gain_db', {})
    return abs(max(g.values()) - min(g.values())) if len(g) > 1 else 0.0


def main():
    sys.path.append(str(HERE.parent))
    import project_root
    pdir, args = project_root.split_argv(sys.argv[1:])    # --project → MOTION_PROJECT → <шаблон>/project
    pdir = str(pdir)
    flags = [a for a in args if a in ('--red', '--samples', '--final')]
    rest = [a for a in args if a not in flags]
    bad = [a for a in rest[1:] if a.startswith('--')]
    if not rest or rest[0].startswith('--') or bad:
        sys.exit('нужен фильм: check_mix.py <фильм> [--project DIR] [--final | --red [подстрока…] | --samples [подстрока…]]')
    film = rest[0]
    only = rest[1:]
    if '--red' in flags or '--samples' in flags:
        mode = 'all' if '--red' in flags and '--samples' in flags else ('red' if '--red' in flags else 'samples')
        sys.exit(red(pdir, film, only, mode))
    if only:
        sys.exit('лишние аргументы: %s' % only)
    fails = check(make_paths(pdir, film), final='--final' in flags)
    print('итог: %s' % ('всё зелёное' if not fails else 'красных строк %d' % len(fails)))
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
