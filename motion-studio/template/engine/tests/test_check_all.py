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
Chrome не нужен: план строится и печатается (--list), шаги не запускаются.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

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
    return proj


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
        check(not [n for n in _names(quick, True) if 'test_pieces' in n or 'test_project' in n], '--quick гоняет медленные тесты')
        check([n for n in _names(usual) if 'test_pieces' in n], 'обычный прогон без медленных тестов')
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


if __name__ == '__main__':
    sys.exit(run_module(globals()))
