import os, asyncio, json, time, base64, uuid, random, io, urllib.parse, hashlib, tempfile
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
ACC2_DISPLAY_NAME = os.environ.get("ACC2_DISPLAY_NAME", "𝙱𝚞𝚣𝚣𝚢𝚅𝚊𝚣𝚣𝚢")
INVITES_FILE = Path(os.environ.get("INVITES_FILE", "invites.json"))
ADMINS_FILE = Path("admins.json")
DATA_FILE = Path("userbot_data.json")
LOG_FILE = Path("command_history.json")

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
invites = {}
admins = {}

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

load_admins(); load_invites(); load_state(); load_history()

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
    data = {"muted_chats": list(muted_chats), "protected_users": list(protected_users), "history": command_history, "chat_names": await get_chat_names(), "user_names": await get_user_names(), "acc1_name": (await client1.get_me()).first_name or "Аккаунт 1", "acc2_name": acc2_name, "invites": invites, "admins": list(admins.keys())}
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
    for uid in protected_users: names[str(uid)] = await resolve_name(uid)
    return names

async def init_protected_users():
    me1 = await client1.get_me(); protected_users.add(me1.id)
    if client2:
        try:
            me2 = await client2.get_me(); protected_users.add(me2.id)
        except Exception as e: print(f"⚠️ Не удалось получить данные второго аккаунта: {e}")
    save_state(); await broadcast_state()

# ========== ОБРАБОТЧИКИ КОМАНД ==========
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

    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.unmute$'))
    async def unmute_cmd(event):
        muted_chats.discard(event.chat_id); save_state(); await event.delete()
        user_name = await resolve_name(event.sender_id); target_name = await resolve_chat_name(event.chat_id)
        log_command(event.sender_id, ".unmute", source="Telegram", target_id=event.chat_id, user_name=user_name, target_name=target_name, result="ok")
        await event.client.send_message(event.chat_id, "🔊 <b>Мут снят.</b> Сообщения больше не удаляются.", parse_mode='html')
        await broadcast_state()

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

    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.delfriend$'))
    async def delfriend_cmd(event):
        if not event.is_private: await event.reply("❌ Команда .delfriend работает только в личных сообщениях."); return
        chat = await event.get_chat(); friend_id = chat.id
        me = await event.client.get_me()
        if friend_id == me.id: await event.reply("❌ Нельзя удалить владельца из защиты."); return
        if friend_id in protected_users: protected_users.discard(friend_id); save_state(); await event.reply("✅ Пользователь удалён из списка защиты.")
        else: await event.reply("❌ Пользователь не найден в списке защиты.")

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
        sets = ["UtyaDuck", "HotCherry", "PigPeccary"]
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

register_handlers(client1)
if client2: register_handlers(client2)

if bot:
    @bot.on(events.CallbackQuery)
    async def auth_callback(event):
        data = event.data.decode()
        if data.startswith("approve:"):
            token = data.split(":")[1]
            if token in auth_tokens: auth_tokens[token] = True; await event.edit("✅ Вход одобрен. Можете вернуться на сайт и войти.", buttons=None)
        elif data.startswith("reject:"):
            token = data.split(":")[1]; auth_tokens.pop(token, None); await event.edit("🚫 Вход отклонён.", buttons=None)

