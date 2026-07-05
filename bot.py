import os, asyncio, json, time, base64, uuid, random, io, urllib.parse, hashlib, tempfile, signal
from pathlib import Path
from datetime import datetime, timedelta
from telethon import TelegramClient, events, Button
from telethon.errors import FloodWaitError
from telethon.sessions import StringSession
from deep_translator import GoogleTranslator
from aiohttp import web, WSMsgType, ClientSession
import qrcode
from gtts import gTTS
import speech_recognition as sr
from pydub import AudioSegment
AudioSegment.converter = "/opt/render/project/src/ffmpeg"

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
BACKUP_CHAT = os.environ.get("BACKUP_CHAT", "@websats_bot")
DATA_FILE = Path("userbot_data.json")
LOG_FILE = Path("command_history.json")
WARN_FILE = Path("warns.json")
AFK_FILE = Path("afk.json")
REMIND_FILE = Path("reminds.json")
INVITES_FILE = Path("invites.json")
ADMINS_FILE = Path("admins.json")

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
ws_clients = set()
http_session: ClientSession = None
warns = {}
afk_users = {}
reminders = []
invites = {}
admins = {}
extra_clients = {}

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

warns = load_json(WARN_FILE, {})
afk_users = load_json(AFK_FILE, {})
reminders = load_json(REMIND_FILE, [])
load_admins(); load_invites(); load_state(); load_history()

async def backup_state():
    data = {"muted_chats": list(muted_chats), "protected_users": list(protected_users), "admins": admins, "extra_clients": {k: {"session": v["session"]} for k, v in extra_clients.items()}, "auto_reply_global": auto_reply_global, "auto_reply_chats": auto_reply_chats}
    text = json.dumps(data, ensure_ascii=False)

    # Пробуем через бота в BACKUP_CHAT
    sent = False
    if bot and bot.is_connected():
        try:
            async for msg in bot.iter_messages(BACKUP_CHAT, from_user='me', limit=10):
                await msg.delete()
            await bot.send_message(BACKUP_CHAT, text)
            sent = True
        except Exception as e:
            print(f"⚠️ Бэкап через бота не удался: {e}")

    # Если не отправлено — в избранное основного аккаунта
    if not sent:
        try:
            async for msg in client1.iter_messages('me', from_user='me', limit=10):
                if msg.text and msg.text.startswith('{'):
                    await msg.delete()
            await client1.send_message('me', text)
        except Exception as e:
            print(f"⚠️ Не удалось сохранить бэкап в Избранное: {e}")

async def restore_state():
    data = None
    # Сначала ищем в BACKUP_CHAT (через бота)
    if bot and bot.is_connected():
        try:
            async for msg in bot.iter_messages(BACKUP_CHAT, from_user='me', limit=1):
                if msg.text: data = json.loads(msg.text); break
        except: pass
    # Если не нашли — ищем в избранном client1
    if not data:
        try:
            async for msg in client1.iter_messages('me', from_user='me', limit=1):
                if msg.text and msg.text.startswith('{'): data = json.loads(msg.text); break
        except: pass
    if not data: return

    global muted_chats, protected_users, admins, extra_clients, auto_reply_global, auto_reply_chats
    muted_chats = set(data.get("muted_chats", []))
    protected_users = set(data.get("protected_users", []))
    admins = data.get("admins", {})
    auto_reply_global = data.get("auto_reply_global", auto_reply_global)
    auto_reply_chats = data.get("auto_reply_chats", {})
    for name, info in data.get("extra_clients", {}).items():
        sess = info.get("session")
        if sess:
            try:
                client = TelegramClient(StringSession(sess), API_ID, API_HASH)
                await client.start()
                extra_clients[name] = {"session": sess, "client": client}
            except Exception as e: print(f"⚠️ Не удалось подключить {name}: {e}")

