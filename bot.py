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
from duckduckgo_search import DDGS
from bs4 import BeautifulSoup
import requests

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
TEMPLATES_DIR = Path("templates")

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
deleted_messages = {}
log_buffer = []

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

# ---------- Логирование ----------
def add_log(msg_type, text):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_buffer.append({"time": ts, "type": msg_type, "text": text})
    if len(log_buffer) > 200:
        log_buffer.pop(0)
    print(f"[{msg_type}] {text}")
    asyncio.ensure_future(broadcast_log(msg_type, text, ts))

async def broadcast_log(msg_type, text, ts):
    data = {"event": "log", "time": ts, "type": msg_type, "text": text}
    msg = json.dumps(data, ensure_ascii=False)
    for ws in list(ws_clients):
        try: await ws.send_str(msg)
        except: ws_clients.discard(ws)

# ---------- Поисковые функции ----------
def yandex_search(query, num=5):
    try:
        url = f"https://yandex.ru/search/?text={urllib.parse.quote(query)}&lr=2"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        results = []
        for item in soup.select('li.serp-item')[:num]:
            link = item.select_one('a.link')
            if link and link.get('href'):
                results.append(link['href'])
        return results
    except Exception as e:
        return [f"Ошибка: {e}"]

# ---------- Бэкапы ----------
async def cleanup_old_backups():
    global last_backup_msg_id
    if not client2 or not client2.is_connected(): return
    try:
        deleted = 0
        async for msg in client2.iter_messages('me', from_user='me'):
            if msg.file and msg.file.name == "backup.enc":
                await msg.delete(); deleted += 1
        if deleted:
            add_log("INFO", f"🧹 Очищено {deleted} старых бэкапов у друга")
            last_backup_msg_id = None; save_json(LAST_MSG_FILE, None)
    except Exception as e: add_log("ERROR", f"Ошибка при очистке старых бэкапов: {e}")

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
        except Exception as e: add_log("WARN", f"Не удалось удалить старый бэкап: {e}")
        last_backup_msg_id = None; save_json(LAST_MSG_FILE, None)
    try:
        msg = await client2.send_file('me', io.BytesIO(encrypted), file_name="backup.enc")
        last_backup_msg_id = msg.id; save_json(LAST_MSG_FILE, last_backup_msg_id)
        success = True; add_log("INFO", f"Бэкап отправлен другу (id={msg.id})")
    except Exception as e: error_text = f"Ошибка отправки другу: {e}"; add_log("ERROR", error_text)
    if success:
        try:
            owner = await client1.get_entity(OWNER_USERNAME)
            try:
                async for msg in client1.iter_messages(owner.id, from_user='me', limit=10):
                    if msg.text and "✅ Бэкап сделан" in msg.text: await msg.delete()
            except: pass
            await client1.send_message(owner.id, "✅ Бэкап сделан")
            add_log("INFO", "Уведомление о бэкапе отправлено владельцу")
        except Exception as e: add_log("WARN", f"Не удалось уведомить владельца: {e}")
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
    except Exception as e: add_log("WARN", f"Ошибка восстановления: {e}")
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
            except Exception as e: add_log("WARN", f"Не удалось подключить {name}: {e}")

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
                add_log("ERROR", f"Ошибка выполнения задачи {task}: {e}")
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
    logs = log_buffer[-50:]
    for ws in list(ws_clients):
        try: await ws.send_str(json.dumps({"event": "logs_init", "logs": logs}, ensure_ascii=False))
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
        except Exception as e: add_log("WARN", f"Не удалось получить данные второго аккаунта: {e}")
    try:
        owner = await client1.get_entity(OWNER_USERNAME); protected_users.add(owner.id)
    except Exception as e: add_log("WARN", f"Не удалось найти владельца {OWNER_USERNAME}: {e}")
    save_state(); await broadcast_state(); await backup_state()

