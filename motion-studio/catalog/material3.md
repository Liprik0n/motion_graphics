# Material 3 — числа из токенов Google

Ролик «в стиле Material Design 3» берёт числа отсюда, а не из памяти. Стиля `material3` в каталоге
шаблона нет: его делают стилем проекта (`project/styles/<имя>/`, см. [styles.md](styles.md)).

Источники сверены 2026-11-18. Сайт m3.material.io — JS-оболочка, текст через загрузку не отдаёт, поэтому
числа взяты из токенов, из которых он собран:

- material-web, `tokens/versions/v0_192/`: `_md-sys-motion.scss`, `_md-sys-shape.scss`,
  `_md-sys-elevation.scss`, `_md-comp-elevated-card.scss`, `_md-comp-assist-chip.scss`
  (github.com/material-components/material-web);
- androidx Compose Material 3, `compose/material3/material3/src/commonMain/kotlin/androidx/compose/material3/`:
  `tokens/ExpressiveMotionTokens.kt`, `tokens/ShapeTokens.kt`, `tokens/ElevatedCardTokens.kt`,
  `MaterialShapes.kt` (github.com/androidx/androidx).

## 1. Кривые (web)

| Токен | Значение |
|---|---|
| `easing-emphasized` | `cubic-bezier(0.2, 0, 0, 1)` — в web совпадает со standard |
| `easing-emphasized-decelerate` | `cubic-bezier(0.05, 0.7, 0.1, 1)` — вход на экран |
| `easing-emphasized-accelerate` | `cubic-bezier(0.3, 0, 0.8, 0.15)` — уход |
| `easing-standard` | `cubic-bezier(0.2, 0, 0, 1)` |
| `easing-standard-decelerate` / `-accelerate` | `(0, 0, 0, 1)` / `(0.3, 0, 1, 1)` |
| `easing-legacy` | `(0.4, 0, 0.2, 1)` — Material 2, для M3 не брать |

## 2. Длительности — шкала с шагом 50 мс

| Ступень | 1 | 2 | 3 | 4 |
|---|---|---|---|---|
| short | 50 | 100 | 150 | 200 |
| medium | 250 | 300 | 350 | 400 |
| long | 450 | 500 | 550 | 600 |
| extra-long | 700 | 800 | 900 | 1000 |

**Подписывать длительность именем токена** — `0,45 с = long1`, а не «среднее». В первом промо в духе M3 свои
имена разошлись с M3: «short 0,25» там — это M3 medium1, «medium 0,45» — long1. Числа были на шкале,
подписи — нет, и сверка потратила время на то, чего не было.

Шкала — нормы интерфейса, где пользователь ждёт. В ролике крупное сценическое движение длиннее
(0,6–1,2 с): брать extra-long и называть это прямо.

## 3. Пружины Expressive — движение M3 Expressive задаётся ими, а не кривой

Две семьи: **spatial** — положение, размер, поворот, форма (перелёт допустим); **effects** — цвет и
непрозрачность (без перелёта). Масса 1. Перелёт и время успокоения до 2 % посчитаны интегрированием
и сверены с формулой `exp(−πζ/√(1−ζ²))`.

| Токен | ζ (damping) | k (stiffness) | перелёт | успокоение, с | GSAP `back.out(c)` с тем же перелётом |
|---|---|---|---|---|---|
| spatial fast | 0,6 | 800 | 9,48 % | 0,21 | `c = 1.65` |
| spatial default | 0,8 | 380 | 1,52 % | 0,19 | `c = 0.654` |
| spatial slow | 0,8 | 200 | 1,52 % | 0,27 | `c = 0.654` |
| effects fast | 1,0 | 3800 | 0 | 0,10 | кривая без перелёта |
| effects default | 1,0 | 1600 | 0 | 0,15 | то же |
| effects slow | 1,0 | 800 | 0 | 0,21 | то же |

Как применять в движке (кривые там — строки GSAP):

- **Мелкое** — иконка, чип, точка — spatial fast: `back.out(1.65)`.
- **Крупное** — герой-шейп, карточка во весь кадр, морф формы — spatial default/slow: `back.out(0.654)`.
  Перелёт почти не виден, и это правило M3, а не недосмотр.
- **Цвет и непрозрачность** не пружинят никогда: `power2.out` или emphasized decelerate.
- Пик `back.out(c)` = `4c³ / 27(c+1)²` — так перелёт пересчитывается в `c` и обратно (проверено
  перебором: `c = 1.4` → 7,06 %). Потолок перелёта в стиле проекта ставить по этой таблице, а не «≤ 8 %»
  на всё: в первом промо в духе M3 крупные шейпы перелетали как мелкие (≈ 7 % против 1,5 % по M3).
- Время успокоения — для экрана телефона; в ролике длительность действия задаёт раскадровка, пружина
  задаёт только форму кривой.

## 4. Формы

Скругления, dp: none 0 · extra-small 4 · small 8 · medium 12 · large 16 · large-increased 20 ·
extra-large 28 · extra-large-increased 32 · extra-extra-large 48 · full.

| Компонент | Скругление | Высота |
|---|---|---|
| карточка (elevated/filled/outlined) | medium 12 | — |
| чип (assist и др.) | small 8 | 32 |
| кнопка | full | — |
| лист снизу | extra-large-top 28 | — |

**dp в пиксели кадра — через масштаб, а не один к одному.** Кадр 1920 не экран телефона: масштаб
задаёт высота чипа. Чип высотой 96 px — это 32 dp × 3, значит карточке положено 12 × 3 = 36 px,
чипу — 8 × 3 = 24 px. Писать скругление числом без масштаба — значит промахнуться в 2–3 раза в любую
сторону.

Библиотека форм Expressive (`MaterialShapes`, 35): Circle, Square, Slanted, Arch, Fan, Arrow, SemiCircle,
Oval, Pill, Triangle, Diamond, ClamShell, Pentagon, Gem, Sunny, VerySunny, Cookie4Sided, Cookie6Sided,
Cookie7Sided, Cookie9Sided, Cookie12Sided, Ghostish, Clover4Leaf, Clover8Leaf, Burst, SoftBurst, Boom,
SoftBoom, Flower, Puffy, PuffyDiamond, PixelCircle, PixelTriangle, Bun, Heart. Шейп стиля называть именем
отсюда. Геометрию Google задаёт `RoundedPolygon` (androidx graphics-shapes); своя отрисовка — приближение.

## 5. Тени

Уровни, dp: level0 0 · level1 1 · level2 3 · level3 6 · level4 8 · level5 12. Карточка elevated — level1.
Уровень называть по этой шкале и пересчитывать в пиксели тем же масштабом, что и формы.

## 6. Что этим файлом не покрыто

- **Тональная палитра.** M3 строит тона от цвета-семени в пространстве HCT (material-color-utilities).
  Библиотеки на машине нет; тона, подобранные на глаз, называть «приближением M3», а не тонами M3.
- **Типографика.** Шкала M3 в sp для экрана (display-large 57/64) в кадр видео прямо не переносится;
  кегли ролика — роли `tokens.json type` и порог V38.
