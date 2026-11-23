# -*- coding: utf-8 -*-
"""render_pack.py: пакет на рендер для другой машины и проверка результата.

    python engine/tests/test_render_pack.py

Ожидания — из задания: `make` кладёт проект, RENDER.md, FILES.md и expect.json,
без .env, секретов, node_modules и out/; команда рендера из пакета в НОВОЙ папке даёт видео и report.json; `verify`
зелёный на честном результате и красный своей строкой на видео другой длины, другого размера, другой картинки и на
отчёте от другой страницы. «Другая машина» здесь — новая папка на этой же машине. Ожидаемые величины — демо шаблона:
сцены demo-a и demo-b, 30 кадр/с, 1920×1080, длительность из film.json; секрет и мусор подкладывает сам тест.
Один полный рендер демо (минуты, под замком Chrome); проект копируется во временную папку, поставка не трогается.
"""
import atexit
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

NEEDS_CHROME = True      # make строит страницу, run рендерит: общий прогон берёт замок и не зовёт в --quick

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import ENGINE, PY, check, run_module   # noqa: E402

sys.path.insert(0, str(ENGINE))
sys.path.insert(0, str(ENGINE / 'tools'))
import deps          # noqa: E402
import render_pack   # noqa: E402

TOOL = str(ENGINE / 'tools' / 'render_pack.py')
SECRET = 'sk-test-' + '0123456789' + 'abcdef'           # подложенный «ключ»: его не должно быть нигде в пакете
_state = {}


def _env():
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    env.pop('MOTION_PROJECT', None)
    return env


def _run(*args, cwd=None):
    r = subprocess.run([PY, *args], env=_env(), capture_output=True, text=True, encoding='utf-8', errors='replace',
                       cwd=cwd, timeout=3600)
    out = [l for l in (r.stdout + r.stderr).splitlines() if not l.startswith('замок Chrome')]
    return r.returncode, '\n'.join(out).strip()


def _cleanup():
    pack = _state.get('pack')
    if pack:
        nm = os.path.join(pack, 'engine', 'video', 'node_modules')
        if os.path.lexists(nm):
            try:
                os.rmdir(nm)               # ссылка на общую установку: снимаем её, а не содержимое
            except OSError:
                pass
    shutil.rmtree(_state.get('tmp', ''), ignore_errors=True)


def _setup():
    if 'tmp' in _state:
        return
    tmp = tempfile.mkdtemp(prefix='render_pack_test_')
    _state['tmp'] = tmp
    atexit.register(_cleanup)
    src = os.path.join(tmp, 'src', 'project')
    shutil.copytree(ENGINE.parent / 'project', src, ignore=shutil.ignore_patterns('out', '.env', '__pycache__'))
    with open(os.path.join(src, '.env'), 'w', encoding='utf-8') as fh:          # настоящий .env проекта
        fh.write('MINIMAX_API_KEY=%s\n' % SECRET)
    os.makedirs(os.path.join(src, 'out', 'tts'))                                 # выход сборки: в пакет не идёт
    with open(os.path.join(src, 'out', 'tts', 'old.txt'), 'w') as fh:
        fh.write('x')
    os.makedirs(os.path.join(src, 'node_modules', 'junk'))
    with open(os.path.join(src, 'node_modules', 'junk', 'a.js'), 'w') as fh:
        fh.write('x')
    with open(os.path.join(src, 'assets', 'client.pem'), 'w') as fh:
        fh.write('-----BEGIN-----')
    _state['src'] = src
    _state['pack'] = os.path.join(tmp, 'pack')


def _pack():
    """Пакет, собранный командой make (один раз на тест)."""
    _setup()
    if 'made' not in _state:
        code, out = _run(TOOL, 'make', 'demo', '--to', _state['pack'], '--project', _state['src'])
        _state['made'] = (code, out)
    return _state['made']


def _all_files(root):
    for base, _dirs, files in os.walk(root):
        for f in files:
            yield os.path.join(base, f)


