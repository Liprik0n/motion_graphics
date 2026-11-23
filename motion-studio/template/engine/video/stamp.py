# -*- coding: utf-8 -*-
"""Отметки кадров: при какой странице они отрендерены. Две ступени — кусок (фильм) и сцена.

    build.py <фильм>               кадры сцен <out>/<фильм>/frames/<сцена>/frame_%06d.png, у каждой сцены своя отметка
                                   frames/<сцена>/stamp.json; после полного рендера — отметка куска frames/stamp.json
    build.py <фильм> --draft       то же в черновой папке frames-draft/ (свой размер и частота кадров)
    assemble.py                    берёт кусок, только если отметка куска совпадает с нынешней страницей

Отметка куска — отпечаток всего, что рисует кадр: index.html (в нём разметка, стили, скрипты и данные фильма), film.json
и каждый файл assets/ страницы (шрифты, картинки, gsap). Пересборка страницы (`build.py --page`, общий прогон
проверок) кадры НЕ удаляет: страница собралась той же — отметка совпала, кадры годятся; страница изменилась —
отметка разошлась, склейка отказывает и называет команду перерендера. Так полный прогон проверок не стоит рендера
заново, а устаревший кусок в склейку не попадает (урок прошлого ролика: lessons.md скила, строка 52).

Отметка сцены — кэш рендера: правка одной сцены не перерендеривает остальные. Отпечаток сцены (scene_print) собран
из страницы: общая часть (всё, что не принадлежит ни одной сцене: стили, скрипты, каркас, шрифты, файлы assets/),
своя часть сцены (её <section>, заголовок и номер каркаса, её строка FILM.scenes, её реплики, элементы и рамки)
и свои части сцен, на которые она ссылается (move к чужому элементу, id чужой сцены строкой в разметке или
настройках плагина). Соседи по шву в отпечаток не входят: что изменившийся сосед делает с кадрами у шва, сборка
проверяет пересъёмкой окна шва (build.py) — scene_stale называет стороны, которые надо пересмотреть.

Число кадров не зависит от раскладки внутри frames/: frame_files и frames_on_disk видят и кадры сцен, и плоскую
последовательность frames/frame_%06d.png прежних версий и чужих кусков.
"""
import hashlib
import json
import os
import re

NAME = 'stamp.json'
FRAME_RE = re.compile(r'frame_(\d{6})\.png$')
FRAMES = 'frames'              # кадры финального размера и частоты (их берёт склейка)
DRAFT = 'frames-draft'         # кадры черновика (build.py --draft): свой размер и частота, в склейку не идут
FILM_HEAD, FILM_TAIL = '<script>window.__FILM__ = ', ';</script>'
SECTION_RE = re.compile(r'<section class="scene" id="scene--([^"]+)"')
FRAME_LINE_RE = re.compile(r'^<div class="fr fr-(?:title|num)" id="(?:title|num)--([^"]+)" data-scene="[^"\n]*".*$\n?', re.M)
DURATION_RE = re.compile(r'(<div id="root"[^>]*?data-duration=")[^"]*(")')
SCENE_KEYS = ('scenes', 'replies', 'elements', 'boxes', 'duration')     # ключи FILM, которые делятся по сценам
TIME_KEYS = ('t', 'until', 'from', 'to', 'at')     # ключи моментов (секунды фильма) в узлах сцены и настройках плагинов
SEAM_MIN, SEAM_MAX = 0.5, 2.0                      # окно шва, с: не короче и не длиннее (в пределах сцены)


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


def frame_files(out_dir, root=FRAMES):
    """Все кадры куска по порядку номеров — пути. Раскладка внутри папки кадров любая: frames/<сцена>/frame_%06d.png
    (кэш по сценам) и плоская frames/frame_%06d.png (прежние версии, чужие куски). Один номер дважды — отказ."""
    d = os.path.join(out_dir, root)
    found = {}
    if os.path.isdir(d):
        for base, dirs, files in os.walk(d):
            dirs.sort()
            for f in files:
                m = FRAME_RE.match(f)
                if not m:
                    continue
                k = int(m.group(1))
                if k in found:
                    raise SystemExit('кадр %s лежит дважды: %s и %s — папка кадров собрана из разных рендеров; '
                                     'перерендерь кусок (build.py <фильм> --png --force)' % (f, found[k], os.path.join(base, f)))
                found[k] = os.path.join(base, f)
    return [found[k] for k in sorted(found)]


