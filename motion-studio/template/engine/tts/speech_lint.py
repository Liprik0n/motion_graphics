# -*- coding: utf-8 -*-
"""Линт текста для синтеза — ДО оплаты. Ловит то, за что в прошлом ролике платили дважды.

    speech_lint.py [--project DIR]   строки rows.json (+ speech_edits.json)
    speech_lint.py --red             порчи: каждая обязана покраснеть своим классом
    speech_lint.py --samples         законные формулировки: проходят молча

Проверяется текст, который уйдёт в синтез: `speech` из `speech_edits.json`, если правка
есть, иначе `text` строки. Авторская разметка — `(breath)`, `<#0.3#>` — вычищается
до проверки. Классы (классы дефектов 7–9, 11, 16 — checklists/defect-classes.md скила):

    цифры          «24 часов» синтез читает «двадцать четыре часов»: только словами
                   и в нужном падеже; знаки № % § — тоже
    кавычки        цитата в кавычках даёт провал 0,5–0,7 с внутри словосочетания
    омограф        слово из homographs.txt: знака ударения у MiniMax нет
    аббревиатуры встык  две аббревиатуры подряд («ОТК НИИ ЦОД») читаются одним словом
    носитель       «слайд», «на экране», «нажмите» — шаблоны carrier_words.txt

Выход — «строка N → класс → фрагмент», код 1, если есть находка без правки и без
разрешения. Разрешение — `speech_edits.json[N].allow: [класс, …]` с непустым `why`:
человек прослушал и принял. Правка без основания, правка для несуществующей строки,
устаревшая правка (`doc` ≠ текст строки) — тоже провал: белый список, который никто
не ведёт, становится свалкой.

Проверка не импортирует сборку: rows.json и speech_edits.json читаются здесь своим способом.
"""

import json
import os
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

HERE = Path(__file__).resolve().parent
sys.path.append(str(HERE.parent))
import project_root   # noqa: E402

DIGITS = 'цифры'
QUOTES = 'кавычки'
HOMOGRAPH = 'омограф'
ABBR = 'аббревиатуры встык'
CARRIER = 'носитель'
CLASSES = (DIGITS, QUOTES, HOMOGRAPH, ABBR, CARRIER)
# Классы промера после синтеза: их разрешает тот же реестр, а судит check_audio.py.
AUDIO_CLASSES = ('пауза', 'протяжность')

NO_WHY = 'правка без основания'
NO_ROW = 'правка без строки'
STALE = 'правка устарела'
BAD_CLASS = 'неизвестный класс'

AUTHOR_MARK_RE = re.compile(r'<#[^#>]*#>|\([A-Za-z][A-Za-z_ ]*\)')
DIGIT_RE = re.compile(r'[0-9№%§]+')
QUOTE_RE = re.compile(r'[«»„“”"]')
WORD_RE = re.compile(r'[А-Яа-яЁёA-Za-z]+(?:-[А-Яа-яЁёA-Za-z]+)*')
# Аббревиатура — слово из двух и более заглавных букв без строчных; встык — две
# такие подряд, между ними только пробел. «ТС и ПО», «ОТК, НИИ», «ГосНИИ ЦОД» проходят.
ABBR_PAIR_RE = re.compile(r'(?<![А-ЯЁA-Za-zа-яё])([А-ЯЁA-Z]{2,})\s+([А-ЯЁA-Z]{2,})(?![А-ЯЁA-Za-zа-яё])')


def load_words(path):
    words = {}
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        body = re.split(r'\s+#', line, maxsplit=1)[0].strip()
        if not body or line.lstrip().startswith('#'):
            continue
        words[norm(body)] = line.split('#', 1)[1].strip() if '#' in line else ''
    return words


def load_patterns(path):
    pats = []
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        body = re.split(r'\s+#\s', line, maxsplit=1)[0].strip()
        pats.append(re.compile(body, re.IGNORECASE))
    return pats


def norm(word):
    return word.lower().replace('ё', 'е')


