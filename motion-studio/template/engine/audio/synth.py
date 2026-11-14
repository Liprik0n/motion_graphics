# -*- coding: utf-8 -*-
"""Синтез звука без файлов извне: каталог эффектов `sfx.json` и пэд-заглушка музыки.

Чистый Python (синусы, шум, бикварды), детерминированно: зерно — от имени события, поэтому
повторная сборка даёт те же отсчёты. Всё, что выше ~7 кГц, не синтезируется: частичные тоны
выше PARTIAL_MAX_HZ отбрасываются, шум идёт через НЧ-фильтр, клип целиком — через три
НЧ-биквада (над 8 кГц ≈ −22 дБ, над 10 кГц ≈ −40).

Виды `bell click whoosh thump tick` на биквадах, без привязки к теме. Новый вид — функция в CLIPS: `f(seed, variant, lead) -> (отсчёты, lead_sec)`,
где lead_sec — смещение главного удара от начала клипа (эффект стартует за lead_sec до события).
"""
import array
import math
import os
import random
import sys
import wave

sys.dont_write_bytecode = True
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

SR = 44100
PARTIAL_MAX_HZ = 6500.0
POST_LP_HZ, POST_LP_ORDER = 5500.0, 3
FADE_TAIL = 0.05            # концевое затухание клипа до нуля, с


class Biquad:
    """RBJ-биквад, коэффициенты можно менять на ходу (вжух)."""

    def __init__(self, kind, f, q=0.707):
        self.x1 = self.x2 = self.y1 = self.y2 = 0.0
        self.kind = kind
        self.set(f, q)

    def set(self, f, q):
        w = 2 * math.pi * f / SR
        c, s = math.cos(w), math.sin(w)
        al = s / (2 * q)
        if self.kind == 'lp':
            b0, b1, b2 = (1 - c) / 2, 1 - c, (1 - c) / 2
        elif self.kind == 'hp':
            b0, b1, b2 = (1 + c) / 2, -(1 + c), (1 + c) / 2
        else:   # bp, пик 0 дБ
            b0, b1, b2 = al, 0.0, -al
        a0, a1, a2 = 1 + al, -2 * c, 1 - al
        self.b = (b0 / a0, b1 / a0, b2 / a0)
        self.a = (a1 / a0, a2 / a0)

    def run(self, xs):
        b0, b1, b2 = self.b
        a1, a2 = self.a
        x1, x2, y1, y2 = self.x1, self.x2, self.y1, self.y2
        out = []
        for x in xs:
            y = b0 * x + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
            x2, x1, y2, y1 = x1, x, y1, y
            out.append(y)
        self.x1, self.x2, self.y1, self.y2 = x1, x2, y1, y2
        return out


def zeros(sec):
    return [0.0] * int(round(sec * SR))


def add(dst, src, at_sec, gain=1.0):
    i0 = int(round(at_sec * SR))
    for i, v in enumerate(src):
        j = i0 + i
        if 0 <= j < len(dst):
            dst[j] += gain * v


def noise(n, rng):
    return [rng.uniform(-1.0, 1.0) for _ in range(n)]


def bell(f, tau, sec, partials=((1.0, 1.0), (2.76, 0.42), (5.40, 0.18)), attack=0.0015):
    """Колокольчик: негармонические частичные с затуханием (выше частота — короче хвост)."""
    n = int(round(sec * SR))
    out = [0.0] * n
    for ratio, amp in partials:
        fr = f * ratio
        if fr > PARTIAL_MAX_HZ:
            continue
        t_r = tau / ratio ** 0.5
        w = 2 * math.pi * fr / SR
        k = math.exp(-1.0 / (t_r * SR))
        g = amp
        for i in range(n):
            out[i] += g * math.sin(w * i)
            g *= k
    na = max(1, int(attack * SR))
    for i in range(min(na, n)):
        out[i] *= i / na
    return out


