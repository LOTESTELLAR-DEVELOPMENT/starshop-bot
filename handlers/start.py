from aiogram import Router
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
from aiogram.filters import Command
from aiogram import F
from config import load_config
from aiogram.types import CallbackQuery
from aiogram.utils.markdown import hbold
import re
from handlers.profile import get_or_create_user, PromoUserStates
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
import httpx
import time
import asyncio
from aiogram.exceptions import TelegramBadRequest
import random
import string
from datetime import datetime, timedelta, timezone

router = Router()
config = load_config()

# Глобальные переменные для кэширования JWT-токена
_jwt_token_cache = None
_jwt_token_expire = 0

STAR_PACKS = [
    50, 75, 100, 150, 250,
    350, 500, 750, 1000, 1500,
    2500, 5000, 10000, 25000, 35000,
    50000, 100000, 150000, 500000, 1000000
]
PACKS_PER_PAGE = 5
STAR_PRICE = 1.8

FRAGMENT_API_KEY = config.fragment_api_key
FRAGMENT_SHOP_ID = config.fragment_shop_id

# Обновляем тарифы только для премиума (3, 6, 12 мес)
PREMIUM_PLANS = [
    {"name": "3 месяца", "price": 799, "duration": 90},
    {"name": "6 месяцев", "price": 1499, "duration": 180},
    {"name": "12 месяцев", "price": 2499, "duration": 365}
]

def get_channel_link():
    # Если это username (@channel), формируем ссылку https://t.me/username
    if config.news_channel_id.startswith('@'):
        return f"https://t.me/{config.news_channel_id.lstrip('@')}"
    # Если это уже ссылка, возвращаем как есть
    if config.news_channel_id.startswith('https://t.me/'):
        return config.news_channel_id
    # На всякий случай, если id (например, -100...), формируем ссылку
    if re.match(r"^-?\d+$", config.news_channel_id):
        return f"https://t.me/c/{config.news_channel_id.lstrip('-100')}"
    return config.news_channel_id

async def check_subscription(user_id: int, bot) -> bool:
    try:
        member = await bot.get_chat_member(config.news_channel_id, user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception:
        return False

def main_menu_kb(user_id=None):
    buttons = [
        [
            InlineKeyboardButton(text="⭐ Купить звёзды", callback_data="buy_stars"),
            InlineKeyboardButton(text="💎 Купить премиум", callback_data="buy_premium")
        ],
        [
            InlineKeyboardButton(text="👤 Профиль", callback_data="profile"),
            InlineKeyboardButton(text="🆘 Поддержка", url=config.support_url)
        ],
        [
            InlineKeyboardButton(text="📢 Новостной канал", url=config.news_channel_link)
        ]
    ]
    if user_id is not None and str(user_id) == str(config.admin_id):
        buttons.append([
            InlineKeyboardButton(text="⚙️ Админ панель", callback_data="admin_panel")
        ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def admin_panel_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Управления балансами", callback_data="admin_balances")],
        [InlineKeyboardButton(text="Промокоды", callback_data="admin_promos")],
        [InlineKeyboardButton(text="Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="Управления ценами", callback_data="admin_prices")],
        [InlineKeyboardButton(text="Настройки пополнения", callback_data="admin_payment_settings")],
        [InlineKeyboardButton(text="⬅️ В меню", callback_data="main_menu")],
    ])

@router.message(Command("start"))
async def cmd_start(message: Message, bot, db_pool):
    # Обработка реферального аргумента
    invited_by = None
    args = message.text.split()
    if len(args) > 1:
        try:
            invited_by = int(args[1])
        except ValueError:
            invited_by = None
    # Создаём пользователя, если его нет, и сохраняем invited_by
    user = await get_or_create_user(db_pool, message.from_user.id, message.from_user.username, invited_by=invited_by)

    # Главное меню
    await message.answer_photo(config.welcome_image_url, caption=config.welcome_description, reply_markup=main_menu_kb(message.from_user.id), parse_mode="HTML")


@router.callback_query(F.data == "buy_stars")
async def buy_stars_callback(call: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🧑‍💼 Себе", callback_data="buy_stars_self"),
            InlineKeyboardButton(text="🎁 Другому", callback_data="buy_stars_gift")
        ],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ])
    await call.message.answer_photo(
        config.welcome_image_url,
        caption="<b>Купить звёзды</b>\n\nКому вы хотите купить звёзды?",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await call.answer()

class BuyStarsGiftStates(StatesGroup):
    waiting_for_recipient = State()
    waiting_for_gift_amount = State()

class BuyStarsSelfStates(StatesGroup):
    waiting_for_self_amount = State()

class BuyStarsConfirmStates(StatesGroup):
    waiting_for_confirm = State()
    waiting_for_gift_confirm = State()

@router.callback_query(F.data == "buy_stars_self")
async def buy_stars_self_callback(call: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔢 Ввести количество", callback_data="buy_stars_self_amount"),
            InlineKeyboardButton(text="📦 Готовые паки", callback_data="buy_stars_self_packs")
        ],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="buy_stars")]
    ])
    await call.message.edit_caption(
        caption="<b>Покупка звёзд для себя</b>\n\nВыберите способ:",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await call.answer()

@router.callback_query(F.data == "buy_stars_self_amount")
async def buy_stars_self_amount_callback(call: CallbackQuery, state: FSMContext):
    await call.message.edit_caption(
        caption="<b>Введите количество звёзд для покупки (минимум 50):</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="buy_stars_self")]
        ]),
        parse_mode="HTML"
    )
    await state.set_state(BuyStarsSelfStates.waiting_for_self_amount)
    await call.answer()

@router.message(BuyStarsSelfStates.waiting_for_self_amount)
async def process_self_amount(message: Message, state: FSMContext, db_pool):
    try:
        amount = int(message.text)
    except ValueError:
        await message.answer("❗ Введите целое число (минимум 50):")
        return
    if amount < 50:
        await message.answer("❗ Минимальное количество для покупки — 50 звёзд. Попробуйте снова:")
        return
    star_price = await get_star_price(db_pool)
    total = round(amount * star_price, 2)
    data = await state.get_data()
    discount = data.get("active_discount")
    if not discount:
        user = await get_or_create_user(db_pool, message.from_user.id, message.from_user.username)
        discount = user.get("discount")
    if discount:
        discount = float(discount)
        discounted_total = round(total * (1 - discount / 100), 2)
        await state.update_data(amount=amount, total=discounted_total, original_total=total)
        price_text = f"Вы выбрали: <b>{amount}</b> звёзд\n" \
                    f"Итоговая стоимость: <s>{total}₽</s> <b>{discounted_total}₽</b> (скидка {discount}%)\n\nПодтвердить покупку?"
    else:
        await state.update_data(amount=amount, total=total)
        price_text = f"Вы выбрали: <b>{amount}</b> звёзд\nИтоговая стоимость: <b>{total}₽</b>\n\nПодтвердить покупку?"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data="buy_stars_self_confirm")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="buy_stars_self_cancel")]
    ])
    await message.answer(price_text, reply_markup=kb, parse_mode="HTML")
    await state.set_state(BuyStarsConfirmStates.waiting_for_confirm)

async def create_fragment_order(quantity, username, api_key=None, show_sender=False):
    from config import load_config
    config = load_config()
    url = "https://api.fragment-api.com/v1/order/stars/"
    username = username.lstrip("@") if username else ""
    data = {
        "username": username,
        "quantity": quantity,
        "show_sender": False
    }
    jwt_token = await get_jwt_token(config)
    headers = {
        "Accept": "application/json",
        "Authorization": f"JWT {jwt_token}",
        "Content-Type": "application/json"
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json=data, headers=headers)
        resp.raise_for_status()
        return resp.json()

@router.callback_query(F.data == "buy_stars_self_confirm")
async def buy_stars_self_confirm_callback(call: CallbackQuery, state: FSMContext, db_pool):
    if not call.from_user.username:
        await call.message.answer("У вас нету логина в тг, установите его и попробуйте еще раз")
        await state.clear()
        return
    await call.answer()
    data = await state.get_data()
    amount = data.get("amount")
    total = data.get("total")
    if total is None or amount is None:
        await call.message.answer(
            "Ошибка: не удалось определить сумму покупки. Попробуйте начать заново.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ В меню", callback_data="main_menu")]
            ]),
            parse_mode="HTML"
        )
        await state.clear()
        return
    user = await get_or_create_user(db_pool, call.from_user.id, call.from_user.username)
    if float(user["balance"]) < total:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💰 Пополнить баланс", callback_data="profile_topup")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="buy_stars_self")]
        ])
        balance_str = f"Ваш баланс: <b>{float(user['balance'])}₽</b>"
        await call.message.answer(
            f"Недостаточно средств!\n{balance_str}\nНе хватает: <b>{total - float(user['balance'])}₽</b>",
            reply_markup=kb,
            parse_mode="HTML"
        )
        await state.clear()
        return
    
    # Отправить стартовое сообщение с фото и главным меню
    from config import load_config
    config = load_config()
    await call.message.answer_photo(
        config.welcome_image_url,
        caption=config.welcome_description,
        reply_markup=main_menu_kb(call.from_user.id),
        parse_mode="HTML"
    )
    # Сообщение об успешном оформлении заказа
    await call.message.answer("Спасибо за покупку ✅\nЗвёзды придут в течении 5 минут ⭐️\n\nВаша подписка на наш канал лучшая благодарность для нашего сервиса ❤️\n\n@BuysStarsNews", parse_mode="HTML")
    # Списываю баланс
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE users SET balance = balance - $1, username = $2 WHERE telegram_id=$3", total, call.from_user.username, user["telegram_id"])
        # Сброс скидки после покупки
        await conn.execute("UPDATE users SET discount=NULL WHERE telegram_id=$1", user["telegram_id"])
    # Оформляю заказ в фоне
    asyncio.create_task(create_fragment_order(amount, call.from_user.username))
    await state.clear()
    return

@router.callback_query(F.data == "buy_stars_self_cancel")
async def buy_stars_self_cancel_callback(call: CallbackQuery, state: FSMContext):
    await state.clear()
    from config import load_config
    config = load_config()
    from handlers.start import main_menu_kb
    await call.message.answer_photo(
        config.welcome_image_url,
        caption=config.welcome_description,
        reply_markup=main_menu_kb(call.from_user.id),
        parse_mode="HTML"
    )
    await call.answer()

