# -*- coding: utf-8 -*-
"""Промер озвучки ПОСЛЕ синтеза: то, что слышно, но не видно в тексте.

    check_audio.py [--project DIR]   реплики проекта: out/tts/reply + cache + manifest
    check_audio.py --red             порчи на синтетическом наборе: каждая краснеет своей строкой
    check_audio.py --samples         законные варианты: проходят молча

Условия (классы дефектов 9, 10, 12 — checklists/defect-classes.md скила):

    reply ≠ cache            reply/NNN.mp3 байт в байт = cache/<ключ из манифеста>.mp3;
                             иначе файл чужой, как бы хорошо он ни звучал
    манифест устарел         запись манифеста о строке говорит не тот текст, голос
                             или эмоцию, что rows.json + speech_edits.json сейчас
    пауза внутри словосочетания  внутренняя пауза ≥ 0,35 с, которой не досталось знака
                             препинания или авторской метки рядом (см. PAUSE_*)
    протяжность              промер / (знаки × sec_per_char_net + clip_pad_sec) > 1,6
    громкость голосов        медианы интегральной громкости (LUFS) голосов после
                             gain_db из voices.json расходятся > 0,5 дБ
    КЛИППИНГ / ОБРЫВ         пик > −0,5 dBFS; заголовок длиннее раскодированного ≥ 0,15 с

Пауза и протяжность — «на прослушку»: красное значит «послушай», а не «плохо». Принятое
на слух записывается в speech_edits.json[N].allow («пауза», «протяжность») с why.

**Калибровка — промер, не выбор** (198 оплаченных реплик прошлого ролика):
    протяжность: максимум на принятом наборе 1,526, минимум 0,70;
                 дефект, услышанный пользователем, — 3,27 / 1,52 ≈ 2,15. Порог 1,6 —
                 ноль находок на эталоне, дефект ловится
    паузы: допуск max(25 % озвученного времени, 0,5 с) — при 10 % находок 15.
                 Красных реплик 7 из 198, все в известных классах: одна — дефект,
                 подрезанный тогда же; одна — кавычки в тексте синтеза; две —
                 аббревиатуры встык; три — пауза без знака, на прослушку.
                 Остаточная дыра честная: пауза в пределах допуска от свободного
                 знака не видна
    громкость: медианы −30,40 / −32,50 LUFS, поправка +2,1 дБ — разница 0,0

Проверка не импортирует сборку: конфиги и манифест читаются здесь своим способом.
"""

import array
import hashlib
import json
import math
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

sys.path.append(str(Path(__file__).resolve().parents[1]))
import project_root   # noqa: E402

PAUSE_FLOOR_DB = -35          # промер: отделяет речь (RMS ~ −30) от фона
PAUSE_DETECT_SEC = 0.05
PAUSE_MERGE_SEC = 0.005       # измеритель дробит одну паузу на смежные куски
PAUSE_EDGE_SEC = 0.05         # тишина у края — окантовка клипа, не пауза
PAUSE_LONG_SEC = 0.35         # класс дефектов 9
PAUSE_TOL_FRAC = 0.25         # калибровка выше
PAUSE_TOL_SEC = 0.5
STRETCH_MAX = 1.6             # класс дефектов 10
LOUD_SPREAD_DB = 0.5          # класс дефектов 12
CLIP_PEAK_DB = -0.5
CUT_GAP_SEC = 0.15            # промер: целые 0,02–0,04 с, обрыв 5 % байт ≥ 0,50 с

M_ORDER = 'reply ≠ cache'
M_STALE = 'манифест устарел'
M_MISSING = 'нет реплики'
M_PAUSE = 'пауза внутри словосочетания'
M_STRETCH = 'протяжность'
M_LOUD = 'громкость голосов'
M_CLIP = 'КЛИППИНГ'
M_CUT = 'ОБРЫВ'
M_PROBE = 'ПРОМЕР НЕ УДАЛСЯ'

AUTHOR_MARK_RE = re.compile(r'<#[^#>]*#>|\([A-Za-z][A-Za-z_ ]*\)')
PUNCT_RE = re.compile(r'[,.!?:;…—–](?=\s)')
SIL_S = re.compile(r'silence_start:\s*(-?[\d.]+)')
SIL_E = re.compile(r'silence_end:\s*(-?[\d.]+)')
TIME_RE = re.compile(r'time=(\d+):(\d\d):(\d\d\.\d+)')
LUFS_RE = re.compile(r'I:\s*(-?[\d.]+) LUFS')
PEAK_RE = re.compile(r'Peak level dB:\s*(-?[\d.]+|-inf)')


def ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


# ---------------------------------------------------------------------------
# Промер
# ---------------------------------------------------------------------------

def measure(path):
    """Один проход ffmpeg: длительности, паузы, громкость, пик. Неудача — {'error'}."""
    try:
        proc = subprocess.run(
            [ffmpeg(), '-hide_banner', '-i', str(path), '-af',
             'silencedetect=n=%ddB:d=%.2f,astats=metadata=0,ebur128=framelog=quiet'
             % (PAUSE_FLOOR_DB, PAUSE_DETECT_SEC), '-f', 'null', '-'],
            capture_output=True, text=True, encoding='utf-8', errors='replace')
    except (OSError, ImportError) as exc:
        return {'error': 'измеритель ffmpeg недоступен: %s' % exc}
    err = proc.stderr or ''
    if proc.returncode != 0:
        return {'error': 'ffmpeg вернул код %d' % proc.returncode}
    header = None
    m = re.search(r'Duration:\s*(\d+):(\d\d):(\d\d\.\d+)', err)
    if m:
        header = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    marks = TIME_RE.findall(err)
    lufs = LUFS_RE.findall(err)
    peaks = PEAK_RE.findall(err)
    if header is None or not marks or not lufs or not peaks:
        return {'error': 'ffmpeg не дал длительность, громкость или пик'}
    h, mi, s = marks[-1]
    decoded = int(h) * 3600 + int(mi) * 60 + float(s)
    spans, start = [], None
    for line in err.splitlines():
        a = SIL_S.search(line)
        if a:
            start = max(float(a.group(1)), 0.0)
        b = SIL_E.search(line)
        if b and start is not None:
            spans.append([start, float(b.group(1))])
            start = None
    if start is not None:
        spans.append([start, decoded])
    merged = []
    for a, b in spans:
        if merged and a - merged[-1][1] <= PAUSE_MERGE_SEC:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    peak = peaks[-1]
    return {'header': header, 'decoded': decoded, 'silences': merged,
            'lufs': float(lufs[-1]), 'peak': -200.0 if peak == '-inf' else float(peak)}


def text_marks(speech):
    """(длина чистого текста, [позиции знаков и меток в чистом тексте])."""
    clean, marks, pos = '', [], 0
    for m in AUTHOR_MARK_RE.finditer(speech):
        clean += speech[pos:m.start()]
        marks.append(len(clean.strip()) if not clean.strip() else len(clean))
        pos = m.end()
    clean += speech[pos:]
    lead = len(clean) - len(clean.lstrip())
    clean_s = clean.strip()
    marks = [max(0, p - lead) for p in marks]
    marks += [m.start() for m in PUNCT_RE.finditer(clean_s)]
    return max(1, len(clean_s)), sorted(marks)


def stray_pauses(speech, data):
    """Внутренние паузы ≥ PAUSE_LONG_SEC без знака рядом: [(начало, длина)]."""
    dur = data['decoded']
    sil = data['silences']
    lead = sil[0][1] if sil and sil[0][0] <= PAUSE_EDGE_SEC else 0.0
    tail = sil[-1][0] if sil and sil[-1][1] >= dur - PAUSE_EDGE_SEC else dur
    inner = [(a, b) for a, b in sil if a > PAUSE_EDGE_SEC and b < dur - PAUSE_EDGE_SEC]
    voiced = (tail - lead) - sum(b - a for a, b in inner)
    if voiced <= 0:
        return []
    length, marks = text_marks(speech)
    fracs = [p / float(length) for p in marks]
    tol = max(PAUSE_TOL_FRAC * voiced, PAUSE_TOL_SEC)
    used, stray = set(), []
    for a, b in inner:
        if b - a < PAUSE_LONG_SEC:
            continue
        before = (a - lead) - sum(min(bb, a) - aa for aa, bb in inner if aa < a)
        f = before / voiced
        # Каждый знак разрешает одну паузу. Паузы идут по времени, и каждой отдаётся
        # самый левый свободный знак в пределах допуска: на прямой это даёт наибольшее
        # число разрешённых пауз (ближайший знак «отбирал» соседний у следующей паузы
        # и красил 6 законных реплик из 198 на калибровке).
        cand = [i for i, p in enumerate(fracs)
                if i not in used and abs(f - p) * voiced <= tol]
        if not cand:
            stray.append((round(a, 2), round(b - a, 2)))
        else:
            used.add(min(cand, key=lambda i: fracs[i]))
    return stray


