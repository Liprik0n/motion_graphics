# -*- coding: utf-8 -*-
"""Настенное время кадра: таймер до события и часы (engine/video/wallclock.py; плагины timer и clock).

    python engine/video/tests/test_wallclock.py        (секунда, без браузера)

Ожидания посчитаны руками, не списаны с кода. Ролик начинают смотреть в 18:00:00 (+03:00), до первого кадра склейки
идёт 1044,8 с, кадр — на 199-й секунде склейки: 18:00:00 + 1044,8 + 199 = 18:20:43,8. Событие — в полночь того же
пояса: до него 5:39:16,2 → секунды вниз → «0 д 05:39:16». Часы в этот же кадр показывают 18:20:43.
"""
import sys
from pathlib import Path

VIDEO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(VIDEO.parent / 'tests'))
from _util import check, run_module   # noqa: E402

sys.path.insert(0, str(VIDEO))
import wallclock as W  # noqa: E402

START, EVENT = '2030-01-15T18:00:00+03:00', '2030-01-16T00:00:00+03:00'
LEAD, T = 1044.8, 199


def _refuses(fn, word, why):
    try:
        fn()
    except ValueError as e:
        check(word in str(e), 'отказ должен объяснять («%s»): %s' % (word, e))
        return
    check(False, why)


def test_timer_value_by_hand():
    got = W.timer_at(START, LEAD, T, EVENT)
    check(got == '0 д 05:39:16', 'ждали «0 д 05:39:16», получили %r' % got)
    check(W.timer_parts(START, LEAD, T, EVENT) == (0, 5, 39, 16), 'части: %r' % (W.timer_parts(START, LEAD, T, EVENT),))
    s = W.seconds_left(START, LEAD, T, EVENT)
    check(abs(s - 20356.2) < 1e-6, 'секунд до события: ждали 20356,2, получили %r' % s)


def test_start_shift_moves_timer():
    got = W.timer_at('2030-01-15T17:59:00+03:00', LEAD, T, EVENT)
    check(got == '0 д 05:40:16', 'старт на минуту раньше — на минуту больше: %r' % got)


def test_lead_and_offset_are_the_same_axis():
    a = W.timer_at(START, LEAD + 60, T, EVENT)
    b = W.timer_at(START, LEAD, T + 60, EVENT)
    check(a == b == '0 д 05:38:16', 'минута предыстории = минута смещения куска: %r, %r' % (a, b))


def test_other_zone_same_instant():
    got = W.timer_at('2030-01-15T16:00:00+01:00', LEAD, T, EVENT)
    check(got == '0 д 05:39:16', 'тот же момент в другом поясе: %r' % got)


def test_days_counted():
    got = W.timer_at('2030-01-13T18:00:00+03:00', LEAD, T, EVENT)
    check(got == '2 д 05:39:16', 'двое суток раньше: %r' % got)


def test_seconds_go_down_not_round():
    # 18:20:43,8 → до полуночи 16,2 с сверх минут: floor = 16; через 0,3 с осталось 15,9 → 15, а не 16
    got = W.timer_at(START, LEAD, T + 0.3, EVENT)
    check(got == '0 д 05:39:15', 'секунды — вниз: таймер не обещает больше, чем осталось: %r' % got)


def test_past_event_refuses():
    _refuses(lambda: W.timer_at('2030-01-16T00:10:00+03:00', LEAD, T, EVENT), 'минус',
             'таймер после события должен отказывать, а не показывать ноль или минус')


def test_naive_time_refuses():
    _refuses(lambda: W.timer_at('2030-01-15T18:00:00', LEAD, T, EVENT), 'пояс',
             'время без пояса должно отказывать: пояс машины молча сдвинул бы таймер')
    _refuses(lambda: W.clock_at('2030-01-15T18:00:00', LEAD, T), 'пояс', 'часы без пояса должны отказывать')


def test_not_a_time_refuses():
    _refuses(lambda: W.timer_at('вечером', LEAD, T, EVENT), 'ISO', 'не время — отказ с объяснением')


def test_clock_value_by_hand():
    check(W.clock_at(START, LEAD, T) == '18:20:43', 'часы: ждали 18:20:43, получили %r' % W.clock_at(START, LEAD, T))
    check(W.clock_at(START, LEAD, T, 'HH:MM') == '18:20', 'часы HH:MM: %r' % W.clock_at(START, LEAD, T, 'HH:MM'))


def test_clock_shows_zone_of_start():
    # тот же момент, записанный в поясе +01:00, — на стене в том поясе 16:20:43
    got = W.clock_at('2030-01-15T16:00:00+01:00', LEAD, T)
    check(got == '16:20:43', 'часы показывают время пояса start: %r' % got)


def test_clock_wraps_midnight():
    # 23:59:50 + 15 с = 00:00:05 следующих суток
    got = W.clock_at('2030-01-15T23:59:50+03:00', 0, 15)
    check(got == '00:00:05', 'через полночь — по кругу: %r' % got)


def test_clock_unknown_format_refuses():
    _refuses(lambda: W.clock_at(START, LEAD, T, 'H:M'), 'формат', 'неизвестный формат часов — отказ')


if __name__ == '__main__':
    sys.exit(run_module(globals()))
