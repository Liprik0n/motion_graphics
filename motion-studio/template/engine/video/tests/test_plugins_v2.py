# -*- coding: utf-8 -*-
"""Буквы «пером» (плагин pen), набор букв (libs: card-kit) и Lottie (плагин lottie) — на собранной странице.

    python engine/video/tests/test_plugins_v2.py     (≈ 7 мин: сборки страниц фильма pen и пробного фильма Lottie,
                                                     полосы кадров, два рендера кадрами, под замком Chrome)

Ожидания — не из кода плагинов:
  перо — закон записи из tokens.json motion.act.pen_stem (_pen_comment) и геометрия строк из раскадровки pen-probe:
    строка i начинается в t0 + i · line_lag · L, L = (until − t0) / (1 + (N − 1) · line_lag); доля строки под пером в
    доле p её длины — ease((p − lead_in) / (contour_until − lead_in)); ширина строки — по файлу шрифта (PIL). На кадрах
    полосы правее пера с запасом тёмных пикселей нет, к концу строка написана; пиксели цвета ведущей линии прибывают
    и убывают не за один кадр;
  набор букв — частицы фразы начинают в рамке банки (objects метки live, доли кадра), фраза дословно из раскадровки;
    читаемость по пикселям (V37) видит фразу: её строка объявлена областью текста там, где её ставит раскадровка
    (ширина — по файлу шрифта, PIL), и мерится только после сборки (until метки gather); «золото на закате» на самой
    странице — золото (255, 214, 120) вместо красок фразы, шафран (244, 178, 96) вместо бумаги, контраст по формуле
    WCAG 1,33 — красит V37 строкой этой фразы;
  данные фильма на странице — чужой файл анимации, у которого имя слоя закрывает <script> и открывает свой, не даёт
    странице второго исполняемого скрипта (скрипты считает разборщик HTML стандартной библиотеки);
  Lottie — кадр анимации в момент t равен (t − at) · speed · fr файла; проигрыватель настоящий (пакет lottie-web из
    набора Node движка); где стоит квадрат в кадрах 0, 15, 30, 45 — разобрано вручную по ключам файла
    libs/pulse.lottie.json (SQUARE_X).
Работает на копии project/ во временной папке; поставка не трогается. Кадры — только через engine/tools/strip.py.
"""
NEEDS_CHROME = True      # страницы собираются и снимаются безголовым браузером: общий прогон берёт на него замок

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path

VIDEO = Path(__file__).resolve().parents[1]
ENGINE = VIDEO.parent
TEMPLATE = ENGINE.parent
sys.path.insert(0, str(ENGINE / 'tests'))
sys.path.insert(0, str(ENGINE / 'tools'))
sys.path.insert(0, str(ENGINE))
from _util import PY, check, run_module   # noqa: E402
import strip                               # noqa: E402  единственный способ добыть кадр
import chrome_lock                         # noqa: E402

FILM = 'pen'
SCENE = 'pen-probe'
FPS = 30
SCALE = 0.5                # кадры полосы — половина полотна
PAPER = (255, 255, 255)    # tokens.json palette.paper
DARK = 110                 # пиксель «тёмный» (чернила фразы: palette.ink #1A1C1E): все каналы ниже
FONT = TEMPLATE / 'engine' / 'video' / 'assets' / 'fonts' / 'LiberationSansNarrow-Bold.ttf'
_TMP = {}


def _env(extra=None):
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    env.pop('MOTION_PROJECT', None)
    env.update(extra or {})
    return env


def run(cmd, extra=None):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, encoding='utf-8', errors='replace', env=_env(extra))
    return r.returncode, r.stdout + r.stderr


def project(tag):
    tmp = tempfile.mkdtemp(prefix='plugins_v2_%s_' % tag)
    proj = Path(tmp) / 'project'
    shutil.copytree(TEMPLATE / 'project', proj, ignore=shutil.ignore_patterns('out', '.env', '__pycache__', 'music'))
    return tmp, proj


def build(proj, film=FILM, extra=None):
    return run([PY, VIDEO / 'build.py', film, '--page', '--project', proj], extra)


def checks(proj, film=FILM, extra=None):
    """Строки проверки страницы: {'V38': 'OK   V38 …' | 'SKIP …' | 'FAIL …; FAIL …'}."""
    code, text = run([PY, VIDEO / 'check.py', film, '--page', '--project', proj], extra)
    out = {}
    for ln in text.splitlines():
        m = re.match(r'(OK|SKIP|FAIL)\s+(V\d+)\b', ln)
        if m:
            out[m.group(2)] = (out[m.group(2)] + '; ' + ln) if m.group(2) in out else ln
    return out, text


def pen_page():
    """Собранная один раз страница фильма pen во временной копии проекта: (проект, папка страницы)."""
    if 'pen' not in _TMP:
        tmp, proj = project('pen')
        code, text = build(proj)
        check(code == 0, 'страница фильма pen не собралась: %s' % text[-900:])
        _TMP['pen'] = (tmp, proj, proj / 'out' / FILM)
    return _TMP['pen'][1], _TMP['pen'][2]


def load(p):
    with open(p, encoding='utf-8-sig') as fh:
        return json.load(fh)


def cue_of(proj, cue_id, scene=SCENE):
    sb = load(proj / 'scenes' / scene / 'storyboard.json')
    return next(c for c in sb['plugins']['act']['cues'] if c['id'] == cue_id)


