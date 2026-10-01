from __future__ import annotations

import io
import logging
from datetime import UTC, datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app.config import AppConfig
from app.database import Database
from app.openai_service import (
    IMAGE_RESERVATION_MICROUSD,
    TEXT_RESERVATION_MICROUSD,
    OpenAIService,
)
from app.utils import split_telegram_text

LOGGER = logging.getLogger(__name__)
MODE_NAMES = {
    "general": "Обычная задача",
    "semantics": "Семантика",
    "ads": "Объявления",
    "image": "Изображение",
}
IMAGE_SIZES = {
    "square": ("1:1", "1024x1024"),
    "portrait": ("вертикальное", "1024x1536"),
    "landscape": ("горизонтальное", "1536x1024"),
}


def menu_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Обычная задача", callback_data="mode:general"),
                InlineKeyboardButton("Семантика", callback_data="mode:semantics"),
            ],
            [
                InlineKeyboardButton("Объявления", callback_data="mode:ads"),
                InlineKeyboardButton("Изображение", callback_data="mode:image"),
            ],
            [InlineKeyboardButton("Мой лимит", callback_data="show:limit")],
        ]
    )


def image_size_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("1:1", callback_data="size:square"),
                InlineKeyboardButton("Вертикальное", callback_data="size:portrait"),
                InlineKeyboardButton("Горизонтальное", callback_data="size:landscape"),
            ],
            [InlineKeyboardButton("Назад в меню", callback_data="mode:general")],
        ]
    )


