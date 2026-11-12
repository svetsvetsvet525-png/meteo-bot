"""Парсер страницы метeо/актировок сайта администрации Норильска."""
from __future__ import annotations

import logging
import re
import time

import httpx
from bs4 import BeautifulSoup

from bot import config
from bot.models import DISTRICT_KEYS, Announcement, ShiftAktirovka
from bot.sources.http import proxied_site_client, site_client
from bot.sources.parsing import (
    detect_districts,
    extract_date_iso,
    extract_shift,
    looks_like_aktirovka,
    parse_announcement,
)

log = logging.getLogger(__name__)

# Сайт нестабилен: после неудачи пробуем не чаще раза в час,
# чтобы не тормозить циклы (важно, когда трафик идёт через телефонный туннель)
_COOLDOWN = 3600.0
_cooldown_until = 0.0


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


def _candidate_texts(soup: BeautifulSoup) -> list[str]:
    """Короткие блоки текста, похожие на объявление об актировках."""
    candidates: list[str] = []
    for tag in soup.find_all(["p", "div"]):
        text = tag.get_text(" ", strip=True)
        if not text or len(text) > 2500:
            continue
        if looks_like_aktirovka(text.lower().replace("ё", "е")):
            candidates.append(text)
    # Убираем дубли и вложенные повторы (div содержит те же p)
    seen, unique = set(), []
    for text in candidates:
        if text not in seen:
            seen.add(text)
            unique.append(text)
    return unique


def _grade_from_cell(text: str) -> tuple[int, int] | None:
    """Ячейку таблицы '1-9 классы' / 'нет' -> диапазон или None."""
    low = text.lower().replace("ё", "е")
    if "нет" in low:
        return None
    m = re.search(r"1\s*(?:[-–—]\s*|\s+по\s+)(\d{1,2})\s*класс", text, re.IGNORECASE)
    if m and 1 <= int(m.group(1)) <= 11:
        return (1, int(m.group(1)))
    return None


def _from_tables(soup: BeautifulSoup, candidates: list[str]) -> list[Announcement]:
    """Структурированный вариант: таблица 'район — классы' + текст смены (как в npr_meteobot)."""
    page_text = candidates[0] if candidates else soup.get_text(" ", strip=True)
    date_iso = extract_date_iso(page_text)
    shift = extract_shift(page_text)
    if date_iso is None or shift is None:
        return []

    grades: dict[str, tuple[int, int] | None] = {}
    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            if len(cells) < 2:
                continue
            matched = detect_districts(cells[0].lower().replace("ё", "е"))
            if not matched:
                continue
            grades[matched[0]] = _grade_from_cell(cells[1])

    # Считаем результат надёжным, если найдено хотя бы два района
    if len(grades) < 2:
        return []

    return [
        Announcement(
            date=date_iso,
            shift_data=ShiftAktirovka(
                shift=shift, grades={d: grades.get(d) for d in DISTRICT_KEYS}
            ),
            published=None,
            source="site",
        )
    ]


async def fetch(client=None) -> list[Announcement]:
    """Скачивает страницу и возвращает объявления об актировках (0..1 шт.)."""
    global _cooldown_until
    if time.monotonic() < _cooldown_until:
        return []
    # Всегда свой клиент: у сайта администрации бывает просроченный
    # сертификат (SITE_VERIFY_SSL=0), а общий клиент проверяет SSL всегда.
    # При настроенном RU_PROXY — через прокси (гео-блок).
    client = proxied_site_client() or site_client()
    # Короткий таймаут: сайт бывает недоступен, не даём командам бота подвисать
    try:
        response = await client.get(
            config.SITE_URL, timeout=httpx.Timeout(12.0, connect=5.0)
        )
        response.raise_for_status()
    except Exception:
        _cooldown_until = time.monotonic() + _COOLDOWN
        raise
    _cooldown_until = 0.0  # сайт жив — пробуем каждый цикл
    html = _decode(response)
    soup = BeautifulSoup(html, "html.parser")

    candidates = _candidate_texts(soup)

    announcements = _from_tables(soup, candidates)
    if announcements:
        return announcements

    # Фолбэк: разбор похожих блоков текста как обычного объявления
    for text in candidates:
        parsed = parse_announcement(text, published=None, source="site")
        if parsed:
            return [parsed]
    return []