# ---------- Обработчики команд ----------
def register_handlers(client_instance):
    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.mute$'))
    async def mute_cmd(event):
        chat = await event.get_chat()
        if hasattr(chat, 'broadcast') and chat.broadcast: return
        muted_chats.add(event.chat_id); save_state(); await event.delete()
        user_name = await resolve_name(event.sender_id); target_name = await resolve_chat_name(event.chat_id)
        log_command(event.sender_id, ".mute", source="Telegram", target_id=event.chat_id, user_name=user_name, target_name=target_name, result="ok")
        add_log("CMD", f"Мут чата {target_name} ({event.chat_id})")
        text = "🔇 <b>Пользователь заглушен</b>\nВсе его сообщения будут <i>мгновенно удаляться</i>.\n\nНажмите кнопку ниже, чтобы размутить."
        buttons = [Button.inline("🔊 Размутить", b"unmute")]
        await event.client.send_message(event.chat_id, text, buttons=buttons, parse_mode='html')
        await broadcast_state(); await backup_state()

    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.unmute$'))
    async def unmute_cmd(event):
        muted_chats.discard(event.chat_id); save_state(); await event.delete()
        user_name = await resolve_name(event.sender_id); target_name = await resolve_chat_name(event.chat_id)
        log_command(event.sender_id, ".unmute", source="Telegram", target_id=event.chat_id, user_name=user_name, target_name=target_name, result="ok")
        add_log("CMD", f"Размут чата {target_name} ({event.chat_id})")
        await event.client.send_message(event.chat_id, "🔊 <b>Мут снят.</b> Сообщения больше не удаляются.", parse_mode='html')
        await broadcast_state(); await backup_state()

    @client_instance.on(events.NewMessage(incoming=True))
    async def delete_muted(event):
        if event.chat_id in muted_chats and not event.out:
            if event.sender_id not in protected_users:
                if event.text:
                    cid = event.chat_id
                    if cid not in deleted_messages:
                        deleted_messages[cid] = []
                    deleted_messages[cid].append(event.text)
                    if len(deleted_messages[cid]) > 50:
                        deleted_messages[cid] = deleted_messages[cid][-50:]
                    add_log("DEL", f"Удалено сообщение из чата {event.chat_id}: {event.text[:50]}...")
                try: await event.delete()
                except: pass

    @client_instance.on(events.CallbackQuery(data=b"unmute"))
    async def unmute_callback(event):
        muted_chats.discard(event.chat_id); save_state()
        user_name = await resolve_name(event.sender_id); target_name = await resolve_chat_name(event.chat_id)
        log_command(event.sender_id, "Размутил (кнопка)", source="Telegram", target_id=event.chat_id, user_name=user_name, target_name=target_name, result="ok")
        add_log("CMD", f"Размут чата {target_name} ({event.chat_id}) через кнопку")
        await event.edit("🔊 <b>Мут снят.</b>", buttons=None, parse_mode='html')
        await broadcast_state(); await backup_state()

    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.avto(\s+all)?(?:\s+(.*))?'))
    async def avto_cmd(event):
        is_global = bool(event.pattern_match.group(1)); custom_text = event.pattern_match.group(2).strip() if event.pattern_match.group(2) else None
        if is_global:
            auto_reply_global['enabled'] = True
            if custom_text: auto_reply_global['text'] = custom_text
            await event.delete()
            await event.client.send_message(event.chat_id if event.is_private else None, f"🌐 <b>Глобальный автоответчик включён.</b>\nТекст: {auto_reply_global['text']}", parse_mode='html')
        else:
            if not event.is_private: await event.reply("❌ Автоответчик для групп не поддерживается."); return
            if custom_text is None: custom_text = "⏳ Привет! Я сейчас не в сети, отвечу позже."
            auto_reply_chats[event.chat_id] = {'enabled': True, 'text': custom_text}
            await event.delete()
            await event.client.send_message(event.chat_id, f"✅ <b>Автоответчик включён в этом чате.</b>\nТекст: {custom_text}", parse_mode='html')

    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.unavto(\s+all)?'))
    async def unavto_cmd(event):
        is_global = bool(event.pattern_match.group(1))
        if is_global:
            auto_reply_global['enabled'] = False; await event.delete()
            if event.is_private: await event.client.send_message(event.chat_id, "🌐 <b>Глобальный автоответчик выключен.</b>", parse_mode='html')
        else:
            if not event.is_private: await event.reply("❌ Автоответчик для групп не поддерживается."); return
            if event.chat_id in auto_reply_chats: del auto_reply_chats[event.chat_id]
            await event.delete()
            await event.client.send_message(event.chat_id, "❌ <b>Автоответчик выключен в этом чате.</b>", parse_mode='html')

    @client_instance.on(events.NewMessage(incoming=True))
    async def auto_reply_handler(event):
        if event.out: return
        chat_id = event.chat_id
        if chat_id in muted_chats:
            if event.sender_id not in protected_users:
                try: await event.delete()
                except: pass
            return
        chat_settings = auto_reply_chats.get(chat_id)
        if chat_settings and chat_settings.get('enabled'):
            reply_text = chat_settings.get('text')
            if reply_text:
                if last_replied.get(chat_id) == event.id: return
                await asyncio.sleep(1); await event.client.send_message(chat_id, reply_text)
                last_replied[chat_id] = event.id
            return
        if auto_reply_global['enabled']:
            reply_text = auto_reply_global.get('text')
            if reply_text:
                if last_replied.get(chat_id) == event.id: return
                await asyncio.sleep(1); await event.client.send_message(chat_id, reply_text)
                last_replied[chat_id] = event.id

    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.spam\s+(\d+)\s+(.*)'))
    async def spam_cmd(event):
        count = int(event.pattern_match.group(1)); text = event.pattern_match.group(2)
        await event.delete()
        user_name = await resolve_name(event.sender_id); target_name = await resolve_chat_name(event.chat_id)
        log_command(event.sender_id, f".spam {count} {text}", source="Telegram", target_id=event.chat_id, user_name=user_name, target_name=target_name, result="ok")
        if count > 50: await event.client.send_message(event.chat_id, "⚠️ Максимум 50 повторений за раз."); return
        for _ in range(count): await event.client.send_message(event.chat_id, text); await asyncio.sleep(0.4)

    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.ping$'))
    async def ping_cmd(event):
        start = time.time(); msg = await event.reply("🏓 Пинг..."); elapsed = (time.time() - start) * 1000
        await msg.edit(f"🏓 Понг! `{elapsed:.1f}ms`")

    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.purge(?:\s+(\d+))?'))
    async def purge_cmd(event):
        num = int(event.pattern_match.group(1)) if event.pattern_match.group(1) else 10
        if num > 200: num = 200
        await event.delete()
        user_name = await resolve_name(event.sender_id); target_name = await resolve_chat_name(event.chat_id)
        log_command(event.sender_id, f".purge {num}", source="Telegram", target_id=event.chat_id, user_name=user_name, target_name=target_name, result="ok")
        deleted = 0
        async for message in event.client.iter_messages(event.chat_id, from_user='me', limit=num):
            try: await message.delete(); deleted += 1; await asyncio.sleep(0.5)
            except: pass
        tmp = await event.client.send_message(event.chat_id, f"🗑 Удалено {deleted} сообщений.")
        await asyncio.sleep(3); await tmp.delete()

    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.save\s+(.*)'))
    async def save_cmd(event):
        text = event.pattern_match.group(1)
        await event.client.send_message('me', f"📌 Заметка:\n{text}")
        await event.reply("✅ Заметка сохранена в «Избранное».")

    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.get$'))
    async def get_cmd(event):
        async for msg in event.client.iter_messages('me', limit=20):
            if msg.text and msg.text.startswith("📌"):
                await event.client.send_message(event.chat_id, msg.text); return
        await event.reply("❌ Нет сохранённых заметок.")

    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.stats$'))
    async def stats_cmd(event):
        chat = await event.get_chat()
        if hasattr(chat, 'broadcast') and chat.broadcast: await event.reply("❌ Команда недоступна для каналов."); return
        participants_count = 0
        try: participants_count = (await event.client.get_participants(chat, limit=0)).total
        except: pass
        text = f"📊 <b>Статистика чата</b>\nНазвание: {chat.title}\nID: {chat.id}\nТип: {'Супергруппа' if chat.megagroup else 'Группа' if chat.broadcast else 'ЛС'}\nУчастников: {participants_count}"
        await event.reply(text, parse_mode='html')

    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.tr\s+([a-z]{2})\s+(.*)'))
    async def translate_cmd(event):
        target_lang = event.pattern_match.group(1); text = event.pattern_match.group(2)
        try:
            translated = GoogleTranslator(source='auto', target=target_lang).translate(text)
            await event.reply(f"🌐 Перевод ({target_lang}):\n{translated}")
        except Exception as e: await event.reply(f"❌ Ошибка перевода: {e}")

    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.addfriend$'))
    async def addfriend_cmd(event):
        if not event.is_private: await event.reply("❌ Команда .addfriend работает только в личных сообщениях."); return
        chat = await event.get_chat(); friend_id = chat.id
        if friend_id == event.sender_id: await event.reply("❌ Нельзя добавить самого себя (вы уже защищены)."); return
        protected_users.add(friend_id); save_state()
        await event.reply("✅ Пользователь добавлен в список защищённых от мута.")
        await backup_state()

    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.delfriend$'))
    async def delfriend_cmd(event):
        if not event.is_private: await event.reply("❌ Команда .delfriend работает только в личных сообщениях."); return
        chat = await event.get_chat(); friend_id = chat.id
        me = await event.client.get_me()
        if friend_id == me.id: await event.reply("❌ Нельзя удалить владельца из защиты."); return
        try:
            owner = await client1.get_entity(OWNER_USERNAME)
            if friend_id == owner.id: await event.reply("❌ Создатель не может быть удалён из защиты."); return
        except: pass
        if friend_id in protected_users: protected_users.discard(friend_id); save_state(); await event.reply("✅ Пользователь удалён из списка защиты.")
        else: await event.reply("❌ Пользователь не найден в списке защиты.")
        await backup_state()

    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.listfriends$'))
    async def listfriends_cmd(event):
        if not protected_users: await event.reply("Список защиты пуст."); return
        lines = ["🛡 <b>Защищённые пользователи (не мутаются):</b>"]
        for uid in protected_users:
            try:
                user = await event.client.get_entity(uid)
                name = f"@{user.username}" if user.username else f"{user.first_name} (ID: {uid})"
            except: name = f"ID: {uid}"
            lines.append(f"• {name}")
        await event.reply("\n".join(lines), parse_mode='html')

    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.clearall$'))
    async def clearall_cmd(event):
        await event.delete()
        user_name = await resolve_name(event.sender_id); target_name = await resolve_chat_name(event.chat_id)
        log_command(event.sender_id, ".clearall", source="Telegram", target_id=event.chat_id, user_name=user_name, target_name=target_name, result="ok")
        chat = await event.get_chat()
        if hasattr(chat, 'broadcast') and chat.broadcast: await event.reply("❌ В канале невозможно очистить сообщения."); return
        deleted = 0
        async for msg in event.client.iter_messages(event.chat_id):
            try: await msg.delete(); deleted += 1; await asyncio.sleep(0.5)
            except: pass
        tmp = await event.client.send_message(event.chat_id, f"🗑 Удалено {deleted} сообщений.")
        await asyncio.sleep(3); await tmp.delete()

    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.history$'))
    async def history_cmd(event):
        if not command_history: await event.reply("📜 История команд пуста."); return
        text = "📜 <b>Последние команды</b>:\n"
        for entry in command_history[-10:]:
            text += f"• {entry['time'][:19]} — {entry['source']} {entry['user_name']}: {entry['command']} → {entry['target_name']}\n"
        await event.reply(text, parse_mode='html')

    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.help$'))
    async def help_cmd(event):
        await event.delete()
        text = (
            "📖 <b>Список команд юзербота:</b>\n\n"
            "<b>.mute</b> — заглушить чат\n<b>.unmute</b> — снять мут\n<b>.clearall</b> — удалить все сообщения в чате\n"
            "<b>.avto</b> / .avto all / .unavto — автоответчик\n<b>.spam N текст</b> — повторить N раз\n"
            "<b>.ping</b> — пинг\n<b>.purge [N]</b> — удалить свои последние N сообщений\n<b>.save текст</b> / .get — заметки\n"
            "<b>.stats</b> — статистика чата\n<b>.tr код текст</b> — перевод\n<b>.addfriend</b> / .delfriend / .listfriends\n"
            "<b>.history</b> — история последних команд\n<b>.stt</b> — распознать голосовое сообщение\n<b>.qr текст</b> — QR-код\n"
            "<b>.weather город</b> — погода\n<b>.tts текст</b> — голосовое сообщение\n<b>.sticker</b> — случайный стикер\n"
            "<b>.search [yandex|duck] запрос</b> — поиск\n<b>.recover [N]</b> — показать удалённые сообщения\n"
            "<b>.afk [причина]</b> / .unafk — режим AFK\n<b>.help</b> — это сообщение"
        )
        await event.client.send_message(event.chat_id, text, parse_mode='html')

    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.qr\s+(.*)'))
    async def qr_cmd(event):
        text = event.pattern_match.group(1); await event.delete()
        img = qrcode_lib.make(text); buf = io.BytesIO(); img.save(buf, format='PNG'); buf.seek(0)
        await event.client.send_file(event.chat_id, buf, caption=f"QR: {text}")

    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.weather\s+(.*)'))
    async def weather_cmd(event):
        city = event.pattern_match.group(1).strip(); await event.delete()
        url = f"https://wttr.in/{urllib.parse.quote(city)}?format=%C+%t+%w&lang=ru"
        try:
            async with http_session.get(url, timeout=15) as resp:
                t = await resp.text(); await event.client.send_message(event.chat_id, f"🌤 Погода в {city}:\n{t.strip()}")
        except: await event.client.send_message(event.chat_id, "❌ Не удалось получить погоду.")

    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.tts\s+(.*)'))
    async def tts_cmd(event):
        text = event.pattern_match.group(1); await event.delete()
        try:
            tts = gTTS(text, lang='ru'); buf = io.BytesIO(); tts.write_to_fp(buf); buf.seek(0)
            await event.client.send_file(event.chat_id, buf, voice_note=True)
        except Exception as e: await event.client.send_message(event.chat_id, f"❌ Ошибка синтеза речи: {e}")

    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.sticker$'))
    async def sticker_cmd(event):
        sets = ["UtyaDuck", "HotCherry", "PigPeccary", "duckduckduck", "capoo_stickers"]
        try:
            sticker_set = await event.client.get_sticker_set(random.choice(sets))
            if sticker_set.documents: await event.client.send_file(event.chat_id, random.choice(sticker_set.documents))
            else: await event.reply("Не удалось загрузить стикер.")
        except: await event.reply("❌ Ошибка получения стикера.")

    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.stt$'))
    async def stt_cmd(event):
        if not event.reply_to_msg_id: await event.reply("❌ Ответьте на голосовое сообщение."); return
        reply = await event.get_reply_message()
        if not reply.voice and not (reply.audio and reply.audio.mime_type in ['audio/ogg', 'audio/mp4']):
            await event.reply("❌ Это не голосовое сообщение."); return
        await event.reply("🎙 Распознаю речь...")
        try:
            with tempfile.NamedTemporaryFile(suffix='.ogg', delete=False) as tmp:
                await reply.download_media(tmp.name); ogg_path = tmp.name
            wav_path = ogg_path.replace('.ogg', '.wav')
            audio = AudioSegment.from_file(ogg_path, format="ogg"); audio.export(wav_path, format="wav")
            recognizer = sr.Recognizer()
            with sr.AudioFile(wav_path) as source: audio_data = recognizer.record(source)
            text = recognizer.recognize_google(audio_data, language="ru-RU")
            await event.reply(f"📝 Распознанный текст:\n{text}")
            log_command(event.sender_id, f".stt: {text}", source="Telegram", target_id=event.chat_id, result="ok")
        except Exception as e: await event.reply(f"❌ Ошибка распознавания: {e}")
        finally:
            if os.path.exists(ogg_path): os.unlink(ogg_path)
            if os.path.exists(wav_path): os.unlink(wav_path)

    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.shutdown$'))
    async def shutdown_cmd(event):
        if event.sender_id != (await client1.get_entity(OWNER_USERNAME)).id:
            await event.reply("❌ Только создатель может выключить бота."); return
        await event.reply("👋 Завершаю работу...")
        os._exit(0)

    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.restart$'))
    async def restart_cmd(event):
        if event.sender_id != (await client1.get_entity(OWNER_USERNAME)).id:
            await event.reply("❌ Только создатель может перезапустить бота."); return
        await event.reply("🔄 Перезапуск...")
        os._exit(1)

    @client_instance.on(events.NewMessage(incoming=True))
    async def afk_handler(event):
        if event.out or not event.is_private: return
        if str(event.sender_id) in afk_users:
            reason = afk_users[str(event.sender_id)]
            await event.reply(f"⏳ Пользователь отошёл: {reason}")

    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.afk(\s+(.*))?'))
    async def afk_set_cmd(event):
        reason = event.pattern_match.group(2).strip() if event.pattern_match.group(2) else "отошёл"
        afk_users[str(event.sender_id)] = reason; save_json(AFK_FILE, afk_users)
        await event.delete()
        await event.client.send_message(event.chat_id, f"⏳ Вы ушли в AFK: {reason}")
        await broadcast_state()

    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.unafk$'))
    async def unafk_cmd(event):
        if str(event.sender_id) in afk_users:
            del afk_users[str(event.sender_id)]; save_json(AFK_FILE, afk_users)
            await event.delete()
            await event.client.send_message(event.chat_id, "✅ Вы вернулись из AFK.")
            await broadcast_state()

    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.search\s+(.+)'))
    async def search_cmd(event):
        args = event.pattern_match.group(1).strip()
        await event.delete()
        parts = args.split(maxsplit=1)
        engine = 'duck'
        query = args
        if parts[0] in ('yandex', 'duck', 'google'):
            engine = parts[0]
            query = parts[1] if len(parts) > 1 else ''
        if not query:
            await event.client.send_message(event.chat_id, "Введите запрос после названия поисковика.")
            return
        try:
            if engine == 'yandex':
                results = yandex_search(query)
            elif engine == 'google':
                results = ["Google поиск недоступен, используйте yandex или duck"]
            else:
                with DDGS() as ddgs:
                    results = [r['href'] for r in ddgs.text(query, max_results=5)]
            if results and not results[0].startswith('Ошибка'):
                text = f"🔎 Результаты ({engine}): {query}\n" + "\n".join(results)
            elif results and results[0].startswith('Ошибка'):
                text = f"❌ {results[0]}"
            else:
                text = "Ничего не найдено."
        except Exception as e:
            text = f"❌ Ошибка: {e}"
        await event.client.send_message(event.chat_id, text)

    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.recover(?:\s+(\d+))?'))
    async def recover_cmd(event):
        num = int(event.pattern_match.group(1)) if event.pattern_match.group(1) else 5
        cid = event.chat_id
        msgs = deleted_messages.get(cid, [])
        if not msgs:
            await event.reply("Нет удалённых сообщений.")
            return
        recent = msgs[-num:]
        text = "📝 **Последние удалённые сообщения:**\n" + "\n".join(f"• {m}" for m in recent)
        await event.client.send_message(event.chat_id, text)
        await event.delete()

    @client_instance.on(events.NewMessage(incoming=True))
    async def filter_handler(event):
        if event.out: return
        chat_id = str(event.chat_id)
        text = event.text or ""
        for word in blacklist:
            if word.lower() in text.lower():
                try: await event.delete()
                except: pass
                return
        if chat_id in filters:
            for rule in filters[chat_id]:
                if rule["word"].lower() in text.lower():
                    if rule["action"] == "delete":
                        try: await event.delete()
                        except: pass
                    elif rule["action"] == "mute":
                        muted_chats.add(event.chat_id); save_state(); await broadcast_state()
                    return

    @client_instance.on(events.NewMessage(incoming=True))
    async def auto_read_handler(event):
        if getattr(client_instance, 'auto_read', False) and not event.out:
            await event.mark_read()

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
                add_log("AUTH", "Вход одобрен через бота")
            elif token in pending_registrations:
                info = pending_registrations.pop(token)
                password = uuid.uuid4().hex[:8]
                admins[info["name"]] = {"password": hash_password(password), "role": info["role"]}
                save_admins()
                await event.edit(f"✅ Пользователь {info['name']} добавлен как {info['role']}. Пароль: {password}", buttons=None)
                add_log("AUTH", f"Новый пользователь {info['name']} зарегистрирован")
        elif data.startswith("reject:"):
            token = data.split(":")[1]
            auth_tokens.pop(token, None)
            if token in pending_registrations:
                pending_registrations.pop(token)
            await event.edit("🚫 Вход отклонён.", buttons=None)
            add_log("AUTH", "Вход отклонён")

    @bot.on(events.NewMessage(pattern=r'^/mute\s+(\S+)'))
    async def bot_mute(event):
        chat_id = int(event.pattern_match.group(1))
        muted_chats.add(chat_id); save_state()
        await event.reply("Чат заглушен.")
        add_log("CMD", f"Бот: мут чата {chat_id}")
        await broadcast_state(); await backup_state()

    @bot.on(events.NewMessage(pattern=r'^/unmute\s+(\S+)'))
    async def bot_unmute(event):
        chat_id = int(event.pattern_match.group(1))
        muted_chats.discard(chat_id); save_state()
        await event.reply("Чат размучен.")
        add_log("CMD", f"Бот: размут чата {chat_id}")
        await broadcast_state(); await backup_state()

    @bot.on(events.NewMessage(pattern=r'^/unmuteall'))
    async def bot_unmuteall(event):
        muted_chats.clear(); save_state()
        await event.reply("Все чаты размучены.")
        add_log("CMD", "Бот: сняты все муты")
        await broadcast_state(); await backup_state()

    @bot.on(events.NewMessage(pattern=r'^/autoreply\s+(on|off)'))
    async def bot_autoreply(event):
        state = event.pattern_match.group(1)
        auto_reply_global['enabled'] = (state == 'on')
        await event.reply(f"Автоответчик {'включён' if state == 'on' else 'выключен'}.")
        add_log("CMD", f"Бот: автоответчик {state}")
        await broadcast_state(); await backup_state()

    @bot.on(events.NewMessage(pattern=r'^/status'))
    async def bot_status(event):
        await event.reply(f"Активных мутов: {len(muted_chats)}\nAFK: {len(afk_users)}\nАвтоответчик: {'включён' if auto_reply_global['enabled'] else 'выключен'}")