def findings_of(text, homographs, carriers):
    """[(класс, фрагмент)] одной строки текста для синтеза."""
    clean = AUTHOR_MARK_RE.sub(' ', text)
    found = []
    for m in DIGIT_RE.finditer(clean):
        found.append((DIGITS, m.group(0)))
    for m in QUOTE_RE.finditer(clean):
        found.append((QUOTES, m.group(0)))
    for m in WORD_RE.finditer(clean):
        if norm(m.group(0)) in homographs:
            found.append((HOMOGRAPH, m.group(0)))
    pos = 0
    while True:
        m = ABBR_PAIR_RE.search(clean, pos)
        if not m:
            break
        found.append((ABBR, m.group(0)))
        pos = m.start(2)
    for pat in carriers:
        for m in pat.finditer(clean):
            found.append((CARRIER, m.group(0)))
    return found


def lint(rows, edits, homographs, carriers):
    """Все находки: [(n или ключ правки, класс, фрагмент)]; пустой список — чисто."""
    out = []
    by_n = {str(r['n']): r for r in rows}
    for key, e in edits.items():
        if key.startswith('_'):
            continue
        if key not in by_n:
            out.append((key, NO_ROW, 'в rows.json нет строки %s' % key))
            continue
        if not str(e.get('why', '')).strip():
            out.append((key, NO_WHY, 'нет why'))
        if 'doc' in e and e['doc'] != by_n[key]['text']:
            out.append((key, STALE, 'doc ≠ text строки: перечитать и переписать правку'))
        for cls in e.get('allow', []):
            if cls not in CLASSES + AUDIO_CLASSES:
                out.append((key, BAD_CLASS, cls))
    for r in rows:
        e = edits.get(str(r['n'])) or {}
        speech = e.get('speech', r['text'])
        allowed = set(e.get('allow', [])) if str(e.get('why', '')).strip() else set()
        for cls, frag in findings_of(speech, homographs, carriers):
            if cls not in allowed:
                out.append((r['n'], cls, frag))
    return out


def report(found):
    for n, cls, frag in found:
        print('  строка %s → %s → %s' % (n, cls, frag))


# ---------------------------------------------------------------------------
# Порчи и образцы — на класс, а не на названный пример
# ---------------------------------------------------------------------------

def R(text, n=1):
    return [{'n': n, 'scene': 's', 'voice': 'a', 'emotion': 'Neutral', 'text': text}]


RED = [
    # (имя, строки, правки, ожидаемый класс в находках)
    ('число цифрами', R('Восстанавливают в течение 24 часов.'), {}, DIGITS),
    ('год цифрами', R('Приказ вышел в 2024 году.'), {}, DIGITS),
    ('знак номера', R('Приказ № четыреста восемнадцать.'), {}, DIGITS),
    ('процент знаком', R('Доля выросла на сорок %.'), {}, DIGITS),
    ('ёлочки', R('Ситуация: «утеря сведений».'), {}, QUOTES),
    ('лапки', R('Пароль „по умолчанию“ меняют.'), {}, QUOTES),
    ('прямые кавычки', R('Учётная запись "admin" отключена.'), {}, QUOTES),
    ('омограф из прошлого ролика', R('Получается, беды ещё нет.'), {}, HOMOGRAPH),
    ('омограф с заглавной', R('Головы не помнят, руки помнят.'), {}, HOMOGRAPH),
    ('омограф заглавными', R('Без ВОДЫ никак.'), {}, HOMOGRAPH),
    ('омограф в конце фразы', R('Данные хранятся в сети'), {}, HOMOGRAPH),
    ('омограф класса', R('Это замок на двери.'), {}, HOMOGRAPH),
    ('две аббревиатуры', R('Начальник ОТК НИИ ЦОД проверяет.'), {}, ABBR),
    ('пара встык', R('Сервер ЦОД ИТ стоит в стойке.'), {}, ABBR),
    ('латиница встык', R('Доступ к ПО CRM ограничен.'), {}, ABBR),
    ('слайд', R('На слайде они оранжевые.'), {}, CARRIER),
    ('слайд в другом падеже', R('Вернёмся к этому слайду.'), {}, CARRIER),
    ('на экране', R('Посмотрите, что на экране.'), {}, CARRIER),
    ('нажмите', R('Нажмите, чтобы продолжить.'), {}, CARRIER),
    ('презентация', R('В презентации это есть.'), {}, CARRIER),
    ('правка не лечит', R('В течение 24 часов.'),
     {'1': {'speech': 'В течение 24-х часов.', 'why': 'число'}}, DIGITS),
    ('правка без основания', R('В течение 24 часов.'),
     {'1': {'speech': 'В течение двадцати четырёх часов.'}}, NO_WHY),
    ('разрешение без основания', R('На слайде.'),
     {'1': {'allow': [CARRIER]}}, CARRIER),
    ('правка без строки', R('Чисто.'), {'9': {'speech': 'x', 'why': 'y'}}, NO_ROW),
    ('правка устарела', R('Новый текст строки.'),
     {'1': {'speech': 'Старый.', 'why': 'w', 'doc': 'Старый текст строки.'}}, STALE),
    ('неизвестный класс', R('Чисто.'), {'1': {'allow': ['всё'], 'why': 'w'}}, BAD_CLASS),
    ('разрешён не тот класс', R('В течение 24 часов, на слайде.'),
     {'1': {'allow': [CARRIER], 'why': 'прослушано'}}, DIGITS),
]

