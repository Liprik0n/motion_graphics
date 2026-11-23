# -*- coding: utf-8 -*-
"""Вырезка предмета с ровного фона: PNG с прозрачностью, чистой кромкой и запасом поля под движение.

    python engine/tools/cutout.py <вход.png|jpg|webp> -o <выход.png> [--margin 0.15] [--tol 24] [--scale 1]
                                   [--model] [--sheet] [--bg "#3a6ea5"]

Обычный режим (PIL, без сети) — для картинки на ровном нейтральном фоне: так просят генерировать предметы
(`templates/picture-list.md`). Фон — цвет по четырём углам; фоном считаются пиксели, близкие к нему по всем каналам
(`--tol`) и связанные с краем листа. На кромке (3 px от фона) альфа — проекция цвета пикселя на прямую «фон → предмет»,
а цвет — обратное смешение с фоном (`C = a·F + (1 − a)·B`): предмет получает свой цвет, а не светлую кайму фона.
Дальше альфа сжимается на 1 px и растушёвывается на 0,6 px, цвет прозрачных пикселей ведётся к цвету предмета, чтобы
при масштабировании и сжатии видео не вылезал ореол. Образец — матовка открытки (`matte.py`), обобщённая с белого фона
на любой ровный.

--model — вместо цвета фона маску даёт `hyperframes remove-background` из общей установки (локальная модель
`u2net_human_seg`, на процессоре; ≈ 8 с на картинку 640×800, ≈ 340 МБ памяти). Нужны пакет onnxruntime-node 1.21.1
(`npm.cmd install onnxruntime-node@1.21.1 --save-exact` в общей папке `~/.motion-studio`; в набор шаблона он не входит,
и `npm ci` его уберёт) и веса (≈ 176 МБ, первый запуск скачивает их в `~/.cache/hyperframes/background-removal/models`;
дальше сети не нужно — проверено запретом сети в Node). Проверено на нарисованной фигуре на неровном фоне: фигура
вырезана, но с мусором — куски фона, похожие на человека, остались. Модель обучена на людях, предметы режет плохо: на
нарисованном яблоке с неровным фоном круг взят, а плодоножка и листок потеряны. Для предмета — ровный фон и вырезка по
цвету (без `--model`). Настоящее фото человека не пробовали. Нет общей установки — строка с командой.

--margin — запас поля вокруг предмета, доля большей стороны предмета (по умолчанию 0,15): вырезка обрезается по
предмету и обводится прозрачным полем, чтобы движение (качание, дыхание, рост) не упиралось в край. --scale — во
сколько раз уменьшить (или увеличить) результат; картинку просят вдвое больше нужного и уменьшают.
--sheet — контрольный лист рядом с результатом (`<выход>-sheet.png`): предмет на чёрном, белом и заданном `--bg`
фоне; ореол по кромке виден на чёрном, дыры — на белом.
"""
import argparse
import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))      # <проект>/engine
import deps  # noqa: E402

TOL = 24            # допуск цвета фона по каждому каналу (шум JPEG, лёгкий градиент)
EDGE = 3            # px: ширина кромки, где считается смесь с фоном
CHOKE = 1           # px: на сколько альфа сжата внутрь (против светлой каймы)
FEATHER = 0.6       # px: растушёвка альфы после сжатия
MIN_CONTRAST = 900  # |предмет − фон|²: меньше — предмет цветом сливается с фоном, смесь не разделить, альфа = 1
CORNER = 0.04       # доля стороны: угловой участок, по которому берётся цвет фона
VISIBLE = 8         # альфа выше этого — предмет есть (для рамки и поля)
HF_BIN_REL = ('hyperframes', 'bin', 'hyperframes.mjs')
MODEL_NAME = 'u2net_human_seg'


def parse_color(text):
    t = text.strip().lstrip('#')
    if len(t) == 3:
        t = ''.join(c * 2 for c in t)
    if len(t) != 6:
        raise SystemExit('ОШИБКА: цвет «%s» — нужен вид #rrggbb' % text)
    return tuple(int(t[i:i + 2], 16) for i in (0, 2, 4))


def background_color(img):
    """Цвет фона: медиана по четырём угловым участкам. Возвращает (цвет, разброс между углами по каналам)."""
    from PIL import ImageStat
    w, h = img.size
    pw, ph = max(2, int(w * CORNER)), max(2, int(h * CORNER))
    boxes = [(0, 0, pw, ph), (w - pw, 0, w, ph), (0, h - ph, pw, h), (w - pw, h - ph, w, h)]
    cols = [ImageStat.Stat(img.crop(b)).median[:3] for b in boxes]
    med = tuple(sum(sorted(c[i] for c in cols)[1:3]) / 2 for i in range(3))     # среднее двух средних из четырёх
    spread = max(max(c[i] for c in cols) - min(c[i] for c in cols) for i in range(3))
    return tuple(int(round(v)) for v in med), spread