# ---------------------------------------------------------------------------
# Проверка проекта
# ---------------------------------------------------------------------------

class Report:
    def __init__(self, quiet=False):
        self.fails, self.quiet = [], quiet

    def ok(self, msg):
        if not self.quiet:
            print('  ok   %s' % msg)

    def fail(self, msg):
        self.fails.append(msg)
        if not self.quiet:
            print('  FAIL %s' % msg)

    def note(self, msg):
        if not self.quiet:
            print('  --   %s' % msg)


def load(pdir):
    pdir = Path(pdir)

    def rd(name, default=None):
        p = pdir / name
        if not p.exists():
            return default
        with open(p, encoding='utf-8') as fh:
            return json.load(fh)
    return rd('voices.json'), rd('rows.json'), rd('speech_edits.json', {}), tts_out(pdir)


def need_gain(vcfg, vid):
    """gain_db голоса из voices.json — обязательное поле: тихий 0 спрятал бы забытую поправку."""
    v = vcfg.get(vid)
    if v is None:
        raise SystemExit('voices.json: голоса %r нет' % (vid,))
    if v.get('gain_db') is None:
        raise SystemExit('voices.json: нет обязательного поля voices.%s.gain_db' % vid)
    return v['gain_db']


def tts_out(pdir):
    """Выход озвучки: <проект>/<project.json paths.voices_out> — от папки проекта, как все paths.*."""
    p = Path(pdir) / 'project.json'
    if not p.exists():
        raise SystemExit('нет файла %s' % p)
    with open(p, encoding='utf-8-sig') as fh:
        rel = (json.load(fh).get('paths') or {}).get('voices_out')
    if not rel:
        raise SystemExit('project.json: нет обязательного поля paths.voices_out')
    return Path(pdir) / rel


def check_project(pdir, rep):
    voices, rows, edits, out = load(pdir)
    vcfg = voices['voices']
    man_path = out / 'manifest.json'
    if not man_path.exists():
        rep.fail('%s: манифеста нет — синтез не запускался (%s)' % (M_MISSING, man_path))
        return
    with open(man_path, encoding='utf-8') as fh:
        man = {e['n']: e for e in json.load(fh)}
    by_voice = {}
    for r in rows:
        n = r['n']
        e = edits.get(str(n)) or {}
        speech = e.get('speech', r['text'])
        allow = set(e.get('allow', [])) if str(e.get('why', '')).strip() else set()
        api = vcfg[r['voice']]['emotion_map'][r['emotion']]
        reply = out / 'reply' / ('%03d.mp3' % n)
        ent = man.get(n)
        if ent is None or not reply.exists():
            rep.fail('%s: строка %d — нет %s' % (M_MISSING, n,
                                                 'записи в манифесте' if ent is None else reply.name))
            continue
        stale = [f for f, want in (('speech', speech), ('voice', r['voice']),
                                   ('api_emotion', api)) if ent.get(f) != want]
        if stale:
            rep.fail('%s: строка %d — поля %s не те, что в rows.json/speech_edits.json; '
                     'синтезировать заново' % (M_STALE, n, stale))
        cache = out / 'cache' / ('%s.mp3' % ent.get('key', ''))
        if not cache.exists() or cache.read_bytes() != reply.read_bytes():
            rep.fail('%s: строка %d — %s не совпадает байт в байт с cache/%s.mp3'
                     % (M_ORDER, n, reply.name, str(ent.get('key', ''))[:10]))
        data = measure(reply)
        if 'error' in data:
            rep.fail('%s: строка %d — %s' % (M_PROBE, n, data['error']))
            continue
        if data['peak'] > CLIP_PEAK_DB:
            rep.fail('%s: строка %d — пик %.2f dBFS' % (M_CLIP, n, data['peak']))
        if data['header'] - data['decoded'] >= CUT_GAP_SEC:
            rep.fail('%s: строка %d — декодировано %.2f с из %.2f с'
                     % (M_CUT, n, data['decoded'], data['header']))
        stray = stray_pauses(speech, data)
        if stray and 'пауза' in allow:
            rep.note('строка %d: пауза %s принята на слух (%s)' % (n, stray, e.get('why')))
        elif stray:
            rep.fail('%s: строка %d — пауза ≥ %.2f с без знака рядом %s → на прослушку'
                     % (M_PAUSE, n, PAUSE_LONG_SEC, stray))
        v = vcfg[r['voice']]
        want = len(speech) * v['sec_per_char_net'] + v['clip_pad_sec']
        ratio = data['decoded'] / want
        if ratio > STRETCH_MAX and 'протяжность' in allow:
            rep.note('строка %d: протяжность %.2f принята на слух' % (n, ratio))
        elif ratio > STRETCH_MAX:
            rep.fail('%s: строка %d — %.2f с при расчёте %.2f с (×%.2f > %.1f) → на прослушку'
                     % (M_STRETCH, n, data['decoded'], want, ratio, STRETCH_MAX))
        by_voice.setdefault(r['voice'], []).append(data['lufs'])
    med = {vid: statistics.median(vals) + float(need_gain(vcfg, vid))
           for vid, vals in by_voice.items()}
    if len(med) >= 2:
        spread = max(med.values()) - min(med.values())
        line = ', '.join('%s %.2f' % (vid, med[vid]) for vid in sorted(med))
        if spread > LOUD_SPREAD_DB:
            rep.fail('%s: медианы после gain_db расходятся на %.2f дБ > %.1f (%s LUFS) — '
                     'поправить gain_db в voices.json' % (M_LOUD, spread, LOUD_SPREAD_DB, line))
        else:
            rep.ok('громкость голосов после gain_db: %s LUFS, разброс %.2f дБ' % (line, spread))
    if not rep.fails:
        rep.ok('%d реплик: reply = cache, паузы, протяжность, пик, обрыв — чисто' % len(rows))


