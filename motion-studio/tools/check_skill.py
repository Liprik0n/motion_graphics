# -*- coding: utf-8 -*-
"""Единая проверка скила motion-studio: одна команда отвечает «зелёно ли».

    python tools/check_skill.py                  ссылки скила (check_links.py, его порчи и образцы) и все тесты скила
                                                 и шаблона, которым не нужен браузер; минуты две, Chrome не нужен
    python tools/check_skill.py --chrome         плюс круг с браузером, под замком Chrome, минуты:
                                                   новый проект во временной папке — его общий прогон (демо: страница,
                                                   проверка, порчи, образцы) и рендер демо кадрами: число кадров
                                                   обязано совпасть с расчётом;
                                                   тесты с NEEDS_CHROME = True;
                                                   фильмы-фикстуры шаблона без проходов по стилям: страница, проверка,
                                                   порчи, образцы
    python tools/check_skill.py --chrome --full  ещё фильмы с проходами по стилям, порчи стилей, медленные порчи —
                                                 десятки минут
    python tools/check_skill.py --list [...]     показать шаги и не запускать

Тесты никуда не вписываются: test_*.py под tools/ и под template/engine/ находятся обходом; тест, которому нужен
браузер, объявляет в файле `NEEDS_CHROME = True`. Самотесты движка и фильмы-фикстуры шаблона гоняет эта команда;
общий прогон проекта (engine/tools/check_all.py) проверяет только свой проект.
Код выхода: 0 — зелёный, 1 — есть красное, 2 — не хватает программы или пакета (названо, чем поставить).
"""
import json
import math
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')
sys.dont_write_bytecode = True

SKILL = Path(__file__).resolve().parents[1]
TOOLS = SKILL / 'tools'
TEMPLATE = SKILL / 'template'
ENGINE = TEMPLATE / 'engine'
PROJECT = TEMPLATE / 'project'
LINKS = TOOLS / 'check_links.py'
PY = sys.executable
sys.path.insert(0, str(ENGINE / 'tools'))
sys.path.insert(0, str(ENGINE))
sys.path.insert(0, str(TEMPLATE))
import check_all      # noqa: E402  шаги, обход тестов и исполнение плана — те же, что у прогона проекта
import deps           # noqa: E402
import new_project    # noqa: E402

FRESH_FLAG = '--fresh-project'      # внутренний шаг: новый проект во временной папке и его общий прогон
ONLY_WITH_CHROME = 'тест с браузером — только с --chrome'


def plan(chrome=False, full=False):
    """Шаги проверки скила по порядку."""
    step = check_all.step
    out = [step('ссылки скила', [PY, str(LINKS)]),
           step('ссылки скила: порчи', [PY, str(LINKS), '--red']),
           step('ссылки скила: образцы', [PY, str(LINKS), '--samples'])]
    tests = check_all.test_steps(TOOLS, quick=not chrome) + check_all.engine_steps(PROJECT, quick=not chrome)
    for st in tests:
        if st['cmd'] is None and st['chrome']:
            st['why'] = ONLY_WITH_CHROME
    out += [st for st in tests if not st['chrome'] or st['cmd'] is None]
    if not chrome:
        return out
    out.append(step('новый проект: общий прогон и рендер демо', [PY, str(Path(__file__).resolve()), FRESH_FLAG]
                    + (['--full'] if full else [])))          # замок берут его шаги сами
    out += [st for st in tests if st['chrome'] and st['cmd'] is not None]
    fixtures = check_all.steps(PROJECT, quick=not full, full=full, only_films=new_project.fixtures(PROJECT)['films'])
    for st in fixtures:
        if st['cmd'] is None and '--quick' in (st['why'] or ''):
            st['why'] = 'фильм с проходами по стилям — только с --full'
    return out + fixtures


def _stream(cmd, cwd):
    print('  > ' + ' '.join(str(c) for c in cmd), flush=True)
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    env.pop('MOTION_PROJECT', None)
    return subprocess.run(cmd, cwd=cwd, env=env).returncode


def frames_verdict(out_dir):
    """Рендер демо кадрами: сколько кадров лежит, сколько записано в отметке и сколько должно быть по длительности
    (HyperFrames: ближайшее целое к длительность × fps, иначе вверх). Пустая строка — совпало, иначе что не так."""
    with open(os.path.join(out_dir, 'film.json'), encoding='utf-8') as fh:
        film = json.load(fh)
    raw = film['duration'] * film['fps']
    want = round(raw) if abs(raw - round(raw)) <= 1e-3 else math.ceil(raw)
    sys.path.insert(0, str(ENGINE / 'video'))
    import stamp          # раскладку внутри frames/ и ключи отметки знает только engine/video/stamp.py
    got = stamp.frame_counts(out_dir)
    if got['on_disk'] == want == got['stamped'] == got['full']:
        print('кадров демо: %d = расчёту по длительности %.2f с × %s к/с' % (got['on_disk'], film['duration'], film['fps']))
        return ''
    return ('FAIL число кадров демо: на диске %d, в отметке %s из %s, по расчёту (%.3f с × %s к/с) %d'
            % (got['on_disk'], got['stamped'], got['full'], film['duration'], film['fps'], want))


def fresh_project(full=False):
    """Новый проект во временной папке: его общий прогон (--quick, с --full — обычный) и рендер демо кадрами."""
    tmp = tempfile.mkdtemp(prefix='motion-skill-check-')
    target = Path(tmp) / 'proj'
    code = 1
    try:
        target, how = new_project.create(target, 'Проверка скила')
        print('новый проект: %s (node_modules: %s → %s)' % (target, how, deps.shared_node_modules()), flush=True)
        code = _stream([PY, str(target / 'engine' / 'tools' / 'check_all.py')] + ([] if full else ['--quick']), str(target))
        if code == 0:
            code = _stream([PY, str(target / 'engine' / 'video' / 'build.py'), 'demo', '--png'], str(target))
        if code == 0:
            bad = frames_verdict(str(target / 'project' / 'out' / 'demo'))
            if bad:
                print(bad)
                code = 1
    except new_project.UserError as e:
        print('ОШИБКА: %s' % e)
        code = 2
    finally:
        new_project.remove_tree(target)                 # ссылка node_modules снимается как ссылка
        try:
            os.rmdir(tmp)
        except OSError:
            pass
    print('новый проект: %s' % ('зелёный' if code == 0 else 'КРАСНЫЙ'))
    return code


def main(argv):
    known = {'--chrome', '--full', '--list', FRESH_FLAG}
    extra = [a for a in argv if a not in known]
    if extra:
        print('ОШИБКА: не знаю %s; есть --chrome, --full, --list' % ' '.join(extra), file=sys.stderr)
        return 2
    full = '--full' in argv
    if FRESH_FLAG in argv:
        return fresh_project(full=full)
    chrome = '--chrome' in argv or full
    steps = plan(chrome=chrome, full=full)
    if '--list' in argv:
        check_all.print_plan(steps)
        print('шагов: %d (скил %s)' % (len(steps), SKILL))
        return 0
    lost = deps.missing(chrome=chrome)
    if lost:
        print('ОШИБКА: проверке не хватает программ\n  ' + '\n  '.join(deps.report(lost)))
        return 2
    t0 = time.time()
    bad = check_all.run_plan(steps, str(TEMPLATE))
    print('итог: %s · %.0f с' % ('зелёный' if not bad else 'КРАСНЫЙ: ' + ', '.join(bad), time.time() - t0))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(deps.run(main, sys.argv[1:]))
