"""Фолбэк-источник: веб-версия канала «Актировка Норильск» (t.me/s/aktirovka_norilsk)."""
from __future__ import annotations

import logging
from datetime import datetime

from bs4 import BeautifulSoup

from bot import config
from bot.models import Announcement, Storm
from bot.sources.http import http_client
from bot.sources.parsing import parse_announcement

log = logging.getLogger(__name__)


async def fetch(client=None) -> tuple[list[Announcement], list[Storm]]:
    """Возвращает (объявления об актировках, штормовые предупреждения) из последних постов канала."""
    client = client or http_client()
    response = await client.get(config.CHANNEL_URL)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    announcements: list[Announcement] = []
    storms: list[Storm] = []

    for message in soup.select("div.tgme_widget_message"):
        published: datetime | None = None
        time_tag = message.find("time")
        if time_tag and time_tag.get("datetime"):
            try:
                published = datetime.fromisoformat(time_tag["datetime"])
            except ValueError:
                pass

        text_el = message.select_one(".tgme_widget_message_text")
        if text_el is None:
            continue
        text = text_el.get_text("\n", strip=True)
        low = text.lower()

        parsed = parse_announcement(text, published=published, source="channel")
        if parsed:
            announcements.append(parsed)
        elif "штормов" in low:
            storms.append(Storm(published=published, text=text))

    return announcements, storms