def _rendered():
    """Рендер внутри пакета: новая папка, общая установка Node подключена ссылкой (одна машина — не качаем заново)."""
    _pack()
    if 'run' not in _state:
        pack = _state['pack']
        nm = os.path.join(pack, 'engine', 'video', 'node_modules')
        shared = str(deps.shared_node_modules())
        check(os.path.isdir(shared), 'нет общей установки Node (%s): тест рендера берёт её вместо скачивания' % shared)
        if os.name == 'nt':
            r = subprocess.run(['cmd', '/c', 'mklink', '/J', nm, shared], capture_output=True, text=True)
            check(r.returncode == 0, 'ссылка на node_modules не вышла: %s' % (r.stdout + r.stderr))
        else:
            os.symlink(shared, nm, target_is_directory=True)
        _state['run'] = _run(os.path.join(pack, 'engine', 'tools', 'render_pack.py'), 'run', 'demo', cwd=pack)
    return _state['run']


def _ffmpeg_video(path, size, seconds, source):
    r = subprocess.run([render_pack.ffmpeg(), '-y', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i',
                        '%s=s=%s:r=30:d=%s' % (source, size, seconds) if source == 'testsrc'
                        else 'color=c=red:s=%s:r=30:d=%s' % (size, seconds), '-pix_fmt', 'yuv420p', path],
                       capture_output=True, text=True)
    check(r.returncode == 0 and os.path.exists(path), 'ffmpeg не собрал пробное видео: %s' % r.stderr[-300:])
    return path


def _verify(report, video, expect=None):
    """verify «здесь»: в проекте, из которого собран пакет, — там лежит запись make об ожидаемом."""
    args = [TOOL, 'verify', report, video, '--project', _state['src']]
    if expect:
        args += ['--expect', expect]
    return _run(*args)


# ---------- без браузера: сводка расхождений на синтетических данных ----------

def _synthetic():
    flat = [100] * 144
    expect = {'film': 'f', 'page_sha256': 'a' * 64,
              'video': {'width': 1920, 'height': 1080, 'fps': 30.0, 'frames': 600, 'duration_sec': 20.0},
              'tolerance': {'frame_mad': 14, 'bad_share': 0.1, 'frames': 1},
              'strips': [{'id': 'a:b', 't0': 1.0, 't1': 2.0, 'fps': 10,
                          'frames': [{'t': 1 + k / 10, 'f': 30 + 3 * k, 'sig': flat} for k in range(10)]}]}
    actual = {'width': 1920, 'height': 1080, 'fps': 30.0, 'frames': 600, 'duration_sec': 20.0, 'sha256': 'b' * 64}
    report = {'film': 'f', 'page_sha256': 'a' * 64, 'video': dict(actual),
              'strips': [{'id': 'a:b', 'frames': [{'sig': flat} for _ in range(10)]}]}
    got = [{'id': 'a:b', 'frames': [{'sig': flat} for _ in range(10)]}]
    return expect, report, actual, got


def test_compare_honest_and_pixel_noise_are_green():
    expect, report, actual, got = _synthetic()
    check(render_pack.compare(expect, report, actual, got) == [], 'честный результат дал расхождения')
    noisy = [{'id': 'a:b', 'frames': [{'sig': [100 + 6] * 144} for _ in range(10)]}]       # кодек и драйвер: лёгкий шум
    bad = render_pack.compare(expect, dict(report, strips=[{'id': 'a:b', 'frames': [{'sig': [100 + 6] * 144}] * 10}]),
                              actual, noisy)
    check(bad == [], 'небольшая разница яркости (6 из 255) сочтена другой картинкой: %s' % bad)


def test_compare_each_difference_has_its_own_line():
    expect, report, actual, got = _synthetic()
    cases = {
        'другой длины': dict(actual, frames=300, duration_sec=10.0),
        'другого размера': dict(actual, width=1280, height=720),
        'другой частоты': dict(actual, fps=25.0),
        'не то, что описано в отчёте': dict(actual, sha256='c' * 64),
    }
    for part, act in cases.items():
        bad = render_pack.compare(expect, report, act, got)
        check(any(part in b for b in bad), 'ждали строку со словами «%s», вышло: %s' % (part, bad))
    bad = render_pack.compare(expect, dict(report, page_sha256='d' * 64), actual, got)
    check(len(bad) == 1 and 'другой страницы' in bad[0], 'отчёт от другой страницы: %s' % bad)
    far = [{'id': 'a:b', 'frames': [{'sig': [200] * 144} for _ in range(10)]}]
    bad = render_pack.compare(expect, report, actual, far)
    check(any('вне допуска' in b for b in bad), 'другая картинка в полосе шва не поймана: %s' % bad)
    short = [{'id': 'a:b', 'frames': [{'sig': [100] * 144}] * 4 + [{'t': 1.4, 'f': 42}] * 6}]
    bad = render_pack.compare(expect, report, actual, short)
    check(any('нет 6 из 10 кадров' in b for b in bad), 'кадры за концом видео не пойманы: %s' % bad)


