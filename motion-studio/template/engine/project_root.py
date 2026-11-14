# -*- coding: utf-8 -*-
"""Корень проекта — одно правило для всех точек входа движка (видео, озвучка, звук, проверки).

    --project DIR  (или --project=DIR)  →  переменная окружения MOTION_PROJECT  →  <шаблон>/project

Корень проекта — папка с project.json; все пути проекта (`project.json paths.*`) считаются
от неё, в том числе выходы: `paths.out` (видео, звук фильма) и `paths.voices_out` (озвучка).
<шаблон> — папка над engine/: этот файл лежит в <шаблон>/engine/project_root.py.

    import project_root
    root, rest = project_root.split_argv(sys.argv[1:])   # root — Path, rest — argv без --project
    root = project_root.resolve(value)                    # value: явная папка или None
"""
import os
from pathlib import Path

ENGINE = Path(__file__).resolve().parent
TEMPLATE = ENGINE.parent
DEFAULT = TEMPLATE / 'project'
ENV = 'MOTION_PROJECT'
RULE = '--project → %s → <шаблон>/project' % ENV


def resolve(value=None):
    """Папка проекта по правилу: явное значение → MOTION_PROJECT → <шаблон>/project."""
    if value:
        return Path(value).resolve()
    env = os.environ.get(ENV)
    if env:
        return Path(env).resolve()
    return DEFAULT.resolve()


def split_argv(argv):
    """(папка проекта, argv без --project). Понимает `--project DIR` и `--project=DIR`;
    флаг без значения, пустое значение или повтор флага — отказ с объяснением."""
    rest, value, seen = [], None, 0
    args = list(argv)
    i = 0
    while i < len(args):
        a = args[i]
        if a == '--project' or a.startswith('--project='):
            seen += 1
            if a == '--project':
                if i + 1 >= len(args) or args[i + 1].startswith('--'):
                    raise SystemExit('после --project нужна папка проекта (%s)' % RULE)
                value = args[i + 1]
                i += 2
            else:
                value = a.split('=', 1)[1]
                i += 1
            if not value:
                raise SystemExit('--project с пустым значением (%s)' % RULE)
            continue
        rest.append(a)
        i += 1
    if seen > 1:
        raise SystemExit('--project указан %d раза — нужен один (%s)' % (seen, RULE))
    return resolve(value), rest
