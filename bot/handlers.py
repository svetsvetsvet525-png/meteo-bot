"""Хэндлеры команд Telegram-бота."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot import texts
from bot.db import ChatSettings, Database
from bot.models import DISTRICT_DISPLAY, DISTRICT_KEYS
from bot.sources import channel as channel_src
from bot.sources import weather as weather_src
from bot.sources.http import http_client
from bot.watch import collect, current_board
from bot.watch import norilsk_today as _today_iso

log = logging.getLogger(__name__)
router = Router()


class Setup(StatesGroup):
    district = State()
    shift = State()
    grade = State()


# --- клавиатуры ---------------------------------------------------------------


def kb_district() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=DISTRICT_DISPLAY[d], callback_data=f"setup:dist:{d}")]
            for d in DISTRICT_KEYS
        ]
    )


def kb_shift() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="1-я смена", callback_data="setup:shift:1")],
            [InlineKeyboardButton(text="2-я смена", callback_data="setup:shift:2")],
        ]
    )


def kb_grade() -> InlineKeyboardMarkup:
    rows, current = [], []
    for g in range(1, 12):
        current.append(InlineKeyboardButton(text=str(g), callback_data=f"setup:grade:{g}"))
        if len(current) == 4:
            rows.append(current)
            current = []
    if current:
        rows.append(current)
    return InlineKeyboardMarkup(inline_keyboard=rows)


# --- старт и настройка ---------------------------------------------------------


@router.message(CommandStart())
async def cmd_start(message: Message, db: Database) -> None:
    await db.upsert_chat(message.chat.id, getattr(message.chat, "title", "") or "")
    if message.chat.type == "private":
        await message.answer(
            "Привет! Я бот актировок Норильска ❄️\n\n"
            "Настройте свой класс: /setup\nСписок команд: /help"
        )
    else:
        await message.answer(
            "Привет! Я бот актировок Норильска ❄️\n"
            "Буду присылать сюда сводки об актировках.\n\n"
            "Настройте класс, смену и район: /setup"
        )


@router.message(Command("setup", "настройка"))
async def cmd_setup(message: Message, state: FSMContext, db: Database) -> None:
    await db.upsert_chat(message.chat.id, getattr(message.chat, "title", "") or "")
    await state.set_state(Setup.district)
    await message.answer("Шаг 1/3 — выберите район:", reply_markup=kb_district())


@router.callback_query(F.data.startswith("setup:dist:"), Setup.district)
async def cb_district(call: CallbackQuery, state: FSMContext) -> None:
    district = call.data.split(":")[2]
    if district not in DISTRICT_KEYS:
        await call.answer("Неизвестный район")
        return
    await state.update_data(district=district)
    await state.set_state(Setup.shift)
    await call.message.answer("Шаг 2/3 — выберите смену:", reply_markup=kb_shift())
    await call.answer()


@router.callback_query(F.data.startswith("setup:shift:"), Setup.shift)
async def cb_shift(call: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(shift=int(call.data.split(":")[2]))
    await state.set_state(Setup.grade)
    await call.message.answer("Шаг 3/3 — выберите ваш класс:", reply_markup=kb_grade())
    await call.answer()


@router.callback_query(F.data.startswith("setup:grade:"), Setup.grade)
async def cb_grade(call: CallbackQuery, state: FSMContext, db: Database) -> None:
    data = await state.get_data()
    grade = int(call.data.split(":")[2])
    await db.update_settings(
        call.message.chat.id,
        district=data.get("district"),
        shift=data.get("shift"),
        grade=grade,
    )
    await state.clear()
    chat = await db.get_chat(call.message.chat.id)
    await call.message.answer(
        f"Готово! {texts.chat_label(chat)}\n\n"
        "Проверить: /aktirovka\n\n"
        "💡 Дополнительно можно указать номер школы (/school 31) — тогда бот "
        "оповестит и о технической актировке именно вашей школы."
    )
    await call.answer("Сохранено")


# --- команды --------------------------------------------------------------------


@router.message(Command("aktirovka", "актировка"))
async def cmd_aktirovka(message: Message, db: Database) -> None:
    await db.upsert_chat(message.chat.id, getattr(message.chat, "title", "") or "")
    board, latest_date = await current_board(db, http_client())
    chat = await db.get_chat(message.chat.id)
    await message.answer(
        texts.command_text(board, chat, today_iso=_today_iso(), latest_date=latest_date)
    )


@router.message(Command("storm", "шторм"))
async def cmd_storm(message: Message) -> None:
    _, storms = await collect(http_client(), full=False)
    if not storms:
        await message.answer("Штормовых предупреждений в источниках сейчас нет.")
        return
    # Бюллетень ГО и ЧС (sgnorilsk) — без времени публикации, но страница живая
    # и обновляется; канал @aktirovka_norilsk заморожен с июня 2026, поэтому его
    # штормовые (с метками времени) используем только если бюллетеня нет.
    live = [s for s in storms if s.published is None]
    timestamped = [s for s in storms if s.published is not None]
    latest = live[0] if live else max(timestamped, key=lambda s: s.published)
    await message.answer(texts.storm_text(latest.text, latest.source))


@router.message(Command("pogoda", "погода", "weather"))
async def cmd_pogoda(message: Message) -> None:
    data = await weather_src.fetch(http_client())
    await message.answer(texts.format_weather(data))


@router.message(Command("school", "школа"))
async def cmd_school(message: Message, db: Database) -> None:
    await db.upsert_chat(message.chat.id, getattr(message.chat, "title", "") or "")
    args = message.text.split()[1:]
    if not args:
        chat = await db.get_chat(message.chat.id)
        current = chat.school if chat else None
        await message.answer(
            f"Текущая школа: {current if current else 'не задана'}.\n"
            "Укажите номер: /school 31 (или /school 0, чтобы сбросить)"
        )
        return
    try:
        school = int(args[0])
    except ValueError:
        await message.answer("Номер школы должен быть числом, например: /school 31")
        return
    await db.update_settings(message.chat.id, school=school if school > 0 else None)
    if school > 0:
        await message.answer(f"Школа №{school} сохранена ✅")
    else:
        await message.answer("Номер школы сброшен.")


@router.message(Command("digest"))
async def cmd_digest(message: Message, db: Database) -> None:
    await db.upsert_chat(message.chat.id, getattr(message.chat, "title", "") or "")
    chat = await db.get_chat(message.chat.id)
    new_value = not (chat.daily_digest if chat else True)
    await db.update_settings(message.chat.id, daily_digest=new_value)
    state_word = "включена ✅" if new_value else "выключена 🔕"
    await message.answer(f"Ежедневная сводка {state_word}")


@router.message(Command("status", "настройки"))
async def cmd_status(message: Message, db: Database) -> None:
    chat = await db.get_chat(message.chat.id)
    if not chat or not (chat.district and chat.shift and chat.grade):
        await message.answer("Настройки не заданы. Выполните /setup")
        return
    extra = f"Школа №{chat.school}" if chat.school else "Школа не указана"
    digest = "вкл" if chat.daily_digest else "выкл"
    await message.answer(
        f"{texts.chat_label(chat)}\n{extra}\nЕжедневная сводка: {digest}\n\n"
        "Изменить: /setup • /school 31 • /digest"
    )


@router.message(Command("id"))
async def cmd_id(message: Message) -> None:
    await message.answer(f"chat_id: <code>{message.chat.id}</code>")


@router.message(Command("help", "команды"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "<b>Команды:</b>\n\n"
        "/aktirovka — сводка об актировках на сегодня\n"
        "/pogoda — погода в Норильске\n"
        "/storm — штормовое предупреждение\n"
        "/setup — настроить район, смену и класс\n"
        "/school 31 — номер вашей школы (для технических актировок)\n"
        "/digest — вкл/выкл ежедневную сводку «актировок нет»\n"
        "/status — текущие настройки\n"
        "/id — узнать chat_id этого чата\n\n"
        "<i>Бот проверяет источники каждые несколько минут и сам пишет "
        "в чат, когда объявляют актировку.</i>"
    )