def get_packs_kb(page: int, prefix: str, star_price, discount=None):
    start = page * PACKS_PER_PAGE
    end = start + PACKS_PER_PAGE
    packs = STAR_PACKS[start:end]
    kb = []
    for amount in packs:
        price = round(amount * star_price, 2)
        if discount:
            discounted_price = round(price * (1 - float(discount) / 100), 2)
            btn_text = f"⭐ {amount:,} Stars — {price}₽ → {discounted_price}₽ (-{discount}%)"
        else:
            btn_text = f"⭐ {amount:,} Stars — {price}₽"
        kb.append([InlineKeyboardButton(text=btn_text, callback_data=f"{prefix}_pack_{amount}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"{prefix}_packs_page_{page-1}"))
    if end < len(STAR_PACKS):
        nav.append(InlineKeyboardButton(text="Вперёд ➡️", callback_data=f"{prefix}_packs_page_{page+1}"))
    if nav:
        kb.append(nav)
    kb.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"{prefix}")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

@router.callback_query(F.data == "buy_stars_self_packs")
async def buy_stars_self_packs_callback(call: CallbackQuery, state: FSMContext, db_pool):
    user = await get_or_create_user(db_pool, call.from_user.id, call.from_user.username)
    star_price = await get_star_price(db_pool)
    discount = user.get("discount")
    await call.message.edit_caption(
        caption="<b>Выберите готовый пакет звёзд:</b>",
        reply_markup=get_packs_kb(0, "buy_stars_self", star_price, discount),
        parse_mode="HTML"
    )
    await call.answer()

@router.callback_query(F.data.startswith("buy_stars_self_packs_page_"))
async def buy_stars_self_packs_page_callback(call: CallbackQuery, state: FSMContext, db_pool):
    user = await get_or_create_user(db_pool, call.from_user.id, call.from_user.username)
    page = int(call.data.split("_")[-1])
    star_price = await get_star_price(db_pool)
    discount = user.get("discount")
    await call.message.edit_caption(
        caption="<b>Выберите готовый пакет звёзд:</b>",
        reply_markup=get_packs_kb(page, "buy_stars_self", star_price, discount),
        parse_mode="HTML"
    )
    await call.answer()

@router.callback_query(F.data.startswith("buy_stars_self_pack_"))
async def buy_stars_self_pack_selected(call: CallbackQuery, state: FSMContext, db_pool):
    user = await get_or_create_user(db_pool, call.from_user.id, call.from_user.username)
    amount = int(call.data.split("_")[-1])
    star_price = await get_star_price(db_pool)
    total = round(amount * star_price, 2)
    discount = user.get("discount")
    if discount:
        discount = float(discount)
        discounted_total = round(total * (1 - discount / 100), 2)
        await state.update_data(amount=amount, total=discounted_total, original_total=total)
        price_text = (
            f"Вы выбрали пакет: <b>{amount}</b> звёзд\n"
            f"Итоговая стоимость: {total}₽ → <b>{discounted_total}₽</b> (скидка {discount}%)\n\nПодтвердить покупку?"
        )
    else:
        await state.update_data(amount=amount, total=total)
        price_text = (
            f"Вы выбрали пакет: <b>{amount}</b> звёзд\n"
            f"Итоговая стоимость: <b>{total}₽</b>\n\nПодтвердить покупку?"
        )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data="buy_stars_self_confirm")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="buy_stars_self_cancel")]
    ])
    await call.message.edit_caption(
        caption=price_text,
        reply_markup=kb,
        parse_mode="HTML"
    )
    await state.set_state(BuyStarsConfirmStates.waiting_for_confirm)
    await call.answer()

@router.callback_query(F.data == "buy_stars_gift")
async def buy_stars_gift_callback(call: CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="buy_stars")]
    ])
    text = "<b>Пожалуйста, укажите логин (@username) или ID пользователя в Telegram, которому хотите подарить звёзды.</b>"
    if getattr(call.message, "content_type", None) == "photo":
        await call.message.edit_caption(
            caption=text,
            reply_markup=kb,
            parse_mode="HTML"
        )
    else:
        await call.message.edit_text(
            text,
            reply_markup=kb,
            parse_mode="HTML"
        )
    await state.set_state(BuyStarsGiftStates.waiting_for_recipient)
    await call.answer()

@router.message(BuyStarsGiftStates.waiting_for_recipient)
async def process_gift_recipient(message: Message, state: FSMContext):
    await state.update_data(recipient=message.text.strip())
    await message.answer(f"Вы указали: <code>{message.text}</code>\nКому хотите подарить звёзды?\n\nВыберите способ:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🔢 Ввести количество", callback_data="buy_stars_gift_amount"),
                InlineKeyboardButton(text="📦 Готовые паки", callback_data="buy_stars_gift_packs")
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="buy_stars")]
        ]),
        parse_mode="HTML")
    await state.set_state(BuyStarsGiftStates.waiting_for_gift_amount)

@router.callback_query(F.data == "buy_stars_gift_amount")
async def buy_stars_gift_amount_callback(call: CallbackQuery, state: FSMContext):
    text = "<b>Введите количество звёзд для подарка (минимум 50):</b>"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="buy_stars_gift_packs")]
    ])
    if getattr(call.message, "content_type", None) == "photo":
        await call.message.edit_caption(
            caption=text,
            reply_markup=kb,
            parse_mode="HTML"
        )
    else:
        await call.message.edit_text(
            text,
            reply_markup=kb,
            parse_mode="HTML"
        )
    await state.set_state(BuyStarsGiftStates.waiting_for_gift_amount)
    await call.answer()

@router.callback_query(F.data == "buy_stars_gift_packs")
async def buy_stars_gift_packs_callback(call: CallbackQuery, state: FSMContext, db_pool):
    user = await get_or_create_user(db_pool, call.from_user.id, call.from_user.username)
    star_price = await get_star_price(db_pool)
    discount = user.get("discount")
    await call.message.edit_text(
        "<b>Выберите готовый пакет звёзд для подарка:</b>",
        reply_markup=get_packs_kb(0, "buy_stars_gift", star_price, discount),
        parse_mode="HTML"
    )
    await call.answer()

@router.callback_query(F.data.startswith("buy_stars_gift_packs_page_"))
async def buy_stars_gift_packs_page_callback(call: CallbackQuery, state: FSMContext, db_pool):
    user = await get_or_create_user(db_pool, call.from_user.id, call.from_user.username)
    page = int(call.data.split("_")[-1])
    star_price = await get_star_price(db_pool)
    discount = user.get("discount")
    await call.message.edit_text(
        "<b>Выберите готовый пакет звёзд для подарка:</b>",
        reply_markup=get_packs_kb(page, "buy_stars_gift", star_price, discount),
        parse_mode="HTML"
    )
    await call.answer()

@router.callback_query(F.data.startswith("buy_stars_gift_pack_"))
async def buy_stars_gift_pack_selected(call: CallbackQuery, state: FSMContext, db_pool):
    user = await get_or_create_user(db_pool, call.from_user.id, call.from_user.username)
    amount = int(call.data.split("_")[-1])
    star_price = await get_star_price(db_pool)
    total = round(amount * star_price, 2)
    discount = user.get("discount")
    data = await state.get_data()
    recipient = data.get("recipient")
    if not recipient:
        recipient = call.from_user.username or call.from_user.id or "неизвестно"
    if discount:
        discount = float(discount)
        discounted_total = round(total * (1 - discount / 100), 2)
        await state.update_data(amount=amount, total=discounted_total, original_total=total)
        price_text = (
            f"Вы выбрали пакет для подарка: <b>{amount}</b> звёзд\n"
            f"Итоговая стоимость: {total}₽ → <b>{discounted_total}₽</b> (скидка {discount}%)\n"
            f"Кому: <code>{recipient}</code>\n\nПодтвердить покупку?"
        )
    else:
        await state.update_data(amount=amount, total=total)
        price_text = (
            f"Вы выбрали пакет для подарка: <b>{amount}</b> звёзд\n"
            f"Итоговая стоимость: <b>{total}₽</b>\n"
            f"Кому: <code>{recipient}</code>\n\nПодтвердить покупку?"
        )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data="buy_stars_gift_confirm")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="buy_stars_gift_cancel")]
    ])
    await call.message.edit_text(
        price_text,
        reply_markup=kb,
        parse_mode="HTML"
    )
    await state.set_state(BuyStarsConfirmStates.waiting_for_gift_confirm)
    await call.answer()

@router.message(BuyStarsGiftStates.waiting_for_gift_amount)
async def process_gift_amount(message: Message, state: FSMContext, db_pool):
    try:
        amount = int(message.text)
    except ValueError:
        await message.answer("❗ Введите целое число (минимум 50):")
        return
    if amount < 50:
        await message.answer("❗ Минимальное количество для подарка — 50 звёзд. Попробуйте снова:")
        return
    star_price = await get_star_price(db_pool)
    total = round(amount * star_price, 2)
    data = await state.get_data()
    recipient = data.get("recipient")
    if not recipient:
        # Если recipient не найден, пробуем взять из предыдущего сообщения пользователя
        # (например, если пользователь только что ввёл логин)
        # Обычно recipient должен быть в state, но на всякий случай:
        recipient = message.from_user.username or message.from_user.id or "неизвестно"
    discount = data.get("active_discount")
    if not discount:
        user = await get_or_create_user(db_pool, message.from_user.id, message.from_user.username)
        discount = user.get("discount")
    if discount:
        discount = float(discount)
        discounted_total = round(total * (1 - discount / 100), 2)
        await state.update_data(amount=amount, total=discounted_total, original_total=total)
        price_text = (
            f"Вы выбрали: <b>{amount}</b> звёзд для подарка\n"
            f"Итоговая стоимость: <s>{total}₽</s> <b>{discounted_total}₽</b> (скидка {discount}%)\n"
            f"Кому: <code>{recipient}</code>\n\nПодтвердить покупку?"
        )
    else:
        await state.update_data(amount=amount, total=total)
        price_text = (
            f"Вы выбрали: <b>{amount}</b> звёзд для подарка\n"
            f"Итоговая стоимость: <b>{total}₽</b>\n"
            f"Кому: <code>{recipient}</code>\n\nПодтвердить покупку?"
        )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data="buy_stars_gift_confirm")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="buy_stars_gift_cancel")]
    ])
    await message.answer(price_text, reply_markup=kb, parse_mode="HTML")
    await state.set_state(BuyStarsConfirmStates.waiting_for_gift_confirm)

