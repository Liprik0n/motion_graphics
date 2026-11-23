# -*- coding: utf-8 -*-
"""Проверка ссылок скила `motion-studio`: пути, якоря, карта референсов, пути чужой машины.

    check_links.py [--root DIR] [-v]                     все .md скила (кроме node_modules)
    check_links.py --red                                 порчи: каждая обязана покраснеть своей строкой
    check_links.py --samples                             законные формы: проходят молча

Что проверяется (код находки — в скобках; `--red` ищет именно его):
  [битая ссылка]  markdown-ссылка `[т](путь)` ведёт в несуществующий файл
  [битый якорь]   `[т](файл.md#якорь)`: такого заголовка в файле нет (слаг как на GitHub)
  [битый путь]    путь в `обратных кавычках` не существует (от корня скила; от корня репозитория;
                  от шаблона `template/`; от каталога файла для ../ и ./)
  [путь машины]   абсолютный путь (`C:\\…`, `/home/…`) в тексте скила: скил ставится на любую машину,
                  его документы ссылаются только на свои файлы; пути пользователя живут в его `links.md`
                  (раздел 1, заполняется на интервью) — там они разрешены; путь от домашней папки
                  (`~/.claude/agents/`) одинаков везде и путём машины не считается
  [0 проверок]    ни одной ссылки не проверено: «зелёное» без проверок охраной не считается
  [links.md: …]   в таблицах карты референсов: нет лицензии · статус не из трёх

Кодовые блоки (```…```) не проверяются: в них пути проекта, а не скила. Имена файлов без каталога
(`tokens.json`), плейсхолдеры (`out/<film>/`), шаблоны (`*`), URL — пропускаются и считаются.

Проверка не импортирует ничего из шаблона: файлы читаются здесь своим способом. Код возврата
0 — всё чисто, 1 — есть красное.
"""

import argparse
import re
import sys
import urllib.parse
from collections import Counter
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

SKILL_ROOT = Path(__file__).resolve().parents[1]

# --- коды находок ---------------------------------------------------------
BAD_LINK = 'битая ссылка'
BAD_ANCHOR = 'битый якорь'
BAD_PATH = 'битый путь'
MACHINE = 'путь машины'
ZERO = '0 проверок'
LM_STATUS = 'links.md: статус не из трёх'
LM_LICENSE = 'links.md: нет лицензии'

# Первые сегменты путей, которые считаются путём (иначе токен в кавычках — не путь).
ROOT_NAMES = {'process', 'profiles', 'checklists', 'catalog', 'templates', 'template', 'tools',
              'docs', 'engine', 'project', 'agents'}
ROOT_FILES = {'SKILL.md', 'links.md', 'lessons.md', 'CONTEXT.md', 'README.md'}
STATUSES = ('своё', 'можно копировать', 'только пример')
LINKS_USER_SECTION = '## 1.'          # раздел links.md с путями пользователя: абсолютные пути там законны

FENCE_RE = re.compile(r'^\s*```')
LINK_RE = re.compile(r'(?<!\!)\[([^\]\n]*)\]\(([^)\s]+)(?:\s+"[^"]*")?\)')
CODE_RE = re.compile(r'`([^`\n]+)`')
HEAD_RE = re.compile(r'^(#{1,6})\s+(.*?)\s*#*\s*$')
# путь от домашней папки (`~/.claude/agents/`) одинаков на любой машине — он не «путь машины»
ABS_RE = re.compile(r'^(?:[A-Za-z]:[\\/]|/(?:home|Users|mnt|opt|var|tmp)/)')
ABS_TEXT_RE = re.compile(r'(?<![\w/.:])(?:[A-Za-z]:\\[^\s`|)]+|/(?:home|Users)/[^\s`|)]+)')
URL_RE = re.compile(r'^[a-z][a-z0-9+.\-]*://', re.I)
SKIP_CHARS = set('<>*{}$|?=…')


class Ctx:
    def __init__(self, skill_root):
        self.skill = Path(skill_root).resolve()
        self.project = self.skill.parent          # корень репозитория: рядом лежат agents/, README.md


