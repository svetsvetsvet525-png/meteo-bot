"""Точка входа: python -m bot"""
from __future__ import annotations

import asyncio
import logging
import sys
import time

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramNetworkError

from bot import config, handlers, watch
from bot.db import Database


def _make_bot() -> Bot:
    """Создаёт бота; при заданном TELEGRAM_PROXY — через SOCKS/HTTP-прокси.

    Обычно не нужно (Telegram в России работает напрямую), но годится
    как страховка: socks5-релей поднимается на своём VPS командой
    `ssh -N -D 1080 root@vps` (см. tunnel/run_bot_termux.sh).
    """
    kwargs: dict = {
        "default": DefaultBotProperties(parse_mode=ParseMode.HTML),
    }
    if config.TELEGRAM_PROXY:
        kwargs["session"] = AiohttpSession(proxy=config.TELEGRAM_PROXY)
    return Bot(token=config.BOT_TOKEN, **kwargs)


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    if not config.BOT_TOKEN:
        sys.exit("Не задан BOT_TOKEN. Создайте файл .env по образцу .env.example")

    db = Database(config.DB_PATH)
    await db.init()

    bot = _make_bot()
    dp = Dispatcher()
    dp.include_router(handlers.router)
    dp["db"] = db

    scheduler = asyncio.create_task(watch.run_forever(bot, db))
    log = logging.getLogger(__name__)
    log.info("Бот запущен")

    # Сетевые качели (VPN, провайдер) не должны убивать процесс:
    # при TelegramNetworkError ждём и поднимаем polling заново.
    delay = 5.0
    try:
        while True:
            started = time.monotonic()
            try:
                await dp.start_polling(bot)
                break  # штатная остановка (сигнал/KeyboardInterrupt)
            except TelegramNetworkError as e:
                if time.monotonic() - started > 60:
                    delay = 5.0  # polling долго работал — сбрасываем задержку
                log.warning(
                    "Сеть Telegram недоступна (%r) — повтор через %.0f c", e, delay
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, 300)
    finally:
        scheduler.cancel()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
