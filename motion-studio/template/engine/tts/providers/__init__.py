# -*- coding: utf-8 -*-
"""Интерфейс провайдера синтеза. Ядро (`tts.py`) не знает, кто синтезирует.

Провайдер — модуль `providers/<имя>.py` с классом `Provider(cfg, env)`, где
`cfg` — весь `voices.json`, `env` — словарь `.env` проекта (может быть пустым).
Имя берётся из `voices.json["provider"]`. Новый провайдер — новый файл,
ядро не правится.

Обязательное:
    name                    имя в манифесте и в ключе кэша
    emotions                закрытый список эмоций провайдера или None
    env_names(cfg)          классметод: какие переменные .env нужны (имена)
    list_voices() -> list[dict]
    synthesize(text, voice_cfg, emotion, speed, pitch) -> bytes   (mp3)
    price_chars(text) -> int            сколько единиц выставят в счёт
    cache_params(voice_cfg) -> dict     всё, что влияет на звук, кроме текста,
                                        эмоции, скорости и питча (модель, голос,
                                        формат); входит в ключ кэша, не печатается
"""

import importlib


class Provider:
    name = 'base'
    emotions = None

    def __init__(self, cfg, env):
        self.cfg = cfg
        self.env = env

    @classmethod
    def env_names(cls, cfg):
        return []

    def list_voices(self):
        raise NotImplementedError

    def synthesize(self, text, voice_cfg, emotion, speed, pitch):
        raise NotImplementedError

    def price_chars(self, text):
        return len(text)

    def cache_params(self, voice_cfg):
        raise NotImplementedError


def provider_class(cfg):
    name = cfg.get('provider')
    if not name or not str(name).isidentifier():
        raise SystemExit('voices.json: поле provider пусто или не имя модуля: %r' % (name,))
    try:
        module = importlib.import_module('providers.%s' % name)
    except ModuleNotFoundError:
        raise SystemExit('нет провайдера providers/%s.py' % name)
    return module.Provider