class Finding:
    def __init__(self, code, rel, line, detail):
        self.code, self.rel, self.line, self.detail = code, rel, line, detail

    def __str__(self):
        return '[%s] %s:%s — %s' % (self.code, self.rel, self.line, self.detail)


class Stats:
    def __init__(self):
        self.checked = 0
        self.skipped = Counter()
        self.unclassified = []


# ---------------------------------------------------------------------------
# Чтение
# ---------------------------------------------------------------------------

def collect(skill_root):
    """{Path: text} всех .md скила, кроме node_modules и out."""
    root = Path(skill_root).resolve()
    texts = {}
    for p in sorted(root.rglob('*.md')):
        rel = p.relative_to(root).parts
        if 'node_modules' in rel or 'out' in rel:
            continue
        texts[p] = p.read_text(encoding='utf-8')
    return texts


def strip_fences(text):
    """Строки вне ``` … ``` (внутри — пустые, номера строк сохраняются)."""
    out, inside = [], False
    for line in text.split('\n'):
        if FENCE_RE.match(line):
            inside = not inside
            out.append('')
        else:
            out.append('' if inside else line)
    return out


def slugs(text):
    """Якоря заголовков по правилу GitHub (нижний регистр, без знаков, пробел → дефис)."""
    seen, result = Counter(), set()
    for line in strip_fences(text):
        m = HEAD_RE.match(line)
        if not m:
            continue
        s = re.sub(r'[^\w\- ]', '', m.group(2).lower().replace('`', ''), flags=re.U).strip().replace(' ', '-')
        n = seen[s]
        seen[s] += 1
        result.add(s if n == 0 else '%s-%d' % (s, n))
    return result


# ---------------------------------------------------------------------------
# Пути
# ---------------------------------------------------------------------------

def norm(token):
    return token.replace('\\', '/')


def pathlike(token):
    """Токен в обратных кавычках — путь, который стоит проверять? (иначе None / причина пропуска)."""
    t = token.strip()
    if not t:
        return None, 'пусто'
    if URL_RE.match(t):
        return None, 'url'
    if any(c in SKIP_CHARS for c in t) or t.startswith('-') or '...' in t:
        return None, 'шаблон'
    if ABS_RE.match(t):
        return 'abs', ''
    if ' ' in t:
        return None, 'не путь'
    n = norm(t)
    if n in ROOT_FILES:
        return 'rel', ''
    if n.startswith('../') or n.startswith('./'):
        return ('rel', '') if ('/' in n.lstrip('./')) or re.search(r'\.\w{1,5}$', n) else (None, 'не путь')
    first = n.split('/')[0]
    if '/' in n and first in ROOT_NAMES:
        return 'rel', ''
    if '/' not in n:
        return None, 'имя файла'
    return None, 'не классифицирован'


def candidates(token, here, ctx):
    n = norm(token.strip())
    if n.startswith('../') or n.startswith('./'):
        return [(here.parent / n)]
    out = [ctx.skill / n, ctx.project / n]
    first = n.split('/')[0]
    if first in ('engine', 'project'):
        out.insert(0, ctx.skill / 'template' / n)
    return out


def exists_for(path, token):
    t = token.strip()
    if t.endswith('/') or t.endswith('\\'):
        return Path(norm(str(path))).is_dir()
    return Path(norm(str(path))).exists()


def rel_name(path, ctx):
    try:
        return str(Path(path).resolve().relative_to(ctx.skill)).replace('\\', '/')
    except ValueError:
        return str(path)


def user_section_lines(rel, text):
    """Номера строк раздела 1 карты референсов — там пути пользователя законны."""
    if rel != 'links.md':
        return set()
    out, inside = set(), False
    for i, line in enumerate(text.split('\n'), 1):
        if line.startswith('## '):
            inside = line.startswith(LINKS_USER_SECTION)
        if inside:
            out.add(i)
    return out


# ---------------------------------------------------------------------------
# Проверка файла
# ---------------------------------------------------------------------------