# ---------- Веб-обработчики ----------
async def check_auth(request):
    auth = request.headers.get("Authorization")
    if auth and auth.startswith("Basic "):
        credentials = base64.b64decode(auth[6:]).decode()
        user, pwd = credentials.split(":", 1)
        if user in admins and admins[user]["password"] == hash_password(pwd): return user
    token = request.cookies.get("auth_token")
    if token and (auth_tokens.get(token) == True or token == "password_ok"):
        return "admin"
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

async def login_page(request):
    return web.Response(text=HTML_LOGIN, content_type="text/html")

async def auth_login(request):
    data = await request.post()
    username = data.get("username", ""); password = data.get("password", "")
    if username in admins and admins[username]["password"] == hash_password(password):
        auth_tokens["password_ok"] = True
        resp = web.HTTPFound("/dashboard")
        resp.set_cookie("auth_token", "password_ok")
        add_log("AUTH", f"Вход в панель: {username}")
        return resp
    return web.HTTPFound("/login?error=1")

async def logout(request):
    resp = web.HTTPFound("/login"); resp.del_cookie("auth_token"); resp.del_cookie("invite_token")
    auth_tokens.pop("password_ok", None)
    return resp

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

async def add_admin(request):
    user = await check_auth(request)
    if user != "admin" and (user not in admins or admins[user]["role"] != "admin"): raise web.HTTPFound("/dashboard?error=Только+главный+админ")
    data = await request.post()
    new_user = data.get("username","").strip(); new_pass = data.get("password","").strip(); role = data.get("role","readonly")
    if not new_user or not new_pass: raise web.HTTPFound("/dashboard?error=Логин+и+пароль+обязательны")
    admins[new_user] = {"password": hash_password(new_pass), "role": role}; save_admins(); await broadcast_state()
    raise web.HTTPFound("/dashboard?msg=Пользователь+добавлен")

