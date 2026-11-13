# All The Stone 1 — Stoneblock на 1.21.1 / NeoForge

Сборка «камень вместо мира»: весь оверворлд — сплошной камень от `y=-64` до `y=319`,
игрок стартует в вырубленной комнате 5×5×5 на `0 64 0`, а весь прогресс идёт через
Ex Deorum (молот → сито → галька/гравий/песок/пыль), FTB Quests и тех-моды.

Версия игры: **1.21.1**, загрузчик: **NeoForge 21.1.x** (рекомендуется последний `21.1.266`).

---

## 1. Как запустить (3 шага)

```bash
# 1) скачать моды (Modrinth -> CurseForge -> GitHub releases)
python3 download_mods.py

# 2) проверить, что все файлы сборки валидны
python3 tools/validate_pack.py

# 3) положить папку как instance:
#    <instance>/mods, <instance>/config, <instance>/kubejs
```

Дальше — установить **NeoForge 21.1.266** для 1.21.1 (https://neoforged.net/),
выделить **4–6 ГБ RAM** и запустить.

> Если `download_mods.py` не смог достать часть модов (например, сетевая песочница
> блокирует `cdn.modrinth.com` и `mediafilez.forgecdn.net`), он пишет список
> **`MISSING_MODS.md`** с прямыми ссылками. Скачай их руками в `mods/` и запусти
> скрипт снова — он докачает только отсутствующее.

### Ключ CurseForge (необязательно, но сильно помогает)

```bash
export CF_API_KEY="<твой ключ с https://console.curseforge.com/>"
python3 download_mods.py
```

Без ключа источник CurseForge просто пропускается (в логе будет
`no CurseForge build (or CF_API_KEY not set)`), и скрипт идёт дальше по списку
Modrinth → GitHub.

---

## 2. Что внутри

| Путь | Назначение |
| --- | --- |
| `modlist.json` | каталог модов: Modrinth slug, CurseForge slug, GitHub repo, зачем мод нужен |
| `download_mods.py` | загрузчик: Modrinth API → CurseForge API → GitHub releases, sha512-проверка, отчёт |
| `mods/` | сюда падают `.jar` (в git не коммитятся, см. `.gitignore`) |
| `mods/manifest.json` | CurseForge-манифест (projectID/fileID) для импорта в лаунчер |
| `config/ftbquests/quests/` | квесты: **две главы — Welcome и Stone Age** |
| `kubejs/data/minecraft/worldgen/noise_settings/overworld.json` | сплошной камень, без пещер/руд, бедрок на `-64` и `319` |
| `kubejs/data/allthestone1/…` | отдельное измерение `allthestone1:stone_world` с теми же настройками |
| `kubejs/server_scripts/stone_block_spawn.js` | комната 5×5×5 на `0 64 0`, телепорт при первом входе, `setworldspawn`, защита от «задохнуться в камне» |
| `kubejs/server_scripts/progression.js` | галька (shift + ПКМ пустой рукой, 50%) и стартовые рецепты |
| `tools/validate_pack.py` | проверка JSON/SNBT/квестов/скриптов без запуска игры |

### Моды (30 позиций в каталоге)

* **Основа:** Ex Deorum, KubeJS, Rhino, Architectury API, JEI, Jade, Better Advanced Tooltips
* **FTB:** FTB Library, FTB Teams, FTB Quests, FTB Ultimine
* **Техно/ресурсы:** Mekanism, AE2 (+ GuideME), Powah, Ender IO, Mystical Agriculture (+ Cucumber),
  Industrial Foregoing (+ Titanium), Functional Storage, Pipez, Sophisticated Backpacks (+ Core),
  Cobble For Days
* **Оптимизация:** Embeddium *или* Sodium (не оба!), Ferrite Core, ModernFix, ImmediatelyFast

---

## 3. Каменный мир — как это работает

Два уровня защиты от «игрок задохнулся в камне»:

1. **`noise_settings/overworld.json`** — ванильный оверворлд генерируется сплошным
   `minecraft:stone` (`final_density: 1.0`, без акуиферов, руд и мобов),
   `default_fluid: minecraft:air`, бедрок в `surface_rule` на `-64` и `319`.
2. **Измерение `allthestone1:stone_world`** — использует те же настройки явно.
   JSON-файл не может поменять генератор в уже созданном `level.dat`, поэтому
   скрипт отправляет игрока в отдельное измерение, где камень гарантирован,
   и вырезает комнату командами `/fill`:

```text
x,z = -2..2, y = 64..68   -> воздух (5x5x5)
пол y=63, потолок y=69    -> бедрок (чтобы камень не «затёк» обратно)
внутри: факел, верстак, печь, пол из гладкого камня + каменного кирпича
```

Если стартовая комната нужна в самом оверворлде — в `stone_block_spawn.js`
поставь `BUILD_IN_OVERWORLD = true` (комната и тогда будет вырезана в камне).

**Хочешь классический Stoneblock в оверворлде без отдельного измерения?**
Создай новый мир с типом «Суперплоскость» и пресетом **All The Stone (air room)**
(он лежит в `kubejs/data/minecraft/worldgen/flat_level_generator_preset/`) —
это один слой воздуха, а скрипт всё равно построит комнату и посадит спавн.

---

## 4. Прогрессия

### Камень руками (KubeJS)

* **Shift + ПКМ пустой рукой** по камню/булыжнику/гладкому камню/кирпичам/граниту/
  диориту/андезиту/глубинному сланцу — с шансом **50%** падает `exdeorum:stone_pebble`.
* 4 гальки = булыжник (рецепт Ex Deorum есть, но он продублирован в `progression.js`).

### Стартовые рецепты (`progression.js`)

| Результат | Ингредиенты | Зачем |
| --- | --- | --- |
| `minecraft:crafting_table` | 2 булыжника + 2 гальки | первый верстак без досок |
| `minecraft:stick` ×4 | 2 гальки | палки без дерева |
| `exdeorum:wooden_hammer` | 3 гальки + 2 палки | молот, если стартовый сломался |
| `minecraft:dirt` | 4 гравия + 4 песка/пыли | первая земля |
| `minecraft:bone_meal` | 3 `exdeorum:dust` | костная мука без костей |
| `minecraft:oak_sapling` | земля + 4 костной муки/пыли + галька | **первое дерево** |
| `minecraft:string` ×2 | 2 `exdeorum:wood_chippings` | нитяная сетка для сита |
| `minecraft:flint` | 4 гравия | кремнёвая сетка |
| `minecraft:andesite` / `diorite` / `granite` | булыжник + пыль/костная мука/кремень | варианты сита |
| `minecraft:torch` ×4 | пыль/уголь + палка | свет без угля из шахты |

### Дальше — цепочка Ex Deorum

```
камень --молот--> булыжник --молот--> гравий --молот--> песок --молот--> пыль
гравий/песок/пыль --сито--> руды, семена, глина, кремень
вода + лава --> обсидиан --> Mekanism / Powae / AE2 ...
```

---

## 5. Квесты (FTB Quests)

Ровно **две вкладки**, как и просили:

1. **Welcome** — 3 квеста: вступление, правила выживания (keepInventory, что делать
   если застрял в камне), карта прогрессии.
2. **Stone Age** — 10 квестов: галька → верстак → молот → сито → земля → первое
   дерево → бочка/вода → обсидиан → железо → первая энергия (Heat Generator).

Формат: FTB Quests 1.21.1 (`version: 13`), заголовки и описания — в
`config/ftbquests/quests/lang/en_us.snbt` (в 1.21.1 они хранятся в таблице
переводов, а не в файле главы).

Иконки и предметы в квестах проверены по исходникам модов (Ex Deorum 3.x, FTB Quests 1.21.1);
`tools/validate_pack.py` проверяет id, зависимости и наличие задач.

---

## 6. Диагностика

| Симптом | Что делать |
| --- | --- |
| Игрок появился внутри камня | `/execute in allthestone1:stone_world run tp @s 0 64 0` — скрипт починит комнату сам |
| Комната не построилась | проверь лог `logs/latest.log` на `[allthestone1] dimension ... is not loaded` |
| Квесты пустые | `config/ftbquests/quests/chapters/*.snbt` должны лежать на **сервере**, не в `kubejs/` |
| Не грузится один мод | `python3 download_mods.py --only <slug> --force` и проверь версию в `mods/installed.json` |
| Хочу оверворлд-версию | `BUILD_IN_OVERWORLD = true` в `stone_block_spawn.js` |

---

## 7. Честные ограничения

* `.jar`-файлы **не** лежат в git (`.gitignore`): моды качаются скриптом, чтобы не
  тащить в репозиторий сотни мегабайт и не нарушать лицензии.
* Официальный CurseForge API требует ключ — без него источник пропускается.
* GitHub-фолбэк принимает только те релизы, в имени/теге которых явно есть `1.21.1`;
  иначе мод попадает в `MISSING_MODS.md` (лучше пропустить мод, чем поставить jar
  от другой версии и получить краш).
* Скрипты написаны под KubeJS 7 (1.21.1). Если KubeJS обновится и переименует метод,
  правки нужны только в двух файлах из `kubejs/server_scripts/`.
