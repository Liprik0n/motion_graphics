# -*- coding: utf-8 -*-
"""Каталог источников и проверка материалов говорят одно: catalog/sources.md против engine/tools/check_materials.py.

    python tools/tests/test_sources_catalog.py

Каталог учит, как писать лицензию в materials.json; проверка решает, что зелёное. Разойдутся — человек запишет
название «как в каталоге» и получит красное (так и было: «Lottie Simple License», «Pixabay Content License»,
«Unsplash License», «SIL OFL 1.1»). Ожидания берутся из текста каталога, а не из кода проверки:
  - каждое название из таблицы «Как писать лицензию в materials.json» (столбцы «Писать в license» и «Так тоже
    принимается») проверка принимает;
  - у каждой разрешённой проверкой лицензии есть строка в таблице, и лишних строк в таблице нет;
  - поле, которое таблица называет обязательным (author, note), проверка требует — и только у этих строк;
  - каждое название из правила «Запрещены» проверка называет запрещённым.
Chrome и сеть не нужны.
"""
import json
import os
import re
import sys
import tempfile
from pathlib import Path

SKILL = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILL / 'template' / 'engine' / 'tests'))
from _util import check, run_module   # noqa: E402

sys.path.insert(0, str(SKILL / 'template' / 'engine' / 'tools'))
import check_materials   # noqa: E402

CATALOG = SKILL / 'catalog' / 'sources.md'
HEADING = '## Как писать лицензию в `materials.json`'
FORBIDDEN_RULE = '**Запрещены'


def _ticks(cell):
    return re.findall(r'`([^`]+)`', cell)


def _table():
    """Строки таблицы названий: [{write, also: [...], needs: {'author', 'note'}}]."""
    text = CATALOG.read_text(encoding='utf-8')
    check(HEADING in text, 'в catalog/sources.md нет раздела «%s»: каталог не называет, что принимает проверка' % HEADING)
    body = text.split(HEADING, 1)[1].split('\n## ', 1)[0]
    rows = []
    lines = [l for l in body.splitlines() if l.startswith('|')][2:]          # без шапки и черты под ней
    for line in lines:
        cells = [c.strip() for c in line.strip()[1:-1].split('|')]
        check(len(cells) == 4 and _ticks(cells[1]), 'строка таблицы названий не из четырёх столбцов с названием: %s' % line)
        rows.append({'write': _ticks(cells[1])[0], 'also': _ticks(cells[2]),
                     'needs': {f for f in ('author', 'note') if '`%s`' % f in cells[3]}})
    check(len(rows) >= 5, 'таблица названий в каталоге не разобрана: строк %d' % len(rows))
    return rows


def _findings(license_name, author='', note=''):
    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(os.path.join(tmp, 'assets'))
        with open(os.path.join(tmp, 'assets', 'a.png'), 'wb') as fh:
            fh.write(b'x')
        with open(os.path.join(tmp, 'materials.json'), 'w', encoding='utf-8') as fh:
            json.dump([{'file': 'assets/a.png', 'source': 'источник', 'license': license_name, 'author': author,
                        'url': '', 'note': note}], fh, ensure_ascii=False)
        return check_materials.check(tmp)


def test_every_catalog_name_is_accepted():
    for row in _table():
        for name in [row['write']] + row['also']:
            bad = _findings(name, author='Автор', note='условия файла')
            check(bad == [], 'каталог велит писать «%s», а проверка краснеет: %s' % (name, bad))


def test_catalog_and_check_list_the_same_licenses():
    rows = _table()
    in_catalog = {check_materials.license_key(r['write']) for r in rows}
    check(None not in in_catalog, 'в таблице каталога есть название, которого проверка не знает')
    allowed = set(check_materials.ALLOWED)
    check(in_catalog == allowed, 'каталог и проверка расходятся: только в проверке %s, только в каталоге %s'
          % (sorted(allowed - in_catalog), sorted(in_catalog - allowed)))
    check(len(rows) == len(in_catalog), 'две строки таблицы каталога про одну лицензию')


def test_required_fields_match():
    for row in _table():
        for field in ('author', 'note'):
            filled = {'author': 'Автор', 'note': 'условия файла'}
            filled[field] = ''
            bad = _findings(row['write'], **filled)
            if field in row['needs']:
                check(bad and field in bad[0], '«%s»: каталог требует %s, а проверка без него %s'
                      % (row['write'], field, 'зелёная' if not bad else 'говорит о другом: %s' % bad))
            else:
                check(bad == [], '«%s»: каталог %s не требует, а проверка краснеет: %s' % (row['write'], field, bad))


def test_catalog_forbidden_is_forbidden():
    text = CATALOG.read_text(encoding='utf-8')
    lines = [l for l in text.splitlines() if FORBIDDEN_RULE in l]
    check(len(lines) == 1, 'в каталоге нет одной строки правила «Запрещены»: %d' % len(lines))
    rule = text[text.index(lines[0]):].split('\n4. ', 1)[0]
    names = _ticks(rule)
    check(len(names) >= 6, 'в правиле «Запрещены» названия не выделены: %s' % names)
    for name in names:
        check(check_materials.forbidden_reason(name), 'каталог запрещает «%s», а проверка запрещённым его не называет' % name)
        bad = _findings(name, author='Автор', note='условия')
        check(bad and 'запрещ' in bad[0], '«%s» из запрещённых каталога: проверка %s' % (name, bad or 'зелёная'))


if __name__ == '__main__':
    sys.exit(run_module(globals()))
