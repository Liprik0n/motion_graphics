# -*- coding: utf-8 -*-
"""Тесты швов проекта: один корень и один `out`, манифест озвучки → фильм, громкость голоса,
обязательные ключи конфигов, px_per_in, порчи при переименованных голосах.

    python engine/video/tests/test_project.py [--tmp ПАПКА] [--skip-red]

Каждый тест работает на копии `project/` во временной папке; поставка не трогается.
Сеть не открывается: озвучка — провайдер `fake` (синус), сборка — только `--page`.
Нужен engine/video/node_modules (проект из new_project.py его кладёт).
Ожидаемые значения — из спецификации конфигов (поля конфигов, правило корня), а не из кода.
"""
NEEDS_CHROME = True      # тест запускает безголовый браузер: общий прогон берёт на него замок и не зовёт в --quick

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
sys.dont_write_bytecode = True

VIDEO = Path(__file__).resolve().parents[1]
ENGINE = VIDEO.parent
TEMPLATE = ENGINE.parent
PY = sys.executable

FAILS = []

# Обязательные ключи (спецификация конфигов, п. 4): удаление каждого — отказ с именем поля
REQUIRED_PROJECT = ['fps', 'canvas.w', 'canvas.h', 'canvas.px_per_in', 'pause_sec', 'scene_gap_sec',
                    'lead_sec', 'tail_sec', 'scene_exit_delay', 'frame.seam_half', 'frame.seam_dur',
                    'paths.out', 'paths.voices_out', 'voice_bars.min', 'voice_bars.max']
REQUIRED_TOKENS = ['motion.level_step', 'motion.level_gap', 'motion.level_mid', 'motion.ink_dur',
                   'motion.breathe.scale', 'motion.breathe.period', 'density.max_opacity_step',
                   'density.words_per_chunk', 'type.title.weight']
# Ключи конфигов, которые код не смеет читать с запасным числом: .get('<ключ>', <число>)
NO_NUMERIC_FALLBACK = {
    'fps', 'w', 'h', 'px_per_in', 'pause_sec', 'scene_gap_sec', 'lead_sec', 'tail_sec', 'scene_exit_delay',
    'seam_half', 'seam_dur', 'min', 'max', 'gap', 'bars', 'bar_w', 'bar_step', 'box_y', 'box_h', 'weight',
    'size_pt', 'level_shade', 'level_mid', 'level_step', 'level_gap', 'ink_dur', 'scale', 'period', 'edge',
    'title_in', 'chapter_dur', 'emph_dur', 'move_dur', 'beat_tail', 'pulse_amp', 'ring_amp', 'flash_dur',
    'max_opacity_step', 'words_per_chunk'}
VOICE_KEYS = {'gain_db'}           # только engine/video и engine/tts: у music.json своё умолчание трека
ROOT_MODULE = 'project_root.py'


def ok(msg):
    print('  ok   %s' % msg)


def fail(msg):
    FAILS.append(msg)
    print('  FAIL %s' % msg)


def check(cond, msg):
    (ok if cond else fail)(msg)


def run(script, *args, env=None):
    e = dict(os.environ)
    e.pop('MOTION_PROJECT', None)
    e.update(env or {})
    e['PYTHONDONTWRITEBYTECODE'] = '1'
    r = subprocess.run([PY, str(script)] + [str(a) for a in args], capture_output=True, text=True,
                       encoding='utf-8', errors='replace', env=e)
    return r.returncode, r.stdout + r.stderr


def copy_project(tmp, name):
    dst = Path(tmp) / name
    shutil.copytree(TEMPLATE / 'project', dst, ignore=shutil.ignore_patterns('out', '.env', '__pycache__'))
    return dst


def load(p):
    return json.loads(Path(p).read_text(encoding='utf-8-sig'))


def save(p, data):
    Path(p).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')


def drop(data, dotted):
    parts = dotted.split('.')
    cur = data
    for p in parts[:-1]:
        cur = cur[p]
    del cur[parts[-1]]


def set_fake(proj):
    v = load(proj / 'voices.json')
    v['provider'] = 'fake'
    save(proj / 'voices.json', v)


BUILD = VIDEO / 'build.py'
CHECK = VIDEO / 'check.py'
TTS = ENGINE / 'tts' / 'tts.py'


