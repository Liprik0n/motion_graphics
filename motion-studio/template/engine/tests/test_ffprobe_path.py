# -*- coding: utf-8 -*-
"""Какой ffprobe получает HyperFrames: на Windows — заглушка шаблона, на остальных системах — настоящий из PATH.

    python engine/tests/test_ffprobe_path.py

Ожидания: заглушка `engine/video/tools/ffprobe.exe` — программа Windows, на Linux и macOS она не запустится. Поэтому
сборка (`engine/video/build.py ensure_ffprobe_stub`) и вырезка моделью (`engine/tools/cutout.py ffprobe_path`) не на
Windows отдают путь к `ffprobe` из PATH, а без него отказывают одной строкой с подсказкой поставить ffmpeg; на
Windows поведение прежнее — путь к заглушке. Платформа и PATH здесь подставные, ни ffprobe, ни браузер не запускаются.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import ENGINE, VIDEO, check, run_module   # noqa: E402

sys.path.insert(0, str(ENGINE))
sys.path.insert(0, str(VIDEO))
sys.path.insert(0, str(ENGINE / 'tools'))
import build    # noqa: E402
import cutout   # noqa: E402

STUB = VIDEO / 'tools' / 'ffprobe.exe'


class FakePath:
    """PATH из одной временной папки; with_ffprobe — положить в неё файл ffprobe, который найдёт shutil.which."""
    def __init__(self, with_ffprobe):
        self.with_ffprobe = with_ffprobe

    def __enter__(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='ms-ffprobe-'))
        self.old = os.environ.get('PATH', '')
        self.exe = self.tmp / ('ffprobe.exe' if os.name == 'nt' else 'ffprobe')
        if self.with_ffprobe:
            self.exe.write_bytes(b'')
            os.chmod(self.exe, 0o755)
        os.environ['PATH'] = str(self.tmp)
        return self

    def __exit__(self, *exc):
        os.environ['PATH'] = self.old
        shutil.rmtree(self.tmp, ignore_errors=True)


def _same(a, b):
    return os.path.normcase(os.path.abspath(str(a))) == os.path.normcase(os.path.abspath(str(b)))


def _refusal(fn):
    try:
        fn(windows=False)
    except SystemExit as e:
        return str(e)
    return None


def test_build_takes_real_ffprobe_off_windows():
    with FakePath(True) as p:
        got = build.ensure_ffprobe_stub(windows=False)
        check(_same(got, p.exe), 'не на Windows сборка берёт ffprobe из PATH: %s, а в PATH лежит %s' % (got, p.exe))


def test_build_refuses_without_ffprobe_off_windows():
    with FakePath(False):
        msg = _refusal(build.ensure_ffprobe_stub)
        check(msg is not None and 'ffprobe' in msg and 'ffmpeg' in msg and '\n' not in msg.strip(),
              'без ffprobe в PATH — отказ одной строкой с подсказкой поставить ffmpeg: %r' % msg)


def test_build_keeps_stub_on_windows():
    with FakePath(True):
        got = build.ensure_ffprobe_stub(windows=True)
        check(STUB.is_file() and _same(got, STUB), 'на Windows сборка отдаёт заглушку шаблона, как раньше: %s' % got)


def test_cutout_takes_real_ffprobe_off_windows():
    with FakePath(True) as p:
        got = cutout.ffprobe_path(windows=False)
        check(_same(got, p.exe), 'не на Windows вырезка берёт ffprobe из PATH: %s, а в PATH лежит %s' % (got, p.exe))


def test_cutout_refuses_without_ffprobe_off_windows():
    with FakePath(False):
        msg = _refusal(cutout.ffprobe_path)
        check(msg is not None and 'ffprobe' in msg and 'ffmpeg' in msg and '\n' not in msg.strip(),
              'без ffprobe в PATH — отказ одной строкой с подсказкой поставить ffmpeg: %r' % msg)


def test_cutout_keeps_stub_on_windows():
    with FakePath(True):
        got = cutout.ffprobe_path(windows=True)
        check(_same(got, STUB), 'на Windows вырезка отдаёт заглушку шаблона, как раньше: %s' % got)


def test_platform_is_detected_by_default():
    """Без подставной платформы функции смотрят на настоящую: на этой машине ответ тот же, что с её признаком."""
    with FakePath(True):
        check(_same(build.ensure_ffprobe_stub(), build.ensure_ffprobe_stub(windows=os.name == 'nt')),
              'сборка: платформа по умолчанию — настоящая')
        check(_same(cutout.ffprobe_path(), cutout.ffprobe_path(windows=os.name == 'nt')),
              'вырезка: платформа по умолчанию — настоящая')


if __name__ == '__main__':
    sys.exit(run_module(globals()))