def click(seed, f_body=220.0, f_snap=2600.0, sec=0.08):
    """Тихий щелчок: шумовой всплеск 1,5 мс в полосе + короткое тело-синус."""
    rng = random.Random(seed)
    n = int(sec * SR)
    snap = [v * math.exp(-i / (0.0015 * SR)) for i, v in enumerate(noise(n, rng))]
    snap = Biquad('bp', f_snap, 1.0).run(snap)
    body = [math.sin(2 * math.pi * f_body * i / SR) * math.exp(-i / (0.018 * SR)) for i in range(n)]
    out = [0.55 * a + 0.45 * b for a, b in zip(snap, body)]
    return Biquad('lp', 6000).run(out)


def whoosh(seed, sec, f0=380.0, f1=1500.0):
    """Мягкий «вжух»: шум в полосе, центр едет вверх; растёт до 72 % длины, гаснет к нулю к концу."""
    rng = random.Random(seed)
    n = int(round(sec * SR))
    src = noise(n, rng)
    bp = Biquad('bp', f0, 1.1)
    lp = Biquad('lp', 4000)
    out = []
    blk = 128
    for i0 in range(0, n, blk):
        x = i0 / n
        bp.set(f0 * (f1 / f0) ** x, 1.1)
        out += bp.run(src[i0:i0 + blk])
    out = lp.run(out)
    peak = 0.72
    for i in range(n):
        x = i / n
        out[i] *= x / peak if x < peak else math.cos(math.pi / 2 * (x - peak) / (1 - peak))
    return out


def thump(seed, f=110.0, sec=0.22):
    """Глухой «топ»: низкое тело + приглушённый хруст."""
    rng = random.Random(seed)
    n = int(sec * SR)
    na = int(0.003 * SR)
    body = [math.sin(2 * math.pi * f * i / SR) * math.exp(-i / (0.045 * SR)) * min(1.0, i / na) for i in range(n)]
    crunch = Biquad('lp', 700).run([v * math.exp(-i / (0.025 * SR)) for i, v in enumerate(noise(n, rng))])
    grit = Biquad('bp', 1800, 1.2).run([v * math.exp(-i / (0.012 * SR)) for i, v in enumerate(noise(n, rng))])
    return [0.8 * a + 1.6 * b + 0.25 * c for a, b, c in zip(body, crunch, grit)]


def tick(seed, f=1200.0, sec=0.09):
    rng = random.Random(seed)
    n = int(sec * SR)
    na = int(0.001 * SR)
    tone = [math.sin(2 * math.pi * f * i / SR) * math.exp(-i / (0.018 * SR)) * min(1.0, i / na) for i in range(n)]
    snap = Biquad('bp', 3000, 1.2).run([v * math.exp(-i / (0.003 * SR)) for i, v in enumerate(noise(n, rng))])
    return Biquad('lp', 6000).run([a + 0.5 * b for a, b in zip(tone, snap)])


def fade_end(xs, sec=FADE_TAIL):
    n = min(len(xs), int(sec * SR))
    for i in range(n):
        xs[len(xs) - n + i] *= math.cos(math.pi / 2 * (i + 1) / n)
    return xs


def normalize(xs, peak=0.5):
    m = max(abs(v) for v in xs) or 1.0
    return [v * peak / m for v in xs]


# ---------------------------------------------------------------- каталог видов (clip в sfx.json)

def clip_tick(seed, v, lead):
    return tick(seed, (1200.0, 1350.0, 1500.0)[v % 3]), 0.0


def clip_click(seed, v, lead):
    return click(seed, (220.0, 250.0, 195.0)[v % 3], (2600.0, 2900.0, 2300.0)[v % 3]), 0.0


def clip_ping(seed, v, lead):
    return bell((1568.0, 1760.0, 1975.5)[v % 3], 0.25, 0.7, partials=((1.0, 1.0), (2.0, 0.3))), 0.0


def clip_bell(seed, v, lead):
    return bell((1174.7, 1318.5, 1396.9)[v % 3], 0.8, 1.6), 0.0