def test_collect_project_leaves_out_env_and_secrets():
    tmp = tempfile.mkdtemp(prefix='render_pack_unit_')
    try:
        for rel, body in (('scenes/a/storyboard.json', '{}'), ('.env', 'K=1'), ('.env.local', 'K=1'),
                          ('out/x/video.mp4', 'v'), ('node_modules/p/i.js', 'j'), ('assets/key.pem', 'k'),
                          ('assets/__pycache__/m.pyc', 'c'), ('assets/ok.png', 'p'), ('big/skip.bin', 'b')):
            p = os.path.join(tmp, *rel.split('/'))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, 'w') as fh:
                fh.write(body)
        keep, dropped = render_pack.collect_project(tmp, 'out', ['big'])
        names = sorted(r for r, _ in keep)
        check(names == ['assets/ok.png', 'scenes/a/storyboard.json'], 'уезжают не те файлы: %s' % names)
        check(dropped['по --exclude'] == 1 and dropped['out'] == 1 and dropped['секреты'] == 3,
              'счёт отброшенного: %s' % dropped)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------- make ----------

def test_make_lays_out_the_pack_without_secrets():
    code, out = _pack()
    check(code == 0, 'make упал (код %d): %s' % (code, out[-500:]))
    pack = _state['pack']
    for f in ('RENDER.md', 'FILES.md', 'expect.json', 'project/project.json', 'engine/tools/render_pack.py',
              'engine/video/package-lock.json', 'project/scenes/demo-a/storyboard.json'):
        check(os.path.exists(os.path.join(pack, f)), 'в пакете нет %s' % f)
    names = [os.path.relpath(p, pack).replace(os.sep, '/') for p in _all_files(pack)]
    bad = [n for n in names if re.search(r'(^|/)(\.env[^/]*|node_modules/.*|[^/]*\.pem)$', n) or n.startswith('project/out/')
           or '__pycache__' in n]
    check(not bad, 'в пакете лишнее (.env, секреты, node_modules, out): %s' % bad[:5])
    for p in _all_files(pack):
        with open(p, 'rb') as fh:
            check(SECRET.encode() not in fh.read(), 'значение секрета лежит в пакете: %s' % os.path.relpath(p, pack))
    files_md = open(os.path.join(pack, 'FILES.md'), encoding='utf-8').read()
    check('project/scenes' not in files_md and '`scenes/demo-a/storyboard.json`' in files_md,
          'FILES.md не перечисляет файлы заказчика (сцены демо) от корня проекта')
    check('.env' not in files_md.replace('(`.env`, ключи)', '').replace('`.env`', ''), 'FILES.md называет .env как уезжающий файл')
    render_md = open(os.path.join(pack, 'RENDER.md'), encoding='utf-8').read()
    for part in ('render_pack.py install', 'render_pack.py run demo', 'return/'):
        check(part in render_md, 'в RENDER.md нет «%s»' % part)


def test_expect_json_numbers():
    _pack()
    ex = json.load(open(os.path.join(_state['pack'], 'expect.json'), encoding='utf-8'))
    film = json.load(open(os.path.join(_state['src'], 'out', 'demo', 'film.json'), encoding='utf-8'))
    v = ex['video']
    check((v['width'], v['height'], v['fps']) == (1920, 1080, 30.0), 'размер/частота в expect: %s' % v)
    check(v['frames'] == 647 and abs(v['duration_sec'] - 647 / 30) < 1e-3, 'кадров %s, ждали 647 (21,5667 с × 30)' % v['frames'])
    check(abs(v['film_duration_sec'] - film['duration']) < 1e-3, 'длительность не из film.json')
    # контрольная сумма страницы — отпечаток страницы целиком (stamp.page_print: index.html, film.json, файлы assets/),
    # а не одного index.html: sha256 от его JSON с ключами по алфавиту
    import hashlib
    sys.path.insert(0, str(ENGINE / 'video'))
    import stamp
    page = os.path.join(_state['src'], 'out', 'demo')
    whole = hashlib.sha256(json.dumps(stamp.page_print(page), sort_keys=True).encode('utf-8')).hexdigest()
    check(ex['page_sha256'] == whole, 'контрольная сумма страницы в expect.json — не отпечаток страницы целиком '
          '(index.html + film.json + assets/): %s' % ('это sha256 одного index.html' if ex['page_sha256'] ==
                                                      hashlib.sha256(open(os.path.join(page, 'index.html'), 'rb').read()).hexdigest() else ex['page_sha256'][:12]))
    check([s['id'] for s in ex['strips']] == ['demo-a:demo-b'] and len(ex['strips'][0]['frames']) >= 15,
          'полосы шва в expect: %s' % [(s['id'], len(s['frames'])) for s in ex['strips']])


