# -*- coding: utf-8 -*-
"""Проверки набора букв (engine/video/libs/card-kit.js, ключ фильма libs: ["card-kit"]) — V40–V43 для check.py.

    V40 v40_card_kit      частицы фразы начинают в своём предмете, окна-буквы с тенью, нырок в штрих буквы
    V41 v41_card_frames   кадры фильма (stills): кадр 0 по правилу фильма, швы, детерминизм
    V42 v42_beatsync      ключевые события меток — на долях трека (project.json beats)
    V43 v43_card_texts    текст фразы на экране дословно равен раскадровке

Ожидания — из раскадровок, tokens.json и файлов шрифтов, не из card-kit: его промер (плагин cardkit в probe.json,
CardKit.state) только сообщает, что нарисовано. Фильм без меток gather / windows / dive и без ключа stills эти
проверки пропускает (None). Порчи и образцы — checks/red_pen.py. Условия — строки CHECKS.md.
Модуль зовёт check.py (обёртки v40…v43): помощники контекста берутся у него.
"""
import math
import os
import sys

from check import (DET_PIX, FR, _rgb_cached, beat_t, canvas, cfg_need, fps, load_json, reply_of,  # noqa: F401
                   storyboards)

DIVE_SCALE = 0.1          # V40: соседние кадры нырка сравниваются в 1/10 размера (engine/tools/strip.py)


def dive_frames(ctx, t0, t1):
    """Кадры отрезка нырка [t0, t1) с частотой фильма — у инструмента полос (кэш полосы; замок Chrome берёт он сам).
    ctx['eye'] = False (порча на копии данных без страницы) — кадры не снимаются: None."""
    if ctx.get('eye') is False or t1 - t0 < 2.0 / fps(ctx):
        return None
    engine = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    for d in (engine, os.path.join(engine, 'tools')):
        if d not in sys.path:
            sys.path.append(d)
    import strip
    name = str(ctx['film']['film']).replace('\\', '/').split('/')[0]
    f = float(fps(ctx))
    return strip.frames(ctx['root'], name, round(t0 * f) / f, t1, f, DIVE_SCALE, page=ctx['out_dir'])


# ---------------------------------------------------------------- V40–V41 набор букв: частицы, окна, нырок, кадры
SRC_TOL_PX = 2.0          # V40: частица в рамке предмета-источника с допуском (дрожь выборки точек)
SHADOW_TOL = 0.02         # V40: непрозрачность тени окна против tokens card_windows.shadow_alpha
GEOM_TOL_PX = 1.0         # V40: смещение и размытие тени, база и кегль нырка против раскадровки и tokens
GLYPH_INK = 128           # V40: штрих буквы — альфа глифа (PIL, файл шрифта роли) ≥ порога в точке нырка
SEAM_MEAN = 0.02          # V41: шов — средняя разница яркости кадров N и N+1
SEAM_CELL = 0.08          # V41: шов — разница в любой клетке SEAM_GRID × SEAM_GRID
SEAM_GRID = 4


def _ck_items(smp, kind=None):
    for p in (smp or {}).get('plugins') or []:
        if p and p.get('plugin') == 'cardkit':
            return [it for it in p.get('items') or [] if kind is None or it.get('kind') == kind]
    return []


def _ck_cues(ctx):
    """[(сцена, раскадровка, метка)] — метки act сцен фильма."""
    out = []
    for s, sb in storyboards(ctx):
        for c in ((sb.get('plugins') or {}).get('act') or {}).get('cues') or []:
            out.append((s['id'], sb, c))
    return out


def _live_boxes(sb, W, H):
    out = {}
    for c in ((sb.get('plugins') or {}).get('act') or {}).get('cues') or []:
        for o in c.get('objects') or []:
            b = o['box']
            out[o['id']] = (b[0] * W, b[1] * H, b[2] * W, b[3] * H)
    return out


def _role_font_file(ctx, role):
    for f in list(ctx['tokens'].get('fonts') or []) + list(ctx['project'].get('fonts') or []):
        if f.get('role', 'brand') == role:
            files = f.get('files') or {}
            rel = files.get('700') or (list(files.values()) or [None])[0]
            if rel:        # как у сборки (config.asset): от корня проекта, иначе от движка, иначе шрифты движка
                video = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                for p in (os.path.join(ctx['root'], rel), os.path.join(video, rel),
                          os.path.join(video, 'assets', 'fonts', os.path.basename(rel))):
                    if os.path.exists(p):
                        return p
                return None
    return None


def _drift_at(ctx, scene, t):
    """Дрейф камеры сцены в t — из tokens.json motion.act.card_live (hann по длине сцены, 0 в швах), не из card-kit."""
    m = cfg_need(ctx, 'tokens', 'motion.act.card_live')
    sc = [s for s in ctx['film']['scenes'] if s['id'] == scene][0]
    W, H = canvas(ctx)
    p = min(1.0, max(0.0, (t - sc['start']) / max(1e-6, sc['end'] - sc['start'])))
    k = math.sin(math.pi * p) ** 2
    return 1 + float(m['drift_scale_pct']) / 100 * k, -float(m['drift_pan_pct_h']) / 100 * H * k


def _drift_pt(ctx, d, x, y):
    W, H = canvas(ctx)
    return (x - W / 2) * d[0] + W / 2, (y - H / 2) * d[0] + H / 2 + d[1]


_FONT_CACHE = {}


def _pil_font(path, px):
    from PIL import ImageFont
    key = (path, px)
    if key not in _FONT_CACHE:
        _FONT_CACHE[key] = ImageFont.truetype(path, px)
    return _FONT_CACHE[key]


def _line_layout(ctx, ln):
    """Строка раскадровки → (шрифт PIL, кегль px, левый край, база): кегль size_frac_w × W, база y × H, выравнивание
    align по ширине строки из файла шрифта роли. Ничего из card-kit."""
    W, H = canvas(ctx)
    fp = _role_font_file(ctx, ln.get('role'))
    if not fp:
        return None
    px = int(round(float(ln['size_frac_w']) * W))
    font = _pil_font(fp, px)
    width = font.getlength(ln['text'])
    x = float(ln['x']) * W
    left = x if ln.get('align') == 'left' else x - width if ln.get('align') == 'right' else x - width / 2
    return font, px, left, float(ln['y']) * H


