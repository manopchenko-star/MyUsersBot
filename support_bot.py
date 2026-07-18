import asyncio, sqlite3, os, logging, json, aiohttp
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
BOT_TOKEN = os.environ.get("SUPPORT_BOT_TOKEN", "")
GITHUB_HELP = os.environ.get("GITHUB_HELP", "")
MAIN_ADMIN_USERNAME = "Anopchenko2011"
AI_MODEL = "gpt-4o-mini"
AI_MAX_TOKENS = 300
AI_TEMPERATURE = 0.7
AI_SYSTEM_PROMPT = "Ты — дружелюбный помощник игрового сообщества Roblox. Отвечай кратко и по делу. Если пользователь говорит, что не может зайти в игру из-за возраста (<16 лет), запроси его ник, затем скажи: 'Принято. Пожалуйста, вступите в нашу группу Roblox: https://www.roblox.com/communities/746872156/Defense-mans#!/about , иначе мы не сможем помочь.' Если вопрос слишком сложный или требует вмешательства человека, предложи связаться с оператором."
DATABASE = "support_bot.db"
active_chats = {}
user_chat_admin = {}
is_bot_enabled = True
def get_db(): return sqlite3.connect(DATABASE, check_same_thread=False)
def init_db():
    conn = get_db(); c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY, username TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS tickets (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, username TEXT,
        question TEXT, status TEXT DEFAULT 'open', operator_id INTEGER,
        created_at TEXT, closed_at TEXT
    )''')
    c.execute("INSERT OR IGNORE INTO admins (user_id, username) VALUES (0, ?)", (MAIN_ADMIN_USERNAME,))
    conn.commit(); conn.close()
def is_admin(user_id):
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT 1 FROM admins WHERE user_id=?", (user_id,))
    r = c.fetchone(); conn.close(); return r is not None
def is_main_admin(username): return username and username.lower() == MAIN_ADMIN_USERNAME.lower()
def add_user(user_id, username):
    conn = get_db(); c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users VALUES (?,?)", (user_id, username))
    conn.commit(); conn.close()
def get_all_user_ids():
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT user_id FROM users"); ids=[row[0] for row in c.fetchall()]; conn.close(); return ids
def create_ticket(user_id, username, question):
    conn = get_db(); c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("INSERT INTO tickets (user_id, username, question, status, created_at) VALUES (?,?,?,'open',?)",
              (user_id, username, question, now))
    tid = c.lastrowid; conn.commit(); conn.close()
    return tid
def get_open_tickets():
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT id, user_id, username, question, created_at FROM tickets WHERE status='open' ORDER BY id")
    rows = c.fetchall(); conn.close(); return rows
def assign_ticket(ticket_id, operator_id):
    conn = get_db(); c = conn.cursor()
    c.execute("UPDATE tickets SET status='in_progress', operator_id=? WHERE id=?", (operator_id, ticket_id))
    conn.commit(); conn.close()
def close_ticket(ticket_id):
    conn = get_db(); c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("UPDATE tickets SET status='closed', closed_at=? WHERE id=?", (now, ticket_id))
    conn.commit(); conn.close()
def get_ticket(ticket_id):
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM tickets WHERE id=?", (ticket_id,))
    row = c.fetchone(); conn.close(); return row
async def ask_ai(prompt):
    if not GITHUB_HELP: return "❌ API-ключ не задан."
    headers = {"Authorization": f"Bearer {GITHUB_HELP}", "Content-Type": "application/json"}
    payload = {"model": AI_MODEL, "messages": [{"role":"system","content":AI_SYSTEM_PROMPT},{"role":"user","content":prompt}],
               "max_tokens": AI_MAX_TOKENS, "temperature": AI_TEMPERATURE}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post("https://models.inference.ai.azure.com/chat/completions", json=payload, headers=headers, timeout=30) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data["choices"][0]["message"]["content"]
                else: return "⚠️ Ошибка AI"
    except Exception as e: return f"⚠️ Сетевая ошибка: {e}"
def user_keyboard():
    return ReplyKeyboardMarkup([[KeyboardButton("🆘 Поддержка")], [KeyboardButton("📋 Мои тикеты")]], resize_keyboard=True)
def admin_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📋 Все тикеты"), KeyboardButton("🆘 Поддержка")],
        [KeyboardButton("👥 Админы"), KeyboardButton("⚙️ Настройки")]
    ], resize_keyboard=True)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; add_user(user.id, user.username or "unknown")
    if user.username and is_main_admin(user.username):
        conn = get_db(); c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO admins (user_id, username) VALUES (?,?)", (user.id, user.username))
        conn.commit(); conn.close()
    if is_admin(user.id):
        await update.message.reply_text("👑 Панель администратора поддержки.", reply_markup=admin_keyboard())
    else:
        await update.message.reply_text("👋 Я бот поддержки. Задайте вопрос или нажмите кнопку.", reply_markup=user_keyboard())
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("ℹ️ Я могу ответить на вопросы по игре, помочь с проблемами входа. Если нужен живой оператор, нажмите «🆘 Поддержка».")
async def support_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("📞 Связаться с оператором", callback_data="req_operator")]])
    await update.message.reply_text("Нажмите кнопку, чтобы создать заявку для оператора.", reply_markup=kb)
async def my_tickets_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT id, question, status, created_at FROM tickets WHERE user_id=? ORDER BY id DESC LIMIT 5", (user.id,))
    rows = c.fetchall(); conn.close()
    if not rows:
        await update.message.reply_text("У вас нет заявок."); return
    text = "📋 Ваши заявки:\n"
    for t in rows:
        text += f"#{t[0]} [{t[2]}] {t[1][:50]}...\n"
    await update.message.reply_text(text)
async def all_tickets_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Только администратор."); return
    tickets = get_open_tickets()
    if not tickets:
        await update.message.reply_text("Нет открытых тикетов."); return
    text = "📋 Открытые тикеты:\n"
    keyboard = []
    for t in tickets:
        tid, uid, uname, q, _ = t
        text += f"#{tid} от @{uname}: {q[:40]}...\n"
        keyboard.append([InlineKeyboardButton(f"✉️ Ответить #{tid}", callback_data=f"take_{tid}")])
    reply = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, reply_markup=reply)
async def admins_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Только администратор."); return
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT username FROM admins"); admins = c.fetchall(); conn.close()
    await update.message.reply_text("Администраторы: " + ", ".join([a[0] for a in admins]))
async def settings_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Только администратор."); return
    status = "включён" if is_bot_enabled else "выключен"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 Включить бота" if not is_bot_enabled else "🔴 Выключить бота", callback_data="toggle_bot")]
    ])
    await update.message.reply_text(f"Бот поддержки: {status}", reply_markup=kb)
async def toggle_bot_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    if not is_main_admin(query.from_user.username):
        await query.answer("⛔ Только главный администратор.", show_alert=True); return
    global is_bot_enabled; is_bot_enabled = not is_bot_enabled
    await query.edit_message_text(f"Бот поддержки: {'включён' if is_bot_enabled else 'выключен'}")
async def req_operator_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    user = query.from_user
    ticket_id = create_ticket(user.id, user.username or "unknown", "Запрос оператора (нажата кнопка)")
    await query.edit_message_text("✅ Ваш запрос передан оператору. Ожидайте ответа.")
    for uid in get_all_user_ids():
        if is_admin(uid) and uid != user.id:
            try: await context.bot.send_message(uid, f"🔔 Новый тикет #{ticket_id} от @{user.username or user.id}.")
            except: pass
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; msg = update.message.text
    if not msg: return
    if user.id in active_chats:
        target_admin = active_chats[user.id]
        try: await context.bot.send_message(target_admin, f"💬 От @{user.username or user.id}: {msg}")
        except: pass
        return
    if user.id in user_chat_admin:
        target_user = user_chat_admin[user.id]
        try: await context.bot.send_message(target_user, f"👤 Оператор: {msg}")
        except: pass
        return
    if is_admin(user.id) and msg.startswith("/answer "):
        parts = msg.split(maxsplit=2)
        if len(parts) < 3:
            await update.message.reply_text("Формат: /answer <ticket_id> <текст>"); return
        try: tid = int(parts[1])
        except: await update.message.reply_text("Неверный ID."); return
        ticket = get_ticket(tid)
        if not ticket or ticket[4] != 'open':
            await update.message.reply_text("Тикет неактивен."); return
        assign_ticket(tid, user.id)
        try:
            await context.bot.send_message(ticket[1], f"👤 Оператор: {parts[2]}")
            await update.message.reply_text("✅ Ответ отправлен.")
        except Exception as e: await update.message.reply_text(f"Ошибка: {e}")
        return
    if is_main_admin(user.username) and msg.startswith("/support_on"):
        global is_bot_enabled; is_bot_enabled = True
        await update.message.reply_text("✅ Бот поддержки включён."); return
    if is_main_admin(user.username) and msg.startswith("/support_off"):
        is_bot_enabled = False
        await update.message.reply_text("❌ Бот поддержки выключен."); return
    if not is_bot_enabled:
        await update.message.reply_text("Бот временно недоступен."); return
    answer = await ask_ai(msg)
    if "оператор" in answer.lower() or "свяжитесь с оператором" in answer.lower():
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("📞 Связаться с оператором", callback_data="req_operator")]])
        await update.message.reply_text(answer + "\n\nИли нажмите кнопку:", reply_markup=kb)
    else:
        await update.message.reply_text(answer)
async def take_ticket_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    admin = query.from_user
    if not is_admin(admin.id):
        await query.answer("⛔ Только администратор.", show_alert=True); return
    data = query.data
    if data.startswith("take_"):
        tid = int(data.split("_")[1])
        ticket = get_ticket(tid)
        if not ticket or ticket[4] != 'open':
            await query.edit_message_text("Тикет уже обработан."); return
        assign_ticket(tid, admin.id)
        active_chats[ticket[1]] = admin.id
        user_chat_admin[admin.id] = ticket[1]
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Завершить чат", callback_data=f"endchat_{tid}")]])
        await query.edit_message_text(f"Взяли тикет #{tid}. Пишите сообщение – оно отправится пользователю.")
        try:
            await context.bot.send_message(ticket[1], "👤 Оператор подключился. Можете писать ваш вопрос.")
        except: pass
    elif data.startswith("endchat_"):
        tid = int(data.split("_")[1])
        if admin.id in user_chat_admin:
            uid = user_chat_admin.pop(admin.id)
            active_chats.pop(uid, None)
        close_ticket(tid)
        await query.edit_message_text("✅ Чат завершён, тикет закрыт.")
is_running = False
application = None
polling_task = None
async def start_support():
    global is_running, application, polling_task
    if is_running: return
    if not BOT_TOKEN:
        logging.warning("SUPPORT_BOT_TOKEN не задан")
        return
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.Regex("^🆘 Поддержка$"), support_button))
    app.add_handler(MessageHandler(filters.Regex("^📋 Мои тикеты$"), my_tickets_button))
    app.add_handler(MessageHandler(filters.Regex("^📋 Все тикеты$"), all_tickets_button))
    app.add_handler(MessageHandler(filters.Regex("^👥 Админы$"), admins_button))
    app.add_handler(MessageHandler(filters.Regex("^⚙️ Настройки$"), settings_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(req_operator_callback, pattern="^req_operator$"))
    app.add_handler(CallbackQueryHandler(take_ticket_callback, pattern="^(take_|endchat_)"))
    app.add_handler(CallbackQueryHandler(toggle_bot_callback, pattern="^toggle_bot$"))
    await app.initialize()
    await app.start()
    polling_task = asyncio.create_task(app.updater.start_polling())
    application = app
    is_running = True
async def stop_support():
    global is_running, application, polling_task
    if not is_running: return
    if polling_task:
        polling_task.cancel(); polling_task = None
    if application:
        await application.stop(); await application.shutdown(); application = None
    is_running = False