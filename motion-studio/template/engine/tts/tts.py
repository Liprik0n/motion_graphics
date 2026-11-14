# -*- coding: utf-8 -*-
"""Конвейер озвучки: rows.json (+ speech_edits.json) → mp3 по репликам → склейка по сценам.

    tts.py --estimate [--rows 1-4]     смета по голосам и хронометраж, без сети
    tts.py --voices                    голоса ключа у провайдера (у MiniMax бесплатно)
    tts.py --rows 1,3-4 [--yes-i-pay]  синтез выбранных строк
    tts.py --all [--yes-i-pay]         полный прогон
    tts.py --assemble [--scenes a,b]   склейка сцен из готовых реплик
    tts.py --report                    хронометраж по манифесту
    общий ключ: --project <папка проекта>  (иначе MOTION_PROJECT, иначе <шаблон>/project — engine/project_root.py)

Провайдер — `voices.json["provider"]` → `providers/<имя>.py`; ядро его не знает.

**Синтез тарифицируется с аккаунта пользователя.** Без `--yes-i-pay` в сеть не уходит
ни одна строка: команда печатает, сколько стоило бы, и останавливается. Согласие
проверяется в точке расхода — `synthesize_paid()`, — а не только в смете: между
подсчётом и вызовом запись кэша может исчезнуть.

**Кэш** `<проект>/out/tts/cache/<sha1>.mp3` + `.json`. Ключ — sha1 от провайдера, его
`cache_params` (модель, голос, формат), эмоции, скорости, питча и `speech`: правка
одной строки перегенерирует одну строку. Скорость в ключе — её правка оплачивает весь
прогон заново. `cached()` сверяет размер с `bytes` в `.json` и отвергает усечённую
запись. Кэш, `reply/` и манифест пишутся в одном шаге цикла: обрыв стоит остатка.

Значения `.env` наружу не выходят: ошибки провайдера проходят через `redact()`.
"""

import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config  # noqa: E402
from envfile import read_env_file, redact, require  # noqa: E402
from providers import provider_class  # noqa: E402

SEP = '|#|'
TIME_RE = re.compile(r'time=(\d+):(\d\d):(\d\d\.\d+)')


def ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def decoded_sec(path):
    """Длительность по раскодированному звуку (заголовок mp3 завышает на ~0,04 с)."""
    proc = subprocess.run([ffmpeg(), '-hide_banner', '-i', str(path), '-f', 'null', '-'],
                          capture_output=True, text=True, encoding='utf-8', errors='replace')
    marks = TIME_RE.findall(proc.stderr or '')
    if not marks:
        return 0.0
    h, m, s = marks[-1]
    return int(h) * 3600 + int(m) * 60 + float(s)


# ---------------------------------------------------------------------------
# Кэш
# ---------------------------------------------------------------------------

def cache_key(provider, line, voice_cfg):
    parts = [provider.name, json.dumps(provider.cache_params(voice_cfg), sort_keys=True,
                                       ensure_ascii=False),
             line['api_emotion'], '%.2f' % float(voice_cfg.get('speed', 1.0)),
             str(voice_cfg.get('pitch', 0)), line['speech']]
    return hashlib.sha1(SEP.join(parts).encode('utf-8')).hexdigest()


def cached(cache_dir, key):
    """(mp3, meta) только если запись дописана до конца; иначе (None, None)."""
    mp3 = Path(cache_dir) / (key + '.mp3')
    meta = Path(cache_dir) / (key + '.json')
    if not (mp3.exists() and meta.exists()):
        return None, None
    try:
        data = json.loads(meta.read_text(encoding='utf-8'))
    except (ValueError, OSError):
        return None, None
    size = mp3.stat().st_size
    if not size or size != data.get('bytes'):
        return None, None
    return mp3, data


def put_cache(cache_dir, key, audio, ms, usage):
    os.makedirs(cache_dir, exist_ok=True)
    mp3 = Path(cache_dir) / (key + '.mp3')
    mp3.write_bytes(audio)
    ms = ms if ms is not None else int(round(decoded_sec(mp3) * 1000))
    meta = {'ms': ms, 'usage': usage, 'bytes': len(audio)}
    (Path(cache_dir) / (key + '.json')).write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), encoding='utf-8')
    return mp3, meta


# ---------------------------------------------------------------------------
# Провайдер, .env, оплата
# ---------------------------------------------------------------------------