def moment(film, m):
    r = next(x for x in film['replies'] if x['num'] == m['reply'])
    return r['start'] + m['at'] * (r['end'] - r['start']) + m.get('offset', 0.0)


def power_ease(name):
    """Кривые GSAP power<N>.in / out / inOut и none — по их определению (степень N + 1)."""
    if name == 'none':
        return lambda x: x
    m = re.match(r'power(\d)\.(in|out|inOut)$', name)
    n, kind = int(m.group(1)) + 1, m.group(2)
    if kind == 'in':
        return lambda x: x ** n
    if kind == 'out':
        return lambda x: 1 - (1 - x) ** n
    return lambda x: (2 ** (n - 1)) * x ** n if x < 0.5 else 1 - (-2 * x + 2) ** n / 2


def pen_law(proj, film, cue):
    """Закон записи метки по tokens.json и раскадровке → (числа движения, [начало строки, с], длина строки, с)."""
    m = load(proj / 'tokens.json')['motion']['act'][cue['motion']]
    t0, until = moment(film, cue['t']), moment(film, cue['until'])
    n = len(cue['lines'])
    span = (until - t0) / (1 + (n - 1) * m['line_lag'])
    return m, [t0 + i * m['line_lag'] * span for i in range(n)], span


def tip_share(m, p):
    """Доля строки под пером в доле p длины её записи; None — перо ещё не дошло до строки."""
    if p <= m['lead_in']:
        return None
    return power_ease(m['ease'])(min(1.0, (p - m['lead_in']) / (m['contour_until'] - m['lead_in'])))


def host_box(proj, who, scene=SCENE):
    txt = (proj / 'scenes' / scene / 'markup.html').read_text(encoding='utf-8')
    m = re.search(r'id="%s"[^>]*style="left:(\d+)px; top:(\d+)px; width:(\d+)px; height:(\d+)px;' % who, txt)
    return [int(v) for v in m.groups()]


def line_span_px(host, ln):
    """Левый край и ширина строки в px кадра — по файлу шрифта (PIL), не по странице."""
    from PIL import ImageFont
    w = ImageFont.truetype(str(FONT), int(ln['size'])).getlength(ln['text'])
    x = host[0] + ln['x']
    left = x if ln['align'] == 'left' else x - w if ln['align'] == 'right' else x - w / 2
    return left, w


def _pixels(im):
    b = im.tobytes()
    return zip(b[0::3], b[1::3], b[2::3])


def dark_count(im, box):
    """Сколько тёмных пикселей (чернила) в рамке box — px кадра полного размера, кадр im — в масштабе SCALE."""
    x0, y0, x1, y1 = [int(round(v * SCALE)) for v in box]
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(im.width, x1), min(im.height, y1)
    if x1 <= x0 or y1 <= y0:
        return 0
    return sum(1 for r, g, b in _pixels(im.crop((x0, y0, x1, y1))) if r < DARK and g < DARK and b < DARK)


def near_count(im, box, rgb, tol=40):
    x0, y0, x1, y1 = [int(round(v * SCALE)) for v in box]
    return sum(1 for r, g, b in _pixels(im.crop((max(0, x0), max(0, y0), min(im.width, x1), min(im.height, y1))))
               if abs(r - rgb[0]) < tol and abs(g - rgb[1]) < tol and abs(b - rgb[2]) < tol)


def strip_frames(proj, page, t0, t1):
    """[(t, кадр PIL)] полосы отрезка [t0, t1) с частотой фильма; t0 — на границе кадра."""
    from PIL import Image
    t0 = round(t0 * FPS) / FPS
    paths = strip.frames(str(proj), FILM, t0, t1, FPS, SCALE, page=str(page))
    return [(t0 + k / FPS, Image.open(p).convert('RGB')) for k, p in enumerate(paths)]


# ---------------------------------------------------------------- перо
def test_pen_letters_hidden_until_pen_reaches_them():
    """Полоса кадров записи write-stem: правее пера (с запасом) тёмных пикселей нет ни в одном кадре, пока перо не дошло
    до строки — строка пуста; после записи строка написана."""
    proj, page = pen_page()
    film = load(page / 'film.json')
    cue = cue_of(proj, 'write-stem')
    m, starts, span = pen_law(proj, film, cue)
    host = host_box(proj, cue['who'])
    frames = strip_frames(proj, page, starts[0] - 0.2, starts[-1] + span + 0.4)
    seen_partial = 0
    for i, ln in enumerate(cue['lines']):
        left, width = line_span_px(host, ln)
        y0, y1 = host[1] + ln['y'] - ln['size'] * 0.95, host[1] + ln['y'] + ln['size'] * 0.3
        guard = 0.04 * width + 14          # разница метрик PIL и Chrome и сглаживание кромки
        for t, im in frames:
            p = (t - starts[i]) / span
            e = tip_share(m, min(1.0, max(0.0, p)))
            tip = left if e is None else left + width * e
            ahead = dark_count(im, (tip + guard, y0, left + width + 30, y1))
            check(ahead <= 4, 'строка %d «%s» видна до пера: t=%.3f с (доля записи %.2f), перо на x=%.0f, правее него %d тёмных '
                              'пикселей' % (i + 1, ln['text'], t, p, tip, ahead))
            if e is not None and 0.3 < e < 0.7:
                behind = dark_count(im, (left - 10, y0, tip - guard, y1))
                check(behind > 40, 'строка %d: перо прошло %.0f %% строки (t=%.3f с), а за ним пусто (%d тёмных пикселей) — '
                                   'буквы не пишутся под пером' % (i + 1, e * 100, t, behind))
                seen_partial += 1
        t_end, im_end = frames[-1]
        whole = dark_count(im_end, (left - 10, y0, left + width + 30, y1))
        check(whole > 400, 'строка %d «%s» не написана к концу записи (t=%.3f с): тёмных пикселей %d' % (i + 1, ln['text'], t_end, whole))
    check(seen_partial >= 4, 'в полосе нет кадров с пером посреди строки (%d) — тест ничего не доказал' % seen_partial)