# ---------------------------------------------------------------- п. 1, 2: один out, манифест → фильм
def test_one_out_and_manifest(tmp):
    print('озвучка и видео пишут в один <проект>/out; фильм с manifest собирается и ставит реплику по манифесту')
    proj = copy_project(tmp, 'man')
    set_fake(proj)
    code, out = run(TTS, '--rows', '1-4', '--yes-i-pay', '--max-chars', '1000', '--project', proj)
    check(code == 0, 'tts --rows 1-4 (fake) код 0 (был %s) %s' % (code, out[-200:]))
    code, out = run(TTS, '--assemble', '--project=%s' % proj)
    check(code == 0, 'tts --assemble с --project=DIR код 0 (был %s) %s' % (code, out[-200:]))
    man_path = proj / 'out' / 'tts' / 'manifest.json'
    check(man_path.exists(), 'манифест лежит в <проект>/out/tts (paths.voices_out от папки проекта)')
    check(not (proj.parent / 'out').exists(), 'над папкой проекта out/ не появился')
    if not man_path.exists():
        return None
    man = load(man_path)
    check(all('scene_start' in e for e in man), '--assemble пишет scene_start у всех реплик')
    # раскладка не подряд: реплике 2 сцены demo-a — +1 с к scene_start
    shifted = round(man[1]['scene_start'] + 1.0, 3)
    man[1]['scene_start'] = shifted
    save(man_path, man)
    save(proj / 'films' / 'm.json', {'title': 'm', 'scenes': ['demo-a', 'demo-b'],
                                     'manifest': 'out/tts/manifest.json'})
    code, out = run(BUILD, 'm', '--page', '--project', proj)
    check(code == 0, 'build.py m --page с "manifest": "out/tts/manifest.json" код 0 (был %s) %s' % (code, out[-300:]))
    fj = proj / 'out' / 'm' / 'film.json'
    if code or not fj.exists():
        return None
    film = load(fj)
    r = {x['num']: x for x in film['replies']}
    fps = load(proj / 'project.json')['fps']
    want = r[1]['start'] - man[0]['scene_start'] + shifted
    check(abs(r[2]['start'] - want) <= 1.0 / fps + 1e-6,
          'реплика 2 стоит по манифесту: %.3f с, ждали %.3f с (раскладка подряд дала бы ≈ %.3f)'
          % (r[2]['start'], want, want - 1.0))
    return proj


# ---------------------------------------------------------------- п. 3: голос и gain_db — из voices.json
def test_voice_gain(tmp):
    print('голос фильма не из voices.json и голос без gain_db роняют сборку')
    proj = copy_project(tmp, 'gain')
    d = load(proj / 'films' / 'demo.json')
    d['replies'][1]['voice'] = 'zz'
    save(proj / 'films' / 'bad.json', d)
    code, out = run(BUILD, 'bad', '--page', '--project', proj)
    check(code != 0 and "'zz'" in out and 'voices.json' in out,
          'голос zz: отказ с именем голоса и voices.json (код %s: %s)' % (code, out.strip()[-160:]))
    v = load(proj / 'voices.json')
    del v['voices']['b']['gain_db']
    save(proj / 'voices.json', v)
    code, out = run(BUILD, 'demo', '--page', '--project', proj)
    check(code != 0 and 'voices.b.gain_db' in out,
          'нет gain_db у голоса b: отказ с именем поля (код %s: %s)' % (code, out.strip()[-160:]))


# ---------------------------------------------------------------- п. 4, 6: обязательные ключи, px_per_in
def test_required_keys(tmp):
    print('обязательные ключи project.json / tokens.json: нет ключа — отказ с именем поля')
    base = copy_project(tmp, 'req')
    for fname, keys in (('project.json', REQUIRED_PROJECT), ('tokens.json', REQUIRED_TOKENS)):
        for key in keys:
            data = load(base / fname)
            drop(data, key)
            save(base / fname, data)
            code, out = run(BUILD, 'demo', '--page', '--project', base)
            check(code != 0 and ('нет обязательного поля %s' % key) in out and 'Traceback' not in out,
                  'build без %s %s: отказ с именем поля (код %s: %s)' % (fname, key, code, out.strip()[-120:]))
            shutil.copyfile(TEMPLATE / 'project' / fname, base / fname)
    pj = load(base / 'project.json')
    pj['canvas']['px_per_in'] = 72
    save(base / 'project.json', pj)
    code, out = run(BUILD, 'demo', '--page', '--project', base)
    check(code != 0 and 'px_per_in' in out and '96' in out,
          'px_per_in 72: сборка отказывает с объяснением (код %s: %s)' % (code, out.strip()[-160:]))


