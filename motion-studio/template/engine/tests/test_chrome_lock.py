# -*- coding: utf-8 -*-
"""Замок безголового Chrome: engine/tools/with_chrome_lock.py <команда> — второй ждёт, пока первый не закончит.

    python engine/tests/test_chrome_lock.py

Ожидания: «не даёт двум безголовым Chrome работать разом (второй ждёт)»; вложенный вызов
(сборка под замком зовёт промер) не виснет; замок умершего процесса не держит вечно.
Из задания: ожидание ограничено и без --timeout (MOTION_CHROME_LOCK_TIMEOUT, иначе предел по
умолчанию); по истечении — одна строка с меткой и pid владельца, без трассировки; build.py выходит так же.
Каждый тест берёт свою папку замка (MOTION_CHROME_LOCK), общий замок проекта не трогается.
"""
import json
import os
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import ENGINE, PY, check, run_module   # noqa: E402

TOOL = ENGINE / 'tools' / 'with_chrome_lock.py'
HOLD = r'''
import sys, time
log, tag, sec = sys.argv[1], sys.argv[2], float(sys.argv[3])
with open(log, 'a') as fh: fh.write('%s start %.4f\n' % (tag, time.time()))
time.sleep(sec)
with open(log, 'a') as fh: fh.write('%s end %.4f\n' % (tag, time.time()))
'''


def _env(lock):
    env = dict(os.environ)
    env['MOTION_CHROME_LOCK'] = lock
    env.pop('MOTION_CHROME_LOCK_HELD', None)
    return env


def _intervals(log):
    iv = {}
    for line in open(log, encoding='utf-8'):
        tag, kind, t = line.split()
        iv.setdefault(tag, {})[kind] = float(t)
    return iv


def test_second_waits():
    tmp = tempfile.mkdtemp(prefix='lock_test_')
    hold, log, lock = os.path.join(tmp, 'hold.py'), os.path.join(tmp, 'log.txt'), os.path.join(tmp, 'lock')
    open(hold, 'w').write(HOLD)
    check(TOOL.exists(), 'нет %s' % TOOL)
    a = subprocess.Popen([PY, str(TOOL), PY, hold, log, 'A', '1.5'], env=_env(lock))
    time.sleep(0.3)
    b = subprocess.Popen([PY, str(TOOL), PY, hold, log, 'B', '0.2'], env=_env(lock))
    check(a.wait(30) == 0 and b.wait(30) == 0, 'команды под замком вернули не 0')
    iv = _intervals(log)
    check(set(iv) == {'A', 'B'}, 'обе команды должны отработать: %s' % iv)
    first, second = sorted(iv.values(), key=lambda x: x['start'])
    check(second['start'] >= first['end'] - 0.01,
          'интервалы перекрылись: первый %.3f–%.3f, второй начал в %.3f' % (first['start'], first['end'], second['start']))
    check(not os.path.exists(lock), 'замок не снят после работы: %s' % lock)


def test_exit_code_passes_through():
    tmp = tempfile.mkdtemp(prefix='lock_test_')
    r = subprocess.run([PY, str(TOOL), PY, '-c', 'import sys; sys.exit(7)'], env=_env(os.path.join(tmp, 'lock')))
    check(r.returncode == 7, 'код выхода команды должен пройти насквозь: %s' % r.returncode)


