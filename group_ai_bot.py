import asyncio, sqlite3, os, logging, json, aiohttp, random, io, re
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from gtts import gTTS
from duckduckgo_search import DDGS

BOT_TOKEN = os.environ.get("GROUP_AI_BOT_TOKEN", "")
GITHUB_TOKEN32 = os.environ.get("GITHUB_TOKEN32", "")
FOUNDER_USERNAME = "Anopchenko2011"
AI_MODEL = "gpt-4o-mini"
AI_MAX_TOKENS = 200
AI_TEMPERATURE = 0.95
AI_SYSTEM_PROMPT = (
    "Ты — развязный и смешной собеседник для группового чата. "
    "Отвечай коротко, с юмором, используй смайлики. "
    "Если просят мем — придумай короткий смешной текст (можно абсурдный). "
    "Если просят шутку — расскажи анекдот или шутку. "
    "Не используй команды в ответах, просто отвечай текстом."
)
DATABASE = "group_ai_bot.db"

context_data = {}
last_random_time = {}
group_admins = set()
founder_id = None

SOUND_MEMES = {
    "планктон": "https://www.myinstants.com/media/sounds/plankton-aaa.mp3",
    "это мой сын": "https://www.myinstants.com/media/sounds/eto-moi-syn.mp3",
    "астанавись": "https://www.myinstants.com/media/sounds/astanavis.mp3",
    "смех дьявола": "https://www.myinstants.com/media/sounds/devil-laugh.mp3",
    "ня": "https://www.myinstants.com/media/sounds/nya.mp3",
    "вжух": "https://www.myinstants.com/media/sounds/vzhuh.mp3",
    "грустный кот": "https://www.myinstants.com/media/sounds/sad-cat.mp3",
    "угар": "https://www.myinstants.com/media/sounds/ugarniy-smeh.mp3",
    "бензопила": "https://www.myinstants.com/media/sounds/chainsaw.mp3",
    "крики чайки": "https://www.myinstants.com/media/sounds/seagull.mp3",
    "идеально": "https://www.myinstants.com/media/sounds/idealno.mp3",
    "хы": "https://www.myinstants.com/media/sounds/heh.mp3",
    "ой всё": "https://www.myinstants.com/media/sounds/oi-vse.mp3",
    "сюрприз": "https://www.myinstants.com/media/sounds/surprise-mf.mp3",
}

def get_db(): return sqlite3.connect(DATABASE, check_same_thread=False)