def test_check_required(tmp, built):
    print('check.py: нет обязательного ключа или px_per_in ≠ 96 — отказ с именем поля')
    if built is None:
        fail('нет собранной страницы m — тест пропущен')
        return
    code, out = run(CHECK, 'm', '--page', '--project', built)
    check(code == 0, 'положительный образец: check m --page на полных конфигах зелёный (код %s) %s'
          % (code, out.strip()[-200:]))
    for fname, key in (('tokens.json', 'density.words_per_chunk'), ('tokens.json', 'motion.breathe.period'),
                       ('project.json', 'tail_sec'), ('project.json', 'fps')):
        data = load(built / fname)
        keep = json.loads(json.dumps(data))
        drop(data, key)
        save(built / fname, data)
        code, out = run(CHECK, 'm', '--page', '--project', built)
        check(code != 0 and key in out and 'Traceback' not in out,
              'check без %s %s: отказ с именем поля (код %s: %s)' % (fname, key, code, out.strip()[-120:]))
        save(built / fname, keep)
    pj = load(built / 'project.json')
    pj['canvas']['px_per_in'] = 120
    save(built / 'project.json', pj)
    code, out = run(CHECK, 'm', '--page', '--project', built)
    check(code != 0 and 'px_per_in' in out and 'Traceback' not in out,
          'check при px_per_in 120: отказ (код %s: %s)' % (code, out.strip()[-120:]))
    pj['canvas']['px_per_in'] = 96
    save(built / 'project.json', pj)


def _py_files():
    for p in sorted(ENGINE.rglob('*.py')):
        if 'node_modules' in p.parts or 'tests' in p.parts or '__pycache__' in p.parts:
            continue
        yield p


def numeric_fallbacks(src, keys):
    """[(строка, ключ)]: вызовы x.get('<ключ>', <число>) и mo(ctx, '<ключ>', <что угодно>)."""
    out = []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        name = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else None)
        a = node.args
        if name == 'get' and len(a) == 2 and isinstance(a[0], ast.Constant) and a[0].value in keys:
            d = a[1]
            if isinstance(d, ast.UnaryOp):
                d = d.operand
            if isinstance(d, ast.Constant) and isinstance(d.value, (int, float)) and not isinstance(d.value, bool):
                out.append((node.lineno, a[0].value))
        if name == 'mo' and len(a) >= 3:
            out.append((node.lineno, getattr(a[1], 'value', '?')))
    return out


def test_no_numeric_fallback():
    print('код движка не читает ключи конфигов с запасным числом (класс дефекта, п. 4)')
    hits = []
    for p in _py_files():
        keys = NO_NUMERIC_FALLBACK | (VOICE_KEYS if p.parent.name in ('video', 'tts') else set())
        for line, key in numeric_fallbacks(p.read_text(encoding='utf-8'), keys):
            hits.append('%s:%d %s' % (p.relative_to(ENGINE), line, key))
    check(not hits, 'запасных чисел у ключей конфигов нет (%s)' % ('; '.join(hits[:8]) or '0'))
    # самопроверка сканера: он обязан увидеть запасное число в образце
    sample = "fps = int(P.project.get('fps', 30))\ntail = mo(ctx, 'move_dur', 0.7)\nx = b.get('offset', 0.0)\n"
    got = sorted(k for _, k in numeric_fallbacks(sample, NO_NUMERIC_FALLBACK))
    check(got == ['fps', 'move_dur'], 'сканер ловит образцы fps и move_dur и пропускает offset раскадровки (%s)' % got)