def check_file(path, text, ctx, stats, texts):
    found = []
    rel = rel_name(path, ctx)
    lines = strip_fences(text)
    allowed = user_section_lines(rel, text)

    # пути чужой машины ищем по всему тексту, включая кодовые блоки
    for i, line in enumerate(text.split('\n'), 1):
        if i in allowed:
            continue
        for m in ABS_TEXT_RE.finditer(line):
            found.append(Finding(MACHINE, rel, i, '«%s» — путь конкретной машины; в скиле только свои файлы' % m.group(0)))

    for i, line in enumerate(lines, 1):
        for m in LINK_RE.finditer(line):
            target = m.group(2)
            if URL_RE.match(target) or target.startswith('mailto:'):
                stats.skipped['url'] += 1
                continue
            file_part, _, anchor = target.partition('#')
            anchor = urllib.parse.unquote(anchor)
            stats.checked += 1
            if file_part:
                dest = (path.parent / urllib.parse.unquote(file_part)).resolve()
                if not dest.exists():
                    found.append(Finding(BAD_LINK, rel, i, '[%s](%s) — файла нет' % (m.group(1), target)))
                    continue
            else:
                dest = path
            if anchor:
                if dest.suffix.lower() != '.md':
                    continue
                body = texts.get(dest)
                if body is None and dest.exists():
                    body = dest.read_text(encoding='utf-8')
                if body is not None and anchor.lower() not in slugs(body):
                    found.append(Finding(BAD_ANCHOR, rel, i, '[%s](%s) — заголовка «%s» нет' % (m.group(1), target, anchor)))
        if i in allowed:
            continue
        for m in CODE_RE.finditer(line):
            token = m.group(1)
            kind, why = pathlike(token)
            if kind is None:
                stats.skipped[why] += 1
                if why == 'не классифицирован':
                    stats.unclassified.append('%s:%d %s' % (rel, i, token))
                continue
            stats.checked += 1
            if kind == 'abs':
                found.append(Finding(MACHINE, rel, i, '«%s» — путь конкретной машины; в скиле только свои файлы' % token))
                continue
            if any(exists_for(c, token) for c in candidates(token, path, ctx)):
                continue
            found.append(Finding(BAD_PATH, rel, i, '%s — нигде не найден' % token))
    return found


# ---------------------------------------------------------------------------
# links.md
# ---------------------------------------------------------------------------

def table_rows(lines):
    """Строки таблиц: (номер, [ячейки]); разделители и пустые пропущены."""
    for i, line in enumerate(lines, 1):
        s = line.strip()
        if not s.startswith('|'):
            continue
        cells = [c.strip() for c in s.strip('|').split('|')]
        if all(re.fullmatch(r':?-{2,}:?', c) for c in cells if c) and any(cells):
            continue
        yield i, cells


def check_links_md(path, text, ctx):
    """Лицензия и статус у каждой строки таблиц с колонками «Лицензия» и «Статус». Строка-образец формы
    (ячейки в угловых скобках) не проверяется."""
    found = []
    rel = rel_name(path, ctx)
    header = None
    for i, cells in table_rows(strip_fences(text)):
        low = [c.lower() for c in cells]
        if 'лицензия' in low and 'статус' in low:
            header = (low.index('лицензия'), low.index('статус'))
            continue
        if header is None:
            continue
        if len(cells) <= max(header):
            header = None
            continue
        if cells[0].startswith('<'):
            continue
        lic, st = cells[header[0]], cells[header[1]]
        if not lic:
            found.append(Finding(LM_LICENSE, rel, i, 'у «%s» не указана лицензия' % cells[0]))
        if not any(st.lower().startswith(s) for s in STATUSES):
            found.append(Finding(LM_STATUS, rel, i, 'у «%s» статус «%s», нужен один из: %s' % (cells[0], st, ', '.join(STATUSES))))
    return found


# ---------------------------------------------------------------------------
# Сборка проверки
# ---------------------------------------------------------------------------

def run_checks(texts, ctx):
    stats = Stats()
    found = []
    for path, text in texts.items():
        found += check_file(path, text, ctx, stats, texts)
        if rel_name(path, ctx) == 'links.md':
            found += check_links_md(path, text, ctx)
    if stats.checked == 0:
        found.append(Finding(ZERO, '-', 0, 'ссылок не проверено ни одной — это не «зелёное»'))
    return found, stats


