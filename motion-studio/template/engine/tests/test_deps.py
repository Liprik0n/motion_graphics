# -*- coding: utf-8 -*-
"""Нехватка программы или пакета — имя и команда установки одной строкой, без трассировки: engine/deps.py.

    python engine/tests/test_deps.py

Ожидания — из задания («команда, которой не хватает программы или пакета, называет его и команду
установки, без трассировки») (общая установка ~/.motion-studio/node_modules, переменная
MOTION_NODE_MODULES её переопределяет):
  - нет пакета Python — названы пакет pip (Pillow, а не модуль PIL) и команда pip install;
  - в node_modules нет набора — названы gsap, hyperframes, puppeteer-core и setup.py install;
  - набор Node — тот, что записан в engine/video/package.json (с lottie-web), а не свой список в коде;
  - подсказка установки называет интерпретатор, которым запущена команда (sys.executable): голый `python` на
    машине заказчика может оказаться заглушкой магазина приложений и зависнуть;
  - точка входа под deps.run(): нехватка — строка «ОШИБКА: …» и код 2; чужое исключение летит как было;
  - build.py без набора Node выходит такой же строкой;
  - команды звука, озвучки и склейки (music.py, check_mix.py, sfx.py, tts.py, check_audio.py, assemble.py) без
    пакета imageio-ffmpeg выходят строкой «нет … — поставь: …» и кодом 2, без трассировки — каждая; то же даёт
    deps.need() для Pillow. Отсутствие пакета моделируется: команда запускается в интерпретаторе, где импорт
    модуля запрещён (sys.modules[имя] = None — так же отвечает Python, когда пакета нет); пакеты не удаляются.
Chrome и сеть не нужны.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import ENGINE, PY, VIDEO, check, run_module   # noqa: E402

sys.path.insert(0, str(ENGINE))


def test_shared_install_folder():
    import deps
    old = os.environ.pop('MOTION_NODE_MODULES', None)
    try:
        check(deps.shared_node_modules() == Path.home() / '.motion-studio' / 'node_modules',
              'общая установка по умолчанию не ~/.motion-studio/node_modules: %s' % deps.shared_node_modules())
        tmp = tempfile.mkdtemp(prefix='deps_test_')
        os.environ['MOTION_NODE_MODULES'] = os.path.join(tmp, 'x', 'node_modules')
        check(deps.shared_node_modules() == Path(tmp).resolve() / 'x' / 'node_modules', 'MOTION_NODE_MODULES не переопределяет папку')
        shutil.rmtree(tmp, ignore_errors=True)
    finally:
        os.environ.pop('MOTION_NODE_MODULES', None)
        if old is not None:
            os.environ['MOTION_NODE_MODULES'] = old


def test_missing_python_package_is_named():
    import deps
    line = deps.explain(ModuleNotFoundError("No module named 'PIL'", name='PIL'))
    check(line and 'Pillow' in line and 'pip install Pillow' in line, 'нет Pillow: строка не называет пакет и команду: %s' % line)
    line = deps.explain(ModuleNotFoundError("No module named 'imageio_ffmpeg'", name='imageio_ffmpeg'))
    check(line and 'pip install imageio-ffmpeg' in line, 'нет imageio-ffmpeg: %s' % line)
    check(deps.explain(ModuleNotFoundError("No module named 'moe'", name='moe')) is None, 'чужой модуль объяснён как нехватка пакета')
    check(deps.explain(KeyError('x')) is None, 'постороннее исключение объяснено как нехватка')


def test_missing_node_packages_are_named():
    import deps
    tmp = tempfile.mkdtemp(prefix='deps_test_')
    try:
        lost = deps.missing(chrome=True, node_modules=os.path.join(tmp, 'node_modules'))
        text = '\n'.join(deps.report(lost))
        for name in ('gsap', 'hyperframes', 'puppeteer-core'):
            check(name in text, 'пустой node_modules: не назван %s: %s' % (name, text))
        check('setup.py' in text and 'install' in text, 'не названа команда установки: %s' % text)
        check(deps.missing(chrome=False) == [], 'на этой машине пакеты Python есть, а названы недостающими: %s' % deps.missing(chrome=False))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_node_set_is_read_from_package_json():
    """Пустой node_modules: назван каждый пакет из engine/video/package.json — их четыре, с lottie-web
    (проигрыватель плагина Lottie)."""
    import deps
    with open(VIDEO / 'package.json', encoding='utf-8') as fh:
        want = sorted(json.load(fh)['dependencies'])
    check(want == ['gsap', 'hyperframes', 'lottie-web', 'puppeteer-core'], 'в package.json не тот набор, что ждёт тест: %s' % want)
    tmp = tempfile.mkdtemp(prefix='deps_test_')
    try:
        text = '\n'.join(deps.report(deps.missing(chrome=True, node_modules=os.path.join(tmp, 'node_modules'))))
        for name in want:
            check(name in text, 'пустой node_modules: не назван %s из package.json: %s' % (name, text))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _bare_python(text):
    """Команда `python …` без пути: слово python в начале команды, а не в составе пути или слова «Python»."""
    return re.search(r'(^|[\s:(«`])python(\.exe)?\s', text)


def test_install_hints_name_this_python():
    import deps
    tmp = tempfile.mkdtemp(prefix='deps_test_')
    try:
        lost = deps.missing(chrome=True, node_modules=os.path.join(tmp, 'node_modules'))
        hints = [cmd for _name, cmd in lost if 'setup.py' in cmd]
        check(hints, 'пустой node_modules: нет подсказки с setup.py: %s' % lost)
        for cmd in hints:
            check('"%s"' % sys.executable in cmd and not _bare_python(cmd), 'подсказка зовёт не этот интерпретатор: %s' % cmd)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    line = deps.explain(ModuleNotFoundError("No module named 'PIL'", name='PIL'))
    check(not _bare_python(line) and line.count('"%s"' % sys.executable) == 2,
          'нет Pillow: и pip, и «всё разом» должны звать этот интерпретатор: %s' % line)
    code = ("import sys; sys.modules['PIL'] = None; sys.path.insert(0, r'%s'); import deps\ndeps.need('PIL')\n" % ENGINE)
    r = subprocess.run([PY, '-c', code], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60,
                       env=dict(os.environ, PYTHONIOENCODING='utf-8'))
    all_at_once = [l for l in r.stderr.splitlines() if l.startswith('всё разом')]
    check(len(all_at_once) == 1 and '"%s"' % PY in all_at_once[0] and not _bare_python(all_at_once[0]),
          'need(): строка «всё разом» зовёт не этот интерпретатор: %s' % r.stderr[-300:])


def test_run_turns_shortage_into_one_line():
    code = ("import sys; sys.path.insert(0, r'%s'); import deps\n"
            "def main():\n    raise ModuleNotFoundError(\"No module named 'PIL'\", name='PIL')\n"
            "sys.exit(deps.run(main))\n" % ENGINE)
    r = subprocess.run([PY, '-c', code], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60,
                       env=dict(os.environ, PYTHONIOENCODING='utf-8'))
    check(r.returncode == 2 and 'ОШИБКА' in r.stderr and 'Pillow' in r.stderr, 'нехватка пакета: код %d, %s' % (r.returncode, r.stderr[-300:]))
    check('Traceback' not in r.stderr, 'нехватка пакета — трассировкой: %s' % r.stderr[-300:])
    code = ("import sys; sys.path.insert(0, r'%s'); import deps\n"
            "def main():\n    raise KeyError('своя ошибка')\n"
            "sys.exit(deps.run(main))\n" % ENGINE)
    r = subprocess.run([PY, '-c', code], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60)
    check(r.returncode == 1 and 'KeyError' in r.stderr, 'постороннее исключение проглочено: код %d' % r.returncode)


def test_build_without_node_set_names_command():
    """build.py в движке без node_modules: одна строка «чего нет и чем поставить». Движок копируется во временную
    папку без набора Node — как проект, у которого ссылка не создана."""
    tmp = tempfile.mkdtemp(prefix='deps_test_')
    try:
        shutil.copytree(ENGINE, os.path.join(tmp, 'engine'), ignore=shutil.ignore_patterns('node_modules', '__pycache__', 'tests'))
        shutil.copytree(ENGINE.parent / 'project', os.path.join(tmp, 'project'), ignore=shutil.ignore_patterns('out', '.env', '__pycache__'))
        env = dict(os.environ, PYTHONIOENCODING='utf-8')
        env.pop('MOTION_PROJECT', None)
        r = subprocess.run([PY, os.path.join(tmp, 'engine', 'video', 'build.py'), 'demo', '--page'], env=env, capture_output=True,
                           text=True, encoding='utf-8', errors='replace', timeout=120)
        out = r.stdout + r.stderr
        check(r.returncode != 0 and 'hyperframes' in out and 'setup.py' in out, 'build.py без набора Node: код %d, %s' % (r.returncode, out[-400:]))
        check('Traceback' not in out, 'build.py без набора Node — трассировкой: %s' % out[-500:])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# команда → её обычные аргументы (до них дело не доходит: пакет нужен команде с первой строки)
NEEDS_FFMPEG = {
    'audio/music.py': ['demo'],
    'audio/check_mix.py': ['demo'],
    'audio/sfx.py': ['demo'],
    'tts/tts.py': ['--estimate'],
    'tts/check_audio.py': [],
    'video/assemble.py': ['demo', '--check'],
}
WITHOUT = ("import runpy, sys\n"
           "for name in sys.argv[1].split(','):\n"
           "    sys.modules[name] = None\n"            # как у машины без пакета: import падает ModuleNotFoundError
           "sys.argv = sys.argv[2:]\n"
           "runpy.run_path(sys.argv[0], run_name='__main__')\n")


def _run_without(modules, script, args):
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    env.pop('MOTION_PROJECT', None)
    r = subprocess.run([PY, '-c', WITHOUT, ','.join(modules), str(script)] + list(args), env=env, capture_output=True,
                       text=True, encoding='utf-8', errors='replace', timeout=120, cwd=str(ENGINE.parent))
    return r.returncode, r.stdout + r.stderr


def _shortage_line(out, package):
    """Строка вида «нет … <пакет> … — поставь: … pip install <пакет>»."""
    return [l for l in out.splitlines() if 'нет' in l and package in l and '— поставь:' in l and 'pip install %s' % package in l]


def _command_without_ffmpeg(rel):
    def test():
        code, out = _run_without(['imageio_ffmpeg'], ENGINE / rel, NEEDS_FFMPEG[rel])
        check('Traceback' not in out, '%s без imageio-ffmpeg — трассировкой: %s' % (rel, out[-500:]))
        check(_shortage_line(out, 'imageio-ffmpeg'), '%s без imageio-ffmpeg не назвал пакет и команду установки: %s' % (rel, out[-400:]))
        check(code == 2, '%s без imageio-ffmpeg: код %d, а нужен 2' % (rel, code))
    return test


for _rel in NEEDS_FFMPEG:
    globals()['test_without_ffmpeg_' + _rel.replace('/', '_').replace('.py', '')] = _command_without_ffmpeg(_rel)


def test_need_names_pillow():
    """deps.need('PIL') без Pillow: та же строка и код 2; с пакетом на месте — молча."""
    code = ("import sys; sys.modules['PIL'] = None; sys.path.insert(0, r'%s'); import deps\n"
            "deps.need('PIL', 'imageio_ffmpeg')\nprint('дальше')\n" % ENGINE)
    r = subprocess.run([PY, '-c', code], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60,
                       env=dict(os.environ, PYTHONIOENCODING='utf-8'))
    out = r.stdout + r.stderr
    check(r.returncode == 2 and _shortage_line(out, 'Pillow') and 'Traceback' not in out and 'дальше' not in out,
          'need() без Pillow: код %d, %s' % (r.returncode, out[-300:]))
    check(not _shortage_line(out, 'imageio-ffmpeg'), 'назван недостающим пакет, который на месте: %s' % out[-300:])
    code = "import sys; sys.path.insert(0, r'%s'); import deps\ndeps.need('PIL', 'imageio_ffmpeg')\nprint('дальше')\n" % ENGINE
    r = subprocess.run([PY, '-c', code], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60,
                       env=dict(os.environ, PYTHONIOENCODING='utf-8'))
    check(r.returncode == 0 and 'дальше' in r.stdout, 'need() при пакетах на месте: код %d, %s' % (r.returncode, r.stderr[-300:]))


if __name__ == '__main__':
    sys.exit(run_module(globals()))
