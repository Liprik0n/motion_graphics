# -*- coding: utf-8 -*-
"""Чего не хватает на машине и чем это поставить — одно место для команд движка.

    import deps
    deps.need('imageio_ffmpeg')                                # первая строка команды: нет пакета — строка и код 2
    for name, command in deps.missing(chrome=True): ...        # [(имя, команда установки)]; пусто — всё на месте
    sys.exit(deps.run(main))                                   # точка входа: нехватка — одна строка, без трассировки

Что нужно движку: пакеты Python (Pillow, imageio-ffmpeg — с ним приходит ffmpeg; fontTools — только для
video/tools/fix_font.py), Node.js и набор Node в engine/video/node_modules — ссылка на общую установку
`~/.motion-studio/node_modules` (другая папка — переменная MOTION_NODE_MODULES), Chrome в кэше HyperFrames. Всё это
одной командой ставит `<скил>/tools/setup.py install`; здесь — только названия и команды, сам модуль ничего не ставит
и в сеть не ходит.

Набор Node и минимум Node нигде в коде не переписаны: это `dependencies` и `engines.node` файла
engine/video/package.json (сейчас gsap, hyperframes, lottie-web, puppeteer-core; Node 22). Минимум Python — PYTHON_MIN
здесь; его же называют tools/setup.py и RENDER.md пакета на рендер. Команды в подсказках зовут интерпретатор, которым
запущена сама команда (sys.executable): голый `python` на чужой машине может оказаться не тем или зависнуть.
"""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parent
VIDEO = ENGINE / 'video'
NODE_MODULES = VIDEO / 'node_modules'
ENV_NODE_MODULES = 'MOTION_NODE_MODULES'
SHARED_HOME = '.motion-studio'                   # общая установка: ~/.motion-studio/node_modules
PACKAGE_JSON = VIDEO / 'package.json'            # набор Node (dependencies) и минимум Node (engines.node)
PYTHON = sys.executable or 'python'              # интерпретатор этой команды: им же зовут pip и setup.py в подсказках
PYTHON_MIN = (3, 10)                             # минимум Python: один на setup.py, RENDER.md пакета и документы
PY_PACKAGES = {'PIL': 'Pillow', 'imageio_ffmpeg': 'imageio-ffmpeg', 'fontTools': 'fonttools'}   # модуль → пакет pip
PY_REQUIRED = ('PIL', 'imageio_ffmpeg')          # без них не идёт ни сборка, ни проверка
NODE_INSTALL = 'winget install OpenJS.NodeJS.LTS  (или установщик LTS с https://nodejs.org)'


def _read_package():
    """(пакеты набора Node, минимум Node) из engine/video/package.json: dependencies и engines.node («>=22»)."""
    try:
        with open(PACKAGE_JSON, encoding='utf-8') as fh:
            data = json.load(fh)
        return tuple(sorted(data['dependencies'])), int(re.match(r'\s*>=\s*(\d+)', data['engines']['node']).group(1))
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        raise SystemExit('ОШИБКА: не читается %s (%s: %s) — в нём набор Node движка (dependencies) и минимум Node '
                         '(engines.node «>=N»); движок скопирован не целиком' % (PACKAGE_JSON, type(e).__name__, e))


def setup_command():
    """Команда общей установки, этим же интерпретатором. Путь к setup.py скила известен, когда движок лежит в самом
    скиле или скил стоит в ~/.claude/skills; из копии движка в проекте скил не виден — тогда путь назван словами."""
    here = ENGINE.parent                          # <скил>/template, если это движок шаблона
    found = [p for p in ((here.parent / 'tools' / 'setup.py') if (here / 'new_project.py').is_file() else None,
                         Path.home() / '.claude' / 'skills' / 'motion-studio' / 'tools' / 'setup.py')
             if p is not None and p.is_file()]
    return '"%s" "%s" install' % (PYTHON, found[0] if found else '<скил motion-studio>/tools/setup.py')


NODE_PACKAGES, NODE_MIN = _read_package()        # HyperFrames 0.9.x: engines.node >= 22
SETUP = setup_command()


def shared_node_modules():
    """Папка общей установки Node: MOTION_NODE_MODULES, иначе ~/.motion-studio/node_modules."""
    env = os.environ.get(ENV_NODE_MODULES)
    if env:
        return Path(env).expanduser().resolve()
    return Path.home() / SHARED_HOME / 'node_modules'


def pip_command(package):
    return '"%s" -m pip install %s' % (PYTHON, package)


