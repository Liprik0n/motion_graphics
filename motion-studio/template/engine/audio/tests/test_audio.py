# -*- coding: utf-8 -*-
"""Тесты швов звука: раскладка музыки по главам, круг короткого трека, план эффектов по событиям,
сквозная сборка на крошечном фильме (детерминизм `-bitexact`, нет сети, нет записи в шаблон).

    python tests/test_audio.py [--tmp ПАПКА] [--fast]

--fast пропускает сквозной прогон (ffmpeg, ~1 мин). Все тесты работают на публичных функциях
`music.resolve_parts / layout`, `sfx.plan` и на CLI; конфиги шаблона не трогаются.
"""
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
sys.stdout.reconfigure(encoding='utf-8')

AUDIO = Path(__file__).resolve().parents[1]
TEMPLATE = AUDIO.parents[1]
sys.path.insert(0, str(AUDIO))

FAILS = []


def ok(cond, msg):
    print('  %s   %s' % ('ok ' if cond else 'ПРОВАЛ', msg))
    if not cond:
        FAILS.append(msg)


def raises(fn, needle):
    try:
        fn()
    except SystemExit as e:
        return needle in str(e)
    except Exception:       # noqa: BLE001 — любое другое исключение — не то, что проверяем
        return False
    return False


# ---------------------------------------------------------------- музыка: главы → части

def film_with_chapters():
    return {'duration': 30.0,
            'scenes': [{'id': 's1', 'chapter_from': 'intro', 'chapter': 'steps'},
                       {'id': 's2', 'chapter_from': None, 'chapter': 'contacts'}],
            'events': [{'kind': 'chapter', 't': 2.0, 'scene': 's1', 'ref': 'steps', 'dur': 0.6},
                       {'kind': 'show', 't': 5.0, 'scene': 's1', 'ref': 'x'},
                       {'kind': 'chapter', 't': 12.0, 'scene': 's2', 'ref': 'contacts', 'dur': 0.5},
                       {'kind': 'chapter', 't': 12.0, 'scene': 's2', 'ref': 'contacts', 'dur': 0.5}]}


def test_parts():
    import music
    film = film_with_chapters()
    cfg = {'tracks': [{'chapter': 'steps', 'file': 'steps.wav', 'license': 'x', 'start_sec': 1.0},
                      {'chapter': '*', 'file': 'any.wav', 'license': 'x'}]}
    parts = music.resolve_parts(film, cfg)
    ok([(p['chapters'], p['track']) for p in parts] == [(['intro'], 1), (['steps'], 0), (['contacts'], 1)],
       'части: intro → запасной «*», steps → свой трек, contacts → снова «*» (повтор события главы не множит часть)')
    ok([round(p['from'], 3) for p in parts] == [0.0, 2.3, 12.25] and parts[-1]['to'] == 30.0,
       'стык частей — середина хода полосы главы (t + dur/2), последняя часть до конца фильма')
    one = music.resolve_parts(film, {'tracks': [{'chapter': '*', 'file': 'any.wav', 'license': 'x'}]})
    ok(len(one) == 1 and one[0]['chapters'] == ['intro', 'steps', 'contacts'] and one[0]['to'] == 30.0,
       'один трек «*» на все главы — одна часть, стыков нет')
    ok(raises(lambda: music.resolve_parts(film, {'tracks': [{'chapter': 'steps', 'file': 'a', 'license': 'x'}]}),
              'нет трека для главы intro'),
       'глава без трека и без «*» — понятная ошибка с именем главы')
    ok(raises(lambda: music.resolve_parts(film, {'tracks': [{'chapter': '*', 'file': 'a', 'license': ''}]}),
              'license'),
       'трек без лицензии не принимается: источник и условия обязательны')


def test_layout():
    import music
    tracks = {0: {'a': 2.0, 'b': 22.0}}
    parts = [{'index': 0, 'track': 0, 'start_sec': 0.0, 'from': 0.0, 'to': 60.0}]
    segs = music.layout(parts, tracks, 60.0, xf=2.5, loop_xf=3.0, first_fade=0.5)
    ok(len(segs) == 3 and all(s['track'] == 0 for s in segs), 'трек 22 с на часть 60 с идёт кругом: 3 сегмента')
    ok(abs(segs[0]['src1'] - 23.5) < 1e-9 and abs(segs[1]['src0'] - 0.5) < 1e-9 and abs(segs[1]['at'] - 20.5) < 1e-9,
       'круг: выход в b + xf/2, вход в a − xf/2, склейка встык на кроссфейде')
    ok(segs[0]['fade_in'] == 0.5 and segs[1]['fade_in'] == 3.0 and segs[-1]['fade_out'] == 0.0,
       'вход фильма 0,5 с, склейки круга 3 с, финал без кроссфейда (затухание — огибающая)')
    short = music.layout([dict(parts[0], to=10.0)], tracks, 10.0, 2.5, 3.0, 0.5)
    ok(len(short) == 1, 'часть короче трека — без круга')


