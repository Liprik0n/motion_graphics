# -*- coding: utf-8 -*-
"""strip.py: полоса кадров, лист, видео, пара «до / после» и вход strip.frames для проверок.

    python engine/tests/test_strip.py

Ожидания — из задания и из известных величин демо: сцена demo-a
идёт с 0 до значения film.json scenes[].end, реплика 2 лежит в demo-a. Работает на копии project/ во временной
папке; поставка не трогается. Страница собирается один раз (build.py --page), остальные запуски берут её же.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

NEEDS_CHROME = True      # безголовый браузер: общий прогон берёт замок и не зовёт в --quick

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import ENGINE, PY, check, run_module   # noqa: E402

STRIP = str(ENGINE / 'tools' / 'strip.py')
_state = {}


def _run(*args):
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    env.pop('MOTION_PROJECT', None)
    r = subprocess.run([PY, STRIP] + list(args), env=env, capture_output=True, text=True, encoding='utf-8',
                       errors='replace', timeout=1800)
    # «замок Chrome занят … — жду» — не вывод команды, а ожидание чужого браузера: при занятой машине такая строка
    # вставала перед ошибкой и роняла проверки «ошибка — одна строка»
    out = [l for l in (r.stdout + r.stderr).splitlines() if not l.startswith('замок Chrome')]
    return r.returncode, '\n'.join(out).strip()


def _project():
    if 'proj' not in _state:
        tmp = tempfile.mkdtemp(prefix='strip_test_')
        proj = os.path.join(tmp, 'project')
        shutil.copytree(ENGINE.parent / 'project', proj, ignore=shutil.ignore_patterns('out', '.env', '__pycache__'))
        _state.update(tmp=tmp, proj=proj, strips=os.path.join(proj, 'out', 'demo', 'strips'))
        _state['before'] = _tree(proj, skip_out=True)
    return _state['proj']


def _tree(root, skip_out):
    seen = {}
    for d, dirs, files in os.walk(root):
        if skip_out and os.path.relpath(d, root) == '.':
            dirs[:] = [x for x in dirs if x != 'out']
        for f in files:
            p = os.path.join(d, f)
            with open(p, 'rb') as fh:
                seen[os.path.relpath(p, root)] = hashlib.sha1(fh.read()).hexdigest()
    return seen


def _strip(*args):
    proj = _project()
    code, out = _run('demo', '--project', proj, *args)
    return code, out


def _json(name):
    with open(os.path.join(_state['strips'], name, 'strip.json'), encoding='utf-8') as fh:
        return json.load(fh)


def _duration(path):
    import re
    sys.path.insert(0, str(ENGINE / 'video'))
    import lipsync
    r = subprocess.run([lipsync.ffmpeg_exe(), '-i', path], capture_output=True, text=True, encoding='utf-8', errors='replace')
    m = re.search(r'Duration: (\d+):(\d+):([\d.]+)', r.stderr)
    check(m, 'ffmpeg не открыл %s: %s' % (path, r.stderr[-200:]))
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def test_scene_strip_files_and_json():
    code, out = _strip('--scene', 'demo-a', '--video', '--gif')
    check(code == 0, 'strip --scene упал (код %d): %s' % (code, out[-400:]))
    d = os.path.join(_state['strips'], 'scene-demo-a')
    for f in ('strip.png', 'sheet.png', 'strip.json', 'clip.mp4', 'clip.gif'):
        check(os.path.exists(os.path.join(d, f)), 'нет %s в %s' % (f, d))
    j = _json('scene-demo-a')
    for k in ('film', 'kind', 'id', 't0', 't1', 'fps', 'scale', 'frames', 'page_sha256'):
        check(k in j, 'в strip.json нет поля %s' % k)
    with open(os.path.join(_state['proj'], 'out', 'demo', 'film.json'), encoding='utf-8') as fh:
        scene = [s for s in json.load(fh)['scenes'] if s['id'] == 'demo-a'][0]
    check(j['film'] == 'demo' and j['kind'] == 'scene' and j['id'] == 'demo-a', 'film/kind/id: %s' % j)
    check(abs(j['t0'] - scene['start']) < 1e-3 and abs(j['t1'] - scene['end']) < 1e-3, 'отрезок %s…%s, а сцена %s…%s'
          % (j['t0'], j['t1'], scene['start'], scene['end']))
    want = round((scene['end'] - scene['start']) * 10)
    check(len(j['frames']) == want, 'кадров %d, ждали %d (10 кадр/с)' % (len(j['frames']), want))
    check(all(os.path.exists(os.path.join(d, f['file'])) for f in j['frames']), 'в frames/ не все файлы из strip.json')
    from PIL import Image
    check(Image.open(os.path.join(d, 'frames', '0001.png')).size == (480, 270), 'кадр не 480×270 при --height 270')
    dur = _duration(os.path.join(d, 'clip.mp4'))
    check(abs(dur - (scene['end'] - scene['start'])) <= 0.15, 'clip.mp4 длится %.2f с, отрезок %.2f с' % (dur, scene['end'] - scene['start']))


def test_two_runs_same_bytes():
    d = os.path.join(_state['strips'], 'scene-demo-a')
    first = _tree(d, skip_out=False)
    code, out = _strip('--scene', 'demo-a', '--no-build', '--video', '--gif')
    check(code == 0, 'повторный запуск упал: %s' % out[-300:])
    second = _tree(d, skip_out=False)
    frames = {k: v for k, v in first.items() if k.startswith('frames')}
    check(frames and all(second.get(k) == v for k, v in frames.items()), 'кадры двух запусков на той же странице разные')
    check(first['strip.png'] == second['strip.png'], 'strip.png двух запусков разный')


def test_seam_at_range():
    code, out = _strip('--seam', 'demo-a:demo-b')
    check(code == 0, '--seam: %s' % out[-300:])
    j = _json('seam-demo-a-demo-b')
    check(j['kind'] == 'seam' and j['t0'] < j['t1'], 'шов: %s' % {k: v for k, v in j.items() if k != 'frames'})
    page = os.path.join(_state['proj'], 'out', 'demo--demo-a,demo-b', 'film.json')
    check(os.path.exists(page), 'страница пары сцен не собрана: %s' % page)
    with open(page, encoding='utf-8') as fh:
        sc = {s['id']: s for s in json.load(fh)['scenes']}
    border = sc['demo-a']['end']
    check(j['t0'] < border < j['t1'], 'окно шва %s…%s не содержит границу сцен %s' % (j['t0'], j['t1'], border))
    code, out = _strip('--at', '2:0.5', '--no-build')
    check(code == 0, '--at: %s' % out[-300:])
    j = _json('at-2-0_5')
    with open(os.path.join(_state['proj'], 'out', 'demo', 'film.json'), encoding='utf-8') as fh:
        r = [x for x in json.load(fh)['replies'] if x['num'] == 2][0]
    mid = r['start'] + 0.5 * (r['end'] - r['start'])
    check(j['t0'] < mid < j['t1'], '--at 2:0.5: момент %.2f с вне окна %s…%s' % (mid, j['t0'], j['t1']))
    code, out = _strip('--range', '1:2.5', '--fps', '5', '--no-build', '--video')
    check(code == 0, '--range: %s' % out[-300:])
    j = _json('range-1-2_5')
    check(len(j['frames']) == 8 and j['fps'] == 5, '--range 1:2.5 при 5 кадр/с: %d кадров, ждали 8' % len(j['frames']))
    dur = _duration(os.path.join(_state['strips'], 'range-1-2_5', 'clip.mp4'))
    check(abs(dur - 1.5) <= 0.25, 'clip.mp4 отрезка 1,5 с длится %.2f с' % dur)


def test_pair():
    old = os.path.join(_state['strips'], 'scene-demo-a')
    keep = old + '-old'
    shutil.rmtree(keep, ignore_errors=True)
    shutil.copytree(old, keep)
    code, out = _strip('--scene', 'demo-a', '--no-build', '--pair', keep)
    check(code == 0, '--pair: %s' % out[-300:])
    from PIL import Image
    p = Image.open(os.path.join(old, 'pair.png'))
    s = Image.open(os.path.join(old, 'strip.png'))
    check(p.width == s.width and p.height >= 2 * s.height, 'pair.png %s — две полосы %s друг над другом не получились' % (p.size, s.size))
    code, out = _strip('--range', '1:2.5', '--no-build', '--pair', keep, '--name', 'pair-bad')
    check(code != 0 and 'тем же таймкодам' in out, 'несовпадение отрезков не названо понятной ошибкой: %s' % out[-300:])
    check(len(out.splitlines()) == 1, 'ошибка длиннее одной строки: %s' % out)


def test_pair_onto_the_same_folder_keeps_the_old_strip_on_top():
    """`--pair` на папку с тем же именем, что у новой полосы (так учит process/08-render-qa.md): прежняя полоса
    читается до того, как её папка стирается. Страница в тесте не менялась, новая полоса вышла бы точной копией
    прежней — поэтому прежняя перед запуском перекрашена (негатив): верх pair.png обязан быть ею, низ — новой."""
    from PIL import Image, ImageChops, ImageOps
    old = os.path.join(_state['strips'], 'scene-demo-a')
    with Image.open(os.path.join(old, 'strip.png')) as im:
        before = ImageOps.invert(im.convert('RGB'))
    before.save(os.path.join(old, 'strip.png'))
    code, out = _strip('--scene', 'demo-a', '--no-build', '--pair', old)
    check(code == 0, '--pair на свою же папку: %s' % out[-300:])
    with Image.open(os.path.join(old, 'strip.png')) as im:
        new = im.convert('RGB')
    with Image.open(os.path.join(old, 'pair.png')) as im:
        pair = im.convert('RGB')
    check(new.size == before.size and ImageChops.difference(new, before).getbbox() is not None,
          'новая полоса не отличается от перекрашенной прежней — тест ничего не мерит')
    bar = (pair.height - before.height - new.height) // 2
    top = pair.crop((0, bar, before.width, bar + before.height))
    low = pair.crop((0, 2 * bar + before.height, new.width, 2 * bar + before.height + new.height))
    check(ImageChops.difference(top, before).getbbox() is None,
          'верхняя полоса pair.png — не прежняя: прежняя стёрта до склейки%s'
          % (' (сверху лежит новая: «после» над «после»)' if ImageChops.difference(top, new).getbbox() is None else ''))
    check(ImageChops.difference(low, new).getbbox() is None, 'нижняя полоса pair.png — не новая')


def test_name_cannot_point_outside_strips_folder():
    """`--name` с частями пути не стирает чужое: рядом со страницей лежит папка с файлом, у фильма есть полоса и
    кэш кадров — после отказа всё на месте (`--name ../keep` стирало out/<фильм>/keep, `--name .` — все полосы)."""
    keep = os.path.join(_state['proj'], 'out', 'demo', 'keep', 'video.mp4')
    os.makedirs(os.path.dirname(keep), exist_ok=True)
    with open(keep, 'w', encoding='utf-8') as fh:
        fh.write('чужой файл')
    mine = os.path.join(_state['strips'], 'scene-demo-a', 'strip.json')
    cache = os.path.join(_state['strips'], '_cache')
    cached = sorted(os.listdir(cache))
    check(os.path.exists(mine) and cached, 'до проверки нет полосы scene-demo-a или кэша кадров')
    for name in ('../keep', '.', '_cache', '..'):
        code, out = _strip('--scene', 'demo-a', '--no-build', '--name', name)
        check(os.path.exists(keep), '--name %s стёр out/demo/keep (чужую папку рядом со страницей)' % name)
        check(os.path.exists(mine), '--name %s стёр полосы фильма' % name)
        check(sorted(os.listdir(cache)) == cached, '--name %s тронул кэш кадров' % name)
        check(code != 0 and '--name' in out and len(out.splitlines()) == 1, '--name %s: нет отказа одной строкой: %s' % (name, out[-300:]))
    shutil.rmtree(os.path.dirname(keep), ignore_errors=True)


def test_frames_entry_cached():
    sys.path.insert(0, str(ENGINE / 'tools'))
    import strip
    proj = _state['proj']
    a = strip.frames(proj, 'demo', 1.0, 2.0, 10, 0.1)
    check(len(a) == 10 and all(os.path.exists(p) for p in a), 'strip.frames: %d путей, ждали 10' % len(a))
    stamp = [os.stat(p).st_mtime_ns for p in a]
    b = strip.frames(proj, 'demo', 1.0, 2.0, 10, 0.1)
    check(a == b and stamp == [os.stat(p).st_mtime_ns for p in b], 'те же аргументы снимают кадры заново (Chrome второй раз)')


def test_replaced_asset_reshoots_frames():
    """Файл в assets/ страницы, заменённый под тем же именем (картинка-кадр, шрифт), index.html не меняет, а кадр
    меняет: кадры из кэша после замены брать нельзя. Ключ кэша — отпечаток страницы целиком (stamp.page_print)."""
    from PIL import Image
    sys.path.insert(0, str(ENGINE / 'tools'))
    import strip
    proj = _state['proj']
    page = os.path.join(proj, 'out', 'demo')
    picture = os.path.join(page, 'assets', 'start-frame.png')
    Image.new('RGB', (64, 36), (200, 40, 40)).save(picture)
    with open(os.path.join(page, 'index.html'), 'rb') as fh:
        index = hashlib.sha256(fh.read()).hexdigest()
    a = strip.frames(proj, 'demo', 1.0, 2.0, 10, 0.1)
    stamp = [os.stat(p).st_mtime_ns for p in a]
    check(a == strip.frames(proj, 'demo', 1.0, 2.0, 10, 0.1) and stamp == [os.stat(p).st_mtime_ns for p in a],
          'та же страница с той же картинкой снята заново')
    Image.new('RGB', (64, 36), (40, 40, 200)).save(picture)             # другая картинка под тем же именем
    with open(os.path.join(page, 'index.html'), 'rb') as fh:
        check(hashlib.sha256(fh.read()).hexdigest() == index, 'index.html изменился — тест меряет не замену файла в assets/')
    b = strip.frames(proj, 'demo', 1.0, 2.0, 10, 0.1)
    check(len(b) == 10 and all(os.path.exists(p) for p in b), 'после замены картинки кадры не сняты: %d' % len(b))
    check(b != a, 'картинка в assets/ заменена под тем же именем, а кадры взяты из кэша прежней страницы')
    code, out = _strip('--range', '1:2', '--no-build', '--name', 'asset-a')
    check(code == 0, 'полоса после замены картинки: %s' % out[-300:])
    Image.new('RGB', (64, 36), (40, 200, 40)).save(picture)
    code, out = _strip('--range', '1:2', '--no-build', '--name', 'asset-b')
    check(code == 0, 'полоса после второй замены картинки: %s' % out[-300:])
    check(_json('asset-a')['page_sha256'] != _json('asset-b')['page_sha256'],
          'strip.json: page_sha256 один и тот же при разных картинках в assets/ — отпечаток не видит файлы страницы')
    os.remove(picture)


def _reference_frames(page, numbers, scale):
    """Кадры страницы по номеру кадра фильма — мимо strip.py: прямой вызов промера probe_frames.mjs --strip."""
    sys.path.insert(0, str(ENGINE))
    import chrome_lock
    d = os.path.join(_state['tmp'], 'reference')
    os.makedirs(d, exist_ok=True)
    files = {f: os.path.join(d, 'f%05d.png' % f) for f in numbers}
    job = os.path.join(d, 'job.json')
    with open(job, 'w', encoding='utf-8') as fh:
        json.dump({'scale': scale, 'frames': [{'f': f, 'file': p} for f, p in files.items()]}, fh)
    with chrome_lock.held('test_strip.py: эталонные кадры'):
        r = subprocess.run(['node', str(ENGINE / 'video' / 'probe_frames.mjs'), page, '--strip', job], capture_output=True,
                           text=True, encoding='utf-8', errors='replace', timeout=1800)
    check(r.returncode == 0 and all(os.path.exists(p) for p in files.values()), 'эталонные кадры не сняты: %s' % (r.stdout + r.stderr)[-300:])
    return files


def _same(a, b):
    from PIL import Image, ImageChops
    x, y = Image.open(a).convert('RGB'), Image.open(b).convert('RGB')
    return x.size == y.size and ImageChops.difference(x, y).getbbox() is None


def test_frame_is_taken_at_its_named_time():
    """Кадр, заявленный как t, снят в момент t фильма и тогда, когда частота полосы не равна частоте фильма.
    Эталон — не расчёт strip.py: промер зовётся напрямую с номером кадра фильма, сосчитанным руками. Фильм демо
    идёт 30 кадр/с: 13,0 с — кадр 390, 13,5 с — кадр 405 (оба — сцена demo-b, во втором уже звучит реплика 3).
    Кадр 26 (0,87 с, сцена demo-a) — туда попадала полоса 2 кадр/с, считая номер кадра по своей частоте: 13,0 × 2."""
    proj = _project()
    page = os.path.join(proj, 'out', 'demo')
    built = os.path.exists(os.path.join(page, 'index.html'))
    code, out = _strip('--range', '13:14', '--fps', '10', '--name', 'time-check', *(['--no-build'] if built else []))
    check(code == 0, '--range 13:14 --fps 10: %s' % out[-300:])
    with open(os.path.join(page, 'film.json'), encoding='utf-8') as fh:
        check(json.load(fh)['fps'] == 30, 'демо больше не 30 кадр/с — номера кадров теста сосчитаны для 30')
    ref = _reference_frames(page, [26, 390, 405], 0.25)
    check(not _same(ref[390], ref[26]) and not _same(ref[390], ref[405]), 'эталонные кадры 26, 390 и 405 не различаются — тест ничего не мерит')
    sys.path.insert(0, str(ENGINE / 'tools'))
    import strip
    got = strip.frames(proj, 'demo', 13.0, 14.0, 2, 0.25)
    check(len(got) == 2, 'strip.frames 13…14 с при 2 кадр/с: %d кадров, ждали 2' % len(got))
    check(not _same(got[0], ref[26]), 'strip.frames: кадр «13,0 с» при 2 кадр/с снят на 0,87 с фильма (кадр 26)')
    check(_same(got[0], ref[390]) and _same(got[1], ref[405]), 'strip.frames при 2 кадр/с: кадры «13,0 с» и «13,5 с» — не кадры 390 и 405 фильма')
    j = _json('time-check')
    check(len(j['frames']) == 10 and j['frames'][0]['t'] == 13.0 and j['frames'][5]['t'] == 13.5,
          'strip.json: времена кадров %s' % [f['t'] for f in j['frames']])
    d = os.path.join(_state['strips'], 'time-check')
    check(_same(os.path.join(d, j['frames'][0]['file']), ref[390]), 'полоса --fps 10: кадр с подписью 13,0 с — не кадр 390 фильма')
    check(_same(os.path.join(d, j['frames'][5]['file']), ref[405]), 'полоса --fps 10: кадр с подписью 13,5 с — не кадр 405 фильма')


def test_errors_one_line_and_project_clean():
    for args, part in ((('--scene', 'nope'), 'demo-a'), (('--seam', 'demo-b:demo-a'), 'demo-a:demo-b'),
                       (('--range', '500:501'), 'вне фильма'), (('--at', '99:0.5'), 'есть: 1')):
        code, out = _strip(*args, '--no-build')
        check(code != 0 and part in out and len(out.splitlines()) == 1, '%s: ждали одну строку с «%s», вышло: %s' % (args, part, out[-300:]))
    after = _tree(_state['proj'], skip_out=True)
    check(after == _state['before'], 'strip.py изменил файлы проекта вне out/: %s' % sorted(set(after.items()) ^ set(_state['before'].items()))[:3])
    shutil.rmtree(_state['tmp'], ignore_errors=True)


if __name__ == '__main__':
    sys.exit(run_module(globals()))
