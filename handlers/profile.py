from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from config import load_config
import time
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
import httpx
import hmac
import hashlib
import json
import base64
from aiogram.exceptions import TelegramBadRequest
from datetime import datetime, timezone
from utils.payment_models import create_mulenpay_invoice, create_heleket_invoice
from aiogram.types import InputTextMessageContent

router = Router()
config = load_config()

# Добавить курс рубль-доллар (можно вынести в конфиг)
RUB_TO_USD = 75  # обновлённый курс рубль-доллар

class TopupSBPStates(StatesGroup):
    waiting_for_amount = State()

class PromoUserStates(StatesGroup):
    waiting_for_code = State()

class TopupCryptoStates(StatesGroup):
    waiting_for_amount = State()

async def get_or_create_user(pool, telegram_id, username, invited_by=None):
    async with pool.acquire() as conn:
        user = await conn.fetchrow("SELECT * FROM users WHERE telegram_id=$1", telegram_id)
        if not user:
            await conn.execute(
                "INSERT INTO users (telegram_id, username, invited_by) VALUES ($1, $2, $3)", telegram_id, username, invited_by
            )
            user = await conn.fetchrow("SELECT * FROM users WHERE telegram_id=$1", telegram_id)
        return user

async def get_ref_stats(pool, telegram_id):
    async with pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM users WHERE invited_by=$1", telegram_id)
        # Сумма всех бонусов, начисленных этому пользователю (5% от пополнений рефералов)
        bonus = await conn.fetchval(
            """
            SELECT COALESCE(SUM(ROUND(amount * 0.05, 2)), 0)
            FROM payments
            WHERE user_id IN (SELECT telegram_id FROM users WHERE invited_by=$1) AND is_paid=true
            """, telegram_id
        )
        return count, bonus

def profile_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💰 Пополнить баланс", callback_data="profile_topup"),
            InlineKeyboardButton(text="🎟️ Промокоды", callback_data="profile_activate_promo")
        ],
        [
            InlineKeyboardButton(text="👥 Реферальная система", callback_data="profile_referral"),
            InlineKeyboardButton(text="📄 Публичная оферта", url=config.profile_offer_url)
        ],
        [
            InlineKeyboardButton(text="🔒 Политика конфиденциальности", url=config.profile_privacy_url)
        ],
        [
            InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")
        ]
    ])

@router.callback_query(F.data == "profile")
async def profile_callback(call: CallbackQuery, db_pool):
    user = await get_or_create_user(db_pool, call.from_user.id, call.from_user.username)
    text = (
        f"<b>Профиль</b>\n\n"
        f"ID: <code>{user['telegram_id']}</code>\n"
        f"Username: @{call.from_user.username or '-'}\n"
        f"Баланс: <b>{user['balance']} ₽</b>"
    )
    await call.message.edit_caption(
        caption=text,
        reply_markup=profile_kb(),
        parse_mode="HTML"
    )
    await call.answer()

@router.callback_query(F.data == "profile_topup")
async def profile_topup_callback(call: CallbackQuery, db_pool, state: FSMContext = None):
    if state:
        await state.clear()
    user = await get_or_create_user(db_pool, call.from_user.id, call.from_user.username)
    text = (
        f"<b>Пополнение баланса</b>\n\n"
        f"Ваш текущий баланс: <b>{user['balance']} ₽</b>\n\n"
        f"Выберите способ пополнения:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Банковская карта (СБП)", callback_data="topup_sbp")],
        [InlineKeyboardButton(text="Криптовалюта", callback_data="topup_crypto")],
        [InlineKeyboardButton(text="Назад", callback_data="profile")],
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
    await call.answer()