def clip_chime(seed, v, lead):
    """Тёплый перезвон: три колокольчика аккордом и второй звон мягким входом."""
    x = zeros(3.0)
    for f, g in ((1046.5, 0.5), (1318.5, 0.35), (1568.0, 0.3)):
        add(x, bell(f * (1.0, 1.0595, 0.9439)[v % 3], 1.1, 3.0), 0.0, g)
    add(x, bell(2093.0 * (1.0, 1.0595, 0.9439)[v % 3], 0.8, 2.6, attack=0.05), 0.18, 0.2)
    return x, 0.0


def clip_thump(seed, v, lead):
    return thump(seed, (118.0, 104.0, 132.0)[v % 3]), 0.0


def clip_whoosh(seed, v, lead):
    sec = lead if lead else DEFAULT_LEAD
    return whoosh(seed, sec, (360.0, 400.0, 340.0)[v % 3], (1400.0, 1650.0, 1250.0)[v % 3]), 0.72 * sec


def clip_whoosh_click(seed, v, lead):
    """Вжух, на конце которого — щелчок посадки (lead — длина вжуха до щелчка)."""
    lead = lead if lead else DEFAULT_LEAD
    x = zeros(lead + 0.15)
    add(x, whoosh(seed, lead, (360.0, 400.0, 340.0)[v % 3], (1400.0, 1650.0, 1250.0)[v % 3]), 0.0, 0.7)
    add(x, click(seed, (220.0, 250.0, 195.0)[v % 3], (2600.0, 2900.0, 2300.0)[v % 3]), lead, 0.9)
    return x, lead


DEFAULT_LEAD = 0.55


def lead_of(clip, lead=None):
    """Смещение главного удара от начала клипа — без синтеза (планировщику нужно до рендера)."""
    sec = lead if lead else DEFAULT_LEAD
    return {'whoosh': 0.72 * sec, 'whoosh_click': sec}.get(clip, 0.0)


CLIPS = {'tick': clip_tick, 'click': clip_click, 'ping': clip_ping, 'bell': clip_bell, 'chime': clip_chime,
         'thump': clip_thump, 'whoosh': clip_whoosh, 'whoosh_click': clip_whoosh_click}
LEADABLE = ('whoosh', 'whoosh_click')     # у этих видов длина разгона настраивается `lead_sec`


GLASS_HZ = (2637.0, 3520.0, 4186.0)     # «стеклянные» парциалы (E7, A7, C8) — ниже среза POST_LP_HZ


def material(x, seed, mat, hit=0.0):
    """Материал звука стиля (engine/video/styles/<имя>/style.json sfx.clips.<вид>) поверх синтеза клипа.
    Момент удара не сдвигается: материал меняет тембр, а не время. Поля (границы — styles/_core/registry.py):
      grit 0…1        шорох: шум по огибающей клипа (бумага, ткань, глина — вместе с lp_hz);
      crackle 0…200   треск: щелчков в секунду по длине клипа (плёнка, винил);
      noise_burst 0…1 хлопок: шумовой удар 30 мс от момента удара (комикс, удар печати);
      partials 0…1    стекло: высокие парциалы GLASS_HZ по огибающей клипа (звон, блик);
      wave            square — жёсткое ограничение в меандр (8 бит), soft — мягкое насыщение tanh (глина, ткань);
      bits 2…16       разрядность: квантование амплитуды (8 бит);
      hold 1…32       битрейт: каждый отсчёт держится hold отсчётов (понижение частоты, 8 бит);
      lp_hz 500…12000 глухость: срез верха (последним)."""
    rng = random.Random(seed * 104729 + 7)
    out = list(x)
    env, a, envs = 0.0, math.exp(-1.0 / (0.004 * SR)), []
    for v in x:
        env = max(abs(v), env * a)
        envs.append(env)
    if mat.get('grit'):
        g = float(mat['grit'])
        for i in range(len(out)):
            out[i] += g * envs[i] * rng.uniform(-1.0, 1.0)
    if mat.get('crackle'):
        k = int(round(float(mat['crackle']) * len(x) / SR))
        click_n = int(0.002 * SR)
        for _ in range(k):
            i0, amp = rng.randrange(len(x)), 0.35 * rng.random()
            for j in range(click_n):
                if i0 + j < len(out):
                    out[i0 + j] += amp * math.exp(-j / (0.0004 * SR)) * rng.uniform(-1.0, 1.0)
    if mat.get('noise_burst'):
        g, i0, n = float(mat['noise_burst']), int(round(hit * SR)), int(0.03 * SR)
        for j in range(n):
            if 0 <= i0 + j < len(out):
                out[i0 + j] += g * 0.6 * math.exp(-j / (0.008 * SR)) * rng.uniform(-1.0, 1.0)
    if mat.get('partials'):
        g = float(mat['partials'])
        for i in range(len(out)):
            t = i / SR
            out[i] += g * envs[i] * sum(math.sin(2 * math.pi * f * t) / (k + 1) for k, f in enumerate(GLASS_HZ)) * 0.5
    w = mat.get('wave')
    if w:
        peak = max(abs(v) for v in out) or 1.0
        if w == 'square':
            out = [(1.0 if v > 0 else -1.0 if v < 0 else 0.0) * envs[i] for i, v in enumerate(out)]
        elif w == 'soft':
            out = [math.tanh(2.5 * v / peak) * peak for v in out]
    if mat.get('hold') and int(mat['hold']) > 1:
        h = int(mat['hold'])
        out = [out[i - i % h] for i in range(len(out))]
    if mat.get('bits'):
        peak = max(abs(v) for v in out) or 1.0
        q = 2 ** (int(mat['bits']) - 1)
        out = [round(v / peak * q) / q * peak for v in out]
    if mat.get('lp_hz'):
        for _ in range(2):
            out = Biquad('lp', float(mat['lp_hz'])).run(out)
    return out