# ---------------------------------------------------------------------------
# Синтетический набор для порч и образцов
# ---------------------------------------------------------------------------

RATE, PAD = 0.0575, 0.36
BASE_ROWS = [
    ('a', 'Инструкция задаёт порядок действий, а сотрудник сообщает о сбое сразу.'),
    ('b', 'Сообщаете дежурному немедленно, без ожидания и без поиска виноватых.'),
    ('a', 'Инструкция проверки данных при расхождениях в разных версиях документов '
          'описывает порядок работы.'),
    ('b', 'Номера дежурных указаны в карточке проекта.'),
]


def synth_wav(path, text, level_db=-20.0, extra=(), stretch=1.0, mark_pause=0.42,
              clip=False, sr=22050):
    """Речеподобный сигнал: «слоги» тона, паузы на знаках и метках, лишние — в extra.

    extra — [(доля озвученного времени, длина паузы)]. Ничего не знает о проверке:
    паузы ставятся по тексту так же, как их ставит диктор.
    """
    length, marks = text_marks(text)
    voiced = length * RATE * stretch
    cuts = sorted([(p / float(length) * voiced, mark_pause) for p in marks]
                  + [(f * voiced, d) for f, d in extra])
    amp = 1.6 if clip else 10 ** (level_db / 20.0)
    buf = array.array('h')

    def silence(sec):
        buf.extend([0] * int(sec * sr))

    def tone(sec):
        n = int(sec * sr)
        for i in range(n):
            t = i / float(sr)
            on = (t % 0.19) < 0.16
            x = amp * math.sin(2 * math.pi * 170 * t) if on else 0.0
            buf.append(max(-32767, min(32767, int(x * 32767))))
    silence(0.12)
    t = 0.0
    for at, d in cuts:
        tone(max(0.0, at - t))
        silence(d)
        t = max(t, at)
    tone(max(0.0, voiced - t))
    silence(0.15)
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(buf.tobytes())


def encode(wav, mp3):
    subprocess.run([ffmpeg(), '-hide_banner', '-loglevel', 'error', '-y', '-i', str(wav),
                    '-ar', '44100', '-ac', '1', '-c:a', 'libmp3lame', '-b:a', '128k', str(mp3)],
                   check=True)


