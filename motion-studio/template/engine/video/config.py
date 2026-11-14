# -*- coding: utf-8 -*-
"""Конфиги проекта: project.json + tokens.json — единственный источник констант видео.

Корень проекта — одно правило движка (engine/project_root.py): `--project` → MOTION_PROJECT →
<шаблон>/project. Все пути проекта, включая выходы (`paths.out`, `paths.voices_out`), — от него.

Обязательные ключи читаются без запасного значения: нет ключа — отказ с именем поля
(`project.json: нет обязательного поля canvas.px_per_in`). Числа живут только в конфигах:
запасное число в коде молча подменило бы забытый ключ значением, которого никто не выбирал.
"""
import json
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

ENGINE = Path(__file__).resolve().parent          # <шаблон>/engine/video
sys.path.append(str(ENGINE.parent))
sys.path.append(str(ENGINE.parent / 'tts'))
import project_root   # noqa: E402
import voice_gain     # noqa: E402

# Размеры страницы (stage.css, разметка демо-сцен, рамки голоса) записаны в px при 96 px на дюйм.
# Другой px_per_in пересчитал бы координаты из дюймов, а px оставил бы как есть — кадр разъехался бы.
PX_PER_IN_SUPPORTED = 96

# Обязательные ключи: путь через точку. Проверяются при чтении, до сборки.
REQUIRED_PROJECT = (
    'fps', 'canvas.w', 'canvas.h', 'canvas.px_per_in',
    'pause_sec', 'scene_gap_sec', 'lead_sec', 'tail_sec', 'scene_exit_delay',
    'frame.seam_half', 'frame.seam_dur',
    'paths.out', 'paths.voices_out',
)
REQUIRED_VOICE_BARS = ('min', 'max', 'bars', 'bar_w', 'bar_step', 'box_y', 'box_h')
REQUIRED_TOKENS = (
    'palette', 'type', 'motion', 'density.max_opacity_step', 'density.words_per_chunk',
)
REQUIRED_MOTION = ('level_shade', 'level_step', 'level_gap', 'level_mid', 'ink_dur', 'breathe.scale', 'breathe.period',
                   'breathe.edge', 'title_in', 'chapter_dur', 'emph_dur', 'move_dur', 'beat_tail')


def project_root_dir():
    return project_root.resolve()


def dig(data, dotted, fname):
    """Значение по пути через точку; нет — SystemExit с именем файла и поля."""
    cur = data
    for part in dotted.split('.'):
        if not isinstance(cur, dict) or part not in cur or cur[part] is None:
            raise SystemExit('%s: нет обязательного поля %s' % (fname, dotted))
        cur = cur[part]
    return cur


def read_json(p):
    with open(p, encoding='utf-8-sig') as fh:
        return json.load(fh)