async def backup_loop():
    while True:
        await asyncio.sleep(1800)
        await backup_state()

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
    data = {"muted_chats": list(muted_chats), "protected_users": list(protected_users), "history": command_history, "chat_names": await get_chat_names(), "user_names": await get_user_names(), "acc1_name": (await client1.get_me()).first_name or "Аккаунт 1", "acc2_name": acc2_name, "invites": invites, "admins": list(admins.keys()), "extra_clients": list(extra_clients.keys()), "owner_id": owner_id}
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
        try:
            me2 = await client2.get_me(); protected_users.add(me2.id)
        except Exception as e: print(f"⚠️ Не удалось получить данные второго аккаунта: {e}")
    try:
        owner = await client1.get_entity(OWNER_USERNAME)
        protected_users.add(owner.id)
    except Exception as e: print(f"⚠️ Не удалось найти владельца {OWNER_USERNAME}: {e}")
    save_state(); await broadcast_state()
    await backup_state()

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
        await broadcast_state()
        await backup_state()

    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.unmute$'))
    async def unmute_cmd(event):
        muted_chats.discard(event.chat_id); save_state(); await event.delete()
        user_name = await resolve_name(event.sender_id); target_name = await resolve_chat_name(event.chat_id)
        log_command(event.sender_id, ".unmute", source="Telegram", target_id=event.chat_id, user_name=user_name, target_name=target_name, result="ok")
        await event.client.send_message(event.chat_id, "🔊 <b>Мут снят.</b> Сообщения больше не удаляются.", parse_mode='html')
        await broadcast_state()
        await backup_state()

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
        await broadcast_state()
        await backup_state()

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
        for _ in range(count):
            await event.client.send_message(event.chat_id, text)
            await asyncio.sleep(0.4)

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
        if hasattr(chat, 'broadcast') and chat.broadcast:
            await event.reply("❌ Команда недоступна для каналов."); return
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
        if hasattr(chat, 'broadcast') and chat.broadcast:
            await event.reply("❌ В канале невозможно очистить сообщения."); return
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
            "<b>.mute</b> — заглушить чат\n"
            "<b>.unmute</b> — снять мут\n"
            "<b>.clearall</b> — удалить все сообщения в чате\n"
            "<b>.avto</b> / .avto all / .unavto — автоответчик\n"
            "<b>.spam N текст</b> — повторить N раз\n"
            "<b>.ping</b> — пинг\n"
            "<b>.purge [N]</b> — удалить свои последние N сообщений\n"
            "<b>.save текст</b> / .get — заметки\n"
            "<b>.stats</b> — статистика чата\n"
            "<b>.tr код текст</b> — перевод\n"
            "<b>.addfriend</b> / .delfriend / .listfriends\n"
            "<b>.history</b> — история последних команд\n"
            "<b>.stt</b> — распознать голосовое сообщение (реплай)\n"
            "<b>.qr текст</b> — QR-код\n"
            "<b>.weather город</b> — погода\n"
            "<b>.tts текст</b> — голосовое сообщение\n"
            "<b>.sticker</b> — случайный стикер\n"
            "<b>.shutdown</b> — выключить бота (только создатель)\n"
            "<b>.restart</b> — перезапустить бота (только создатель)\n"
            "<b>.help</b> — это сообщение"
        )
        await event.client.send_message(event.chat_id, text, parse_mode='html')

    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.qr\s+(.*)'))
    async def qr_cmd(event):
        text = event.pattern_match.group(1); await event.delete()
        img = qrcode.make(text); buf = io.BytesIO(); img.save(buf, format='PNG'); buf.seek(0)
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

    @client_instance.on(events.NewMessage(incoming=True))
    async def auto_read_handler(event):
        if getattr(client_instance, 'auto_read', False) and not event.out:
            await event.mark_read()

register_handlers(client1)
if client2: register_handlers(client2)
for client_info in extra_clients.values():
    register_handlers(client_info["client"])

if bot:
    @bot.on(events.CallbackQuery)
    async def auth_callback(event):
        data = event.data.decode()
        if data.startswith("approve:"):
            token = data.split(":")[1]
            if token in auth_tokens: auth_tokens[token] = True; await event.edit("✅ Вход одобрен.", buttons=None)
        elif data.startswith("reject:"):
            token = data.split(":")[1]; auth_tokens.pop(token, None); await event.edit("🚫 Вход отклонён.", buttons=None)

HTML_LOGIN = """<html><head><meta charset="utf-8"><title>Вход</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@300;600&display=swap');
* { box-sizing: border-box; }
body { margin: 0; height: 100vh; display: flex; align-items: center; justify-content: center; background: linear-gradient(45deg, #0a0a0a, #1a1a2e, #0a0a0a); background-size: 400% 400%; animation: gradientBG 10s ease infinite; font-family: 'Montserrat', sans-serif; }
@keyframes gradientBG { 0%{background-position:0% 50%} 50%{background-position:100% 50%} 100%{background-position:0% 50%} }
.card { background: rgba(20,20,30,0.9); backdrop-filter: blur(10px); border: 1px solid rgba(233,69,96,0.3); border-radius: 16px; padding: 2rem; width: 320px; box-shadow: 0 0 30px rgba(233,69,96,0.3), 0 0 60px rgba(233,69,96,0.1); animation: pulse 2s infinite; }
@keyframes pulse { 0% { box-shadow: 0 0 30px rgba(233,69,96,0.3); } 50% { box-shadow: 0 0 50px rgba(233,69,96,0.6); } 100% { box-shadow: 0 0 30px rgba(233,69,96,0.3); } }
h2 { color: #e94560; text-align: center; font-weight: 600; margin-top: 0; text-shadow: 0 0 10px rgba(233,69,96,0.5); }
input { width: 100%; padding: 0.7rem; margin: 0.5rem 0; border: none; border-radius: 8px; background: #1a1a2e; color: #e0e0e0; font-size: 1rem; border: 1px solid rgba(233,69,96,0.2); transition: 0.3s; }
input:focus { border-color: #e94560; box-shadow: 0 0 10px rgba(233,69,96,0.5); outline: none; }
button { width: 100%; padding: 0.7rem; margin-top: 1rem; border: none; border-radius: 8px; background: #e94560; color: white; font-weight: 600; cursor: pointer; transition: 0.3s; box-shadow: 0 0 15px rgba(233,69,96,0.4); }
button:hover { background: #c93750; transform: scale(1.02); box-shadow: 0 0 25px rgba(233,69,96,0.6); }
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
</script>
</body></html>"""

