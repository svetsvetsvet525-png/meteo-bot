"""Конфигурация бота из переменных окружения / файла .env."""
from __future__ import annotations

import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _env_path(name: str, default: str) -> Path:
    value = os.getenv(name, default)
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")

# Интервал проверки источников, секунд
CHECK_INTERVAL: int = int(os.getenv("CHECK_INTERVAL", "300"))

# База данных (SQLite)
DB_PATH: Path = _env_path("DB_PATH", "data/bot.db")

# Источники данных
SITE_URL: str = os.getenv("SITE_URL", "https://www.norilsk-city.ru/meteo/")
CHANNEL_URL: str = os.getenv("CHANNEL_URL", "https://t.me/s/aktirovka_norilsk")
# Портал «Северный город» — основной источник (перепечатка бюллетеня администрации)
SGNORILSK_URL: str = os.getenv("SGNORILSK_URL", "https://sgnorilsk.ru/pogoda/")
# Официальный сайт норильск.рф — первоисточник бюллетеня. Домен сейчас нестабилен
# (сломан DNS), источник опрашивается не чаще раза в час и включается сам, когда сайт оживает
NORILSKRF_URL: str = os.getenv("NORILSKRF_URL", "https://xn--h1aecgfmj1g.xn--p1ai/weather/")
# Резервный источник meteonpr.ru — подключается, только если остальные молчат
METEONPR_URL: str = os.getenv("METEONPR_URL", "https://meteonpr.ru/")

# Прокси для российских сайтов, которые режут зарубежный трафик (гео-блок).
# Формат: "http://host:port" или "http://user:pass@host:port" (socks5:// —
# требует pip install "httpx[socks]"). Пусто = не использовать.
# Применяется только к норильск.рф и norilsk-city.ru.
RU_PROXY: str = os.getenv("RU_PROXY", "").strip()

# Проверка SSL-сертификата сайта администрации.
# На муниципальных сайтах сертификат бывает просрочен — ставьте 0, чтобы бот
# всё равно читал страницу (риск для публичной страницы чтения минимален).
SITE_VERIFY_SSL: bool = os.getenv("SITE_VERIFY_SSL", "1") == "1"

# Часовой пояс города (для определения «сегодня»)
TZ_NAME: str = os.getenv("TZ_NAME", "Asia/Krasnoyarsk")
TZ: ZoneInfo = ZoneInfo(TZ_NAME)

# Прокси для Telegram API. Обычно не нужен: Telegram в России работает напрямую.
# Страховка от редких замедлений — SOCKS через свой VPS (см. tunnel/README.md):
#   на телефоне:  ssh -N -D 1080 root@vps   (делает скрипт run_bot_termux.sh)
#   в .env:       TELEGRAM_PROXY=socks5://127.0.0.1:1080
TELEGRAM_PROXY: str = os.getenv("TELEGRAM_PROXY", "").strip()