# ========== СТИЛЬНЫЙ САЙТ ==========
HTML_LOGIN = f"""<html><head><meta charset="utf-8"><title>Вход</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@300;600&display=swap');
* {{ box-sizing: border-box; }}
body {{ margin: 0; height: 100vh; display: flex; align-items: center; justify-content: center; background: #0a0a0a; font-family: 'Montserrat', sans-serif; }}
.card {{ background: rgba(20,20,30,0.9); backdrop-filter: blur(10px); border: 1px solid rgba(255,255,255,0.1); border-radius: 16px; padding: 2rem; width: 320px; box-shadow: 0 0 30px rgba(233,69,96,0.2); }}
h2 {{ color: #e94560; text-align: center; font-weight: 600; margin-top: 0; }}
input {{ width: 100%; padding: 0.7rem; margin: 0.5rem 0; border: none; border-radius: 8px; background: #1a1a2e; color: #e0e0e0; font-size: 1rem; }}
button {{ width: 100%; padding: 0.7rem; margin-top: 1rem; border: none; border-radius: 8px; background: #e94560; color: white; font-weight: 600; cursor: pointer; transition: 0.3s; }}
button:hover {{ background: #c93750; transform: scale(1.02); }}
.bot-login {{ margin-top: 1.5rem; text-align: center; }}
.bot-login button {{ background: #1a1a2e; border: 1px solid #e94560; }}
</style></head><body>
<div class="card">
<form action="/auth/login" method="post">
<h2>Вход</h2>
<input type="text" name="username" placeholder="Логин" value="{ADMIN_USER}">
<input type="password" name="password" placeholder="Пароль">
<button type="submit">Войти</button>
</form>
<div class="bot-login">
<button onclick="loginViaBot()">Войти через Telegram</button>
</div>
</div>
<script>
async function loginViaBot() {{
    const resp = await fetch('/auth/request_bot');
    const data = await resp.json();
    if (data.token) {{
        document.cookie = "auth_token=" + data.token + "; path=/";
        alert("Запрос отправлен. Нажмите 'Принять' в боте.");
        const interval = setInterval(async () => {{
            const check = await fetch('/auth/check_token?token=' + data.token);
            if ((await check.json()).approved) {{ clearInterval(interval); window.location.href = '/dashboard'; }}
        }}, 3000);
    }} else alert("Ошибка: " + data.error);
}}
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
    body { margin: 0; background: #0a0a0a; color: #e0e0e0; font-family: 'Montserrat', sans-serif; }
    .navbar { display: flex; align-items: center; justify-content: space-between; background: #13131f; padding: 0.8rem 2rem; border-bottom: 1px solid rgba(233,69,96,0.3); }
    .navbar-brand { font-size: 1.5rem; font-weight: 600; color: #e94560; text-decoration: none; }
    .nav-info { display: flex; gap: 1.5rem; align-items: center; }
    .nav-info span { opacity: 0.8; }
    .logout-btn { background: rgba(233,69,96,0.2); padding: 0.4rem 0.8rem; border-radius: 6px; color: #e94560; text-decoration: none; font-size: 0.9rem; }
    .tabs { display: flex; gap: 0.5rem; padding: 1rem 2rem; background: #13131f; border-bottom: 1px solid rgba(255,255,255,0.05); overflow-x: auto; }
    .tabs button { background: transparent; color: #aaa; border: none; padding: 0.5rem 1rem; border-radius: 8px; font-size: 0.9rem; cursor: pointer; transition: 0.2s; }
    .tabs button.active { background: #e94560; color: white; }
    .content { padding: 2rem; }
    .tab-pane { display: none; }
    .tab-pane.active { display: block; }
    .list-group-item { background: #13131f; border: 1px solid rgba(255,255,255,0.05); border-radius: 8px; padding: 0.7rem 1rem; margin-bottom: 0.5rem; display: flex; justify-content: space-between; align-items: center; }
    .btn-custom { background: #e94560; color: white; border: none; padding: 0.4rem 0.8rem; border-radius: 6px; cursor: pointer; font-size: 0.8rem; }
    .btn-custom:hover { background: #c93750; }
    table { width: 100%; border-collapse: collapse; margin-top: 1rem; }
    th, td { padding: 0.6rem; border-bottom: 1px solid rgba(255,255,255,0.05); text-align: left; }
    th { color: #e94560; font-weight: 600; }
    .badge { padding: 0.2rem 0.5rem; border-radius: 4px; font-size: 0.75rem; }
    .badge-ok { background: #238636; }
    .badge-error { background: #da3633; }
    .notification { position: fixed; top: 1rem; right: 1rem; background: #238636; color: white; padding: 0.8rem 1.2rem; border-radius: 8px; display: none; z-index: 999; }
    .notification.error { background: #da3633; }
    @media (max-width: 768px) { .tabs { flex-wrap: nowrap; } }
  </style>
</head>
<body>
  <nav class="navbar">
    <a class="navbar-brand" href="#">🤖 Userbot Panel</a>
    <div class="nav-info">
      <span><i class="far fa-user"></i> {user}</span>
      <span>Акк1: <span id="acc1Name">—</span></span>
      <span>Акк2: <span id="acc2Name">—</span></span>
      <a href="/logout" class="logout-btn"><i class="fas fa-sign-out-alt"></i></a>
    </div>
  </nav>
  <div class="tabs">
    <button class="active" data-tab="muted">🔇 Чаты в муте</button>
    <button data-tab="protected">🛡 Защищённые</button>
    <button data-tab="commands">⚡ Команды</button>
    <button data-tab="history">📜 История</button>
    <button data-tab="admins">👥 Админы</button>
    <button data-tab="invites">🔗 Приглашения</button>
  </div>
  <div class="content">
    <div id="muted" class="tab-pane active"><div id="mutedList"></div></div>
    <div id="protected" class="tab-pane"><div id="protectedList"></div></div>
    <div id="commands" class="tab-pane">
      <form action="/send_cmd" method="post" style="display: grid; gap: 0.8rem; max-width: 500px;">
        <select name="account" id="accountSelect" style="padding:0.5rem; background:#13131f; color:white; border:1px solid #30363d; border-radius:6px;"></select>
        <input name="target" placeholder="Чат (username или ID, пусто = Избранное)" style="padding:0.5rem; background:#13131f; color:white; border:1px solid #30363d; border-radius:6px;">
        <select name="command" id="cmdSelect" style="padding:0.5rem; background:#13131f; color:white; border:1px solid #30363d; border-radius:6px;">
          <option value=".mute">.mute</option><option value=".unmute">.unmute</option><option value=".spam">.spam</option><option value=".ping">.ping</option><option value=".purge">.purge</option><option value=".clearall">.clearall</option><option value=".stats">.stats</option><option value=".tr">.tr</option><option value=".avto">.avto</option><option value=".help">.help</option>
        </select>
        <input name="args" placeholder="Аргументы" style="padding:0.5rem; background:#13131f; color:white; border:1px solid #30363d; border-radius:6px;">
        <button type="submit" class="btn-custom" style="padding:0.6rem;">Отправить</button>
      </form>
    </div>
    <div id="history" class="tab-pane">
      <div style="margin-bottom:0.5rem;">
        <select id="accountFilter" style="padding:0.3rem; background:#13131f; color:white; border:1px solid #30363d; border-radius:4px;">
          <option value="all">Все</option><option value="acc1">Акк1</option><option value="acc2">Акк2</option>
        </select>
        <button class="btn-custom" onclick="toggleAllHistory()">Показать все</button>
      </div>
      <table><thead><tr><th>Время</th><th>Источник</th><th>Пользователь</th><th>Команда</th><th>Цель</th><th>Рез.</th></tr></thead><tbody id="historyBody"></tbody></table>
    </div>
    <div id="admins" class="tab-pane">
      <form action="/add_admin" method="post" style="display:flex; gap:0.5rem; margin-bottom:1rem;">
        <input name="username" placeholder="Логин" required style="flex:1; padding:0.5rem; background:#13131f; color:white; border:1px solid #30363d; border-radius:6px;">
        <input name="password" type="password" placeholder="Пароль" required style="flex:1; padding:0.5rem; background:#13131f; color:white; border:1px solid #30363d; border-radius:6px;">
        <select name="role" style="padding:0.5rem; background:#13131f; color:white; border:1px solid #30363d; border-radius:6px;"><option value="admin">Админ</option><option value="readonly">Чтение</option></select>
        <button type="submit" class="btn-custom">Добавить</button>
      </form>
      <div id="adminsList"></div>
    </div>
    <div id="invites" class="tab-pane">
      <form action="/create_invite" method="post" style="display:flex; gap:0.5rem; margin-bottom:1rem;">
        <select name="role" style="padding:0.5rem; background:#13131f; color:white; border:1px solid #30363d; border-radius:6px;"><option value="readonly">Только чтение</option><option value="admin">Администратор</option></select>
        <button type="submit" class="btn-custom">Создать</button>
      </form>
      <div id="invitesList"></div>
    </div>
  </div>
  <div id="notification" class="notification"></div>

  <script>
    let ws, fullHistory=[], acc1Name="Аккаунт 1", acc2Name="Аккаунт 2", showAllHistory=false;
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
      document.getElementById('acc1Name').textContent = data.acc1_name || 'Аккаунт 1';
      document.getElementById('acc2Name').textContent = data.acc2_name || '—';
      acc1Name = data.acc1_name; acc2Name = data.acc2_name;
      let sel = document.getElementById('accountSelect');
      sel.innerHTML = ''; sel.add(new Option(acc1Name,'1'));
      if (acc2Name) sel.add(new Option(acc2Name,'2'));
      let filter = document.getElementById('accountFilter');
      filter.options[0].text = 'Все'; filter.options[1].text = acc1Name;
      if (acc2Name) filter.options[2].text = acc2Name;

      fullHistory = data.history || [];
      renderHistory();

      let mutedHtml = '';
      for (let id in data.chat_names) mutedHtml += `<div class="list-group-item">${data.chat_names[id]} <button class="btn-custom" onclick="unmuteChat(${id})">Размутить</button></div>`;
      document.getElementById('mutedList').innerHTML = mutedHtml || 'Нет чатов';

      let protectedHtml = '';
      for (let id in data.user_names) protectedHtml += `<div class="list-group-item">${data.user_names[id]}</div>`;
      document.getElementById('protectedList').innerHTML = protectedHtml || 'Нет';

      let adminsHtml = '';
      if (data.admins) data.admins.forEach(user => adminsHtml += `<div class="list-group-item">${user} <a href="/delete_admin?user=${user}" class="btn-custom">Удалить</a></div>`);
      document.getElementById('adminsList').innerHTML = adminsHtml || 'Нет админов';

      let invitesHtml = '';
      for (let key in data.invites) invitesHtml += `<div class="list-group-item">${key} (${data.invites[key].role}) <a href="/delete_invite?key=${key}" class="btn-custom">Удалить</a></div>`;
      document.getElementById('invitesList').innerHTML = invitesHtml || 'Нет приглашений';
    }

    function unmuteChat(id) { fetch('/unmute?chat_id='+id+'&account='+document.querySelector('select[name="account"]').value).then(() => location.reload()); }

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

# ========== ВЕБ-СЕРВЕР ОБРАБОТЧИКИ ==========
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
    is_admin = (user == "admin" or (user in admins and admins[user]["role"] == "admin"))
    return web.Response(text=HTML_DASHBOARD.format(user=user, is_admin=is_admin), content_type="text/html")

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

async def create_invite(request):
    user = await check_auth(request)
    if user != "admin" and (user not in admins or admins[user]["role"] != "admin"): raise web.HTTPFound("/dashboard?error=Только+админ")
    data = await request.post(); role = data.get("role","readonly"); key = str(uuid.uuid4())[:8]
    invites[key] = {"role": role, "created": datetime.now().isoformat()}; save_invites(); await broadcast_state()
    raise web.HTTPFound("/dashboard?msg=Инвайт+создан")

async def delete_invite(request):
    user = await check_auth(request)
    if user != "admin" and (user not in admins or admins[user]["role"] != "admin"): raise web.HTTPFound("/dashboard?error=Только+админ")
    key = request.query.get("key","")
    if key in invites: del invites[key]; save_invites(); await broadcast_state()
    raise web.HTTPFound("/dashboard?msg=Инвайт+удалён")

async def unmute_handler(request):
    user = await check_auth(request)
    if user == "readonly": raise web.HTTPFound("/dashboard?error=Недостаточно+прав")
    chat_id = int(request.query["chat_id"]); muted_chats.discard(chat_id); save_state()
    account = request.query.get("account","1")
    client = client2 if (account == "2" and client2) else client1
    acc_name = (await client.get_me()).first_name or ("Аккаунт2" if account=="2" else "Аккаунт1")
    target_name = await resolve_chat_name(chat_id)
    log_command(0, f"Размутил чат {chat_id}", source="Web", target_id=chat_id, user_name=acc_name, target_name=target_name, result="ok")
    try: await client.send_message(chat_id, "🔊 Администратор размутил этот чат! Берегитесь, он может снова замутить 😈")
    except: pass
    await broadcast_state(); raise web.HTTPFound("/dashboard?msg=Чат+размучен")

async def remove_protected(request):
    user = await check_auth(request)
    if user == "readonly": raise web.HTTPFound("/dashboard?error=Недостаточно+прав")
    user_id = int(request.query["user_id"]); me1 = await client1.get_me(); me2_id = (await client2.get_me()).id if client2 else None
    if user_id != me1.id and user_id != me2_id:
        protected_users.discard(user_id); save_state()
        user_name = await resolve_name(me1.id); target_name = await resolve_name(user_id)
        log_command(me1.id, f"Удалил из защиты {user_id}", source="Web", target_id=user_id, user_name=user_name, target_name=target_name, result="ok")
        await broadcast_state(); raise web.HTTPFound("/dashboard?msg=Пользователь+удалён+из+защиты")
    raise web.HTTPFound("/dashboard?error=Нельзя+удалить+владельца")

async def send_cmd(request):
    user = await check_auth(request)
    if user == "readonly": raise web.HTTPFound("/dashboard?error=Недостаточно+прав")
    data = await request.post(); account = data.get("account","1"); target = data.get("target","").strip()
    command = data.get("command","").strip(); args = data.get("args","").strip()
    if not command: raise web.HTTPFound("/dashboard?error=Команда+не+выбрана")
    client = client2 if (account == "2" and client2) else client1
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

    if result_msg: redirect_url = f"/dashboard?msg={result_msg.replace(' ', '+')}"
    else: redirect_url = "/dashboard"
    raise web.HTTPFound(redirect_url)

async def handle_health(request): return web.Response(text="OK")

async def websocket_handler(request):
    token = request.cookies.get("auth_token"); invite_token = request.cookies.get("invite_token")
    if not token and not invite_token: return web.Response(status=401)
    if token and token != "password_ok" and auth_tokens.get(token) != True: return web.Response(status=401)
    if invite_token and invite_token not in invites: return web.Response(status=401)
    ws = web.WebSocketResponse(); await ws.prepare(request); ws_clients.add(ws)
    acc2_name = ACC2_DISPLAY_NAME if ACC2_DISPLAY_NAME else (await client2.get_me()).first_name if client2 else None
    initial = {"muted_chats": list(muted_chats), "protected_users": list(protected_users), "history": command_history, "chat_names": await get_chat_names(), "user_names": await get_user_names(), "acc1_name": (await client1.get_me()).first_name or "Аккаунт 1", "acc2_name": acc2_name, "invites": invites, "admins": list(admins.keys())}
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
app.router.add_post("/create_invite", create_invite); app.router.add_get("/delete_invite", delete_invite)
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
    await start_web_server()
    tasks = [client1.run_until_disconnected()]
    if client2: tasks.append(client2.run_until_disconnected())
    if bot and bot.is_connected(): tasks.append(bot.run_until_disconnected())
    await asyncio.gather(*tasks)
    if http_session: await http_session.close()

if __name__ == "__main__":
    asyncio.run(main())
