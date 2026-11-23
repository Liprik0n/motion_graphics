# -*- coding: utf-8 -*-
"""Материалы и растр: вырезка (cutout.py), проверка принесённой картинки (picture_check.py), учёт источников
и лицензий (check_materials.py).

    python engine/tests/test_materials.py

Ожидания — не из кода под тестом: тестовые картинки рисуются здесь (диск известного цвета и диаметра на ровном
фоне, с настоящим сглаженным краем — рисуется в четыре раза крупнее и уменьшается), поэтому правильный цвет кромки
и размер поля известны заранее; запрещённые лицензии — из исследования лицензий (CC BY-NC, «только для
YouTube»). Модель HyperFrames проверяется, только если её веса уже скачаны; без них тест печатает пропуск.
"""
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import ENGINE, ROOT, PY, check, run_module   # noqa: E402

TOOLS = ENGINE / 'tools'
DISC = (170, 60, 40)            # цвет предмета
BG = (245, 245, 240)            # ровный светлый фон «как просим у генерации»
D = 200                         # диаметр диска, px


def disc_picture(path, size=(400, 300), bg=BG, center=None, diameter=D, quality=None, gradient=False):
    """Диск DISC на фоне bg с настоящей смесью на кромке (рисунок ×4 и уменьшение)."""
    from PIL import Image, ImageDraw
    w, h = size
    cx, cy = center or (w // 2, h // 2)
    big = Image.new('RGB', (w * 4, h * 4), bg)
    if gradient:
        d0 = ImageDraw.Draw(big)
        for x in range(w * 4):
            k = x / (w * 4)
            d0.line([(x, 0), (x, h * 4)], fill=tuple(int(bg[i] * (1 - 0.35 * k)) for i in range(3)))
    d = ImageDraw.Draw(big)
    r = diameter * 2
    d.ellipse((cx * 4 - r, cy * 4 - r, cx * 4 + r, cy * 4 + r), fill=DISC)
    img = big.resize((w, h), Image.LANCZOS)
    if quality:
        img.save(path, quality=quality)
    else:
        img.save(path)
    return path


def run(script, *args, env=None):
    e = dict(os.environ, PYTHONIOENCODING='utf-8')
    if env:
        e.update(env)
    r = subprocess.run([PY, str(TOOLS / script)] + [str(a) for a in args], capture_output=True, text=True,
                       encoding='utf-8', errors='replace', env=e)
    return r.returncode, (r.stdout + r.stderr)


def edge_halo(rgba, ref=DISC):
    """Насколько кромка светлее предмета: прямой цвет пикселей с заметной альфой (32…254), максимум по каналам
    превышения над цветом предмета; 0 — кромка цвета предмета, около 75 — кайма фона. Тёмные выбросы ресемплинга
    (звон Ланцоша) — не ореол и не считаются."""
    px = rgba.load()
    w, h = rgba.size
    worst = 0
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if 32 <= a < 255:
                worst = max(worst, r - ref[0], g - ref[1], b - ref[2])
    return worst


def test_cutout_gives_alpha_and_margin():
    from PIL import Image
    with tempfile.TemporaryDirectory() as tmp:
        src, out = os.path.join(tmp, 'disc.png'), os.path.join(tmp, 'cut.png')
        disc_picture(src)
        code, text = run('cutout.py', src, '-o', out, '--margin', '0.15')
        check(code == 0, 'cutout.py упал: %s' % text[-300:])
        im = Image.open(out)
        check(im.mode == 'RGBA', 'выход не RGBA: %s' % im.mode)
        pad = round(0.15 * D)
        check(abs(im.width - (D + 2 * pad)) <= 4 and abs(im.height - (D + 2 * pad)) <= 4,
              'размер %s, ждали ≈ %d (диск %d + 2 × поле %d)' % (im.size, D + 2 * pad, D, pad))
        check(im.getpixel((2, 2))[3] == 0, 'угол поля не прозрачный')
        check(im.getpixel((im.width // 2, im.height // 2)) == DISC + (255,), 'центр диска не цвета диска: %s' % (im.getpixel((im.width // 2, im.height // 2)),))
        box = im.split()[3].point(lambda v: 255 if v > 8 else 0).getbbox()
        check(abs(box[0] - pad) <= 3 and abs(im.width - box[2] - pad) <= 3, 'поле слева/справа не %d px: рамка %s' % (pad, box))


def test_no_light_halo_on_edge():
    from PIL import Image
    with tempfile.TemporaryDirectory() as tmp:
        src, out = os.path.join(tmp, 'disc.png'), os.path.join(tmp, 'cut.png')
        disc_picture(src)
        code, text = run('cutout.py', src, '-o', out)
        check(code == 0, text[-300:])
        worst = edge_halo(Image.open(out))
        check(worst <= 20, 'кромка светлее диска на %d (светлая кайма фона)' % worst)
        black = Image.new('RGB', Image.open(out).size, (0, 0, 0))
        im = Image.open(out)
        black.paste(im, (0, 0), im)
        lum = lambda c: 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
        raw = black.tobytes()
        top = max(lum(raw[i:i + 3]) for i in range(0, len(raw), 3))
        check(top <= lum(DISC) + 12, 'на чёрном есть пиксель ярче диска: %.0f против %.0f' % (top, lum(DISC)))


def test_halo_measure_catches_naive_key():
    """Мера кромки чувствительна: цветовой ключ «похож на фон → прозрачно» без очистки кромки её не проходит."""
    from PIL import Image
    with tempfile.TemporaryDirectory() as tmp:
        src = disc_picture(os.path.join(tmp, 'disc.png'))
        im = Image.open(src).convert('RGB')
        px = im.load()
        out = Image.new('RGBA', im.size)
        o = out.load()
        for y in range(im.height):
            for x in range(im.width):
                c = px[x, y]
                near = max(abs(c[0] - BG[0]), abs(c[1] - BG[1]), abs(c[2] - BG[2])) <= 24
                o[x, y] = (0, 0, 0, 0) if near else c + (200,)         # 200: кромка полупрозрачна
        check(edge_halo(out) > 20, 'мера кромки не заметила наивный ключ')


def test_cutout_survives_jpeg_noise():
    from PIL import Image
    with tempfile.TemporaryDirectory() as tmp:
        src, out = os.path.join(tmp, 'disc.jpg'), os.path.join(tmp, 'cut.png')
        disc_picture(src, quality=70)
        code, text = run('cutout.py', src, '-o', out)
        check(code == 0, text[-300:])
        im = Image.open(out)
        check(im.getpixel((1, 1))[3] == 0, 'фон с шумом JPEG не стал прозрачным')
        check(edge_halo(im) <= 30, 'кайма на JPEG: %d' % edge_halo(im))


def test_sheet_on_black_white_and_given_background():
    from PIL import Image
    with tempfile.TemporaryDirectory() as tmp:
        src, out = os.path.join(tmp, 'disc.png'), os.path.join(tmp, 'cut.png')
        disc_picture(src)
        code, text = run('cutout.py', src, '-o', out, '--sheet', '--bg', '#204060')
        check(code == 0, text[-300:])
        sheet = Image.open(os.path.join(tmp, 'cut-sheet.png')).convert('RGB')
        h = sheet.height
        # панели в ряд: три одинаковых по ширине; верхний левый угол каждой — цвет её фона (поле предмета прозрачно)
        panel = (sheet.width - 8) // 3 - 8 // 3
        xs = [8 + n * (panel + 8) + 2 for n in range(3)]
        cols = [sheet.getpixel((x, 8 + 2)) for x in xs]
        check(cols[0] == (0, 0, 0), 'первая панель не чёрная: %s' % (cols[0],))
        check(cols[1] == (255, 255, 255), 'вторая панель не белая: %s' % (cols[1],))
        check(cols[2] == (0x20, 0x40, 0x60), 'третья панель не цвета --bg: %s' % (cols[2],))


def test_model_without_install_names_the_command():
    with tempfile.TemporaryDirectory() as tmp:
        src = disc_picture(os.path.join(tmp, 'disc.png'))
        empty = os.path.join(tmp, 'no-node-modules')
        os.makedirs(empty)
        code, text = run('cutout.py', src, '-o', os.path.join(tmp, 'o.png'), '--model', env={'MOTION_NODE_MODULES': empty})
        check(code != 0, 'без общей установки команда не должна пройти')
        check('setup.py' in text and 'install' in text, 'ошибка не называет команду установки: %s' % text[-300:])
        check('Traceback' not in text, 'трассировка вместо строки')


def _model_missing():
    """Причина, по которой модель здесь не проверить, или None: нет пакета onnxruntime-node или нет весов."""
    sys.path.insert(0, str(ENGINE))
    import deps
    if not (deps.shared_node_modules() / 'onnxruntime-node' / 'package.json').exists():
        return 'нет onnxruntime-node в общей установке (ставится отдельно: npm install onnxruntime-node@1.21.1 --save-exact)'
    if not os.path.exists(os.path.join(os.path.expanduser('~'), '.cache', 'hyperframes', 'background-removal', 'models',
                                       'u2net_human_seg.onnx')):
        return 'нет весов u2net_human_seg (первый запуск `cutout.py --model` их скачает)'
    return None


NO_NET = """// проба: любая попытка сети из Node — запись в NONET_LOG и ошибка
const fs = require('fs'); const log = process.env.NONET_LOG;
const note = (w, a) => { fs.appendFileSync(log, w + ' ' + String(a) + '\\n'); throw new Error('сеть запрещена пробой: ' + w); };
globalThis.fetch = (u) => note('fetch', (u && u.url) || u);
for (const m of ['http', 'https']) { const x = require(m); x.request = (...a) => note(m + '.request', a[0]); x.get = x.request; }
require('net').connect = (...a) => note('net.connect', JSON.stringify(a[0]));
"""


def person_picture(path):
    """Нарисованная фигура человека на неровном фоне (пятна и размытие): голова, торс, руки, ноги."""
    import random
    from PIL import Image, ImageDraw, ImageFilter
    random.seed(3)
    im = Image.new('RGB', (640, 800), (100, 120, 90))
    d = ImageDraw.Draw(im)
    for _ in range(60):
        x, y, r = random.randrange(640), random.randrange(800), random.randrange(15, 70)
        d.ellipse((x - r, y - r, x + r, y + r), fill=tuple(random.randrange(60, 200) for _ in range(3)))
    im = im.filter(ImageFilter.GaussianBlur(3))
    d = ImageDraw.Draw(im)
    skin, cloth = (225, 176, 142), (40, 70, 150)
    d.ellipse((270, 120, 370, 240), fill=skin)
    d.ellipse((265, 100, 375, 170), fill=(70, 40, 25))
    d.rectangle((305, 235, 335, 275), fill=skin)
    d.rounded_rectangle((220, 270, 420, 560), radius=50, fill=cloth)
    d.rounded_rectangle((165, 280, 225, 520), radius=28, fill=cloth)
    d.rounded_rectangle((415, 280, 475, 520), radius=28, fill=cloth)
    d.rounded_rectangle((235, 555, 315, 780), radius=25, fill=(30, 30, 40))
    d.rounded_rectangle((325, 555, 405, 780), radius=25, fill=(30, 30, 40))
    im.save(path)
    return path


def test_model_cutout_runs_without_network_after_first_launch():
    """Вырезка моделью HyperFrames фигуры на неровном фоне: PNG с прозрачностью, торс остался, угол фона прозрачен, запас
    поля есть, и при запрещённой сети (проба в Node ловит любой запрос) запуск проходит. Нет пакета или весов — пропуск
    с названной причиной."""
    from PIL import Image
    why = _model_missing()
    if why:
        print('       (пропуск: %s)' % why)
        return
    with tempfile.TemporaryDirectory() as tmp:
        src, out, pre, log = (os.path.join(tmp, n) for n in ('p.png', 'o.png', 'nonet.cjs', 'nonet.log'))
        person_picture(src)
        with open(pre, 'w', encoding='utf-8') as fh:
            fh.write(NO_NET)
        code, text = run('cutout.py', src, '-o', out, '--model', '--margin', '0.1',
                         env={'NODE_OPTIONS': '--require ' + pre.replace('\\', '/'), 'NONET_LOG': log})
        check(code == 0, 'вырезка моделью не прошла: %s' % text[-500:])
        seen = open(log, encoding='utf-8').read()[:200] if os.path.exists(log) else ''
        check(not seen, 'запуск с весами в кэше полез в сеть: %s' % seen)
        res = Image.open(out)
        check(res.mode == 'RGBA', 'выход модели не RGBA')
        check(res.getpixel((2, 2))[3] == 0, 'угол поля не прозрачный')
        box = res.split()[3].point(lambda v: 255 if v > 8 else 0).getbbox()
        check(box and box[0] > 10 and box[1] > 10 and res.width - box[2] > 10 and res.height - box[3] > 10, 'нет поля вокруг фигуры: %s' % (box,))
        # торс исходника — прямоугольник (220, 270)–(420, 560); в вырезке он смещён на поле и рамку — берём точку в его середине
        cx, cy = (box[0] + box[2]) // 2, box[1] + int((box[3] - box[1]) * 0.5)
        check(res.getpixel((cx, cy))[3] == 255, 'в середине фигуры маска не плотная: %s' % (res.getpixel((cx, cy)),))


def test_picture_check_names_each_problem():
    with tempfile.TemporaryDirectory() as tmp:
        small = disc_picture(os.path.join(tmp, 'small.png'), size=(160, 120), diameter=60)
        code, text = run('picture_check.py', small, '--need', '800x600')
        check(code == 1 and 'маленьк' in text and '800' in text, 'маленькая картинка: код %s, текст %r' % (code, text[-200:]))
        edge = disc_picture(os.path.join(tmp, 'edge.png'), size=(800, 600), center=(400, 300), diameter=580)
        code, text = run('picture_check.py', edge, '--need', '800x600', '--margin', '0.08')
        check(code == 1 and 'поля' in text, 'картинка без поля: код %s, текст %r' % (code, text[-200:]))
        uneven = disc_picture(os.path.join(tmp, 'uneven.png'), size=(800, 600), diameter=120, gradient=True)
        code, text = run('picture_check.py', uneven, '--need', '800x600')
        check(code == 1 and 'фон' in text and 'ровн' in text, 'неровный фон: код %s, текст %r' % (code, text[-200:]))
        for out in (text,):
            check('попросить' in out or 'Попросить' in out, 'нет строки «что попросить заново»: %r' % out[-200:])


def test_picture_check_silent_on_good_picture():
    with tempfile.TemporaryDirectory() as tmp:
        good = disc_picture(os.path.join(tmp, 'good.png'), size=(1000, 800), diameter=400)
        code, text = run('picture_check.py', good, '--need', '800x600')
        check(code == 0 and text.strip() == '', 'годная картинка: код %s, текст %r' % (code, text))


def test_picture_check_alpha_required():
    from PIL import Image
    with tempfile.TemporaryDirectory() as tmp:
        flat = disc_picture(os.path.join(tmp, 'flat.png'), size=(1000, 800), diameter=400)
        code, text = run('picture_check.py', flat, '--need', '800x600', '--alpha')
        check(code == 1 and 'прозрач' in text, 'нет альфы, а просили: код %s, %r' % (code, text[-200:]))
        a = Image.new('RGBA', (1000, 800), (0, 0, 0, 0))
        a.paste(Image.new('RGBA', (400, 400), DISC + (255,)), (300, 200))
        ok = os.path.join(tmp, 'alpha.png')
        a.save(ok)
        code, text = run('picture_check.py', ok, '--need', '800x600', '--alpha')
        check(code == 0 and text.strip() == '', 'годный PNG с альфой: код %s, %r' % (code, text))


def _project(tmp, rows, files=('assets/a.png',)):
    for f in files:
        p = os.path.join(tmp, f)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, 'wb').write(b'x')
    os.makedirs(os.path.join(tmp, 'project'), exist_ok=True)
    with open(os.path.join(tmp, 'materials.json'), 'w', encoding='utf-8') as fh:
        json.dump(rows, fh, ensure_ascii=False)
    return tmp


def _row(**kw):
    row = {'file': 'assets/a.png', 'source': 'Poly Haven', 'license': 'CC0', 'author': '', 'url': 'https://polyhaven.com/x', 'note': ''}
    row.update(kw)
    return row


def test_check_materials_red_on_file_without_row():
    with tempfile.TemporaryDirectory() as tmp:
        _project(tmp, [], files=('assets/a.png', 'assets/sub/b.webp'))
        code, text = run('check_materials.py', '--project', tmp)
        check(code == 1 and 'assets/a.png' in text and 'assets/sub/b.webp' in text, 'нет строки у файла: %s %r' % (code, text[-300:]))


def test_check_materials_red_on_forbidden_license():
    for lic in ('CC BY-NC 4.0', 'Только для YouTube', 'CC-BY-NC-SA'):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp, [_row(license=lic)])
            code, text = run('check_materials.py', '--project', tmp)
            check(code == 1 and 'запрещ' in text, 'лицензия «%s» прошла: %s %r' % (lic, code, text[-200:]))


# названия, которые велит писать каталог скила (catalog/sources.md, «Как писать лицензию в materials.json»)
CATALOG_NAMES = ('Lottie Simple License', 'Pixabay Content License', 'Unsplash License', 'SIL OFL 1.1')
# запрещённое каталогом (catalog/sources.md, правило 3)
CATALOG_FORBIDDEN = ('CC BY-NC 4.0', 'CC BY-NC-SA 4.0', 'CC BY-ND 4.0', 'CC BY-SA 4.0', 'только для YouTube',
                     'личное использование', 'редакционное', 'все права защищены', 'RMBG-2.0')


def _catalog_name_is_green(lic):
    def test():
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp, [_row(license=lic)])
            code, text = run('check_materials.py', '--project', tmp)
            check(code == 0, 'название из каталога «%s» покраснело: %s' % (lic, text[-300:]))
    return test


for _lic in CATALOG_NAMES:
    globals()['test_check_materials_green_on_catalog_name_' + _lic.lower().replace(' ', '_').replace('.', '_')] = _catalog_name_is_green(_lic)


def test_check_materials_catalog_forbidden_stays_red():
    for lic in CATALOG_FORBIDDEN:
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp, [_row(license=lic)])
            code, text = run('check_materials.py', '--project', tmp)
            check(code == 1 and 'запрещ' in text, 'запрещённое каталогом «%s» не названо запрещённым: %s %r' % (lic, code, text[-200:]))


