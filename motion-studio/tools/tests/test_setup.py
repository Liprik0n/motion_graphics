# -*- coding: utf-8 -*-
"""Проверка и установка зависимостей скила одной командой: tools/setup.py check | install | agents.

    python tools/tests/test_setup.py

Ожидания — из задания («Установка и общая папка HyperFrames»):
  - detect() отдаёт ровно {python, pillow, ffmpeg, node, npm, hyperframes, chrome, cores, gpu};
  - ветка «видеокарта есть» проверяется подставленным ответом определения: настоящая карта названа и захват
    выбирается с ней; виртуальные и базовые адаптеры (эта машина) — «видеокарты нет», захват программный;
  - check при нехватке называет недостающее и команду установки, код возврата не ноль;
  - план install пуст, когда всё на месте (повторный запуск ничего не переустанавливает), и называет только
    недостающее;
  - версия HyperFrames в package.json шаблона — точная 0.9.x, package-lock.json называет её же;
  - agents копирует только agents/motion-*.md;
  - подсказка установки называет интерпретатор, которым запущена команда, а не голый `python`;
  - минимум Python и Node один: setup.py, deps.py и RENDER.md пакета на рендер называют одни числа, Node — то,
    что записано в package.json шаблона (engines.node).
Сеть и npm не трогаются: общая установка подменяется папкой во временном каталоге (MOTION_NODE_MODULES).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SKILL = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILL / 'template' / 'engine' / 'tests'))
from _util import PY, check, run_module   # noqa: E402

sys.path.insert(0, str(SKILL / 'tools'))
TOOL = SKILL / 'tools' / 'setup.py'
PACKAGE = SKILL / 'template' / 'engine' / 'video' / 'package.json'
KEYS = {'python', 'pillow', 'ffmpeg', 'node', 'npm', 'hyperframes', 'chrome', 'cores', 'gpu'}
REAL_CARD = 'NVIDIA GeForce RTX 4070'
# то, что видит гость виртуальной машины и удалённый стол: это не видеокарта для захвата
VIRTUAL = ['Microsoft Remote Display Adapter', 'Базовый видеоадаптер (Майкрософт)', 'Microsoft Basic Display Adapter',
           'Red Hat QXL controller', 'VirtualBox Graphics Adapter (WDDM)', 'VMware SVGA 3D', 'Microsoft Hyper-V Video']


def _setup():
    import importlib
    return importlib.import_module('setup')


def _fake_node_modules(tmp, versions):
    nm = Path(tmp) / 'shared' / 'node_modules'
    for name, ver in versions.items():
        (nm / name).mkdir(parents=True)
        (nm / name / 'package.json').write_text(json.dumps({'name': name, 'version': ver}), encoding='utf-8')
    return nm


def _wanted():
    return json.loads(PACKAGE.read_text(encoding='utf-8'))['dependencies']


def test_detect_keys():
    found = _setup().detect(video_controllers=[])
    check(set(found) == KEYS, 'detect() отдал не те ключи: %s' % sorted(found))
    check(isinstance(found['cores'], int) and found['cores'] >= 1, 'cores — не число ядер: %r' % found['cores'])
    check(found['python'] == '%d.%d.%d' % sys.version_info[:3], 'python — не версия этого интерпретатора: %r' % found['python'])


def test_gpu_present_branch():
    s = _setup()
    found = s.detect(video_controllers=VIRTUAL[:2] + [REAL_CARD])
    check(found['gpu'] == [REAL_CARD], 'настоящая видеокарта не названа: %r' % found['gpu'])
    mode = s.capture_mode(found)
    check(mode['mode'] == 'gpu', 'с видеокартой выбран не захват с видеокартой: %r' % mode)
    text = '\n'.join(s.report(found))
    check(REAL_CARD in text and mode['label'] in text, 'отчёт не называет видеокарту и режим захвата:\n%s' % text)


def test_no_gpu_branch():
    s = _setup()
    found = s.detect(video_controllers=VIRTUAL)
    check(found['gpu'] == [], 'виртуальный адаптер принят за видеокарту: %r' % found['gpu'])
    mode = s.capture_mode(found)
    check(mode['mode'] == 'software', 'без видеокарты выбран не программный захват: %r' % mode)
    check('видеокарты нет' in '\n'.join(s.report(found)), 'отчёт не говорит, что видеокарты нет')


def test_check_names_missing_and_command():
    tmp = tempfile.mkdtemp(prefix='setup_test_')
    try:
        env = dict(os.environ, MOTION_NODE_MODULES=str(Path(tmp) / 'empty' / 'node_modules'), PYTHONIOENCODING='utf-8')
        r = subprocess.run([PY, str(TOOL), 'check'], env=env, capture_output=True, text=True, encoding='utf-8',
                           errors='replace', timeout=120)
        out = r.stdout + r.stderr
        check(r.returncode != 0, 'check без общей установки вернул 0:\n%s' % out[-400:])
        check('hyperframes' in out and 'setup.py' in out and 'install' in out,
              'check не назвал hyperframes и команду установки:\n%s' % out[-600:])
        for word in ('ядер', 'видеокарт', 'Python', 'Node', 'Chrome'):
            check(word in out, 'check не напечатал «%s»:\n%s' % (word, out[-600:]))
        check('Traceback' not in out, 'check упал трассировкой:\n%s' % out[-600:])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_install_hint_names_this_python():
    """Строка «поставь: … setup.py install» зовёт тот же интерпретатор, которым запущена проверка."""
    tmp = tempfile.mkdtemp(prefix='setup_test_')
    try:
        env = dict(os.environ, MOTION_NODE_MODULES=str(Path(tmp) / 'empty' / 'node_modules'), PYTHONIOENCODING='utf-8')
        r = subprocess.run([PY, str(TOOL), 'check'], env=env, capture_output=True, text=True, encoding='utf-8',
                           errors='replace', timeout=120)
        hints = [l for l in (r.stdout + r.stderr).splitlines() if 'setup.py' in l and 'install' in l]
        check(hints, 'check без общей установки не назвал команду установки:\n%s' % (r.stdout + r.stderr)[-400:])
        for line in hints:
            cmd = line.split('поставь:', 1)[-1]
            check('"%s"' % PY in cmd, 'подсказка зовёт не этот интерпретатор (%s): %s' % (PY, line))
            check(not re.search(r'(^|[\s:(«`])python(\.exe)?\s', cmd), 'в подсказке голый python: %s' % line)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_python_and_node_minimums_are_one():
    s = _setup()
    sys.path.insert(0, str(SKILL / 'template' / 'engine'))
    sys.path.insert(0, str(SKILL / 'template' / 'engine' / 'tools'))
    import deps
    import render_pack
    video = {'width': 1920, 'height': 1080, 'fps': 30.0, 'frames': 90, 'duration_sec': 3.0}
    text = render_pack.render_md('demo', {'video': video, 'page_sha256': 'a' * 64})
    check('Python %d.%d+' % s.PYTHON_MIN in text, 'RENDER.md называет не тот минимум Python, что setup.py (%d.%d): %s'
          % (s.PYTHON_MIN + (re.findall(r'Python \d+\.\d+\+?', text),)))
    engines = json.loads(PACKAGE.read_text(encoding='utf-8'))['engines']['node']
    want = int(re.fullmatch(r'>=\s*(\d+)', engines).group(1))
    check(deps.NODE_MIN == want, 'deps.NODE_MIN %s, а package.json требует Node %s' % (deps.NODE_MIN, engines))
    check('Node.js %d ' % want in text, 'RENDER.md называет не тот минимум Node: ждали %d' % want)


def test_install_plan_is_empty_when_all_present():
    s = _setup()
    tmp = tempfile.mkdtemp(prefix='setup_test_')
    try:
        nm = _fake_node_modules(tmp, _wanted())
        state = {'python_packages': [], 'node': 'v24.0.0', 'npm': '11.0.0', 'node_modules': str(nm),
                 'chrome': 'C:/chrome.exe', 'template_link': str(nm)}
        check(s.install_plan(state) == [], 'всё на месте, а план установки не пуст: %s' % s.install_plan(state))
        old = dict(_wanted(), hyperframes='0.8.181')
        nm2 = _fake_node_modules(os.path.join(tmp, 'b'), old)
        state2 = dict(state, node_modules=str(nm2), template_link=str(nm2))
        check(s.install_plan(state2) == ['node_modules'], 'старая версия HyperFrames: план %s' % s.install_plan(state2))
        state3 = dict(state, chrome=None, python_packages=['fonttools'])
        check(s.install_plan(state3) == ['python_packages', 'chrome'], 'нет Chrome и пакета: план %s' % s.install_plan(state3))
        state4 = dict(state, template_link=None)
        check(s.install_plan(state4) == ['template_link'], 'ссылка шаблона не на общую установку: план %s' % s.install_plan(state4))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_hyperframes_version_is_pinned():
    deps = _wanted()
    check(set(deps) == {'gsap', 'hyperframes', 'lottie-web', 'puppeteer-core'}, 'в package.json не тот набор: %s' % sorted(deps))
    for name, ver in deps.items():
        check(re.fullmatch(r'\d+\.\d+\.\d+', ver), '%s: версия не точная (%s)' % (name, ver))
    check(deps['hyperframes'].startswith('0.9.'), 'HyperFrames не 0.9.x: %s' % deps['hyperframes'])
    lock = json.loads((PACKAGE.parent / 'package-lock.json').read_text(encoding='utf-8'))
    for name, ver in deps.items():
        got = lock['packages']['node_modules/' + name]['version']
        check(got == ver, 'package-lock.json: %s %s, а package.json требует %s' % (name, got, ver))


def test_agents_copies_only_role_cards():
    s = _setup()
    tmp = tempfile.mkdtemp(prefix='setup_test_')
    try:
        src, dst = Path(tmp) / 'agents', Path(tmp) / 'home' / 'agents'
        src.mkdir()
        (src / 'motion-qa.md').write_text('карточка QA\n', encoding='utf-8')
        (src / 'motion-scene.md').write_text('карточка сцены\n', encoding='utf-8')
        (src / 'README.md').write_text('не карточка\n', encoding='utf-8')
        done = s.agents(src=src, dst=dst)
        check(sorted(p.name for p in dst.iterdir()) == ['motion-qa.md', 'motion-scene.md'],
              'скопировано не то: %s' % sorted(p.name for p in dst.iterdir()))
        check(len(done) == 2 and (dst / 'motion-qa.md').read_text(encoding='utf-8') == 'карточка QA\n', 'карточка скопирована не дословно')
        r = subprocess.run([PY, str(TOOL), 'agents', '--from', str(Path(tmp) / 'net'), '--to', str(dst)], capture_output=True,
                           text=True, encoding='utf-8', errors='replace', timeout=60)
        check(r.returncode != 0 and 'Traceback' not in r.stdout + r.stderr, 'нет папки карточек: код %d, %s' % (r.returncode, (r.stdout + r.stderr)[-300:]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(run_module(globals()))
