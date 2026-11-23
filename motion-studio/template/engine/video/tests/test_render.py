# -*- coding: utf-8 -*-
"""Рендер по сценам: черновик, кэш кадров, отрезок, время на кадр, воркеры, оборванный рендер, сосед для --only, замок.

    python engine/video/tests/test_render.py        (≈ 3 мин: десяток коротких рендеров HyperFrames, под замком Chrome)

Ожидания — из задания на рендер, а не из кода build.py:
  - `--draft` даёт видео размера и частоты из project.json render.draft; финал — полотно и частота проекта;
  - после правки одной сцены остальные берутся из кэша, о чём сказано в выводе и в render.log, а кадры после
    всех правок побайтно равны рендеру с нуля в пустой папке; правка, которая видна в кадрах соседа у шва,
    перерендеривает и соседа (иначе итог не был бы равен рендеру с нуля);
  - оборванный рендер (у недоснятой сцены есть кадры, но нет отметки) докатывает только её;
  - `--scene <id>` и `--start/--end` дают mp4 отрезка с его числом кадров;
  - в render.log на снятую сцену строка «сцена <id>: <N> кадров, <X> мс/кадр»; бюджет ниже факта — строка,
    начинающаяся с «ТРЕВОГА», с именем сцены; бюджет выше — такой строки нет;
  - "workers": "auto" — число по ядрам и памяти, напечатано; число из project.json — оно и берётся;
  - `--only <сцена>`, которая называет соседа в разметке, сама добавляет его и пишет об этом;
  - истёкшее ожидание замка Chrome в рендере не меняет выходную папку и не оставляет временной папки и mp4.
Работает на копии project/ во временной папке с фильмом из трёх коротких сцен; поставка не трогается.
"""
NEEDS_CHROME = True      # тест запускает безголовый браузер: общий прогон берёт на него замок и не зовёт в --quick

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

VIDEO = Path(__file__).resolve().parents[1]
ENGINE = VIDEO.parent
TEMPLATE = ENGINE.parent
sys.path.insert(0, str(ENGINE / 'tests'))
from _util import PY, check, run_module   # noqa: E402

sys.path.insert(0, str(ENGINE))
import chrome_lock   # noqa: E402

BUILD = VIDEO / 'build.py'
FPS, W, H = 30, 1920, 1080
DRAFT = {'scale': 0.5, 'fps': 15}
STATE = {}

MARKUP = ('<div class="el" id="box" style="left:360px; top:%dpx; width:1200px; height:120px;">\n'
          '  <span class="t" style="display:block; width:1200px; line-height:120px; text-align:center; font-size:64px; '
          'font-weight:700; color:var(--c-ink); white-space:nowrap;">%s</span>\n</div>\n')


def ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def _run(*args, env=None, timeout=1500):
    e = dict(os.environ)
    e.pop('MOTION_PROJECT', None)
    e.update(env or {})
    r = subprocess.run([PY, str(BUILD)] + [str(a) for a in args], capture_output=True, text=True, encoding='utf-8',
                       errors='replace', env=e, timeout=timeout)
    return r.returncode, r.stdout + r.stderr


def _scene(proj, sid, text, y, beats, script=''):
    d = proj / 'scenes' / sid
    d.mkdir(parents=True, exist_ok=True)
    (d / 'markup.html').write_text(MARKUP % (y, text) + script, encoding='utf-8')
    sb = {'scene': sid, 'title': sid, 'frame': False, 'markup': 'markup.html', 'start_state': {}, 'end_state': {},
          'beats': beats}
    (d / 'storyboard.json').write_text(json.dumps(sb, ensure_ascii=False, indent=1), encoding='utf-8')


def _settings(proj, **render):
    p = proj / 'project.json'
    pj = json.loads(p.read_text(encoding='utf-8-sig'))
    pj.update(scene_gap_sec=0.6, pause_sec=0.2, lead_sec=0.2, tail_sec=0.2)
    pj['render'] = dict({'workers': 'auto', 'frame_budget_ms': 10 ** 9, 'draft': dict(DRAFT)}, **render)
    p.write_text(json.dumps(pj, ensure_ascii=False, indent=1), encoding='utf-8')


