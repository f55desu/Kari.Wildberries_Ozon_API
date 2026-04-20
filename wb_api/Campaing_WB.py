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

def get_promotion_adverts_df(API_KEY: str, df_count: pd.DataFrame, params: dict | None = None,
                             stop_event=None, ui_log=None) -> pd.DataFrame:
    """
    Берёт advertId из df_count, делает запросы GET /api/advert/v2/adverts чанками по 50,
    ретраит 429/5xx с увеличением задержки,
    показывает прогресс,
    и в конце печатает контроль полноты (missing ids и распределение типов по missing).

    Схема ответа v2 отличается от v1:
      корень: {"adverts": [ {id, bid_type, status, settings{...}, nm_settings[...], timestamps{...}}, ... ]}
    Здесь мы разворачиваем ответ в плоский DF с колонками, совместимыми с прежним кодом:
      advertId, name, status, status_name, nms, createTime, startTime, endTime, changeTime,
      plus новые: bid_type, payment_type, placement_recommendations, placement_search,
                  subject_id, subject_name, bid_recommendations, bid_search.
    """
    if df_count.empty:
        raise SystemExit("Нет advertId для запроса v2/adverts")

    url_adverts = "https://advert-api.wildberries.ru/api/advert/v2/adverts"

    if params is None:
        params = {}

    # ВАЖНО: держим связку advertId -> type, чтобы понять, чего не хватает
    df_ids = df_count[["advertId", "type"]].dropna().drop_duplicates()
    advert_ids = df_ids["advertId"].astype(int).tolist()

    total_ids = len(advert_ids)
    if total_ids == 0:
        return pd.DataFrame()

    # В v2 лимит 50 id на запрос (см. описание параметра ids в Swagger WB)
    chunk_size = 50
    total_chunks = (total_ids + chunk_size - 1) // chunk_size

    print(f"[START] advertId total={total_ids}, chunks={total_chunks}, chunk_size={chunk_size}")

    headers = {"Authorization": API_KEY}
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

    if stop_event is not None and stop_event.is_set():
        if ui_log: ui_log("⛔ Остановлено пользователем (до начала запросов).")
        return pd.DataFrame()

    # --- основной проход по чанкам ---
    for chunk_idx in range(total_chunks):
        start = chunk_idx * chunk_size
        end = min(start + chunk_size, total_ids)
        chunk_ids = advert_ids[start:end]

        # В v2 ids — это строка с id через запятую, передаётся в query
        query = {"ids": ",".join(str(x) for x in chunk_ids)}
        # дополнительные необязательные фильтры (statuses, payment_type), если переданы
        for k, v in params.items():
            if v is not None:
                query[k] = v

        attempt = 0
        while True:
            attempt += 1
            try:
                if stop_event is not None and stop_event.is_set():
                    if ui_log: ui_log("⛔ Остановлено пользователем (во время выгрузки).")
                    break
                resp = session.get(
                    url_adverts,
                    headers=headers,
                    params=query,
                    timeout=60,
                )

                code = resp.status_code

                # ПРОГРЕСС
                print(f"[{chunk_idx+1}/{total_chunks}] ids={len(chunk_ids)} attempt={attempt} status={code}")

                if code == 200:
                    body = resp.json() or {}
                    adverts = body.get("adverts") if isinstance(body, dict) else None
                    if isinstance(adverts, list) and adverts:
                        all_rows.extend(adverts)
                        ids_got = set()
                        for obj in adverts:
                            if isinstance(obj, dict) and "id" in obj:
                                try:
                                    ids_got.add(int(obj["id"]))
                                except Exception:
                                    pass
                        returned_ids |= ids_got
                        # Принт в консоль
                        print(f"    got_objects={len(adverts)} got_unique_ids={len(ids_got)} "
                              f"total_unique_ids={len(returned_ids)}")
                        # Принт в UI
                        msg = f"[{chunk_idx}/{total_chunks}] got_unique={len(returned_ids)} / requested={total_ids}"
                        if ui_log:
                            ui_log(msg)
                    else:
                        print("    200 OK but empty adverts (no objects).")

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
    # v2 response -> плоский DataFrame.
    # Имена колонок подобраны так, чтобы совпадать с прежней схемой v1
    # (advertId, nms, status, createTime, startTime, endTime, changeTime, name).
    # Строки без nm_settings не выкидываем — nms=None.
    # ----------------------------------------------------------
    rows = []
    for adv in all_rows:
        if not isinstance(adv, dict):
            continue

        settings = adv.get("settings") or {}
        placements = settings.get("placements") or {}
        ts = adv.get("timestamps") or {}
        nm_settings = adv.get("nm_settings") or []

        base = {
            "advertId": adv.get("id"),
            "bid_type": adv.get("bid_type"),
            "status": adv.get("status"),
            "name": settings.get("name"),
            "payment_type": settings.get("payment_type"),
            "placement_recommendations": placements.get("recommendations"),
            "placement_search": placements.get("search"),
            "createTime": ts.get("created"),
            "startTime": ts.get("started"),
            "endTime": ts.get("deleted"),   # в v2 нет явного endTime; используем deleted
            "changeTime": ts.get("updated"),
        }

        if not nm_settings:
            rows.append({
                **base,
                "nms": None,
                "subject_id": None,
                "subject_name": None,
                "bid_recommendations": None,
                "bid_search": None,
            })
            continue

        for nm in nm_settings:
            if not isinstance(nm, dict):
                continue
            subj = nm.get("subject") or {}
            bids = nm.get("bids_kopecks") or {}
            rows.append({
                **base,
                "nms": nm.get("nm_id"),
                "subject_id": subj.get("id"),
                "subject_name": subj.get("name"),
                "bid_recommendations": bids.get("recommendations"),
                "bid_search": bids.get("search"),
            })

    df_adv = pd.DataFrame(rows)

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

    # Принт в консоль
    print(f"[DF] rows={len(df_adv)} unique_advertId={df_adv['advertId'].nunique()} "
          f"unique_nms={(df_adv['nms'].nunique() if 'nms' in df_adv.columns else 'NA')}")

    # Принт в UI
    msg = (f"[DF] rows={len(df_adv)} unique_advertId={df_adv['advertId'].nunique()} "
       f"unique_nms={(df_adv['nms'].nunique() if 'nms' in df_adv.columns else 'NA')}")
    if ui_log:
        ui_log(msg)

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
