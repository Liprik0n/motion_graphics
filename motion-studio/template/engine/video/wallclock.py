# -*- coding: utf-8 -*-
"""Настенное время кадра ролика: что показывают часы на стене в момент, когда кадр на экране, и сколько от него
осталось до события. На этом стоят плагины timer (отсчёт до события) и clock (часы в кадре).

    seconds_left(start, lead_sec, t, event) → секунды (дробные)
    timer_parts(...) → (дни, часы, минуты, секунды)        timer_at(...) → '0 д 05:38:16'
    clock_seconds(start, lead_sec, t) → секунды от полуночи (пояс start)
    clock_at(start, lead_sec, t, fmt="HH:MM:SS") → "18:18:32"

start — когда ролик начинают смотреть (ISO 8601 с поясом или datetime с tzinfo); lead_sec — сколько секунд идёт
до первого кадра склейки (то, что смотрят перед роликом; 0 — ролик идёт первым); t — секунда склейки (смещение
куска films/<f>.json timeline_offset_sec + время кадра внутри куска); event — момент события, к которому отсчёт.
Секунды — вниз (floor): таймер не обещает больше, чем осталось.
Время без пояса — отказ: пояс машины молча сдвинул бы таймер. Отсчёт ≤ 0 — отказ: показывать нечего.

Значения ролика лежат в project.json wall_clock {start, lead_sec, event}; сдвинулся старт — правится только
wall_clock.start, пересобирается кусок с таймером или часами и склейка (assemble.py).
"""
import math
from datetime import datetime, timedelta


def _moment(v, what):
    if isinstance(v, datetime):
        d = v
    else:
        try:
            d = datetime.fromisoformat(str(v))
        except ValueError:
            raise ValueError('%s: не время ISO 8601: %r' % (what, v))
    if d.tzinfo is None or d.utcoffset() is None:
        raise ValueError('%s: время без пояса (%r) — допиши смещение, например +03:00' % (what, v))
    return d


def seconds_left(start, lead_sec, t, event):
    """Секунд от момента, когда кадр t на экране, до события event (дробные)."""
    s = _moment(start, 'wall_clock.start')
    o = _moment(event, 'wall_clock.event')
    on_screen = s + timedelta(seconds=float(lead_sec) + float(t))
    left = (o - on_screen).total_seconds()
    if left <= 0:
        raise ValueError('таймер в кадре в %s, а событие — в %s: отсчёт ушёл в минус'
                         % (on_screen.isoformat(), o.isoformat()))
    return left


def timer_parts(start, lead_sec, t, event):
    """(дни, часы, минуты, секунды) — целые, секунды вниз."""
    total = int(math.floor(seconds_left(start, lead_sec, t, event) + 1e-6))
    d, rest = divmod(total, 86400)
    h, rest = divmod(rest, 3600)
    m, sec = divmod(rest, 60)
    return d, h, m, sec


def timer_at(start, lead_sec, t, event):
    """Строка «Д д ЧЧ:ММ:СС» — что показывает таймер в момент t."""
    d, h, m, s = timer_parts(start, lead_sec, t, event)
    return '%d д %02d:%02d:%02d' % (d, h, m, s)


# ---------------------------------------------------------------- часы в кадре (плагин clock)
CLOCK_FORMATS = ('HH:MM:SS', 'HH:MM')


def clock_seconds(start, lead_sec, t):
    """Секунды от полуночи (в поясе start, дробные) в секунду t склейки: start + lead_sec + t."""
    s = _moment(start, 'wall_clock.start')
    on = s + timedelta(seconds=float(lead_sec) + float(t))
    mid = on.replace(hour=0, minute=0, second=0, microsecond=0)
    return (on - mid).total_seconds()


def clock_text(sec_of_day, fmt='HH:MM:SS'):
    """Табло часов: секунды от полуночи → «ЧЧ:ММ:СС» (секунды вниз, через полночь — по кругу)."""
    if fmt not in CLOCK_FORMATS:
        raise ValueError('формат часов %r — только %s' % (fmt, ', '.join(CLOCK_FORMATS)))
    s = int(math.floor(sec_of_day + 1e-6)) % 86400
    h, rest = divmod(s, 3600)
    m, sec = divmod(rest, 60)
    return '%02d:%02d:%02d' % (h, m, sec) if fmt == 'HH:MM:SS' else '%02d:%02d' % (h, m)


def clock_at(start, lead_sec, t, fmt='HH:MM:SS'):
    """Что показывают часы в секунду t склейки."""
    return clock_text(clock_seconds(start, lead_sec, t), fmt)