def _proj():
    """Копия проекта шаблона с фильмом tiny: три сцены по одной немой строке 0,3 с (звука нет, длины — по ms).
    r1 уходит наплывом — её надпись ещё видна в первых кадрах r2; r2 и r3 гаснут сразу, за свои границы не выходят.
    Фильм win: сцена w1 называет w2 в разметке (окно в соседнюю сцену)."""
    if 'proj' not in STATE:
        tmp = Path(tempfile.mkdtemp(prefix='render_test_'))
        proj = tmp / 'project'
        shutil.copytree(TEMPLATE / 'project', proj, ignore=shutil.ignore_patterns('out', '.env', '__pycache__'))
        _settings(proj)
        show = lambda n: {'reply': n, 'at': 0, 'action': 'show', 'targets': ['box'], 'anim': 'cut'}      # noqa: E731
        cut = lambda n: {'reply': n, 'at': 1, 'action': 'hide', 'targets': ['box'], 'anim': 'cut'}       # noqa: E731
        _scene(proj, 'r1', 'Первая сцена', 300, [show(1)])
        _scene(proj, 'r2', 'Вторая сцена', 480, [show(2), cut(2)])
        _scene(proj, 'r3', 'Третья сцена', 660, [show(3), cut(3)])
        _scene(proj, 'w1', 'Окно в соседа', 300, [show(1)], "<script>window.__windowTo = 'w2';</script>\n")
        _scene(proj, 'w2', 'Сосед', 480, [show(2)])
        rep = lambda n, s: {'n': n, 'scene': s, 'voice': 'a', 'emotion': 'Neutral', 'ms': 300}           # noqa: E731
        (proj / 'films' / 'tiny.json').write_text(json.dumps(
            {'title': 'тест рендера', 'scenes': ['r1', 'r2', 'r3'], 'replies': [rep(1, 'r1'), rep(2, 'r2'), rep(3, 'r3')]},
            ensure_ascii=False), encoding='utf-8')
        (proj / 'films' / 'win.json').write_text(json.dumps(
            {'title': 'тест соседа', 'scenes': ['w1', 'w2'], 'replies': [rep(1, 'w1'), rep(2, 'w2')]},
            ensure_ascii=False), encoding='utf-8')
        STATE.update(tmp=tmp, proj=proj, out=proj / 'out' / 'tiny')
        STATE['first'] = _run('tiny', '--draft', '--project', proj)
    return STATE['proj']


def _retext(proj, sid, old, new):
    p = proj / 'scenes' / sid / 'markup.html'
    s = p.read_text(encoding='utf-8')
    check(old in s, 'в разметке %s нет «%s» — тест правит не то' % (sid, old))
    p.write_text(s.replace(old, new), encoding='utf-8')


def _tree(root):
    """{относительный путь кадра: байты} по всей папке кадров."""
    root = Path(root)
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob('frame_*.png'))}


def _video(path):
    """(ширина, высота, к/с, кадров) видеодорожки mp4."""
    r = subprocess.run([ffmpeg(), '-hide_banner', '-i', str(path), '-map', '0:v:0', '-c', 'copy', '-f', 'null', '-'],
                       capture_output=True, text=True, encoding='utf-8', errors='replace').stderr
    m = re.search(r'Video: h264.*?, (\d+)x(\d+).*?, ([\d.]+) fps', r)
    fr = re.findall(r'frame=\s*(\d+)', r)
    check(m and fr, 'не прочесть видеодорожку %s: %s' % (path, r[-300:]))
    return int(m.group(1)), int(m.group(2)), float(m.group(3)), int(fr[-1])


def _film(out):
    return json.loads((Path(out) / 'film.json').read_text(encoding='utf-8'))