def test_pen_lead_line_grows_and_does_not_vanish_in_one_frame():
    """Пиксели цвета ведущей линии (write-wire: palette.primary) по кадрам: до начала записи их нет; линия растёт не
    меньше трёх кадров; гаснет тоже не за кадр — последний кадр с линией несёт не больше половины её наибольшего."""
    proj, page = pen_page()
    film = load(page / 'film.json')
    cue = cue_of(proj, 'write-wire')
    m, starts, span = pen_law(proj, film, cue)
    host = host_box(proj, cue['who'])
    primary = tuple(int(load(proj / 'tokens.json')['palette']['primary'][k:k + 2], 16) for k in (1, 3, 5))
    box = (host[0], host[1], host[0] + host[2], host[1] + host[3])
    series = [(t, near_count(im, box, primary)) for t, im in strip_frames(proj, page, starts[0] - 0.2, starts[0] + span + 0.3)]
    before = [n for t, n in series if t < starts[0] - 1e-6]
    check(before and max(before) == 0, 'до начала записи в хозяине уже есть пиксели ведущей линии: %s' % before)
    top = max(n for _, n in series)
    check(top > 150, 'ведущей линии в кадрах нет (наибольшее число её пикселей %d)' % top)
    on = [k for k, (_, n) in enumerate(series) if n > 0]
    first, last = on[0], on[-1]
    check(all(series[k][1] > 0 for k in range(first, last + 1)), 'ведущая линия мигает: %s' % [n for _, n in series])
    check(series[first][1] <= 0.5 * top, 'ведущая линия появилась сразу: в первом кадре с линией (t=%.3f с) %d пикселей из %d'
          % (series[first][0], series[first][1], top))
    grow = [n for _, n in series[first:first + 4]]
    check(len(grow) == 4 and all(b > a for a, b in zip(grow, grow[1:])), 'ведущая линия не растёт от кадра к кадру: %s' % grow)
    check(last + 1 < len(series), 'полоса кончилась раньше, чем линия погасла — тест ничего не доказал')
    check(series[last][1] <= 0.5 * top, 'ведущая линия погасла одним кадром: в последнем кадре с линией (t=%.3f с) %d пикселей из %d'
          % (series[last][0], series[last][1], top))
    fade = [n for _, n in series[last - 3:last + 1]]
    check(all(b < a for a, b in zip(fade, fade[1:])), 'ведущая линия не убывает перед тем, как погаснуть: %s' % fade)


