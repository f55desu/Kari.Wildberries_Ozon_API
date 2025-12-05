import requests
import json
import collections
import pandas as pd

API_KEY = "eyJhbGciOiJFUzI1NiIsImtpZCI6IjIwMjUwOTA0djEiLCJ0eXAiOiJKV1QifQ.eyJhY2MiOjEsImVudCI6MSwiZXhwIjoxNzc5OTk2ODQ4LCJpZCI6IjAxOWFjNDNiLWRjMDEtN2RlMS1iZWJjLTM0ZGVjNDE2NmI1MCIsImlpZCI6MTU4MTg5MDYsIm9pZCI6NDE2MTA2OCwicyI6MTYxMjYsInNpZCI6IjQ0OTAyOWU4LTkxYmItNDNhOC1iM2IyLTFkYTBhMmY3NjdiNSIsInQiOmZhbHNlLCJ1aWQiOjE1ODE4OTA2fQ.6xWz0isz52O--s6Ara1oYORzTB0r-4gTQX8YI610sYQUu3LzueK0m8ooyfCHw2rvBupqzV7wGJ4wIjIqi32-zA"

url_count = "https://advert-api.wildberries.ru/adv/v1/promotion/count"
headers = {"Authorization": API_KEY}

resp = requests.get(url_count, headers=headers)
print("Status code (count):", resp.status_code)
print("Raw text (count):", resp.text)

if resp.status_code != 200:
    raise SystemExit(f"Ошибка запроса /promotion/count: {resp.status_code} {resp.text}")

data_count = json.loads(resp.text)
adverts_blocks = data_count.get("adverts", [])

# Если кампаний вообще нет
if not adverts_blocks:
    print("По /promotion/count кампаний нет (adverts пустой).")
    df_count = pd.DataFrame()
else:
    # Разворачиваем структуру count → плоский список кампаний
    rows = []
    for block in adverts_blocks:
        t = block.get("type")
        status_code = block.get("status")
        advert_list = block.get("advert_list") or []

        for adv in advert_list:
            rows.append(
                {
                    "advertId": adv.get("advertId"),
                    "changeTime_count": adv.get("changeTime"),
                    "type": t,
                    "status": status_code,
                }
            )

    df_count = pd.DataFrame(rows)

    # Маппинг статусов
    status_map = {
        -1: "удалена",
        4: "готова к запуску",
        7: "завершена",
        8: "отменена",
        9: "активна",
        11: "на паузе",
    }
    df_count["status_name"] = df_count["status"].map(status_map).fillna("неизвестный статус")

print("DF после /promotion/count:")
print(df_count)

# Если нечего запрашивать дальше
if df_count.empty:
    raise SystemExit("Нет advertId для запроса /promotion/adverts")

# -------------------------
# 2. По полученным advertId вызываем /adv/v1/promotion/adverts
# -------------------------
url_adverts = "https://advert-api.wildberries.ru/adv/v1/promotion/adverts"

# Массив ID кампаний из df_count
advert_ids = df_count["advertId"].unique().tolist()

# ВНИМАНИЕ: по докам этот метод работает для устаревших типов 4-8.
# Если у тебя только type=9 — он может вернуть пусто или ошибку.
# Для простоты отправляем всё, что есть.
print("Будем запрашивать детализацию по следующим advertId:", advert_ids)

# Можно (но не обязательно) задать фильтры в query params:
# param_status = None  # например, 9 — активна
# param_type = None    # например, 4
params = {
    # "status": 9,
    # "type": 4,
    # "order": "create",    # create / change / id
    # "direction": "desc",  # desc / asc
}

resp_adv = requests.post(
    url_adverts,
    headers={
        "Authorization": API_KEY,
        "Content-Type": "application/json",
    },
    params=params,
    json=advert_ids,   # тело запроса — список ID кампаний
)

print("Status code (adverts):", resp_adv.status_code)
print("Raw text (adverts):", resp_adv.text)

if resp_adv.status_code == 204:
    raise SystemExit("По /promotion/adverts кампании не найдены (204).")
if resp_adv.status_code != 200:
    raise SystemExit(f"Ошибка /promotion/adverts: {resp_adv.status_code} {resp_adv.text}")

data_adverts = resp_adv.json()  # ожидаем массив объектов кампаний

# -------------------------
# 3. Преобразуем ответ /promotion/adverts в DataFrame
# -------------------------
# Пример одного объекта в ответе по докам:
# {
#   "endTime": "2023-10-05T21:37:37.226021+03:00",
#   "createTime": "2023-08-21T13:45:31.121172+03:00",
#   "changeTime": "2023-08-21T14:59:33.622594+03:00",
#   "startTime": "2023-08-21T13:45:31.147601+03:00",
#   "autoParams": {},
#   "name": "Кампания1",
#   "dailyBudget": 0,
#   "advertId": 11111111,
#   "status": 7,
#   "type": 8,
#   "paymentType": "cpm"
# }

df_adv = pd.DataFrame(data_adverts)

# Если столбца unitedParams нет вообще — просто добавим пустой и пойдём дальше
if "unitedParams" not in df_adv.columns:
    df_adv["unitedParams"] = None

# 1) Разворачиваем список unitedParams (list[dict]) в строки
df_adv = df_adv.explode("unitedParams", ignore_index=True)

# 2) Из каждого dict в unitedParams достаём список nms
def extract_nms(up):
    if isinstance(up, dict):
        nms = up.get("nms", [])
        # гарантируем, что это список
        if isinstance(nms, collections.abc.Iterable) and not isinstance(nms, (str, bytes)):
            return list(nms)
        else:
            return [nms] if nms is not None else []
    return []

df_adv["nms_list"] = df_adv["unitedParams"].apply(extract_nms)

# 3) Разворачиваем nms_list → один nm на строку
df_adv = df_adv.explode("nms_list", ignore_index=True)

# 4) Переименовываем столбец в nms и очищаем
df_adv = df_adv.rename(columns={"nms_list": "nms"})
df_adv.drop(columns=["unitedParams"], inplace=True)

# Если хочешь отбросить строки без номенклатуры
df_adv = df_adv[~df_adv["nms"].isna()].reset_index(drop=True)

# Маппим статус в читаемый вид
status_map = {
    -1: "удалена",
    4: "готова к запуску",
    7: "завершена",
    8: "отменена",
    9: "активна",
    11: "на паузе",
}
df_adv["status_name"] = df_adv["status"].map(status_map).fillna("неизвестный статус")

# (Опционально) конвертируем время в datetime для дальнейшей аналитики
time_cols = ["createTime", "startTime", "endTime", "changeTime"]
for col in time_cols:
    if col in df_adv.columns:
        df_adv[col] = pd.to_datetime(df_adv[col], errors="coerce")

print("DF после /promotion/adverts:")
print(df_adv.head())

# -------------------------
# 4. Объединяем count + adverts (если нужно) и сохраняем в Excel
# -------------------------
# Джойним по advertId, чтобы в итоговой табличке были и данные из count, и детализация
df_final = df_adv.merge(
    df_count[["advertId", "status_name", "changeTime_count"]],
    on="advertId",
    how="left",
    suffixes=("", "_from_count"),
)

# Убираем таймзону у всех столбцов с tz-aware datetime
for col in df_final.select_dtypes(include=["datetimetz"]).columns:
    df_final[col] = df_final[col].dt.tz_localize(None)

output_file = "wb_promotion_campaigns_full.xlsx"
df_final.to_excel(output_file, index=False)
print(f"Итог записан в: {output_file}")