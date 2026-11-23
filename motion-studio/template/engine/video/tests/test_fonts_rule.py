# -*- coding: utf-8 -*-
"""«Шрифт загружен» — одно правило по начертанию на весь движок: engine/video/lib/fonts.js (window.StageFonts).

    python engine/video/tests/test_fonts_rule.py        (секунды, без браузера: правило исполняет node на подставном
                                                        document.fonts)

Общий ответ страницы document.fonts.status — «loaded», пока ни один шрифт не грузится: в том числе до того, как
браузер начал грузить начертание, которого ещё нет. Геометрия букв, запомненная в этот момент, — геометрия запасного
шрифта. Поэтому правило смотрит само начертание (@font-face: семейство и вес) и его состояние:
  StageFonts.face(семейство, вес) — у страницы есть такое начертание в состоянии loaded;
  StageFonts.all() — каждое объявленное начертание пришло (loaded) или отвергнуто (error); ждёт загрузки — нет.
Ожидания ниже — из этого описания и состояний FontFace по стандарту CSS Font Loading (unloaded, loading, loaded,
error), не из кода. Четыре места, где движок спрашивает о шрифте (lib/stage.js, styles/_core/core.js, plugins/pen.js,
libs/card-kit.js), обязаны звать правило, а не держать своё.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

VIDEO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(VIDEO.parent / 'tests'))
from _util import check, run_module   # noqa: E402

RULE = VIDEO / 'lib' / 'fonts.js'
USERS = [VIDEO / 'lib' / 'stage.js', VIDEO / 'styles' / '_core' / 'core.js', VIDEO / 'plugins' / 'pen.js', VIDEO / 'libs' / 'card-kit.js']
OWN_RULE = re.compile(r'document\.fonts\.(status|forEach)\b')

# подставная страница: node исполняет файл правила и отвечает на вопросы о наборах начертаний
DRIVER = r'''
const fs = require('fs');
const code = fs.readFileSync(process.argv[1], 'utf8');
const cases = JSON.parse(process.argv[2]);
const out = [];
for (const c of cases) {
  const faces = c.faces.map(([family, weight, status]) => ({ family, weight: String(weight), style: 'normal', status }));
  const win = {};
  const doc = c.faces === null ? {} : { fonts: { status: c.status, forEach: (fn) => faces.forEach(fn), check: () => true } };
  new Function('window', 'document', code)(win, doc);
  out.push({ all: win.StageFonts.all(), face: c.ask ? win.StageFonts.face(c.ask[0], c.ask[1]) : null });
}
console.log(JSON.stringify(out));
'''


def _ask(cases):
    check(RULE.exists(), 'нет файла правила %s' % RULE)
    r = subprocess.run(['node', '-e', DRIVER, str(RULE), json.dumps(cases)], capture_output=True, text=True, encoding='utf-8',
                       errors='replace', timeout=60)
    check(r.returncode == 0, 'правило не исполнилось в node: %s' % (r.stdout + r.stderr)[-600:])
    return json.loads(r.stdout)


def test_face_is_loaded_only_when_its_own_face_is_loaded():
    got = _ask([
        # общий ответ «loaded», а начертание ещё не начинало грузиться — это и есть ложь общего ответа
        {'status': 'loaded', 'faces': [['Brand', 400, 'loaded'], ['Brand', 700, 'unloaded']], 'ask': ['Brand', 700]},
        {'status': 'loading', 'faces': [['Brand', 400, 'loaded'], ['Brand', 700, 'loading']], 'ask': ['Brand', 700]},
        {'status': 'loaded', 'faces': [['Brand', 400, 'loaded'], ['Brand', 700, 'loaded']], 'ask': ['Brand', 700]},
        {'status': 'loaded', 'faces': [['"Brand"', 700, 'loaded']], 'ask': ['Brand', 700]},          # имя в кавычках — то же семейство
        {'status': 'loaded', 'faces': [['Brand', 400, 'loaded']], 'ask': ['Brand', 700]},            # другой вес — другое начертание
        {'status': 'loaded', 'faces': [['Brand', 400, 'loaded']], 'ask': ['Brand', None]},           # вес не назван — любое начертание семейства
        {'status': 'loaded', 'faces': [['Other', 700, 'loaded']], 'ask': ['Brand', 700]},
    ])
    want = [False, False, True, True, False, True, False]
    check([g['face'] for g in got] == want, 'StageFonts.face: ждали %s, получили %s' % (want, [g['face'] for g in got]))


def test_all_waits_for_every_declared_face():
    got = _ask([
        {'status': 'loaded', 'faces': [['Brand', 400, 'loaded'], ['Brand', 700, 'unloaded']]},      # общий ответ врёт: 700 ещё нет
        {'status': 'loading', 'faces': [['Brand', 400, 'loaded'], ['Digits', 700, 'loading']]},
        {'status': 'loaded', 'faces': [['Brand', 400, 'loaded'], ['Digits', 700, 'loaded']]},
        {'status': 'loaded', 'faces': [['Brand', 400, 'loaded'], ['Broken', 700, 'error']]},         # отвергнутый файл не ждут вечно
        {'status': 'loaded', 'faces': [['Brand', 700, 'unloaded'], ['Brand', 700, 'loaded']]},       # одно начертание объявлено дважды
        {'status': 'loaded', 'faces': []},                                                             # шрифтов у страницы нет
    ])
    want = [False, False, True, True, True, True]
    check([g['all'] for g in got] == want, 'StageFonts.all: ждали %s, получили %s' % (want, [g['all'] for g in got]))


def test_engine_asks_the_one_rule():
    for p in USERS:
        text = p.read_text(encoding='utf-8')
        own = OWN_RULE.findall(text)
        check(not own, '%s держит своё правило «шрифт загружен» (document.fonts.%s) — одно правило в lib/fonts.js' % (p.name, ', '.join(sorted(set(own)))))
        check('StageFonts.' in text, '%s не спрашивает правило StageFonts (lib/fonts.js)' % p.name)


if __name__ == '__main__':
    sys.exit(run_module(globals()))
