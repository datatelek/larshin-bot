"""
Telegram-бот: «ГДЕ ВАША ТОЧКА РОСТА В КАРЬЕРЕ И ДОХОДЕ»
Автор сценария: Анна Ларшина (@larshinaann)

Логика:
1. Пользователь проходит 12 шагов (приветствие, подписка, телефон, 7 вопросов, финал)
2. По завершении бот автоматически отправляет Анне сообщение с именем, телефоном и 7 ответами
3. Пользователю показывается финальное сообщение с кнопкой написать Анне
"""

import asyncio
import logging
import os
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── Конфигурация ──────────────────────────────────────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ANNA_CHAT_ID = os.environ.get("ANNA_CHAT_ID", "")   # chat_id Анны (числовой)
CHANNEL_USERNAME = "@larshinaann_channel"            # канал для проверки подписки (можно изменить)

# ─── Состояния FSM ─────────────────────────────────────────────────────────────
class Survey(StatesGroup):
    waiting_subscription = State()
    waiting_phone        = State()
    q1 = State()
    q2 = State()
    q3 = State()
    q4 = State()
    q5 = State()
    q6 = State()
    q7 = State()

# ─── Тексты вопросов ───────────────────────────────────────────────────────────
QUESTIONS = [
    {
        "state": Survey.q1,
        "text": (
            "Вопрос 1 из 7\n\n"
            "Как бы вы описали свою текущую профессиональную ситуацию?\n\n"
            "A — Я только начинаю карьеру и ищу своё направление\n"
            "B — У меня есть опыт, но я застрял(а) на одном месте\n"
            "C — Я активно развиваюсь, но доход не растёт\n"
            "D — Я состоявшийся специалист, хочу выйти на новый уровень"
        ),
    },
    {
        "state": Survey.q2,
        "text": (
            "Вопрос 2 из 7\n\n"
            "Что происходит с вашим доходом прямо сейчас?\n\n"
            "A — Доход нестабильный, не хватает на всё нужное\n"
            "B — Доход стабильный, но не растёт уже больше года\n"
            "C — Доход растёт, но медленнее, чем хотелось бы\n"
            "D — Доход устраивает, хочу его масштабировать"
        ),
    },
    {
        "state": Survey.q3,
        "text": (
            "Вопрос 3 из 7\n\n"
            "Какая ваша самая сильная сторона в профессии?\n\n"
            "A — Глубокие экспертные знания в своей области\n"
            "B — Умение выстраивать отношения и коммуникацию\n"
            "C — Системное мышление и умение управлять процессами\n"
            "D — Креативность и умение находить нестандартные решения"
        ),
    },
    {
        "state": Survey.q4,
        "text": (
            "Вопрос 4 из 7\n\n"
            "Как вы чаще всего проявляетесь в работе?\n\n"
            "A — Работаю в одиночку, глубоко погружаясь в задачу\n"
            "B — Работаю в команде, беру на себя роль лидера\n"
            "C — Работаю с клиентами, помогаю решать их задачи\n"
            "D — Создаю продукты, системы или контент для широкой аудитории"
        ),
    },
    {
        "state": Survey.q5,
        "text": (
            "Вопрос 5 из 7\n\n"
            "Что, на ваш взгляд, больше всего тормозит ваш рост?\n\n"
            "A — Не понимаю, куда двигаться дальше\n"
            "B — Знаю куда, но не хватает уверенности и действий\n"
            "C — Есть план, но нет времени или ресурсов\n"
            "D — Внешние обстоятельства: рынок, окружение, ситуация"
        ),
    },
    {
        "state": Survey.q6,
        "text": (
            "Вопрос 6 из 7\n\n"
            "Каким вы видите свой карьерный план на ближайший год?\n\n"
            "A — Сменить сферу или профессию\n"
            "B — Вырасти внутри своей компании или ниши\n"
            "C — Запустить своё дело или выйти на фриланс\n"
            "D — Масштабировать уже существующий бизнес или проект"
        ),
    },
    {
        "state": Survey.q7,
        "text": (
            "Вопрос 7 из 7\n\n"
            "Что для вас самое важное в работе и карьере?\n\n"
            "A — Финансовая стабильность и уверенность в завтрашнем дне\n"
            "B — Признание, статус и влияние\n"
            "C — Свобода и гибкость в жизни\n"
            "D — Смысл, реализация потенциала и вклад в что-то большее"
        ),
    },
]

