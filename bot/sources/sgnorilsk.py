"""Основной источник: портал «Северный город» (sgnorilsk.ru/pogoda/).

Портал перепечатывает официальный бюллетень администрации Норильска:
объявление об актировках + таблицу по районам, прогноз погоды, состояние
дорог и предупреждения Управления ГО и ЧС. Сайт стабильно доступен
(в отличие от norilsk-city.ru), поэтому подключён как первый источник.

Структура бюллетеня (проверена на реальной странице):
    <h2 id="aktirovki">Актировки и Сообщения ГО и ЧС</h2>
    <p><b style="color:#ff0000">01.11.2026</b></p>        <- дата бюллетеня
    <p><b>ИНФОРМАЦИЯ ОБ АКТИРОВКАХ</b></p>
    <p>В соответствии ... для обучающихся 2-ой смены ... актировки нет.</p>
    <table> Центральный район | нет  (4 района) </table>
    <p><b>ИНФОРМАЦИЯ О ПОГОДЕ</b></p> ...
    <p><b>УПРАВЛЕНИЕ ГО и ЧС ПРЕДУПРЕЖДАЕТ</b></p> ...
    <p><b>АДМИНИСТРАЦИЯ ГОРОДА НОРИЛЬСКА ИНФОРМИРУЕТ</b></p> ...
"""
from __future__ import annotations

import html as html_mod
import logging
import re

import httpx
from bs4 import BeautifulSoup

from bot import config
from bot.models import DISTRICT_KEYS, Announcement, ShiftAktirovka, Storm
from bot.sources.http import http_client
from bot.sources.parsing import (
    DISTRICT_ALIASES,
    NO_AKTIROVKA_RE,
    SCHOOL_RE,
    detect_districts,
    extract_date_iso,
    extract_shift,
    looks_like_aktirovka,
    parse_grade_range,
)

log = logging.getLogger(__name__)

SOURCE = "sgnorilsk"
STORM_SOURCE = "sgnorilsk.ru — Управление ГО и ЧС Норильска"

# Маркеры разделов бюллетеня (страница отдаёт их заглавными буквами)
_AKT_MARKER = "информация об актировках"
_WEATHER_MARKER = "информация о погоде"
_STORM_MARKER = "управление го и чс предупреждает"
# Секция штормовых заканчивается этим (или дальше) разделом
_STORM_STOPPERS = (
    "администрация города норильска информирует",
    "<footer",
    "jeg_footer",
)

_DATE_IN_HTML = re.compile(r"\d{1,2}\.\d{2}\.\d{4}")
# Разрезаем бюллетень на фрагменты по упоминаниям смен
_FRAGMENT_SPLIT = re.compile(r"(?=для (?:обучающихся|учащихся))", re.IGNORECASE)
# «для обучающихся 1-ой и 2-ой смен», «обеих смен» — объявление сразу для двух смен
_BOTH_SHIFTS_RE = re.compile(
    r"(обе[их]?\s+смен|1\s*[-–—]?\s*(?:ой|я)?\s*и\s*2\s*[-–—]?\s*(?:ой|я)?\s*смен)",
    re.IGNORECASE,
)
# Ячейка таблицы вида «1-6» (без слова «класс»)
_CELL_RANGE_RE = re.compile(r"(\d{1,2})\s*[-–—]\s*(\d{1,2})")

# Значения ячейки, означающие «актировки нет»
_CELL_NO = ("нет", "-", "—", "")


def _low(text: str) -> str:
    return text.lower().replace("ё", "е")


def _strip_tags(fragment: str) -> str:
    """HTML-фрагмент -> читабельный текст (блочные теги дают перенос строки)."""
    fragment = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", fragment)
    fragment = re.sub(
        r"(?i)</?(?:p|div|li|ul|ol|h[1-6]|tr|table|tbody|thead)(?:[^>]*)>", "\x00", fragment
    )
    fragment = re.sub(r"(?i)<br\s*/?>", "\x00", fragment)
    fragment = re.sub(r"<[^>]+>", " ", fragment)
    text = html_mod.unescape(fragment)
    text = re.sub(r"\s+", " ", text)  # переводы строк внутри тегов — в пробел
    lines = (line.strip() for line in text.split("\x00"))
    return "\n".join(line for line in lines if line)


def _match_district(cell_text: str) -> str | None:
    """Название района из ячейки таблицы -> канонический ключ."""
    low = _low(cell_text)
    for key, aliases in DISTRICT_ALIASES.items():
        if any(alias in low for alias in aliases):
            return key
    return None


def _cell_range(raw: str) -> tuple[int, int] | None:
    """Значение ячейки таблицы -> диапазон классов или None (актировки нет)."""
    low = _low(raw).strip()
    if low in _CELL_NO or "нет" in low:
        return None
    rng = parse_grade_range(raw)
    if rng:
        return rng
    m = _CELL_RANGE_RE.search(low)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        if 1 <= lo <= hi <= 11:
            return (lo, hi)
    # Актировка объявлена, но диапазон в ячейке не расписан — считаем все классы
    return (1, 11)


