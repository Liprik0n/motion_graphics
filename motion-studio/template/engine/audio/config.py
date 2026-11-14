# -*- coding: utf-8 -*-
"""Где проект и что в его конфигах звука. Абсолютных путей нет.

Раскладка шаблона: `<шаблон>/engine/audio/` (этот код) и `<шаблон>/project/` (конфиги).
Папка проекта — одно правило движка (engine/project_root.py): `--project` → `MOTION_PROJECT` →
`<шаблон>/project`; все `paths.*` считаются от неё. Результаты фильма лежат там, куда их кладёт
сборка видео: `<проект>/<project.json paths.out>/<фильм>/`.

Конфиги звука: `music.json` (треки по главам, ducking, цели громкости), `sfx.json` (каталог
событий → эффект, уровни, плотность), `voices.json` (поправка громкости голоса `gain_db`,
читается через engine/tts/voice_gain.py). Связь с видео — только `film.json` на диске.
"""
import json
import os
import sys

sys.dont_write_bytecode = True
from pathlib import Path

ENGINE_AUDIO = Path(__file__).resolve().parent
TEMPLATE = ENGINE_AUDIO.parents[1]

# engine/tts лежит рядом: поправку громкости голоса берём из единственного места
sys.path.insert(0, str(ENGINE_AUDIO.parent / 'tts'))
sys.path.append(str(ENGINE_AUDIO.parent))
import voice_gain     # noqa: E402
import project_root   # noqa: E402


def project_dir(argv=None):
    """Папка проекта из argv по общему правилу движка."""
    return project_root.split_argv(argv or [])[0]


def read_json(path):
    path = Path(path)
    if not path.exists():
        raise SystemExit('нет файла %s' % path)
    with open(path, encoding='utf-8-sig') as fh:
        return json.load(fh)


def write_json(path, data):
    tmp = str(path) + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


class Audio:
    """Конфиги и пути звука одного фильма проекта."""

    def __init__(self, pdir, film):
        self.dir = Path(pdir).resolve()
        self.film_name = film
        self.meta = read_json(self.dir / 'project.json')
        if self.meta.get('fps') is None:
            raise SystemExit('project.json: нет обязательного поля fps')
        self.fps = int(self.meta['fps'])
        self.music = read_json(self.dir / 'music.json')
        self.sfx = read_json(self.dir / 'sfx.json')
        out = (self.meta.get('paths') or {}).get('out')
        if not out:
            raise SystemExit('project.json: нет обязательного поля paths.out')
        self.out = self.dir / out / film
        self.film_path = self.out / 'film.json'
        self.music_wav = self.out / 'music.wav'
        self.sfx_wav = self.out / 'sfx.wav'
        self.mix_m4a = self.out / 'mix.m4a'
        self.video = self.out / 'video.mp4'
        self.video_music = self.out / 'video-music.mp4'
        self.cues = self.out / 'cues.json'
        self.proba = self.out / 'sfx-proba.mp3'

    def film(self):
        f = read_json(self.film_path)
        if f.get('estimate'):
            raise SystemExit('film.json собран по смете (--estimate): звука реплик нет, микс невозможен')
        return f

    def replies(self, film):
        """Реплики с озвучкой: [{num, voice, start, end, path}], path — абсолютный."""
        out = []
        for r in film['replies']:
            if not r.get('file'):
                continue
            p = self.dir / r['file']
            if not p.exists():
                raise SystemExit('нет mp3 реплики %s: %s' % (r.get('num', r.get('n')), p))
            out.append({'num': r.get('num', r.get('n')), 'voice': r['voice'], 'start': r['start'],
                        'end': r['end'], 'path': str(p)})
        if not out:
            raise SystemExit('в film.json нет ни одной реплики с mp3 — микс не из чего собирать')
        return out

    def voice_gain_db(self, voice):
        return voice_gain.gain_db(voice, self.dir)


def parse_cli(argv, flags=()):
    """Общий разбор: [фильм] [--project DIR] [--флаги]. Возвращает (фильм, project_dir, набор флагов)."""
    pdir, args = project_root.split_argv(argv)
    got = {a for a in args if a in flags}
    rest = [a for a in args if a not in flags]
    bad = [a for a in rest if a.startswith('--')]
    if bad:
        raise SystemExit('неизвестные аргументы: %s' % bad)
    if len(rest) != 1:
        raise SystemExit('нужен один аргумент — имя фильма (папка в <out>/): %s' % rest)
    return rest[0], pdir, got
