# -*- coding: utf-8 -*-
"""Сцена, начатая с картинки-кадра, даёт первый кадр рендера, попиксельно равный этой картинке.

    python engine/video/tests/test_start_frame.py     (≈ 1 мин: рендер 2 с фикстуры bare кадрами, под замком Chrome)

Ожидание — из описания поля раскадровки start_image (engine/video/plugins/README.md, schema.core.json): «первый
кадр сцены = картинка пиксель в пиксель». Условие V28 проверяет это по промеру DOM (рамка, непрозрачность, ничего
поверх); здесь — сами пиксели настоящего рендера: стык с готовым роликом, чей последний кадр подан картинкой, не
должен дать ни сдвига, ни пересчёта цвета. Контроль сравнения: в окне помех кадр от картинки отличается — иначе
сравнение ничего не видит. Работает на копии project/ во временной папке; поставка не трогается.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

VIDEO = Path(__file__).resolve().parents[1]
ENGINE = VIDEO.parent
TEMPLATE = ENGINE.parent
sys.path.insert(0, str(ENGINE / 'tests'))
from _util import PY, check, run_module   # noqa: E402

FILM, SCENE = 'bare', 'bare-start'
FRAMES = 60          # 2 с при 30 к/с: первый кадр и начало окна помех фикстуры


def test_first_frame_equals_png_and_glitch_differs():
    import json
    from PIL import Image, ImageChops
    tmp = tempfile.mkdtemp(prefix='start_frame_')
    try:
        proj = Path(tmp) / 'project'
        shutil.copytree(TEMPLATE / 'project', proj, ignore=shutil.ignore_patterns('out', '.env', '__pycache__', 'music'))
        sb = json.load(open(proj / 'scenes' / SCENE / 'storyboard.json', encoding='utf-8'))
        pj = json.load(open(proj / 'project.json', encoding='utf-8'))
        png = proj / sb['start_image']
        check(png.exists(), 'нет картинки-кадра фикстуры %s' % png)
        ref = Image.open(png).convert('RGB')
        check(ref.size == (pj['canvas']['w'], pj['canvas']['h']), 'картинка-кадр не размером с полотно: %s' % (ref.size,))
        env = dict(os.environ)
        env.pop('MOTION_PROJECT', None)
        r = subprocess.run([PY, str(VIDEO / 'build.py'), FILM, '--png', '--frames', str(FRAMES), '--project', str(proj),
                            '--tmp', os.path.join(tmp, 'render')], capture_output=True, text=True, encoding='utf-8',
                           errors='replace', env=env)
        check(r.returncode == 0, 'рендер упал: %s' % (r.stdout + r.stderr)[-800:])
        fdir = proj / pj['paths']['out'] / FILM / 'frames'
        fr = sorted(f for f in os.listdir(fdir) if f.endswith('.png'))
        check(len(fr) == FRAMES, 'ждали %d кадров, а %d' % (FRAMES, len(fr)))
        first = Image.open(fdir / fr[0]).convert('RGB')
        bbox = ImageChops.difference(ref, first).getbbox()
        check(bbox is None, 'первый кадр отличается от картинки-кадра в области %s' % (bbox,))
        fps = pj['fps']
        diffs = [ImageChops.difference(ref, Image.open(fdir / f).convert('RGB')).getbbox() for f in fr[fps:]]
        check(any(d is not None for d in diffs), 'в окне помех кадры совпали с картинкой — помех нет или сравнение слепо')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(run_module(globals()))
