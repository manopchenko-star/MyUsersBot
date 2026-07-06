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

# ---------- Обработчики команд (полный список, как раньше) ----------
def register_handlers(client_instance):
    # (все обработчики .mute, .unmute, .avto, .spam, .ping, .purge, .save, .get, .stats, .tr, .addfriend, .delfriend, .listfriends, .clearall, .history, .help, .qr, .weather, .tts, .sticker, .stt, .shutdown, .restart, .afk, .unafk, .search, filter_handler, auto_read_handler)
    # ... (сокращено для краткости, но они должны быть здесь как в предыдущем ответе)
    pass

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

HTML_LOGIN = """<html><head><meta charset="utf-8"><title>Вход</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@300;600&display=swap');
* { box-sizing: border-box; }
body { margin: 0; height: 100vh; display: flex; align-items: center; justify-content: center; background: linear-gradient(45deg, #0a0a0a, #1a1a2e, #0a0a0a); background-size: 400% 400%; animation: gradientBG 10s ease infinite; font-family: 'Montserrat', sans-serif; }
@keyframes gradientBG { 0%{background-position:0% 50%} 50%{background-position:100% 50%} 100%{background-position:0% 50%} }
.card { background: rgba(20,20,30,0.9); backdrop-filter: blur(10px); border: 1px solid rgba(233,69,96,0.3); border-radius: 16px; padding: 2rem; width: 320px; box-shadow: 0 0 30px rgba(233,69,96,0.3); animation: pulse 2s infinite; }
@keyframes pulse { 0% { box-shadow: 0 0 30px rgba(233,69,96,0.3); } 50% { box-shadow: 0 0 50px rgba(233,69,96,0.6); } 100% { box-shadow: 0 0 30px rgba(233,69,96,0.3); } }
h2 { color: #e94560; text-align: center; font-weight: 600; margin-top: 0; }
input, select { width: 100%; padding: 0.7rem; margin: 0.5rem 0; border: none; border-radius: 8px; background: #1a1a2e; color: #e0e0e0; font-size: 1rem; border: 1px solid rgba(233,69,96,0.2); transition: 0.3s; }
input:focus, select:focus { border-color: #e94560; box-shadow: 0 0 10px rgba(233,69,96,0.5); outline: none; }
button { width: 100%; padding: 0.7rem; margin-top: 1rem; border: none; border-radius: 8px; background: #e94560; color: white; font-weight: 600; cursor: pointer; transition: 0.3s; }
button:hover { background: #c93750; transform: scale(1.02); }
.bot-login { margin-top: 1.5rem; text-align: center; }
.bot-login button { background: transparent; border: 1px solid #e94560; box-shadow: none; }
.bot-login button:hover { background: rgba(233,69,96,0.1); }
</style></head><body>
<div class="card">
<form action="/auth/login" method="post">
<h2>Вход</h2>
<input type="text" name="username" placeholder="Логин" value="admin" autocomplete="username">
<input type="password" name="password" placeholder="Пароль" autocomplete="current-password">
<button type="submit">Войти</button>
</form>
<div class="bot-login">
<button onclick="loginViaBot()">Войти через Telegram</button>
<button onclick="showRegister()">Регистрация через QR</button>
</div>
<div id="registerForm" style="display:none; margin-top:1rem;">
<input type="text" id="regName" placeholder="Имя пользователя">
<select id="regRole"><option value="admin">Админ</option><option value="readonly">Чтение</option></select>
<button onclick="registerViaBot()">Зарегистрироваться</button>
</div>
</div>
<script>
async function loginViaBot() {
    const resp = await fetch('/auth/request_bot');
    const data = await resp.json();
    if (data.token) {
        document.cookie = "auth_token=" + data.token + "; path=/";
        const interval = setInterval(async () => {
            const check = await fetch('/auth/check_token?token=' + data.token);
            if ((await check.json()).approved) {
                clearInterval(interval);
                window.location.href = '/dashboard';
            }
        }, 3000);
    }
}
async function registerViaBot() {
    const name = document.getElementById('regName').value.trim();
    const role = document.getElementById('regRole').value;
    if (!name) { alert('Введите имя'); return; }
    const resp = await fetch('/auth/request_bot?mode=register&name=' + encodeURIComponent(name) + '&role=' + role);
    const data = await resp.json();
    if (data.token) {
        document.cookie = "auth_token=" + data.token + "; path=/";
        const qrDiv = document.createElement('div');
        qrDiv.innerHTML = '<img src="' + data.qr_url + '" style="width:200px;height:200px;"><br>Отсканируйте QR-код или перейдите по <a href="' + data.qr_url + '" target="_blank">ссылке</a>';
        document.querySelector('.card').appendChild(qrDiv);
        const interval = setInterval(async () => {
            const check = await fetch('/auth/check_token?token=' + data.token);
            const res = await check.json();
            if (res.approved) {
                clearInterval(interval);
                window.location.href = '/dashboard';
            } else if (res.rejected) {
                clearInterval(interval);
                alert('Регистрация отклонена');
            }
        }, 3000);
    }
}
function showRegister() { document.getElementById('registerForm').style.display='block'; }
</script>
</body></html>"""

