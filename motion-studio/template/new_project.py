# -*- coding: utf-8 -*-
"""Новый проект ролика одной командой.

    python new_project.py <папка> "<название>" [--node-modules <путь>] [--copy-node-modules]

Что делает:
  1. копирует engine/ и project/ шаблона в <папку> (без project/out, __pycache__, .env, node_modules);
  2. кладёт node_modules в <папка>/engine/video/node_modules: junction на --node-modules
     (быстро, ничего не качается) либо копию (--copy-node-modules, а также если junction не вышел);
     без --node-modules источник — engine/video/node_modules самого шаблона; если его нет,
     проект создаётся без node_modules и печатается, как поставить зависимости;
  3. ставит в project/project.json название и "template_demo": false;
  4. убеждается, что рядом с проектом лежит project/.env.example;
  5. печатает следующие шаги.

Отказывает, не тронув ничего, если <папка> непуста или указанного --node-modules нет.
Ничего не устанавливает из сети. Абсолютных путей нет: корень шаблона и умолчание --node-modules
(node_modules с hyperframes, gsap и puppeteer-core) берутся из расположения этого файла.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

TEMPLATE = Path(__file__).resolve().parent
NODE_MODULES_REL = Path('engine') / 'video' / 'node_modules'
DEFAULT_NODE_MODULES = TEMPLATE / NODE_MODULES_REL
NODE_REQUIRED = ('gsap/dist/gsap.min.js', 'hyperframes/bin/hyperframes.mjs')

ENV_EXAMPLE = """# Шаблон. Скопируй этот файл в .env рядом с ним (project/.env) и впиши значения.
# В коде, отчётах и логах фигурируют только ИМЕНА переменных; значения не печатаются нигде.