HTML_DASHBOARD = """<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Userbot Panel</title>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@300;400;600&display=swap');
    * { box-sizing: border-box; }
    body { margin: 0; background: linear-gradient(135deg, #0a0a0a, #1a1a2e, #0a0a0a); background-size: 400% 400%; animation: gradientBG 15s ease infinite; color: #e0e0e0; font-family: 'Montserrat', sans-serif; }
    @keyframes gradientBG { 0%{background-position:0% 50%} 50%{background-position:100% 50%} 100%{background-position:0% 50%} }
    .navbar { display: flex; align-items: center; justify-content: space-between; background: rgba(19,19,31,0.9); backdrop-filter: blur(10px); padding: 0.8rem 2rem; border-bottom: 1px solid rgba(233,69,96,0.3); box-shadow: 0 0 20px rgba(233,69,96,0.2); }
    .navbar-brand { font-size: 1.5rem; font-weight: 600; color: #e94560; text-decoration: none; text-shadow: 0 0 10px rgba(233,69,96,0.5); }
    .nav-info { display: flex; gap: 1.5rem; align-items: center; }
    .nav-info span { opacity: 0.8; }
    .logout-btn { background: rgba(233,69,96,0.2); padding: 0.4rem 0.8rem; border-radius: 6px; color: #e94560; text-decoration: none; font-size: 0.9rem; transition: 0.3s; }
    .logout-btn:hover { background: rgba(233,69,96,0.4); box-shadow: 0 0 10px rgba(233,69,96,0.3); }
    .tabs { display: flex; gap: 0.5rem; padding: 1rem 2rem; background: rgba(19,19,31,0.8); border-bottom: 1px solid rgba(255,255,255,0.05); overflow-x: auto; }
    .tabs button { background: transparent; color: #aaa; border: none; padding: 0.5rem 1rem; border-radius: 8px; font-size: 0.9rem; cursor: pointer; transition: 0.2s; }
    .tabs button.active { background: #e94560; color: white; box-shadow: 0 0 15px rgba(233,69,96,0.5); }
    .tabs button:hover:not(.active) { color: #e94560; }
    .content { padding: 2rem; }
    .tab-pane { display: none; }
    .tab-pane.active { display: block; }
    .list-group-item { background: rgba(19,19,31,0.8); border: 1px solid rgba(255,255,255,0.05); border-radius: 8px; padding: 0.7rem 1rem; margin-bottom: 0.5rem; display: flex; justify-content: space-between; align-items: center; transition: 0.3s; }
    .list-group-item:hover { border-color: rgba(233,69,96,0.3); box-shadow: 0 0 10px rgba(233,69,96,0.2); }
    .btn-custom { background: #e94560; color: white; border: none; padding: 0.4rem 0.8rem; border-radius: 6px; cursor: pointer; font-size: 0.8rem; transition: 0.3s; box-shadow: 0 0 10px rgba(233,69,96,0.3); }
    .btn-custom:hover { background: #c93750; box-shadow: 0 0 15px rgba(233,69,96,0.5); }
    table { width: 100%; border-collapse: collapse; margin-top: 1rem; }
    th, td { padding: 0.6rem; border-bottom: 1px solid rgba(255,255,255,0.05); text-align: left; }
    th { color: #e94560; font-weight: 600; }
    .badge { padding: 0.2rem 0.5rem; border-radius: 4px; font-size: 0.75rem; }
    .badge-ok { background: #238636; }
    .badge-error { background: #da3633; }
    .notification { position: fixed; top: 1rem; right: 1rem; background: #238636; color: white; padding: 0.8rem 1.2rem; border-radius: 8px; display: none; z-index: 999; box-shadow: 0 0 15px rgba(35,134,54,0.4); }
    .notification.error { background: #da3633; box-shadow: 0 0 15px rgba(218,54,51,0.4); }
    input, select { background: #13131f; color: white; border: 1px solid #30363d; border-radius: 6px; padding: 0.5rem; transition: 0.3s; }
    input:focus, select:focus { border-color: #e94560; box-shadow: 0 0 10px rgba(233,69,96,0.3); outline: none; }
    @media (max-width: 768px) { .tabs { flex-wrap: nowrap; } }
  </style>
</head>
<body>
  <nav class="navbar">
    <a class="navbar-brand" href="#">🤖 Userbot Panel</a>
    <div class="nav-info">
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
  </div>
  <div class="content">
    <div id="muted" class="tab-pane active"><div id="mutedList"></div></div>
    <div id="protected" class="tab-pane"><div id="protectedList"></div></div>
    <div id="commands" class="tab-pane">
      <form action="/send_cmd" method="post" style="display: grid; gap: 0.8rem; max-width: 500px;">
        <select name="account" id="accountSelect"></select>
        <input name="target" placeholder="Чат (username или ID, пусто = Избранное)">
        <select name="command" id="cmdSelect">
          <option value=".mute">.mute</option><option value=".unmute">.unmute</option><option value=".spam">.spam</option><option value=".ping">.ping</option><option value=".purge">.purge</option><option value=".clearall">.clearall</option><option value=".stats">.stats</option><option value=".tr">.tr</option><option value=".avto">.avto</option><option value=".help">.help</option>
        </select>
        <input name="args" placeholder="Аргументы">
        <button type="submit" class="btn-custom" style="padding:0.6rem;">Отправить</button>
      </form>
    </div>
    <div id="history" class="tab-pane">
      <div style="margin-bottom:0.5rem;">
        <select id="accountFilter">
          <option value="all">Все</option><option value="acc1">Акк1</option><option value="acc2">Акк2</option>
        </select>
        <button class="btn-custom" onclick="toggleAllHistory()">Показать все</button>
      </div>
      <table><thead><tr><th>Время</th><th>Источник</th><th>Пользователь</th><th>Команда</th><th>Цель</th><th>Рез.</th></tr></thead><tbody id="historyBody"></tbody></table>
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
        <input name="name" placeholder="Имя аккаунта (для отображения)" required>
        <textarea name="session_string" placeholder="SESSION_STRING" required style="height:100px;"></textarea>
        <button type="submit" class="btn-custom">Подключить</button>
      </form>
      <div id="extraAccountsList" style="margin-top:1rem;"></div>
    </div>
    <div id="backup" class="tab-pane">
      <button class="btn-custom" onclick="createBackup()" style="margin-bottom:1rem;">Создать бэкап сейчас</button>
      <h5>📦 Состояние из последнего бэкапа</h5>
      <div id="backupMutedList"></div>
      <h5 style="margin-top:1rem;">🛡 Защищённые</h5>
      <div id="backupProtectedList"></div>
      <h5 style="margin-top:1rem;">👤 Дополнительные аккаунты</h5>
      <div id="backupExtraAccounts"></div>
    </div>
  </div>
  <div id="notification" class="notification"></div>

  <script>
    let ws, fullHistory=[], acc1Name="Аккаунт 1", acc2Name="Аккаунт 2", showAllHistory=false, extraAccounts=[];
    const MAX_VISIBLE=20;

    function showNotification(text, isError=false) {
      const n = document.getElementById('notification');
      n.textContent = text; n.className = 'notification' + (isError ? ' error' : ''); n.style.display='block';
      setTimeout(() => n.style.display='none', 4000);
    }

    window.addEventListener('load', () => {
      const params = new URLSearchParams(location.search);
      if (params.has('msg')) showNotification(params.get('msg'));
      else if (params.has('error')) showNotification(params.get('error'), true);
      window.history.replaceState({}, document.title, location.pathname);
      connectWS();
    });

    function connectWS() {
      ws = new WebSocket('wss://' + location.host + '/ws');
      ws.onmessage = e => updateUI(JSON.parse(e.data));
      ws.onclose = () => setTimeout(connectWS, 3000);
    }

    function updateUI(data) {
      acc1Name = data.acc1_name || 'Аккаунт 1'; acc2Name = data.acc2_name;
      extraAccounts = data.extra_clients || [];
      let sel = document.getElementById('accountSelect');
      sel.innerHTML = ''; sel.add(new Option(acc1Name,'1'));
      if (acc2Name) sel.add(new Option(acc2Name,'2'));
      extraAccounts.forEach(name => sel.add(new Option(name, name)));
      let filter = document.getElementById('accountFilter');
      filter.options[0].text = 'Все'; filter.options[1].text = acc1Name;
      if (acc2Name) filter.options[2].text = acc2Name;

      fullHistory = data.history || [];
      renderHistory();

      let mutedHtml = '';
      for (let id in data.chat_names) mutedHtml += `<div class="list-group-item">${data.chat_names[id]} <button class="btn-custom" onclick="unmuteChat(${id})">Размутить</button></div>`;
      document.getElementById('mutedList').innerHTML = mutedHtml || 'Нет чатов';
      document.getElementById('backupMutedList').innerHTML = mutedHtml || 'Нет чатов';

      let protectedHtml = '';
      for (let id in data.user_names) protectedHtml += `<div class="list-group-item">${data.user_names[id]}</div>`;
      document.getElementById('protectedList').innerHTML = protectedHtml || 'Нет';
      document.getElementById('backupProtectedList').innerHTML = protectedHtml || 'Нет';

      let adminsHtml = '';
      if (data.admins) data.admins.forEach(user => adminsHtml += `<div class="list-group-item">${user} <a href="/delete_admin?user=${user}" class="btn-custom">Удалить</a></div>`);
      document.getElementById('adminsList').innerHTML = adminsHtml || 'Нет админов';

      let extraHtml = '';
      extraAccounts.forEach(name => extraHtml += `<div class="list-group-item">${name} <a href="/remove_account?name=${name}" class="btn-custom">Отключить</a></div>`);
      document.getElementById('extraAccountsList').innerHTML = extraHtml || 'Нет дополнительных аккаунтов';
      document.getElementById('backupExtraAccounts').innerHTML = extraHtml || 'Нет дополнительных аккаунтов';
    }

    async function unmuteChat(id) {
      const btn = event.target;
      btn.disabled = true;
      btn.textContent = '⏳';
      try {
        await fetch('/unmute?chat_id='+id+'&account='+document.querySelector('select[name="account"]').value);
        showNotification('Чат размучен');
        document.getElementById('mutedList').querySelector(`button[onclick="unmuteChat(${id})"]`).closest('.list-group-item').remove();
      } catch(e) {
        showNotification('Ошибка при размуте', true);
        btn.disabled = false;
        btn.textContent = 'Размутить';
      }
    }

    async function createBackup() {
      try {
        await fetch('/backup_now');
        showNotification('Бэкап создан');
      } catch(e) {
        showNotification('Ошибка создания бэкапа', true);
      }
    }

    function renderHistory() {
      let filter = document.getElementById('accountFilter').value;
      let filtered = fullHistory;
      if (filter==='acc1') filtered = fullHistory.filter(e => e.user_name===acc1Name);
      else if (filter==='acc2') filtered = fullHistory.filter(e => e.user_name===acc2Name);
      if (!showAllHistory) filtered = filtered.slice(-MAX_VISIBLE);
      let html = '';
      filtered.forEach(e => html += `<tr><td>${e.time.substr(11,8)}</td><td>${e.source}</td><td>${e.user_name}</td><td>${e.command}</td><td>${e.target_name||''}</td><td><span class="badge ${e.result==='ok'?'badge-ok':'badge-error'}">${e.result||''}</span></td></tr>`);
      document.getElementById('historyBody').innerHTML = html || '<tr><td colspan="6">Нет записей</td></tr>';
    }

    function toggleAllHistory() { showAllHistory=!showAllHistory; document.querySelector('#history button').textContent = showAllHistory ? 'Последние 20' : 'Показать все'; renderHistory(); }

    document.querySelectorAll('.tabs button').forEach(btn => btn.addEventListener('click', function() {
      document.querySelectorAll('.tabs button').forEach(b => b.classList.remove('active'));
      this.classList.add('active');
      let tabId = this.dataset.tab;
      document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
      document.getElementById(tabId).classList.add('active');
      if (tabId==='history') renderHistory();
    }));
  </script>
</body>
</html>"""