def frame_runs(out_dir, root=FRAMES):
    """Кадры куска отрезками подряд в одной папке: [(папка, первый номер, число кадров)] — вход ffmpeg по шаблону
    frame_%06d.png. Плоская раскладка — один отрезок; кэш по сценам — по отрезку на сцену."""
    runs = []
    for p in frame_files(out_dir, root):
        d, k = os.path.dirname(p), int(FRAME_RE.match(os.path.basename(p)).group(1))
        if runs and runs[-1][0] == d and runs[-1][1] + runs[-1][2] == k:
            runs[-1][2] += 1
        else:
            runs.append([d, k, 1])
    return [tuple(r) for r in runs]


def frames_on_disk(out_dir, root=FRAMES):
    """Сколько кадров куска лежит на диске — при любой раскладке внутри папки кадров (frame_files)."""
    return len(frame_files(out_dir, root))


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


def frame_counts(out_dir):
    """Числа кадров куска одним местом: {on_disk — лежит на диске (frame_files), stamped — записано в отметке куска,
    full — сколько кадров в фильме по отметке}; отметки нет — stamped и full равны None."""
    st = read(out_dir) or {}
    return {'on_disk': frames_on_disk(out_dir), 'stamped': st.get('frames'), 'full': st.get('full')}


# ---------------------------------------------------------------- отметка сцены (кэш рендера)
_PARTS = {}          # разбор страницы: один на процесс и на состояние index.html


def _hash(*parts):
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode('utf-8') if isinstance(p, str) else p)
        h.update(b'\0')
    return h.hexdigest()


def _dump(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v)