async def delete_admin(request):
    user = await check_auth(request)
    if user != "admin" and (user not in admins or admins[user]["role"] != "admin"): raise web.HTTPFound("/dashboard?error=Только+главный+админ")
    del_user = request.query.get("user","")
    if del_user == ADMIN_USER: raise web.HTTPFound("/dashboard?error=Нельзя+удалить+главного+админа")
    if del_user in admins: del admins[del_user]; save_admins(); await broadcast_state()
    raise web.HTTPFound("/dashboard?msg=Пользователь+удалён")

async def add_account(request):
    user = await check_auth(request)
    if user == "readonly": raise web.HTTPFound("/dashboard?error=Недостаточно+прав")
    data = await request.post()
    name = data.get("name","").strip(); sess = data.get("session_string","").strip()
    if not name or not sess: raise web.HTTPFound("/dashboard?error=Заполните+все+поля")
    if name in extra_clients: raise web.HTTPFound("/dashboard?error=Такое+имя+уже+есть")
    try:
        client = TelegramClient(StringSession(sess), API_ID, API_HASH)
        await client.start()
        extra_clients[name] = {"session": sess, "client": client}
        register_handlers(client)
        await broadcast_state(); await backup_state()
    except Exception as e: raise web.HTTPFound(f"/dashboard?error=Не+удалось+подключить+аккаунт:+{str(e)}")
    raise web.HTTPFound("/dashboard?msg=Аккаунт+подключён")

