from __future__ import annotations

import asyncio

import pytest

from app.database import Database


@pytest.mark.asyncio
async def test_concurrent_reservations_respect_limit(tmp_path) -> None:
    database = Database(tmp_path / "test.sqlite3")
    await database.initialize()
    await database.upsert_user(101, "employee", "Сотрудник")

    results = await asyncio.gather(
        *[database.reserve_image(101, "2026-10-01", 5) for _ in range(6)]
    )

    assert sum(1 for allowed, _ in results if allowed) == 5
    assert await database.get_image_usage(101, "2026-10-01") == 5


@pytest.mark.asyncio
async def test_release_returns_reserved_image(tmp_path) -> None:
    database = Database(tmp_path / "test.sqlite3")
    await database.initialize()
    await database.upsert_user(202, None, "Илья")

    allowed, used = await database.reserve_image(202, "2026-10-01", 5)
    await database.release_image(202, "2026-10-01")

    assert allowed is True
    assert used == 1
    assert await database.get_image_usage(202, "2026-10-01") == 0


@pytest.mark.asyncio
async def test_usage_is_separate_for_each_date(tmp_path) -> None:
    database = Database(tmp_path / "test.sqlite3")
    await database.initialize()
    await database.upsert_user(303, None, "Илья")

    await database.reserve_image(303, "2026-10-01", 5)

    assert await database.get_image_usage(303, "2026-10-01") == 1
    assert await database.get_image_usage(303, "2026-10-02") == 0
