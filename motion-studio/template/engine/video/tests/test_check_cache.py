# -*- coding: utf-8 -*-
"""Проверка не берёт устаревший кадр молча — engine/video/check.py против отметок engine/video/stamp.py.

    python engine/video/tests/test_check_cache.py        (секунды, без браузера)

Два места, где старая картинка проходила зелёной:
  ролик. check.py <фильм> без --page мерит video.mp4, а страницу после рендера могли пересобрать другой (правка сцены
    → build.py --page → зелёная проверка страницы → в сдаче прежняя картинка). Отметка кадров frames/stamp.json пишется
    каждым полным рендером; ожидание: V1 красная, когда stamp.stale(<out>/<фильм>) не пуст, и называет причину и
    команду перерендера; с --page ролик не смотрится — отметка не при чём;
  кадры глаза. V36 и V37 берут кадры страницы из кэша. Файл в assets/, заменённый под тем же именем (картинка-кадр,
    шрифт), не меняет ни index.html, ни film.json — но меняет кадр. Ожидание: ключ кэша — отпечаток страницы
    stamp.page_print (index.html + film.json + каждый файл assets/): после замены картинки кадры запрашиваются заново
    и проверка видит новые.
Ролик теста — 2 с, 64×36, со звуком (ffmpeg из imageio-ffmpeg); страница — три файла во временной папке. Кадры
страницы тесту даёт подмена strip.frames (счётчик запросов): Chrome не нужен, замок — свой, во временной папке.
"""
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

VIDEO = Path(__file__).resolve().parents[1]
ENGINE = VIDEO.parent
sys.path.insert(0, str(ENGINE / 'tests'))
from _util import check, run_module   # noqa: E402

sys.path.insert(0, str(VIDEO))
sys.path.insert(0, str(ENGINE))
sys.path.insert(0, str(ENGINE / 'tools'))
import check as C     # noqa: E402
import stamp          # noqa: E402

FPS, W, H = 30, 64, 36
REPLY_END, TAIL = 1.0, 1.0          # ролик = конец последней реплики + хвост = 2,0 с
_tmp = []


def _dir():
    d = tempfile.mkdtemp(prefix='check_cache_')
    _tmp.append(d)
    return d


def _page(out, body='<div id="content">сцена</div>', picture=(200, 30, 30)):
    """Собранная «страница»: index.html, film.json и картинка в assets/."""
    from PIL import Image
    os.makedirs(os.path.join(out, 'assets'), exist_ok=True)
    with open(os.path.join(out, 'index.html'), 'w', encoding='utf-8') as fh:
        fh.write('<!doctype html><body>%s<img src="assets/start.png"></body>' % body)
    film = {'film': 't', 'fps': FPS, 'duration': REPLY_END + TAIL, 'canvas': {'w': W, 'h': H, 'px_per_in': 96},
            'scenes': [{'id': 's1', 'start': 0.0, 'end': REPLY_END + TAIL, 'first': 0.0, 'last': REPLY_END}],
            'replies': [{'n': 1, 'num': 1, 'scene': 's1', 'start': 0.0, 'end': REPLY_END, 'file': None}]}
    with open(os.path.join(out, 'film.json'), 'w', encoding='utf-8') as fh:
        json.dump(film, fh)
    Image.new('RGB', (W, H), picture).save(os.path.join(out, 'assets', 'start.png'))
    return film


def _ctx(root, out, film, page_only):
    os.makedirs(os.path.join(root, 'scenes', 's1'), exist_ok=True)
    with open(os.path.join(root, 'scenes', 's1', 'storyboard.json'), 'w', encoding='utf-8') as fh:
        json.dump({'scene': 's1', 'title': 'T', 'start_state': {}, 'end_state': {}, 'beats': []}, fh)
    with open(os.path.join(root, 'project.json'), 'w', encoding='utf-8') as fh:
        json.dump({'title': 'T', 'paths': {'out': 'out'}}, fh)
    rule = [[(k + 0.5) / FPS, math.floor((k + 0.5) / FPS * FPS + 0.5 + 0.005) / FPS] for k in range(4)]
    tokens = {'motion': {'beat_tail': 0.5, 'title_in': 0.4, 'chapter_dur': 0.4},
              'density': {'max_static': 6.0, 'zones': {'grid': [4, 3], 'min_share': 0.002, 'delta': 0.02, 'step_sec': 0.5}},
              'legibility': {'pixel': {'contrast_min': 3.0, 'keep': 0.8}}}
    return C.Ctx(root=root, project={'fps': FPS, 'tail_sec': TAIL, 'canvas': {'w': W, 'h': H, 'px_per_in': 96}},
                 tokens=tokens, film=film, probe={'samples': [], 'round_rule': rule, 'errors': []}, fdef={},
                 out_dir=out, scenes_dir=os.path.join(root, 'scenes'), page=os.path.join(out, 'index.html'),
                 mp4=os.path.join(out, 'video.mp4'), page_only=page_only)


