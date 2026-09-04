import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, PreCheckoutQuery, LabeledPrice, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import aiohttp
from playwright.async_api import async_playwright

# ---------- КОНФИГУРАЦИЯ ----------
BOT_TOKEN = "8631951504:AAE1piQHr_LAUyImmhJMdpdcF7yF3lSwlgE"  # Токен вашего бота
ADMIN_IDS = [1523825366]      # Ваш Telegram ID

PANEL_URL = "http://germany-d2.h1cloud.net:25638"
PANEL_LOGIN = "manopchenko@yandex.ru"
PANEL_PASSWORD = "N9GGxxZXXVAN"
INBOUND_NAME = "reality"

CRYPTOBOT_TOKEN = "629761:AA1CGjxMUWJHt5YzxBIEULwF1uiLoMtcdba"
ENABLE_CRYPTOBOT = True
ENABLE_STARS = True

# Тарифы
PLANS = {
    "1m": {"name": "1 месяц", "price_rub": 100, "price_stars": 70, "days": 30, "devices": 3, "traffic_gb": 0},
    "3m": {"name": "3 месяца", "price_rub": 270, "price_stars": 189, "days": 90, "devices": 3, "traffic_gb": 0},
    "6m": {"name": "6 месяцев", "price_rub": 540, "price_stars": 378, "days": 180, "devices": 5, "traffic_gb": 0},
}

TRIAL_DAYS = 1
TRIAL_TRAFFIC_GB = 20
TRIAL_DEVICES = 1

# Ссылки на документацию
USER_AGREEMENT_URL = "https://telegra.ph/Polzovatelskoe-soglashenie-09-02-67"
PRIVACY_POLICY_URL = "https://telegra.ph/Politika-konfidencialnosti-09-02-105"

# Канал для обязательной подписки
CHANNEL_USERNAME = "@Mirvpn1"
CHANNEL_URL = "https://t.me/Mirvpn1"

# Ссылка на поддержку (ваш аккаунт)
SUPPORT_URL = "https://t.me/Anopchenko2011"

# ---------- БАЗА ДАННЫХ ----------
def init_db():
    conn = sqlite3.connect("bot.db")
    cur = conn.cursor()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            trial_used INTEGER DEFAULT 0,
            balance_rub REAL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            panel_username TEXT UNIQUE,
            plan TEXT,
            devices INTEGER,
            traffic_gb REAL,
            start_date TEXT,
            end_date TEXT,
            active INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS promocodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE,
            discount_percent REAL,
            discount_fixed_rub REAL,
            free_subscription INTEGER DEFAULT 0,
            plan_limit TEXT,
            max_uses INTEGER DEFAULT 0,
            used_count INTEGER DEFAULT 0,
            active INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL,
            currency TEXT,
            method TEXT,
            status TEXT,
            payload TEXT,
            created_at TEXT
        );
    """)
    conn.commit()
    conn.close()

def get_db():
    conn = sqlite3.connect("bot.db")
    conn.row_factory = sqlite3.Row
    return conn

# ---------- ПЛАТЕЖИ ----------
async def create_cryptobot_invoice(amount_rub: float, description: str, payload: str) -> str:
    url = "https://pay.crypt.bot/api/createInvoice"
    headers = {"Crypto-Pay-API-Token": CRYPTOBOT_TOKEN}
    data = {
        "asset": "USDT",
        "amount": str(amount_rub),
        "description": description,
        "payload": payload,
        "allow_comments": False,
        "allow_anonymous": False,
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=data, headers=headers) as resp:
            result = await resp.json()
            if result.get("ok"):
                return result["result"]["pay_url"]
            else:
                raise Exception("CryptoBot error")

async def send_stars_invoice(bot, chat_id, title, description, payload, amount_stars):
    await bot.send_invoice(
        chat_id=chat_id,
        title=title,
        description=description,
        payload=payload,
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label=title, amount=amount_stars)]
    )

# ---------- АВТОМАТИЗАЦИЯ ПАНЕЛИ (Playwright) ----------
async def create_client_via_browser(username: str, days: int, traffic_gb: float, device_limit: int) -> str:
    """Создаёт клиента в панели Marzban и возвращает ссылку на подписку."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(PANEL_URL + "/panel")

        # Логин
        await page.fill("input[type='text']", PANEL_LOGIN)
        await page.fill("input[type='password']", PANEL_PASSWORD)
        await page.click("button[type='submit']")
        await page.wait_for_load_state("networkidle")

        # Переход в "Клиенты"
        await page.click("text=Клиенты")
        await page.wait_for_load_state("networkidle")

        # Новый клиент
        await page.click("text=Новый клиент")
        await page.wait_for_load_state("networkidle")

        # Заполнение полей (селекторы требуют уточнения!)
        await page.fill("input[name='username']", username)
        await page.fill("input[name='expire_days']", str(days))
        await page.fill("input[name='data_limit_gb']", str(traffic_gb))
        await page.fill("input[name='device_limit']", str(device_limit))

        # Создание
        await page.click("button[type='submit']")
        await page.wait_for_load_state("networkidle")

        # Открыть пользователя и получить ссылку подписки
        await page.click(f"text={username}")
        await page.wait_for_load_state("networkidle")

        # Поиск ссылки (нужно адаптировать под реальную вёрстку)
        sub_link = await page.evaluate("""
            () => {
                const el = [...document.querySelectorAll('*')].find(e => e.textContent.includes('Подписка'));
                if (el) {
                    const link = el.querySelector('a');
                    return link ? link.href : null;
                }
                return null;
            }
        """)
        if not sub_link:
            sub_link = f"{PANEL_URL}/sub/{username}"  # запасной вариант

        await browser.close()
        return sub_link

