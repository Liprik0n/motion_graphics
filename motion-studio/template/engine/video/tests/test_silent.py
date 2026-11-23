# -*- coding: utf-8 -*-
"""Ролик без голоса: страница собирается без озвучки, время событий — шкала тактов, а не секунды.

    python engine/video/tests/test_silent.py     (≈ 1–2 мин: пять сборок страницы демо-фильма silent, под замком Chrome)

Ожидания — не из кода сборки: (1) в фильме silent нет ни одной озвученной реплики, голоса «none» нет в voices.json —
сборка не спрашивает о нём; (2) такт шкалы — 2,0 с (director/silent-timeline.json: 120 ударов в минуту, 4 доли), лид
ролика 0,6 с (project.json lead_sec): метка на такте 3 стоит на 0,6 + 2 × 2,0 = 4,6 с; шкалу растянули на четверть
(такт 2,5 с) — та же метка на 0,6 + 2 × 2,5 = 5,6 с, сцена не ломается; (3) сцена без единой строки шкалы — отказ с
подсказкой про немые строки.
Работает на копии project/ во временной папке; поставка не трогается.
"""
NEEDS_CHROME = True      # сборка страницы снимает промер DOM безголовым браузером: общий прогон берёт на него замок

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

VIDEO = Path(__file__).resolve().parents[1]
ENGINE = VIDEO.parent
TEMPLATE = ENGINE.parent
sys.path.insert(0, str(ENGINE / 'tests'))
from _util import PY, check, run_module   # noqa: E402

FILM = 'silent'
LEAD = 0.6            # project.json lead_sec: с начала ролика до первой строки
BAR = 2.0             # секунд в такте шкалы демо
FRAME = 1 / 30.0      # project.json fps = 30


def project(tmp):
    proj = Path(tmp) / 'project'
    shutil.copytree(TEMPLATE / 'project', proj, ignore=shutil.ignore_patterns('out', '.env', '__pycache__', 'music'))
    return proj


def build(proj):
    env = dict(os.environ)
    env.pop('MOTION_PROJECT', None)
    r = subprocess.run([PY, str(VIDEO / 'build.py'), FILM, '--page', '--project', str(proj)], capture_output=True,
                       text=True, encoding='utf-8', errors='replace', env=env)
    return r.returncode, r.stdout + r.stderr


def film_json(proj):
    return json.load(open(proj / 'out' / FILM / 'film.json', encoding='utf-8'))


def act_t(film, cue_id):
    return next(a['t'] for a in film['acts'] if a['id'] == cue_id)


def test_page_without_voice_and_voices_json():
    tmp = tempfile.mkdtemp(prefix='silent_')
    try:
        proj = project(tmp)
        voices = json.load(open(proj / 'voices.json', encoding='utf-8'))
        check('none' not in json.dumps(voices), 'в voices.json демо уже есть голос none — тест ничего не докажет')
        code, text = build(proj)
        check(code == 0, 'страница фильма без голоса не собралась: %s' % text[-600:])
        check('voices.json' not in text, 'сборка заговорила о voices.json у фильма без голоса: %s' % text[-400:])
        film = film_json(proj)
        reps = film['replies']
        check(len(reps) == 8 and all(r['silent'] for r in reps), 'ждали 8 немых строк шкалы, получили %s' % reps)
        check(abs(reps[0]['start'] - LEAD) < 1e-6 and abs((reps[1]['start'] - reps[0]['start']) - BAR) < 1e-6,
              'такты шкалы: строка 1 — на %.1f с, строка 2 — на такт позже; получили %.3f и %.3f' % (LEAD, reps[0]['start'], reps[1]['start']))
        check(abs(act_t(film, 'on3') - (LEAD + 2 * BAR)) < 1e-3,
              'метка на такте 3 стоит на %.2f с, ждали %.2f с (лид + два такта)' % (act_t(film, 'on3'), LEAD + 2 * BAR))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_event_follows_the_bar_not_the_second():
    tmp = tempfile.mkdtemp(prefix='silent_bar_')
    try:
        proj = project(tmp)
        tl = proj / 'director' / 'silent-timeline.json'
        rows = json.load(open(tl, encoding='utf-8'))
        for r in rows:                                   # шкала тактов растянута на четверть: такт 2,5 с
            r['ms'] = int(r['ms'] * 1.25)
            r['scene_start'] = r['scene_start'] * 1.25
        json.dump(rows, open(tl, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        code, text = build(proj)
        check(code == 0, 'страница на растянутой шкале не собралась: %s' % text[-600:])
        film = film_json(proj)
        want = LEAD + 2 * BAR * 1.25
        check(abs(act_t(film, 'on3') - want) < 2 * FRAME,
              'метка такта 3 осталась на секунде: %.3f с, при шкале ×1,25 ждали %.3f с' % (act_t(film, 'on3'), want))
        check(film['scenes'][0]['end'] - film['scenes'][0]['start'] > 8.0 * 1.25 - 1.0, 'сцена не растянулась вместе со шкалой')
        eighth = next(r['start'] for r in film['replies'] if r['num'] == 8)
        check(abs(act_t(film, 'up3') - eighth) < 2 * FRAME,
              'метка сцены silent-b не на такте 8: %.3f с вместо %.3f с' % (act_t(film, 'up3'), eighth))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_scene_without_timeline_rows_is_refused_with_hint():
    tmp = tempfile.mkdtemp(prefix='silent_rows_')
    try:
        proj = project(tmp)
        tl = proj / 'director' / 'silent-timeline.json'
        rows = [r for r in json.load(open(tl, encoding='utf-8')) if r['scene'] != 'silent-b']
        json.dump(rows, open(tl, 'w', encoding='utf-8'), ensure_ascii=False)
        code, text = build(proj)
        check(code != 0 and 'silent-b' in text and 'немые строки' in text,
              'у сцены нет строк шкалы: ждали отказ с именем сцены и подсказкой про немые строки, получили код %d: %s'
              % (code, text[-400:]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_film_keys_libs_and_stills():
    """libs — скрипт проекта в <head> страницы до разметки сцен; stills — кадры шва для промера (кадр до и после стыка)."""
    tmp = tempfile.mkdtemp(prefix='silent_libs_')
    try:
        proj = project(tmp)
        (proj / 'assets' / 'probe-lib.js').write_text('window.__LIB_LOADED = 1;', encoding='utf-8')
        fp = proj / 'films' / (FILM + '.json')
        film = json.load(open(fp, encoding='utf-8'))
        film.update(libs=['assets/probe-lib.js'], stills=True)
        json.dump(film, open(fp, 'w', encoding='utf-8'), ensure_ascii=False)
        code, text = build(proj)
        check(code == 0, 'страница с libs и stills не собралась: %s' % text[-500:])
        page = (proj / 'out' / FILM / 'index.html').read_text(encoding='utf-8')
        check('data-lib="assets/probe-lib.js"' in page and page.index('data-lib=') < page.index('silent-a--head'),
              'скрипт libs не стоит на странице до разметки сцен')
        seam = film_json(proj)['stills']['seams'][0]
        check((seam['from'], seam['to']) == ('silent-a', 'silent-b') and seam['b'] == seam['a'] + 1,
              'кадры шва в stills: ждали пару соседних кадров между silent-a и silent-b, получили %s' % seam)
        film['libs'] = ['assets/нет-такого.js']
        json.dump(film, open(fp, 'w', encoding='utf-8'), ensure_ascii=False)
        code, text = build(proj)
        check(code != 0 and 'libs' in text, 'нет файла libs — ждали отказ с именем ключа, получили код %d' % code)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(run_module(globals()))