def _parse_table(table_html: str) -> dict[str, tuple[int, int] | None]:
    """Таблица бюллетеня -> {район: диапазон классов | None}."""
    grades: dict[str, tuple[int, int] | None] = {}
    soup = BeautifulSoup(table_html, "html.parser")
    for tr in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        if len(cells) < 2:
            continue
        district = _match_district(cells[0])
        if district is None:
            continue
        grades[district] = _cell_range(cells[1])
    return grades


def _parse_fragments(
    text: str,
    page_date: str | None,
    table_grades: dict[str, tuple[int, int] | None] | None,
) -> list[Announcement]:
    """Разбирает текст раздела «ИНФОРМАЦИЯ ОБ АКТИРОВКАХ» по фрагментам-сменам."""
    announcements: list[Announcement] = []
    seen_shifts: set[int] = set()

    for fragment in _FRAGMENT_SPLIT.split(text):
        low = _low(fragment)
        if not looks_like_aktirovka(low):
            continue
        date_iso = extract_date_iso(fragment) or page_date
        if date_iso is None:
            continue

        if _BOTH_SHIFTS_RE.search(fragment):
            shifts = (1, 2)
        else:
            shift = extract_shift(fragment)
            if shift is None:
                continue
            shifts = (shift,)

        schools = {int(n) for n in SCHOOL_RE.findall(fragment)}
        districts = detect_districts(low)
        rng = parse_grade_range(fragment)

        for shift in shifts:
            if shift in seen_shifts:
                continue

            # Техническая актировка конкретных школ (без перечисления районов)
            if schools:
                seen_shifts.add(shift)
                announcements.append(
                    Announcement(
                        date=date_iso,
                        shift_data=ShiftAktirovka(
                            shift=shift,
                            grades={d: None for d in DISTRICT_KEYS},
                            school_numbers=set(schools),
                        ),
                        source=SOURCE,
                    )
                )
                continue

            if districts and rng:
                # Обычное объявление: районы и классы перечислены в тексте
                grades = {d: (rng if d in districts else None) for d in DISTRICT_KEYS}
            elif table_grades:
                # Текст не перечисляет районы — берём значения из таблицы бюллетеня
                grades = {d: table_grades.get(d) for d in DISTRICT_KEYS}
            elif NO_AKTIROVKA_RE.search(low):
                grades = {d: None for d in DISTRICT_KEYS}
            else:
                log.warning(
                    "sgnorilsk: в объявлении нет ни районов, ни таблицы, пропускаю: %.120s",
                    " ".join(fragment.split()),
                )
                continue

            seen_shifts.add(shift)
            announcements.append(
                Announcement(
                    date=date_iso,
                    shift_data=ShiftAktirovka(shift=shift, grades=grades),
                    source=SOURCE,
                )
            )

    return announcements


def parse_html(html: str) -> tuple[list[Announcement], list[Storm]]:
    """Разбор страницы бюллетеня. Отдельно от fetch() — для офлайн-тестов."""
    low_html = _low(html)
    announcements: list[Announcement] = []
    storms: list[Storm] = []

    # --- актировки -------------------------------------------------------------
    start = low_html.find(_AKT_MARKER)
    if start != -1:
        table_start = low_html.find("<table", start)
        weather_pos = low_html.find(_WEATHER_MARKER, start)
        ends = [p for p in (table_start, weather_pos) if p != -1]
        section_end = min(ends) if ends else start + 8000
        text = _strip_tags(html[start:section_end])

        # Дата бюллетеня — красная жирная строка непосредственно перед разделом
        page_date = None
        before = _DATE_IN_HTML.findall(low_html[max(0, start - 1500):start])
        if before:
            page_date = extract_date_iso(before[-1])

        table_grades = None
        if table_start != -1:
            table_end = low_html.find("</table", table_start)
            if table_end != -1:
                table_grades = _parse_table(html[table_start:table_end])

        announcements = _parse_fragments(text, page_date, table_grades)

    # --- предупреждения ГО и ЧС (для команды /storm) -----------------------------
    storm_start = low_html.find(_STORM_MARKER)
    if storm_start != -1:
        after = storm_start + len(_STORM_MARKER)
        stops = [low_html.find(marker, after) for marker in _STORM_STOPPERS]
        stops = [p for p in stops if p != -1]
        storm_end = min(stops) if stops else storm_start + 12000
        lines = [
            line
            for line in _strip_tags(html[storm_start:storm_end]).split("\n")
            if line and _low(line) != _STORM_MARKER
        ]
        if lines:
            storms.append(
                Storm(published=None, text="\n\n".join(lines), source=STORM_SOURCE)
            )

    return announcements, storms


def _decode(response) -> str:
    """Текст страницы с учётом возможной Windows-1251."""
    charset = response.charset_encoding
    if charset:
        return response.content.decode(charset, errors="replace")
    raw = response.content
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1251", errors="replace")


async def fetch(client=None) -> tuple[list[Announcement], list[Storm]]:
    """Скачивает бюллетень и возвращает (актировки, предупреждения ГО и ЧС)."""
    client = client or http_client()
    response = await client.get(
        config.SGNORILSK_URL, timeout=httpx.Timeout(15.0, connect=8.0)
    )
    response.raise_for_status()
    return parse_html(_decode(response))