@router.callback_query(F.data == "profile_referral")
async def profile_referral_callback(call: CallbackQuery, db_pool):
    user = await get_or_create_user(db_pool, call.from_user.id, call.from_user.username)
    me = await call.bot.get_me()
    bot_username = me.username
    ref_link = f"https://t.me/{bot_username}?start={user['telegram_id']}"
    ref_count, ref_bonus = await get_ref_stats(db_pool, user['telegram_id'])
    text = (
        f"<b>Реферальная система</b>\n\n"
        f"Ваша реферальная ссылка:\n<code>{ref_link}</code>\n\n"
        f"Приглашайте друзей и получайте <b>5% от их пополнений</b>!\n\n"
        f"<i>Приглашено:</i> <b>{ref_count}</b>\n"
        f"<i>Заработано бонусов:</i> <b>{ref_bonus} ₽</b>\n"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Назад", callback_data="profile")],
    ])
    await call.message.edit_caption(
        caption=text,
        reply_markup=kb,
        parse_mode="HTML"
    )
    await call.answer()

@router.callback_query(F.data == "main_menu")
async def main_menu_callback(call: CallbackQuery):
    from handlers.start import main_menu_kb  # избегаем циклического импорта
    from config import load_config
    config = load_config()
    try:
        await call.message.edit_caption(
            caption=config.welcome_description,
            reply_markup=main_menu_kb(call.from_user.id),
            parse_mode="HTML"
        )
    except TelegramBadRequest:
        await call.message.delete()
        await call.message.answer_photo(
            config.welcome_image_url,
            caption=config.welcome_description,
            reply_markup=main_menu_kb(call.from_user.id),
            parse_mode="HTML"
        )
    await call.answer()

@router.callback_query(F.data == "profile_activate_promo")
async def profile_activate_promo_callback(call: CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="profile")],
    ])
    await call.message.edit_caption(
        caption="<b>Активация промокода</b>\n\nВведите промокод:",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await state.set_state(PromoUserStates.waiting_for_code)
    await call.answer()

@router.message(PromoUserStates.waiting_for_code)
async def promo_user_enter_code(message: Message, state: FSMContext, db_pool):
    code = message.text.strip().upper()
    user_id = message.from_user.id
    async with db_pool.acquire() as conn:
        promo = await conn.fetchrow("SELECT * FROM promo_codes WHERE code=$1 AND is_active=true", code)
        if not promo:
            await message.answer("❗ Промокод не найден или неактивен. Попробуйте другой или нажмите 'Назад'.")
            return
        # Проверка на срок действия
        if promo['expires_at'] and promo['expires_at'] < datetime.now(timezone.utc):
            await message.answer("❗ Срок действия промокода истёк.")
            return
        # Проверка на количество использований
        if promo['max_uses'] and promo['current_uses'] >= promo['max_uses']:
            await message.answer("❗ Промокод уже использован максимальное количество раз.")
            return
        # Проверка, использовал ли уже этот пользователь
        used = await conn.fetchval("SELECT 1 FROM promo_history WHERE user_id=$1 AND promo_code_id=$2", user_id, promo['id'])
        if used:
            await message.answer("❗ Вы уже использовали этот промокод.")
            return
        # --- Новая логика ---
        if promo['promo_type'] == 'discount':
            await state.update_data(active_discount=promo['value'])
            await conn.execute("UPDATE promo_codes SET current_uses = current_uses + 1 WHERE id=$1", promo['id'])
            await conn.execute("INSERT INTO promo_history (user_id, promo_code_id, used_at) VALUES ($1, $2, $3)", user_id, promo['id'], datetime.now(timezone.utc))
            await message.answer(f"🎉 Промокод <code>{code}</code> успешно активирован! Ваша скидка: <b>{promo['value']}%</b> на следующую покупку.", parse_mode="HTML")
            await state.clear()
            from handlers.start import main_menu_kb
            await message.answer("Главное меню:", reply_markup=main_menu_kb(message.from_user.id))
            return
        # --- Стандартное пополнение баланса ---
        await conn.execute("UPDATE users SET balance = balance + $1 WHERE telegram_id=$2", promo['value'], user_id)
        await conn.execute("UPDATE promo_codes SET current_uses = current_uses + 1 WHERE id=$1", promo['id'])
        await conn.execute("INSERT INTO promo_history (user_id, promo_code_id, used_at) VALUES ($1, $2, $3)", user_id, promo['id'], datetime.now(timezone.utc))
    await message.answer(f"🎉 Промокод <code>{code}</code> успешно активирован! Баланс пополнен на <b>{promo['value']} ₽</b>.", parse_mode="HTML")
    await state.clear()
    from handlers.start import main_menu_kb
    await message.answer("Главное меню:", reply_markup=main_menu_kb(message.from_user.id))

@router.callback_query(F.data == "profile_topup", TopupSBPStates.waiting_for_amount)
async def fsm_back_to_topup(call: CallbackQuery, state: FSMContext, db_pool):
    await state.clear()
    user = await get_or_create_user(db_pool, call.from_user.id, call.from_user.username)
    text = (
        f"<b>Пополнение баланса</b>\n\n"
        f"Ваш текущий баланс: <b>{user['balance']} ₽</b>\n\n"
        f"Выберите способ пополнения:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Банковская карта (СБП)", callback_data="topup_sbp")],
        [InlineKeyboardButton(text="Криптовалюта", callback_data="topup_crypto")],
        [InlineKeyboardButton(text="Назад", callback_data="profile")],
    ])
    await call.message.edit_caption(
        caption=text,
        reply_markup=kb,
        parse_mode="HTML"
    )
    await call.answer()

