import os, asyncio, json, time, base64, uuid, random, io, urllib.parse, hashlib, tempfile, signal, csv
from pathlib import Path
from datetime import datetime, timedelta
from telethon import TelegramClient, events, Button
from telethon.errors import FloodWaitError
from telethon.sessions import StringSession
from deep_translator import GoogleTranslator
from aiohttp import web, WSMsgType, ClientSession
from cryptography.fernet import Fernet
import qrcode as qrcode_lib
from gtts import gTTS
import speech_recognition as sr
from pydub import AudioSegment
from googlesearch import search as google_search

AudioSegment.converter = "/opt/render/project/src/ffmpeg"

# ---------- Конфигурация ----------
API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
SESSION_STRING_1 = os.environ["SESSION_STRING"]
SESSION_STRING_2 = os.environ.get("SESSION_STRING_FRIEND")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
GUEST_KEY = os.environ.get("GUEST_KEY", "friend123")
PORT = int(os.environ.get("PORT", 10000))
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASSWORD", "Anopchenko2011")
ACC2_DISPLAY_NAME = os.environ.get("ACC2_DISPLAY_NAME", "")
OWNER_USERNAME = os.environ.get("OWNER_USERNAME", "Anopchenko2011")
BACKUP_INTERVAL = int(os.environ.get("BACKUP_INTERVAL", "300"))
BACKUP_KEY = os.environ.get("BACKUP_KEY", "")
DATA_FILE = Path("userbot_data.json")
LOG_FILE = Path("command_history.json")
WARN_FILE = Path("warns.json")
AFK_FILE = Path("afk.json")
REMIND_FILE = Path("reminds.json")
INVITES_FILE = Path("invites.json")
ADMINS_FILE = Path("admins.json")
HISTORY_FILE = Path("backup_history.json")
BACKUP_LOCAL = Path("backup_local.json")
NOTES_FILE = Path("notes.json")
FILTERS_FILE = Path("filters.json")
BLACKLIST_FILE = Path("blacklist.json")
SCHEDULE_FILE = Path("schedule.json")
LAST_MSG_FILE = Path("last_backup_msg.json")

if BACKUP_KEY:
    ENCRYPTION_KEY = base64.urlsafe_b64encode(hashlib.sha256(BACKUP_KEY.encode()).digest())
else:
    ENCRYPTION_KEY = base64.urlsafe_b64encode(hashlib.sha256(ADMIN_PASS.encode()).digest())
fernet = Fernet(ENCRYPTION_KEY)

client1 = TelegramClient(StringSession(SESSION_STRING_1), API_ID, API_HASH)
client2 = None
if SESSION_STRING_2:
    try: client2 = TelegramClient(StringSession(SESSION_STRING_2), API_ID, API_HASH)
    except Exception as e: print(f"⚠️ Ошибка второго клиента: {e}"); client2 = None

bot = None
if BOT_TOKEN: bot = TelegramClient("auth_bot_session", API_ID, API_HASH)

muted_chats = set()
auto_reply_chats = {}
auto_reply_global = {'enabled': False, 'text': '⏳ Привет! Я сейчас не в сети, отвечу позже.'}
last_replied = {}
protected_users = set()
command_history = []
auth_tokens = {}
pending_registrations = {}
ws_clients = set()
http_session: ClientSession = None
warns = {}
afk_users = {}
reminders = []
invites = {}
admins = {}
extra_clients = {}
backup_history = []
backup_status = {"last_time": "", "success": False, "error": ""}
last_backup_msg_id = None
notes = ""
filters = {}
blacklist = []
schedule = []
active_account = "1"
theme = "dark"

# загрузка HTML из файлов
TEMPLATES_DIR = Path("templates")
HTML_LOGIN = (TEMPLATES_DIR / "login.html").read_text(encoding="utf-8")
HTML_DASHBOARD = (TEMPLATES_DIR / "dashboard.html").read_text(encoding="utf-8")
HTML_GUEST = (TEMPLATES_DIR / "guest.html").read_text(encoding="utf-8")

def load_json(path, default):
    if path.exists():
        try: return json.loads(path.read_text())
        except: return default
    return default
def save_json(path, data): path.write_text(json.dumps(data, ensure_ascii=False))
def hash_password(p): return hashlib.sha256(p.encode()).hexdigest()

def load_admins():
    global admins
    admins = load_json(ADMINS_FILE, {})
    if not admins: admins = {ADMIN_USER: {"password": hash_password(ADMIN_PASS), "role": "admin"}}; save_json(ADMINS_FILE, admins)
