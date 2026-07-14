import asyncio, sqlite3, os, logging, json, aiohttp
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ConversationHandler, filters, ContextTypes

# Только эти два токена берутся из переменных окружения Render
BOT_TOKEN = os.environ.get("TDXT_BOT_TOKEN", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

# ------------------ НАСТРОЙКИ (вшиты) ------------------
MAIN_ADMIN_USERNAME = "Anopchenko2011"
ACCEPT_THRESHOLD = 1
REJECT_THRESHOLD = 1
DATABASE = "tdxt_bot.db"

# AI moderation (gpt-4o-mini)
AI_API_URL = "https://models.inference.ai.azure.com/chat/completions"
AI_MODEL = "gpt-4o-mini"
AI_MAX_TOKENS = 200
AI_TEMPERATURE = 0.7
AI_SYSTEM_PROMPT = "Ты — помощник, анализирующий заявки на партнёрство."
# --------------------------------------------------------

Q1, Q2, Q3, Q4, Q5, Q6, Q7, Q8, Q9, Q10, Q11, Q12 = range(12)

QUESTIONS = [
    "1️⃣ Сколько вам лет?",
    "2️⃣ Как вас зовут?",
    "3️⃣ Ваш ник в РБ",
    "4️⃣ В какой группе вы в Роблоксе? (Roblox Kids, Roblos, Селестра или просто Roblox)",
    "5️⃣ Что такое адекватность, почему это так должно влиять на вас и разрешение на использование прав? — Полным ответом ниже, если не отвечаете сразу отказано:\n(Нельзя брать из источников, только написать самому.)",
    "6️⃣ Как быть адекватным и вести себя адекватно, как надо использовать права партнёра и для чего они вообще нужны? Как надо разговаривать с партнёрами:",
    "7️⃣ Зачем мне вообще нужны эти права если я не адекват, или я всё же адекват? Права партнёра относятся только к адекватным и нормальным людям. Пример ненормального человека: ЫЫЫ Я СДЕЛАЮ РАЗДАЧУ И УДАЛЮ ВАШУ ИГРУ И ЭКОНОМИКУ ЫЫЫ ВАТ ВАМ ССЫЛКА НА ЧАТ ПАРТНЁРОВ И АДМИНОВ.\n\nПриведите свой ответ сюда:",
    "8️⃣ Каковы мои минусы или плюсы чтоб я мог стать партнёром и вообще стоит меня взять? По какой причине мы обязаны вас взять?",
    "9️⃣ Какое время вы сможете уделять игре нам и всему подобному, сколько можете играть? Хейтите ли вы игру или наоборот рады ей?\n\n[ ] [Время]",
    "🔟 Имеете ли вы свой канал? Собственно если нет можете публиковать на другие площадки но желательно YouTube так мы пытаемся доказать что мы лучше ПТТД и ТТД\n\n[ ]",
    "1️⃣1️⃣ Я уверен что могу помочь вам, я смогу помочь чем только понадобится и готов участвовать в съёмках игры, разрешено использовать внешность моего персонажа:\n\n[ ]",
    "1️⃣2️⃣ Скинь ссылки на ваши все каналы, где вы будете публиковать видео по игре 🎥"
]

active_chat = {}
chat_partner = {}
pending_reason = {}
pending_ban = {}
pending_delete = {}
pending_broadcast = set()
ai_review_enabled = False

def get_db():
    return sqlite3.connect(DATABASE, check_same_thread=False)

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY, username TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS pending_admins (username TEXT PRIMARY KEY)''')
    c.execute('''CREATE TABLE IF NOT EXISTS applications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, username TEXT, status TEXT DEFAULT 'pending',
        answers TEXT, created_at TEXT, reject_reason TEXT DEFAULT ''
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS votes (
        application_id INTEGER, admin_id INTEGER, vote TEXT,
        PRIMARY KEY (application_id, admin_id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS banned (user_id INTEGER PRIMARY KEY, reason TEXT DEFAULT '')''')
    c.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('applications_open', '1')")
    c.execute("INSERT OR IGNORE INTO pending_admins (username) VALUES ('clennidze')")
    c.execute('''CREATE TABLE IF NOT EXISTS ai_reviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        app_id INTEGER UNIQUE,
        decision TEXT NOT NULL,
        reason TEXT NOT NULL,
        status TEXT DEFAULT 'pending',
        reviewed_by INTEGER,
        reviewed_at TEXT,
        FOREIGN KEY (app_id) REFERENCES applications(id)
    )''')
    conn.commit()
    conn.close()

def get_all_admin_ids():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT user_id FROM admins")
    ids = [row[0] for row in c.fetchall()]
    conn.close()
    return ids

def add_admin_to_db(user_id, username):
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO admins VALUES (?, ?)", (user_id, username))
    conn.commit()
    conn.close()

def remove_admin_from_db(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def is_admin(user_id):
    return user_id in get_all_admin_ids()

def is_main_admin(username):
    return username and username.lower() == MAIN_ADMIN_USERNAME.lower()

def add_pending_admin(username):
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO pending_admins VALUES (?)", (username.lower(),))
    conn.commit()
    conn.close()

def get_and_clear_pending(username):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT 1 FROM pending_admins WHERE username = ?", (username.lower(),))
    exists = c.fetchone()
    if exists:
        c.execute("DELETE FROM pending_admins WHERE username = ?", (username.lower(),))
        conn.commit()
    conn.close()
    return exists is not None

def save_application(user_id, username, answers):
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO applications (user_id, username, status, answers, created_at) VALUES (?, ?, 'pending', ?, ?)",
              (user_id, username, json.dumps(answers, ensure_ascii=False), datetime.now().isoformat()))
    app_id = c.lastrowid
    conn.commit()
    conn.close()
    return app_id

def get_application(app_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM applications WHERE id=?", (app_id,))
    row = c.fetchone()
    conn.close()
    return row

def get_user_applications(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, status, created_at FROM applications WHERE user_id=? AND status != 'deleted' ORDER BY id DESC", (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows

def has_pending_application(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT 1 FROM applications WHERE user_id=? AND status='pending'", (user_id,))
    res = c.fetchone() is not None
    conn.close()
    return res

def get_applications_by_status(status):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, user_id, username, created_at FROM applications WHERE status=? ORDER BY id DESC", (status,))
    rows = c.fetchall()
    conn.close()
    return rows

def add_vote(app_id, admin_id, vote):
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO votes VALUES (?, ?, ?)", (app_id, admin_id, vote))
    conn.commit()
    conn.close()

def get_votes(app_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT admin_id, vote FROM votes WHERE application_id=?", (app_id,))
    votes = c.fetchall()
    conn.close()
    return votes

def count_votes(app_id):
    votes = get_votes(app_id)
    acc = sum(1 for _, v in votes if v == 'accept')
    rej = sum(1 for _, v in votes if v == 'reject')
    return acc, rej

def set_application_status(app_id, status):
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE applications SET status=? WHERE id=?", (status, app_id))
    conn.commit()
    conn.close()

def set_reject_reason(app_id, reason):
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE applications SET reject_reason=? WHERE id=?", (reason, app_id))
    conn.commit()
    conn.close()

def is_banned(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT 1 FROM banned WHERE user_id=?", (user_id,))
    res = c.fetchone() is not None
    conn.close()
    return res

def ban_user(user_id, reason):
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO banned (user_id, reason) VALUES (?, ?)", (user_id, reason))
    conn.commit()
    conn.close()

def unban_user(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM banned WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def get_banned_users():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT b.user_id, u.username, b.reason FROM banned b LEFT JOIN users u ON b.user_id = u.user_id")
    rows = c.fetchall()
    conn.close()
    return rows

def add_user(user_id, username):
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, username))
    conn.commit()
    conn.close()

def get_all_user_ids():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT user_id FROM users")
    ids = [row[0] for row in c.fetchall()]
    conn.close()
    return ids

def get_all_users():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT user_id, username FROM users")
    users = c.fetchall()
    conn.close()
    return users

def get_user_count():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    count = c.fetchone()[0]
    conn.close()
    return count

def get_ban_count():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM banned")
    count = c.fetchone()[0]
    conn.close()
    return count

def get_admin_count():
    return len(get_all_admin_ids())

def get_app_counts():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT status, COUNT(*) FROM applications GROUP BY status")
    rows = c.fetchall()
    conn.close()
    counts = {"pending":0,"accepted":0,"rejected":0,"deleted":0}
    for status, cnt in rows:
        if status in counts:
            counts[status] = cnt
    return counts

def is_applications_open():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key='applications_open'")
    row = c.fetchone()
    open_flag = row and row[0] == '1'
    c.execute("SELECT value FROM settings WHERE key='scheduled_open_time'")
    sched = c.fetchone()
    conn.close()
    if sched:
        try:
            open_time = datetime.fromisoformat(sched[0])
            if datetime.now() >= open_time:
                set_applications_open(True)
                clear_scheduled_open()
                return True
            else:
                return False
        except:
            pass
    return open_flag

def set_applications_open(open: bool):
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE settings SET value=? WHERE key='applications_open'", ('1' if open else '0',))
    conn.commit()
    conn.close()

def schedule_reopen(seconds: int):
    set_applications_open(False)
    reopen_time = datetime.now() + timedelta(seconds=seconds)
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('scheduled_open_time', ?)", (reopen_time.isoformat(),))
    conn.commit()
    conn.close()

def clear_scheduled_open():
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM settings WHERE key='scheduled_open_time'")
    conn.commit()
    conn.close()

# ------------------ AI review DB functions ------------------
def get_pending_ai_reviews():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT r.id, r.app_id, r.decision, r.reason, a.user_id, a.username FROM ai_reviews r JOIN applications a ON r.app_id = a.id WHERE r.status = 'pending' ORDER BY r.id")
    rows = c.fetchall()
    conn.close()
    return rows

def has_ai_review(app_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT 1 FROM ai_reviews WHERE app_id = ?", (app_id,))
    exists = c.fetchone() is not None
    conn.close()
    return exists

def save_ai_review(app_id, decision, reason):
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO ai_reviews (app_id, decision, reason) VALUES (?, ?, ?)",
              (app_id, decision, reason))
    conn.commit()
    conn.close()

def confirm_ai_review(review_id, admin_id):
    conn = get_db()
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("UPDATE ai_reviews SET status = 'confirmed', reviewed_by = ?, reviewed_at = ? WHERE id = ?",
              (admin_id, now, review_id))
    conn.commit()
    conn.close()

def reject_ai_review(review_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE ai_reviews SET status = 'rejected' WHERE id = ?", (review_id,))
    conn.commit()
    conn.close()

def get_ai_review_by_id(review_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM ai_reviews WHERE id = ?", (review_id,))
    row = c.fetchone()
    conn.close()
    return row

async def ask_ai(prompt: str):
    if not GITHUB_TOKEN:
        return None, "❌ Не задан GITHUB_TOKEN"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": AI_MODEL,
        "messages": [
            {"role": "system", "content": AI_SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        "max_tokens": AI_MAX_TOKENS,
        "temperature": AI_TEMPERATURE
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(AI_API_URL, json=payload, headers=headers, timeout=30) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    answer = data["choices"][0]["message"]["content"]
                    return answer, None
                else:
                    return None, f"Ошибка AI: {resp.status}"
    except Exception as e:
        return None, f"Сетевая ошибка: {e}"

async def analyze_application(app_id):
    app = get_application(app_id)
    if not app or app[3] != "pending":
        return
    if has_ai_review(app_id):
        return
    answers = json.loads(app[4])
    qa_text = ""
    for i, (q, a) in enumerate(zip(QUESTIONS, answers), 1):
        qa_text += f"Вопрос {i}: {q}\nОтвет: {a}\n\n"
    prompt = f"""Проанализируй заявку на партнёрство. Ниже — вопросы и ответы пользователя.

{qa_text}
На основе ответов реши, стоит ли принять заявку (accept) или отклонить (reject).
Критерии: возраст (не менее 13 лет), адекватность, понимание обязанностей партнёра, готовность помогать проекту.

Верни ТОЛЬКО валидный JSON без Markdown:
{{"decision": "accept или reject", "reason": "краткое обоснование на русском языке"}}"""
    answer, error = await ask_ai(prompt)
    if error:
        return
    try:
        ai_result = json.loads(answer.strip().replace("```json", "").replace("```", ""))
        decision = ai_result.get("decision", "reject")
        reason = ai_result.get("reason", "Без обоснования")
        if decision not in ("accept", "reject"):
            return
    except:
        return
    save_ai_review(app_id, decision, reason)

# ------------------ Menu & Keyboard ------------------
MENU_BUTTONS = {
    "📋 Мои заявки", "📋 Все заявки", "✅ Принятые", "❌ Отклонённые",
    "🗑 Удалённые заявки", "🚫 Забаненные", "📖 Команды", "📝 Пройти тест",
    "🔒 Закрыть подачу заявок", "🔓 Открыть подачу заявок", "⏱ Закрыть на время",
    "🤖 AI Review"
}

def main_keyboard(user_id, username=None):
    if is_admin(user_id):
        buttons = [
            [KeyboardButton("📋 Все заявки"), KeyboardButton("✅ Принятые"), KeyboardButton("❌ Отклонённые")],
            [KeyboardButton("🗑 Удалённые заявки")],
        ]
        if is_applications_open():
            buttons.append([KeyboardButton("🔒 Закрыть подачу заявок"), KeyboardButton("⏱ Закрыть на время")])
        else:
            buttons.append([KeyboardButton("🔓 Открыть подачу заявок")])
        buttons.append([KeyboardButton("🚫 Забаненные")])
        buttons.append([KeyboardButton("📖 Команды")])
        buttons.append([KeyboardButton("📝 Пройти тест")])
        if is_main_admin(username):
            buttons.append([KeyboardButton("🤖 AI Review")])
    else:
        buttons = [
            [KeyboardButton("📋 Мои заявки")],
            [KeyboardButton("📖 Команды")],
            [KeyboardButton("📝 Пройти тест")]
        ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

def clear_all_pending(user_id: int):
    pending_reason.pop(user_id, None)
    pending_ban.pop(user_id, None)
    pending_delete.pop(user_id, None)
    pending_broadcast.discard(user_id)

# ---------- Command Handlers ----------
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_user(user.id, user.username or "unknown")
    if user.username and get_and_clear_pending(user.username):
        add_admin_to_db(user.id, user.username)
        await update.message.reply_text("✅ Вы были добавлены как администратор!")
    if not get_all_admin_ids() and user.username and is_main_admin(user.username):
        add_admin_to_db(user.id, user.username)
        await update.message.reply_text("👑 Вы главный администратор TDXT!")
    await update.message.reply_text(
        "👋 Добро пожаловать в официального бота TDXT | Защита башни x туалет!\n"
        "Используйте кнопки ниже.\n"
        "Для списка команд нажмите /help",
        reply_markup=main_keyboard(user.id, user.username)
    )

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    is_adm = is_admin(user.id)
    is_main = is_main_admin(user.username)
    text = "📖 <b>Список команд:</b>\n\n"
    text += "/test – Подать заявку\n"
    text += "/help – Показать этот список\n"
    if is_adm:
        text += "/stats – Статистика бота\n"
        text += "/users – Список всех пользователей\n"
        text += "/ban @username – Забанить пользователя\n"
        text += "/unban @username – Разбанить пользователя\n"
        text += "/deleteapp ID – Удалить заявку\n"
        text += "/broadcast – Рассылка всем пользователям\n"
        text += "/openapps – Открыть приём заявок\n"
        text += "/closeapps – Закрыть приём заявок\n"
    if is_main:
        text += "/addadmin @username – Добавить админа (только главный)\n"
        text += "/removeadmin @username – Удалить админа (только главный)\n"
        text += "/aireview on/off/run/list – Управление AI-модерацией заявок\n"
    await update.message.reply_text(text, parse_mode="HTML")

async def commands_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_help(update, context)

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Только администратор.")
        return
    users = get_user_count()
    admins = get_admin_count()
    bans = get_ban_count()
    counts = get_app_counts()
    text = (
        f"📊 <b>Статистика бота</b>\n"
        f"👥 Пользователей: {users}\n"
        f"👑 Администраторов: {admins}\n"
        f"🚫 Забанено: {bans}\n\n"
        f"📋 Заявки:\n"
        f"  ⏳ Ожидают: {counts['pending']}\n"
        f"  ✅ Принято: {counts['accepted']}\n"
        f"  ❌ Отклонено: {counts['rejected']}\n"
        f"  🗑 Удалено: {counts['deleted']}"
    )
    await update.message.reply_text(text, parse_mode="HTML")

async def cmd_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Только администратор.")
        return
    users = get_all_users()
    if not users:
        await update.message.reply_text("👥 В боте ещё нет зарегистрированных пользователей.")
        return
    text = "👥 <b>Список пользователей:</b>\n"
    for i, (user_id, username) in enumerate(users, 1):
        name = f"@{username}" if username else f"ID:{user_id}"
        text += f"{i}. {name} (ID: {user_id})\n"
    if len(text) > 4096:
        for part in [text[i:i+4096] for i in range(0, len(text), 4096)]:
            await update.message.reply_text(part, parse_mode="HTML")
    else:
        await update.message.reply_text(text, parse_mode="HTML")

async def cmd_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Только администратор.")
        return
    if not context.args:
        await update.message.reply_text("Использование: /ban @username")
        return
    username = context.args[0].lstrip("@").lower()
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE username=?", (username,))
    row = c.fetchone()
    conn.close()
    if not row:
        await update.message.reply_text("Пользователь не найден в базе.")
        return
    target_user = row[0]
    if is_banned(target_user):
        await update.message.reply_text("Пользователь уже забанен.")
        return
    pending_ban[update.effective_user.id] = target_user
    await update.message.reply_text("Введите причину бана (следующим сообщением).")

async def cmd_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Только администратор.")
        return
    if not context.args:
        await update.message.reply_text("Использование: /unban @username")
        return
    username = context.args[0].lstrip("@").lower()
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE username=?", (username,))
    row = c.fetchone()
    conn.close()
    if not row:
        await update.message.reply_text("Пользователь не найден в базе.")
        return
    target_user = row[0]
    if not is_banned(target_user):
        await update.message.reply_text("Пользователь не забанен.")
        return
    unban_user(target_user)
    await update.message.reply_text(f"✅ Пользователь @{username} разбанен.")

async def cmd_deleteapp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Только администратор.")
        return
    if not context.args:
        await update.message.reply_text("Использование: /deleteapp <ID заявки>")
        return
    try:
        app_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Некорректный ID заявки.")
        return
    app = get_application(app_id)
    if not app:
        await update.message.reply_text("Заявка не найдена.")
        return
    if app[3] == "deleted":
        await update.message.reply_text("Заявка уже удалена.")
        return
    pending_delete[update.effective_user.id] = app_id
    await update.message.reply_text("Введите причину удаления заявки (следующим сообщением).")

async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Только администратор.")
        return
    pending_broadcast.add(update.effective_user.id)
    await update.message.reply_text("📢 Введите текст для рассылки всем пользователям:")

async def cmd_openapps(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Только администратор.")
        return
    clear_scheduled_open()
    set_applications_open(True)
    msg_text = "🔓 Приём заявок снова открыт! Ждём ваши анкеты! 🎉"
    users = get_all_user_ids()
    count = 0
    for uid in users:
        try:
            await context.bot.send_message(chat_id=uid, text=msg_text)
            count += 1
        except:
            pass
    await update.message.reply_text(f"✅ Приём заявок открыт. Уведомление отправлено {count} пользователям.",
                                    reply_markup=main_keyboard(update.effective_user.id, update.effective_user.username))

async def cmd_closeapps(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Только администратор.")
        return
    clear_scheduled_open()
    set_applications_open(False)
    msg_text = "🔒 Внимание! Приём заявок временно приостановлен. Мы скоро вернёмся! 🛑"
    users = get_all_user_ids()
    count = 0
    for uid in users:
        try:
            await context.bot.send_message(chat_id=uid, text=msg_text)
            count += 1
        except:
            pass
    await update.message.reply_text(f"✅ Приём заявок закрыт. Уведомление отправлено {count} пользователям.",
                                    reply_markup=main_keyboard(update.effective_user.id, update.effective_user.username))

async def my_applications(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_all_pending(update.effective_user.id)
    user = update.effective_user
    apps = get_user_applications(user.id)
    if not apps:
        await update.message.reply_text("У вас пока нет заявок.")
        return
    text = "📋 <b>Ваши заявки:</b>\n\n"
    for app in apps:
        app_id, status, created = app
        emoji = {"pending": "⏳", "accepted": "✅", "rejected": "❌", "deleted": "🗑"}.get(status, "")
        text += f"#{app_id} — {emoji} {status}\n📅 {created[:10]}\n\n"
    await update.message.reply_text(text, parse_mode="HTML")

async def start_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_applications_open():
        await update.message.reply_text("🔒 Приём заявок временно закрыт. Попробуйте позже.")
        return ConversationHandler.END
    if is_banned(update.effective_user.id):
        await update.message.reply_text("🚫 Вы заблокированы и не можете подавать заявки.")
        return ConversationHandler.END
    if has_pending_application(update.effective_user.id):
        await update.message.reply_text("У вас уже есть ожидающая заявка. Дождитесь решения администрации.")
        return ConversationHandler.END
    await update.message.reply_text("Начинаем тест 📝\nВопрос 1/12")
    await update.message.reply_text(QUESTIONS[0])
    return Q1

async def handle_q1(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['answers'] = [update.message.text]
    await update.message.reply_text(QUESTIONS[1])
    return Q2
async def handle_q2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['answers'].append(update.message.text)
    await update.message.reply_text(QUESTIONS[2])
    return Q3
async def handle_q3(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['answers'].append(update.message.text)
    await update.message.reply_text(QUESTIONS[3])
    return Q4
async def handle_q4(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['answers'].append(update.message.text)
    await update.message.reply_text(QUESTIONS[4])
    return Q5
async def handle_q5(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['answers'].append(update.message.text)
    await update.message.reply_text(QUESTIONS[5])
    return Q6
async def handle_q6(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['answers'].append(update.message.text)
    await update.message.reply_text(QUESTIONS[6])
    return Q7
async def handle_q7(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['answers'].append(update.message.text)
    await update.message.reply_text(QUESTIONS[7])
    return Q8
async def handle_q8(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['answers'].append(update.message.text)
    await update.message.reply_text(QUESTIONS[8])
    return Q9
async def handle_q9(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['answers'].append(update.message.text)
    await update.message.reply_text(QUESTIONS[9])
    return Q10
async def handle_q10(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['answers'].append(update.message.text)
    await update.message.reply_text(QUESTIONS[10])
    return Q11
async def handle_q11(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['answers'].append(update.message.text)
    await update.message.reply_text(QUESTIONS[11])
    return Q12
async def handle_q12(update: Update, context: ContextTypes.DEFAULT_TYPE):
    answers = context.user_data['answers'] + [update.message.text]
    user = update.effective_user
    app_id = save_application(user.id, user.username or "unknown", answers)
    await update.message.reply_text(
        "✅ <b>Ваша заявка принята!</b>\n"
        "Администраторы рассмотрят её в ближайшее время.\n"
        f"Номер заявки: #{app_id}",
        parse_mode="HTML"
    )
    if ai_review_enabled:
        asyncio.create_task(analyze_application(app_id))
    await update.message.reply_text("Вы можете продолжить, используя меню.", reply_markup=main_keyboard(user.id, user.username))
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_all_pending(update.effective_user.id)
    await update.message.reply_text("Тест отменён.", reply_markup=main_keyboard(update.effective_user.id, update.effective_user.username))
    return ConversationHandler.END

async def all_apps_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_all_pending(update.effective_user.id)
    await show_applications_by_status(update, "pending")

async def accepted_apps_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_all_pending(update.effective_user.id)
    await show_applications_by_status(update, "accepted")

async def rejected_apps_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_all_pending(update.effective_user.id)
    await show_applications_by_status(update, "rejected")

async def deleted_apps_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_all_pending(update.effective_user.id)
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Только для администраторов.")
        return
    await show_applications_by_status(update, "deleted")

async def banned_users_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_all_pending(update.effective_user.id)
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Только администратор.")
        return
    banned = get_banned_users()
    if not banned:
        await update.message.reply_text("Нет забаненных пользователей.")
        return
    text = "🚫 <b>Забаненные пользователи:</b>\n"
    buttons = []
    for user_id, username, reason in banned:
        name = f"@{username}" if username else f"ID:{user_id}"
        buttons.append([InlineKeyboardButton(f"Разбанить {name}", callback_data=f"unban_{user_id}")])
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")

async def toggle_applications(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_all_pending(update.effective_user.id)
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Только администратор.")
        return
    clear_scheduled_open()
    was_open = is_applications_open()
    set_applications_open(not was_open)
    now_open = not was_open
    if now_open:
        msg_text = "🔓 Приём заявок снова открыт! Ждём ваши анкеты! 🎉"
    else:
        msg_text = "🔒 Внимание! Приём заявок временно приостановлен. Мы скоро вернёмся! 🛑"
    users = get_all_user_ids()
    count = 0
    for uid in users:
        try:
            await context.bot.send_message(chat_id=uid, text=msg_text)
            count += 1
        except Exception as e:
            logging.warning(f"Не удалось отправить уведомление {uid}: {e}")
    await update.message.reply_text(f"✅ Режим подачи заявок изменён. Уведомление отправлено {count} пользователям.",
                                    reply_markup=main_keyboard(update.effective_user.id, update.effective_user.username))

async def close_timed_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_all_pending(update.effective_user.id)
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Только администратор.")
        return
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🕐 1 час", callback_data="close_time_3600")],
        [InlineKeyboardButton("🕑 3 часа", callback_data="close_time_10800")],
        [InlineKeyboardButton("🕓 6 часов", callback_data="close_time_21600")],
        [InlineKeyboardButton("🕛 12 часов", callback_data="close_time_43200")],
        [InlineKeyboardButton("🕟 24 часа (1 день)", callback_data="close_time_86400")],
        [InlineKeyboardButton("Отмена", callback_data="close_time_cancel")]
    ])
    await update.message.reply_text("⏱ Выберите срок закрытия приёма заявок:", reply_markup=keyboard)

async def close_time_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        await query.answer("⛔ Только администратор.", show_alert=True)
        return
    data = query.data
    if data == "close_time_cancel":
        await query.edit_message_text("⏱ Закрытие на время отменено.")
        return
    seconds = int(data.split("_")[-1])
    schedule_reopen(seconds)
    reopen_time = datetime.now() + timedelta(seconds=seconds)
    await query.edit_message_text(
        f"🔒 Приём заявок закрыт на {seconds//3600} ч. и откроется автоматически в {reopen_time.strftime('%H:%M')}."
    )
    users = get_all_user_ids()
    for uid in users:
        try:
            await context.bot.send_message(
                chat_id=uid,
                text=f"🔒 Внимание! Приём заявок временно закрыт до {reopen_time.strftime('%H:%M')}."
            )
        except:
            pass

async def open_app_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    admin = query.from_user
    if not is_admin(admin.id):
        await query.answer("⛔ Нет доступа", show_alert=True)
        return
    app_id = int(query.data.split("_")[-1])
    app = get_application(app_id)
    if not app:
        await query.edit_message_text("Заявка не найдена.")
        return
    _, user_id, username, status, answers_json, created, reason = app
    answers = json.loads(answers_json)
    text = f"📩 <b>Заявка #{app_id}</b>\n"
    text += f"👤 @{username} (ID: {user_id})\n"
    text += f"Статус: {status}\n📅 {created[:10]}\n"
    if reason:
        text += f"Причина: {reason}\n"
    text += "\n"
    for i, (q, a) in enumerate(zip(QUESTIONS, answers), 1):
        text += f"<b>{q}</b>\n➡️ {a}\n\n"
    buttons = []
    if status == "pending":
        acc, rej = count_votes(app_id)
        buttons.append([
            InlineKeyboardButton(f"✅ Принять ({acc})", callback_data=f"accept_{app_id}"),
            InlineKeyboardButton(f"❌ Отклонить ({rej})", callback_data=f"reject_{app_id}")
        ])
    if is_admin(admin.id):
        buttons.append([InlineKeyboardButton("💬 Связаться с заявителем", callback_data=f"chat_{user_id}")])
        if is_banned(user_id):
            buttons.append([InlineKeyboardButton("✅ Разбанить пользователя", callback_data=f"unban_{user_id}")])
        else:
            buttons.append([InlineKeyboardButton("🚫 Забанить пользователя", callback_data=f"ban_{user_id}")])
        buttons.append([InlineKeyboardButton("🗑 Удалить заявку", callback_data=f"delapp_{app_id}")])
    buttons.append([InlineKeyboardButton("🔙 Назад к списку", callback_data=f"admin_list_{status}")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")

async def vote_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    admin_id = query.from_user.id
    if not is_admin(admin_id):
        await query.answer("⛔ Вы не администратор.", show_alert=True)
        return
    data = query.data
    action, app_id_str = data.split("_")
    app_id = int(app_id_str)
    app = get_application(app_id)
    if not app or app[3] != "pending":
        await query.edit_message_text("Заявка уже обработана.")
        return
    vote = action
    add_vote(app_id, admin_id, vote)
    accepts, rejects = count_votes(app_id)
    if accepts >= ACCEPT_THRESHOLD:
        set_application_status(app_id, "accepted")
        await query.edit_message_text(f"✅ Заявка #{app_id} принята (голосов за: {accepts}).")
        app = get_application(app_id)
        if app:
            user_id = app[1]
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text="🎉 <b>Поздравляю!</b>\nВы теперь официально партнёр в <b>TDXT | Защита башни x туалет</b>!\n\n🔗 Вступайте в чат: https://t.me/+k1iuZTvjHT03OWFi",
                    parse_mode="HTML"
                )
            except:
                pass
    elif rejects >= REJECT_THRESHOLD:
        set_application_status(app_id, "rejected")
        pending_reason[admin_id] = app_id
        await query.edit_message_text(
            f"❌ Заявка #{app_id} отклонена (голосов против: {rejects}).\n\n"
            "<b>Напишите причину отказа (следующим сообщением):</b>\n"
            "Для отмены нажмите любую кнопку меню.",
            parse_mode="HTML"
        )
    else:
        await query.edit_message_reply_markup(
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(f"✅ Принять ({accepts})", callback_data=f"accept_{app_id}"),
                InlineKeyboardButton(f"❌ Отклонить ({rejects})", callback_data=f"reject_{app_id}")
            ]])
        )

async def ban_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        await query.answer("⛔ Только администратор.", show_alert=True)
        return
    parts = query.data.split("_")
    target_user = int(parts[-1])
    pending_ban[query.from_user.id] = target_user
    await query.edit_message_text(
        f"🚫 Вы собираетесь забанить пользователя (ID: {target_user}).\nНапишите причину бана (следующим сообщением).\nДля отмены нажмите кнопку меню."
    )

async def unban_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        await query.answer("⛔ Только администратор.", show_alert=True)
        return
    parts = query.data.split("_")
    target_user = int(parts[-1])
    unban_user(target_user)
    username = None
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT username FROM users WHERE user_id=?", (target_user,))
    row = c.fetchone()
    if row:
        username = row[0]
    conn.close()
    name = f"@{username}" if username else f"ID:{target_user}"
    await query.edit_message_text(f"✅ Пользователь {name} разбанен.")

async def delete_app_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        await query.answer("⛔ Только администратор.", show_alert=True)
        return
    parts = query.data.split("_")
    app_id = int(parts[-1])
    pending_delete[query.from_user.id] = app_id
    await query.edit_message_text(
        f"🗑 Вы собираетесь удалить заявку #{app_id}.\nНапишите причину удаления (следующим сообщением).\nДля отмены нажмите кнопку меню."
    )

async def chat_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    admin_id = query.from_user.id
    if not is_admin(admin_id):
        await query.answer("⛔ Только администратор.", show_alert=True)
        return
    if admin_id in active_chat:
        await query.answer("Вы уже находитесь в чате с другим пользователем.", show_alert=True)
        return
    target_user = int(query.data.split("_")[1])
    if target_user in chat_partner:
        await query.answer("С этим пользователем уже общается другой администратор.", show_alert=True)
        return
    active_chat[admin_id] = target_user
    chat_partner[target_user] = admin_id
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Завершить чат", callback_data="end_chat")]])
    await query.edit_message_text(
        f"💬 Вы начали чат с пользователем ID:{target_user}.\n"
        "Все ваши следующие сообщения будут пересылаться ему.\n"
        "Для завершения нажмите кнопку ниже.",
        reply_markup=keyboard
    )
    try:
        await context.bot.send_message(
            chat_id=target_user,
            text="💬 С вами связался администратор. Можете отвечать на это сообщение."
        )
    except:
        await query.message.reply_text("⚠️ Не удалось уведомить пользователя.")

async def end_chat_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    admin_id = query.from_user.id
    if admin_id not in active_chat:
        await query.answer("Вы не в чате.", show_alert=True)
        return
    user_id = active_chat.pop(admin_id)
    chat_partner.pop(user_id, None)
    await query.edit_message_text("🔒 Чат завершён.")
    try:
        await context.bot.send_message(chat_id=user_id, text="🔒 Администратор завершил чат.")
    except:
        pass
    try:
        await context.bot.send_message(
            chat_id=admin_id,
            text="Вы вернулись в обычный режим.",
            reply_markup=main_keyboard(admin_id)
        )
    except:
        pass

async def handle_chat_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id in active_chat:
        target = active_chat[user.id]
        try:
            await context.bot.send_message(chat_id=target, text=f"Сообщение от администратора:\n{update.message.text}")
        except:
            await update.message.reply_text("⚠️ Не удалось отправить сообщение.")
        return
    if user.id in chat_partner:
        target = chat_partner[user.id]
        try:
            await context.bot.send_message(chat_id=target, text=f"Сообщение от пользователя @{user.username or user.id}:\n{update.message.text}")
        except:
            await update.message.reply_text("⚠️ Администратор сейчас недоступен.")
        return

async def handle_admin_username_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    action = context.user_data.get('action')
    if not action:
        return False
    text = update.message.text.strip()
    if text in MENU_BUTTONS:
        clear_all_pending(update.effective_user.id)
        return False
    username = text.lstrip("@")
    if not username:
        await update.message.reply_text("Некорректный формат. Введите @username:")
        return True
    if action == 'add_admin':
        if not is_main_admin(update.effective_user.username):
            await update.message.reply_text("⛔ Только главный администратор может добавлять админов.")
            clear_all_pending(update.effective_user.id)
            return True
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT user_id FROM admins WHERE username=?", (username.lower(),))
        exists = c.fetchone()
        conn.close()
        if exists:
            await update.message.reply_text("ℹ️ Этот пользователь уже администратор.")
        else:
            add_pending_admin(username)
            await update.message.reply_text(f"✅ @{username} добавлен в список ожидания. Попросите его запустить /start.")
        clear_all_pending(update.effective_user.id)
        return True
    elif action == 'remove_admin':
        if not is_main_admin(update.effective_user.username):
            await update.message.reply_text("⛔ Только главный администратор может удалять админов.")
            clear_all_pending(update.effective_user.id)
            return True
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT user_id FROM admins WHERE username=?", (username.lower(),))
        row = c.fetchone()
        if row:
            remove_admin_from_db(row[0])
            await update.message.reply_text(f"❌ @{username} удалён из администраторов.")
        else:
            await update.message.reply_text("ℹ️ Такой администратор не найден.")
        conn.close()
        clear_all_pending(update.effective_user.id)
        return True
    return True

async def handle_reject_reason_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in pending_reason:
        return False
    text = update.message.text.strip()
    if text in MENU_BUTTONS:
        del pending_reason[user_id]
        return False
    app_id = pending_reason.pop(user_id)
    set_reject_reason(app_id, text)
    app = get_application(app_id)
    if app:
        applicant_id = app[1]
        try:
            await context.bot.send_message(
                chat_id=applicant_id,
                text=f"😔 <b>Вам отказали.</b>\nПричина: {text}\nПопробуйте позже.",
                parse_mode="HTML"
            )
        except:
            pass
    await update.message.reply_text("✅ Причина отказа сохранена и отправлена заявителю.")
    return True

async def handle_ban_reason_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in pending_ban:
        return False
    text = update.message.text.strip()
    if text in MENU_BUTTONS:
        del pending_ban[user_id]
        return False
    target_user = pending_ban.pop(user_id)
    ban_user(target_user, text)
    await update.message.reply_text(f"🚫 Пользователь заблокирован. Причина: {text}")
    try:
        await context.bot.send_message(chat_id=target_user, text=f"🚫 Вы были забанены администрацией. Причина: {text}")
    except:
        pass
    return True

async def handle_delete_reason_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in pending_delete:
        return False
    text = update.message.text.strip()
    if text in MENU_BUTTONS:
        del pending_delete[user_id]
        return False
    app_id = pending_delete.pop(user_id)
    set_application_status(app_id, "deleted")
    set_reject_reason(app_id, text)
    app = get_application(app_id)
    if app:
        applicant_id = app[1]
        try:
            await context.bot.send_message(
                chat_id=applicant_id,
                text=f"🗑 Ваша заявка #{app_id} была удалена администрацией. Причина: {text}",
                parse_mode="HTML"
            )
        except:
            pass
    await update.message.reply_text("✅ Заявка удалена.")
    return True

async def handle_broadcast_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in pending_broadcast:
        return False
    text = update.message.text.strip()
    if text in MENU_BUTTONS:
        pending_broadcast.discard(user_id)
        return False
    pending_broadcast.discard(user_id)
    users = get_all_user_ids()
    count = 0
    for uid in users:
        try:
            await context.bot.send_message(chat_id=uid, text=text)
            count += 1
        except Exception as e:
            logging.warning(f"Не удалось отправить сообщение {uid}: {e}")
    await update.message.reply_text(f"✅ Рассылка завершена. Сообщение отправлено {count} пользователям.")
    return True

async def show_applications_by_status(update: Update, status: str):
    apps = get_applications_by_status(status)
    status_names = {"pending": "ожидающих", "accepted": "принятых", "rejected": "отклонённых", "deleted": "удалённых"}
    title = status_names.get(status, status)
    if not apps:
        text = f"Заявок со статусом «{title}» нет."
        if update.callback_query:
            await update.callback_query.edit_message_text(text)
        else:
            await update.message.reply_text(text)
        return
    text = f"📋 <b>Список {title} заявок</b>\nВсего: {len(apps)}"
    buttons = []
    for app in apps:
        app_id, uid, username, created = app
        buttons.append([InlineKeyboardButton(f"📄 Заявка #{app_id} от @{username}", callback_data=f"open_app_{app_id}")])
    reply_markup = InlineKeyboardMarkup(buttons)
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")

# ------------------ AI Review Management ------------------
async def ai_review_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_main_admin(user.username):
        await update.message.reply_text("⛔ Только главный администратор.")
        return
    if not context.args:
        await update.message.reply_text(
            "Использование:\n"
            "/aireview on — включить автоматический анализ новых заявок\n"
            "/aireview off — выключить\n"
            "/aireview run — проанализировать все текущие заявки\n"
            "/aireview list — показать список решений ИИ"
        )
        return
    sub = context.args[0].lower()
    global ai_review_enabled
    if sub == "on":
        ai_review_enabled = True
        await update.message.reply_text("✅ AI-модерация заявок включена. Новые заявки будут автоматически анализироваться.")
    elif sub == "off":
        ai_review_enabled = False
        await update.message.reply_text("❌ AI-модерация выключена.")
    elif sub == "run":
        apps = get_applications_by_status("pending")
        if not apps:
            await update.message.reply_text("Нет ожидающих заявок.")
            return
        msg = await update.message.reply_text(f"🔄 Анализирую {len(apps)} заявок...")
        for app in apps:
            await analyze_application(app[0])
        await msg.edit_text(f"✅ Анализ завершён. Используйте /aireview list для просмотра.")
    elif sub == "list":
        reviews = get_pending_ai_reviews()
        if not reviews:
            await update.message.reply_text("Нет нерассмотренных решений ИИ.")
            return
        text = "🤖 <b>Предложения ИИ по заявкам:</b>\n"
        keyboard = []
        for rev in reviews:
            review_id, app_id, decision, reason, user_id, username = rev
            name = f"@{username}" if username else f"ID:{user_id}"
            emoji = "✅" if decision == "accept" else "❌"
            text += f"🔹 Заявка #{app_id} ({name}) — {emoji} {decision}\n   {reason}\n\n"
            keyboard.append([
                InlineKeyboardButton(f"✅ Принять #{app_id}", callback_data=f"confirm_ai_{review_id}"),
                InlineKeyboardButton(f"❌ Отменить #{app_id}", callback_data=f"reject_ai_{review_id}")
            ])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=reply_markup)
    else:
        await update.message.reply_text("Неизвестная подкоманда. Используйте on/off/run/list.")

async def ai_review_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.args = ["list"]
    await ai_review_cmd(update, context)

async def confirm_ai_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    admin = query.from_user
    if not is_main_admin(admin.username):
        await query.answer("⛔ Только главный администратор.", show_alert=True)
        return
    data = query.data.split("_")
    review_id = int(data[-1])
    review = get_ai_review_by_id(review_id)
    if not review or review[4] != 'pending':
        await query.edit_message_text("Решение уже обработано.")
        return
    app_id = review[1]
    decision = review[2]
    reason = review[3]
    if decision == "accept":
        set_application_status(app_id, "accepted")
    else:
        set_reject_reason(app_id, reason)
        set_application_status(app_id, "rejected")
    confirm_ai_review(review_id, admin.id)
    app = get_application(app_id)
    if app:
        try:
            if decision == "accept":
                text = f"🎉 <b>Поздравляю!</b>\nВы теперь официально партнёр в <b>TDXT</b>!\nКомментарий AI: {reason}"
            else:
                text = f"😔 <b>Вам отказали.</b>\nПричина (анализ AI): {reason}"
            await context.bot.send_message(chat_id=app[1], text=text, parse_mode="HTML")
        except:
            pass
    await query.edit_message_text(f"✅ Решение ИИ по заявке #{app_id} применено: {decision}.")

async def reject_ai_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    admin = query.from_user
    if not is_main_admin(admin.username):
        await query.answer("⛔ Только главный администратор.", show_alert=True)
        return
    data = query.data.split("_")
    review_id = int(data[-1])
    review = get_ai_review_by_id(review_id)
    if not review or review[4] != 'pending':
        await query.edit_message_text("Решение уже обработано.")
        return
    reject_ai_review(review_id)
    await query.edit_message_text(f"🚫 Предложение ИИ по заявке #{review[1]} отклонено. Заявка оставлена без изменений.")

# ---------- Bot management ----------
is_running = False
application = None
polling_task = None

async def start_tdxt():
    global is_running, application, polling_task, ai_review_enabled
    if is_running: return
    if not BOT_TOKEN:
        logging.warning("TDXT_BOT_TOKEN не задан")
        return
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_chat_message), group=-1)
    app.add_handler(MessageHandler(filters.Regex("^📋 Мои заявки$"), my_applications))
    app.add_handler(MessageHandler(filters.Regex("^📋 Все заявки$"), all_apps_button))
    app.add_handler(MessageHandler(filters.Regex("^✅ Принятые$"), accepted_apps_button))
    app.add_handler(MessageHandler(filters.Regex("^❌ Отклонённые$"), rejected_apps_button))
    app.add_handler(MessageHandler(filters.Regex("^🗑 Удалённые заявки$"), deleted_apps_button))
    app.add_handler(MessageHandler(filters.Regex("^🚫 Забаненные$"), banned_users_button))
    app.add_handler(MessageHandler(filters.Regex("^📖 Команды$"), commands_button))
    app.add_handler(MessageHandler(filters.Regex("^🔒 Закрыть подачу заявок$"), toggle_applications))
    app.add_handler(MessageHandler(filters.Regex("^🔓 Открыть подачу заявок$"), toggle_applications))
    app.add_handler(MessageHandler(filters.Regex("^⏱ Закрыть на время$"), close_timed_button))
    app.add_handler(MessageHandler(filters.Regex("^🤖 AI Review$"), ai_review_button))
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("users", cmd_users))
    app.add_handler(CommandHandler("ban", cmd_ban))
    app.add_handler(CommandHandler("unban", cmd_unban))
    app.add_handler(CommandHandler("deleteapp", cmd_deleteapp))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))
    app.add_handler(CommandHandler("openapps", cmd_openapps))
    app.add_handler(CommandHandler("closeapps", cmd_closeapps))
    app.add_handler(CommandHandler("aireview", ai_review_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_username_input), group=1)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_reject_reason_input), group=2)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ban_reason_input), group=3)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_delete_reason_input), group=4)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_broadcast_input), group=5)
    conv_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^📝 Пройти тест$"), start_test),
            CommandHandler("test", start_test)
        ],
        states={
            Q1: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_q1)],
            Q2: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_q2)],
            Q3: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_q3)],
            Q4: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_q4)],
            Q5: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_q5)],
            Q6: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_q6)],
            Q7: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_q7)],
            Q8: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_q8)],
            Q9: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_q9)],
            Q10: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_q10)],
            Q11: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_q11)],
            Q12: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_q12)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(vote_callback, pattern=r"^(accept|reject)_\d+$"))
    app.add_handler(CallbackQueryHandler(ban_callback, pattern="^ban_"))
    app.add_handler(CallbackQueryHandler(unban_callback, pattern="^unban_"))
    app.add_handler(CallbackQueryHandler(delete_app_callback, pattern="^delapp_"))
    app.add_handler(CallbackQueryHandler(close_time_callback, pattern="^close_time_"))
    app.add_handler(CallbackQueryHandler(open_app_callback, pattern="^open_app_"))
    app.add_handler(CallbackQueryHandler(chat_callback, pattern="^chat_"))
    app.add_handler(CallbackQueryHandler(end_chat_callback, pattern="^end_chat$"))
    app.add_handler(CallbackQueryHandler(lambda u, c: show_applications_by_status(u, "pending"), pattern="^admin_list_pending$"))
    app.add_handler(CallbackQueryHandler(lambda u, c: show_applications_by_status(u, "accepted"), pattern="^admin_list_accepted$"))
    app.add_handler(CallbackQueryHandler(lambda u, c: show_applications_by_status(u, "rejected"), pattern="^admin_list_rejected$"))
    app.add_handler(CallbackQueryHandler(lambda u, c: show_applications_by_status(u, "deleted"), pattern="^admin_list_deleted$"))
    app.add_handler(CallbackQueryHandler(confirm_ai_callback, pattern=r"^confirm_ai_\d+$"))
    app.add_handler(CallbackQueryHandler(reject_ai_callback, pattern=r"^reject_ai_\d+$"))
    await app.initialize()
    await app.start()
    polling_task = asyncio.create_task(app.updater.start_polling())
    application = app
    is_running = True

async def stop_tdxt():
    global is_running, application, polling_task
    if not is_running: return
    if polling_task:
        polling_task.cancel()
        polling_task = None
    if application:
        await application.stop()
        await application.shutdown()
        application = None
    is_running = False