def test_make_records_expect_checksum_in_the_project():
    """make оставляет на этой машине запись об ожидаемом: <out>/<фильм>/render_pack.json с sha256 expect.json пакета.
    По ней verify отличает свой expect.json от поправленного на той стороне."""
    import hashlib
    _pack()
    rec_path = os.path.join(_state['src'], 'out', 'demo', 'render_pack.json')
    check(os.path.exists(rec_path), 'make не оставил запись %s' % rec_path)
    rec = json.load(open(rec_path, encoding='utf-8'))
    sha = hashlib.sha256(open(os.path.join(_state['pack'], 'expect.json'), 'rb').read()).hexdigest()
    check(rec.get('film') == 'demo' and [p.get('expect_sha256') for p in rec.get('packs', [])] == [sha],
          'в записи make не sha256 expect.json пакета: %s' % rec)
    names = [os.path.relpath(p, _state['pack']).replace(os.sep, '/') for p in _all_files(_state['pack'])]
    check(not [n for n in names if n.endswith('render_pack.json')], 'запись make уехала в пакет')


def test_make_refuses_nonempty_target_and_secret_lines():
    _pack()
    code, out = _run(TOOL, 'make', 'demo', '--to', _state['pack'], '--project', _state['src'])
    check(code != 0 and 'не пуста' in out, 'make в непустую папку: код %d, %s' % (code, out[-200:]))
    with open(os.path.join(_state['src'], 'notes.txt'), 'w', encoding='utf-8') as fh:
        fh.write('MINIMAX_API_KEY = %s\n' % SECRET)
    to = os.path.join(_state['tmp'], 'pack2')
    code, out = _run(TOOL, 'make', 'demo', '--to', to, '--project', _state['src'])
    check(code != 0 and 'notes.txt:1' in out and 'MINIMAX_API_KEY' in out, 'секретная строка не остановила make: %s' % out[-300:])
    check(SECRET not in out, 'значение секрета напечатано в сообщении об ошибке')
    check(not os.path.exists(to), 'после отказа осталась недособранная папка пакета')
    os.remove(os.path.join(_state['src'], 'notes.txt'))


# ---------- run на «другой машине» и verify ----------

def test_run_in_fresh_folder_gives_video_and_report():
    code, out = _rendered()
    check(code == 0, 'run упал (код %d): %s' % (code, out[-600:]))
    ret = os.path.join(_state['pack'], 'return')
    for f in ('video.mp4', 'report.json', 'expect.json', 'render.log'):
        check(os.path.exists(os.path.join(ret, f)), 'в return/ нет %s' % f)
    rep = json.load(open(os.path.join(ret, 'report.json'), encoding='utf-8'))
    ex = json.load(open(os.path.join(ret, 'expect.json'), encoding='utf-8'))
    v = rep['video']
    for k in ('width', 'height', 'fps', 'duration_sec', 'frames', 'sha256', 'size_bytes'):
        check(k in v, 'в report.video нет %s' % k)
    check((v['width'], v['height']) == (1920, 1080) and abs(v['frames'] - 647) <= 1, 'отрендерено %s: %s' % ((v['width'], v['height']), v['frames']))
    check(rep['page_sha256'] == ex['page_sha256'], 'страница в новой папке собралась другой: контрольные суммы разошлись')
    check(rep['machine'].get('cores') and rep['machine'].get('python') and rep['machine'].get('platform'), 'нет сведений о машине')
    check(len(rep['strips']) == len(ex['strips']) and all('sig' in f for s in rep['strips'] for f in s['frames']),
          'полосы швов в отчёте неполные')


def test_verify_green_on_honest_result():
    _rendered()
    ret = os.path.join(_state['pack'], 'return')
    code, out = _verify(os.path.join(ret, 'report.json'), os.path.join(ret, 'video.mp4'))
    check(code == 0 and 'зелёное' in out, 'честный результат: код %d, %s' % (code, out[-500:]))
    check('может отличаться в пикселях' in out and 'по полосам' in out and 'не побайтно' in out,
          'verify не сказал, что пиксели с другой машины отличаются и сравнение по полосам: %s' % out)


