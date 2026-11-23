# -*- coding: utf-8 -*-
"""Реестр стилей: стиль — папка, а не строка в списке.

Стиль `<name>` — папка `styles/<name>/` с `style.json` (обязателен), `style.css` и `plugin.js`
(необязательны). Ищется сначала в `<проект>/styles/`, потом в `engine/video/styles/`: свой стиль
проекта добавляется папкой в проекте, общий — папкой в движке; ни build.py, ни check.py для этого
не правятся. Папки на `_` (здесь `_core`) — общий код стилей, а не стили.

Выбор стиля сцены (сильнейший первым):
    storyboard.json "style"  →  проход фильма (films/<f>.json "styles": [...])  →  films/<f>.json "style"
    →  project.json "style"  →  без стиля.
У раскадровки "style": null — явно без стиля, даже если фильм или проект его задают.
Имя "none" в списке проходов — бренд без стиля (кадр для сравнения).

Модель «стиль — целый мир»: стиль владеет фоном кадра, своей палитрой декора (decor),
шрифтом заголовка, набором нарисованных кодом предметов (objects ≥ 5), движением и звуком. Бренд остаётся:
основной текст — фирменным шрифтом и ролями палитры бренда, --c-* не меняются (check.py V21, V22).
project.json "style_brand_lock": true — «только фактура»: world.css не кладётся, плагин получает world=false.

Что проверяется здесь (до сборки, отказом с именем стиля и поля):
- style.json: только известные поля, name = имя папки, motion, sfx, decor, fonts, objects в своих границах;
  у шрифта стиля обязана быть кириллица (рендер букв против пустого глифа, Pillow);
  шрифт — файл: папка стиля → <проект>/assets/fonts → engine/video/assets/fonts (шрифты движка под OFL,
  источник и лицензия — assets/fonts/README.md) → системная папка шрифтов (только свой стиль проекта:
  системный шрифт не переносится на другую машину и не публикуется, стили движка его не называют);
  роли шрифтов: title (заголовок каркаса), decor (надписи предметов) и свои роли плагина (латиница, цифры, «_») —
  у каждой своя переменная --sty-<стиль>-<роль> и cfg.fonts.<роль>;
- style.css и world.css: каждый селектор привязан к своему стилю — содержит [data-style="<name>"];
  @import, @font-face (шрифты стиля объявляет сборка из fonts), @media — запрещены, @keyframes — только <name>-….
"""
import json
import os
import re

CORE = os.path.dirname(os.path.abspath(__file__))       # engine/video/styles/_core
ENGINE_STYLES = os.path.dirname(CORE)                    # engine/video/styles
ENGINE_FONTS = os.path.join(os.path.dirname(ENGINE_STYLES), 'assets', 'fonts')   # шрифты движка файлами (OFL)
NONE = 'none'

TOP_KEYS = {'name', 'label', 'description', 'use_for', 'params', 'motion', 'sfx', 'never', 'decor', 'fonts', 'objects',
            '_comment'}
FONT_ROLES = ('title', 'decor')
FONT_ROLE_RE = re.compile(r'^[a-z][a-z0-9_]*$')      # своя роль шрифта плагина (вырезки зина: cut_poster, cut_serif…)
OBJECTS_MIN = 5
HEX_RE = re.compile(r'^#[0-9A-Fa-f]{6}$')
CYR_PROBE = 'ЖЁйЫюЩ'
NUM = (int, float)
# движение стиля (lib/stage.js): обязательные — у иконок; необязательные — у любого узла сцены стиля, по умолчанию выкл.
MOTION_KEYS = {'icon_step_frames': (int, 1, 4), 'icon_overshoot': (NUM, 0.0, 3.0)}
MOTION_OPT = {'step_frames': (int, 1, 4),       # форма узла «на N»: пиксель на двойках/тройках, глина покадрово
              'grid_px': (int, 0, 32),          # позиция узла — по сетке N px (пиксель)
              'overshoot': (NUM, 0.0, 3.0),     # перелёт входа rise/pop/lift у любого узла (отскок плашек комикса)
              'move_overshoot': (NUM, 0.0, 3.0),  # перелёт в конце move
              'jitter_px': (NUM, 0.0, 6.0)}     # дрожь рисунка: сдвиг ±N px, новый на каждый рисунок (глина, бойл)