# ---------------------------------------------------------------- эффекты: события → реплики

RULES = {'min_gap_sec': 1.5, 'keep_prio': 9,
         'events': [{'kind': 'seam', 'clip': 'whoosh_click', 'variants': 3, 'gain_db': -13, 'prio': 9, 'lead_sec': 0.45},
                    {'kind': 'chapter', 'clip': 'whoosh_click', 'variants': 3, 'gain_db': -14, 'prio': 7,
                     'anchor': 'end'},
                    {'kind': 'emph', 'match': {'style': ['ring', 'flash']}, 'clip': 'ping', 'variants': 3,
                     'gain_db': -27, 'prio': 1},
                    {'kind': 'show', 'match': {'anim': 'draw'}, 'clip': 'tick', 'gain_db': -24, 'prio': 2}]}


def ev(kind, t, ref='x', **kw):
    return dict({'kind': kind, 't': t, 'scene': 's', 'ref': ref}, **kw)


def test_plan():
    import sfx
    events = [ev('emph', 9.0, style='ring'), ev('emph', 9.5, style='breathe'), ev('show', 4.0, anim='rise'),
              ev('show', 20.0, 'ok', anim='draw'), ev('seam', 12.0, 'a>b'), ev('chapter', 12.0, 'c', dur=0.5)]
    cues, dropped = sfx.plan(events, RULES)
    ok([c['clip'] for c in cues] == ['ping', 'whoosh_click', 'tick'],
       'в план входят только события каталога (правило + match): breathe и rise не звучат')
    seam = cues[1]
    ok(abs(seam['hit'] - 12.0) < 1e-9 and abs(seam['onset'] - 11.55) < 1e-9,
       'удар эффекта — на событии, начало раньше на lead_sec (вжух перед щелчком)')
    ok(len(dropped) == 1 and dropped[0]['kind'] == 'chapter' and 'seam' in dropped[0]['reason'],
       'глава в тот же миг, что шов, выпадает по плотности (приоритет 7 < 9), причина названа')
    ok(all(b['onset'] - a['onset'] >= 1.5 for a, b in zip(cues, cues[1:])), 'начала эффектов не ближе min_gap_sec')
    ch = sfx.plan([ev('chapter', 2.0, 'c', dur=0.6)], RULES)[0][0]
    ok(abs(ch['hit'] - 2.6) < 1e-9, 'anchor: end — удар на конце хода полосы (t + dur)')
    eq = sfx.plan([ev('emph', 9.0, 'a', style='ring'), ev('emph', 9.4, 'b', style='ring')], RULES)
    ok(len(eq[0]) == 1 and eq[0][0]['event']['ref'] == 'a' and eq[1][0]['event'] == 'emph:b',
       'равный приоритет: остаётся более ранний, второй записан в выпавших')
    ok(raises(lambda: sfx.plan([ev('seam', 5.0, 'a>b'), ev('seam', 5.5, 'c>d')], RULES), 'выбрать некого'),
       'два «неприкосновенных» (приоритет ≥ keep_prio) ближе min_gap_sec — сборка отказывает')
    ok(raises(lambda: sfx.plan([ev('seam', 0.2, 'a>b')], RULES), 'раньше начала фильма'),
       'эффект, начало которого раньше нуля, — ошибка с событием, а не молчаливая обрезка')
    bad = copy.deepcopy(RULES)
    bad['events'][0]['clip'] = 'гром'
    ok(raises(lambda: sfx.plan([ev('seam', 5.0, 'a>b')], bad), 'вид эффекта'), 'неизвестный вид клипа назван в ошибке')


# ---------------------------------------------------------------- сквозной прогон