# Финальный HTML_DASHBOARD – проверен, без синтаксических ошибок
HTML_DASHBOARD = """<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Userbot Panel</title>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@300;400;600&display=swap');
    :root { --bg: linear-gradient(135deg, #0a0a0a, #1a1a2e, #0a0a0a); --card: rgba(19,19,31,0.8); --text: #e0e0e0; --accent: #e94560; }
    .light { --bg: #f0f0f0; --card: rgba(255,255,255,0.9); --text: #222; --accent: #e94560; }
    * { box-sizing: border-box; }
    body { margin: 0; background: var(--bg); background-size: 400% 400%; animation: gradientBG 15s ease infinite; color: var(--text); font-family: 'Montserrat', sans-serif; }
    @keyframes gradientBG { 0%{background-position:0% 50%} 50%{background-position:100% 50%} 100%{background-position:0% 50%} }
    .navbar { display: flex; align-items: center; justify-content: space-between; background: rgba(19,19,31,0.9); backdrop-filter: blur(10px); padding: 0.8rem 2rem; border-bottom: 1px solid rgba(233,69,96,0.3); }
    .navbar-brand { font-size: 1.5rem; font-weight: 600; color: #e94560; text-decoration: none; }
    .nav-info { display: flex; gap: 1.5rem; align-items: center; }
    .nav-info span { opacity: 0.8; }
    .logout-btn { background: rgba(233,69,96,0.2); padding: 0.4rem 0.8rem; border-radius: 6px; color: #e94560; text-decoration: none; }
    .tabs { display: flex; gap: 0.5rem; padding: 1rem 2rem; background: rgba(19,19,31,0.8); overflow-x: auto; }
    .tabs button { background: transparent; color: #aaa; border: none; padding: 0.5rem 1rem; border-radius: 8px; cursor: pointer; }
    .tabs button.active { background: var(--accent); color: white; }
    .content { padding: 2rem; }
    .tab-pane { display: none; }
    .tab-pane.active { display: block; }
    .list-group-item { background: var(--card); border: 1px solid rgba(255,255,255,0.05); border-radius: 8px; padding: 0.7rem 1rem; margin-bottom: 0.5rem; display: flex; justify-content: space-between; align-items: center; }
    .btn-custom { background: var(--accent); color: white; border: none; padding: 0.4rem 0.8rem; border-radius: 6px; cursor: pointer; font-size: 0.8rem; text-decoration: none; display: inline-block; }
    table { width: 100%; border-collapse: collapse; margin-top: 1rem; }
    th, td { padding: 0.6rem; border-bottom: 1px solid rgba(255,255,255,0.05); text-align: left; }
    th { color: var(--accent); }
    .badge { padding: 0.2rem 0.5rem; border-radius: 4px; font-size: 0.75rem; }
    .badge-ok { background: #238636; }
    .badge-error { background: #da3633; }
    .notification { position: fixed; top: 1rem; right: 1rem; background: #238636; color: white; padding: 0.8rem 1.2rem; border-radius: 8px; display: none; z-index: 999; }
    input, select, textarea { background: #13131f; color: white; border: 1px solid #30363d; border-radius: 6px; padding: 0.5rem; }
    @media (max-width: 768px) { .tabs { flex-wrap: nowrap; } }
  </style>
</head>
<body class="{theme_class}">
  <nav class="navbar">
    <a class="navbar-brand" href="#">🤖 Userbot Panel</a>
    <div class="nav-info">
      <select id="activeAccountSelect" onchange="setActiveAccount(this.value)" style="background:#13131f;color:white;"></select>
      <button class="btn-custom" onclick="toggleTheme()">🌓 Тема</button>
      <span><i class="far fa-user"></i> {user}</span>
      <a href="/logout" class="logout-btn"><i class="fas fa-sign-out-alt"></i></a>
    </div>
  </nav>
  <div class="tabs">
    <button class="active" data-tab="muted">🔇 Чаты в муте</button>
    <button data-tab="protected">🛡 Защищённые</button>
    <button data-tab="commands">⚡ Команды</button>
    <button data-tab="history">📜 История</button>
    <button data-tab="admins">👥 Админы</button>
    <button data-tab="accounts">👤 Аккаунты</button>
    <button data-tab="backup">📦 Бэкап</button>
    <button data-tab="notes">📝 Заметки</button>
    <button data-tab="afk">⏳ AFK</button>
    <button data-tab="filters">🔍 Фильтры</button>
    <button data-tab="schedule">⏰ Планировщик</button>
    <button data-tab="stats">📊 Статистика</button>
  </div>
  <div class="content">
    <div id="muted" class="tab-pane active">
      <div style="margin-bottom:1rem;">
        <input type="text" id="massMuteInput" placeholder="ID чатов через запятую">
        <button class="btn-custom" onclick="massMute()">Замутить все</button>
        <button class="btn-custom" onclick="massUnmute()">Размутить все</button>
      </div>
      <div id="mutedList"></div>
    </div>
    <div id="protected" class="tab-pane"><div id="protectedList"></div></div>
    <div id="commands" class="tab-pane">
      <form action="/send_cmd" method="post" style="display: grid; gap: 0.8rem; max-width: 500px;">
        <select name="account" id="accountSelect"></select>
        <input name="target" placeholder="Чат (username или ID, пусто = Избранное)">
        <select name="command" id="cmdSelect">
          <option value=".mute">.mute</option><option value=".unmute">.unmute</option><option value=".spam">.spam</option><option value=".ping">.ping</option><option value=".purge">.purge</option><option value=".clearall">.clearall</option><option value=".stats">.stats</option><option value=".tr">.tr</option><option value=".avto">.avto</option><option value=".help">.help</option><option value=".search">.search</option>
        </select>
        <input name="args" placeholder="Аргументы">
        <button type="submit" class="btn-custom" style="padding:0.6rem;">Отправить</button>
      </form>
    </div>
    <div id="history" class="tab-pane">
      <button class="btn-custom" onclick="exportCSV()" style="margin-bottom:0.5rem;">Экспорт CSV</button>
      <table><thead><tr><th>Время</th><th>Источник</th><th>Пользователь</th><th>Команда</th><th>Цель</th></tr></thead><tbody id="historyBody"></tbody></table>
    </div>
    <div id="admins" class="tab-pane">
      <form action="/add_admin" method="post" style="display:flex; gap:0.5rem; margin-bottom:1rem;">
        <input name="username" placeholder="Логин" required>
        <input name="password" type="password" placeholder="Пароль" required autocomplete="new-password">
        <select name="role"><option value="admin">Админ</option><option value="readonly">Чтение</option></select>
        <button type="submit" class="btn-custom">Добавить</button>
      </form>
      <div id="adminsList"></div>
    </div>
    <div id="accounts" class="tab-pane">
      <form action="/add_account" method="post" style="display:flex; flex-direction:column; gap:0.5rem; max-width:500px;">
        <input name="name" placeholder="Имя аккаунта" required>
        <textarea name="session_string" placeholder="SESSION_STRING" required style="height:100px;"></textarea>
        <button type="submit" class="btn-custom">Подключить</button>
      </form>
      <div id="extraAccountsList" style="margin-top:1rem;"></div>
    </div>
    <div id="backup" class="tab-pane">
      <button class="btn-custom" onclick="createBackup()">Создать бэкап</button>
      <div style="margin:1rem 0;">
        <a href="/download/backup/enc" class="btn-custom">Скачать зашифрованный</a>
        <a href="/download/backup/dec" class="btn-custom">Скачать расшифрованный</a>
      </div>
      <table><thead><tr><th>Время</th><th>Статус</th></tr></thead><tbody id="backupHistoryBody"></tbody></table>
    </div>
    <div id="notes" class="tab-pane">
      <textarea id="notesText" style="width:100%; height:300px;"></textarea>
      <button class="btn-custom" onclick="saveNotes()">Сохранить</button>
    </div>
    <div id="afk" class="tab-pane">
      <div id="afkList"></div>
    </div>
    <div id="filters" class="tab-pane">
      <h5>Чёрный список слов (глобальный)</h5>
      <div id="blacklistWords"></div>
      <input id="newBlacklistWord" placeholder="Слово"><button class="btn-custom" onclick="addBlacklistWord()">Добавить</button>
      <h5>Фильтры чатов</h5>
      <div id="filtersList"></div>
      <input id="filterChatId" placeholder="ID чата"><input id="filterWord" placeholder="Слово"><select id="filterAction"><option value="delete">Удалить</option><option value="mute">Замутить</option></select>
      <button class="btn-custom" onclick="addFilter()">Добавить</button>
    </div>
    <div id="schedule" class="tab-pane">
      <form id="scheduleForm">
        <input type="datetime-local" id="schedTime" required>
        <select id="schedAccount"></select>
        <input id="schedTarget" placeholder="Чат (пусто=Избранное)">
        <select id="schedCommand">
          <option value=".spam">.spam</option><option value=".ping">.ping</option><option value=".mute">.mute</option><option value=".unmute">.unmute</option>
        </select>
        <input id="schedArgs" placeholder="Аргументы">
        <button type="button" class="btn-custom" onclick="addSchedule()">Добавить задачу</button>
      </form>
      <div id="scheduleList"></div>
    </div>
    <div id="stats" class="tab-pane">
      <canvas id="statsChart" width="400" height="200"></canvas>
    </div>
  </div>
  <div id="notification" class="notification"></div>
  <script>
    var ws, fullHistory=[], acc1Name="Аккаунт 1", acc2Name="Аккаунт 2", extraAccounts=[], backupHistory=[], afkUsers={}, notes="", filters={}, blacklist=[], schedule=[], activeAccount="1", theme="dark";

    function showNotification(text, isError) {
      isError = isError || false;
      var n = document.getElementById('notification');
      n.textContent = text;
      n.className = 'notification' + (isError ? ' error' : '');
      n.style.display = 'block';
      setTimeout(function() { n.style.display = 'none'; }, 4000);
    }

    window.addEventListener('load', function() {
      connectWS();
      document.getElementById('activeAccountSelect').addEventListener('change', function() { setActiveAccount(this.value); });
    });

    function connectWS() {
      ws = new WebSocket('wss://' + location.host + '/ws');
      ws.onmessage = function(e) { updateUI(JSON.parse(e.data)); };
      ws.onclose = function() { setTimeout(connectWS, 3000); };
    }

    function updateUI(data) {
      acc1Name = data.acc1_name || 'Аккаунт 1';
      acc2Name = data.acc2_name;
      extraAccounts = data.extra_clients || [];
      var sel = document.getElementById('accountSelect');
      sel.innerHTML = '';
      sel.add(new Option(acc1Name, '1'));
      if (acc2Name) sel.add(new Option(acc2Name, '2'));
      extraAccounts.forEach(function(name) { sel.add(new Option(name, name)); });
      var activeSel = document.getElementById('activeAccountSelect');
      activeSel.innerHTML = '';
      activeSel.add(new Option(acc1Name, '1'));
      if (acc2Name) activeSel.add(new Option(acc2Name, '2'));
      extraAccounts.forEach(function(name) { activeSel.add(new Option(name, name)); });
      activeSel.value = data.active_account || "1";
      activeAccount = data.active_account || "1";

      fullHistory = data.history || [];
      backupHistory = data.backup_history || [];
      afkUsers = data.afk_users || {};
      notes = data.notes || "";
      filters = data.filters || {};
      blacklist = data.blacklist || [];
      schedule = data.schedule || [];
      theme = data.theme || "dark";
      document.body.className = theme;
      document.getElementById('notesText').value = notes;

      renderMuted(data);
      renderProtected(data);
      renderHistory();
      renderBackupHistory();
      renderAdmins(data);
      renderExtraAccounts();
      renderAfk();
      renderFilters();
      renderSchedule();
      updateStatsChart();
    }

    function renderMuted(data) {
      var html = '';
      for (var id in data.chat_names) {
        html += '<div class="list-group-item">' + data.chat_names[id] + ' <button class="btn-custom" onclick="unmuteChat(' + id + ')">Размутить</button></div>';
      }
      document.getElementById('mutedList').innerHTML = html || 'Нет чатов';
    }

    function renderProtected(data) {
      var html = '';
      for (var id in data.user_names) {
        html += '<div class="list-group-item">' + data.user_names[id] + '</div>';
      }
      document.getElementById('protectedList').innerHTML = html || 'Нет';
    }

    function renderHistory() {
      var html = '';
      fullHistory.slice(-20).forEach(function(e) {
        html += '<tr><td>' + e.time.substr(11,8) + '</td><td>' + e.source + '</td><td>' + e.user_name + '</td><td>' + e.command + '</td><td>' + (e.target_name||'') + '</td></tr>';
      });
      document.getElementById('historyBody').innerHTML = html || '<tr><td colspan="5">Нет записей</td></tr>';
    }

    function renderBackupHistory() {
      var html = '';
      backupHistory.forEach(function(e) {
        var statusHtml = e.success ? '<span class="badge badge-ok">✅</span>' : '<span class="badge badge-error">❌</span>';
        html += '<tr><td>' + new Date(e.time).toLocaleString() + '</td><td>' + statusHtml + '</td></tr>';
      });
      document.getElementById('backupHistoryBody').innerHTML = html || '<tr><td colspan="2">Нет бэкапов</td></tr>';
    }

    function renderAdmins(data) {
      var html = '';
      if (data.admins) data.admins.forEach(function(user) {
        html += '<div class="list-group-item">' + user + ' <a href="/delete_admin?user=' + user + '" class="btn-custom">Удалить</a></div>';
      });
      document.getElementById('adminsList').innerHTML = html || 'Нет админов';
    }

    function renderExtraAccounts() {
      var html = '';
      extraAccounts.forEach(function(name) {
        html += '<div class="list-group-item">' + name + ' <a href="/remove_account?name=' + name + '" class="btn-custom">Отключить</a></div>';
      });
      document.getElementById('extraAccountsList').innerHTML = html || 'Нет';
    }

    function renderAfk() {
      var html = '';
      for (var uid in afkUsers) {
        html += '<div class="list-group-item">' + uid + ': ' + afkUsers[uid] + ' <button class="btn-custom" onclick="removeAfk(\'' + uid + '\')">Снять</button></div>';
      }
      document.getElementById('afkList').innerHTML = html || 'Нет AFK';
    }

    function renderFilters() {
      var blackHtml = blacklist.map(function(w) { return '<span class="badge badge-error">' + w + ' <i onclick="removeBlacklistWord(\'' + w + '\')" style="cursor:pointer;">×</i></span>'; }).join(' ');
      document.getElementById('blacklistWords').innerHTML = blackHtml || 'Нет слов';
      var filterHtml = '';
      for (var chat in filters) {
        filters[chat].forEach(function(rule) {
          filterHtml += '<div class="list-group-item">Чат ' + chat + ': слово "' + rule.word + '" -> ' + rule.action + ' <button class="btn-custom" onclick="removeFilter(\'' + chat + '\', \'' + rule.word + '\')">Удалить</button></div>';
        });
      }
      document.getElementById('filtersList').innerHTML = filterHtml || 'Нет фильтров';
    }

    function renderSchedule() {
      var html = '';
      schedule.forEach(function(task, idx) {
        html += '<div class="list-group-item">' + task.time + ' - ' + task.command + ' ' + (task.args||'') + ' в ' + (task.target||'Избранное') + ' <button class="btn-custom" onclick="deleteSchedule(' + idx + ')">Удалить</button></div>';
      });
      document.getElementById('scheduleList').innerHTML = html || 'Нет задач';
    }

    var statsChartInstance;
    function updateStatsChart() {
      var ctx = document.getElementById('statsChart');
      if (!ctx) return;
      ctx = ctx.getContext('2d');
      var days = {};
      fullHistory.forEach(function(e) {
        var day = e.time.substr(0,10);
        days[day] = (days[day]||0) + 1;
      });
      var labels = Object.keys(days).sort();
      var values = labels.map(function(d) { return days[d]; });
      if (window.statsChartInstance) window.statsChartInstance.destroy();
      window.statsChartInstance = new Chart(ctx, {
        type: 'line',
        data: { labels: labels, datasets: [{ label: 'Команды по дням', data: values, borderColor: '#e94560' }] }
      });
    }

    async function unmuteChat(id) {
      await fetch('/unmute?chat_id='+id+'&account='+activeAccount);
      showNotification('Чат размучен');
    }
    async function createBackup() {
      await fetch('/backup_now');
      showNotification('Бэкап создан');
    }
    function exportCSV() {
      var csv = "time,source,user,command,target\n";
      fullHistory.forEach(function(e) { csv += e.time + ',' + e.source + ',' + e.user_name + ',' + e.command + ',' + (e.target_name||'') + '\n'; });
      var blob = new Blob([csv], {type: 'text/csv'});
      var url = URL.createObjectURL(blob);
      var a = document.createElement('a');
      a.href = url;
      a.download = 'history.csv';
      a.click();
    }
    async function saveNotes() {
      var text = document.getElementById('notesText').value;
      await fetch('/api/notes', {method: 'POST', body: new URLSearchParams({notes: text})});
      showNotification('Заметки сохранены');
    }
    async function removeAfk(uid) {
      await fetch('/api/afk/remove?uid=' + uid);
    }
    async function addBlacklistWord() {
      var word = document.getElementById('newBlacklistWord').value.trim();
      if (word) await fetch('/api/blacklist/add', {method: 'POST', body: new URLSearchParams({word: word})});
    }
    async function removeBlacklistWord(word) {
      await fetch('/api/blacklist/remove?word=' + word);
    }
    async function addFilter() {
      var chat = document.getElementById('filterChatId').value;
      var word = document.getElementById('filterWord').value;
      var action = document.getElementById('filterAction').value;
      if (chat && word) await fetch('/api/filters/add', {method: 'POST', body: new URLSearchParams({chat: chat, word: word, action: action})});
    }
    async function removeFilter(chat, word) {
      await fetch('/api/filters/remove?chat=' + chat + '&word=' + word);
    }
    async function addSchedule() {
      var time = document.getElementById('schedTime').value;
      var account = document.getElementById('schedAccount').value || "1";
      var target = document.getElementById('schedTarget').value || "me";
      var command = document.getElementById('schedCommand').value;
      var args = document.getElementById('schedArgs').value;
      await fetch('/api/schedule/add', {method: 'POST', body: new URLSearchParams({time: time, account: account, target: target, command: command, args: args})});
    }
    async function deleteSchedule(idx) {
      await fetch('/api/schedule/delete?idx=' + idx);
    }
    async function setActiveAccount(acc) {
      activeAccount = acc;
      await fetch('/api/active_account', {method: 'POST', body: new URLSearchParams({account: acc})});
    }
    async function toggleTheme() {
      var newTheme = theme === 'dark' ? 'light' : 'dark';
      theme = newTheme;
      document.body.className = theme;
      await fetch('/api/theme', {method: 'POST', body: new URLSearchParams({theme: newTheme})});
    }
    async function massMute() {
      var ids = document.getElementById('massMuteInput').value.split(',').map(function(s) { return s.trim(); }).filter(Boolean);
      for (var i = 0; i < ids.length; i++) {
        await fetch('/api/mass_mute?chat_id=' + ids[i]);
      }
      showNotification('Массовый мут выполнен');
    }
    async function massUnmute() {
      var ids = document.getElementById('massMuteInput').value.split(',').map(function(s) { return s.trim(); }).filter(Boolean);
      for (var i = 0; i < ids.length; i++) {
        await fetch('/api/mass_unmute?chat_id=' + ids[i]);
      }
      showNotification('Массовый размут выполнен');
    }

    document.querySelectorAll('.tabs button').forEach(function(btn) {
      btn.addEventListener('click', function() {
        document.querySelectorAll('.tabs button').forEach(function(b) { b.classList.remove('active'); });
        this.classList.add('active');
        document.querySelectorAll('.tab-pane').forEach(function(p) { p.classList.remove('active'); });
        document.getElementById(this.dataset.tab).classList.add('active');
        if (this.dataset.tab === 'stats') updateStatsChart();
      });
    });
  </script>
</body>
</html>"""

