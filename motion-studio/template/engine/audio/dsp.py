# -*- coding: utf-8 -*-
"""Общие мелочи сборки звука: ffmpeg, раскодирование, RMS, громкость (ebur128), хеш.

Только stdlib и ffmpeg из imageio_ffmpeg (numpy не нужен). Проверка `check_mix.py` этот модуль
НЕ импортирует: она меряет результат своим способом (проверка, считающая тем же кодом, что и
сборка, не находит ошибок никогда).
"""
import array
import hashlib
import math
import re
import subprocess
import sys

sys.dont_write_bytecode = True
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

import imageio_ffmpeg

FF = imageio_ffmpeg.get_ffmpeg_exe()
SR = 44100          # частота микса — как у речи в сведении видео
ASR = 16000         # частота промера (RMS реплик, огибающие)
BITEXACT = ['-fflags', '+bitexact', '-flags:a', '+bitexact', '-map_metadata', '-1']


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, **kw)
    if r.returncode:
        err = r.stderr.decode('utf-8', 'replace') if isinstance(r.stderr, bytes) else r.stderr
        raise SystemExit('ffmpeg упал (код %d): %s' % (r.returncode, err[-1500:]))
    return r


def decode_mono(path, rate=ASR):
    """Файл → моно s16 с частотой rate (ffmpeg), массив отсчётов."""
    r = run([FF, '-v', 'error', '-i', str(path), '-ac', '1', '-ar', str(rate), '-f', 's16le', '-'])
    a = array.array('h')
    a.frombytes(r.stdout)
    return a


def rms_db(a, i0, i1):
    i0, i1 = max(0, i0), min(len(a), i1)
    if i1 <= i0:
        return -120.0
    s = sum(x * x for x in a[i0:i1])
    return 10 * math.log10(s / (i1 - i0) / 32768.0 ** 2 + 1e-12)


def lufs(args_in):
    """Интегральная громкость ebur128: (I LUFS, true peak dBTP)."""
    r = run([FF, '-hide_banner', '-nostats'] + args_in + ['-af', 'ebur128=peak=true', '-f', 'null', '-'])
    e = r.stderr.decode('utf-8', 'replace')
    summ = e[e.rfind('Summary:'):]
    i = float(re.search(r'I:\s+(-?[\d.]+) LUFS', summ).group(1))
    tp = float(re.search(r'Peak:\s+(-?[\d.]+|-inf) dBFS', summ).group(1))
    return i, tp


def sha1(path):
    h = hashlib.sha1()
    with open(path, 'rb') as fh:
        for blk in iter(lambda: fh.read(1 << 20), b''):
            h.update(blk)
    return h.hexdigest()


def speech_levels(audio, replies):
    """{номер реплики: RMS речи, дБ} — с поправкой голоса (voices.json gain_db), до итоговой поправки микса.
    От этого уровня считаются и музыка под речью, и эффекты."""
    out = {}
    for r in replies:
        a = decode_mono(r['path'])
        out[r['num']] = rms_db(a, 0, len(a)) + audio.voice_gain_db(r['voice'])
    return out


def speech_graph(audio, replies, first_input):
    """Цепочки ffmpeg: реплики со сдвигом и поправкой голоса → [sp] (стерео). Возвращает (входы, цепочки)."""
    inputs, chains = [], []
    for j, r in enumerate(replies):
        inputs += ['-i', r['path']]
        chains.append('[%d:a]aresample=%d,aformat=channel_layouts=mono,volume=%.4fdB,adelay=delays=%dS:all=1[s%d]'
                      % (first_input + j, SR, audio.voice_gain_db(r['voice']), int(round(r['start'] * SR)), j))
    mix = ''.join('[s%d]' % j for j in range(len(replies)))
    chains.append('%samix=inputs=%d:normalize=0:dropout_transition=0,apad,'
                  'pan=stereo|c0=c0|c1=c0[sp]' % (mix, len(replies)))
    return inputs, chains
