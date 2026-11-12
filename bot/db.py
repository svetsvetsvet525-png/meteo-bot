"""SQLite-база: подписанные чаты и служебное состояние."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (
    chat_id     INTEGER PRIMARY KEY,
    title       TEXT NOT NULL DEFAULT '',
    district    TEXT,
    shift       INTEGER,
    grade       INTEGER,
    school      INTEGER,
    daily_digest INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_ALLOWED_FIELDS = ("district", "shift", "grade", "school", "daily_digest", "title")


@dataclass
class ChatSettings:
    chat_id: int
    title: str = ""
    district: str | None = None
    shift: int | None = None
    grade: int | None = None
    school: int | None = None
    daily_digest: bool = True


class Database:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._conn: aiosqlite.Connection | None = None

    async def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    # --- чаты ---------------------------------------------------------------

    async def upsert_chat(self, chat_id: int, title: str = "") -> None:
        await self._conn.execute(
            "INSERT INTO chats(chat_id, title) VALUES(?, ?) "
            "ON CONFLICT(chat_id) DO NOTHING",
            (chat_id, title or ""),
        )
        await self._conn.commit()

    @staticmethod
    def _to_chat(row: aiosqlite.Row) -> ChatSettings:
        return ChatSettings(
            chat_id=row["chat_id"],
            title=row["title"],
            district=row["district"],
            shift=row["shift"],
            grade=row["grade"],
            school=row["school"],
            daily_digest=bool(row["daily_digest"]),
        )

    async def get_chat(self, chat_id: int) -> ChatSettings | None:
        async with self._conn.execute(
            "SELECT * FROM chats WHERE chat_id = ?", (chat_id,)
        ) as cur:
            row = await cur.fetchone()
        return self._to_chat(row) if row else None

    async def all_chats(self) -> list[ChatSettings]:
        async with self._conn.execute("SELECT * FROM chats") as cur:
            rows = await cur.fetchall()
        return [self._to_chat(row) for row in rows]

    async def update_settings(self, chat_id: int, **fields: Any) -> None:
        sets, params = [], []
        for name, value in fields.items():
            if name not in _ALLOWED_FIELDS:
                raise ValueError(f"Недопустимое поле: {name}")
            sets.append(f"{name} = ?")
            params.append(int(value) if isinstance(value, bool) else value)
        if not sets:
            return
        params.append(chat_id)
        await self._conn.execute(
            f"UPDATE chats SET {', '.join(sets)} WHERE chat_id = ?", params
        )
        await self._conn.commit()

    # --- состояние (сводки, дедупликация) ------------------------------------

    async def get_state(self, key: str) -> str | None:
        async with self._conn.execute(
            "SELECT value FROM state WHERE key = ?", (key,)
        ) as cur:
            row = await cur.fetchone()
        return row["value"] if row else None

    async def set_state(self, key: str, value: str) -> None:
        await self._conn.execute(
            "INSERT INTO state(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        await self._conn.commit()
