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
AI_SYSTEM_PROMPT = (
    "Ты — дружелюбный помощник игрового сообщества Roblox. "
    "Отвечай кратко и по делу. Если пользователь говорит, что не может зайти в игру из-за возраста (<16 лет), "
    "запроси его ник, затем скажи: 'Принято. Пожалуйста, вступите в нашу группу Roblox: "
    "https://www.roblox.com/communities/746872156/Defense-mans#!/about , иначе мы не сможем помочь.' "
    "Если вопрос слишком сложный или требует вмешательства человека, предложи связаться с оператором."
)
DATABASE = "support_bot.db"

active_chats = {}          # user_id -> operator_id
user_chat_admin = {}       # operator_id -> user_id
is_bot_enabled = True
test_mode_users = set()    # user_id админов, находящихся в тестовом режиме

def get_db(): return sqlite3.connect(DATABASE, check_same_thread=False)

def init_db():
    conn = get_db(); c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY, username TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS tickets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, username TEXT, question TEXT, status TEXT DEFAULT 'open',
        operator_id INTEGER, created_at TEXT, closed_at TEXT)''')
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
    tid = c.lastrowid; conn.commit(); conn.close(); return tid

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

def add_admin_to_db(user_id, username):
    conn = get_db(); c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO admins (user_id, username) VALUES (?,?)", (user_id, username))
    conn.commit(); conn.close()

def remove_admin_from_db(user_id):
    conn = get_db(); c = conn.cursor()
    c.execute("DELETE FROM admins WHERE user_id=?", (user_id,))
    conn.commit(); conn.close()

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
        [KeyboardButton("👥 Админы"), KeyboardButton("⚙️ Настройки")],
        [KeyboardButton("🧪 Тестовый режим")]
    ], resize_keyboard=True)

def operator_chat_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("❌ Завершить чат")],
        [KeyboardButton("🧪 Тестовый режим"), KeyboardButton("🔙 Выйти без закрытия")]
    ], resize_keyboard=True)

# ---------- Обработчики кнопок ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; add_user(user.id, user.username or "unknown")
    if user.username and is_main_admin(user.username):
        add_admin_to_db(user.id, user.username)
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
        await update.message.reply_text("У вас нет заявок.")
        return
    text = "📋 Ваши заявки:\n"
    for t in rows: text += f"#{t[0]} [{t[2]}] {t[1][:50]}...\n"
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
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def admins_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Только администратор."); return
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT username FROM admins")
    admins = c.fetchall(); conn.close()
    admin_list = "\n".join([f"• {a[0]}" for a in admins])
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Добавить админа", callback_data="add_admin")],
        [InlineKeyboardButton("➖ Удалить админа", callback_data="remove_admin")]
    ])
    await update.message.reply_text(f"👥 Администраторы:\n{admin_list}", reply_markup=kb)

async def add_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    if not is_admin(query.from_user.id):
        await query.answer("⛔ Нет доступа.", show_alert=True); return
    context.user_data['action'] = 'add_admin'
    await query.edit_message_text("Введите @username или ID пользователя для добавления в администраторы:")

async def remove_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    if not is_admin(query.from_user.id):
        await query.answer("⛔ Нет доступа.", show_alert=True); return
    context.user_data['action'] = 'remove_admin'
    await query.edit_message_text("Введите @username или ID пользователя для удаления из администраторов:")

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

# Новые обработчики кнопок, вынесенные из handle_message
async def end_chat_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in user_chat_admin:
        await update.message.reply_text("Эта кнопка только для оператора в активном чате.")
        return
    target_user = user_chat_admin[user.id]
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT id FROM tickets WHERE status='in_progress' AND operator_id=? ORDER BY id DESC LIMIT 1", (user.id,))
    row = c.fetchone(); conn.close()
    tid = row[0] if row else None
    await end_chat_session(update, context, user.id, target_user, tid)

async def test_mode_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("⛔ Только для администраторов.")
        return
    if user.id in user_chat_admin:
        # оператор в чате: входим в тестовый режим (смена клавиатуры)
        test_mode_users.add(user.id)
        await update.message.reply_text("🧪 Вы вошли в тестовый режим. Теперь вы общаетесь с ботом как обычный пользователь. Нажмите «🔙 Выйти из теста», чтобы вернуться.",
                                        reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🔙 Выйти из теста")]], resize_keyboard=True))
    else:
        # админ не в чате: просто включаем тестовый режим
        test_mode_users.add(user.id)
        await update.message.reply_text("🧪 Вы вошли в тестовый режим. Используйте клавиатуру пользователя. Для выхода нажмите «🔙 Выйти из теста».",
                                        reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🔙 Выйти из теста")]], resize_keyboard=True))

async def exit_without_close_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in user_chat_admin:
        await update.message.reply_text("Эта кнопка только для оператора в активном чате.")
        return
    target_user = user_chat_admin.pop(user.id)
    active_chats.pop(target_user, None)
    await update.message.reply_text("🔙 Вы вышли из чата. Тикет остаётся открытым.", reply_markup=admin_keyboard())
    try: await context.bot.send_message(target_user, "🔒 Оператор завершил сеанс. Ожидайте другого оператора.")
    except: pass

async def exit_test_mode_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id in test_mode_users:
        test_mode_users.discard(user.id)
        if is_admin(user.id):
            await update.message.reply_text("🔙 Вы вышли из тестового режима.", reply_markup=admin_keyboard())
        else:
            await update.message.reply_text("🔙 Вы вышли из тестового режима.", reply_markup=user_keyboard())
    else:
        await update.message.reply_text("Вы не в тестовом режиме.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global is_bot_enabled
    user = update.effective_user; msg = update.message.text
    if not msg: return

    # Пересылка сообщений в активном чате
    if user.id in active_chats:
        target_admin = active_chats[user.id]
        try: await context.bot.send_message(target_admin, f"💬 От @{user.username or user.id}: {msg}")
        except: pass
        return

    # Оператор в чате (но кнопки уже обрабатываются отдельными handler, сюда попадают только текстовые сообщения для пересылки)
    if user.id in user_chat_admin:
        target_user = user_chat_admin[user.id]
        try: await context.bot.send_message(target_user, f"👤 Оператор: {msg}")
        except: pass
        return

    # Тестовый режим (выход обрабатывается отдельно, здесь сам режим)
    if user.id in test_mode_users:
        if is_bot_enabled:
            answer = await ask_ai(msg)
            await update.message.reply_text(answer)
        else:
            await update.message.reply_text("Бот временно недоступен.")
        return

    # Действия по вводу username для добавления/удаления админа
    if context.user_data.get('action') in ('add_admin', 'remove_admin'):
        action = context.user_data.pop('action')
        username = msg.strip().lstrip("@")
        if not username:
            await update.message.reply_text("Некорректный формат. Отмена."); return
        if action == 'add_admin':
            add_admin_to_db(-1, username)
            await update.message.reply_text(f"✅ @{username} добавлен в список ожидания. Попросите его запустить /start.")
        elif action == 'remove_admin':
            conn = get_db(); c = conn.cursor()
            c.execute("SELECT user_id FROM admins WHERE username=?", (username,))
            row = c.fetchone()
            if row:
                remove_admin_from_db(row[0])
                await update.message.reply_text(f"❌ @{username} удалён из администраторов.")
            else:
                await update.message.reply_text("Администратор не найден.")
            conn.close()
        return

    # Команды ответа на тикет (вне чата)
    if is_admin(user.id) and msg.startswith("/answer "):
        parts = msg.split(maxsplit=2)
        if len(parts) < 3:
            await update.message.reply_text("Формат: /answer <ticket_id> <текст>"); return
        try: tid = int(parts[1])
        except ValueError: await update.message.reply_text("Неверный ID."); return
        ticket = get_ticket(tid)
        if not ticket or ticket[4] != 'open':
            await update.message.reply_text("Тикет неактивен."); return
        assign_ticket(tid, user.id)
        try:
            await context.bot.send_message(ticket[1], f"👤 Оператор: {parts[2]}")
            await update.message.reply_text("✅ Ответ отправлен.")
        except Exception as e: await update.message.reply_text(f"Ошибка: {e}")
        return

    if is_main_admin(user.username):
        if msg.startswith("/support_on"):
            is_bot_enabled = True
            await update.message.reply_text("✅ Бот поддержки включён."); return
        if msg.startswith("/support_off"):
            is_bot_enabled = False
            await update.message.reply_text("❌ Бот поддержки выключен."); return

    if not is_bot_enabled:
        await update.message.reply_text("Бот временно недоступен."); return

    # Обычное сообщение от пользователя (или админа не в тесте)
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
        user_id = ticket[1]
        active_chats[user_id] = admin.id
        user_chat_admin[admin.id] = user_id
        await context.bot.send_message(admin.id, f"✉️ Вы подключились к тикету #{tid}.", reply_markup=operator_chat_keyboard())
        await query.edit_message_text(f"Тикет #{tid} взят в работу.")
        try: await context.bot.send_message(user_id, "👤 Оператор подключился. Можете писать ваш вопрос.")
        except: pass
    elif data.startswith("endchat_"):
        tid = int(data.split("_")[1])
        if admin.id in user_chat_admin:
            uid = user_chat_admin.pop(admin.id)
            active_chats.pop(uid, None)
        close_ticket(tid)
        await query.edit_message_text("✅ Чат завершён, тикет закрыт.")
        await context.bot.send_message(admin.id, "✅ Сеанс завершён.", reply_markup=admin_keyboard())
        try: await context.bot.send_message(uid, "🔒 Чат с оператором завершён.")
        except: pass

async def end_chat_session(update_or_query, context, admin_id, user_id, ticket_id):
    if admin_id in user_chat_admin:
        user_chat_admin.pop(admin_id)
        active_chats.pop(user_id, None)
    if ticket_id: close_ticket(ticket_id)
    await context.bot.send_message(admin_id, "✅ Сеанс завершён.", reply_markup=admin_keyboard())
    try: await context.bot.send_message(user_id, "🔒 Чат с оператором завершён.")
    except: pass

# ---------- Управление ботом ----------
is_running = False
application = None
polling_task = None

async def start_support():
    global is_running, application, polling_task
    if is_running: return
    if not BOT_TOKEN:
        logging.warning("SUPPORT_BOT_TOKEN не задан"); return
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    # Обработчики кнопок (точные совпадения)
    app.add_handler(MessageHandler(filters.Regex("^❌ Завершить чат$"), end_chat_button))
    app.add_handler(MessageHandler(filters.Regex("^🧪 Тестовый режим$"), test_mode_button))
    app.add_handler(MessageHandler(filters.Regex("^🔙 Выйти без закрытия$"), exit_without_close_button))
    app.add_handler(MessageHandler(filters.Regex("^🔙 Выйти из теста$"), exit_test_mode_button))
    # Стандартные кнопки меню
    app.add_handler(MessageHandler(filters.Regex("^🆘 Поддержка$"), support_button))
    app.add_handler(MessageHandler(filters.Regex("^📋 Мои тикеты$"), my_tickets_button))
    app.add_handler(MessageHandler(filters.Regex("^📋 Все тикеты$"), all_tickets_button))
    app.add_handler(MessageHandler(filters.Regex("^👥 Админы$"), admins_button))
    app.add_handler(MessageHandler(filters.Regex("^⚙️ Настройки$"), settings_button))
    # Обработчик всех остальных текстовых сообщений
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    # Callback'и
    app.add_handler(CallbackQueryHandler(req_operator_callback, pattern="^req_operator$"))
    app.add_handler(CallbackQueryHandler(take_ticket_callback, pattern="^(take_|endchat_)"))
    app.add_handler(CallbackQueryHandler(toggle_bot_callback, pattern="^toggle_bot$"))
    app.add_handler(CallbackQueryHandler(add_admin_callback, pattern="^add_admin$"))
    app.add_handler(CallbackQueryHandler(remove_admin_callback, pattern="^remove_admin$"))
    # Команды
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
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