def _scene_lines(text):
    """{сцена: строка} — строки «сцена <id>: …» вывода или журнала."""
    return {m.group(1): m.group(0) for m in re.finditer(r'^\s*сцена (\S+): .*$', text, re.M)}


def test_draft_has_size_and_fps_of_render_draft():
    proj = _proj()
    code, out = STATE['first']
    check(code == 0, 'build.py tiny --draft упал: %s' % out[-900:])
    mp4 = STATE['out'] / 'video-draft.mp4'
    check(mp4.exists(), 'черновик не дал video-draft.mp4: %s' % out[-400:])
    w, h, fps, n = _video(mp4)
    check((w, h) == (int(W * DRAFT['scale']), int(H * DRAFT['scale'])),
          'кадр черновика %d × %d, а project.json render.draft.scale %s от %d × %d — %d × %d'
          % (w, h, DRAFT['scale'], W, H, W * DRAFT['scale'], H * DRAFT['scale']))
    check(fps == DRAFT['fps'], 'частота черновика %s к/с, а в render.draft.fps — %s' % (fps, DRAFT['fps']))
    want = _film(STATE['out'])['duration'] * DRAFT['fps']
    check(abs(n - want) <= 1, 'кадров в черновике %d, а длительность × частота черновика — %.1f' % (n, want))
    check(not (STATE['out'] / 'video.mp4').exists(), 'черновик записан в video.mp4 — он выдаёт себя за финал')


def test_draft_log_has_ms_per_frame_and_auto_workers():
    _proj()
    out = STATE['first'][1]
    log = (STATE['out'] / 'render.log').read_text(encoding='utf-8')
    for sid in ('r1', 'r2', 'r3'):
        check(re.search(r'^сцена %s: \d+ кадров, \d+ мс/кадр' % sid, log, re.M),
              'в render.log нет строки «сцена %s: <N> кадров, <X> мс/кадр»: %s' % (sid, log[-600:]))
    m = re.search(r'воркеры захвата: (\d+) \(([^)]*)\)', out)
    check(m, 'число воркеров не напечатано: %s' % out[-600:])
    check('auto' in m.group(2) and 'ядер' in m.group(2) and 'ОЗУ' in m.group(2),
          'при "workers": "auto" не сказано, по чему выбрано число (ядра, память): %s' % m.group(0))
    check(1 <= int(m.group(1)) <= (os.cpu_count() or 1), 'воркеров %s при %s ядрах' % (m.group(1), os.cpu_count()))
    check(not re.search(r'^ТРЕВОГА', log, re.M), 'тревога при бюджете 10^9 мс на кадр: %s' % log[-400:])


def test_edit_of_one_scene_takes_the_rest_from_cache():
    proj = _proj()
    before = _tree(STATE['out'] / 'frames-draft')
    _retext(proj, 'r3', 'Третья сцена', 'Третья сцена, правка')
    code, out = _run('tiny', '--draft', '--project', proj)
    check(code == 0, 'рендер после правки r3 упал: %s' % out[-900:])
    lines = _scene_lines(out)
    for sid in ('r1', 'r2'):
        check('из кэша' in lines.get(sid, ''), 'сцена %s после правки r3 не взята из кэша: %s' % (sid, lines.get(sid) or out[-600:]))
    check('мс/кадр' in lines.get('r3', ''), 'правленая r3 не снята заново: %s' % (lines.get('r3') or out[-600:]))
    log = (STATE['out'] / 'render.log').read_text(encoding='utf-8')
    check(re.search(r'^сцена r1: \d+ кадров из кэша', log, re.M) and re.search(r'^сцена r2: \d+ кадров из кэша', log, re.M),
          'в render.log не сказано, какие сцены взяты из кэша: %s' % log[-500:])
    after = _tree(STATE['out'] / 'frames-draft')
    same = [k for k in before if k.startswith(('r1/', 'r2/'))]
    check(same and all(before[k] == after.get(k) for k in same), 'кадры r1 и r2 переписаны, хотя взяты из кэша')
    check(any(before[k] != after.get(k) for k in before if k.startswith('r3/')), 'кадры r3 после правки её текста те же')