MINIMAX_API_KEY=
MINIMAX_GROUP_ID=
MINIMAX_VOICE_A=
MINIMAX_VOICE_B=
"""


class UserError(Exception):
    """Понятная пользователю ошибка: печатается одной строкой, код выхода 2."""


def _ignore_engine(_dir, names):
    return [n for n in names if n in ('node_modules', '__pycache__') or n.endswith('.pyc')]


def _ignore_project(dirpath, names):
    skip = [n for n in names if n in ('__pycache__', 'node_modules', '.env') or n.endswith('.pyc')]
    if Path(dirpath).resolve() == (TEMPLATE / 'project').resolve():
        skip += [n for n in names if n == 'out']        # out/ шаблона в поставку не входит
    return skip


def check_target(target):
    if target.exists():
        if not target.is_dir():
            raise UserError('%s существует и это не папка' % target)
        if any(target.iterdir()):
            raise UserError('папка %s не пуста — ничего не тронуто. Возьми новую или пустую папку' % target)


def check_node_modules(src):
    if not src.is_dir():
        raise UserError('нет node_modules: %s — укажи --node-modules <путь> '
                        '(нужны gsap и hyperframes; ничего не устанавливается)' % src)
    for rel in NODE_REQUIRED:
        if not (src / rel).exists():
            raise UserError('в %s нет %s — это не тот node_modules (нужны gsap, hyperframes)' % (src, rel))


def link_node_modules(src, dst, copy):
    """Junction (Windows) или копия. Возвращает, что получилось: 'junction' | 'copy'."""
    if not copy and os.name == 'nt':
        r = subprocess.run(['cmd', '/c', 'mklink', '/J', str(dst), str(src)],
                           capture_output=True, text=True)
        if r.returncode == 0 and dst.exists():
            return 'junction'
        print('junction не вышел (%s) — копирую node_modules' % (r.stdout + r.stderr).strip()[:200])
    elif not copy:
        try:
            os.symlink(src, dst, target_is_directory=True)
            return 'symlink'
        except OSError as e:
            print('symlink не вышел (%s) — копирую node_modules' % e)
    shutil.copytree(src, dst, symlinks=True)
    return 'copy'


def patch_project_json(path, title):
    with open(path, encoding='utf-8-sig') as fh:
        data = json.load(fh)
    data['title'] = title
    data['template_demo'] = False
    with open(path, 'w', encoding='utf-8', newline='\n') as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
        fh.write('\n')


def create(target, title, node_modules=None, copy_node_modules=False):
    """node_modules=None — умолчание шаблона; его отсутствие не отказ, а проект без node_modules."""
    target = Path(target).resolve()
    title = (title or '').strip()
    if not title:
        raise UserError('название ролика пустое')
    nm_src = Path(node_modules if node_modules is not None else DEFAULT_NODE_MODULES).resolve()
    skip_nm = node_modules is None and not nm_src.is_dir()
    check_target(target)                 # все отказы — до первой записи
    if not skip_nm:
        check_node_modules(nm_src)
    target.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copytree(TEMPLATE / 'engine', target / 'engine', ignore=_ignore_engine)
        shutil.copytree(TEMPLATE / 'project', target / 'project', ignore=_ignore_project)
        if skip_nm:
            how = 'нет'
        else:
            how = link_node_modules(nm_src, target / NODE_MODULES_REL, copy_node_modules)
        patch_project_json(target / 'project' / 'project.json', title)
        env_example = target / 'project' / '.env.example'
        if not env_example.exists():
            env_example.write_text(ENV_EXAMPLE, encoding='utf-8', newline='\n')
    except Exception:
        # неполный проект хуже отсутствующего: убрать, не заходя в junction
        remove_tree(target)
        raise
    return target, how


def remove_tree(target):
    """Снести созданное, не проходя внутрь junction node_modules."""
    nm = target / NODE_MODULES_REL
    if nm.exists() and os.path.isdir(nm) and _is_link(nm):
        if os.name == 'nt':
            subprocess.run(['cmd', '/c', 'rmdir', str(nm)], capture_output=True)
        else:
            os.unlink(nm)
    shutil.rmtree(target, ignore_errors=True)


def _is_link(p):
    if os.path.islink(p):
        return True
    return os.name == 'nt' and bool(os.lstat(p).st_file_attributes & 0x400)   # REPARSE_POINT


def next_steps(target, how):
    py = sys.executable or 'python'
    deps = []
    if how == 'нет':
        deps = ['', 'node_modules нет: в шаблоне не нашлось %s.' % DEFAULT_NODE_MODULES,
                'Поставь зависимости: cd "%s" && npm install (см. README.md в корне)'
                % (target / NODE_MODULES_REL.parent)]
    return '\n'.join([
        'Проект создан: %s (node_modules: %s)' % (target, how),
    ] + deps + [
        '',
        'Дальше (из папки проекта):',
        '  cd "%s"' % target,
        '  "%s" engine/video/build.py demo --page          # демо собирается в project/out/demo/index.html' % py,
        '  "%s" engine/video/check.py demo --page          # проверки страницы' % py,
        '  "%s" engine/tts/tts.py --estimate               # смета озвучки, без сети' % py,
        '  "%s" engine/tools/check_all.py --quick          # общий прогон проверок проекта (без --quick — полный)' % py,
        '  project/.env.example → project/.env             # только когда дойдёшь до платного синтеза',
        '',
        'Своё: project/project.json (главы, футер), tokens.json (палитра, шрифты), rows.json, voices.json,',
        'scenes/<id>/; демо-сцены demo-a, demo-b, пробы style-probe, kit-probe, фикстуры bare-*, act-* и их фильмы',
        '(films/demo.json, styles.json, kits.json, bare.json, acts.json, acts-hide.json) удали, когда появятся свои',
        '(что ещё убрать вместе с фикстурами — template/README.md); куски ролика — в project/montage.json.',
        'Плагины движка (действия мира, камера, помехи, отсчёт, часы) — engine/video/plugins/README.md. Безголовый Chrome — один на машину:',
        'свой скрипт с браузером запускай через engine/tools/with_chrome_lock.py.',
        'Порядок работы и ворота — motion-studio/SKILL.md; команды по этапам — template/README.md.',
    ])


def main(argv=None):
    ap = argparse.ArgumentParser(description='Новый проект ролика из шаблона motion-studio')
    ap.add_argument('folder', help='новая или пустая папка проекта')
    ap.add_argument('title', help='название ролика (в project.json: title)')
    ap.add_argument('--node-modules', default=None,
                    help='откуда взять node_modules (hyperframes, gsap, puppeteer-core); '
                         'умолчание — engine/video/node_modules шаблона')
    ap.add_argument('--copy-node-modules', action='store_true',
                    help='копировать node_modules вместо junction')
    a = ap.parse_args(argv)
    try:
        target, how = create(a.folder, a.title, a.node_modules, a.copy_node_modules)
    except UserError as e:
        print('ОШИБКА: %s' % e, file=sys.stderr)
        return 2
    print(next_steps(target, how))
    return 0


if __name__ == '__main__':
    sys.exit(main())