class BotHandlers:
    def __init__(self, config: AppConfig, database: Database, openai: OpenAIService) -> None:
        self.config = config
        self.database = database
        self.openai = openai

    def register(self, application) -> None:
        application.add_handler(CommandHandler("start", self.start))
        application.add_handler(CommandHandler("menu", self.start))
        application.add_handler(CommandHandler("whoami", self.whoami))
        application.add_handler(CommandHandler("limit", self.limit))
        application.add_handler(CommandHandler("stats", self.stats))
        application.add_handler(CallbackQueryHandler(self.callback))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.text))
        application.add_error_handler(self.error)

    async def _remember_user(self, update: Update) -> int | None:
        user = update.effective_user
        if user is None:
            return None
        await self.database.upsert_user(user.id, user.username, user.first_name)
        return user.id

    def _allowed(self, user_id: int) -> bool:
        return user_id in self.config.allowed_user_ids

    async def _require_access(self, update: Update) -> int | None:
        user_id = await self._remember_user(update)
        if user_id is None:
            return None
        if self._allowed(user_id):
            return user_id
        if update.effective_message:
            await update.effective_message.reply_text(
                "Доступ пока не разрешён. Передайте администратору ваш Telegram ID: "
                f"{user_id}"
            )
        return None

    def _today(self) -> str:
        return datetime.now(self.config.timezone).date().isoformat()

    def _budget_periods(self) -> tuple[str, str, str]:
        now = datetime.now(UTC)
        local_date = now.astimezone(self.config.timezone).date().isoformat()
        weekly_cutoff = (now - timedelta(days=7)).isoformat()
        return local_date, weekly_cutoff, now.isoformat()

    @staticmethod
    def _format_usd(cost_microusd: int) -> str:
        return f"${cost_microusd / 1_000_000:.2f}".replace(".", ",")

    async def _check_budget(self, user_id: int, reservation_microusd: int):
        usage_date, weekly_cutoff, _ = self._budget_periods()
        usage = await self.database.get_budget_usage(user_id, usage_date, weekly_cutoff)
        daily_allowed = (
            usage.user_daily_microusd + reservation_microusd
            <= self.config.daily_user_budget_microusd
        )
        weekly_allowed = (
            usage.global_weekly_microusd + reservation_microusd
            <= self.config.weekly_global_budget_microusd
        )
        return daily_allowed, weekly_allowed, usage

    async def _record_cost(self, user_id: int, category: str, cost_microusd: int) -> None:
        usage_date, _, created_at = self._budget_periods()
        await self.database.record_cost(
            user_id, usage_date, created_at, cost_microusd, category
        )

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = await self._require_access(update)
        if user_id is None:
            return
        context.user_data.setdefault("mode", "general")
        await update.effective_message.reply_text(
            "Выберите тип задачи. После выбора отправьте задание обычным сообщением.",
            reply_markup=menu_markup(),
        )

    async def whoami(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = await self._remember_user(update)
        if user_id is not None:
            await update.effective_message.reply_text(f"Ваш Telegram ID: {user_id}")

    async def limit(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = await self._require_access(update)
        if user_id is None:
            return
        await self._send_limit(update.effective_message, user_id)

    async def _send_limit(self, message, user_id: int) -> None:
        usage_date, weekly_cutoff, _ = self._budget_periods()
        images_used = await self.database.get_image_usage(user_id, usage_date)
        usage = await self.database.get_budget_usage(user_id, usage_date, weekly_cutoff)
        images_remaining = max(self.config.daily_image_limit - images_used, 0)
        daily_remaining = max(
            self.config.daily_user_budget_microusd - usage.user_daily_microusd, 0
        )
        weekly_remaining = max(
            self.config.weekly_global_budget_microusd - usage.global_weekly_microusd, 0
        )
        await message.reply_text(
            f"Ваш расход сегодня: {self._format_usd(usage.user_daily_microusd)} из "
            f"{self._format_usd(self.config.daily_user_budget_microusd)}. "
            f"Осталось: {self._format_usd(daily_remaining)}.\n"
            f"Общий расход за 7 дней: "
            f"{self._format_usd(usage.global_weekly_microusd)} из "
            f"{self._format_usd(self.config.weekly_global_budget_microusd)}. "
            f"Осталось: {self._format_usd(weekly_remaining)}.\n"
            f"Изображения сегодня: {images_used} из {self.config.daily_image_limit}. "
            f"Осталось: {images_remaining}. Дневной лимит сбрасывается в 00:00 по Москве."
        )

    async def stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = await self._require_access(update)
        if user_id is None:
            return
        if user_id not in self.config.admin_user_ids:
            await update.effective_message.reply_text("Команда доступна только администратору.")
            return
        rows = await self.database.daily_usage(self._today())
        if not rows:
            await update.effective_message.reply_text("Пользователей пока нет.")
            return
        _, weekly_cutoff, _ = self._budget_periods()
        weekly_usage = await self.database.get_budget_usage(user_id, self._today(), weekly_cutoff)
        lines = [
            f"Использование за {self._today()}:",
            (
                f"Общий расход за 7 дней: "
                f"{self._format_usd(weekly_usage.global_weekly_microusd)} из "
                f"{self._format_usd(self.config.weekly_global_budget_microusd)}."
            ),
        ]
        for row in rows:
            name = f"@{row.username}" if row.username else (row.first_name or str(row.user_id))
            lines.append(
                f"{name} ({row.user_id}): {self._format_usd(row.cost_microusd)}, "
                f"изображений: {row.image_count}"
            )
        await update.effective_message.reply_text("\n".join(lines))

    async def callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if query is None:
            return
        await query.answer()
        user_id = await self._require_access(update)
        if user_id is None:
            return
        data = query.data or ""
        if data == "show:limit":
            await self._send_limit(query.message, user_id)
            return
        if data.startswith("mode:"):
            mode = data.removeprefix("mode:")
            if mode not in MODE_NAMES:
                return
            context.user_data["mode"] = mode
            if mode == "image":
                context.user_data.setdefault("image_size", "1024x1024")
                await query.edit_message_text(
                    "Режим: Изображение. Выберите формат, затем отправьте описание. "
                    "За один запрос создаётся одно изображение.",
                    reply_markup=image_size_markup(),
                )
                return
            await query.edit_message_text(
                f"Режим: {MODE_NAMES[mode]}.\n\nОтправьте задачу одним сообщением.",
                reply_markup=menu_markup(),
            )
            return
        if data.startswith("size:"):
            size_name = data.removeprefix("size:")
            if size_name not in IMAGE_SIZES:
                return
            label, api_size = IMAGE_SIZES[size_name]
            context.user_data["mode"] = "image"
            context.user_data["image_size"] = api_size
            await query.edit_message_text(
                f"Формат: {label}. Теперь отправьте описание изображения.",
                reply_markup=image_size_markup(),
            )

    async def text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = await self._require_access(update)
        message = update.effective_message
        if user_id is None or message is None or not message.text:
            return
        prompt = message.text.strip()
        if len(prompt) > self.config.max_prompt_chars:
            await message.reply_text(
                f"Сообщение слишком длинное. Максимум: {self.config.max_prompt_chars} символов."
            )
            return
        mode = context.user_data.get("mode", "general")
        if mode == "image":
            image_size = context.user_data.get("image_size", "1024x1024")
            await self._handle_image(message, user_id, prompt, image_size)
        else:
            await self._handle_text(message, user_id, mode, prompt)

    async def _handle_text(self, message, user_id: int, mode: str, prompt: str) -> None:
        daily_allowed, weekly_allowed, _ = await self._check_budget(
            user_id, TEXT_RESERVATION_MICROUSD
        )
        if not daily_allowed:
            await message.reply_text(
                "Ваш дневной лимит расходов исчерпан. Новый лимит будет доступен "
                "завтра в 00:00 по Москве."
            )
            return
        if not weekly_allowed:
            await message.reply_text(
                "Общий лимит расходов за последние 7 дней исчерпан. "
                "Доступ восстановится автоматически по мере выхода старых расходов "
                "из семидневного периода."
            )
            return
        await message.chat.send_action(ChatAction.TYPING)
        try:
            result = await self.openai.generate_text(user_id, mode, prompt)
            await self._record_cost(user_id, "text", result.cost_microusd)
            await self.database.record_event(user_id, mode, "success", prompt)
            for part in split_telegram_text(result.value):
                await message.reply_text(part)
        except Exception as exc:
            LOGGER.exception("Ошибка текстовой генерации для пользователя %s", user_id)
            await self.database.record_event(user_id, mode, "error", prompt, str(exc))
            await message.reply_text(
                "Не удалось выполнить задачу. Ошибка записана в журнал. Попробуйте позже."
            )

    async def _handle_image(self, message, user_id: int, prompt: str, size: str) -> None:
        daily_allowed, weekly_allowed, _ = await self._check_budget(
            user_id, IMAGE_RESERVATION_MICROUSD
        )
        if not daily_allowed:
            await message.reply_text(
                "Ваш дневной лимит расходов исчерпан. Новый лимит будет доступен "
                "завтра в 00:00 по Москве."
            )
            return
        if not weekly_allowed:
            await message.reply_text(
                "Общий лимит расходов за последние 7 дней исчерпан. "
                "Доступ восстановится автоматически по мере выхода старых расходов "
                "из семидневного периода."
            )
            return
        usage_date = self._today()
        reserved, used = await self.database.reserve_image(
            user_id, usage_date, self.config.daily_image_limit
        )
        if not reserved:
            await message.reply_text(
                "Дневной лимит изображений исчерпан. Новый лимит будет доступен "
                "завтра в 00:00 по Москве."
            )
            return
        await message.chat.send_action(ChatAction.UPLOAD_PHOTO)
        try:
            result = await self.openai.generate_image(prompt, size)
            await self._record_cost(user_id, "image", result.cost_microusd)
            image_file = io.BytesIO(result.value)
            image_file.name = "generated.png"
            remaining = self.config.daily_image_limit - used
            await message.reply_photo(
                photo=image_file,
                caption=f"Готово. Осталось изображений сегодня: {remaining}.",
            )
            await self.database.record_event(user_id, "image", "success", prompt)
        except Exception as exc:
            await self.database.release_image(user_id, usage_date)
            LOGGER.exception("Ошибка генерации изображения для пользователя %s", user_id)
            await self.database.record_event(user_id, "image", "error", prompt, str(exc))
            await message.reply_text(
                "Изображение не создано. Лимит не списан. Ошибка записана в журнал."
            )

    async def error(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        LOGGER.exception("Необработанная ошибка Telegram-бота", exc_info=context.error)
