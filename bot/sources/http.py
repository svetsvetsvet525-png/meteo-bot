"""Общий HTTP-клиент для всех источников."""
from __future__ import annotations

import httpx

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

_client: httpx.AsyncClient | None = None
_site_client: httpx.AsyncClient | None = None


def http_client() -> httpx.AsyncClient:
    """Ленивый общий клиент (создаётся внутри работающего event loop)."""
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT, "Accept-Language": "ru"},
            timeout=httpx.Timeout(25.0, connect=15.0),
            follow_redirects=True,
        )
    return _client


def site_client() -> httpx.AsyncClient:
    """Отдельный клиент для сайта администрации (с настраиваемой проверкой SSL)."""
    global _site_client
    if _site_client is None:
        _site_client = httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT, "Accept-Language": "ru"},
            timeout=httpx.Timeout(30.0, connect=15.0),
            follow_redirects=True,
            verify=site_verify_ssl(),
        )
    return _site_client


def site_verify_ssl() -> bool:
    import bot.config as config
    return config.SITE_VERIFY_SSL


_proxy_client: httpx.AsyncClient | None = None


def proxied_site_client() -> httpx.AsyncClient | None:
    """Клиент через RU_PROXY для сайтов с гео-блоком; None, если прокси не настроен."""
    global _proxy_client
    import bot.config as config
    if not config.RU_PROXY:
        return None
    if _proxy_client is None:
        _proxy_client = httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT, "Accept-Language": "ru"},
            timeout=httpx.Timeout(30.0, connect=15.0),
            follow_redirects=True,
            verify=site_verify_ssl(),
            proxy=config.RU_PROXY,
        )
    return _proxy_client