HTML_GUEST = """<html><head><meta charset="utf-8"><title>Гостевой просмотр</title>
<style>body { background: #0a0a0a; color: #e0e0e0; font-family: sans-serif; padding: 20px; } ul { list-style: none; }</style>
</head><body><h1>Состояние бота</h1><div id="content"></div>
<script>
let ws = new WebSocket('wss://' + location.host + '/guest-ws?key=' + (new URL(location)).searchParams.get('key'));
ws.onmessage = function(event) {
  const data = JSON.parse(event.data);
  let html = '<h3>Чаты в муте:</h3><ul>';
  for (let id in data.chat_names) html += '<li>' + data.chat_names[id] + '</li>';
  html += '</ul><h3>Защищённые:</h3><ul>';
  for (let id in data.user_names) html += '<li>' + data.user_names[id] + '</li>';
  html += '</ul><h3>История:</h3><table border="1" cellpadding="4"><tr><th>Время</th><th>Источник</th><th>Пользователь</th><th>Команда</th><th>Цель</th></tr>';
  data.history.forEach(e => { html += `<tr><td>${e.time.substr(11,8)}</td><td>${e.source}</td><td>${e.user_name}</td><td>${e.command}</td><td>${e.target_name||''}</td></tr>`; });
  html += '</table>';
  document.getElementById('content').innerHTML = html;
};
</script>
</body></html>"""

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
    return web.Response(text=HTML_DASHBOARD.replace("{user}", user), content_type="text/html")

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
    if not bot: return web.json_response({"error": "Бот не настроен"})
    token = str(uuid.uuid4()); auth_tokens[token] = "pending"
    me1 = await client1.get_me()
    try:
        await bot.send_message(me1.id, "🔐 <b>Запрос на вход</b>\nРазрешить?", buttons=[[Button.inline("✅ Принять", f"approve:{token}")], [Button.inline("❌ Отклонить", f"reject:{token}")]], parse_mode='html')
        return web.json_response({"token": token})
    except Exception as e:
        auth_tokens.pop(token, None); return web.json_response({"error": str(e)})

