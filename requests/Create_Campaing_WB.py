import requests
import json
import collections
import pandas as pd
import os
from glob import glob
from datetime import timedelta
import time
from dotenv import load_dotenv
import datetime

load_dotenv() # Load variables from .env

API_KEY = os.getenv("API_KEY")

BASE_URL = "https://advert-api.wildberries.ru"


def create_seacat_campaign(name: str,
                           nms: list[int],
                           bid_type: str = "manual",
                           placement_types: list[str] | None = None) -> dict:
    """
    Создаёт кампанию seacat через /adv/v2/seacat/save-ad
    и ВОЗВРАЩАЕТ:
      {
        "advertId": <int>,
        "name": <str>,
        "nms": <list[int]>
      }
    """

    if placement_types is None and bid_type == "manual":
        placement_types = ["search", "recommendations"]

    payload = {
        "name": name,
        "nms": nms,
        "bid_type": bid_type,
    }

    if bid_type == "manual" and placement_types:
        payload["placement_types"] = placement_types

    headers = {
        "Authorization": API_KEY,
        "Content-Type": "application/json",
    }

    resp = requests.post(
        f"{BASE_URL}/adv/v2/seacat/save-ad",
        headers=headers,
        json=payload,
        timeout=30,
    )

    print("save-ad status:", resp.status_code, resp.text)
    resp.raise_for_status()

    # WB возвращает ID кампании просто строкой / числом
    advert_id_str = resp.text.strip()
    advert_id = int(advert_id_str)

    # ВАЖНО: здесь мы специально возвращаем и advertId, и nms
    return {
        "advertId": advert_id,
        "name": name,
        "nms": list(nms),
    }


def start_campaign(advert_id: int) -> requests.Response:
    headers = {"Authorization": API_KEY}
    resp = requests.get(
        f"{BASE_URL}/adv/v0/start",
        headers=headers,
        params={"id": advert_id},
        timeout=30,
    )
    print("start status:", advert_id, resp.status_code, resp.text)
    return resp


def pause_campaign(advert_id: int) -> requests.Response:
    headers = {"Authorization": API_KEY}
    resp = requests.get(
        f"{BASE_URL}/adv/v0/pause",
        headers=headers,
        params={"id": advert_id},
        timeout=30,
    )
    print("pause status:", advert_id, resp.status_code, resp.text)
    return resp


def create_and_pause_campaign(name: str,
                              nms: list[int],
                              bid_type: str = "manual",
                              placement_types: list[str] | None = None) -> dict:
    """
    1) создаёт кампанию seacat,
    2) пытается сразу перевести её в статус 11 (на паузе),
    3) ВОЗВРАЩАЕТ:
       {
         "advertId": <int>,
         "name": <str>,
         "nms": <list[int]>,
         "paused": <bool>,
         "pause_status_code": <int | None>,
         "pause_response_text": <str | None>
       }
    """

    base_info = create_seacat_campaign(
        name=name,
        nms=nms,
        bid_type=bid_type,
        placement_types=placement_types,
    )

    advert_id = base_info["advertId"]

    # Пытаемся сразу поставить на паузу
    # resp_pause = pause_campaign(advert_id)

    # paused = (resp_pause.status_code == 200)

    # Если WB не дал поставить на паузу (например, статус ещё 4),
    # можно по желанию сначала стартануть, потом снова пауза.
    # Тут оставляю минимальный вариант.
    result = {
        "advertId": advert_id,
        "name": base_info["name"],
        "nms": base_info["nms"],
        # "paused": paused,
        # "pause_status_code": resp_pause.status_code,
        # "pause_response_text": resp_pause.text,
    }

    return result


# Собираем все .xlsx файлы
files = glob(os.path.join("Товары/Товары ВБ", "*.xlsx"))

df_list = []
for file in files:
    # читаем, пропуская первую строку
    df_tmp = pd.read_excel(file, engine='calamine', skiprows=2)
    df_list.append(df_tmp)

# объединяем все файлы
df_all = pd.concat(df_list, ignore_index=True)
df_all.drop([0], inplace=True)

df_campaings = pd.read_excel("wb_promotion_campaigns_full.xlsx", engine='calamine')
df_filtered = df_all[~df_all['Артикул WB'].isin(df_campaings['nms'])]

CAMPAING_LIMIT = 2110

for art in range(len(df_filtered[0:CAMPAING_LIMIT])):
    campaign_nms = [int(df_filtered[0:CAMPAING_LIMIT].sample()['Артикул WB'].values[0])]
    campaign_mask = f"Тест seacat через API {campaign_nms}"

    info = create_and_pause_campaign(
        name=campaign_mask,
        nms=campaign_nms,
        bid_type="manual",              # или "unified"
        placement_types=["search"],     # для manual
    )
    print("Результат:")
    print(info)
    time.sleep(13) # 13 секунд ждём для след запроса

print(f'{datetime.datetime.now()} - Новые {CAMPAING_LIMIT} кампании созданы\n')

# if __name__ == "__main__":
#     # Собираем все .xlsx файлы
#     files = glob(os.path.join("Товары/Товары ВБ", "*.xlsx"))

#     df_list = []
#     for file in files:
#         # читаем, пропуская первую строку
#         df_tmp = pd.read_excel(file, engine='calamine', skiprows=2)
#         df_list.append(df_tmp)

#     # объединяем все файлы
#     df_all = pd.concat(df_list, ignore_index=True)

#     # for 

#     # campaign_mask = "Тест seacat через API"
#     # campaign_nms = [248627550]

#     # info = create_and_pause_campaign(
#     #     name=campaign_name,
#     #     nms=campaign_nms,
#     #     bid_type="manual",              # или "unified"
#     #     placement_types=["search"],     # для manual
#     # )

#     print("Результат:")
#     print(info)
    # Пример вывода:
    # {
    #   'advertId': 1234567,
    #   'name': 'Тест seacat через API',
    #   'nms': [146168367, 200425104],
    #   'paused': True,
    #   'pause_status_code': 200,
    #   'pause_response_text': 'ok'
    # }