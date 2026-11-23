# -*- coding: utf-8 -*-
"""Замок безголового Chrome: на машине одновременно работает не больше одного (два разом вешали её).

    import chrome_lock
    with chrome_lock.held('build.py probe'):      # ждёт, пока замок свободен; держит, пока блок идёт
        subprocess.run(['node', 'probe_dom.mjs', ...])

    python engine/tools/with_chrome_lock.py <команда> [аргументы]    то же для любой команды целиком

Замок — папка (os.mkdir атомарен): по умолчанию `<временная папка системы>/motion-studio-chrome-lock/` — одна
на машину, общая для всех проектов на шаблоне (два проекта тоже не запустят два Chrome разом); другая — переменная
MOTION_CHROME_LOCK (тесты берут свою; проект со своим замком в папке проекта ставит её сам). В папке owner.json: pid, подпись, время, token. Замок процесса, которого точно нет, снимается
атомарно: папка переименовывается в уникальное `<имя>.stale-…` и удаляется, только если это та же папка с тем же
владельцем; иначе возвращается на место. Процесс владельца не открылся (отказ в доступе) — владелец жив, если
сверка не говорит обратного: в owner.json записано имя программы владельца (exe), и когда под его pid уже
работает другая программа (pid переиспользован системным процессом), замок считается брошенным.
Держатель снимает только свой замок (token). Замки старого вида (без token) понимаются так же.
Ожидание ограничено: held() без timeout ждёт wait_limit() секунд — MOTION_CHROME_LOCK_TIMEOUT, иначе
DEFAULT_TIMEOUT_SEC; по истечении — LockTimeout со строкой «кто держит»: pid, метка, с какого времени.
Точки входа (build.py, check_all.py, with_chrome_lock.py) ловят его и выходят этой строкой, без трассировки.
Вложенность: держатель кладёт в окружение MOTION_CHROME_LOCK_HELD = путь замка; дочерние процессы
(сборка под with_chrome_lock зовёт промер) видят, что замок уже их, и не ждут сами себя.
"""
import contextlib
import json
import os
import shutil
import sys
import tempfile
import time
import uuid
from pathlib import Path

ENV_PATH = 'MOTION_CHROME_LOCK'
ENV_HELD = 'MOTION_CHROME_LOCK_HELD'
ENV_TIMEOUT = 'MOTION_CHROME_LOCK_TIMEOUT'
DEFAULT_TIMEOUT_SEC = 3600.0   # предел ожидания: дольше часа законный владелец (рендер фильма) замок не держит
DEFAULT = Path(tempfile.gettempdir()) / 'motion-studio-chrome-lock'     # один замок на машину
POLL_SEC = 0.25
NOTE_EVERY_SEC = 30.0
FRESH_SEC = 10.0          # папка без owner.json моложе этого — замок только что взят, не чужой мусор


class LockTimeout(TimeoutError):
    """Замок не освободился за предел ожидания. owner — owner.json владельца (может быть пустым)."""

    def __init__(self, waited, owner):
        self.waited, self.owner = waited, dict(owner or {})
        super().__init__(describe(self.owner, waited))


def lock_path():
    return Path(os.environ.get(ENV_PATH) or DEFAULT).resolve()


def wait_limit():
    """Сколько секунд ждать замок, если вызов не назвал предел сам: MOTION_CHROME_LOCK_TIMEOUT, иначе умолчание."""
    raw = os.environ.get(ENV_TIMEOUT)
    if not raw:
        return DEFAULT_TIMEOUT_SEC
    try:
        sec = float(raw.replace(',', '.'))
    except ValueError:
        sec = -1.0
    if sec <= 0:
        raise SystemExit('%s=%r — нужно число секунд больше нуля (предел ожидания замка Chrome)' % (ENV_TIMEOUT, raw))
    return sec