def make_abcd_keyboard(prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="A", callback_data=f"{prefix}:A"),
            InlineKeyboardButton(text="B", callback_data=f"{prefix}:B"),
        ],
        [
            InlineKeyboardButton(text="C", callback_data=f"{prefix}:C"),
            InlineKeyboardButton(text="D", callback_data=f"{prefix}:D"),
        ],
    ])

def phone_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Поделиться номером", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )

# ─── Роутер ────────────────────────────────────────────────────────────────────
router = Router()

# ── /start ─────────────────────────────────────────────────────────────────────
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, bot: Bot):
    user = message.from_user
    # Логируем chat_id каждого кто пишет /start — для отладки
    logger.info(f"/start from: chat_id={message.chat.id} username=@{user.username if user else '?'} name={user.first_name if user else '?'}")

    # Если Анна пишет /start — сообщаем ей chat_id (проверяем по username И по ANNA_CHAT_ID)
    is_anna = (
        user and user.username and user.username.lower() in ("larshinaann", "larshinaanna")
    ) or (
        ANNA_CHAT_ID and str(message.chat.id) == str(ANNA_CHAT_ID)
    )

    if is_anna:
        await state.clear()
        await message.answer(
            f"Анна, ваш chat\_id: `{message.chat.id}`\n\n"
            "Бот будет автоматически присылать вам результаты тестов.",
            parse_mode="Markdown"
        )
        return

    user_name = user.first_name if user else "друг"
    await state.clear()
    await state.update_data(user_name=user_name, user_id=message.from_user.id if message.from_user else None)

    await message.answer(
        f"Привет, {user_name}! 👋\n\n"
        "Я — бот Анны Ларшиной, карьерного стратега и ментора.\n\n"
        "Здесь вы можете пройти бесплатный тест и узнать, "
        "где находится ваша точка роста в карьере и доходе.\n\n"
        "Готовы начать?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Старт", callback_data="start_survey")]
        ])
    )

# ── Старт → проверка подписки ──────────────────────────────────────────────────
@router.callback_query(F.data == "start_survey")
async def cb_start_survey(call: CallbackQuery, state: FSMContext):
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer(
        "Прежде чем начать — подпишитесь на канал Анны, "
        "там она делится карьерными стратегиями и разборами:\n\n"
        "👉 https://t.me/larshinaann\n\n"
        "После того как подпишетесь, нажмите кнопку ниже:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Подписался(-ась)", callback_data="subscribed")]
        ])
    )
    await state.set_state(Survey.waiting_subscription)

# ── Подтверждение подписки → запрос телефона ──────────────────────────────────
@router.callback_query(F.data == "subscribed", Survey.waiting_subscription)
async def cb_subscribed(call: CallbackQuery, state: FSMContext):
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer(
        "Отлично! 🎉\n\n"
        "Для связи с вами оставьте, пожалуйста, номер телефона:",
        reply_markup=phone_keyboard()
    )
    await state.set_state(Survey.waiting_phone)

# ── Получение телефона → вводная + первый вопрос ──────────────────────────────
@router.message(Survey.waiting_phone, F.contact)
async def got_phone(message: Message, state: FSMContext):
    phone = message.contact.phone_number if message.contact else "не указан"
    await state.update_data(phone=phone)
    await message.answer(
        "Спасибо! Номер сохранён ✅",
        reply_markup=ReplyKeyboardRemove()
    )
    await message.answer(
        "ТЕСТ: ГДЕ ВАША ТОЧКА РОСТА В КАРЬЕРЕ И ДОХОДЕ\n\n"
        "Ответьте на 7 коротких вопросов. Это займёт буквально 2 минуты.\n\n"
        "По итогам теста вы поймёте:\n"
        "▪️ на каком этапе карьерного роста вы сейчас находитесь\n"
        "▪️ что именно тормозит рост вашего дохода\n"
        "▪️ где находится ваша точка роста\n"
        "▪️ какой следующий шаг поможет вам двигаться дальше\n\n"
        "В конце вы получите краткий разбор вашей ситуации от Анны.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="▶️ Начать тест", callback_data="begin_test")]
        ])
    )

@router.message(Survey.waiting_phone)
async def phone_not_shared(message: Message):
    await message.answer(
        "Пожалуйста, воспользуйтесь кнопкой «📱 Поделиться номером» ниже.",
        reply_markup=phone_keyboard()
    )

# ── Начало теста → Q1 ──────────────────────────────────────────────────────────
@router.callback_query(F.data == "begin_test")
async def begin_test(call: CallbackQuery, state: FSMContext):
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer(
        QUESTIONS[0]["text"],
        reply_markup=make_abcd_keyboard("q1")
    )
    await state.set_state(Survey.q1)