SAMPLES = [
    ('число словами', R('В течение двадцати четырёх часов.'), {}),
    ('союз между аббревиатурами', R('Это ТС и ПО.'), {}),
    ('запятая между аббревиатурами', R('Это ОТК, НИИ.'), {}),
    ('смешанный регистр', R('Сводка ГосНИИ ЦОД.'), {}),
    ('одна аббревиатура', R('Порты ЛВС и ВЛВС.'), {}),
    ('одна буква перед аббревиатурой', R('И ЦОД живёт.'), {}),
    ('авторская разметка', R('(breath) Часы разъехались. <#0.3#> Низкий.'), {}),
    ('слайдер', R('Двигайте слайдер.'), {}),
    ('экранирование', R('Экранирование кабеля.'), {}),
    ('словоформа не омограф', R('Руками и головой.'), {}),
    ('беда', R('Беда ещё не случилась.'), {}),
    ('правка лечит цифры', R('Восстанавливают «в течение 24 часов».'),
     {'1': {'speech': 'Восстанавливают, в течение двадцати четырёх часов.',
            'why': 'число словами, без кавычек — прошлый ролик', 'doc': 'Восстанавливают «в течение 24 часов».'}}),
    ('правка лечит омограф', R('Получается, беды ещё нет.'),
     {'1': {'speech': 'Получается, беда ещё не случилась.', 'why': 'БЕды — прошлый ролик'}}),
    ('разрешение с основанием', R('Все и не нужно, на слайде они оранжевые.'),
     {'1': {'allow': [CARRIER], 'why': 'прослушано, демо'}}),
]


def self_check(dic, carriers, mode):
    fails = 0
    if mode in ('red', 'all'):
        for name, rows, edits, want in RED:
            got = lint(rows, edits, dic, carriers)
            hit = [f for f in got if f[1] == want]
            if hit:
                print('  ok   порча «%s» покраснела: %s → %s' % (name, want, hit[0][2]))
            else:
                fails += 1
                print('  FAIL порча «%s» не покраснела классом «%s» (находки: %s)'
                      % (name, want, got))
    if mode in ('samples', 'all'):
        for name, rows, edits in SAMPLES:
            got = lint(rows, edits, dic, carriers)
            if got:
                fails += 1
                print('  FAIL образец «%s» покраснел: %s' % (name, got))
            else:
                print('  ok   образец «%s» прошёл молча' % name)
    return fails


def main(argv):
    dic = load_words(HERE / 'homographs.txt')
    carriers = load_patterns(HERE / 'carrier_words.txt')
    if '--red' in argv or '--samples' in argv:
        mode = 'all' if ('--red' in argv and '--samples' in argv) else (
            'red' if '--red' in argv else 'samples')
        fails = self_check(dic, carriers, mode)
        print('---\nпровалов самопроверки: %d' % fails)
        return 1 if fails else 0
    pdir, argv = project_root.split_argv(argv)     # --project → MOTION_PROJECT → <шаблон>/project
    with open(pdir / 'rows.json', encoding='utf-8') as fh:
        rows = json.load(fh)
    edits = {}
    if (pdir / 'speech_edits.json').exists():
        with open(pdir / 'speech_edits.json', encoding='utf-8') as fh:
            edits = json.load(fh)
    found = lint(rows, edits, dic, carriers)
    report(found)
    allowed = sum(len(e.get('allow', [])) for k, e in edits.items() if not k.startswith('_'))
    print('---')
    print('строк: %d; правок для синтеза: %d; разрешений: %d; находок: %d'
          % (len(rows), sum(1 for k, e in edits.items() if not k.startswith('_') and 'speech' in e),
             allowed, len(found)))
    return 1 if found else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
