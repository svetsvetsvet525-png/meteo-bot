"""Форматирование сообщений бота."""
from __future__ import annotations

import html
from datetime import date, timedelta

from bot.db import ChatSettings
from bot.models import Board, DISTRICT_DISPLAY, DISTRICT_KEYS

STORM_SOURCE = "канал @aktirovka_norilsk"


def ru_date(iso_date: str) -> str:
    try:
        y, m, d = iso_date.split("-")
        return f"{d}.{m}.{y}"
    except ValueError:
        return iso_date


def _range_str(g: tuple[int, int]) -> str:
    if g[0] == g[1]:
        return f"{g[0]} класс"
    return f"с {g[0]} по {g[1]} классы"


def _shift_lines(sa) -> list[str]:
    lines = []
    for district in DISTRICT_KEYS:
        g = sa.grades.get(district)
        name = DISTRICT_DISPLAY[district]
        if g is None:
            lines.append(f"• {name}: ✅ актировок нет")
        else:
            lines.append(f"• {name}: ⚠️ актировка {_range_str(g)}")
    if sa.school_numbers:
        nums = ", ".join(f"№{n}" for n in sorted(sa.school_numbers))
        lines.append(f"• Техническая актировка: школа {nums} (1–11 классы)")
    return lines


def format_board(board: Board) -> str:
    out = [f"❄️ <b>Актировки на {ru_date(board.date)}</b>", ""]
    for shift in (1, 2):
        sa = board.shifts.get(shift)
        if sa is None:
            out.append(f"<b>{shift}-я смена:</b> данных пока нет")
        else:
            out.append(f"<b>{shift}-я смена:</b>")
            out.extend(_shift_lines(sa))
        out.append("")
    return "\n".join(out).strip()


def chat_label(chat: ChatSettings) -> str:
    parts = []
    if chat.grade:
        parts.append(f"{chat.grade}-й класс")
    if chat.shift:
        parts.append(f"{chat.shift}-я смена")
    if chat.district:
        parts.append(DISTRICT_DISPLAY[chat.district])
    return ", ".join(parts) if parts else "класс не настроен"


def _personal_line(board: Board, chat: ChatSettings) -> str | None:
    configured = chat.district and chat.shift and chat.grade
    if not configured:
        return None
    relevant, detail = board.affects(chat.district, chat.shift, chat.grade, chat.school)
    label = chat_label(chat)
    if relevant:
        return f"⚠️ <b>Вас касается</b> ({label}): {detail}"
    # «Занятия по расписанию» честно говорим только когда по смене есть данные
    sa = board.shifts.get(int(chat.shift))
    if sa is not None:
        return f"✅ {label} — занятия по расписанию"
    return f"⏳ {label} — по вашей смене данных ещё нет"


def command_text(
    board: Board, chat: ChatSettings | None, today_iso: str | None = None,
    latest_date: str | None = None,
) -> str:
    """Ответ на /aktirovka: сводка + строка про класс чата."""
    body = format_board(board)
    head = "🏫 <b>Сводка</b>\n\n"
    if today_iso and board.date != today_iso:
        tomorrow = (date.fromisoformat(today_iso) + timedelta(days=1)).isoformat()
        if board.date == tomorrow:
            head += "📅 <i>Уже объявлено на завтра:</i>\n\n"
        else:
            head += (
                "⚠️ <i>Свежих данных за сегодня нет — это последние доступные данные "
                f"(на {ru_date(board.date)}).</i>\n\n"
            )
    elif not board.shifts:
        head += "💤 <i>За сегодня данных ещё нет — источники пока молчат."
        if latest_date:
            head += f"\nПоследнее объявление в источниках — от {ru_date(latest_date)}."
        head += "</i>\n\n"
    personal = _personal_line(board, chat) if chat else None
    if personal:
        head += personal + "\n\n"
    return head + body


def broadcast_text(board: Board, chat: ChatSettings) -> str | None:
    """Сообщение для рассылки при изменении сводки.

    Возвращает None, если чату писать не нужно.
    """
    relevant, detail = board.affects(chat.district, chat.shift, chat.grade, chat.school)

    if relevant:
        head = "❄️❄️❄️ <b>АКТИРОВКА!</b> ❄️❄️❄️\n"
        head += f"{chat_label(chat)}\n"
        head += f"⚠️ Занятия отменяются — {detail}.\n\n"
        return head + format_board(board)

    if not chat.daily_digest:
        return None

    personal = _personal_line(board, chat)
    if board.has_any():
        text = (personal + "\n\n") if personal else ""
        return text + format_board(board)

    text = f"✅ <b>Актировок нет</b> — {ru_date(board.date)}.\nЗанятия по расписанию."
    if personal:
        text += "\n\n" + personal
    return text


def storm_text(text: str, source: str | None = None) -> str:
    label = source or STORM_SOURCE
    return (
        "🌪 <b>Штормовое предупреждение</b>\n\n"
        f"{html.escape(text)}\n\n"
        f"<i>Источник: {html.escape(label)}</i>"
    )


_WEATHER_CODE = {
    0: "☀️", 1: "🌤️", 2: "⛅️", 3: "☁️", 45: "🌫️", 48: "🌫️",
    51: "🌦️", 53: "🌦️", 55: "🌦️", 56: "🌧️", 57: "🌧️",
    61: "🌧️", 63: "🌧️", 65: "🌧️", 66: "🌧️", 67: "🌧️",
    71: "🌨️", 73: "🌨️", 75: "❄️", 77: "🌨️",
    80: "🌧️", 81: "🌧️", 82: "🌧️", 85: "🌨️", 86: "❄️",
    95: "⛈️", 96: "⛈️", 99: "⛈️",
}

_WIND_DIRS = ["С", "СВ", "В", "ЮВ", "Ю", "ЮЗ", "З", "СЗ"]


def _wind_dir(deg: float | None) -> str:
    if deg is None:
        return ""
    return _WIND_DIRS[round(deg / 45) % 8]


def format_weather(data: dict) -> str:
    cur = data["current"]
    daily = data["daily"]
    emoji = _WEATHER_CODE.get(cur.get("weather_code"), "🌡️")

    lines = [
        f"{emoji} <b>Погода: Норильск</b>",
        "",
        (
            f"Сейчас: {cur['temperature_2m']}°C "
            f"(ощущается {cur['apparent_temperature']}°C), "
            f"ветер {cur['wind_speed_10m']} м/с "
            f"{_wind_dir(cur.get('wind_direction_10m'))}, "
            f"порывы до {cur['wind_gusts_10m']} м/с"
        ),
        "",
    ]

    for i, day in enumerate(daily["time"][:2]):
        title = "Сегодня" if i == 0 else "Завтра"
        code = _WEATHER_CODE.get(daily["weather_code"][i], "🌡️")
        lines.append(
            f"<b>{title}:</b> {daily['temperature_2m_min'][i]}…{daily['temperature_2m_max'][i]}°C, "
            f"ветер до {daily['wind_speed_10m_max'][i]} м/с "
            f"(порывы до {daily['wind_gusts_10m_max'][i]}) {code}"
        )

    return "\n".join(lines)
