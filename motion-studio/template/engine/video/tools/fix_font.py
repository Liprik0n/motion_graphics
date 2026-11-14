# -*- coding: utf-8 -*-
"""Шрифт для браузера: пересохранить TTF через fontTools и дописать недостающие коды cmap.

    python engine/video/tools/fix_font.py <исходный.ttf> <выход.ttf> [--cp1251]

Зачем (урок прошлого ролика): Chrome молча отвергает шрифт с кривыми
searchRange / rangeShift в каталоге таблиц и cmap (санитайзер OTS) — и страница рисуется запасным.
Пересохранение через fontTools пересчитывает эти поля. --cp1251: у старых шрифтов Ё, ё, № лежат в
слотах cp1251 (0xA8, 0xB8, 0xB9) — дописываем U+0401, U+0451, U+2116 на те же глифы.
Результат положить в проект и указать в tokens.json fonts; промер (probe.json fonts) обязан дать loaded.
"""
import sys

sys.stdout.reconfigure(encoding='utf-8')

CP1251_SLOTS = {0x0401: 0xA8, 0x0451: 0xB8, 0x2116: 0xB9}
NEED = 'АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯабвгдеёжзийклмнопрстуфхцчшщъыьэюя«»—–№'


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if len(args) != 2:
        raise SystemExit(__doc__)
    from fontTools.ttLib import TTFont
    src, dst = args
    f = TTFont(src)
    if '--cp1251' in sys.argv:
        best = f.getBestCmap()
        for t in f['cmap'].tables:
            if t.isUnicode():
                for uni, slot in CP1251_SLOTS.items():
                    if uni not in t.cmap and slot in best:
                        t.cmap[uni] = best[slot]
    f.save(dst)
    got = TTFont(dst).getBestCmap()
    missing = [c for c in NEED if ord(c) not in got]
    print('%s → %s; нет знаков: %s' % (src, dst, ''.join(missing) or 'нет'))
    if missing:
        sys.exit(1)


if __name__ == '__main__':
    main()
