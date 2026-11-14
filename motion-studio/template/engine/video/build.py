# -*- coding: utf-8 -*-
"""Сборка ролика: раскадровки + звук → страница HyperFrames → промер DOM → mp4.

    python engine/video/build.py demo                   весь фильм films/demo.json → <out>/demo/video.mp4
    python engine/video/build.py demo --page            только страница, film.json и промер DOM (секунды)
    python engine/video/build.py demo --only demo-b     одна сцена → <out>/demo--demo-b/
    python engine/video/build.py film --only s07,s08 --page   пара сцен — шов без рендера
    python engine/video/build.py demo --estimate        без звука: длительности по ms строк / смете
    python engine/video/build.py demo --draft           CRF 23 вместо 18
    python engine/video/build.py demo --keep-frames     не удалять PNG-кадры
    python engine/video/build.py demo --png             кусок для склейки: кадры <out>/demo/frames/ и отметка
                                                        frames/stamp.json, без mp4; свежие кадры не рендерятся
                                                        заново (--force — заново; --frames N — пробные N кадров)
    python engine/video/build.py demo --workers 3 --chunk-sec 20 --tmp <папка>
    python engine/video/build.py styles                 фильм с проходами по стилям (films/styles.json "styles") →
                                                        <out>/styles/<стиль>/ + <out>/styles/styles-sheet.png
    python engine/video/build.py styles --style film    один проход в стиле (имя папки styles/ или none)

Стили — engine/video/styles/README.md: стиль сцены (раскадровка → проход → фильм → project.json style),
CSS и плагин стиля на странице, промер стиля styles/_core/probe_style.mjs → style_probe.json (check.py V21–V24).

Корень проекта — --project → MOTION_PROJECT → <шаблон>/project (engine/project_root.py); константы — project.json и tokens.json
(engine/video/config.py), схема раскадровки — engine/video/schema.core.json + enum из конфигов.
Шаги: раскадровки (схема, контракт стыка) → таймлайн из звука → огибающие голоса → index.html +
film.json → промер DOM (probe_dom.mjs → probe.json) → рендер HyperFrames в PNG кусками → один
ffmpeg на весь фильм со сведённым звуком → покадровый лист.

Кусок рендера — фильм: ролик из нескольких фильмов рендерится кусками (`--png`), склейка — engine/video/assemble.py
по монтажному листу project/montage.json. Пересборка страницы кадры куска не удаляет: годятся ли они, решает
отметка (engine/video/stamp.py). Безголовый Chrome (промеры и рендер) запускается только под замком
engine/chrome_lock.py — один на машину.

Почему png-sequence: ffprobe на машине может не быть, а HyperFrames зовёт его, чтобы промерить свой
mp4 и звук. PNG-последовательность он не промеряет, звук сводим сами — поэтому в композиции нет
<audio>, а tools/ffprobe.exe — заглушка, которая громко отказывает, если её всё-таки позовут.
"""
import argparse
import copy
import html
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

sys.dont_write_bytecode = True
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import config      # noqa: E402
import lipsync     # noqa: E402
import wallclock  # noqa: E402  настенное время кадра: таймер до события и часы (плагины timer, clock)
import storyboard  # noqa: E402
import timing      # noqa: E402
sys.path.insert(0, os.path.join(HERE, 'styles', '_core'))
import registry as styles_registry   # noqa: E402
import stamp as frame_stamp          # noqa: E402  отметка кадров куска (frames/stamp.json)
sys.path.insert(0, os.path.dirname(HERE))
import chrome_lock   # noqa: E402  замок безголового Chrome: один на машину (engine/chrome_lock.py)
import resources     # noqa: E402  свободное место и ОЗУ — печать перед рендером (engine/resources.py)

GSAP = os.path.join(HERE, 'node_modules', 'gsap', 'dist', 'gsap.min.js')
HF_BIN = os.path.join(HERE, 'node_modules', 'hyperframes', 'bin', 'hyperframes.mjs')
FFPROBE_STUB = os.path.join(HERE, 'tools', 'ffprobe.exe')
FFPROBE_STUB_SRC = os.path.join(HERE, 'tools', 'ffprobe_stub.cs')
CHUNK_SEC = 20.0           # кусок рендера: 20 с; HyperFrames требует свободными ~8,3 МБ на кадр куска (его оценка сверху)
CHUNK_PAGE = 'chunk.html'
ROUND_EPS = 5e-3           # доли кадра: моменты в файлах округлены до 4 знаков
STEP_TEXT_DX = 0.85        # ″: текст шага от левого края элемента (кружок 0,62 + зазор), как .step-text в stage.css
TEXT_LH = 1.2              # межстрочный у box, bullet, quiz (у обеих сторон текстового морфа один)
BOX_PAD, BOX_PAD_RIGHT = 0.29, 0.25
VALIGN = {'top': 'flex-start', 'middle': 'center', 'bottom': 'flex-end'}
BULLET_MARKER, BULLET_TEXT_DX = 0.12, 0.31
QUIZ = {'num': (0.29, 0.22, 0.62), 'text': (1.10, 0.20, 7.26, 1.85), 'answer_h': 0.70, 'answer_dx': 0.29}
DISPLACING = ('rise', 'lift', 'pop')      # входы, которые сдвигают или масштабируют элемент
START_IMAGE = 'start-image'               # id элемента картинки-кадра сцены (storyboard start_image)
PLUGINS_DIR = os.path.join(HERE, 'plugins')
FRAMELESS_FORBIDS = ('title_at', 'num_at', 'chapter_at', 'chapter_from', 'tracker_emph')
# Поля плагинов, без которых сборка отказывает (запасных чисел движения в коде нет: значение — из раскадровки
# сцены, иначе из tokens.json motion.<плагин>; см. engine/video/plugins/README.md)
PLUGIN_REQUIRED = {
    'glitch': ('from', 'to', 'seed', 'tear_px', 'bands', 'band_h', 'rgb_px', 'jitter_px', 'burst_gap', 'burst_frames',
               'calm', 'edge'),
    'timer': ('host', 'at', 'mode'),
    'clock': ('host', 'mode', 'format', 'digits_px', 'color', 'font'),
    'act': ('cues',),
}
CLOCK_MODES = ('digital',)
ACT_CUE_KEYS = ('id', 't', 'who', 'do')
CAM = 'cam'                    # who камеры сцены: исполняет движок (plugins/act.js), положения — разметка cam-pos
CAM_ASPECT_TOL = 0.01          # положение камеры — рамка с пропорциями кадра (± доля): масштаб один по обеим осям
TIMER_MODES = ('countdown', 'date')
TIMER_COUNTDOWN = ('digits_px', 'labels_px', 'gap_px', 'label_gap_px', 'digits_color', 'labels_color', 'digits_font',
                   'labels_font', 'labels', 'sep')
TIMER_DATE = ('date_text', 'labels_px', 'labels_color', 'labels_font')
ICON_COLOR_RE = re.compile(r'(stroke|fill)="#(?:fff|FFF|ffffff|FFFFFF)"')
OFFICE_COLOR_RE = re.compile(r'(stroke|fill)="#4472[Cc]4"')

P = None                   # config.Project — читает main()
SCENES_DIR = None


def log(msg):
    print(msg, flush=True)


def px(v):
    return round(v * P.PX, 2)


def pt_px(pt):
    return round(pt * P.PX / 72.0, 2)


def mo(key):
    return P.tok('motion.' + key)


# ---------------------------------------------------------------- ресурсы и токены
def icon_svg(name):
    with open(P.icon(name), encoding='utf-8') as fh:
        s = fh.read()
    s = re.sub(r'\sdata-dc-tpl="\d+"', '', s)
    s = re.sub(r'<\?xml[^>]*\?>', '', s)
    for _ in range(2):
        s = re.sub(r'(<svg\b[^>]*?)\s(width|height)="[^"]*"', r'\1', s)
    return recolor_svg(s, name)


def recolor_svg(s, name='svg'):
    """Белый (#fff) и акцент офисной темы (#4472C4) становятся currentColor — иконка берёт цвет вида.
    Свои цвета файла остаются, но только из палитры tokens.json: цвет вне палитры — ошибка сборки."""
    s = re.sub(r'<style\b[^>]*>[^<]*MsftOfcThm_[^<]*</style>', '', s)
    s = re.sub(r'\sclass="MsftOfcThm_[^"]*"', '', s)
    s = ICON_COLOR_RE.sub(r'\1="currentColor"', s)
    s = OFFICE_COLOR_RE.sub(r'\1="currentColor"', s)
    bad = sorted({c.upper() for c in re.findall(r'#[0-9A-Fa-f]{6}\b', s)} - set(P.palette.values()))
    if bad:
        raise SystemExit('Иконка %s: цвет вне палитры tokens.json после перекраски: %s' % (name, ', '.join(bad)))
    return s


FONT_WARM = 'АаЖжЁёЯя0189:«»'       # строка прогрева: каждое объявленное начертание грузится до промера (V11)


def font_css(out_dir):
    """@font-face из ролей шрифтов (tokens.json fonts + project.json fonts, config.all_fonts; файлы копируются в
    <out>/assets/fonts), --font-brand и --font-<роль> у каждой роли; описатели метрик (descriptors) — в @font-face."""
    faces, families = [], []
    for f in P.fonts:
        present = {}
        for wt, rel in f['files'].items():
            p = P.asset(rel, sub='assets/fonts')
            if p:
                present[wt] = p
        role = f.get('role', 'brand')
        if not present:
            if role != 'brand':
                raise SystemExit('Шрифт роли %s (%s): нет файла %s — роль без файла роняет страницу'
                                 % (role, f['family'], ', '.join(f['files'].values())))
            log('  шрифт %s не найден (%s) — пропущен' % (f['family'], ', '.join(f['files'].values())))
            continue
        if role == 'brand':
            families.append('"%s"' % f['family'])
        desc = ''.join('%s:%s;' % (k, v) for k, v in sorted((f.get('descriptors') or {}).items()))
        for wt, p in present.items():
            dst = os.path.join(out_dir, 'assets', 'fonts', os.path.basename(str(p)))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(p, dst)
            faces.append('@font-face{font-family:"%s";font-weight:%s;%ssrc:url("assets/fonts/%s");}'
                         % (f['family'], wt, desc, os.path.basename(str(p))))
    if not families:
        raise SystemExit('Нет ни одного файла шрифта роли brand (tokens.json fonts)')
    roles = ''.join('--font-%s:"%s", var(--font-brand);' % (f['role'], f['family'])
                    for f in P.fonts if f.get('role', 'brand') != 'brand')
    return '\n'.join(faces) + '\n:root{--font-brand:%s, sans-serif;%s}' % (', '.join(families), roles)


def font_warm_html():
    """Скрытые строки вне кадра — по одной на каждое начертание каждой роли: браузер грузит шрифт, только когда
    встретил его букву, а промер (V11) ждёт loaded у всех ролей, в том числе у тех, что сцена ещё не рисует."""
    return ''.join('<span style="position:absolute;left:-9999px;top:0;font-family:&quot;%s&quot;;font-weight:%s">%s</span>'
                   % (html.escape(f['family']), wt, FONT_WARM) for f in P.fonts for wt in f['files'])


def font_family(role, what):
    """Роль шрифта → значение font-family (роль, запасной — фирменный); неизвестная роль — отказ сборки."""
    fams = {f.get('role', 'brand'): f['family'] for f in P.fonts}
    if role not in fams:
        raise SystemExit('%s «%s»: такой роли нет в fonts (tokens.json + project.json; есть: %s)'
                         % (what, role, ', '.join(sorted(fams))))
    return '"%s", var(--font-brand)' % fams[role]


def tokens_css():
    """CSS-переменные из конфигов: --c-<роль>, --t-<роль>-size|weight|family, --k-… (виды, каркас, голос)."""
    v = ['--c-%s:%s' % (k, h) for k, h in sorted(P.palette.items())]
    fam = {f.get('role', 'brand'): f['family'] for f in P.fonts}
    for role, t in sorted(P.tokens['type'].items()):
        v += ['--t-%s-size:%spx' % (role, pt_px(t['size_pt'])), '--t-%s-weight:%s' % (role, t['weight'])]
        if t.get('family') in fam:
            v.append('--t-%s-family:"%s"' % (role, fam[t['family']]))
    for k, val in sorted(P.kinds().items()):
        if k in ('tones', 'shade_text'):
            continue
        if isinstance(val, str):
            v.append('--k-%s:%s' % (k, P.color(val, 'tokens.json kinds.%s' % k)))
        elif isinstance(val, dict):
            for sub, role in sorted(val.items()):
                v.append('--k-%s-%s:%s' % (k, sub, P.color(role, 'tokens.json kinds.%s.%s' % (k, sub))))
    fr = P.project.get('frame', {})
    tr = fr.get('tracker') or {}
    for name, role in (('title', (fr.get('title') or {}).get('color', 'ink')), ('number', (fr.get('number') or {}).get('color', 'primary')),
                       ('footer', (fr.get('footer') or {}).get('color', 'footer')), ('line', fr.get('line_color', 'line')),
                       ('tracker', tr.get('color', 'subtle')), ('tracker-fill', tr.get('fill', 'primary')),
                       ('tracker-on', tr.get('on_color', 'paper')), ('tracker-line', tr.get('line', 'line'))):
        v.append('--k-frame-%s:%s' % (name, P.color(role, 'project.json frame.%s' % name)))
    vb = P.project.get('voice_bars') or {}
    v.append('--k-voice-mute:%s' % P.color(vb.get('mute', 'footer'), 'project.json voice_bars.mute'))
    return ':root{%s;}\n#root{width:%dpx;height:%dpx;}' % (';'.join(v), P.W, P.H)