class Project:
    """Прочитанные конфиги и пути проекта."""

    def __init__(self, root=None):
        self.root = project_root.resolve(root)
        pj, tk = self.root / 'project.json', self.root / 'tokens.json'
        for p in (pj, tk):
            if not p.exists():
                raise SystemExit('Нет конфига проекта %s (корень проекта: %s)' % (p, project_root.RULE))
        self.project = read_json(pj)
        self.tokens = read_json(tk)
        for key in REQUIRED_PROJECT:
            dig(self.project, key, 'project.json')
        vb = self.project.get('voice_bars')
        if vb and vb.get('voices'):
            for key in REQUIRED_VOICE_BARS:
                dig(self.project, 'voice_bars.' + key, 'project.json')
        for key in REQUIRED_TOKENS:
            dig(self.tokens, key, 'tokens.json')
        for key in REQUIRED_MOTION:
            dig(self.tokens, 'motion.' + key, 'tokens.json')
        for role, t in self.tokens['type'].items():
            for f in ('size_pt', 'weight'):
                dig(self.tokens, 'type.%s.%s' % (role, f), 'tokens.json')
        self.palette = {k: v.upper() for k, v in self.tokens['palette'].items()}
        self.fps = int(self.req('fps'))
        self.W, self.H = int(self.req('canvas.w')), int(self.req('canvas.h'))
        self.PX = float(self.req('canvas.px_per_in'))
        if self.PX != PX_PER_IN_SUPPORTED:
            raise SystemExit(
                'project.json canvas.px_per_in = %s: движок поддерживает только %d. Размеры stage.css, разметки '
                'сцен и рамок записаны в px при %d px на дюйм; другое значение пересчитало бы координаты из дюймов, '
                'а px оставило бы как есть. Меняй разрешение через canvas.w и canvas.h вместе с координатами в дюймах.'
                % (cv_repr(self.project), PX_PER_IN_SUPPORTED, PX_PER_IN_SUPPORTED))
        self.motion = self.tokens['motion']
        self.chapters = self.project.get('chapters', [])
        self.fonts = all_fonts(self.tokens, self.project)

    # ---- обязательные значения
    def req(self, dotted):
        """Обязательное значение project.json по пути через точку."""
        return dig(self.project, dotted, 'project.json')

    def tok(self, dotted):
        """Обязательное значение tokens.json по пути через точку."""
        return dig(self.tokens, dotted, 'tokens.json')

    # ---- пути
    def path(self, key):
        return (self.root / dig(self.project, 'paths.' + key, 'project.json')).resolve()

    def opt_path(self, key, default):
        """Необязательный путь: папка с ресурсами проекта (scenes, films, icons)."""
        return (self.root / (self.project.get('paths') or {}).get(key, default)).resolve()

    @property
    def out(self):
        return self.path('out')

    @property
    def scenes(self):
        return self.opt_path('scenes', 'scenes')

    @property
    def films(self):
        return self.opt_path('films', 'films')

    def asset(self, rel, sub=''):
        """Файл ресурса: от корня проекта, иначе от папки движка (шрифты и иконки по умолчанию)."""
        for base in (self.root, ENGINE):
            p = (base / rel).resolve()
            if p.exists():
                return p
        if sub:
            p = (ENGINE / sub / os.path.basename(rel)).resolve()
            if p.exists():
                return p
        return None

    def icon(self, name):
        for d in (self.opt_path('icons', 'assets/icons'), ENGINE / 'assets' / 'icons'):
            p = Path(d) / name
            if p.exists():
                return p
        raise SystemExit('Нет иконки %s ни в project.json paths.icons, ни в engine/video/assets/icons' % name)

    # ---- цвета
    def color(self, role, what='цвет'):
        """Роль палитры → hex. Неизвестная роль — ошибка сборки (схема ловит раньше)."""
        if role is None:
            return None
        if role not in self.palette:
            raise SystemExit('%s «%s» — нет такой роли в tokens.json palette (есть: %s)'
                             % (what, role, ', '.join(sorted(self.palette))))
        return self.palette[role]

    def type(self, role):
        t = self.tokens['type'].get(role)
        if t is None:
            raise SystemExit('Нет роли кегля «%s» в tokens.json type' % role)
        return t

    def kinds(self):
        return self.tokens.get('kinds', {})

    def voice_gain_db(self, voice):
        """Поправка громкости голоса — одно место: engine/tts/voice_gain.py (voices.json voices[id].gain_db).
        Голоса нет в voices.json или у него нет gain_db — отказ сборки."""
        return voice_gain.gain_db(voice, self.root)


FONT_KEYS = {'role', 'family', 'files', 'descriptors', 'note'}
FONT_DESCRIPTORS = {'ascent-override', 'descent-override', 'line-gap-override', 'size-adjust'}


def all_fonts(tokens, project):
    """Роли шрифтов страницы: tokens.json fonts (фирменный brand) + project.json fonts (шрифты проекта сверх
    фирменного: заголовочный, цифры табло, рукописный…). Роль — одна на оба файла: повтор — отказ, а не перекрытие.
    Запись: {role, family, files: {жирность: путь от корня проекта}, descriptors?: {ascent-override, …}, note?}."""
    out, seen = [], {}
    for fname, lst in (('tokens.json', tokens.get('fonts') or []), ('project.json', project.get('fonts') or [])):
        for f in lst:
            if not isinstance(f, dict) or set(f) - FONT_KEYS or not f.get('family') or not isinstance(f.get('files'), dict) \
                    or not f['files']:
                raise SystemExit('%s fonts: запись %r — {role, family, files: {жирность: путь}, descriptors?, note?}'
                                 % (fname, {k: f.get(k) for k in ('role', 'family')} if isinstance(f, dict) else f))
            bad = set(f.get('descriptors') or {}) - FONT_DESCRIPTORS
            if bad:
                raise SystemExit('%s fonts %s: описатели %s — можно только %s' % (fname, f['family'], sorted(bad),
                                                                                 ', '.join(sorted(FONT_DESCRIPTORS))))
            role = f.get('role', 'brand')
            if role in seen:
                raise SystemExit('%s fonts: роль «%s» уже есть в %s' % (fname, role, seen[role]))
            seen[role] = fname
            out.append(f)
    return out


def cv_repr(project):
    return (project.get('canvas') or {}).get('px_per_in')