# ---------------------------------------------------------------------------
# Порчи и образцы
# ---------------------------------------------------------------------------

def replace_in(rel, old, new, count=1):
    def fn(texts, ctx):
        p = ctx.skill / rel
        if p not in texts:
            raise KeyError('нет файла %s' % rel)
        if old not in texts[p]:
            raise KeyError('в %s нет фрагмента %r' % (rel, old))
        texts[p] = texts[p].replace(old, new, count)
    return fn


def add_file(name, body_fn):
    def fn(texts, ctx):
        texts[ctx.skill / 'process' / name] = body_fn(ctx)
    return fn


def add_user_row(row):
    """Строка в раздел 1 links.md (пути пользователя) — после строки-образца формы."""
    def fn(texts, ctx):
        p = ctx.skill / 'links.md'
        lines = texts[p].split('\n')
        k = [i for i, l in enumerate(lines) if l.startswith('| <путь')]
        if not k:
            raise KeyError('в links.md нет строки-образца раздела 1')
        lines.insert(k[0] + 1, row)
        texts[p] = '\n'.join(lines)
    return fn


def empty_all(texts, ctx):
    texts.clear()


USER_ROW = '| `D:\\Работа\\Бренд\\` | брендбук и шрифты | этап 2 | заказчика | своё |'

# (имя, мутатор, ожидаемая подстрока провала)
REDS = [
    ('битая markdown-ссылка', add_file('__red.md', lambda c: 'См. [файл](00-net-takogo.md).\n'), BAD_LINK),
    ('битый якорь', add_file('__red.md', lambda c: 'См. [раздел](00-intake.md#net-takogo-razdela).\n'), BAD_ANCHOR),
    ('битый путь от корня скила', add_file('__red.md', lambda c: 'Читать `process/99-net-takogo.md` на этапе.\n'), BAD_PATH),
    ('битый путь от ../', add_file('__red.md', lambda c: 'Основание `../catalog/net-takogo.md` §1.\n'), BAD_PATH),
    ('битый путь в template/', add_file('__red.md', lambda c: 'Читать `template/engine/audio/net_takogo.py`.\n'), BAD_PATH),
    ('битый путь проекта engine/', add_file('__red.md', lambda c: 'Команда `engine/video/net_takogo.py`.\n'), BAD_PATH),
    ('битая роль агента', add_file('__red.md', lambda c: 'Агент `agents/motion-net-takogo.md`.\n'), BAD_PATH),
    ('путь машины в кавычках (Windows)', add_file('__red.md', lambda c: 'Эталон лежит в `D:\\Проекты\\ролик\\video.mp4`.\n'), MACHINE),
    ('путь машины в кавычках (домашняя папка)', add_file('__red.md', lambda c: 'Агенты — `/home/kto-to/.claude/agents/`.\n'), MACHINE),
    ('путь машины текстом', add_file('__red.md', lambda c: 'Шрифты взять из C:\\Users\\kto-to\\fonts.\n'), MACHINE),
    ('путь машины в кодовом блоке', add_file('__red.md', lambda c: '```\ncd /home/kto-to/project\n```\n'), MACHINE),
    ('путь пользователя вне раздела 1 links.md', replace_in('links.md', '## 2. Сам скил\n', '## 2. Сам скил\n\nЭталон: `E:\\Ролики\\прошлый\\`.\n'), MACHINE),
    ('ноль проверенных ссылок', empty_all, ZERO),
    ('links.md: нет лицензии', add_user_row('| `D:\\Работа\\Фото\\` | фото объекта | этап 5 | | своё |'), LM_LICENSE),
    ('links.md: статус не из трёх', add_user_row('| `D:\\Работа\\Музыка\\` | треки | этап 8 | CC BY | наверное можно |'), LM_STATUS),
    ('links.md: пустой статус', add_user_row('| `D:\\Работа\\Тексты\\` | исходные тексты | этап 1 | своё | |'), LM_STATUS),
]