def package_version(node_modules, name):
    """Версия пакета Node в node_modules или None (пакета нет либо его package.json не читается)."""
    try:
        with open(Path(node_modules) / name / 'package.json', encoding='utf-8') as fh:
            return json.load(fh).get('version')
    except (OSError, ValueError):
        return None


def node_version():
    """Версия Node («v24.1.0») или None, если node не найден."""
    exe = shutil.which('node')
    if not exe:
        return None
    try:
        r = subprocess.run([exe, '--version'], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() or None


def find_chrome():
    """Путь к Chrome по правилу video/chrome_path.mjs (тот же файл читают промеры) или None."""
    exe = shutil.which('node')
    if not exe:
        return None
    try:
        r = subprocess.run([exe, str(VIDEO / 'chrome_path.mjs')], capture_output=True, text=True, encoding='utf-8',
                           errors='replace', timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None


def _importable(module):
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):       # сломанная запись о модуле — для команды это то же «пакета нет»
        return False


def need(*modules):
    """Первая строка команды, которой нужны пакеты Python (имена модулей: 'PIL', 'imageio_ffmpeg'). Нет хоть
    одного — строки «нет: … — поставь: …» в stderr и код 2, без трассировки. Зовётся до импорта самих пакетов:
    команда, которая импортирует пакет на уровне модуля, иначе упала бы раньше, чем дошла до своего main()."""
    lost = missing(chrome=False, modules=modules)
    if not lost:
        return
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8')
    print('\n'.join(report(lost) + ['всё разом: ' + SETUP]), file=sys.stderr, flush=True)
    raise SystemExit(2)


def missing(chrome=False, modules=PY_REQUIRED, node_modules=None):
    """Чего не хватает команде движка: [(имя, команда установки)]. chrome=True — ещё Node, набор Node и Chrome
    (всё, что нужно шагу с браузером)."""
    out = []
    for mod in modules:
        if not _importable(mod):
            out.append(('пакет Python %s (модуль %s)' % (PY_PACKAGES[mod], mod), pip_command(PY_PACKAGES[mod])))
    if not chrome:
        return out
    ver = node_version()
    if ver is None:
        out.append(('Node.js (команда node, версия %d или новее)' % NODE_MIN, NODE_INSTALL))
    nm = Path(node_modules) if node_modules else NODE_MODULES
    lost = [p for p in NODE_PACKAGES if package_version(nm, p) is None]
    if lost:
        out.append(('набор Node в %s: %s' % (nm, ', '.join(lost)), SETUP))
    elif ver is not None and find_chrome() is None:
        out.append(('Chrome для промера и рендера', SETUP + '  (он зовёт `hyperframes browser ensure`)'))
    return out


def report(lost):
    """Строки «нет X — поставь: команда» для печати."""
    return ['нет: %s — поставь: %s' % (name, cmd) for name, cmd in lost]


def explain(exc):
    """Понятная строка для исключения, за которым стоит нехватка программы или пакета; иначе None."""
    import chrome_lock
    if isinstance(exc, chrome_lock.LockTimeout):
        return str(exc)
    if isinstance(exc, ImportError):
        mod = (getattr(exc, 'name', None) or '').split('.')[0]
        if mod in PY_PACKAGES:
            return ('нет пакета Python %s (модуль %s) — поставь: %s; всё разом: %s'
                    % (PY_PACKAGES[mod], mod, pip_command(PY_PACKAGES[mod]), SETUP))
        return None
    if isinstance(exc, FileNotFoundError):
        if shutil.which('node') is None:
            return 'нет Node.js (команда node не найдена) — поставь: %s; затем %s' % (NODE_INSTALL, SETUP)
        return None
    if isinstance(exc, subprocess.CalledProcessError):
        cmd = exc.cmd if isinstance(exc.cmd, str) else ' '.join(str(c) for c in exc.cmd)
        return 'команда завершилась с кодом %s (её сообщение — выше): %s' % (exc.returncode, cmd[:300])
    return None


def run(main, *args):
    """Запустить точку входа. Нехватка программы или пакета, упавший промер, истёкшее ожидание замка Chrome —
    одна строка «ОШИБКА: …» и код 2 вместо трассировки; всё остальное летит как было."""
    try:
        return main(*args)
    except (ImportError, FileNotFoundError, subprocess.CalledProcessError, TimeoutError) as e:
        line = explain(e)
        if line is None:
            raise
        print('ОШИБКА: ' + line, file=sys.stderr, flush=True)
        return 2