# ---------- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ----------
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

async def get_next_username() -> str:
    conn = get_db()
    rows = conn.execute("SELECT panel_username FROM subscriptions WHERE panel_username LIKE 'user%'").fetchall()
    max_num = 0
    for row in rows:
        try:
            num = int(row['panel_username'][4:])
            if num > max_num:
                max_num = num
        except:
            pass
    conn.close()
    return f"user{max_num + 1}"

async def activate_subscription(user_id: int, plan_id: str, promo=None) -> str:
    """Активирует подписку, создавая клиента в панели и возвращая ссылку."""
    if plan_id == "trial":
        plan = {"name": "Пробный", "days": TRIAL_DAYS, "devices": TRIAL_DEVICES, "traffic_gb": TRIAL_TRAFFIC_GB}
    else:
        plan = PLANS[plan_id]

    days = plan['days']
    devices = plan['devices']
    traffic_gb = plan['traffic_gb']

    username = await get_next_username()
    sub_link = await create_client_via_browser(username, days, traffic_gb, devices)

    conn = get_db()
    conn.execute(
        "INSERT INTO subscriptions (user_id, panel_username, plan, devices, traffic_gb, start_date, end_date) VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now', '+{} days'))".format(days),
        (user_id, username, plan_id, devices, traffic_gb)
    )
    conn.commit()
    conn.close()
    return sub_link

async def check_subscription(user_id: int) -> bool:
    """Проверяет, подписан ли пользователь на канал."""
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        return member.status in ["member", "administrator", "creator"]
    except Exception:
        return False

# ---------- КЛАВИАТУРЫ ----------
def main_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="🛒 Купить VPN", callback_data="buy")
    kb.button(text="🎁 Пробный период", callback_data="trial")
    kb.button(text="📱 Моя подписка", callback_data="status")
    kb.button(text="💰 Пополнить баланс", callback_data="topup")
    kb.button(text="👤 Мой профиль", callback_data="profile")
    kb.button(text="📚 Документация", callback_data="docs")
    kb.button(text="🆘 Помощь", url=SUPPORT_URL)  # кнопка помощи ведёт на ваш аккаунт
    kb.adjust(2)
    return kb.as_markup()

def subscribe_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="Подписаться на канал", url=CHANNEL_URL)
    kb.button(text="Я подписался", callback_data="check_sub")
    kb.adjust(1)
    return kb.as_markup()

# ---------- ОБРАБОТЧИКИ КОМАНД ----------
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    # Регистрируем пользователя в БД
    conn = get_db()
    conn.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, message.from_user.username))
    conn.commit()
    conn.close()

    # Проверяем подписку на канал
    if await check_subscription(user_id):
        await message.answer("👋 Добро пожаловать в VPN-бот!\nВыберите действие:", reply_markup=main_keyboard())
    else:
        await message.answer(
            "⚠️ Для использования бота необходимо подписаться на наш канал.\n"
            "Подпишитесь и нажмите кнопку проверки.",
            reply_markup=subscribe_keyboard()
        )