def open_provider(proj, need_env):
    cls = provider_class(proj.voices_cfg)
    env = read_env_file(proj.env_path)
    names = cls.env_names(proj.voices_cfg)
    if need_env and names:
        require(env, names, str(proj.env_path))
    return cls(proj.voices_cfg, env), env


def env_ready(proj, cls):
    names = cls.env_names(proj.voices_cfg)
    if not names:
        return True
    env = read_env_file(proj.env_path)
    return all(env.get(k) for k in names)


class Budget:
    """Остаток лимита знаков `--max-chars` на этот запуск."""

    def __init__(self, limit):
        self.limit = self.left = int(limit)


def synthesize_paid(provider, line, voice_cfg, pay, budget=None):
    """Единственное место, откуда уходят деньги, — согласие и лимит проверяются здесь.

    Смета в `generate()` отказывает раньше, но точка расхода не верит смете: без
    бюджета или сверх его остатка запрос не уходит. Остаток списывается до вызова —
    оборванный запрос мог быть уже тарифицирован.
    """
    if not pay:
        raise SystemExit('строка %d не нашлась в кэше, а согласия на расход нет: '
                         'синтез остановлен, ничего не отправлено (повторите с --yes-i-pay)'
                         % line['n'])
    if budget is None:
        raise SystemExit('строка %d: платный синтез без лимита знаков (--max-chars N) '
                         'не отправляется' % line['n'])
    price = provider.price_chars(line['speech'])
    if price > budget.left:
        raise SystemExit('строка %d: %d знаков сверх остатка лимита %d из %d — '
                         'ничего не отправлено' % (line['n'], price, budget.left, budget.limit))
    budget.left -= price
    return provider.synthesize(line['speech'], voice_cfg, line['api_emotion'],
                               voice_cfg.get('speed', 1.0), voice_cfg.get('pitch', 0))


# ---------------------------------------------------------------------------
# Манифест
# ---------------------------------------------------------------------------

def load_manifest(proj):
    if not proj.manifest.exists():
        return []
    return json.loads(proj.manifest.read_text(encoding='utf-8'))


def merge_manifest(proj, entries):
    """Влить записи; запись атомарна (временный файл + os.replace)."""
    by_n = {e['n']: e for e in load_manifest(proj)}
    for e in entries:
        by_n[e['n']] = e
    os.makedirs(proj.out, exist_ok=True)
    part = str(proj.manifest) + '.part'
    with io.open(part, 'w', encoding='utf-8') as fh:
        json.dump([by_n[n] for n in sorted(by_n)], fh, ensure_ascii=False, indent=1)
    os.replace(part, proj.manifest)


def reply_path(proj, n):
    return proj.reply / ('%03d.mp3' % n)


def manifest_entry(proj, provider, line, key, meta):
    return {'n': line['n'], 'scene': line['scene'], 'voice': line['voice'],
            'emotion': line['emotion'], 'api_emotion': line['api_emotion'],
            'text': line['text'], 'speech': line['speech'], 'chars': len(line['speech']),
            'provider': provider.name, 'key': key, 'ms': meta['ms'], 'usage': meta['usage'],
            'file': 'reply/%03d.mp3' % line['n']}


# ---------------------------------------------------------------------------
# Команды
# ---------------------------------------------------------------------------

def parse_rows_arg(arg, lines):
    wanted = set()
    for part in arg.split(','):
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            a, b = part.split('-', 1)
            wanted.update(range(int(a), int(b) + 1))
        else:
            wanted.add(int(part))
    unknown = sorted(wanted - {x['n'] for x in lines})
    if unknown:
        raise SystemExit('в rows.json нет строк с номерами %s' % unknown)
    return wanted