@router.callback_query(F.data == "buy_stars_gift_confirm")
async def buy_stars_gift_confirm_callback(call: CallbackQuery, state: FSMContext, db_pool):
    await call.answer()
    data = await state.get_data()
    amount = data.get("amount")
    total = data.get("total")
    recipient = data.get("recipient")
    if total is None or amount is None or recipient is None:
        await call.message.answer(
            "Ошибка: не удалось определить тариф или получателя. Попробуйте начать заново.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ В меню", callback_data="main_menu")]
            ])
        )
        await state.clear()
        return
    user = await get_or_create_user(db_pool, call.from_user.id, call.from_user.username)
    if float(user["balance"]) < total:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💰 Пополнить баланс", callback_data="profile_topup")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="buy_stars_gift")]
        ])
        balance_str = f"Ваш баланс: <b>{float(user['balance'])}₽</b>"
        await call.message.answer(
            f"Недостаточно средств!\n{balance_str}\nНе хватает: <b>{total - float(user['balance'])}₽</b>",
            reply_markup=kb,
            parse_mode="HTML"
        )
        await state.clear()
        return
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE users SET balance = balance - $1 WHERE telegram_id=$2", total, user["telegram_id"])
    # Сообщение об успешном оформлении подарка
    await call.message.answer("Спасибо за покупку ✅\nЗвёзды придут в течении 5 минут ⭐️\n\nВаша подписка на наш канал лучшая благодарность для нашего сервиса ❤️\n\n@BuysStarsNews", parse_mode="HTML")
    # Отправить стартовое сообщение с фото и главным меню
    from config import load_config
    config = load_config()
    await call.message.answer_photo(
        config.welcome_image_url,
        caption=config.welcome_description,
        reply_markup=main_menu_kb(call.from_user.id),
        parse_mode="HTML"
    )
    # Оформляю заказ в фоне
    data = await state.get_data()
    plan_index = data.get("plan_index")
    plan = PREMIUM_PLANS[plan_index]
    months = plan["duration"] // 30
    asyncio.create_task(create_fragment_gift_premium(recipient, months, config))
    # Сброс скидки после покупки
    await state.update_data(active_discount=None)
    await state.clear()

@router.callback_query(F.data == "buy_stars_gift_cancel")
async def buy_stars_gift_cancel_callback(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.answer_photo(
        config.welcome_image_url,
        caption=config.welcome_description,
        reply_markup=main_menu_kb(call.from_user.id),
        parse_mode="HTML"
    )
    await call.answer()

async def get_jwt_token(config):
    global _jwt_token_cache, _jwt_token_expire
    if getattr(config, 'fragment_jwt_token', None):
        return config.fragment_jwt_token
    now = time.time()
    if _jwt_token_cache and now < _jwt_token_expire:
        return _jwt_token_cache
    url = "https://api.fragment-api.com/v1/auth/authenticate/"
    payload = {
        "api_key": config.fragment_api_key,
        "phone_number": config.fragment_phone_number,
        "mnemonics": config.fragment_mnemonics.split()
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            resp_json = resp.json()
            token = resp_json["token"]
            expires_in = resp_json.get("expires_in", 3600)
            _jwt_token_cache = token
            _jwt_token_expire = time.time() + expires_in - 30
            return token
    except Exception as e:
        raise

async def create_fragment_gift_premium(username, months, config):
    url = "https://api.fragment-api.com/v1/order/premium/"
    username = username.lstrip("@") if username else ""
    data = {
        "username": username,
        "months": months
    }
    jwt_token = await get_jwt_token(config)
    headers = {
        "Accept": "application/json",
        "Authorization": f"JWT {jwt_token}",
        "Content-Type": "application/json"
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json=data, headers=headers)
        resp.raise_for_status()
        return resp.json()

class BuyPremiumStates(StatesGroup):
    waiting_for_self_or_gift = State()
    waiting_for_gift_recipient = State()
    waiting_for_self_plan = State()
    waiting_for_gift_plan = State()
    waiting_for_self_confirm = State()
    waiting_for_gift_confirm = State()

@router.callback_query(F.data == "buy_premium")
async def buy_premium_callback(call: CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🧑‍💼 Себе", callback_data="buy_premium_self"),
            InlineKeyboardButton(text="🎁 Другому", callback_data="buy_premium_gift")
        ],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ])
    text = "<b>Купить премиум</b>\n\nКому вы хотите купить премиум?"
    if getattr(call.message, "content_type", None) == "photo":
        await call.message.edit_caption(
            caption=text,
            reply_markup=kb,
            parse_mode="HTML"
        )
    else:
        await call.message.edit_text(
            text,
            reply_markup=kb,
            parse_mode="HTML"
        )
    await state.set_state(BuyPremiumStates.waiting_for_self_or_gift)
    await call.answer()

@router.callback_query(F.data == "buy_premium_self")
async def buy_premium_self_callback(call: CallbackQuery, state: FSMContext, db_pool):
    user = await get_or_create_user(db_pool, call.from_user.id, call.from_user.username)
    premium_prices = await get_premium_prices(db_pool)
    discount = user.get("discount")
    kb = []
    for i, plan in enumerate(PREMIUM_PLANS):
        price = premium_prices[i]
        if discount:
            discounted_price = round(price * (1 - float(discount) / 100), 2)
            btn_text = f"💎 {plan['name']} — {price}₽ → {discounted_price}₽ (-{discount}%)"
        else:
            btn_text = f"💎 {plan['name']} — {price}₽"
        kb.append([
            InlineKeyboardButton(
                text=btn_text,
                callback_data=f"buy_premium_self_plan_{i}"
            )
        ])
    kb.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="buy_premium")])
    markup = InlineKeyboardMarkup(inline_keyboard=kb)
    text = "<b>Выберите тариф для себя:</b>"
    if call.message.content_type == "photo":
        await call.message.edit_caption(
            caption=text,
            reply_markup=markup,
            parse_mode="HTML"
        )
    else:
        await call.message.edit_text(
            text,
            reply_markup=markup,
            parse_mode="HTML"
        )
    await state.set_state(BuyPremiumStates.waiting_for_self_plan)
    await call.answer()

@router.callback_query(F.data.startswith("buy_premium_self_plan_"))
async def buy_premium_self_plan_selected(call: CallbackQuery, state: FSMContext, db_pool):
    user = await get_or_create_user(db_pool, call.from_user.id, call.from_user.username)
    plan_index = int(call.data.split("_")[-1])
    plan = PREMIUM_PLANS[plan_index]
    premium_prices = await get_premium_prices(db_pool)
    price = premium_prices[plan_index]
    discount = user.get("discount")
    if discount:
        discount = float(discount)
        discounted_price = round(price * (1 - discount / 100), 2)
        await state.update_data(plan_index=plan_index, total=discounted_price, original_total=price)
        text = (
            f"Вы выбрали тариф для себя:\n"
            f"<b>{plan['name']}</b>\n"
            f"Стоимость: {price}₽ → <b>{discounted_price}₽</b> (скидка {discount}%)\n\n"
            f"Подтвердить покупку?"
        )
    else:
        await state.update_data(plan_index=plan_index, total=price)
        text = (
            f"Вы выбрали тариф для себя:\n"
            f"<b>{plan['name']}</b>\n"
            f"Стоимость: <b>{price}₽</b>\n\n"
            f"Подтвердить покупку?"
        )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data="buy_premium_self_confirm")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="buy_premium_cancel")]
    ])
    if call.message.content_type == "photo":
        await call.message.edit_caption(
            caption=text,
            reply_markup=kb,
            parse_mode="HTML"
        )
    else:
        await call.message.edit_text(
            text,
            reply_markup=kb,
            parse_mode="HTML"
        )
    await state.set_state(BuyPremiumStates.waiting_for_self_confirm)
    await call.answer()

@router.callback_query(F.data == "buy_premium_self_confirm")
async def buy_premium_self_confirm_callback(call: CallbackQuery, state: FSMContext, db_pool):
    from config import load_config
    config = load_config()
    if not call.from_user.username:
        await call.message.answer("У вас нету логина в тг, установите его и попробуйте еще раз")
        await state.clear()
        return
    data = await state.get_data()
    plan_index = data.get("plan_index")
    total = data.get("total")
    if plan_index is None or total is None:
        await call.message.answer(
            "Ошибка: не удалось определить выбранный тариф. Попробуйте начать заново.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ В меню", callback_data="main_menu")]
            ])
        )
        await state.clear()
        return
    plan = PREMIUM_PLANS[plan_index]
    user = await get_or_create_user(db_pool, call.from_user.id, call.from_user.username)
    if float(user["balance"]) < total:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💰 Пополнить баланс", callback_data="profile_topup")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="buy_premium_self")]
        ])
        balance_str = f"Ваш баланс: <b>{float(user['balance'])}₽</b>"
        await call.message.answer(
            f"Недостаточно средств!\n{balance_str}\nНе хватает: <b>{total - float(user['balance'])}₽</b>",
            reply_markup=kb,
            parse_mode="HTML"
        )
        await state.clear()
        return
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET balance = balance - $1, username = $2 WHERE telegram_id = $3",
            total, call.from_user.username, user["telegram_id"]
        )
    await call.message.answer(
        f"✅ Премиум успешно активирован!\n"
        f"Тариф: <b>{plan['name']}</b>\n"
        f"Длительность: <b>{plan['duration']} дней</b>",
        parse_mode="HTML"
    )
    # Отправить стартовое сообщение с фото и главным меню
    await call.message.answer_photo(
        config.welcome_image_url,
        caption=config.welcome_description,
        reply_markup=main_menu_kb(call.from_user.id),
        parse_mode="HTML"
    )
    # Вызов Fragment API в фоне
    async def _activate_premium_bg():
        try:
            months = plan["duration"] // 30
            await create_fragment_gift_premium(call.from_user.username, months, config)
        except Exception as e:
            print(f"[Fragment API] Ошибка при активации премиума: {e}")
    asyncio.create_task(_activate_premium_bg())
    # Сброс скидки после покупки
    await state.update_data(active_discount=None)
    await state.clear()

@router.callback_query(F.data == "buy_premium_gift")
async def buy_premium_gift_callback(call: CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="buy_premium")]
    ])
    text = "<b>Пожалуйста, укажите логин (@username) или ID пользователя в Telegram, которому хотите подарить премиум.</b>"
    if getattr(call.message, "content_type", None) == "photo":
        await call.message.edit_caption(
            caption=text,
            reply_markup=kb,
            parse_mode="HTML"
        )
    else:
        await call.message.edit_text(
            text,
            reply_markup=kb,
            parse_mode="HTML"
        )
    await state.set_state(BuyPremiumStates.waiting_for_gift_recipient)
    await call.answer()

