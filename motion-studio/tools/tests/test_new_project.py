# -*- coding: utf-8 -*-
"""Новый проект из шаблона: template/new_project.py.

    python tools/tests/test_new_project.py

Ожидания — из задания:
  - без --node-modules проект ссылается на общую установку (~/.motion-studio/node_modules, переменная
    MOTION_NODE_MODULES её переопределяет); абсолютного пути этой машины в коде шаблона нет;
  - общей установки нет — отказ называет её и команду установки, папка проекта не создаётся;
  - в свежий проект идёт только стартовый фильм (demo) и его сцены: фикстуры возможностей движка
    (films/acts, acts-hide, bare, kits, styles и их сцены) остаются в шаблоне, записи project.json, которые
    называют сцены фикстур, сняты; --with-fixtures кладёт всё как в шаблоне;
  - общий прогон свежего проекта (check_all.py --list) не называет ни самотестов движка, ни фильмов-фикстур.
Chrome и сеть не нужны: общая установка подменяется папкой-пустышкой с нужными файлами.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SKILL = Path(__file__).resolve().parents[2]
TEMPLATE = SKILL / 'template'
sys.path.insert(0, str(TEMPLATE / 'engine' / 'tests'))
from _util import PY, check, run_module   # noqa: E402

sys.path.insert(0, str(TEMPLATE))
TOOL = TEMPLATE / 'new_project.py'
FIXTURE_FILMS = ['acts', 'acts-hide', 'bare', 'kits', 'styles']        #
FIXTURE_SCENES = ['act-sign', 'act-stage', 'bare-start', 'bare-timer', 'kit-probe', 'style-probe']
ENGINE_TESTS = ['test_pieces', 'test_pose', 'test_project', 'test_start_frame', 'test_tts', 'test_audio',
                'test_chrome_lock', 'test_assemble', 'test_wallclock', 'test_resources']


# набор Node движка — четыре пакета из template/engine/video/package.json (lottie-web — проигрыватель плагина Lottie)
FAKE_SET = ('gsap/dist/gsap.min.js', 'gsap/package.json', 'hyperframes/bin/hyperframes.mjs', 'hyperframes/package.json',
            'puppeteer-core/package.json', 'lottie-web/build/player/lottie.min.js', 'lottie-web/package.json')


def _fake_shared(tmp, without=()):
    nm = Path(tmp) / 'shared' / 'node_modules'
    for rel in FAKE_SET:
        if rel.split('/')[0] in without:
            continue
        (nm / rel).parent.mkdir(parents=True, exist_ok=True)
        (nm / rel).write_text('// пустышка теста\n', encoding='utf-8')
    return nm


def _env(nm):
    env = dict(os.environ, MOTION_NODE_MODULES=str(nm), PYTHONIOENCODING='utf-8')
    env.pop('MOTION_PROJECT', None)
    return env


def _create(tmp, *flags, nm=None):
    nm = nm or _fake_shared(tmp)
    target = Path(tmp) / 'proj'
    r = subprocess.run([PY, str(TOOL), str(target), 'Проба'] + list(flags), env=_env(nm), capture_output=True, text=True,
                       encoding='utf-8', errors='replace', timeout=120)
    return target, nm, r


def _cleanup(tmp):
    import new_project
    for nm in Path(tmp).glob('*/engine/video/node_modules'):
        if new_project._is_link(nm):
            subprocess.run(['cmd', '/c', 'rmdir', str(nm)], capture_output=True) if os.name == 'nt' else os.unlink(nm)
    shutil.rmtree(tmp, ignore_errors=True)


def test_default_node_modules_is_shared_install():
    tmp = tempfile.mkdtemp(prefix='newproj_test_')
    try:
        target, nm, r = _create(tmp)
        check(r.returncode == 0, 'проект без --node-modules не создан: %s' % (r.stdout + r.stderr)[-400:])
        link = target / 'engine' / 'video' / 'node_modules'
        check((link / 'gsap' / 'dist' / 'gsap.min.js').exists(), 'в проекте нет набора Node общей установки')
        check(os.path.samefile(link, nm), 'node_modules проекта — не общая установка: %s' % os.path.realpath(link))
    finally:
        _cleanup(tmp)


def test_no_machine_path_in_template_code():
    bad = []
    for p in TEMPLATE.rglob('*'):
        if not p.is_file() or 'node_modules' in p.parts or 'out' in p.parts or '__pycache__' in p.parts:
            continue
        if p.suffix.lower() not in ('.py', '.mjs', '.js', '.json', '.md', '.html', '.css'):
            continue
        text = p.read_text(encoding='utf-8', errors='replace').replace('\\\\', '\\').replace('/', '\\')
        if 'Q:\\\\rabochaya-baza' in text:
            bad.append(str(p.relative_to(TEMPLATE)))
    check(not bad, 'абсолютный путь этой машины (Q:\\\\rabochaya-baza…) в шаблоне: %s' % ', '.join(bad))


def test_missing_shared_install_names_command():
    tmp = tempfile.mkdtemp(prefix='newproj_test_')
    try:
        target, nm, r = _create(tmp, nm=Path(tmp) / 'net' / 'node_modules')
        out = r.stdout + r.stderr
        check(r.returncode != 0 and not target.exists(), 'без общей установки проект создан или код 0')
        check('setup.py' in out and 'install' in out and str(nm) in out, 'отказ не называет папку и команду установки: %s' % out[-400:])
        check('Traceback' not in out, 'отказ — трассировкой: %s' % out[-400:])
        check('"%s"' % PY in out, 'команда установки зовёт не этот интерпретатор (%s): %s' % (PY, out[-400:]))
    finally:
        _cleanup(tmp)


def test_shared_install_without_lottie_is_refused():
    """Набор Node — четыре пакета из package.json шаблона: общая установка без lottie-web неполная, проект не создаётся."""
    tmp = tempfile.mkdtemp(prefix='newproj_test_')
    try:
        target, nm, r = _create(tmp, nm=_fake_shared(tmp, without=('lottie-web',)))
        out = r.stdout + r.stderr
        check(r.returncode != 0 and not target.exists(), 'общая установка без lottie-web: проект создан или код 0')
        check('lottie-web' in out and 'setup.py' in out, 'отказ не называет lottie-web и команду установки: %s' % out[-400:])
    finally:
        _cleanup(tmp)


def test_fresh_project_has_only_starter_film():
    tmp = tempfile.mkdtemp(prefix='newproj_test_')
    try:
        target, nm, r = _create(tmp)
        check(r.returncode == 0, 'проект не создан: %s' % (r.stdout + r.stderr)[-400:])
        proj = target / 'project'
        films = sorted(p.stem for p in (proj / 'films').glob('*.json'))
        check(films == ['demo'], 'в свежем проекте не только стартовый фильм: %s' % films)
        scenes = sorted(p.name for p in (proj / 'scenes').iterdir())
        check(scenes == ['demo-a', 'demo-b'], 'в свежем проекте сцены фикстур: %s' % scenes)
        text = (proj / 'project.json').read_text(encoding='utf-8')
        named = [s for s in FIXTURE_SCENES if s in text]
        check(not named, 'project.json свежего проекта называет сцены фикстур: %s' % named)
        pj = json.loads(text)
        check(pj['title'] == 'Проба' and pj['template_demo'] is False, 'название и template_demo не поставлены')
        check(pj.get('wall_clock') and pj.get('fonts') and pj['text_guard']['rules'], 'сняты ключи, которые нужны и своему ролику')
        check(not (proj / 'assets' / 'start-frame.png').exists(), 'картинка-кадр фикстуры осталась в свежем проекте')
        check((TEMPLATE / 'project' / 'films' / 'acts.json').exists() and (TEMPLATE / 'project' / 'scenes' / 'kit-probe').is_dir(),
              'фикстуры пропали из самого шаблона')
    finally:
        _cleanup(tmp)


def test_with_fixtures_copies_template_as_is():
    tmp = tempfile.mkdtemp(prefix='newproj_test_')
    try:
        target, nm, r = _create(tmp, '--with-fixtures')
        check(r.returncode == 0, 'проект --with-fixtures не создан: %s' % (r.stdout + r.stderr)[-400:])
        films = sorted(p.stem for p in (target / 'project' / 'films').glob('*.json'))
        check(set(FIXTURE_FILMS) <= set(films) and 'demo' in films, '--with-fixtures не положил фикстуры: %s' % films)
        check((target / 'project' / 'scenes' / 'act-stage').is_dir() and (target / 'project' / 'assets' / 'start-frame.png').exists(),
              '--with-fixtures не положил сцены и картинку фикстур')
        check('act-sign' in (target / 'project' / 'project.json').read_text(encoding='utf-8'), '--with-fixtures снял записи фикстур')
    finally:
        _cleanup(tmp)


def test_remove_link_spares_target():
    """Снимается только сама ссылка: то, на что она смотрела (общий набор), остаётся целым; настоящую папку
    команда не удаляет вовсе."""
    import new_project
    tmp = tempfile.mkdtemp(prefix='newproj_test_')
    try:
        nm = _fake_shared(tmp)
        link = Path(tmp) / 'link'
        how = new_project.link_node_modules(nm, link, copy=False)
        check(how in ('junction', 'symlink') and new_project.is_link(link), 'ссылка не создана: %s' % how)
        new_project.remove_link(link)
        check(not os.path.lexists(link), 'ссылка не снята')
        check((nm / 'gsap' / 'dist' / 'gsap.min.js').exists() and (nm / 'hyperframes' / 'bin' / 'hyperframes.mjs').exists(),
              'вместе со ссылкой удалено то, на что она смотрела')
        try:
            new_project.remove_link(nm)
            check(False, 'remove_link согласилась удалить настоящую папку')
        except new_project.UserError:
            pass
        check(nm.is_dir(), 'настоящая папка тронута')
    finally:
        _cleanup(tmp)


def test_fresh_check_all_has_no_engine_selftests():
    tmp = tempfile.mkdtemp(prefix='newproj_test_')
    try:
        target, nm, r = _create(tmp)
        check(r.returncode == 0, 'проект не создан: %s' % (r.stdout + r.stderr)[-400:])
        r = subprocess.run([PY, str(target / 'engine' / 'tools' / 'check_all.py'), '--list'], env=_env(nm), cwd=str(target),
                           capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120)
        out = r.stdout + r.stderr
        check(r.returncode == 0 and 'demo: сборка --page' in out, 'план свежего проекта не напечатан: %s' % out[-400:])
        alien = [t for t in ENGINE_TESTS if t in out] + [f for f in FIXTURE_FILMS if ('%s: ' % f) in out]
        check(not alien, 'общий прогон свежего проекта зовёт самотесты движка или фикстуры: %s' % alien)
        check('схема раскадровки: порчи' not in out, 'порчи схемы раскадровки — самотест движка, а он в проектном прогоне')
    finally:
        _cleanup(tmp)


if __name__ == '__main__':
    sys.exit(run_module(globals()))
