# -*- coding: utf-8 -*-
"""Раскадровка сцены: схема из конфигов проекта, проверка, своя разметка.

    python engine/video/storyboard.py --schema            записать <out>/schema.json из конфигов, вывести путь
    python engine/video/storyboard.py <раскадровка.json>  проверка по схеме, код 0 / 1
    python engine/video/storyboard.py --red               порчи проверяльщика (каждая — своей строкой)

Схема — schema.core.json движка (язык раскадровки) + enum, которые генератор подставляет из конфигов:
@palette — роли палитры tokens.json, @chapters — id глав project.json, @tones — тоны kinds.tones,
@levels — уровни непрозрачности motion, @styles+null — папки стилей (styles/_core/registry.py) + none + null, @canvas_w_in / @canvas_h_in — размер полотна в дюймах.
Ручной копии enum нет: правка tokens.json / project.json меняет схему при следующей сборке.

jsonschema на машине нет, поэтому здесь маленький проверяльщик ровно того подмножества
JSON Schema 2020-12, которое использует схема; незнакомое ключевое слово — ошибка, а не пропуск.
"""
import copy
import json
import os
import re
import sys

sys.dont_write_bytecode = True
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import config  # noqa: E402
sys.path.insert(0, os.path.join(HERE, 'styles', '_core'))
import registry as styles_registry  # noqa: E402

CORE_PATH = os.path.join(HERE, 'schema.core.json')

KNOWN = {'$schema', '$id', 'title', 'description', 'default', '$defs', 'type', 'required',
         'properties', 'additionalProperties', 'enum', 'const', 'pattern', 'minimum',
         'maximum', 'exclusiveMinimum', 'minLength', 'minItems', 'maxItems', 'items', '$ref', 'allOf',
         'oneOf', 'if', 'then', 'else', 'dependentRequired', 'propertyNames'}
TYPES = {'object': dict, 'array': list, 'string': str, 'boolean': bool}


def _type_ok(v, t):
    if t == 'integer':
        return isinstance(v, int) and not isinstance(v, bool)
    if t == 'number':
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    return isinstance(v, TYPES[t])


def validate(inst, schema, root, path='$'):
    """Список ошибок «путь: что не так»; пустой — раскадровка годна."""
    if schema is True:
        return []
    if schema is False:
        return ['%s: поле здесь запрещено' % path]
    errs = []
    unknown = set(schema) - KNOWN
    if unknown:
        raise ValueError('Проверяльщик не знает ключей схемы %s в %s' % (sorted(unknown), path))
    if '$ref' in schema:
        ref = schema['$ref']
        assert ref.startswith('#/$defs/'), ref
        errs += validate(inst, root['$defs'][ref[8:]], root, path)
    if 'type' in schema and not _type_ok(inst, schema['type']):
        return errs + ['%s: ожидается %s' % (path, schema['type'])]
    if 'enum' in schema and inst not in schema['enum']:
        errs.append('%s: %r не из %r' % (path, inst, schema['enum']))
    if 'const' in schema and inst != schema['const']:
        errs.append('%s: ожидается %r' % (path, schema['const']))
    if isinstance(inst, str):
        if 'pattern' in schema and not re.search(schema['pattern'], inst):
            errs.append('%s: %r не по шаблону %s' % (path, inst, schema['pattern']))
        if 'minLength' in schema and len(inst) < schema['minLength']:
            errs.append('%s: пустая строка' % path)
    if isinstance(inst, (int, float)) and not isinstance(inst, bool):
        if 'minimum' in schema and inst < schema['minimum']:
            errs.append('%s: %r меньше %r' % (path, inst, schema['minimum']))
        if 'maximum' in schema and inst > schema['maximum']:
            errs.append('%s: %r больше %r' % (path, inst, schema['maximum']))
        if 'exclusiveMinimum' in schema and inst <= schema['exclusiveMinimum']:
            errs.append('%s: %r не больше %r' % (path, inst, schema['exclusiveMinimum']))
    if isinstance(inst, dict):
        for k in schema.get('required', []):
            if k not in inst:
                errs.append('%s: нет поля «%s»' % (path, k))
        for k, need in schema.get('dependentRequired', {}).items():
            if k in inst:
                errs += ['%s: «%s» требует поля «%s»' % (path, k, n) for n in need if n not in inst]
        props = schema.get('properties', {})
        for k, v in inst.items():
            if k in props:
                errs += validate(v, props[k], root, '%s.%s' % (path, k))
            elif schema.get('additionalProperties') is False:
                errs.append('%s: лишнее поле «%s»' % (path, k))
            elif isinstance(schema.get('additionalProperties'), dict):
                errs += validate(v, schema['additionalProperties'], root, '%s.%s' % (path, k))
            if 'propertyNames' in schema:
                errs += ['%s: имя поля %s' % (path, e.split(': ', 1)[1]) for e in validate(k, schema['propertyNames'], root, path)]
    if isinstance(inst, list):
        if 'minItems' in schema and len(inst) < schema['minItems']:
            errs.append('%s: меньше %d элементов' % (path, schema['minItems']))
        if 'maxItems' in schema and len(inst) > schema['maxItems']:
            errs.append('%s: больше %d элементов' % (path, schema['maxItems']))
        if 'items' in schema:
            for i, v in enumerate(inst):
                errs += validate(v, schema['items'], root, '%s[%d]' % (path, i))
    for sub in schema.get('allOf', []):
        errs += validate(inst, sub, root, path)
    if 'oneOf' in schema:
        ok = sum(1 for sub in schema['oneOf'] if not validate(inst, sub, root, path))
        if ok != 1:
            alts = ' | '.join(','.join(sub.get('required', ['?'])) for sub in schema['oneOf'])
            errs.append('%s: нужно ровно одно из (%s), а подходит %d' % (path, alts, ok))
    if 'if' in schema:
        if not validate(inst, schema['if'], root, path):
            if 'then' in schema:
                errs += validate(inst, schema['then'], root, path)
        elif 'else' in schema:
            errs += validate(inst, schema['else'], root, path)
    return errs