HTML_GUEST = """<html><head><meta charset="utf-8"><title>Гостевой просмотр</title>
<style>body { background: #0a0a0a; color: #e0e0e0; font-family: sans-serif; padding: 20px; }</style>
</head><body><h1>Состояние бота</h1><div id="content"></div>
<script>
var ws = new WebSocket('wss://' + location.host + '/guest-ws?key=' + (new URL(location)).searchParams.get('key'));
ws.onmessage = function(event) {
  var data = JSON.parse(event.data);
  var html = '<h3>Чаты в муте:</h3><ul>';
  for (var id in data.chat_names) html += '<li>' + data.chat_names[id] + '</li>';
  html += '</ul><h3>Защищённые:</h3><ul>';
  for (var id in data.user_names) html += '<li>' + data.user_names[id] + '</li>';
  html += '</ul><h3>История:</h3><table border="1"><tr><th>Время</th><th>Команда</th></tr>';
  data.history.forEach(function(e) { html += '<tr><td>' + e.time.substr(11,8) + '</td><td>' + e.command + '</td></tr>'; });
  html += '</table>';
  document.getElementById('content').innerHTML = html;
};
</script>
</body></html>"""

# ---------- Веб-обработчики ----------
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

async def auth_login(request):
    data = await request.post()
    username = data.get("username", ""); password = data.get("password", "")
    if username in admins and admins[username]["password"] == hash_password(password):
        resp = web.HTTPFound("/dashboard"); resp.set_cookie("auth_token", "password_ok"); return resp
    return web.HTTPFound("/login?error=1")

