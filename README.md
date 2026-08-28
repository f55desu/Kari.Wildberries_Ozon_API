# Kari.Wildberries_Ozon_API

<div align="center">

**[English](#-english)  ·  [Русский](#-русский)**

</div>

---

## English

<details open>
<summary><b>Click to expand / collapse the English version</b></summary>

### Overview

A desktop tool (Tkinter GUI + Python package) for exporting **Wildberries advertising campaigns**
through the WB Seller / Advert API, enriching them with the internal product reference
(«Справочник») from the corporate SQL Server, and saving the result to an Excel file.

The repository also contains an experimental script for **bulk creation** of `seacat` campaigns.

### Features

- Pulls the full campaign list via `GET /adv/v1/promotion/count`.
- Filters campaigns by status (ready to launch / finished / cancelled / active / paused).
- Fetches campaign details via `GET /api/advert/v2/adverts` in chunks of 50 ids
  with automatic retries and exponential backoff on `429` and `5xx`.
- Flattens the v2 response (settings, placements, timestamps, `nm_settings`, bids) into a tabular
  `DataFrame`, one row per `advertId` × `nm_id`.
- LEFT-joins the SQL product reference by `nms == [Артикул WB]` (NMID): article, name, brand,
  collection, season, department, cost price, VAT, redemption rate, etc.
- Strips timezones from all datetime values so the file can be written to `.xlsx`.
- GUI with a background export thread, a **Stop** button and a live status log.

### Project structure

```
Kari.Wildberries_Ozon_API/
├── WB_gui.py                    # Tkinter application (entry point)
├── wb_api/
│   ├── Campaing_WB.py           # API calls + building the final DataFrame
│   ├── Goods_Dictionary.py      # SQL product reference (cl01sql) + merge
│   └── Create_Campaing_WB.py    # Bulk creation of seacat campaigns (experimental)
├── Campaing_WB_Old.py           # Legacy script (v1 API), kept for reference
├── WB Campaing Export.spec      # PyInstaller spec
├── app.ico                      # Application icon
├── .env                         # API tokens (NOT in git)
└── dist/                        # Built executable
```

### Requirements

- Python 3.10+
- ODBC Driver 17 for SQL Server (for the product reference)
- Network access to `advert-api.wildberries.ru` and to the `cl01sql` SQL Server
  (Windows authentication / trusted connection)

Python packages:

```bash
pip install requests pandas openpyxl python-dotenv sqlalchemy pyodbc python-calamine
```

### Configuration

Create a `.env` file next to the application:

```
API_KEY_RU="<your WB Seller API token, RU account>"
API_KEY_KZ="<your WB Seller API token, KZ account>"
```

The token is issued in the WB Seller portal: **Settings → Access to the API → Advertising**.
`.env` is listed in `.gitignore` and must never be committed.

### Usage

Run the GUI:

```bash
python WB_gui.py
```

1. Tick the campaign statuses you want to export.
2. Choose the destination `.xlsx` file.
3. Press **Выгрузить** (Export). Progress is shown in the status log; **Стоп** interrupts
   the run after the current chunk.

Run without the GUI (uses `API_KEY_RU` from `.env`):

```bash
python wb_api/Campaing_WB.py
```

Use as a library:

```python
from wb_api import Campaing_WB

df_count = Campaing_WB.get_promotion_count_df(api_key)
df_count = df_count[df_count["status_name"].isin(["активна", "на паузе"])]
df_adv   = Campaing_WB.get_promotion_adverts_df(api_key, df_count)
df_final = Campaing_WB.build_final_df(df_count, df_adv)
df_final.to_excel("wb_promotion_campaigns_full_RU.xlsx", index=False)
```

Pass `with_reference=False` to `build_final_df` to skip the SQL enrichment step.

### Campaign statuses

| Code | Meaning |
| ---: | --- |
| `-1` | deleted |
| `4`  | ready to launch |
| `7`  | finished |
| `8`  | cancelled |
| `9`  | active |
| `11` | paused |

### Building the executable

```bash
pyinstaller "WB Campaing Export.spec"
```

The result is placed in `dist/`. Keep a `.env` file next to the `.exe` — it is read at runtime.

### Notes and limitations

- WB rate limits are strict: the exporter sleeps ~1.2 s between chunks and backs off up to 60 s
  on `429`. A full export of several thousand campaigns takes tens of minutes.
- After the run the script prints a completeness check: requested vs returned ids and the
  type distribution of the missing ones.
- `Create_Campaing_WB.py` **executes on import** and creates real campaigns in WB.
  Do not import it accidentally — run it deliberately and only after reviewing the limits inside.
- Despite the repository name, only the Wildberries part is implemented so far; the Ozon
  integration is not present yet.

</details>

---

## Русский

<details open>
<summary><b>Нажмите, чтобы развернуть / свернуть русскую версию</b></summary>

### Описание

Настольный инструмент (GUI на Tkinter + Python-пакет) для выгрузки **рекламных кампаний
Wildberries** через WB Seller / Advert API, обогащения их внутренним Справочником товаров
из корпоративного SQL Server и сохранения результата в Excel.

В репозитории также лежит экспериментальный скрипт **массового создания** кампаний `seacat`.

### Возможности

- Получение полного списка кампаний через `GET /adv/v1/promotion/count`.
- Фильтрация кампаний по статусам (готова к запуску / завершена / отменена / активна / на паузе).
- Получение детализации через `GET /api/advert/v2/adverts` чанками по 50 id
  с автоматическими ретраями и экспоненциальной задержкой на `429` и `5xx`.
- Разворачивание ответа v2 (settings, placements, timestamps, `nm_settings`, ставки) в плоский
  `DataFrame` — одна строка на `advertId` × `nm_id`.
- LEFT join Справочника из SQL по `nms == [Артикул WB]` (NMID): артикул, наименование, бренд,
  коллекция, сезон, отдел, себестоимость, НДС, процент выкупа и т. д.
- Снятие таймзон со всех datetime-значений, иначе Excel не сохранит файл.
- GUI с выгрузкой в фоновом потоке, кнопкой **Стоп** и живым логом статуса.

### Структура проекта

```
Kari.Wildberries_Ozon_API/
├── WB_gui.py                    # Приложение на Tkinter (точка входа)
├── wb_api/
│   ├── Campaing_WB.py           # Запросы к API + сборка финального DataFrame
│   ├── Goods_Dictionary.py      # Справочник товаров из SQL (cl01sql) + merge
│   └── Create_Campaing_WB.py    # Массовое создание кампаний seacat (эксперимент)
├── Campaing_WB_Old.py           # Старый скрипт (API v1), оставлен для истории
├── WB Campaing Export.spec      # Spec-файл PyInstaller
├── app.ico                      # Иконка приложения
├── .env                         # API-токены (НЕ в git)
└── dist/                        # Собранный исполняемый файл
```

### Требования

- Python 3.10+
- ODBC Driver 17 for SQL Server (для Справочника)
- Доступ к `advert-api.wildberries.ru` и к SQL Server `cl01sql`
  (доменная аутентификация, trusted connection)

Python-пакеты:

```bash
pip install requests pandas openpyxl python-dotenv sqlalchemy pyodbc python-calamine
```

### Настройка

Создайте файл `.env` в одной папке с программой:

```
API_KEY_RU="<ваш API-токен WB Seller, кабинет РФ>"
API_KEY_KZ="<ваш API-токен WB Seller, кабинет КЗ>"
```

Токен выпускается в личном кабинете WB Seller: **Настройки → Доступ к API → Продвижение**.
Файл `.env` перечислен в `.gitignore` и не должен попадать в репозиторий.

### Запуск

Графический интерфейс:

```bash
python WB_gui.py
```

1. Отметьте нужные статусы кампаний.
2. Выберите путь к файлу `.xlsx`.
3. Нажмите **Выгрузить**. Прогресс отображается в логе статуса; кнопка **Стоп** прерывает
   выгрузку после текущего чанка.

Запуск без GUI (использует `API_KEY_RU` из `.env`):

```bash
python wb_api/Campaing_WB.py
```

Использование как библиотеки:

```python
from wb_api import Campaing_WB

df_count = Campaing_WB.get_promotion_count_df(api_key)
df_count = df_count[df_count["status_name"].isin(["активна", "на паузе"])]
df_adv   = Campaing_WB.get_promotion_adverts_df(api_key, df_count)
df_final = Campaing_WB.build_final_df(df_count, df_adv)
df_final.to_excel("wb_promotion_campaigns_full_RU.xlsx", index=False)
```

Передайте `with_reference=False` в `build_final_df`, чтобы пропустить обогащение из SQL.

### Статусы кампаний

| Код | Значение |
| ---: | --- |
| `-1` | удалена |
| `4`  | готова к запуску |
| `7`  | завершена |
| `8`  | отменена |
| `9`  | активна |
| `11` | на паузе |

### Сборка исполняемого файла

```bash
pyinstaller "WB Campaing Export.spec"
```

Результат появится в папке `dist/`. Рядом с `.exe` должен лежать файл `.env` — он читается
при запуске.

### Замечания и ограничения

- Лимиты WB жёсткие: между чанками пауза ~1.2 с, при `429` задержка растёт до 60 с.
  Полная выгрузка нескольких тысяч кампаний занимает десятки минут.
- После завершения скрипт печатает контроль полноты: сколько id запрошено, сколько вернулось
  и распределение типов среди недостающих.
- `Create_Campaing_WB.py` **выполняется при импорте** и создаёт реальные кампании в WB.
  Не импортируйте его случайно — запускайте осознанно и только после проверки лимитов внутри.
- Несмотря на название репозитория, реализована пока только часть Wildberries;
  интеграции с Ozon в проекте нет.

</details>