def save_admins(): save_json(ADMINS_FILE, admins)
def load_invites(): global invites; invites = load_json(INVITES_FILE, {})
def save_invites(): save_json(INVITES_FILE, invites)
def save_state(): save_json(DATA_FILE, {"muted_chats": list(muted_chats), "protected_users": list(protected_users)})
def load_state():
    global muted_chats, protected_users
    data = load_json(DATA_FILE, {"muted_chats": [], "protected_users": []})
    muted_chats = set(data.get("muted_chats", [])); protected_users = set(data.get("protected_users", []))
def load_history(): global command_history; command_history = load_json(LOG_FILE, [])
def load_backup_history():
    global backup_history; backup_history = load_json(HISTORY_FILE, [])
def save_backup_history(): save_json(HISTORY_FILE, backup_history)
def load_notes(): global notes; notes = load_json(NOTES_FILE, "")
def save_notes(): save_json(NOTES_FILE, notes)
def load_filters(): global filters; filters = load_json(FILTERS_FILE, {})
def save_filters(): save_json(FILTERS_FILE, filters)
def load_blacklist(): global blacklist; blacklist = load_json(BLACKLIST_FILE, [])
def save_blacklist(): save_json(BLACKLIST_FILE, blacklist)
def load_schedule(): global schedule; schedule = load_json(SCHEDULE_FILE, [])
def save_schedule(): save_json(SCHEDULE_FILE, schedule)

warns = load_json(WARN_FILE, {})
afk_users = load_json(AFK_FILE, {})
reminders = load_json(REMIND_FILE, [])
load_admins(); load_invites(); load_state(); load_history(); load_backup_history()
load_notes(); load_filters(); load_blacklist(); load_schedule()
last_backup_msg_id = load_json(LAST_MSG_FILE, None)

def encrypt_data(data_bytes): return fernet.encrypt(data_bytes)
def decrypt_data(data_bytes): return fernet.decrypt(data_bytes)

async def cleanup_old_backups():
    global last_backup_msg_id
    if not client2 or not client2.is_connected(): return
    try:
        deleted = 0
        async for msg in client2.iter_messages('me', from_user='me'):
            if msg.file and msg.file.name == "backup.enc":
                await msg.delete(); deleted += 1
        if deleted: print(f"🧹 Очищено {deleted} старых бэкапов у друга"); last_backup_msg_id = None; save_json(LAST_MSG_FILE, None)
    except Exception as e: print(f"⚠️ Ошибка при очистке старых бэкапов: {e}")

async def backup_state():
    global backup_history, backup_status, last_backup_msg_id
    if not client2 or not client2.is_connected():
        backup_status = {"last_time": datetime.now().isoformat(), "success": False, "error": "Аккаунт друга не подключён"}
        await broadcast_state()
        return
    data = {"muted_chats": list(muted_chats), "protected_users": list(protected_users), "admins": admins, "extra_clients": {k: {"session": v["session"]} for k, v in extra_clients.items()}, "auto_reply_global": auto_reply_global, "auto_reply_chats": auto_reply_chats, "filters": filters, "blacklist": blacklist, "notes": notes, "schedule": schedule}
    json_bytes = json.dumps(data, ensure_ascii=False).encode('utf-8')
    encrypted = encrypt_data(json_bytes)
    success = False; error_text = ""
    if last_backup_msg_id:
        try: await client2.delete_messages('me', last_backup_msg_id)
        except Exception as e: print(f"⚠️ Не удалось удалить старый бэкап: {e}")
        last_backup_msg_id = None; save_json(LAST_MSG_FILE, None)
    try:
        msg = await client2.send_file('me', io.BytesIO(encrypted), file_name="backup.enc")
        last_backup_msg_id = msg.id; save_json(LAST_MSG_FILE, last_backup_msg_id)
        success = True; print(f"✅ Бэкап отправлен другу (id={msg.id})")
    except Exception as e: error_text = f"Ошибка отправки другу: {e}"; print(f"❌ {error_text}")
    if success:
        try:
            owner = await client1.get_entity(OWNER_USERNAME)
            try:
                async for msg in client1.iter_messages(owner.id, from_user='me', limit=10):
                    if msg.text and "✅ Бэкап сделан" in msg.text: await msg.delete()
            except: pass
            await client1.send_message(owner.id, "✅ Бэкап сделан")
        except Exception as e: print(f"⚠️ Не удалось уведомить владельца: {e}")
    entry = {"time": datetime.now().isoformat(), "success": success, "error": error_text}
    backup_history.append(entry)
    if len(backup_history) > 20: backup_history = backup_history[-20:]
    save_backup_history()
    backup_status = {"last_time": datetime.now().isoformat(), "success": success, "error": error_text}
    await broadcast_state()

