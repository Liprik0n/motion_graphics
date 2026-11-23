# -*- coding: utf-8 -*-
"""Новый проект ролика одной командой.

    python new_project.py <папка> "<название>" [--node-modules <путь>] [--copy-node-modules] [--with-fixtures]

Что делает:
  1. копирует engine/ и project/ шаблона в <папку> (без project/out, __pycache__, .env, node_modules);
     из project/ берётся только стартовый фильм (demo) и его сцены: фильмы-фикстуры возможностей движка
     (всё остальное в films/), их сцены, картинки-кадры и записи project.json, которые называют их сцены,
     остаются в шаблоне — их гоняет проверка скила (tools/check_skill.py). --with-fixtures — взять всё;
  2. кладёт node_modules в <папка>/engine/video/node_modules: ссылка (junction) на общую установку —
     ~/.motion-studio/node_modules, другая — переменная MOTION_NODE_MODULES или --node-modules (быстро,
     ничего не качается) либо копия (--copy-node-modules, а также если ссылка не вышла);
  3. ставит в project/project.json название и "template_demo": false;
  4. убеждается, что рядом с проектом лежит project/.env.example;
  5. печатает следующие шаги.

Отказывает, не тронув ничего, если <папка> непуста или общей установки нет (называет команду, которая её
ставит: <скил>/tools/setup.py install). Сам ничего не устанавливает и в сеть не ходит. Путей этой машины в
коде нет: корень шаблона берётся из расположения файла, общая установка — из домашней папки пользователя.
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
sys.path.insert(0, str(TEMPLATE / 'engine'))
import deps   # noqa: E402  общая установка Node и команда, которая её ставит

NODE_MODULES_REL = Path('engine') / 'video' / 'node_modules'
# набор Node — из engine/video/package.json (deps.NODE_PACKAGES); у пакета проверяется файл, который берёт движок
NODE_ENTRY = {'gsap': 'dist/gsap.min.js', 'hyperframes': 'bin/hyperframes.mjs', 'lottie-web': 'build/player/lottie.min.js'}
NODE_REQUIRED = tuple('%s/%s' % (p, NODE_ENTRY.get(p, 'package.json')) for p in deps.NODE_PACKAGES)
STARTER_FILMS = ('demo',)      # фильм, с которого начинается свой ролик; всё остальное в films/ шаблона — фикстуры
SETUP_COMMAND = '"%s" "%s" install' % (deps.PYTHON, TEMPLATE.parent / 'tools' / 'setup.py')   # этим же интерпретатором

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


def _load(path):
    with open(path, encoding='utf-8-sig') as fh:
        return json.load(fh)


def fixtures(project=None):
    """Что в project/ шаблона принадлежит фикстурам возможностей движка, а не стартовому фильму:
    {films, scenes, files} — имена фильмов и сцен и пути файлов от корня проекта (картинки-кадры сцен)."""
    project = Path(project or TEMPLATE / 'project')
    pj = _load(project / 'project.json')
    paths = pj.get('paths') or {}
    films_dir, scenes_dir = project / paths.get('films', 'films'), project / paths.get('scenes', 'scenes')
    films = {p.stem: _load(p) for p in sorted(films_dir.glob('*.json'))}
    keep = {s for name in STARTER_FILMS for s in (films.get(name) or {}).get('scenes', [])}
    drop_films = [name for name in films if name not in STARTER_FILMS]
    drop_scenes = sorted(p.name for p in scenes_dir.iterdir() if p.is_dir() and p.name not in keep) if scenes_dir.is_dir() else []

    def start_image(scene):
        sb = scenes_dir / scene / 'storyboard.json'
        return (_load(sb).get('start_image') if sb.exists() else None) or None
    kept_files = {start_image(s) for s in keep}
    files = sorted({f for f in map(start_image, drop_scenes) if f and f not in kept_files})
    return {'films': drop_films, 'scenes': drop_scenes, 'files': files}


def _ignore_project(skip_fixtures):
    """Что не копировать из project/ шаблона: out, кэши, .env и (skip_fixtures) фильмы, сцены и файлы фикстур."""
    root = (TEMPLATE / 'project').resolve()
    fx = fixtures(root) if skip_fixtures else {'films': [], 'scenes': [], 'files': []}
    pj = _load(root / 'project.json')
    paths = pj.get('paths') or {}
    drop = {(root / paths.get('films', 'films') / (f + '.json')).resolve() for f in fx['films']}
    drop |= {(root / paths.get('scenes', 'scenes') / s).resolve() for s in fx['scenes']}
    drop |= {(root / f).resolve() for f in fx['files']}

    def ignore(dirpath, names):
        here = Path(dirpath).resolve()
        skip = [n for n in names if n in ('__pycache__', 'node_modules', '.env') or n.endswith('.pyc')]
        if here == root:
            skip += [n for n in names if n == 'out']        # out/ шаблона в поставку не входит
        return skip + [n for n in names if (here / n) in drop]
    return ignore


def check_target(target):
    if target.exists():
        if not target.is_dir():
            raise UserError('%s существует и это не папка' % target)
        if any(target.iterdir()):
            raise UserError('папка %s не пуста — ничего не тронуто. Возьми новую или пустую папку' % target)


def check_node_modules(src):
    if not src.is_dir():
        raise UserError('нет набора Node (%s): папки %s нет — поставь общую установку: '
                        '%s (другая папка — --node-modules <путь> или переменная %s)'
                        % (', '.join(deps.NODE_PACKAGES), src, SETUP_COMMAND, deps.ENV_NODE_MODULES))
    for rel in NODE_REQUIRED:
        if not (src / rel).exists():
            raise UserError('в %s нет %s — набор Node неполный, поставь его заново: %s' % (src, rel, SETUP_COMMAND))


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


def _without_fixture_scenes(data, scenes):
    """Снять из project.json записи, которые называют сцены фикстур: исключения читаемости по элементу
    «сцена:элемент» и правила сторожа текста, написанные только для этих сцен. Остальные ключи нужны и своему ролику."""
    gone = set(scenes)
    if isinstance(data.get('legibility_except'), list):
        data['legibility_except'] = [e for e in data['legibility_except'] if str(e.get('el', '')).split(':')[0] not in gone]
    guard = data.get('text_guard')
    if isinstance(guard, dict) and isinstance(guard.get('rules'), list):
        guard['rules'] = [r for r in guard['rules'] if not r.get('scenes') or not set(r['scenes']) <= gone]
    data.pop('_fixtures_comment', None)


def patch_project_json(path, title, fixture_scenes=()):
    with open(path, encoding='utf-8-sig') as fh:
        data = json.load(fh)
    data['title'] = title
    data['template_demo'] = False
    if fixture_scenes:
        _without_fixture_scenes(data, fixture_scenes)
    with open(path, 'w', encoding='utf-8', newline='\n') as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
        fh.write('\n')


def prune_materials(project):
    """materials.json нового проекта — только строки файлов, которые в него попали (файлы фикстур не копируются)."""
    path = Path(project) / 'materials.json'
    if not path.exists():
        return
    rows = _load(path)
    rows = [r for r in rows if (Path(project) / str(r.get('file', ''))).is_file()]
    with open(path, 'w', encoding='utf-8', newline='\n') as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=2)
        fh.write('\n')


def create(target, title, node_modules=None, copy_node_modules=False, with_fixtures=False):
    """Новый проект в target. node_modules — откуда взять набор Node (None — общая установка)."""
    target = Path(target).resolve()
    title = (title or '').strip()
    if not title:
        raise UserError('название ролика пустое')
    nm_src = Path(node_modules).resolve() if node_modules else deps.shared_node_modules()
    fx = {'scenes': []} if with_fixtures else fixtures()
    check_target(target)                 # все отказы — до первой записи
    check_node_modules(nm_src)
    target.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copytree(TEMPLATE / 'engine', target / 'engine', ignore=_ignore_engine)
        shutil.copytree(TEMPLATE / 'project', target / 'project', ignore=_ignore_project(not with_fixtures))
        how = link_node_modules(nm_src, target / NODE_MODULES_REL, copy_node_modules)
        patch_project_json(target / 'project' / 'project.json', title, fx['scenes'])
        prune_materials(target / 'project')
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
    if is_link(nm):
        remove_link(nm)
    shutil.rmtree(target, ignore_errors=True)


def is_link(p):
    """Ссылка ли это (symlink или junction Windows), а не настоящая папка. Нет такого пути — False."""
    if os.path.islink(p):
        return True
    try:
        return os.name == 'nt' and bool(os.lstat(p).st_file_attributes & 0x400)   # REPARSE_POINT
    except OSError:
        return False


_is_link = is_link


def remove_link(p):
    """Снять саму ссылку node_modules, не заходя в то, на что она смотрит."""
    if not is_link(p):
        raise UserError('%s — не ссылка: настоящую папку эта команда не удаляет' % p)
    if os.name == 'nt' and not os.path.islink(p):
        os.rmdir(p)             # junction: RemoveDirectory снимает точку повторного разбора, цель не трогает
    else:
        os.unlink(p)


def next_steps(target, how):
    py = sys.executable or 'python'
    return '\n'.join([
        'Проект создан: %s (node_modules: %s)' % (target, how),
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
        'scenes/<id>/; демо-сцены demo-a, demo-b и фильм films/demo.json удали, когда появятся свои (вместе с листом',
        'demo в montage.json); куски ролика — в project/montage.json. Порчи своего фильма заводит',
        '`check.py <фильм> --red-init` (engine/video/checks/red_<фильм>.py: слой заморожен, золото на закате — рабочий',
        'минимум; свои дописываются туда же). Фикстуры возможностей движка (фильмы acts, bare,',
        'kits, styles и их сцены) остались в шаблоне: образцы полей — там, в проект их кладёт --with-fixtures.',
        'Плагины движка (действия мира, камера, помехи, отсчёт, часы) — engine/video/plugins/README.md. Безголовый Chrome — один на машину:',
        'свой скрипт с браузером запускай через engine/tools/with_chrome_lock.py.',
        'Порядок работы и ворота — motion-studio/SKILL.md; команды по этапам — template/README.md.',
    ])


def main(argv=None):
    ap = argparse.ArgumentParser(description='Новый проект ролика из шаблона motion-studio')
    ap.add_argument('folder', help='новая или пустая папка проекта')
    ap.add_argument('title', help='название ролика (в project.json: title)')
    ap.add_argument('--node-modules',
                    help='откуда взять node_modules (%s); умолчание — общая установка '
                         '~/.motion-studio/node_modules (или переменная %s)'
                         % (', '.join(deps.NODE_PACKAGES), deps.ENV_NODE_MODULES))
    ap.add_argument('--copy-node-modules', action='store_true',
                    help='копировать node_modules вместо junction')
    ap.add_argument('--with-fixtures', action='store_true',
                    help='взять и фильмы-фикстуры возможностей движка с их сценами (как в шаблоне)')
    a = ap.parse_args(argv)
    try:
        target, how = create(a.folder, a.title, a.node_modules, a.copy_node_modules, a.with_fixtures)
    except UserError as e:
        print('ОШИБКА: %s' % e, file=sys.stderr)
        return 2
    print(next_steps(target, how))
    return 0


if __name__ == '__main__':
    sys.exit(main())
