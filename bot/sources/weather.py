"""Прогноз погоды через Open-Meteo (бесплатно, без API-ключа)."""
from __future__ import annotations

import httpx

from bot.sources.http import http_client

# Координаты Норильска
LATITUDE = 69.3535
LONGITUDE = 88.2021

PARAMS = {
    "latitude": LATITUDE,
    "longitude": LONGITUDE,
    "current": "temperature_2m,apparent_temperature,wind_speed_10m,wind_gusts_10m,wind_direction_10m,weather_code",
    "daily": "temperature_2m_max,temperature_2m_min,wind_speed_10m_max,wind_gusts_10m_max,weather_code",
    "timezone": "Asia/Krasnoyarsk",
    "forecast_days": 3,
}


async def fetch(client: httpx.AsyncClient | None = None) -> dict:
    client = client or http_client()
    response = await client.get("https://api.open-meteo.com/v1/forecast", params=PARAMS)
    response.raise_for_status()
    return response.json()
