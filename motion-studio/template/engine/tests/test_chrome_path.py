# -*- coding: utf-8 -*-
"""Где лежит Chrome — одно правило на все промеры: engine/video/chrome_path.mjs.

    python engine/tests/test_chrome_path.py

Ожидания — из задания («chromePath() — один модуль, три .mjs импортируют его»):
  - probe_dom.mjs, probe_frames.mjs и styles/_core/probe_style.mjs не держат своей копии, а импортируют модуль;
  - порядок поиска: CHROME_PATH → кэш HyperFrames (самая новая сборка, сборки сравниваются числами: 152 новее 99;
    папка платформы не зашита — linux64 находится так же, как win64) → Chrome системы;
  - Chrome нет — одна строка с командой установки и код 2, без трассировки; CHROME_PATH на несуществующий файл —
    тоже отказ, а не молчаливая подмена другим браузером.
Сам Chrome не запускается: пути подставные, домашняя папка — временная. Нужен только node.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import VIDEO, check, run_module   # noqa: E402

MODULE = VIDEO / 'chrome_path.mjs'
USERS = [VIDEO / 'probe_dom.mjs', VIDEO / 'probe_frames.mjs', VIDEO / 'styles' / '_core' / 'probe_style.mjs']
SHELL = 'chrome-headless-shell'


def _home(tmp, builds):
    """Временная домашняя папка с кэшем HyperFrames: builds — [(папка сборки, папка платформы, имя файла)]."""
    home = Path(tmp) / 'home'
    for build, platform, exe in builds:
        d = home / '.cache' / 'hyperframes' / 'chrome' / SHELL / build / platform
        d.mkdir(parents=True)
        (d / exe).write_text('пустышка', encoding='utf-8')
    home.mkdir(parents=True, exist_ok=True)
    return home


def _ask(home, chrome_path=None):
    env = {k: v for k, v in os.environ.items() if k.upper() not in ('CHROME_PATH', 'PROGRAMFILES', 'PROGRAMFILES(X86)', 'LOCALAPPDATA')}
    env.update({'USERPROFILE': str(home), 'HOME': str(home)})
    if chrome_path is not None:
        env['CHROME_PATH'] = chrome_path
    r = subprocess.run(['node', str(MODULE)], env=env, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60)
    return r.returncode, r.stdout.strip(), r.stderr


def test_three_probes_share_one_rule():
    check(MODULE.exists(), 'нет %s' % MODULE)
    for p in USERS:
        text = p.read_text(encoding='utf-8')
        check('function chromePath' not in text, '%s держит свою копию chromePath()' % p.name)
        check('chrome_path.mjs' in text and 'chromePath()' in text, '%s не берёт Chrome из chrome_path.mjs' % p.name)
        check('chrome-headless-shell-win64' not in text, '%s зашивает папку платформы win64' % p.name)


def test_newest_build_wins_by_number():
    tmp = tempfile.mkdtemp(prefix='chrome_path_test_')
    try:
        home = _home(tmp, [('win64-99.0.1.1', SHELL + '-win64', SHELL + '.exe'), ('win64-152.0.7977.30', SHELL + '-win64', SHELL + '.exe')])
        code, out, err = _ask(home)
        check(code == 0 and 'win64-152.0.7977.30' in out, 'взята не самая новая сборка (152 новее 99): код %d, %s %s' % (code, out, err[-200:]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_platform_folder_is_not_hardcoded():
    tmp = tempfile.mkdtemp(prefix='chrome_path_test_')
    try:
        home = _home(tmp, [('linux-152.0.7977.30', SHELL + '-linux64', SHELL)])
        code, out, err = _ask(home)
        check(code == 0 and out.replace('\\', '/').endswith('linux-152.0.7977.30/%s-linux64/%s' % (SHELL, SHELL)),
              'сборка linux64 в кэше не найдена: код %d, %s %s' % (code, out, err[-200:]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_env_wins_and_must_exist():
    tmp = tempfile.mkdtemp(prefix='chrome_path_test_')
    try:
        home = _home(tmp, [('win64-152.0.7977.30', SHELL + '-win64', SHELL + '.exe')])
        mine = Path(tmp) / 'my-chrome.exe'
        mine.write_text('пустышка', encoding='utf-8')
        code, out, err = _ask(home, str(mine))
        check(code == 0 and out == str(mine), 'CHROME_PATH не главнее кэша: код %d, %s' % (code, out))
        code, out, err = _ask(home, str(Path(tmp) / 'net.exe'))
        check(code == 2 and not out and 'CHROME_PATH' in err, 'CHROME_PATH на несуществующий файл принят молча: код %d, %s %s' % (code, out, err[-200:]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_no_chrome_is_one_line_with_command():
    """Chrome нет нигде (пустая домашняя папка, пустое окружение) — поиск честно отвечает «нет»; отказ через
    CHROME_PATH на несуществующий файл идёт тем же выходом: одна строка с командой установки, код 2."""
    tmp = tempfile.mkdtemp(prefix='chrome_path_test_')
    try:
        home = _home(tmp, [])
        js = ("const m = await import(process.argv[1]); "
              "console.log(JSON.stringify(m.findChrome({}, process.argv[2])));")
        r = subprocess.run(['node', '--input-type=module', '-e', js, MODULE.as_uri(), str(home)], capture_output=True, text=True,
                           encoding='utf-8', errors='replace', timeout=60)
        check(r.returncode == 0 and r.stdout.strip() == 'null', 'без Chrome поиск ответил не «нет»: %s %s' % (r.stdout, r.stderr[-300:]))
        code, out, err = _ask(home, str(Path(tmp) / 'net.exe'))
        check(code == 2, 'нет Chrome: код %d, а нужен 2' % code)
        check('browser ensure' in err and 'setup.py' in err, 'отказ не называет команду установки: %s' % err[-300:])
        check('    at ' not in err and 'Error:' not in err, 'отказ — трассировкой node: %s' % err[-400:])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(run_module(globals()))