async def check_token(request):
    token = request.query.get("token")
    if token and token in auth_tokens: return web.json_response({"approved": auth_tokens[token] == True})
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
        await broadcast_state()
        await backup_state()
    except Exception as e: raise web.HTTPFound(f"/dashboard?error=Не+удалось+подключить+аккаунт:+{str(e)}")
    raise web.HTTPFound("/dashboard?msg=Аккаунт+подключён")

async def remove_account(request):
    user = await check_auth(request)
    if user == "readonly": raise web.HTTPFound("/dashboard?error=Недостаточно+прав")
    name = request.query.get("name","")
    if name in extra_clients:
        await extra_clients[name]["client"].disconnect()
        del extra_clients[name]
        await broadcast_state()
        await backup_state()
    raise web.HTTPFound("/dashboard?msg=Аккаунт+отключён")

async def unmute_handler(request):
    user = await check_auth(request)
    if user == "readonly": raise web.HTTPFound("/dashboard?error=Недостаточно+прав")
    chat_id = int(request.query["chat_id"]); muted_chats.discard(chat_id); save_state()
    account = request.query.get("account","1")
    if account == "2" and client2: client = client2
    elif account in extra_clients: client = extra_clients[account]["client"]
    else: client = client1
    acc_name = (await client.get_me()).first_name or ("Аккаунт2" if account=="2" else "Аккаунт1")
    target_name = await resolve_chat_name(chat_id)
    log_command(0, f"Размутил чат {chat_id}", source="Web", target_id=chat_id, user_name=acc_name, target_name=target_name, result="ok")
    try: await client.send_message(chat_id, "🔊 Администратор размутил этот чат! Берегитесь, он может снова замутить 😈")
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
        user_name = await resolve_name(me1.id); target_name = await resolve_name(user_id)
        log_command(me1.id, f"Удалил из защиты {user_id}", source="Web", target_id=user_id, user_name=user_name, target_name=target_name, result="ok")
        await broadcast_state(); await backup_state()
        raise web.HTTPFound("/dashboard?msg=Пользователь+удалён+из+защиты")
    raise web.HTTPFound("/dashboard?error=Нельзя+удалить+владельца")