def describe(owner, waited):
    """Строка об истёкшем ожидании: кто держит замок и что с этим делать."""
    pid, label, since = owner.get('pid'), owner.get('label'), owner.get('since')
    if pid is None:
        who = 'владелец не назван (в папке замка нет owner.json)'
    else:
        when = time.strftime('%H:%M:%S', time.localtime(float(since))) if since else '?'
        who = 'его держит pid %s («%s», с %s)' % (pid, label, when)
    return ('замок Chrome занят дольше %.0f с: %s. Дождись его или заверши зависший процесс — замок мёртвого '
            'владельца снимается сам; папка замка: %s; свой предел ожидания — %s=<секунд>'
            % (waited, who, lock_path(), ENV_TIMEOUT))


def _image_name(pid):
    """Имя программы процесса pid (Windows: снимок процессов, работает и для тех, что не открыть) или None."""
    if os.name != 'nt':
        try:
            with open('/proc/%d/comm' % pid, encoding='utf-8') as fh:
                return fh.read().strip() or None
        except OSError:
            return None
    import ctypes
    from ctypes import wintypes

    class Entry(ctypes.Structure):
        _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD), ('th32ProcessID', wintypes.DWORD),
                    ('th32DefaultHeapID', ctypes.c_void_p), ('th32ModuleID', wintypes.DWORD),
                    ('cntThreads', wintypes.DWORD), ('th32ParentProcessID', wintypes.DWORD),
                    ('pcPriClassBase', ctypes.c_long), ('dwFlags', wintypes.DWORD), ('szExeFile', ctypes.c_wchar * 260)]
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    k.Process32FirstW.argtypes = k.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(Entry))
    k.CloseHandle.argtypes = (wintypes.HANDLE,)
    snap = k.CreateToolhelp32Snapshot(0x2, 0)              # TH32CS_SNAPPROCESS
    if not snap or snap == wintypes.HANDLE(-1).value:
        return None
    try:
        e = Entry()
        e.dwSize = ctypes.sizeof(Entry)
        more = k.Process32FirstW(snap, ctypes.byref(e))
        while more:
            if e.th32ProcessID == pid:
                return e.szExeFile or None
            more = k.Process32NextW(snap, ctypes.byref(e))
        return None
    finally:
        k.CloseHandle(snap)