@router.message(BuyPremiumStates.waiting_for_gift_recipient)
async def process_premium_gift_recipient(message: Message, state: FSMContext, db_pool):
    await state.update_data(recipient=message.text.strip())
    user = await get_or_create_user(db_pool, message.from_user.id, message.from_user.username)
    premium_prices = await get_premium_prices(db_pool)
    discount = user.get("discount")
    kb = []
    for i, plan in enumerate(PREMIUM_PLANS):
        price = premium_prices[i]
        if discount:
            discounted_price = round(price * (1 - float(discount) / 100), 2)
            btn_text = f"💎 {plan['name']} — {price}₽ → {discounted_price}₽ (-{discount}%)"
        else:
            btn_text = f"💎 {plan['name']} — {price}₽"
        kb.append([
            InlineKeyboardButton(
                text=btn_text,
                callback_data=f"buy_premium_gift_plan_{i}"
            )
        ])
    kb.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="buy_premium_gift")])
    await message.answer(
        "<b>Выберите тариф для подарка:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb),
        parse_mode="HTML"
    )
    await state.set_state(BuyPremiumStates.waiting_for_gift_plan)

@router.callback_query(F.data.startswith("buy_premium_gift_plan_"))
async def buy_premium_gift_plan_selected(call: CallbackQuery, state: FSMContext, db_pool):
    user = await get_or_create_user(db_pool, call.from_user.id, call.from_user.username)
    plan_index = int(call.data.split("_")[-1])
    plan = PREMIUM_PLANS[plan_index]
    premium_prices = await get_premium_prices(db_pool)
    price = premium_prices[plan_index]
    discount = user.get("discount")
    data = await state.get_data()
    recipient = data.get("recipient")
    if discount:
        discount = float(discount)
        discounted_price = round(price * (1 - discount / 100), 2)
        await state.update_data(plan_index=plan_index, total=discounted_price, original_total=price)
        text = (
            f"Вы выбрали тариф для подарка:\n"
            f"<b>{plan['name']}</b>\n"
            f"Стоимость: {price}₽ → <b>{discounted_price}₽</b> (скидка {discount}%)\n"
            f"Кому: <code>{recipient}</code>\n\n"
            f"Подтвердить покупку?"
        )
    else:
        await state.update_data(plan_index=plan_index, total=price)
        text = (
            f"Вы выбрали тариф для подарка:\n"
            f"<b>{plan['name']}</b>\n"
            f"Стоимость: <b>{price}₽</b>\n"
            f"Кому: <code>{recipient}</code>\n\n"
            f"Подтвердить покупку?"
        )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data="buy_premium_gift_confirm")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="buy_premium_cancel")]
    ])
    await call.message.edit_text(
        text,
        reply_markup=kb,
        parse_mode="HTML"
    )
    await state.set_state(BuyPremiumStates.waiting_for_gift_confirm)
    await call.answer()

@router.callback_query(F.data == "buy_premium_gift_confirm")
async def buy_premium_gift_confirm_callback(call: CallbackQuery, state: FSMContext, db_pool):
    from config import load_config
    config = load_config()
    data = await state.get_data()
    plan_index = data.get("plan_index")
    recipient = data.get("recipient")
    total = data.get("total")
    if plan_index is None or recipient is None or total is None:
        await call.message.answer(
            "Ошибка: не удалось определить тариф или получателя. Попробуйте начать заново.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ В меню", callback_data="main_menu")]
            ])
        )
        await state.clear()
        return
    plan = PREMIUM_PLANS[plan_index]
    months = plan["duration"] // 30
    user = await get_or_create_user(db_pool, call.from_user.id, call.from_user.username)
    if float(user["balance"]) < total:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💰 Пополнить баланс", callback_data="profile_topup")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="buy_premium_gift")]
        ])
        balance_str = f"Ваш баланс: <b>{float(user['balance'])}₽</b>"
        await call.message.answer(
            f"Недостаточно средств!\n{balance_str}\nНе хватает: <b>{total - float(user['balance'])}₽</b>",
            reply_markup=kb,
            parse_mode="HTML"
        )
        await state.clear()
        return
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE users SET balance = balance - $1 WHERE telegram_id=$2", total, user["telegram_id"])
    # Отправить стартовое сообщение с фото и главным меню
    await call.message.answer_photo(
        config.welcome_image_url,
        caption=config.welcome_description,
        reply_markup=main_menu_kb(call.from_user.id),
        parse_mode="HTML"
    )
    # Сообщение об успешном оформлении заказа
    await call.message.answer("Спасибо за покупку ✅\nЗвёзды придут в течении 5 минут ⭐️\n\nВаша подписка на наш канал лучшая благодарность для нашего сервиса ❤️\n\n@BuysStarsNews", parse_mode="HTML")
    # Оформляю заказ в фоне
    asyncio.create_task(create_fragment_gift_premium(recipient, months, config))
    # Сброс скидки после покупки
    await state.update_data(active_discount=None)
    await state.clear()

@router.callback_query(F.data == "buy_premium_cancel")
async def buy_premium_cancel_callback(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.answer_photo(
        config.welcome_image_url,
        caption=config.welcome_description,
        reply_markup=main_menu_kb(call.from_user.id),
        parse_mode="HTML"
    )
    await call.answer()

@router.callback_query(F.data == "admin_panel")
async def admin_panel_callback(call: CallbackQuery):
    from config import load_config
    config = load_config()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Управления балансами", callback_data="admin_balances")],
        [InlineKeyboardButton(text="Промокоды", callback_data="admin_promos")],
        [InlineKeyboardButton(text="Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="Управления ценами", callback_data="admin_prices")],
        [InlineKeyboardButton(text="Настройки пополнения", callback_data="admin_payment_settings")],
        [InlineKeyboardButton(text="⬅️ В меню", callback_data="main_menu")],
    ])
    text = "<b>⚙️ Админ панель</b>\n\nВыберите действие:"
    try:
        await call.message.delete()
    except Exception:
        pass
    await call.message.answer_photo(
        config.welcome_image_url,
        caption=text,
        reply_markup=kb,
        parse_mode="HTML"
    )
    await call.answer()

class AdminBalanceStates(StatesGroup):
    waiting_for_user = State()
    waiting_for_amount = State()

@router.callback_query(F.data == "admin_balances")
async def admin_balances_start(call: CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")]
    ])
    text = "<b>Управление балансом</b>\n\nВведите username (без @) или ID пользователя:"
    try:
        await call.message.edit_caption(
            caption=text,
            reply_markup=kb,
            parse_mode="HTML"
        )
    except TelegramBadRequest:
        from config import load_config
        config = load_config()
        await call.message.delete()
        await call.message.answer_photo(
            config.welcome_image_url,
            caption=text,
            reply_markup=kb,
            parse_mode="HTML"
        )
    await state.set_state(AdminBalanceStates.waiting_for_user)
    await call.answer()

@router.message(AdminBalanceStates.waiting_for_user)
async def admin_balance_get_user(message: Message, state: FSMContext, db_pool):
    text = message.text.strip()
    user = None
    if text.isdigit():
        async with db_pool.acquire() as conn:
            user = await conn.fetchrow("SELECT * FROM users WHERE telegram_id=$1", int(text))
    else:
        async with db_pool.acquire() as conn:
            user = await conn.fetchrow("SELECT * FROM users WHERE username=$1", text)
    if not user:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")]
        ])
        await message.answer("Пользователь не найден. Попробуйте снова или нажмите 'Назад'.", reply_markup=kb)
        return
    await state.update_data(target_user_id=user['telegram_id'])
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_balances")]
    ])
    await message.answer(
        f"Пользователь: <b>{user['username'] or user['telegram_id']}</b>\nТекущий баланс: <b>{user['balance']} ₽</b>\n\nВведите изменение баланса (например, +100 или -100):",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await state.set_state(AdminBalanceStates.waiting_for_amount)

@router.message(AdminBalanceStates.waiting_for_amount)
async def admin_balance_change(message: Message, state: FSMContext, db_pool):
    text = message.text.strip().replace(' ', '')
    if not (text.startswith('+') or text.startswith('-')) or not text[1:].isdigit():
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_balances")]
        ])
        await message.answer("Введите корректное изменение баланса (например, +100 или -100):", reply_markup=kb)
        return
    amount = int(text)
    data = await state.get_data()
    target_user_id = data.get('target_user_id')
    if not target_user_id:
        await message.answer("Ошибка: не выбран пользователь.")
        await state.clear()
        return
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE users SET balance = balance + $1 WHERE telegram_id=$2", amount, target_user_id)
        user = await conn.fetchrow("SELECT * FROM users WHERE telegram_id=$1", target_user_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")]
    ])
    await message.answer(
        f"Баланс пользователя обновлён!\nТекущий баланс: <b>{user['balance']} ₽</b>",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await state.clear()

@router.callback_query(F.data == "admin_balances", AdminBalanceStates.waiting_for_amount)
async def admin_balances_back_from_amount(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await admin_panel_callback(call)

class PromoStates(StatesGroup):
    menu = State()
    create_choose_name = State()
    create_input_name = State()
    create_choose_type = State()  # <--- добавляю это состояние
    create_input_sum = State()
    create_choose_limit = State()
    create_input_uses = State()
    create_input_time = State()
    delete_choose = State()
    show_active = State()
    show_stats = State()

@router.callback_query(F.data == "admin_promos")
async def admin_promos_menu(call: CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Создать промокод", callback_data="promo_create")],
        [InlineKeyboardButton(text="Удалить промокод", callback_data="promo_delete")],
        [InlineKeyboardButton(text="Активные промокоды", callback_data="promo_active")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")],
    ])
    text = "<b>Промокоды</b>\n\nВыберите действие:"
    if call.message.content_type == "photo":
        await call.message.edit_caption(caption=text, reply_markup=kb, parse_mode="HTML")
    else:
        await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await state.set_state(PromoStates.menu)
    await call.answer()

@router.callback_query(F.data == "promo_create", PromoStates.menu)
async def promo_create_choose_type(call: CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Пополнение баланса (₽)", callback_data="promo_type_balance")],
        [InlineKeyboardButton(text="Скидка (%)", callback_data="promo_type_discount")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_promos")],
    ])
    text = "<b>Создание промокода</b>\n\nКакой тип промокода вы хотите создать?"
    if call.message.content_type == "photo":
        await call.message.edit_caption(caption=text, reply_markup=kb, parse_mode="HTML")
    else:
        await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await state.set_state(PromoStates.create_choose_type)
    await call.answer()

@router.callback_query(F.data.startswith("promo_type_"), PromoStates.create_choose_type)
async def promo_create_choose_name(call: CallbackQuery, state: FSMContext):
    promo_type = call.data.replace("promo_type_", "")
    await state.update_data(promo_type=promo_type)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Сгенерировать название", callback_data="promo_gen_name")],
        [InlineKeyboardButton(text="Ввести название", callback_data="promo_input_name")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="promo_create")],
    ])
    text = "<b>Создание промокода</b>\n\nВыберите способ задания названия:"
    if call.message.content_type == "photo":
        await call.message.edit_caption(caption=text, reply_markup=kb, parse_mode="HTML")
    else:
        await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await state.set_state(PromoStates.create_choose_name)
    await call.answer()

