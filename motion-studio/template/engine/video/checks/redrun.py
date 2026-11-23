# -*- coding: utf-8 -*-
"""Прогон порч и образцов — один на все файлы порч (red_demo, red_acts, red_bare, red_film, файл своего фильма).

Договор один:
    порча   (имя, порча(ctx, tmp), ожидание, …) — правит копию контекста проверки; засчитана, только если покраснела
            строка FAIL именно с ожидаемой подстрокой (ожидание — строка или функция ctx → строка; считается до порчи);
    образец (имя, правка(ctx, tmp)) — законный вариант на грани порога, обязан пройти молча;
    медленные — строки отчёта даёт файл порч (копия проекта, пересборка, новый промер), вердикт — здесь.
Перед порчами исходный фильм обязан быть зелёным (base). Файл порч держит списки, сами порчи и то, чем его фильм
особенный (вторая страница, виды медленных порч); цикл, вердикт и итоговые строки — только здесь.

Unfit — порчу или образец на этом фильме построить нельзя: проверка на нём слепа (сцена короче, чем нужно порогу
проекта). Порча с такой причиной — MISS: слепую проверку зелёной порчей не закрывают, порог ради порчи не меняют.
Образец — SKIP: «прошёл молча» там, где проверка и не могла покраснеть, ничего не доказывает.
"""
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # engine/video
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import check as C      # noqa: E402

WIDTH = 40             # ширина имени порчи в строке отчёта


class Unfit(Exception):
    """Порча или образец не строится на этом фильме: причина строкой (что слепо, длина сцены, порог)."""


def base(root, out_dir, label='Исходный фильм'):
    """Контекст страницы для порч; None (и строки провалов на экран) — исходный фильм красный, порчи бессмысленны.
    Порчи промера калиброваны на страницу: длина — film.json; видео мерит своя порча (page_only)."""
    ctx = C.make_ctx(root, out_dir, page_only=True)
    bad, lines = C.run(ctx, quiet=True)
    if bad:
        print('%s уже красный — порчи бессмысленны:\n' % label + '\n'.join(l for l in lines if l.startswith('FAIL')))
        return None
    return ctx


def expect_text(ctx, expect):
    return expect(ctx) if callable(expect) else expect


def verdict(name, lines, expect, width=WIDTH):
    """Покраснела ли своя строка: печатает RED или MISS, возвращает число промахов (0 | 1)."""
    hit = [l for l in lines if l.startswith('FAIL') and expect in l]
    if hit:
        print('RED  %-*s → %s' % (width, name, hit[0][5:]))
        return 0
    got = [l for l in lines if l.startswith('FAIL')] or ['(всё зелёное)']
    print('MISS %-*s ждали «%s», получили: %s' % (width, name, expect, ' | '.join(got)[:600]))
    return 1


def fast(rows, pick, filt=None, expect_of=expect_text, skip=None, width=WIDTH):
    """Быстрые порчи: rows — (имя, порча(ctx, tmp), ожидание, …); pick(row) → исходный контекст этой порчи;
    expect_of(ctx, ожидание) → подстрока; skip(row, исходный ctx) → причина пропуска или None. Код 0 | 1."""
    t0 = time.time()
    failed = n = 0
    for row in rows:
        name, fn, expect = row[:3]
        if filt and filt not in name:
            continue
        origin = pick(row)
        why = skip(row, origin) if skip else None
        if why:
            print('SKIP %-*s %s' % (width, name, why))
            continue
        n += 1
        ctx = C.fresh(origin)
        tmp = tempfile.mkdtemp(prefix='motion_red_')
        try:
            want = expect_of(ctx, expect)
            fn(ctx, tmp)
            _, lines = C.run(ctx, quiet=True)
        except Unfit as e:
            failed += 1
            print('MISS %-*s %s' % (width, name, e))
            continue
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        failed += verdict(name, lines, want, width)
    print('быстрые порчи: %d, не покраснело своей строкой: %d · %.0f с' % (n, failed, time.time() - t0))
    return 1 if failed else 0


def samples(rows, origin, filt=None, width=WIDTH):
    """Образцы: rows — (имя, правка(ctx, tmp)); origin — исходный контекст. Код 0 | 1."""
    failed = n = 0
    for name, fn in rows:
        if filt and filt not in name:
            continue
        ctx = C.fresh(origin)
        tmp = tempfile.mkdtemp(prefix='motion_smp_')
        try:
            fn(ctx, tmp)
            bad, lines = C.run(ctx, quiet=True)
        except Unfit as e:
            print('SKIP образец %-*s %s' % (width - 7, name, e))
            continue
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        n += 1
        if bad:
            failed += 1
            print('MISS образец «%s» покраснел: %s' % (name, ' | '.join(l for l in lines if l.startswith('FAIL'))[:600]))
        else:
            print('ok   образец %-*s — молча' % (width, name))
    print('образцы: %d, покраснело: %d' % (n, failed))
    return 1 if failed else 0


def slow(reds, smps, lines_of, expect_of, filt=None, skip=None, width=WIDTH):
    """Медленные порчи и образцы: lines_of(row) → строки отчёта проверки по порченой копии; expect_of(row) → подстрока
    строки FAIL у порчи, начало зелёной строки («OK   V29») у образца; skip(row) → причина пропуска или None."""
    t0 = time.time()
    failed = n = 0
    for row in reds:
        if filt and filt not in row[0]:
            continue
        why = skip(row) if skip else None
        if why:
            print('SKIP %-*s %s' % (width, row[0], why))
            continue
        n += 1
        failed += verdict(row[0], lines_of(row), expect_of(row), width)
    for row in smps:
        if filt and filt not in row[0]:
            continue
        why = skip(row) if skip else None
        if why:
            print('SKIP образец %-*s %s' % (width - 7, row[0], why))
            continue
        n += 1
        lines, expect = lines_of(row), expect_of(row)
        bad = [l for l in lines if l.startswith('FAIL')]
        if bad or not any(l.startswith(expect) for l in lines):
            failed += 1
            print('MISS образец «%s»: ждали «%s» и ни одного FAIL, получили: %s'
                  % (row[0], expect, ' | '.join(bad or [l for l in lines if expect.split()[-1] in l])[:600]))
        else:
            print('ok   образец %-*s — молча (%s)' % (width, row[0], expect.strip()))
    print('медленные порчи и образцы: %d, не так, как ждали: %d · %.0f с' % (n, failed, time.time() - t0))
    return 1 if failed else 0
