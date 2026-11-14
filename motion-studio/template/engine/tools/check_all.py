# -*- coding: utf-8 -*-
"""Одна команда проверки проекта ролика: тесты движка + сборка и проверка каждого фильма проекта + склейки.

    python engine/tools/check_all.py             всё, кроме самого долгого (см. ниже)
    python engine/tools/check_all.py --quick     быстрый круг: без медленных тестов, без --red-slow, без фильмов
                                                 с проходами по стилям
    python engine/tools/check_all.py --full      ещё порчи и образцы стилей (styles --red, --samples: ≈ 15 мин)
    python engine/tools/check_all.py --films a,b только эти фильмы (тесты и остальное — как обычно)
    python engine/tools/check_all.py --list      показать шаги и не запускать
    --project DIR   корень проекта: --project → MOTION_PROJECT → <шаблон>/project (engine/project_root.py)

Список шагов строится из конфигов проекта, а не зашит в код:
  фильмы     каждый <проект>/films/*.json: build.py <фильм> --page и check.py <фильм> --page (фильм с "styles" —
             все его проходы); порчи и образцы (--red, --samples, --red-slow) — у фильма, для которого они
             калиброваны: есть engine/video/checks/red_<фильм>.py, либо это демо шаблона (red_demo.py);
  склейки    каждый лист <проект>/montage.json: assemble.py <лист> --check — если кадры его кусков отрендерены,
             иначе SKIP с командой рендера;
  звук       линт текста до синтеза (speech_lint.py); промер голоса (check_audio.py) — если есть манифест озвучки;
             проверка микса (check_mix.py <фильм>) — если микс фильма сведён;
  свои шаги  project.json "check_all": [{"name": "…", "cmd": ["scenes/_checks/red.py", "--out", "out/film"],
             "needs": ["out/film/probe.json"], "slow": false}] — порчи сцен и другие проверки проекта; cmd —
             скрипт Python от корня проекта и его аргументы; needs — входы, без которых шаг печатает SKIP.

Шаг, которому нужны входы, которых на чистой машине может не быть (озвучка, микс, кадры), без них печатает SKIP с
причиной и прогон не роняет. Весь прогон идёт под замком Chrome (engine/chrome_lock.py): второй такой запуск ждёт.
Кадры кусков (out/<фильм>/frames) прогон не трогает: пересборка страницы их не удаляет, годятся ли они — решает
отметка (engine/video/stamp.py). Код выхода 0 — всё зелёное; 1 — хоть что-то красное (список в конце).
"""
import json
import os
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')
sys.dont_write_bytecode = True
ENGINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))        # <проект>/engine
sys.path.insert(0, ENGINE)
sys.path.insert(0, os.path.join(ENGINE, 'video'))
import chrome_lock    # noqa: E402
import project_root   # noqa: E402
import stamp          # noqa: E402

PY = sys.executable
V = os.path.join(ENGINE, 'video')
FAST_TESTS = [os.path.join(ENGINE, 'tests', 'test_chrome_lock.py'), os.path.join(ENGINE, 'tests', 'test_resources.py'),
              os.path.join(V, 'tests', 'test_assemble.py'), os.path.join(ENGINE, 'tests', 'test_check_all.py'),
              os.path.join(V, 'tests', 'test_wallclock.py')]
SLOW_TESTS = [os.path.join(V, 'tests', 'test_pieces.py'), os.path.join(V, 'tests', 'test_pose.py'),
              os.path.join(V, 'tests', 'test_start_frame.py'),
              os.path.join(V, 'tests', 'test_project.py'), os.path.join(ENGINE, 'tts', 'tests', 'test_tts.py'),
              os.path.join(ENGINE, 'audio', 'tests', 'test_audio.py')]
DEMO, STYLES = 'demo', 'styles'      # фильмы шаблона с калиброванными порчами: checks/red_demo.py, checks/red_styles.py


def load_json(p):
    with open(p, encoding='utf-8-sig') as fh:
        return json.load(fh)


