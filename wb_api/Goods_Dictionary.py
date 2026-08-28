"""Загрузка Справочника по артикулам из SQL (cl01sql) и подмешивание к выгрузке кампаний.

Справочник детализирован по размеру (одна строка на Артикул+Размер), поэтому
для присоединения к выгрузке кампаний (которая идёт по NMID) он схлопывается
до одной строки на [Артикул WB] = NMID.
"""
import pandas as pd
from sqlalchemy import create_engine

SQL_SERVER = "cl01sql"
SQL_DATABASE = "DBReport"  # запрос использует полные 3-частные имена, БД для коннекта роли не играет

# Ключ соединения: nms (nm_id из кампаний) == [Артикул WB] (b.NMID) из Справочника
CAMPAIGN_KEY = "nms"
REFERENCE_KEY = "Артикул WB"

REFERENCE_SQL = """
with tmp as (
    select distinct
        q.itemid as [Артикул],
        q.itemnameRU as [Наименование],
        b.inventsizeid as [Размер],
        q.KAR_ACTUALCOLLECTION as [Коллекция],
        q.trademark as [Бренд],
        q.KAR_SEASONCODERU as [Сезон],
        q.DIVISIONGROUPRU as [Направление],
        q.DEPARTMENTIDRU as [Розничный отдел],
        q.[namealias] as [Модель],
        q.businessgroupru as [Бизнес-группа],
        CONCAT(q.retailgroup,' ',q.grpnameru) as [Группа],
        q.kar_technicalsegmentvalueid as [Техсегмент],
        q.buyer as [Байер]
    from [DBReport].[dbo].[GuideAssortiment] q
    inner join [DynamicsAx1].[dbo].[INVENTITEMBARCODE] a
        on q.itemid = a.itemid
    inner join [DynamicsAx1].[dbo].[INVENTDIM] b
        on a.inventdimid = b.inventdimid
    left join [DynamicsAx1].[dbo].[INVENTTABLE] c
        on q.itemid = c.itemid
    where a.dataareaid = 'vrt'
      and b.dataareaid = 'vrt'
      and c.dataareaid = 'vrt'
      and c.itemgroupid = 'Goods'
)
select
    tmp.*,
    isnull(a.[Две последние коллекции], [Коллекция]) as [Две последние коллекции],
    case
        when d.itemanalogid is not null then d.itemid
        else tmp.[Артикул]
    end as [Основной артикул],
    b.[NMID] as [Артикул WB],
    c.OZON_SKU as [Артикул OZ],
    e.[Группа для отчетов],
    xx.[Себестоимость с НДС],
    xx.[Себестоимость без НДС],
    nds.НДС_условие,
    coalesce(
        nullif(art.[Процент выкупа], 0),
        nullif(grp.[Процент выкупа], 0),
        bg_avg_o.[Средний процент выкупа]
    ) as [Процент выкупа],
    coalesce(
        nullif(art_wb.[Процент выкупа], 0),
        nullif(grp_wb.[Процент выкупа], 0),
        bg_avg_wb.[Средний процент выкупа]
    ) as [Процент выкупа ВБ]
from tmp
left join [DBPartners].[dbo].[WblmRepFromBuyersReports] a
    on tmp.Артикул = a.Артикул
left join [DBPartners].[dbo].[WblmRepGetNomenclatureWildberries] b
    on tmp.Артикул = b.ITEMID and tmp.Размер = b.INVENTSIZEID
left join [DBPartners].[dbo].[WblmRepGetNomenclatureOzon] c
    on tmp.Артикул = c.ITEMID and tmp.Размер = c.INVENTSIZEID
left join (
    select distinct itemanalogid, itemid
    from [DynamicsAx1].[dbo].[KAR_RBOITEMANALOGSTABLE]
) d
    on tmp.[Артикул] = d.itemanalogid
left join (
    select distinct [Артикул], [Группа для отчетов]
    from [DBPartners].[dbo].[WblmRepGuideAssortiment]
) e
    on tmp.[Артикул] = e.[Артикул]
left join (
    select
        Артикул,
        avg(Себестоимость) as [Себестоимость с НДС],
        avg("Себестоимость без НДС, руб") as [Себестоимость без НДС]
    from [DBPartners].[dbo].[WblmRepEstimatedMargin]
    group by Артикул
) xx
    on tmp.[Артикул] = xx.[Артикул]
left join (
    select
        [ITEMID],
        case
            when avg([NDS]) < 15 then 10
            else 20
        end as НДС_условие
    from [DBPartners].[dbo].[WblmRepFromAxaptaNDS]
    where DT = cast(getdate() as date)
    group by [ITEMID]
) nds
    on tmp.[Артикул] = nds.[ITEMID]
left join (
    select distinct
        r.[ITEMID],
        r.[REDEMPTION] as [Процент выкупа]
    from [DBPartners].[dbo].[WblmRepPartnerRedemption] r
    where r.AGREGATOR = 'Ozon'
) art
    on tmp.[Артикул] = art.[ITEMID]
left join (
    select distinct
        r.[RETAILGROUP],
        r.[REDEMPTION] as [Процент выкупа]
    from [DBPartners].[dbo].[WblmRepPartnerRedemption] r
    where r.AGREGATOR = 'Ozon'
) grp
    on tmp.[Группа] = grp.[RETAILGROUP]
left join (
    select distinct
        r.[ITEMID],
        r.[REDEMPTION] as [Процент выкупа]
    from [DBPartners].[dbo].[WblmRepPartnerRedemption] r
    where r.AGREGATOR = 'Wildberries'
) art_wb
    on tmp.[Артикул] = art_wb.[ITEMID]
left join (
    select distinct
        r.[RETAILGROUP],
        r.[REDEMPTION] as [Процент выкупа]
    from [DBPartners].[dbo].[WblmRepPartnerRedemption] r
    where r.AGREGATOR = 'Wildberries'
) grp_wb
    on tmp.[Группа] = grp_wb.[RETAILGROUP]
left join (
    select
        q.businessgroupru as [Бизнес-группа],
        avg(r.[REDEMPTION]) as [Средний процент выкупа]
    from [DBPartners].[dbo].[WblmRepPartnerRedemption] r
    inner join [DBReport].[dbo].[GuideAssortiment] q
        on r.[ITEMID] = q.itemid
    where r.AGREGATOR = 'Ozon'
    group by q.businessgroupru
) bg_avg_o
    on tmp.[Бизнес-группа] = bg_avg_o.[Бизнес-группа]
left join (
    select
        q.businessgroupru as [Бизнес-группа],
        avg(r.[REDEMPTION]) as [Средний процент выкупа]
    from [DBPartners].[dbo].[WblmRepPartnerRedemption] r
    inner join [DBReport].[dbo].[GuideAssortiment] q
        on r.[ITEMID] = q.itemid
    where r.AGREGATOR = 'Wildberries'
    group by q.businessgroupru
) bg_avg_wb
    on tmp.[Бизнес-группа] = bg_avg_wb.[Бизнес-группа]
"""