def test_nested_does_not_hang():
    tmp = tempfile.mkdtemp(prefix='lock_test_')
    lock = os.path.join(tmp, 'lock')
    inner = [PY, str(TOOL), PY, '-c', 'print("inner")']
    r = subprocess.run([PY, str(TOOL)] + inner, env=_env(lock), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    check(r.returncode == 0 and 'inner' in r.stdout, 'вложенный вызов под тем же замком: %s %s' % (r.returncode, r.stderr[-300:]))


def test_stale_lock_of_dead_process_is_taken():
    tmp = tempfile.mkdtemp(prefix='lock_test_')
    lock = os.path.join(tmp, 'lock')
    dead = subprocess.Popen([PY, '-c', 'pass'])
    dead.wait()
    os.makedirs(lock)
    with open(os.path.join(lock, 'owner.json'), 'w', encoding='utf-8') as fh:
        json.dump({'pid': dead.pid, 'label': 'упавший', 'since': time.time() - 60}, fh)
    r = subprocess.run([PY, str(TOOL), PY, '-c', 'print("got")'], env=_env(lock), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    check(r.returncode == 0 and 'got' in r.stdout, 'замок мёртвого процесса должен сниматься: %s' % r.stderr[-300:])


def _unopenable_pid():
    """Живой процесс, который нам не открыть (отказ в доступе): System, smss, csrss… Нет такого — None."""
    if os.name != 'nt':
        return 1                                   # init: os.kill(1, 0) без прав — PermissionError
    import ctypes
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.OpenProcess.restype = ctypes.c_void_p
    for pid in (4, 8):
        h = k.OpenProcess(0x1000, False, pid)
        if h:
            k.CloseHandle(ctypes.c_void_p(h))
        elif ctypes.get_last_error() == 5:         # ERROR_ACCESS_DENIED
            return pid
    out = subprocess.run(['tasklist', '/fo', 'csv', '/nh'], capture_output=True, text=True, errors='replace').stdout
    for line in out.splitlines():
        parts = line.split('","')
        if len(parts) > 1 and parts[1].isdigit():
            pid = int(parts[1])
            h = k.OpenProcess(0x1000, False, pid)
            if h:
                k.CloseHandle(ctypes.c_void_p(h))
            elif ctypes.get_last_error() == 5:
                return pid
    return None


def test_owner_we_cannot_open_is_alive():
    """OpenProcess отказал в доступе — владелец не «мёртв», его замок не снимается."""
    pid = _unopenable_pid()
    if pid is None:
        print('  skip test_owner_we_cannot_open_is_alive: нет процесса с отказом в доступе (запуск с правами?)')
        return
    tmp = tempfile.mkdtemp(prefix='lock_test_')
    lock = os.path.join(tmp, 'lock')
    os.makedirs(lock)
    owner = {'pid': pid, 'label': 'чужой живой', 'since': time.time()}
    with open(os.path.join(lock, 'owner.json'), 'w', encoding='utf-8') as fh:
        json.dump(owner, fh)
    r = subprocess.run([PY, str(TOOL), '--timeout', '1', PY, '-c', 'print("got")'], env=_env(lock), capture_output=True,
                       text=True, encoding='utf-8', errors='replace', timeout=30)
    check(r.returncode != 0 and 'got' not in r.stdout,
          'владелец pid %d не открывается (отказ в доступе) — он жив, замок не взят: код %d, %s' % (pid, r.returncode, r.stdout))
    check(json.load(open(os.path.join(lock, 'owner.json'), encoding='utf-8')) == owner, 'чужой живой замок тронут')


def test_owner_pid_taken_by_other_program_is_stale():
    """Сверка владельца: замок записал интерпретатор (owner.json exe), а его pid теперь у чужой программы, которую
    нам даже не открыть, — владелец мёртв, замок снимается, а не держит очередь до предела."""
    pid = _unopenable_pid()
    if pid is None or os.name != 'nt':
        print('  skip test_owner_pid_taken_by_other_program_is_stale: нет процесса с отказом в доступе')
        return
    tmp = tempfile.mkdtemp(prefix='lock_test_')
    lock = os.path.join(tmp, 'lock')
    os.makedirs(lock)
    owner = {'pid': pid, 'label': 'давно упал', 'since': time.time(), 'exe': 'net-takoj-programmy.exe'}
    with open(os.path.join(lock, 'owner.json'), 'w', encoding='utf-8') as fh:
        json.dump(owner, fh, ensure_ascii=False)
    r = subprocess.run([PY, str(TOOL), '--timeout', '3', PY, '-c', 'print("got")'], env=_env(lock), capture_output=True,
                       text=True, encoding='utf-8', errors='replace', timeout=30)
    check(r.returncode == 0 and 'got' in r.stdout,
          'pid %d занят чужой программой, а замок не снят: код %d, %s' % (pid, r.returncode, r.stderr[-300:]))


def test_new_lock_records_program():
    """held() пишет в owner.json имя своей программы — по нему и идёт сверка."""
    tmp = tempfile.mkdtemp(prefix='lock_test_')
    lock = os.path.join(tmp, 'lock')
    code = 'import json, os; print(json.load(open(os.path.join(os.environ["MOTION_CHROME_LOCK"], "owner.json"), encoding="utf-8")).get("exe"))'
    r = subprocess.run([PY, str(TOOL), PY, '-c', code], env=_env(lock), capture_output=True, text=True, encoding='utf-8',
                       errors='replace', timeout=30)
    check(r.returncode == 0 and r.stdout.strip().lower() == os.path.basename(PY).lower(),
          'в owner.json нет имени программы владельца: %r' % r.stdout.strip())


def test_stale_removal_spares_lock_retaken_meanwhile():
    """Ждущий решил «брошен», а владелец тем временем снял замок и взял заново — свежий замок не стирается."""
    sys.path.insert(0, str(ENGINE))
    import chrome_lock
    import shutil
    tmp = tempfile.mkdtemp(prefix='lock_test_')
    lock = os.path.join(tmp, 'lock')
    dead = subprocess.Popen([PY, '-c', 'pass'])
    dead.wait()
    os.makedirs(lock)
    with open(os.path.join(lock, 'owner.json'), 'w', encoding='utf-8') as fh:
        json.dump({'pid': dead.pid, 'label': 'упавший', 'since': time.time() - 60}, fh)
    fresh = {'pid': os.getpid(), 'label': 'взял заново', 'since': time.time()}
    real, swapped = chrome_lock._alive, []

    def racing_alive(pid, *a, **kw):
        if not swapped:                            # пока ждущий решал, старый замок сняли и взяли заново
            swapped.append(1)
            shutil.rmtree(lock)
            os.mkdir(lock)
            with open(os.path.join(lock, 'owner.json'), 'w', encoding='utf-8') as fh:
                json.dump(fresh, fh)
            return False                           # ответ — про старого, мёртвого владельца
        return real(pid, *a, **kw)

    old_env = {k: os.environ.get(k) for k in ('MOTION_CHROME_LOCK', 'MOTION_CHROME_LOCK_HELD')}
    os.environ['MOTION_CHROME_LOCK'] = lock
    os.environ.pop('MOTION_CHROME_LOCK_HELD', None)
    chrome_lock._alive = racing_alive
    got = False
    try:
        with chrome_lock.held('ждущий', timeout=1.0, out=open(os.devnull, 'w', encoding='utf-8')):
            got = True
    except TimeoutError:
        pass
    finally:
        chrome_lock._alive = real
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    check(swapped, 'гонка не разыграна: проверка живости не вызвана')
    check(not got, 'ждущий взял замок, который владелец только что взял заново — замок достался двоим')
    check(os.path.isdir(lock) and json.load(open(os.path.join(lock, 'owner.json'), encoding='utf-8')) == fresh,
          'свежий замок владельца стёрт или подменён')
    left = [n for n in os.listdir(tmp) if n != 'lock']
    check(not left, 'после снятия остался мусор рядом с замком: %s' % left)


def _held_by_live(tmp, label='чужая сборка'):
    """Замок, который держит живой процесс (этот тест): папка и owner.json, как их пишет held()."""
    lock = os.path.join(tmp, 'lock')
    os.makedirs(lock)
    owner = {'pid': os.getpid(), 'label': label, 'since': time.time(), 'token': 'test'}
    with open(os.path.join(lock, 'owner.json'), 'w', encoding='utf-8') as fh:
        json.dump(owner, fh, ensure_ascii=False)
    return lock, owner


def test_wait_is_limited_without_flag():
    """Ожидание ограничено само: без --timeout предел берётся из MOTION_CHROME_LOCK_TIMEOUT."""
    tmp = tempfile.mkdtemp(prefix='lock_test_')
    lock, owner = _held_by_live(tmp)
    env = _env(lock)
    env['MOTION_CHROME_LOCK_TIMEOUT'] = '1'
    try:
        r = subprocess.run([PY, str(TOOL), PY, '-c', 'print("got")'], env=env, capture_output=True, text=True,
                           encoding='utf-8', errors='replace', timeout=20)
    except subprocess.TimeoutExpired:
        check(False, 'ожидание замка без --timeout не кончилось за 20 с при пределе 1 с')
    out = r.stdout + r.stderr
    check(r.returncode != 0 and 'got' not in r.stdout, 'замок живого владельца взят или код 0: %s' % out[-300:])
    check(str(owner['pid']) in out and owner['label'] in out, 'строка об истечении не называет pid и метку владельца: %s' % out[-300:])
    check('Traceback' not in out, 'истечение ожидания — трассировкой: %s' % out[-400:])
    check(json.load(open(os.path.join(lock, 'owner.json'), encoding='utf-8')) == owner, 'чужой живой замок тронут')


def test_default_limit_is_finite():
    """Предел по умолчанию — конечное число секунд; переменная его переопределяет, мусор в ней — отказ с именем."""
    sys.path.insert(0, str(ENGINE))
    import chrome_lock
    old = os.environ.pop('MOTION_CHROME_LOCK_TIMEOUT', None)
    try:
        lim = chrome_lock.wait_limit()
        check(isinstance(lim, float) and 0 < lim < float('inf'), 'предел ожидания по умолчанию не конечен: %r' % lim)
        os.environ['MOTION_CHROME_LOCK_TIMEOUT'] = '7.5'
        check(chrome_lock.wait_limit() == 7.5, 'MOTION_CHROME_LOCK_TIMEOUT не переопределяет предел')
        os.environ['MOTION_CHROME_LOCK_TIMEOUT'] = 'долго'
        try:
            chrome_lock.wait_limit()
            check(False, 'мусор в MOTION_CHROME_LOCK_TIMEOUT принят молча')
        except SystemExit as e:
            check('MOTION_CHROME_LOCK_TIMEOUT' in str(e), 'отказ не называет переменную: %s' % e)
    finally:
        os.environ.pop('MOTION_CHROME_LOCK_TIMEOUT', None)
        if old is not None:
            os.environ['MOTION_CHROME_LOCK_TIMEOUT'] = old


def test_build_exits_with_owner_line():
    """build.py, не дождавшись замка, выходит одной строкой с меткой и pid владельца. Chrome не запускается:
    до него дело не доходит (страница собирается без браузера, промер ждёт замок)."""
    import shutil
    tmp = tempfile.mkdtemp(prefix='lock_test_')
    try:
        proj = os.path.join(tmp, 'project')
        shutil.copytree(ENGINE.parent / 'project', proj, ignore=shutil.ignore_patterns('out', '.env', '__pycache__'))
        lock, owner = _held_by_live(tmp, 'долгий рендер')
        env = _env(lock)
        env['MOTION_CHROME_LOCK_TIMEOUT'] = '1'
        env.pop('MOTION_PROJECT', None)
        r = subprocess.run([PY, str(ENGINE / 'video' / 'build.py'), 'demo', '--page', '--project', proj,
                            '--out-dir', os.path.join(tmp, 'page')], env=env, capture_output=True, text=True,
                           encoding='utf-8', errors='replace', timeout=120)
        out = r.stdout + r.stderr
        check(r.returncode != 0, 'build.py под чужим замком вернул 0')
        check('замок Chrome' in out and str(owner['pid']) in out and owner['label'] in out,
              'build.py не назвал владельца замка: %s' % out[-400:])
        check('Traceback' not in out, 'build.py вышел трассировкой: %s' % out[-600:])
        check(not os.path.exists(os.path.join(tmp, 'page', 'probe.json')), 'промер прошёл под чужим замком')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(run_module(globals()))
