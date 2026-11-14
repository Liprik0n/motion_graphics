# -*- coding: utf-8 -*-
"""Условие позы V25 на настоящей странице: при поднятой руке опущенная той же стороны скрыта.

    python engine/video/tests/test_pose.py        (≈ 30 с: две сборки страницы пробы наборов, под замком Chrome)

Ожидание — из класса дефектов 35 скила (checklists/defect-classes.md «Лишняя часть тела в позе») и урока
lessons.md, строка 49: «у позы с поднятой рукой опущенная рука той же стороны скрыта; условие позы с порчей заводится
вместе с первым жестом». Здесь проверяется вся цепочка, а не только условие на подставленных данных (это делают
быстрые порчи check.py demo --red): разметка data-limb → промер DOM (limbs) → строка V25.
  - сцена-проба kit-probe (манекен поднимает правую руку, опущенную прячет): V25 зелёное и не SKIP;
  - та же сцена, где опущенную руку перестали прятать: V25 красное, названы сцена, герой и сторона.
Работает на копии project/ во временной папке; поставка не трогается.
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

BUILD, CHECK = VIDEO / 'build.py', VIDEO / 'check.py'
HIDE = "    api.setAttr(st.querySelector('[data-limb$=\":right:down\"]'), 'visibility', raised ? 'hidden' : 'inherit');\n"
STATE = {}


def _run(script, *args):
    env = dict(os.environ)
    env.pop('MOTION_PROJECT', None)
    r = subprocess.run([PY, str(script)] + [str(a) for a in args], capture_output=True, text=True, encoding='utf-8',
                       errors='replace', env=env)
    return r.returncode, r.stdout + r.stderr


def _proj():
    if 'proj' not in STATE:
        tmp = tempfile.mkdtemp(prefix='pose_test_')
        proj = Path(tmp) / 'project'
        shutil.copytree(TEMPLATE / 'project', proj, ignore=shutil.ignore_patterns('out', '.env', '__pycache__'))
        STATE.update(tmp=tmp, proj=proj)
    return STATE['proj']


def _v25(proj):
    code, out = _run(BUILD, 'kits', '--page', '--style', 'none', '--project', proj)
    check(code == 0, 'сборка пробы наборов упала: %s' % out[-600:])
    code, out = _run(CHECK, 'kits', '--page', '--style', 'none', '--project', proj)
    return [l for l in out.splitlines() if 'V25' in l], out


def test_two_arms_pass_and_are_measured():
    lines, out = _v25(_proj())
    check(lines and lines[0].startswith('OK   V25'), 'на манекене с двумя руками V25 не зелёное (или SKIP): %s' % (lines or out[-400:]))


def test_third_arm_is_red():
    proj = _proj()
    mk = proj / 'scenes' / 'kit-probe' / 'markup.html'
    text = mk.read_text(encoding='utf-8')
    check(HIDE in text, 'в разметке пробы нет строки, прячущей опущенную руку, — тест устарел')
    mk.write_text(text.replace(HIDE, ''), encoding='utf-8')
    lines, out = _v25(proj)
    want = 'V25 поза: kit-probe — у «maneken» видны и поднятая, и опущенная конечность стороны right'
    check(any(l.startswith('FAIL') and want in l for l in lines), 'третья рука не покраснела своей строкой: %s' % (lines or out[-400:]))


def test_cleanup():
    if STATE.get('tmp'):
        shutil.rmtree(STATE['tmp'], ignore_errors=True)


if __name__ == '__main__':
    sys.exit(run_module(globals()))
