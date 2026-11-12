"""Модели данных: актировки по сменам и районам."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime

# Канонические ключи районов Норильского промрайона
DISTRICT_KEYS = ("norilsk", "talnakh", "oganer", "kayerkan")

DISTRICT_DISPLAY = {
    "norilsk": "Норильск (Центральный район)",
    "talnakh": "Талнах",
    "oganer": "Оганер",
    "kayerkan": "Кайеркан",
}

GradeRange = tuple[int, int]  # (с какого класса, по какой)


@dataclass
class ShiftAktirovka:
    """Актировки одной смены: район -> диапазон классов или None (актировки нет)."""

    shift: int
    grades: dict[str, GradeRange | None]
    school_numbers: set[int] = field(default_factory=set)

    def affects(self, district: str, grade: int, school: int | None) -> tuple[bool, str | None]:
        """Проверяет, касается ли актировка конкретного класса. Возвращает (да/нет, причина)."""
        if self.school_numbers and school is not None and school in self.school_numbers:
            return True, "техническая актировка в вашей школе (1–11 классы)"
        g = self.grades.get(district)
        if g and g[0] <= grade <= g[1]:
            if g[0] == g[1]:
                return True, f"актировка для {g[0]} класса"
            return True, f"актировка с {g[0]} по {g[1]} классы"
        return False, None

    def to_dict(self) -> dict:
        return {
            "shift": self.shift,
            "grades": {d: (list(g) if g else None) for d, g in self.grades.items()},
            "schools": sorted(self.school_numbers),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ShiftAktirovka":
        grades = {d: (tuple(g) if g else None) for d, g in data.get("grades", {}).items()}
        return cls(
            shift=int(data["shift"]),
            grades=grades,
            school_numbers=set(data.get("schools", [])),
        )


@dataclass
class Board:
    """Сводка актировок за одну дату по всем сменам."""

    date: str  # ISO-дата, на которую объявлены актировки
    shifts: dict[int, ShiftAktirovka] = field(default_factory=dict)

    def merge(self, sa: ShiftAktirovka) -> None:
        self.shifts[int(sa.shift)] = sa

    def has_any(self) -> bool:
        """Есть ли хоть где-то актировка (или техническая — по школам)."""
        for sa in self.shifts.values():
            if sa.school_numbers:
                return True
            if any(g is not None for g in sa.grades.values()):
                return True
        return False

    def affects(
        self, district: str | None, shift: int | None, grade: int | None, school: int | None
    ) -> tuple[bool, str | None]:
        if district is None or shift is None or grade is None:
            return False, None
        sa = self.shifts.get(int(shift))
        if not sa:
            return False, None
        return sa.affects(district, grade, school)

    def signature(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False)

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "shifts": {str(s): sa.to_dict() for s, sa in sorted(self.shifts.items())},
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Board":
        board = cls(date=data["date"])
        for s, sa in data.get("shifts", {}).items():
            board.merge(ShiftAktirovka.from_dict(sa))
        return board


@dataclass
class Announcement:
    """Разобранное объявление об актировках (с сайта или из канала)."""

    date: str  # ISO-дата, на которую объявлено
    shift_data: ShiftAktirovka
    published: datetime | None = None  # UTC-время публикации, если известно
    source: str = ""  # "site" | "channel"


@dataclass
class Storm:
    """Штормовое предупреждение."""

    published: datetime | None
    text: str
    source: str = ""  # подпись источника (для сообщений); "" — канал @aktirovka_norilsk
