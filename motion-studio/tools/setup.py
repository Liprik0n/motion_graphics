# -*- coding: utf-8 -*-
"""Что есть на машине для скила motion-studio, чего не хватает и установка недостающего одной командой.

    python tools/setup.py check                       что найдено (ядра, видеокарта, версии Python, Node, HyperFrames,
                                                      Chrome), какой захват выберет рендер и чего не хватает — с командой
                                                      установки; код 1, если чего-то нет
    python tools/setup.py install                     поставить недостающее; повторный запуск ничего не переустанавливает
    python tools/setup.py agents [--from DIR] [--to DIR]   карточки ролей agents/motion-*.md → ~/.claude/agents/

Что ставит install и откуда:
  пакеты Python      pip, по списку requirements.txt скила (Pillow, imageio-ffmpeg — с ним ffmpeg, fontTools);
  набор Node         `npm ci` в общей папке ~/.motion-studio (другая — переменная MOTION_NODE_MODULES, путь к
                     её node_modules) по template/engine/video/package.json и package-lock.json: gsap, hyperframes,
                     lottie-web, puppeteer-core точными версиями — набор читается из package.json, своего списка
                     здесь нет. Проекты и сам шаблон подключают эту папку ссылкой;
  Chrome             `hyperframes browser ensure` — в кэш HyperFrames (~/.cache/hyperframes/chrome);
  ссылку шаблона     template/engine/video/node_modules → общая установка (снимается только сама ссылка).
Python и Node.js сама команда не ставит: называет их и команду установки и останавливается. Минимумы — одни на весь
скил: Python — deps.PYTHON_MIN, Node — engines.node в package.json шаблона (deps.NODE_MIN). Подсказки зовут
интерпретатор, которым запущена эта команда (sys.executable), а не голый `python`.
Старые проекты со своей ссылкой на прежний набор (HyperFrames 0.8.x) не затрагиваются.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')
sys.dont_write_bytecode = True

SKILL = Path(__file__).resolve().parents[1]
TEMPLATE = SKILL / 'template'
ENGINE = TEMPLATE / 'engine'
VIDEO = ENGINE / 'video'
PACKAGE, PACKAGE_LOCK = VIDEO / 'package.json', VIDEO / 'package-lock.json'
REQUIREMENTS = SKILL / 'requirements.txt'
TEMPLATE_LINK = VIDEO / 'node_modules'
AGENTS_SRC = SKILL / 'agents'
AGENTS_DST = Path.home() / '.claude' / 'agents'
AGENTS_GLOB = 'motion-*.md'
sys.path.insert(0, str(ENGINE))
sys.path.insert(0, str(TEMPLATE))
import deps           # noqa: E402  названия и команды установки — одни на движок и на эту команду
import new_project    # noqa: E402  ссылка node_modules: создать, распознать, снять

PYTHON_MIN = deps.PYTHON_MIN

# адаптеры, которые не ускоряют захват: гость виртуальной машины, удалённый стол, базовый драйвер Windows
VIRTUAL_ADAPTER = re.compile(r'basic display|basic render|базовый видеоадаптер|remote display|hyper-v|virtualbox|vmware|'
                             r'\bqxl\b|virtio|parsec|standard vga|citrix|displaylink', re.I)
HF_QUIET = {'HYPERFRAMES_NO_TELEMETRY': '1', 'DO_NOT_TRACK': '1', 'HYPERFRAMES_NO_UPDATE_CHECK': '1',
            'HYPERFRAMES_SKIP_SKILLS': '1', 'HYPERFRAMES_NO_OPTIONAL_INSTALL': '1'}
PLAN_ORDER = ('python_packages', 'node', 'node_modules', 'chrome', 'template_link')
SELF = '"%s" "%s" install' % (deps.PYTHON, Path(__file__).resolve())


class UserError(Exception):
    """Понятная пользователю ошибка: одна строка, код 2."""


def wanted():
    """Точные версии набора Node — из package.json шаблона."""
    with open(PACKAGE, encoding='utf-8') as fh:
        return json.load(fh)['dependencies']


def _out(cmd, timeout=60):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def _module_version(module, attr='__version__'):
    try:
        mod = __import__(module)
    except ImportError:
        return None
    return str(getattr(mod, attr, None) or getattr(mod, 'version', '') or '?')


def _ffmpeg():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:           # пакета нет или он не нашёл свой ffmpeg — для отчёта это одно и то же «нет»
        return None


def list_video_controllers():
    """Имена видеоадаптеров, как их называет система. Не узнали — пустой список."""
    if os.name == 'nt':
        ps = shutil.which('powershell') or shutil.which('pwsh')
        if not ps:
            return []
        out = _out([ps, '-NoProfile', '-NonInteractive', '-Command',
                    '[Console]::OutputEncoding=[Text.Encoding]::UTF8; (Get-CimInstance Win32_VideoController).Name'])
    else:
        smi = shutil.which('nvidia-smi')
        out = _out([smi, '--query-gpu=name', '--format=csv,noheader']) if smi else None
    return [l.strip() for l in (out or '').splitlines() if l.strip()]


def detect(video_controllers=None):
    """Что есть на машине: {python, pillow, ffmpeg, node, npm, hyperframes, chrome, cores, gpu}. Нет — None;
    gpu — список настоящих видеокарт (пустой — захват программный). video_controllers — подставленный ответ
    определения адаптеров (тест ветки «видеокарта есть»); None — спросить систему."""
    names = list_video_controllers() if video_controllers is None else list(video_controllers)
    npm = shutil.which('npm')
    return {
        'python': '%d.%d.%d' % sys.version_info[:3],
        'pillow': _module_version('PIL'),
        'ffmpeg': _ffmpeg(),
        'node': deps.node_version(),
        'npm': _out([npm, '--version']) if npm else None,
        'hyperframes': deps.package_version(deps.shared_node_modules(), 'hyperframes'),
        'chrome': deps.find_chrome(),
        'cores': os.cpu_count() or 1,
        'gpu': [n for n in names if not VIRTUAL_ADAPTER.search(n)],
    }


def capture_mode(found):
    """Какой захват кадров выберет рендер на этой машине: {mode: 'gpu'|'software', label, flag}."""
    if found['gpu']:
        return {'mode': 'gpu', 'label': 'захват с видеокартой (HyperFrames --browser-gpu)', 'flag': '--browser-gpu'}
    return {'mode': 'software', 'label': 'захват программный, на процессоре (HyperFrames --no-browser-gpu)',
            'flag': '--no-browser-gpu'}


def report(found):
    """Строки «что найдено» для печати."""
    def have(v):
        return v if v else 'нет'
    return [
        'Python %s · Pillow %s · ffmpeg: %s' % (found['python'], have(found['pillow']), have(found['ffmpeg'])),
        'Node %s · npm %s' % (have(found['node']), have(found['npm'])),
        'HyperFrames %s (нужна %s) · общая установка: %s' % (have(found['hyperframes']), wanted()['hyperframes'],
                                                             deps.shared_node_modules()),
        'Chrome: %s' % have(found['chrome']),
        'машина: ядер %d · %s' % (found['cores'], 'видеокарта: ' + ', '.join(found['gpu']) if found['gpu'] else 'видеокарты нет'),
        capture_mode(found)['label'],
    ]


def _node_major(ver):
    m = re.match(r'v?(\d+)', ver or '')
    return int(m.group(1)) if m else 0


def versions_mismatch(node_modules, want=None):
    """Пакеты набора, которых нет в node_modules или они не той версии."""
    want = wanted() if want is None else want
    return [n for n, v in want.items() if deps.package_version(node_modules, n) != v]


def _link_target():
    """Куда смотрит node_modules шаблона (настоящий путь) или None, если его нет."""
    return str(TEMPLATE_LINK.resolve()) if TEMPLATE_LINK.exists() else None


def current_state(found=None):
    """Состояние машины для плана установки."""
    found = found or detect()
    import importlib.util
    lost = [pkg for mod, pkg in deps.PY_PACKAGES.items() if importlib.util.find_spec(mod) is None]
    return {'python_packages': lost, 'node': found['node'], 'npm': found['npm'],
            'node_modules': str(deps.shared_node_modules()), 'chrome': found['chrome'], 'template_link': _link_target()}


def install_plan(state):
    """Что надо поставить, по порядку: подмножество PLAN_ORDER. Пусто — всё на месте."""
    plan = []
    if state['python_packages']:
        plan.append('python_packages')
    if _node_major(state['node']) < deps.NODE_MIN or not state['npm']:
        plan.append('node')
    shared = Path(state['node_modules'])
    if versions_mismatch(shared):
        plan.append('node_modules')
    if not state['chrome']:
        plan.append('chrome')
    link = state['template_link']
    if link is None or (Path(link).resolve() != shared.resolve() and versions_mismatch(link)):
        plan.append('template_link')
    return plan


def needs(state, found):
    """Чего не хватает, для печати: [(имя, команда)]."""
    out = []
    if sys.version_info[:2] < PYTHON_MIN:
        out.append(('Python %d.%d или новее (сейчас %s)' % (PYTHON_MIN + (found['python'],)),
                    'winget install Python.Python.3.13  (или установщик с https://www.python.org)'))
    plan = install_plan(state)
    if 'python_packages' in plan:
        out.append(('пакеты Python: ' + ', '.join(state['python_packages']),
                    deps.pip_command('-r "%s"' % REQUIREMENTS) + '  — или ' + SELF))
    if 'node' in plan:
        out.append(('Node.js %d или новее с npm (сейчас node: %s, npm: %s)' % (deps.NODE_MIN, state['node'] or 'нет', state['npm'] or 'нет'),
                    deps.NODE_INSTALL))
    if 'node_modules' in plan:
        want = wanted()
        lost = ', '.join('%s %s' % (n, want[n]) for n in versions_mismatch(state['node_modules']))
        out.append(('набор Node в %s: %s' % (state['node_modules'], lost), SELF))
    if 'chrome' in plan:
        out.append(('Chrome для промера и рендера (кэш HyperFrames)', SELF))
    if 'template_link' in plan:
        out.append(('ссылка %s на общую установку (сейчас: %s)' % (TEMPLATE_LINK, state['template_link'] or 'нет'), SELF))
    return out


def check(found=None):
    found = found or detect()
    for line in report(found):
        print(line)
    lost = needs(current_state(found), found)
    for line in deps.report(lost):
        print(line)
    print('итог: %s' % ('всё на месте' if not lost else 'не хватает: %d' % len(lost)))
    return 1 if lost else 0


# ---------------------------------------------------------------- шаги установки
def _run(cmd, cwd=None, env=None):
    print('  > ' + ' '.join('"%s"' % c if ' ' in str(c) else str(c) for c in cmd), flush=True)
    return subprocess.run(cmd, cwd=cwd, env=env).returncode


def _step_python_packages(state):
    return _run([sys.executable, '-m', 'pip', 'install', '-r', str(REQUIREMENTS)]) == 0


def _step_node(state):
    print('Node.js %d или новее с npm команда не ставит сама — поставь: %s; потом повтори: %s'
          % (deps.NODE_MIN, deps.NODE_INSTALL, SELF))
    return False


def _step_node_modules(state):
    shared = Path(state['node_modules'])
    if shared.name != 'node_modules':
        raise UserError('%s должна указывать на папку с именем node_modules (сейчас %s)' % (deps.ENV_NODE_MODULES, shared))
    home = shared.parent
    home.mkdir(parents=True, exist_ok=True)
    for src in (PACKAGE, PACKAGE_LOCK):
        shutil.copyfile(src, home / src.name)
    env = dict(os.environ, **HF_QUIET)
    if _run([shutil.which('npm'), 'ci', '--no-audit', '--no-fund'], cwd=str(home), env=env):
        return False
    lost = versions_mismatch(shared)
    if lost:
        print('npm отработал, но в %s нет нужных версий: %s' % (shared, ', '.join(lost)))
    return not lost


def _step_chrome(state):
    hf = Path(state['node_modules']) / 'hyperframes' / 'bin' / 'hyperframes.mjs'
    if _run([shutil.which('node'), str(hf), 'browser', 'ensure'], env=dict(os.environ, **HF_QUIET)):
        return False
    return deps.find_chrome() is not None


def _step_template_link(state):
    shared = Path(state['node_modules'])
    if TEMPLATE_LINK.exists() or new_project.is_link(TEMPLATE_LINK):
        if not new_project.is_link(TEMPLATE_LINK):
            print('%s — настоящая папка с другим набором, а не ссылка: убери её сам, команда чужие файлы не удаляет' % TEMPLATE_LINK)
            return False
        new_project.remove_link(TEMPLATE_LINK)        # только сама ссылка; то, на что она смотрела, остаётся
    how = new_project.link_node_modules(shared, TEMPLATE_LINK, copy=False)
    print('  node_modules шаблона → %s (%s)' % (shared, how))
    return True


STEPS = {'python_packages': ('пакеты Python', _step_python_packages), 'node': ('Node.js', _step_node),
         'node_modules': ('набор Node (npm ci)', _step_node_modules), 'chrome': ('Chrome', _step_chrome),
         'template_link': ('ссылка шаблона', _step_template_link)}


def install():
    done = []
    while True:
        plan = [s for s in install_plan(current_state()) if s not in done]
        if not plan:
            break
        step = plan[0]           # план пересчитывается после каждого шага: Chrome ищется уже новым набором
        print('ставлю: %s' % STEPS[step][0], flush=True)
        if not STEPS[step][1](current_state()):
            print('не вышло: %s — остальное не ставилось' % STEPS[step][0])
            return 1
        done.append(step)
    print('поставлено: %s' % (', '.join(STEPS[s][0] for s in done) if done else 'ничего — всё уже на месте'))
    return check()


def agents(src=None, dst=None):
    """Скопировать карточки ролей motion-*.md из скила в папку агентов. Возвращает список записанных файлов."""
    src, dst = Path(src or AGENTS_SRC), Path(dst or AGENTS_DST)
    cards = sorted(src.glob(AGENTS_GLOB)) if src.is_dir() else []
    if not cards:
        raise UserError('в %s нет карточек ролей %s — копировать нечего' % (src, AGENTS_GLOB))
    dst.mkdir(parents=True, exist_ok=True)
    out = []
    for card in cards:
        shutil.copyfile(card, dst / card.name)
        out.append(dst / card.name)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description='Зависимости скила motion-studio: проверить и поставить')
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('check', help='что найдено и чего не хватает')
    sub.add_parser('install', help='поставить недостающее')
    ag = sub.add_parser('agents', help='карточки ролей → ~/.claude/agents')
    ag.add_argument('--from', dest='src', help='откуда (умолчание — agents/ скила)')
    ag.add_argument('--to', dest='dst', help='куда (умолчание — ~/.claude/agents)')
    a = ap.parse_args(argv)
    try:
        if a.cmd == 'check':
            return check()
        if a.cmd == 'install':
            return install()
        done = agents(a.src, a.dst)
        print('карточек ролей скопировано: %d → %s' % (len(done), done[0].parent))
        return 0
    except (UserError, new_project.UserError) as e:
        print('ОШИБКА: %s' % e, file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