# ---------------------------------------------------------------- схема из конфигов
def build_schema(P):
    """schema.core.json + enum из конфигов проекта P (config.Project). Метки @… заменяются везде."""
    with open(CORE_PATH, encoding='utf-8') as fh:
        core = json.load(fh)
    m = P.motion
    roles = sorted(P.palette)
    chapters = [c['id'] for c in P.chapters]
    if len(set(chapters)) != len(chapters):
        raise SystemExit('project.json chapters: id глав повторяются: %s' % chapters)
    subst = {
        '@palette': roles, '@palette+null': roles + [None],
        '@chapters': chapters, '@chapters+null': chapters + [None],
        '@tones': sorted(P.kinds().get('tones', {})),
        '@levels': [m['level_shade'], m['level_mid'], 1],
        '@canvas_w_in': round(P.W / P.PX, 4), '@canvas_h_in': round(P.H / P.PX, 4),
        '@styles+null': styles_registry.names(P.root) + [styles_registry.NONE, None],
    }

    def walk(n):
        if isinstance(n, dict):
            return {k: walk(v) for k, v in n.items()}
        if isinstance(n, list):
            return [walk(v) for v in n]
        if isinstance(n, str) and n.startswith('@'):
            if n not in subst:
                raise SystemExit('schema.core.json: неизвестная метка %s' % n)
            return subst[n]
        return n
    return walk(core)


def write_schema(P):
    """Пишет <out>/schema.json (для редакторов и людей) и возвращает схему."""
    s = build_schema(P)
    os.makedirs(P.out, exist_ok=True)
    p = os.path.join(P.out, 'schema.json')
    with open(p, 'w', encoding='utf-8') as fh:
        json.dump(s, fh, ensure_ascii=False, indent=1)
    return s, p


def load(scene, scenes_dir, schema):
    """Раскадровка сцены + текст её разметки (или None). Падает со списком ошибок."""
    d = os.path.join(scenes_dir, scene)
    p = os.path.join(d, 'storyboard.json')
    if not os.path.exists(p):
        raise SystemExit('Сцены «%s» нет: не найден %s (раскадровку пишет режиссёр)' % (scene, p))
    with open(p, encoding='utf-8') as fh:
        sb = json.load(fh)
    errs = validate(sb, schema, schema)
    if sb.get('scene') != scene:
        errs.append('$.scene: «%s» не совпадает с папкой «%s»' % (sb.get('scene'), scene))
    files = sorted(f for f in os.listdir(d) if f != 'storyboard.json')
    markup = None
    if sb.get('markup'):
        mp = os.path.join(d, sb['markup'])
        if not os.path.exists(mp):
            errs.append('$.markup: нет файла %s' % mp)
        else:
            with open(mp, encoding='utf-8') as fh:
                markup = fh.read()
    extra = [f for f in files if f != sb.get('markup')]
    if extra:
        errs.append('сцена = раскадровка + не больше одного файла разметки; лишнее: %s' % extra)
    if errs:
        raise SystemExit('Раскадровка %s не годится:\n  ' % p + '\n  '.join(errs))
    return sb, markup


