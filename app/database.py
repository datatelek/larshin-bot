from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class UserDailyUsage:
    user_id: int
    username: str | None
    first_name: str | None
    image_count: int
    cost_microusd: int


@dataclass(frozen=True, slots=True)
class BudgetUsage:
    user_daily_microusd: int
    global_weekly_microusd: int


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(self._initialize_sync)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize_sync(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    telegram_user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS image_usage (
                    telegram_user_id INTEGER NOT NULL,
                    usage_date TEXT NOT NULL,
                    image_count INTEGER NOT NULL DEFAULT 0 CHECK (image_count >= 0),
                    PRIMARY KEY (telegram_user_id, usage_date),
                    FOREIGN KEY (telegram_user_id) REFERENCES users(telegram_user_id)
                );

                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_user_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    status TEXT NOT NULL,
                    request_excerpt TEXT,
                    error_text TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_audit_log_user_created
                    ON audit_log(telegram_user_id, created_at);

                CREATE TABLE IF NOT EXISTS api_cost_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_user_id INTEGER NOT NULL,
                    usage_date TEXT NOT NULL,
                    cost_microusd INTEGER NOT NULL CHECK (cost_microusd >= 0),
                    category TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (telegram_user_id) REFERENCES users(telegram_user_id)
                );

                CREATE INDEX IF NOT EXISTS idx_api_cost_user_date
                    ON api_cost_usage(telegram_user_id, usage_date);

                CREATE INDEX IF NOT EXISTS idx_api_cost_created
                    ON api_cost_usage(created_at);
                """
            )

    async def upsert_user(
        self, user_id: int, username: str | None, first_name: str | None
    ) -> None:
        def operation() -> None:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO users (telegram_user_id, username, first_name)
                    VALUES (?, ?, ?)
                    ON CONFLICT(telegram_user_id) DO UPDATE SET
                        username = excluded.username,
                        first_name = excluded.first_name,
                        last_seen_at = CURRENT_TIMESTAMP
                    """,
                    (user_id, username, first_name),
                )

        async with self._lock:
            await asyncio.to_thread(operation)

    async def reserve_image(self, user_id: int, usage_date: str, limit: int) -> tuple[bool, int]:
        def operation() -> tuple[bool, int]:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    """
                    SELECT image_count FROM image_usage
                    WHERE telegram_user_id = ? AND usage_date = ?
                    """,
                    (user_id, usage_date),
                ).fetchone()
                current = int(row["image_count"]) if row else 0
                if current >= limit:
                    connection.rollback()
                    return False, current
                new_count = current + 1
                connection.execute(
                    """
                    INSERT INTO image_usage (telegram_user_id, usage_date, image_count)
                    VALUES (?, ?, ?)
                    ON CONFLICT(telegram_user_id, usage_date) DO UPDATE SET
                        image_count = excluded.image_count
                    """,
                    (user_id, usage_date, new_count),
                )
                connection.commit()
                return True, new_count
            finally:
                connection.close()

        async with self._lock:
            return await asyncio.to_thread(operation)

    async def release_image(self, user_id: int, usage_date: str) -> None:
        def operation() -> None:
            with self._connect() as connection:
                connection.execute(
                    """
                    UPDATE image_usage
                    SET image_count = MAX(image_count - 1, 0)
                    WHERE telegram_user_id = ? AND usage_date = ?
                    """,
                    (user_id, usage_date),
                )

        async with self._lock:
            await asyncio.to_thread(operation)

    async def get_image_usage(self, user_id: int, usage_date: str) -> int:
        def operation() -> int:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT image_count FROM image_usage
                    WHERE telegram_user_id = ? AND usage_date = ?
                    """,
                    (user_id, usage_date),
                ).fetchone()
                return int(row["image_count"]) if row else 0

        async with self._lock:
            return await asyncio.to_thread(operation)

    async def record_event(
        self,
        user_id: int,
        action: str,
        status: str,
        request_excerpt: str = "",
        error_text: str = "",
    ) -> None:
        def operation() -> None:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO audit_log
                        (telegram_user_id, action, status, request_excerpt, error_text)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (user_id, action, status, request_excerpt[:500], error_text[:1000]),
                )

        async with self._lock:
            await asyncio.to_thread(operation)

    async def record_cost(
        self,
        user_id: int,
        usage_date: str,
        created_at: str,
        cost_microusd: int,
        category: str,
    ) -> None:
        if cost_microusd < 0:
            raise ValueError("Стоимость запроса не может быть отрицательной")

        def operation() -> None:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO api_cost_usage
                        (telegram_user_id, usage_date, cost_microusd, category, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (user_id, usage_date, cost_microusd, category, created_at),
                )

        async with self._lock:
            await asyncio.to_thread(operation)

    async def get_budget_usage(
        self, user_id: int, usage_date: str, weekly_cutoff: str
    ) -> BudgetUsage:
        def operation() -> BudgetUsage:
            with self._connect() as connection:
                daily_row = connection.execute(
                    """
                    SELECT COALESCE(SUM(cost_microusd), 0) AS total
                    FROM api_cost_usage
                    WHERE telegram_user_id = ? AND usage_date = ?
                    """,
                    (user_id, usage_date),
                ).fetchone()
                weekly_row = connection.execute(
                    """
                    SELECT COALESCE(SUM(cost_microusd), 0) AS total
                    FROM api_cost_usage
                    WHERE created_at >= ?
                    """,
                    (weekly_cutoff,),
                ).fetchone()
                return BudgetUsage(
                    user_daily_microusd=int(daily_row["total"]),
                    global_weekly_microusd=int(weekly_row["total"]),
                )

        async with self._lock:
            return await asyncio.to_thread(operation)

    async def daily_usage(self, usage_date: str) -> list[UserDailyUsage]:
        def operation() -> list[UserDailyUsage]:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT
                        u.telegram_user_id,
                        u.username,
                        u.first_name,
                        COALESCE(i.image_count, 0) AS image_count,
                        COALESCE(c.cost_microusd, 0) AS cost_microusd
                    FROM users AS u
                    LEFT JOIN image_usage AS i
                        ON i.telegram_user_id = u.telegram_user_id
                        AND i.usage_date = ?
                    LEFT JOIN (
                        SELECT telegram_user_id, SUM(cost_microusd) AS cost_microusd
                        FROM api_cost_usage
                        WHERE usage_date = ?
                        GROUP BY telegram_user_id
                    ) AS c ON c.telegram_user_id = u.telegram_user_id
                    ORDER BY cost_microusd DESC, image_count DESC, u.telegram_user_id
                    """,
                    (usage_date, usage_date),
                ).fetchall()
                return [
                    UserDailyUsage(
                        user_id=int(row["telegram_user_id"]),
                        username=row["username"],
                        first_name=row["first_name"],
                        image_count=int(row["image_count"]),
                        cost_microusd=int(row["cost_microusd"]),
                    )
                    for row in rows
                ]

        async with self._lock:
            return await asyncio.to_thread(operation)
