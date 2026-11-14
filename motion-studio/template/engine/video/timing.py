# -*- coding: utf-8 -*-
"""Таймлайн ролика: строки озвучки → начало и конец каждой реплики, сцены и стыки.

Единственный источник времени — звук. Строки берутся из фильма (`films/<имя>.json`):
  "replies": [{n, scene, voice, emotion?, file}]      — прямо в фильме (демо), file — от корня проекта;
  "manifest": "<путь от корня проекта>"               — манифест конвейера озвучки: список строк
      {n|num, scene, voice, emotion?, file|mp3, scene_start?, ms?} — так его пишет `tts.py --assemble`.
`scene` строки — id сцены раскадровки. Если у всех строк сцены есть `scene_start` (начало реплики на шкале
своей сцены, с), раскладка внутри сцены берётся из него — реплика стоит там, где её поставила склейка
озвучки; иначе реплики идут подряд с паузой pause_sec.
Между сценами — scene_gap_sec (project.json): в этой паузе идёт бесшовный переход.

Длительность реплики — промер mp3 (lipsync.analyze), а не поле манифеста: кадр обязан
совпасть со звуком, который в него смешан. Без звука (--estimate) — `ms` строки, иначе смета
знаки × est_sec_per_char.
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

EST_SEC_PER_CHAR = 0.065     # смета без звука: грубо, только чтобы раскадровка собралась (не для сметы оплаты)
EST_NO_TEXT_SEC = 4.0        # строка без текста и без ms — условная длина реплики


class Timing:
    def __init__(self, P):
        self.fps = P.fps
        self.pause = float(P.req('pause_sec'))
        self.gap = float(P.req('scene_gap_sec'))
        self.lead = float(P.req('lead_sec'))
        self.tail = float(P.req('tail_sec'))
        self.root = P.root

    def frame_round(self, sec):
        """Время на сетке кадров: стык и начало реплики попадают ровно в кадр."""
        return round(sec * self.fps) / self.fps

    def rows(self, film):
        """Строки озвучки фильма с абсолютным путём к mp3."""
        if film.get('replies') is not None:
            raw, base = film['replies'], str(self.root)
        elif film.get('manifest'):
            p = os.path.join(str(self.root), film['manifest'])
            if not os.path.exists(p):
                return None
            with open(p, encoding='utf-8') as fh:
                raw = json.load(fh)
            base = os.path.dirname(os.path.abspath(p))
        else:
            raise SystemExit('В фильме нет ни replies, ни manifest')
        out = []
        for r in raw:
            f = r.get('mp3') or r.get('file')
            if f:
                f = f.replace('\\', os.sep).replace('/', os.sep)
                if not os.path.isabs(f):
                    f = os.path.normpath(os.path.join(base, f))
            n = r.get('n', r.get('num'))
            if n is None or not r.get('scene') or not r.get('voice'):
                raise SystemExit('Строка озвучки без n / scene / voice: %s' % r)
            row = {'num': int(n), 'scene': r['scene'], 'voice': r['voice'], 'emotion': r.get('emotion'),
                   'file': f, 'text': r.get('text', '')}
            if r.get('scene_start') is not None:
                row['scene_start'] = float(r['scene_start'])
            if r.get('ms') is not None:
                row['ms'] = r['ms']
            if r.get('silent'):
                # немая строка: без звука, длина — ms; рот закрыт, в сведении молчит (опора времени для действия без речи)
                if f or r.get('ms') is None:
                    raise SystemExit('Немая строка %s: у строки silent нет ms или есть файл звука %s' % (n, f))
                row['silent'] = True
            out.append(row)
        return out

    def estimate_ms(self, r):
        if r.get('ms'):
            return int(r['ms'])
        if not r.get('text'):
            return int(EST_NO_TEXT_SEC * 1000)
        return int(max(1.0, len(r['text']) * EST_SEC_PER_CHAR) * 1000)

    def build(self, rows, scenes, durations, tail_sec=None):
        """rows — строки нужных сцен; scenes — id сцен в порядке фильма; durations — {num: с}.
        → {'fps','duration','replies':[...],'scenes':[{id,start,end,first,last}]}."""
        tail_sec = self.tail if tail_sec is None else tail_sec
        by = {s: sorted([r for r in rows if r['scene'] == s], key=lambda r: r['num']) for s in scenes}
        for s in scenes:
            if not by[s]:
                raise SystemExit('В строках озвучки нет ни одной реплики сцены %s' % s)
        replies, t = [], self.lead
        for si, s in enumerate(scenes):
            if si:
                t += self.gap - self.pause
            base = t
            placed = all('scene_start' in r for r in by[s])
            for r in by[s]:
                start = self.frame_round(base + r['scene_start']) if placed else self.frame_round(t)
                end = start + durations[r['num']]
                replies.append({'num': r['num'], 'scene': s, 'voice': r['voice'], 'emotion': r.get('emotion'),
                                'start': round(start, 4), 'end': round(end, 4), 'file': r.get('file'),
                                'silent': bool(r.get('silent'))})
                t = end + self.pause
        duration = self.frame_round(replies[-1]['end'] + tail_sec)
        out = []
        for s in scenes:
            rs = [r for r in replies if r['scene'] == s]
            out.append({'id': s, 'first': rs[0]['start'], 'last': rs[-1]['end']})
        for si, sc in enumerate(out):
            sc['start'] = 0.0 if si == 0 else out[si - 1]['end']
            sc['end'] = self.frame_round((sc['last'] + out[si + 1]['first']) / 2) if si + 1 < len(out) else duration
        return {'fps': self.fps, 'duration': duration, 'replies': replies, 'scenes': out}