def tiny_project(tmp):
    """Копия конфигов шаблона + мини-фильм на готовых mp3 демо (без сборки видео)."""
    proj = Path(tmp) / 'proj'
    shutil.copytree(TEMPLATE / 'project', proj, ignore=shutil.ignore_patterns('out', '.env'))
    out = proj / 'out' / 'tiny'
    out.mkdir(parents=True)
    film = {'film': 'tiny', 'estimate': False, 'fps': 30, 'duration': 12.0,
            'scenes': [{'id': 's1', 'chapter_from': 'intro', 'chapter': 'steps'}],
            'replies': [{'n': 1, 'num': 1, 'scene': 's1', 'voice': 'a', 'start': 0.6, 'end': 5.4,
                         'file': 'demo-audio/130.mp3'},
                        {'n': 2, 'num': 2, 'scene': 's1', 'voice': 'b', 'start': 6.0, 'end': 10.9,
                         'file': 'demo-audio/131.mp3'}],
            'events': [{'kind': 'chapter', 't': 1.5, 'scene': 's1', 'ref': 'steps', 'dur': 0.6},
                       {'kind': 'emph', 't': 8.0, 'scene': 's1', 'ref': 'bell', 'style': 'ring', 'dur': 0.8}]}
    (out / 'film.json').write_text(json.dumps(film, ensure_ascii=False), encoding='utf-8')
    return proj


def run_py(script, *args):
    r = subprocess.run([sys.executable, str(AUDIO / script)] + list(args), capture_output=True)
    return r.returncode, (r.stdout + r.stderr).decode('utf-8', 'replace')


def test_end_to_end(tmp):
    import dsp
    proj = tiny_project(tmp)
    snap = {p: p.stat().st_mtime_ns for p in (TEMPLATE / 'project').rglob('*') if p.is_file()}
    had_out = (TEMPLATE / 'project' / 'out').exists()      # в проекте с собранными фильмами out/ уже есть
    pad = proj / 'music' / 'placeholder-pad.wav'
    ok(pad.exists(), 'демо-проект везёт файл трека-заглушки music/placeholder-pad.wav')
    code, text = run_py('music.py', 'tiny', '--project', str(proj))
    out = proj / 'out' / 'tiny'
    ok(code == 0 and (out / 'mix.m4a').exists(), 'music.py собирает mix.m4a на мини-фильме: %s' % text[-300:].strip())
    first = {n: dsp.sha1(out / n) for n in ('mix.m4a', 'music.wav', 'sfx.wav')}
    code2, _ = run_py('music.py', 'tiny', '--project', str(proj))
    second = {n: dsp.sha1(out / n) for n in ('mix.m4a', 'music.wav', 'sfx.wav')}
    ok(code2 == 0 and first == second, 'пересборка байт в байт (-bitexact): mix.m4a, music.wav, sfx.wav')
    lufs, tp = dsp.lufs(['-i', str(out / 'mix.m4a')])
    ok(abs(lufs + 16.0) <= 1.0 and tp <= -1.0, 'микс −16 ± 1 LUFS, пик ≤ −1 dBTP: %.2f LUFS, %.2f dBTP' % (lufs, tp))
    # без видео --mux честно отказывает
    code3, text3 = run_py('music.py', 'tiny', '--project', str(proj), '--mux')
    ok(code3 != 0 and 'video.mp4' in text3, '--mux без video.mp4 — отказ с именем файла')
    code4, text4 = run_py('sfx.py', 'tiny', '--project', str(proj))
    ok(code4 == 0 and (out / 'sfx-proba.mp3').exists(), 'sfx.py пишет sfx-proba.mp3 без видео и без музыки: %s' % text4[-200:].strip())
    after = {p: p.stat().st_mtime_ns for p in (TEMPLATE / 'project').rglob('*') if p.is_file()}
    ok(after == snap and (TEMPLATE / 'project' / 'out').exists() == had_out,
       'проект рядом с движком не тронут: out/ не появился, mtime файлов те же')
    for name in ('music.py', 'sfx.py', 'check_mix.py', 'config.py', 'dsp.py', 'synth.py'):
        src = (AUDIO / name).read_text(encoding='utf-8')
        ok('J:\\' not in src and 'J:/' not in src and 'urllib' not in src and 'requests' not in src,
           '%s: нет абсолютных путей и сетевых вызовов' % name)


def main():
    args = sys.argv[1:]
    tmp_root = args[args.index('--tmp') + 1] if '--tmp' in args else None
    for name, fn in (('музыка: главы → части', test_parts), ('музыка: круг трека', test_layout),
                     ('эффекты: план по событиям', test_plan)):
        print(name)
        try:
            fn()
        except NotImplementedError:
            ok(False, 'не реализовано: %s' % fn.__name__)
    if '--fast' not in args:
        print('сквозной прогон')
        tmp = tempfile.mkdtemp(prefix='t04-', dir=tmp_root)
        try:
            test_end_to_end(tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    print('итог: %s' % ('всё зелёное' if not FAILS else 'красных %d' % len(FAILS)))
    sys.exit(1 if FAILS else 0)


if __name__ == '__main__':
    main()