def cmd_estimate(proj, lines, subset=None):
    cls = provider_class(proj.voices_cfg)
    part = [x for x in lines if subset is None or x['n'] in subset]
    ready = env_ready(proj, cls)
    provider = cls(proj.voices_cfg, read_env_file(proj.env_path)) if ready else None
    pricer = provider or cls(proj.voices_cfg, {})
    print('провайдер: %s; строк: %d%s' % (cls.name, len(part),
                                          '' if subset is None else ' (выбранные %s)' % sorted(subset)))
    total_chars = total_price = 0
    speech_sec = clip_sec = 0.0
    for vid in sorted(proj.voices_cfg['voices']):
        v = proj.voice(vid)
        mine = [x for x in part if x['voice'] == vid]
        chars = sum(len(x['speech']) for x in mine)
        price = sum(pricer.price_chars(x['speech']) for x in mine)
        sec = chars * v.get('sec_per_char', 0.0)
        clip = sum(len(x['speech']) * v.get('sec_per_char_net', 0.0) + v.get('clip_pad_sec', 0.0)
                   for x in mine)
        total_chars += chars
        total_price += price
        speech_sec += sec
        clip_sec += clip
        print('    голос %-4s %-40s %3d реплик %6d знаков  к счёту %6d  речь %6.1f с  '
              'скорость %.2f' % (vid, v.get('label', '')[:40], len(mine), chars, price, sec,
                                 v.get('speed', 1.0)))
    edited = [x['n'] for x in part if x['speech'] != x['text']]
    print('знаков в запросах: %d (в документе %d; правка текста для синтеза в строках %s)'
          % (total_chars, sum(len(x['text']) for x in part), edited))
    scenes = []
    for x in part:
        if x['scene'] not in scenes:
            scenes.append(x['scene'])
    joins = len(part) - len(scenes)
    print('речь: %.1f с (ставка брутто); клипы с окантовкой %.1f с; со стыками %.2f с '
          'внутри сцен: %.1f с' % (speech_sec, clip_sec, proj.pause_sec,
                                   clip_sec + joins * proj.pause_sec))
    print('    ставки — замер прошлого проекта; обещание длительности ставить только '
          'после полного прогона')
    if provider is None:
        print('кэш не сверен: в .env проекта нет переменных %s — без них ключ кэша не посчитать'
              % ', '.join(cls.env_names(proj.voices_cfg)))
        print('знаков к оплате при синтезе всех строк: %d' % total_price)
        return 0
    fresh = [x for x in part
             if not cached(proj.cache, cache_key(provider, x, proj.voice(x['voice'])))[0]]
    print('уже в кэше: %d строк; знаков к оплате: %d'
          % (len(part) - len(fresh), sum(provider.price_chars(x['speech']) for x in fresh)))
    return 0


def cmd_voices(proj):
    provider, env = open_provider(proj, need_env=True)
    try:
        found = provider.list_voices()
    except SystemExit as exc:
        raise SystemExit(redact(exc, env))
    for v in found:
        print('    голос %-4s %-40s %s' % (v['voice'], v.get('label', '')[:40],
                                           'доступен ключу' if v['available']
                                           else 'КЛЮЧУ НЕ ПРИНАДЛЕЖИТ (у MiniMax — ошибка 2042)'))
    return 0 if all(v['available'] for v in found) else 1


def parse_max_chars(argv):
    """Лимит знаков из `--max-chars N`; None — флага нет; SystemExit — не число."""
    if '--max-chars' not in argv:
        return None
    i = argv.index('--max-chars')
    try:
        value = int(argv[i + 1])
    except (IndexError, ValueError):
        raise SystemExit('--max-chars требует целое число знаков')
    if value < 0:
        raise SystemExit('--max-chars не может быть отрицательным')
    return value


def lint_findings(proj, nums):
    """Находки speech_lint на строках `nums` — тот же линт, что запускают руками."""
    import speech_lint
    rows = config.read_json(proj.dir / 'rows.json')
    edits = config.read_json(proj.dir / 'speech_edits.json', {})
    found = speech_lint.lint(rows, edits,
                             speech_lint.load_words(speech_lint.HERE / 'homographs.txt'),
                             speech_lint.load_patterns(speech_lint.HERE / 'carrier_words.txt'))
    keys = {str(n) for n in nums}
    return [f for f in found if str(f[0]) in keys]


