# -*- coding: utf-8 -*-
"""Поправка громкости по голосу — одно место: `project/voices.json`, поле `voices.<id>.gain_db`.

Её применяют там, где реплики сводятся (видео, музыка), а не перегенерацией:
`reply/` обязан совпадать с `cache/` байт в байт. Охрана — `check_audio.py`
(медианы голосов после поправки ≤ 0,5 дБ) и проверка микса.

    from voice_gain import gain_db;  gain_db('b')          # → 2.1
    python voice_gain.py [--project DIR]                   # печать всех поправок
"""

import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))
import project_root   # noqa: E402


def gains(project_dir=None):
    """{голос: дБ}. Папка проекта — явная, иначе общее правило движка (engine/project_root.py).
    У голоса нет gain_db — отказ с именем поля: тихий 0 дБ спрятал бы забытую поправку."""
    pdir = project_root.resolve(project_dir)
    with open(pdir / 'voices.json', encoding='utf-8-sig') as fh:
        cfg = json.load(fh)
    out = {}
    for vid, v in (cfg.get('voices') or {}).items():
        if v.get('gain_db') is None:
            raise SystemExit('voices.json: нет обязательного поля voices.%s.gain_db' % vid)
        out[vid] = float(v['gain_db'])
    return out


def gain_db(voice, project_dir=None):
    table = gains(project_dir)
    if voice not in table:
        raise SystemExit('voice_gain: голоса %r нет в voices.json' % (voice,))
    return table[voice]


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    pdir, _ = project_root.split_argv(sys.argv[1:])
    for vid, g in gains(pdir).items():
        print('%s %+.2f дБ' % (vid, g))