def _near_bg(img, bg, tol):
    """L-маска: 255 там, где пиксель в пределах tol от цвета фона по каждому каналу."""
    from PIL import Image, ImageChops
    diff = ImageChops.difference(img.convert('RGB'), Image.new('RGB', img.size, bg))
    out = None
    for ch in diff.split():
        m = ch.point(lambda v: 255 if v <= tol else 0)
        out = m if out is None else ImageChops.darker(out, m)
    return out


def background_mask(img, tol=TOL, bg=None):
    """L-маска фона (255): пиксели цвета фона, связанные с краем листа. Связность считается на уменьшенной копии,
    затем маска уточняется до пикселя и прорастает в соседние пиксели цвета фона."""
    from collections import deque
    from PIL import Image, ImageChops, ImageFilter
    img = img.convert('RGB')
    w, h = img.size
    if bg is None:
        bg, _ = background_color(img)
    cand = _near_bg(img, bg, tol)
    f = max(1, math.ceil(max(w, h) / 600))
    sw, sh = max(1, w // f), max(1, h // f)
    small = cand.resize((sw, sh), Image.BOX).point(lambda v: 255 if v >= 250 else 0)
    sd = small.tobytes()
    seen = bytearray(sw * sh)
    q = deque()
    for x in range(sw):
        for y in (0, sh - 1):
            i = y * sw + x
            if sd[i] and not seen[i]:
                seen[i] = 1
                q.append(i)
    for y in range(sh):
        for x in (0, sw - 1):
            i = y * sw + x
            if sd[i] and not seen[i]:
                seen[i] = 1
                q.append(i)
    while q:
        i = q.popleft()
        y, x = divmod(i, sw)
        for j in ((i - 1) if x > 0 else -1, (i + 1) if x < sw - 1 else -1, (i - sw) if y > 0 else -1, (i + sw) if y < sh - 1 else -1):
            if j >= 0 and sd[j] and not seen[j]:
                seen[j] = 1
                q.append(j)
    comp = Image.frombytes('L', (sw, sh), bytes(255 if v else 0 for v in seen)).resize((w, h), Image.NEAREST)
    bgm = ImageChops.darker(comp, cand)
    for _ in range(f * 2 + 2):                              # прорастание в пиксели цвета фона у границ блоков
        bgm = ImageChops.lighter(bgm, ImageChops.darker(bgm.filter(ImageFilter.MaxFilter(3)), cand))
    return bgm


def _subject_color(rgb, core):
    """Цвет предмета у кромки: усреднение ближних пикселей ядра (далеких от фона) с растеканием по радиусам."""
    from PIL import Image, ImageChops, ImageFilter, ImageMath
    r, g, b = rgb.split()
    prem = [ImageChops.multiply(c, core) for c in (r, g, b)]
    est = None
    for rad in (16, 6, 2):
        den = core.filter(ImageFilter.GaussianBlur(rad))
        ok = den.point(lambda v: 255 if v >= 4 else 0)
        cur = [ImageMath.lambda_eval(lambda e: e['n'] * 255.0 / (e['d'] + (e['d'] == 0)),
                                     n=p.filter(ImageFilter.GaussianBlur(rad)).convert('F'), d=den.convert('F')).convert('L')
               for p in prem]
        est = cur if est is None else [Image.composite(c, o, ok) for c, o in zip(cur, est)]
    return est


def cutout(img, tol=TOL, bg=None):
    """RGB-исходник на ровном фоне → RGBA-вырезка того же размера (поле и обрезка — `add_margin`)."""
    from PIL import Image, ImageChops, ImageFilter
    img = img.convert('RGB')
    w, h = img.size
    if bg is None:
        bg, _ = background_color(img)
    mask = background_mask(img, tol, bg)
    near = mask.filter(ImageFilter.MaxFilter(2 * EDGE + 1))                 # фон и кромка вокруг него
    core = ImageChops.invert(mask.filter(ImageFilter.MaxFilter(2 * EDGE + 3)))
    est = _subject_color(img, core)
    r, g, b = (bytearray(c.tobytes()) for c in img.split())
    fr, fg, fb = (c.tobytes() for c in est)
    mk, nr = mask.tobytes(), near.tobytes()
    alpha = bytearray(b'\xff' * (w * h))
    for i, v in enumerate(nr):
        if not v:
            continue
        if mk[i]:
            alpha[i] = 0
            continue
        dr, dg, db = fr[i] - bg[0], fg[i] - bg[1], fb[i] - bg[2]
        dd = dr * dr + dg * dg + db * db
        if dd < MIN_CONTRAST:
            continue
        a = ((r[i] - bg[0]) * dr + (g[i] - bg[1]) * dg + (b[i] - bg[2]) * db) / dd
        a = min(1.0, max(0.0, a))
        if a < 0.03:
            alpha[i] = 0
            continue
        if a > 0.97:
            continue
        alpha[i] = round(a * 255)
        for ch, bc, fc in ((r, bg[0], fr[i]), (g, bg[1], fg[i]), (b, bg[2], fb[i])):
            un = (ch[i] - (1 - a) * bc) / a
            un = min(255.0, max(0.0, un))
            ch[i] = round(fc + (un - fc) * a * a)
    return _finish(Image.merge('RGB', [Image.frombytes('L', (w, h), bytes(c)) for c in (r, g, b)]),
                   Image.frombytes('L', (w, h), bytes(alpha)), est)


def _finish(rgb, alpha, est):
    """Сжатие и растушёвка альфы; цвет пикселей, где альфа не полная, — цвет предмета (est), если исходного нет."""
    from PIL import Image, ImageChops, ImageFilter
    a = alpha
    for _ in range(CHOKE):
        a = a.filter(ImageFilter.MinFilter(3))
    a = a.filter(ImageFilter.GaussianBlur(FEATHER))
    # где исходная альфа нулевая — цвета предмета нет, берём оценку; где частичная — смешанный цвет, он уже очищен
    zero = alpha.point(lambda v: 255 if v == 0 else 0)
    chans = [Image.composite(e, c, zero) for c, e in zip(rgb.split(), est)]
    return Image.merge('RGBA', chans + [a])


def refine_model(rgba):
    """Результат модели: альфа сжата и растушёвана, цвет полупрозрачной кромки — цвет ядра предмета."""
    from PIL import Image, ImageChops, ImageFilter
    rgba = rgba.convert('RGBA')
    rgb = Image.merge('RGB', rgba.split()[:3])
    alpha = rgba.split()[3]
    core = alpha.point(lambda v: 255 if v >= 250 else 0).filter(ImageFilter.MinFilter(2 * EDGE + 1))
    est = _subject_color(rgb, core)
    soft = alpha.point(lambda v: 255 if v < 250 else 0).filter(ImageFilter.MaxFilter(3))
    chans = [Image.composite(e, c, soft) for c, e in zip(rgb.split(), est)]
    a = alpha
    for _ in range(CHOKE):
        a = a.filter(ImageFilter.MinFilter(3))
    a = a.filter(ImageFilter.GaussianBlur(FEATHER))
    return Image.merge('RGBA', chans + [a])


def add_margin(rgba, margin=0.15):
    """Обрезать по предмету и обвести прозрачным полем margin × большая сторона предмета с каждой стороны."""
    from PIL import Image
    box = rgba.split()[3].point(lambda v: 255 if v > VISIBLE else 0).getbbox()
    if box is None:
        raise SystemExit('ОШИБКА: на картинке не нашлось предмета — вся она оказалась фоном. Проверь фон и --tol')
    sub = rgba.crop(box)
    pad = int(round(margin * max(sub.size)))
    out = Image.new('RGBA', (sub.width + 2 * pad, sub.height + 2 * pad), (0, 0, 0, 0))
    out.paste(sub, (pad, pad))
    return out


def sheet(rgba, bg, height=480):
    """Контрольный лист: предмет на чёрном, белом и заданном фоне — три панели в ряд."""
    from PIL import Image, ImageDraw
    k = height / rgba.height
    small = rgba.resize((max(1, round(rgba.width * k)), height), Image.LANCZOS)
    gap = 8
    panels = [((0, 0, 0), 'black'), ((255, 255, 255), 'white'), (bg, 'bg #%02x%02x%02x' % tuple(bg))]
    out = Image.new('RGB', (len(panels) * (small.width + gap) + gap, height + 2 * gap + 12), (128, 128, 128))
    d = ImageDraw.Draw(out)
    for n, (col, label) in enumerate(panels):
        x = gap + n * (small.width + gap)
        tile = Image.new('RGB', small.size, col)
        tile.paste(small, (0, 0), small)
        out.paste(tile, (x, gap))
        d.text((x, gap + height + 2), label, fill=(255, 255, 255))
    return out


def hyperframes_bin():
    """Путь к hyperframes из общей установки или SystemExit с командой установки."""
    nm = deps.shared_node_modules()
    exe = nm.joinpath(*HF_BIN_REL)
    if not exe.exists():
        raise SystemExit('ОШИБКА: нет общей установки HyperFrames (%s) — вырезка моделью без неё не идёт. '
                         'Поставь: %s' % (exe, deps.SETUP))
    return exe


def ffprobe_path(windows=None):
    """ffprobe для HyperFrames. Windows: заглушка шаблона (None, если её нет, — тогда HyperFrames ищет сам).
    Не Windows: заглушка-exe там не запустится — настоящий ffprobe из PATH (пакет ffmpeg системы), нет его — отказ.
    windows — признак платформы для теста; по умолчанию настоящая."""
    if (os.name == 'nt') if windows is None else windows:
        stub = os.path.join(os.path.dirname(deps.__file__), 'video', 'tools', 'ffprobe.exe')
        return stub if os.path.exists(stub) else None
    real = shutil.which('ffprobe')
    if not real:
        raise SystemExit('ОШИБКА: нет ffprobe в PATH: поставь ffmpeg пакетом системы (brew install ffmpeg / apt install ffmpeg)')
    return real


def run_model(src, dst):
    """`hyperframes remove-background src -o dst.png`; первый запуск скачивает веса модели, дальше сети нет."""
    exe = hyperframes_bin()
    env = dict(os.environ, HYPERFRAMES_NO_TELEMETRY='1', DO_NOT_TRACK='1', HYPERFRAMES_NO_UPDATE_CHECK='1',
               HYPERFRAMES_SKIP_SKILLS='1')                # NO_OPTIONAL_INSTALL не ставим: первый запуск докачивает onnxruntime-node
    # HyperFrames хочет ffmpeg и ffprobe: берём те же, что у сборки (ffmpeg из imageio-ffmpeg, заглушка ffprobe шаблона)
    try:
        import imageio_ffmpeg
        env.setdefault('HYPERFRAMES_FFMPEG_PATH', imageio_ffmpeg.get_ffmpeg_exe())
    except ImportError:
        pass
    probe = ffprobe_path()
    if probe:
        env.setdefault('HYPERFRAMES_FFPROBE_PATH', probe)
    node = shutil.which('node') or 'node'
    r = subprocess.run([node, str(exe), 'remove-background', str(src), '-o', str(dst)],
                       capture_output=True, text=True, encoding='utf-8', errors='replace', env=env)
    if r.returncode != 0 or not os.path.exists(dst):
        tail = (r.stdout + r.stderr).strip().splitlines()[-6:]
        hint = ''
        if 'onnxruntime' in ' '.join(tail):
            hint = ('\n  Первый запуск ставит onnxruntime-node (npm) и качает веса %s: сеть нужна один раз. '
                    'Поставить заранее: npm install onnxruntime-node в %s' % (MODEL_NAME, deps.shared_node_modules().parent))
        raise SystemExit('ОШИБКА: hyperframes remove-background не вырезал картинку (код %s):\n  %s%s'
                         % (r.returncode, '\n  '.join(tail), hint))


def process(src, dst, margin=0.15, tol=TOL, scale=1.0, model=False, sheet_bg=None, make_sheet=False):
    """Вырезать src → dst (PNG); вернуть путь листа или None."""
    from PIL import Image
    src, dst = str(src), str(dst)
    if model:
        with tempfile.TemporaryDirectory() as tmp:
            raw = os.path.join(tmp, 'model.png')
            run_model(src, raw)
            res = refine_model(Image.open(raw))
    else:
        res = cutout(Image.open(src), tol)
    res = add_margin(res, margin)
    if scale != 1:
        res = res.resize((max(1, round(res.width * scale)), max(1, round(res.height * scale))), Image.LANCZOS)
    os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
    res.save(dst)
    if not make_sheet:
        return None
    path = os.path.splitext(dst)[0] + '-sheet.png'
    sheet(res, sheet_bg or parse_color('#3a6ea5')).save(path)
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description='Вырезка предмета с ровного фона: PNG с альфой и запасом поля.')
    ap.add_argument('input', help='картинка предмета (png, jpg, webp)')
    ap.add_argument('-o', '--output', required=True, help='выходной PNG')
    ap.add_argument('--margin', type=float, default=0.15, help='поле вокруг предмета, доля его большей стороны (0,15)')
    ap.add_argument('--tol', type=int, default=TOL, help='допуск цвета фона по каналу (%d)' % TOL)
    ap.add_argument('--scale', type=float, default=1.0, help='масштаб результата (0,5 — уменьшить вдвое)')
    ap.add_argument('--model', action='store_true', help='вырезать моделью HyperFrames (люди, сложный фон)')
    ap.add_argument('--sheet', action='store_true', help='контрольный лист на чёрном, белом и --bg')
    ap.add_argument('--bg', default='#3a6ea5', help='фон третьей панели листа (#3a6ea5)')
    a = ap.parse_args(argv)
    if not os.path.exists(a.input):
        raise SystemExit('ОШИБКА: нет файла %s' % a.input)
    bgc = parse_color(a.bg)
    sheet_path = process(a.input, a.output, a.margin, a.tol, a.scale, a.model, bgc, a.sheet)
    print('вырезка → %s' % a.output)
    if sheet_path:
        print('контрольный лист → %s' % sheet_path)
    return 0


if __name__ == '__main__':
    sys.exit(deps.run(main))