def _word_mask(ctx, ln, word, size, drift):
    """Маска букв слова word строки ln (PIL, файл шрифта роли) в координатах кадра под дрейфом drift."""
    from PIL import Image, ImageDraw
    lay = _line_layout(ctx, ln)
    if not lay:
        return None
    font, px, left, base = lay
    i = ln['text'].index(word)
    wx = left + font.getlength(ln['text'][:i])
    im = Image.new('L', size, 0)
    ImageDraw.Draw(im).text((wx, base), word, font=font, fill=255, anchor='ls')
    if drift[0] != 1 or drift[1]:
        W, H = size
        s, dy = drift
        # кадр = (x − W/2)·s + W/2, (y − H/2)·s + H/2 + dy → обратное отображение для Image.transform
        a, c = 1 / s, W / 2 - (W / 2) / s
        e, f = 1 / s, H / 2 - (H / 2 + dy) / s
        im = im.transform(size, Image.AFFINE, (a, 0, c, 0, e, f), resample=Image.BILINEAR)
    return im.point(lambda v: 255 if v >= 128 else 0)


SHADOW_BAND_RATIO = 0.94   # V40: полоса под верхним краем прорези темнее полосы над нижним краем хотя бы на 6 %
SHADOW_BAND_FRAC = 1 / 3.0  # V40: глубина полосы — треть смещения тени (штрих буквы уже двух смещений)


def _shadow_pixels(ctx, img, mask, dy_px, edge_px):
    """(яркость полосы под верхним краем прорезей, яркость полосы над нижним краем) по кадру img и маске прорезей:
    маска сжимается на кромку, полоса — глубиной dy_px. Тень верхнего слоя падает вниз — верхняя полоса темнее."""
    from PIL import ImageChops, ImageFilter, ImageStat
    k = 2 * int(edge_px + 2) + 1
    inner = mask.filter(ImageFilter.MinFilter(k))
    b = max(2, int(round(dy_px)))
    down = ImageChops.offset(inner, 0, b)       # маска, сдвинутая вниз: пиксель p в ней ↔ p − b в inner
    up = ImageChops.offset(inner, 0, -b)
    top = ImageChops.subtract(inner, down)      # в прорези, но выше на b — уже не прорезь: у верхнего края
    bottom = ImageChops.subtract(inner, up)
    lum = img.convert('L')
    st, sb = ImageStat.Stat(lum, top), ImageStat.Stat(lum, bottom)
    if not st.count[0] or not sb.count[0]:
        return None
    return st.mean[0] / 255.0, sb.mean[0] / 255.0


SPENT_TOL = 0.001          # V40 SPENT: доля источника после spent / сборки при расходе — ноль; до emit_from — целиком
SPOUT_SIGMAS = 1.5         # V40: частица у излива — в пределах 1,5 × spout_jitter (3 σ) + SRC_TOL_PX
FLIGHT_DEV_FRAC_W = 0.1    # V40 FLIGHT: отклонение частицы в полёте от линии «источник → цель» не больше 0,1 W …
FLIGHT_DEV_SHARE = 0.10    # … у ≥ 90 % частиц в полёте
FLIGHT_MIN_N = 10          # V40 FLIGHT: кадр меряется, если в полёте ≥ 10 частиц выборки
FLIGHT_AT_BARS = (0.25, 0.5)   # V40 FLIGHT: кадры t сборки + ¼ и ½ такта
FLIGHT_AT_TOL = 0.26       # V40 FLIGHT: кадр промера не дальше полудоли от этих моментов
SHAPE_MASK_PAD_FRAC_W = 0.006   # V40 SMILEY: маска фигуры, расширенная на 0,006 W — вне неё крупинок нет
SHAPE_RING_COVER = 0.85    # V40 SMILEY: обод закрыт ≥ 85 % длины …
SHAPE_RING_GAP_FRAC_W = 0.03    # … зазор не больше 0,03 W
SHAPE_MIN_PART = 3         # V40 SMILEY: в каждом глазу и в улыбке — не меньше точек выборки
FORMED_TOL_FRAMES = 2      # V40 SMILEY: в formed ± 2 кадра
DIVE_ALPHA_MIN = 0.999     # V40 DIVE-THROUGH: альфа верха = 1 на всём нырке
DIVE_COVER_STEP = 0.25     # V40 DIVE-THROUGH: доля кадра под верхом за кадр падает не больше чем на 0,25 …
DIVE_COVER_TOL = 0.002     # … с cover_by — 0 (шум растра 1/10)
DIVE_COVER_GROW = 0.01     # … и не растёт больше чем на 0,01 за кадр (соседние окна-буквы уходят за край кадра — верх их закрывает)
DIVE_LUMA_STEP = 0.12      # V40 DIVE-THROUGH: средняя разница яркости соседних кадров нырка ≤ 12 %
DIVE_LOWER_TOL = 0.002     # V40 DIVE-THROUGH: низ в последнем кадре нырка — масштаб 1


def _cue_motion(ctx, c):
    return ((cfg_need(ctx, 'tokens', 'motion.act') or {}).get(c.get('motion')) or {})


def _cue_until(ctx, c):
    if c.get('until') is not None:
        return beat_t(ctx, c['until'])
    t = beat_t(ctx, c['t'])
    d = _cue_motion(ctx, c).get('dur')
    return None if t is None or d is None else t + float(d)


def _smiley_geom(to, W, H):
    """Смайлик метки fall (to: center — доли кадра, diameter_frac_w, ring/eyes/smile; _r — в радиусах, y вниз) → px сцены;
    толщины — верхние границы line_frac_w и size_r (маска фигуры)."""
    R = float(to['diameter_frac_w']) * W / 2
    g = {'x': float(to['center'][0]) * W, 'y': float(to['center'][1]) * H, 'r': R, 'ring': None, 'eyes': [], 'smile': None, 'eye_d': 0, 'smile_w': 0}
    if to.get('ring'):
        g['ring'] = float(to['ring']['line_frac_w'][1]) * W
    if to.get('eyes'):
        g['eyes'] = [(float(a[0]) * R, float(a[1]) * R) for a in to['eyes']['at_r']]
        g['eye_d'] = float(to['eyes']['size_r'][1]) * R
    if to.get('smile'):
        p = [(float(a[0]) * R, float(a[1]) * R) for a in to['smile']['through_r']]
        cx, cy = 2 * p[1][0] - (p[0][0] + p[2][0]) / 2, 2 * p[1][1] - (p[0][1] + p[2][1]) / 2
        g['smile'] = [((1 - t) ** 2 * p[0][0] + 2 * (1 - t) * t * cx + t * t * p[2][0],
                       (1 - t) ** 2 * p[0][1] + 2 * (1 - t) * t * cy + t * t * p[2][1]) for t in [k / 200.0 for k in range(201)]]
        g['smile_w'] = float(to['smile']['line_frac_w'][1]) * W
    ext = R + (g['ring'] or 0) / 2
    g['bbox'] = (g['x'] - ext, g['y'] - ext, g['x'] + ext, g['y'] + ext)
    return g


