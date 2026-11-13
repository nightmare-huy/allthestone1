# All The Stone 1 — статус сборки

Короткая сводка: что уже лежит на диске, что проверено и что нужно сделать руками.
Цель: **Minecraft 1.21.1 + NeoForge 21.1.x**, стиль классического Stoneblock.

---

## ✅ Готово и закоммичено

| Компонент | Файл(ы) | Статус |
| --- | --- | --- |
| Структура сборки | `mods/`, `config/ftbquests/quests/chapters/`, `kubejs/server_scripts/`, `kubejs/startup_scripts/`, `kubejs/data/minecraft/worldgen/noise_settings/` | ✅ |
| Каменный мир (оверворлд) | `kubejs/data/minecraft/worldgen/noise_settings/overworld.json` | ✅ сплошной камень `-64…319`, бедрок сверху и снизу, без пещер/руд/мобов, без воды |
| Отдельное измерение | `kubejs/data/allthestone1/dimension/stone_world.json` + `worldgen/dimension_type/stone_world.json` | ✅ гарантированный камень в новом мире |
| Спавн-комната 5×5×5 | `kubejs/server_scripts/stone_block_spawn.js` | ✅ `/fill` через `execute in`, бедроковая оболочка, факел/верстак/печь, `setworldspawn`, телепорт при первом входе, страховка от «задохнулся в камне» |
| Каменная галька | `kubejs/server_scripts/progression.js` | ✅ shift + ПКМ пустой рукой по камню/булыжнику → 50 % шанс `exdeorum:stone_pebble` |
| Стартовые рецепты | `kubejs/server_scripts/progression.js` | ✅ земля, саженец, палки, верстак из булыжника+гальки, молот, нить, кремень, костная мука, тори |
| Квесты FTB Quests | `config/ftbquests/quests/` | ✅ **ровно 2 вкладки**: Welcome (3 квеста) + Stone Age (10 квестов), формат `version: 13` |
| Загрузчик модов | `download_mods.py` + `modlist.json` | ✅ Modrinth → CurseForge → Maven → GitHub releases, sha512, `.mrpack`, отчёт о недостающих |
| Проверки | `tools/validate_pack.py`, `tools/test_downloader.py` | ✅ 0 ошибок, всё зелёное |

Проверить самому:

```bash
python3 tools/validate_pack.py      # JSON + SNBT + граф квестов + скрипты
python3 tools/test_downloader.py    # логика выбора версий (офлайн)
```

---

## 📦 Моды уже скачаны

29 jar-ов для 1.21.1 / NeoForge собраны CI и лежат в:
* релизе **`mods-latest`** этого репозитория (+ `allthestone1-1.0.0.mrpack` и `installed.json`);
* ветке **`mods-store`** (только jar-ы, чтобы забирать по git-протоколу):

```bash
git fetch origin mods-store
git archive FETCH_HEAD mods | tar -x
python3 tools/check_mods.py     # 29 mod ids, 0 ошибок, 0 предупреждений
```

CI-прогон `fetch-mods` скачал их с Modrinth (24) и Maven `maven.ftb.dev` (4 FTB-мода),
плюс Mekanism/JEI через Maven-резерв; сборка повторяется при каждом изменении
`modlist.json` и по расписанию (каждый понедельник).

## ⚠️ Ограничение этой песочницы (важно)

Сеть здесь разрешает **только** `api.github.com`, `github.com` (git) и прокси для чтения
страниц.
`cdn.modrinth.com`, `mediafilez.forgecdn.net`, `objects.githubusercontent.com`,
`maven.blamejared.com` и т.п. **закрыты на уровне TLS**, поэтому **ни один `.jar`
физически не скачался** — это ограничение окружения, а не скрипта.
Именно поэтому `.jar`-файлы не лежат в репозитории (и не должны: лицензии + вес).

Что скрипт делает в таких условиях (проверено запуском):

1. Пытается Modrinth → CurseForge → Maven → GitHub;
2. честно пишет `MISSING_MODS.md` со ссылками на скачивание;
3. собирает `mods/manifest.json` (CurseForge-манифест) и умеет `--mrpack`
   (Modrinth-пак, где jar-ы качает сам лаунчер — этот путь работает даже без
   прямого доступа к CDN).

---

## 🚀 Как доукомплектовать моды (1 минута)

**Вариант A — обычный ПК с интернетом (рекомендую):**

```bash
python3 download_mods.py                  # скачает всё сам
export CF_API_KEY="ключ с console.curseforge.com"   # опционально: + источник CurseForge
python3 download_mods.py                  # добьёт то, чего нет на Modrinth
```

**Вариант B — лаунчер качает сам (без прямого доступа к CDN):**

```bash
python3 download_mods.py --mrpack allthestone1-1.0.0.mrpack
```

Полученный `.mrpack` импортируется в Prism/ATLauncher/Modrinth App — они сами
скачают все 30 модов в нужных версиях, а `config/` и `kubejs/` уже внутри архива.

**Вариант C — руками:** открыть `MISSING_MODS.md`, скачать jar-ы по ссылкам в
`mods/`, затем ещё раз `python3 download_mods.py` (он пропустит уже имеющееся).

Затем: NeoForge **21.1.266** для 1.21.1, 4–6 ГБ RAM, запуск.

---

## 🎮 Что игрок увидит при первом входе

1. Спавн в комнате 5×5×5 (`0 64 0`) внутри измерения `allthestone1:stone_world`.
2. В инвентаре: квест-бук, деревянный молот, нитяная сетка, 16 факелов.
3. Две вкладки квестов: **Welcome** (вступление / правила / карта) и
   **Stone Age** (галька → верстак → молот → сито → земля → дерево → бочка →
   обсидиан → железо → первая энергия).
4. Застрял в камне? Перезайди или подожди секунду — скрипт вытащит в комнату.

---

## 📌 Если нужен камень именно в оверворлде

В `kubejs/server_scripts/stone_block_spawn.js`:

```js
const BUILD_IN_OVERWORLD = true
```

Комната тогда вырезается прямо в ванильном оверворлде (его генератор уже сделан
сплошным камнем через `noise_settings`). Либо создавай новый мир с пресетом
суперплоскости **All The Stone (air room)** — он лежит в
`kubejs/data/minecraft/worldgen/flat_level_generator_preset/`.

Подробности — в `README.md`.