async def remove_account(request):
    user = await check_auth(request)
    if user == "readonly": raise web.HTTPFound("/dashboard?error=Недостаточно+прав")
    name = request.query.get("name","")
    if name in extra_clients:
        await extra_clients[name]["client"].disconnect()
        del extra_clients[name]
        await broadcast_state(); await backup_state()
    raise web.HTTPFound("/dashboard?msg=Аккаунт+отключён")

async def unmute_handler(request):
    user = await check_auth(request)
    if user == "readonly": raise web.HTTPFound("/dashboard?error=Недостаточно+прав")
    chat_id = int(request.query["chat_id"]); muted_chats.discard(chat_id); save_state()
    account = request.query.get("account", active_account)
    if account == "2" and client2: client = client2
    elif account in extra_clients: client = extra_clients[account]["client"]
    else: client = client1
    try: await client.send_message(chat_id, "🔊 Администратор размутил этот чат!")
    except: pass
    await broadcast_state(); await backup_state()
    return web.Response(text="OK")

async def remove_protected(request):
    user = await check_auth(request)
    if user == "readonly": raise web.HTTPFound("/dashboard?error=Недостаточно+прав")
    user_id = int(request.query["user_id"]); me1 = await client1.get_me(); me2_id = (await client2.get_me()).id if client2 else None
    try:
        owner = await client1.get_entity(OWNER_USERNAME)
        if user_id == owner.id: raise web.HTTPFound("/dashboard?error=Нельзя+удалить+создателя")
    except: pass
    if user_id != me1.id and user_id != me2_id:
        protected_users.discard(user_id); save_state()
        await broadcast_state(); await backup_state()
        raise web.HTTPFound("/dashboard?msg=Пользователь+удалён+из+защиты")
    raise web.HTTPFound("/dashboard?error=Нельзя+удалить+владельца")

