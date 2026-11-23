# -*- coding: utf-8 -*-
"""strip.py --name: имя папки полосы — одна часть пути внутри <out>/<фильм>/strips/, иначе отказ до первой записи.

    python engine/tests/test_strip_name.py

Имя идёт в путь папки, которую команда сначала стирает: `--name ../../..` указывало на папку проекта, `--name .` —
на все полосы фильма вместе с кэшем кадров, `--name _cache` — на сам кэш. Ожидания: имя — одна
часть пути, не `.`, не `..`, не `_cache`; иначе отказ одной строкой, и на диске ничего не тронуто. Windows сама
срезает у имени папки точки и пробелы в конце и не различает регистр, поэтому `_CACHE`, `keep.` и пробел — те же
случаи. Браузер не нужен: отказ обязан прийти раньше страницы, сборки и замка Chrome (замок теста — свой, в его
временной папке). Что полоса с законным именем пишется куда надо — в test_strip.py (с браузером).
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import ENGINE, PY, check, run_module   # noqa: E402

STRIP = str(ENGINE / 'tools' / 'strip.py')
BAD_NAMES = ('../../..', '..', '.', '_cache', '_CACHE', 'a/b', 'a\\b', '../keep', 'C:evil', 'keep.', 'keep ', ' ')


def _tree(root):
    seen = {}
    for d, _dirs, files in os.walk(root):
        for f in files:
            p = os.path.join(d, f)
            with open(p, 'rb') as fh:
                seen[os.path.relpath(p, root)] = hashlib.sha1(fh.read()).hexdigest()
    return seen


def _project(tmp):
    """Проект без страницы: project.json, фильм demo, прежняя полоса keep, кэш кадров и чужие файлы рядом."""
    proj = os.path.join(tmp, 'project')
    for rel, body in (('project.json', '{}'), ('films/demo.json', json.dumps({'scenes': ['demo-a']})),
                      ('scenes/demo-a/storyboard.json', '{}'), ('out/demo/strips/keep/strip.json', '{"id": "keep"}'),
                      ('out/demo/strips/keep/strip.png', 'png'), ('out/demo/strips/_cache/abc/0001.png', 'png'),
                      ('out/demo/keep/video.mp4', 'video'), ('out/tts/r001.mp3', 'voice')):
        p = os.path.join(proj, *rel.split('/'))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'w', encoding='utf-8') as fh:
            fh.write(body)
    return proj


def _run(tmp, proj, name):
    env = dict(os.environ, PYTHONIOENCODING='utf-8', MOTION_CHROME_LOCK=os.path.join(tmp, 'lock'),
               MOTION_CHROME_LOCK_TIMEOUT='20')
    for k in ('MOTION_PROJECT', 'MOTION_CHROME_LOCK_HELD'):
        env.pop(k, None)
    r = subprocess.run([PY, STRIP, 'demo', '--project', proj, '--scene', 'demo-a', '--no-build', '--name', name],
                       env=env, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=300)
    return r.returncode, (r.stdout + r.stderr).strip()


def test_name_outside_strips_folder_is_refused_before_any_write():
    tmp = tempfile.mkdtemp(prefix='strip_name_test_')
    try:
        proj = _project(tmp)
        before = _tree(proj)
        for name in BAD_NAMES:
            code, out = _run(tmp, proj, name)
            check(code != 0, '--name %r принято (код 0): %s' % (name, out[-200:]))
            check('--name' in out and len(out.splitlines()) == 1,
                  '--name %r: отказ не про имя полосы или не одной строкой: %s' % (name, out[-300:]))
            check('Traceback' not in out, '--name %r: трассировка: %s' % (name, out[-300:]))
            after = _tree(proj)
            check(after == before, '--name %r: на диске изменилось %s' % (name, sorted(set(after.items()) ^ set(before.items()))[:3]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_plain_name_passes_the_name_check():
    """Законное имя отказом «про имя» не останавливается: команда идёт дальше и спотыкается уже о страницу,
    которой в этом проекте нет."""
    tmp = tempfile.mkdtemp(prefix='strip_name_test_')
    try:
        proj = _project(tmp)
        for name in ('scene-demo-a-v2', 'сцена.2', '_cache2'):
            code, out = _run(tmp, proj, name)
            check(code != 0 and 'нет страницы' in out and '--name' not in out,
                  'законное имя %r остановлено не на странице: %s' % (name, out[-300:]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(run_module(globals()))