def type_size(role, override=None):
    return pt_px(override if override is not None else P.type(role)['size_pt'])


def type_weight(role, bold=None):
    if bold is None:
        return P.type(role)['weight']
    return 700 if bold else 400


# ---------------------------------------------------------------- элементы сцены
def element_html(scene, e):
    dom = '%s--%s' % (scene, e['id'])
    st = 'left:%spx;top:%spx;width:%spx;height:%spx;' % (px(e['x']), px(e['y']), px(e['w']), px(e['h']))
    k = e['kind']
    esc = html.escape
    K = P.kinds()
    if k == 'text':
        st += 'font-size:%spx;color:%s;font-weight:%s;text-align:%s;' % (
            type_size('text', e['size']), P.color(e.get('color', K.get('text_color', 'text'))),
            type_weight('text', e.get('bold', False)), e.get('align', 'left'))
        inner = '<span class="t" data-part="text">%s</span>' % text_with_parts(e)
    elif k == 'step':
        # ширина текста — от x + 0,85″ до правого края элемента, а при метке — до метки
        right = e['tag_x'] if (e.get('tag') and e.get('tag_x') is not None) else e['x'] + e['w']
        inner = ('<div class="step-num t" data-part="num">%d</div>'
                 '<div class="step-text t" data-part="text" style="width:%spx">%s</div>'
                 % (e['num'], px(right - e['x'] - STEP_TEXT_DX), esc(e['text'])))
        if e.get('tag'):
            left = px(e.get('tag_x', e['x'] + 6.0) - e['x'])
            inner += '<div class="step-tag t" data-part="tag" style="left:%spx">%s</div>' % (left, esc(e['tag']))
    elif k in ('card', 'plaque'):
        ico = '<div class="ico" data-part="icon">%s</div>' % icon_svg(e['icon']) if e.get('icon') else ''
        tst = ' style="font-size:%spx"' % pt_px(e['size']) if (k == 'plaque' and e.get('size')) else ''
        inner = ico + '<span class="t" data-part="text"%s>%s</span>' % (tst, esc(e['text']))
    elif k == 'icon':
        st += 'color:%s;' % P.color(e.get('color', K.get('icon_color', 'primary')))
        inner = icon_svg(e['icon'])
    elif k == 'box':
        b = box_style(e)
        inner = '<div class="bx-fill" data-part="fill" style="background:%s"></div>' % (b['fill'] or 'transparent')
        inner += ('<div class="bx-line" data-part="line" style="border:%spx solid %s"></div>' % (pt_px(b['line_pt']), b['line'])
                  if b['line'] else '<div class="bx-line" data-part="line"></div>')
        if e.get('text'):
            pad = e.get('pad', BOX_PAD)
            inner += ('<div class="bx-body" style="left:%spx;width:%spx;justify-content:%s">'
                      '<span class="t" data-part="text" style="font-size:%spx;color:%s;font-weight:%s;text-align:%s">%s</span></div>'
                      % (px(pad), px(e['w'] - pad - BOX_PAD_RIGHT), VALIGN[e.get('valign', 'middle')], type_size('box', e.get('size')),
                         b['color'], type_weight('box', e.get('bold')), e.get('align', 'left'), text_with_parts(e)))
    elif k == 'bullet':
        ms, dx = e.get('marker_size', BULLET_MARKER), e.get('text_dx', BULLET_TEXT_DX)
        fpx = type_size('bullet', e.get('size'))
        top = round((fpx * TEXT_LH - ms * P.PX) / 2, 2)          # маркер — по центру первой строки
        inner = ('<div class="bl-marker" data-part="marker" style="top:%spx;width:%spx;height:%spx;background:%s"></div>'
                 '<span class="t" data-part="text" style="left:%spx;width:%spx;font-size:%spx;color:%s;font-weight:%s">%s</span>'
                 % (top, px(ms), px(ms), P.color(e.get('marker', K.get('bullet', {}).get('marker', 'primary'))), px(dx),
                    px(e['w'] - dx), fpx, P.color(e.get('color', K.get('bullet', {}).get('color', 'text'))),
                    type_weight('bullet', e.get('bold')), text_with_parts(e)))
    elif k == 'quiz':
        tone = tone_colors(e.get('tone', 'mid'))
        inner = ('<div class="qz-num t" data-part="num" style="left:%spx;top:%spx;width:%spx;height:%spx">%d</div>'
                 '<span class="qz-text t" data-part="text" style="left:%spx;top:%spx;width:%spx;height:%spx;font-size:%spx;font-weight:%s">%s</span>'
                 '<div class="qz-answer" data-part="answer" style="top:%spx;height:%spx;background:%s;%s">'
                 '<span class="t" style="padding-left:%spx;color:%s">%s</span></div>'
                 % (px(QUIZ['num'][0]), px(QUIZ['num'][1]), px(QUIZ['num'][2]), px(QUIZ['num'][2]), e['num'],
                    px(QUIZ['text'][0]), px(QUIZ['text'][1]), px(QUIZ['text'][2]), px(QUIZ['text'][3]),
                    type_size('quiz', e.get('size')), type_weight('quiz'), esc(e['text']),
                    px(e['h'] - QUIZ['answer_h']), px(QUIZ['answer_h']), tone['fill'],
                    ('box-shadow:inset 0 0 0 %spx %s' % (pt_px(tone['line_pt']), tone['line'])) if tone['line'] else '',
                    px(QUIZ['answer_dx']), tone['color'], esc(e['answer'])))
    else:
        raise SystemExit('Неизвестный вид элемента %s' % k)
    cls = 'el k-%s' % k
    if k == 'step' and e.get('accent'):
        cls += ' accent'
    if k == 'plaque' and e.get('tone') == 'warn':
        cls += ' warn'
    layer = ' data-layer="%s"' % e['layer'] if e.get('layer') else ''
    return '<div class="%s" id="%s" data-scene="%s"%s style="%s">%s</div>' % (cls, dom, scene, layer, st, inner), dom


def element_parts(e):
    """Части элемента вида из раскадровки — как их размечает element_html."""
    k = e['kind']
    if k == 'text':
        return {'text'} | text_part_names(e)
    if k == 'step':
        return {'num', 'text'} | ({'tag'} if e.get('tag') else set())
    if k in ('card', 'plaque'):
        return {'text'} | ({'icon'} if e.get('icon') else set())
    if k == 'box':
        return {'fill', 'line'} | ({'text'} | text_part_names(e) if e.get('text') else set())
    if k == 'bullet':
        return {'marker', 'text'} | text_part_names(e)
    if k == 'quiz':
        return {'num', 'text', 'answer'}
    return set()


def tone_colors(name):
    tones = P.kinds().get('tones', {})
    if name not in tones:
        raise SystemExit('Тон «%s» — нет в tokens.json kinds.tones' % name)
    t = tones[name]
    return {'fill': P.color(t.get('fill')), 'line': P.color(t.get('line')), 'line_pt': t.get('line_pt', 0),
            'color': P.color(t.get('color', 'text'))}


def box_style(e):
    """Заливка, обводка и цвет надписи box: tone даёт значения по умолчанию, поля их перекрывают."""
    base = tone_colors(e['tone']) if e.get('tone') else {'fill': None, 'line': None, 'line_pt': 1.0,
                                                         'color': P.color(P.kinds().get('text_color', 'text'))}
    for k in ('fill', 'line', 'color'):
        if k in e:
            base[k] = P.color(e[k])
    if 'line_pt' in e:
        base['line_pt'] = e['line_pt']
    if base['line'] and not base['line_pt']:
        base['line_pt'] = 1.0
    return base


def text_part_names(e):
    tp = e.get('text_parts') or {}
    return {k for k in tp if k != '*'} | set(tp.get('*', []))


def text_with_parts(e):
    """Текст надписи с частями-подстроками (text_parts): каждая — <span data-part class=ip> (inline-block),
    без класса t. Ключ «*» — список частей по порядку, покрывающий весь текст без остатка."""
    text, tp = e['text'], dict(e.get('text_parts') or {})
    esc = html.escape
    order = tp.pop('*', None)
    spans = []
    if order is None:
        for name, sub in tp.items():
            at = text.find(sub)
            if at < 0:
                raise SystemExit('%s: в тексте нет подстроки части «%s»: «%s»' % (e['id'], name, sub))
            spans.append((at, at + len(sub), name, True))
    else:
        pos, gap = 0, None
        for name in order:
            if name in tp:
                at = text.find(tp[name], pos)
                if at < 0:
                    raise SystemExit('%s: «*» — подстрока части «%s» не найдена после позиции %d' % (e['id'], name, pos))
                if gap is not None:
                    if at == pos:
                        raise SystemExit('%s: «*» — часть «%s» пуста' % (e['id'], gap))
                    spans.append((pos, at, gap, False))
                    gap = None
                elif at != pos:
                    raise SystemExit('%s: «*» — текст «%s» не покрыт ни одной частью' % (e['id'], text[pos:at]))
                spans.append((at, at + len(tp[name]), name, True))
                pos = at + len(tp[name])
            else:
                if gap is not None:
                    raise SystemExit('%s: «*» — две части без подстроки подряд: %s, %s' % (e['id'], gap, name))
                gap = name
        if gap is not None:
            if pos >= len(text):
                raise SystemExit('%s: «*» — часть «%s» пуста' % (e['id'], gap))
            spans.append((pos, len(text), gap, False))
        elif pos != len(text):
            raise SystemExit('%s: «*» — хвост «%s» не покрыт ни одной частью' % (e['id'], text[pos:]))
        extra = set(tp) - set(order)
        if extra:
            raise SystemExit('%s: части %s есть в text_parts, но не в «*»' % (e['id'], sorted(extra)))
    spans.sort()
    for a, b in zip(spans, spans[1:]):
        if b[0] < a[1]:
            raise SystemExit('%s: части «%s» и «%s» перекрываются' % (e['id'], a[2], b[2]))
    out, pos = [], 0
    for a, b, name, block in spans:
        out.append(esc(text[pos:a]))
        out.append('<span data-part="%s"%s>%s</span>' % (name, ' class="ip"' if block else '', esc(text[a:b])))
        pos = b
    out.append(esc(text[pos:]))
    return ''.join(out)


# ---------------------------------------------------------------- раскадровки → события
def seam_contract(sbs):
    """Контракт стыка: end_state N = start_state N+1 (в ядре — пустые объекты; плагин может нести свои поля)."""
    errs = []
    for a, b in zip(sbs, sbs[1:]):
        if a['end_state'] != b['start_state']:
            errs.append('стык %s → %s: конец %s ≠ начало %s' % (a['scene'], b['scene'], a['end_state'], b['start_state']))
    return errs


def when(r, b):
    """Абсолютное время момента {reply, at, offset} по реплике r."""
    return r['start'] + b['at'] * (r['end'] - r['start']) + b.get('offset', 0.0)