@router.callback_query(F.data == "promo_gen_name", PromoStates.create_choose_name)
async def promo_create_gen_name(call: CallbackQuery, state: FSMContext, db_pool):
    code = await generate_promo_code(db_pool)
    await state.update_data(promo_name=code)
    data = await state.get_data()
    promo_type = data.get("promo_type", "balance")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="promo_create")],
    ])
    if promo_type == "discount":
        text = f"Введите процент скидки для промокода <code>{code}</code> (например, 10 для 10%):"
    else:
        text = f"Введите сумму пополнения для промокода <code>{code}</code>:"
    await call.message.edit_caption(caption=text, reply_markup=kb, parse_mode="HTML")
    await state.set_state(PromoStates.create_input_sum)
    await call.answer()

@router.callback_query(F.data == "promo_input_name", PromoStates.create_choose_name)
async def promo_create_input_name(call: CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="promo_create")],
    ])
    text = "Введите название промокода:"
    await call.message.edit_caption(caption=text, reply_markup=kb, parse_mode="HTML")
    await state.set_state(PromoStates.create_input_name)
    await call.answer()

@router.callback_query(F.data == "promo_create", PromoStates.create_input_name)
async def promo_create_back_from_input_name(call: CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Сгенерировать название", callback_data="promo_gen_name")],
        [InlineKeyboardButton(text="Ввести название", callback_data="promo_input_name")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_promos")],
    ])
    text = "<b>Создание промокода</b>\n\nВыберите способ задания названия:"
    await call.message.edit_caption(caption=text, reply_markup=kb, parse_mode="HTML")
    await state.set_state(PromoStates.create_choose_name)
    await call.answer()

@router.message(PromoStates.create_input_name)
async def promo_create_input_name_msg(message: Message, state: FSMContext, db_pool):
    code = message.text.strip().upper()
    # Проверка на уникальность
    async with db_pool.acquire() as conn:
        exists = await conn.fetchval("SELECT 1 FROM promo_codes WHERE code=$1", code)
    if exists:
        await message.answer("Промокод с таким названием уже существует. Введите другое название.")
        return
    await state.update_data(promo_name=code)
    data = await state.get_data()
    promo_type = data.get("promo_type")
    if promo_type:
        # Тип уже выбран — сразу просим сумму/процент
        if promo_type == "discount":
            text = f"Введите процент скидки для промокода <code>{code}</code> (например, 10 для 10%):"
        else:
            text = f"Введите сумму пополнения для промокода <code>{code}</code>:"
        await message.answer(text, parse_mode="HTML")
        await state.set_state(PromoStates.create_input_sum)
    else:
        # Тип не выбран — предлагаем выбрать
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Пополнение баланса (₽)", callback_data="promo_type_balance")],
            [InlineKeyboardButton(text="Скидка (%)", callback_data="promo_type_discount")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="promo_create")],
        ])
        text = f"Выберите тип промокода для <code>{code}</code>:"
        await message.answer(text, reply_markup=kb, parse_mode="HTML")
        await state.set_state(PromoStates.create_choose_type)

@router.callback_query(F.data.startswith("promo_type_"), PromoStates.create_choose_type)
async def promo_create_choose_type(call: CallbackQuery, state: FSMContext):
    promo_type = call.data.replace("promo_type_", "")
    await state.update_data(promo_type=promo_type)
    data = await state.get_data()
    code = data.get("promo_name")
    if promo_type == "balance":
        text = f"Введите сумму пополнения для промокода <code>{code}</code>:"
    else:
        text = f"Введите процент скидки для промокода <code>{code}</code> (например, 10 для 10%):"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="promo_create")],
    ])
    await call.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await state.set_state(PromoStates.create_input_sum)

@router.callback_query(F.data == "promo_create", PromoStates.create_input_sum)
async def promo_create_back_from_sum(call: CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Сгенерировать название", callback_data="promo_gen_name")],
        [InlineKeyboardButton(text="Ввести название", callback_data="promo_input_name")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_promos")],
    ])
    text = "<b>Создание промокода</b>\n\nВыберите способ задания названия:"
    if call.message.content_type == "photo":
        await call.message.edit_caption(caption=text, reply_markup=kb, parse_mode="HTML")
    else:
        await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await state.set_state(PromoStates.create_choose_name)
    await call.answer()

@router.message(PromoStates.create_input_sum)
async def promo_create_input_sum_msg(message: Message, state: FSMContext):
    data = await state.get_data()
    promo_type = data.get('promo_type', 'balance')
    try:
        value = float(message.text.strip().replace(',', '.'))
        if promo_type == 'discount':
            if not (1 <= value <= 100):
                raise ValueError
        else:
            if value <= 0:
                raise ValueError
    except Exception:
        if promo_type == 'discount':
            await message.answer("Введите корректный процент скидки (от 1 до 100):")
        else:
            await message.answer("Введите корректную сумму (например, 100 или 250.50):")
        return
    await state.update_data(promo_sum=value)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="По количеству использований", callback_data="promo_limit_uses")],
        [InlineKeyboardButton(text="По времени", callback_data="promo_limit_time")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="promo_create")],
    ])
    if promo_type == 'discount':
        text = f"Выберите ограничение для промокода (скидка <b>{value}%</b>):"
    else:
        text = f"Выберите ограничение для промокода (пополнение <b>{value}₽</b>):"
    await message.answer(text, reply_markup=kb, parse_mode="HTML")
    await state.set_state(PromoStates.create_choose_limit)

@router.callback_query(F.data == "promo_limit_uses", PromoStates.create_choose_limit)
async def promo_create_limit_uses(call: CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="promo_create")],
    ])
    text = "Введите количество активаций для промокода:"
    if call.message.content_type == "photo":
        await call.message.edit_caption(caption=text, reply_markup=kb, parse_mode="HTML")
    else:
        await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await state.set_state(PromoStates.create_input_uses)
    await call.answer()

@router.message(PromoStates.create_input_uses)
async def promo_create_input_uses_msg(message: Message, state: FSMContext, db_pool):
    try:
        uses = int(message.text.strip())
        if uses <= 0:
            raise ValueError
    except Exception:
        await message.answer("Введите корректное количество активаций (целое число > 0):")
        return
    data = await state.get_data()
    await create_promo(db_pool, data['promo_name'], data['promo_sum'], data.get('promo_type', 'balance'), max_uses=uses)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="В админ-панель", callback_data="admin_panel")]
    ])
    await message.answer(f"Промокод <code>{data['promo_name']}</code> создан!", reply_markup=kb, parse_mode="HTML")
    await state.clear()

@router.callback_query(F.data == "promo_limit_time", PromoStates.create_choose_limit)
async def promo_create_limit_time(call: CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="promo_create")],
    ])
    text = "Введите время действия промокода в минутах (или 0 для неограниченно):"
    if call.message.content_type == "photo":
        await call.message.edit_caption(caption=text, reply_markup=kb, parse_mode="HTML")
    else:
        await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await state.set_state(PromoStates.create_input_time)
    await call.answer()

@router.message(PromoStates.create_input_time)
async def promo_create_input_time_msg(message: Message, state: FSMContext, db_pool):
    try:
        minutes = int(message.text.strip())
        if minutes < 0:
            raise ValueError
    except Exception:
        await message.answer("Введите корректное время (целое число >= 0):")
        return
    data = await state.get_data()
    await create_promo(db_pool, data['promo_name'], data['promo_sum'], data.get('promo_type', 'balance'), expires_minutes=minutes)
    await message.answer(f"Промокод <code>{data['promo_name']}</code> создан!", parse_mode="HTML")
    await state.clear()

@router.callback_query(F.data == "promo_delete", PromoStates.menu)
async def promo_delete_choose(call: CallbackQuery, state: FSMContext, db_pool):
    promos = await get_active_promos(db_pool)
    kb = []
    for promo in promos:
        kb.append([InlineKeyboardButton(text=promo['code'], callback_data=f"promo_delete_promo_{promo['code']}")])
    kb.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_promos")])
    markup = InlineKeyboardMarkup(inline_keyboard=kb)
    text = "Выберите промокод для удаления:"
    await call.message.edit_caption(caption=text, reply_markup=markup, parse_mode="HTML")
    await state.set_state(PromoStates.delete_choose)
    await call.answer()

@router.callback_query(F.data.startswith("promo_delete_promo_"), PromoStates.delete_choose)
async def promo_delete_confirm(call: CallbackQuery, state: FSMContext, db_pool):
    code = call.data.replace("promo_delete_promo_", "")
    await delete_promo(db_pool, code)
    await call.message.answer(f"Промокод <code>{code}</code> удалён!", parse_mode="HTML")
    await state.clear()
    await admin_promos_menu(call, state)

@router.callback_query(F.data == "promo_active")
async def promo_active_list_universal(call: CallbackQuery, state: FSMContext, db_pool):
    promos = await get_active_promos(db_pool)
    kb = []
    for promo in promos:
        kb.append([InlineKeyboardButton(text=promo['code'], callback_data=f"promo_stats_{promo['code']}")])
    kb.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_promos")])
    markup = InlineKeyboardMarkup(inline_keyboard=kb)
    text = "Активные промокоды:"
    if call.message.content_type == "photo":
        await call.message.edit_caption(caption=text, reply_markup=markup, parse_mode="HTML")
    else:
        await call.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    await state.set_state(PromoStates.show_active)
    await call.answer()