@router.callback_query(F.data == "topup_sbp")
async def topup_sbp_start(call: CallbackQuery, state: FSMContext, db_pool):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    # Получаем min_amount из БД
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT min_amount FROM payment_settings WHERE system='sbp'")
    min_amount = float(row['min_amount']) if row and row['min_amount'] else 10
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_topup_sbp")]
    ])
    await call.message.answer(
        f"Введите сумму пополнения в рублях (минимум {min_amount}):",
        reply_markup=kb
    )
    await state.update_data(min_amount=min_amount)
    await state.set_state(TopupSBPStates.waiting_for_amount)
    await call.answer()

@router.callback_query(F.data == "cancel_topup_sbp")
async def cancel_topup_sbp(call: CallbackQuery, state: FSMContext):
    await state.clear()
    from handlers.start import main_menu_kb
    from config import load_config
    config = load_config()
    try:
        await call.message.edit_caption(
            caption=config.welcome_description,
            reply_markup=main_menu_kb(call.from_user.id),
            parse_mode="HTML"
        )
    except Exception:
        await call.message.delete()
        await call.message.answer_photo(
            config.welcome_image_url,
            caption=config.welcome_description,
            reply_markup=main_menu_kb(call.from_user.id),
            parse_mode="HTML"
        )
    await call.answer()