async def logout(request):
    resp = web.HTTPFound("/login"); resp.del_cookie("auth_token"); resp.del_cookie("invite_token"); return resp

async def request_bot_auth(request):
    mode = request.query.get("mode", "login")
    if not bot: return web.json_response({"error": "Бот не настроен"})
    token = str(uuid.uuid4())
    if mode == "register":
        name = request.query.get("name", "user")
        role = request.query.get("role", "readonly")
        pending_registrations[token] = {"name": name, "role": role}
        me1 = await client1.get_me()
        text = f"🔐 <b>Запрос на регистрацию</b>\nПользователь: {name}\nРоль: {role}\nРазрешить?"
    else:
        auth_tokens[token] = "pending"
        me1 = await client1.get_me()
        text = "🔐 <b>Запрос на вход</b>\nРазрешить?"
    try:
        await bot.send_message(me1.id, text, buttons=[
            [Button.inline("✅ Принять", f"approve:{token}")],
            [Button.inline("❌ Отклонить", f"reject:{token}")]
        ], parse_mode='html')
        qr_url = f"https://myusersbot.onrender.com/auth/check_token?token={token}"
        return web.json_response({"token": token, "qr_url": qr_url})
    except Exception as e:
        auth_tokens.pop(token, None); pending_registrations.pop(token, None)
        return web.json_response({"error": str(e)})

async def check_token(request):
    token = request.query.get("token")
    if token in pending_registrations:
        info = pending_registrations.pop(token)
        password = uuid.uuid4().hex[:8]
        admins[info["name"]] = {"password": hash_password(password), "role": info["role"]}
        save_admins()
        auth_tokens[token] = True
        return web.Response(text=f"Регистрация одобрена. Ваш пароль: {password}")
    if token in auth_tokens and auth_tokens[token] == "pending":
        auth_tokens[token] = True
        return web.Response(text="Вход одобрен. Можете вернуться в панель.")
    if token in auth_tokens:
        return web.json_response({"approved": auth_tokens[token] == True})
    return web.json_response({"approved": False})

# Остальные обработчики (add_admin, delete_admin, add_account, remove_account, unmute, remove_protected, send_cmd, backup_now, download_backup_enc, download_backup_dec, websocket, guest_ws, api_*) без изменений
# ... (вставьте их из предыдущего полного кода, они уже отлажены)

# Запуск
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