def resolve(film_sbs, tl, film_plugin_cfg=None):
    """Биты раскадровок → узлы рантайма в абсолютных секундах + события для звука (events).

    Узел — элемент целиком или его часть («id.часть»): events (show/hide), levels, moves, emph и
    initial — видим ли он до первого события (элемент — нет, часть — да, если первым не идёт show)."""
    reps = {r['num']: r for r in tl['replies']}
    scenes = {s['id']: s for s in tl['scenes']}
    sbm = {sb['scene']: sb for sb in film_sbs}
    in_film = set(sbm)
    nodes, order, boxes, layers, ids = {}, [], {}, {}, {}
    beat_events = []           # события звука: каждый бит каждой цели (до раскладки уровней по умолчанию)
    for sb in film_sbs:
        sc = sb['scene']
        ids[sc] = {}
        for e in sb.get('elements', []):
            ids[sc][e['id']] = element_parts(e)
            l, t, w, h = px(e['x']), px(e['y']), px(e['w']), px(e['h'])
            boxes['%s--%s' % (sc, e['id'])] = {'x': l + w / 2, 'y': t + h / 2, 'box': [l, t, w, h]}
        layers[sc] = {e['id']: e.get('layer') for e in sb.get('elements', [])}
        layers[sc].update(sb.get('_markup_layers', {}))
        if sb.get('start_image'):         # картинка-кадр: элемент слоя under во всё полотно
            if START_IMAGE in ids[sc]:
                raise SystemExit('%s: id «%s» занят картинкой-кадром start_image' % (sc, START_IMAGE))
            ids[sc][START_IMAGE] = set()
            layers[sc][START_IMAGE] = 'under'
            boxes['%s--%s' % (sc, START_IMAGE)] = {'x': P.W / 2, 'y': P.H / 2, 'box': [0, 0, P.W, P.H]}
        parts_in_markup = set(re.findall(r'\bdata-part="([a-z0-9-]+)"', sb.get('_markup', '')))
        for mid, (l, t, w, h) in sb.get('_markup_boxes', {}).items():
            if mid in ids[sc]:
                raise SystemExit('%s: id «%s» есть и в elements, и в разметке' % (sc, mid))
            ids[sc][mid] = parts_in_markup
            boxes['%s--%s' % (sc, mid)] = {'x': l + w / 2, 'y': t + h / 2, 'box': [l, t, w, h]}

    def node(sc, tg):
        key = '%s:%s' % (sc, tg)
        if key not in nodes:
            base, _, part = tg.partition('.')
            if base not in ids[sc]:
                raise SystemExit('%s: бит ссылается на неизвестный элемент «%s»' % (sc, base))
            if part and part not in ids[sc][base]:
                raise SystemExit('%s: у «%s» нет части «%s» (есть: %s)' % (sc, base, part, ', '.join(sorted(ids[sc][base])) or 'нет'))
            nodes[key] = {'key': key, 'dom': '%s--%s' % (sc, base), 'part': part or None, 'scene': sc,
                          'events': [], 'levels': [], 'moves': [], 'emph': []}
            if not part and layers.get(sc, {}).get(base):
                nodes[key]['layer'] = layers[sc][base]
            order.append(key)
        return nodes[key]

    for sb in film_sbs:               # каждый элемент — узел, даже без событий
        for i in ids[sb['scene']]:
            node(sb['scene'], i)

    skipped_moves, seq, tail = 0, 0, 0.0
    exit_delay = float(P.req('scene_exit_delay'))
    for si, sb in enumerate(film_sbs):
        sc = sb['scene']
        sl = scenes[sc]
        own = [r['num'] for r in tl['replies'] if r['scene'] == sc]
        first_num = min(own)
        prev = scenes[film_sbs[si - 1]['scene']] if si else None
        prev_last = max(r['num'] for r in tl['replies'] if r['scene'] == prev['id']) if prev else None

        def at(b, what='бит'):
            r = reps.get(b['reply'])
            if r is not None and r['scene'] == sc:
                return when(r, b)
            # бит от конца предыдущей сцены: её последняя реплика, at = 1, offset от A (конца звука N).
            # Сцена собрана без предыдущей (--only): A = первая реплика этой сцены − scene_gap_sec.
            if (prev_last is not None and b['reply'] == prev_last) or (prev is None and b['reply'] < first_num):
                if b['at'] != 1:
                    raise SystemExit('%s: %s от конца предыдущей сцены (реплика %d) — только at = 1, а стоит %s'
                                     % (sc, what, b['reply'], b['at']))
                if prev is not None:
                    return prev['last'] + b.get('offset', 0.0)
                return sl['first'] - float(P.req('scene_gap_sec')) + b.get('offset', 0.0)
            raise SystemExit('%s: %s — реплика %s не принадлежит сцене и не последняя реплика предыдущей сцены'
                             % (sc, what, b['reply']))
        sl['tracker_emph'] = [round(at(w, 'tracker_emph'), 4) for w in sb.get('tracker_emph', [])]
        for w in sl['tracker_emph']:
            tail = max(tail, w + mo('emph_dur'))
        for k in ('title_at', 'chapter_at', 'num_at'):
            if sb.get(k):
                t = at(sb[k], k)
                if t < sl['start'] - 1e-6:
                    raise SystemExit('%s: %s в %.2f с — раньше начала сцены (%.2f с)' % (sc, k, t, sl['start']))
                sl[k] = round(t, 4)
                tail = max(tail, sl[k] + (mo('chapter_dur') if k == 'chapter_at' else mo('title_in')))
        sl['plugins'] = resolve_plugins(sc, sb, at, ids[sc], film_plugin_cfg)
        for b in sb['beats']:
            t0 = at(b)
            tail = max(tail, beat_end(b, t0))
            if b['action'] == 'emph' and b.get('style') == 'breathe':
                tail = max(tail, at(b['until'], 'until') + (len(b['targets']) - 1) * b.get('stagger', 0.0) + mo('breathe')['edge'])
            act = b['action']
            for i, tg in enumerate(b['targets']):
                n = node(sc, tg)
                tt = round(t0 + i * b.get('stagger', 0.0), 4)
                seq += 1
                ev_out = {'kind': act, 't': tt, 'scene': sc, 'ref': tg}
                if act in ('show', 'hide'):
                    ev = {'t': tt, 'type': act, 'anim': b.get('anim', 'rise' if act == 'show' else 'fade')}
                    if b.get('dur') is not None:
                        ev['dur'] = b['dur']
                    n['events'].append(ev)
                    ev_out['anim'] = ev['anim']
                    ev_out['dur'] = ev.get('dur', mo('anim_dur').get(ev['anim'], 0.5))
                    if act == 'show':     # вход ставит уровень сразу: тень, приглушён или чернила
                        n['levels'].append({'t': tt, 'value': b.get('level', 1), 'dur': 0, 'ease': 'none', 'seq': seq})
                        ev_out['level'] = b.get('level', 1)
                elif act == 'emph':
                    style = b.get('style', 'pulse')
                    em = {'t': tt, 'style': style, 'dur': b.get('dur', mo('flash_dur') if style == 'flash' else mo('emph_dur')),
                          'amp': b.get('amp', {'ring': mo('ring_amp'), 'pulse': mo('pulse_amp'), 'breathe': mo('breathe')['scale'],
                                               'spin': 0, 'flip': 0, 'flash': 0}[style])}
                    if style == 'flash':
                        em['color'] = P.color(b['color'], 'emph flash')
                    if style == 'spin':
                        em['dir'] = b.get('dir', 1)
                    if style == 'breathe':
                        em['until'] = round(at(b['until'], 'until') + i * b.get('stagger', 0.0), 4)
                        if em['until'] - tt < mo('breathe')['min']:
                            raise SystemExit('%s: дыхание %s короче %.1f с (until раньше начала?)' % (sc, tg, mo('breathe')['min']))
                        em['dur'] = round(em['until'] + mo('breathe')['edge'] - tt, 4)
                    n['emph'].append(em)
                    ev_out.update(style=style, dur=em['dur'])
                elif act == 'level':
                    n['levels'].append({'t': tt, 'value': b['value'], 'dur': b.get('dur'), 'ease': b.get('ease'), 'seq': seq})
                    ev_out['value'] = b['value']
                else:
                    mv = move_spec(sc, b, in_film, ids)
                    if mv is None:
                        skipped_moves += 1
                        continue
                    mv['t'] = tt
                    n['moves'].append(mv)
                    ev_out.update(dur=mv['dur'], to=mv['dest'].get('dom') or 'box')
                beat_events.append(ev_out)
        # уход содержания сцены: после её последней реплики, кроме последней сцены,
        # если раскадровка не убрала элемент сама (последнее его событие — show)
        last_scene = sb is film_sbs[-1]
        for key in order:
            n = nodes[key]
            if n['scene'] != sc:
                continue
            n['events'].sort(key=lambda e: e['t'])
            start_img = key == '%s:%s' % (sc, START_IMAGE) and not n['events']
            if not last_scene and n['part'] is None and (start_img or n['events'] and n['events'][-1]['type'] == 'show'):
                t_exit = round(sl['last'] + exit_delay, 4)
                n['events'].append({'t': t_exit, 'type': 'hide', 'anim': 'fade'})
                beat_events.append({'kind': 'hide', 't': t_exit, 'scene': sc, 'ref': key.split(':', 1)[1], 'anim': 'fade',
                                    'dur': mo('anim_dur')['fade'], 'auto': True})
    for key in order:
        nodes[key]['moves'].sort(key=lambda e: e['t'])
        nodes[key]['events'].sort(key=lambda e: e['t'])
    satellites(film_sbs, nodes)
    elements = []
    for key in order:
        n = nodes[key]
        n['initial'] = 0 if n['part'] is None or (n['events'] and n['events'][0]['type'] == 'show') else 1
        if key.endswith(':' + START_IMAGE) and not (n['events'] and n['events'][0]['type'] == 'show'):
            n['initial'] = 1          # картинка-кадр видна с первого кадра сцены
        n['levels'].sort(key=lambda e: (e['t'], e['seq']))
        n['levels'] = level_defaults(n['levels'])
        n['emph'].sort(key=lambda e: e['t'])
        elements.append(n)
    if skipped_moves:
        log('  %d move к элементам сцен вне этой сборки (--only) пропущены — элемент стоит на месте' % skipped_moves)
    return elements, boxes, tail, beat_events


def _is_when(v):
    return isinstance(v, dict) and 'reply' in v and 'at' in v and set(v) <= {'reply', 'at', 'offset'}


def resolve_plugins(sc, sb, at, scene_ids, film_cfg=None):
    """Настройки плагинов сцены (storyboard plugins) → данные рантайма: моменты {reply, at, offset} → секунды,
    недостающие поля — из tokens.json motion.<плагин>, поверх — film_cfg фильма (films/<f>.json plugin_config).
    Нет обязательного поля — отказ с его именем (числа движения в коде не живут)."""
    out = {}
    for name, cfg in sorted((sb.get('plugins') or {}).items()):
        if not os.path.exists(os.path.join(PLUGINS_DIR, name + '.js')):
            raise SystemExit('%s: плагина «%s» нет (%s)' % (sc, name, os.path.join(PLUGINS_DIR, name + '.js')))
        base = copy.deepcopy((P.tokens.get('motion') or {}).get(name) or {})
        base.update(copy.deepcopy(cfg))
        base.update(copy.deepcopy((film_cfg or {}).get(name) or {}))
        need = list(PLUGIN_REQUIRED.get(name, ()))
        if name == 'timer':
            need += TIMER_DATE if base.get('mode') == 'date' else TIMER_COUNTDOWN
        miss = [k for k in need if base.get(k) is None]
        if miss:
            raise SystemExit('%s: плагин %s — нет обязательных полей %s (раскадровка plugins.%s или tokens.json motion.%s)'
                             % (sc, name, ', '.join(miss), name, name))

        def conv(v, path):
            if _is_when(v):
                return round(at(v, 'plugins.%s' % path), 4)
            if isinstance(v, dict):
                return {k: conv(x, path + '.' + k) for k, x in v.items()}
            if isinstance(v, list):
                return [conv(x, path) for x in v]
            return v
        r = conv(base, name)
        for key in ('host', 'source'):
            if key in r and r[key] not in scene_ids:
                raise SystemExit('%s: плагин %s — %s «%s»: такого элемента в сцене нет' % (sc, name, key, r[key]))
        if name == 'glitch':
            r.setdefault('source', START_IMAGE)
            if r['source'] not in scene_ids:
                raise SystemExit('%s: помехи берут картинку элемента «%s», а его в сцене нет (start_image?)' % (sc, r['source']))
            if r['to'] <= r['from']:
                raise SystemExit('%s: помехи — to (%.2f с) не позже from (%.2f с)' % (sc, r['to'], r['from']))
        if name == 'timer':
            if r['mode'] not in TIMER_MODES:
                raise SystemExit('%s: плагин timer — mode «%s», есть только %s' % (sc, r['mode'], ', '.join(TIMER_MODES)))
            if r['mode'] != 'date' and (not isinstance(r['labels'], list) or len(r['labels']) != 4):
                raise SystemExit('%s: плагин timer — labels: четыре подписи (дни, часы, минуты, секунды)' % sc)
            for k in ('digits_color', 'labels_color'):
                if k in r:
                    P.color(r[k], 'plugins.timer.%s' % k)
                    r[k] = 'var(--c-%s)' % r[k]
            for k in ('digits_font', 'labels_font'):
                if k in r:
                    r[k] = font_family(r[k], '%s: плагин timer — %s' % (sc, k))
        if name == 'clock':
            r = clock_config(sc, r)
        if name == 'act':
            r = act_config(sc, sb, r, scene_ids)
        out[name] = r
    return out


def clock_config(sc, r):
    """Плагин clock (настенные часы в кадре): формат и вид из tokens.json motion.clock / раскадровки; цвет — роль
    палитры, шрифт — роль шрифта. Значение кладёт clock_values (от project.json wall_clock и смещения куска)."""
    if r['mode'] not in CLOCK_MODES:
        raise SystemExit('%s: плагин clock — mode «%s», есть только %s' % (sc, r['mode'], ', '.join(CLOCK_MODES)))
    if r['format'] not in wallclock.CLOCK_FORMATS:
        raise SystemExit('%s: плагин clock — format «%s», есть только %s' % (sc, r['format'], ', '.join(wallclock.CLOCK_FORMATS)))
    P.color(r['color'], '%s: плагин clock — color' % sc)
    r['color'] = 'var(--c-%s)' % r['color']
    r['font'] = font_family(r['font'], '%s: плагин clock — font' % sc)
    return r


def act_span(m):
    """Длина действия по числам motion.act.<motion> (tokens.json): dur, иначе in + hold + out, иначе spinup, roll, min;
    у действия без длины (шаг спрайта, скорость карандаша) — 0: метка — мгновенная смена."""
    if 'dur' in m:
        return float(m['dur'])
    if 'in' in m:
        return float(m['in']) + float(m.get('hold', 0)) + float(m.get('out', 0))
    for k in ('spinup', 'roll', 'min'):
        if k in m:
            return float(m[k])
    return 0.0