# материал звука SFX (engine/audio/synth.py material): числа с границами + форма волны
SFX_CLIP_KEYS = {'lp_hz': (NUM, 500.0, 12000.0), 'grit': (NUM, 0.0, 1.0), 'crackle': (NUM, 0.0, 200.0),
                 'bits': (int, 2, 16), 'hold': (int, 1, 32), 'noise_burst': (NUM, 0.0, 1.0), 'partials': (NUM, 0.0, 1.0)}
SFX_WAVES = ('square', 'soft')
CODE = 'code'        # fonts.title.kind: заголовок рисует plugin.js (StyleCore.codeTitle)
NAME_RE = re.compile(r'^[a-z][a-z0-9-]*$')


def search_dirs(project_root=None):
    out = []
    if project_root:
        out.append(os.path.join(str(project_root), 'styles'))
    out.append(ENGINE_STYLES)
    return out


def names(project_root=None):
    """Все стили: папки с style.json, без `_`-папок; свой стиль проекта закрывает одноимённый движка."""
    seen = set()
    for d in search_dirs(project_root):
        if not os.path.isdir(d):
            continue
        for n in os.listdir(d):
            if n.startswith('_') or n in seen or not os.path.exists(os.path.join(d, n, 'style.json')):
                continue
            seen.add(n)
    return sorted(seen)


def folder(name, project_root=None):
    for d in search_dirs(project_root):
        p = os.path.join(d, name)
        if os.path.exists(os.path.join(p, 'style.json')):
            return p
    raise SystemExit('Стиля «%s» нет: нет папки styles/%s/style.json ни в проекте, ни в engine/video/styles '
                     '(есть: %s)' % (name, name, ', '.join(names(project_root)) or 'ни одного'))


def _num(v, spec, where):
    typ, lo, hi = spec
    if isinstance(v, bool) or not isinstance(v, typ):
        raise SystemExit('%s: ожидается число, а стоит %r' % (where, v))
    if not lo <= v <= hi:
        raise SystemExit('%s: %s вне [%s, %s]' % (where, v, lo, hi))


