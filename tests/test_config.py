from __future__ import annotations

import pytest

from app.config import AppConfig


def test_config_parses_user_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "123, 456")
    monkeypatch.setenv("ADMIN_TELEGRAM_USER_IDS", "123")

    config = AppConfig.load()

    assert config.allowed_user_ids == frozenset({123, 456})
    assert config.admin_user_ids == frozenset({123})
    assert config.daily_image_limit == 5
    assert config.daily_user_budget_microusd == 500_000
    assert config.weekly_global_budget_microusd == 4_500_000


def test_config_rejects_zero_daily_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DAILY_IMAGE_LIMIT", "0")

    with pytest.raises(ValueError, match="больше нуля"):
        AppConfig.load()


def test_config_rejects_zero_daily_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DAILY_USER_BUDGET_USD", "0")

    with pytest.raises(ValueError, match="DAILY_USER_BUDGET_USD"):
        AppConfig.load()
