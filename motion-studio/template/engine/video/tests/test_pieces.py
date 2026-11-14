# -*- coding: utf-8 -*-
"""Кусок рендера — фильм: кадры с отметкой переживают пересборку страницы, устаревший кусок склейка не берёт.

    python engine/video/tests/test_pieces.py        (≈ 1 мин: страница демо, рендер 3 кадров HyperFrames, под замком Chrome)

Ожидания — из урока прошлого ролика (lessons.md скила, строка 52) и process/08-render-qa.md, а не из кода:
  - `build.py <фильм> --png` кладёт кадры и отметку frames/stamp.json;
  - пересборка страницы (`--page`, как в общем прогоне проверок) кадры НЕ удаляет, и склейка их берёт;
  - правка сцены после рендера → кадры на диске остаются, но склейка отказывает и называет команду перерендера;
  - `--frames N` без `--png` — отказ (mp4 из части кадров был бы короче звука).
Работает на копии project/ во временной папке; поставка не трогается. Нужен engine/video/node_modules.
"""
import json
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

BUILD, ASM = VIDEO / 'build.py', VIDEO / 'assemble.py'
N = 3
STATE = {}


def _run(script, *args):
    env = dict(os.environ)
    env.pop('MOTION_PROJECT', None)
    r = subprocess.run([PY, str(script)] + [str(a) for a in args], capture_output=True, text=True, encoding='utf-8',
                       errors='replace', env=env)
    return r.returncode, r.stdout + r.stderr


def _proj():
    """Копия проекта шаблона с листом «clip» из одного пробного куска demo; рендер — один раз на все тесты."""
    if 'proj' not in STATE:
        tmp = tempfile.mkdtemp(prefix='pieces_test_')
        proj = Path(tmp) / 'project'
        shutil.copytree(TEMPLATE / 'project', proj, ignore=shutil.ignore_patterns('out', '.env', '__pycache__'))
        (proj / 'montage.json').write_text(json.dumps({'clip': {'pieces': [{'film': 'demo', 'partial': True}]}}), encoding='utf-8')
        STATE.update(tmp=tmp, proj=proj)
        STATE['render'] = _run(BUILD, 'demo', '--png', '--frames', N, '--project', proj)
    return STATE['proj']


def _frames(proj):
    d = proj / 'out' / 'demo' / 'frames'
    return sorted(p.name for p in d.glob('frame_*.png')) if d.is_dir() else []


def test_png_piece_has_frames_and_stamp():
    proj = _proj()
    code, out = STATE['render']
    check(code == 0, 'build.py demo --png --frames %d упал: %s' % (N, out[-600:]))
    check(len(_frames(proj)) == N, 'кадров %d, а просили %d' % (len(_frames(proj)), N))
    sp = proj / 'out' / 'demo' / 'frames' / 'stamp.json'
    check(sp.exists(), 'рендер кадрами не оставил отметку frames/stamp.json')
    st = json.loads(sp.read_text(encoding='utf-8'))
    check(st.get('frames') == N and st.get('full', 0) > N, 'отметка не называет пробный кусок: %s' % st)
    check(not (proj / 'out' / 'demo' / 'video.mp4').exists(), '--png собрал mp4')


def test_page_rebuild_keeps_frames_and_piece_is_taken():
    proj = _proj()
    code, out = _run(BUILD, 'demo', '--page', '--project', proj)
    check(code == 0, 'пересборка страницы упала: %s' % out[-600:])
    check(len(_frames(proj)) == N, 'пересборка страницы удалила кадры куска (осталось %d из %d)' % (len(_frames(proj)), N))
    check('свежие' in out, 'сборка не сказала, что кадры после пересборки той же страницы годятся: %s' % out[-300:])
    code, out = _run(ASM, 'clip', '--check', '--silent', '--project', proj)
    check(code == 0, 'склейка отвергла кусок после пересборки той же страницы: %s' % out[-400:])


def test_assemble_makes_mp4_from_the_piece():
    proj = _proj()
    code, out = _run(ASM, 'clip', '--silent', '--draft', '--project', proj)
    check(code == 0 and 'зелёный' in out, 'склейка куска упала: %s' % out[-500:])
    check((proj / 'out' / 'final' / 'clip.mp4').exists(), 'нет out/final/clip.mp4')


def test_scene_edit_makes_piece_stale_but_keeps_frames():
    proj = _proj()
    mk = proj / 'scenes' / 'demo-a' / 'markup.html'
    mk.write_text(mk.read_text(encoding='utf-8') + '\n<!-- правка сцены после рендера -->\n', encoding='utf-8')
    code, out = _run(BUILD, 'demo', '--page', '--project', proj)
    check(code == 0, 'пересборка после правки сцены упала: %s' % out[-600:])
    check(len(_frames(proj)) == N, 'кадры удалены — отметка должна решать, а не удаление')
    check('устарели' in out and 'build.py demo --png' in out, 'сборка не сказала, что кадры устарели: %s' % out[-300:])
    code, out = _run(ASM, 'clip', '--check', '--silent', '--project', proj)
    check(code != 0 and 'build.py demo --png' in out, 'склейка взяла устаревший кусок: %s' % out[-400:])


def test_frames_flag_needs_png():
    proj = _proj()
    code, out = _run(BUILD, 'demo', '--frames', 5, '--project', proj)
    check(code != 0 and '--png' in out, '--frames без --png не отвергнут: %s' % out[-300:])


def test_cleanup():
    if STATE.get('tmp'):
        shutil.rmtree(STATE['tmp'], ignore_errors=True)


if __name__ == '__main__':
    sys.exit(run_module(globals()))