def test_pen_numbers_come_from_tokens():
    """Числа пера — tokens.json motion.act: без ключа сборка отказывает с его именем (запасного числа в коде нет);
    другое contour_until — перо в тот же момент в другом месте строки (промер страницы)."""
    tmp, proj = project('pen_tokens')
    try:
        tk = load(proj / 'tokens.json')
        gone = dict(tk['motion']['act']['pen_stem'])
        del gone['lead_out']
        tk['motion']['act']['pen_stem'] = gone
        (proj / 'tokens.json').write_text(json.dumps(tk, ensure_ascii=False), encoding='utf-8')
        code, text = build(proj)
        check(code != 0 and 'lead_out' in text and 'pen_stem' in text,
              'нет числа pen_stem.lead_out: ждали отказ сборки с именем ключа, получили код %d: %s' % (code, text[-400:]))
        tk['motion']['act']['pen_stem'] = dict(gone, lead_out=0.2, contour_until=0.5)
        (proj / 'tokens.json').write_text(json.dumps(tk, ensure_ascii=False), encoding='utf-8')
        code, text = build(proj)
        check(code == 0, 'страница с contour_until 0,5 не собралась: %s' % text[-600:])
        film = load(proj / 'out' / FILM / 'film.json')
        cue = cue_of(proj, 'write-stem')
        m, starts, span = pen_law(proj, film, cue)
        check(m['contour_until'] == 0.5, 'тест читает не те tokens')
        old = dict(m, contour_until=0.75)
        probe = load(proj / 'out' / FILM / 'probe.json')
        seen = 0
        for s in probe['samples']:
            p = (s['t'] - starts[0]) / span
            if not (m['lead_in'] + 0.08 < p < 0.48):
                continue
            item = next((it for pl in s['plugins'] if pl and pl.get('plugin') == 'pen' for it in pl['items'] if it['cue'] == 'write-stem'), None)
            check(item is not None, 'в промере страницы нет записи плагина pen о метке write-stem (t=%.2f с)' % s['t'])
            ln = item['lines'][0]
            got = (ln['tip'] - ln['rect'][0]) / ln['rect'][2]
            want, was = tip_share(m, p), tip_share(old, p)
            check(abs(got - want) < 0.02, 't=%.3f с: перо на %.3f строки, по tokens (contour_until 0,5) ждали %.3f' % (s['t'], got, want))
            check(abs(got - was) > 0.02, 't=%.3f с: перо стоит как при contour_until 0,75 (%.3f) — число из tokens не дошло' % (s['t'], was))
            seen += 1
        check(seen >= 3, 'кадров промера посреди записи %d — тест ничего не доказал' % seen)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_v38_green_on_page_and_red_on_pale_line_before_pen():
    """V38 молчит на исправной странице и краснеет на порче самой страницы: заливка фразы включена бледной до пера
    (прежний дефект набора букв) — правка одной строки плагина в собранной странице и новый промер."""
    tmp, proj = project('pen_red')
    try:
        code, text = build(proj)
        check(code == 0, 'страница фильма pen не собралась: %s' % text[-900:])
        res, text = checks(proj)
        check(res.get('V38', '').startswith('OK'), 'V38 на исправной странице: ждали OK, получили «%s»\n%s' % (res.get('V38'), text[-1200:]))
        index = proj / 'out' / FILM / 'index.html'
        page = index.read_text(encoding='utf-8')
        healthy = 'var fillTo = L.rx + L.rw * st.f, fillOn = st.f > 0, fillAlpha = 1;'
        check(page.count(healthy) == 1, 'в странице нет строки плагина pen, которую портит тест (заливка до fillTo)')
        index.write_text(page.replace(healthy, 'var fillTo = L.rx + L.rw, fillOn = true, fillAlpha = 0.3;'), encoding='utf-8')
        with chrome_lock.held('test_plugins_v2: промер испорченной страницы'):
            r = subprocess.run(['node', str(VIDEO / 'probe_dom.mjs'), str(proj / 'out' / FILM)], capture_output=True, text=True,
                               encoding='utf-8', errors='replace')
        check(r.returncode == 0, 'промер испорченной страницы упал: %s' % (r.stdout + r.stderr)[-500:])
        res, text = checks(proj)
        check(res.get('V38', '').startswith('FAIL') and 'видна до пера' in res['V38'],
              'бледная строка до пера: ждали FAIL V38 «видна до пера», получили «%s»' % res.get('V38'))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- набор букв
def test_kit_connects_through_libs_and_its_checks_pass():
    """Набор букв подключён ключом фильма libs: [\"card-kit\"] из engine/video/libs; его проверки на фильме pen зелёные,
    частицы фразы начинают в рамке банки, текст фразы — из раскадровки."""
    proj, page = pen_page()
    html_text = (page / 'index.html').read_text(encoding='utf-8')
    check('data-lib="card-kit"' in html_text and html_text.index('data-lib="card-kit"') < html_text.index('id="scene--pen-probe"'),
          'набора букв нет на странице до разметки сцен (ключ фильма libs: ["card-kit"])')
    check('data-lib="stage-fonts"' in html_text and html_text.index('data-lib="stage-fonts"') < html_text.index('data-lib="card-kit"'),
          'правило «шрифт загружен» (lib/fonts.js) стоит на странице не перед набором букв: набор спрашивает его при разборе разметки')
    cue = cue_of(proj, 'gather')
    jar = next(o for c in load(proj / 'scenes' / SCENE / 'storyboard.json')['plugins']['act']['cues'] for o in c.get('objects') or [])
    bx = [jar['box'][0] * 1920, jar['box'][1] * 1080, jar['box'][2] * 1920, jar['box'][3] * 1080]
    probe = load(page / 'probe.json')
    item = next((it for s in probe['samples'] for pl in s['plugins'] if pl and pl.get('plugin') == 'cardkit'
                 for it in pl['items'] if it.get('kind') == 'phrase'), None)
    check(item is not None, 'в промере страницы нет фразы набора букв (плагин cardkit)')
    check(item['text'] == [ln['text'] for ln in cue['lines']], 'фраза набора на странице %s ≠ раскадровке' % item['text'])
    out = [p for p in item['origins'] if not (bx[0] - 2 <= p[0] <= bx[0] + bx[2] + 2 and bx[1] - 2 <= p[1] <= bx[1] + bx[3] + 2)]
    check(item['origins'] and not out, 'частицы фразы начинают вне банки: %d из %d' % (len(out), len(item['origins'])))
    res, text = checks(proj)
    for code in ('V38', 'V39', 'V40', 'V41', 'V43'):
        check(res.get(code, '').startswith('OK'), '%s на фильме pen: ждали OK, получили «%s»\n%s' % (code, res.get(code), text[-1500:]))
    bad = [ln for ln in text.splitlines() if ln.startswith('FAIL')]
    check(not bad, 'страница фильма pen не прошла проверку: %s' % bad[:6])


GOLD, SAFFRON = '#FFD678', '#F4B260'      # золото (255, 214, 120) на шафране (244, 178, 96): контраст по WCAG 1,33