def act_config(sc, sb, r, scene_ids):
    """Плагин act (действия мира): метки {id, t, who, do, motion?, …} → данные рантайма.
    t — уже секунды; motion — имя из tokens.json motion.act (неизвестное — отказ); m — его числа, span — длина.
    who «cam» — камера сцены: do move, to (и from у первой) — положения из разметки (cam-pos), motion обязателен."""
    table = (P.tokens.get('motion') or {}).get('act') or {}
    cues = r.get('cues')
    if not isinstance(cues, list) or not cues:
        raise SystemExit('%s: плагин act — cues: непустой список меток' % sc)
    seen, out = set(), []
    for c in cues:
        miss = [k for k in ACT_CUE_KEYS if c.get(k) in (None, '')]
        if miss:
            raise SystemExit('%s: act — у метки %s нет полей %s' % (sc, c.get('id', '?'), ', '.join(miss)))
        if c['id'] in seen:
            raise SystemExit('%s: act — метка %s повторяется' % (sc, c['id']))
        seen.add(c['id'])
        c = dict(c)
        c.pop('note', None)
        if c.get('motion') is not None:
            if c['motion'] not in table or not isinstance(table[c['motion']], dict):
                raise SystemExit('%s: act — метка %s: motion «%s» нет в tokens.json motion.act (есть: %s)'
                                 % (sc, c['id'], c['motion'], ', '.join(sorted(k for k in table if not k.startswith('_')))))
            c['m'] = copy.deepcopy(table[c['motion']])
        else:
            c['m'] = {}
        c['span'] = round(act_span(c['m']), 4)
        if c['who'] == CAM and (c['do'] != 'move' or not c.get('to') or not c.get('motion')):
            raise SystemExit('%s: act — метка камеры %s: нужны do «move», to и motion (числа — tokens.json motion.act)'
                             % (sc, c['id']))
        out.append(c)
    out.sort(key=lambda c: (c['t'], c['id']))
    res = {'cues': out}
    cam = [c for c in out if c['who'] == CAM]
    if cam or any(c['m'].get('shake_px') for c in out):
        pos = storyboard.markup_cams(sb.get('_markup'))
        names = {c['to'] for c in cam} | {c['from'] for c in cam if c.get('from')}
        lost = sorted(n for n in names if n not in pos)
        if lost:
            raise SystemExit('%s: камера — положений %s нет в разметке сцены (<div class="cam-pos" data-cam="…" style=…>)'
                             % (sc, ', '.join(lost)))
        for n, (x, y, w, h) in pos.items():
            if w <= 0 or h <= 0 or abs((w / h) / (P.W / P.H) - 1) > CAM_ASPECT_TOL:
                raise SystemExit('%s: положение камеры «%s» %s × %s — не в пропорциях кадра %d × %d'
                                 % (sc, n, w, h, P.W, P.H))
        drift = table.get('cam_drift') or {}
        res['camera'] = {'pos': {n: list(v) for n, v in pos.items()}, 'start': cam[0].get('from') if cam else None,
                         'drift': drift}
    return res


def scene_camera(sb):
    """Есть ли у сцены камера (метка cam или толчок кадра): содержание сцены — в трёх обёртках."""
    act = (sb.get('plugins') or {}).get('act') or {}
    table = (P.tokens.get('motion') or {}).get('act') or {}
    return any(c.get('who') == CAM or (table.get(c.get('motion')) or {}).get('shake_px') for c in act.get('cues') or [])


def apply_hide(film, sbs):
    """Ключ фильма "hide": ["id" | "сцена:id", …] (вариант ролика): элемент на странице есть, но не
    виден ни в одном кадре; биты на него снимаются. Неизвестный id — отказ. → {dom-id скрытых}."""
    hide = film.get('hide') or []
    out = set()
    for h in hide:
        sc, _, el = h.rpartition(':')
        hit = []
        for sb in sbs:
            if sc and sb['scene'] != sc:
                continue
            known = {e['id'] for e in sb.get('elements', [])} | set(sb.get('_markup_boxes', {}))
            if el in known:
                hit.append(sb)
        if not hit:
            raise SystemExit('films "hide": элемента «%s» нет ни в одной сцене фильма' % h)
        for sb in hit:
            out.add('%s--%s' % (sb['scene'], el))
            for b in sb['beats']:
                b['targets'] = [t for t in b['targets'] if t.split('.')[0] != el]
            sb['beats'] = [b for b in sb['beats'] if b['targets']]
    return out


def scene_extras(sbs):
    """Проверки полей раскадровки, которых схема не видит: сцена без каркаса не зовёт каркас,
    картинка-кадр есть и размером с полотно."""
    errs = []
    for sb in sbs:
        sc = sb['scene']
        if sb.get('frame') is False:
            bad = [k for k in FRAMELESS_FORBIDS if sb.get(k)]
            if bad:
                errs.append('%s: сцена без каркаса (frame: false), а в раскадровке %s — каркаса нет, бить нечем'
                            % (sc, ', '.join(bad)))
        if sb.get('start_image'):
            p = os.path.join(str(P.root), sb['start_image'])
            if not os.path.exists(p):
                errs.append('%s: start_image — нет файла %s' % (sc, p))
            else:
                wh = png_size(p)
                if wh != (P.W, P.H):
                    errs.append('%s: start_image %s — %s, а полотно %d × %d' % (sc, sb['start_image'],
                                '%d × %d' % wh if wh else 'не PNG', P.W, P.H))
    if errs:
        raise SystemExit('Раскадровки не годятся:\n  ' + '\n  '.join(errs))


def png_size(p):
    with open(p, 'rb') as fh:
        head = fh.read(24)
    if head[:8] != b'\x89PNG\r\n\x1a\n' or head[12:16] != b'IHDR':
        return None
    return int.from_bytes(head[16:20], 'big'), int.from_bytes(head[20:24], 'big')


def satellites(film_sbs, nodes):
    """Спутники: подчёркивание, иконка у строки, точка легенды едут со своей надписью — её move, масштаб,
    наклон, подъём — всё время, пока привязаны. Привязка — узлу follow: [{t, dur, ease, host}]:
      - `with` у элемента / data-with у верхнего узла разметки — с начала сцены;
      - move to_text на надпись своей сцены — с этого move: спутник переезжает, привязка перетекает за время move;
      - move к элементу другой сцены (мост) — отвязывает: спутник улетает сам.
    Хозяин не входит со сдвигом (rise, lift, pop), пока спутник уже виден: спутник ехал бы рывком — ошибка сборки."""
    ids = {}
    for sb in film_sbs:
        sc = sb['scene']
        decl = {e['id']: e['with'] for e in sb.get('elements', []) if e.get('with')}
        decl.update(sb.get('_markup_with', {}))
        for sid, hid in decl.items():
            if hid == sid:
                raise SystemExit('%s: спутник «%s» привязан к самому себе' % (sc, sid))
            if '%s:%s' % (sc, hid) not in nodes:
                raise SystemExit('%s: спутник «%s» — with «%s»: такого элемента в сцене нет' % (sc, sid, hid))
            ids['%s:%s' % (sc, sid)] = [{'t': None, 'dur': 0, 'ease': 'none', 'host': '%s--%s' % (sc, hid)}]
    for key, n in nodes.items():
        if n['part'] is not None:
            continue
        fl = ids.get(key, [])
        for mv in n['moves']:
            dom = mv['dest'].get('dom')
            if not dom:
                continue
            same = dom.startswith(n['scene'] + '--')
            if same and mv['dest']['kind'] == 'text' and dom != n['dom']:
                fl.append({'t': mv['t'], 'dur': mv['dur'], 'ease': mv['ease'], 'host': dom})
            elif not same and fl and fl[-1]['host'] is not None:
                fl.append({'t': mv['t'], 'dur': mv['dur'], 'ease': mv['ease'], 'host': None})
        if fl:
            n['follow'] = fl
    by_dom = {n['dom']: n for n in nodes.values() if n['part'] is None}
    for key, n in nodes.items():
        for i, b in enumerate(n.get('follow', [])):
            if b['host'] is None:
                continue
            h = by_dom[b['host']]
            if h.get('follow'):
                raise SystemExit('%s: спутник «%s» привязан к «%s», а тот сам спутник — цепочек нет' % (n['scene'], n['dom'], h['dom']))
            t0 = b['t'] if b['t'] is not None else -1e9
            t1 = n['follow'][i + 1]['t'] if i + 1 < len(n['follow']) else 1e9
            for ev in h['events']:
                if ev['type'] == 'show' and ev['anim'] in DISPLACING and t0 <= ev['t'] < t1 and _visible(n, ev['t']):
                    raise SystemExit('%s: спутник «%s» уже виден, когда его надпись «%s» входит со сдвигом (%s в %.2f с) — '
                                     'покажи надпись раньше спутника или войди без сдвига (fade, wipe)'
                                     % (n['scene'], n['dom'], h['dom'], ev['anim'], ev['t']))


def _visible(n, t):
    last = None
    for ev in n['events']:
        if ev['t'] < t - 1e-6:
            last = ev
    if last is None:
        return False
    return last['type'] == 'show' or t < last['t'] + mo('anim_dur').get(last['anim'], 0.4)


def beat_end(b, t0):
    """Конец бита: начало + stagger последней цели + длительность действия."""
    act, ad = b['action'], mo('anim_dur')
    if act == 'show':
        d = b['dur'] if b.get('dur') is not None else ad.get(b.get('anim', 'rise'), 0.5)
    elif act == 'hide':
        d = b['dur'] if b.get('dur') is not None else ad.get(b.get('anim', 'fade'), 0.5)
    elif act == 'level':
        d = b.get('dur', mo('ink_dur'))
    elif act == 'emph' and b.get('style') == 'breathe':
        return 0.0
    elif act == 'emph':
        d = b.get('dur', mo('flash_dur') if b.get('style') == 'flash' else mo('emph_dur'))
    elif act == 'move':
        d = b.get('dur', mo('move_dur'))
    else:
        return 0.0
    return t0 + (len(b['targets']) - 1) * b.get('stagger', 0.0) + d


def extend_tail(tl, tail):
    """Хвост фильма — до конца последнего бита + beat_tail, если это позже обычного."""
    need = math.ceil((tail + mo('beat_tail')) * tl['fps'] - 1e-6) / tl['fps']
    if need > tl['duration'] + 1e-9:
        log('  хвост продлён до последнего бита: %.3f → %.3f с' % (tl['duration'], need))
        tl['duration'] = round(need, 4)
        tl['scenes'][-1]['end'] = tl['duration']


def move_spec(sc, b, in_film, ids):
    """Бит move → данные рантайма; None — цель в сцене, которой нет в этой сборке."""
    def ref(s):
        dsc, _, did = s.rpartition(':')
        dsc = dsc or sc
        if dsc not in in_film:
            return None
        if did not in ids[dsc]:
            raise SystemExit('%s: move — у сцены %s нет элемента «%s»' % (sc, dsc, did))
        return '%s--%s' % (dsc, did)
    if 'to' in b:
        bx = b['to']
        dest = {'kind': 'box', 'box': [px(bx['x']), px(bx['y']), px(bx['w']), px(bx['h'])]}
    elif 'to_el' in b:
        dom = ref(b['to_el'])
        if dom is None:
            return None
        dest = {'kind': 'el', 'dom': dom}
    else:
        dom = ref(b['to_text']['el'])
        if dom is None:
            return None
        dest = {'kind': 'text', 'dom': dom, 'sub': b['to_text']['sub'], 'nth': b['to_text'].get('nth', 1)}
    pad = b.get('pad', [0, 0])
    if len(pad) == 2:
        pad = [pad[0], pad[1], pad[0], pad[1]]
    dest['pad'] = [px(v) for v in pad]
    fit = b.get('fit', 'text' if dest['kind'] == 'text' else 'box')
    anchor = b.get('anchor', [0.5, 0.5] if fit == 'none' else [0, 0])
    return {'dest': dest, 'fit': fit, 'anchor': anchor, 'self': b.get('self', anchor), 'tilt': b.get('tilt', 0),
            'dx': px(b.get('dx', 0)), 'dy': px(b.get('dy', 0)), 'size': b.get('size'),
            'color': P.color(b['color'], 'move color') if b.get('color') else None,
            'dur': b.get('dur', mo('move_dur')), 'ease': b.get('ease', mo('move_ease'))}


def frame_of(t, fps):
    """Номер кадра момента t: ОДНО правило округления на сборку, промер и проверку — floor(t·fps + 0,5 + 0,005)."""
    return math.floor(t * fps + 0.5 + ROUND_EPS)


def snap(t, fps):
    return round(frame_of(t, fps) / fps, 6)


def level_defaults(levels):
    """Длительность и кривая уровня, если бит их не задал (tokens.json motion; урок прошлого ролика: «резко появляются и
    резко уходят в тень»). Смена через полосу тени (тень ↔ чернила) — две ступени level_step с level_ease:
    до level_mid с бита и дальше с бита + level_gap; остальное — одна ступень level_step. Если до второй
    ступени у узла следующий уровень — одна ступень ink_dur."""
    out, cur = [], 1
    shade, mid, step, gap, ink = mo('level_shade'), mo('level_mid'), mo('level_step'), mo('level_gap'), mo('ink_dur')
    ez = mo('level_ease')
    for k, lv in enumerate(levels):
        del lv['seq']
        if lv['dur'] is None:
            lo, hi = min(cur, lv['value']), max(cur, lv['value'])
            nxt = levels[k + 1]['t'] if k + 1 < len(levels) else None
            if lo <= shade and hi > mid:
                if nxt is None or nxt > lv['t'] + gap + 1e-6:
                    out.append({'t': lv['t'], 'value': mid, 'dur': step, 'ease': ez})
                    out.append({'t': round(lv['t'] + gap, 4), 'value': lv['value'], 'dur': step, 'ease': ez})
                    cur = lv['value']
                    continue
                lv['dur'] = ink
            else:
                lv['dur'] = step
        lv['ease'] = lv['ease'] or ez
        out.append(lv)
        cur = lv['value']
    return out


