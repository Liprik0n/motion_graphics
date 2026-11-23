# -*- coding: utf-8 -*-
"""Данные фильма, вшитые в страницу (<script>window.__FILM__ = …): чужая строка не закрывает скрипт — engine/video/build.py.

    python engine/video/tests/test_page_data.py        (секунда, без браузера)

В данные фильма попадает чужое: файл анимации Lottie вшивается целиком (имена слоёв — любые строки), тексты и
подписи пишет автор сцены. По правилам разбора HTML содержимое <script> кончается на первом «</script», что бы ни
стояло вокруг в JavaScript: строка «</script><script>…» внутри JSON закрыла бы скрипт данных и открыла свой,
исполняемый (промеры открывают страницу без песочницы). «<!--» вместе с «<script» включает режим, где настоящий
«</script>» скрипт уже не закрывает. Ожидание — из правил HTML, не из кода сборки: во вшитом тексте нет ни одного
знака «<», а разбор текста как JSON возвращает те же данные. Скрипты считает разборщик HTML из стандартной
библиотеки (html.parser) — он режет <script> по тому же правилу.
"""
import json
import sys
from html.parser import HTMLParser
from pathlib import Path

VIDEO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(VIDEO.parent / 'tests'))
from _util import check, run_module   # noqa: E402

sys.path.insert(0, str(VIDEO))
import build as B     # noqa: E402
import stamp          # noqa: E402

EVIL = '</script><script>window.__INJECTED__ = 1;</script><script>'
DATA = {'film': 't', 'duration': 2.0, 'scenes': [{'id': 's1', 'start': 0.0, 'end': 2.0, 'plugins': {'lottie': {'items': [
    {'id': 'anim', 'data': {'nm': 'pulse', 'layers': [{'nm': EVIL}, {'nm': '<!-- <script>'}, {'nm': '</SCRIPT >'}]}}]}}}],
    'elements': [{'scene': 's1', 'text': 'a < b и <b>жирный</b> — законный текст'}], 'replies': [], 'boxes': {}}


class Scripts(HTMLParser):
    """Содержимое каждого элемента <script> страницы — как его режет браузер."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.scripts, self._open = [], False

    def handle_starttag(self, tag, attrs):
        if tag == 'script':
            self._open = True
            self.scripts.append('')

    def handle_endtag(self, tag):
        if tag == 'script':
            self._open = False

    def handle_data(self, data):
        if self._open:
            self.scripts[-1] += data


def test_embedded_json_has_no_markup_and_round_trips():
    text = B.script_json(DATA)
    check('<' not in text, 'во вшитом JSON остался знак «<»: строка данных может закрыть <script> — %s' % text[:200])
    check(json.loads(text) == DATA, 'вшитый текст после разбора JSON — не те же данные')


def test_layer_name_does_not_open_second_script():
    page = '<body>\n<script>window.__FILM__ = %s;</script>\n<script>var stage = 1;</script>\n</body>' % B.script_json(DATA)
    p = Scripts()
    p.feed(page)
    check(len(p.scripts) == 2, 'на странице ждали два скрипта (данные и движок), разборщик HTML нашёл %d: %s'
          % (len(p.scripts), [s[:60] for s in p.scripts]))
    check(not any(s.strip().startswith('window.__INJECTED__') for s in p.scripts), 'имя слоя стало исполняемым скриптом')


def test_scene_stamp_still_reads_embedded_data():
    """Отметка сцены (stamp.py) читает данные фильма из страницы: экранирование её не ломает."""
    page = '<script>window.__FILM__ = %s;</script>' % B.script_json(DATA)
    a = page.find(stamp.FILM_HEAD)
    b = page.find(stamp.FILM_TAIL, a)
    check(a == 0 and b > 0, 'в странице нет начала или конца данных фильма по правилу stamp.py')
    check(page.count(stamp.FILM_TAIL) == 1, 'конец данных фильма встречается в странице не один раз')
    check(json.loads(page[a + len(stamp.FILM_HEAD):b]) == DATA, 'stamp.py прочёл бы не те данные')


if __name__ == '__main__':
    sys.exit(run_module(globals()))
