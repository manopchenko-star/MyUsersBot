import asyncio, sqlite3, os, logging
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    ContextTypes,
)

BOT_TOKEN = os.environ.get("TDXT_BOT_TOKEN", "")
MAIN_ADMIN_USERNAME = "Anopchenko2011"
ACCEPT_THRESHOLD = 1
REJECT_THRESHOLD = 1
DATABASE = "tdxt_bot.db"
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

# ---------- работа с БД ----------
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
    conn.commit()
    conn.close()

# ... (все остальные функции: get_all_admin_ids, add_admin_to_db, remove_admin_from_db, is_admin, is_main_admin,
#      save_application, get_application, get_user_applications, has_pending_application,
#      get_applications_by_status, add_vote, get_votes, count_votes, set_application_status,
#      set_reject_reason, is_banned, ban_user, unban_user, get_banned_users,
#      add_user, get_all_user_ids, get_all_users, get_user_count, get_ban_count, get_admin_count,
#      get_app_counts, is_applications_open, set_applications_open, schedule_reopen, clear_scheduled_open,
#      main_keyboard, clear_all_pending, и все обработчики команд и колбэков)
#      – полностью копируются из исходного скрипта, который вы прислали.
#      Здесь они опущены для краткости, но в реальном файле они ДОЛЖНЫ присутствовать.
#      После функций идёт сборка приложения.

# Глобальное состояние
is_running = False
application = None
polling_task = None

async def start_tdxt():
    global is_running, application, polling_task
    if is_running: return
    if not BOT_TOKEN:
        logging.warning("TDXT_BOT_TOKEN не задан")
        return
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    # Регистрируем все обработчики
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