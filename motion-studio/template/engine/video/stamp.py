# -*- coding: utf-8 -*-
"""Отметка кадров куска: при какой странице они отрендерены.

    build.py <фильм> --png        кладёт кадры <out>/<фильм>/frames/frame_%06d.png и рядом frames/stamp.json
    assemble.py                    берёт кусок, только если отметка совпадает с нынешней страницей

Отметка — отпечаток всего, что рисует кадр: index.html (в нём разметка, стили, скрипты и данные фильма), film.json
и каждый файл assets/ страницы (шрифты, картинки, gsap). Пересборка страницы (`build.py --page`, общий прогон
проверок) кадры НЕ удаляет: страница собралась той же — отметка совпала, кадры годятся; страница изменилась —
отметка разошлась, склейка отказывает и называет команду перерендера. Так полный прогон проверок не стоит рендера
заново, а устаревший кусок в склейку не попадает (урок прошлого ролика: lessons.md скила, строка 52).
"""
import hashlib
import json
import os
import re

NAME = 'stamp.json'
FRAME_RE = re.compile(r'frame_\d{6}\.png$')


def _sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for block in iter(lambda: fh.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def page_print(out_dir):
    """Отпечаток собранной страницы: {index_sha256, film_json_sha256, assets_sha256}; нет страницы — None."""
    idx, fj = os.path.join(out_dir, 'index.html'), os.path.join(out_dir, 'film.json')
    if not (os.path.exists(idx) and os.path.exists(fj)):
        return None
    h = hashlib.sha256()
    adir = os.path.join(out_dir, 'assets')
    for base, dirs, files in os.walk(adir):
        dirs.sort()
        for f in sorted(files):
            p = os.path.join(base, f)
            h.update(os.path.relpath(p, adir).replace(os.sep, '/').encode('utf-8'))
            h.update(_sha(p).encode('ascii'))
    return {'index_sha256': _sha(idx), 'film_json_sha256': _sha(fj), 'assets_sha256': h.hexdigest()}


def frames_on_disk(out_dir):
    d = os.path.join(out_dir, 'frames')
    return len([f for f in os.listdir(d) if FRAME_RE.match(f)]) if os.path.isdir(d) else 0


def write(out_dir, frames, full, fps, canvas):
    """frames — сколько кадров отрендерено, full — сколько в фильме (frames < full — пробный кусок --frames)."""
    st = dict(page_print(out_dir), frames=int(frames), full=int(full), fps=fps, canvas=list(canvas))
    p = os.path.join(out_dir, 'frames', NAME)
    with open(p + '.tmp', 'w', encoding='utf-8') as fh:
        json.dump(st, fh, ensure_ascii=False, indent=1)
    os.replace(p + '.tmp', p)          # запись атомарна
    return st


def read(out_dir):
    p = os.path.join(out_dir, 'frames', NAME)
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding='utf-8') as fh:
            return json.load(fh)
    except ValueError:
        return None


def stale(out_dir):
    """[] — кадры годятся; иначе причины, по которым кусок надо перерендерить (строки)."""
    st = read(out_dir)
    if st is None:
        return ['у кадров нет отметки frames/%s — неизвестно, с какой страницы они сняты' % NAME]
    now = page_print(out_dir)
    if now is None:
        return ['нет собранной страницы (index.html, film.json) — сверить кадры не с чем']
    why = []
    for key, what in (('index_sha256', 'страница index.html'), ('film_json_sha256', 'film.json'),
                      ('assets_sha256', 'файлы assets/ (шрифты, картинки)')):
        if st.get(key) != now[key]:
            why.append('%s изменились после рендера кадров' % what)
    have = frames_on_disk(out_dir)
    if have != st.get('frames'):
        why.append('кадров на диске %d, а в отметке %s' % (have, st.get('frames')))
    return why
