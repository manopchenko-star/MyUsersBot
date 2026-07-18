import asyncio, sqlite3, os, logging, json, aiohttp, random, io, time
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from gtts import gTTS
from duckduckgo_search import DDGS

BOT_TOKEN = os.environ.get("GROUP_AI_BOT_TOKEN", "")
GITHUB_TOKEN32 = os.environ.get("GITHUB_TOKEN32", "")   # <-- отдельный ключ
FOUNDER_USERNAME = "Anopchenko2011"
AI_MODEL = "gpt-4o-mini"
AI_MAX_TOKENS = 250
AI_TEMPERATURE = 0.9
AI_SYSTEM_PROMPT = (
    "Ты — весёлый и разговорчивый собеседник в групповом чате. "
    "Отвечай кратко, используй смайлики. Ты можешь шутить, рассказывать истории и отвечать на любые вопросы. "
    "Если тебя просят озвучить текст — ответь командой /tts <текст>. "
    "Если просят видео — ответь командой /video <запрос>. "
    "Всегда будь дружелюбным."
)
DATABASE = "group_ai_bot.db"

context_data = {}
last_random_time = {}
group_admins = set()
founder_id = None

def get_db():
    return sqlite3.connect(DATABASE, check_same_thread=False)

def init_db():
    conn = get_db(); c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY)''')
    c.execute('''CREATE TABLE IF NOT EXISTS group_settings (
        chat_id INTEGER PRIMARY KEY,
        enabled INTEGER DEFAULT 0,
        random_tts INTEGER DEFAULT 0,
        random_video INTEGER DEFAULT 0,
        interval_minutes INTEGER DEFAULT 60
    )''')
    conn.commit(); conn.close()

def load_admins():
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT user_id FROM admins")
    return {row[0] for row in c.fetchall()}

def save_admin_to_db(user_id):
    conn = get_db(); c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO admins VALUES (?)", (user_id,))
    conn.commit(); conn.close()

def remove_admin_from_db(user_id):
    conn = get_db(); c = conn.cursor()
    c.execute("DELETE FROM admins WHERE user_id=?", (user_id,))
    conn.commit(); conn.close()

def get_group_settings(chat_id):
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT enabled, random_tts, random_video, interval_minutes FROM group_settings WHERE chat_id=?", (chat_id,))
    row = c.fetchone()
    if row:
        return {"enabled":bool(row[0]), "random_tts":bool(row[1]), "random_video":bool(row[2]), "interval":row[3]}
    return {"enabled":False, "random_tts":False, "random_video":False, "interval":60}

def set_group_setting(chat_id, key, value):
    conn = get_db(); c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO group_settings (chat_id) VALUES (?)", (chat_id,))
    if key == "enabled":
        c.execute("UPDATE group_settings SET enabled=? WHERE chat_id=?", (int(value), chat_id))
    elif key == "random_tts":
        c.execute("UPDATE group_settings SET random_tts=? WHERE chat_id=?", (int(value), chat_id))
    elif key == "random_video":
        c.execute("UPDATE group_settings SET random_video=? WHERE chat_id=?", (int(value), chat_id))
    elif key == "interval":
        c.execute("UPDATE group_settings SET interval_minutes=? WHERE chat_id=?", (int(value), chat_id))
    conn.commit(); conn.close()

def is_admin(user_id):
    return user_id in group_admins or user_id == founder_id

def is_founder_by_username(username):
    return username and username.lower() == FOUNDER_USERNAME.lower()

async def ask_ai(prompt, context=[]):
    if not GITHUB_TOKEN32:
        return "❌ GITHUB_TOKEN32 не задан."
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN32}", "Content-Type": "application/json"}
    messages = [{"role":"system","content":AI_SYSTEM_PROMPT}]
    for entry in context[-10:]:
        messages.append(entry)
    messages.append({"role":"user","content":prompt})
    payload = {"model":AI_MODEL, "messages":messages, "max_tokens":AI_MAX_TOKENS, "temperature":AI_TEMPERATURE}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post("https://models.inference.ai.azure.com/chat/completions", json=payload, headers=headers, timeout=30) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data["choices"][0]["message"]["content"]
                else:
                    return "⚠️ Ошибка AI"
    except Exception as e:
        return f"⚠️ Сетевая ошибка: {e}"

async def generate_tts(text):
    try:
        tts = gTTS(text, lang='ru')
        buf = io.BytesIO()
        tts.write_to_fp(buf)
        buf.seek(0)
        return buf
    except Exception as e:
        logging.error(f"TTS error: {e}")
        return None

async def search_video(query):
    try:
        with DDGS() as ddgs:
            results = list(ddgs.videos(query, max_results=1))
            if results:
                return results[0]['content']
    except Exception as e:
        logging.error(f"Video search error: {e}")
    return None

RANDOM_TTS_PHRASES = [
    "Кстати, а вы знали, что коты спят 70% своей жизни?",
    "Слушайте, я сегодня в хорошем настроении!",
    "А вы уже пили чай сегодня?",
    "Мне кажется, здесь слишком тихо...",
    "Почему никто не шутит? Давайте посмеёмся!",
    "Интересный факт: утки могут спать с одним открытым глазом!",
    "Что-то я проголодался... А вы?"
]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global founder_id
    user = update.effective_user
    if update.effective_chat.type == "private" and is_founder_by_username(user.username):
        founder_id = user.id
        save_admin_to_db(founder_id)
        await update.message.reply_text("✅ Вы признаны основателем! Используйте команды в группах, куда добавлен бот.")
        return
    if update.effective_chat.type in ("group", "supergroup"):
        await update.message.reply_text(
            "👋 Я AI-помощник группы. Команды:\n"
            "/enable – включить бота\n"
            "/disable – выключить\n"
            "/settings – настройки случайных сообщений\n"
            "/admin add @user – добавить админа (основатель)\n"
            "/admin remove @user – удалить админа\n"
            "Также я автоматически отвечаю на сообщения, когда включён."
        )
    else:
        await update.message.reply_text("Я работаю только в группах!")

async def enable_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Только администратор.")
        return
    chat_id = update.effective_chat.id
    set_group_setting(chat_id, "enabled", True)
    context_data.pop(chat_id, None)
    await update.message.reply_text("✅ Бот включён в этом чате.")

async def disable_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Только администратор.")
        return
    chat_id = update.effective_chat.id
    set_group_setting(chat_id, "enabled", False)
    context_data.pop(chat_id, None)
    await update.message.reply_text("❌ Бот выключен.")

async def settings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Только администратор.")
        return
    chat_id = update.effective_chat.id
    settings = get_group_settings(chat_id)
    tts_status = "🟢 Вкл" if settings['random_tts'] else "🔴 Выкл"
    video_status = "🟢 Вкл" if settings['random_video'] else "🔴 Выкл"
    keyboard = [
        [InlineKeyboardButton(f"Случайные голосовые: {tts_status}", callback_data="toggle_tts")],
        [InlineKeyboardButton(f"Случайные видео: {video_status}", callback_data="toggle_video")],
        [InlineKeyboardButton(f"Интервал: {settings['interval']} мин", callback_data="change_interval")],
        [InlineKeyboardButton("Закрыть", callback_data="close_settings")]
    ]
    await update.message.reply_text("⚙️ Настройки группы:", reply_markup=InlineKeyboardMarkup(keyboard))

async def settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        await query.answer("⛔ Только админ.", show_alert=True)
        return
    chat_id = query.message.chat_id
    data = query.data
    if data == "close_settings":
        await query.edit_message_text("Настройки закрыты.")
        return
    settings = get_group_settings(chat_id)
    if data == "toggle_tts":
        new_val = not settings['random_tts']
        set_group_setting(chat_id, "random_tts", new_val)
    elif data == "toggle_video":
        new_val = not settings['random_video']
        set_group_setting(chat_id, "random_video", new_val)
    elif data == "change_interval":
        context.user_data['waiting_interval'] = True
        await query.edit_message_text("Введите новый интервал в минутах (от 10 до 1440):")
        return
    settings = get_group_settings(chat_id)
    tts_status = "🟢 Вкл" if settings['random_tts'] else "🔴 Выкл"
    video_status = "🟢 Вкл" if settings['random_video'] else "🔴 Выкл"
    keyboard = [
        [InlineKeyboardButton(f"Случайные голосовые: {tts_status}", callback_data="toggle_tts")],
        [InlineKeyboardButton(f"Случайные видео: {video_status}", callback_data="toggle_video")],
        [InlineKeyboardButton(f"Интервал: {settings['interval']} мин", callback_data="change_interval")],
        [InlineKeyboardButton("Закрыть", callback_data="close_settings")]
    ]
    await query.edit_message_text("⚙️ Настройки группы:", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_founder_by_username(update.effective_user.username):
        await update.message.reply_text("⛔ Только основатель (@Anopchenko2011).")
        return
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("Использование: /admin add @user или /admin remove @user")
        return
    action = context.args[0].lower()
    username = context.args[1].lstrip("@")
    if action == "add":
        await update.message.reply_text(f"✅ @{username} добавлен как администратор. Он должен написать /start в ЛС боту, чтобы активировать права.")
        save_admin_to_db(-1)
    elif action == "remove":
        await update.message.reply_text("Укажите команду /remove_admin <user_id>")
    else:
        await update.message.reply_text("Неизвестная подкоманда.")

async def remove_admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_founder_by_username(update.effective_user.username):
        await update.message.reply_text("⛔ Только основатель.")
        return
    if not context.args:
        await update.message.reply_text("Укажите user_id: /remove_admin 123456")
        return
    try:
        user_id = int(context.args[0])
        if user_id == founder_id:
            await update.message.reply_text("Нельзя удалить основателя.")
            return
        remove_admin_from_db(user_id)
        if user_id in group_admins:
            group_admins.discard(user_id)
        await update.message.reply_text("✅ Администратор удалён.")
    except:
        await update.message.reply_text("Неверный ID.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ("group", "supergroup"):
        return
    chat_id = update.effective_chat.id
    user = update.effective_user
    text = update.message.text.strip() if update.message.text else ""

    if context.user_data.get('waiting_interval') and is_admin(user.id):
        try:
            interval = int(text)
            if 10 <= interval <= 1440:
                set_group_setting(chat_id, "interval", interval)
                await update.message.reply_text(f"✅ Интервал случайных сообщений установлен на {interval} мин.")
            else:
                await update.message.reply_text("Интервал должен быть от 10 до 1440 минут.")
        except ValueError:
            await update.message.reply_text("Введите число.")
        context.user_data['waiting_interval'] = False
        return

    settings = get_group_settings(chat_id)
    if not settings['enabled']:
        return

    if chat_id not in context_data:
        context_data[chat_id] = []
    user_name = f"@{user.username}" if user.username else user.first_name
    context_data[chat_id].append({"role":"user","content":f"{user_name}: {text}"})
    if len(context_data[chat_id]) > 20:
        context_data[chat_id] = context_data[chat_id][-20:]

    answer = await ask_ai(text, context_data[chat_id])
    context_data[chat_id].append({"role":"assistant","content":answer})

    if answer.startswith("/tts "):
        tts_text = answer[5:].strip()
        voice = await generate_tts(tts_text)
        if voice:
            await update.message.reply_voice(voice)
        else:
            await update.message.reply_text("Не удалось создать голосовое сообщение.")
    elif answer.startswith("/video "):
        query = answer[7:].strip()
        video_url = await search_video(query)
        if video_url:
            await update.message.reply_text(video_url)
        else:
            await update.message.reply_text("Не удалось найти видео.")
    else:
        await update.message.reply_text(answer)

async def random_sender(app: Application):
    while True:
        await asyncio.sleep(60)
        try:
            conn = get_db(); c = conn.cursor()
            c.execute("SELECT chat_id, interval_minutes, random_tts, random_video FROM group_settings WHERE enabled=1")
            rows = c.fetchall()
            conn.close()
            now = datetime.now()
            for chat_id, interval, tts_enabled, video_enabled in rows:
                last_time = last_random_time.get(chat_id)
                if last_time and (now - last_time).total_seconds() < interval * 60:
                    continue
                if not tts_enabled and not video_enabled:
                    continue
                if tts_enabled and video_enabled:
                    choice = random.choice(['tts','video'])
                elif tts_enabled:
                    choice = 'tts'
                else:
                    choice = 'video'
                try:
                    if choice == 'tts':
                        phrase = random.choice(RANDOM_TTS_PHRASES)
                        voice = await generate_tts(phrase)
                        if voice:
                            await app.bot.send_voice(chat_id, voice)
                    else:
                        query = random.choice(["смешные кошки", "интересные факты", "приколы", "забавные животные"])
                        video_url = await search_video(query)
                        if video_url:
                            await app.bot.send_message(chat_id, f"Случайное видео: {video_url}")
                except Exception as e:
                    logging.warning(f"Random send failed for {chat_id}: {e}")
                last_random_time[chat_id] = now
        except Exception as e:
            logging.error(f"Random sender error: {e}")

is_running = False
application = None
polling_task = None

async def start_group_ai():
    global is_running, application, polling_task, group_admins, founder_id
    if is_running:
        return
    if not BOT_TOKEN:
        logging.warning("GROUP_AI_BOT_TOKEN не задан")
        return
    init_db()
    group_admins = load_admins()
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT user_id FROM admins WHERE user_id != -1 AND user_id != 0")
    for row in c.fetchall():
        if row[0]:
            founder_id = row[0]
            break
    conn.close()

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("enable", enable_cmd))
    app.add_handler(CommandHandler("disable", disable_cmd))
    app.add_handler(CommandHandler("settings", settings_cmd))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CommandHandler("remove_admin", remove_admin_cmd))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CallbackQueryHandler(settings_callback, pattern="^(toggle_tts|toggle_video|change_interval|close_settings)$"))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & (filters.ChatType.GROUPS | filters.ChatType.SUPERGROUP),
        handle_message
    ))
    asyncio.create_task(random_sender(app))
    await app.initialize()
    await app.start()
    polling_task = asyncio.create_task(app.updater.start_polling())
    application = app
    is_running = True

async def stop_group_ai():
    global is_running, application, polling_task
    if not is_running:
        return
    if polling_task:
        polling_task.cancel()
        polling_task = None
    if application:
        await application.stop()
        await application.shutdown()
        application = None
    is_running = False
