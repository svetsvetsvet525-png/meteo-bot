"""Фоновый мониторинг: сбор данных, сравнение сводок и рассылка в чаты."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter

from bot import config, texts
from bot.db import Database
from bot.models import Announcement, Board
from bot.sources import channel as channel_src
from bot.sources import meteonpr as meteonpr_src
from bot.sources import norilskrf as norilskrf_src
from bot.sources import site as site_src
from bot.sources import sgnorilsk as sgnorilsk_src
from bot.sources.http import http_client

log = logging.getLogger(__name__)

STATE_BOARD = "board_json"
STATE_SIG = "last_board_sig"
STATE_STORM = "last_storm_ts"

# Приоритет источников при одинаковых (дата, смена):
# официальный сайт норильск.рф > norilsk-city.ru > перепечатка на sgnorilsk.ru > канал/резерв
_SOURCE_RANK = {"norilskrf": 3, "site": 2, "sgnorilsk": 1, "channel": 0, "meteonpr": 0}


def norilsk_today() -> str:
    """Сегодняшняя дата по времени Норильска (UTC+7)."""
    return datetime.now(config.TZ).date().isoformat()


def _key(a: Announcement) -> tuple[str, int]:
    return (a.date, int(a.shift_data.shift))


def _better(a: Announcement, b: Announcement) -> bool:
    """Предпочитаем более авторитетный источник; при равном — более свежую публикацию."""
    ra, rb = _SOURCE_RANK.get(a.source, 0), _SOURCE_RANK.get(b.source, 0)
    if ra != rb:
        return ra > rb
    if a.published and b.published:
        return a.published > b.published
    return b.published is None


def _dedupe(announcements: list[Announcement]) -> list[Announcement]:
    best: dict[tuple[str, int], Announcement] = {}
    for a in announcements:
        k = _key(a)
        if k not in best or _better(a, best[k]):
            best[k] = a
    return list(best.values())


async def collect(client, full: bool = True) -> tuple[list[Announcement], list]:
    """Опрашивает источники: норильск.рф → sgnorilsk.ru → сайт администрации → канал → meteonpr.ru.

    full=False — быстрый режим для команд: медленные и нестабильные сайты
    опрашиваются, только если быстрый основной источник не дал данных.
    """
    announcements: list[Announcement] = []
    storms = []

    # Официальный сайт норильск.рф — первоисточник бюллетеня. Домен сейчас
    # нестабилен, поэтому источник сам троттлит попытки (не чаще раза в час)
    if full:
        try:
            nor_anns, nor_storms = await norilskrf_src.fetch(client)
            if nor_anns or nor_storms:
                log.info(
                    "норильск.рф ответил: %s объявл., %s штормовых",
                    len(nor_anns), len(nor_storms),
                )
            announcements.extend(nor_anns)
            storms.extend(nor_storms)
        except Exception as e:  # noqa: BLE001
            log.warning("Официальный сайт норильск.рф недоступен: %r", e)

    try:
        sgn_anns, sgn_storms = await sgnorilsk_src.fetch(client)
        announcements.extend(sgn_anns)
        storms.extend(sgn_storms)
    except Exception as e:  # noqa: BLE001 — портал может быть недоступен
        log.warning("Портал sgnorilsk.ru недоступен: %r", e)

    # Сайт администрации — первоисточник, но нестабильный и медленный
    if full or not announcements:
        try:
            announcements.extend(await site_src.fetch(client))
        except Exception as e:  # noqa: BLE001
            log.warning("Сайт администрации недоступен: %r", e)

    try:
        channel_anns, channel_storms = await channel_src.fetch(client)
        announcements.extend(channel_anns)
        storms.extend(channel_storms)
    except Exception as e:  # noqa: BLE001
        log.warning("Канал @aktirovka_norilsk недоступен: %r", e)

    # Резерв meteonpr.ru подключаем, только если все остальные молчат
    if not announcements:
        try:
            announcements.extend(await meteonpr_src.fetch(client))
        except Exception as e:  # noqa: BLE001
            log.warning("meteonpr.ru недоступен: %r", e)

    return _dedupe(announcements), storms


def _target_date(announcements: list[Announcement], today_iso: str) -> str:
    """Дата, на которую строим сводку: сегодня, иначе завтра.

    Вечером администрация иногда публикует объявление уже на следующий
    день — такое объявление важнее пропасть не должно.
    """
    dates = {a.date for a in announcements}
    if today_iso in dates:
        return today_iso
    tomorrow = (date.fromisoformat(today_iso) + timedelta(days=1)).isoformat()
    if tomorrow in dates:
        return tomorrow
    return today_iso


def _build_board(announcements: list[Announcement], today_iso: str) -> Board:
    target = _target_date(announcements, today_iso)
    board = Board(date=target)
    for a in announcements:
        if a.date == target:
            board.merge(a.shift_data)
    return board


async def current_board(db: Database, client) -> tuple[Board, str | None]:
    """Сводка для команд + дата самого свежего объявления в источниках.

    Приоритет: сегодняшние данные → последняя сохранённая → последнее
    объявление источников (команда texts.command_text пометит его датой).
    """
    announcements, _ = await collect(client, full=False)
    today = norilsk_today()
    board = _build_board(announcements, today)
    latest_date = max((a.date for a in announcements), default=None)

    if not board.shifts:
        stored = await load_board(db)
        if stored:
            board = stored
        elif latest_date and latest_date != today:
            # Данных за сегодня нет — показываем последнее объявление источников
            board = Board(date=latest_date)
            for a in announcements:
                if a.date == latest_date:
                    board.merge(a.shift_data)
    return board, latest_date


async def load_board(db: Database) -> Board | None:
    raw = await db.get_state(STATE_BOARD)
    if not raw:
        return None
    try:
        return Board.from_dict(json.loads(raw))
    except (ValueError, KeyError):
        return None


async def save_board(db: Database, board: Board) -> None:
    await db.set_state(STATE_BOARD, json.dumps(board.to_dict(), ensure_ascii=False))


# --- рассылка ----------------------------------------------------------------


async def safe_send(bot: Bot, chat_id: int, text: str) -> None:
    try:
        await bot.send_message(chat_id, text)
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after + 1)
        try:
            await bot.send_message(chat_id, text)
        except Exception as e:  # noqa: BLE001
            log.warning("Повторная отправка в %s не удалась: %r", chat_id, e)
    except Exception as e:  # noqa: BLE001
        log.warning("Не удалось отправить сообщение в %s: %r", chat_id, e)


async def broadcast_aktirovka(bot: Bot, db: Database, board: Board) -> None:
    for chat in await db.all_chats():
        text = texts.broadcast_text(board, chat)
        if text:
            await safe_send(bot, chat.chat_id, text)
            await asyncio.sleep(0.4)


async def broadcast_storms(bot: Bot, db: Database, storms) -> None:
    timestamps = [s.published for s in storms if s.published]
    if not timestamps:
        return
    newest = max(timestamps)
    last_raw = await db.get_state(STATE_STORM)
    await db.set_state(STATE_STORM, newest.isoformat())

    if last_raw is None:  # первый запуск — старые посты не рассылаем
        return
    try:
        last_seen = datetime.fromisoformat(last_raw)
    except ValueError:
        return

    new_storms = sorted((s for s in storms if s.published and s.published > last_seen),
                        key=lambda s: s.published)
    for storm in new_storms:
        text = texts.storm_text(storm.text, storm.source)
        for chat in await db.all_chats():
            await safe_send(bot, chat.chat_id, text)
            await asyncio.sleep(0.4)


# --- основной цикл ------------------------------------------------------------


async def check_cycle(bot: Bot, db: Database, client) -> None:
    announcements, storms = await collect(client)
    today = norilsk_today()
    board = _build_board(announcements, today)

    # Дополняем сохранёнными данными за ту же дату (другая смена могла быть объявлена раньше)
    stored = await load_board(db)
    if stored and stored.date == board.date:
        for sa in stored.shifts.values():
            if sa.shift not in board.shifts:
                board.merge(sa)

    sig = board.signature() if board.shifts else ""
    last_sig = await db.get_state(STATE_SIG)

    # Первый запуск без свежих данных: запоминаем текущий бюллетень источников
    # как базу, чтобы самое первое НОВОЕ объявление пришло в чат сообщением.
    if not board.shifts and last_sig is None:
        await _seed_first_state(db, announcements)
        last_sig = await db.get_state(STATE_SIG)

    if board.shifts and sig != last_sig:
        first_run = last_sig is None
        await save_board(db, board)
        await db.set_state(STATE_SIG, sig)
        if not first_run:
            log.info("Сводка изменилась — рассылка (%s постов)", len(await db.all_chats()))
            await broadcast_aktirovka(bot, db, board)

    await broadcast_storms(bot, db, storms)


async def _seed_first_state(db: Database, announcements: list[Announcement]) -> None:
    """Фиксирует текущее состояние источников как стартовую базу сравнения."""
    dates = [a.date for a in announcements if a.date]
    if not dates:
        return
    latest = max(dates)
    board = Board(date=latest)
    for a in announcements:
        if a.date == latest:
            board.merge(a.shift_data)
    await save_board(db, board)
    await db.set_state(STATE_SIG, board.signature())
    log.info("Первый запуск: база — бюллетень источников от %s", latest)


async def run_forever(bot: Bot, db: Database) -> None:
    log.info("Планировщик запущен, проверка каждые %s сек.", config.CHECK_INTERVAL)
    async with http_client() as client:
        while True:
            try:
                await check_cycle(bot, db, client)
            except Exception:  # noqa: BLE001
                log.exception("Ошибка цикла проверки")
            await asyncio.sleep(config.CHECK_INTERVAL)