@dp.message(Command("help"))
async def cmd_help(message: Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="🆘 Связаться с поддержкой", url=SUPPORT_URL)
    kb.adjust(1)
    await message.answer("Нужна помощь? Нажмите кнопку ниже, чтобы написать нам.", reply_markup=kb.as_markup())

@dp.callback_query(F.data == "check_sub")
async def check_sub_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    if await check_subscription(user_id):
        await callback.message.delete()
        await callback.message.answer("✅ Подписка подтверждена! Добро пожаловать.", reply_markup=main_keyboard())
    else:
        await callback.answer("Вы ещё не подписались на канал.", show_alert=True)

# ---------- ДОКУМЕНТАЦИЯ ----------
@dp.callback_query(F.data == "docs")
async def docs(callback: CallbackQuery):
    kb = InlineKeyboardBuilder()
    kb.button(text="Пользовательское соглашение", url=USER_AGREEMENT_URL)
    kb.button(text="Политика конфиденциальности", url=PRIVACY_POLICY_URL)
    kb.adjust(1)
    await callback.message.edit_text("Документация:", reply_markup=kb.as_markup())

# ---------- ПРОФИЛЬ ----------
@dp.callback_query(F.data == "profile")
async def profile(callback: CallbackQuery):
    user_id = callback.from_user.id
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    sub = conn.execute("SELECT * FROM subscriptions WHERE user_id = ? AND active = 1 ORDER BY id DESC LIMIT 1", (user_id,)).fetchone()
    conn.close()

    text = f"👤 Профиль:\nБаланс: {user['balance_rub']:.2f} руб.\n"
    if sub:
        text += f"\n📊 Активная подписка:\n"
        text += f"Имя в панели: {sub['panel_username']}\n"
        text += f"Тариф: {sub['plan']}\n"
        text += f"Устройства: {sub['devices']}\n"
        text += f"Трафик: {sub['traffic_gb'] if sub['traffic_gb'] else 'безлимит'}\n"
        text += f"Окончание: {sub['end_date']}\n"
        text += f"Ссылка: {PANEL_URL}/sub/{sub['panel_username']}"
    else:
        text += "\nАктивной подписки нет."
    await callback.message.edit_text(text)

# ---------- ПОПОЛНЕНИЕ БАЛАНСА ----------
class TopupStates(StatesGroup):
    waiting_amount = State()
    waiting_method = State()

@dp.callback_query(F.data == "topup")
async def topup_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите сумму пополнения (от 100 до 10000 рублей):")
    await state.set_state(TopupStates.waiting_amount)

@dp.message(TopupStates.waiting_amount)
async def topup_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text)
        if amount < 100 or amount > 10000:
            await message.answer("Сумма должна быть от 100 до 10000 рублей. Попробуйте ещё раз.")
            return
        await state.update_data(amount=amount)
        kb = InlineKeyboardBuilder()
        if ENABLE_CRYPTOBOT:
            kb.button(text="Оплатить CryptoBot", callback_data="topup_crypto")
        if ENABLE_STARS:
            kb.button(text=f"Оплатить Stars ({int(amount)} ⭐)", callback_data="topup_stars")
        kb.adjust(1)
        await message.answer("Выберите способ оплаты:", reply_markup=kb.as_markup())
        await state.set_state(TopupStates.waiting_method)
    except ValueError:
        await message.answer("Введите число.")