@router.callback_query(F.data.startswith("promo_stats_"), PromoStates.show_active)
async def promo_show_stats(call: CallbackQuery, state: FSMContext, db_pool):
    code = call.data.replace("promo_stats_", "")
    promo, uses = await get_promo_stats(db_pool, code)
    if not promo:
        await call.message.answer("Промокод не найден.", parse_mode="HTML")
        await state.clear()
        await admin_promos_menu(call, state)
        return
    if promo['promo_type'] == 'discount':
        value_str = f"Скидка: {promo['value']}%"
    else:
        value_str = f"Сумма: {promo['value']} ₽"
    text = (
        f"<b>Промокод:</b> <code>{promo['code']}</code>\n"
        f"<b>{value_str}</b>\n"
        f"<b>Ограничение:</b> "
    )
    if promo['max_uses']:
        text += f"{promo['max_uses']} использований\n"
    elif promo['expires_at']:
        text += f"до {promo['expires_at'].strftime('%d.%m.%Y %H:%M')}\n"
    else:
        text += "Без ограничений\n"
    text += f"<b>Использовано:</b> {uses} раз(а)\n"
    text += f"<b>Статус:</b> {'Активен' if promo['is_active'] else 'Неактивен'}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="promo_active")],
    ])
    if call.message.content_type == "photo":
        await call.message.edit_caption(caption=text, reply_markup=kb, parse_mode="HTML")
    else:
        await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await state.set_state(PromoStates.show_active)
    await call.answer()

# --- Вспомогательные функции для работы с промокодами ---
async def generate_promo_code(pool):
    # Генерируем уникальный промокод
    for _ in range(10):
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        async with pool.acquire() as conn:
            exists = await conn.fetchval("SELECT 1 FROM promo_codes WHERE code=$1", code)
        if not exists:
            return code
    raise Exception("Не удалось сгенерировать уникальный промокод")