def probe_times(elements, tl):
    """Моменты промера событий: кадр до, начало, 20 %, середина, 80 %, конец + 2 кадра; полёт move — каждый кадр."""
    f = 1.0 / tl['fps']
    out = set()
    ad = mo('anim_dur')

    def around(t, d):
        out.update(round(x, 4) for x in (t - f, t, t + f, t + 0.2 * d, t + d / 2, t + 0.8 * d, t + d + 2 * f))
    for n in elements:
        for e in n['events']:
            around(e['t'], e.get('dur', ad.get(e['anim'], 0.5)))
        for e in n['levels']:
            around(e['t'], max(e['dur'], mo('level_step')))
            out.add(round(e['t'] + mo('ink_dur') + 2 * f, 4))
        for e in n['moves'] + n['emph']:
            around(e['t'], e['dur'])
        for e in n['emph']:
            out.add(round(e['t'] + 0.2 * e['dur'], 4))
            if e['style'] == 'flash':
                out.add(round(e['t'] + 0.15 / 1.55 * e['dur'] + 2 * f, 4))
            if e['style'] == 'breathe':
                bp, be = mo('breathe')['period'], mo('breathe')['edge']
                out.update(round(x, 4) for x in (e['t'] + bp / 2, e['until'] + be + 2 * f, e['until'] + be + 2 * f + bp / 4))
        for e in n['moves']:
            k = 0
            while k * f <= e['dur']:
                out.add(round(e['t'] + k * f, 4))
                k += 1
    for s in tl['scenes']:
        if s.get('title_at') is not None:
            around(s['title_at'], mo('title_in'))
        if s.get('num_at') is not None:
            around(s['num_at'] - mo('title_in'), mo('title_in'))
            around(s['num_at'], mo('title_in'))
        if s.get('chapter_at') is not None:
            around(s['chapter_at'], mo('chapter_dur'))
        for t in s.get('tracker_emph') or []:
            around(t, mo('emph_dur'))
    return sorted(t for t in out if 0 <= t < tl['duration'])


def film_events(tl, beat_events, sbs):
    """События фильма для звука (SFX) и проверки: биты целей + стыки + смена главы + вход заголовка."""
    ev = list(beat_events)
    by = {sb['scene']: sb for sb in sbs}
    for a, b in zip(tl['scenes'], tl['scenes'][1:]):
        ev.append({'kind': 'seam', 't': a['end'], 'scene': b['id'], 'ref': '%s>%s' % (a['id'], b['id']),
                   'a': a['last'], 'b': b['first']})
        fa, fb = a.get('chapter'), (b.get('chapter_from') or b.get('chapter'))
        if fb is not None and fb != fa:
            ev.append({'kind': 'chapter', 't': a['end'], 'scene': b['id'], 'ref': fb, 'dur': P.req('frame.seam_dur')})
    for s in tl['scenes']:
        if s.get('chapter_at') is not None:
            ev.append({'kind': 'chapter', 't': s['chapter_at'], 'scene': s['id'], 'ref': s['chapter'], 'dur': mo('chapter_dur')})
        ev.append({'kind': 'title', 't': s['title_at'] if s.get('title_at') is not None else s['start'], 'scene': s['id'],
                   'ref': by[s['id']]['title']})
    ev.sort(key=lambda e: (e['t'], e['kind'], e['ref']))
    return ev


# ---------------------------------------------------------------- страница
def box_css(x, y, w, h):
    return 'left:%spx;top:%spx;width:%spx;height:%spx;' % (px(x), px(y), px(w), px(h))


def tracker_boxes():
    """Плашки трекера глав: рамка трекера project.json frame.tracker, ширина плашки — по длине подписи."""
    tr = P.project.get('frame', {}).get('tracker')
    if not tr or not P.chapters:
        return []
    x, y, w, h = tr['box']
    if 'gap' not in tr:
        raise SystemExit('project.json: нет обязательного поля frame.tracker.gap')
    gap = tr['gap']
    n = len(P.chapters)
    weights = [len(c['label']) + 2 for c in P.chapters]
    free = w - gap * (n - 1)
    out, cx = [], x
    for c, k in zip(P.chapters, weights):
        cw = round(free * k / sum(weights), 4)
        out.append((c, (cx, y, cw, h)))
        cx += cw + gap
    return out


def framed(sb):
    """Сцена с каркасом учебного жанра (по умолчанию да; storyboard "frame": false — без него)."""
    return sb.get('frame', True) is not False


def frame_html(film_sbs, numbers, voice_on):
    """Каркас: общая часть (трекер, линии, футер, голос) — в #frame-global, её непрозрачность ведёт рантайм по
    признаку frame сцен (наплыв на стыке сцены с каркасом и без); заголовок и номер — у сцен с каркасом.
    Все сцены без каркаса — каркаса на странице нет вовсе."""
    fr = P.project.get('frame', {})
    if not any(framed(sb) for sb in film_sbs):
        return ''
    parts = []
    for k, (c, b) in enumerate(tracker_boxes()):
        parts.append('<div class="fr tr-plq" id="tr-%d" data-chapter="%s" style="%s"><span class="tr-lab">%s</span>'
                     '<div class="tr-on" id="tr-on-%d"><span class="tr-lab">%s</span></div></div>'
                     % (k, html.escape(c['id']), box_css(*b), html.escape(c['label']), k, html.escape(c['label'])))
    for i, ln in enumerate(fr.get('lines', [])):
        parts.append('<div class="fr fr-line" id="fr-line-%d" style="%s"></div>' % (i, box_css(*ln)))
    if fr.get('footer') and P.project.get('footer'):
        parts.append('<div class="fr fr-footer" id="fr-footer" style="%s"><span class="t">%s</span></div>'
                     % (box_css(*fr['footer']['box']), html.escape(P.project['footer'])))
    vb = P.project.get('voice_bars') or {}
    if voice_on:
        for v in vb.get('voices', []):
            bars = ''.join('<div class="vo-bar" style="left:%spx;width:%spx"></div>' % (px(k * vb['bar_step']), px(vb['bar_w']))
                           for k in range(vb['bars']))
            parts.append('<div class="fr fr-voice" id="vo-%s" data-voice="%s" style="%s">'
                         '<div class="vo-bars" style="width:%spx;height:%spx">%s</div><span class="t vo-name">%s</span></div>'
                         % (v['id'], v['id'], box_css(v['x'], vb['box_y'], v['w'], vb['box_h']),
                            px(vb['bars'] * vb['bar_step'] - (vb['bar_step'] - vb['bar_w'])), px(vb['max']), bars,
                            html.escape(v['label'])))
    parts = ['<div id="frame-global">'] + parts + ['</div>']
    for sb in film_sbs:
        if not framed(sb):
            continue
        if fr.get('title'):
            parts.append('<div class="fr fr-title" id="title--%s" data-scene="%s" style="%sopacity:0"><span class="t">%s</span></div>'
                         % (sb['scene'], sb['scene'], box_css(*fr['title']['box']), html.escape(sb['title'])))
        if fr.get('number'):
            parts.append('<div class="fr fr-num" id="num--%s" data-scene="%s" style="%sopacity:0"><span class="t">%02d</span></div>'
                         % (sb['scene'], sb['scene'], box_css(*fr['number']['box']), numbers[sb['scene']]))
    return '\n'.join(parts)


def start_image_html(sb, out_dir):
    """Картинка-кадр сцены: элемент «start-image» во всё полотно, слой under; файл — в <out>/assets/img/."""
    src = os.path.join(str(P.root), sb['start_image'])
    name = '%s--%s' % (sb['scene'], os.path.basename(src))
    dst = os.path.join(out_dir, 'assets', 'img', name)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copyfile(src, dst)
    return ('<div class="el start-image" id="%s--%s" data-scene="%s" data-layer="under" style="left:0px;top:0px;width:%dpx;height:%dpx;">'
            '<img src="assets/img/%s" alt="" style="display:block;width:%dpx;height:%dpx"></div>'
            % (sb['scene'], START_IMAGE, sb['scene'], P.W, P.H, html.escape(name), P.W, P.H))


def timer_values(tl, offset):
    """Плагин timer: сколько осталось до события в момент его at — wallclock.timer_at(start, lead_sec, offset + at,
    event) из project.json wall_clock; значение кладётся в данные плагина (left_at), рантайм отсчитывает от него."""
    out = []
    for s in tl['scenes']:
        cfg = (s.get('plugins') or {}).get('timer')
        if not cfg:
            continue
        rec = {'scene': s['id'], 'at': cfg['at'], 'mode': cfg['mode'], 'offset': offset}
        if cfg['mode'] != 'date':
            start, lead, event = P.req('wall_clock.start'), float(P.req('wall_clock.lead_sec')), P.req('wall_clock.event')
            t_timer = offset + cfg['at']
            try:
                cfg['left_at'] = round(wallclock.seconds_left(start, lead, t_timer, event), 4)
                rec['text'] = wallclock.timer_at(start, lead, t_timer, event)
            except ValueError as e:
                raise SystemExit('%s: таймер — %s' % (s['id'], e))
            rec.update(t_timer=round(t_timer, 4), left_at=cfg['left_at'], start=start, lead_sec=lead, event=event)
            log('  таймер %s: в %.2f с склейки (кусок с %.2f с) показывает %s' % (s['id'], t_timer, offset, rec['text']))
        else:
            rec['text'] = cfg['date_text']
        out.append(rec)
    return out


def clock_values(tl, offset):
    """Плагин clock: секунды от полуночи (пояс wall_clock.start) в кадр 0 куска — wallclock.clock_seconds(start,
    lead_sec, offset) из project.json wall_clock; рантайм прибавляет время кадра (секунды вниз). → записи для film.json."""
    out = []
    for s in tl['scenes']:
        cfg = (s.get('plugins') or {}).get('clock')
        if not cfg:
            continue
        start, lead = P.req('wall_clock.start'), float(P.req('wall_clock.lead_sec'))
        try:
            cfg['base'] = round(wallclock.clock_seconds(start, lead, offset), 4)
        except ValueError as e:
            raise SystemExit('%s: часы — %s' % (s['id'], e))
        rec = {'scene': s['id'], 'host': cfg['host'], 'format': cfg['format'], 'base': cfg['base'], 'offset': offset,
               'at_start': wallclock.clock_at(start, lead, offset + s['start'], cfg['format'])}
        log('  часы %s: кусок с %.2f с склейки, в начале сцены %s' % (s['id'], offset, rec['at_start']))
        out.append(rec)
    return out


def act_values(tl):
    """Метки act в film.json (промер и проверка V31–V32): сцена, id, время, who, do, длина."""
    out = []
    for s in tl['scenes']:
        a = (s.get('plugins') or {}).get('act')
        if a:
            out += [{'scene': s['id'], 'id': c['id'], 't': c['t'], 'who': c['who'], 'do': c['do'], 'span': c['span'],
                     'motion': c.get('motion')} for c in a['cues']]
    return out


def plugin_probe_times(meta):
    """Моменты промера плагинов: таймер — кадр до, сам момент, +2 кадра, +1 с, +1,5 с; помехи — края окна;
    метки act — кадр до, начало, кадр после, середина и конец действия + 2 кадра; часы — начало сцены и +1 с."""
    f = 1.0 / meta['fps']
    out = []
    for c in meta.get('acts') or []:
        out += [c['t'] - f, c['t'], c['t'] + f, c['t'] + c['span'] / 2, c['t'] + c['span'] + 2 * f]
    for c in meta.get('clocks') or []:
        s = [x for x in meta['scenes'] if x['id'] == c['scene']][0]
        out += [s['start'], s['start'] + 1.0, s['first']]
    for tm in meta['timers']:
        out += [tm['at'] - f, tm['at'], tm['at'] + 2 * f, tm['at'] + 1.0, tm['at'] + 1.5]
    for _, a, b in meta['glitch_windows']:
        out += [a - f, a, b, b + 2 * f]
    for s in meta['scenes']:
        if s.get('start_image'):
            out += [s['start'], s['start'] + f]
    return [round(t, 4) for t in out if 0 <= t < meta['duration']]


PAGE = '''<!doctype html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=%(w)d, height=%(h)d">
<title>%(title)s</title>
<script src="assets/gsap.min.js"></script>
<style>
%(fonts)s
%(tokens)s
%(css)s
</style>
%(style_css)s</head>
<body>
<div id="root" data-composition-id="main" data-start="0" data-duration="%(duration)s" data-fps="%(fps)d"
     data-width="%(w)d" data-height="%(h)d">
<div id="frame" class="layer">
%(frame)s
</div>
<div id="content" class="layer">
%(content)s
</div>
</div>
%(font_warm)s
<script>window.__FILM__ = %(film)s;</script>
%(plugins)s
<script>
%(stage_js)s
</script>
</body>
</html>
'''


