"""Резервный источник: meteonpr.ru (блок «Информация об актировках»).

Специализированный метео-сайт Норильского промрайона. Блок размечен
просто: <h2>Информация об актировках</h2><a class='info'>текст</a>.
Подключается только когда основные источники молчат: страница тяжёлая
(~1 МБ), а текст там появляется в том же официальном виде, что и на
сайте администрации, — его разбирает общий parse_announcement().
"""
from __future__ import annotations

import logging
import re

import httpx
from bs4 import BeautifulSoup

from bot import config
from bot.models import Announcement
from bot.sources.http import http_client
from bot.sources.parsing import parse_announcement

log = logging.getLogger(__name__)

SOURCE = "meteonpr"


async def fetch(client=None) -> list[Announcement]:
    """Скачивает главную и разбирает блок «Информация об актировках» (0..1 шт.)."""
    client = client or http_client()
    response = await client.get(
        config.METEONPR_URL, timeout=httpx.Timeout(12.0, connect=6.0)
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    block = None
    heading = soup.find("h2", string=re.compile("актиров", re.IGNORECASE))
    if heading is not None:
        block = heading.find_next("a", class_="info")
    if block is None:
        block = soup.find("a", class_="info")
    if block is None:
        return []

    text = block.get_text(" ", strip=True)
    parsed = parse_announcement(text, published=None, source=SOURCE)
    if parsed is None:
        log.debug("meteonpr: текст без даты/смены пропущен: %.120s", text)
    return [parsed] if parsed else []
