"""Быстрая проверка парсеров без запуска бота: python smoke_test.py"""
from __future__ import annotations

import asyncio
import json

from bot.sources import channel as channel_src
from bot.sources import meteonpr as meteonpr_src
from bot.sources import site as site_src
from bot.sources import sgnorilsk as sgnorilsk_src
from bot.sources import weather as weather_src
from bot.sources.http import http_client
from bot.sources.parsing import parse_announcement

# Реальные тексты постов канала «Актировка Норильск» (проверка офлайн-логики)
FIXTURES = [
    # Обычная актировка, 2-я смена, все районы
    "❗19.03.2026.\nВ соответствии с предоставленной метеорологической информацией "
    "Таймырским ЦГМС – филиалом ФГБУ «СУГМС» о фактической погоде по состоянию на 11:00 19.03.2026, "
    "прогнозом погоды на 19.03.2026, предупреждением о неблагоприятных явлениях погоды, "
    "руководствуясь Графиком определения погодных условий, по усмотрению родителей "
    "(иных законных представителей) допускается не посещать занятия обучающимся образовательных "
    "учреждений городского округа город Норильск 2-ой смены в Центральном районе, "
    "жилом образовании Оганер, районах Талнах и Кайеркан с 1 по 6 классы.",
    # Техническая актировка одной школы + «актировок нет»
    "20.03.2026\nПо решению Управления общего и дошкольного образования Администрации города "
    "Норильска, 20.03.2026 объявляется техническая актировка для учащихся 1-ой смены МБОУ "
    "Средняя школа № 31 с 1 по 11 классы.\n\nВ соответствии с предоставленной метеорологической "
    "информацией Таймырским ЦГМС ... для обучающихся 1-ой смены образовательных учреждений "
    "городского округа город Норильск актировок нет.",
    # Простое «актировок нет»
    "19.11.2025. ... руководствуясь Графиком определения погодных условий, для обучающихся "
    "1-ой смены образовательных учреждений муниципального образования город Норильск актировок нет.",
    # Штормовое предупреждение (не актировка)
    "С 10:00 18.05.2026 объявляется \"штормовое предупреждение по очень сильному ветру\".",
    # Прогноз погоды (не актировка)
    "Специализированный прогноз погоды по Норильскому промышленному району с 19:00 19.03.2026 "
    "до 19:00 20.03.2026: ночью небольшой снег...",
]

# Реальный фрагмент бюллетеня с sgnorilsk.ru/pogoda/ (01.11.2026, «актировки нет»)
SGN_FIXTURE_NO = """
<h2 class="page-heading__title" id="aktirovki">Актировки и Сообщения ГО и ЧС</h2>
<p style="text-align: justify;"><b style="color: #ff0000;">01.11.2026</b></p>
<p style="text-align: justify;"><b><span>ИНФОРМАЦИЯ ОБ АКТИРОВКАХ</span></b></p>
<p style="text-align: justify;"><span>В соответствии с предоставленной метеорологической
информацией Таймырским ЦГМС – филиалом ФГБУ «СУГМС» о фактической погоде по состоянию
на 11:00 01.11.2026, с прогнозом погоды на 01.11.2026, руководствуясь Графиком определения
погодных условий, для обучающихся 2-ой смены образовательных учреждений городского
округа город Норильск актировки нет.</span></p>
<table class="table table-striped">
<tr><td>Центральный район</td><td>нет</td></tr>
<tr><td>ж/о Оганер</td><td>нет</td></tr>
<tr><td>район Талнах</td><td>нет</td></tr>
<tr><td>район Кайеркан</td><td>нет</td></tr>
</table>
<p><b>ИНФОРМАЦИЯ О ПОГОДЕ</b></p>
<p>Прогноз погоды на 02.11.2026: без осадков, видимость хорошая.</p>
<p><b>УПРАВЛЕНИЕ ГО и ЧС ПРЕДУПРЕЖДАЕТ</b></p>
<p>Внимание! Управление ГО и ЧС г. Норильска предупреждает! В связи с угрозой схода
снежной лавины ограничен доступ на юго-западный склон горы «Отдельная».</p>
<p>АДМИНИСТРАЦИЯ ГОРОДА НОРИЛЬСКА ИНФОРМИРУЕТ</p>
<p>Уважаемые жители городского округа город Норильск!</p>
"""

