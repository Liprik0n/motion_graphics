# -*- coding: utf-8 -*-
"""Общее для тестов движка: пути, питон, мини-раннер без pytest (на машине его нет).

Тест — файл test_*.py с функциями test_*(); запуск одного файла — `python engine/tests/test_<имя>.py`, всех тестов
движка — `python <скил>/tools/check_skill.py` (в своей копии движка — `python engine/tools/check_all.py --engine`).
Регистрировать тест нигде не надо: его находят обходом; тесту с браузером нужна строка `NEEDS_CHROME = True`.
Каждая функция печатает строку ok / FAIL; код выхода 1 при провале.
"""
import os
import sys
import traceback
from pathlib import Path

sys.dont_write_bytecode = True
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

ENGINE = Path(__file__).resolve().parents[1]        # <проект>/engine
ROOT = ENGINE.parent                                # папка над engine/ (в ней project/)
VIDEO = ENGINE / 'video'
PY = sys.executable


class Fail(AssertionError):
    pass


def check(cond, msg):
    if not cond:
        raise Fail(msg)


def run_module(mod_globals):
    """Прогнать все test_* модуля по порядку объявления; вернуть код выхода."""
    names = [n for n in mod_globals if n.startswith('test_') and callable(mod_globals[n])]
    bad = 0
    for n in names:
        try:
            mod_globals[n]()
            print('  ok   %s' % n)
        except Fail as e:
            bad += 1
            print('  FAIL %s: %s' % (n, e))
        except Exception:
            bad += 1
            print('  FAIL %s: исключение\n%s' % (n, traceback.format_exc()[-1500:]))
    print('%s: %d тестов, провалов %d' % (os.path.basename(mod_globals.get('__file__', '?')), len(names), bad))
    return 1 if bad else 0