SAMPLE_BODY = """# Образцы

Внешняя [ссылка](https://example.com/page#frag), URL `https://hyperframes.heygen.com`, почта [м](mailto:a@b.c).
Плейсхолдеры `out/<film>/video.mp4`, `scenes/<id>/`, шаблон `agents/motion-*.md`, `catalog/img/*.png`.
Имена файлов без каталога `tokens.json`, `film.json`, `speech_lint.py`; команда `"$PY" engine/tts/tts.py --voices`.
Живой якорь [раздел](00-intake.md#как-спрашивать) и живая ссылка [рядом](01-script.md).
Живой путь шаблона `template/engine/audio/music.py` и он же от проекта `engine/tts/tts.py`; роль `agents/motion-qa.md`.
Корень скила `SKILL.md`, карта `links.md`; соседний этап `../process/02-design.md`.
Отношение 16:9 и время 18:00 — не пути; дробь 1/10 тоже.
Путь от домашней папки одинаков на любой машине: `~/.claude/agents/`, `~/.motion-studio/node_modules`.

```
`process/99-ne-proveryaetsya.md` и [x](net-takogo.md) внутри кодового блока
```
"""


def run_red(ctx):
    base_texts = collect(ctx.skill)
    problems = 0
    rows = 0
    for name, mutate, expected in REDS:
        rows += 1
        ctx_i = Ctx(ctx.skill)
        before, _ = run_checks(dict(base_texts), ctx_i)
        before_count = sum(1 for f in before if expected in f.code)
        texts = dict(base_texts)
        snap = dict(texts)
        try:
            mutate(texts, ctx_i)
        except KeyError as e:
            print('ПРОВАЛ  порча «%s»: не применилась (%s)' % (name, e.args[0]))
            problems += 1
            continue
        if texts == snap and name != 'ноль проверенных ссылок':
            print('ПРОВАЛ  порча «%s»: текст не изменился' % name)
            problems += 1
            continue
        after, _ = run_checks(texts, ctx_i)
        after_count = sum(1 for f in after if expected in f.code)
        if after_count > before_count:
            print('ОК      порча «%s» → [%s]' % (name, expected))
        else:
            print('ПРОВАЛ  порча «%s»: [%s] не появилось (было %d, стало %d)' % (name, expected, before_count, after_count))
            problems += 1
    # законная форма: путь пользователя в разделе 1 links.md — не красный
    texts = dict(base_texts)
    add_user_row(USER_ROW)(texts, ctx)
    legal = [f for f in run_checks(texts, Ctx(ctx.skill))[0] if f.code == MACHINE]
    if legal:
        print('ПРОВАЛ  путь пользователя в разделе 1 links.md покраснел: %s' % legal[0])
        problems += 1
    else:
        print('ОК      путь пользователя в разделе 1 links.md — законный')
    print('порч: %d, провалов: %d' % (rows + 1, problems))
    return problems


def run_samples(ctx):
    ctx_i = Ctx(ctx.skill)
    texts = {ctx.skill / 'process' / '__samples.md': SAMPLE_BODY}
    found, stats = run_checks(texts, ctx_i)
    for f in found:
        print('ЛОЖНОЕ КРАСНОЕ  %s' % f)
    print('образцов: 1 набор (%d проверено), ложных красных: %d' % (stats.checked, len(found)))
    return 1 if found else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--root', default=str(SKILL_ROOT), help='корень скила (по умолчанию — расположение скрипта)')
    ap.add_argument('--red', action='store_true')
    ap.add_argument('--samples', action='store_true')
    ap.add_argument('-v', '--verbose', action='store_true')
    args = ap.parse_args()
    ctx = Ctx(args.root)
    if args.red:
        sys.exit(1 if run_red(ctx) else 0)
    if args.samples:
        sys.exit(run_samples(ctx))
    texts = collect(ctx.skill)
    found, stats = run_checks(texts, ctx)
    for f in found:
        print(f)
    if args.verbose:
        for line in stats.unclassified:
            print('не классифицирован: ' + line)
    print('файлов .md: %d · ссылок проверено: %d · пропущено: %s · красных: %d'
          % (len(texts), stats.checked,
             ', '.join('%s %d' % kv for kv in sorted(stats.skipped.items())) or '0', len(found)))
    sys.exit(1 if found else 0)


if __name__ == '__main__':
    main()