def generate(proj, lines, wanted, pay, max_chars=None):
    if pay and max_chars is None:
        print('--yes-i-pay без --max-chars N: платный синтез без лимита знаков не запускается. '
              'Ничего не отправлено.')
        return 1
    provider, env = open_provider(proj, need_env=True)
    todo = [x for x in lines if x['n'] in wanted]
    fresh = [x for x in todo
             if not cached(proj.cache, cache_key(provider, x, proj.voice(x['voice'])))[0]]
    price = sum(provider.price_chars(x['speech']) for x in fresh)
    if fresh and not pay:
        print('к синтезу %d строк %s, %d знаков к счёту — это расход с аккаунта.'
              % (len(fresh), [x['n'] for x in fresh], price))
        print('ничего не отправлено. Повторите с --yes-i-pay, когда решение принято.')
        return 1
    if fresh:
        found = lint_findings(proj, [x['n'] for x in fresh])
        if found:
            for n, cls, frag in found:
                print('  строка %s → %s → %s' % (n, cls, frag))
            print('speech_lint: %d находок на оплачиваемых строках без правки или разрешения '
                  '(speech_edits.json). Ничего не отправлено.' % len(found))
            return 1
        if price > max_chars:
            print('к оплате %d знаков (%d строк %s) больше лимита --max-chars %d. '
                  'Ничего не отправлено.' % (price, len(fresh), [x['n'] for x in fresh],
                                             max_chars))
            return 1
    budget = Budget(max_chars if max_chars is not None else 0)
    os.makedirs(proj.reply, exist_ok=True)
    spent = 0
    for x in todo:
        v = proj.voice(x['voice'])
        key = cache_key(provider, x, v)
        mp3, meta = cached(proj.cache, key)
        if mp3 is None:
            try:
                audio = synthesize_paid(provider, x, v, pay, budget)
            except SystemExit as exc:
                raise SystemExit(redact(exc, env))
            mp3, meta = put_cache(proj.cache, key, audio, None, provider.price_chars(x['speech']))
            spent += meta['usage']
            mark = 'синтез'
        else:
            mark = 'из кэша'
        shutil.copyfile(mp3, reply_path(proj, x['n']))
        merge_manifest(proj, [manifest_entry(proj, provider, x, key, meta)])
        print('  %03d  %-10s голос %-4s %-10s %5d знаков  %6.2f с  %s'
              % (x['n'], x['scene'], x['voice'], x['api_emotion'], len(x['speech']),
                 meta['ms'] / 1000.0, mark))
    print('---')
    print('обработано строк: %d, оплачено знаков: %d' % (len(todo), spent))
    return 0


def ensure_pause(proj):
    path = proj.out / ('pause-%.2f.mp3' % proj.pause_sec)
    if path.exists() and path.stat().st_size > 0:
        return path
    os.makedirs(proj.out, exist_ok=True)
    subprocess.run([ffmpeg(), '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi',
                    '-i', 'anullsrc=r=44100:cl=mono', '-t', str(proj.pause_sec),
                    '-c:a', 'libmp3lame', '-b:a', '128k', str(path)], check=True)
    return path


def concat(files, out, pause):
    listing = Path(str(out) + '.txt')
    with io.open(listing, 'w', encoding='utf-8') as fh:
        for i, path in enumerate(files):
            if i:
                fh.write("file '%s'\n" % str(pause).replace('\\', '/'))
            fh.write("file '%s'\n" % str(path).replace('\\', '/'))
    subprocess.run([ffmpeg(), '-hide_banner', '-loglevel', 'error', '-y', '-f', 'concat',
                    '-safe', '0', '-i', str(listing), '-c:a', 'libmp3lame', '-b:a', '128k',
                    '-ar', '44100', '-ac', '1', str(out)], check=True)
    listing.unlink()


def cmd_assemble(proj, lines, only=None):
    """Сцена = реплики подряд через паузу `pause_sec`. Манифест получает шкалу.

    `scene_start/scene_end` — на шкале своей сцены; `start/end` — на общей шкале
    сцен подряд без зазора (зазор между сценами задаёт видео: project.json.scene_gap_sec).
    """
    order, by_scene = [], {}
    for x in lines:
        if x['scene'] not in by_scene:
            order.append(x['scene'])
            by_scene[x['scene']] = []
        by_scene[x['scene']].append(x)
    if only:
        unknown = sorted(set(only) - set(order))
        if unknown:
            raise SystemExit('таких сцен в rows.json нет: %s' % unknown)
    missing = [x['n'] for x in lines if not reply_path(proj, x['n']).exists()
               and (not only or x['scene'] in only)]
    if missing:
        print('нет файлов реплик: %s — сначала синтез' % missing[:20])
        return 1
    man = {e['n']: e for e in load_manifest(proj)}
    pause = ensure_pause(proj)
    pause_sec = decoded_sec(pause)
    os.makedirs(proj.scene, exist_ok=True)
    offset, updates = 0.0, []
    for scene in order:
        files = [reply_path(proj, x['n']) for x in by_scene[scene]]
        out = proj.scene / ('%s.mp3' % scene)
        if not only or scene in only:
            concat(files, out, pause)
        t = 0.0
        for i, (x, f) in enumerate(zip(by_scene[scene], files)):
            if i:
                t += pause_sec
            d = decoded_sec(f)
            e = dict(man.get(x['n']) or {'n': x['n']})
            e.update({'scene_mp3': 'scene/%s.mp3' % scene, 'scene_start': round(t, 3),
                      'scene_end': round(t + d, 3), 'start': round(offset + t, 3),
                      'end': round(offset + t + d, 3)})
            updates.append(e)
            t += d
        sec = decoded_sec(out) if out.exists() else t
        print('  сцена %-12s %2d реплик  %6.2f с  %s' % (scene, len(files), sec, out.name))
        offset += sec
    merge_manifest(proj, updates)
    print('---')
    print('сцен: %d, всего %.2f с; шкала реплик записана в манифест' % (len(order), offset))
    return 0