def read(p):
    with open(p, encoding='utf-8') as fh:
        return fh.read()


def page_styles(film, sbs, forced, out_dir):
    """Стили сцен (styles/_core/registry.py: раскадровка → проход → фильм → проект) и всё, что они кладут
    на страницу: {сцена: имя|None}, {имя: загруженный стиль}, <style> и <script> страницы, режим «мир».

    Мир (по умолчанию): style.css + world.css + шрифты стиля; project.json style_brand_lock: true —
    «только фактура»: только style.css, плагин получает world=false."""
    by_scene = styles_registry.scene_styles(P.project, film, sbs, forced)
    world = not P.project.get('style_brand_lock', False)
    used = {}
    for name in sorted({v for v in by_scene.values() if v}):
        used[name] = styles_registry.load(name, P.root)
    css, js, faces = [], [], []
    for name, st in used.items():
        st['families'] = {}
        for role, path in st['fonts'].items():
            fam = 'sty-%s-%s' % (name, role)
            if path == styles_registry.CODE:          # заголовок рисует плагин (StyleCore.codeTitle); шрифт каркаса — фирменный
                faces.append(':root{--%s:var(--font-brand);}' % fam)
                st['families'][role] = styles_registry.CODE
                continue
            if path is None:
                log('  стиль %s: шрифта %s (%s) нет на машине — %s фирменным' % (
                    name, role, ', '.join(st['data']['fonts'][role]['files']), 'заголовок' if role == 'title' else 'надписи декора'))
                faces.append(':root{--%s:var(--font-brand);}' % fam)
                continue
            fn = '%s%s' % (fam, os.path.splitext(path)[1].lower())
            os.makedirs(os.path.join(out_dir, 'assets', 'fonts'), exist_ok=True)
            shutil.copyfile(path, os.path.join(out_dir, 'assets', 'fonts', fn))
            # вес шрифта стиля необязателен (style.json fonts.<роль>.weight?): нет — CSS-умолчание normal, а не число в коде
            faces.append('@font-face{font-family:"%s";font-weight:%s;src:url("assets/fonts/%s");}'
                         % (fam, st['data']['fonts'][role].get('weight', 'normal'), fn))
            faces.append(':root{--%s:"%s", var(--font-brand);}' % (fam, fam))
            st['families'][role] = fam
    if used:
        js.append('<script data-style-core>\n%s\n</script>' % styles_registry.core_js())
        css.append('<style data-style-fonts>\n%s\n</style>\n' % '\n'.join(faces))
    for name, st in used.items():
        if st['css']:
            css.append('<style data-style-css="%s">\n%s\n</style>\n' % (name, st['css']))
        if world and st['world_css']:
            css.append('<style data-style-css="%s" data-world>\n%s\n</style>\n' % (name, st['world_css']))
        if st['plugin']:
            js.append('<script data-style-plugin="%s">\n%s\n</script>' % (name, st['plugin']))
    # шрифт декора и заголовка грузится сразу: скрытые строки вне #root (надписи плагина рисуются в init)
    # кавычки имени — сущностью: прямые кавычки внутри style="…" обрывали атрибут, и шрифт стиля, которым сцена без
    # каркаса ничего не пишет (заголовка нет), оставался unloaded (V22)
    # вес — тот же, что в @font-face выше: нет в style.json — CSS-умолчание normal, а не число в коде
    warm = ''.join('<span style="position:absolute;left:-9999px;font-family:&quot;%s&quot;;font-weight:%s">АаЖж</span>'
                   % (f, st['data']['fonts'][role].get('weight', 'normal'))
                   for st in used.values() for role, f in st['families'].items() if f != styles_registry.CODE)
    return by_scene, used, ''.join(css), '\n'.join(js) + ('\n' if js else ''), world, warm


def build_page(film_name, film, sbs, out_dir, estimate, forced_style=None):
    t_start = time.time()
    names = [sb['scene'] for sb in sbs]
    scene_style, used_styles, style_css, style_js, style_world, font_warm = page_styles(film, sbs, forced_style, out_dir)
    T = timing.Timing(P)
    rows = T.rows(film)
    if rows is None:
        if not estimate and not film.get('estimate_if_no_manifest'):
            raise SystemExit('Нет манифеста звука %s (флаг --estimate — сборка по смете)' % film.get('manifest'))
        raise SystemExit('Нет манифеста звука и строк для сметы: положи replies в фильм или манифест')
    rows = [r for r in rows if r['scene'] in names]
    for v in sorted({r['voice'] for r in rows}):
        P.voice_gain_db(v)        # голоса нет в voices.json — отказ сборки здесь, а не тихий 0 дБ в сведении
    durations, mouths = {}, {}
    for r in rows:
        if r.get('silent'):           # немая строка: длина — ms строки, рот закрыт
            durations[r['num']] = T.estimate_ms(r) / 1000.0
            mouths[r['num']] = '0' * len(lipsync.synthetic(r['num'], durations[r['num']]))
        elif estimate or not r.get('file'):
            durations[r['num']] = T.estimate_ms(r) / 1000.0
            mouths[r['num']] = lipsync.synthetic(r['num'], durations[r['num']])
        else:
            if not os.path.exists(r['file']):
                raise SystemExit('Нет mp3 реплики %d: %s' % (r['num'], r['file']))
            durations[r['num']], mouths[r['num']] = lipsync.analyze(r['file'])
    if estimate:
        log('  --estimate: длительности по смете, звука нет')
    tail_sec = film.get('tail_sec', T.tail)
    tl = T.build(rows, names, durations, tail_sec)
    numbers = {}
    for i, (sb, sc) in enumerate(zip(sbs, tl['scenes'])):
        full_idx = film['scenes'].index(sb['scene'])
        numbers[sb['scene']] = sb.get('number', full_idx + 1)
        sc.update({'number': numbers[sb['scene']], 'title': sb['title'], 'chapter': sb.get('chapter'),
                   'chapter_from': sb.get('chapter_from'), 'title_at': None, 'chapter_at': None, 'num_at': None,
                   'tracker_emph': []})
    for r in tl['replies']:
        r['mouth'] = mouths[r['num']]
    hidden = apply_hide(film, sbs)
    elements, boxes, tail, beat_events = resolve(sbs, tl, film.get('plugin_config'))
    for n in elements:
        if n['dom'] in hidden and n['part'] is None:
            n['hidden'] = True
    offset = float(film.get('timeline_offset_sec', 0.0))      # где кусок стоит в склейке (таймер и часы считают от него)
    timers = timer_values(tl, offset)
    clocks = clock_values(tl, offset)
    acts = act_values(tl)
    extend_tail(tl, tail)
    vb = P.project.get('voice_bars') or {}
    voice_on = bool(film.get('voice_bars', vb.get('on', False))) and bool(vb.get('voices')) and any(framed(sb) for sb in sbs)
    events = film_events(tl, beat_events, sbs)

    if os.path.exists(out_dir):
        for name in ('index.html', 'film.json', 'probe.json'):
            p = os.path.join(out_dir, name)
            if os.path.exists(p):
                os.remove(p)
    os.makedirs(os.path.join(out_dir, 'assets'), exist_ok=True)
    if not os.path.exists(GSAP):
        raise SystemExit('Нет %s: скопируй node_modules (hyperframes, gsap, puppeteer-core) в engine/video — ничего не ставить' % GSAP)
    shutil.copyfile(GSAP, os.path.join(out_dir, 'assets', 'gsap.min.js'))
    content = []
    for sb in sbs:
        st = scene_style[sb['scene']]
        content.append('<section class="scene" id="scene--%s" data-scene="%s"%s>'
                       % (sb['scene'], sb['scene'], ' data-style="%s"' % st if st else ''))
        if sb.get('start_image'):
            content.append(start_image_html(sb, out_dir))
        cam = scene_camera(sb)
        if cam:                 # камера сцены — три вложенные обёртки (закон 4): сюжет, парение, толчок
            content.append('<div class="cam" id="cam--%s" data-scene="%s"><div class="cam-float"><div class="cam-shake">'
                           % (sb['scene'], sb['scene']))
        for e in sb.get('elements', []):
            content.append(element_html(sb['scene'], e)[0])
        if sb.get('_markup'):
            m = storyboard.prefix_ids(sb['_markup'], sb['scene'])
            m = m.replace('class="el"', 'class="el" data-scene="%s"' % sb['scene'])
            content.append(m)
        if cam:
            content.append('</div></div></div>')
        content.append('</section>')
    fr = P.project.get('frame', {})
    sh = P.kinds().get('shade_text')
    data = {
        'fps': tl['fps'], 'duration': tl['duration'], 'px': P.PX,
        'motion': P.motion, 'frame': {'seam_half': P.req('frame.seam_half'), 'seam_dur': P.req('frame.seam_dur')},
        'chapters': P.chapters,
        'scenes': [{k: s.get(k) for k in ('id', 'number', 'chapter', 'chapter_from', 'chapter_at', 'title_at', 'num_at',
                                          'start', 'end', 'first', 'last', 'tracker_emph')}
                   for s in tl['scenes']],
        'styles': {n: {'params': st['data'].get('params', {}), 'motion': st['data']['motion'], 'decor': st['data']['decor'],
                       'world': style_world, 'objects': st['data']['objects'],
                       'fonts': {r: (styles_registry.CODE if st['families'].get(r) == styles_registry.CODE else 'var(--sty-%s-%s)' % (n, r))
                                 for r in st['data']['fonts'] if r != '_comment'}}
                   for n, st in used_styles.items()},
        'replies': [{k: r[k] for k in ('num', 'scene', 'voice', 'emotion', 'start', 'end', 'mouth', 'silent')} for r in tl['replies']],
        'elements': elements, 'boxes': boxes,
        'voice': {'on': voice_on, 'ids': [v['id'] for v in vb.get('voices', [])] if voice_on else [],
                  'min': px(vb['min']), 'max': px(vb['max']),
                  'colors': {v['id']: P.color(v['color'], 'voice_bars color') for v in vb.get('voices', [])},
                  'mute': P.color(vb.get('mute', 'footer')), 'ink': P.color(vb.get('ink', 'text'))},
        'shade': {'fill': P.color(sh['fill']), 'lo': sh['lo'], 'hi': sh['hi']} if sh else None,
    }
    zones = {sb['scene']: [[px(z['x']), px(z['y']), px(z['w']), px(z['h'])] for z in sb.get('decor_zones', [])] for sb in sbs}
    sb_by = {sb['scene']: sb for sb in sbs}
    tl_by = {s['id']: s for s in tl['scenes']}
    for s in data['scenes']:
        s['style'] = scene_style[s['id']]
        s['decor_zones'] = zones[s['id']]       # место сцены под мир стиля (раскадровка decor_zones, дюймы → px)
        s['frame'] = framed(sb_by[s['id']])
        s['plugins'] = tl_by[s['id']].get('plugins') or {}
    data['frame_mixed'] = len({s['frame'] for s in data['scenes']}) > 1
    used_plugins = sorted({n for s in data['scenes'] for n in s['plugins']})
    plugins = ''.join('<script>\n%s\n</script>\n' % read(os.path.join(str(P.root), p)) for p in film.get('plugins', []))
    plugins += ''.join('<script data-plugin="%s">\n%s\n</script>\n' % (n, read(os.path.join(PLUGINS_DIR, n + '.js')))
                       for n in used_plugins)
    page = PAGE % {
        'title': html.escape(film.get('title', film_name)), 'w': P.W, 'h': P.H,
        'fonts': font_css(out_dir), 'tokens': tokens_css(),
        'css': read(os.path.join(HERE, 'lib', 'stage.css')),
        'duration': tl['duration'], 'fps': tl['fps'],
        'frame': frame_html(sbs, numbers, voice_on), 'content': '\n'.join(content),
        'film': json.dumps(data, ensure_ascii=False, separators=(',', ':')),
        'plugins': plugins + style_js, 'style_css': style_css, 'font_warm': font_warm + font_warm_html(),
        'stage_js': read(os.path.join(HERE, 'lib', 'stage.js')),
    }
    with open(os.path.join(out_dir, 'index.html'), 'w', encoding='utf-8') as fh:
        fh.write(page)
    reps_by_scene = {}
    for r in tl['replies']:
        reps_by_scene.setdefault(r['scene'], []).append({'n': r['num'], 'start': r['start'], 'end': r['end'], 'voice': r['voice']})
    scenes_meta = []
    for s, sb in zip(tl['scenes'], sbs):
        d = dict(s, start_state=sb['start_state'], end_state=sb['end_state'], replies=reps_by_scene[s['id']],
                 style=scene_style[s['id']], frame=framed(sb), start_image=sb.get('start_image'))
        scenes_meta.append(d)
    meta = {'film': film_name, 'estimate': estimate, 'fps': tl['fps'], 'duration': tl['duration'],
            'style_pass': forced_style, 'palette_roles': sorted(P.palette),
            # шов со звуком: материал SFX стиля сцены (engine/audio/sfx.py читает scenes[].style и styles[имя].sfx)
            'styles': {n: {'label': st['data']['label'], 'sfx': st['data']['sfx'], 'world': style_world,
                           'fonts': {r: st['families'].get(r) for r in st['fonts']}} for n, st in used_styles.items()},
            'canvas': {'w': P.W, 'h': P.H, 'px_per_in': P.PX},
            'scenes': scenes_meta,
            'replies': [{'n': r['num'], 'num': r['num'], 'scene': r['scene'], 'voice': r['voice'], 'emotion': r['emotion'],
                         'start': r['start'], 'end': r['end'], 'silent': r['silent'],
                         'file': os.path.relpath(r['file'], str(P.root)).replace(os.sep, '/') if r.get('file') else None}
                        for r in tl['replies']],
            'events': events,
            'beat_times': sorted(set([e['t'] for d in elements for e in d['events']])),
            'scenes_dir': os.path.relpath(SCENES_DIR, str(P.root)).replace(os.sep, '/'),
            'moves': [dict(mv, node=n['key'], dom=n['dom'], part=n['part']) for n in elements for mv in n['moves']],
            'sats': [{'node': n['key'], 'dom': n['dom'], 'follow': n['follow']} for n in elements if n.get('follow')],
            'probe_times': probe_times(elements, tl),
            'flashes': [{'node': n['key'], 'dom': n['dom'], 'part': n['part']} for n in elements
                        if any(e['style'] == 'flash' for e in n['emph'])],
            'voice_bars': voice_on, 'tail_sec': tail_sec,
            'timeline_offset_sec': offset, 'timers': timers, 'clocks': clocks, 'acts': acts, 'hidden': sorted(hidden),
            'glitch_windows': [[s['id'], s['plugins']['glitch']['from'], s['plugins']['glitch']['to']]
                               for s in tl['scenes'] if (s.get('plugins') or {}).get('glitch')]}
    meta['probe_times'] = sorted(set(meta['probe_times']) | set(plugin_probe_times(meta)))
    with open(os.path.join(out_dir, 'film.json'), 'w', encoding='utf-8') as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=1)
    log('  страница: %s · %.2f с · %d реплик · %d событий · %.1f с сборки'
        % (os.path.join(out_dir, 'index.html'), tl['duration'], len(tl['replies']), len(events), time.time() - t_start))
    return meta