def _times(obj):
    """Числа под ключами моментов (TIME_KEYS) на любой глубине."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in TIME_KEYS and isinstance(v, (int, float)) and not isinstance(v, bool):
                yield float(v)
            else:
                yield from _times(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _times(v)


def seam_window(scene, side):
    """Окно шва сцены, секунды фильма (t0, t1): 'prev' — от начала сцены до её первой реплики, 'next' — от конца
    последней реплики до конца сцены; не короче SEAM_MIN, не длиннее SEAM_MAX, в пределах сцены. В этих кадрах
    сосед законно виден (вход в паузе шва, уход, смена каркаса) — их и переснимают, когда сосед изменился."""
    a, b = float(scene['start']), float(scene['end'])
    if side == 'prev':
        return a, min(b, a + SEAM_MAX, max(float(scene.get('first', a)), a + SEAM_MIN))
    return max(a, b - SEAM_MAX, min(float(scene.get('last', b)), b - SEAM_MIN)), b


def _page_parts(out_dir):
    """Страница, разобранная на общую часть и части сцен: {order, common, self: {id: sha}, refs: {id: [id]}};
    страницы нет или в ней нет данных фильма — None."""
    idx = os.path.join(out_dir, 'index.html')
    if not os.path.exists(idx):
        return None
    st = os.stat(idx)
    key = (os.path.abspath(idx), st.st_mtime_ns, st.st_size)
    if _PARTS.get('key') == key:
        return _PARTS['val']
    with open(idx, encoding='utf-8') as fh:
        page = fh.read()
    a = page.find(FILM_HEAD)
    b = page.find(FILM_TAIL, a) if a >= 0 else -1
    if b < 0:
        return None
    try:
        film = json.loads(page[a + len(FILM_HEAD):b])
    except ValueError:
        return None
    scenes = film.get('scenes') or []
    order = [s['id'] for s in scenes]
    head, tail = page[:a], page[b:]
    html = {}
    marks = [(m.start(), m.group(1)) for m in SECTION_RE.finditer(head)]
    if marks:
        end = head.rfind('</section>')
        end = len(head) if end < marks[-1][0] else end + len('</section>')
        cuts = [p for p, _ in marks] + [end]
        for (p, sid), q in zip(marks, cuts[1:]):
            html[sid] = head[p:q]
        head = head[:marks[0][0]] + head[end:]
    lines = {}

    def take(m):
        lines.setdefault(m.group(1), []).append(m.group(0))
        return ''
    head = FRAME_LINE_RE.sub(take, head)            # заголовок и номер сцены в каркасе — её часть, не общая
    head = DURATION_RE.sub(r'\1\2', head, count=1)  # длина фильма — часть последней сцены (её end), не общая
    assets = (page_print(out_dir) or {}).get('assets_sha256', '')
    common = _hash(head, tail, _dump({k: v for k, v in film.items() if k not in SCENE_KEYS}), assets)
    own, data = {}, {}
    for i, s in enumerate(scenes):
        sid = s['id']
        data[sid] = {'scene': s, 'first_scene': i == 0, 'last_scene': i == len(scenes) - 1,
                     'replies': [r for r in film.get('replies') or [] if r.get('scene') == sid],
                     'elements': [e for e in film.get('elements') or [] if e.get('scene') == sid],
                     'boxes': {k: v for k, v in (film.get('boxes') or {}).items() if k.startswith(sid + '--')}}
        own[sid] = _hash(_dump(data[sid]), html.get(sid, ''), ''.join(lines.get(sid, [])))
    refs = {}
    for sid in order:
        strs = list(_strings(data[sid]))
        text = html.get(sid, '')
        refs[sid] = [x for x in order if x != sid and (
            any(s == x or s.startswith(x + '--') or s.startswith(x + ':') for s in strs)
            or re.search('([\'"])%s\\1' % re.escape(x), text))]
    # момент сцены, который падает в чужую сцену вне окна шва (бит по чужой реплике, метка плагина): та сцена
    # зависит от этой целиком — окно шва такого не увидит
    for i, a in enumerate(scenes):
        moments = set(_times(data[a['id']]['elements'])) | set(_times(a.get('plugins') or {}))
        for j, x in enumerate(scenes):
            if j == i or a['id'] in refs[x['id']]:
                continue
            inside = [t for t in moments if x['start'] <= t < x['end']]
            if j == i + 1:
                inside = [t for t in inside if t >= seam_window(x, 'prev')[1]]
            elif j == i - 1:
                inside = [t for t in inside if t < seam_window(x, 'next')[0]]
            if inside:
                refs[x['id']] = [s for s in order if s in refs[x['id']] or s == a['id']]
    val = {'order': order, 'common': common, 'self': own, 'refs': refs,
           'windows': {s['id']: {k: list(seam_window(s, k)) for k in ('prev', 'next')} for s in scenes}}
    _PARTS.update(key=key, val=val)
    return val


def scene_print(out_dir, scene_id):
    """Отпечаток сцены собранной страницы: {scene, sha256, common_sha256, self_sha256, refs: {id: sha}, prev, next, window}.

    sha256 — всё, от чего зависят кадры сцены вдали от швов: общая часть страницы, своя часть сцены и свои части
    сцен из refs (на них сцена ссылается: move к чужому элементу, id чужой сцены строкой в разметке или плагине).
    prev и next — {id, self_sha256} соседей по шву (None у края фильма): сосед из refs уже в sha256, остальных
    scene_stale отдаёт на пересмотр окна шва; window — {prev, next: [t0, t1]}, окна шва сцены в секундах фильма
    (seam_window). Нет страницы или сцены в ней — None."""
    parts = _page_parts(out_dir)
    if parts is None or scene_id not in parts['self']:
        return None
    order, i = parts['order'], parts['order'].index(scene_id)
    refs = {x: parts['self'][x] for x in parts['refs'][scene_id]}

    def side(k):
        return {'id': order[k], 'self_sha256': parts['self'][order[k]]} if 0 <= k < len(order) else None
    return {'scene': scene_id, 'common_sha256': parts['common'], 'self_sha256': parts['self'][scene_id], 'refs': refs,
            'sha256': _hash(parts['common'], parts['self'][scene_id], _dump(refs)),
            'prev': side(i - 1), 'next': side(i + 1), 'window': parts['windows'][scene_id]}


def scene_dir(out_dir, scene_id, root=FRAMES):
    return os.path.join(out_dir, root, scene_id)


def scene_frames(out_dir, scene_id, root=FRAMES):
    """Имена кадров сцены на диске по порядку."""
    d = scene_dir(out_dir, scene_id, root)
    return sorted(f for f in os.listdir(d) if FRAME_RE.match(f)) if os.path.isdir(d) else []


def scene_read(out_dir, scene_id, root=FRAMES):
    p = os.path.join(scene_dir(out_dir, scene_id, root), NAME)
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding='utf-8') as fh:
            return json.load(fh)
    except ValueError:
        return None


def scene_write(out_dir, scene_id, first, frames, mode, root=FRAMES, **extra):
    """Отметка сцены: отпечаток нынешней страницы, кадры first … first + frames − 1 (номера файлов), настройки
    захвата mode (частота, размер, версия движка — чужой режим кадры не берёт); extra — замер (мс на кадр и т. п.)."""
    st = dict(scene_print(out_dir, scene_id), first=int(first), frames=int(frames), mode=mode, **extra)
    p = os.path.join(scene_dir(out_dir, scene_id, root), NAME)
    with open(p + '.tmp', 'w', encoding='utf-8') as fh:
        json.dump(st, fh, ensure_ascii=False, indent=1)
    os.replace(p + '.tmp', p)          # запись атомарна: оборванный рендер отметку не оставляет
    return st


def scene_stale(out_dir, scene_id, first, frames, mode, root=FRAMES):
    """Годятся ли кадры сцены из кэша: (причины, стороны).

    причины не пусты — сцену надо рендерить заново (строки); причины пусты, стороны не пусты ('prev', 'next') —
    сцена та же, но изменился сосед по шву: кадры у этого шва надо пересмотреть (сборка переснимает окно шва и
    сравнивает); обе пусты — кадры годятся как есть."""
    st = scene_read(out_dir, scene_id, root)
    if st is None:
        return ['нет отметки %s/%s/%s (не рендерилась или рендер оборван)' % (root, scene_id, NAME)], []
    now = scene_print(out_dir, scene_id)
    if now is None:
        return ['нет собранной страницы или сцены в ней — сверить кадры не с чем'], []
    why = []
    if st.get('sha256') != now['sha256']:
        if st.get('common_sha256') != now['common_sha256']:
            why.append('изменилась общая часть страницы (стили, скрипты, каркас, шрифты, файлы assets/)')
        if st.get('self_sha256') != now['self_sha256']:
            why.append('изменилась сама сцена')
        was = st.get('refs') or {}
        for x in sorted(set(was) | set(now['refs'])):
            if was.get(x) != now['refs'].get(x):
                why.append('изменилась сцена %s, на которую она ссылается' % x)
        if not why:
            why.append('отпечаток сцены другой')
    if st.get('mode') != mode:
        why.append('кадры сняты с другими настройками захвата (%s, а нужно %s)' % (_dump(st.get('mode')), _dump(mode)))
    want = ['frame_%06d.png' % k for k in range(int(first), int(first) + int(frames))]
    if (st.get('first'), st.get('frames')) != (int(first), int(frames)):
        why.append('в отметке кадры с %s, %s шт., а сцена теперь — кадры с %d, %d шт.'
                   % (st.get('first'), st.get('frames'), first, frames))
    elif scene_frames(out_dir, scene_id, root) != want:
        why.append('кадров сцены на диске %d, а в отметке %d' % (len(scene_frames(out_dir, scene_id, root)), frames))
    if why:
        return why, []
    sides = [k for k in ('prev', 'next')
             if st.get(k) != now[k] and (now[k] or {}).get('id') not in now['refs']]
    return [], sides
