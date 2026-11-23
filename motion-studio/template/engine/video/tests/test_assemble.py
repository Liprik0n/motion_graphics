# -*- coding: utf-8 -*-
"""Склейка engine/video/assemble.py: куски монтажного листа → один mp4 одним кодированием.

    python engine/video/tests/test_assemble.py

Ожидания — из правил скила (process/08-render-qa.md «Рендер: куски…», lessons.md строка 52), а не из кода склейки:
  - склейка = сумма кадров кусков ± 1 кадр, в порядке листа, полотно и частота кадров проекта, h264 + AAC стерео;
  - кусок без отметки и кусок, чья страница изменилась после рендера, — отказ с командой перерендера;
  - пересборка страницы ТЕМИ ЖЕ байтами кадры не портит: кусок берётся (полный прогон проверок не стоит рендера);
  - звук другой длины — отказ (молча под картинку не подгоняется); в пределах кадра — проходит;
  - у куска-фильма нет mix.m4a — отказ с командой сведения; --silent — тишина;
  - --check ничего не пишет.
Chrome здесь не нужен: куски — PNG, сделанные PIL; проект — временная папка с project.json и montage.json.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

VIDEO = Path(__file__).resolve().parents[1]
ENGINE = VIDEO.parent
sys.path.insert(0, str(ENGINE / 'tests'))
from _util import PY, check, run_module   # noqa: E402

sys.path.insert(0, str(VIDEO))
import stamp   # noqa: E402

ASM = VIDEO / 'assemble.py'
FPS, W, H = 30, 320, 180


def ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def _project(tmp, sheet):
    """Временный проект: полотно 320×180 px, 30 к/с, лист «clip»."""
    proj = os.path.join(tmp, 'project')
    os.makedirs(proj)
    with open(os.path.join(proj, 'project.json'), 'w', encoding='utf-8') as fh:
        json.dump({'fps': FPS, 'canvas': {'w': W, 'h': H, 'px_per_in': 96}, 'paths': {'out': 'out'}}, fh)
    _sheet(proj, sheet)
    return proj


def _sheet(proj, sheet):
    with open(os.path.join(proj, 'montage.json'), 'w', encoding='utf-8') as fh:
        json.dump({'_comment': 'тест', 'clip': sheet}, fh)


def _film(proj, name, n, rgb, stamped=True):
    """Кусок-фильм, как его кладёт build.py --png: страница, film.json, кадры, отметка."""
    from PIL import Image
    d = os.path.join(proj, 'out', name)
    os.makedirs(os.path.join(d, 'frames'))
    os.makedirs(os.path.join(d, 'assets'))
    for k in range(n):
        Image.new('RGB', (W, H), rgb).save(os.path.join(d, 'frames', 'frame_%06d.png' % (k + 1)))
    with open(os.path.join(d, 'film.json'), 'w', encoding='utf-8') as fh:
        json.dump({'film': name, 'fps': FPS, 'duration': n / FPS}, fh)
    with open(os.path.join(d, 'index.html'), 'w', encoding='utf-8') as fh:
        fh.write('<html><body>%s</body></html>' % name)
    with open(os.path.join(d, 'assets', 'a.css'), 'w', encoding='utf-8') as fh:
        fh.write('body{}')
    if stamped:
        stamp.write(d, n, n, FPS, (W, H))
    return d


def _tone(path, sec):
    subprocess.run([ffmpeg(), '-v', 'error', '-y', '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=44100:duration=%s' % sec,
                    '-ac', '2', '-c:a', 'aac', path], check=True)


def _run(proj, *args):
    env = dict(os.environ)
    env.pop('MOTION_PROJECT', None)
    r = subprocess.run([PY, str(ASM), '--project', proj] + list(args), capture_output=True, text=True, encoding='utf-8',
                       errors='replace', env=env)
    return r.returncode, r.stdout + r.stderr


def _probe(path):
    v = subprocess.run([ffmpeg(), '-hide_banner', '-i', path, '-map', '0:v:0', '-c', 'copy', '-f', 'null', '-'],
                       capture_output=True, text=True, encoding='utf-8', errors='replace').stderr
    fr = re.findall(r'frame=\s*(\d+)', v)
    return int(fr[-1]) if fr else None, ' '.join(l.strip() for l in v.splitlines() if 'Stream #' in l)


def _frame_rgb(path, t):
    """Средний цвет кадра mp4 в момент t."""
    from PIL import Image, ImageStat
    png = path + '.%d.png' % int(t * 1000)
    subprocess.run([ffmpeg(), '-v', 'error', '-y', '-ss', '%.4f' % t, '-i', path, '-frames:v', '1', png], check=True)
    return ImageStat.Stat(Image.open(png).convert('RGB')).mean


def _two(tmp, **sheet):
    proj = _project(tmp, dict({'pieces': [{'film': 'red'}, {'film': 'blue'}]}, **sheet))
    _film(proj, 'red', 12, (200, 30, 30))
    _film(proj, 'blue', 18, (30, 30, 200))
    return proj


def _tmp():
    return tempfile.mkdtemp(prefix='asm_test_')


def test_length_order_and_format():
    tmp = _tmp()
    try:
        proj = _two(tmp)
        code, out = _run(proj, 'clip', '--silent', '--draft')
        check(code == 0, 'склейка двух кусков упала: %s' % out[-500:])
        dst = os.path.join(proj, 'out', 'final', 'clip.mp4')
        check(os.path.exists(dst), 'нет %s' % dst)
        fr, streams = _probe(dst)
        check(fr is not None and abs(fr - 30) <= 1, 'кадров %s, а куски 12 + 18 = 30' % fr)
        check(re.search(r'Video: h264 \(High\).*yuv420p.*%dx%d.*%d fps' % (W, H, FPS), streams), 'видео не h264 %d×%d %d к/с: %s' % (W, H, FPS, streams))
        first, last = _frame_rgb(dst, 0.1), _frame_rgb(dst, 0.8)
        check(first[0] > first[2] + 60, 'первый кусок листа — красный, а кадр в 0,1 с: %s' % [round(c) for c in first])
        check(last[2] > last[0] + 60, 'второй кусок листа — синий, а кадр в 0,8 с: %s' % [round(c) for c in last])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _film_by_scenes(proj, name, scenes):
    """Кусок-фильм с кэшем кадров по сценам: frames/<сцена>/frame_%06d.png, номера сквозные по фильму (interfaces
    сборки, «Рендер»); scenes — [(id, кадров, цвет)]."""
    from PIL import Image
    d = _film(proj, name, 0, (0, 0, 0), stamped=False)
    k, total = 0, sum(n for _, n, _ in scenes)
    for sid, n, rgb in scenes:
        os.makedirs(os.path.join(d, 'frames', sid))
        for _ in range(n):
            k += 1
            Image.new('RGB', (W, H), rgb).save(os.path.join(d, 'frames', sid, 'frame_%06d.png' % k))
    with open(os.path.join(d, 'film.json'), 'w', encoding='utf-8') as fh:
        json.dump({'film': name, 'fps': FPS, 'duration': total / FPS}, fh)
    stamp.write(d, total, total, FPS, (W, H))
    return d


def test_piece_laid_out_by_scenes_keeps_order_and_length():
    tmp = _tmp()
    try:
        proj = _project(tmp, {'pieces': [{'film': 'split'}]})
        # папки сцен по алфавиту идут не в порядке фильма: порядок кадров задают номера, а не имена папок
        _film_by_scenes(proj, 'split', [('z-first', 6, (200, 30, 30)), ('m-second', 9, (30, 200, 30)), ('a-third', 3, (30, 30, 200))])
        code, out = _run(proj, 'clip', '--silent', '--draft')
        check(code == 0, 'склейка куска с кадрами по сценам упала: %s' % out[-500:])
        dst = os.path.join(proj, 'out', 'final', 'clip.mp4')
        fr, _ = _probe(dst)
        check(fr is not None and abs(fr - 18) <= 1, 'кадров %s, а сцены 6 + 9 + 3 = 18' % fr)
        a, b, c = _frame_rgb(dst, 2.5 / FPS), _frame_rgb(dst, 10.5 / FPS), _frame_rgb(dst, 16.5 / FPS)
        check(a[0] > a[1] + 60 and a[0] > a[2] + 60, 'кадр 3 — первая сцена (красная), а он %s' % [round(x) for x in a])
        check(b[1] > b[0] + 60 and b[1] > b[2] + 60, 'кадр 11 — вторая сцена (зелёная), а он %s' % [round(x) for x in b])
        check(c[2] > c[0] + 60 and c[2] > c[1] + 60, 'кадр 17 — третья сцена (синяя), а он %s' % [round(x) for x in c])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_piece_with_a_hole_in_frame_numbers_refuses():
    tmp = _tmp()
    try:
        proj = _project(tmp, {'pieces': [{'film': 'split', 'partial': True}]})
        d = _film_by_scenes(proj, 'split', [('one', 6, (200, 30, 30)), ('two', 6, (30, 200, 30))])
        os.remove(os.path.join(d, 'frames', 'two', 'frame_000009.png'))
        stamp.write(d, 11, 12, FPS, (W, H))            # отметка согласна с диском: отказать должен счёт номеров
        _refuses(proj, 'не подряд')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _refuses(proj, word, *args):
    code, out = _run(proj, 'clip', '--check', *(args or ('--silent',)))
    check(code != 0, 'сухой прогон прошёл, а должен отказать (%s): %s' % (word, out[-300:]))
    check(word in out, 'в отказе нет «%s»: %s' % (word, out[-400:]))


def test_frames_without_stamp_refuse():
    tmp = _tmp()
    try:
        proj = _two(tmp)
        os.remove(os.path.join(proj, 'out', 'red', 'frames', 'stamp.json'))
        _refuses(proj, 'build.py red --png')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_page_changed_after_render_refuses():
    tmp = _tmp()
    try:
        proj = _two(tmp)
        with open(os.path.join(proj, 'out', 'blue', 'index.html'), 'a', encoding='utf-8') as fh:
            fh.write('<!-- сцену поправили -->')
        _refuses(proj, 'build.py blue --png')
        code, out = _run(proj, 'clip', '--check', '--silent')
        check('index.html' in out, 'отказ не называет, что изменилось: %s' % out[-300:])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_same_page_rebuilt_keeps_piece():
    """Урок 52: полный прогон проверок пересобирает страницы — кадры при этом остаются годными."""
    tmp = _tmp()
    try:
        proj = _two(tmp)
        for name in ('red', 'blue'):                       # «пересборка»: те же байты записаны заново
            for f in ('index.html', 'film.json', os.path.join('assets', 'a.css')):
                p = os.path.join(proj, 'out', name, f)
                data = open(p, 'rb').read()
                os.remove(p)
                open(p, 'wb').write(data)
        code, out = _run(proj, 'clip', '--check', '--silent')
        check(code == 0, 'после пересборки той же страницы кусок отвергнут: %s' % out[-400:])
        check(os.path.isdir(os.path.join(proj, 'out', 'red', 'frames')), 'кадры пропали')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_asset_changed_refuses():
    tmp = _tmp()
    try:
        proj = _two(tmp)
        with open(os.path.join(proj, 'out', 'red', 'assets', 'a.css'), 'w', encoding='utf-8') as fh:
            fh.write('body{color:red}')
        _refuses(proj, 'assets')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_partial_piece_refuses_unless_allowed():
    tmp = _tmp()
    try:
        proj = _two(tmp)
        d = os.path.join(proj, 'out', 'red')
        for k in (10, 11, 12):
            os.remove(os.path.join(d, 'frames', 'frame_%06d.png' % k))
        stamp.write(d, 9, 12, FPS, (W, H))                 # пробный кусок: build.py red --png --frames 9
        _refuses(proj, 'неполный')
        _sheet(proj, {'pieces': [{'film': 'red', 'partial': True}, {'film': 'blue'}]})
        code, out = _run(proj, 'clip', '--check', '--silent')
        check(code == 0 and '27 кадров' in out, 'пробный кусок с partial не взят: %s' % out[-300:])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_piece_audio_missing_refuses_and_silent_passes():
    tmp = _tmp()
    try:
        proj = _two(tmp)
        code, out = _run(proj, 'clip', '--check')
        check(code != 0 and 'music.py red' in out, 'без mix.m4a куска склейка не назвала команду сведения: %s' % out[-300:])
        _tone(os.path.join(proj, 'out', 'red', 'mix.m4a'), 12 / FPS)
        _tone(os.path.join(proj, 'out', 'blue', 'mix.m4a'), 18 / FPS)
        code, out = _run(proj, 'clip', '--draft')
        check(code == 0, 'склейка со звуком кусков упала: %s' % out[-500:])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_piece_audio_of_other_length_refuses():
    tmp = _tmp()
    try:
        proj = _two(tmp)
        _tone(os.path.join(proj, 'out', 'red', 'mix.m4a'), 1.5)        # кусок 0,4 с
        _tone(os.path.join(proj, 'out', 'blue', 'mix.m4a'), 18 / FPS)
        code, out = _run(proj, 'clip', '--check')
        check(code != 0 and 'пересведи' in out, 'звук куска другой длины не отвергнут: %s' % out[-300:])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_one_audio_length():
    tmp = _tmp()
    try:
        proj = _two(tmp, audio='mix-all.m4a')
        _tone(os.path.join(proj, 'mix-all.m4a'), 2.0)                   # куски — 1,0 с
        code, out = _run(proj, 'clip', '--check')
        check(code != 0 and 'пересведи' in out, 'звук 2,0 с к кускам 1,0 с не отвергнут: %s' % out[-300:])
        _tone(os.path.join(proj, 'mix-all.m4a'), 1.0)
        code, out = _run(proj, 'clip', '--check')
        check(code == 0, 'звук длиной в куски отвергнут: %s' % out[-300:])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_external_frames_piece():
    from PIL import Image
    tmp = _tmp()
    try:
        proj = _two(tmp)
        ext = os.path.join(proj, 'capture', 'frames')
        os.makedirs(ext)
        for k in range(6):
            Image.new('RGB', (W, H), (30, 200, 30)).save(os.path.join(ext, 'f%05d.png' % k))
        with open(os.path.join(proj, 'capture', 'plan.json'), 'w', encoding='utf-8') as fh:
            json.dump({'frames': 6}, fh)
        piece = {'frames': 'capture/frames', 'pattern': 'f%05d.png', 'start': 0, 'expect': ['capture/plan.json']}
        _sheet(proj, {'pieces': [{'film': 'red'}, piece, {'film': 'blue'}]})
        code, out = _run(proj, 'clip', '--check', '--silent')
        check(code == 0 and '36 кадров' in out, 'кусок готовых кадров не взят (12 + 6 + 18 = 36): %s' % out[-300:])
        os.remove(os.path.join(ext, 'f00003.png'))
        _refuses(proj, 'не подряд')
        Image.new('RGB', (W, H), (30, 200, 30)).save(os.path.join(ext, 'f00003.png'))
        with open(os.path.join(proj, 'capture', 'plan.json'), 'w', encoding='utf-8') as fh:
            json.dump({'frames': 7}, fh)
        _refuses(proj, 'ждёт 7')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_check_writes_nothing():
    tmp = _tmp()
    try:
        proj = _two(tmp)
        code, out = _run(proj, 'clip', '--check', '--silent')
        check(code == 0 and 'сухой прогон' in out, 'сухой прогон не прошёл: %s' % out[-300:])
        check(not os.path.exists(os.path.join(proj, 'out', 'final')), '--check создал папку выхода')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_unknown_sheet_names_known():
    tmp = _tmp()
    try:
        proj = _two(tmp)
        code, out = _run(proj, 'net-takogo')
        check(code != 0 and 'clip' in out, 'неизвестный лист: отказ не называет существующие: %s' % out[-300:])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(run_module(globals()))