def _smiley_part(g, x, y, tol, s=1.0, cx=None, cy=None):
    """Часть смайлика g (под масштабом дрейфа s, центр в кадре cx, cy) с точкой (x, y): ring, eye-l, eye-r, smile или None."""
    dx, dy = (x - cx) / s, (y - cy) / s
    tol = tol / s
    if g['ring'] is not None and abs(math.hypot(dx, dy) - g['r']) <= g['ring'] / 2 + tol:
        return 'ring'
    for k, (ex, ey) in enumerate(g['eyes']):
        if math.hypot(dx - ex, dy - ey) <= g['eye_d'] / 2 + tol:
            return 'eye-r' if k else 'eye-l'
    if g['smile'] and min(math.hypot(dx - px, dy - py) for px, py in g['smile']) <= g['smile_w'] / 2 + tol:
        return 'smile'
    return None


def _smiley_verdict(ctx, g, pts, d, W):
    """(вне маски, доля обода закрыта, наибольший зазор px, части с недобором) для точек pts в кадре под дрейфом d."""
    cx, cy = _drift_pt(ctx, d, g['x'], g['y'])
    pad = SHAPE_MASK_PAD_FRAC_W * W
    parts = [_smiley_part(g, p[0], p[1], pad, d[0], cx, cy) for p in pts]
    outside = sum(1 for p in parts if not p)
    cover, gap = 1.0, 0.0
    if g['ring'] is not None:
        ang = sorted(math.atan2(p[1] - cy, p[0] - cx) for p, k in zip(pts, parts) if k == 'ring')
        if len(ang) < 2:
            cover, gap = 0.0, 2 * math.pi * g['r']
        else:
            gaps = [b - a for a, b in zip(ang, ang[1:])] + [ang[0] + 2 * math.pi - ang[-1]]
            thr = SHAPE_RING_GAP_FRAC_W * W / (g['r'] * d[0])
            cover = 1 - sum(x for x in gaps if x > thr) / (2 * math.pi)
            gap = max(gaps) * g['r'] * d[0]
    want = (['eye-l', 'eye-r'][:len(g['eyes'])]) + (['smile'] if g['smile'] else [])
    lack = [n for n in want if parts.count(n) < SHAPE_MIN_PART]
    return outside, cover, gap, lack


