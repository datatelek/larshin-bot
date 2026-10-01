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


@pytest.mark.asyncio
async def test_budget_usage_counts_user_day_and_global_rolling_week(tmp_path) -> None:
    database = Database(tmp_path / "test.sqlite3")
    await database.initialize()
    await database.upsert_user(101, "one", "Первый")
    await database.upsert_user(202, "two", "Второй")

    await database.record_cost(101, "2026-10-01", "2026-10-01T10:00:00+00:00", 120_000, "text")
    await database.record_cost(202, "2026-10-01", "2026-10-01T11:00:00+00:00", 80_000, "image")
    await database.record_cost(101, "2026-09-20", "2026-09-20T10:00:00+00:00", 900_000, "text")

    usage = await database.get_budget_usage(
        101, "2026-10-01", "2026-09-24T12:00:00+00:00"
    )

    assert usage.user_daily_microusd == 120_000
    assert usage.global_weekly_microusd == 200_000

    rows = await database.daily_usage("2026-10-01")
    assert [(row.user_id, row.cost_microusd) for row in rows] == [
        (101, 120_000),
        (202, 80_000),
    ]