def build_fixture(root, spec):
    """Проект во временной папке: конфиги + <проект>/out/tts с кэшем, репликами и манифестом."""
    pdir = Path(root) / 'project'
    out = pdir / 'out' / 'tts'               # = tts_out(pdir): paths.voices_out от папки проекта
    for d in (pdir, out / 'cache', out / 'reply'):
        d.mkdir(parents=True, exist_ok=True)
    emap = {'Neutral': 'calm'}
    voices = {'provider': 'fake', 'voices': {
        vid: {'label': vid, 'voice_env': 'X_%s' % vid.upper(), 'speed': 1.0, 'pitch': 0,
              'emotion_map': emap, 'sec_per_char': 0.063, 'sec_per_char_net': RATE,
              'clip_pad_sec': PAD, 'gain_db': spec['gain'][vid]}
        for vid in ('a', 'b')}}
    rows, man = [], []
    for i, row in enumerate(spec['rows'], 1):
        rows.append({'n': i, 'scene': 's1' if i <= 2 else 's2', 'voice': row['voice'],
                     'emotion': 'Neutral', 'text': row['text']})
        wav = Path(root) / ('%03d.wav' % i)
        synth_wav(wav, row['text'], row.get('level', spec['level'][row['voice']]),
                  row.get('extra', ()), row.get('stretch', 1.0),
                  mark_pause=row.get('mark_pause', 0.42), clip=row.get('clip', False))
        tmp = Path(root) / ('%03d.mp3' % i)
        encode(wav, tmp)
        data = tmp.read_bytes()
        key = hashlib.sha1(('%s|%s' % (row['voice'], row['text'])).encode('utf-8')).hexdigest()
        (out / 'cache' / (key + '.mp3')).write_bytes(data)
        (out / 'cache' / (key + '.json')).write_text(json.dumps({'ms': 0, 'usage': 0,
                                                                 'bytes': len(data)}))
        shutil.copyfile(tmp, out / 'reply' / ('%03d.mp3' % i))
        man.append({'n': i, 'scene': rows[-1]['scene'], 'voice': row['voice'],
                    'emotion': 'Neutral', 'api_emotion': 'calm', 'text': row['text'],
                    'speech': row['text'], 'chars': len(row['text']), 'provider': 'fake',
                    'key': key, 'ms': 0, 'usage': 0, 'file': 'reply/%03d.mp3' % i})
    for name, obj in (('voices.json', voices), ('rows.json', rows),
                      ('speech_edits.json', spec.get('edits', {})),
                      ('project.json', {'paths': {'voices_out': 'out/tts'}})):
        (pdir / name).write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding='utf-8')
    (out / 'manifest.json').write_text(json.dumps(man, ensure_ascii=False, indent=1),
                                       encoding='utf-8')
    return pdir


def base_spec():
    return {'rows': [{'voice': v, 'text': t} for v, t in BASE_ROWS],
            'level': {'a': -20.0, 'b': -22.0}, 'gain': {'a': 0.0, 'b': 2.0}}


def edit_spec(fn):
    def make():
        s = base_spec()
        fn(s)
        return s
    return make


def _set(path, key, value):
    def go(s):
        node = s
        for k in path:
            node = node[k]
        node[key] = value
    return go


def _many(*fns):
    def go(s):
        for f in fns:
            f(s)
    return go


def swap_reply(pdir):
    out = tts_out(pdir) / 'reply'
    shutil.copyfile(out / '004.mp3', out / '002.mp3')


