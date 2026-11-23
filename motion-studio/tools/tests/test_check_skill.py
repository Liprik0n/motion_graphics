# -*- coding: utf-8 -*-
"""Единая проверка скила tools/check_skill.py и правила хранения файлов скила (.gitattributes, requirements.txt).

    python tools/tests/test_check_skill.py

Ожидания — из задания:
  - без флагов: ссылки скила (check_links.py, --red, --samples) и все тесты скила и шаблона без Chrome; тесты с
    NEEDS_CHROME и сборка страниц — не запускаются (шагов под замком Chrome нет);
  - --chrome: новый проект во временной папке, тесты с браузером, фильмы-фикстуры шаблона; фильмы с проходами по
    стилям — только с --full;
  - тесты никто не вписывает в список: новый test_*.py под tools/ или в движке попадает в план сам. Поэтому и
    этот файл не называет чужие тесты и фильмы поимённо: он сам обходит диск по тому же правилу и сверяет план
    с найденным — новый тест соседней задачи ничего здесь не ломает и не требует правки;
  - .gitattributes держит LF для текстовых файлов и помечает бинарными все двоичные файлы скила;
  - requirements.txt называет Pillow, imageio-ffmpeg и fontTools.
Здесь план только печатается (--list): ничего не собирается и браузер не нужен.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILL / 'template' / 'engine' / 'tests'))
from _util import PY, check, run_module   # noqa: E402

TOOL = SKILL / 'tools' / 'check_skill.py'
SKIP_DIRS = {'node_modules', 'out', '__pycache__', '.git'}


def _list(*flags):
    r = subprocess.run([PY, str(TOOL), '--list'] + list(flags), capture_output=True, text=True, encoding='utf-8',
                       errors='replace', timeout=120)
    check(r.returncode == 0, 'check_skill.py --list %s: код %d, %s' % (' '.join(flags), r.returncode, (r.stdout + r.stderr)[-400:]))
    run = [l[5:] for l in r.stdout.splitlines() if l.startswith('шаг  ')]
    skip = [l[5:] for l in r.stdout.splitlines() if l.startswith('SKIP ')]
    return run, skip


def _has(lines, word):
    return [l for l in lines if word in l]


def _tests_on_disk():
    """Тесты скила и шаблона, как их описывает правило: test_*.py под tools/ и под template/engine/ (папки
    node_modules, out, __pycache__ и скрытые — мимо); браузер нужен тому, в чьём файле есть строка
    `NEEDS_CHROME = True`. Возвращает {'тест <путь от своего корня>': нужен ли браузер} — так шаг назван в плане."""
    found = {}
    for root in (SKILL / 'tools', SKILL / 'template' / 'engine'):
        for p in sorted(root.rglob('test_*.py')):
            rel = p.relative_to(root)
            if any(part in SKIP_DIRS or part.startswith('.') for part in rel.parts[:-1]):
                continue
            chrome = bool(re.search(r'^NEEDS_CHROME\s*=\s*True\b', p.read_text(encoding='utf-8-sig', errors='replace'), re.M))
            found['тест ' + rel.as_posix()] = chrome
    return found


def _fixture_films():
    """Фильмы шаблона, кроме стартового: {имя: есть ли проходы по стилям}."""
    sys.path.insert(0, str(SKILL / 'template'))
    import new_project
    films = {}
    for p in sorted((SKILL / 'template' / 'project' / 'films').glob('*.json')):
        if p.stem not in new_project.STARTER_FILMS:
            films[p.stem] = bool(json.loads(p.read_text(encoding='utf-8-sig')).get('styles'))
    return films, new_project.STARTER_FILMS


def _step(lines, name):
    """Строки плана, которые называют ровно этот шаг (имя — с начала строки, дальше пробел или конец)."""
    return [l for l in lines if l == name or l.startswith(name + ' ')]


def test_default_plan_needs_no_chrome():
    run, skip = _list()
    check(len(_has(run, 'ссылки скила')) == 3, 'нет трёх шагов ссылок (проверка, порчи, образцы): %s' % _has(run, 'ссылки'))
    tests = _tests_on_disk()
    check(len([t for t, chrome in tests.items() if not chrome]) >= 2 and [t for t, chrome in tests.items() if chrome],
          'на диске не нашлось тестов обоих видов — сверять план не с чем: %s' % sorted(tests))
    for name, chrome in tests.items():
        if chrome:
            check(not _step(run, name) and _step(skip, name), '«%s» — тест с браузером: без --chrome он должен быть SKIP' % name)
        else:
            check(_step(run, name), 'в плане без флагов нет шага «%s», а файл теста лежит на диске' % name)
    planned = [l.split('  ')[0].strip() for l in run + skip if l.startswith('тест ')]
    alien = [n for n in planned if n not in tests]
    check(not alien, 'в плане тесты, которых нет на диске: %s' % alien)
    check(_has(run, 'схема раскадровки'), 'в плане без флагов нет порч схемы раскадровки')
    check(not _has(run, 'под замком Chrome'), 'без флагов в плане шаг с браузером: %s' % _has(run, 'под замком Chrome'))
    check(not _has(run, 'сборка --page') and not _has(run, 'новый проект'), 'без флагов в плане сборка страниц')


def test_chrome_plan_is_full_circle():
    run, skip = _list('--chrome')
    check(_has(run, 'новый проект'), 'в круге с браузером нет нового проекта во временной папке')
    for name in _tests_on_disk():
        check(_step(run, name), 'в круге с браузером нет шага «%s», а файл теста лежит на диске' % name)
    films, starter = _fixture_films()
    plain = [f for f, styles in films.items() if not styles]
    styled = [f for f, styles in films.items() if styles]
    check(plain and styled, 'в шаблоне нет фильмов-фикстур обоих видов: %s' % films)
    for film in plain:
        check(_step(run, '%s: сборка --page' % film) and _step(run, '%s: проверка --page' % film),
              'в круге с браузером нет сборки и проверки фильма-фикстуры «%s»' % film)
    for film in starter:
        check(not _step(run, '%s: сборка --page' % film), 'стартовый фильм «%s» собирается и в шаблоне, и в новом проекте — дважды' % film)
    for film in styled:
        check(not _step(run, '%s: сборка --page' % film) and _has(skip, film + ':'), 'фильм «%s» с проходами по стилям — только с --full' % film)
    full, _ = _list('--chrome', '--full')
    for film in styled:
        check(_step(full, '%s: сборка --page' % film), '--full не добавил фильм «%s» с проходами по стилям' % film)
    check(len(_has(full, 'порчи --red')) > len(_has(run, 'порчи --red')), '--full не добавил порчи стилей')


def test_gitattributes_keeps_lf_and_marks_binaries():
    text = (SKILL / '.gitattributes').read_text(encoding='utf-8')
    check(re.search(r'^\*\s+text=auto\s+eol=lf\s*$', text, re.M), '.gitattributes не держит LF для текстовых файлов (* text=auto eol=lf)')
    binary = {m.group(1).lower() for m in re.finditer(r'^\*(\.\w+)\s+binary\s*$', text, re.M)}
    lost = set()
    for p in SKILL.rglob('*'):
        if not p.is_file() or SKIP_DIRS & set(p.parts):
            continue
        with open(p, 'rb') as fh:
            if b'\0' in fh.read(8192) and p.suffix.lower() not in binary:
                lost.add(p.suffix.lower() or p.name)
    check(not lost, 'двоичные файлы скила не помечены binary в .gitattributes: %s' % sorted(lost))
    for ext in ('.png', '.mp3', '.wav', '.ttf', '.exe', '.jpg', '.webp', '.mp4', '.woff2', '.lottie'):
        check(ext in binary, 'расширение %s не помечено binary' % ext)


def test_requirements_name_python_packages():
    names = {re.split(r'[<>=!~ ]', l.strip(), maxsplit=1)[0].lower() for l in (SKILL / 'requirements.txt').read_text(encoding='utf-8').splitlines()
             if l.strip() and not l.lstrip().startswith('#')}
    check(names == {'pillow', 'imageio-ffmpeg', 'fonttools'}, 'requirements.txt называет не те пакеты: %s' % sorted(names))


if __name__ == '__main__':
    sys.exit(run_module(globals()))