# ---------------------------------------------------------------- своя разметка
MARKUP_EL = re.compile(r'<(\w+)\b([^>]*\bclass="[^"]*\bel\b[^"]*"[^>]*)>')
LAYER_ATTR = re.compile(r'\bdata-layer="([^"]*)"')
WITH_ATTR = re.compile(r'\bdata-with="([^"]*)"')
TEXT_CLASS = re.compile(r'class="[^"]*\bt\b')


def markup_boxes(markup):
    """{id: (left, top, width, height)} верхних элементов разметки — из inline style в px."""
    boxes = {}
    for m in MARKUP_EL.finditer(markup):
        attrs = m.group(2)
        mid = re.search(r'\bid="([a-z0-9-]+)"', attrs)
        st = re.search(r'\bstyle="([^"]*)"', attrs)
        if not mid or not st:
            raise SystemExit('Разметка: у элемента class="el" нужны id и style с left/top/width/height в px: %s' % m.group(0))
        vals = dict(re.findall(r'(left|top|width|height)\s*:\s*([\d.]+)px', st.group(1)))
        if len(vals) != 4:
            raise SystemExit('Разметка: у #%s в style нет left/top/width/height в px' % mid.group(1))
        boxes[mid.group(1)] = tuple(float(vals[k]) for k in ('left', 'top', 'width', 'height'))
    return boxes


def prefix_ids(markup, scene):
    """id="x" → id="<сцена>--x": id во всём фильме не повторяются."""
    return re.sub(r'\bid="([a-z0-9-]+)"', lambda m: 'id="%s--%s"' % (scene, m.group(1)), markup)


def _markup_bodies(markup):
    ms = list(MARKUP_EL.finditer(markup))
    out = []
    for k, m in enumerate(ms):
        mid = re.search(r'\bid="([a-z0-9-]+)"', m.group(2))
        body = markup[m.end():ms[k + 1].start() if k + 1 < len(ms) else len(markup)]
        out.append((mid.group(1) if mid else None, m.group(2), body))
    return out


def markup_texted(markup):
    """id верхних элементов разметки, у которых есть надпись .t."""
    return [mid for mid, _, body in _markup_bodies(markup) if mid and TEXT_CLASS.search(body)]


def markup_layers(markup):
    """{id: 'under'|'over'} верхних элементов разметки с data-layer."""
    out = {}
    for mid, attrs, _ in _markup_bodies(markup):
        lay = LAYER_ATTR.search(attrs)
        if mid and lay:
            if lay.group(1) not in ('under', 'over'):
                raise SystemExit('Разметка: у #%s data-layer="%s" — допустимо under, over' % (mid, lay.group(1)))
            out[mid] = lay.group(1)
    return out


CAM_EL = re.compile(r'<\w+\b([^>]*\bclass="[^"]*\bcam-pos\b[^"]*"[^>]*)>')


def markup_cams(markup):
    """{имя: (left, top, width, height) px} положений камеры сцены — узлы разметки
    <div class="cam-pos" data-cam="<имя>" style="left:…px;top:…px;width:…px;height:…px"></div>.
    Положение — рамка мира, которую камера растягивает на весь кадр (plugins.act, метка cam · move)."""
    out = {}
    for m in CAM_EL.finditer(markup or ''):
        attrs = m.group(1)
        name = re.search(r'\bdata-cam="([a-z0-9-]+)"', attrs)
        st = re.search(r'\bstyle="([^"]*)"', attrs)
        vals = dict(re.findall(r'(left|top|width|height)\s*:\s*(-?[\d.]+)px', st.group(1))) if st else {}
        if not name or len(vals) != 4:
            raise SystemExit('Разметка: у положения камеры нужны data-cam="<имя>" и style с left/top/width/height в px: %s'
                             % m.group(0))
        if name.group(1) in out:
            raise SystemExit('Разметка: положение камеры «%s» объявлено дважды' % name.group(1))
        out[name.group(1)] = tuple(float(vals[k]) for k in ('left', 'top', 'width', 'height'))
    return out