async def send_cmd(request):
    user = await check_auth(request)
    if user == "readonly": raise web.HTTPFound("/dashboard?error=Недостаточно+прав")
    data = await request.post(); account = data.get("account", active_account); target = data.get("target","").strip() or 'me'
    command = data.get("command","").strip(); args = data.get("args","").strip()
    if account == "2" and client2: client = client2
    elif account in extra_clients: client = extra_clients[account]["client"]
    else: client = client1
    try:
        if command == ".mute":
            muted_chats.add(int(target)); save_state()
        elif command == ".unmute":
            muted_chats.discard(int(target)); save_state()
        elif command == ".spam":
            parts = args.split(maxsplit=1)
            if len(parts)==2:
                count = int(parts[0]); text = parts[1]
                if count <= 50:
                    for _ in range(count): await client.send_message(target, text); await asyncio.sleep(0.4)
        elif command == ".ping":
            start = time.time(); msg = await client.send_message(target, "🏓 Пинг...")
            elapsed = (time.time() - start) * 1000
            await msg.edit(f"🏓 Понг! {elapsed:.1f}ms")
        elif command == ".search":
            parts = args.split(maxsplit=1)
            engine = 'duck'
            query = args
            if parts[0] in ('yandex', 'duck', 'google'):
                engine = parts[0]
                query = parts[1] if len(parts) > 1 else ''
            if not query:
                raise web.HTTPFound("/dashboard?error=Укажите+поисковый+запрос")
            if engine == 'yandex':
                results = yandex_search(query)
            elif engine == 'google':
                results = ["Google недоступен"]
            else:
                with DDGS() as ddgs:
                    results = [r['href'] for r in ddgs.text(query, max_results=5)]
            if results:
                await client.send_message(target, "\n".join(results))
            else:
                await client.send_message(target, "Ничего не найдено.")
    except Exception as e:
        raise web.HTTPFound(f"/dashboard?error={str(e)}")
    await broadcast_state(); await backup_state()
    raise web.HTTPFound("/dashboard?msg=Команда+выполнена")

async def backup_now_handler(request):
    user = await check_auth(request)
    await backup_state()
    raise web.HTTPFound("/dashboard?msg=Бэкап+создан")