# Гипотетический бюллетень с реальной актировкой (проверка объединения текста и таблицы)
SGN_FIXTURE_AKT = """
<p><b style="color: #ff0000;">13.11.2026</b></p>
<p><b>ИНФОРМАЦИЯ ОБ АКТИРОВКАХ</b></p>
<p>В соответствии с предоставленной метеорологической информацией Таймырским ЦГМС,
руководствуясь Графиком определения погодных условий, по усмотрению родителей
допускается не посещать занятия обучающимся 1-ой смены образовательных учреждений
городского округа город Норильск с 1 по 6 классы.</p>
<table class="table table-striped">
<tr><td>Центральный район</td><td>1-6</td></tr>
<tr><td>ж/о Оганер</td><td>1-6</td></tr>
<tr><td>район Талнах</td><td>1-6</td></tr>
<tr><td>район Кайеркан</td><td>1-6</td></tr>
</table>
<p><b>ИНФОРМАЦИЯ О ПОГОДЕ</b></p>
"""


def anns_view(anns) -> list[dict]:
    """Компактное представление объявлений для печати."""
    return [
        {"date": a.date, "source": a.source, **a.shift_data.to_dict()} for a in anns
    ]


def show(title: str, obj) -> None:
    print(f"--- {title} ---")
    if obj is None:
        print("None")
    else:
        data = obj.to_dict() if hasattr(obj, "to_dict") else obj
        print(json.dumps(data, ensure_ascii=False, indent=1, default=str))
    print()


async def main() -> None:
    print("== Офлайн-разбор объявлений ==")
    for i, text in enumerate(FIXTURES, 1):
        show(f"фикстура {i}", parse_announcement(text, source="test"))

    print("== sgnorilsk.ru: офлайн-разбор бюллетеня «актировки нет» ==")
    anns, storms = sgnorilsk_src.parse_html(SGN_FIXTURE_NO)
    show("актировки", anns_view(anns))
    show("штормовые ГО и ЧС", [s.text[:100] for s in storms])

    print("== sgnorilsk.ru: офлайн-разбор бюллетеня с актировкой ==")
    anns, _ = sgnorilsk_src.parse_html(SGN_FIXTURE_AKT)
    show("актировки", anns_view(anns))

    client = http_client()

    print("== Живой портал sgnorilsk.ru ==")
    try:
        anns, storms = await sgnorilsk_src.fetch(client)
        print(f"актировок: {len(anns)}, предупреждений ГО и ЧС: {len(storms)}")
        for a in anns:
            print(" ", a.date, "смена", a.shift_data.shift, a.shift_data.to_dict()["grades"])
        for s in storms:
            print("  ГОиЧС:", (s.text or "")[:80].replace("\n", " "))
    except Exception as e:
        print("sgnorilsk.ru недоступен:", repr(e))

    print("\n== Живой канал @aktirovka_norilsk ==")
    try:
        anns, storms = await channel_src.fetch(client)
        print(f"актировок: {len(anns)}, штормовых: {len(storms)}")
        for a in anns:
            print(" ", a.date, "смена", a.shift_data.shift, a.shift_data.to_dict()["grades"])
        for s in storms[:1]:
            print("  шторм:", (s.text or "")[:80])
    except Exception as e:
        print("канал недоступен:", repr(e))

    print("\n== Сайт администрации ==")
    try:
        anns = await site_src.fetch(client)
        print(f"объявлений: {len(anns)}")
        for a in anns:
            print(" ", a.date, "смена", a.shift_data.shift, a.shift_data.to_dict()["grades"])
    except Exception as e:
        print("сайт недоступен:", repr(e))

    print("\n== meteonpr.ru (резерв) ==")
    try:
        anns = await meteonpr_src.fetch(client)
        print(f"объявлений: {len(anns)}")
        for a in anns:
            print(" ", a.date, "смена", a.shift_data.shift, a.shift_data.to_dict()["grades"])
        if not anns:
            print("  блок без даты/смены (например «актировок нет») — корректно пропущен")
    except Exception as e:
        print("meteonpr.ru недоступен:", repr(e))

    print("\n== Погода (Open-Meteo) ==")
    try:
        data = await weather_src.fetch(client)
        from bot.texts import format_weather
        print(format_weather(data))
    except Exception as e:
        print("погода недоступна:", repr(e))


if __name__ == "__main__":
    asyncio.run(main())
