# -*- coding: utf-8 -*-
"""render_pack.py verify: ожидаемое — только то, что записал make на этой машине.

    python engine/tests/test_render_verify.py

`return/` приходит с чужой машины целиком, вместе с expect.json. Если verify верит этому файлу, правка его на той
стороне даёт зелёное на любом видео. Ожидания: expect.json сверяется по sha256 с записью, которую
make оставил на этой машине (`<out>/<фильм>/render_pack.json`, поле packs[].expect_sha256), и ни путь по умолчанию
(рядом с отчётом), ни `--expect` на поправленный файл проверку не обходят; нет записи — тоже красное, а не доверие.

Без браузера: запись make тест кладёт сам в её формате (sha256 честного expect.json считает hashlib), видео собирает
ffmpeg из тестовой картинки, expect.json и report.json пишутся руками в формате пакета
(docs/render-pack.md скила). Что запись оставляет сам make и что честный рендер зелёный — в test_render_pack.py (с браузером).
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

sys.path.insert(0, str(ENGINE))
sys.path.insert(0, str(ENGINE / 'tools'))
import render_pack   # noqa: E402

TOOL = str(ENGINE / 'tools' / 'render_pack.py')
FILM = 'f'


def _video(path, seconds):
    r = subprocess.run([render_pack.ffmpeg(), '-y', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i',
                        'testsrc=s=640x360:r=30:d=%s' % seconds, '-pix_fmt', 'yuv420p', path], capture_output=True, text=True)
    check(r.returncode == 0 and os.path.exists(path), 'ffmpeg не собрал пробное видео: %s' % r.stderr[-300:])
    return path


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='\n') as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
        fh.write('\n')
    return path


def _case(tmp):
    """Проект с записью make, пакет на этой машине и заказ: 640×360, 30 кадр/с, 60 кадров."""
    proj = os.path.join(tmp, 'project')
    _write(os.path.join(proj, 'project.json'), {})
    expect = {'format': 1, 'film': FILM, 'page_sha256': 'a' * 64,
              'video': {'width': 640, 'height': 360, 'fps': 30.0, 'frames': 60, 'duration_sec': 2.0, 'film_duration_sec': 2.0},
              'strip_size': [160, 90], 'sig_grid': [16, 9], 'tolerance': {'frame_mad': 14, 'bad_share': 0.1, 'frames': 1},
              'strips': []}
    pack_expect = _write(os.path.join(tmp, 'pack', 'expect.json'), expect)
    with open(pack_expect, 'rb') as fh:
        sha = hashlib.sha256(fh.read()).hexdigest()
    _write(os.path.join(proj, 'out', FILM, 'render_pack.json'),
           {'format': 1, 'film': FILM, 'packs': [{'made_at': '2026-11-22T12:00:00', 'to': os.path.join(tmp, 'pack'),
                                                   'expect_sha256': sha}]})
    return proj, expect, pack_expect


def _returned(tmp, name, seconds, expect=None, expect_file=None):
    """Папка return/ с той стороны: видео, отчёт о нём и expect.json — копия файла пакета либо свой."""
    ret = os.path.join(tmp, name)
    os.makedirs(ret)
    video = _video(os.path.join(ret, 'video.mp4'), seconds)
    _write(os.path.join(ret, 'report.json'), {'format': 1, 'film': FILM, 'page_sha256': 'a' * 64,
                                              'video': render_pack.probe_video(video), 'machine': {}, 'strips': []})
    if expect_file:
        shutil.copyfile(expect_file, os.path.join(ret, 'expect.json'))
    else:
        _write(os.path.join(ret, 'expect.json'), expect)
    return ret


def _verify(proj, ret, expect=None):
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    env.pop('MOTION_PROJECT', None)
    args = [PY, TOOL, 'verify', os.path.join(ret, 'report.json'), os.path.join(ret, 'video.mp4'), '--project', proj]
    if expect:
        args += ['--expect', expect]
    r = subprocess.run(args, env=env, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=600)
    return r.returncode, (r.stdout + r.stderr).strip()


def test_verify_green_on_recorded_expect_and_red_on_edited_one():
    tmp = tempfile.mkdtemp(prefix='render_verify_test_')
    try:
        proj, expect, pack_expect = _case(tmp)
        honest = _returned(tmp, 'return-honest', 2, expect_file=pack_expect)
        code, out = _verify(proj, honest)
        check(code == 0 and 'зелёное' in out, 'честный результат с expect.json из пакета: код %d, %s' % (code, out[-400:]))
        # та сторона отрендерила половину и поправила expect.json под своё видео
        edited = dict(expect, video=dict(expect['video'], frames=30, duration_sec=1.0, film_duration_sec=1.0))
        cheat = _returned(tmp, 'return-edited', 1, expect=edited)
        for arg, how in ((None, 'рядом с отчётом'), (os.path.join(cheat, 'expect.json'), '--expect')):
            code, out = _verify(proj, cheat, arg)
            check(code == 1 and 'зелёное' not in out, 'поправленный expect.json (%s) принят: код %d, %s' % (how, code, out[-400:]))
            check('expect.json' in out and 'make' in out, 'красное не говорит, что expect.json не тот, что записал make: %s' % out[-400:])
            check('Traceback' not in out, 'трассировка: %s' % out[-400:])
        code, out = _verify(proj, cheat, pack_expect)
        check(code == 1 and 'видео другой длины' in out, 'с expect.json пакета на этой машине короткое видео не поймано: %s' % out[-400:])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_verify_red_without_make_record():
    """Проект, в котором пакет не собирался (или запись стёрта вместе с out/): подтвердить ожидаемое нечем — красное
    с подсказкой, а не доверие файлу из return/."""
    tmp = tempfile.mkdtemp(prefix='render_verify_test_')
    try:
        proj, _expect, pack_expect = _case(tmp)
        honest = _returned(tmp, 'return-honest', 2, expect_file=pack_expect)
        other = os.path.join(tmp, 'other-project')
        _write(os.path.join(other, 'project.json'), {})
        code, out = _verify(other, honest)
        check(code == 1 and 'зелёное' not in out, 'без записи make результат принят: код %d, %s' % (code, out[-400:]))
        check('make' in out and '--project' in out, 'красное не называет запись make и ключ --project: %s' % out[-400:])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(run_module(globals()))
