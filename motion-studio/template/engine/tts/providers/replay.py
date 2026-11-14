# -*- coding: utf-8 -*-
"""Готовые записи вместо синтеза: человек, другой сервис, прошлый проект.

Звук берётся из папки `voices.json["replay"]["dir"]` (путь от папки `project/`)
по указателю `index.json` в ней: `{"текст запроса": "файл.mp3"}`. Нет записи для
текста — отказ, а не тишина. Сеть не открывается. Записи — те же mp3, что ушли
бы в `reply/`, поэтому проверки промера (`check_audio.py`) работают на них так же,
как на синтезе.
"""

import json
import os

from providers import Provider as Base


class Provider(Base):
    name = 'replay'
    emotions = None

    def _dir(self):
        rel = (self.cfg.get('replay') or {}).get('dir')
        if not rel:
            raise SystemExit('voices.json: для provider replay нужен replay.dir')
        return os.path.join(self.cfg['_project_dir'], rel)

    def _index(self):
        path = os.path.join(self._dir(), 'index.json')
        if not os.path.exists(path):
            raise SystemExit('replay: нет указателя %s' % path)
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)

    def list_voices(self):
        return [{'voice': vid, 'label': v.get('label', ''), 'available': True,
                 'total': len(self.cfg['voices'])}
                for vid, v in self.cfg['voices'].items()]

    def synthesize(self, text, voice_cfg, emotion, speed, pitch):
        name = self._index().get(text)
        if not name:
            raise SystemExit('replay: нет записи для текста %r' % text[:60])
        with open(os.path.join(self._dir(), name), 'rb') as fh:
            return fh.read()

    def price_chars(self, text):
        return 0

    def cache_params(self, voice_cfg):
        return {'replay_dir': (self.cfg.get('replay') or {}).get('dir'),
                'voice_env': voice_cfg.get('voice_env')}