@router.message(TopupSBPStates.waiting_for_amount)
async def topup_sbp_amount(message: Message, state: FSMContext, db_pool):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    data = await state.get_data()
    min_amount = data.get('min_amount', 10)
    try:
        amount = float(message.text.replace(",", "."))
    except Exception:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_topup_sbp")]
        ])
        await message.answer(
            f"❗ Введите корректную сумму (например, 100 или 250.50):\nМинимум: {min_amount}",
            reply_markup=kb
        )
        return
    if amount < min_amount:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_topup_sbp")]
        ])
        await message.answer(
            f"❗ Минимальная сумма пополнения — {min_amount}₽. Попробуйте снова:",
            reply_markup=kb
        )
        return
    user = await get_or_create_user(db_pool, message.from_user.id, message.from_user.username)
    unique_uuid = f"{user['telegram_id']}_{int(time.time())}"
    invoice = await create_mulenpay_invoice(unique_uuid, amount)
    # Сохраняем платёж в БД
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO payments (uuid, user_id, amount, is_paid, created_at)
            VALUES ($1, $2, $3, false, NOW())
            """,
            unique_uuid, user["telegram_id"], amount
        )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Оплатить", url=invoice['paymentUrl'])],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_topup_sbp")]
    ])
    await message.answer(
        f"Счёт на пополнение {amount}₽ создан!\n\nДля оплаты нажмите кнопку ниже:",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await state.clear()

@router.callback_query(F.data == "topup_crypto")
async def topup_crypto_start(call: CallbackQuery, state: FSMContext, db_pool):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    # Получаем min_amount из БД
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT min_amount, exchange_rate FROM payment_settings WHERE system='crypto'")
    min_amount = float(row['min_amount']) if row and row['min_amount'] else 75
    exchange_rate = float(row['exchange_rate']) if row and row['exchange_rate'] else 75
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_topup_crypto")]
    ])
    await call.message.answer(
        f"Введите сумму пополнения в рублях (минимум {min_amount}):\n\nТекущий курс: 1 USD = {exchange_rate} RUB",
        reply_markup=kb
    )
    await state.update_data(min_amount=min_amount, exchange_rate=exchange_rate)
    await state.set_state(TopupCryptoStates.waiting_for_amount)
    await call.answer()

@router.callback_query(F.data == "cancel_topup_crypto")
async def cancel_topup_crypto(call: CallbackQuery, state: FSMContext):
    await state.clear()
    from handlers.start import main_menu_kb
    from config import load_config
    config = load_config()
    try:
        await call.message.edit_caption(
            caption=config.welcome_description,
            reply_markup=main_menu_kb(call.from_user.id),
            parse_mode="HTML"
        )
    except Exception:
        await call.message.delete()
        await call.message.answer_photo(
            config.welcome_image_url,
            caption=config.welcome_description,
            reply_markup=main_menu_kb(call.from_user.id),
            parse_mode="HTML"
        )
    await call.answer()

@router.message(TopupCryptoStates.waiting_for_amount)
async def topup_crypto_amount(message: Message, state: FSMContext, db_pool):
    from config import load_config
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    config = load_config()
    data = await state.get_data()
    min_amount = data.get('min_amount', 75)
    exchange_rate = data.get('exchange_rate', 75)
    try:
        amount_rub = float(message.text.replace(",", "."))
    except Exception:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_topup_crypto")]
        ])
        await message.answer(
            f"❗ Введите корректную сумму в рублях (например, 100 или 250.50):\n\nТекущий курс: 1 USD = {exchange_rate} RUB",
            reply_markup=kb
        )
        return
    if amount_rub < min_amount:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_topup_crypto")]
        ])
        await message.answer(
            f"❗ Минимальная сумма пополнения — {min_amount} RUB. Попробуйте снова:\n\nТекущий курс: 1 USD = {exchange_rate} RUB",
            reply_markup=kb
        )
        return
    amount_usd = round(amount_rub / exchange_rate, 2)
    user = await get_or_create_user(db_pool, message.from_user.id, message.from_user.username)
    invoice = await create_heleket_invoice(
        user["telegram_id"],
        amount_usd,
        config.heleket_api_key,
        config.heleket_merchant_id,
        config.heleket_callback_url
    )
    # Проверяем успешность создания инвойса
    if invoice.get("state") != 0 or "result" not in invoice:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_topup_crypto")]
        ])
        await message.answer(f"Ошибка создания крипто-счёта: {invoice}", reply_markup=kb)
        await state.clear()
        return
    pay_url = invoice["result"]["url"]
    uuid = invoice["result"]["uuid"]
    # Сохраняем платёж в БД
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO payments (uuid, user_id, amount, is_paid, created_at)
            VALUES ($1, $2, $3, false, NOW())
            """,
            uuid, user["telegram_id"], amount_rub
        )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Оплатить", url=pay_url)],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_topup_crypto")]
    ])
    await message.answer(
        f"Счёт на пополнение {amount_rub} RUB (≈ {amount_usd} USD) создан!\n\nДля оплаты нажмите кнопку ниже:",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await state.clear()