def cmd_report(proj, lines):
    man = load_manifest(proj)
    if not man:
        print('манифест пуст — синтез ещё не запускался')
        return 1
    by_scene = {}
    for e in man:
        by_scene.setdefault(e.get('scene', '?'), []).append(e)
    for scene, part in by_scene.items():
        print('  сцена %-12s %2d реплик  %6.2f с' % (scene, len(part),
                                                    sum(e['ms'] for e in part) / 1000.0))
    print('---')
    print('реплик в манифесте: %d из %d строк' % (len(man), len(lines)))
    print('тарифицировано знаков: %d' % sum(e.get('usage', 0) for e in man))
    joins = len(man) - len(by_scene)
    speech = sum(e['ms'] for e in man) / 1000.0
    print('речь: %.2f с (промер клипов); со стыками %.2f с внутри сцен: %.2f с'
          % (speech, proj.pause_sec, speech + joins * proj.pause_sec))
    return 0


def main(argv):
    pdir, argv = config.project_root.split_argv(argv)     # --project → MOTION_PROJECT → <шаблон>/project
    proj = config.Project(pdir)
    cls = provider_class(proj.voices_cfg)
    lines = proj.lines(cls.emotions)
    pay = '--yes-i-pay' in argv
    if '--voices' in argv:
        return cmd_voices(proj)
    if '--assemble' in argv:
        only = None
        if '--scenes' in argv:
            only = {s for s in argv[argv.index('--scenes') + 1].split(',') if s}
        return cmd_assemble(proj, lines, only)
    if '--report' in argv:
        return cmd_report(proj, lines)
    if '--estimate' in argv:
        subset = parse_rows_arg(argv[argv.index('--rows') + 1], lines) if '--rows' in argv else None
        return cmd_estimate(proj, lines, subset)
    if '--all' in argv:
        return generate(proj, lines, {x['n'] for x in lines}, pay, parse_max_chars(argv))
    if '--rows' in argv:
        return generate(proj, lines, parse_rows_arg(argv[argv.index('--rows') + 1], lines), pay,
                        parse_max_chars(argv))
    return cmd_estimate(proj, lines)


def cli(argv):
    """Точка входа: ЛЮБОЕ исключение печатается через redact() значений .env проекта.

    SystemExit провайдеров уже затёрт, но сбой сети (TimeoutError, RemoteDisconnected),
    ошибка разбора и любая другая трассировка могут нести заголовок запроса или эхо
    тела — поэтому затирается всё, что выходит наружу, включая трассировку.
    """
    import traceback
    try:
        return main(argv)
    except KeyboardInterrupt:
        print('прервано', file=sys.stderr)
        return 130
    except BaseException as exc:
        if isinstance(exc, SystemExit) and isinstance(exc.code, int):
            return exc.code
        try:
            env = read_env_file(str(config.Project(config.project_dir(argv)).env_path))
        except BaseException:
            env = read_env_file(str(config.project_dir(argv) / '.env'))
        if isinstance(exc, SystemExit):
            print(redact(exc.code, env), file=sys.stderr)
            return 1
        tb = ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        print(redact(tb, env), file=sys.stderr)
        print('%s: %s' % (type(exc).__name__, redact(exc, env)), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(cli(sys.argv[1:]))