def validate(name, data, css):
    w = 'styles/%s/style.json' % name
    extra = set(data) - TOP_KEYS
    if extra:
        raise SystemExit('%s: лишнее поле %s (известны: %s)' % (w, sorted(extra), ', '.join(sorted(TOP_KEYS))))
    for k in ('name', 'label', 'motion', 'sfx', 'decor', 'fonts', 'objects'):
        if k not in data:
            raise SystemExit('%s: нет обязательного поля %s' % (w, k))
    if data['name'] != name or not NAME_RE.match(name) or name == NONE:
        raise SystemExit('%s: name «%s» ≠ имени папки «%s» (имя — латиница, цифры, дефис; «none» занято)'
                         % (w, data['name'], name))
    mo = data['motion']
    for k in MOTION_KEYS:
        if k not in mo:
            raise SystemExit('%s: нет обязательного поля motion.%s' % (w, k))
        _num(mo[k], MOTION_KEYS[k], '%s motion.%s' % (w, k))
    for k in set(mo) & set(MOTION_OPT):
        _num(mo[k], MOTION_OPT[k], '%s motion.%s' % (w, k))
    if set(mo) - set(MOTION_KEYS) - set(MOTION_OPT):
        raise SystemExit('%s: лишнее поле motion.%s' % (w, sorted(set(mo) - set(MOTION_KEYS) - set(MOTION_OPT))[0]))
    sfx = data['sfx']
    if not isinstance(sfx, dict) or set(sfx) - {'clips', '_comment'} or not isinstance(sfx.get('clips'), dict):
        raise SystemExit('%s: sfx — {"clips": {вид клипа: {lp_hz?, grit?, crackle?}}}' % w)
    for clip, mat in sfx['clips'].items():
        if not isinstance(mat, dict) or not mat or set(mat) - set(SFX_CLIP_KEYS) - {'wave'}:
            raise SystemExit('%s: sfx.clips.%s — поля только из %s' % (w, clip, ', '.join(sorted(set(SFX_CLIP_KEYS) | {'wave'}))))
        for k, v in mat.items():
            if k == 'wave':
                if v not in SFX_WAVES:
                    raise SystemExit('%s: sfx.clips.%s.wave = %r — только %s' % (w, clip, v, ', '.join(SFX_WAVES)))
                continue
            _num(v, SFX_CLIP_KEYS[k], '%s sfx.clips.%s.%s' % (w, clip, k))
    dec = data['decor']
    if not isinstance(dec, dict) or not dec:
        raise SystemExit('%s: decor — непустая палитра декора стиля {роль: "#RRGGBB"}' % w)
    for role, hx in dec.items():
        if not re.match(r'^[a-z][a-z0-9_]*$', role) or not isinstance(hx, str) or not HEX_RE.match(hx):
            raise SystemExit('%s: decor.%s = %r — роль латиницей, цвет #RRGGBB' % (w, role, hx))
    fonts = data['fonts']
    if not isinstance(fonts, dict) or 'title' not in fonts:
        raise SystemExit('%s: fonts — {"title": {...}, "decor"?: {...}}, шрифт заголовка обязателен' % w)
    odd = sorted(r for r in fonts if r != '_comment' and not FONT_ROLE_RE.match(r))
    if odd:
        raise SystemExit('%s: fonts.%s — имя роли шрифта: латиница, цифры, «_» (title, decor или своя роль плагина)'
                         % (w, odd[0]))
    for role in font_roles(fonts):
        f = fonts[role]
        if isinstance(f, dict) and f.get('kind') == 'code':
            # надпись, нарисованная кодом (пиксельный шрифт, вырезанные буквы): файла нет, рисует plugin.js
            if role != 'title' or set(f) - {'kind', 'note'}:
                raise SystemExit('%s: fonts.%s — kind "code" бывает только у title: {"kind": "code", "note"?}' % (w, role))
            continue
        if not isinstance(f, dict) or not f.get('family') or not isinstance(f.get('files'), list) or not f['files'] \
                or set(f) - {'family', 'files', 'weight', 'note'}:
            raise SystemExit('%s: fonts.%s — {family, files: [имя файла…], weight?, note?}' % (w, role))
    obj = data['objects']
    if not isinstance(obj, list) or len(obj) < OBJECTS_MIN or not all(isinstance(o, str) and o for o in obj):
        raise SystemExit('%s: objects — список предметов мира стиля, не меньше %d (есть %s)'
                         % (w, OBJECTS_MIN, len(obj) if isinstance(obj, list) else obj))
    for fname, text in css.items():
        if text is not None:
            check_css(name, text, fname)


def check_css(name, css, fname='style.css'):
    """Каждое правило style.css / world.css привязано к стилю: селектор содержит [data-style="<name>"]."""
    w = 'styles/%s/%s' % (name, fname)
    tag = '[data-style="%s"]' % name
    s = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
    i, depth, start = 0, 0, 0
    while i < len(s):
        c = s[i]
        if c == '{':
            if depth == 0:
                head = s[start:i].strip()
                if head.startswith('@'):
                    m = re.match(r'@keyframes\s+([\w-]+)$', head)
                    if not m or not m.group(1).startswith(name + '-'):
                        raise SystemExit('%s: «%s» — из @-правил можно только @keyframes %s-…' % (w, head[:60], name))
                    # блок @keyframes пропускаем целиком
                    d, j = 1, i + 1
                    while j < len(s) and d:
                        d += {'{': 1, '}': -1}.get(s[j], 0)
                        j += 1
                    i, start = j, j
                    continue
                for sel in head.split(','):
                    if tag not in sel:
                        raise SystemExit('%s: селектор «%s» не привязан к стилю — нужен %s '
                                         '(.scene%s для содержания, #root%s для каркаса и слоёв)'
                                         % (w, sel.strip()[:80], tag, tag, tag))
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                start = i + 1
        elif c == ';' and depth == 0:
            head = s[start:i].strip()
            if head:
                raise SystemExit('%s: «%s» — @import и правила вне блока запрещены' % (w, head[:60]))
            start = i + 1
        i += 1