def test_v37_measures_kit_phrase_and_gold_on_sunset_is_red_on_page():
    """Фраза набора букв — текст на canvas: проверке читаемости её области отдаёт сам набор (L.textRects → плагин слоя →
    window.__textRects). На исправной странице V37 мерит строку фразы после сборки и молчит; на странице, где краски
    фразы — золото, а бумага — шафран заката, краснеет строкой этой фразы."""
    from PIL import ImageFont
    sys.path.insert(0, str(VIDEO))
    import check as C
    tmp, proj = project('kit_gold')
    try:
        code, text = build(proj)
        check(code == 0, 'страница фильма pen не собралась: %s' % text[-900:])
        out = proj / 'out' / FILM
        film, cue = load(out / 'film.json'), cue_of(proj, 'gather')
        ln = cue['lines'][0]
        t0, t_done = moment(film, cue['t']), moment(film, cue['until'])
        ey = C.eye(C.make_ctx(str(proj), str(out), page_only=True))
        seen = [(fr['t'], x) for fr in ey['frames'] for x in fr['text'] if x.get('src') == 'canvas' and x.get('text') == ln['text']]
        check(seen, 'в кадрах полосы нет области текста фразы набора «%s» — V37 её не видит (объявлены: %s)'
              % (ln['text'], sorted({x.get('text') for fr in ey['frames'] for x in fr['text'] if x.get('src') == 'canvas'})))
        full = [t for t, x in seen if x.get('opacity', 1) >= 0.99]
        check(full, 'строка фразы ни в одном кадре не объявлена видимой на 1,0 — V37 её не мерит')
        check(min(full) >= t_done - 1e-6, 'строка фразы мерится в t=%.2f с, а собрана она только к %.2f с' % (min(full), t_done))
        check(any(t >= t_done for t in full) and all(x.get('opacity', 1) < 0.99 for t, x in seen if t < t0),
              'до начала сборки (%.2f с) строка фразы объявлена видимой или после сборки (%.2f с) — нет' % (t0, t_done))
        # где стоит строка: середина — x раскадровки, низ букв — у базовой линии; ширина — по файлу шрифта
        size = ln['size_frac_w'] * 1920
        width = ImageFont.truetype(str(FONT), int(round(size))).getlength(ln['text'])
        rect = next(x['rect'] for t, x in seen if t >= t_done)
        cx, base = ln['x'] * 1920, ln['y'] * 1080
        check(abs(rect[0] + rect[2] / 2 - cx) < 0.03 * 1920 and abs(rect[2] - width) < 0.08 * width + 24,
              'рамка строки фразы %s: ждали середину x≈%.0f и ширину ≈%.0f px (шрифт %s px)' % (rect, cx, width, round(size)))
        check(base - 1.2 * size < rect[1] < base - 0.4 * size and base - 0.05 * size < rect[1] + rect[3] < base + 0.5 * size,
              'рамка строки фразы %s не у базовой линии y≈%.0f (кегль %.0f px)' % (rect, base, size))
        res, text = checks(proj)
        check(res.get('V37', '').startswith('OK'), 'V37 на исправной странице фильма pen: ждали OK, получили «%s»' % res.get('V37'))
        # «золото на закате» на самой странице: краски фразы — золото, бумага — шафран
        pal = load(proj / 'tokens.json')['palette']
        index = out / 'index.html'
        page = index.read_text(encoding='utf-8')
        for role, new in (('primary', GOLD), ('accent', GOLD), ('paper', SAFFRON)):
            old = '--c-%s:%s;' % (role, pal[role])
            check(page.count(old) == 1, 'в странице нет роли палитры %s одной строкой «%s»' % (role, old))
            page = page.replace(old, '--c-%s:%s;' % (role, new))
        index.write_text(page, encoding='utf-8')
        with chrome_lock.held('test_plugins_v2: промер испорченной страницы'):
            subprocess.run(['node', str(VIDEO / 'probe_dom.mjs'), str(out)], capture_output=True, text=True, encoding='utf-8', errors='replace')
        res, text = checks(proj)
        mine = [l for l in res.get('V37', '').split('; ') if 'canvas' in l and ln['text'][:20] in l]
        check(res.get('V37', '').startswith('FAIL') and mine,
              'золото на закате в фразе набора: ждали FAIL V37 со строкой «%s», получили «%s»' % (ln['text'], res.get('V37')))
        got = float(re.search(r'контраст\D*(\d+[.,]\d+)', mine[0]).group(1).replace(',', '.'))
        check(got < 1.8, 'контраст золота на шафране по формуле WCAG — 1,33; проверка намерила %.2f: %s' % (got, mine[0]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_kit_checks_skip_in_film_without_kit():
    """Фильм без набора букв, без пера и без Lottie (films/silent.json): V38–V43 пропущены, а не красные."""
    tmp, proj = project('nokit')
    try:
        code, text = build(proj, 'silent')
        check(code == 0, 'страница фильма silent не собралась: %s' % text[-600:])
        res, text = checks(proj, 'silent')
        for code in ('V38', 'V39', 'V40', 'V41', 'V42', 'V43'):
            check(res.get(code, '').startswith('SKIP'), '%s у фильма без набора: ждали SKIP, получили «%s»' % (code, res.get(code)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_pen_film_reds_and_samples():
    """Порчи фильма pen (checks/red_pen.py: V38–V43) краснеют каждая своей строкой, образцы молчат."""
    proj, page = pen_page()
    code, text = run([PY, VIDEO / 'check.py', FILM, '--red', '--project', proj])
    check(code == 0, 'порчи фильма pen: %s' % text[-1500:])
    for name in ('V38', 'V39', 'V40', 'V41', 'V42', 'V43'):
        check(name in text, 'среди порч фильма pen нет порчи %s:\n%s' % (name, text[-1500:]))
    code, text = run([PY, VIDEO / 'check.py', FILM, '--samples', '--project', proj])
    check(code == 0, 'образцы фильма pen: %s' % text[-1500:])


# ---------------------------------------------------------------- Lottie
LOTTIE_FILM = 'lottie'       # пробный фильм из одной сцены lottie-probe: короче фильма pen (рендер кадрами дважды)
LOTTIE_ROWS = [{'n': 31, 'scene': 'lottie-probe', 'voice': 'none', 'ms': 2000, 'scene_start': 0, 'silent': True, 'what': 'такт 1'},
               {'n': 32, 'scene': 'lottie-probe', 'voice': 'none', 'ms': 2000, 'scene_start': 2.0, 'silent': True, 'what': 'такт 2'},
               {'n': 33, 'scene': 'lottie-probe', 'voice': 'none', 'ms': 2000, 'scene_start': 4.0, 'silent': True, 'what': 'такт 3'}]
# Путь квадрата в файле libs/pulse.lottie.json, разобранный вручную: центр по x — 110 → 290 → 110 единиц файла на кадрах
# 0, 30, 60; кривая ключей симметрична (0,5; 0 → 0,5; 1), значит на кадрах 15 и 45 центр ровно посередине — 200; по y — 200.
# Центр масс квадрата от поворота и масштаба не зависит (якорь слоя в его центре).
SQUARE_X = {0: 110.0, 15: 200.0, 30: 290.0, 45: 200.0}
SQUARE_Y = 200.0
LOTTIE_BOX = 400.0           # полотно файла, единиц


def lottie_project(tag):
    tmp, proj = project(tag)
    (proj / 'films' / (LOTTIE_FILM + '.json')).write_text(json.dumps({
        'title': 'Проба Lottie', 'scenes': ['lottie-probe'], 'stills': True, 'tail_sec': 1.0, 'voice_bars': False,
        'replies': LOTTIE_ROWS}, ensure_ascii=False), encoding='utf-8')
    return tmp, proj


def lottie_element(proj):
    sb = load(proj / 'scenes' / 'lottie-probe' / 'storyboard.json')
    return next(e for e in sb['elements'] if e['kind'] == 'lottie')


def lottie_data(proj, el):
    return load(next(q for q in (proj / el['src'], VIDEO / el['src']) if q.exists()))     # файл: от проекта, иначе от движка


def square_center(im, el, primary, scale=1.0):
    """Центр масс пикселей цвета квадрата в рамке элемента — в единицах файла анимации; None — квадрата в кадре нет."""
    x0, y0, w, h = [int(round(el[k] * 96 * scale)) for k in ('x', 'y', 'w', 'h')]
    box = im.crop((x0, y0, x0 + w, y0 + h))
    sx = sy = n = 0
    for k, (r, g, b) in enumerate(_pixels(box)):
        if abs(r - primary[0]) < 30 and abs(g - primary[1]) < 30 and abs(b - primary[2]) < 30:
            sx += k % w
            sy += k // w
            n += 1
    if n < 50:
        return None
    return sx / n * LOTTIE_BOX / w, sy / n * LOTTIE_BOX / h


def primary_rgb(proj):
    return tuple(int(load(proj / 'tokens.json')['palette']['primary'][k:k + 2], 16) for k in (1, 3, 5))


def test_lottie_player_is_in_engine_node_set():
    """Проигрыватель — пакет lottie-web ровно той версии, что записана в наборе Node движка (engine/video/package.json)."""
    want = load(VIDEO / 'package.json')['dependencies'].get('lottie-web')
    check(want == '5.12.2', 'в engine/video/package.json lottie-web = %s, ждали точную версию 5.12.2' % want)
    have = VIDEO / 'node_modules' / 'lottie-web' / 'package.json'
    check(have.exists(), 'пакета lottie-web нет в наборе Node (%s): поставь tools/setup.py install' % have)
    check(load(have)['version'] == want, 'стоит lottie-web %s, а набор движка требует %s' % (load(have)['version'], want))
    check((VIDEO / 'node_modules' / 'lottie-web' / 'build' / 'player' / 'lottie.min.js').exists(), 'в пакете нет файла проигрывателя')


def test_lottie_without_player_is_refused_with_package_name():
    tmp, proj = lottie_project('lottie_noplayer')
    try:
        code, text = build(proj, LOTTIE_FILM, {'MOTION_LOTTIE_PLAYER': str(Path(tmp) / 'нет-такого.js')})
        check(code != 0 and 'lottie-web' in text, 'нет проигрывателя: ждали отказ сборки с именем пакета lottie-web, получили код %d: %s'
              % (code, text[-400:]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


EVIL_NAME = '</script><script>window.__INJECTED__ = 1;</script><script>'


class _Scripts(HTMLParser):
    """Содержимое каждого <script> страницы — как его режет браузер (первое «</script» закрывает скрипт)."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.scripts, self._open = [], False

    def handle_starttag(self, tag, attrs):
        if tag == 'script':
            self._open = True
            self.scripts.append('')

    def handle_endtag(self, tag):
        if tag == 'script':
            self._open = False

    def handle_data(self, data):
        if self._open:
            self.scripts[-1] += data


def test_lottie_layer_name_cannot_close_script():
    """Чужой файл анимации: имя слоя — «</script><script>…». Файл вшивается в данные фильма страницы; на странице не
    появляется скрипта из имени слоя, страница собирается и играет, имя слоя доходит до проигрывателя как есть."""
    tmp, proj = lottie_project('lottie_inject')
    try:
        el = lottie_element(proj)
        data = load(VIDEO / el['src'])
        data['layers'][0]['nm'] = EVIL_NAME
        (proj / el['src']).parent.mkdir(parents=True, exist_ok=True)
        (proj / el['src']).write_text(json.dumps(data), encoding='utf-8')         # файл проекта главнее файла движка
        code, text = build(proj, LOTTIE_FILM)
        index = proj / 'out' / LOTTIE_FILM / 'index.html'
        check(index.exists(), 'страница не записана: %s' % text[-600:])
        p = _Scripts()
        p.feed(index.read_text(encoding='utf-8'))
        check(not any(x.strip().startswith('window.__INJECTED__') for x in p.scripts),
              'имя слоя чужого файла Lottie стало на странице исполняемым скриптом (скриптов на странице %d)' % len(p.scripts))
        films = [x for x in p.scripts if x.lstrip().startswith('window.__FILM__')]
        check(len(films) == 1, 'скриптов с данными фильма на странице %d, ждали один' % len(films))
        got = json.loads(films[0].strip()[len('window.__FILM__ = '):].rstrip(';'))
        names = [l.get('nm') for sc in got['scenes'] for it in ((sc.get('plugins') or {}).get('lottie') or {}).get('items', [])
                 for l in it['data']['layers']]
        check(EVIL_NAME in names, 'имя слоя не дошло до данных страницы как есть: %s' % names)
        check(code == 0, 'страница с таким файлом не собралась: %s' % text[-600:])
        res, text = checks(proj, LOTTIE_FILM)
        check(res.get('V39', '').startswith('OK') and res.get('V1', '').startswith('OK'),
              'страница с таким файлом: ждали OK у V39 и V1 (ошибок страницы нет), получили «%s» и «%s»' % (res.get('V39'), res.get('V1')))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_lottie_plays_on_timeline_in_film_pen():
    """Фильм pen, сцена lottie-probe, настоящий проигрыватель: кадр анимации в каждом кадре промера — (t − at) · speed · fr
    файла (до at — первый, после конца — последний); на кадрах полосы квадрат стоит там, где его ставит файл; страница
    не ходит в сеть; V39 зелёная."""
    proj, page = pen_page()
    film = load(page / 'film.json')
    el = lottie_element(proj)
    data = lottie_data(proj, el)
    at, speed, total = moment(film, el['at']), el.get('speed', 1), data['op'] - data['ip']
    seen = set()
    for s in load(page / 'probe.json')['samples']:
        it = next((x for pl in s['plugins'] if pl and pl.get('plugin') == 'lottie' for x in pl['items']), None)
        check(it is not None, 'в промере страницы нет записи плагина lottie (t=%.2f с)' % s['t'])
        check(it['loaded'] and it['nodes'] > 3, 't=%.3f с: проигрыватель не загрузил анимацию (узлов %s)' % (s['t'], it['nodes']))
        want = min(total - 1.0, max(0.0, (s['t'] - at) * speed * data['fr']))
        check(abs(it['frame'] - want) < 0.01, 't=%.3f с: показан кадр %.3f, по шкале ждали %.3f' % (s['t'], it['frame'], want))
        seen.add(round(want))
    check(len(seen) >= 5, 'промер застал %d разных кадров анимации — тест ничего не доказал' % len(seen))
    frames = strip_frames(proj, page, at, at + 1.6)
    primary = primary_rgb(proj)
    for k, want_x in sorted(SQUARE_X.items()):
        got = square_center(frames[k][1], el, primary, SCALE)
        check(got is not None, 'кадр файла %d (t=%.3f с): квадрата анимации в кадре нет — файл не открылся проигрывателем' % (k, frames[k][0]))
        check(abs(got[0] - want_x) < 3 and abs(got[1] - SQUARE_Y) < 3,
              'кадр файла %d (t=%.3f с): квадрат в (%.1f, %.1f) единицах файла, по ключам файла ждали (%.1f, %.1f)'
              % (k, frames[k][0], got[0], got[1], want_x, SQUARE_Y))
    html_text = (page / 'index.html').read_text(encoding='utf-8')
    check(not re.search(r'(src|href)\s*=\s*["\']https?://', html_text), 'в странице есть адрес сети в src / href')
    check('data-lib="lottie-web"' in html_text, 'проигрыватель lottie-web не вшит в страницу')
    pp = load(page / 'plugin_probe.json')
    check(pp.get('requests') == [], 'при показе страницы были запросы мимо её файлов: %s' % pp.get('requests'))


def test_lottie_two_strips_are_byte_equal_from_any_start():
    """Два снятия одной сцены побайтно равны; кадр момента t один и тот же, с какого бы места ни начали полосу."""
    proj, page = pen_page()
    film = load(page / 'film.json')
    at = round(moment(film, lottie_element(proj)['at']) * FPS) / FPS
    a = strip.frames(str(proj), FILM, at, at + 1.0, FPS, SCALE, page=str(page))
    blobs_a = [Path(q).read_bytes() for q in a]
    check(len(set(blobs_a)) >= 20, 'анимация не играет: из %d кадров полосы разных %d' % (len(blobs_a), len(set(blobs_a))))
    shutil.rmtree(Path(a[0]).parent, ignore_errors=True)            # кэш этой полосы: второе снятие — новым запуском Chrome
    b = strip.frames(str(proj), FILM, at, at + 1.0, FPS, SCALE, page=str(page))
    check(blobs_a == [Path(q).read_bytes() for q in b], 'два снятия одной сцены разошлись побайтно')
    k = 12
    c = strip.frames(str(proj), FILM, at + k / FPS, at + 1.0, FPS, SCALE, page=str(page))
    check(Path(c[0]).read_bytes() == blobs_a[k] and Path(c[5]).read_bytes() == blobs_a[k + 5],
          'кадр момента t зависит от того, с какого места начали снимать')


def test_lottie_render_twice_is_byte_equal_and_follows_at():
    """Рендер кадрами (HyperFrames) дважды — побайтно тот же; в кадре рендера квадрат стоит там, где велит шкала
    (at, speed) и файл, а не там, куда анимацию поставил бы адаптер Lottie из HyperFrames, отсчитав от начала ролика:
    у анимации один хозяин."""
    from PIL import Image
    sys.path.insert(0, str(VIDEO))
    import stamp
    tmp, proj = lottie_project('lottie_render')
    try:
        out = proj / 'out' / LOTTIE_FILM
        code, text = run([PY, VIDEO / 'build.py', LOTTIE_FILM, '--png', '--project', proj])
        check(code == 0, 'рендер кадрами не прошёл: %s' % text[-900:])
        files = stamp.frame_files(str(out))
        first = [Path(q).read_bytes() for q in files]
        film = load(out / 'film.json')
        el = lottie_element(proj)
        at = moment(film, el['at'])
        check(len(first) == round(film['duration'] * FPS), 'кадров рендера %d, а по длительности %d' % (len(first), round(film['duration'] * FPS)))
        primary = primary_rgb(proj)
        for k, want_x in sorted(SQUARE_X.items()):
            if not k:
                continue
            n = int(round((at + k / 30.0) * FPS))            # кадр файла k идёт через k / fr секунд после at (fr файла — 30)
            got = square_center(Image.open(files[n]).convert('RGB'), el, primary)
            check(got is not None and abs(got[0] - want_x) < 3,
                  'кадр рендера %d (t=%.3f с): квадрат на x=%s единиц файла, по шкале и файлу ждали %.1f — анимацию ведёт второй хозяин'
                  % (n, n / FPS, got and round(got[0], 1), want_x))
        code, text = run([PY, VIDEO / 'build.py', LOTTIE_FILM, '--png', '--force', '--project', proj])
        check(code == 0, 'второй рендер кадрами не прошёл: %s' % text[-900:])
        second = [Path(q).read_bytes() for q in stamp.frame_files(str(out))]
        check(first == second, 'два рендера одной сцены разошлись побайтно: кадров %d и %d, разных %d'
              % (len(first), len(second), sum(1 for x, y in zip(first, second) if x != y)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_v39_red_when_time_comes_from_page_load():
    """Порча «время от загрузки» на настоящем проигрывателе: плагин на странице ставит кадр по часам страницы, а не
    по шкале — V39 краснеет."""
    tmp, proj = lottie_project('lottie_red')
    try:
        code, text = build(proj, LOTTIE_FILM)
        check(code == 0, 'страница с Lottie не собралась: %s' % text[-900:])
        res, text = checks(proj, LOTTIE_FILM)
        check(res.get('V39', '').startswith('OK'), 'V39 на исправной странице: ждали OK, получили «%s»\n%s' % (res.get('V39'), text[-800:]))
        index = proj / 'out' / LOTTIE_FILM / 'index.html'
        page = index.read_text(encoding='utf-8')
        healthy = 'var local = t - it.c.at;'
        check(page.count(healthy) == 1, 'в странице нет строки плагина lottie, которую портит тест (время от шкалы)')
        index.write_text(page.replace(healthy, 'var local = performance.now() / 1000;'), encoding='utf-8')
        with chrome_lock.held('test_plugins_v2: промер испорченной страницы'):
            r = subprocess.run(['node', str(VIDEO / 'probe_dom.mjs'), str(proj / 'out' / LOTTIE_FILM)], capture_output=True, text=True,
                               encoding='utf-8', errors='replace')
        check(r.returncode == 0, 'промер испорченной страницы упал: %s' % (r.stdout + r.stderr)[-500:])
        res, text = checks(proj, LOTTIE_FILM)
        check(res.get('V39', '').startswith('FAIL') and 'не от шкалы' in res['V39'],
              'время от загрузки: ждали FAIL V39 «не от шкалы», получили «%s»' % res.get('V39'))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_zz_cleanup():
    for tmp, _proj, _page in _TMP.values():
        shutil.rmtree(tmp, ignore_errors=True)
    _TMP.clear()


if __name__ == '__main__':
    sys.exit(run_module(globals()))
