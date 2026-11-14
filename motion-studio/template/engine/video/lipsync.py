# -*- coding: utf-8 -*-
"""Огибающая громкости реплики → уровень открытия рта на каждый кадр.

`analyze(mp3)` декодирует звук нашим ffmpeg (imageio_ffmpeg) в моно 16 кГц,
считает RMS на окне одного кадра (1/30 с) и квантует в цифры 0–9, нормируя по
95-му перцентилю реплики: тихий и громкий голос открывают рот одинаково.
Результат — строка, один символ на кадр, и точная длительность звука.
Кэш — <out проекта>/cache/lipsync/<sha1 файла>.json (папку задаёт сборка): пересчёт только при смене mp3.

`synthetic(num, seconds)` — огибающая без звука для сметного режима:
слоги ~5 в секунду, детерминированно от номера реплики.
"""
import array
import hashlib
import json
import math
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

CACHE = None      # папка кэша — ставит сборка (config: <out>/cache/lipsync)
FPS = 30          # ставит сборка из project.json fps
RATE = 16000
VERSION = 1   # меняется вместе с формулой — старый кэш перестаёт подходить


def ffmpeg_exe():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def _sha1(path):
    h = hashlib.sha1()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def decode(path):
    """mp3 → массив int16, моно, RATE Гц."""
    out = subprocess.run([ffmpeg_exe(), '-v', 'error', '-i', path, '-ac', '1', '-ar', str(RATE),
                          '-f', 's16le', '-'], check=True, capture_output=True).stdout
    a = array.array('h')
    a.frombytes(out[:len(out) - len(out) % 2])
    if sys.byteorder != 'little':
        a.byteswap()
    return a


def levels_from_samples(a):
    win = RATE // FPS
    rms = []
    for i in range(0, len(a), win):
        chunk = a[i:i + win]
        if not chunk:
            break
        rms.append(math.sqrt(sum(x * x for x in chunk) / len(chunk)))
    ref = sorted(rms)[int(len(rms) * 0.95)] if rms else 1.0
    ref = ref or 1.0
    return ''.join(str(min(9, int(9.99 * min(1.0, r / ref)))) for r in rms)


def analyze(path):
    """(секунды, строка уровней) для mp3; с кэшем."""
    key = _sha1(path)
    cpath = os.path.join(CACHE, '%s-%d.json' % (key, FPS))
    if os.path.exists(cpath):
        with open(cpath, encoding='utf-8') as fh:
            c = json.load(fh)
        if c.get('version') == VERSION:
            return c['seconds'], c['levels']
    a = decode(path)
    seconds = len(a) / RATE
    levels = levels_from_samples(a)
    os.makedirs(CACHE, exist_ok=True)
    with open(cpath, 'w', encoding='utf-8') as fh:
        json.dump({'version': VERSION, 'file': os.path.basename(path),
                   'seconds': seconds, 'levels': levels}, fh)
    return seconds, levels


def synthetic(num, seconds):
    """Огибающая без звука: слоги по 0,2 с, амплитуда от номера реплики."""
    n = int(round(seconds * FPS))
    seed = (num * 2654435761) & 0xFFFFFFFF
    out = []
    for i in range(n):
        seed = (seed * 1103515245 + 12345) & 0x7FFFFFFF
        syl = abs(math.sin(math.pi * i / 6.0))      # 6 кадров = 0,2 с на слог
        edge = min(1.0, i / 4.0, (n - 1 - i) / 4.0)  # рот закрыт на краях реплики
        v = syl * edge * (0.6 + 0.4 * (seed % 100) / 100.0)
        out.append(str(min(9, int(v * 9.99))))
    return ''.join(out)
