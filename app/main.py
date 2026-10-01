from __future__ import annotations

import logging

from telegram import BotCommand, Update
from telegram.ext import Application, ApplicationBuilder

from app.bot import BotHandlers
from app.config import AppConfig
from app.database import Database
from app.openai_service import OpenAIService


def build_application(config: AppConfig) -> Application:
    database = Database(config.database_path)
    openai_service = OpenAIService(config)
    handlers = BotHandlers(config, database, openai_service)

    async def post_init(application: Application) -> None:
        await database.initialize()
        await application.bot.set_my_commands(
            [
                BotCommand("menu", "Открыть меню"),
                BotCommand("limit", "Показать лимит изображений"),
                BotCommand("whoami", "Показать Telegram ID"),
                BotCommand("stats", "Статистика администратора"),
            ]
        )

    async def post_shutdown(application: Application) -> None:
        await openai_service.close()

    application = (
        ApplicationBuilder()
        .token(config.telegram_bot_token)
        .concurrent_updates(False)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    handlers.register(application)
    return application


def main() -> None:
    try:
        config = AppConfig.load()
        config.validate_runtime_secrets()
    except (ValueError, TypeError) as exc:
        raise SystemExit(f"Ошибка конфигурации: {exc}") from exc

    logging.basicConfig(
        level=getattr(logging, config.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    application = build_application(config)
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
