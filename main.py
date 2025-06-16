import asyncio
from aiogram import Bot, Dispatcher
from config import load_config
from handlers.start import router as start_router, delete_expired_promos, main_menu_kb
from handlers.profile import router as profile_router
from database import create_pg_pool, create_redis_pool
from aiohttp import web
from utils.payment_models import verify_signature
import json

async def promo_cleanup_scheduler(db_pool):
    while True:
        await delete_expired_promos(db_pool)
        await asyncio.sleep(600)  # каждые 10 минут

async def mulenpay_webhook(request):
    config = load_config()
    db_pool = request.app["db_pool"]
    raw_body = await request.read()
    try:
        data = json.loads(raw_body)
    except Exception:
        return web.Response(status=400, text="Invalid JSON")
    # sign = request.headers.get("X-Signature")
    # if not sign or not verify_signature(raw_body, sign, config.mulenpay_webhook_secret):
    #     return web.Response(status=403, text="Invalid signature")
    print("WEBHOOK DATA:", data)
    uuid = data.get("uuid")
    status = data.get("status") or data.get("payment_status")
    amount = float(data.get("amount", 0))
    if not uuid or status not in ("paid", "success", "done"):  # поддержка разных статусов
        return web.Response(status=200, text="Ignored")
    # Найти платёж и обновить статус
    async with db_pool.acquire() as conn:
        payment = await conn.fetchrow("SELECT * FROM payments WHERE uuid=$1", uuid)
        if not payment or payment["is_paid"]:
            return web.Response(status=200, text="Already processed")
        await conn.execute("UPDATE payments SET is_paid=true WHERE uuid=$1", uuid)
        await conn.execute("UPDATE users SET balance = balance + $1 WHERE telegram_id=$2", amount, payment["user_id"])
    # Отправляем уведомление пользователю о пополнении
    bot = Bot(token=config.bot_token)
    try:
        await bot.send_photo(
            payment["user_id"],
            config.welcome_image_url,
            caption=config.welcome_description,
            reply_markup=main_menu_kb(payment["user_id"]),
            parse_mode="HTML"
        )
        await bot.send_message(
            payment["user_id"],
            f"✅ Ваш баланс успешно пополнен на {amount} RUB!"
        )
    except Exception as e:
        print(f"Не удалось отправить сообщение пользователю: {e}")
    return web.Response(status=200, text="OK")

async def heleket_webhook(request):
    config = load_config()
    db_pool = request.app["db_pool"]
    raw_body = await request.read()
    try:
        data = request.query if request.content_type == 'application/x-www-form-urlencoded' else await request.json()
    except Exception:
        return web.Response(status=400, text="Invalid JSON")
    # Верификация подписи (если требуется, добавить здесь)
    # Пример: sign = request.headers.get("X-Signature")
    # if not sign or not verify_signature(raw_body, sign, config.heleket_webhook_secret):
    #     return web.Response(status=403, text="Invalid signature")
    # Проверяем статус оплаты
    result = data.get("result") or data
    status = result.get("payment_status") or result.get("status")
    uuid = result.get("uuid")
    if not uuid or status not in ("paid", "success", "done"):
        return web.Response(status=200, text="Ignored")
    # Найти платёж и обновить статус
    async with db_pool.acquire() as conn:
        payment = await conn.fetchrow("SELECT * FROM payments WHERE uuid=$1", uuid)
        if not payment or payment["is_paid"]:
            return web.Response(status=200, text="Already processed")
        await conn.execute("UPDATE payments SET is_paid=true WHERE uuid=$1", uuid)
        amount = float(payment["amount"])  # Используем сумму из базы
        await conn.execute("UPDATE users SET balance = balance + $1 WHERE telegram_id=$2", amount, payment["user_id"])
    # Отправляем уведомление пользователю о пополнении через Crypto
    bot = Bot(token=config.bot_token)
    try:
        await bot.send_photo(
            payment["user_id"],
            config.welcome_image_url,
            caption=config.welcome_description,
            reply_markup=main_menu_kb(payment["user_id"]),
            parse_mode="HTML"
        )
        await bot.send_message(
            payment["user_id"],
            f"✅ Ваш баланс успешно пополнен на {amount} RUB!"
        )
    except Exception as e:
        print(f"Не удалось отправить сообщение пользователю (crypto): {e}")
    return web.Response(status=200, text="OK")

async def main():
    config = load_config()
    bot = Bot(token=config.bot_token)
    dp = Dispatcher()
    pool = await create_pg_pool(config.postgres_dsn)
    redis = await create_redis_pool(config.redis_url)
    dp['db_pool'] = pool
    dp['redis'] = redis
    dp.include_router(start_router)
    dp.include_router(profile_router)
    # Запуск фонового таска
    asyncio.create_task(promo_cleanup_scheduler(pool))
    # --- aiohttp web server ---
    app = web.Application()
    app["db_pool"] = pool
    app.router.add_post("/webhook/mulenpay", mulenpay_webhook)
    app.router.add_post("/webhook/heleket", heleket_webhook)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8443)
    asyncio.create_task(site.start())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main()) 