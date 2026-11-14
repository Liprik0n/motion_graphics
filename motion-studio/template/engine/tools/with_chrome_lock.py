# -*- coding: utf-8 -*-
"""Команда под замком безголового Chrome: пока она идёт, второй такой запуск ждёт.

    python engine/tools/with_chrome_lock.py [--timeout СЕК] <команда> [аргументы]

Код выхода — код команды. Замок — engine/chrome_lock.py (одна папка на машину во временной папке системы,
другая — MOTION_CHROME_LOCK). Сборка (build.py), порчи проверок и общий прогон (check_all.py) берут тот же замок
сами вокруг каждого запуска Chrome; вложенные вызовы под этой обёрткой не ждут сами себя. Свой скрипт, который
запускает безголовый браузер (лист кадров, снимок страницы), зови только через эту обёртку.
"""
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))      # <проект>/engine
import chrome_lock  # noqa: E402


def main(argv):
    timeout = None
    if argv[:1] == ['--timeout']:
        timeout = float(argv[1])
        argv = argv[2:]
    if argv[:1] == ['--']:
        argv = argv[1:]
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    with chrome_lock.held(' '.join(argv)[:200], timeout=timeout):
        return subprocess.run(argv).returncode


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
