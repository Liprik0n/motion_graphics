# -*- coding: utf-8 -*-
"""Склейка ролика из кусков: куски монтажного листа → один mp4 одним кодированием.

    python engine/video/assemble.py <лист>                  <out>/final/<лист>.mp4
    python engine/video/assemble.py <лист> --check          сухой прогон: всё, что проверяется до кодирования (кадры
                                                            кусков, отметки, число кадров, звук), без кодирования
    python engine/video/assemble.py <лист> --draft          пробное кодирование (CRF 23, veryfast) — не для показа
    python engine/video/assemble.py <лист> --silent         без звука (тишина), пока звук не сведён
    python engine/video/assemble.py <лист> --audio <файл>   один звук на всю склейку вместо звука из листа
    python engine/video/assemble.py --list                  какие листы есть в project/montage.json
    --project DIR   корень проекта: --project → MOTION_PROJECT → <шаблон>/project (engine/project_root.py)
    --out-root DIR  где лежат <фильм>/ с кадрами (иначе project.json paths.out)
    --out FILE      куда писать (иначе поле out листа, иначе <out>/final/<лист>.mp4)

Зачем: кусок рендера — фильм. Ролик из нескольких фильмов рендерится по куску (`build.py <фильм> --png`), правка
одной сцены перерендеривает только её фильм; склейка собирает куски в порядке листа (process/08-render-qa.md скила,
«Рендер: куски, один сборщик, бюджет диска»).

Монтажный лист — project/montage.json (путь от корня проекта; другой — project.json paths.montage):

    {"<лист>": {"pieces": [...], "audio": "<файл>" | null, "out": "<файл>", "crf": 18, "preset": "medium",
                "audio_bitrate": "192k"}}

    pieces   куски по порядку:
             {"film": "<фильм>"} — кадры <out>/<фильм>/frames/ (build.py <фильм> --png) с отметкой frames/stamp.json;
                 {"film": …, "style": "<стиль>"} — проход фильма в стиле (<out>/<фильм>/<стиль>/);
                 {"film": …, "partial": true} — пробный кусок (--frames N) допустим;
             {"frames": "<папка>", "pattern": "f%05d.png", "start": 0, "expect": ["<json с полем frames>", …]} —
                 готовая PNG-последовательность (захват, сторонний рендер): кадры подряд от start без дыр, их число =
                 полю frames каждого файла expect;
             {"mp4": "<файл>"} — видеодорожка готового mp4 (декодируется и кодируется заново вместе со всем).
    audio    один сведённый звук на всю склейку (путь от корня проекта); его длина обязана совпасть с суммой кадров
             кусков ± 1 кадр — иначе отказ (молча звук под картинку не подгоняется). Поля нет (или null) — звук по
             кускам: у куска-фильма <out>/<фильм>/mix.m4a (engine/audio/music.py <фильм>), длина = кадры куска ± 1 кадр;
             у кусков frames и mp4 без своего звука — тишина. Нет mix.m4a — отказ с командой; тишина — только --silent.

Почему одним кодированием: сшивка готовых mp4 без перекодирования рвёт GOP на стыке. Кусок берётся, только если его
отметка совпадает с нынешней страницей (engine/video/stamp.py): страницу пересобрали другой — отказ с командой
перерендера. Пересборка той же страницы (общий прогон проверок) кадры не трогает и склейку не ломает.
Перед кодированием печатаются свободное место и ОЗУ; после — длины дорожек и потоки выхода, расхождение с ожидаемым
± 1 кадр — код 1. Chrome склейке не нужен.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

sys.dont_write_bytecode = True
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

HERE = os.path.dirname(os.path.abspath(__file__))           # <проект>/engine/video
ENGINE = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ENGINE)
import deps          # noqa: E402
deps.need('imageio_ffmpeg')     # нет пакета — строка «нет: … — поставь: …» и код 2, без трассировки
import project_root  # noqa: E402
import resources     # noqa: E402
import stamp         # noqa: E402

AR = 44100
DEFAULTS = {'crf': 18, 'preset': 'medium', 'audio_bitrate': '192k'}
MIX = 'mix.m4a'


def log(msg):
    print(msg, flush=True)


def ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def load_json(p):
    with open(p, encoding='utf-8') as fh:
        return json.load(fh)


class Ctx:
    """Проект склейки: корень, полотно и частота кадров из project.json, где лежат выходы фильмов."""

    def __init__(self, root, out_root=None):
        self.root = os.path.abspath(str(root))
        pj = load_json(os.path.join(self.root, 'project.json'))
        for key in ('fps', 'canvas', 'paths'):
            if key not in pj:
                raise SystemExit('project.json: нет обязательного поля %s' % key)
        self.fps = pj['fps']
        self.w, self.h = int(pj['canvas']['w']), int(pj['canvas']['h'])      # полотно в px (как engine/video/config.py)
        self.paths = pj['paths']
        if not self.paths.get('out'):
            raise SystemExit('project.json: нет обязательного поля paths.out')
        self.out_root = os.path.abspath(out_root) if out_root else os.path.join(self.root, self.paths['out'])
        self.montage = os.path.join(self.root, self.paths.get('montage', 'montage.json'))

    def rel(self, p):
        return p if os.path.isabs(p) else os.path.normpath(os.path.join(self.root, p))

    def frames_of(self, sec):
        return int(round(sec * self.fps))


def piece_dir(cx, pc):
    return os.path.join(cx.out_root, pc['film'], pc['style']) if pc.get('style') else os.path.join(cx.out_root, pc['film'])


def render_cmd(pc):
    return 'build.py %s --png%s' % (pc['film'], ' --style %s' % pc['style'] if pc.get('style') else '')


# ---------------------------------------------------------------- куски
def piece_input(cx, pc):
    """Кусок → {args: вход ffmpeg, n: кадров, label, audio: свой звук куска или None, film: имя или None}."""
    if 'film' in pc:
        d = piece_dir(cx, pc)
        fdir = os.path.join(d, stamp.FRAMES)
        if not os.path.isdir(fdir):
            raise SystemExit('кусок %s: нет кадров %s — отрендерь: %s' % (pc['film'], fdir, render_cmd(pc)))
        why = stamp.stale(d)
        if why:
            raise SystemExit('кусок %s: кадры не годятся — %s; перерендерь: %s' % (pc['film'], '; '.join(why), render_cmd(pc)))
        st = stamp.read(d)
        meta = load_json(os.path.join(d, 'film.json'))
        n, full = stamp.frames_on_disk(d), cx.frames_of(meta['duration'])
        if meta.get('fps') != cx.fps or list(st.get('canvas') or []) != [cx.w, cx.h]:
            raise SystemExit('кусок %s: кадры %s к/с %s, а проект — %s к/с %d × %d; перерендерь: %s'
                             % (pc['film'], meta.get('fps'), st.get('canvas'), cx.fps, cx.w, cx.h, render_cmd(pc)))
        if n != full and not pc.get('partial'):
            raise SystemExit('кусок %s: кадров %d, а фильм длиной %d кадров — кусок неполный (пробный рендер --frames?); '
                             'перерендерь: %s' % (pc['film'], n, full, render_cmd(pc)))
        mix = os.path.join(d, MIX)
        # кадры куска лежат по сценам (frames/<сцена>/frame_%06d.png, номера сквозные) либо плоско: вход ffmpeg —
        # на каждый отрезок номеров подряд в одной папке; дыра в номерах — отказ, а не тихий сдвиг картинки
        runs = stamp.frame_runs(d)
        gap = [(a, b) for a, b in zip(runs, runs[1:]) if a[1] + a[2] != b[1]]
        if not runs or runs[0][1] != 1 or gap:
            raise SystemExit('кусок %s: кадры не подряд с первого (%s) — перерендерь: %s'
                             % (pc['film'], 'после кадра %d идёт %d' % (gap[0][0][1] + gap[0][0][2] - 1, gap[0][1][1])
                                if gap else 'нет кадра 1', render_cmd(pc)))
        inputs = [(['-framerate', str(cx.fps), '-start_number', str(k), '-i', os.path.join(rd, 'frame_%06d.png')], cnt)
                  for rd, k, cnt in runs]
        return {'args': inputs[0][0], 'inputs': inputs,
                'n': n, 'label': 'фильм %s%s' % (pc['film'], ' · ' + pc['style'] if pc.get('style') else ''),
                'audio': mix if os.path.exists(mix) else None, 'film': pc['film'], 'mix': mix}
    if 'frames' in pc:
        fdir = cx.rel(pc['frames'])
        pat = pc.get('pattern', 'frame_%06d.png')
        start = int(pc.get('start', 1))
        rx = re.compile('^' + re.sub(r'%0(\d)d', lambda m: r'\d{%s}' % m.group(1), re.escape(pat).replace(r'\%', '%')) + '$')
        if not os.path.isdir(fdir):
            raise SystemExit('кусок: нет папки кадров %s' % fdir)
        n = len([f for f in os.listdir(fdir) if rx.match(f)])
        if not n:
            raise SystemExit('кусок: в %s нет кадров %s (шаблон имени не тот?)' % (fdir, pat))
        gap = [k for k in range(start, start + n) if not os.path.exists(os.path.join(fdir, pat % k))]
        if gap:
            raise SystemExit('кусок %s: %d кадров %s, но не подряд от %d — нет %s' % (fdir, n, pat, start, pat % gap[0]))
        for src in pc.get('expect') or []:
            sp = cx.rel(src)
            if not os.path.exists(sp):
                raise SystemExit('кусок %s: нет %s — не с чем сверить число кадров' % (fdir, sp))
            want = load_json(sp).get('frames')
            if want != n:
                raise SystemExit('кусок %s: кадров %d, а %s ждёт %s — последовательность неполная или расписание пересчитано'
                                 % (fdir, n, src, want))
        return {'args': ['-framerate', str(cx.fps), '-start_number', str(start), '-i', os.path.join(fdir, pat)],
                'n': n, 'label': 'кадры %s' % fdir, 'audio': None, 'film': None}
    if 'mp4' in pc:
        p = cx.rel(pc['mp4'])
        if not os.path.exists(p):
            raise SystemExit('кусок: нет файла %s' % p)
        return {'args': ['-i', p], 'n': cx.frames_of(media_duration(p)), 'label': 'mp4 %s' % p,
                'audio': p if audio_seconds(p) is not None else None, 'film': None}
    raise SystemExit('кусок без film / frames / mp4: %s' % pc)


def audio_seconds(p):
    """Длина первой звуковой дорожки файла, с (по пакетам, без декодирования); дорожки нет — None."""
    a = subprocess.run([ffmpeg(), '-hide_banner', '-nostats', '-progress', 'pipe:2', '-i', p, '-map', '0:a:0',
                        '-c', 'copy', '-f', 'null', '-'], capture_output=True, text=True, encoding='utf-8', errors='replace').stderr
    au = re.findall(r'out_time_us=(\d+)', a)
    return int(au[-1]) / 1e6 if au else None


def media_duration(p):
    err = subprocess.run([ffmpeg(), '-hide_banner', '-i', p], capture_output=True, text=True, encoding='utf-8',
                         errors='replace').stderr
    m = re.search(r'Duration: (\d+):(\d+):([\d.]+)', err)
    if not m:
        raise SystemExit('не прочесть длительность %s' % p)
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def check_one_audio(cx, audio, infos):
    """Один звук на всю склейку: длина = сумма кадров кусков ± 1 кадр. Иначе отказ — подгонка (apad/atrim) молча
    развела бы звук с картинкой."""
    total = sum(i['n'] for i in infos)
    want, tol = total / cx.fps, 1.0 / cx.fps + 1e-6
    have = audio_seconds(audio)
    if have is None:
        raise SystemExit('звук %s: не прочесть длину звуковой дорожки' % audio)
    if abs(have - want) > tol:
        raise SystemExit('звук %s длится %.3f с, а куски — %d кадров (%.3f с): расхождение %.3f с больше 1 кадра — '
                         'звук сведён под другие куски; пересведи' % (audio, have, total, want, have - want))
    log('  звук склейки: %.3f с = куски %d кадров ± 1 кадр' % (have, total))


def check_piece_audio(cx, infos, silent):
    """Звук по кускам: у куска-фильма обязан быть mix.m4a длиной в кусок ± 1 кадр (или --silent)."""
    tol = 1.0 / cx.fps + 1e-6
    for i in infos:
        if i['film'] and not i['audio'] and not silent:
            raise SystemExit('кусок %s: нет звука %s — сведи: engine/audio/music.py %s (или --silent для пробы, '
                             'или один звук на склейку: поле audio листа, --audio)' % (i['film'], i['mix'], i['film']))
        if i['film'] and i['audio']:
            have, want = audio_seconds(i['audio']), i['n'] / cx.fps
            if have is None or abs(have - want) > tol:
                raise SystemExit('кусок %s: звук %s длится %s с, а кадров %d (%.3f с) — пересведи: engine/audio/music.py %s'
                                 % (i['film'], i['audio'], '%.3f' % have if have is not None else '—', i['n'], want, i['film']))


# ---------------------------------------------------------------- кодирование
def video_chain(cx, i, n):
    """Вход i → [v<i>]: ровно n кадров, частота и размер проекта, yuv420p."""
    return ('[%d:v]trim=end_frame=%d,setpts=N/(%d*TB),scale=%d:%d:flags=bicubic,setsar=1,format=yuv420p[v%d]'
            % (i, n, cx.fps, cx.w, cx.h, i))


def audio_chain(i, sec, tag):
    """Вход i → [tag] ровно sec секунд. apad/atrim — только защита в пределах кадра: звук другой длины
    отвергнут до кодирования."""
    return ('[%d:a]aresample=%d,aformat=sample_fmts=fltp:channel_layouts=stereo,apad,atrim=0:%.6f,asetpts=N/SR/TB[%s]'
            % (i, AR, sec, tag))


def encode_args(cx, cfg, draft):
    crf, preset = (23, 'veryfast') if draft else (cfg['crf'], cfg['preset'])
    return ['-r', str(cx.fps), '-c:v', 'libx264', '-profile:v', 'high', '-pix_fmt', 'yuv420p', '-crf', str(crf),
            '-preset', preset, '-c:a', 'aac', '-b:a', cfg['audio_bitrate'], '-ac', '2', '-ar', str(AR),
            '-movflags', '+faststart']


def run_ffmpeg(cmd, dst):
    tmp = dst + '.part.mp4'
    t0 = time.time()
    r = subprocess.run(cmd + [tmp])
    if r.returncode:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise SystemExit('ffmpeg не собрал %s (код %d)' % (dst, r.returncode))
    os.replace(tmp, dst)          # запись атомарна: недописанный файл не выдаётся за готовый
    log('  записан %s · %.1f с' % (dst, time.time() - t0))


def build(cx, infos, one_audio, silent, dst, cfg, draft):
    total = sum(i['n'] for i in infos)
    sec = total / cx.fps
    cmd = [ffmpeg(), '-hide_banner', '-v', 'error', '-stats', '-y']
    parts, first = [], []          # входы картинки по порядку: у куска-фильма — по входу на сцену (кэш кадров по сценам)
    for i in infos:
        first.append(len(parts))
        for args, cnt in i.get('inputs') or [(i['args'], i['n'])]:
            cmd += args
            parts.append(cnt)
    fc = [video_chain(cx, k, cnt) for k, cnt in enumerate(parts)]
    fc.append(''.join('[v%d]' % k for k in range(len(parts))) + 'concat=n=%d:v=1:a=0[v]' % len(parts))
    nxt = len(parts)
    if one_audio or silent:
        cmd += (['-i', one_audio] if one_audio else ['-f', 'lavfi', '-t', '%.6f' % sec, '-i', 'anullsrc=r=%d:cl=stereo' % AR])
        fc.append(audio_chain(nxt, sec, 'a'))
    else:                          # звук по кускам: свой у куска или тишина его длины, затем склейка дорожек
        tags = []
        for k, i in enumerate(infos):
            psec = i['n'] / cx.fps
            if i['audio'] and i['args'][-1] == i['audio']:
                src = first[k]     # кусок mp4: звук — из того же входа
            else:
                cmd += (['-i', i['audio']] if i['audio']
                        else ['-f', 'lavfi', '-t', '%.6f' % psec, '-i', 'anullsrc=r=%d:cl=stereo' % AR])
                src = nxt
                nxt += 1
            fc.append(audio_chain(src, psec, 'a%d' % k))
            tags.append('[a%d]' % k)
        fc.append(''.join(tags) + 'concat=n=%d:v=0:a=1[a]' % len(tags))
    cmd += ['-filter_complex', ';'.join(fc), '-map', '[v]', '-map', '[a]', '-frames:v', str(total), '-t', '%.6f' % sec]
    cmd += encode_args(cx, cfg, draft)
    log('склейка: %d кусков, %d кадров (%.3f с) → %s' % (len(infos), total, sec, dst))
    run_ffmpeg(cmd, dst)
    return total


# ---------------------------------------------------------------- проверка выхода
def measure(path):
    """(кадров видео, секунд звука, строки потоков) — кадры без декодирования (stream copy)."""
    v = subprocess.run([ffmpeg(), '-hide_banner', '-i', path, '-map', '0:v:0', '-c', 'copy', '-f', 'null', '-'],
                       capture_output=True, text=True, encoding='utf-8', errors='replace').stderr
    fr = re.findall(r'frame=\s*(\d+)', v)
    return (int(fr[-1]) if fr else None), audio_seconds(path), [l.strip() for l in v.splitlines() if 'Stream #' in l]


def verify(cx, path, want_frames):
    fr, au, streams = measure(path)
    bad = []
    if fr is None or abs(fr - want_frames) > 1:
        bad.append('кадров %s, а ждали %d ± 1' % (fr, want_frames))
    if au is None or abs(au - want_frames / cx.fps) > 1.0 / cx.fps + 1e-6:
        bad.append('звук %s с, а видео %.3f с (± 1 кадр)' % (au, want_frames / cx.fps))
    vs = ' '.join(streams)
    if not re.search(r'Video: h264 \(High\).*yuv420p.*%dx%d.*%s fps' % (cx.w, cx.h, cx.fps), vs):
        bad.append('видео не h264 High yuv420p %d×%d %s к/с' % (cx.w, cx.h, cx.fps))
    if not re.search(r'Audio: aac \(LC\).*%d Hz, stereo' % AR, vs):
        bad.append('звук не AAC-LC %d Гц стерео' % AR)
    log('  промер %s: %s кадров (%.3f с), звук %s с' % (os.path.basename(path), fr, (fr or 0) / cx.fps,
                                                        '%.3f' % au if au is not None else '—'))
    for b in bad:
        log('  FAIL %s: %s' % (os.path.basename(path), b))
    return not bad


# ---------------------------------------------------------------- вход
def montages(cx):
    if not os.path.exists(cx.montage):
        raise SystemExit('нет монтажного листа %s — {"<лист>": {"pieces": [{"film": "<фильм>"}, …]}}' % cx.montage)
    return {k: v for k, v in load_json(cx.montage).items() if not k.startswith('_')}


def main(argv=None):
    root, argv = project_root.split_argv(sys.argv[1:] if argv is None else list(argv))
    ap = argparse.ArgumentParser(description='Склейка ролика из кусков одним кодированием')
    ap.add_argument('montage', nargs='?', help='имя листа из project/montage.json')
    ap.add_argument('--list', action='store_true', help='перечислить листы')
    ap.add_argument('--check', action='store_true', help='сухой прогон: проверки до кодирования, без кодирования')
    ap.add_argument('--draft', action='store_true', help='пробное кодирование: CRF 23, veryfast')
    ap.add_argument('--silent', action='store_true', help='звук — тишина (пока звук не сведён)')
    ap.add_argument('--audio', help='один звук на всю склейку (иначе поле audio листа, иначе звук кусков)')
    ap.add_argument('--out-root', help='где лежат <фильм>/ с кадрами (иначе project.json paths.out)')
    ap.add_argument('--out', help='куда писать (иначе поле out листа, иначе <out>/final/<лист>.mp4)')
    a = ap.parse_args(argv)
    cx = Ctx(root, a.out_root)
    sheets = montages(cx)
    if a.list:
        for name, m in sheets.items():
            log('%s: %s' % (name, ' → '.join(pc.get('film') or pc.get('frames') or pc.get('mp4') or '?' for pc in m.get('pieces') or [])))
        return 0
    if not a.montage:
        raise SystemExit('какой лист склеивать? есть: %s' % (', '.join(sheets) or '— (project/montage.json пуст)'))
    if a.montage not in sheets:
        raise SystemExit('листа «%s» нет в %s (есть: %s)' % (a.montage, cx.montage, ', '.join(sheets) or '—'))
    cfg = dict(DEFAULTS)
    cfg.update(sheets[a.montage])
    pieces = cfg.get('pieces')
    if not pieces:
        raise SystemExit('лист «%s»: нет кусков (pieces)' % a.montage)
    infos = [piece_input(cx, pc) for pc in pieces]
    for i in infos:
        log('  кусок %-44s %5d кадров (%.3f с)' % (i['label'], i['n'], i['n'] / cx.fps))
    one_audio = None
    if not a.silent:
        src = a.audio or cfg.get('audio')
        if src:
            one_audio = cx.rel(src)
            if not os.path.exists(one_audio):
                raise SystemExit('нет звука склейки %s — сведи звук или --silent для пробы' % one_audio)
            check_one_audio(cx, one_audio, infos)
        else:
            check_piece_audio(cx, infos, a.silent)
    total = sum(i['n'] for i in infos)
    if a.check:
        log('  склейка «%s»: %d кадров (%.3f с)' % (a.montage, total, total / cx.fps))
        log('сухой прогон: до кодирования всё сходится (--check: файлы не пишутся)')
        return 0
    dst = os.path.abspath(a.out) if a.out else cx.rel(cfg.get('out') or os.path.join(cx.paths['out'], 'final', a.montage + '.mp4'))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    log(resources.report(os.path.dirname(dst)))
    ok = verify(cx, dst, build(cx, infos, one_audio, a.silent, dst, cfg, a.draft))
    log('итог: %s' % ('зелёный' if ok else 'КРАСНЫЙ'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