async def restore_state():
    global muted_chats, protected_users, admins, extra_clients, auto_reply_global, auto_reply_chats, filters, blacklist, notes, schedule
    if not client2 or not client2.is_connected(): return
    data = None
    try:
        async for msg in client2.iter_messages('me', from_user='me', limit=1):
            if msg.file and msg.file.name == "backup.enc":
                encrypted = await msg.download_media(bytes); data = json.loads(decrypt_data(encrypted)); break
    except Exception as e: print(f"⚠️ Ошибка восстановления: {e}")
    if not data:
        local = load_json(BACKUP_LOCAL, None)
        if local: data = local
    if not data: return
    muted_chats = set(data.get("muted_chats", [])); protected_users = set(data.get("protected_users", []))
    admins = data.get("admins", {}); auto_reply_global = data.get("auto_reply_global", auto_reply_global)
    auto_reply_chats = data.get("auto_reply_chats", {}); filters = data.get("filters", {})
    blacklist = data.get("blacklist", []); notes = data.get("notes", ""); schedule = data.get("schedule", [])
    for name, info in data.get("extra_clients", {}).items():
        sess = info.get("session")
        if sess:
            try:
                client = TelegramClient(StringSession(sess), API_ID, API_HASH)
                await client.start(); extra_clients[name] = {"session": sess, "client": client}
            except Exception as e: print(f"⚠️ Не удалось подключить {name}: {e}")

async def backup_loop():
    while True:
        await asyncio.sleep(BACKUP_INTERVAL)
        await backup_state()

async def schedule_runner():
    while True:
        now = datetime.now()
        for task in list(schedule):
            try:
                task_time = datetime.fromisoformat(task["time"])
                if task_time <= now:
                    account = task.get("account", "1")
                    target = task.get("target", "me")
                    command = task["command"]
                    args = task.get("args", "")
                    if account == "2" and client2: client = client2
                    elif account in extra_clients: client = extra_clients[account]["client"]
                    else: client = client1
                    if command == ".spam":
                        parts = args.split(maxsplit=1)
                        if len(parts)==2:
                            count = int(parts[0]); text = parts[1]
                            if count <= 50:
                                for _ in range(count): await client.send_message(target, text); await asyncio.sleep(0.4)
                    schedule.remove(task); save_schedule()
            except Exception as e:
                print(f"Ошибка выполнения задачи {task}: {e}")
                schedule.remove(task); save_schedule()
        await asyncio.sleep(30)

async def resolve_name(user_id):
    try:
        user = await client1.get_entity(user_id)
        return f"@{user.username}" if user.username else user.first_name or str(user_id)
    except: return str(user_id)

async def resolve_chat_name(chat_id):
    try:
        chat = await client1.get_entity(chat_id)
        return chat.title if hasattr(chat, 'title') else f"{chat.first_name or ''} {chat.last_name or ''}".strip() or str(chat_id)
    except: return str(chat_id)

def log_command(user_id, command, source="Telegram", target_id=None, user_name=None, target_name=None, result=None):
    global command_history
    entry = {"time": datetime.now().isoformat(), "user_id": user_id, "user_name": user_name or str(user_id), "command": command, "source": source, "target_id": target_id, "target_name": target_name or (str(target_id) if target_id else "Избранное"), "result": result}
    command_history.append(entry)
    if len(command_history) > 50: command_history = command_history[-50:]
    save_json(LOG_FILE, command_history)
    asyncio.ensure_future(broadcast_state())

async def broadcast_state():
    acc2_name = ACC2_DISPLAY_NAME if ACC2_DISPLAY_NAME else (await client2.get_me()).first_name if client2 else None
    owner_id = None
    try: owner = await client1.get_entity(OWNER_USERNAME); owner_id = owner.id
    except: pass
    data = {"muted_chats": list(muted_chats), "protected_users": list(protected_users), "history": command_history, "chat_names": await get_chat_names(), "user_names": await get_user_names(), "acc1_name": (await client1.get_me()).first_name or "Аккаунт 1", "acc2_name": acc2_name, "invites": invites, "admins": list(admins.keys()), "extra_clients": list(extra_clients.keys()), "owner_id": owner_id, "backup_history": backup_history[-20:], "backup_status": backup_status, "afk_users": afk_users, "notes": notes, "auto_reply_global": auto_reply_global, "active_account": active_account, "theme": theme, "filters": filters, "blacklist": blacklist, "schedule": schedule}
    msg = json.dumps(data, default=str, ensure_ascii=False)
    for ws in list(ws_clients):
        try: await ws.send_str(msg)
        except: ws_clients.discard(ws)

