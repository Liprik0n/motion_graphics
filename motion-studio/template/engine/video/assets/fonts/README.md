# Шрифты движка: файлы, источник, лицензия

Все шрифты движка лежат здесь файлами: на другой машине кадр тот же, системные шрифты Windows по имени
не берутся. Свой шрифт проекта — в `tokens.json fonts` (файл в `<проект>/assets/fonts`), с лицензией на файлы
и строкой в `materials.json`.

## Демо-шрифт шаблона

`LiberationSansNarrow-Regular.ttf`, `LiberationSansNarrow-Bold.ttf` — Liberation Sans Narrow.

- Copyright 2010 Oracle and/or its affiliates. Liberation is a trademark of Red Hat, Inc.
- Лицензия — Liberation Fonts license (GNU GPL v2 с исключением для шрифтов: документ, в который встроен
  шрифт, лицензией не затрагивается), так записано в самих файлах (таблица `name`, поля 13 и 14):
  <https://fedoraproject.org/wiki/Licensing/LiberationFontLicense>.
- Текст лицензии — `LICENSE-LiberationSansNarrow.txt` рядом: соглашение «Liberation Font Software» (Red Hat) и
  GNU GPL версии 2, на которую оно ссылается. Слова не менялись, свои только переносы строк соглашения; взято с
  этой машины: соглашение — из `license.txt` установленного LibreOffice (раздел Liberation), GPL v2 — из
  `LICENSE.txt` установленного Git for Windows. Это не OFL: шрифт идёт с этим файлом, а не с `OFL-….txt`.

Шрифт нужен демо и проверкам шаблона.

## Шрифты стилей

Заголовки и надписи миров (`styles/<имя>/style.json fonts`). Лицензия у всех — SIL Open Font License 1.1 (OFL),
текст лицензии каждого семейства — файл `OFL-<семейство>.txt` рядом. Источник — репозиторий Google Fonts
`https://github.com/google/fonts`, папка `ofl/<папка>/`; файлы взяты 2026-11-22 без изменений (вариативные —
целиком, вес задаёт `style.json`), переименованы только те, в чьём имени были квадратные скобки. У каждого
есть кириллица: её проверяет сборка (`styles/_core/registry.py has_cyrillic`).

| Семейство | Файл здесь | Файл в источнике | Папка в источнике | Размер, байт | Лицензия | Кому |
|---|---|---|---|---|---|---|
| Rubik | `Rubik-wght.ttf` | `Rubik[wght].ttf` | `ofl/rubik` | 359 804 | `OFL-Rubik.txt` | заголовок `paper-cut` (700) и `fabric` (900), буквы `clay` (700) |
| Oswald | `Oswald-wght.ttf` | `Oswald[wght].ttf` | `ofl/oswald` | 172 088 | `OFL-Oswald.txt` | заголовок и надписи `comic` (700), вырезки `zine` |
| Old Standard TT | `OldStandard-Bold.ttf` | то же | `ofl/oldstandardtt` | 267 128 | `OFL-OldStandardTT.txt` | заголовок `engravure`, вырезки `zine` |
| Old Standard TT | `OldStandard-Italic.ttf` | то же | `ofl/oldstandardtt` | 272 692 | `OFL-OldStandardTT.txt` | надписи `engravure` |
| PT Serif | `PT_Serif-Web-Bold.ttf` | то же | `ofl/ptserif` | 339 996 | `OFL-PTSerif.txt` | заголовок `film`, вырезки `zine` |
| IBM Plex Mono | `IBMPlexMono-Bold.ttf` | то же | `ofl/ibmplexmono` | 137 784 | `OFL-IBMPlexMono.txt` | надписи `film` и `zine` |
| Golos Text | `GolosText-wght.ttf` | `GolosText[wght].ttf` | `ofl/golostext` | 184 292 | `OFL-GolosText.txt` | заголовок `flat-edu` (900), вырезки `zine` |
| Open Sans | `OpenSans-wdth-wght.ttf` | `OpenSans[wdth,wght].ttf` | `ofl/opensans` | 532 636 | `OFL-OpenSans.txt` | заголовок (300) и надписи (400) `glass` |
| Comic Relief | `ComicRelief-Bold.ttf` | то же | `ofl/comicrelief` | 94 684 | `OFL-ComicRelief.txt` | заголовок `line-boil`, вырезки `zine` |
| Comic Relief | `ComicRelief-Regular.ttf` | то же | `ofl/comicrelief` | 80 324 | `OFL-ComicRelief.txt` | надписи `line-boil` |
| Sofia Sans | `SofiaSans-wght.ttf` | `SofiaSans[wght].ttf` | `ofl/sofiasans` | 345 684 | `OFL-SofiaSans.txt` | заголовок `neon-line` и `tv-splash` (700) |
| Caveat | `Caveat-wght.ttf` | `Caveat[wght].ttf` | `ofl/caveat` | 403 648 | `OFL-Caveat.txt` | заголовок (700) и надписи (400) `sketchbook` |
| Press Start 2P | `PressStart2P-Regular.ttf` | то же | `ofl/pressstart2p` | 118 204 | `OFL-PressStart2P.txt` | пиксельный заголовок и табло `pixel` |

Заменить шрифт стиля: положить файл сюда или в `<проект>/assets/fonts`, назвать его первым в
`style.json fonts.<роль>.files`, добавить строку в эту таблицу и файл лицензии. Шрифт без права
распространения (системный, купленный на одно рабочее место) сюда не кладётся.
