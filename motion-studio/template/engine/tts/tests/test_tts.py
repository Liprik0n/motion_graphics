# -*- coding: utf-8 -*-
"""Тесты швов озвучки: смета без сети, подмена провайдера, оплата в точке расхода,
кэш с отказом усечённым записям, redact().

    python tests/test_tts.py [--tmp ПАПКА] [--env-scan ПУТЬ_К_.env ...]

Каждый тест работает на копии `project/` во временной папке — шаблон не трогается.
На всё время прогона `urllib.request.urlopen` и `http.client` подменены заглушкой,
которая роняет тест: **сеть за деньги здесь не открывается**, и если какой-то путь
кода до неё дотянется, тест покраснеет строкой «СЕТЬ ОТКРЫТА», а не заплатит.

`--env-scan` — путь к настоящему `.env`: тест ищет значения его переменных в коде
`engine/tts/` и в собственном выводе прогона и печатает только имена и счёт,
значений не печатает.
"""

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import urllib.request
import http.client
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

TTS_DIR = Path(__file__).resolve().parents[1]
TEMPLATE = TTS_DIR.parents[1]
sys.path.insert(0, str(TTS_DIR))

FAILS = []
NET_CALLS = []


def ok(msg):
    print('  ok   %s' % msg)


def fail(msg):
    FAILS.append(msg)
    print('  FAIL %s' % msg)


def check(cond, msg):
    (ok if cond else fail)(msg)


def _no_net(*a, **k):
    NET_CALLS.append(repr(a[:1]))
    raise RuntimeError('СЕТЬ ОТКРЫТА: тест запрещает любой сетевой вызов')


urllib.request.urlopen = _no_net
http.client.HTTPSConnection.request = _no_net
http.client.HTTPConnection.request = _no_net


def run(argv):
    """tts.main(argv) в этом же процессе; (код, вывод)."""
    import tts
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            code = tts.main(argv)
        except SystemExit as exc:
            print(exc)
            code = exc.code if isinstance(exc.code, int) else 1
    out = buf.getvalue()
    return code, out


def project_copy(tmp, name, provider=None):
    dst = Path(tmp) / name
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(TEMPLATE / 'project', dst / 'project',
                    ignore=shutil.ignore_patterns('.env', 'demo-audio', 'scenes',
                                                  'films', 'director'))
    if provider:
        vpath = dst / 'project' / 'voices.json'
        cfg = json.loads(vpath.read_text(encoding='utf-8'))
        cfg['provider'] = provider
        vpath.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding='utf-8')
    return dst / 'project'


def files(path, pattern):
    return sorted(Path(path).glob(pattern)) if Path(path).exists() else []


def test_estimate(tmp):
    print('смета на демо-rows.json без сети')
    proj = project_copy(tmp, 'est')
    code, out = run(['--estimate', '--project', str(proj)])
    check(code == 0, 'код 0 (был %s)' % code)
    for vid in ('a', 'b'):
        check(('голос %s' % vid) in out, 'смета называет голос %s' % vid)
    check('знаков к оплате' in out, 'смета называет знаки к оплате')
    check('.env' in out, 'без .env смета говорит, что кэш не сверен')
    check(not NET_CALLS, 'сеть не открывалась')


