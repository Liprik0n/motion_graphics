# -*- coding: utf-8 -*-
"""У каждого чужого материала проекта есть строка с источником и лицензией; запрещённые лицензии не проходят.

    python engine/tools/check_materials.py [--project <папка project>] [-v]   (корень — по правилу engine/project_root.py)

Что смотрит: файлы-материалы в `<project>/assets/` (картинки, видео, звук, шрифты, Lottie) и `<project>/materials.json`:

    [{"file": "assets/rose.png", "source": "Poly Haven", "license": "CC0", "author": "", "url": "https://…", "note": ""}]

Красное (код 1, по строке на находку):
  - файл-материал без строки в materials.json;
  - строка без файла (опечатка в пути или файл удалён);
  - у строки пусто source или license;
  - лицензия из запрещённых (CC BY-NC и вся «некоммерческая» семья, ND, SA, «только для YouTube», «личное использование»,
    все права защищены);
  - лицензия не из списка разрешённых (в том числе «проверить у файла»): непроверенное в ролик не идёт;
  - лицензия с подписью (CC BY) без author;
  - лицензия, у которой условия свои у каждого файла (Mixkit), без note.
Как писать название: так, как оно стоит у файла, — «Lottie Simple License», «Pixabay Content License», «Unsplash
License», «SIL OFL 1.1», «CC BY 4.0»; короткие ключи (`ofl`, `cc-by`, `pixabay`) тоже годятся. Регистр, пробелы и номер
версии в конце значения не имеют. Полная таблица названий — в скиле, `catalog/sources.md`, раздел «Как писать
лицензию в materials.json»: таблица и списки ниже обязаны совпадать (тест скила tools/tests/test_sources_catalog.py).
Своё и принесённое заказчиком получает те же строки: license `own` (сделано нами, кодом) или `customer` (картинка заказчика,
права на нём), source — откуда (`сгенерировано заказчиком`, `код шаблона`), чтобы в проекте не было безымянных файлов.
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))      # <проект>/engine
import deps  # noqa: E402
import project_root  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
MATERIAL_EXT = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.avif', '.svg', '.mp4', '.webm', '.mov', '.mp3', '.wav', '.ogg', '.m4a',
                '.flac', '.ttf', '.otf', '.woff', '.woff2', '.lottie'}
LOTTIE_JSON_DIRS = {'lottie', 'animations'}      # .json в этих папках — анимации Lottie, а не данные проекта

# Разрешённые лицензии — нормализованный вид (строчные, пробелы и подчёркивания → «-», без версии: «cc-by-4.0» → «cc-by»).
ALLOWED = {
    'own': 'сделано нами, кодом шаблона или проекта',
    'customer': 'принесено заказчиком, права на нём',
    'cc0': 'CC0: без условий',
    'public-domain': 'общественное достояние',
    'ofl': 'SIL Open Font License (шрифты Google Fonts)',
    'apache-2.0': 'Apache 2.0',
    'mit': 'MIT',
    'cc-by': 'CC BY: нужна подпись автора (author)',
    'lottiefiles-simple': 'Lottie Simple License: коммерция без подписи',
    'unsplash': 'лицензия Unsplash: без подписи',
    'pixabay': 'лицензия Pixabay: без подписи',
    'undraw': 'unDraw: без подписи',
    'mixkit': 'Mixkit: условия смотреть у файла — записать в note',
}
# Как писать в materials.json (первый столбец таблицы каталога): ключ → название. Его называет сообщение об ошибке.
WRITE = {
    'own': 'own', 'customer': 'customer', 'cc0': 'CC0', 'public-domain': 'Public Domain', 'ofl': 'SIL OFL 1.1',
    'apache-2.0': 'Apache-2.0', 'mit': 'MIT', 'cc-by': 'CC BY 4.0', 'lottiefiles-simple': 'Lottie Simple License',
    'unsplash': 'Unsplash License', 'pixabay': 'Pixabay Content License', 'undraw': 'unDraw License',
    'mixkit': 'Mixkit License',
}
# Названия, как они стоят у файла, в нормализованном виде и без версии → ключ ALLOWED.
NAMES = {
    'cc0-1.0-universal': 'cc0',
    'sil-ofl': 'ofl', 'sil-open-font-license': 'ofl', 'open-font-license': 'ofl',
    'apache-license': 'apache-2.0',
    'mit-license': 'mit',
    'cc-attribution': 'cc-by',
    'lottie-simple-license': 'lottiefiles-simple',
    'unsplash-license': 'unsplash', 'лицензия-unsplash': 'unsplash',
    'pixabay-content-license': 'pixabay', 'pixabay-license': 'pixabay', 'лицензия-pixabay': 'pixabay',
    'undraw-license': 'undraw',
    'mixkit-license': 'mixkit',
}
NEEDS_AUTHOR = {'cc-by'}
NEEDS_NOTE = {'mixkit'}          # условия у каждого файла свои: название лицензии файла и условия — в note
# Запрещённые — образцы по нормализованной строке (поиск подстроки по границам слов); сообщение называет причину.
FORBIDDEN = [
    (r'(^|-)nc(-|$)|non-?commercial|некоммерч|noncommercial', 'некоммерческая лицензия (NC): ролик заказчика — коммерческое использование'),
    (r'(^|-)nd(-|$)|no-?derivs|без-?производных', 'лицензия ND запрещает переделку: вырезка и анимация — это переделка'),
    (r'(^|-)sa(-|$)|share-?alike', 'лицензия SA заражает ролик условиями: без решения заказчика не берём'),
    (r'youtube', 'лицензия «только для YouTube»: ролик живёт не только там'),
    (r'personal|личн|для-?дома|home-?use|editorial|редакц', 'личное или редакционное использование: ролик не личный'),
    (r'all-?rights-?reserved|все-?права-?защищены', 'все права защищены: нужна лицензия'),
    (r'rmbg', 'RMBG-2.0 — некоммерческая модель: ею не вырезаем'),
]


def normalize(text):
    t = re.sub(r'[\s_]+', '-', str(text).strip().lower())
    return re.sub(r'^creative-commons-?', 'cc-', t)


def license_key(text):
    """Ключ из ALLOWED или None. Принимается и ключ, и название, как оно стоит у файла (NAMES); версия в конце
    («CC BY 4.0» → cc-by, «SIL OFL 1.1» → ofl) отбрасывается, если целиком названия нет."""
    t = normalize(text)
    for cand in (t, re.sub(r'-v?\d+(\.\d+)*$', '', t)):
        if cand in ALLOWED:
            return cand
        if cand in NAMES:
            return NAMES[cand]
    return None


def forbidden_reason(license_text):
    t = normalize(license_text)
    for pattern, why in FORBIDDEN:
        if re.search(pattern, t):
            return why
    return None


def material_files(project):
    out = []
    base = Path(project) / 'assets'
    if not base.is_dir():
        return out
    for p in sorted(base.rglob('*')):
        if not p.is_file():
            continue
        ext = p.suffix.lower()
        rel = p.relative_to(project).as_posix()
        if ext in MATERIAL_EXT or (ext == '.json' and LOTTIE_JSON_DIRS & set(x.lower() for x in p.relative_to(base).parts[:-1])):
            out.append(rel)
    return out


def load_rows(project):
    path = Path(project) / 'materials.json'
    if not path.exists():
        return None, ['нет файла %s: заведи materials.json — список строк {file, source, license, author, url, note}' % path.as_posix()]
    try:
        rows = json.loads(path.read_text(encoding='utf-8-sig'))
    except ValueError as e:
        return None, ['materials.json не читается: %s' % e]
    if not isinstance(rows, list):
        return None, ['materials.json — не список строк']
    return rows, []


def check(project):
    """Список находок (строки); пустой — зелёное."""
    rows, bad = load_rows(project)
    if rows is None:
        return bad
    listed = {}
    for n, row in enumerate(rows, 1):
        f = str(row.get('file', '')).replace('\\', '/').strip() if isinstance(row, dict) else ''
        if not f:
            bad.append('строка %d materials.json без поля file' % n)
            continue
        listed[f] = row
        if not (Path(project) / f).is_file():
            bad.append('%s: строка есть, а файла нет — опечатка в пути или файл удалён' % f)
        src, lic = str(row.get('source', '')).strip(), str(row.get('license', '')).strip()
        if not src:
            bad.append('%s: пусто source — откуда файл' % f)
        if not lic:
            bad.append('%s: пусто license — под какой лицензией' % f)
            continue
        why = forbidden_reason(lic)
        if why:
            bad.append('%s: лицензия «%s» запрещена — %s' % (f, lic, why))
            continue
        key = license_key(lic)
        if key is None:
            bad.append('%s: лицензия «%s» не из разрешённых — проверить у файла и записать её название; принимаются: %s'
                       % (f, lic, ', '.join(WRITE[k] for k in ALLOWED)))
        elif key in NEEDS_AUTHOR and not str(row.get('author', '')).strip():
            bad.append('%s: лицензия %s требует подписи — заполни автор (author)' % (f, lic))
        elif key in NEEDS_NOTE and not str(row.get('note', '')).strip():
            bad.append('%s: у лицензии %s условия свои у каждого файла — запиши в note название лицензии файла и её '
                       'условия' % (f, lic))
    for f in material_files(project):
        if f not in listed:
            bad.append('%s: файл-материал без строки в materials.json (источник и лицензия)' % f)
    return bad


def main(argv=None):
    ap = argparse.ArgumentParser(description='Источники и лицензии материалов проекта.')
    ap.add_argument('-v', '--verbose', action='store_true')
    project, rest = project_root.split_argv(sys.argv[1:] if argv is None else list(argv))   # --project → MOTION_PROJECT → <шаблон>/project
    a = ap.parse_args(rest)
    a.project = str(project)
    bad = check(a.project)
    for b in bad:
        print('КРАСНЫЙ ' + b)
    if a.verbose or not bad:
        print('материалы: файлов %d, строк в materials.json %d — %s' % (
            len(material_files(a.project)), len((load_rows(a.project)[0] or [])), 'красное: %d' % len(bad) if bad else 'зелёное'))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(deps.run(main))