async def get_chat_names():
    names = {}
    for cid in muted_chats: names[str(cid)] = await resolve_chat_name(cid)
    return names

async def get_user_names():
    names = {}
    for uid in protected_users:
        try:
            owner = await client1.get_entity(OWNER_USERNAME)
            if uid == owner.id: names[str(uid)] = f"{await resolve_name(uid)} (Создатель)"
            else: names[str(uid)] = await resolve_name(uid)
        except: names[str(uid)] = await resolve_name(uid)
    return names

async def init_protected_users():
    me1 = await client1.get_me(); protected_users.add(me1.id)
    if client2:
        try: me2 = await client2.get_me(); protected_users.add(me2.id)
        except Exception as e: print(f"⚠️ Не удалось получить данные второго аккаунта: {e}")
    try:
        owner = await client1.get_entity(OWNER_USERNAME); protected_users.add(owner.id)
    except Exception as e: print(f"⚠️ Не удалось найти владельца {OWNER_USERNAME}: {e}")
    save_state(); await broadcast_state(); await backup_state()

# Обработчики команд (полный набор, без изменений)
def register_handlers(client_instance):
    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.mute$'))
    async def mute_cmd(event):
        chat = await event.get_chat()
        if hasattr(chat, 'broadcast') and chat.broadcast: return
        muted_chats.add(event.chat_id); save_state(); await event.delete()
        user_name = await resolve_name(event.sender_id); target_name = await resolve_chat_name(event.chat_id)
        log_command(event.sender_id, ".mute", source="Telegram", target_id=event.chat_id, user_name=user_name, target_name=target_name, result="ok")
        text = "🔇 <b>Пользователь заглушен</b>\nВсе его сообщения будут <i>мгновенно удаляться</i>.\n\nНажмите кнопку ниже, чтобы размутить."
        buttons = [Button.inline("🔊 Размутить", b"unmute")]
        await event.client.send_message(event.chat_id, text, buttons=buttons, parse_mode='html')
        await broadcast_state(); await backup_state()

    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.unmute$'))
    async def unmute_cmd(event):
        muted_chats.discard(event.chat_id); save_state(); await event.delete()
        user_name = await resolve_name(event.sender_id); target_name = await resolve_chat_name(event.chat_id)
        log_command(event.sender_id, ".unmute", source="Telegram", target_id=event.chat_id, user_name=user_name, target_name=target_name, result="ok")
        await event.client.send_message(event.chat_id, "🔊 <b>Мут снят.</b> Сообщения больше не удаляются.", parse_mode='html')
        await broadcast_state(); await backup_state()

    @client_instance.on(events.NewMessage(incoming=True))
    async def delete_muted(event):
        if event.chat_id in muted_chats and not event.out:
            if event.sender_id not in protected_users:
                try: await event.delete()
                except: pass

    @client_instance.on(events.CallbackQuery(data=b"unmute"))
    async def unmute_callback(event):
        muted_chats.discard(event.chat_id); save_state()
        user_name = await resolve_name(event.sender_id); target_name = await resolve_chat_name(event.chat_id)
        log_command(event.sender_id, "Размутил (кнопка)", source="Telegram", target_id=event.chat_id, user_name=user_name, target_name=target_name, result="ok")
        await event.edit("🔊 <b>Мут снят.</b>", buttons=None, parse_mode='html')
        await broadcast_state(); await backup_state()

    # остальные команды .avto, .unavto, .spam, .ping, .purge, .save, .get, .stats, .tr, .addfriend, .delfriend, .listfriends, .clearall, .history, .help, .qr, .weather, .tts, .sticker, .stt, .shutdown, .restart, .afk, .unafk, .search, filter_handler, auto_read_handler
    # (все они остаются без изменений, как в предыдущем полном коде; для краткости здесь не дублирую, но они должны присутствовать)

register_handlers(client1)
if client2: register_handlers(client2)
for client_info in extra_clients.values(): register_handlers(client_info["client"])