# ── Обработчики ответов Q1–Q6 (переход к следующему вопросу) ──────────────────
async def handle_answer(call: CallbackQuery, state: FSMContext, q_key: str, next_q_index: int):
    answer = call.data.split(":")[1]
    await state.update_data(**{q_key: answer})
    await call.message.edit_reply_markup(reply_markup=None)
    # Показываем выбранный ответ
    await call.message.answer(f"Ваш ответ: {answer} ✓")

    q = QUESTIONS[next_q_index]
    await call.message.answer(
        q["text"],
        reply_markup=make_abcd_keyboard(f"q{next_q_index + 1}")
    )
    await state.set_state(q["state"])

@router.callback_query(F.data.startswith("q1:"), Survey.q1)
async def ans_q1(call: CallbackQuery, state: FSMContext):
    await handle_answer(call, state, "q1", 1)

@router.callback_query(F.data.startswith("q2:"), Survey.q2)
async def ans_q2(call: CallbackQuery, state: FSMContext):
    await handle_answer(call, state, "q2", 2)

@router.callback_query(F.data.startswith("q3:"), Survey.q3)
async def ans_q3(call: CallbackQuery, state: FSMContext):
    await handle_answer(call, state, "q3", 3)

@router.callback_query(F.data.startswith("q4:"), Survey.q4)
async def ans_q4(call: CallbackQuery, state: FSMContext):
    await handle_answer(call, state, "q4", 4)

@router.callback_query(F.data.startswith("q5:"), Survey.q5)
async def ans_q5(call: CallbackQuery, state: FSMContext):
    await handle_answer(call, state, "q5", 5)

@router.callback_query(F.data.startswith("q6:"), Survey.q6)
async def ans_q6(call: CallbackQuery, state: FSMContext):
    await handle_answer(call, state, "q6", 6)

# ── Последний вопрос Q7 → финал + отправка Анне ───────────────────────────────
@router.callback_query(F.data.startswith("q7:"), Survey.q7)
async def ans_q7(call: CallbackQuery, state: FSMContext, bot: Bot):
    answer = call.data.split(":")[1]
    await state.update_data(q7=answer)
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer(f"Ваш ответ: {answer} ✓")

    data = await state.get_data()
    await state.clear()

    user_name = data.get("user_name", "Неизвестно")
    phone     = data.get("phone", "не указан")
    q1 = data.get("q1", "—")
    q2 = data.get("q2", "—")
    q3 = data.get("q3", "—")
    q4 = data.get("q4", "—")
    q5 = data.get("q5", "—")
    q6 = data.get("q6", "—")
    q7 = answer

    # ── Сообщение пользователю ────────────────────────────────────────────────
    await call.message.answer(
        "Тест пройден! 🎉\n\n"
        "Анна уже получила ваши результаты и скоро подготовит персональный разбор.\n\n"
        "Если хотите написать ей напрямую — нажмите кнопку ниже:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="💬 Написать Анне",
                url="https://t.me/larshinaann"
            )]
        ])
    )

    # ── Автоматическое сообщение Анне ─────────────────────────────────────────
    anna_chat_id = ANNA_CHAT_ID

    # Пробуем прочитать chat_id из файла (если Анна писала боту)
    if not anna_chat_id:
        try:
            with open("anna_chat_id.txt") as f:
                anna_chat_id = f.read().strip()
        except FileNotFoundError:
            pass

    if anna_chat_id:
        report = (
            f"📋 Новый результат теста\n"
            f"{'─' * 30}\n"
            f"👤 Имя: {user_name}\n"
            f"📞 Телефон: {phone}\n"
            f"{'─' * 30}\n"
            f"Ответы на тест:\n\n"
            f"В1 (профессиональная ситуация): {q1}\n"
            f"В2 (доход): {q2}\n"
            f"В3 (сильная сторона): {q3}\n"
            f"В4 (проявление в работе): {q4}\n"
            f"В5 (что тормозит рост): {q5}\n"
            f"В6 (план карьеры): {q6}\n"
            f"В7 (важное в карьере): {q7}\n"
            f"{'─' * 30}\n"
            f"Архетип можно определить по совокупности ответов ⬆️"
        )
        try:
            await bot.send_message(chat_id=int(anna_chat_id), text=report)
            logger.info(f"Results sent to Anna (chat_id={anna_chat_id})")
        except Exception as e:
            logger.error(f"Failed to send results to Anna: {e}")
    else:
        logger.warning("ANNA_CHAT_ID not set — results not sent!")

# ─── Запуск ────────────────────────────────────────────────────────────────────
async def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN environment variable is not set!")

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    logger.info("Bot started (polling mode)")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