def read(p):
    with open(p, encoding='utf-8-sig') as fh:
        return fh.read()


def load(name, project_root=None):
    """{name, dir, data, css, world_css, plugin, fonts{роль: путь|None}} — style.json проверен."""
    d = folder(name, project_root)
    try:
        data = json.loads(read(os.path.join(d, 'style.json')))
    except ValueError as e:
        raise SystemExit('styles/%s/style.json не разбирается: %s' % (name, e))
    def opt(f):
        p = os.path.join(d, f)
        return read(p) if os.path.exists(p) else None
    css = {'style.css': opt('style.css'), 'world.css': opt('world.css')}
    validate(name, data, css)
    fonts = {role: (CODE if data['fonts'][role].get('kind') == 'code' else font_file(name, data['fonts'][role], d, project_root))
             for role in font_roles(data['fonts'])}
    return {'name': name, 'dir': d, 'data': data, 'css': css['style.css'], 'world_css': css['world.css'],
            'plugin': opt('plugin.js'), 'fonts': fonts}


def font_roles(fonts):
    """Роли шрифтов стиля по порядку: title, decor, затем свои роли плагина по алфавиту (порядок — в CSS страницы)."""
    return [r for r in FONT_ROLES if fonts.get(r) is not None] + sorted(r for r in fonts if r not in FONT_ROLES and r != '_comment')


def font_dirs(style_dir, project_root=None):
    """Где искать файл шрифта стиля: папка стиля, <проект>/assets/fonts, шрифты движка (engine/video/assets/fonts),
    последними — системные (%WINDIR%/Fonts): ими пользуется только свой стиль проекта, стили движка — файлами."""
    out = [style_dir]
    if project_root:
        out.append(os.path.join(str(project_root), 'assets', 'fonts'))
    out.append(ENGINE_FONTS)
    if os.environ.get('WINDIR'):
        out.append(os.path.join(os.environ['WINDIR'], 'Fonts'))
    return out


def font_file(name, spec, style_dir, project_root=None):
    """Первый найденный файл шрифта из spec.files; нет ни одного — None (заголовок останется фирменным).
    Найденный без кириллицы — отказ: заголовки русские."""
    for fn in spec['files']:
        for d in font_dirs(style_dir, project_root):
            p = os.path.join(d, fn)
            if os.path.exists(p):
                if not has_cyrillic(p):
                    raise SystemExit('styles/%s/style.json fonts: в %s нет кириллицы (%s) — возьми другой файл'
                                     % (name, fn, CYR_PROBE))
                return p
    return None


def has_cyrillic(path):
    """Буквы CYR_PROBE рисуются не пустым глифом (.notdef) — рендер Pillow против заведомо пустого кода."""
    from PIL import ImageFont
    ft = ImageFont.truetype(path, 40)
    empty = bytes(ft.getmask('\U0010FFFD'))
    return all(bytes(ft.getmask(c)) != empty for c in CYR_PROBE)


def core_js():
    return read(os.path.join(CORE, 'core.js'))


def scene_styles(project, film, sbs, forced=None):
    """{сцена: имя стиля | None} по правилу выбора; forced — проход фильма (имя или NONE)."""
    base = project.get('style')
    if film.get('style') is not None:
        base = film['style']
    if forced is not None:
        base = forced
    out = {}
    for sb in sbs:
        st = sb['style'] if 'style' in sb else base
        out[sb['scene']] = None if st in (None, NONE) else st
    return out