async def create_promo(pool, code, value, promo_type, max_uses=None, expires_minutes=None):
    now = datetime.now(timezone.utc)
    expires_at = None
    if expires_minutes and int(expires_minutes) > 0:
        expires_at = now + timedelta(minutes=int(expires_minutes))
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO promo_codes (code, promo_type, value, max_uses, current_uses, created_at, expires_at, is_active)
            VALUES ($1, $2, $3, $4, 0, $5, $6, true)
            """,
            code, promo_type, float(value), int(max_uses) if max_uses else (None if expires_at else 1), now, expires_at
        )

async def get_active_promos(pool):
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM promo_codes WHERE is_active=true ORDER BY created_at DESC")
    return rows

async def delete_promo(pool, code):
    async with pool.acquire() as conn:
        promo_id = await conn.fetchval("SELECT id FROM promo_codes WHERE code=$1", code)
        if promo_id:
            await conn.execute("DELETE FROM promo_history WHERE promo_code_id=$1", promo_id)
            await conn.execute("DELETE FROM promo_codes WHERE id=$1", promo_id)

async def get_promo_stats(pool, code):
    async with pool.acquire() as conn:
        promo = await conn.fetchrow("SELECT * FROM promo_codes WHERE code=$1", code)
        uses = await conn.fetchval("SELECT COUNT(*) FROM promo_history WHERE promo_code_id=(SELECT id FROM promo_codes WHERE code=$1)", code)
    return promo, uses

@router.message(PromoUserStates.waiting_for_code)
async def promo_activate_success(message: Message, db_pool, bot, state: FSMContext):
    code = message.text.strip().upper()
    user_id = message.from_user.id
    async with db_pool.acquire() as conn:
        promo = await conn.fetchrow("SELECT * FROM promo_codes WHERE code=$1 AND is_active=true", code)
        if not promo:
            await message.answer("Промокод не найден или неактивен.")
            return
        # Проверка на срок действия
        if promo['expires_at'] and promo['expires_at'] < datetime.now(timezone.utc):
            await message.answer("Срок действия промокода истёк.")
            return
        # Проверка на количество использований
        if promo['max_uses'] and promo['current_uses'] >= promo['max_uses']:
            await message.answer("Промокод уже использован максимальное количество раз.")
            return
        # Проверка, использовал ли уже этот пользователь
        used = await conn.fetchval("SELECT 1 FROM promo_history WHERE user_id=$1 AND promo_code_id=$2", user_id, promo['id'])
        if used:
            await message.answer("Вы уже использовали этот промокод.")
            return
        # Всё ок — начисляем баланс или скидку
        if promo['promo_type'] == 'discount':
            await conn.execute("UPDATE promo_codes SET current_uses = current_uses + 1 WHERE id=$1", promo['id'])
            await conn.execute("INSERT INTO promo_history (user_id, promo_code_id, used_at) VALUES ($1, $2, $3)", user_id, promo['id'], datetime.now(timezone.utc))
            # Проверяем, достигнут ли лимит и удаляем историю и сам промокод
            updated_promo = await conn.fetchrow("SELECT current_uses, max_uses FROM promo_codes WHERE id=$1", promo['id'])
            if updated_promo['max_uses'] and updated_promo['current_uses'] >= updated_promo['max_uses']:
                await conn.execute("DELETE FROM promo_history WHERE promo_code_id=$1", promo['id'])
                await conn.execute("DELETE FROM promo_codes WHERE id=$1", promo['id'])
            # Сохраняем скидку в базе пользователя
            await conn.execute("UPDATE users SET discount=$1 WHERE telegram_id=$2", promo['value'], user_id)
            await message.answer(f"🎉 Промокод <code>{code}</code> успешно активирован! Ваша персональная скидка <b>{promo['value']}%</b> будет применена к следующей покупке.", parse_mode="HTML")
        else:
            await conn.execute("UPDATE users SET balance = balance + $1 WHERE telegram_id=$2", promo['value'], user_id)
            await conn.execute("UPDATE promo_codes SET current_uses = current_uses + 1 WHERE id=$1", promo['id'])
            await conn.execute("INSERT INTO promo_history (user_id, promo_code_id, used_at) VALUES ($1, $2, $3)", user_id, promo['id'], datetime.now(timezone.utc))
            # Проверяем, достигнут ли лимит и удаляем историю и сам промокод
            updated_promo = await conn.fetchrow("SELECT current_uses, max_uses FROM promo_codes WHERE id=$1", promo['id'])
            if updated_promo['max_uses'] and updated_promo['current_uses'] >= updated_promo['max_uses']:
                await conn.execute("DELETE FROM promo_history WHERE promo_code_id=$1", promo['id'])
                await conn.execute("DELETE FROM promo_codes WHERE id=$1", promo['id'])
            await message.answer(f"🎉 Промокод <code>{code}</code> успешно активирован! Баланс пополнен на <b>{promo['value']} ₽</b>.", parse_mode="HTML")
    await cmd_start(message, bot, db_pool)

class PriceStates(StatesGroup):
    menu = State()
    stars_show = State()
    stars_input = State()
    stars_confirm = State()
    premium_choose = State()
    premium_show = State()
    premium_input = State()
    premium_confirm = State()

@router.callback_query(F.data == "admin_prices")
async def admin_prices_menu(call: CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Цены на звезды", callback_data="price_stars")],
        [InlineKeyboardButton(text="Цены на премиум", callback_data="price_premium")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")],
    ])
    await call.message.edit_caption(
        caption="<b>Управление ценами</b>\n\nВыберите действие:",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await state.set_state(PriceStates.menu)
    await call.answer()

@router.callback_query(F.data == "price_stars", PriceStates.menu)
async def price_stars_show(call: CallbackQuery, state: FSMContext, db_pool):
    star_price = await get_star_price(db_pool)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Изменить цену", callback_data="price_stars_input")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_prices")],
    ])
    await call.message.edit_caption(
        caption=f"<b>Текущая цена за 1 звезду:</b> <code>{star_price}</code> ₽\n\nВведите новую цену или нажмите 'Изменить цену'.",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await state.set_state(PriceStates.stars_show)
    await call.answer()

@router.callback_query(F.data == "price_stars_input", PriceStates.stars_show)
async def price_stars_input(call: CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="price_stars")],
    ])
    await call.message.edit_caption(
        caption="<b>Введите новую цену за 1 звезду:</b>",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await state.set_state(PriceStates.stars_input)
    await call.answer()

@router.message(PriceStates.stars_input)
async def price_stars_input_msg(message: Message, state: FSMContext):
    try:
        price = float(message.text.replace(",", "."))
        if price <= 0:
            raise ValueError
    except Exception:
        await message.answer("Введите корректную цену (например, 1.8):")
        return
    await state.update_data(new_star_price=price)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data="price_stars_confirm")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="price_stars")],
    ])
    await message.answer(f"Подтвердить изменение цены за 1 звезду на <b>{price}₽</b>?", reply_markup=kb, parse_mode="HTML")
    await state.set_state(PriceStates.stars_confirm)

@router.callback_query(F.data == "price_stars_confirm", PriceStates.stars_confirm)
async def price_stars_confirm(call: CallbackQuery, state: FSMContext, db_pool):
    data = await state.get_data()
    price = data.get("new_star_price")
    await set_star_price(db_pool, price)
    await call.message.answer(f"Цена за 1 звезду успешно изменена на <b>{price}₽</b>.", parse_mode="HTML")
    await state.clear()
    await call.message.answer("<b>⚙️ Админ панель</b>\n\nВыберите действие:", reply_markup=admin_panel_kb(), parse_mode="HTML")
    await call.answer()

@router.callback_query(F.data == "price_premium")
async def price_premium_choose(call: CallbackQuery, state: FSMContext, db_pool):
    premium_prices = await get_premium_prices(db_pool)
    from handlers.start import PREMIUM_PLANS
    kb = InlineKeyboardMarkup(inline_keyboard=[
        *[[InlineKeyboardButton(text=f"{plan['name']} — {premium_prices[i]}₽", callback_data=f"price_premium_{i}")]
          for i, plan in enumerate(PREMIUM_PLANS)],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_prices")],
    ])
    text = "<b>Выберите тариф для изменения цены:</b>"
    if call.message.content_type == "photo":
        await call.message.edit_caption(
            caption=text,
            reply_markup=kb,
            parse_mode="HTML"
        )
    else:
        await call.message.edit_text(
            text,
            reply_markup=kb,
            parse_mode="HTML"
        )
    await state.set_state(PriceStates.premium_choose)
    await call.answer()

@router.callback_query(F.data.startswith("price_premium_"), PriceStates.premium_choose)
async def price_premium_show(call: CallbackQuery, state: FSMContext, db_pool):
    premium_prices = await get_premium_prices(db_pool)
    from handlers.start import PREMIUM_PLANS
    plan_index = int(call.data.split("_")[-1])
    plan = PREMIUM_PLANS[plan_index]
    price = premium_prices[plan_index]
    await state.update_data(plan_index=plan_index)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Изменить цену", callback_data="price_premium_input")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="price_premium")],
    ])
    text = f"<b>Тариф:</b> {plan['name']}\n<b>Текущая цена:</b> <code>{price}</code> ₽\n\nВведите новую цену или нажмите 'Изменить цену'."
    if call.message.content_type == "photo":
        await call.message.edit_caption(
            caption=text,
            reply_markup=kb,
            parse_mode="HTML"
        )
    else:
        await call.message.edit_text(
            text,
            reply_markup=kb,
            parse_mode="HTML"
        )
    await state.set_state(PriceStates.premium_show)
    await call.answer()

@router.callback_query(F.data == "price_premium_input", PriceStates.premium_show)
async def price_premium_input(call: CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="price_premium")],
    ])
    await call.message.edit_caption(
        caption="<b>Введите новую цену для выбранного тарифа:</b>",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await state.set_state(PriceStates.premium_input)
    await call.answer()

@router.message(PriceStates.premium_input)
async def price_premium_input_msg(message: Message, state: FSMContext):
    try:
        price = float(message.text.replace(",", "."))
        if price <= 0:
            raise ValueError
    except Exception:
        await message.answer("Введите корректную цену (например, 799):")
        return
    await state.update_data(new_premium_price=price)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data="price_premium_confirm")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="price_premium")],
    ])
    await message.answer(f"Подтвердить изменение цены на <b>{price}₽</b>?", reply_markup=kb, parse_mode="HTML")
    await state.set_state(PriceStates.premium_confirm)

@router.callback_query(F.data == "price_premium_confirm", PriceStates.premium_confirm)
async def price_premium_confirm(call: CallbackQuery, state: FSMContext, db_pool):
    data = await state.get_data()
    price = data.get("new_premium_price")
    plan_index = data.get("plan_index")
    await set_premium_price(db_pool, plan_index, price)
    await call.message.answer(f"Цена тарифа успешно изменена на <b>{price}₽</b>.", parse_mode="HTML")
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Выбрать другой тариф", callback_data="price_premium")],
        [InlineKeyboardButton(text="В админ-панель", callback_data="admin_panel")],
    ])
    await call.message.answer("Что дальше?", reply_markup=kb, parse_mode="HTML")
    await call.answer()

class BroadcastStates(StatesGroup):
    choose_type = State()
    waiting_for_text = State()
    waiting_for_photo = State()
    confirm_text = State()
    confirm_photo = State()

@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_menu(call: CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Текст", callback_data="broadcast_text"),
            InlineKeyboardButton(text="Текст+Фото", callback_data="broadcast_photo")
        ],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")]
    ])
    await call.message.edit_caption(
        caption="<b>Рассылка</b>\n\nВыберите тип рассылки:",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await state.set_state(BroadcastStates.choose_type)
    await call.answer()

@router.callback_query(F.data == "broadcast_text", BroadcastStates.choose_type)
async def broadcast_text_start(call: CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_broadcast")]
    ])
    await call.message.edit_caption(
        caption=(
            "<b>Введите текст для рассылки:</b>\n\n"
            "<i>Можно использовать HTML:</i>\n"
            "&lt;b&gt;жирный&lt;/b&gt;\n"
            "&lt;i&gt;курсив&lt;/i&gt;\n"
            "&lt;u&gt;подчёркнутый&lt;/u&gt;\n"
            "&lt;s&gt;зачёркнутый&lt;/s&gt;\n"
            "&lt;code&gt;код&lt;/code&gt;\n"
            "&lt;pre&gt;блок кода&lt;/pre&gt;\n"
            "&lt;a href='https://site.ru'&gt;ссылка&lt;/a&gt;\n"
            "&lt;tg-spoiler&gt;спойлер&lt;/tg-spoiler&gt;"
        ),
        reply_markup=kb,
        parse_mode="HTML"
    )
    await state.set_state(BroadcastStates.waiting_for_text)
    await call.answer()

@router.message(BroadcastStates.waiting_for_text)
async def broadcast_text_input(message: Message, state: FSMContext):
    # Сохраняем только message.text, чтобы не экранировать HTML
    await state.update_data(broadcast_text=message.text)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data="broadcast_confirm_text")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_broadcast")]
    ])
    await message.answer(
        f"<b>Текст рассылки:</b>\n{message.text}\n\nПодтвердить отправку?",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await state.set_state(BroadcastStates.confirm_text)

@router.callback_query(F.data == "broadcast_confirm_text", BroadcastStates.confirm_text)
async def broadcast_text_confirm(call: CallbackQuery, state: FSMContext, db_pool, bot):
    data = await state.get_data()
    text = data.get("broadcast_text")
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT telegram_id FROM users")
    count = 0
    errors = 0
    for row in rows:
        try:
            await bot.send_message(row["telegram_id"], text, parse_mode="HTML")
            count += 1
        except Exception:
            errors += 1
    await call.message.answer(f"Рассылка завершена!\nУспешно: {count}\nОшибок: {errors}")
    await state.clear()
    # Отправляем админ-панель отдельным новым сообщением
    await call.message.answer("<b>⚙️ Админ панель</b>\n\nВыберите действие:",
        reply_markup=admin_panel_kb(),
        parse_mode="HTML"
    )

@router.callback_query(F.data == "broadcast_photo", BroadcastStates.choose_type)
async def broadcast_photo_start(call: CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_broadcast")]
    ])
    await call.message.edit_caption(
        caption=(
            "<b>Загрузите фото с подписью для рассылки:</b>\n\n"
            "<i>Можно использовать HTML:</i>\n"
            "&lt;b&gt;жирный&lt;/b&gt;\n"
            "&lt;i&gt;курсив&lt;/i&gt;\n"
            "&lt;u&gt;подчёркнутый&lt;/u&gt;\n"
            "&lt;s&gt;зачёркнутый&lt;/s&gt;\n"
            "&lt;code&gt;код&lt;/code&gt;\n"
            "&lt;pre&gt;блок кода&lt;/pre&gt;\n"
            "&lt;a href='https://site.ru'&gt;ссылка&lt;/a&gt;\n"
            "&lt;tg-spoiler&gt;спойлер&lt;/tg-spoiler&gt;"
        ),
        reply_markup=kb,
        parse_mode="HTML"
    )
    await state.set_state(BroadcastStates.waiting_for_photo)
    await call.answer()

@router.message(BroadcastStates.waiting_for_photo)
async def broadcast_photo_input(message: Message, state: FSMContext):
    if not message.photo:
        await message.answer("Пожалуйста, отправьте фото с подписью.")
        return
    await state.update_data(broadcast_photo=message.photo[-1].file_id, broadcast_caption=message.caption)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data="broadcast_confirm_photo")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_broadcast")]
    ])
    await message.answer_photo(
        message.photo[-1].file_id,
        caption=f"<b>Подпись:</b>\n{message.caption}\n\nПодтвердить отправку?",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await state.set_state(BroadcastStates.confirm_photo)

@router.callback_query(F.data == "broadcast_confirm_photo", BroadcastStates.confirm_photo)
async def broadcast_photo_confirm(call: CallbackQuery, state: FSMContext, db_pool, bot):
    data = await state.get_data()
    photo_id = data.get("broadcast_photo")
    caption = data.get("broadcast_caption")
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT telegram_id FROM users")
    count = 0
    errors = 0
    for row in rows:
        try:
            await bot.send_photo(row["telegram_id"], photo_id, caption=caption, parse_mode="HTML")
            count += 1
        except Exception:
            errors += 1
    await call.message.answer(f"Рассылка с фото завершена!\nУспешно: {count}\nОшибок: {errors}")
    await state.clear()
    # Отправляем админ-панель отдельным новым сообщением
    await call.message.answer("<b>⚙️ Админ панель</b>\n\nВыберите действие:",
        reply_markup=admin_panel_kb(),
        parse_mode="HTML"
    )
    await call.answer()

# --- Работа с ценами (settings) ---
async def get_star_price(db_pool):
    async with db_pool.acquire() as conn:
        value = await conn.fetchval("SELECT value FROM settings WHERE key='star_price'")
        return float(value) if value else 1.8

async def set_star_price(db_pool, price):
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE settings SET value=$1 WHERE key='star_price'", str(price))

async def get_premium_prices(db_pool):
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT key, value FROM settings WHERE key LIKE 'premium_price_%' ORDER BY key")
        return [float(row['value']) for row in sorted(rows, key=lambda r: int(r['key'].split('_')[-1]))]

async def set_premium_price(db_pool, index, price):
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE settings SET value=$1 WHERE key=$2", str(price), f'premium_price_{index}')

# --- Использование цен в расчетах ---
# Везде, где используется STAR_PRICE, замените на await get_star_price(db_pool)
# Для премиум-цен используйте await get_premium_prices(db_pool)

@router.callback_query(F.data == "price_stars", PriceStates.menu)
async def price_stars_show(call: CallbackQuery, state: FSMContext, db_pool):
    star_price = await get_star_price(db_pool)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Изменить цену", callback_data="price_stars_input")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_prices")],
    ])
    await call.message.edit_caption(
        caption=f"<b>Текущая цена за 1 звезду:</b> <code>{star_price}</code> ₽\n\nВведите новую цену или нажмите 'Изменить цену'.",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await state.set_state(PriceStates.stars_show)
    await call.answer()

@router.callback_query(F.data == "price_stars_confirm", PriceStates.stars_confirm)
async def price_stars_confirm(call: CallbackQuery, state: FSMContext, db_pool):
    data = await state.get_data()
    price = data.get("new_star_price")
    await set_star_price(db_pool, price)
    await call.message.answer(f"Цена за 1 звезду успешно изменена на <b>{price}₽</b>.", parse_mode="HTML")
    await state.clear()
    await call.message.answer("<b>⚙️ Админ панель</b>\n\nВыберите действие:", reply_markup=admin_panel_kb(), parse_mode="HTML")
    await call.answer()

@router.callback_query(F.data == "price_premium")
async def price_premium_choose(call: CallbackQuery, state: FSMContext, db_pool):
    premium_prices = await get_premium_prices(db_pool)
    from handlers.start import PREMIUM_PLANS
    kb = InlineKeyboardMarkup(inline_keyboard=[
        *[[InlineKeyboardButton(text=f"{plan['name']} — {premium_prices[i]}₽", callback_data=f"price_premium_{i}")]
          for i, plan in enumerate(PREMIUM_PLANS)],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_prices")],
    ])
    text = "<b>Выберите тариф для изменения цены:</b>"
    if call.message.content_type == "photo":
        await call.message.edit_caption(
            caption=text,
            reply_markup=kb,
            parse_mode="HTML"
        )
    else:
        await call.message.edit_text(
            text,
            reply_markup=kb,
            parse_mode="HTML"
        )
    await state.set_state(PriceStates.premium_choose)
    await call.answer()

@router.callback_query(F.data.startswith("price_premium_"), PriceStates.premium_choose)
async def price_premium_show(call: CallbackQuery, state: FSMContext, db_pool):
    premium_prices = await get_premium_prices(db_pool)
    from handlers.start import PREMIUM_PLANS
    plan_index = int(call.data.split("_")[-1])
    plan = PREMIUM_PLANS[plan_index]
    price = premium_prices[plan_index]
    await state.update_data(plan_index=plan_index)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Изменить цену", callback_data="price_premium_input")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="price_premium")],
    ])
    await call.message.edit_caption(
        caption=f"<b>Тариф:</b> {plan['name']}\n<b>Текущая цена:</b> <code>{price}</code> ₽\n\nВведите новую цену или нажмите 'Изменить цену'.",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await state.set_state(PriceStates.premium_show)
    await call.answer()

@router.callback_query(F.data == "price_premium_input", PriceStates.premium_show)
async def price_premium_input(call: CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="price_premium")],
    ])
    await call.message.edit_caption(
        caption="<b>Введите новую цену для выбранного тарифа:</b>",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await state.set_state(PriceStates.premium_input)
    await call.answer()

@router.message(PriceStates.premium_input)
async def price_premium_input_msg(message: Message, state: FSMContext):
    try:
        price = float(message.text.replace(",", "."))
        if price <= 0:
            raise ValueError
    except Exception:
        await message.answer("Введите корректную цену (например, 799):")
        return
    await state.update_data(new_premium_price=price)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data="price_premium_confirm")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="price_premium")],
    ])
    await message.answer(f"Подтвердить изменение цены на <b>{price}₽</b>?", reply_markup=kb, parse_mode="HTML")
    await state.set_state(PriceStates.premium_confirm)

@router.callback_query(F.data == "price_premium_confirm", PriceStates.premium_confirm)
async def price_premium_confirm(call: CallbackQuery, state: FSMContext, db_pool):
    data = await state.get_data()
    price = data.get("new_premium_price")
    plan_index = data.get("plan_index")
    await set_premium_price(db_pool, plan_index, price)
    await call.message.answer(f"Цена тарифа успешно изменена на <b>{price}₽</b>.", parse_mode="HTML")
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Выбрать другой тариф", callback_data="price_premium")],
        [InlineKeyboardButton(text="В админ-панель", callback_data="admin_panel")],
    ])
    await call.message.answer("Что дальше?", reply_markup=kb, parse_mode="HTML")
    await call.answer()

# --- Фоновая задача для удаления просроченных промокодов ---
from datetime import datetime, timezone

async def delete_expired_promos(db_pool):
    async with db_pool.acquire() as conn:
        # Сначала удаляем историю, чтобы не было внешних ключей
        await conn.execute("""
            DELETE FROM promo_history WHERE promo_code_id IN (
                SELECT id FROM promo_codes WHERE expires_at IS NOT NULL AND expires_at < $1
            )
        """, datetime.now(timezone.utc))
        await conn.execute("""
            DELETE FROM promo_codes WHERE expires_at IS NOT NULL AND expires_at < $1
        """, datetime.now(timezone.utc))

class PaymentSettingsStates(StatesGroup):
    choose_system = State()
    choose_action = State()
    waiting_for_min_amount = State()
    waiting_for_exchange_rate = State()

@router.callback_query(F.data == "admin_payment_settings")
async def admin_payment_settings_menu(call: CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="SBP", callback_data="admin_payment_sbp")],
        [InlineKeyboardButton(text="Crypto", callback_data="admin_payment_crypto")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")],
    ])
    text = "<b>Настройки пополнения</b>\n\nВыберите платёжную систему:"
    if getattr(call.message, "content_type", None) == "photo":
        await call.message.edit_caption(
            caption=text,
            reply_markup=kb,
            parse_mode="HTML"
        )
    else:
        await call.message.edit_text(
            text,
            reply_markup=kb,
            parse_mode="HTML"
        )
    await state.set_state(PaymentSettingsStates.choose_system)
    await call.answer()

@router.callback_query(F.data.startswith("admin_payment_"), PaymentSettingsStates.choose_system)
async def admin_payment_choose_action(call: CallbackQuery, state: FSMContext, db_pool):
    system = call.data.replace("admin_payment_", "")
    await state.update_data(system=system)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Изменить минимальную сумму", callback_data="admin_payment_min")],
        *([[InlineKeyboardButton(text="Изменить курс USD/RUB", callback_data="admin_payment_rate")]] if system == "crypto" else []),
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_payment_settings")],
    ])
    # Получить текущие значения
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM payment_settings WHERE system=$1", system)
    text = f"<b>Настройки для {system.upper()}</b>\n"
    if row:
        text += f"Минимальная сумма: <b>{row['min_amount']} {row['currency']}</b>\n"
        if system == "crypto":
            text += f"Курс: <b>1 USD = {row['exchange_rate']} RUB</b>\n"
    else:
        text += "Нет данных."
    await call.message.edit_caption(
        caption=text + "\nВыберите действие:",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await state.set_state(PaymentSettingsStates.choose_action)
    await call.answer()

@router.callback_query(F.data == "admin_payment_min", PaymentSettingsStates.choose_action)
async def admin_payment_min_start(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    system = data.get("system")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_payment_settings")],
    ])
    await call.message.edit_caption(
        caption=f"<b>Изменить минимальную сумму для {system.upper()}</b>\n\nВведите новую минимальную сумму:",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await state.set_state(PaymentSettingsStates.waiting_for_min_amount)
    await call.answer()

@router.message(PaymentSettingsStates.waiting_for_min_amount)
async def admin_payment_min_set(message: Message, state: FSMContext, db_pool):
    try:
        min_amount = float(message.text.replace(",", "."))
        if min_amount <= 0:
            raise ValueError
    except Exception:
        await message.answer("Введите корректную сумму (число больше 0):")
        return
    data = await state.get_data()
    system = data.get("system")
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE payment_settings SET min_amount=$1, updated_at=NOW() WHERE system=$2",
            min_amount, system
        )
    await message.answer(f"Минимальная сумма для {system.upper()} успешно изменена на <b>{min_amount}</b>.", parse_mode="HTML")
    await state.clear()
    from config import load_config
    config = load_config()
    try:
        await message.answer_photo(
            config.welcome_image_url,
            caption="<b>⚙️ Админ панель</b>\n\nВыберите действие:",
            reply_markup=admin_panel_kb(),
            parse_mode="HTML"
        )
    except Exception as e:
        print(f"Не удалось отправить фото админ-панели: {e}")

@router.callback_query(F.data == "admin_payment_rate", PaymentSettingsStates.choose_action)
async def admin_payment_rate_start(call: CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_payment_settings")],
    ])
    await call.message.edit_caption(
        caption="<b>Изменить курс USD/RUB</b>\n\nВведите новый курс (сколько рублей за 1 USD):",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await state.set_state(PaymentSettingsStates.waiting_for_exchange_rate)
    await call.answer()

@router.message(PaymentSettingsStates.waiting_for_exchange_rate)
async def admin_payment_rate_set(message: Message, state: FSMContext, db_pool):
    try:
        rate = float(message.text.replace(",", "."))
        if rate <= 0:
            raise ValueError
    except Exception:
        await message.answer("Введите корректный курс (число больше 0):")
        return
    data = await state.get_data()
    system = data.get("system")
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE payment_settings SET exchange_rate=$1, updated_at=NOW() WHERE system=$2",
            rate, system
        )
    await message.answer(f"Курс для {system.upper()} успешно изменён: <b>1 USD = {rate} RUB</b>.", parse_mode="HTML")
    await state.clear()
    from config import load_config
    config = load_config()
    try:
        await message.answer_photo(
            config.welcome_image_url,
            caption="<b>⚙️ Админ панель</b>\n\nВыберите действие:",
            reply_markup=admin_panel_kb(),
            parse_mode="HTML"
        )
    except Exception as e:
        print(f"Не удалось отправить фото админ-панели: {e}")

@router.callback_query(F.data == "buy_stars", BuyStarsGiftStates.waiting_for_recipient)
async def back_from_gift_recipient(call: CallbackQuery, state: FSMContext):
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🧑‍💼 Себе", callback_data="buy_stars_self"),
            InlineKeyboardButton(text="🎁 Другому", callback_data="buy_stars_gift")
        ],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ])
    await call.message.edit_caption(
        caption="<b>Купить звёзды</b>\n\nКому вы хотите купить звёзды?",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await call.answer()

@router.callback_query(F.data == "buy_premium", BuyPremiumStates.waiting_for_gift_recipient)
async def back_from_premium_gift_recipient(call: CallbackQuery, state: FSMContext):
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🧑‍💼 Себе", callback_data="buy_premium_self"),
            InlineKeyboardButton(text="🎁 Другому", callback_data="buy_premium_gift")
        ],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ])
    from config import load_config
    config = load_config()
    await call.message.answer_photo(
        config.welcome_image_url,
        caption="<b>Купить премиум</b>\n\nКому вы хотите купить премиум?",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await call.answer()

@router.callback_query(F.data == "buy_premium_gift", BuyPremiumStates.waiting_for_gift_plan)
async def back_from_premium_gift_plan(call: CallbackQuery, state: FSMContext):
    kb = []
    for i, plan in enumerate(PREMIUM_PLANS):
        price = await get_premium_prices(call.data.get('db_pool')) if hasattr(call.data, 'get') else [plan['price'] for plan in PREMIUM_PLANS]
        btn_text = f"💎 {plan['name']} — {price[i]}₽"
        kb.append([
            InlineKeyboardButton(
                text=btn_text,
                callback_data=f"buy_premium_gift_plan_{i}"
            )
        ])
    kb.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="buy_premium_gift")])
    await call.message.edit_caption(
        caption="<b>Выберите тариф для подарка:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb),
        parse_mode="HTML"
    )
    await state.set_state(BuyPremiumStates.waiting_for_gift_plan)
    await call.answer()