def flip_byte(pdir):
    p = tts_out(pdir) / 'reply' / '001.mp3'
    data = bytearray(p.read_bytes())
    data[len(data) // 2] ^= 0x01
    p.write_bytes(bytes(data))


def drop_reply(pdir):
    (tts_out(pdir) / 'reply' / '003.mp3').unlink()


def retext_row(pdir):
    p = pdir / 'rows.json'
    rows = json.loads(p.read_text(encoding='utf-8'))
    rows[0]['text'] = rows[0]['text'].replace('сразу', 'немедленно')
    p.write_text(json.dumps(rows, ensure_ascii=False), encoding='utf-8')


def truncate_both(pdir):
    out = tts_out(pdir)
    man = json.loads((out / 'manifest.json').read_text(encoding='utf-8'))
    key = man[2]['key']
    data = (out / 'reply' / '003.mp3').read_bytes()
    cut = data[: int(len(data) * 0.6)]
    for p in (out / 'reply' / '003.mp3', out / 'cache' / (key + '.mp3')):
        p.write_bytes(cut)


MID_PAUSE = [(0.5, 0.55)]

# (имя, сборка набора, порча файлов или None, ожидаемая подстрока провала)
RED = [
    ('пауза внутри словосочетания', edit_spec(_set(('rows', 2), 'extra', MID_PAUSE)),
     None, M_PAUSE),
    ('лишняя пауза рядом с занятым знаком',
     edit_spec(_set(('rows', 1), 'extra', [(0.78, 0.5)])), None, M_PAUSE),
    ('пауза в фразе без знаков, короткая реплика',
     edit_spec(_set(('rows', 3), 'extra', [(0.45, 0.45)])), None, M_PAUSE),
    ('разрешение паузы без основания не снимает', edit_spec(_many(
        _set(('rows', 2), 'extra', MID_PAUSE),
        _set((), 'edits', {'3': {'allow': ['пауза']}}))), None, M_PAUSE),
    ('протяжность', edit_spec(_set(('rows', 3), 'stretch', 2.4)), None, M_STRETCH),
    ('протяжность длинной реплики', edit_spec(_set(('rows', 0), 'stretch', 1.9)), None, M_STRETCH),
    ('громкость голосов (gain_db 0)', edit_spec(_set(('gain',), 'b', 0.0)), None, M_LOUD),
    ('громкость голосов (поправка не в ту сторону)', edit_spec(_set(('gain',), 'b', -2.0)),
     None, M_LOUD),
    ('громкость голосов (тихий голос без поправки)', edit_spec(_set(('level',), 'a', -24.0)),
     None, M_LOUD),
    ('reply ≠ cache (чужой файл)', base_spec, swap_reply, M_ORDER),
    ('reply ≠ cache (один байт)', base_spec, flip_byte, M_ORDER),
    ('нет реплики', base_spec, drop_reply, M_MISSING),
    ('манифест устарел', base_spec, retext_row, M_STALE),
    ('клиппинг', edit_spec(_set(('rows', 0), 'clip', True)), None, M_CLIP),
    ('обрыв записи', base_spec, truncate_both, M_CUT),
]

SAMPLES = [
    ('чистый набор', base_spec, None),
    ('долгая пауза на запятой', edit_spec(_set(('rows', 0), 'mark_pause', 0.75)), None),
    ('пауза у авторской метки', edit_spec(_set(('rows', 3), 'text',
                                                'Номера дежурных <#0.5#> указаны в карточке проекта.')),
     None),
    ('протяжность в пределах (сигнал ×1,3)', edit_spec(_set(('rows', 1), 'stretch', 1.3)), None),
    ('громкость в пределах 0,3 дБ', edit_spec(_set(('level',), 'b', -21.7)), None),
    ('пауза принята на слух', edit_spec(_many(
        _set(('rows', 2), 'extra', MID_PAUSE),
        _set((), 'edits', {'3': {'allow': ['пауза'], 'why': 'прослушано: вдох на месте'}}))),
     None),
]


def run_case(make, spoil):
    tmp = tempfile.mkdtemp(prefix='check_audio_')
    try:
        pdir = build_fixture(tmp, make())
        if spoil:
            spoil(pdir)
        rep = Report(quiet=True)
        check_project(pdir, rep)
        return rep.fails
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def self_check(mode):
    fails = 0
    if mode in ('red', 'all'):
        for name, make, spoil, want in RED:
            got = run_case(make, spoil)
            hit = [f for f in got if want in f]
            if hit:
                print('  ok   порча «%s» покраснела: %s' % (name, hit[0][:110]))
            else:
                fails += 1
                print('  FAIL порча «%s» не покраснела «%s»; провалы: %s' % (name, want, got))
    if mode in ('samples', 'all'):
        for name, make, spoil in SAMPLES:
            got = run_case(make, spoil)
            if got:
                fails += 1
                print('  FAIL образец «%s» покраснел: %s' % (name, got))
            else:
                print('  ok   образец «%s» прошёл молча' % name)
    return fails


def main(argv):
    if '--red' in argv or '--samples' in argv:
        mode = 'all' if ('--red' in argv and '--samples' in argv) else (
            'red' if '--red' in argv else 'samples')
        if mode == 'red':
            mode = 'all'   # порча без образцов — односторонняя охрана
        fails = self_check(mode)
        print('---\nпровалов самопроверки: %d' % fails)
        return 1 if fails else 0
    pdir, argv = project_root.split_argv(argv)     # --project → MOTION_PROJECT → <шаблон>/project
    rep = Report()
    check_project(pdir, rep)
    print('---\nпровалов: %d' % len(rep.fails))
    return 1 if rep.fails else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