def _v40_gather_extra(ctx, sc, sb, c, recs, key):
    """SPENT, FLIGHT, излив, SMILEY — для метки gather сцены sc."""
    W, H = canvas(ctx)
    f = []
    m = _cue_motion(ctx, c)
    t0 = beat_t(ctx, c['t'])
    until = _cue_until(ctx, c)
    acts = {a['id']: a for a in c.get('sources_act') or [] if a.get('id')}
    # SPENT: spend 'all' — до emit_from источник целиком, после spent — пуст, просыпи with[] к spent ушли, после until пусто и без остатка
    if c.get('spend') == 'all' or c.get('consume') or m.get('consume'):
        if not any(until is not None and s['t'] >= until - 1e-6 for s, _ in recs):
            f.append('V40 card-kit %s: источник не израсходован — нет кадра промера после сборки (t ≥ %.2f с)' % (key, until or -1))
        early = late = spill = None
        for s, it in recs:
            left = it.get('source_left')
            if left is None:
                late = 'card-kit не отдал source_left (режим расхода не включён)'
                break
            sa = it.get('source_acts') or {}
            for n, a in acts.items():
                em, sp = beat_t(ctx, a['emit_from']) if a.get('emit_from') else None, beat_t(ctx, a['spent']) if a.get('spent') else None
                if em is not None and s['t'] < em - 1e-6 and left.get(n, 1) < 1 - SPENT_TOL and not early:
                    early = '%s: t=%.2f с, до emit_from %.2f с уже ушло %.0f %%' % (n, s['t'], em, (1 - left[n]) * 100)
                if sp is not None and s['t'] >= sp + 1e-6 and left.get(n, 0) > SPENT_TOL and not late:
                    late = '%s: t=%.2f с, после spent %.2f с осталось %.0f %%' % (n, s['t'], sp, left[n] * 100)
                for w in a.get('with') or []:
                    if sp is not None and s['t'] >= sp + 1e-6 and (sa.get(w) or {}).get('left', 1) > SPENT_TOL and not spill:
                        spill = '%s (просыпь %s): t=%.2f с, после spent осталось %.0f %%' % (w, n, s['t'], (sa.get(w) or {}).get('left', 1) * 100)
            if until is not None and s['t'] >= until - 1e-6:
                full = {n: v for n, v in left.items() if v > SPENT_TOL}
                if (full or it.get('rest')) and not late:
                    late = 't=%.2f с, после сборки осталось %s, крупинок остатка %d' % (
                        s['t'], ', '.join('%s %.0f %%' % (k, v * 100) for k, v in sorted(full.items())) or '—', len(it.get('rest') or []))
        if late:
            f.append('V40 card-kit %s: источник не израсходован (%s)' % (key, late))
        if early:
            f.append('V40 card-kit %s: вылет до emit_from (%s)' % (key, early))
        if spill:
            f.append('V40 card-kit %s: просыпь не ушла (%s)' % (key, spill))
    # излив: частицы предмета с spout начинают у точки излива
    objs = {o['id']: o for q in ((sb.get('plugins') or {}).get('act') or {}).get('cues') or [] for o in q.get('objects') or []}
    names = []
    for ln in c.get('lines') or []:
        for n in (ln.get('source') if isinstance(ln.get('source'), list) else [ln.get('source')]):
            if n in objs and n not in names:
                names.append(n)

    def spout_of(n):
        sp = (acts.get(n) or {}).get('spout') or objs[n].get('spout')
        if not sp:
            return None
        at = sp if isinstance(sp, list) else sp.get('at')
        return float(at[0]) * W, float(at[1]) * H
    spouts = [(n, spout_of(n)) for n in names if spout_of(n)]
    if spouts and recs:
        tol = SPOUT_SIGMAS * float(m.get('spout_jitter_frac_w') or 0) * W + SRC_TOL_PX
        plain = [tuple(v * (W if i % 2 == 0 else H) for i, v in enumerate(objs[n]['box'])) for n in names if not spout_of(n)]
        bad = [p for p in recs[0][1].get('origins') or []
               if not any(math.hypot(p[0] - x, p[1] - y) <= tol for _, (x, y) in spouts)
               and not any(r[0] - SRC_TOL_PX <= p[0] <= r[0] + r[2] + SRC_TOL_PX and r[1] - SRC_TOL_PX <= p[1] <= r[1] + r[3] + SRC_TOL_PX for r in plain)]
        if bad:
            f.append('V40 card-kit %s: поток не из излива — %d из %d частиц начинают дальше %.1f px от излива %s (первая %s)'
                     % (key, len(bad), len(recs[0][1].get('origins') or []), tol, ', '.join(n for n, _ in spouts), bad[0]))
    # FLIGHT: медиана размера частиц в полёте ≥ нижней границы flight_size_frac_w; от линии «источник → цель» дальше 0,1 W — ≤ 10 %
    fsz = m.get('flight_size_frac_w')
    if fsz is not None:
        need = float(fsz[0] if isinstance(fsz, list) else fsz) * W
        rep = reply_of(ctx, c['t']['reply']) if isinstance(c.get('t'), dict) else None
        bar = (rep['end'] - rep['start']) if rep else 0
        moments = [t0 + k * bar for k in FLIGHT_AT_BARS] if t0 is not None and bar else []
        for s, it in recs:
            fl = it.get('flight') or []
            if not any(abs(s['t'] - mt) <= FLIGHT_AT_TOL for mt in moments) or not (t0 < s['t'] < until) or len(fl) < FLIGHT_MIN_N:
                continue
            sizes = sorted(p[2] for p in fl)
            med = sizes[len(sizes) // 2]
            dev = 0
            for x, y, _sz, sx, sy, tx, ty in (p[:7] for p in fl):
                L2 = (tx - sx) ** 2 + (ty - sy) ** 2
                u = max(0.0, min(1.0, ((x - sx) * (tx - sx) + (y - sy) * (ty - sy)) / L2)) if L2 else 0.0
                if math.hypot(x - (sx + u * (tx - sx)), y - (sy + u * (ty - sy))) > FLIGHT_DEV_FRAC_W * W:
                    dev += 1
            if med < need - 0.05:
                f.append('V40 card-kit %s: полёт не читается (t=%.2f с) — медиана размера частиц в полёте %.1f px < %.1f px (flight_size_frac_w)'
                         % (key, s['t'], med, need))
                break
            if dev > FLIGHT_DEV_SHARE * len(fl):
                f.append('V40 card-kit %s: полёт не читается (t=%.2f с) — %d из %d частиц дальше %.0f px от линии «источник → цель»'
                         % (key, s['t'], dev, len(fl), FLIGHT_DEV_FRAC_W * W))
                break
    # SMILEY: метка fall с to — в formed все крупинки в маске, обод закрыт, фигура в кадре до readable_until, formed раньше нырка
    sc_rec = [x for x in ctx['film']['scenes'] if x['id'] == sc][0]
    dives = [beat_t(ctx, q['t']) for s2, _sb, q in _ck_cues(ctx) if s2 == sc and q.get('do') == 'dive']
    t_dive = min([sc_rec['end']] + [x for x in dives if x is not None])
    fps_ = fps(ctx)
    for s2, _sb, q in _ck_cues(ctx):
        to = q.get('to') if s2 == sc and q.get('do') == 'fall' and q.get('who') == c.get('who') else None
        if not to or to.get('shape', 'smiley') != 'smiley':
            continue
        fkey = '%s:%s' % (sc, q.get('id'))
        tf = beat_t(ctx, q['formed']) if q.get('formed') is not None else None
        if tf is None or tf >= t_dive - 1e-6:
            f.append('V40 card-kit %s: смайлик не сложился до нырка — formed %s, нырок %.2f с' % (fkey, '%.2f с' % tf if tf is not None else 'не задан', t_dive))
            continue
        g = _smiley_geom(to, W, H)
        sh = next((x for s, it in recs for x in it.get('shapes') or [] if x.get('word') == q.get('word') and x.get('formed')), None)
        if not sh:
            f.append('V40 card-kit %s: смайлик не сложился — в промере card-kit нет фигуры слова «%s» (осыпание без to)' % (fkey, q.get('word')))
            continue
        fr = sh['formed']
        if abs(float(fr['t']) - tf) > FORMED_TOL_FRAMES / float(fps_):
            f.append('V40 card-kit %s: смайлик не сложился к formed — card-kit сложил к %.3f с, а formed %.3f с' % (fkey, fr['t'], tf))
        out, cover, gap, lack = _smiley_verdict(ctx, g, fr['now'], _drift_at(ctx, sc, tf), W)
        if out or fr.get('outside') or cover < SHAPE_RING_COVER or gap > SHAPE_RING_GAP_FRAC_W * W + 1e-6 or lack:
            f.append('V40 card-kit %s: смайлик не сложился в formed (%.2f с) — вне маски %d из %d (card-kit: %d), обод закрыт %.0f %% (нужно ≥ %.0f %%), '
                     'зазор %.0f px (≤ %.0f)%s' % (fkey, tf, out, len(fr['now']), fr.get('outside') or 0, cover * 100, SHAPE_RING_COVER * 100, gap,
                                                   SHAPE_RING_GAP_FRAC_W * W, ('; пусто: ' + ', '.join(lack)) if lack else ''))
        t_read = min(t_dive, beat_t(ctx, q['readable_until'])) if q.get('readable_until') is not None else t_dive
        for s, it in recs:
            if not (tf <= s['t'] < t_read):
                continue
            d = _drift_at(ctx, sc, s['t'])
            x0, y0 = _drift_pt(ctx, d, g['bbox'][0], g['bbox'][1])
            x1, y1 = _drift_pt(ctx, d, g['bbox'][2], g['bbox'][3])
            if x0 < 0 or y0 < 0 or x1 > W or y1 > H:
                f.append('V40 card-kit %s: смайлик не сложился — фигура за краем кадра (t=%.2f с, рамка %.0f…%.0f × %.0f…%.0f)' % (fkey, s['t'], x0, x1, y0, y1))
                break
            shn = next((x for x in it.get('shapes') or [] if x.get('word') == q.get('word')), None)
            if shn and shn.get('now'):
                o2 = _smiley_verdict(ctx, g, shn['now'], d, W)[0]
                if o2:
                    f.append('V40 card-kit %s: смайлик не сложился — до readable_until крупинки ушли из маски (t=%.2f с, вне маски %d)' % (fkey, s['t'], o2))
                    break
    return f


def _hole_radius(im, px, py, ink, limit):
    """Радиус круга с центром (px, py), целиком лежащего в глифе im (альфа ≥ ink), px; поиск до limit."""
    pix = im.load()
    best = limit
    r = int(limit) + 1
    for yy in range(max(0, int(py) - r), min(im.height, int(py) + r + 1)):
        for xx in range(max(0, int(px) - r), min(im.width, int(px) + r + 1)):
            if pix[xx, yy] < ink:
                dd = math.hypot(xx + 0.5 - px, yy + 0.5 - py)
                if dd < best:
                    best = dd
    return max(0.0, best - 0.5)


def _v40_dive_extra(ctx, sc, c, recs, key, im, px, py, size_px):
    """DIVE-THROUGH: альфа верха = 1 на всём нырке; доля кадра под
    непрозрачным верхом (coverUpper, промер card-kit по кадрам) не растёт и за кадр падает ≤ 0,25, с cover_by до шва — 0; средняя
    разница яркости соседних кадров нырка (stills.every) ≤ 12 %; в cover_by и в последнем кадре круг окна в штрихе (глиф PIL минус
    полкромки card_windows) × масштаб верха ≥ расстояния до дальнего угла; низ в последнем кадре в масштабе 1."""
    m = _cue_motion(ctx, c)
    if m.get('mode') != 'through' and c.get('fade') != 'none' and not c.get('through') and not m.get('log_keys'):
        return []
    W, H = canvas(ctx)
    f = []
    t0 = beat_t(ctx, c['t'])
    for s, it in recs:
        if t0 is not None and s['t'] >= t0 - 1e-6 and float((it.get('upper') or {}).get('alpha', 1)) < DIVE_ALPHA_MIN:
            f.append('V40 card-kit %s: верх гаснет при нырке (t=%.2f с) — непрозрачность %.3f, а нырок насквозь' % (key, s['t'], it['upper']['alpha']))
            break
    s, it = recs[0]
    end = it.get('end')
    if not end:
        f.append('V40 card-kit %s: окно не заполнило кадр — card-kit не отдал последний кадр нырка (end)' % key)
        return f
    if float(end.get('alpha', 1)) < DIVE_ALPHA_MIN:
        f.append('V40 card-kit %s: верх гаснет при нырке (последний кадр, t=%.2f с) — непрозрачность %.3f' % (key, end['t'], end['alpha']))
    # coverUpper по кадрам
    tc = beat_t(ctx, c['cover_by']) if c.get('cover_by') is not None else None
    ser = it.get('cover_upper')
    if not ser:
        f.append('V40 card-kit %s: окно не заполнило кадр — card-kit не отдал coverUpper по кадрам нырка' % key)
    else:
        for (ta, a), (tb, b) in zip(ser, ser[1:]):
            if b > a + DIVE_COVER_GROW or a - b > DIVE_COVER_STEP:
                f.append('V40 card-kit %s: скачок в нырке (кадр %.3f → %.3f с) — доля кадра под верхом %.3f → %.3f (не растёт, за кадр ≤ −%.2f)'
                         % (key, ta, tb, a, b, DIVE_COVER_STEP))
                break
        if tc is not None:
            left = [(t, v) for t, v in ser if t >= tc - 1e-6 and v > DIVE_COVER_TOL]
            if left:
                f.append('V40 card-kit %s: окно не заполнило кадр с cover_by (%.2f с) — в %.3f с под верхом %.1f %% кадра' % (key, tc, left[0][0], left[0][1] * 100))
    # соседние кадры нырка по пикселям
    sc_rec = [x for x in ctx['film']['scenes'] if x['id'] == sc][0]
    paths = dive_frames(ctx, t0, sc_rec['end']) if t0 is not None else None
    if paths:
        from PIL import ImageChops, ImageStat
        k0 = int(round(t0 * fps(ctx)))
        for j, (pa, pb) in enumerate(zip(paths, paths[1:])):
            dlt = ImageStat.Stat(ImageChops.difference(_rgb_cached(pa).convert('L'), _rgb_cached(pb).convert('L'))).mean[0] / 255.0
            if dlt > DIVE_LUMA_STEP:
                f.append('V40 card-kit %s: скачок в нырке — кадры %d → %d: средняя разница яркости %.3f > %.2f'
                         % (key, k0 + j, k0 + j + 1, dlt, DIVE_LUMA_STEP))
                break
    edge = float(((cfg_need(ctx, 'tokens', 'motion.act') or {}).get('card_windows') or {}).get('edge_frac_w') or 0) * W
    r_in = _hole_radius(im, px, py, GLYPH_INK, size_px) - edge / 2
    frames = [('последнем кадре нырка', end)]
    if tc is not None:
        cov = it.get('cover')
        if not cov:
            f.append('V40 card-kit %s: окно не заполнило кадр — card-kit не отдал кадр накрытия (cover_by)' % key)
        else:
            frames.append(('кадре накрытия cover_by', cov))
    for what, fr in frames:
        ex, ey = fr['pivot']
        far = max(math.hypot(ex, ey), math.hypot(W - ex, ey), math.hypot(ex, H - ey), math.hypot(W - ex, H - ey))
        if r_in <= 0 or float(fr['scale']) * r_in < far:
            f.append('V40 card-kit %s: окно не заполнило кадр в %s (t=%.2f с) — круг окна %.1f px × масштаб %.1f = %.0f px, '
                     'а до дальнего угла %.0f px: камера не прошла букву насквозь'
                     % (key, what, fr['t'], r_in, float(fr['scale']), float(fr['scale']) * max(0, r_in), far))
    if abs(float(end.get('lower', 1)) - 1) > DIVE_LOWER_TOL:
        f.append('V40 card-kit %s: окно не заполнило кадр — низ в последнем кадре нырка в масштабе %.4f, а не 1 (кадр входа не совпадёт)'
                 % (key, end['lower']))
    return f


def v40_card_kit(ctx):
    """V40 card-kit: по промеру плагина cardkit (CardKit.state), кадрам
    промера и ожидаемым значениям из раскадровок, tokens.json и файлов шрифтов — не из card-kit:
      частицы — каждая частица фразы начинает в рамке предмета, названного в lines[].source (objects метки live), до
      начала сборки — тоже там; частицы до сборки и остаток в источнике нарисованы под дрейфом камеры card_live
      (hann по сцене) ± 2 px — там же, где мир рисует сам предмет;
      окна — по пикселям кадра с раскрытыми окнами (stills.windows): полоса под верхним краем прорезей темнее полосы над
      нижним краем (тень верхнего слоя падает внутрь); маска прорезей — буквы слова из файла шрифта роли на месте строки
      раскадровки под дрейфом; числа тени в промере = motion.act.card_windows;
      нырок — точка pivot лежит в штрихе буквы word[char]: начало буквы и база — из раскадровки и файла шрифта (PIL),
      глиф — оттуда же."""
    cues = [(sc, sb, c) for sc, sb, c in _ck_cues(ctx) if c.get('do') in ('gather', 'windows', 'dive')]
    if not cues:
        return None
    W, H = canvas(ctx)
    f = []
    samples = sorted(ctx['probe']['samples'], key=lambda s: s['t'])
    wm = (cfg_need(ctx, 'tokens', 'motion.act') or {}).get('card_windows') or {}
    st_wins = {(w['scene'], w['cue']): w for w in ((ctx.get('plugin_probe') or {}).get('stills') or {}).get('windows') or []}
    for sc, sb, c in cues:
        key = '%s:%s' % (sc, c.get('id'))
        recs = [(s, it) for s in samples for it in _ck_items(s) if it.get('scene') == sc and it.get('cue') == c.get('id')]
        if not recs:
            f.append('V40 card-kit %s: метки нет в промере card-kit (CardKit.state) — фраза не из card-kit' % key)
            continue
        gather = [g for sc2, sb2, g in _ck_cues(ctx) if sc2 == sc and g.get('do') == 'gather']
        lines = gather[0].get('lines') if gather else []
        if c['do'] == 'gather':
            boxes = _live_boxes(sb, W, H)
            names = []
            for ln in c.get('lines') or []:
                for n in (ln.get('source') if isinstance(ln.get('source'), list) else [ln.get('source')]):
                    if n not in names:
                        names.append(n)
            lost = [n for n in names if n not in boxes]
            if lost:
                f.append('V40 card-kit %s: источников %s нет в objects метки live' % (key, ', '.join(map(str, lost))))
                continue
            rects = [boxes[n] for n in names]
            # излив источника (sources_act[].spout, objects[].spout) — тоже предмет: горлышко может выходить за рамку банки
            sp_pts = []
            objs_ = {o['id']: o for q in ((sb.get('plugins') or {}).get('act') or {}).get('cues') or [] for o in q.get('objects') or []}
            acts_ = {a['id']: a for a in c.get('sources_act') or [] if a.get('id')}
            for n in names:
                sp = (acts_.get(n) or {}).get('spout') or (objs_.get(n) or {}).get('spout')
                if sp:
                    at = sp if isinstance(sp, list) else sp.get('at')
                    sp_pts.append((float(at[0]) * W, float(at[1]) * H))
            sp_tol = SPOUT_SIGMAS * float(_cue_motion(ctx, c).get('spout_jitter_frac_w') or 0) * W + SRC_TOL_PX

            def inside(x, y):
                return any(r[0] - SRC_TOL_PX <= x <= r[0] + r[2] + SRC_TOL_PX and r[1] - SRC_TOL_PX <= y <= r[1] + r[3] + SRC_TOL_PX
                           for r in rects) or any(math.hypot(x - sx, y - sy) <= sp_tol for sx, sy in sp_pts)
            s, it = recs[0]
            pts = it.get('origins') or []
            out = [p for p in pts if not inside(p[0], p[1])]
            if not pts:
                f.append('V40 card-kit %s: в промере нет начальных точек частиц' % key)
            elif out:
                f.append('V40 card-kit %s: частицы текста без источника — %d из %d начинают вне предметов %s (первая %s)'
                         % (key, len(out), len(pts), ', '.join(names), out[0]))
            t0 = beat_t(ctx, c['t'])
            sc_rec = [x for x in ctx['film']['scenes'] if x['id'] == sc][0]
            drift_bad = None
            for s2, it2 in recs:
                d = _drift_at(ctx, sc, s2['t'])
                pairs = []
                if s2['t'] < t0 - 1e-6:
                    pairs += [(o, n) for o, n in zip(it2.get('origins') or [], it2.get('now') or [])]
                if sc_rec['start'] <= s2['t'] < sc_rec['end']:
                    pairs += [((r[0], r[1]), (r[2], r[3])) for r in it2.get('rest') or []]
                for o, n in pairs:
                    if not inside(o[0], o[1]):
                        f.append('V40 card-kit %s: частицы текста без источника — до сборки (t=%.2f с) частица вне предметов %s'
                                 % (key, s2['t'], ', '.join(names)))
                        drift_bad = 'done'
                        break
                    ex, ey = _drift_pt(ctx, d, o[0], o[1])
                    if math.hypot(n[0] - ex, n[1] - ey) > SRC_TOL_PX + 0.5:
                        drift_bad = (s2['t'], o, n, (ex, ey))
                        break
                if drift_bad:
                    break
            if drift_bad and drift_bad != 'done':
                t, o, n, e = drift_bad
                f.append('V40 card-kit %s: частицы не на нарисованном предмете (t=%.2f с) — точка источника %s в кадре %s, а предмет под '
                         'дрейфом card_live там %s (> %.0f px)' % (key, t, list(o), list(n), [round(e[0], 1), round(e[1], 1)], SRC_TOL_PX))
            f += _v40_gather_extra(ctx, sc, sb, c, recs, key)
        elif c['do'] == 'windows':
            opened = [(s2, it2) for s2, it2 in recs if (it2.get('open') or 0) >= 0.99 and it2.get('drawn')]
            if not opened:
                f.append('V40 card-kit %s: нет кадра промера с открытыми окнами, нарисованного сценой' % key)
                continue
            want = {'color': wm.get('shadow_color'), 'alpha': wm.get('shadow_alpha'),
                    'dy': (wm.get('shadow_dy_frac_w') or 0) * W, 'blur': (wm.get('shadow_blur_frac_w') or 0) * W}
            for s2, it2 in opened:
                sh = it2.get('shadow')
                if not sh or not sh.get('alpha'):
                    f.append('V40 card-kit %s: окно без тени верхнего слоя (t=%.2f с) — в прорезях нет глубины' % (key, s2['t']))
                    break
                miss = []
                if sh.get('color') != want['color']:
                    miss.append('цвет %s ≠ %s' % (sh.get('color'), want['color']))
                if abs(float(sh['alpha']) - float(want['alpha'])) > SHADOW_TOL:
                    miss.append('непрозрачность %.3f ≠ %.3f' % (sh['alpha'], want['alpha']))
                for k in ('dy', 'blur'):
                    if abs(float(sh.get(k) or 0) - want[k]) > GEOM_TOL_PX:
                        miss.append('%s %.2f ≠ %.2f px' % (k, sh.get(k) or 0, want[k]))
                if miss:
                    f.append('V40 card-kit %s: тень окна не по tokens card_windows (t=%.2f с): %s' % (key, s2['t'], '; '.join(miss)))
                    break
            w = st_wins.get((sc, c.get('id')))
            ln = next((x for x in lines if c.get('word', '') in x['text']), None)
            if not w:
                f.append('V40 card-kit %s: нет кадра с раскрытыми окнами (stills.windows) — пересобери страницу' % key)
            elif ln:
                from PIL import Image
                img = Image.open(os.path.join(ctx['out_dir'], w['img'])).convert('RGB')
                mask = _word_mask(ctx, ln, c['word'], img.size, _drift_at(ctx, sc, w['t']))
                got = _shadow_pixels(ctx, img, mask, want['dy'] * SHADOW_BAND_FRAC, float(wm.get('edge_frac_w') or 0) * W) if mask else None
                if got is None:
                    f.append('V40 card-kit %s: прорези слова «%s» не нашлись по маске шрифта' % (key, c['word']))
                elif got[0] > got[1] * SHADOW_BAND_RATIO:
                    f.append('V40 card-kit %s: тень окна не нарисована (кадр %d): полоса под верхним краем прорезей %.3f, над нижним %.3f — '
                             'верх не темнее (нужно ≤ %.0f %%)' % (key, w['f'], got[0], got[1], SHADOW_BAND_RATIO * 100))
        else:
            s, it = recs[0]
            li = c.get('line')
            ln = lines[li] if isinstance(li, int) and li < len(lines) else next((x for x in lines if c.get('word', '') in x['text']), None)
            if not ln or c.get('word') not in ln['text'] or not isinstance(c.get('char'), int) or c['char'] >= len(c['word']):
                f.append('V40 card-kit %s: в раскадровке нет строки со словом «%s» и буквой №%s' % (key, c.get('word'), c.get('char')))
                continue
            ch = c['word'][c['char']]
            lay = _line_layout(ctx, ln)
            if not lay:
                f.append('V40 card-kit %s: нет файла шрифта роли %s — штрих не найти' % (key, ln.get('role')))
                continue
            font, px_, left, base = lay
            size_px = float(ln['size_frac_w']) * W
            if it.get('ch') != ch:
                f.append('V40 card-kit %s: нырок в «%s», а по раскадровке в «%s»' % (key, it.get('ch'), ch))
            if abs(float(it.get('size') or 0) - size_px) > GEOM_TOL_PX or abs(float(it.get('baseline') or 0) - base) > GEOM_TOL_PX:
                f.append('V40 card-kit %s: кегль или база нырка (%.1f, %.1f) ≠ раскадровке (%.1f, %.1f)'
                         % (key, it.get('size') or 0, it.get('baseline') or 0, size_px, base))
            from PIL import Image, ImageDraw
            ci = ln['text'].index(c['word']) + c['char']
            cx = left + font.getlength(ln['text'][:ci])          # начало буквы — из раскадровки и файла шрифта
            pad = int(size_px)
            ox, oy = int(cx) - pad, int(base) - int(size_px * 1.5)
            im = Image.new('L', (int(size_px * 2 + 2 * pad), int(size_px * 2 + 2 * pad)), 0)
            ImageDraw.Draw(im).text((cx - ox, base - oy), ch, font=font, fill=255, anchor='ls')
            px, py = float(it['pivot'][0]) - ox, float(it['pivot'][1]) - oy
            ink = im.getpixel((int(round(px)), int(round(py)))) if 0 <= px < im.width and 0 <= py < im.height else 0
            if ink < GLYPH_INK:
                f.append('V40 card-kit %s: точка нырка не в штрихе буквы «%s» — pivot %s, глиф там %d < %d'
                         % (key, ch, it['pivot'], ink, GLYPH_INK))
            f += _v40_dive_extra(ctx, sc, c, recs, key, im, px, py, size_px)
    return f


def _luma(im):
    return im.convert('L')


def v41_card_frames(ctx):
    """V41 кадры фильма (film.json stills, промер probe_frames.mjs):
      кадр 0 — если фильм объявил правило (films/<f>.json stills: {frame0: {lum: [от, до], sigma}}): средняя яркость
      в пределах lum, σ ≥ sigma (не пустой и не чёрный: превью ролика в мессенджере);
      шов — последний кадр сцены N и первый N+1: средняя разница яркости ≤ SEAM_MEAN и ни в одной клетке
      SEAM_GRID × SEAM_GRID > SEAM_CELL (кадр входа в окнах = первый кадр следующей сцены);
      детерминизм — кадр, снятый в первой загрузке и после перезагрузки в обратном порядке, совпадает попиксельно."""
    if not ctx['film'].get('stills'):
        return None
    pp = ctx.get('plugin_probe') or {}
    st = pp.get('stills')
    if not st:
        return ['V41 кадры фильма: нет промера кадров (plugin_probe.json stills) — пересобери страницу build.py --page']
    from PIL import Image, ImageChops, ImageStat
    f, od = [], ctx['out_dir']

    def img(rel):
        return Image.open(os.path.join(od, rel)).convert('RGB')
    rule = ctx['fdef'].get('stills')
    rule = rule.get('frame0') if isinstance(rule, dict) else None
    if rule and not st.get('frame0'):
        f.append('V41 кадр 0: не снят')
    elif rule:
        lo, hi = rule['lum']
        lum = _luma(img(st['frame0']))
        s = ImageStat.Stat(lum)
        mean, sd = s.mean[0] / 255.0, s.stddev[0] / 255.0
        if not (lo <= mean <= hi) or sd < float(rule['sigma']):
            f.append('V41 кадр 0 пуст: яркость %.3f (нужно %.2f…%.2f), σ %.3f (нужно ≥ %.2f) — превью ролика в мессенджере пустое'
                     % (mean, lo, hi, sd, float(rule['sigma'])))
    want = ctx['film']['stills'].get('seams') or []
    if len(st.get('seams') or []) != len(want):
        f.append('V41 шов: в промере %d пар кадров, а швов %d' % (len(st.get('seams') or []), len(want)))
    for sm in st.get('seams') or []:
        a, b = _luma(img(sm['a'])), _luma(img(sm['b']))
        d = ImageChops.difference(a, b)
        mean = ImageStat.Stat(d).mean[0] / 255.0
        w, h = d.size
        worst = (0.0, 0, 0)
        for gy in range(SEAM_GRID):
            for gx in range(SEAM_GRID):
                cell = d.crop((gx * w // SEAM_GRID, gy * h // SEAM_GRID, (gx + 1) * w // SEAM_GRID, (gy + 1) * h // SEAM_GRID))
                v = ImageStat.Stat(cell).mean[0] / 255.0
                if v > worst[0]:
                    worst = (v, gx + 1, gy + 1)
        if mean > SEAM_MEAN or worst[0] > SEAM_CELL:
            f.append('V41 шов %s → %s (кадры %d/%d): разница яркости %.3f (≤ %.2f), в клетке %d×%d (столбец %d, строка %d) %.3f (≤ %.2f) — '
                     'кадр входа не совпал с первым кадром сцены' % (sm['from'], sm['to'], sm['fa'], sm['fb'], mean, SEAM_MEAN,
                                                                    SEAM_GRID, SEAM_GRID, worst[1], worst[2], worst[0], SEAM_CELL))
    if (ctx['film']['stills'].get('det') or []) and not st.get('det'):
        f.append('V41 детерминизм: в промере нет кадров детерминизма')
    for d0 in st.get('det') or []:
        if not d0.get('b'):
            f.append('V41 детерминизм: у кадра %d нет второго промера' % d0['f'])
            continue
        diff = ImageChops.difference(img(d0['a']), img(d0['b'])).convert('L').point(lambda v: 255 if v else 0)
        n = diff.histogram()[255]
        if n > DET_PIX:
            f.append('V41 детерминизм: кадр %d (t=%.2f с) дважды снят по-разному — %d пикселей разошлись, область %s'
                     % (d0['f'], d0['t'], n, list(diff.getbbox() or [])))
    return f



BEAT_TOL_FRAMES = 2       # V42: ключевое событие на доле, остальное на сетке шестнадцатых — ± 2 кадра


def v43_card_texts(ctx):
    """V43 тексты фраз: строки, которые card-kit нарисовал (промер CardKit.state, text), —
    дословно lines[].text метки gather раскадровки, в том же порядке. Источник текста один — раскадровка."""
    cues = [(sc, c) for sc, sb, c in _ck_cues(ctx) if c.get('do') == 'gather' and c.get('lines')]
    if not cues:
        return None
    f = []
    for sc, c in cues:
        want = [ln['text'] for ln in c['lines']]
        seen = None
        for s in ctx['probe']['samples']:
            for it in _ck_items(s, 'phrase'):
                if it.get('scene') == sc and it.get('cue') == c.get('id'):
                    seen = it.get('text')
                    break
            if seen is not None:
                break
        if seen is None:
            f.append('V43 тексты %s:%s: фразы нет в промере card-kit' % (sc, c.get('id')))
        elif seen != want:
            f.append('V43 тексты %s:%s: на экране %s, а в раскадровке %s — текст фразы ≠ раскадровке (второй источник текста)'
                     % (sc, c.get('id'), seen, want))
    return f


def _film_beats(ctx):
    rel = ctx['project'].get('beats')
    if not rel:
        return None
    p = os.path.join(ctx['root'], rel)
    if not os.path.exists(p):
        return None
    b = load_json(p)
    s = float((b.get('segment') or {}).get('start', 0.0))
    return [x - s for x in b.get('beats') or [] if x >= s - 1e-9]


def v42_beatsync(ctx):
    """V42 BEATSYNC: метки act с key — на доле трека (project.json beats → файл {beats: [с], segment: {start}}, отрезок
    segment) ± 2 кадра: phrase и title — по until, остальные — по t; все метки (t и until) — на сетке шестнадцатых
    между долями ± 2 кадра. Секунды — из раскадровки через шкалу фильма (beat_t), не из card-kit."""
    beats = _film_beats(ctx)
    cues = [(sc, c) for sc, sb, c in _ck_cues(ctx)]
    if beats is None or len(beats) < 2 or not cues:
        return None
    F, tol = FR(ctx), BEAT_TOL_FRAMES * FR(ctx) + 1e-6
    grid = []
    for a, b in zip(beats, beats[1:]):
        grid += [a + (b - a) * k / 4.0 for k in range(4)]
    grid.append(beats[-1])
    p0, p1 = beats[1] - beats[0], beats[-1] - beats[-2]     # затакт до первой доли и хвост — сетка тем же шагом
    k = 1
    while beats[0] - p0 * k / 4.0 >= -p0:
        grid.append(beats[0] - p0 * k / 4.0)
        k += 1
    dur = ctx['film']['duration']
    k = 1
    while beats[-1] + p1 * k / 4.0 <= dur + p1:
        grid.append(beats[-1] + p1 * k / 4.0)
        k += 1
    beats = beats + [beats[0] - p0 * k for k in (1, 2)] + [beats[-1] + p1 * k for k in (1, 2)]

    def near(t, pts):
        return min(abs(t - p) for p in pts)
    f = []
    for sc, c in cues:
        key = '%s:%s' % (sc, c.get('id'))
        moments = [('t', c.get('t'))] + ([('until', c['until'])] if isinstance(c.get('until'), dict) else [])
        for name, m in moments:
            if not isinstance(m, dict):
                continue
            t = beat_t(ctx, m)
            if t is None:
                continue
            if near(t, grid) > tol:
                f.append('V42 BEATSYNC %s: %s=%.3f с не на сетке шестнадцатых (ближе %.0f мс)' % (key, name, t, near(t, grid) * 1000))
        k = c.get('key')
        if k:
            which = 'until' if k in ('phrase', 'title') else 't'
            m = c.get(which)
            t = beat_t(ctx, m) if isinstance(m, dict) else None
            if t is None:
                f.append('V42 BEATSYNC %s: у ключевой метки %s нет момента %s' % (key, k, which))
            elif near(t, beats) > tol:
                f.append('V42 BEATSYNC %s: ключевое событие %s (%s=%.3f с) не на доле трека — ближайшая доля в %.0f мс'
                         % (key, k, which, t, near(t, beats) * 1000))
    return f
