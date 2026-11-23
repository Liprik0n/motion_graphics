# -*- coding: utf-8 -*-
"""Сцена, начатая с картинки-кадра, даёт первый кадр рендера, попиксельно равный этой картинке.

    python engine/video/tests/test_start_frame.py     (≈ 1 мин: рендер 2 с фикстуры bare кадрами, под замком Chrome)

Ожидание — из описания поля раскадровки start_image (engine/video/plugins/README.md, schema.core.json): «первый
кадр сцены = картинка пиксель в пиксель». Условие V28 проверяет это по промеру DOM (рамка, непрозрачность, ничего
поверх); здесь — сами пиксели настоящего рендера: стык с готовым роликом, чей последний кадр подан картинкой, не
должен дать ни сдвига, ни пересчёта цвета. Контроль сравнения: в окне помех кадр от картинки отличается — иначе
сравнение ничего не видит. Работает на копии project/ во временной папке; поставка не трогается.

Второй тест — кадры проверок глаза (V36, V37) после замены картинки-кадра под тем же именем: страница (index.html,
film.json) от замены не меняется, а кадр меняется. Ожидание: check.py --page снимает кадры заново — первый кадр
полосы проверки равен новой картинке (ключ кэша кадров — отпечаток страницы stamp.page_print: с файлами assets/).
"""
NEEDS_CHROME = True      # тест запускает безголовый браузер: общий прогон берёт на него замок и не зовёт в --quick

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
        sys.path.insert(0, str(VIDEO))
        import stamp          # кадры куска по порядку номеров; раскладку внутри frames/ знает только stamp.py
        out_dir = str(proj / pj['paths']['out'] / FILM)
        fr = stamp.frame_files(out_dir)
        got = stamp.frame_counts(out_dir)
        check(len(fr) == got['on_disk'] == got['stamped'] == FRAMES,
              'ждали %d кадров, а на диске %d, в отметке %s' % (FRAMES, len(fr), got['stamped']))
        check(os.path.basename(fr[0]) == 'frame_000001.png', 'первый кадр куска — не кадр 1: %s' % fr[0])
        first = Image.open(fr[0]).convert('RGB')
        bbox = ImageChops.difference(ref, first).getbbox()
        check(bbox is None, 'первый кадр отличается от картинки-кадра в области %s' % (bbox,))
        fps = pj['fps']
        diffs = [ImageChops.difference(ref, Image.open(f).convert('RGB')).getbbox() for f in fr[fps:]]
        check(any(d is not None for d in diffs), 'в окне помех кадры совпали с картинкой — помех нет или сравнение слепо')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_check_page_reshoots_frames_when_start_image_is_replaced_under_same_name():
    import json
    from PIL import Image, ImageChops, ImageOps
    sys.path.insert(0, str(VIDEO))
    import check as C
    tmp = tempfile.mkdtemp(prefix='start_frame_swap_')
    try:
        proj = Path(tmp) / 'project'
        shutil.copytree(TEMPLATE / 'project', proj, ignore=shutil.ignore_patterns('out', '.env', '__pycache__', 'music'))
        sb = json.load(open(proj / 'scenes' / SCENE / 'storyboard.json', encoding='utf-8'))
        pj = json.load(open(proj / 'project.json', encoding='utf-8'))
        png = proj / sb['start_image']
        out_dir = proj / pj['paths']['out'] / FILM
        env = dict(os.environ, PYTHONIOENCODING='utf-8')
        env.pop('MOTION_PROJECT', None)

        def page_and_check():
            for script in ('build.py', 'check.py'):
                r = subprocess.run([PY, str(VIDEO / script), FILM, '--page', '--project', str(proj)], capture_output=True,
                                   text=True, encoding='utf-8', errors='replace', env=env)
                check(r.returncode == 0, '%s %s --page: %s' % (script, FILM, (r.stdout + r.stderr)[-800:]))
            page = (out_dir / 'index.html').read_bytes()
            first = C.eye(C.make_ctx(str(proj), str(out_dir), page_only=True))['frames'][0]['file']     # из кэша проверки
            return page, Image.open(first).convert('RGB')

        old = Image.open(png).convert('RGB')
        page_a, first_a = page_and_check()
        check(ImageChops.difference(old, first_a).getbbox() is None, 'первый кадр полосы проверки — не картинка-кадр (до замены)')
        new = ImageOps.invert(old)
        new.save(png)                                           # та же картинка-кадр, то же имя, другое содержимое
        page_b, first_b = page_and_check()
        check(page_a == page_b, 'тест ничего не доказывает: от замены картинки изменился сам index.html')
        check(ImageChops.difference(new, first_b).getbbox() is None,
              'картинку-кадр заменили под тем же именем, а check.py --page смотрит кадры старой картинки')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(run_module(globals()))
