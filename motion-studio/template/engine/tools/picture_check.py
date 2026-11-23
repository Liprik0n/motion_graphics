# -*- coding: utf-8 -*-
"""Что не так с принесённой картинкой предмета — до вырезки, пока можно попросить заново.

    python engine/tools/picture_check.py <файл> --need <Ш>x<В> [--margin 0.08] [--alpha]

Проверяет по списку картинок (`templates/picture-list.md`):
  1. размер — не меньше --need (просят вдвое больше и уменьшают, поэтому в списке стоит нужный размер, а не «как есть»);
  2. фон — ровный: четыре угла одного цвета и без текстуры (иначе вырезка по цвету даст рваный край; для сложного
     фона годится `cutout.py --model`);
  3. поле — предмет не ближе --margin × сторона картинки к краю (доля, по умолчанию 0,08); без поля движение
     (качание, дыхание) обрежет предмет;
  4. --alpha — картинка должна быть PNG с настоящей прозрачностью (углы прозрачны), а не «фон под прозрачность».
Годная картинка — молчание и код 0. Есть замечание — по строке на каждое: что не так и что попросить заново;
код 1. Картинку или её размер не прочитать — код 2.
"""
import argparse
import os
import re
import sys

sys.dont_write_bytecode = True
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))      # <проект>/engine
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deps  # noqa: E402

CORNER_SPREAD = 14      # углы фона различаются больше (по каналу) — градиент или виньетка
CORNER_NOISE = 10       # разброс внутри углового участка больше — текстура, узор, сильный шум
VISIBLE = 8             # альфа выше этого — предмет есть
BG_TOL = 28             # пиксель отличается от фона больше — это предмет
MIN_MARGIN = 0.08


def parse_need(text):
    m = re.fullmatch(r'\s*(\d+)\s*[xх×*]\s*(\d+)\s*', text)
    if not m:
        raise SystemExit('ОШИБКА: --need пишется как 800x600, получено «%s»' % text)
    return int(m.group(1)), int(m.group(2))


def _corner_patches(img, share=0.04):
    w, h = img.size
    pw, ph = max(2, int(w * share)), max(2, int(h * share))
    return [img.crop(b) for b in ((0, 0, pw, ph), (w - pw, 0, w, ph), (0, h - ph, pw, h), (w - pw, h - ph, w, h))]


def background_problem(img):
    """Строка про неровный фон или None. Смотрятся четыре угла: цвет и разброс пикселей внутри каждого."""
    from PIL import ImageStat
    rgb = img.convert('RGB')
    cols, noise = [], 0
    for p in _corner_patches(rgb):
        st = ImageStat.Stat(p)
        cols.append(st.mean)
        noise = max(noise, max(st.stddev))
    spread = max(max(c[i] for c in cols) - min(c[i] for c in cols) for i in range(3))
    if spread > CORNER_SPREAD:
        return 'фон неровный: углы разного цвета (разница %d) — градиент или виньетка' % spread
    if noise > CORNER_NOISE:
        return 'фон неровный: в углу текстура или узор (разброс %.0f)' % noise
    return None


def subject_box(img, alpha_mode):
    """Рамка предмета (x0, y0, x1, y1) или None, если предмета нет."""
    from PIL import Image, ImageChops, ImageFilter
    if alpha_mode:
        return img.convert('RGBA').split()[3].point(lambda v: 255 if v > VISIBLE else 0).getbbox()
    rgb = img.convert('RGB')
    cols = []
    from PIL import ImageStat
    for p in _corner_patches(rgb):
        cols.append(ImageStat.Stat(p).median[:3])
    bg = tuple(int(round(sorted(c[i] for c in cols)[1] / 2 + sorted(c[i] for c in cols)[2] / 2)) for i in range(3))
    diff = ImageChops.difference(rgb, Image.new('RGB', rgb.size, bg))
    mask = None
    for ch in diff.split():
        m = ch.point(lambda v: 255 if v > BG_TOL else 0)
        mask = m if mask is None else ImageChops.lighter(mask, m)
    mask = mask.filter(ImageFilter.MedianFilter(5))             # одиночный шум не считается предметом
    return mask.getbbox()


def has_real_alpha(img):
    """Есть ли у картинки прозрачность: канал альфы с прозрачными углами."""
    if img.mode not in ('RGBA', 'LA', 'PA') and 'transparency' not in img.info:
        return False
    a = img.convert('RGBA').split()[3]
    return all(p.getextrema()[0] < 255 for p in _corner_patches(a))


def check(path, need, margin=MIN_MARGIN, alpha=False):
    """Список замечаний — строк «что не так → что попросить»; пустой — картинка годная."""
    from PIL import Image
    img = Image.open(path)
    img.load()
    w, h = img.size
    nw, nh = need
    out = []
    if w < nw or h < nh:
        out.append('картинка маленькая: %d×%d, нужно не меньше %d×%d. Попросить заново: размер вдвое больше нужного (%d×%d), '
                   'тот же кадр' % (w, h, nw, nh, nw * 2, nh * 2))
    if alpha:
        if not has_real_alpha(img):
            out.append('нет прозрачности: пришла картинка без альфы или с непрозрачными углами. Попросить заново: PNG с настоящей '
                       'прозрачностью — или тот же предмет на ровном нейтральном фоне, вырежем сами (cutout.py)')
    else:
        bad = background_problem(img)
        if bad:
            out.append(bad + '. Попросить заново: ровный однотонный нейтральный фон без теней на нём, без градиента и текстуры '
                       '— или принять как есть и вырезать моделью (cutout.py --model)')
    box = subject_box(img, alpha)
    if box is None:
        out.append('предмета не видно: вся картинка — фон. Попросить заново: предмет в центре кадра')
    elif not (not alpha and background_problem(img)):
        sides = (('слева', box[0] / w), ('сверху', box[1] / h), ('справа', (w - box[2]) / w), ('снизу', (h - box[3]) / h))
        tight = ['%s %.0f %%' % (n, v * 100) for n, v in sides if v < margin]
        if tight:
            out.append('нет поля вокруг предмета: %s (нужно не меньше %.0f %% с каждой стороны). Попросить заново: предмет целиком, '
                       'по центру, с пустым полем не меньше %.0f %% кадра со всех сторон — под качание и рост' % (
                           ', '.join(tight), margin * 100, margin * 100))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description='Что не так с принесённой картинкой предмета.')
    ap.add_argument('file')
    ap.add_argument('--need', required=True, help='нужный размер, например 1200x1200')
    ap.add_argument('--margin', type=float, default=MIN_MARGIN, help='минимальное поле, доля стороны (0,08)')
    ap.add_argument('--alpha', action='store_true', help='нужна PNG с прозрачностью')
    a = ap.parse_args(argv)
    need = parse_need(a.need)
    try:
        problems = check(a.file, need, a.margin, a.alpha)
    except (OSError, ValueError) as e:
        print('ОШИБКА: картинка не читается (%s): %s' % (a.file, e), file=sys.stderr)
        return 2
    for p in problems:
        print('%s: %s' % (os.path.basename(a.file), p))
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(deps.run(main))