async def download_backup_enc(request):
    await check_auth(request)
    data = {"muted_chats": list(muted_chats), "protected_users": list(protected_users), "admins": admins, "auto_reply_global": auto_reply_global}
    encrypted = encrypt_data(json.dumps(data).encode())
    return web.Response(body=encrypted, content_type="application/octet-stream", headers={"Content-Disposition": "attachment; filename=backup.enc"})

async def download_backup_dec(request):
    await check_auth(request)
    data = {"muted_chats": list(muted_chats), "protected_users": list(protected_users), "admins": admins, "auto_reply_global": auto_reply_global}
    return web.Response(body=json.dumps(data, indent=2), content_type="application/json", headers={"Content-Disposition": "attachment; filename=backup.json"})

async def websocket_handler(request):
    token = request.cookies.get("auth_token"); invite_token = request.cookies.get("invite_token")
    if not token and not invite_token: return web.Response(status=401)
    if token and token != "password_ok" and auth_tokens.get(token) != True: return web.Response(status=401)
    if invite_token and invite_token not in invites: return web.Response(status=401)
    ws = web.WebSocketResponse(); await ws.prepare(request); ws_clients.add(ws)
    initial = {"muted_chats": list(muted_chats), "protected_users": list(protected_users), "history": command_history, "chat_names": await get_chat_names(), "user_names": await get_user_names(), "acc1_name": (await client1.get_me()).first_name or "Аккаунт 1", "acc2_name": ACC2_DISPLAY_NAME if ACC2_DISPLAY_NAME else (await client2.get_me()).first_name if client2 else None, "admins": list(admins.keys()), "extra_clients": list(extra_clients.keys()), "backup_history": backup_history[-20:], "backup_status": backup_status, "afk_users": afk_users, "notes": notes, "auto_reply_global": auto_reply_global, "active_account": active_account, "theme": theme, "filters": filters, "blacklist": blacklist, "schedule": schedule}
    await ws.send_str(json.dumps(initial, default=str, ensure_ascii=False))
    logs = log_buffer[-50:]
    await ws.send_str(json.dumps({"event": "logs_init", "logs": logs}, ensure_ascii=False))
    try:
        async for msg in ws: pass
    finally: ws_clients.discard(ws)
    return ws

async def guest_ws_handler(request):
    key = request.query.get("key","")
    if key != GUEST_KEY: return web.Response(status=403)
    ws = web.WebSocketResponse(); await ws.prepare(request)
    data = {"muted_chats": list(muted_chats), "protected_users": list(protected_users), "history": command_history, "chat_names": await get_chat_names(), "user_names": await get_user_names()}
    await ws.send_str(json.dumps(data, default=str, ensure_ascii=False))
    await ws.close(); return ws

# API
async def api_notes(request):
    if request.method == 'POST':
        data = await request.post()
        global notes; notes = data.get('notes', '')
        save_notes(); await broadcast_state()
    return web.Response(text="OK")

async def api_afk_remove(request):
    uid = request.query['uid']
    if uid in afk_users:
        del afk_users[uid]; save_json(AFK_FILE, afk_users); await broadcast_state()
    return web.Response(text="OK")

async def api_blacklist_add(request):
    data = await request.post()
    word = data.get('word','').strip()
    if word and word not in blacklist:
        blacklist.append(word); save_blacklist(); await broadcast_state()
    return web.Response(text="OK")

async def api_blacklist_remove(request):
    word = request.query.get('word','')
    if word in blacklist:
        blacklist.remove(word); save_blacklist(); await broadcast_state()
    return web.Response(text="OK")

async def api_filters_add(request):
    data = await request.post()
    chat = data.get('chat',''); word = data.get('word',''); action = data.get('action','delete')
    if chat and word:
        if chat not in filters: filters[chat] = []
        filters[chat].append({"word": word, "action": action})
        save_filters(); await broadcast_state()
    return web.Response(text="OK")

async def api_filters_remove(request):
    chat = request.query.get('chat',''); word = request.query.get('word','')
    if chat in filters:
        filters[chat] = [r for r in filters[chat] if r['word'] != word]
        if not filters[chat]: del filters[chat]
        save_filters(); await broadcast_state()
    return web.Response(text="OK")

async def api_schedule_add(request):
    data = await request.post()
    task = {"time": data.get('time',''), "account": data.get('account','1'), "target": data.get('target','me'), "command": data.get('command',''), "args": data.get('args','')}
    schedule.append(task); save_schedule(); await broadcast_state()
    return web.Response(text="OK")

async def api_schedule_delete(request):
    idx = int(request.query.get('idx', -1))
    if 0 <= idx < len(schedule):
        schedule.pop(idx); save_schedule(); await broadcast_state()
    return web.Response(text="OK")

async def api_active_account(request):
    data = await request.post()
    global active_account; active_account = data.get('account', '1')
    await broadcast_state()
    return web.Response(text="OK")

async def api_theme(request):
    data = await request.post()
    global theme; theme = data.get('theme', 'dark')
    await broadcast_state()
    return web.Response(text="OK")

async def api_mass_mute(request):
    chat_id = int(request.query['chat_id'])
    muted_chats.add(chat_id); save_state()
    await broadcast_state(); await backup_state()
    return web.Response(text="OK")

async def api_mass_unmute(request):
    chat_id = int(request.query['chat_id'])
    muted_chats.discard(chat_id); save_state()
    await broadcast_state(); await backup_state()
    return web.Response(text="OK")

async def api_unmute_all(request):
    muted_chats.clear(); save_state()
    try:
        owner = await client1.get_entity(OWNER_USERNAME)
        await client1.send_message(owner.id, "🔊 Все чаты размучены через веб-панель.")
    except: pass
    await broadcast_state(); await backup_state()
    return web.Response(text="OK")

