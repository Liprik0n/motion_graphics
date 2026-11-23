# -*- coding: utf-8 -*-
"""Одна команда проверки проекта ролика: свои тесты проекта + сборка и проверка каждого его фильма + склейки.

    python engine/tools/check_all.py             всё, кроме самого долгого (см. ниже)
    python engine/tools/check_all.py --quick     быстрый круг: без тестов с браузером, без --red-slow, без фильмов
                                                 с проходами по стилям
    python engine/tools/check_all.py --full      ещё порчи и образцы стилей (styles --red, --samples: ≈ 15 мин)
    python engine/tools/check_all.py --films a,b только эти фильмы (тесты и остальное — как обычно)
    python engine/tools/check_all.py --engine    ещё самотесты движка (engine/**/test_*.py, порчи схемы раскадровки)
    python engine/tools/check_all.py --list      показать шаги и не запускать
    --project DIR   корень проекта: --project → MOTION_PROJECT → <шаблон>/project (engine/project_root.py)

Список шагов строится из проекта, а не зашит в код:
  тесты      каждый test_*.py под корнем проекта (обходом; папки out, node_modules, __pycache__ и скрытые — мимо).
             Тест, которому нужен браузер, объявляет в файле строку `NEEDS_CHROME = True`: такой шаг идёт под
             замком Chrome и не входит в --quick. Регистрировать тест нигде не надо;
  фильмы     каждый <проект>/films/*.json: build.py <фильм> --page и check.py <фильм> --page (фильм с "styles" —
             все его проходы); порчи и образцы (--red, --samples, --red-slow) — у фильма, для которого они
             калиброваны: есть engine/video/checks/red_<фильм>.py, либо это демо шаблона (red_demo.py);
  склейки    каждый лист <проект>/montage.json: assemble.py <лист> --check — если кадры его кусков отрендерены,
             иначе SKIP с командой рендера;
  материалы  check_materials.py: у каждого файла в assets/ строка с источником и лицензией — если есть assets/;
  звук       линт текста до синтеза (speech_lint.py); промер голоса (check_audio.py) — если есть манифест озвучки;
             проверка микса (check_mix.py <фильм>) — если микс фильма сведён;
  свои шаги  project.json "check_all": [{"name": "…", "cmd": ["scenes/_checks/red.py", "--out", "out/film"],
             "needs": ["out/film/probe.json"], "slow": false, "chrome": false}] — порчи сцен и другие проверки
             проекта; cmd — скрипт Python от корня проекта и его аргументы; needs — входы, без которых шаг
             печатает SKIP; "chrome": true — шаг сам запускает браузер, взять на него замок.

Самотесты движка и фильмы-фикстуры шаблона в прогон проекта не входят: движок проверяет скил
(`<скил>/tools/check_skill.py`), проект — только своё. --engine добавляет самотесты движка тому, кто правит
движок в своей копии.

Шаг, которому нужны входы, которых на чистой машине может не быть (озвучка, микс, кадры), без них печатает SKIP с
причиной и прогон не роняет. Замок Chrome (engine/chrome_lock.py) берётся только на шагах с браузером — сборка
страницы, медленные порчи, тесты с NEEDS_CHROME; между ними замок свободен, и ждать его дольше предела прогон не
станет: выйдет строкой «кто держит». Кадры кусков (out/<фильм>/frames) прогон не трогает: пересборка страницы их не
удаляет, годятся ли они — решает отметка (engine/video/stamp.py). Код выхода 0 — всё зелёное; 1 — хоть что-то
красное (список в конце); 2 — не хватает программы или пакета (названо, чем поставить).
"""
import json
import os
import re
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
import deps           # noqa: E402
import project_root   # noqa: E402
import stamp          # noqa: E402

PY = sys.executable
V = os.path.join(ENGINE, 'video')
TEST_RE = re.compile(r'^test_.*\.py$')
NEEDS_CHROME_RE = re.compile(r'^NEEDS_CHROME\s*=\s*True\b', re.M)     # строка в файле теста: ему нужен браузер
WALK_SKIP = ('out', 'node_modules', '__pycache__')                     # выход сборки, чужой набор, кэш — не тесты
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