def init_db():
    conn = get_db(); c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY, username TEXT)''')
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
    c.execute("SELECT user_id FROM admins WHERE user_id != -1")
    return {row[0] for row in c.fetchall()}

def save_admin_to_db(user_id, username=None):
    conn = get_db(); c = conn.cursor()
    if username:
        c.execute("INSERT OR IGNORE INTO admins (user_id, username) VALUES (?,?)", (user_id, username))
    else:
        c.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (user_id,))
    conn.commit(); conn.close()

def update_admin_id(username, new_id):
    """Заменяет временную запись (user_id=-1) на реальный ID пользователя."""
    conn = get_db(); c = conn.cursor()
    c.execute("DELETE FROM admins WHERE username=? AND user_id=-1", (username,))
    c.execute("INSERT OR IGNORE INTO admins (user_id, username) VALUES (?,?)", (new_id, username))
    conn.commit(); conn.close()
    # Перезагружаем множество админов в памяти
    global group_admins
    group_admins = load_admins()

def remove_admin_from_db(user_id):
    conn = get_db(); c = conn.cursor()
    c.execute("DELETE FROM admins WHERE user_id=?", (user_id,))
    conn.commit(); conn.close()
    global group_admins
    group_admins.discard(user_id)

def get_group_settings(chat_id):
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT enabled, random_tts, random_video, interval_minutes FROM group_settings WHERE chat_id=?", (chat_id,))
    row = c.fetchone()
    if row: return {"enabled":bool(row[0]), "random_tts":bool(row[1]), "random_video":bool(row[2]), "interval":row[3]}
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

def is_founder(username):
    return username and username.lower() == FOUNDER_USERNAME.lower()

async def ask_ai(prompt, context=[]):
    if not GITHUB_TOKEN32: return "❌ GITHUB_TOKEN32 не задан."
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN32}", "Content-Type": "application/json"}
    messages = [{"role":"system","content":AI_SYSTEM_PROMPT}]
    for entry in context[-6:]:
        messages.append(entry)
    messages.append({"role":"user","content":prompt})
    payload = {"model":AI_MODEL, "messages":messages, "max_tokens":AI_MAX_TOKENS, "temperature":AI_TEMPERATURE}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post("https://models.inference.ai.azure.com/chat/completions", json=payload, headers=headers, timeout=30) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data["choices"][0]["message"]["content"]
                else: return "⚠️ Ошибка AI"
    except Exception as e: return f"⚠️ Сетевая ошибка: {e}"

async def generate_tts(text):
    try:
        tts = gTTS(text, lang='ru')
        buf = io.BytesIO()
        tts.write_to_fp(buf)
        buf.seek(0)
        return buf
    except: return None

async def search_video(query):
    try:
        with DDGS() as ddgs:
            results = list(ddgs.videos(query, max_results=1))
            if results: return results[0]['content']
    except: return None

# ---------- Обработчики ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global founder_id
    user = update.effective_user
    username = user.username

    # Если пользователь в личке и он основатель – сохраняем его ID
    if update.effective_chat.type == "private" and is_founder(username):
        founder_id = user.id
        save_admin_to_db(founder_id, username)
        await update.message.reply_text("✅ Вы признаны основателем! Используйте команды в группах.")
        return

    # Проверяем, есть ли username среди ожидающих подтверждения (добавлен через /admin add)
    if username:
        conn = get_db(); c = conn.cursor()
        c.execute("SELECT 1 FROM admins WHERE username=? AND user_id=-1", (username,))
        if c.fetchone():
            update_admin_id(username, user.id)
            conn.close()
            if update.effective_chat.type == "private":
                await update.message.reply_text("✅ Ваши права администратора активированы! Теперь вы можете управлять ботом в группах.")
            else:
                await update.message.reply_text("✅ Права администратора активированы.")
        else:
            conn.close()

    if update.effective_chat.type in ("group", "supergroup"):
        await update.message.reply_text(
            "👋 Я AI-помощник. Чтобы обратиться ко мне, упомяните @username бота или ответьте на моё сообщение.\n\n"
            "Команды:\n"
            "/meme – случайный мем\n"
            "/joke – шутка\n"
            "/sound <название> – звуковой мем (например /sound планктон)\n"
            "/video_meme – случайный видео‑мем\n"
            "/tts <текст> – озвучить фразу\n"
            "/sounds – список всех звуков\n\n"
            "Управление (админы): /enable, /disable, /settings"
        )
    else:
        await update.message.reply_text("Я работаю только в группах!")

async def meme_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = "Придумай короткий смешной мем (1-2 предложения)."
    answer = await ask_ai(prompt)
    await update.message.reply_text(answer)

async def joke_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = "Расскажи короткий анекдот или шутку."
    answer = await ask_ai(prompt)
    await update.message.reply_text(answer)

async def sound_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Укажите название звука. Список: /sounds")
        return
    name = " ".join(context.args).lower()
    url = SOUND_MEMES.get(name)
    if url:
        await update.message.reply_audio(audio=url, title=name)
    else:
        await update.message.reply_text("Такой звук не найден. Доступные: " + ", ".join(SOUND_MEMES.keys()))

async def list_sounds_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Доступные звуки:\n" + "\n".join(f"• {k}" for k in SOUND_MEMES.keys()))

async def video_meme_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = random.choice(["смешные животные", "приколы", "угарные моменты", "ржака до слез"])
    url = await search_video(query)
    if url:
        await update.message.reply_text(f"Видео-мем: {url}")
    else:
        await update.message.reply_text("Не удалось найти видео.")

async def tts_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args) if context.args else None
    if not text:
        await update.message.reply_text("Введите текст для озвучки: /tts Привет!")
        return
    voice = await generate_tts(text)
    if voice:
        await update.message.reply_voice(voice)
    else:
        await update.message.reply_text("Не удалось создать голосовое сообщение.")

async def enable_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Только администратор."); return
    chat_id = update.effective_chat.id
    set_group_setting(chat_id, "enabled", True)
    context_data.pop(chat_id, None)
    await update.message.reply_text("✅ Бот включён в этом чате.")

async def disable_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Только администратор."); return
    chat_id = update.effective_chat.id
    set_group_setting(chat_id, "enabled", False)
    context_data.pop(chat_id, None)
    await update.message.reply_text("❌ Бот выключен.")

async def settings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Только администратор."); return
    chat_id = update.effective_chat.id
    settings = get_group_settings(chat_id)
    tts_status = "🟢 Вкл" if settings['random_tts'] else "🔴 Выкл"
    video_status = "🟢 Вкл" if settings['random_video'] else "🔴 Выкл"
    keyboard = [
        [InlineKeyboardButton(f"Случайные звуки: {tts_status}", callback_data="toggle_tts")],
        [InlineKeyboardButton(f"Случайные видео: {video_status}", callback_data="toggle_video")],
        [InlineKeyboardButton(f"Интервал: {settings['interval']} мин", callback_data="change_interval")],
        [InlineKeyboardButton("Закрыть", callback_data="close_settings")]
    ]
    await update.message.reply_text("⚙️ Настройки группы:", reply_markup=InlineKeyboardMarkup(keyboard))

async def settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    if not is_admin(query.from_user.id):
        await query.answer("⛔ Только админ.", show_alert=True); return
    chat_id = query.message.chat_id
    data = query.data
    if data == "close_settings":
        await query.edit_message_text("Настройки закрыты."); return
    settings = get_group_settings(chat_id)
    if data == "toggle_tts":
        set_group_setting(chat_id, "random_tts", not settings['random_tts'])
    elif data == "toggle_video":
        set_group_setting(chat_id, "random_video", not settings['random_video'])
    elif data == "change_interval":
        context.user_data['waiting_interval'] = True
        await query.edit_message_text("Введите новый интервал в минутах (от 10 до 1440):"); return
    settings = get_group_settings(chat_id)
    tts_status = "🟢 Вкл" if settings['random_tts'] else "🔴 Выкл"
    video_status = "🟢 Вкл" if settings['random_video'] else "🔴 Выкл"
    keyboard = [
        [InlineKeyboardButton(f"Случайные звуки: {tts_status}", callback_data="toggle_tts")],
        [InlineKeyboardButton(f"Случайные видео: {video_status}", callback_data="toggle_video")],
        [InlineKeyboardButton(f"Интервал: {settings['interval']} мин", callback_data="change_interval")],
        [InlineKeyboardButton("Закрыть", callback_data="close_settings")]
    ]
    await query.edit_message_text("⚙️ Настройки группы:", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_founder(update.effective_user.username):
        await update.message.reply_text("⛔ Только основатель (@Anopchenko2011)."); return
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("Использование: /admin add @user или /admin remove @user"); return
    action = context.args[0].lower()
    username = context.args[1].lstrip("@").lower()
    if action == "add":
        # Сохраняем запись с временным ID -1 и username
        save_admin_to_db(-1, username)
        await update.message.reply_text(f"✅ @{username} добавлен в список ожидания. Попросите его написать /start в личные сообщения боту.")
    elif action == "remove":
        # Удаляем по username (если есть запись с реальным ID, удаляем её)
        conn = get_db(); c = conn.cursor()
        c.execute("SELECT user_id FROM admins WHERE username=? AND user_id != -1", (username,))
        row = c.fetchone()
        if row:
            remove_admin_from_db(row[0])
            await update.message.reply_text(f"❌ @{username} удалён из администраторов.")
        else:
            # Удаляем и временную запись, если была
            c.execute("DELETE FROM admins WHERE username=? AND user_id=-1", (username,))
            conn.commit()
            await update.message.reply_text(f"❌ @{username} удалён из списка ожидания.")
        conn.close()
    else:
        await update.message.reply_text("Неизвестная подкоманда.")

async def remove_admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_founder(update.effective_user.username):
        await update.message.reply_text("⛔ Только основатель."); return
    if not context.args:
        await update.message.reply_text("Укажите user_id: /remove_admin 123456"); return
    try:
        user_id = int(context.args[0])
        if user_id == founder_id:
            await update.message.reply_text("Нельзя удалить основателя."); return
        remove_admin_from_db(user_id)
        await update.message.reply_text("✅ Администратор удалён.")
    except:
        await update.message.reply_text("Неверный ID.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ("group", "supergroup"):
        return
    chat_id = update.effective_chat.id
    user = update.effective_user
    bot_username = context.bot.username

    settings = get_group_settings(chat_id)
    if not settings['enabled']:
        return

    # Обработка ввода интервала
    if context.user_data.get('waiting_interval') and is_admin(user.id):
        text = update.message.text.strip()
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

    mentioned = False
    if update.message.text and f"@{bot_username}" in update.message.text:
        mentioned = True
    if update.message.reply_to_message and update.message.reply_to_message.from_user.id == context.bot.id:
        mentioned = True

    if not mentioned:
        return

    clean_text = update.message.text.replace(f"@{bot_username}", "").strip() if update.message.text else ""
    if not clean_text:
        clean_text = "Привет! Расскажи что-нибудь смешное."

    if chat_id not in context_data:
        context_data[chat_id] = []
    user_name = f"@{user.username}" if user.username else user.first_name
    context_data[chat_id].append({"role":"user","content":f"{user_name}: {clean_text}"})
    if len(context_data[chat_id]) > 6:
        context_data[chat_id] = context_data[chat_id][-6:]

    answer = await ask_ai(clean_text, context_data[chat_id])
    context_data[chat_id].append({"role":"assistant","content":answer})
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
                    choice = random.choice(['sound','video'])
                elif tts_enabled:
                    choice = 'sound'
                else:
                    choice = 'video'

                try:
                    if choice == 'sound':
                        name, url = random.choice(list(SOUND_MEMES.items()))
                        await app.bot.send_audio(chat_id, audio=url, title=name)
                    else:
                        query = random.choice(["смешные коты", "ржачные приколы", "угар", "животные смешные моменты", "мемы"])
                        video_url = await search_video(query)
                        if video_url:
                            await app.bot.send_message(chat_id, f"🎥 Случайный видео‑мем: {video_url}")
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
    if is_running: return
    if not BOT_TOKEN:
        logging.warning("GROUP_AI_BOT_TOKEN не задан"); return
    init_db()
    group_admins = load_admins()
    # Попытка найти основателя по username
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT user_id FROM admins WHERE username=?", (FOUNDER_USERNAME,))
    row = c.fetchone()
    if row and row[0] != -1:
        founder_id = row[0]
    conn.close()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("meme", meme_cmd))
    app.add_handler(CommandHandler("joke", joke_cmd))
    app.add_handler(CommandHandler("sound", sound_cmd))
    app.add_handler(CommandHandler("sounds", list_sounds_cmd))
    app.add_handler(CommandHandler("video_meme", video_meme_cmd))
    app.add_handler(CommandHandler("tts", tts_cmd))
    app.add_handler(CommandHandler("enable", enable_cmd))
    app.add_handler(CommandHandler("disable", disable_cmd))
    app.add_handler(CommandHandler("settings", settings_cmd))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CommandHandler("remove_admin", remove_admin_cmd))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(MessageHandler(filters.TEXT & (filters.ChatType.GROUPS | filters.ChatType.SUPERGROUP), handle_message))
    app.add_handler(CallbackQueryHandler(settings_callback, pattern="^(toggle_tts|toggle_video|change_interval|close_settings)$"))

    asyncio.create_task(random_sender(app))

    await app.initialize()
    await app.start()
    polling_task = asyncio.create_task(app.updater.start_polling())
    application = app
    is_running = True

async def stop_group_ai():
    global is_running, application, polling_task
    if not is_running: return
    if polling_task:
        polling_task.cancel(); polling_task = None
    if application:
        await application.stop(); await application.shutdown(); application = None
    is_running = False
