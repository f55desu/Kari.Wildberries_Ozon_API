import requests
import json
import collections
import pandas as pd
import time
import os
import random
from dotenv import load_dotenv

load_dotenv() # Load variables from .env

API_KEY = os.getenv("API_KEY_RU")

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
    Берёт advertId из df_count, делает запросы /adv/v1/promotion/adverts чанками по 49,
    ретраит 429/5xx с увеличением задержки,
    показывает прогресс,
    и в конце печатает контроль полноты (missing ids и распределение типов по missing).
    """
    if df_count.empty:
        raise SystemExit("Нет advertId для запроса /promotion/adverts")

    url_adverts = "https://advert-api.wildberries.ru/adv/v1/promotion/adverts"

    if params is None:
        params = {}

    # ВАЖНО: держим связку advertId -> type, чтобы понять, чего не хватает
    df_ids = df_count[["advertId", "type"]].dropna().drop_duplicates()
    advert_ids = df_ids["advertId"].astype(int).tolist()

    total_ids = len(advert_ids)
    if total_ids == 0:
        return pd.DataFrame()

    chunk_size = 49
    total_chunks = (total_ids + chunk_size - 1) // chunk_size

    print(f"[START] advertId total={total_ids}, chunks={total_chunks}, chunk_size={chunk_size}")

    headers = {"Authorization": API_KEY, "Content-Type": "application/json"}
    session = requests.Session()

    # Настройки ретраев/пауз
    max_attempts = 30
    base_backoff = 1.0
    max_backoff = 60.0
    normal_sleep = 1.2
    retry_statuses = {429, 500, 502, 503, 504}

    all_rows = []
    returned_ids = set()

    def backoff_sleep(attempt: int, resp_headers: dict | None = None):
        # retry-after, если есть
        if resp_headers:
            ra = resp_headers.get("Retry-After")
            if ra:
                try:
                    s = float(ra)
                    time.sleep(min(max_backoff, s))
                    return
                except ValueError:
                    pass

        s = min(max_backoff, base_backoff * (2 ** (attempt - 1)))
        s *= (1.0 + random.random() * 0.2)
        time.sleep(s)

    def extract_returned_ids(data_list: list) -> set[int]:
        out = set()
        for obj in data_list:
            if isinstance(obj, dict) and "advertId" in obj:
                try:
                    out.add(int(obj["advertId"]))
                except Exception:
                    pass
        return out

    # --- основной проход по чанкам ---
    for chunk_idx in range(total_chunks):
        start = chunk_idx * chunk_size
        end = min(start + chunk_size, total_ids)
        chunk_ids = advert_ids[start:end]

        attempt = 0
        while True:
            attempt += 1
            try:
                resp = session.post(
                    url_adverts,
                    headers=headers,
                    params=params,
                    json=chunk_ids,
                    timeout=60,
                )

                code = resp.status_code

                # ПРОГРЕСС
                print(f"[{chunk_idx+1}/{total_chunks}] ids={len(chunk_ids)} attempt={attempt} status={code}")

                if code == 200:
                    data_chunk = resp.json()
                    if isinstance(data_chunk, list) and data_chunk:
                        all_rows.extend(data_chunk)
                        ids_got = extract_returned_ids(data_chunk)
                        returned_ids |= ids_got
                        print(f"    got_objects={len(data_chunk)} got_unique_ids={len(ids_got)} "
                              f"total_unique_ids={len(returned_ids)}")
                    else:
                        print("    200 OK but empty list (no objects).")

                    time.sleep(normal_sleep)
                    break

                if code == 204:
                    print("    204 No Content (no data for these ids).")
                    time.sleep(normal_sleep)
                    break

                if code in retry_statuses:
                    if attempt >= max_attempts:
                        print(f"    ❌ retry limit reached ({max_attempts}). chunk skipped.")
                        break
                    # 429/5xx → backoff и повторяем этот же чанк
                    print("    retryable -> backing off and retry same chunk")
                    backoff_sleep(attempt, dict(resp.headers))
                    continue

                # прочие 4xx — обычно не ретраим
                print(f"    ⚠️ non-retryable status {code}: {resp.text[:200]}")
                break

            except requests.exceptions.RequestException as e:
                if attempt >= max_attempts:
                    print(f"    ❌ network retry limit reached ({max_attempts}): {e}. chunk skipped.")
                    break
                print(f"    network error: {e} -> backoff and retry")
                backoff_sleep(attempt, None)
                continue

    # --- контроль полноты ---
    requested_ids_set = set(advert_ids)
    missing_ids = requested_ids_set - returned_ids

    print(f"[DONE] requested_unique_ids={len(requested_ids_set)} "
          f"returned_unique_ids={len(returned_ids)} missing_unique_ids={len(missing_ids)}")

    if missing_ids:
        # распределение типов среди missing — это ключ к причине "одно и то же количество"
        miss_types = df_ids[df_ids["advertId"].isin(list(missing_ids))]["type"].value_counts()
        print("[MISSING] type distribution:")
        print(miss_types)

    if not all_rows:
        print("⚠️ all_rows пустой — df_adv будет пустым.")
        return pd.DataFrame()

    # ----------------------------------------------------------
    # Преобразуем объединённые данные в DataFrame (как раньше)
    # НО не выкидываем строки без nms (оставим nms=None)
    # ----------------------------------------------------------
    df_adv = pd.DataFrame(all_rows)

    if "unitedParams" not in df_adv.columns:
        df_adv["unitedParams"] = None

    df_adv = df_adv.explode("unitedParams", ignore_index=True)

    def extract_nms(up):
        # если nms нет — оставляем строку
        if isinstance(up, dict):
            nms = up.get("nms", [])
            if nms is None:
                return [None]
            if isinstance(nms, collections.abc.Iterable) and not isinstance(nms, (str, bytes)):
                nms_list = list(nms)
                return nms_list if nms_list else [None]
            return [nms]
        return [None]

    df_adv["nms_list"] = df_adv["unitedParams"].apply(extract_nms)
    df_adv = df_adv.explode("nms_list", ignore_index=True)
    df_adv = df_adv.rename(columns={"nms_list": "nms"})
    df_adv.drop(columns=["unitedParams"], inplace=True)

    status_map = {
        -1: "удалена",
        4: "готова к запуску",
        7: "завершена",
        8: "отменена",
        9: "активна",
        11: "на паузе",
    }
    if "status" in df_adv.columns:
        df_adv["status_name"] = df_adv["status"].map(status_map).fillna("неизвестный статус")

    time_cols = ["createTime", "startTime", "endTime", "changeTime"]
    for col in time_cols:
        if col in df_adv.columns:
            df_adv[col] = pd.to_datetime(df_adv[col], errors="coerce")

    print(f"[DF] rows={len(df_adv)} unique_advertId={df_adv['advertId'].nunique()} "
          f"unique_nms={(df_adv['nms'].nunique() if 'nms' in df_adv.columns else 'NA')}")

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
    df_count = df_count[df_count["status_name"].isin(['активна', 'на паузе'])]
    df_count.to_excel("wb_campaigns.xlsx", index=False)
    df_adv = get_promotion_adverts_df(API_KEY, df_count)
    df_final = build_final_df(df_count, df_adv)

    output_file = "wb_promotion_campaigns_full_RU.xlsx"
    df_final.to_excel(output_file, index=False)
    print(f"Итог записан в: {output_file}")