def find_tests(root):
    """Тесты под папкой root — обходом, по порядку путей: [(путь к test_*.py, нужен ли ему браузер)].
    Браузер нужен тесту, в файле которого есть строка `NEEDS_CHROME = True`."""
    out = []
    for dirpath, dirs, files in os.walk(str(root)):
        dirs[:] = sorted(d for d in dirs if d not in WALK_SKIP and not d.startswith('.'))
        for name in sorted(files):
            if TEST_RE.match(name):
                p = os.path.join(dirpath, name)
                with open(p, encoding='utf-8-sig', errors='replace') as fh:
                    out.append((p, bool(NEEDS_CHROME_RE.search(fh.read()))))
    return out


def step(name, cmd, needs=None, why=None, slow=False, chrome=False):
    """Шаг прогона. chrome — шаг запускает безголовый браузер: на него берётся замок."""
    return {'name': name, 'cmd': cmd, 'needs': needs or [], 'why': why, 'slow': slow, 'chrome': chrome}


def test_steps(root, quick=False):
    """Шаги тестов, найденных под root: сначала без браузера, потом с ним (в --quick тесты с браузером — SKIP)."""
    found = find_tests(root)
    out = []
    for path, chrome in sorted(found, key=lambda t: t[1]):
        name = 'тест ' + os.path.relpath(path, str(root)).replace(os.sep, '/')
        if chrome and quick:
            out.append(step(name, None, why='тест с браузером — пропущен в --quick', chrome=True))
        else:
            out.append(step(name, [PY, path], slow=chrome, chrome=chrome))
    return out


def engine_steps(root, quick=False):
    """Самотесты движка: его test_*.py и порчи с образцами проверяльщиков, которым не нужен браузер (схема
    раскадровки, линт текста, промер голоса). В прогон проекта входят только по --engine."""
    proj = ['--project', str(root)]
    out = test_steps(ENGINE, quick=quick)
    out.append(step('схема раскадровки: порчи', [PY, os.path.join(V, 'storyboard.py'), '--red'] + proj))
    for label, script in (('линт текста', 'speech_lint.py'), ('промер голоса', 'check_audio.py')):
        for kind, flag in (('порчи', '--red'), ('образцы', '--samples')):
            out.append(step('%s: %s' % (label, kind), [PY, os.path.join(ENGINE, 'tts', script), flag] + proj))
    return out


def steps(root, quick=False, full=False, only_films=None, engine=False):
    """Шаги прогона для проекта root — из его конфигов и файлов. quick — без медленного; full — ещё порчи стилей;
    engine — ещё самотесты движка."""
    root = str(root)
    pj = load_json(os.path.join(root, 'project.json'))
    out_root = os.path.join(root, pj['paths']['out'])
    proj = ['--project', root]
    tests = test_steps(root, quick=quick)
    out = [t for t in tests if not t['chrome']]
    out.append(step('текст в синтез: линт', [PY, os.path.join(ENGINE, 'tts', 'speech_lint.py')] + proj,
                    needs=[os.path.join(root, 'rows.json')], why='нет rows.json — нарезки ещё нет'))
    out.append(step('материалы: источники и лицензии', [PY, os.path.join(ENGINE, 'tools', 'check_materials.py')] + proj,
                    needs=[os.path.join(root, 'assets')], why='нет папки assets/ — чужих материалов ещё нет'))
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
        out.append(step('%s: сборка --page' % film, [PY, os.path.join(V, 'build.py'), film, '--page'] + proj, chrome=True))
        # проверка страницы при первом запуске на ней снимает кадры для V36 и V37 (Chrome): шаг с браузером;
        # замок один — вложенный held в check.py и strip.py видит замок предка и второй раз его не берёт
        out.append(step('%s: проверка --page' % film, [PY, os.path.join(V, 'check.py'), film, '--page'] + proj, chrome=True))
        if calibrated(root, pj, film):
            long = film == STYLES
            if not long or full:
                out.append(step('%s: порчи --red' % film, [PY, os.path.join(V, 'check.py'), film, '--red'] + proj))
                out.append(step('%s: образцы --samples' % film, [PY, os.path.join(V, 'check.py'), film, '--samples'] + proj))
            else:
                out.append(step('%s: порчи и образцы стилей' % film, None, why='долго (≈ 15 мин) — только с --full'))
            if not quick:
                out.append(step('%s: медленные порчи --red-slow' % film, [PY, os.path.join(V, 'check.py'), film, '--red-slow'] + proj,
                                slow=True, chrome=True))
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
                             '"needs"?: [...], "slow"?: bool, "chrome"?: bool}' % k)
        if quick and own.get('slow'):
            out.append(step(own['name'], None, why='медленный шаг проекта — пропущен в --quick'))
            continue
        out.append(step(own['name'], [PY, os.path.join(root, own['cmd'][0])] + [str(a) for a in own['cmd'][1:]],
                        needs=[os.path.join(root, n) for n in own.get('needs') or []], why='нет входов шага',
                        slow=bool(own.get('slow')), chrome=bool(own.get('chrome'))))
    out += [t for t in tests if t['chrome']]
    if engine:
        out += engine_steps(root, quick=quick)
    return out