def _render(out, film):
    """«Полный рендер»: кадры сцены, отметка куска и video.mp4 нужной длины со звуком."""
    n = int(round(film['duration'] * FPS))
    d = os.path.join(out, 'frames', 's1')
    os.makedirs(d, exist_ok=True)
    for k in range(n):
        with open(os.path.join(d, 'frame_%06d.png' % (k + 1)), 'wb') as fh:
            fh.write(b'png')
    stamp.write(out, n, n, FPS, (W, H))
    r = subprocess.run([C.ffmpeg(), '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i',
                        'color=c=white:s=%dx%d:r=%d:d=%s' % (W, H, FPS, film['duration']), '-f', 'lavfi', '-i',
                        'anullsrc=r=44100:cl=mono', '-t', str(film['duration']), '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                        '-c:a', 'aac', os.path.join(out, 'video.mp4')], capture_output=True, text=True)
    check(r.returncode == 0, 'ffmpeg не собрал ролик теста: %s' % r.stderr[-300:])


def test_v1_is_red_when_page_changed_after_render():
    root = _dir()
    out = os.path.join(root, 'out', 't')
    film = _page(out)
    _render(out, film)
    f = C.v1_duration(_ctx(root, out, film, page_only=False))
    check(f == [], 'ролик снят с этой же страницы — V1 должна молчать, получили: %s' % (f,))
    _page(out, body='<div id="content">сцену поправили</div>')          # правка сцены и build.py --page: кадры прежние
    f = C.v1_duration(_ctx(root, out, film, page_only=False))
    check(f and any(l.startswith('V1') and 'index.html' in l and 'build.py t' in l for l in f),
          'страница изменилась после рендера: ждали провал V1 с причиной (index.html) и командой перерендера, получили: %s' % (f,))
    f = C.v1_duration(_ctx(root, out, film, page_only=True))
    check(f == [], 'с --page ролик не смотрится: отметка кадров не при чём, получили: %s' % (f,))


def test_v1_is_red_when_picture_replaced_or_stamp_lost():
    from PIL import Image
    root = _dir()
    out = os.path.join(root, 'out', 't')
    film = _page(out)
    _render(out, film)
    Image.new('RGB', (W, H), (30, 30, 200)).save(os.path.join(out, 'assets', 'start.png'))      # то же имя, другая картинка
    f = C.v1_duration(_ctx(root, out, film, page_only=False))
    check(f and any('assets' in l for l in f), 'картинку заменили под тем же именем: ждали провал V1 про файлы assets/, получили: %s' % (f,))
    _page(out)
    check(C.v1_duration(_ctx(root, out, film, page_only=False)) == [], 'прежняя картинка вернулась — V1 снова молчит')
    os.remove(os.path.join(out, 'frames', stamp.NAME))
    f = C.v1_duration(_ctx(root, out, film, page_only=False))
    check(f and any('отметки' in l for l in f), 'у кадров нет отметки — неизвестно, с какой страницы ролик: ждали провал V1, получили: %s' % (f,))


def test_eye_frames_are_requested_again_when_picture_is_replaced_under_same_name():
    from PIL import Image
    import strip
    root = _dir()
    out = os.path.join(root, 'out', 't')
    film = _page(out)
    calls = []

    def fake_frames(project, name, t0, t1, fps, scale, page=None):
        """Вместо Chrome: «кадр страницы» — её картинка assets/start.png, как её показал бы браузер."""
        d = os.path.join(out, 'strips', '_cache', 'shot-%d' % len(calls))        # там, куда кладёт кадры strip.frames
        os.makedirs(d)
        calls.append(d)
        n = max(1, int(round((t1 - t0) * fps)))
        pic = Image.open(os.path.join(page, 'assets', 'start.png')).convert('RGB')
        paths = []
        for k in range(n):
            paths.append(os.path.join(d, '%04d.png' % (k + 1)))
            pic.save(paths[-1])
        with open(os.path.join(d, C.EYE_TEXT_FILE), 'w', encoding='utf-8') as fh:       # области текста этой полосы
            json.dump({'frames': [{'dom': [], 'canvas': []} for _ in range(n)]}, fh)
        return paths

    real, lock = strip.frames, os.environ.get('MOTION_CHROME_LOCK')
    strip.frames = fake_frames
    os.environ['MOTION_CHROME_LOCK'] = os.path.join(root, 'lock')
    try:
        a = C.eye(_ctx(root, out, film, page_only=True))
        check(len(calls) == 1, 'первая проверка страницы снимает кадры один раз, запросов: %d' % len(calls))
        C.eye(_ctx(root, out, film, page_only=True))
        check(len(calls) == 1, 'та же страница — кадры из кэша, а запросов стало %d' % len(calls))
        Image.new('RGB', (W, H), (30, 30, 200)).save(os.path.join(out, 'assets', 'start.png'))
        b = C.eye(_ctx(root, out, film, page_only=True))
        check(len(calls) == 2, 'картинку заменили под тем же именем — кадры обязаны сняться заново, запросов: %d' % len(calls))
        was = Image.open(a['frames'][0]['file']).convert('RGB').getpixel((5, 5))
        now = Image.open(b['frames'][0]['file']).convert('RGB').getpixel((5, 5))
        check(was == (200, 30, 30) and now == (30, 30, 200), 'проверка смотрит не тот кадр: до замены %s, после %s' % (was, now))
    finally:
        strip.frames = real
        if lock is None:
            os.environ.pop('MOTION_CHROME_LOCK', None)
        else:
            os.environ['MOTION_CHROME_LOCK'] = lock


def test_cleanup():
    for d in _tmp:
        shutil.rmtree(d, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(run_module(globals()))
