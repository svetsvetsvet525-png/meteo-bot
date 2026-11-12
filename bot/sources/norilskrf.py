"""Источник: официальный сайт норильск.рф, раздел «Погода и сообщения ГОиЧС».

Это первоисточник бюллетеня (sgnorilsk.ru перепечатывает именно его). Домен
xн--h1aecgfmj1g.xn--p1ai сейчас нестабилен: DNS-делегирование сломано (все
публичные резолверы получают SERVFAIL), а сервер по прямому IP не отвечает.

Поэтому источник ведёт себя «умно»:
  - в быстром режиме (команды) не опрашивается вовсе;
  - в полном цикле пробуется не чаще одного раза в час (чтобы не тормозить
    цикл 2-минутных проверок DNS-таймаутами);
  - как только сайт оживает — источник автоматически возвращается в строй.

Формат страницы совпадает с бюллетенем на sgnorilsk.ru, поэтому используется
sgnorilsk.parse_html(); дополнительно — фолбэк на общий разбор текстовых
блоков, если вёрстка раздела поменяется.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import replace

import httpx
from bs4 import BeautifulSoup

from bot import config
from bot.models import Announcement, Storm
from bot.sources import sgnorilsk as sgnorilsk_src
from bot.sources.http import proxied_site_client, site_client
from bot.sources.parsing import parse_announcement

log = logging.getLogger(__name__)

SOURCE = "norilskrf"
STORM_SOURCE = "норильск.рф — Управление ГО и ЧС Норильска"

# Повторные попытки после неудачи — не чаще этого интервала (секунды)
_COOLDOWN = 3600.0
_cooldown_until = 0.0  # time.monotonic()

# Признаки DNS-ошибки (при ней http-версию пробовать бессмысленно)
_DNS_MARKS = (
    "name or service not known",
    "nodename nor servname",
    "temporary failure in name resolution",
    "getaddrinfo failed",
    "no address associated",
)


def _is_dns_error(exc: BaseException) -> bool:
    message = str(exc).lower()
    return any(mark in message for mark in _DNS_MARKS)


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


def _fallback_announcements(soup: BeautifulSoup) -> list[Announcement]:
    """Фолбэк-разбор: ищем блоки, похожие на объявление (дата + смена обязательны)."""
    for tag in soup.find_all(["p", "div"]):
        text = tag.get_text(" ", strip=True)
        if not text or len(text) > 2500:
            continue
        parsed = parse_announcement(text, published=None, source=SOURCE)
        if parsed:
            return [parsed]
    return []


def _parse_page(html: str) -> tuple[list[Announcement], list[Storm]]:
    """Разбор страницы. Отдельно от fetch() — для офлайн-тестов."""
    announcements, storms = sgnorilsk_src.parse_html(html)
    if announcements:
        return (
            [replace(a, source=SOURCE) for a in announcements],
            [replace(s, source=STORM_SOURCE) for s in storms],
        )

    soup = BeautifulSoup(html, "html.parser")
    return _fallback_announcements(soup), [replace(s, source=STORM_SOURCE) for s in storms]


async def fetch(client=None) -> tuple[list[Announcement], list[Storm]]:
    """Скачивает раздел «Сообщения ГОиЧС».

    При неудаче устанавливает часовую паузу и возвращает пустой результат,
    чтобы не тормозить циклы опроса недоступным доменом.
    """
    global _cooldown_until
    if time.monotonic() < _cooldown_until:
        return [], []

    # Всегда свой клиент: у российских админ-сайтов бывают просроченные
    # сертификаты (SITE_VERIFY_SSL=0), а общий клиент проверяет SSL всегда.
    # При настроенном RU_PROXY — через прокси (гео-блок).
    client = proxied_site_client() or site_client()

    try:
        response = await client.get(
            config.NORILSKRF_URL, timeout=httpx.Timeout(15.0, connect=8.0)
        )
        response.raise_for_status()
    except httpx.HTTPError as e:
        if _is_dns_error(e):
            _cooldown_until = time.monotonic() + _COOLDOWN
            log.warning("норильск.рф: DNS не отвечает — пауза на час (%r)", e)
            return [], []
        # Не DNS (например, TLS) — пробуем http-версию без сертификата
        try:
            http_url = re.sub(r"^https://", "http://", config.NORILSKRF_URL, count=1)
            response = await client.get(http_url, timeout=httpx.Timeout(15.0, connect=8.0))
            response.raise_for_status()
        except httpx.HTTPError as e2:
            _cooldown_until = time.monotonic() + _COOLDOWN
            log.warning("норильск.рф недоступен — пауза на час (%r)", e2)
            return [], []

    _cooldown_until = 0.0  # сайт жив — пробуем каждый цикл
    return _parse_page(_decode(response))