def markup_with(markup):
    """{id: id хозяина} верхних элементов разметки с data-with — спутник едет со своей надписью."""
    out = {}
    for m in MARKUP_EL.finditer(markup):
        attrs = m.group(2)
        mid = re.search(r'\bid="([a-z0-9-]+)"', attrs)
        w = WITH_ATTR.search(attrs)
        if mid and w:
            if not re.fullmatch(r'[a-z0-9-]+', w.group(1)):
                raise SystemExit('Разметка: у #%s data-with="%s" — нужен id элемента этой сцены' % (mid.group(1), w.group(1)))
            out[mid.group(1)] = w.group(1)
    return out


# ---------------------------------------------------------------- порчи проверяльщика
# Годная раскадровка со всеми полями ядра на демо-конфигах шаблона; каждая порча обязана дать свою ошибку.
_GOOD = {
    'scene': 'x', 'number': 2, 'title': 'T', 'start_state': {}, 'end_state': {}, 'style': 'sketchbook',
    'decor_zones': [{'x': 10.3, 'y': 5.6, 'w': 8.45, 'h': 2.85}],
    'title_at': {'reply': 3, 'at': 0.1}, 'chapter': 'steps', 'chapter_from': 'intro', 'chapter_at': {'reply': 3, 'at': 0.3},
    'tracker_emph': [{'reply': 3, 'at': 0.5}],
    'elements': [{'id': 'a', 'kind': 'text', 'x': 1, 'y': 4, 'w': 5, 'h': 0.5, 'text': 'A б', 'size': 20, 'layer': 'under',
                  'color': 'highlight', 'text_parts': {'b': 'б'}},
                 {'id': 'hd', 'kind': 'box', 'x': 1.25, 'y': 3.45, 'w': 8.65, 'h': 0.8, 'tone': 'mid', 'fill': 'accent_pale',
                  'line': 'accent', 'line_pt': 1.5, 'text': 'СРЕДНИЙ УРОВЕНЬ', 'size': 24, 'bold': True, 'color': 'accent',
                  'pad': 0.29, 'align': 'left', 'valign': 'middle', 'text_parts': {'word': 'СРЕДНИЙ', 'lvl': 'УРОВЕНЬ'}},
                 {'id': 'ln', 'kind': 'box', 'x': 9.9, 'y': 3.45, 'w': 0.02, 'h': 5, 'fill': 'line', 'line': None},
                 {'id': 'b-1', 'kind': 'bullet', 'x': 1.25, 'y': 5.76, 'w': 8.65, 'h': 0.43, 'text': 'план и отчёт',
                  'size': 21.75, 'marker': 'accent', 'marker_size': 0.10, 'text_dx': 0.25,
                  'text_parts': {'slot': 'план', '*': ['slot', 'rest']}},
                 {'id': 'card-3', 'kind': 'quiz', 'x': 1.25, 'y': 6.65, 'w': 8.65, 'h': 2.95, 'num': 3, 'text': '«…»',
                  'answer': 'СРЕДНИЙ', 'tone': 'mid', 'size': 21.75},
                 {'id': 'pl', 'kind': 'plaque', 'x': 1.25, 'y': 9, 'w': 8, 'h': 0.8, 'text': 'П', 'size': 21.75},
                 {'id': 'ic', 'kind': 'icon', 'x': 7, 'y': 3.5, 'w': 0.44, 'h': 0.44, 'icon': 'bell.svg', 'color': 'accent', 'with': 'a'}],
    'beats': [
        {'reply': 3, 'at': 0.1, 'action': 'show', 'targets': ['a'], 'anim': 'lift', 'level': 0.2},
        {'reply': 3, 'at': 0.2, 'action': 'hide', 'targets': ['a.text'], 'anim': 'cut'},
        {'reply': 3, 'at': 0.3, 'action': 'level', 'targets': ['a'], 'value': 0.45, 'dur': 0.5, 'ease': 'power1.inOut'},
        {'reply': 3, 'at': 0.4, 'action': 'emph', 'targets': ['a'], 'style': 'ring', 'amp': 10, 'dur': 0.6},
        {'reply': 3, 'at': 0.5, 'action': 'emph', 'targets': ['a'], 'amp': 0.04},
        {'reply': 3, 'at': 0.6, 'action': 'move', 'targets': ['a.text'], 'to_text': {'el': 'demo-b:lead', 'sub': 'н', 'nth': 1},
         'fit': 'text', 'size': 24, 'color': 'ink', 'dur': 0.7, 'ease': 'power3.inOut'},
        {'reply': 3, 'at': 0.7, 'action': 'move', 'targets': ['a'], 'to': {'x': 1, 'y': 4, 'w': 2, 'h': 1}},
        {'reply': 3, 'at': 0.8, 'action': 'move', 'targets': ['a'], 'to_el': 'b', 'fit': 'none',
         'anchor': [1, 0.5], 'self': [0, 0.5], 'dx': 0.3, 'tilt': -8},
        {'reply': 3, 'at': 0.9, 'action': 'emph', 'targets': ['a'], 'style': 'breathe', 'amp': 0.015,
         'until': {'reply': 4, 'at': 0.5}},
        {'reply': 4, 'at': 0.1, 'action': 'emph', 'targets': ['a'], 'style': 'spin', 'dir': -1, 'dur': 0.8},
        {'reply': 4, 'at': 0.3, 'action': 'move', 'targets': ['a'], 'to_el': 'b-1', 'fit': 'box', 'pad': [0.15, 0.09]},
        {'reply': 4, 'at': 0.6, 'action': 'emph', 'targets': ['a.b'], 'style': 'flash', 'color': 'accent'},
        {'reply': 4, 'at': 0.7, 'action': 'hide', 'targets': ['a'], 'anim': 'fade', 'dur': 0.9},
    ]}