def connect_to_sql(server: str = SQL_SERVER, database: str = SQL_DATABASE):
    connection_string = (
        f"mssql+pyodbc://{server}/{database}?driver=ODBC+Driver+17+for+SQL+Server"
        "&trusted_connection=yes"
    )
    return create_engine(connection_string)


def get_reference_df(engine=None, ui_log=None) -> pd.DataFrame:
    """Выполняет SQL-запрос Справочника и возвращает результат как DataFrame."""
    if engine is None:
        engine = connect_to_sql()

    if ui_log:
        ui_log("Загружаю Справочник из SQL (cl01sql)…")

    df = pd.read_sql(REFERENCE_SQL, engine)

    msg = f"Справочник загружен: строк={len(df)}, уникальных NMID={df[REFERENCE_KEY].nunique()}"
    print(msg)
    if ui_log:
        ui_log(msg)

    return df


def collapse_to_nmid(df_spr: pd.DataFrame) -> pd.DataFrame:
    """Схлопывает Справочник до одной строки на [Артикул WB] (NMID).

    Убирает размерную детализацию (колонку [Размер]) и дубли по NMID,
    чтобы при merge выгрузка кампаний не размножалась по размерам.
    """
    df = df_spr.copy()

    # NMID не должен быть пустым для соединения с кампаниями
    df = df[df[REFERENCE_KEY].notna()]

    # Размер уходит — он единственное, что различается внутри одного NMID
    if "Размер" in df.columns:
        df = df.drop(columns=["Размер"])

    df = df.drop_duplicates(subset=[REFERENCE_KEY], keep="first")
    return df


def merge_reference(df_campaigns: pd.DataFrame, df_spr: pd.DataFrame | None = None,
                      engine=None, ui_log=None) -> pd.DataFrame:
    """Присоединяет Справочник к выгрузке кампаний по nms == [Артикул WB] (LEFT join).

    Если df_spr не передан — загружает его из SQL.
    Возвращает df_campaigns с добавленными колонками Справочника.
    """
    if df_campaigns is None or df_campaigns.empty:
        return df_campaigns

    if df_spr is None:
        df_spr = get_reference_df(engine=engine, ui_log=ui_log)

    df_spr_nmid = collapse_to_nmid(df_spr)

    # Приводим ключи к числу (nms приходит как int/float, NMID может быть строкой)
    left = df_campaigns.copy()
    left["_join_key"] = pd.to_numeric(left[CAMPAIGN_KEY], errors="coerce")

    right = df_spr_nmid.copy()
    right["_join_key"] = pd.to_numeric(right[REFERENCE_KEY], errors="coerce")

    merged = left.merge(
        right,
        on="_join_key",
        how="left",
    ).drop(columns=["_join_key"])

    matched = merged[REFERENCE_KEY].notna().sum() if REFERENCE_KEY in merged.columns else "NA"
    msg = f"Справочник присоединён: строк={len(merged)}, найдено в Справочнике={matched}"
    print(msg)
    if ui_log:
        ui_log(msg)

    return merged