def test_verify_red_on_other_length_size_picture_and_page():
    _rendered()
    ret = os.path.join(_state['pack'], 'return')
    rep, vid = os.path.join(ret, 'report.json'), os.path.join(ret, 'video.mp4')
    tmp = _state['tmp']
    short = _ffmpeg_video(os.path.join(tmp, 'short.mp4'), '1920x1080', 3, 'testsrc')
    code, out = _verify(rep, short)
    check(code == 1 and 'видео другой длины' in out, 'видео другой длины: код %d, %s' % (code, out[-400:]))
    small = _ffmpeg_video(os.path.join(tmp, 'small.mp4'), '640x360', 21.5667, 'testsrc')
    code, out = _verify(rep, small)
    check(code == 1 and 'видео другого размера' in out, 'видео другого размера: код %d, %s' % (code, out[-400:]))
    red = _ffmpeg_video(os.path.join(tmp, 'red.mp4'), '1920x1080', 21.5667, 'color')
    code, out = _verify(rep, red)
    check(code == 1 and 'картинка не та' in out, 'видео той же длины с другой картинкой: код %d, %s' % (code, out[-400:]))
    other = json.load(open(rep, encoding='utf-8'))
    other['page_sha256'] = '0' * 64
    alien = os.path.join(ret, 'report-other.json')
    json.dump(other, open(alien, 'w', encoding='utf-8'))
    code, out = _verify(alien, vid)
    check(code == 1 and 'отчёт от другой страницы' in out, 'отчёт от другой страницы: код %d, %s' % (code, out[-400:]))
    lines = [l for l in out.splitlines() if l.startswith('КРАСНОЕ')]
    check(len(lines) == 1, 'честное видео с чужим отчётом дало %d красных строк вместо одной: %s' % (len(lines), lines))


def test_verify_red_when_expect_was_edited_on_the_other_side():
    """Та сторона вернула видео короче и поправила return/expect.json под него (и отчёт): зелёного быть не должно —
    ожидаемое сверяется с записью make на этой машине, ни один путь к подменённому файлу проверку не обходит."""
    _rendered()
    ret = os.path.join(_state['pack'], 'return')
    fake = os.path.join(_state['tmp'], 'return-edited')
    shutil.rmtree(fake, ignore_errors=True)
    os.makedirs(fake)
    short = _ffmpeg_video(os.path.join(fake, 'video.mp4'), '1920x1080', 3, 'testsrc')
    info = render_pack.probe_video(short)
    expect = json.load(open(os.path.join(ret, 'expect.json'), encoding='utf-8'))
    expect['video'].update(frames=info['frames'], duration_sec=info['duration_sec'])
    expect['strips'] = []
    report = json.load(open(os.path.join(ret, 'report.json'), encoding='utf-8'))
    report.update(video=info, strips=[])
    json.dump(expect, open(os.path.join(fake, 'expect.json'), 'w', encoding='utf-8'))
    json.dump(report, open(os.path.join(fake, 'report.json'), 'w', encoding='utf-8'))
    for expect_arg in (None, os.path.join(fake, 'expect.json')):
        code, out = _verify(os.path.join(fake, 'report.json'), short, expect_arg)
        check(code == 1 and 'зелёное' not in out, 'подменённый expect.json (%s) дал код %d: %s'
              % ('рядом с отчётом' if expect_arg is None else '--expect', code, out[-400:]))
        check('expect.json' in out and 'make' in out, 'отказ не говорит, что expect.json не тот, что записал make: %s' % out[-400:])
    code, out = _verify(os.path.join(fake, 'report.json'), short, os.path.join(_state['pack'], 'expect.json'))
    check(code == 1 and 'видео другой длины' in out, 'с ожидаемым из пакета на этой машине короткое видео не поймано: %s' % out[-400:])


def test_install_dry_run_names_steps_and_installs_nothing():
    code, out = _run(TOOL, 'install', '--dry-run')
    check(code == 0 and 'npm' in out and 'ci' in out and 'pip' in out and 'browser' in out and 'dry-run' in out,
          'install --dry-run: код %d, %s' % (code, out[-300:]))


if __name__ == '__main__':
    sys.exit(run_module(globals()))
