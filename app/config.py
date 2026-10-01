from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv


def _parse_ids(raw_value: str) -> frozenset[int]:
    values: set[int] = set()
    for item in raw_value.split(","):
        cleaned = item.strip()
        if cleaned:
            values.add(int(cleaned))
    return frozenset(values)


def _parse_usd_micros(variable_name: str, default: str) -> int:
    raw_value = os.getenv(variable_name, default).strip()
    try:
        value = Decimal(raw_value)
    except InvalidOperation as exc:
        raise ValueError(f"{variable_name} должен быть числом") from exc
    if value <= 0:
        raise ValueError(f"{variable_name} должен быть больше нуля")
    return int(value * 1_000_000)


@dataclass(frozen=True, slots=True)
class AppConfig:
    telegram_bot_token: str
    openai_api_key: str
    allowed_user_ids: frozenset[int]
    admin_user_ids: frozenset[int]
    text_model: str
    image_model: str
    image_quality: str
    daily_image_limit: int
    daily_user_budget_microusd: int
    weekly_global_budget_microusd: int
    timezone: ZoneInfo
    database_path: Path
    log_level: str
    max_prompt_chars: int
    max_output_tokens: int

    @classmethod
    def load(cls) -> AppConfig:
        load_dotenv()
        timezone_name = os.getenv("APP_TIMEZONE", "Europe/Moscow")
        try:
            timezone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"Неизвестный часовой пояс: {timezone_name}") from exc

        daily_limit = int(os.getenv("DAILY_IMAGE_LIMIT", "5"))
        if daily_limit < 1:
            raise ValueError("DAILY_IMAGE_LIMIT должен быть больше нуля")

        max_prompt_chars = int(os.getenv("MAX_PROMPT_CHARS", "12000"))
        max_output_tokens = int(os.getenv("MAX_OUTPUT_TOKENS", "3000"))
        if max_prompt_chars < 1 or max_output_tokens < 1:
            raise ValueError("Ограничения текста должны быть больше нуля")

        image_quality = os.getenv("OPENAI_IMAGE_QUALITY", "low").strip().lower()
        allowed_qualities = {"auto", "low", "medium", "high", "xhigh", "max"}
        if image_quality not in allowed_qualities:
            raise ValueError("Недопустимое значение OPENAI_IMAGE_QUALITY")

        allowed_user_ids = _parse_ids(os.getenv("ALLOWED_TELEGRAM_USER_IDS", ""))
        admin_user_ids = _parse_ids(os.getenv("ADMIN_TELEGRAM_USER_IDS", ""))

        return cls(
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
            openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
            allowed_user_ids=allowed_user_ids | admin_user_ids,
            admin_user_ids=admin_user_ids,
            text_model=os.getenv("OPENAI_TEXT_MODEL", "gpt-5.6-luna").strip(),
            image_model=os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-2.5-flare").strip(),
            image_quality=image_quality,
            daily_image_limit=daily_limit,
            daily_user_budget_microusd=_parse_usd_micros(
                "DAILY_USER_BUDGET_USD", "0.50"
            ),
            weekly_global_budget_microusd=_parse_usd_micros(
                "WEEKLY_GLOBAL_BUDGET_USD", "4.50"
            ),
            timezone=timezone,
            database_path=Path(os.getenv("DATABASE_PATH", "data/bot.sqlite3")),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            max_prompt_chars=max_prompt_chars,
            max_output_tokens=max_output_tokens,
        )

    def validate_runtime_secrets(self) -> None:
        missing: list[str] = []
        if not self.telegram_bot_token:
            missing.append("TELEGRAM_BOT_TOKEN")
        if not self.openai_api_key:
            missing.append("OPENAI_API_KEY")
        if missing:
            raise ValueError("Не заполнены обязательные переменные: " + ", ".join(missing))