def _alive(pid, since=None, exe=None):
    """Жив ли владелец. Сомнение — в пользу живого: снятый живой замок пускает второй Chrome, а это хуже ожидания.
    Мёртв — только когда точно: процесса с таким pid нет, он завершён, pid занят процессом, начатым после
    since (pid переиспользован), или — когда процесс не открыть — под этим pid работает не та программа, что
    записана владельцем (exe)."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        k = ctypes.WinDLL('kernel32', use_last_error=True)
        k.OpenProcess.restype = wintypes.HANDLE
        k.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        k.CloseHandle.argtypes = (wintypes.HANDLE,)
        h = k.OpenProcess(0x1000, False, pid)              # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            if ctypes.get_last_error() == 87:              # ERROR_INVALID_PARAMETER — такого процесса нет
                return False
            name = _image_name(pid) if exe else None       # отказ в доступе: процесс есть — сверить, тот ли
            return not (name and name.lower() != str(exe).lower())
        try:
            code = wintypes.DWORD()
            if not k.GetExitCodeProcess(h, ctypes.byref(code)):
                return True
            if code.value != 259:                          # STILL_ACTIVE
                return False
            if since:
                c, e, kt, ut = (wintypes.FILETIME() for _ in range(4))
                if k.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e), ctypes.byref(kt), ctypes.byref(ut)):
                    born = ((c.dwHighDateTime << 32) | c.dwLowDateTime) / 1e7 - 11644473600.0
                    if born > float(since) + 2.0:          # процесс начат после того, как замок взят, — чужой pid
                        return False
            return True
        finally:
            k.CloseHandle(h)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except OSError:
        return True                                        # PermissionError: процесс есть, он чужой


def _owner(d):
    try:
        with open(d / 'owner.json', encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _look(d):
    """Что видно в папке замка сейчас: (id папки, её mtime, owner.json или None); папки нет — None."""
    try:
        st = os.stat(d)
    except OSError:
        return None
    return (st.st_dev, st.st_ino), st.st_mtime, _owner(d)


def _stale(seen):
    """Замок брошен: хозяин умер, или папка без owner.json давно."""
    if seen is None:
        return False
    _, mtime, ow = seen
    if ow is None:
        return time.time() - mtime > FRESH_SEC
    return not _alive(ow.get('pid'), ow.get('since'), ow.get('exe'))


def _clear_stale(d, seen):
    """Снять брошенный замок атомарно: переименовать папку в уникальное имя и удалить, только если это та самая
    папка с тем же владельцем, что была признана брошенной. Иначе (замок тем временем сняли и взяли заново) —
    вернуть её на место нетронутой. True — снят."""
    grave = d.with_name('%s.stale-%d-%s' % (d.name, os.getpid(), uuid.uuid4().hex[:12]))
    try:
        os.rename(d, grave)
    except OSError:
        return False                    # папки уже нет или она занята — решим заново на следующем круге
    now = _look(grave)
    if now is None or now[0] != seen[0] or now[2] != seen[2]:
        try:
            os.rename(grave, d)         # чужая свежая папка — на место как была
        except OSError:
            pass                        # d за это мгновение занял третий; grave — живой замок, удалять нельзя
        return False
    shutil.rmtree(grave, ignore_errors=True)
    return True


def _remove(d):
    try:
        (d / 'owner.json').unlink()
    except OSError:
        pass
    try:
        d.rmdir()
    except OSError:
        pass


def _release(d, token):
    """Снять свой замок: только если в папке наш owner.json (token); чужой не трогать."""
    ow = _owner(d)
    if ow is None or ow.get('token') != token:
        return                          # папки нет или она чужая; папка без owner.json станет брошенной сама
    _remove(d)


@contextlib.contextmanager
def held(label, timeout=None, out=None):
    """Взять замок (ждать, пока свободен) на время блока. timeout — секунд ожидания; None — предел по умолчанию
    (wait_limit()). Не дождался — LockTimeout с меткой и pid владельца."""
    out = out or sys.stderr
    if timeout is None:
        timeout = wait_limit()
    d = lock_path()
    if os.environ.get(ENV_HELD) == str(d):
        yield d                         # замок уже держит наш предок
        return
    d.parent.mkdir(parents=True, exist_ok=True)
    t0, last_note = time.time(), 0.0
    token = uuid.uuid4().hex
    while True:
        try:
            os.mkdir(d)
            with open(d / 'owner.json', 'w', encoding='utf-8') as fh:
                json.dump({'pid': os.getpid(), 'label': label, 'since': time.time(), 'token': token,
                           'exe': os.path.basename(sys.executable or '')}, fh, ensure_ascii=False)
            break
        except FileExistsError:
            seen = _look(d)
            if _stale(seen):
                ow = seen[2] or {}
                if _clear_stale(d, seen):
                    print('замок Chrome: снят брошенный (pid %s, %s)' % (ow.get('pid'), ow.get('label')),
                          file=out, flush=True)
                    continue
            now = time.time()
            if now - t0 > timeout:
                raise LockTimeout(timeout, _owner(d))
            if now - last_note >= NOTE_EVERY_SEC:
                ow = _owner(d) or {}
                print('замок Chrome занят (pid %s: %s) — жду' % (ow.get('pid'), ow.get('label')), file=out, flush=True)
                last_note = now
            time.sleep(POLL_SEC)
        except OSError:
            time.sleep(POLL_SEC)        # папку унесли между mkdir и записью owner.json — берём заново
    prev = os.environ.get(ENV_HELD)
    os.environ[ENV_HELD] = str(d)
    try:
        yield d
    finally:
        if prev is None:
            os.environ.pop(ENV_HELD, None)
        else:
            os.environ[ENV_HELD] = prev
        _release(d, token)