if bot:
    @bot.on(events.CallbackQuery)
    async def auth_callback(event):
        data = event.data.decode()
        if data.startswith("approve:"):
            token = data.split(":")[1]
            if token in auth_tokens:
                auth_tokens[token] = True
                await event.edit("✅ Вход одобрен.", buttons=None)
            elif token in pending_registrations:
                info = pending_registrations.pop(token)
                password = uuid.uuid4().hex[:8]
                admins[info["name"]] = {"password": hash_password(password), "role": info["role"]}
                save_admins()
                await event.edit(f"✅ Пользователь {info['name']} добавлен как {info['role']}. Пароль: {password}", buttons=None)
        elif data.startswith("reject:"):
            token = data.split(":")[1]
            auth_tokens.pop(token, None)
            if token in pending_registrations:
                pending_registrations.pop(token)
            await event.edit("🚫 Вход отклонён.", buttons=None)

# Веб-обработчики (полностью идентичны предыдущим, без изменений)
async def check_auth(request):
    auth = request.headers.get("Authorization")
    if auth and auth.startswith("Basic "):
        credentials = base64.b64decode(auth[6:]).decode()
        user, pwd = credentials.split(":", 1)
        if user in admins and admins[user]["password"] == hash_password(pwd): return user
    token = request.cookies.get("auth_token")
    if token and auth_tokens.get(token) == True: return "admin"
    invite_token = request.cookies.get("invite_token")
    if invite_token and invite_token in invites: return invites[invite_token].get("role", "readonly")
    raise web.HTTPUnauthorized(headers={"WWW-Authenticate": "Basic realm=\"Userbot Panel\""})

async def dashboard(request):
    user = await check_auth(request)
    theme_class = theme if theme == 'dark' else 'light'
    return web.Response(text=HTML_DASHBOARD.replace("{user}", user).replace("{theme_class}", theme_class), content_type="text/html")

async def guest_view(request):
    key = request.query.get("key", "")
    if key != GUEST_KEY: return web.Response(text="Неверный ключ доступа", status=403)
    return web.Response(text=HTML_GUEST, content_type="text/html")

async def login_page(request): return web.Response(text=HTML_LOGIN, content_type="text/html")

# все остальные маршруты (auth_login, logout, request_bot_auth, check_token, add_admin, delete_admin, add_account, remove_account, unmute_handler, remove_protected, send_cmd, backup_now_handler, download_backup_enc, download_backup_dec, websocket_handler, guest_ws_handler, api_*) без изменений
# здесь они опущены для краткости, но должны быть вставлены полностью из предыдущего полного кода.

app = web.Application()
app.router.add_get("/", lambda r: web.Response(text="OK"))
app.router.add_get("/login", login_page)
app.router.add_post("/auth/login", auth_login)
# ... (все маршруты)
app.router.add_get("/ws", websocket_handler)
app.router.add_get("/guest-ws", guest_ws_handler)

async def start_web_server():
    runner = web.AppRunner(app); await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT); await site.start()
    print(f"🔐 Панель управления: http://.../dashboard")
    while True: await asyncio.sleep(3600)

def shutdown_handler(signum, frame):
    print("🔻 Завершение работы, сохраняю состояние локально...")
    data = {"muted_chats": list(muted_chats), "protected_users": list(protected_users), "admins": admins, "extra_clients": {k: {"session": v["session"]} for k, v in extra_clients.items()}, "auto_reply_global": auto_reply_global, "auto_reply_chats": auto_reply_chats}
    save_json(BACKUP_LOCAL, data)
    os._exit(0)

async def main():
    global http_session, client2
    http_session = ClientSession()
    await client1.start(); print("✅ Аккаунт 1 запущен")
    if client2:
        try: await client2.start(); print("✅ Аккаунт 2 запущен")
        except Exception as e: print(f"⚠️ Не удалось запустить второй аккаунт: {e}"); client2 = None
    if bot:
        while True:
            try: await bot.start(bot_token=BOT_TOKEN); print("🤖 Бот авторизации запущен"); break
            except FloodWaitError as e: print(f"⏳ FloodWait: ждём {e.seconds} сек"); await asyncio.sleep(e.seconds)
            except Exception as e: print(f"⚠️ Не удалось запустить бота: {e}"); break
    await cleanup_old_backups()
    await init_protected_users()
    await restore_state()
    asyncio.create_task(backup_loop())
    asyncio.create_task(schedule_runner())
    signal.signal(signal.SIGTERM, shutdown_handler)
    await start_web_server()
    tasks = [client1.run_until_disconnected()]
    if client2: tasks.append(client2.run_until_disconnected())
    if bot and bot.is_connected(): tasks.append(bot.run_until_disconnected())
    await asyncio.gather(*tasks)
    if http_session: await http_session.close()

if __name__ == "__main__":
    asyncio.run(main())