def synth(clip, seed, variant, lead=None, mat=None):
    """Клип вида `clip`: (отсчёты float с пиком 0,5, смещение главного удара от начала, с).
    mat — материал звука стиля сцены (см. material), None — как в каталоге."""
    if clip not in CLIPS:
        raise SystemExit('sfx.json: вид эффекта %r не знаю (есть: %s)' % (clip, ', '.join(sorted(CLIPS))))
    x, hit = CLIPS[clip](seed, variant, lead)
    if mat:
        x = material(x, seed, mat, hit)
    for _ in range(POST_LP_ORDER):     # шумовые всплески не оставляют ничего над 8 кГц
        x = Biquad('lp', POST_LP_HZ).run(x)
    return fade_end(normalize(x)), hit


def write_wav(path, xs, rate=SR):
    a = array.array('h', (max(-32767, min(32767, int(round(v * 32767)))) for v in xs))
    tmp = str(path) + '.tmp'
    with wave.open(tmp, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(a.tobytes())
    os.replace(tmp, str(path))


# ---------------------------------------------------------------- пэд-заглушка музыки

def make_pad(path, root_hz=220, seconds=25.0, period=20, rate=16000):
    """Пэд-заглушка: аккорд из целых герц с медленным дрейфом громкости. Все частоты — целые, дрейф —
    k/period Гц, поэтому сигнал периодичен с периодом `period` секунд: круг трека (music.json) бесшовен
    (вход 2 с, выход 2 + period с). Это заглушка: заменить треком с лицензией."""
    chord = ((root_hz, 1.0), (root_hz + 1, 0.55), (root_hz - 1, 0.55), (int(root_hz * 1.5), 0.6),
             (int(root_hz * 1.25), 0.4), (root_hz * 2, 0.35))
    n = int(round(seconds * rate))
    out = array.array('h')
    peak = 0.0
    xs = []
    for i in range(n):
        t = i / rate
        s = 0.0
        for k, (f, g) in enumerate(chord):
            lfo = 0.65 + 0.35 * math.sin(2 * math.pi * (k + 1) / period * t + k)
            s += g * lfo * math.sin(2 * math.pi * f * t)
        xs.append(s)
        peak = max(peak, abs(s))
    for v in xs:
        out.append(int(round(v / peak * 0.5 * 32767)))
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(out.tobytes())