def test_edit_seen_across_the_seam_rerenders_the_neighbour():
    """r1 уходит наплывом и ещё видна в первых кадрах r2: правка r1 меняет кадры r2 у шва — r2 снимается заново.
    r3 от r1 не зависит и остаётся в кэше."""
    proj = _proj()
    _retext(proj, 'r1', 'Первая сцена', 'Первая сцена, правка')
    code, out = _run('tiny', '--draft', '--project', proj)
    check(code == 0, 'рендер после правки r1 упал: %s' % out[-900:])
    lines = _scene_lines(out)
    check('мс/кадр' in lines.get('r1', ''), 'правленая r1 не снята заново: %s' % (lines.get('r1') or out[-600:]))
    check('мс/кадр' in lines.get('r2', '') and 'шв' in lines.get('r2', ''),
          'r2 не снята заново, хотя в её первых кадрах видна правленая r1: %s' % (lines.get('r2') or out[-600:]))
    check('из кэша' in lines.get('r3', ''), 'r3 снята заново, хотя правка r1 до неё не доходит: %s' % (lines.get('r3') or out[-600:]))


def test_frames_after_edits_equal_render_from_scratch():
    proj = _proj()
    scratch = STATE['tmp'] / 'scratch'
    code, out = _run('tiny', '--draft', '--project', proj, '--out-dir', scratch)
    check(code == 0, 'рендер с нуля упал: %s' % out[-900:])
    a, b = _tree(STATE['out'] / 'frames-draft'), _tree(scratch / 'frames-draft')
    check(len(b) > 0 and sorted(a) == sorted(b), 'кадры после правок и с нуля — разные наборы: %d и %d' % (len(a), len(b)))
    diff = [k for k in b if a[k] != b[k]]
    check(not diff, 'после правок с кэшем %d кадров из %d не равны рендеру с нуля побайтно (первый — %s)'
          % (len(diff), len(b), diff[0] if diff else ''))
    STATE['scratch'] = scratch