def films_of(root, pj):
    d = os.path.join(root, (pj.get('paths') or {}).get('films', 'films'))
    return sorted(f[:-5] for f in os.listdir(d) if f.endswith('.json')) if os.path.isdir(d) else []


def film_def(root, pj, film):
    return load_json(os.path.join(root, (pj.get('paths') or {}).get('films', 'films'), film + '.json'))


def calibrated(root, pj, film):
    """Порчи фильма калиброваны: свой модуль checks/red_<фильм>.py или демо шаблона (сцены demo-a, demo-b)."""
    if os.path.exists(os.path.join(V, 'checks', 'red_%s.py' % film)):
        return True
    return film == DEMO and film_def(root, pj, film).get('scenes') == ['demo-a', 'demo-b']


def step(name, cmd, needs=None, why=None, slow=False):
    return {'name': name, 'cmd': cmd, 'needs': needs or [], 'why': why, 'slow': slow}


def test_step(path, slow=False):
    return step('тест ' + os.path.basename(path), [PY, path], needs=[path], why='теста нет в этом движке', slow=slow)


def steps(root, quick=False, full=False, only_films=None):
    """Шаги прогона для проекта root — из его конфигов. quick — без медленного; full — ещё порчи стилей."""
    pj = load_json(os.path.join(root, 'project.json'))
    out_root = os.path.join(root, pj['paths']['out'])
    proj = ['--project', root]
    out = [test_step(t) for t in FAST_TESTS]
    out.append(step('схема раскадровки: порчи', [PY, os.path.join(V, 'storyboard.py'), '--red'] + proj))
    out.append(step('текст в синтез: линт', [PY, os.path.join(ENGINE, 'tts', 'speech_lint.py')] + proj,
                    needs=[os.path.join(root, 'rows.json')], why='нет rows.json — нарезки ещё нет'))
    manifest = os.path.join(root, pj['paths'].get('voices_out', 'out/tts'), 'manifest.json')
    out.append(step('озвучка: промер после синтеза', [PY, os.path.join(ENGINE, 'tts', 'check_audio.py')] + proj,
                    needs=[manifest], why='нет манифеста озвучки — синтеза ещё не было'))
    films = films_of(root, pj)
    if only_films is not None:
        lost = [f for f in only_films if f not in films]
        if lost:
            raise SystemExit('фильмов %s нет в проекте (есть: %s)' % (', '.join(lost), ', '.join(films) or '—'))
        films = [f for f in films if f in only_films]
    for film in films:
        fd = film_def(root, pj, film)
        passes = bool(fd.get('styles'))
        if quick and passes:
            out.append(step('%s: фильм с проходами по стилям' % film, None, why='пропущен в --quick (проходов: %d)' % len(fd['styles'])))
            continue
        out.append(step('%s: сборка --page' % film, [PY, os.path.join(V, 'build.py'), film, '--page'] + proj))
        out.append(step('%s: проверка --page' % film, [PY, os.path.join(V, 'check.py'), film, '--page'] + proj))
        if calibrated(root, pj, film):
            long = film == STYLES
            if not long or full:
                out.append(step('%s: порчи --red' % film, [PY, os.path.join(V, 'check.py'), film, '--red'] + proj))
                out.append(step('%s: образцы --samples' % film, [PY, os.path.join(V, 'check.py'), film, '--samples'] + proj))
            else:
                out.append(step('%s: порчи и образцы стилей' % film, None, why='долго (≈ 15 мин) — только с --full'))
            if not quick:
                out.append(step('%s: медленные порчи --red-slow' % film, [PY, os.path.join(V, 'check.py'), film, '--red-slow'] + proj,
                                slow=True))
        else:
            out.append(step('%s: порчи' % film, None, why='не калиброваны: нет engine/video/checks/red_%s.py; порчи сцен — '
                                                          'шагами project.json "check_all"' % film))
        mix = os.path.join(out_root, film, 'mix.m4a')
        out.append(step('%s: проверка микса' % film, [PY, os.path.join(ENGINE, 'audio', 'check_mix.py'), film] + proj,
                        needs=[mix], why='микс не сведён (engine/audio/music.py %s)' % film))
    mp = os.path.join(root, pj['paths'].get('montage', 'montage.json'))
    if os.path.exists(mp):
        for name, sheet in load_json(mp).items():
            if name.startswith('_'):
                continue
            lost = []
            for pc in sheet.get('pieces') or []:
                if 'film' in pc:
                    d = os.path.join(out_root, pc['film'], pc['style']) if pc.get('style') else os.path.join(out_root, pc['film'])
                    if not stamp.frames_on_disk(d):
                        lost.append('build.py %s --png' % pc['film'])
            sil = [] if sheet.get('audio') else ['--silent']
            cmd = None if lost else [PY, os.path.join(V, 'assemble.py'), name, '--check'] + sil + proj
            out.append(step('склейка %s: сухой прогон' % name, cmd,
                            why='кадры кусков не отрендерены: ' + '; '.join(lost) if lost else None))
    for k, own in enumerate(pj.get('check_all') or []):
        if not isinstance(own, dict) or not own.get('name') or not isinstance(own.get('cmd'), list) or not own['cmd']:
            raise SystemExit('project.json check_all[%d]: нужны {"name": "…", "cmd": ["<скрипт от корня проекта>", …], '
                             '"needs"?: [...], "slow"?: bool}' % k)
        if quick and own.get('slow'):
            out.append(step(own['name'], None, why='медленный шаг проекта — пропущен в --quick'))
            continue
        out.append(step(own['name'], [PY, os.path.join(root, own['cmd'][0])] + [str(a) for a in own['cmd'][1:]],
                        needs=[os.path.join(root, n) for n in own.get('needs') or []], why='нет входов шага',
                        slow=bool(own.get('slow'))))
    if not quick:
        out += [test_step(t, slow=True) for t in SLOW_TESTS]
    return out