def test_check_materials_mixkit_needs_note():
    """Mixkit: условия у каждого файла свои — каталог велит записать их в note; без note строка красная."""
    for lic in ('mixkit', 'Mixkit License'):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp, [_row(source='Mixkit', license=lic, note='')])
            code, text = run('check_materials.py', '--project', tmp)
            check(code == 1 and 'note' in text, '«%s» без note прошёл: %s %r' % (lic, code, text[-200:]))
    with tempfile.TemporaryDirectory() as tmp:
        _project(tmp, [_row(source='Mixkit', license='Mixkit License', note='Mixkit Stock Video Free License: коммерция без подписи')])
        code, text = run('check_materials.py', '--project', tmp)
        check(code == 0, 'Mixkit с условиями в note покраснел: %s' % text[-300:])


def test_check_materials_green_on_listed_files():
    with tempfile.TemporaryDirectory() as tmp:
        rows = [_row(), ]
        _project(tmp, rows)
        code, text = run('check_materials.py', '--project', tmp)
        check(code == 0, 'строка с CC0 покраснела: %s' % text[-300:])
    with tempfile.TemporaryDirectory() as tmp:
        _project(tmp, [_row(license='CC BY 4.0', author='')])
        code, text = run('check_materials.py', '--project', tmp)
        check(code == 1 and 'автор' in text, 'CC BY без автора должна краснеть: %s %r' % (code, text[-200:]))