async def send_cmd(request):
    user = await check_auth(request)
    if user == "readonly": raise web.HTTPFound("/dashboard?error=Недостаточно+прав")
    data = await request.post(); account = data.get("account","1"); target = data.get("target","").strip()
    command = data.get("command","").strip(); args = data.get("args","").strip()
    if not command: raise web.HTTPFound("/dashboard?error=Команда+не+выбрана")
    if account == "2" and client2: client = client2
    elif account in extra_clients: client = extra_clients[account]["client"]
    else: client = client1
    acc_name = (await client.get_me()).first_name or ("Аккаунт2" if account=="2" else "Аккаунт1")
    target_entity = target if target else 'me'; target_name = target_entity
    if target_entity == 'me': target_name = "Избранное"
    else:
        try:
            chat = await client.get_entity(target_entity)
            target_name = chat.title if hasattr(chat, 'title') else (chat.first_name or target_entity)
        except: target_name = target_entity

    result_msg = None
    try:
        if command == ".mute":
            chat = await client.get_entity(target_entity)
            if hasattr(chat, 'broadcast') and chat.broadcast: result_msg = "Ошибка: каналы нельзя мутить"
            else:
                muted_chats.add(chat.id); save_state(); await broadcast_state()
                log_command(0, ".mute", source="Web", target_id=chat.id, user_name=acc_name, target_name=target_name, result="ok")
                result_msg = f"Чат {target_name} заглушен"
        elif command == ".unmute":
            chat = await client.get_entity(target_entity)
            muted_chats.discard(chat.id); save_state(); await broadcast_state()
            log_command(0, ".unmute", source="Web", target_id=chat.id, user_name=acc_name, target_name=target_name, result="ok")
            try: await client.send_message(target_entity, "🔊 Администратор размутил этот чат!")
            except: pass
            result_msg = f"Чат {target_name} размучен"
        elif command == ".spam":
            parts = args.split(maxsplit=1)
            if len(parts)==2:
                count = int(parts[0]); text = parts[1]
                if count > 50: result_msg = "Ошибка: максимум 50 повторений"
                else:
                    for _ in range(count): await client.send_message(target_entity, text); await asyncio.sleep(0.4)
                    log_command(0, f".spam {count} {text}", source="Web", user_name=acc_name, target_name=target_name, result="ok")
                    result_msg = f"Спам отправлен в {target_name}"
            else: result_msg = "Ошибка: укажите число и текст (пример: 3 Привет)"
        elif command == ".ping":
            start = time.time(); msg = await client.send_message(target_entity, "🏓 Пинг...")
            elapsed = (time.time() - start) * 1000; await msg.edit(f"🏓 Понг! `{elapsed:.1f}ms`")
            log_command(0, ".ping", source="Web", user_name=acc_name, target_name=target_name, result="ok")
            result_msg = f"Пинг: {elapsed:.1f}ms"
        elif command == ".purge":
            num = int(args) if args else 10
            if num > 200: num = 200
            deleted = 0
            async for message in client.iter_messages(target_entity, from_user='me', limit=num):
                try: await message.delete(); deleted += 1; await asyncio.sleep(0.5)
                except: pass
            tmp = await client.send_message(target_entity, f"🗑 Удалено {deleted} сообщений.")
            await asyncio.sleep(3); await tmp.delete()
            log_command(0, f".purge {num}", source="Web", user_name=acc_name, target_name=target_name, result="ok")
            result_msg = f"Удалено {deleted} сообщений в {target_name}"
        elif command == ".clearall":
            deleted = 0
            async for msg in client.iter_messages(target_entity):
                try: await msg.delete(); deleted += 1; await asyncio.sleep(0.5)
                except: pass
            tmp = await client.send_message(target_entity, f"🗑 Удалено {deleted} сообщений.")
            await asyncio.sleep(3); await tmp.delete()
            log_command(0, ".clearall", source="Web", user_name=acc_name, target_name=target_name, result="ok")
            result_msg = f"Удалено {deleted} сообщений в {target_name}"
        elif command == ".stats":
            chat = await client.get_entity(target_entity)
            if hasattr(chat, 'broadcast') and chat.broadcast: result_msg = "Ошибка: канал"
            else:
                participants_count = 0
                try: participants_count = (await client.get_participants(chat, limit=0)).total
                except: pass
                text = f"📊 <b>Статистика чата</b>\nНазвание: {chat.title}\nID: {chat.id}\nУчастников: {participants_count}"
                await client.send_message(target_entity, text, parse_mode='html')
                log_command(0, ".stats", source="Web", user_name=acc_name, target_name=target_name, result="ok")
                result_msg = f"Статистика отправлена в {target_name}"
        elif command == ".tr":
            parts = args.split(maxsplit=1)
            if len(parts)==2:
                target_lang, text = parts
                translated = GoogleTranslator(source='auto', target=target_lang).translate(text)
                await client.send_message(target_entity, f"🌐 Перевод ({target_lang}):\n{translated}")
                log_command(0, f".tr {target_lang} {text}", source="Web", user_name=acc_name, target_name=target_name, result="ok")
                result_msg = f"Перевод отправлен в {target_name}"
            else: result_msg = "Ошибка: укажите код языка и текст"
        elif command == ".avto":
            if args.startswith("all "):
                auto_reply_global['enabled'] = True; custom_text = args[4:]
                if custom_text: auto_reply_global['text'] = custom_text
                await client.send_message(target_entity, f"🌐 Глобальный автоответчик включён. Текст: {auto_reply_global['text']}")
                result_msg = "Глобальный автоответчик включён"
            else:
                if target_entity == 'me': result_msg = "Ошибка: автоответчик только в личных сообщениях"
                else:
                    custom_text = args if args else "⏳ Привет! Я сейчас не в сети, отвечу позже."
                    auto_reply_chats[target_entity] = {'enabled': True, 'text': custom_text}
                    await client.send_message(target_entity, f"✅ Автоответчик включён. Текст: {custom_text}")
                    result_msg = f"Автоответчик включён в {target_name}"
            log_command(0, ".avto", source="Web", user_name=acc_name, target_name=target_name, result="ok")
        elif command == ".help":
            text = ("📖 <b>Список команд юзербота:</b>\n\n"
                    "<b>.mute</b> — заглушить чат\n<b>.unmute</b> — снять мут\n<b>.clearall</b> — удалить все сообщения в чате\n"
                    "<b>.avto</b> / .avto all / .unavto — автоответчик\n<b>.spam N текст</b> — повторить N раз\n"
                    "<b>.ping</b> — пинг\n<b>.purge [N]</b> — удалить свои последние N сообщений\n<b>.save текст</b> / .get — заметки\n"
                    "<b>.stats</b> — статистика чата\n<b>.tr код текст</b> — перевод\n<b>.addfriend</b> / .delfriend / .listfriends\n"
                    "<b>.history</b> — история последних команд\n<b>.stt</b> — распознать голосовое сообщение\n<b>.qr текст</b> — QR-код\n"
                    "<b>.weather город</b> — погода\n<b>.tts текст</b> — голосовое сообщение\n<b>.sticker</b> — случайный стикер\n<b>.help</b> — это сообщение")
            await client.send_message(target_entity, text, parse_mode='html')
            result_msg = "Справка отправлена"
        else: result_msg = "Неизвестная команда"
    except Exception as e:
        log_command(0, f"ОШИБКА: {command} -> {e}", source="Web", user_name=acc_name, target_name=target_name, result=f"error: {e}")
        result_msg = f"Ошибка: {str(e)}"

    await backup_state()
    if result_msg: redirect_url = f"/dashboard?msg={result_msg.replace(' ', '+')}"
    else: redirect_url = "/dashboard"
    raise web.HTTPFound(redirect_url)

