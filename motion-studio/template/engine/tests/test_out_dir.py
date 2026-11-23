# -*- coding: utf-8 -*-
"""build.py --out-dir: относительный путь даёт тот же результат, что абсолютный.

    python engine/tests/test_out_dir.py

Ожидание — из задания: «--out-dir приводится к абсолютному». Рендер HyperFrames идёт с рабочей
папкой = папке выхода, поэтому относительный путь раньше удваивался (папка искалась внутри самой себя).
Один и тот же пробный кусок (первые кадры демо) снимается дважды: с относительным --out-dir от текущей папки и с
абсолютным; кадры обязаны совпасть попиксельно, число кадров — с заказанным, а вложенной папки-двойника быть не
должно. Работает на копии project/ во временной папке; поставка не трогается.
"""
import os
import shutil
import subprocess
import sys
import tempfile

NEEDS_CHROME = True      # тест запускает безголовый браузер: общий прогон берёт на него замок и не зовёт в --quick

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import ENGINE, PY, VIDEO, check, run_module   # noqa: E402

FRAMES = 2
REL = os.path.join('rel', 'page')


def _build(tmp, proj, out_dir):
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    env.pop('MOTION_PROJECT', None)
    r = subprocess.run([PY, str(VIDEO / 'build.py'), 'demo', '--png', '--frames', str(FRAMES), '--project', proj,
                        '--out-dir', out_dir, '--tmp', os.path.join(tmp, 'render-tmp')], cwd=tmp, env=env,
                       capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=900)
    return r.returncode, (r.stdout + r.stderr)


def _frame_paths(d):
    """Кадры куска по порядку номеров: {имя: путь}. Раскладку внутри frames/ знает engine/video/stamp.py."""
    sys.path.insert(0, str(VIDEO))
    import stamp
    return {os.path.basename(p): p for p in stamp.frame_files(d)}


def _frames(d):
    return list(_frame_paths(d))


def test_relative_out_dir_equals_absolute():
    from PIL import Image, ImageChops
    tmp = tempfile.mkdtemp(prefix='out_dir_test_')
    try:
        proj = os.path.join(tmp, 'project')
        shutil.copytree(ENGINE.parent / 'project', proj, ignore=shutil.ignore_patterns('out', '.env', '__pycache__'))
        code, out = _build(tmp, proj, REL)
        rel_dir = os.path.join(tmp, REL)
        check(code == 0, 'сборка с относительным --out-dir упала (код %d): %s' % (code, out[-500:]))
        want = ['frame_%06d.png' % (k + 1) for k in range(FRAMES)]
        check(_frames(rel_dir) == want, 'кадры не там, куда указывает относительный путь от текущей папки: %s' % _frames(rel_dir))
        check(not os.path.exists(os.path.join(rel_dir, 'rel')), 'путь удвоился: появилась %s' % os.path.join(rel_dir, 'rel'))
        abs_dir = os.path.join(tmp, 'abs', 'page')
        code, out = _build(tmp, proj, abs_dir)
        check(code == 0 and _frames(abs_dir) == want, 'сборка с абсолютным --out-dir: код %d, кадры %s' % (code, _frames(abs_dir)))
        for name in want:
            a = Image.open(_frame_paths(rel_dir)[name]).convert('RGBA')
            b = Image.open(_frame_paths(abs_dir)[name]).convert('RGBA')
            check(a.size == b.size and ImageChops.difference(a, b).getbbox() is None,
                  'кадр %s при относительном и абсолютном --out-dir разный' % name)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(run_module(globals()))
