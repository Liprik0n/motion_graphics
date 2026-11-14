# -*- coding: utf-8 -*-
"""Порчи и образцы условий стиля V21–V24 (check.py) и реестра стилей — калиброваны на демо-фильме стилей
films/styles.json (сцена style-probe; проход film — база порч страницы).

    check.py styles --red [подстрока]       порчи страницы: копия прохода film, вставка в index.html,
                                            новый промер стиля (styles/_core/probe_style.mjs) → check
    check.py styles --samples [подстрока]   законные варианты на грани: те же копии, обязаны пройти молча
    check.py styles --red-slow [подстрока]  порчи реестра: копия проекта с плохим стилем в <проект>/styles/,
                                            build.py --page обязан отказать своей строкой

Каждая порча — кортеж (имя, правка, подстрока, промер вспышек нужен?): засчитана, только если покраснела
ИМЕННО строка с этой подстрокой. Порчи пишутся на класс дефекта: «стиль накрыл текст» (туман, размытие),
«стиль подменил роль» (переменная, заливка, фильтр CSS и SVG, шрифт, смешение), «мерцание» (весь кадр, угол),
«случайность не от кадра» (Math.random, время загрузки). Поставка не трогается: всё на копиях во временной папке.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # engine/video
sys.path.insert(0, HERE)
import check as C      # noqa: E402
sys.path.insert(0, os.path.dirname(HERE))
import chrome_lock     # noqa: E402  замок безголового Chrome

BASE_STYLE = 'film'
PLUGIN = '(window.StagePlugins = window.StagePlugins || []).push(function (F, api) { %s });'


# ---------------------------------------------------------------- правки копии страницы
def _head(css):
    """<style> стиля (как его кладёт сборка: data-style-css) — выключается в кадре «без стиля»."""
    return lambda page: page.replace('</head>', '<style data-style-css="%s">%s</style>\n</head>' % (BASE_STYLE, css), 1)


def _plain_css(css):
    """<style> проекта, не стиля: действует и в кадре «без стиля»."""
    return lambda page: page.replace('</head>', '<style>%s</style>\n</head>' % css, 1)


def _plugin(body):
    js = '<script>' + PLUGIN % body + '</script>\n'
    # как кладёт сборка: скрипты стиля — после данных фильма, вне слоя содержания (его читает V12)
    return lambda page: page.replace('<script data-style-core>', js + '<script data-style-core>', 1)


def _both(*fns):
    def f(page):
        for fn in fns:
            page = fn(page)
        return page
    return f


def _film(page_fn, film_fn):
    """Правка страницы + правка film.json копии (то, что сборка пишет в film.json для проверки)."""
    def f(page):
        return page_fn(page)
    f.film = film_fn
    return f


def _code_title(text_js, cell, label=None):
    """Заголовок, нарисованный кодом: fonts.title = code в film.json, текст каркаса прозрачен (world.css стиля),
    пиксельная надпись StyleCore.pixelText в рамке заголовка (StyleCore.codeTitle)."""
    js = ('var L = api.addLayer("ct", "back"), C = window.StyleCore;'
          'var svg = C.svg("svg", {width: "1920", height: "1080"}, L); svg.style.position = "absolute";'
          'var r = C.codeTitle(api, api.styleScenes("film"), svg, function (g, text, b) {'
          ' C.pixelText(g, %s, b.x, b.y + 2, {rows: 12, cell: %d, color: "#1A1C1E"}); });'
          '%s return {render: r};' % (text_js, cell, ('svg.querySelector("[data-style-title]").setAttribute("data-text", "%s");' % label)
                                       if label else ''))

    def film_fn(fj):
        fj['styles']['film']['fonts']['title'] = 'code'
    return _film(_both(_plugin(js), _head(R + ' .fr-title .t { color: transparent; }')), film_fn)


MOTION_ALL = '"motion":{"icon_step_frames":1,"icon_overshoot":0}'
S = '.scene[data-style="%s"]' % BASE_STYLE
R = '#root[data-style="%s"]' % BASE_STYLE
TOGGLE = ('var d = api.addLayer("x-%s", "%s"); d.style.cssText += ";%s";'
          'return {render: function (t) { var f = api.frameOf(t); d.style.opacity = (Math.floor(f / %d) %% 2) ? "1" : "0"; }};')
CORNER = 'left:1440px;top:810px;width:480px;height:270px;background:#1A1C1E'

# (имя, правка, подстрока, промер вспышек нужен?, режим): режим — какая страница и какой проект:
#   world — проход film в режиме «мир» (по умолчанию); lock — тот же проход, собранный с project.json
#   style_brand_lock: true («только фактура»); world>lock — страница «мира», а проверка с замком в проекте.
RED = [
    ('туман поверх текста', _plugin('var d = api.addLayer("fog", "over"); d.style.background = "rgba(255,255,255,0.72)"; return {};'),
     'V21 текст читается: #style-probe--', False, 'world'),
    ('размытие букв', _head(S + ' .el .t { filter: blur(4px); }'), 'V21 текст читается: #style-probe--', False, 'world'),
    ('--c-primary подменён', _head(R + ' { --c-primary: #2F6FA9; }'), 'V22 палитра бренда: --c-primary на странице #2F6FA9', False, 'world'),
    ('текст цветом decor', _head(S + ' .el .t { color: #F3ECDD; }'),
     'V22 палитра бренда: цвет текста #style-probe--', False, 'world'),
    ('заливка вне бренда и decor', _head(S + ' .k-plaque { background: #123456; }'),
     'V22 палитра бренда: #style-probe--plaque background rgb(18, 52, 86) — вне палитры бренда и decor стиля film', False, 'world'),
    ('сепия на сцене', _head(S + ' { filter: sepia(0.6); }'), 'V22 палитра бренда: фильтр на #scene--style-probe перекрашивает', False, 'world'),
    ('svg-фильтр с перекраской', _both(
        _plugin('var f = window.StyleCore.svg("filter", {id: "recolor"}, window.StyleCore.defs());'
                'window.StyleCore.svg("feColorMatrix", {type: "hueRotate", values: "90"}, f); return {};'),
        _head(S + ' .k-card { filter: url(#recolor); }')),
     'V22 палитра бренда: фильтр на #style-probe--card перекрашивает содержание: feColorMatrix', False, 'world'),
    ('шрифт основного текста подменён', _head(S + ' .t { font-family: serif; }'), 'font-family со стилем serif', False, 'world'),
    ('чужой шрифт заголовка', _head(R + ' .fr-title { font-family: Impact, serif; }'),
     'V22 палитра бренда: шрифт заголовка #title--style-probe — Impact', False, 'world'),
    ('плашка смешана с фоном', _head(S + ' .k-plaque { mix-blend-mode: multiply; }'),
     'V22 палитра бренда: фильтр — #style-probe--plaque смешивается с фоном', False, 'world'),
    ('стиль приглушил текст', _head(S + ' .el .t { opacity: 0.35; }'), 'V21 текст читается: #style-probe--', False, 'world'),
    ('стиль приглушил плашку', _head(S + ' .k-plaque { opacity: 0.4 !important; }'),
     'V21 текст читается: #style-probe--plaque', False, 'world'),
    ('стиль спрятал текст', _head(S + ' .k-card .t { display: none; }'), '— строки нет в кадре', False, 'world'),
    ('слой поверх: смешение color', _plugin('var d = api.addLayer("ov", "over"); d.style.background = "#D9822B"; d.style.mixBlendMode = "color"; return {};'),
     'V22 палитра бренда: слой стиля поверх содержания #ov перекрашивает его: mix-blend-mode: color', False, 'world'),
    ('слой поверх: backdrop-filter', _plugin('var d = api.addLayer("ov", "over"); d.style.backdropFilter = "hue-rotate(90deg)"; return {};'),
     'слой стиля поверх содержания #ov перекрашивает его: backdrop-filter', False, 'world'),
    ('слой поверх: сепия фильтром', _plugin('var d = api.addLayer("ov", "over"); d.style.background = "rgba(255,255,255,0.05)";'
                                            'd.style.filter = "sepia(1)"; return {};'),
     'слой стиля поверх содержания #ov перекрашивает его: filter: sepia', False, 'world'),
    ('заголовок кодом — чужой текст', _code_title('"ДРУГОЙ ТЕКСТ"', 4, 'ДРУГОЙ ТЕКСТ'), 'V22 палитра бренда: заголовок кодом «ДРУГОЙ ТЕКСТ» ≠ заголовку сцены «Проба стиля»', False, 'world'),
    ('заголовок кодом за рамкой', _code_title('text', 9), 'V22 палитра бренда: заголовок кодом за рамкой заголовка', False, 'world'),
    ('замок: заливка цветом decor', _head(S + ' .k-plaque { background: #F3ECDD; }'),
     'V22 палитра бренда: #style-probe--plaque background со стилем rgb(243, 236, 221)', False, 'lock'),
    ('замок: страница мира', None, '#title--style-probe font-family со стилем sty-film-title', False, 'world>lock'),
    ('чёрный кадр 5 раз в секунду', _plugin(TOGGLE % ('blk', 'over', 'background:#1A1C1E', 3)), 'V23 вспышки: 5 в секунду', True, 'world'),
    ('угол мигает 4 раза в секунду', _plugin(TOGGLE % ('cor', 'back', CORNER, 4)), 'V23 вспышки: 4 в секунду', True, 'world'),
    ('зерно от Math.random', _plugin('var d = api.addLayer("rnd", "over"); d.style.cssText += ";left:40px;top:860px;width:300px;height:120px";'
                                     'return {render: function (t) { d.style.background = "rgba(26,28,30," + (Math.random() * 0.2).toFixed(3) + ")"; }};'),
     'V24 детерминизм стиля: кадр', False, 'world'),
    ('сид от времени загрузки', _plugin('var d = api.addLayer("clk", "over"); d.style.cssText += ";left:40px;top:860px;width:300px;height:120px";'
                                        'var r = window.StyleCore.rng(Date.now() | 0);'
                                        'd.style.background = "rgba(26,28,30," + (0.05 + r() * 0.2).toFixed(3) + ")"; return {};'),
     'V24 детерминизм стиля: кадр', False, 'world'),
]

# (имя, правка, режим): законное на грани — обязано пройти молча
SAMPLES = [
    ('фактура вне палитры над фоном', _plugin('var d = api.addLayer("tint", "back"); d.style.background = "rgba(255,200,120,0.25)"; return {};'), 'world'),
    ('мир: заливка плашки цветом decor', _head(S + ' .k-plaque { background: #F3ECDD; }'), 'world'),
    ('мир: заливка плашки другой ролью бренда', _head(S + ' .k-plaque { background: var(--c-primary_pale); }'), 'world'),
    ('угол мигает 2 раза в секунду', _plugin(TOGGLE % ('cor', 'back', CORNER, 8)), 'world'),
    ('зерно от номера кадра', _plugin('var d = api.addLayer("seed", "back");'
                                      'return {render: function (t) { var r = window.StyleCore.rng(api.frameOf(t));'
                                      'd.style.background = "rgba(26,28,30," + (r() * 0.06).toFixed(3) + ")"; }};'), 'world'),
    ('бледная роль бренда, не стиль', _plain_css('#style-probe--plaque .t { color: var(--c-footer); }'), 'world'),
    ('кипение иконки url-фильтром', _both(_plugin('window.StyleCore.boil("smp-boil", {scale: 3}); return {};'),
                                         _head(S + ' .k-icon svg { filter: url(#smp-boil); }')), 'world'),
    ('заголовок, нарисованный кодом (пиксели)', _code_title('text', 4), 'world'),
    ('декор поверх содержания в поле кадра', _plugin('var d = api.addLayer("ov", "over");'
                                                    'd.style.cssText += ";left:1700px;top:960px;width:150px;height:40px;background:#16130F"; return {};'), 'world'),
    ('движение стиля: ступени, сетка, перелёт, дрожь', _both(lambda p: p.replace(MOTION_ALL,
        '"motion":{"icon_step_frames":2,"icon_overshoot":1.5,"step_frames":3,"grid_px":8,"overshoot":1.5,"move_overshoot":1.2,"jitter_px":2}', 1)), 'world'),
    ('замок: только фактура', None, 'lock'),
]


# ---------------------------------------------------------------- порчи стиля на настоящем фильме (F3)
# Проход фильма в стиле (build.py <фильм> --page --style X → <out>/<фильм>/X/): стиль, откалиброванный на пробе,
# на чужой раскладке «съедал» подписи. Механизм — окна под текстом (StyleCore.textWindows, середина = --c-paper);
# класс дефекта — середина окна не цвета бренда (тон мира: лён, экран плёнки, пергамент) или окна нет.
# Кремовый #F3ECDD — тон экрана плёнки и льна ткани: подпись ролью accent на нём 2,25–2,5 при 2,93 бренда.
WIN = '.style-window'
FILM_RED = [
    ('стиль на фильме: окно под подписью тоном мира', _head(WIN + ' { background: #F3ECDD !important; }'), 'V21 текст читается: #'),
    ('стиль на фильме: тёмный мир без светлого окна', _head(WIN + ' { background: #16130F !important; box-shadow: none !important; }'),
     'V21 текст читается: #'),
]
FILM_SAMPLES = [
    ('стиль на демо-фильме как есть', None),
    ('окно оформлено миром: толстая кромка и тень', _head(WIN + ' { box-shadow: 0 0 0 6px #16130F, 10px 12px 0 #16130F !important; }')),
]


def _pass_dir(out_dir):
    if not os.path.exists(os.path.join(out_dir, 'style_probe.json')):
        print('Нет %s — сначала build.py <фильм> --page --style <стиль>' % os.path.join(out_dir, 'style_probe.json'))
        return None
    return out_dir


def red_film(root, out_dir, film, only, filt=None):
    """check.py <фильм> --page --style X --red: порчи «стиль на фильме роняет контраст подписи» на копии прохода."""
    od = _pass_dir(out_dir)
    if od is None:
        return 1
    t0, failed, n = time.time(), 0, 0
    for name, edit, expect in FILM_RED:
        if filt and filt not in name:
            continue
        n += 1
        failed += _verdict(name, _probe_copy(root, od, edit, False), expect)
    print('порчи стиля на фильме %s: %d, не покраснело своей строкой: %d · %.0f с' % (film, n, failed, time.time() - t0))
    return 1 if failed else 0


def samples_film(root, out_dir, film, only, filt=None):
    od = _pass_dir(out_dir)
    if od is None:
        return 1
    t0, failed, n = time.time(), 0, 0
    for name, edit in FILM_SAMPLES:
        if filt and filt not in name:
            continue
        n += 1
        bad = [l for l in _probe_copy(root, od, edit, False) if l.startswith('FAIL')]
        if bad:
            failed += 1
            print('MISS образец «%s» покраснел: %s' % (name, ' | '.join(bad)[:600]))
        else:
            print('ok   образец %-36s — молча' % name)
    print('образцы стиля на фильме %s: %d, покраснело: %d · %.0f с' % (film, n, failed, time.time() - t0))
    return 1 if failed else 0


# ---------------------------------------------------------------- порчи реестра: копия проекта, свой стиль в <проект>/styles/
def _bad_style(name, data=None, css=None, world=None):
    def f(pd):
        d = os.path.join(pd, 'styles', name)
        os.makedirs(d)
        sj = {'name': name, 'label': 'порча', 'motion': {'icon_step_frames': 1, 'icon_overshoot': 0}, 'sfx': {'clips': {}},
              'decor': {'dark': '#16130F'}, 'fonts': {'title': {'family': 'Georgia', 'files': ['georgiab.ttf']}},
              'objects': ['a', 'b', 'c', 'd', 'e']}
        if data:
            sj.update(data)
        with open(os.path.join(d, 'style.json'), 'w', encoding='utf-8') as fh:
            json.dump(sj, fh, ensure_ascii=False)
        if css is not None:
            with open(os.path.join(d, 'style.css'), 'w', encoding='utf-8') as fh:
                fh.write(css)
        if world is not None:
            with open(os.path.join(d, 'world.css'), 'w', encoding='utf-8') as fh:
                fh.write(world)
    return f


def _title_css(name):
    return '#root[data-style="%s"] .fr-title { font-family: var(--sty-%s-title); }\n' % (name, name)


RED_SLOW = [
    ('селектор без привязки к стилю', 'x', _bad_style('x', css='.k-card { outline: 1px solid red; }'),
     'styles/x/style.css: селектор «.k-card» не привязан к стилю'),
    ('@import в стиле', 'x', _bad_style('x', css='@import url(a.css);'), '«@import url(a.css)» — @import и правила вне блока запрещены'),
    ('лишнее поле style.json', 'x', _bad_style('x', {'palette': {'primary': '#000000'}}), "styles/x/style.json: лишнее поле ['palette']"),
    ('ступени на 9', 'x', _bad_style('x', {'motion': {'icon_step_frames': 9, 'icon_overshoot': 0}}),
     'motion.icon_step_frames: 9 вне [1, 4]'),
    ('материал звука неизвестным полем', 'x', _bad_style('x', {'sfx': {'clips': {'tick': {'reverb': 1}}}}), 'sfx.clips.tick — поля только из'),
    ('@-правило не keyframes', 'x', _bad_style('x', css='@media print { .scene[data-style="x"] .t { color: red; } }'),
     'из @-правил можно только @keyframes x-'),
    ('предметов мира меньше пяти', 'x', _bad_style('x', {'objects': ['sun', 'cloud']}), 'objects — список предметов мира стиля, не меньше 5'),
    ('decor не цветом', 'x', _bad_style('x', {'decor': {'paper': 'кремовый'}}), "decor.paper = 'кремовый' — роль латиницей, цвет #RRGGBB"),
    ('шрифт без кириллицы', 'x', _bad_style('x', {'fonts': {'title': {'family': 'Ink Free', 'files': ['Inkfree.ttf']}}}),
     'в Inkfree.ttf нет кириллицы'),
    ('без шрифта заголовка', 'x', _bad_style('x', {'fonts': {}}), 'шрифт заголовка обязателен'),
    ('сетка движения 40 px', 'x', _bad_style('x', {'motion': {'icon_step_frames': 1, 'icon_overshoot': 0, 'grid_px': 40}}),
     'motion.grid_px: 40 вне [0, 32]'),
    ('волна звука sine', 'x', _bad_style('x', {'sfx': {'clips': {'tick': {'wave': 'sine'}}}}), "sfx.clips.tick.wave = 'sine' — только square, soft"),
    ('битность 1', 'x', _bad_style('x', {'sfx': {'clips': {'tick': {'bits': 1}}}}), 'sfx.clips.tick.bits: 1 вне [2, 16]'),
    ('шрифт декора кодом', 'x', _bad_style('x', {'fonts': {'title': {'kind': 'code'}, 'decor': {'kind': 'code'}}}),
     'kind "code" бывает только у title'),
    ('шрифт заголовка не применён', 'x', _bad_style('x'), 'V22 палитра бренда: шрифт заголовка стиля x (sty-x-title) не стоит на заголовке'),
    ('стиля нет', 'nope', None, 'Стиля «nope» нет'),
]
SAMPLES_SLOW = [
    ('свой стиль: всё движение и звук, check.py целиком', 'mine', _bad_style('mine', {
        'motion': {'icon_step_frames': 2, 'icon_overshoot': 1.5, 'step_frames': 3, 'grid_px': 8, 'overshoot': 1.5,
                   'move_overshoot': 1.2, 'jitter_px': 2},
        'sfx': {'clips': {'tick': {'wave': 'square', 'bits': 4, 'hold': 8}, 'ping': {'partials': 0.6},
                          'whoosh_click': {'noise_burst': 0.8, 'grit': 0.3, 'wave': 'soft', 'lp_hz': 3000}}}},
                                    world=_title_css('mine'))),
    ('свой стиль проекта папкой', 'mine', _bad_style('mine', css='.scene[data-style="mine"] .k-card { outline: 1px solid var(--c-ink); }\n'
                                                                '@keyframes mine-wave { from { opacity: 0 } to { opacity: 1 } }',
                                     world=_title_css('mine'))),
]


# ---------------------------------------------------------------- прогон
def _calibrated(film, only):
    if film != 'styles' or only:
        print('Порчи стиля калиброваны на демо-фильме стилей целиком: check.py styles --red | --samples | --red-slow')
        return False
    return True


def _base_dir(out_dir):
    od = os.path.join(out_dir, BASE_STYLE)
    if not os.path.exists(os.path.join(od, 'style_probe.json')):
        print('Нет %s — сначала build.py styles --page' % os.path.join(od, 'style_probe.json'))
        return None
    return od


class Bases:
    """Страницы порч: «мир» — готовый проход film; «замок» — копия проекта с style_brand_lock: true,
    собранная один раз на прогон (build.py --page --style film) и удаляемая в конце."""
    def __init__(self, root, out_dir):
        self.root, self.world = root, _base_dir(out_dir)
        self.tmp = self.lock_root = self.lock = None

    def get(self, mode):
        if mode == 'world':
            return self.root, self.world
        if self.lock is None:
            self.tmp = tempfile.mkdtemp(prefix='motion_style_lock_')
            pd = os.path.join(self.tmp, 'project')
            shutil.copytree(self.root, pd, ignore=shutil.ignore_patterns('out', 'node_modules', '.env', '__pycache__'))
            pj = C.load_json(os.path.join(pd, 'project.json'))
            pj['style_brand_lock'] = True
            with open(os.path.join(pd, 'project.json'), 'w', encoding='utf-8') as fh:
                json.dump(pj, fh, ensure_ascii=False, indent=1)
            r = subprocess.run([sys.executable, os.path.join(HERE, 'build.py'), 'styles', '--page', '--style', BASE_STYLE,
                                '--project', pd], capture_output=True, text=True, encoding='utf-8', errors='replace')
            od = os.path.join(pd, 'out', 'styles', BASE_STYLE)
            if r.returncode or not os.path.exists(os.path.join(od, 'style_probe.json')):
                raise SystemExit('сборка страницы с замком бренда упала: ' + (r.stdout + r.stderr).strip()[-400:])
            self.lock_root, self.lock = pd, od
        if mode == 'lock':
            return self.lock_root, self.lock
        return self.lock_root, self.world             # world>lock: страница мира, проект с замком

    def close(self):
        if self.tmp:
            shutil.rmtree(self.tmp, ignore_errors=True)


def _probe_copy(root, od, edit, flash):
    """→ строки отчёта check по копии прохода с правкой страницы и новым промером стиля."""
    tmp = tempfile.mkdtemp(prefix='motion_style_')
    try:
        cd = os.path.join(tmp, 'out')
        os.makedirs(cd)
        for n in ('index.html', 'film.json', 'probe.json'):
            shutil.copyfile(os.path.join(od, n), os.path.join(cd, n))
        shutil.copytree(os.path.join(od, 'assets'), os.path.join(cd, 'assets'))
        if edit is not None:
            p = os.path.join(cd, 'index.html')
            with open(p, encoding='utf-8') as fh:
                page = fh.read()
            new = edit(page)
            if new == page:
                return ['FAIL правка не легла на страницу — демо изменилось, обнови порчу']
            with open(p, 'w', encoding='utf-8') as fh:
                fh.write(new)
            if getattr(edit, 'film', None):
                fp = os.path.join(cd, 'film.json')
                fj = C.load_json(fp)
                edit.film(fj)
                with open(fp, 'w', encoding='utf-8') as fh:
                    json.dump(fj, fh, ensure_ascii=False)
        cmd = ['node', os.path.join(HERE, 'styles', '_core', 'probe_style.mjs'), cd] + ([] if flash else ['--skip', 'flash'])
        with chrome_lock.held('red_styles probe_style %s' % cd):
            r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
        if not os.path.exists(os.path.join(cd, 'style_probe.json')):
            return ['FAIL промер стиля копии не дал style_probe.json: ' + (r.stdout + r.stderr).strip()[-400:]]
        ctx = C.make_ctx(root, cd, page_only=True)
        _, lines = C.run(ctx, quiet=True)
        if not flash:                       # без покадрового промера V23 молчит: его порчи и образцы — с промером
            lines = [l for l in lines if 'нет покадровой яркости' not in l]
        return lines
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _verdict(name, lines, expect):
    hit = [l for l in lines if l.startswith('FAIL') and expect in l]
    if hit:
        print('RED  %-36s → %s' % (name, hit[0][5:][:200]))
        return 0
    got = [l for l in lines if l.startswith('FAIL')] or ['(всё зелёное)']
    print('MISS %-36s ждали «%s», получили: %s' % (name, expect, ' | '.join(got)[:600]))
    return 1


def red_fast(root, out_dir, film, only, filt=None):
    if not _calibrated(film, only) or _base_dir(out_dir) is None:
        return 1
    t0, failed, n, bases = time.time(), 0, 0, Bases(root, out_dir)
    try:
        for name, edit, expect, flash, mode in RED:
            if filt and filt not in name:
                continue
            n += 1
            r, od = bases.get(mode)
            failed += _verdict(name, _probe_copy(r, od, edit, flash), expect)
    finally:
        bases.close()
    print('порчи стиля: %d, не покраснело своей строкой: %d · %.0f с' % (n, failed, time.time() - t0))
    return 1 if failed else 0


def samples(root, out_dir, film, only, filt=None):
    if not _calibrated(film, only) or _base_dir(out_dir) is None:
        return 1
    t0, failed, n, bases = time.time(), 0, 0, Bases(root, out_dir)
    try:
        for name, edit, mode in SAMPLES:
            if filt and filt not in name:
                continue
            n += 1
            r, od = bases.get(mode)
            lines = _probe_copy(r, od, edit, True)
            bad = [l for l in lines if l.startswith('FAIL')]
            if bad:
                failed += 1
                print('MISS образец «%s» покраснел: %s' % (name, ' | '.join(bad)[:600]))
            else:
                print('ok   образец %-36s — молча' % name)
    finally:
        bases.close()
    print('образцы стиля: %d, покраснело: %d · %.0f с' % (n, failed, time.time() - t0))
    return 1 if failed else 0


def _build_copy(root, style, fn, check=False):
    """Копия проекта → build.py --page в стиле; check — и check.py этого прохода целиком (V1–V24) на копии."""
    tmp = tempfile.mkdtemp(prefix='motion_style_slow_')
    try:
        pd = os.path.join(tmp, 'project')
        shutil.copytree(root, pd, ignore=shutil.ignore_patterns('out', 'node_modules', '.env', '__pycache__'))
        if fn:
            fn(pd)
        r = subprocess.run([sys.executable, os.path.join(HERE, 'build.py'), 'styles', '--page', '--style', style, '--project', pd],
                           capture_output=True, text=True, encoding='utf-8', errors='replace')
        if r.returncode or not check:
            return r.returncode, (r.stdout + r.stderr)
        c = subprocess.run([sys.executable, os.path.join(HERE, 'check.py'), 'styles/' + style, '--page', '--project', pd],
                           capture_output=True, text=True, encoding='utf-8', errors='replace')
        return c.returncode, chr(10).join(l for l in (c.stdout + c.stderr).splitlines() if l.startswith('FAIL') or l.startswith('итог'))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def red_slow(root, out_dir, film, only, filt=None):
    if not _calibrated(film, only):
        return 1
    t0, failed, n = time.time(), 0, 0
    for name, style, fn, expect in RED_SLOW:
        if filt and filt not in name:
            continue
        n += 1
        code, out = _build_copy(root, style, fn, check=expect.startswith('V'))
        if code and expect in out:
            print('RED  %-36s → %s' % (name, [l for l in out.splitlines() if expect in l][0].strip()[:200]))
        else:
            failed += 1
            print('MISS %-36s ждали отказ «%s», код %d: %s' % (name, expect, code, out.strip()[-400:]))
    for name, style, fn in SAMPLES_SLOW:
        if filt and filt not in name:
            continue
        n += 1
        code, out = _build_copy(root, style, fn, check=True)
        if code:
            failed += 1
            print('MISS образец «%s»: сборка или check.py отказали: %s' % (name, out.strip()[-600:]))
        else:
            print('ok   образец %-36s — собрался, check.py зелёный' % name)
    print('порчи и образцы реестра: %d, не так, как ждали: %d · %.0f с' % (n, failed, time.time() - t0))
    return 1 if failed else 0