async def backup_now_handler(request):
    user = await check_auth(request)
    if user == "readonly": raise web.HTTPFound("/dashboard?error=Недостаточно+прав")
    await backup_state()
    raise web.HTTPFound("/dashboard?msg=Бэкап+создан")

async def handle_health(request): return web.Response(text="OK")

async def websocket_handler(request):
    token = request.cookies.get("auth_token"); invite_token = request.cookies.get("invite_token")
    if not token and not invite_token: return web.Response(status=401)
    if token and token != "password_ok" and auth_tokens.get(token) != True: return web.Response(status=401)
    if invite_token and invite_token not in invites: return web.Response(status=401)
    ws = web.WebSocketResponse(); await ws.prepare(request); ws_clients.add(ws)
    acc2_name = ACC2_DISPLAY_NAME if ACC2_DISPLAY_NAME else (await client2.get_me()).first_name if client2 else None
    initial = {"muted_chats": list(muted_chats), "protected_users": list(protected_users), "history": command_history, "chat_names": await get_chat_names(), "user_names": await get_user_names(), "acc1_name": (await client1.get_me()).first_name or "Аккаунт 1", "acc2_name": acc2_name, "invites": invites, "admins": list(admins.keys()), "extra_clients": list(extra_clients.keys())}
    await ws.send_str(json.dumps(initial, default=str, ensure_ascii=False))
    try:
        async for msg in ws:
            pass
    finally:
        ws_clients.discard(ws)
    return ws