def missing(st):
    return [n for n in st['needs'] if not os.path.exists(n)]


def main(argv):
    root, argv = project_root.split_argv(argv)
    root = str(root)
    quick, full, listing = '--quick' in argv, '--full' in argv, '--list' in argv
    only = None
    if '--films' in argv:
        i = argv.index('--films')
        if i + 1 >= len(argv):
            raise SystemExit('после --films нужен список фильмов через запятую')
        only = [x.strip() for x in argv[i + 1].split(',') if x.strip()]
    plan = steps(root, quick=quick, full=full, only_films=only)
    if listing:
        for st in plan:
            lost = missing(st)
            mark = 'SKIP' if st['cmd'] is None or lost else 'шаг '
            print('%s %-46s %s' % (mark, st['name'], st['why'] if mark == 'SKIP' and st['why'] else ''))
        print('шагов: %d (проект %s)' % (len(plan), root))
        return 0
    t0 = time.time()
    bad = []
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    env.pop(project_root.ENV, None)
    cwd = os.path.dirname(ENGINE)
    with chrome_lock.held('engine/tools/check_all.py'):
        env[chrome_lock.ENV_HELD] = os.environ[chrome_lock.ENV_HELD]
        for st in plan:
            lost = missing(st)
            if st['cmd'] is None or lost:
                print('SKIP %-46s        %s' % (st['name'], st['why'] or 'нет: ' + ', '.join(lost)), flush=True)
                continue
            ts = time.time()
            r = subprocess.run(st['cmd'], cwd=cwd, capture_output=True, text=True, encoding='utf-8', errors='replace', env=env)
            tail = [l for l in (r.stdout + r.stderr).splitlines() if l.strip() and not l.startswith('frame=')]
            mark = 'ok  ' if r.returncode == 0 else 'FAIL'
            print('%s %-46s %5.0f с  %s' % (mark, st['name'], time.time() - ts, (tail[-1] if tail else '')[:150]), flush=True)
            if r.returncode:
                bad.append(st['name'])
                for l in [l for l in tail if l.lstrip().startswith(('FAIL', 'MISS'))][:12]:
                    print('       ' + l[:220])
    print('итог: %s · %.0f с' % ('зелёный' if not bad else 'КРАСНЫЙ: ' + ', '.join(bad), time.time() - t0))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