# ---------------------------------------------------------------- промер, рендер, звук, лист
def hf_env():
    env = dict(os.environ)
    env.update({'HYPERFRAMES_NO_TELEMETRY': '1', 'DO_NOT_TRACK': '1', 'HYPERFRAMES_NO_UPDATE_CHECK': '1',
                'HYPERFRAMES_SKIP_SKILLS': '1', 'HYPERFRAMES_NO_OPTIONAL_INSTALL': '1',
                'HYPERFRAMES_FFMPEG_PATH': lipsync.ffmpeg_exe(), 'HYPERFRAMES_FFPROBE_PATH': ensure_ffprobe_stub()})
    return env


def ensure_ffprobe_stub():
    """Заглушка ffprobe: готовый tools/ffprobe.exe; нет его — собрать csc.exe из .NET Framework (Windows).
    Не Windows: заглушка-exe там не запустится — берётся настоящий ffprobe из PATH (пакет ffmpeg системы)."""
    if os.name != 'nt':
        real = shutil.which('ffprobe')
        if not real:
            raise SystemExit('Нет ffprobe в PATH: поставь ffmpeg пакетом системы (brew install ffmpeg / apt install ffmpeg)')
        return real
    if not os.path.exists(FFPROBE_STUB):
        windir = os.environ.get('WINDIR', '')
        csc = os.path.join(windir, 'Microsoft.NET', 'Framework64', 'v4.0.30319', 'csc.exe')
        if not os.path.exists(csc):
            raise SystemExit('Нет tools/ffprobe.exe и нет csc.exe, чтобы собрать заглушку')
        subprocess.run([csc, '-nologo', '-out:' + FFPROBE_STUB, FFPROBE_STUB_SRC], check=True)
    return FFPROBE_STUB


def probe(out_dir):
    t0 = time.time()
    with chrome_lock.held('build.py probe_dom %s' % out_dir):
        subprocess.run(['node', os.path.join(HERE, 'probe_dom.mjs'), out_dir], check=True)
    log('  промер DOM: %s · %.1f с' % (os.path.join(out_dir, 'probe.json'), time.time() - t0))


def frame_count(duration, fps):
    """Число кадров фильма — как его считает HyperFrames (durationToFrameCount, eps 1e-3)."""
    raw = duration * fps
    near = round(raw)
    return near if abs(raw - near) <= 1e-3 else math.ceil(raw)


def tmp_root(arg):
    """Куда пишутся временные кадры: --tmp, иначе переменная VIDEO_TMP, иначе системный TEMP."""
    base = arg or os.environ.get('VIDEO_TMP') or os.path.join(tempfile.gettempdir(), 'motion-render')
    os.makedirs(base, exist_ok=True)
    return os.path.abspath(base)


def dir_bytes(p):
    total = 0
    try:
        with os.scandir(p) as it:
            for e in it:
                try:
                    if e.is_dir(follow_symlinks=False):
                        total += dir_bytes(e.path)
                    else:
                        total += e.stat(follow_symlinks=False).st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


class DiskPeak(threading.Thread):
    """Промер места: каждые 0,25 с — сколько занимает папка временных кадров; держит максимум."""
    def __init__(self, path):
        super().__init__(daemon=True)
        self.path, self.peak, self.halt = path, 0, threading.Event()

    def run(self):
        while not self.halt.is_set():
            self.peak = max(self.peak, dir_bytes(self.path))
            self.halt.wait(0.25)

    def stop(self):
        self.halt.set()
        self.join()
        self.peak = max(self.peak, dir_bytes(self.path))


class Feeder(threading.Thread):
    """Кадры куска — в stdin кодера по порядку; drop — удалить отработанное вместе с папкой куска."""
    def __init__(self, proc, files, drop, cdir):
        super().__init__(daemon=True)
        self.proc, self.files, self.drop, self.cdir, self.error = proc, files, drop, cdir, None

    def run(self):
        try:
            for p in self.files:
                with open(p, 'rb') as fh:
                    self.proc.stdin.write(fh.read())
                if self.drop:
                    os.remove(p)
            if self.drop:
                shutil.rmtree(self.cdir, ignore_errors=True)
        except OSError as e:
            self.error = SystemExit('Кодер ffmpeg не принял кадры: %s' % e)

    def finish(self):
        self.join()
        if self.error:
            raise self.error


def sheet_picks(meta):
    """Кадры покадрового листа: начало и конец каждой реплики, оба кадра каждого стыка."""
    fps = meta['fps']
    last = frame_count(meta['duration'], fps)
    picks = []
    for r in meta['replies']:
        picks.append((r['start'], '№%d начало · %s' % (r['n'], r['voice'])))
        picks.append((r['end'] - 1.0 / fps, '№%d конец' % r['n']))
    for a, b in zip(meta['scenes'], meta['scenes'][1:]):
        picks.append((a['end'] - 1.0 / fps, 'стык %s → %s: последний кадр' % (a['id'], b['id'])))
        picks.append((a['end'], 'стык %s → %s: первый кадр' % (a['id'], b['id'])))
    picks.sort()
    out = []
    for i, (t, label) in enumerate(picks):
        idx = min(last, max(1, frame_of(t, fps) + 1))     # frame_000001 — кадр t = 0
        out.append((idx, label, '%03d_t%07.3f.png' % (i, idx / fps - 1.0 / fps)))
    return out


def chunk_page(out_dir, frame0, frames, fps):
    """Страница куска: та же index.html, длительность — frames кадров, её кадр j = кадр frame0 + j фильма."""
    page = read(os.path.join(out_dir, 'index.html'))
    page, n = re.subn(r'(<div id="root"[^>]*?data-duration=")[^"]*(")',
                      lambda m: m.group(1) + repr(frames / fps) + m.group(2), page, count=1)
    if n != 1:
        raise SystemExit('В index.html нет data-duration у #root')
    head = '<script>window.__FILM__'
    if page.count(head) != 1:
        raise SystemExit('В index.html нет ровно одного window.__FILM__')
    page = page.replace(head, '<script>window.__CHUNK__ = {"frame0": %d, "frames": %d};</script>\n%s' % (frame0, frames, head))
    with open(os.path.join(out_dir, CHUNK_PAGE), 'w', encoding='utf-8') as fh:
        fh.write(page)
    return CHUNK_PAGE


def start_encoder(out_dir, meta, crf):
    """Один ffmpeg на весь фильм: кадры PNG идут в stdin по мере рендера кусков, звук сводится один раз
    на всю длину — шва между кусками нет ни в картинке, ни в звуке. Громкость голоса — voices.json gain_db."""
    dst = os.path.join(out_dir, 'video.mp4')
    cmd = [lipsync.ffmpeg_exe(), '-v', 'error', '-y', '-f', 'image2pipe', '-c:v', 'png',
           '-framerate', str(meta['fps']), '-i', '-']
    voiced = [r for r in meta['replies'] if r.get('file') and not meta['estimate']]
    for r in voiced:
        cmd += ['-i', os.path.join(str(P.root), r['file'])]
    if voiced:
        chains = ['[%d:a]aresample=44100,aformat=channel_layouts=mono,volume=%.4fdB,adelay=%d:all=1[a%d]'
                  % (i + 1, P.voice_gain_db(r['voice']), round(r['start'] * 1000), i) for i, r in enumerate(voiced)]
        mix = ''.join('[a%d]' % i for i in range(len(voiced)))
        fc = ';'.join(chains) + ';%samix=inputs=%d:normalize=0:dropout_transition=0,apad[aout]' % (mix, len(voiced))
    else:
        cmd += ['-f', 'lavfi', '-i', 'anullsrc=r=44100:cl=mono']
        fc = '[1:a]anull[aout]'
    cmd += ['-filter_complex', fc, '-map', '0:v', '-map', '[aout]', '-t', '%.4f' % meta['duration'],
            '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', str(crf), '-preset', 'medium',
            '-c:a', 'aac', '-b:a', '160k', '-movflags', '+faststart', dst]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE), dst


def render(out_dir, meta, workers, chunk_sec, tmp, crf, keep_frames, png_only=False, max_frames=None):
    """Рендер по кускам времени: кусок → PNG во временной папке → в кодер → удалить. На диске одновременно
    не больше двух кусков, поэтому пик места зависит от длины куска, а не фильма.
    png_only — без mp4: кадры остаются в <out>/frames/frame_%06d.png с отметкой frames/stamp.json (кусок для
    assemble.py); max_frames — только первые N кадров (пробный кусок). Chrome — под замком (engine/chrome_lock.py)."""
    log('  ' + resources.report(tmp))
    log('  ' + resources.report(out_dir))
    fps = meta['fps']
    full = total = frame_count(meta['duration'], fps)
    if max_frames:
        total = min(total, int(max_frames))
    keep_frames = keep_frames or png_only
    per = max(1, int(round(chunk_sec * fps)))
    chunks = [(f0, min(per, total - f0)) for f0 in range(0, total, per)]
    work = os.path.join(tmp, '%s-%d' % (os.path.basename(out_dir), os.getpid()))
    if os.path.exists(work):
        shutil.rmtree(work)
    hf_tmp = os.path.join(work, 'hf-temp')
    os.makedirs(hf_tmp)
    kept = os.path.join(out_dir, 'frames')
    if keep_frames:               # кадры прошлого куска заменяются; рендер в mp4 без --keep-frames их не трогает
        if os.path.exists(kept):
            shutil.rmtree(kept)
        os.makedirs(kept)
    picks = sheet_picks(meta)
    sdir = os.path.join(out_dir, 'sheet')
    if os.path.exists(sdir):
        shutil.rmtree(sdir)
    os.makedirs(sdir)
    env = hf_env()
    env['TEMP'] = env['TMP'] = env['TMPDIR'] = hf_tmp
    logp = os.path.join(out_dir, 'render.log')
    peak = DiskPeak(work)
    peak.start()
    enc, dst = (None, None) if png_only else start_encoder(out_dir, meta, crf)
    feeder = None
    t0 = time.time()
    lock = chrome_lock.held('build.py render %s' % out_dir)
    lock.__enter__()
    try:
        with open(logp, 'w', encoding='utf-8') as fh:
            fh.write('рендер по кускам: %d кадров, %d кусков по %d кадров, временная папка %s\n' % (total, len(chunks), per, work))
            for k, (f0, n) in enumerate(chunks):
                cdir = os.path.join(work, 'chunk-%03d' % k)
                name = chunk_page(out_dir, f0, n, fps)
                fh.write('\n==== кусок %d/%d: кадры %d–%d\n' % (k + 1, len(chunks), f0 + 1, f0 + n))
                fh.flush()
                tk = time.time()
                r = subprocess.run(['node', HF_BIN, 'render', out_dir, '-c', name, '--format', 'png-sequence',
                                    '--workers', str(workers), '-o', cdir], env=env, stdout=fh, stderr=subprocess.STDOUT, cwd=out_dir)
                if r.returncode:
                    raise SystemExit('Рендер HyperFrames упал на куске %d (код %d), журнал: %s' % (k + 1, r.returncode, logp))
                got = sorted(f for f in os.listdir(cdir) if f.endswith('.png'))
                if len(got) != n:
                    raise SystemExit('Кусок %d: ждали %d кадров, HyperFrames дал %d (%s)' % (k + 1, n, len(got), cdir))
                files = []
                for j, f in enumerate(got):
                    src = os.path.join(cdir, f)
                    if keep_frames:
                        moved = os.path.join(kept, 'frame_%06d.png' % (f0 + j + 1))
                        shutil.move(src, moved)
                        src = moved
                    files.append(src)
                for idx, _, sname in picks:
                    if f0 < idx <= f0 + n:
                        shutil.copyfile(files[idx - f0 - 1], os.path.join(sdir, sname))
                if feeder is not None:
                    feeder.finish()
                if png_only:
                    shutil.rmtree(cdir, ignore_errors=True)
                else:
                    feeder = Feeder(enc, files, not keep_frames, cdir)
                    feeder.start()
                log('  кусок %d/%d: %d кадров · %.1f с · временных кадров на диске %.3f ГБ'
                    % (k + 1, len(chunks), n, time.time() - tk, dir_bytes(work) / 1e9))
            if feeder is not None:
                feeder.finish()
        if enc is not None:
            enc.stdin.close()
            if enc.wait():
                raise SystemExit('ffmpeg не собрал mp4 (код %d)' % enc.returncode)
    except BaseException:
        if enc is not None and enc.poll() is None:
            enc.kill()
        raise
    finally:
        lock.__exit__(None, None, None)
        peak.stop()
        p = os.path.join(out_dir, CHUNK_PAGE)
        if os.path.exists(p):
            os.remove(p)
        shutil.rmtree(work, ignore_errors=True)
    if keep_frames:
        frame_stamp.write(out_dir, total, full, fps, (P.W, P.H))
    rsec = time.time() - t0
    log('  рендер%s: %d кадров · %.1f с · пик временных кадров на диске %.3f ГБ'
        % ('' if png_only else ' и mp4', total, rsec, peak.peak / 1e9))
    log('  mp4: %s' % dst if dst else '  кадры PNG: %s (%d шт., отметка %s)' % (kept, total, frame_stamp.NAME))
    with open(logp, 'a', encoding='utf-8') as fh:
        fh.write('\nитог: %d кадров, %d кусков, %.1f с, пик временных файлов на диске %d байт\n' % (total, len(chunks), rsec, peak.peak))
    return picks, rsec, peak.peak