async def guest_ws_handler(request):
    key = request.query.get("key","")
    if key != GUEST_KEY: return web.Response(status=403)
    ws = web.WebSocketResponse(); await ws.prepare(request)
    await ws.send_str(json.dumps({"muted_chats": list(muted_chats), "protected_users": list(protected_users), "history": command_history, "chat_names": await get_chat_names(), "user_names": await get_user_names()}, default=str, ensure_ascii=False))
    await ws.close(); return ws

app = web.Application()
app.router.add_get("/", handle_health); app.router.add_get("/login", login_page); app.router.add_post("/auth/login", auth_login)
app.router.add_get("/logout", logout); app.router.add_get("/auth/request_bot", request_bot_auth); app.router.add_get("/auth/check_token", check_token)
app.router.add_get("/dashboard", dashboard); app.router.add_get("/guest", guest_view); app.router.add_get("/unmute", unmute_handler)
app.router.add_get("/remove_protected", remove_protected); app.router.add_post("/send_cmd", send_cmd)
app.router.add_post("/add_admin", add_admin); app.router.add_get("/delete_admin", delete_admin)
app.router.add_post("/add_account", add_account); app.router.add_get("/remove_account", remove_account)
app.router.add_get("/backup_now", backup_now_handler)
app.router.add_get("/ws", websocket_handler); app.router.add_get("/guest-ws", guest_ws_handler)

async def start_web_server():
    runner = web.AppRunner(app); await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT); await site.start()
    print(f"🔐 Панель управления: http://.../dashboard")
    while True: await asyncio.sleep(3600)

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
    await init_protected_users()
    await restore_state()
    asyncio.create_task(backup_loop())

    def shutdown_handler(signum, frame):
        print("🔻 Завершение работы, сохраняю состояние...")
        loop = asyncio.get_event_loop()
        loop.run_until_complete(backup_state())
        os._exit(0)
    signal.signal(signal.SIGTERM, shutdown_handler)

    await start_web_server()
    tasks = [client1.run_until_disconnected()]
    if client2: tasks.append(client2.run_until_disconnected())
    if bot and bot.is_connected(): tasks.append(bot.run_until_disconnected())
    await asyncio.gather(*tasks)
    if http_session: await http_session.close()

if __name__ == "__main__":
    asyncio.run(main())
