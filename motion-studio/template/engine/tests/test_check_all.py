# -*- coding: utf-8 -*-
"""Общий прогон engine/tools/check_all.py строит шаги из конфигов проекта, а не из имён сцен чужого ролика.

    python engine/tests/test_check_all.py

Ожидания — из задания шаблона («список шагов строится из конфигов проекта») и правил скила (process/08-render-qa.md):
  - у каждого фильма проекта (films/*.json) есть сборка --page и проверка --page; чужих фильмов в плане нет;
  - порчи --red и --samples идут только у фильма с калиброванными порчами; у остальных — SKIP с причиной;
  - --quick пропускает фильм с проходами по стилям и медленные тесты;
  - лист склейки без отрендеренных кадров — SKIP с командой рендера, с кадрами — сухой прогон assemble.py --check;
  - свои шаги проекта (project.json "check_all") попадают в план; медленный — не в --quick;
  - план не содержит команды, которая удаляет кадры кусков.
Из задания:
  - тесты находятся обходом: test_*.py под корнем проекта; тест с NEEDS_CHROME = True — шаг с браузером и не идёт
    в --quick; списков FAST_TESTS / SLOW_TESTS нет; папки out и node_modules не обходятся;
  - самотесты движка (engine/**/test_*.py, порчи схемы раскадровки) в проектный прогон не входят — только по --engine;
  - замок Chrome берётся только на шагах с браузером: прогон без таких шагов не ждёт чужой замок вовсе;
  - не дождавшись замка, прогон выходит одной строкой с меткой и pid владельца, без трассировки.
Chrome не нужен: план строится и печатается (--list); запускаются только шаги-пустышки без браузера.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import ENGINE, PY, check, run_module   # noqa: E402

sys.path.insert(0, str(ENGINE / 'tools'))
TOOL = ENGINE / 'tools' / 'check_all.py'


def _project(tmp, frames=False):
    proj = os.path.join(tmp, 'project')
    os.makedirs(os.path.join(proj, 'films'))
    pj = {'fps': 30, 'canvas': {'w': 320, 'h': 180, 'px_per_in': 96}, 'paths': {'out': 'out', 'voices_out': 'out/tts'},
          'check_all': [{'name': 'порчи сцены intro', 'cmd': ['scenes/_checks/red_intro.py', '--out', 'out/intro'], 'needs': ['scenes/_checks/red_intro.py']},
                        {'name': 'долгий свой шаг', 'cmd': ['scenes/_checks/long.py'], 'slow': True}]}
    json.dump(pj, open(os.path.join(proj, 'project.json'), 'w', encoding='utf-8'))
    json.dump({'scenes': ['i1', 'i2']}, open(os.path.join(proj, 'films', 'intro.json'), 'w', encoding='utf-8'))
    json.dump({'scenes': ['f1']}, open(os.path.join(proj, 'films', 'final.json'), 'w', encoding='utf-8'))
    json.dump({'scenes': ['p1'], 'styles': ['none', 'film']}, open(os.path.join(proj, 'films', 'looks.json'), 'w', encoding='utf-8'))
    json.dump({'_comment': 'тест', 'clip': {'pieces': [{'film': 'intro'}, {'film': 'final'}]}},
              open(os.path.join(proj, 'montage.json'), 'w', encoding='utf-8'))
    if frames:
        for film in ('intro', 'final'):
            d = os.path.join(proj, 'out', film, 'frames')
            os.makedirs(d)
            open(os.path.join(d, 'frame_000001.png'), 'wb').write(b'x')
    # свои тесты проекта: обычный, с браузером, и два, которые обход не должен видеть (выход сборки, чужой набор)
    for rel, body in (('checks/test_own.py', 'print("ok")\n'),
                      ('checks/test_browser.py', '"""Нужен браузер."""\nNEEDS_CHROME = True\nprint("ok")\n'),
                      ('out/intro/test_leftover.py', 'raise SystemExit(1)\n'),
                      ('node_modules/pkg/test_pkg.py', 'raise SystemExit(1)\n')):
        p = os.path.join(proj, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, 'w', encoding='utf-8').write(body)
    return proj


def _bare_project(tmp, own):
    """Проект без фильмов: в плане только свои шаги own — чтобы запустить прогон без браузера."""
    proj = os.path.join(tmp, 'project')
    os.makedirs(proj)
    json.dump({'fps': 30, 'canvas': {'w': 320, 'h': 180, 'px_per_in': 96}, 'paths': {'out': 'out', 'voices_out': 'out/tts'},
               'check_all': own}, open(os.path.join(proj, 'project.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    open(os.path.join(proj, 'step.py'), 'w', encoding='utf-8').write('print("step done")\n')
    return proj


def _held_by_live(tmp):
    """Замок Chrome, который держит живой процесс (этот тест)."""
    lock = os.path.join(tmp, 'lock')
    os.makedirs(lock)
    owner = {'pid': os.getpid(), 'label': 'чужой рендер', 'since': time.time(), 'token': 'test'}
    json.dump(owner, open(os.path.join(lock, 'owner.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    env = dict(os.environ, MOTION_CHROME_LOCK=lock, MOTION_CHROME_LOCK_TIMEOUT='1', PYTHONIOENCODING='utf-8')
    env.pop('MOTION_CHROME_LOCK_HELD', None)
    env.pop('MOTION_PROJECT', None)
    return owner, env


def _plan(proj, **kw):
    import check_all
    return check_all.steps(proj, **kw)


def _names(plan, runnable=None):
    return [s['name'] for s in plan if runnable is None or (s['cmd'] is not None) == runnable]


def _tmp():
    return tempfile.mkdtemp(prefix='check_all_test_')


def test_films_come_from_project():
    tmp = _tmp()
    try:
        plan = _plan(_project(tmp))
        run = _names(plan, True)
        for film in ('intro', 'final', 'looks'):
            check('%s: сборка --page' % film in run and '%s: проверка --page' % film in run, 'у фильма %s нет сборки и проверки: %s' % (film, run))
        cmds = ' '.join(' '.join(s['cmd']) for s in plan if s['cmd'])
        for alien in ('demo', 'styles', 'kits'):
            check(' %s ' % alien not in cmds, 'в плане чужой фильм «%s», которого нет в films/ проекта' % alien)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_porches_only_for_calibrated_film():
    tmp = _tmp()
    try:
        plan = _plan(_project(tmp))
        check(not [n for n in _names(plan, True) if '--red' in n or '--samples' in n], 'порчи запущены у некалиброванного фильма')
        skipped = [s for s in plan if s['cmd'] is None and s['name'] == 'intro: порчи']
        check(skipped and 'red_intro.py' in skipped[0]['why'], 'нет SKIP с причиной у порч фильма intro')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_quick_skips_style_passes_and_slow():
    tmp = _tmp()
    try:
        proj = _project(tmp)
        quick, usual = _plan(proj, quick=True), _plan(proj)
        check('looks: сборка --page' not in _names(quick, True), '--quick собирает фильм с проходами по стилям')
        check('looks: сборка --page' in _names(usual, True), 'обычный прогон не собирает фильм с проходами')
        check(not [n for n in _names(quick, True) if 'test_browser' in n], '--quick гоняет тест с браузером')
        check([n for n in _names(usual, True) if 'test_browser' in n], 'обычный прогон без теста с браузером')
        check([n for n in _names(quick, True) if 'test_own' in n], '--quick потерял быстрый тест проекта')
        check('долгий свой шаг' not in _names(quick, True) and 'долгий свой шаг' in _names(usual, True), 'медленный шаг проекта и --quick')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_montage_needs_rendered_frames():
    tmp = _tmp()
    try:
        plan = _plan(_project(tmp))
        st = [s for s in plan if s['name'] == 'склейка clip: сухой прогон'][0]
        check(st['cmd'] is None and 'build.py intro --png' in st['why'] and 'build.py final --png' in st['why'],
              'без кадров склейка не названа SKIP с командами рендера: %s' % st)
        plan = _plan(_project(os.path.join(tmp, 'b'), frames=True))
        st = [s for s in plan if s['name'] == 'склейка clip: сухой прогон'][0]
        check(st['cmd'] and 'assemble.py' in ' '.join(st['cmd']) and '--check' in st['cmd'], 'с кадрами нет сухого прогона склейки: %s' % st)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_own_steps_of_project():
    tmp = _tmp()
    try:
        proj = _project(tmp)
        st = [s for s in _plan(proj) if s['name'] == 'порчи сцены intro'][0]
        check(st['cmd'][1] == os.path.join(proj, 'scenes/_checks/red_intro.py') and st['cmd'][2:] == ['--out', 'out/intro'],
              'свой шаг проекта не собран из project.json check_all: %s' % st['cmd'])
        check(st['needs'] == [os.path.join(proj, 'scenes/_checks/red_intro.py')], 'needs шага — пути от корня проекта')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_only_films_and_unknown():
    tmp = _tmp()
    try:
        proj = _project(tmp)
        run = _names(_plan(proj, only_films=['final']), True)
        check('final: сборка --page' in run and 'intro: сборка --page' not in run, '--films не сузил план: %s' % run)
        r = subprocess.run([PY, str(TOOL), '--project', proj, '--films', 'net-takogo', '--list'], capture_output=True, text=True,
                           encoding='utf-8', errors='replace')
        check(r.returncode != 0 and 'intro' in (r.stdout + r.stderr), 'неизвестный фильм: отказ не называет фильмы проекта')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_list_runs_nothing_and_never_deletes_frames():
    tmp = _tmp()
    try:
        proj = _project(tmp, frames=True)
        r = subprocess.run([PY, str(TOOL), '--project', proj, '--list'], capture_output=True, text=True, encoding='utf-8', errors='replace')
        out = r.stdout + r.stderr
        check(r.returncode == 0 and 'intro: сборка --page' in out and 'шагов:' in out, '--list не напечатал план: %s' % out[-400:])
        check(os.path.exists(os.path.join(proj, 'out', 'intro', 'frames', 'frame_000001.png')), '--list тронул кадры')
        check(not os.path.exists(os.path.join(proj, 'out', 'intro', 'film.json')), '--list что-то собрал')
        text = TOOL.read_text(encoding='utf-8')
        check('rmtree' not in text and "'frames')" not in text.replace("frames_on_disk", ''), 'общий прогон сам удаляет что-то или лезет в frames/')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_tests_are_found_by_walk():
    import check_all
    check(not hasattr(check_all, 'FAST_TESTS') and not hasattr(check_all, 'SLOW_TESTS'), 'списки FAST_TESTS / SLOW_TESTS остались')
    tmp = _tmp()
    try:
        proj = _project(tmp, frames=True)
        found = {os.path.relpath(p, proj).replace(os.sep, '/'): chrome for p, chrome in check_all.find_tests(proj)}
        check(found == {'checks/test_own.py': False, 'checks/test_browser.py': True},
              'обход нашёл не те тесты (out/ и node_modules — не тесты проекта): %s' % found)
        steps = {s['name']: s for s in _plan(proj)}
        own = [s for n, s in steps.items() if 'test_own.py' in n]
        browser = [s for n, s in steps.items() if 'test_browser.py' in n]
        check(own and browser, 'тесты проекта не попали в план: %s' % sorted(steps))
        check(own[0]['chrome'] is False and browser[0]['chrome'] is True, 'NEEDS_CHROME не стал отметкой шага с браузером')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_materials_step_when_project_has_assets():
    """Из задания роли: у каждого чужого материала строка с источником и лицензией — шаг check_materials.py в проектном прогоне.
    Без папки assets/ проверять нечего: шаг пропускается с причиной, а не краснеет."""
    tmp = _tmp()
    try:
        proj = _project(tmp)
        step = [s for s in _plan(proj) if 'материалы' in s['name']]
        import check_all
        check(len(step) == 1 and not check_all.runnable(step[0]), 'без assets/ шаг материалов не пропущен: %s' % step)
        os.makedirs(os.path.join(proj, 'assets'))
        step = [s for s in _plan(proj) if 'материалы' in s['name']]
        check(len(step) == 1 and check_all.runnable(step[0]) and 'check_materials.py' in ' '.join(step[0]['cmd']),
              'с assets/ нет запускаемого шага check_materials.py: %s' % step)
        check(step[0]['chrome'] is False, 'проверка материалов не нуждается в браузере, а отмечена шагом с ним')
        check('--project' in step[0]['cmd'] and proj in step[0]['cmd'], 'шагу не передан проект: %s' % step[0]['cmd'])
        quick = [s for s in _plan(proj, quick=True) if 'материалы' in s['name']]
        check(quick and check_all.runnable(quick[0]), '--quick потерял быстрый шаг материалов')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_engine_selftests_only_on_request():
    tmp = _tmp()
    try:
        proj = _project(tmp)
        usual = ' | '.join(_names(_plan(proj)))
        for alien in ('test_chrome_lock', 'test_pieces', 'test_audio', 'test_tts', 'схема раскадровки'):
            check(alien not in usual, 'самотест движка «%s» в проектном прогоне: %s' % (alien, usual))
        eng = {s['name']: s for s in _plan(proj, engine=True)}
        lock = [s for n, s in eng.items() if 'test_chrome_lock.py' in n]
        pieces = [s for n, s in eng.items() if 'test_pieces.py' in n]
        check(lock and pieces and [n for n in eng if 'схема раскадровки' in n], '--engine не добавил самотесты движка: %s' % sorted(eng))
        check(lock[0]['chrome'] is False and pieces[0]['chrome'] is True, 'отметка браузера у самотестов движка: замок %s, куски %s'
              % (lock[0]['chrome'], pieces[0]['chrome']))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_browser_flag_on_steps():
    tmp = _tmp()
    try:
        steps = {s['name']: s for s in _plan(_project(tmp))}
        check(steps['intro: сборка --page']['chrome'] is True, 'сборка страницы (промер в Chrome) не отмечена шагом с браузером')
        check(steps['intro: проверка --page']['chrome'] is True,
              'проверка страницы при первом запуске снимает кадры (V36, V37) в Chrome, а шагом с браузером не отмечена')
        check(steps['порчи сцены intro']['chrome'] is False, 'свой шаг без "chrome": true отмечен шагом с браузером')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_no_lock_without_browser_steps():
    """Прогон, в котором нет шагов с браузером, чужой замок не ждёт: замок берётся только на шагах с браузером."""
    tmp = _tmp()
    try:
        proj = _bare_project(tmp, [{'name': 'свой шаг без браузера', 'cmd': ['step.py']}])
        owner, env = _held_by_live(tmp)
        env['MOTION_CHROME_LOCK_TIMEOUT'] = '600'
        try:
            r = subprocess.run([PY, str(TOOL), '--project', proj], env=env, capture_output=True, text=True, encoding='utf-8',
                               errors='replace', timeout=40)
        except subprocess.TimeoutExpired:
            check(False, 'прогон без шагов с браузером ждал чужой замок Chrome дольше 40 с')
        out = r.stdout + r.stderr
        check(r.returncode == 0 and 'итог: зелёный' in out, 'прогон без браузера не зелёный: %s' % out[-400:])
        check(json.load(open(os.path.join(tmp, 'lock', 'owner.json'), encoding='utf-8')) == owner, 'чужой замок тронут')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_lock_timeout_is_one_line():
    tmp = _tmp()
    try:
        proj = _bare_project(tmp, [{'name': 'свой шаг с браузером', 'cmd': ['step.py'], 'chrome': True}])
        owner, env = _held_by_live(tmp)
        try:
            r = subprocess.run([PY, str(TOOL), '--project', proj], env=env, capture_output=True, text=True, encoding='utf-8',
                               errors='replace', timeout=60)
        except subprocess.TimeoutExpired:
            check(False, 'прогон ждал замок дольше 60 с при пределе 1 с')
        out = r.stdout + r.stderr
        check(r.returncode != 0 and 'step done' not in out, 'шаг с браузером прошёл под чужим замком: %s' % out[-400:])
        check('замок Chrome' in out and str(owner['pid']) in out and owner['label'] in out,
              'прогон не назвал владельца замка: %s' % out[-400:])
        check('Traceback' not in out, 'истечение ожидания — трассировкой: %s' % out[-600:])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(run_module(globals()))
