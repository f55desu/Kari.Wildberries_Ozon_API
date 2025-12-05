import requests
import json
import collections
import pandas as pd
import time
import os
from dotenv import load_dotenv

load_dotenv() # Load variables from .env

API_KEY = os.getenv("API_KEY")

# -------------------------
# 1. Функция: /promotion/count → df_count
# -------------------------

def get_promotion_count_df(API_KEY: str) -> pd.DataFrame:
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

    return df_count


# -------------------------
# 2. Функция: /promotion/adverts → df_adv
# -------------------------

def get_promotion_adverts_df(
    API_KEY: str,
    df_count: pd.DataFrame,
    params: dict | None = None
) -> pd.DataFrame:
    """
    Берёт advertId из df_count, делает запросы /adv/v1/promotion/adverts
    порциями по 50 ID, с задержкой 200 мс,
    и возвращает объединённый df_adv (развёрнутый по nms).
    """
    if df_count.empty:
        raise SystemExit("Нет advertId для запроса /promotion/adverts")

    url_adverts = "https://advert-api.wildberries.ru/adv/v1/promotion/adverts"

    # Все уникальные ID кампаний
    advert_ids = df_count["advertId"].unique().tolist()

    print(f"Найдено {len(advert_ids)} кампаний. Будем запрашивать по 50 штук с паузой 200 мс.")

    if params is None:
        params = {}

    all_rows = []  # сюда будем собирать ответы

    # --- Разбиваем на чанки по 50 ---
    def chunks(lst, size=49):
        for i in range(0, len(lst), size):
            yield lst[i:i + size]

    for chunk_ids in chunks(advert_ids, 49):

        resp_adv = requests.post(
            url_adverts,
            headers={
                "Authorization": API_KEY,
                "Content-Type": "application/json",
            },
            params=params,
            json=chunk_ids,
        )

        print("Status code (adverts chunk):", resp_adv.status_code)
        print("Raw chunk response:", resp_adv.text[:500])  # выводим только начало, чтобы не захламлять

        if resp_adv.status_code == 204:
            print("⚠️ Чанк вернул 204 — пропускаем.")
        elif resp_adv.status_code != 200:
            raise SystemExit(f"Ошибка /promotion/adverts: {resp_adv.status_code} {resp_adv.text}")
        else:
            data_chunk = resp_adv.json()

            if isinstance(data_chunk, list):
                all_rows.extend(data_chunk)
            else:
                print("⚠️ Неожиданная форма данных, пропускаю чанк.")

        # Пауза между запросами
        time.sleep(0.2)

    if not all_rows:
        print("⚠️ Все чанки пустые — df_adv будет пустым.")
        return pd.DataFrame()

    # ----------------------------------------------------------
    # Преобразуем объединённые данные в DataFrame (как раньше)
    # ----------------------------------------------------------
    df_adv = pd.DataFrame(all_rows)

    if "unitedParams" not in df_adv.columns:
        df_adv["unitedParams"] = None

    df_adv = df_adv.explode("unitedParams", ignore_index=True)

    def extract_nms(up):
        if isinstance(up, dict):
            nms = up.get("nms", [])
            if isinstance(nms, collections.abc.Iterable) and not isinstance(nms, (str, bytes)):
                return list(nms)
            else:
                return [nms] if nms is not None else []
        return []

    df_adv["nms_list"] = df_adv["unitedParams"].apply(extract_nms)

    df_adv = df_adv.explode("nms_list", ignore_index=True)
    df_adv = df_adv.rename(columns={"nms_list": "nms"})
    df_adv.drop(columns=["unitedParams"], inplace=True)

    df_adv = df_adv[~df_adv["nms"].isna()].reset_index(drop=True)

    status_map = {
        -1: "удалена",
        4: "готова к запуску",
        7: "завершена",
        8: "отменена",
        9: "активна",
        11: "на паузе",
    }
    df_adv["status_name"] = df_adv["status"].map(status_map).fillna("неизвестный статус")

    time_cols = ["createTime", "startTime", "endTime", "changeTime"]
    for col in time_cols:
        if col in df_adv.columns:
            df_adv[col] = pd.to_datetime(df_adv[col], errors="coerce")

    print("DF после /promotion/adverts (полный):")
    print(df_adv.head())

    return df_adv


# -------------------------
# 3. Функция: объединение и подготовка финального df_final
# -------------------------

def build_final_df(df_count: pd.DataFrame, df_adv: pd.DataFrame) -> pd.DataFrame:
    """
    Объединяет df_count и df_adv, убирает таймзоны и возвращает df_final.
    """
    df_final = df_adv.merge(
        df_count[["advertId", "status_name", "changeTime_count"]],
        on="advertId",
        how="left",
        suffixes=("", "_from_count"),
    )

    # Убираем таймзону у всех столбцов с tz-aware datetime
    for col in df_final.select_dtypes(include=["datetimetz"]).columns:
        df_final[col] = df_final[col].dt.tz_localize(None)

    return df_final

# -------------------------
# Пример использования
# -------------------------

if __name__ == "__main__":

    df_count = get_promotion_count_df(API_KEY)
    df_adv = get_promotion_adverts_df(API_KEY, df_count)
    df_final = build_final_df(df_count, df_adv)

    output_file = "wb_promotion_campaigns_full.xlsx"
    df_final.to_excel(output_file, index=False)
    print(f"Итог записан в: {output_file}")
