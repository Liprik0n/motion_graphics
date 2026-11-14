# -*- coding: utf-8 -*-
"""Ресурсы машины одной строкой — печатается перед любым рендером и кодированием.

    import resources
    print(resources.report(<папка временных кадров или выхода>))
    → «ресурсы: диск /data — свободно 48,1 ГБ · ОЗУ: свободно 18,5 из 32,0 ГБ»

Урок прошлого ролика: HyperFrames резервирует ≈ 8,3 МБ на кадр куска, пилот упёрся в 29 ГБ; место и память
называются до рендера, а не после падения (process/08-render-qa.md скила).
"""
import os
import shutil


def ram_bytes():
    """(свободно, всего) байт ОЗУ; (None, None), если узнать нечем."""
    if os.name == 'nt':
        import ctypes

        class MS(ctypes.Structure):
            _fields_ = [('dwLength', ctypes.c_ulong), ('dwMemoryLoad', ctypes.c_ulong),
                        ('ullTotalPhys', ctypes.c_ulonglong), ('ullAvailPhys', ctypes.c_ulonglong),
                        ('ullTotalPageFile', ctypes.c_ulonglong), ('ullAvailPageFile', ctypes.c_ulonglong),
                        ('ullTotalVirtual', ctypes.c_ulonglong), ('ullAvailVirtual', ctypes.c_ulonglong),
                        ('ullAvailExtendedVirtual', ctypes.c_ulonglong)]
        m = MS()
        m.dwLength = ctypes.sizeof(MS)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
            return m.ullAvailPhys, m.ullTotalPhys
        return None, None
    try:
        with open('/proc/meminfo') as fh:
            kv = dict(line.split(':', 1) for line in fh)
        return int(kv['MemAvailable'].split()[0]) * 1024, int(kv['MemTotal'].split()[0]) * 1024
    except (OSError, KeyError, ValueError):
        return None, None


def _gb(b):
    return ('%.1f' % (b / 1e9)).replace('.', ',')


def report(path='.'):
    """Строка «диск <корень пути> — свободно N ГБ · ОЗУ: свободно M из T ГБ»."""
    p = os.path.abspath(path)
    while not os.path.exists(p):
        p = os.path.dirname(p)
    du = shutil.disk_usage(p)
    drive = os.path.splitdrive(p)[0] + os.sep if os.name == 'nt' else p
    free, total = ram_bytes()
    ram = 'ОЗУ: свободно %s из %s ГБ' % (_gb(free), _gb(total)) if free is not None else 'ОЗУ: не узнать'
    return 'ресурсы: диск %s — свободно %s ГБ · %s' % (drive, _gb(du.free), ram)
