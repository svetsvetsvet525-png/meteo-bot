"""Разбор текста объявления об актировках (общий для сайта и канала)."""
from __future__ import annotations

import re
from datetime import date

from bot import config
from bot.models import DISTRICT_KEYS, Announcement, ShiftAktirovka

# "1-ой смены", "2-ой смены", "1 смены", "1-я смена"
SHIFT_RE = re.compile(r"([12])\s*(?:[-–—]\s*)?(?:ой|ого|я|ая)?\s*смен", re.IGNORECASE)
DATE_RE = re.compile(r"(\d{1,2})\.(\d{2})\.(\d{4})")
# "с 1 по 6 классы" (полная форма, с нижней границей)
GRADE_RANGE_RE = re.compile(r"с\s+(\d{1,2})\s+по\s+(\d{1,2})\s*класс", re.IGNORECASE)
# "1-9 классы", "1 по 9 классы", "с 1 по 9 классы" (нижняя граница = 1)
GRADE_RANGE_SHORT_RE = re.compile(r"1\s*(?:[-–—]\s*|\s+по\s+)(\d{1,2})\s*класс", re.IGNORECASE)
# "актировок нет", "актировки нет"
NO_AKTIROVKA_RE = re.compile(r"актиров[а-яё]+\s+нет", re.IGNORECASE)
# "МБОУ Средняя школа № 31", "школы № 31"
SCHOOL_RE = re.compile(r"школ[аыу]\S*\s*№\s*(\d{1,3})", re.IGNORECASE)

# Признаки сообщения об актировках. ВАЖНО: в официальном объявлении слова
# «актировка» может не быть вовсе — только формула «допускается не посещать».
AKTIROVKA_TRIGGERS = ("актиров", "допускается не посещать")


def looks_like_aktirovka(text_lower: str) -> bool:
    return any(t in text_lower for t in AKTIROVKA_TRIGGERS)

DISTRICT_ALIASES = {
    "norilsk": ("центральн",),  # «Центральный район» == город Норильск
    "talnakh": ("талнах",),
    "oganer": ("оганер",),
    "kayerkan": ("кайеркан", "каеркан"),
}


def extract_date_iso(text: str) -> str | None:
    """Первую дату ДД.ММ.ГГГГ из текста -> ISO-строку."""
    m = DATE_RE.search(text)
    if not m:
        return None
    d, mo, y = m.groups()
    try:
        return date(int(y), int(mo), int(d)).isoformat()
    except ValueError:
        return None


def extract_shift(text: str) -> int | None:
    m = SHIFT_RE.search(text)
    return int(m.group(1)) if m else None


def detect_districts(text_lower: str) -> list[str]:
    found = []
    for key, aliases in DISTRICT_ALIASES.items():
        if any(alias in text_lower for alias in aliases):
            found.append(key)
    return found


def parse_grade_range(text: str) -> tuple[int, int] | None:
    m = GRADE_RANGE_RE.search(text)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        if lo <= hi <= 11:
            return (lo, hi)
    m = GRADE_RANGE_SHORT_RE.search(text)
    if m:
        hi = int(m.group(1))
        if 1 <= hi <= 11:
            return (1, hi)
    return None


def parse_announcement(
    text: str, published=None, source: str = ""
) -> Announcement | None:
    """Разбирает объявление об актировках. Возвращает None, если это не оно."""
    low = text.lower().replace("ё", "е")
    if not looks_like_aktirovka(low):
        return None

    # Дата, на которую объявлена актировка: из текста, иначе из времени публикации
    date_iso = extract_date_iso(text)
    if date_iso is None and published is not None:
        date_iso = published.astimezone(config.TZ).date().isoformat()

    shift = extract_shift(text)
    if date_iso is None or shift is None:
        return None

    no_grades = {d: None for d in DISTRICT_KEYS}
    districts = detect_districts(low)

    # Обычное объявление: перечислены районы + диапазон классов
    if districts:
        rng = parse_grade_range(text)
        grades = {d: (rng if d in districts else None) for d in DISTRICT_KEYS}
        return Announcement(
            date=date_iso,
            shift_data=ShiftAktirovka(shift=shift, grades=grades),
            published=published,
            source=source,
        )

    # Техническая актировка для конкретных школ (без перечисления районов)
    schools = {int(n) for n in SCHOOL_RE.findall(text)}
    if schools:
        return Announcement(
            date=date_iso,
            shift_data=ShiftAktirovka(shift=shift, grades=dict(no_grades), school_numbers=schools),
            published=published,
            source=source,
        )

    # «Актировок нет»
    if NO_AKTIROVKA_RE.search(low):
        return Announcement(
            date=date_iso,
            shift_data=ShiftAktirovka(shift=shift, grades=dict(no_grades)),
            published=published,
            source=source,
        )

    return None