def test_check_materials_red_on_row_without_file_and_unknown_license():
    with tempfile.TemporaryDirectory() as tmp:
        _project(tmp, [_row(), _row(file='assets/ghost.png')])
        code, text = run('check_materials.py', '--project', tmp)
        check(code == 1 and 'ghost.png' in text, 'строка без файла прошла: %s %r' % (code, text[-200:]))
    with tempfile.TemporaryDirectory() as tmp:
        _project(tmp, [_row(license='проверить у файла')])
        code, text = run('check_materials.py', '--project', tmp)
        check(code == 1, 'непроверенная лицензия должна краснеть')


def test_check_materials_green_on_template_demo():
    code, text = run('check_materials.py')
    check(code == 0, 'демо шаблона: %s' % text[-400:])


def test_check_materials_green_on_fresh_project():
    """Свежий проект new_project.py (без фикстур и с ними): materials.json и файлы согласованы, проверка зелёная."""
    sys.path.insert(0, str(ROOT))
    import new_project
    for fixtures in (False, True):
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, 'p')
            new_project.create(target, 'Проба материалов', with_fixtures=fixtures)
            project = os.path.join(target, 'project')
            code, text = run('check_materials.py', '--project', project)
            check(code == 0, 'свежий проект (фикстуры: %s): %s' % (fixtures, text[-400:]))
            rows = json.load(open(os.path.join(project, 'materials.json'), encoding='utf-8'))
            have = os.path.isfile(os.path.join(project, 'assets', 'start-frame.png'))
            check((len(rows) == 1) == have, 'строка start-frame.png и файл не согласованы (файл: %s, строк: %d)' % (have, len(rows)))


if __name__ == '__main__':
    sys.exit(run_module(globals()))