async def api_toggle_autoreply(request):
    auto_reply_global['enabled'] = not auto_reply_global['enabled']
    try:
        owner = await client1.get_entity(OWNER_USERNAME)
        await client1.send_message(owner.id, f"🌐 Автоответчик {'включён' if auto_reply_global['enabled'] else 'выключен'} через веб-панель.")
    except: pass
    await broadcast_state(); await backup_state()
    return web.Response(text="OK")

# API для чатов
async def api_chats(request):
    user = await check_auth(request)
    account_id = request.query.get("account", active_account)
    client = client1
    if account_id == "2" and client2: client = client2
    elif account_id in extra_clients: client = extra_clients[account_id]["client"]
    dialogs = []
    try:
        async for d in client.iter_dialogs(limit=50):
            dialogs.append({
                "id": d.id,
                "name": d.name,
                "unread": d.unread_count,
                "last_message": d.message.text if d.message and d.message.text else "",
                "date": d.message.date.isoformat() if d.message and d.message.date else "",
                "pinned": d.pinned
            })
    except Exception as e:
        return web.json_response({"error": str(e)})
    return web.json_response(dialogs)

async def api_messages(request):
    user = await check_auth(request)
    account_id = request.query.get("account", active_account)
    chat_id = int(request.query["chat_id"])
    offset_id = int(request.query.get("offset_id", 0))
    client = client1
    if account_id == "2" and client2: client = client2
    elif account_id in extra_clients: client = extra_clients[account_id]["client"]
    messages = []
    try:
        async for msg in client.iter_messages(chat_id, limit=30, offset_id=offset_id):
            messages.append({
                "id": msg.id,
                "date": msg.date.isoformat(),
                "text": msg.text or "",
                "out": msg.out
            })
    except Exception as e:
        return web.json_response({"error": str(e)})
    return web.json_response(messages)

async def api_send_message(request):
    user = await check_auth(request)
    data = await request.post()
    account_id = data.get("account", active_account)
    chat_id = int(data.get("chat_id"))
    text = data.get("text", "")
    client = client1
    if account_id == "2" and client2: client = client2
    elif account_id in extra_clients: client = extra_clients[account_id]["client"]
    try:
        await client.send_message(chat_id, text, silent=True)
    except Exception as e:
        return web.json_response({"error": str(e)})
    return web.json_response({"ok": True})

app = web.Application()
app.router.add_get("/", lambda r: web.Response(text="OK"))
app.router.add_get("/login", login_page)
app.router.add_post("/auth/login", auth_login)
app.router.add_get("/logout", logout)
app.router.add_get("/auth/request_bot", request_bot_auth)
app.router.add_get("/auth/check_token", check_token)
app.router.add_get("/dashboard", dashboard)
app.router.add_get("/guest", guest_view)
app.router.add_get("/unmute", unmute_handler)
app.router.add_get("/remove_protected", remove_protected)
app.router.add_post("/send_cmd", send_cmd)
app.router.add_post("/add_admin", add_admin)
app.router.add_get("/delete_admin", delete_admin)
app.router.add_post("/add_account", add_account)
app.router.add_get("/remove_account", remove_account)
app.router.add_get("/backup_now", backup_now_handler)
app.router.add_get("/download/backup/enc", download_backup_enc)
app.router.add_get("/download/backup/dec", download_backup_dec)
app.router.add_get("/ws", websocket_handler)
app.router.add_get("/guest-ws", guest_ws_handler)
app.router.add_post("/api/notes", api_notes)
app.router.add_get("/api/afk/remove", api_afk_remove)
app.router.add_post("/api/blacklist/add", api_blacklist_add)
app.router.add_get("/api/blacklist/remove", api_blacklist_remove)
app.router.add_post("/api/filters/add", api_filters_add)
app.router.add_get("/api/filters/remove", api_filters_remove)
app.router.add_post("/api/schedule/add", api_schedule_add)
app.router.add_get("/api/schedule/delete", api_schedule_delete)
app.router.add_post("/api/active_account", api_active_account)
app.router.add_post("/api/theme", api_theme)
app.router.add_get("/api/mass_mute", api_mass_mute)
app.router.add_get("/api/mass_unmute", api_mass_unmute)
app.router.add_get("/api/unmute_all", api_unmute_all)
app.router.add_get("/api/toggle_autoreply", api_toggle_autoreply)
app.router.add_get("/api/chats", api_chats)
app.router.add_get("/api/messages", api_messages)
app.router.add_post("/api/send_message", api_send_message)

async def start_web_server():
    runner = web.AppRunner(app); await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT); await site.start()
    add_log("INFO", f"🔐 Панель управления запущена на порту {PORT}")
    while True: await asyncio.sleep(3600)

def shutdown_handler(signum, frame):
    add_log("INFO", "🔻 Завершение работы, сохраняю состояние локально...")
    data = {"muted_chats": list(muted_chats), "protected_users": list(protected_users), "admins": admins, "extra_clients": {k: {"session": v["session"]} for k, v in extra_clients.items()}, "auto_reply_global": auto_reply_global, "auto_reply_chats": auto_reply_chats}
    save_json(BACKUP_LOCAL, data)
    os._exit(0)

async def main():
    global http_session, client2
    http_session = ClientSession()
    await client1.start(); add_log("INFO", "✅ Аккаунт 1 запущен")
    if client2:
        try: await client2.start(); add_log("INFO", "✅ Аккаунт 2 запущен")
        except Exception as e: add_log("ERROR", f"Не удалось запустить второй аккаунт: {e}"); client2 = None
    if bot:
        while True:
            try: await bot.start(bot_token=BOT_TOKEN); add_log("INFO", "🤖 Бот авторизации запущен"); break
            except FloodWaitError as e: add_log("WARN", f"FloodWait: ждём {e.seconds} сек"); await asyncio.sleep(e.seconds)
            except Exception as e: add_log("ERROR", f"Не удалось запустить бота: {e}"); break
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
