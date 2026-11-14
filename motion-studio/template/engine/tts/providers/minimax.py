# -*- coding: utf-8 -*-
"""MiniMax t2a_v2. Контракт замерен прогонами, а не взят из документации по памяти.

    POST https://api.minimax.io/v1/t2a_v2, Bearer <api_key>
    language_boost обязателен; output_format hex — звук в data.audio
    эмоции API: happy sad angry fearful disgusted surprised calm fluent whisper
                (Neutral в API нет: карта Neutral → calm живёт в voices.json)
    питч нейтрален на 0 (шкала −12…12, целые); скорость ступенчатая
    2042 — voice_id не принадлежит ключу: сначала --voices
    POST /v1/get_voice {"voice_type":"all"} — список голосов, не тарифицируется

Ключ и voice_id берутся из `.env` проекта по ИМЕНАМ из `voices.json`
(`provider_env.api_key`, `voices.<id>.voice_env`). Любой текст ответа или ошибки
проходит через `redact()` — значения всех переменных `.env` затираются.
"""

import binascii
import json
import urllib.error
import urllib.request

from envfile import redact  # noqa: F401  (redact — часть интерфейса провайдера)
from providers import Provider as Base

BASE = 'https://api.minimax.io/v1'
T2A_URL = BASE + '/t2a_v2'
VOICE_URL = BASE + '/get_voice'


class Provider(Base):
    name = 'minimax'
    emotions = ('happy', 'sad', 'angry', 'fearful', 'disgusted', 'surprised',
                'calm', 'fluent', 'whisper')

    @classmethod
    def env_names(cls, cfg):
        names = [cfg.get('provider_env', {}).get('api_key', 'MINIMAX_API_KEY')]
        names += [v['voice_env'] for v in cfg['voices'].values()]
        return names

    def _key(self):
        return self.env[self.cfg.get('provider_env', {}).get('api_key', 'MINIMAX_API_KEY')]

    def voice_id(self, voice_cfg):
        return self.env[voice_cfg['voice_env']]

    def _post(self, url, payload, timeout=180):
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        req = urllib.request.Request(url, data=body, method='POST')
        req.add_header('Authorization', 'Bearer %s' % self._key())
        req.add_header('Content-Type', 'application/json')
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode('utf-8', 'replace')
        # Каждый сбой превращается в отказ с затёртым текстом и БЕЗ цепочки исключений
        # (`from None`): TimeoutError, RemoteDisconnected, сброс соединения и прочее
        # иначе вышли бы трассировкой с эхом запроса. Был ли запрос тарифицирован —
        # неизвестно, поэтому текст говорит «проверьте расход», а не «ничего не ушло».
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read().decode('utf-8', 'replace')[:300]
            except Exception:
                detail = ''
            raise SystemExit('MiniMax ответил HTTP %s: %s'
                             % (exc.code, redact(detail, self.env))) from None
        except urllib.error.URLError as exc:
            raise SystemExit('MiniMax недоступен: %s' % redact(exc.reason, self.env)) from None
        except Exception as exc:
            raise SystemExit('MiniMax: обрыв запроса (%s: %s) — проверьте расход в кабинете '
                             'перед повтором' % (type(exc).__name__, redact(exc, self.env))) from None
        try:
            data = json.loads(raw)
        except ValueError as exc:
            raise SystemExit('MiniMax вернул не JSON: %s' % redact(exc, self.env)) from None
        base = data.get('base_resp') or {}
        code = base.get('status_code', 0)
        if code:
            hint = ''
            if code == 2042:
                hint = '. voice_id не принадлежит ключу: сначала «tts.py --voices»'
            raise SystemExit('MiniMax вернул код %s: %s%s'
                             % (code, redact(base.get('status_msg', ''), self.env), hint))
        return data

    def list_voices(self):
        """Голоса ключа. Запрос бесплатный. Наружу — только факт доступа, без id."""
        data = self._post(VOICE_URL, {'voice_type': 'all'}, timeout=60)
        have = set()
        for group in ('voice_cloning', 'voice_generation', 'system_voice'):
            for item in data.get(group) or []:
                vid = item.get('voice_id') or item.get('id')
                if vid:
                    have.add(vid)
        return [{'voice': vid_name, 'label': v.get('label', ''),
                 'available': self.voice_id(v) in have, 'total': len(have)}
                for vid_name, v in self.cfg['voices'].items()]

    def synthesize(self, text, voice_cfg, emotion, speed, pitch):
        payload = {
            'model': self.cfg['model'],
            'text': text,
            'stream': False,
            'language_boost': self.cfg.get('language', 'Russian'),
            'output_format': 'hex',
            'voice_setting': {'voice_id': self.voice_id(voice_cfg), 'speed': speed,
                              'vol': 1.0, 'pitch': pitch, 'emotion': emotion},
            'audio_setting': dict(self.cfg['audio_setting']),
        }
        data = self._post(T2A_URL, payload)
        hexed = (data.get('data') or {}).get('audio')
        if not hexed:
            raise SystemExit('MiniMax вернул ответ без звука')
        return binascii.unhexlify(hexed)

    def price_chars(self, text):
        # Тариф — знаки текста запроса (extra_info.usage_characters совпадал
        # с длиной на всех 198 репликах прошлого ролика).
        return len(text)

    def cache_params(self, voice_cfg):
        return {'model': self.cfg['model'], 'language': self.cfg.get('language', 'Russian'),
                'voice_id': self.voice_id(voice_cfg),
                'audio_setting': self.cfg['audio_setting']}