def test_one_root_rule():
    print('корень проекта: одно правило в engine/project_root.py, один разбор --project')
    env_hits, argv_hits = [], []
    for p in _py_files():
        src = p.read_text(encoding='utf-8')
        if p.name != ROOT_MODULE and re.search(r"environ(?:\.get\(|\[)\s*'MOTION_PROJECT'", src):
            env_hits.append(str(p.relative_to(ENGINE)))
        if p.name != ROOT_MODULE and re.search(r"'--project' in |index\('--project'\)|add_argument\('--project'", src):
            argv_hits.append(str(p.relative_to(ENGINE)))
    check(not env_hits, 'MOTION_PROJECT читает только project_root.py (%s)' % (', '.join(env_hits) or 'да'))
    check(not argv_hits, '--project разбирает только project_root.split_argv (%s)' % (', '.join(argv_hits) or 'да'))
    sys.path.insert(0, str(ENGINE))
    import project_root as pr
    d = TEMPLATE / 'project'
    check(pr.split_argv(['x', '--project', str(d)]) == (d.resolve(), ['x']), '--project DIR')
    check(pr.split_argv(['--project=%s' % d, 'x']) == (d.resolve(), ['x']), '--project=DIR')
    old = os.environ.pop('MOTION_PROJECT', None)
    try:
        os.environ['MOTION_PROJECT'] = str(ENGINE)
        check(pr.split_argv(['x'])[0] == ENGINE.resolve(), 'без флага — MOTION_PROJECT')
        del os.environ['MOTION_PROJECT']
        check(pr.split_argv([])[0] == (TEMPLATE / 'project').resolve(), 'без флага и переменной — <шаблон>/project')
    finally:
        if old is not None:
            os.environ['MOTION_PROJECT'] = old
    for bad in (['--project'], ['--project', '--page'], ['--project='], ['--project', 'a', '--project', 'b']):
        try:
            pr.split_argv(bad)
            fail('%s принят, а должен быть отказ' % bad)
        except SystemExit as e:
            ok('%s → отказ «%s»' % (bad, str(e.code)[:60]))
    # одинаковый разбор во всех точках входа: --project=DIR понимают все
    for script, args in ((ENGINE / 'tts' / 'tts.py', ['--estimate']), (ENGINE / 'tts' / 'speech_lint.py', []),
                         (ENGINE / 'tts' / 'voice_gain.py', []), (VIDEO / 'storyboard.py', ['--schema'])):
        code, out = run(script, *(args + ['--project=%s' % d]))
        check('после --project' not in out and 'Traceback' not in out and 'нет файла' not in out,
              '%s --project=DIR разобран (код %s)' % (script.name, code))


# ---------------------------------------------------------------- п. 7: порчи при переименованных голосах
def test_red_renamed_voices(tmp):
    print('check.py --red зелёный при переименованных голосах (id голоса — из project.json voice_bars)')
    proj = copy_project(tmp, 'ren')
    ren = {'a': 'lead', 'b': 'guest'}
    v = load(proj / 'voices.json')
    v['voices'] = {ren[k]: x for k, x in v['voices'].items()}
    save(proj / 'voices.json', v)
    pj = load(proj / 'project.json')
    for x in pj['voice_bars']['voices']:
        x['id'] = ren[x['id']]
    save(proj / 'project.json', pj)
    fd = load(proj / 'films' / 'demo.json')
    for r in fd['replies']:
        r['voice'] = ren[r['voice']]
    save(proj / 'films' / 'demo.json', fd)
    rows = load(proj / 'rows.json')
    for r in rows:
        r['voice'] = ren[r['voice']]
    save(proj / 'rows.json', rows)
    code, out = run(BUILD, 'demo', '--page', '--project', proj)
    check(code == 0, 'build demo --page с голосами lead/guest код 0 (был %s) %s' % (code, out[-200:]))
    code, out = run(CHECK, 'demo', '--page', '--project', proj)
    check(code == 0, 'check demo --page зелёный (код %s) %s' % (code, out[-300:]))
    code, out = run(CHECK, 'demo', '--red', '--project', proj)
    miss = [l for l in out.splitlines() if l.startswith('MISS')]
    check(code == 0 and not miss, 'check --red: все порчи краснеют своей строкой (%s)' % ('; '.join(miss)[:300] or out[-120:]))
    check('#vo-lead' in out, 'порча «голос на футере» стоит на #vo-lead')


def main(argv):
    tmp_root = argv[argv.index('--tmp') + 1] if '--tmp' in argv else None
    tmp = tempfile.mkdtemp(prefix='t-project-', dir=tmp_root)
    try:
        test_one_root_rule()
        test_no_numeric_fallback()
        built = test_one_out_and_manifest(tmp)
        test_check_required(tmp, built)
        test_voice_gain(tmp)
        test_required_keys(tmp)
        if '--skip-red' not in argv:
            test_red_renamed_voices(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print('---\nпровалов: %d' % len(FAILS))
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