def test_interrupted_render_continues_from_done_scenes():
    """Оборванный рендер: у недоснятой сцены есть часть кадров, отметки ещё нет (её пишут, когда сняты все кадры)."""
    proj = _proj()
    d = STATE['out'] / 'frames-draft' / 'r2'
    frames = sorted(d.glob('frame_*.png'))
    check(len(frames) > 2 and (d / 'stamp.json').exists(), 'у r2 нет кадров и отметки сцены — нечего обрывать')
    (d / 'stamp.json').unlink()
    for p in frames[len(frames) // 2:]:
        p.unlink()
    code, out = _run('tiny', '--draft', '--project', proj)
    check(code == 0, 'рендер после обрыва упал: %s' % out[-900:])
    lines = _scene_lines(out)
    check('из кэша' in lines.get('r1', '') and 'из кэша' in lines.get('r3', ''),
          'готовые сцены r1 и r3 после обрыва сняты заново: %s | %s' % (lines.get('r1'), lines.get('r3')))
    check('мс/кадр' in lines.get('r2', ''), 'недоснятая r2 не докатана: %s' % (lines.get('r2') or out[-600:]))
    a, b = _tree(STATE['out'] / 'frames-draft'), _tree(STATE['scratch'] / 'frames-draft')
    check(a == b, 'после докатки кадры не равны рендеру с нуля')


def test_scene_flag_renders_one_scene_final_size_and_alarm_below_budget():
    proj = _proj()
    _settings(proj, workers=2, frame_budget_ms=1)
    code, out = _run('tiny', '--scene', 'r2', '--project', proj)
    check(code == 0, 'build.py tiny --scene r2 упал: %s' % out[-900:])
    clip = STATE['out'] / 'clips' / 'scene-r2.mp4'
    check(clip.exists(), '--scene r2 не дал clips/scene-r2.mp4: %s' % out[-400:])
    sc = [s for s in _film(STATE['out'])['scenes'] if s['id'] == 'r2'][0]
    w, h, fps, n = _video(clip)
    check((w, h, fps) == (W, H, FPS), 'финальный кадр %d × %d при %s к/с, а полотно и частота проекта — %d × %d, %d'
          % (w, h, fps, W, H, FPS))
    want = round((sc['end'] - sc['start']) * FPS)
    check(abs(n - want) <= 1, 'в отрезке сцены %d кадров, а сцена длится %d кадров' % (n, want))
    lines = _scene_lines(out)
    check(set(lines) == {'r2'}, '--scene r2 тронул другие сцены: %s' % sorted(lines))
    check(re.search(r'воркеры захвата: 2 \(', out), 'число воркеров из project.json render.workers (2) не взято: %s'
          % (re.search(r'воркеры захвата[^\n]*', out) or [out[-300:]])[0])
    log = (STATE['out'] / 'render.log').read_text(encoding='utf-8')
    check(re.search(r'^сцена r2: %d кадров, \d+ мс/кадр' % n, log, re.M), 'в render.log нет строки сцены r2 с %d кадрами: %s' % (n, log[-500:]))
    alarm = [l for l in log.splitlines() if l.startswith('ТРЕВОГА')]
    check(alarm and 'r2' in alarm[0], 'при бюджете 1 мс на кадр нет строки «ТРЕВОГА» с именем сцены: %s' % log[-500:])


def test_start_end_renders_a_span_and_no_alarm_above_budget():
    proj = _proj()
    _settings(proj, frame_budget_ms=10 ** 9)
    code, out = _run('tiny', '--start', 0.1, '--end', 0.3, '--project', proj)
    check(code == 0, 'build.py tiny --start 0.1 --end 0.3 упал: %s' % out[-900:])
    clips = sorted((STATE['out'] / 'clips').glob('range-*.mp4'))
    check(len(clips) == 1, '--start/--end не дал один clips/range-….mp4: %s' % [c.name for c in clips])
    w, h, fps, n = _video(clips[0])
    check((w, h, fps, n) == (W, H, FPS, 6), 'отрезок 0,1–0,3 с: %d × %d, %s к/с, %d кадров — ждали %d × %d, %d к/с, 6 кадров'
          % (w, h, fps, n, W, H, FPS))
    log = (STATE['out'] / 'render.log').read_text(encoding='utf-8')
    check(re.search(r'^сцена r1: 6 кадров, \d+ мс/кадр', log, re.M), 'нет строки о шести кадрах r1: %s' % log[-500:])
    check(not [l for l in log.splitlines() if l.startswith('ТРЕВОГА')], 'тревога при бюджете выше факта: %s' % log[-400:])


def test_only_adds_the_neighbour_the_scene_names():
    proj = _proj()
    code, out = _run('win', '--only', 'w1', '--page', '--project', proj)
    check(code == 0, 'build.py win --only w1 --page упал: %s' % out[-900:])
    said = [l for l in out.splitlines() if 'w2' in l and 'добавлена' in l]
    check(said and 'w1' in said[0], 'сборка не сказала строкой, что добавила соседа w2 для w1: %s' % out[:600])
    od = proj / 'out' / 'win--w1,w2'
    check(od.is_dir() and [s['id'] for s in _film(od)['scenes']] == ['w1', 'w2'],
          'сосед не попал в сборку: нет %s со сценами w1, w2' % od)
    code, out = _run('win', '--only', 'w2', '--page', '--project', proj)
    check(code == 0 and 'добавлена' not in out and (proj / 'out' / 'win--w2').is_dir(),
          '--only w2 (никого не называет) собрана не одна: %s' % out[:600])


def test_lock_timeout_in_render_changes_nothing():
    """Замок Chrome свободен на промере страницы и занят к рендеру: рендер обязан отказать, ничего не тронув."""
    proj = _proj()
    tmp = STATE['tmp']
    out_dir, rtmp, lock = tmp / 'locked', tmp / 'render-tmp', tmp / 'gate-lock'
    env = {chrome_lock.ENV_PATH: str(lock), chrome_lock.ENV_TIMEOUT: '3'}
    args = ['tiny', '--png', '--frames', 3, '--project', proj, '--out-dir', out_dir, '--tmp', rtmp]

    def call(extra, gate=None):
        e = dict(os.environ, **env)
        e.pop('MOTION_PROJECT', None)
        e.pop(chrome_lock.ENV_HELD, None)          # своя папка замка: ребёнок берёт и ждёт её сам
        p = subprocess.Popen([PY, str(BUILD)] + [str(a) for a in args + extra], stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace', env=e)
        if gate:
            gate(p)
        text = p.communicate(timeout=900)[0]
        return p.returncode, text

    def state():
        files = sorted(p for p in out_dir.rglob('*') if p.is_file() and 'frames' in p.relative_to(out_dir).parts)
        return [(p.relative_to(out_dir).as_posix(), p.stat().st_size, p.stat().st_mtime_ns) for p in files]

    with chrome_lock.held('test_render.py: замок на время теста'):      # настоящий замок машины — у теста
        code, out = call([])
        check(code == 0 and len(list(out_dir.rglob('frame_*.png'))) == 3, 'первый рендер трёх кадров упал: %s' % out[-900:])
        before, t0 = state(), time.time()
        probe = out_dir / 'probe.json'

        def gate(p):          # как только страница промерена заново — занять замок раньше рендера
            def run():
                while p.poll() is None:
                    if probe.exists() and probe.stat().st_mtime > t0:
                        break
                    time.sleep(0.002)
                while p.poll() is None:
                    try:
                        os.mkdir(lock)
                    except OSError:
                        continue
                    (lock / 'owner.json').write_text(json.dumps(
                        {'pid': os.getpid(), 'label': 'test_render.py gate', 'since': time.time(), 'token': 'gate',
                         'exe': os.path.basename(sys.executable)}), encoding='utf-8')
                    break
            threading.Thread(target=run, daemon=True).start()
        try:
            code, out = call(['--force'], gate)
        finally:
            shutil.rmtree(lock, ignore_errors=True)
    check(code != 0 and 'test_render.py gate' in out, 'рендер не отказал по занятому замку с именем владельца: код %d, %s' % (code, out[-600:]))
    check('Traceback' not in out, 'отказ по замку — трассировкой, а не строкой: %s' % out[-600:])
    check(state() == before, 'истёкшее ожидание замка изменило кадры или отметки в выходной папке')
    left = [p.name for p in rtmp.iterdir()] if rtmp.exists() else []
    check(not left, 'после отказа по замку осталась временная папка рендера: %s' % left)
    check(not list(out_dir.rglob('*.mp4')), 'после отказа по замку в выходной папке появился mp4 (кодировщик запущен до замка)')


def test_auto_workers_follow_cores_and_memory():
    """Правило задания: число воркеров — по ядрам и памяти; значения — свойства правила, не его формула."""
    sys.path.insert(0, str(VIDEO))
    import build
    gb = 1e9
    check(build.auto_workers(1, 64 * gb) == 1, 'на одном ядре воркеров не один')
    check(build.auto_workers(12, 64 * gb) > 3, 'на 12 ядрах при свободной памяти — не больше прежних трёх воркеров')
    check(build.auto_workers(12, 64 * gb) <= 12, 'воркеров больше, чем ядер')
    check(build.auto_workers(24, 64 * gb) >= build.auto_workers(12, 64 * gb), 'больше ядер — меньше воркеров')
    check(build.auto_workers(12, 2 * gb) < build.auto_workers(12, 64 * gb), 'мало свободной памяти число воркеров не уменьшило')
    check(build.auto_workers(12, 0.1 * gb) == 1, 'при 100 МБ свободной памяти воркеров не один')


def test_cleanup():
    if STATE.get('tmp'):
        shutil.rmtree(STATE['tmp'], ignore_errors=True)


if __name__ == '__main__':
    sys.exit(run_module(globals()))
