# -*- coding: utf-8 -*-
"""Где проект и что в его конфигах. Абсолютных путей нет: корень — из расположения файла.

Раскладка: `<шаблон>/engine/tts/` (этот код), `<проект>/` (конфиги), `<проект>/out/tts/`
(кэш, реплики, сцены, манифест — `project.json paths.voices_out`, путь от папки проекта,
как и все `paths.*`: у видео, звука и озвучки один базовый каталог). Папка проекта — одно
правило движка (engine/project_root.py): `--project` → `MOTION_PROJECT` → `<шаблон>/project`.

Строки озвучки собираются здесь и только здесь: `text` — документ (`rows.json`),
`speech` — то, что уйдёт в синтез (`speech_edits.json[n].speech`, иначе `text`).
Ключ кэша считается от `speech`: платим за то, что ушло в запрос.
"""

import json
import sys
from pathlib import Path

ENGINE_TTS = Path(__file__).resolve().parent
sys.path.append(str(ENGINE_TTS.parent))
import project_root   # noqa: E402


def project_dir(argv=None):
    """Папка проекта из argv (общее правило движка); остальной argv разбирает вызывающий."""
    return project_root.split_argv(argv or [])[0]


def require(data, dotted, fname):
    cur = data
    for part in dotted.split('.'):
        if not isinstance(cur, dict) or cur.get(part) is None:
            raise SystemExit('%s: нет обязательного поля %s' % (fname, dotted))
        cur = cur[part]
    return cur


def read_json(path, default=None):
    if not Path(path).exists():
        if default is not None:
            return default
        raise SystemExit('нет файла %s' % path)
    with open(path, encoding='utf-8-sig') as fh:
        return json.load(fh)


class Project:
    def __init__(self, pdir):
        self.dir = Path(pdir)
        self.meta = read_json(self.dir / 'project.json')
        self.out = self.dir / require(self.meta, 'paths.voices_out', 'project.json')
        self.cache = self.out / 'cache'
        self.reply = self.out / 'reply'
        self.scene = self.out / 'scene'
        self.manifest = self.out / 'manifest.json'
        self.env_path = self.dir / '.env'
        self.voices_cfg = read_json(self.dir / 'voices.json')
        self.voices_cfg['_project_dir'] = str(self.dir)
        for vid, v in self.voices_cfg['voices'].items():
            v['id'] = vid
        self.pause_sec = float(require(self.meta, 'pause_sec', 'project.json'))

    def voice(self, vid):
        return self.voices_cfg['voices'][vid]

    def lines(self, emotions=None):
        rows = read_json(self.dir / 'rows.json')
        edits = read_json(self.dir / 'speech_edits.json', {})
        voices = self.voices_cfg['voices']
        out = []
        for r in rows:
            for field in ('n', 'scene', 'voice', 'emotion', 'text'):
                if field not in r:
                    raise SystemExit('rows.json: у строки %r нет поля %s' % (r.get('n'), field))
            if r['voice'] not in voices:
                raise SystemExit('строка %d: голоса %r нет в voices.json' % (r['n'], r['voice']))
            emap = voices[r['voice']].get('emotion_map', {})
            if r['emotion'] not in emap:
                raise SystemExit('строка %d: эмоции %r нет в emotion_map голоса %s'
                                 % (r['n'], r['emotion'], r['voice']))
            api = emap[r['emotion']]
            if emotions and api not in emotions:
                raise SystemExit('строка %d: эмоция %r вне закрытого списка провайдера'
                                 % (r['n'], api))
            edit = edits.get(str(r['n'])) or {}
            speech = edit.get('speech', r['text'])
            out.append({'n': r['n'], 'scene': r['scene'], 'voice': r['voice'],
                        'emotion': r['emotion'], 'api_emotion': api,
                        'text': r['text'], 'speech': speech})
        if [x['n'] for x in out] != list(range(1, len(out) + 1)):
            raise SystemExit('rows.json: нумерация строк не сквозная с 1')
        return out