_DEL = object()


def _set(path, value):
    def f(sb):
        node = sb
        for k in path[:-1]:
            node = node[k]
        if value is _DEL:
            del node[path[-1]]
        else:
            node[path[-1]] = value
    return f


RED = [
    ('hide с анимацией входа', _set(['beats', 1, 'anim'], 'pop'), "$.beats[1].anim: 'pop' не из"),
    ('show с неизвестной анимацией', _set(['beats', 0, 'anim'], 'slide'), "$.beats[0].anim: 'slide' не из"),
    ('show с уровнем вне шкалы', _set(['beats', 0, 'level'], 0.3), '$.beats[0].level: 0.3 не из'),
    ('level без value', _set(['beats', 2, 'value'], _DEL), '$.beats[2]: нет поля «value»'),
    ('level вне шкалы', _set(['beats', 2, 'value'], 0.5), '$.beats[2].value: 0.5 не из'),
    ('level с чужой кривой', _set(['beats', 2, 'ease'], 'back.out'), "$.beats[2].ease: 'back.out' не из"),
    ('ring с амплитудой пульса', _set(['beats', 3, 'amp'], 0.04), '$.beats[3].amp: 0.04 меньше 2'),
    ('pulse с амплитудой звона', _set(['beats', 4, 'amp'], 14), '$.beats[4].amp: 14 больше 0.1'),
    ('emph с неизвестным стилем', _set(['beats', 4, 'style'], 'shake'), "$.beats[4].style: 'shake' не из"),
    ('move без цели', _set(['beats', 6, 'to'], _DEL), 'нужно ровно одно из (to | to_el | to_text), а подходит 0'),
    ('move с двумя целями', _set(['beats', 6, 'to_el'], 'b'), 'нужно ровно одно из (to | to_el | to_text), а подходит 2'),
    ('move: подстрока пустая', _set(['beats', 5, 'to_text', 'sub'], ''), '$.beats[5].to_text.sub: пустая строка'),
    ('move: to_text без el', _set(['beats', 5, 'to_text', 'el'], _DEL), '$.beats[5].to_text: нет поля «el»'),
    ('move: anchor из трёх чисел', _set(['beats', 7, 'anchor'], [1, 0.5, 0]), '$.beats[7].anchor: больше 2 элементов'),
    ('move: self вне рамки', _set(['beats', 7, 'self'], [0, 1.5]), '$.beats[7].self[1]: 1.5 больше 1'),
    ('move: неизвестный fit', _set(['beats', 7, 'fit'], 'cover'), "$.beats[7].fit: 'cover' не из"),
    ('move: цвет не из палитры', _set(['beats', 5, 'color'], '#FF0000'), "$.beats[5].color: '#FF0000' не из"),
    ('move: to_el с кривым id', _set(['beats', 7, 'to_el'], 'S13:Lead'), "$.beats[7].to_el: 'S13:Lead' не по шаблону"),
    ('цель с кривой частью', _set(['beats', 1, 'targets'], ['a.Text']), "$.beats[1].targets[0]: 'a.Text' не по шаблону"),
    ('title_at без reply', _set(['title_at', 'reply'], _DEL), '$.title_at: нет поля «reply»'),
    ('title_at с лишним полем', _set(['title_at', 'dur'], 1), '$.title_at: лишнее поле «dur»'),
    ('chapter_from без chapter_at', _set(['chapter_at'], _DEL), '$: «chapter_from» требует поля «chapter_at»'),
    ('chapter_at без chapter_from', _set(['chapter_from'], _DEL), '$: «chapter_at» требует поля «chapter_from»'),
    ('глава не из project.json', _set(['chapter_from'], 'nope'), "$.chapter_from: 'nope' не из"),
    ('layer не из двух', _set(['elements', 0, 'layer'], 'top'), "$.elements[0].layer: 'top' не из"),
    ('move: наклон больше 20°', _set(['beats', 7, 'tilt'], 35), '$.beats[7].tilt: 35 больше 20'),
    ('move: наклон строкой', _set(['beats', 7, 'tilt'], 'left'), '$.beats[7].tilt: ожидается number'),
    ('breathe без until', _set(['beats', 8, 'until'], _DEL), '$.beats[8]: нет поля «until»'),
    ('breathe сильнее 2 %', _set(['beats', 8, 'amp'], 0.04), '$.beats[8].amp: 0.04 больше 0.02'),
    ('breathe с dur', _set(['beats', 8, 'dur'], 1.0), '$.beats[8].dur: поле здесь запрещено'),
    ('until у пульса', _set(['beats', 4, 'until'], {'reply': 4, 'at': 0.5}), '$.beats[4].until: поле здесь запрещено'),
    ('until без reply', _set(['beats', 8, 'until', 'reply'], _DEL), '$.beats[8].until: нет поля «reply»'),
    ('tracker_emph не список', _set(['tracker_emph'], {'reply': 3, 'at': 0.5}), '$.tracker_emph: ожидается array'),
    ('цвет текста hex, а не роль', _set(['elements', 0, 'color'], '#4472C4'), "$.elements[0].color: '#4472C4' не из"),
    ('часть-подстрока пустая', _set(['elements', 0, 'text_parts', 'b'], ''), '$.elements[0].text_parts.b: пустая строка'),
    ('имя части с заглавной', _set(['elements', 0, 'text_parts', 'B'], 'б'), "$.elements[0].text_parts: имя поля 'B' не по шаблону"),
    ('box: заливка не из палитры', _set(['elements', 1, 'fill'], 'red'), "$.elements[1].fill: 'red' не из"),
    ('box: неизвестный tone', _set(['elements', 1, 'tone'], 'max'), "$.elements[1].tone: 'max' не из"),
    ('box: обводка не из палитры', _set(['elements', 1, 'line'], '#12FCE5'), "$.elements[1].line: '#12FCE5' не из"),
    ('box: valign не из трёх', _set(['elements', 1, 'valign'], 'center'), "$.elements[1].valign: 'center' не из"),
    ('box: части без текста', _set(['elements', 2, 'text_parts'], {'x': 'y'}), '$.elements[2]: «text_parts» требует поля «text»'),
    ('bullet без текста', _set(['elements', 3, 'text'], _DEL), '$.elements[3]: нет поля «text»'),
    ('bullet: маркер не из палитры', _set(['elements', 3, 'marker'], '#B0B3B6'), "$.elements[3].marker: '#B0B3B6' не из"),
    ('bullet: «*» из одной части', _set(['elements', 3, 'text_parts', '*'], ['slot']), '$.elements[3].text_parts.*: меньше 2 элементов'),
    ('quiz без ответа', _set(['elements', 4, 'answer'], _DEL), '$.elements[4]: нет поля «answer»'),
    ('quiz: tone info', _set(['elements', 4, 'tone'], 'info'), "$.elements[4].tone: 'info' не из"),
    ('кегль плашки крупнее 40', _set(['elements', 5, 'size'], 48), '$.elements[5].size: 48 больше 40'),
    ('иконка: x за полотном', _set(['elements', 6, 'x'], 25), '$.elements[6].x: 25 больше 20'),
    ('спутник: кривой id хозяина', _set(['elements', 6, 'with'], 'A B'), "$.elements[6].with: 'A B' не по шаблону"),
    ('spin с амплитудой', _set(['beats', 9, 'amp'], 0.04), '$.beats[9].amp: поле здесь запрещено'),
    ('spin: dir 2', _set(['beats', 9, 'dir'], 2), '$.beats[9].dir: 2 не из'),
    ('dir у пульса', _set(['beats', 4, 'dir'], -1), '$.beats[4].dir: поле здесь запрещено'),
    ('move: pad из трёх чисел', _set(['beats', 10, 'pad'], [0.1, 0.1, 0.1]), '$.beats[10].pad: нужно ровно одно из'),
    ('move: pad из одного числа', _set(['beats', 10, 'pad'], [0.1]), '$.beats[10].pad: меньше 2 элементов'),
    ('flash без цвета', _set(['beats', 11, 'color'], _DEL), '$.beats[11]: нет поля «color»'),
    ('flash цветом не из палитры', _set(['beats', 11, 'color'], '#FF0000'), "$.beats[11].color: '#FF0000' не из"),
    ('цвет у пульса', _set(['beats', 4, 'color'], 'accent'), '$.beats[4].color: поле здесь запрещено'),
    ('наплыв длиннее 2 с', _set(['beats', 12, 'dur'], 2.5), '$.beats[12].dur: 2.5 больше 2.0'),
    ('действие плагина без плагина', _set(['beats', 12, 'action'], 'signal'), "$.beats[12].action: 'signal' не из"),
    ('каркас не да/нет', _set(['frame'], 'blue'), '$.frame: ожидается boolean'),
    ('картинка-кадр не PNG', _set(['start_image'], 'assets/kadr.jpg'), '$.start_image:'),
    ('плагин не объектом', _set(['plugins'], {'glitch': 3}), '$.plugins.glitch: ожидается object'),
    ('поле плагина каркаса', _set(['header'], 'blue'), '$: лишнее поле «header»'),
    ('старое имя phase', _set(['phase'], 'steps'), '$: лишнее поле «phase»'),
    ('стиль не из папок styles/', _set(['style'], 'watercolor'), "$.style: 'watercolor' не из"),
    ('стиль списком', _set(['style'], ['film']), "$.style: ['film'] не из"),
    ('зона декора без высоты', _set(['decor_zones', 0, 'h'], _DEL), '$.decor_zones[0]: нет поля «h»'),
    ('зона декора за полотном', _set(['decor_zones', 0, 'x'], 25), '$.decor_zones[0].x: 25 больше 20'),
]