@dp.callback_query(TopupStates.waiting_method, F.data == "topup_crypto")
async def topup_crypto(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    amount = data['amount']
    pay_url = await create_cryptobot_invoice(amount, "Пополнение баланса VPN", "balance_topup")
    kb = InlineKeyboardBuilder()
    kb.button(text="Перейти к оплате", url=pay_url)
    await callback.message.answer("Счёт на пополнение баланса создан. После оплаты нажмите /check_balance", reply_markup=kb.as_markup())
    await state.clear()

@dp.callback_query(TopupStates.waiting_method, F.data == "topup_stars")
async def topup_stars(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    amount = data['amount']
    stars = int(amount)  # 1 рубль = 1 звезда
    await send_stars_invoice(
        bot, callback.from_user.id,
        title="Пополнение баланса",
        description=f"Пополнение на {amount} руб.",
        payload="balance_topup_stars",
        amount_stars=stars
    )
    await callback.message.answer("Выставлен счёт на оплату звёздами. Подтвердите оплату.")
    await state.clear()

# Обработка успешной оплаты (и для подписок, и для баланса)
@dp.pre_checkout_query()
async def process_pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@dp.message(F.successful_payment)
async def successful_payment(message: Message):
    payment = message.successful_payment
    payload = payment.invoice_payload
    user_id = message.from_user.id

    if payload.startswith("vpn_"):
        parts = payload.split("_")
        plan_id = parts[1]
        sub_link = await activate_subscription(user_id, plan_id)
        await message.answer(
            f"✅ Оплата прошла успешно!\n"
            f"Ваша ссылка для подключения:\n<code>{sub_link}</code>\n\n"
            "Скачайте приложение (v2rayNG, Streisand, Shadowrocket), импортируйте подписку и наслаждайтесь."
        )
    elif payload == "balance_topup" or payload == "balance_topup_stars":
        amount = payment.total_amount / 100 if payload == "balance_topup" else payment.total_amount
        conn = get_db()
        conn.execute("UPDATE users SET balance_rub = balance_rub + ? WHERE user_id = ?", (amount, user_id))
        conn.commit()
        conn.close()
        await message.answer(f"✅ Баланс пополнен на {amount:.2f} руб.")
    else:
        await message.answer("Спасибо за оплату!")

# ---------- ПОКУПКА VPN ----------
@dp.callback_query(F.data == "buy")
async def buy_menu(callback: CallbackQuery):
    kb = InlineKeyboardBuilder()
    for plan_id, plan in PLANS.items():
        kb.button(text=f"{plan['name']} — {plan['price_rub']}₽ / {plan['price_stars']}⭐", callback_data=f"select_plan_{plan_id}")
    kb.adjust(1)
    await callback.message.edit_text("Выберите тариф:", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("select_plan_"))
async def select_plan(callback: CallbackQuery):
    plan_id = callback.data.split("_")[2]
    plan = PLANS[plan_id]
    kb = InlineKeyboardBuilder()
    conn = get_db()
    user = conn.execute("SELECT balance_rub FROM users WHERE user_id = ?", (callback.from_user.id,)).fetchone()
    conn.close()
    balance = user['balance_rub'] if user else 0
    if balance >= plan['price_rub']:
        kb.button(text=f"Оплатить с баланса ({balance:.2f} руб.)", callback_data=f"pay_balance_{plan_id}")
    if ENABLE_CRYPTOBOT:
        kb.button(text="Оплатить CryptoBot", callback_data=f"pay_crypto_{plan_id}")
    if ENABLE_STARS:
        kb.button(text=f"Оплатить Stars ({plan['price_stars']}⭐)", callback_data=f"pay_stars_{plan_id}")
    kb.button(text="Ввести промокод", callback_data=f"promo_{plan_id}")
    kb.button(text="Назад", callback_data="buy")
    kb.adjust(1)
    await callback.message.edit_text(
        f"Тариф: {plan['name']}\n"
        f"Срок: {plan['days']} дней\n"
        f"Устройства: {plan['devices']}\n"
        f"Трафик: безлимит\n"
        f"Цена: {plan['price_rub']}₽ / {plan['price_stars']}⭐\n\n"
        "Выберите способ оплаты:",
        reply_markup=kb.as_markup()
    )

@dp.callback_query(F.data.startswith("pay_balance_"))
async def pay_balance(callback: CallbackQuery):
    plan_id = callback.data.split("_")[2]
    plan = PLANS[plan_id]
    user_id = callback.from_user.id
    conn = get_db()
    user = conn.execute("SELECT balance_rub FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if not user or user['balance_rub'] < plan['price_rub']:
        await callback.answer("Недостаточно средств на балансе.", show_alert=True)
        return
    conn.execute("UPDATE users SET balance_rub = balance_rub - ? WHERE user_id = ?", (plan['price_rub'], user_id))
    conn.commit()
    conn.close()
    sub_link = await activate_subscription(user_id, plan_id)
    await callback.message.answer(
        f"✅ Подписка активирована!\n"
        f"Ссылка: <code>{sub_link}</code>"
    )

@dp.callback_query(F.data.startswith("pay_crypto_"))
async def pay_crypto(callback: CallbackQuery):
    plan_id = callback.data.split("_")[2]
    plan = PLANS[plan_id]
    pay_url = await create_cryptobot_invoice(plan['price_rub'], f"VPN {plan['name']}", f"vpn_{plan_id}_crypto")
    kb = InlineKeyboardBuilder()
    kb.button(text="Перейти к оплате", url=pay_url)
    await callback.message.edit_text("Счёт создан. После оплаты подписка активируется автоматически.", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("pay_stars_"))
async def pay_stars(callback: CallbackQuery):
    plan_id = callback.data.split("_")[2]
    plan = PLANS[plan_id]
    await send_stars_invoice(
        bot, callback.from_user.id,
        title=f"VPN {plan['name']}",
        description=f"Срок {plan['days']} дней, {plan['devices']} устройства",
        payload=f"vpn_{plan_id}_stars",
        amount_stars=plan['price_stars']
    )

# ---------- ПРОБНЫЙ ПЕРИОД ----------
@dp.callback_query(F.data == "trial")
async def trial(callback: CallbackQuery):
    user_id = callback.from_user.id
    conn = get_db()
    user = conn.execute("SELECT trial_used FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if user and user['trial_used']:
        await callback.answer("Вы уже использовали пробный период.", show_alert=True)
        return
    sub_link = await activate_subscription(user_id, "trial")
    conn.execute("UPDATE users SET trial_used = 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    await callback.message.answer(
        f"🎉 Пробный период активирован!\n"
        f"Срок: {TRIAL_DAYS} день\n"
        f"Трафик: {TRIAL_TRAFFIC_GB} ГБ\n"
        f"Устройства: {TRIAL_DEVICES}\n"
        f"Ссылка: <code>{sub_link}</code>"
    )

# ---------- МОЯ ПОДПИСКА ----------
@dp.callback_query(F.data == "status")
async def status(callback: CallbackQuery):
    user_id = callback.from_user.id
    conn = get_db()
    sub = conn.execute("SELECT * FROM subscriptions WHERE user_id = ? AND active = 1 ORDER BY id DESC LIMIT 1", (user_id,)).fetchone()
    conn.close()
    if not sub:
        await callback.message.edit_text("У вас нет активной подписки.")
        return
    text = (
        f"📊 Ваша подписка:\n"
        f"Имя: {sub['panel_username']}\n"
        f"Тариф: {sub['plan']}\n"
        f"Устройства: {sub['devices']}\n"
        f"Трафик: {sub['traffic_gb'] if sub['traffic_gb'] else 'безлимит'}\n"
        f"Окончание: {sub['end_date']}\n"
        f"Ссылка: {PANEL_URL}/sub/{sub['panel_username']}"
    )
    await callback.message.edit_text(text)

# ---------- АДМИН-ПАНЕЛЬ (базовая) ----------
@dp.message(Command("admin"))
async def admin_panel(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return
    kb = InlineKeyboardBuilder()
    kb.button(text="Создать подписку", callback_data="admin_create_sub")
    kb.button(text="Промокоды", callback_data="admin_promos")
    kb.button(text="Статистика", callback_data="admin_stats")
    kb.adjust(1)
    await message.answer("Админ-панель:", reply_markup=kb.as_markup())

@dp.callback_query(F.data == "admin_create_sub")
async def admin_create_sub(callback: CallbackQuery):
    await callback.message.answer("Функция в разработке.")

@dp.callback_query(F.data == "admin_promos")
async def admin_promos(callback: CallbackQuery):
    await callback.message.answer("Функция в разработке.")

@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    conn = get_db()
    total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    active_subs = conn.execute("SELECT COUNT(*) FROM subscriptions WHERE active = 1 AND end_date > datetime('now')").fetchone()[0]
    expired_subs = conn.execute("SELECT COUNT(*) FROM subscriptions WHERE active = 1 AND end_date <= datetime('now')").fetchone()[0]
    conn.close()
    await callback.message.answer(
        f"Статистика:\n"
        f"Всего пользователей: {total_users}\n"
        f"Активных подписок: {active_subs}\n"
        f"Истёкших (но не отключенных): {expired_subs}"
    )

# ---------- ЗАПУСК ----------
async def main():
    init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
