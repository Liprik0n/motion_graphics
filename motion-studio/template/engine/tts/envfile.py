# -*- coding: utf-8 -*-
"""`.env` проекта без зависимостей и затирание его значений в любом выводе.

**Значения не печатаются нигде** — ни в логе, ни в ошибке, ни в манифесте. Наружу
выходят только имена переменных. Всё, что провайдер или ядро печатают из ответа
сервиса или из исключения, проходит через `redact()`.
"""

import io
import os
import re

REDACT_MIN_LEN = 4


def read_env_file(path):
    """Пары ключ-значение из файла `.env`; файла нет — пустой словарь."""
    env = {}
    if not os.path.exists(path):
        return env
    with io.open(path, encoding='utf-8') as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, value = line.split('=', 1)
            key = key.strip()
            if key.startswith('export '):
                key = key[len('export '):].strip()
            env[key] = parse_value(value)
    return env


def parse_value(raw):
    """Голое значение: кавычки сняты, хвостовой `  # комментарий` отброшен.

    В кавычках `#` — часть значения; без кавычек комментарий начинается с `#`
    после пробела (`a#b` — значение целиком, как у dotenv и shell).
    """
    raw = raw.strip()
    if raw[:1] in ('"', "'"):
        end = raw.find(raw[0], 1)
        if end > 0:
            return raw[1:end]
        return raw[1:]
    m = re.search(r'\s#', raw)
    if m:
        raw = raw[:m.start()]
    return raw.strip()


def require(env, names, path):
    """Нужные переменные на месте; иначе отказ с ИМЕНАМИ, без значений."""
    if not os.path.exists(path):
        raise SystemExit('нет файла .env (%s) — провайдеру нечем авторизоваться; '
                         'шаблон: .env.example рядом' % os.path.basename(os.path.dirname(path))
                         + os.sep + '.env')
    missing = [k for k in names if not env.get(k)]
    if missing:
        raise SystemExit('в .env не заполнены переменные: %s' % ', '.join(missing))


def redact(text, env):
    """Вырезать значения ВСЕХ переменных `.env`, а не только тех, что нужны провайдеру.

    Список нужных — про полноту файла, а не про секретность: `MINIMAX_GROUP_ID`
    провайдеру не нужен, но в вывод попасть не должен. Длинные значения затираются
    раньше коротких — короткое может оказаться куском длинного, и тогда от длинного
    остался бы открытый хвост.
    """
    text = str(text)
    for key, value in sorted(env.items(), key=lambda kv: -len(kv[1] or '')):
        if value and len(value) >= REDACT_MIN_LEN:
            text = text.replace(value, '<%s>' % key)
    return text