def red():
    P = config.Project()
    schema = build_schema(P)
    failed = 0
    e0 = validate(_GOOD, schema, schema)
    if e0:
        print('MISS образец со всеми полями ядра не проходит:\n  ' + '\n  '.join(e0))
        return 1
    print('ok   образец со всеми полями ядра проходит')
    for name, fn, expect in RED:
        sb = copy.deepcopy(_GOOD)
        fn(sb)
        errs = validate(sb, schema, schema)
        hit = [e for e in errs if expect in e]
        if hit:
            print('RED  %-34s -> %s' % (name, hit[0]))
        else:
            failed += 1
            print('MISS %-34s ждали «%s», получили: %s' % (name, expect, ' | '.join(errs) or '(годна)'))
    print('порч: %d, не покраснело своей строкой: %d' % (len(RED), failed))
    return 1 if failed else 0


def main():
    root, args = config.project_root.split_argv(sys.argv[1:])    # --project → MOTION_PROJECT → <шаблон>/project
    if args == ['--red']:
        sys.exit(red())
    P = config.Project(root)
    if args == ['--schema']:
        _, p = write_schema(P)
        print(p)
        return
    if not args:
        raise SystemExit(__doc__)
    schema = build_schema(P)
    bad = 0
    for p in args:
        with open(p, encoding='utf-8') as fh:
            errs = validate(json.load(fh), schema, schema)
        bad += bool(errs)
        print(('OK   %s' % p) if not errs else ('FAIL %s\n  ' % p + '\n  '.join(errs)))
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