def test_fake_swap(tmp):
    print('подмена провайдера: fake проходит --rows 1-4 --yes-i-pay и --assemble')
    proj = project_copy(tmp, 'fake', provider='fake')
    out_dir = proj / 'out' / 'tts'
    code, out = run(['--rows', '1-4', '--project', str(proj)])
    check(code == 1, 'без --yes-i-pay генерация отказывает (код %s)' % code)
    check('ничего не отправлено' in out, 'отказ говорит «ничего не отправлено»')
    check(not files(out_dir / 'cache', '*.mp3'), 'без согласия кэш пуст')
    code, out = run(['--rows', '1-4', '--yes-i-pay', '--max-chars', '278',
                     '--project', str(proj)])
    check(code == 0, 'с --yes-i-pay --max-chars 278 код 0 (был %s): %s' % (code, out[-300:]))
    check(len(files(out_dir / 'reply', '*.mp3')) == 4, '4 реплики в reply/')
    check(len(files(out_dir / 'cache', '*.mp3')) == 4, '4 записи в cache/')
    man = json.loads((out_dir / 'manifest.json').read_text(encoding='utf-8'))
    check([e['n'] for e in man] == [1, 2, 3, 4], 'манифест о 4 репликах')
    check(all(e['provider'] == 'fake' for e in man), 'в манифесте провайдер fake')
    code, out = run(['--rows', '1-4', '--project', str(proj)])
    check(code == 0 and 'оплачено знаков: 0' in out,
          'повтор без флага берёт всё из кэша и не платит')
    code, out = run(['--assemble', '--project', str(proj)])
    check(code == 0, '--assemble код 0 (был %s): %s' % (code, out[-300:]))
    check([p.name for p in files(out_dir / 'scene', '*.mp3')] == ['demo-a.mp3', 'demo-b.mp3'],
          'склеены сцены demo-a и demo-b')
    man = json.loads((out_dir / 'manifest.json').read_text(encoding='utf-8'))
    check(all('start' in e and 'end' in e for e in man), 'таймлайн: start/end у всех реплик')
    check(man[2]['scene_start'] == 0.0, 'вторая сцена начинается с нуля своей шкалы')
    code, out = run(['--report', '--project', str(proj)])
    check(code == 0 and 'тарифицировано знаков: 278' in out,
          '--report код 0, знаки по манифесту (70+83+101+24)')
    # усечённая запись кэша отвергается: строка снова требует оплаты
    one = files(out_dir / 'cache', '*.mp3')[0]
    data = one.read_bytes()
    one.write_bytes(data[: len(data) // 2])
    code, out = run(['--rows', '1-4', '--project', str(proj)])
    check(code == 1 and 'ничего не отправлено' in out,
          'усечённый кэш не принят за готовый: строка снова к оплате')
    check(not NET_CALLS, 'сеть не открывалась')


def test_pay_point(tmp):
    print('согласие спрашивается в точке расхода')
    import tts
    calls = []

    class Spy:
        name = 'spy'

        def synthesize(self, *a, **k):
            calls.append(a)
            return b''

        def price_chars(self, text):
            return len(text)

    line = {'n': 7, 'speech': 'текст', 'voice': 'a', 'api_emotion': 'calm'}
    try:
        tts.synthesize_paid(Spy(), line, {'speed': 1.0, 'pitch': 0}, pay=False)
        fail('synthesize_paid без согласия не упал')
    except SystemExit as exc:
        check('согласия' in str(exc), 'synthesize_paid без согласия: %s' % exc)
    check(not calls, 'провайдер не вызван ни разу')


def test_minimax_no_env(tmp):
    print('minimax без .env: отказ до сети')
    proj = project_copy(tmp, 'mm')
    code, out = run(['--rows', '1', '--yes-i-pay', '--max-chars', '500', '--project', str(proj)])
    check(code != 0 and '.env' in out, 'нет .env — отказ, названо имя файла')
    check(not NET_CALLS, 'сеть не открывалась')


class SynthCounter:
    """Считает вызовы fake.synthesize — «0 вызовов» проверяется числом, а не выводом."""

    def __init__(self):
        import providers.fake as fake
        self.fake, self.orig, self.calls = fake, fake.Provider.synthesize, []

    def __enter__(self):
        calls, orig = self.calls, self.orig

        def spy(prov, *a, **k):
            calls.append(a[0] if a else '')
            return orig(prov, *a, **k)
        self.fake.Provider.synthesize = spy
        return self

    def __exit__(self, *exc):
        self.fake.Provider.synthesize = self.orig


def test_max_chars(tmp):
    print('лимит знаков: --max-chars обязателен при --yes-i-pay и проверяется до отправки')
    import tts
    proj = project_copy(tmp, 'limit', provider='fake')
    cache = proj / 'out' / 'tts' / 'cache'
    with SynthCounter() as c:
        code, out = run(['--rows', '1-4', '--yes-i-pay', '--project', str(proj)])
    check(code != 0 and '--max-chars' in out and not c.calls,
          'без --max-chars отказ с именем флага, вызовов synthesize: %d' % len(c.calls))
    with SynthCounter() as c:
        code, out = run(['--rows', '1-4', '--yes-i-pay', '--max-chars', '277',
                         '--project', str(proj)])
    check(code != 0 and 'лимит' in out and not c.calls and not files(cache, '*.mp3'),
          'к оплате 278 > лимита 277 — отказ до первой отправки, вызовов: %d' % len(c.calls))
    with SynthCounter() as c:
        code, out = run(['--rows', '1-4', '--yes-i-pay', '--max-chars', 'много',
                         '--project', str(proj)])
    check(code != 0 and not c.calls, 'нечисловой лимит — отказ, вызовов: %d' % len(c.calls))
    with SynthCounter() as c:
        code, out = run(['--rows', '1-2', '--yes-i-pay', '--max-chars', '153',
                         '--project', str(proj)])
    check(code == 0 and len(c.calls) == 2, 'строки 1-2 (70+83=153) в лимит 153 — синтез 2')
    with SynthCounter() as c:
        code, out = run(['--rows', '1-4', '--yes-i-pay', '--max-chars', '125',
                         '--project', str(proj)])
    check(code == 0 and len(c.calls) == 2,
          'в лимит считаются только некэшированные строки (101+24=125), вызовов: %d'
          % len(c.calls))
    # точка расхода: бюджет проверяется в synthesize_paid, даже если смету обошли
    calls = []

    class Spy:
        name = 'spy'

        def synthesize(self, *a, **k):
            calls.append(a)
            return b'x'

        def price_chars(self, text):
            return len(text)
    line = {'n': 1, 'speech': 'десять зн.', 'voice': 'a', 'api_emotion': 'calm'}
    for budget, why in ((None, 'без бюджета'), (tts.Budget(9), 'бюджет 9 < 10')):
        try:
            tts.synthesize_paid(Spy(), line, {'speed': 1.0}, pay=True, budget=budget)
            fail('synthesize_paid %s не упал' % why)
        except SystemExit as exc:
            check(not calls, 'synthesize_paid %s: отказ (%s), вызовов 0' % (why, str(exc)[:60]))
    b = tts.Budget(10)
    tts.synthesize_paid(Spy(), line, {'speed': 1.0}, pay=True, budget=b)
    check(len(calls) == 1 and b.left == 0, 'бюджет 10 на 10 знаков: 1 вызов, остаток 0')
    try:
        tts.synthesize_paid(Spy(), line, {'speed': 1.0}, pay=True, budget=b)
        fail('второй вызов сверх бюджета не упал')
    except SystemExit:
        check(len(calls) == 1, 'второй вызов сверх исчерпанного бюджета не ушёл')


def test_lint_gate(tmp):
    print('платный путь закрыт, пока speech_lint краснеет на оплачиваемых строках')
    proj = project_copy(tmp, 'lintgate', provider='fake')
    rows_p = proj / 'rows.json'
    rows = json.loads(rows_p.read_text(encoding='utf-8'))
    rows[3]['text'] = 'Дежурный на связи: 24 часа.'
    rows_p.write_text(json.dumps(rows, ensure_ascii=False), encoding='utf-8')
    with SynthCounter() as c:
        code, out = run(['--rows', '1-4', '--yes-i-pay', '--max-chars', '5000',
                         '--project', str(proj)])
    check(code != 0 and 'цифры' in out and not c.calls,
          'цифры в строке 4 — отказ с находкой линта, вызовов: %d' % len(c.calls))
    with SynthCounter() as c:
        code, out = run(['--rows', '1-3', '--yes-i-pay', '--max-chars', '5000',
                         '--project', str(proj)])
    check(code == 0 and len(c.calls) == 3, 'строки 1-3 без находок оплачиваются (%d)'
          % len(c.calls))
    edits_p = proj / 'speech_edits.json'
    edits = json.loads(edits_p.read_text(encoding='utf-8'))
    edits['4'] = {'speech': 'Дежурный на связи: двадцать четыре часа.',
                  'why': 'число словами', 'doc': rows[3]['text']}
    edits_p.write_text(json.dumps(edits, ensure_ascii=False), encoding='utf-8')
    with SynthCounter() as c:
        code, out = run(['--rows', '4', '--yes-i-pay', '--max-chars', '5000',
                         '--project', str(proj)])
    check(code == 0 and len(c.calls) == 1, 'после правки в speech_edits строка 4 оплачивается')
    edits['2'] = {'allow': ['носитель'], 'why': ''}
    edits_p.write_text(json.dumps(edits, ensure_ascii=False), encoding='utf-8')
    shutil.rmtree(proj / 'out' / 'tts' / 'cache', ignore_errors=True)
    with SynthCounter() as c:
        code, out = run(['--rows', '2', '--yes-i-pay', '--max-chars', '5000',
                         '--project', str(proj)])
    check(code != 0 and not c.calls,
          'разрешение без основания не снимает находку строки 2, вызовов: %d' % len(c.calls))


def test_exception_redacted(tmp):
    print('любое исключение печатается через redact')
    import tts
    secret = 'sk-TESTSECRET-0042-zz'
    proj = project_copy(tmp, 'exc', provider='fake')
    (proj / '.env').write_text('MINIMAX_API_KEY=%s\n' % secret, encoding='utf-8')
    for exc in (TimeoutError('timed out, key=%s' % secret),
                http.client.RemoteDisconnected('closed: Bearer %s' % secret),
                ValueError('bad %s' % secret)):
        orig = tts.main

        def boom(argv, exc=exc):
            raise exc
        tts.main = boom
        err = io.StringIO()
        try:
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(err):
                code = tts.cli(['--estimate', '--project', str(proj)])
        finally:
            tts.main = orig
        text = err.getvalue()
        check(code == 1 and secret not in text and type(exc).__name__ in text
              and '<MINIMAX_API_KEY>' in text,
              '%s: код 1, секрета нет, имя переменной на месте' % type(exc).__name__)
    import providers.minimax as mm
    prov = mm.Provider({'model': 'm', 'audio_setting': {}, 'voices': {
        'a': {'voice_env': 'MINIMAX_VOICE_A'}}}, {'MINIMAX_API_KEY': secret,
                                                  'MINIMAX_VOICE_A': 'voice-xyz-123'})
    saved = mm.urllib.request.urlopen
    for exc in (TimeoutError('read timeout %s' % secret),
                http.client.RemoteDisconnected('gone %s voice-xyz-123' % secret),
                OSError('reset %s' % secret)):
        def raiser(*a, exc=exc, **k):
            raise exc
        mm.urllib.request.urlopen = raiser
        try:
            prov.synthesize('т', prov.cfg['voices']['a'], 'calm', 1.0, 0)
            fail('minimax: %s не превратился в отказ' % type(exc).__name__)
        except SystemExit as e:
            msg = str(e)
            check(secret not in msg and 'voice-xyz-123' not in msg
                  and e.__cause__ is None and e.__suppress_context__,
                  'minimax %s: отказ без секрета и без цепочки исключений' % type(exc).__name__)
        except Exception as e:
            fail('minimax: %s вышел наружу сырым исключением%s' % (
                type(e).__name__, ' С СЕКРЕТОМ' if secret in str(e) else ''))
        finally:
            mm.urllib.request.urlopen = saved


def test_env_parse(tmp):
    print('.env: комментарии, export, кавычки')
    from envfile import read_env_file
    p = Path(tmp) / 'parse.env'
    p.write_text('\n'.join([
        'A=plain  # комментарий',
        'export B=exported',
        'export C="quoted # не комментарий"  # а это комментарий',
        "D='single'   # c",
        'E=has#hash',
        'F=',
        '# G=commented',
        'H = spaced value  ',
        'I="x"#c',
    ]), encoding='utf-8')
    env = read_env_file(str(p))
    want = {'A': 'plain', 'B': 'exported', 'C': 'quoted # не комментарий', 'D': 'single',
            'E': 'has#hash', 'F': '', 'H': 'spaced value', 'I': 'x'}
    for k, v in want.items():
        check(env.get(k) == v, '%s разобран в голое значение (%d знаков)' % (k, len(v)))
    check('G' not in env and 'export B' not in env, 'закомментированная строка и «export » '
          'в имени не попали в словарь')


def test_redact():
    print('redact() затирает значения всех переменных .env')
    from envfile import redact
    env = {'MINIMAX_API_KEY': 'sk-AAAA1111BBBB', 'MINIMAX_VOICE_A': 'AAAA1111',
           'MINIMAX_GROUP_ID': '99887766', 'SHORT': 'ab', 'EMPTY': ''}
    text = 'key=sk-AAAA1111BBBB voice=AAAA1111 group=99887766 ab'
    red = redact(text, env)
    for v in ('sk-AAAA1111BBBB', 'AAAA1111', '99887766'):
        check(v not in red, 'значение затёрто (%d знаков)' % len(v))
    check('<MINIMAX_API_KEY>' in red, 'длинное затёрто целиком своим именем, '
          'а не по кускам короткого')
    check('<MINIMAX_GROUP_ID>' in red, 'переменная вне списка провайдера тоже затёрта')


def test_env_scan(paths, outputs):
    print('значений .env нет в коде и выводе')
    from envfile import read_env_file
    code_text = ''
    for p in sorted(TTS_DIR.rglob('*')):
        if p.is_file() and p.suffix in ('.py', '.txt', '.json', '.md'):
            code_text += p.read_text(encoding='utf-8', errors='replace')
    for p in sorted((TEMPLATE / 'project').glob('*.json')):
        code_text += p.read_text(encoding='utf-8', errors='replace')
    code_text += (TEMPLATE / 'project' / '.env.example').read_text(encoding='utf-8')
    for path in paths:
        env = read_env_file(path)
        hits = [k for k, v in env.items() if v and len(v) >= 4 and v in code_text]
        check(not hits, '%s: значений %d переменных нет в коде шаблона (совпали: %s)'
              % (os.path.basename(path), len(env), hits))
        hits = [k for k, v in env.items() if v and len(v) >= 4 and v in outputs]
        check(not hits, '%s: значений нет в выводе прогона (совпали: %s)'
              % (os.path.basename(path), hits))
    ex = (TEMPLATE / 'project' / '.env.example').read_text(encoding='utf-8')
    filled = [ln for ln in ex.splitlines()
              if ln.strip() and not ln.startswith('#') and ln.split('=', 1)[1].strip()]
    check(not filled, '.env.example содержит только имена (заполнено: %d)' % len(filled))


def main(argv):
    tmp = argv[argv.index('--tmp') + 1] if '--tmp' in argv else tempfile.mkdtemp()
    scans = [argv[i + 1] for i, a in enumerate(argv) if a == '--env-scan']
    log = io.StringIO()

    class Tee:
        def write(self, s):
            log.write(s)
            sys.__stdout__.write(s)

        def flush(self):
            sys.__stdout__.flush()

    with contextlib.redirect_stdout(Tee()):
        test_estimate(tmp)
        test_fake_swap(tmp)
        test_pay_point(tmp)
        test_minimax_no_env(tmp)
        test_max_chars(tmp)
        test_lint_gate(tmp)
        test_exception_redacted(tmp)
        test_env_parse(tmp)
        test_redact()
    test_env_scan(scans, log.getvalue())
    check(not NET_CALLS, 'за весь прогон ни одного сетевого вызова (%d)' % len(NET_CALLS))
    print('---')
    print('провалов: %d' % len(FAILS))
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