def missing(st):
    return [n for n in st['needs'] if not os.path.exists(n)]


def runnable(st):
    return st['cmd'] is not None and not missing(st)


def print_plan(plan):
    for st in plan:
        if runnable(st):
            print('шаг  %-46s %s' % (st['name'], 'под замком Chrome' if st['chrome'] else ''))
        else:
            print('SKIP %-46s %s' % (st['name'], st['why'] or ''))


def run_plan(plan, cwd):
    """Исполнить шаги по порядку; вернуть имена красных. Замок Chrome — только вокруг шага с браузером; не дождались
    его за предел — строка «кто держит», шаг красный, прогон остановлен."""
    bad = []
    base = dict(os.environ, PYTHONIOENCODING='utf-8')
    base.pop(project_root.ENV, None)
    for st in plan:
        lost = missing(st)
        if st['cmd'] is None or lost:
            print('SKIP %-46s        %s' % (st['name'], st['why'] or 'нет: ' + ', '.join(lost)), flush=True)
            continue
        ts = time.time()
        try:
            if st['chrome']:
                with chrome_lock.held('check_all: %s' % st['name']):
                    r = _run(st, cwd, dict(base, **{chrome_lock.ENV_HELD: os.environ[chrome_lock.ENV_HELD]}))
            else:
                r = _run(st, cwd, base)
        except chrome_lock.LockTimeout as e:
            print('FAIL %-46s %5.0f с  ОШИБКА: %s' % (st['name'], time.time() - ts, e), flush=True)
            bad.append(st['name'])
            print('прогон остановлен: шагам с браузером нужен замок Chrome', flush=True)
            break
        tail = [l for l in (r.stdout + r.stderr).splitlines() if l.strip() and not l.startswith('frame=')]
        mark = 'ok  ' if r.returncode == 0 else 'FAIL'
        print('%s %-46s %5.0f с  %s' % (mark, st['name'], time.time() - ts, (tail[-1] if tail else '')[:150]), flush=True)
        if r.returncode:
            bad.append(st['name'])
            for l in [l for l in tail if l.lstrip().startswith(('FAIL', 'MISS', 'ОШИБКА', 'нет:'))][:12]:
                print('       ' + l[:220])
    return bad


def _run(st, cwd, env):
    return subprocess.run(st['cmd'], cwd=cwd, capture_output=True, text=True, encoding='utf-8', errors='replace', env=env)


def preflight(plan):
    """Чего не хватает шагам плана: [(имя, команда)] — пакеты Python всем, Node, набор Node и Chrome шагам с браузером."""
    return deps.missing(chrome=any(st['chrome'] and runnable(st) for st in plan))


def main(argv):
    root, argv = project_root.split_argv(argv)
    root = str(root)
    quick, full, listing, engine = '--quick' in argv, '--full' in argv, '--list' in argv, '--engine' in argv
    only = None
    if '--films' in argv:
        i = argv.index('--films')
        if i + 1 >= len(argv):
            raise SystemExit('после --films нужен список фильмов через запятую')
        only = [x.strip() for x in argv[i + 1].split(',') if x.strip()]
    plan = steps(root, quick=quick, full=full, only_films=only, engine=engine)
    if listing:
        print_plan(plan)
        print('шагов: %d (проект %s)' % (len(plan), root))
        return 0
    lost = preflight(plan)
    if lost:
        print('ОШИБКА: прогону не хватает программ\n  ' + '\n  '.join(deps.report(lost)))
        return 2
    t0 = time.time()
    bad = run_plan(plan, os.path.dirname(ENGINE))
    print('итог: %s · %.0f с' % ('зелёный' if not bad else 'КРАСНЫЙ: ' + ', '.join(bad), time.time() - t0))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
