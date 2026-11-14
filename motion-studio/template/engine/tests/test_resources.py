# -*- coding: utf-8 -*-
"""Перед любым рендером печатается свободное место на диске и ОЗУ.

    python engine/tests/test_resources.py

Ожидание: строка называет свободные ГБ диска той папки, куда пойдут кадры (как shutil.disk_usage), и
свободную / всего ОЗУ; build.py и assemble.py печатают её до рендера (их тексты зовут resources.report).
"""
import re
import shutil
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import ROOT, ENGINE, check, run_module   # noqa: E402

sys.path.insert(0, str(ENGINE))


def test_report_names_disk_and_ram():
    import resources
    line = resources.report(str(ROOT))
    check('диск' in line and 'ОЗУ' in line, 'в строке нет диска или ОЗУ: %s' % line)
    free = shutil.disk_usage(str(ROOT)).free / 1e9
    m = re.search(r'диск \S+ — свободно ([\d.,]+) ГБ', line)
    check(m and abs(float(m.group(1).replace(',', '.')) - free) < 1.0, 'свободно на диске ≠ disk_usage (%.1f): %s' % (free, line))
    m = re.search(r'ОЗУ: свободно ([\d.,]+) из ([\d.,]+) ГБ', line)
    check(m and 0 < float(m.group(1).replace(',', '.')) <= float(m.group(2).replace(',', '.')), 'ОЗУ не названа числами: %s' % line)


def test_render_entry_points_print_it():
    build = (ENGINE / 'video' / 'build.py').read_text(encoding='utf-8')
    check(re.search(r'def render\(.*?\n(.*\n){0,12}?.*resources\.report\(', build), 'build.py render() не печатает ресурсы в начале')
    asm = (ENGINE / 'video' / 'assemble.py').read_text(encoding='utf-8')
    check('resources.report(' in asm, 'assemble.py не печатает ресурсы перед кодированием')


if __name__ == '__main__':
    sys.exit(run_module(globals()))