def contact_sheet(out_dir, picks, meta):
    """Сводный sheet.png из кадров, которые рендер положил в sheet/ по ходу."""
    from PIL import Image, ImageDraw, ImageFont
    fps = meta['fps']
    sdir = os.path.join(out_dir, 'sheet')
    tw, th, cols = 480, 270, 4
    rows = (len(picks) + cols - 1) // cols
    sheet = Image.new('RGB', (cols * tw, rows * (th + 30)), 'white')
    fp = os.path.join(HERE, 'assets', 'fonts', 'LiberationSansNarrow-Regular.ttf')
    font = ImageFont.truetype(fp, 20) if os.path.exists(fp) else ImageFont.load_default()
    draw = ImageDraw.Draw(sheet)
    for i, (idx, label, name) in enumerate(picks):
        im = Image.open(os.path.join(sdir, name)).convert('RGB').resize((tw, th))
        x, y = (i % cols) * tw, (i // cols) * (th + 30)
        sheet.paste(im, (x, y + 30))
        draw.text((x + 6, y + 4), 't=%.2f с · %s' % ((idx - 1) / fps, label), fill='#202020', font=font)
        draw.rectangle([x, y + 30, x + tw - 1, y + 30 + th - 1], outline='#B0B0B0')
    sp = os.path.join(out_dir, 'sheet.png')
    sheet.save(sp)
    log('  покадровый лист: %s (%d кадров в %s)' % (sp, len(picks), sdir))


def main():
    global P, SCENES_DIR
    ap = argparse.ArgumentParser(description='Сборка ролика из раскадровок и звука')
    ap.add_argument('film', help='имя файла в films/ без .json')
    ap.add_argument('--only', help='одна сцена фильма или несколько через запятую (sA,sB — шов)')
    ap.add_argument('--estimate', action='store_true', help='без звука: длительности по ms строк / смете')
    ap.add_argument('--page', action='store_true', help='только страница, film.json и промер DOM')
    ap.add_argument('--draft', action='store_true', help='быстрее и грубее: CRF 23')
    ap.add_argument('--keep-frames', action='store_true')
    ap.add_argument('--png', action='store_true',
                    help='кусок для склейки: кадры <out>/<фильм>/frames/frame_%%06d.png и отметка, без mp4 (assemble.py)')
    ap.add_argument('--frames', type=int, help='рендер только первых N кадров (пробный кусок; только с --png)')
    ap.add_argument('--force', action='store_true', help='с --png: рендерить, даже если кадры свежие (отметка совпала)')
    ap.add_argument('--workers', type=int, default=3)
    ap.add_argument('--chunk-sec', type=float, default=CHUNK_SEC, help='длина куска рендера, с')
    ap.add_argument('--tmp', help='папка временных кадров (иначе VIDEO_TMP, иначе системный TEMP)')
    ap.add_argument('--style', help='один проход в этом стиле (имя папки styles/ или none) вместо проходов фильма')
    ap.add_argument('--scenes-dir', help=argparse.SUPPRESS)    # порчи проверки: копия scenes/
    ap.add_argument('--out-dir', help=argparse.SUPPRESS)       # порчи проверки: страница во временную папку
    root, argv = config.project_root.split_argv(sys.argv[1:])     # --project → MOTION_PROJECT → <шаблон>/project
    a = ap.parse_args(argv)
    if a.frames and not a.png:
        raise SystemExit('--frames N — только с --png: mp4 из части кадров был бы короче звука')
    if a.png and a.page:
        raise SystemExit('--png и --page вместе не идут: --page не рендерит, --png рендерит кадры')
    P = config.Project(root)
    lipsync.FPS = P.fps
    lipsync.CACHE = os.path.join(str(P.out), 'cache', 'lipsync')
    fp = os.path.join(str(P.films), a.film + '.json')
    if not os.path.exists(fp):
        raise SystemExit('Нет фильма %s' % fp)
    with open(fp, encoding='utf-8') as fh:
        film = json.load(fh)
    SCENES_DIR = os.path.abspath(a.scenes_dir) if a.scenes_dir else str(P.scenes)
    schema, schema_path = storyboard.write_schema(P)
    names = film['scenes']
    if a.only:
        want = [x.strip() for x in a.only.split(',') if x.strip()]
        bad = [x for x in want if x not in names]
        if bad or not want:
            raise SystemExit('Сцен %s нет в фильме %s (есть: %s)' % (', '.join(bad) or a.only, a.film, ', '.join(names)))
        names = [n for n in names if n in want]
    sbs = []
    for n in names:
        sb, markup = storyboard.load(n, SCENES_DIR, schema)
        if markup:
            sb['_markup'] = markup
            sb['_markup_boxes'] = storyboard.markup_boxes(markup)
            sb['_markup_with'] = storyboard.markup_with(markup)
            sb['_markup_layers'] = storyboard.markup_layers(markup)
        sbs.append(sb)
    errs = seam_contract(sbs)
    if errs:
        raise SystemExit('Контракт стыка нарушен:\n  ' + '\n  '.join(errs))
    scene_extras(sbs)
    out_dir = a.out_dir or os.path.join(str(P.out), a.film + ('--' + ','.join(names) if a.only else '')
                                        + ('--estimate' if a.estimate else ''))
    log('Фильм %s: %s (схема %s)' % (a.film, ' → '.join(names), schema_path))
    # проходы по стилям: films/<f>.json "styles": [...] — фильм собирается в каждом стиле в <out>/<f>/<стиль>/
    passes = film.get('styles') or [None]
    if a.style:
        passes = [a.style]
    for st in passes:
        if st not in (None, styles_registry.NONE):
            styles_registry.folder(st, P.root)      # нет такого стиля — отказ до сборки
    done = []
    for st in passes:
        od = out_dir if st is None else os.path.join(out_dir, st)
        if st is not None:
            log('— проход в стиле %s → %s' % (st, od))
        done.append((st, od, one_pass(a, film, sbs, od, st)))
    if len(passes) > 1 or film.get('styles'):
        if a.page or a.png:
            log('  лист стилей — после полного рендера (без --page и --png)')
        else:
            styles_sheet(out_dir, done)


def one_pass(a, film, sbs, out_dir, style):
    t0 = time.time()
    meta = build_page(a.film, film, copy.deepcopy(sbs), out_dir, a.estimate, style)
    probe(out_dir)
    if meta.get('glitch_windows'):
        probe_frames(out_dir)
    else:
        p = os.path.join(out_dir, 'plugin_probe.json')
        if os.path.exists(p):
            os.remove(p)
    if any(s.get('style') for s in meta['scenes']):
        probe_style(out_dir)
    else:
        p = os.path.join(out_dir, 'style_probe.json')
        if os.path.exists(p):
            os.remove(p)
    if a.page:
        why = frame_stamp.stale(out_dir) if frame_stamp.read(out_dir) else None
        if why:           # кадры куска не удаляются: устарели они или нет, решает отметка (engine/video/stamp.py)
            log('  кадры %s устарели (%s) — перерендерь: build.py %s --png' % (os.path.join(out_dir, 'frames'), '; '.join(why), a.film))
        elif why is not None:
            log('  кадры %s свежие: страница собрана той же, отметка совпала' % os.path.join(out_dir, 'frames'))
        return None
    if a.png and not a.force and not a.frames:
        st = frame_stamp.read(out_dir)
        if st and st.get('frames') == st.get('full') and not frame_stamp.stale(out_dir):
            log('  кадры свежие (%d шт., отметка совпала со страницей) — рендер пропущен; --force — рендерить заново'
                % st['frames'])
            return None
    picks, rsec, peak = render(out_dir, meta, a.workers, a.chunk_sec, tmp_root(a.tmp), 23 if a.draft else 18, a.keep_frames,
                               png_only=a.png, max_frames=a.frames)
    if a.png:
        log('Готово: кусок %s — %s кадров за %.1f с (%.2f с на секунду ролика)'
            % (a.film, a.frames or frame_count(meta['duration'], meta['fps']), time.time() - t0, rsec / meta['duration']))
        return None
    contact_sheet(out_dir, picks, meta)
    total = time.time() - t0
    log('Готово: %.2f с ролика за %.1f с (рендер и mp4 %.1f с, %.2f с на секунду ролика; пик на диске %.3f ГБ)'
        % (meta['duration'], total, rsec, rsec / meta['duration'], peak / 1e9))
    return picks


def probe_frames(out_dir):
    """Промер помех (probe_frames.mjs → plugin_probe.json): каждый кадр окон помех в 1/10 размера (вспышки, V27)
    и кадры окна, снятые дважды в разном порядке после перезагрузки (детерминизм)."""
    t0 = time.time()
    with chrome_lock.held('build.py probe_frames %s' % out_dir):
        subprocess.run(['node', os.path.join(HERE, 'probe_frames.mjs'), out_dir], check=True)
    log('  промер помех: %s · %.1f с' % (os.path.join(out_dir, 'plugin_probe.json'), time.time() - t0))


def probe_style(out_dir):
    """Промер стиля (styles/_core/probe_style.mjs → style_probe.json): кадры для контраста и детерминизма,
    цвета и шрифты со стилем и без, покадровая яркость для вспышек. Читает check.py (V21–V24)."""
    t0 = time.time()
    with chrome_lock.held('build.py probe_style %s' % out_dir):
        subprocess.run(['node', os.path.join(HERE, 'styles', '_core', 'probe_style.mjs'), out_dir], check=True)
    log('  промер стиля: %s · %.1f с' % (os.path.join(out_dir, 'style_probe.json'), time.time() - t0))


def styles_sheet(out_dir, done):
    """styles-sheet.png: строка на проход стиля, в строке — кадры его покадрового листа (sheet/)."""
    from PIL import Image, ImageDraw, ImageFont
    rows = [(st, od, picks) for st, od, picks in done if picks]
    if not rows:
        return
    tw, th, head = 480, 270, 34
    cols = max(len(p) for _, _, p in rows)
    sheet = Image.new('RGB', (cols * tw, len(rows) * (th + head)), 'white')
    fp = os.path.join(HERE, 'assets', 'fonts', 'LiberationSansNarrow-Bold.ttf')
    font = ImageFont.truetype(fp, 24) if os.path.exists(fp) else ImageFont.load_default()
    draw = ImageDraw.Draw(sheet)
    for r, (st, od, picks) in enumerate(rows):
        y = r * (th + head)
        label = st or 'без стиля'
        if st and st != styles_registry.NONE:
            label = '%s · %s' % (st, styles_registry.load(st, P.root)['data']['label'])
        draw.text((8, y + 4), label, fill='#202020', font=font)
        for c, (idx, lab, name) in enumerate(picks):
            im = Image.open(os.path.join(od, 'sheet', name)).convert('RGB').resize((tw, th))
            sheet.paste(im, (c * tw, y + head))
            draw.rectangle([c * tw, y + head, c * tw + tw - 1, y + head + th - 1], outline='#B0B0B0')
    sp = os.path.join(out_dir, 'styles-sheet.png')
    sheet.save(sp)
    log('лист стилей: %s (%d стилей × %d кадров)' % (sp, len(rows), cols))


if __name__ == '__main__':
    main()
