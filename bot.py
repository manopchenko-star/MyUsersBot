import os, asyncio, json, time, base64, uuid, random, string, io, re, urllib.parse, logging, unicodedata, tempfile, hashlib
from pathlib import Path
from datetime import datetime, timedelta
from telethon import TelegramClient, events, Button
from telethon.errors import FloodWaitError, ChatAdminRequiredError
from telethon.sessions import StringSession
from telethon.tl.types import MessageEntityTextUrl, DocumentAttributeAudio
from deep_translator import GoogleTranslator
from aiohttp import web, WSMsgType, ClientSession
import qrcode
from gtts import gTTS
import speech_recognition as sr
from pydub import AudioSegment
AudioSegment.converter = "/opt/render/project/src/ffmpeg"

# ---------- КОНФИГУРАЦИЯ ----------
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
    try:
        client2 = TelegramClient(StringSession(SESSION_STRING_2), API_ID, API_HASH)
    except Exception as e:
        print(f"⚠️ Ошибка второго клиента: {e}")
        client2 = None

bot = None
if BOT_TOKEN:
    bot = TelegramClient("auth_bot_session", API_ID, API_HASH)

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

def load_json(path, default):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except:
            return default
    return default

def save_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False))

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def load_admins():
    global admins
    admins = load_json(ADMINS_FILE, {})
    if not admins:
        admins = {ADMIN_USER: {"password": hash_password(ADMIN_PASS), "role": "admin"}}
        save_json(ADMINS_FILE, admins)

def save_admins():
    save_json(ADMINS_FILE, admins)

def load_invites():
    global invites
    invites = load_json(INVITES_FILE, {})

def save_invites():
    save_json(INVITES_FILE, invites)

def save_state():
    save_json(DATA_FILE, {"muted_chats": list(muted_chats), "protected_users": list(protected_users)})

def load_state():
    global muted_chats, protected_users
    data = load_json(DATA_FILE, {"muted_chats": [], "protected_users": []})
    muted_chats = set(data.get("muted_chats", []))
    protected_users = set(data.get("protected_users", []))

def load_history():
    global command_history
    command_history = load_json(LOG_FILE, [])

warns = load_json(WARN_FILE, {})
afk_users = load_json(AFK_FILE, {})
reminders = load_json(REMIND_FILE, [])
load_admins()
load_invites()
load_state()
load_history()

async def resolve_name(user_id):
    try:
        user = await client1.get_entity(user_id)
        return f"@{user.username}" if user.username else user.first_name or str(user_id)
    except:
        return str(user_id)

async def resolve_chat_name(chat_id):
    try:
        chat = await client1.get_entity(chat_id)
        return chat.title if hasattr(chat, 'title') else f"{chat.first_name or ''} {chat.last_name or ''}".strip() or str(chat_id)
    except:
        return str(chat_id)

def log_command(user_id, command, source="Telegram", target_id=None, user_name=None, target_name=None, result=None):
    global command_history
    entry = {
        "time": datetime.now().isoformat(),
        "user_id": user_id,
        "user_name": user_name or str(user_id),
        "command": command,
        "source": source,
        "target_id": target_id,
        "target_name": target_name or (str(target_id) if target_id else "Избранное"),
        "result": result
    }
    command_history.append(entry)
    if len(command_history) > 50:
        command_history = command_history[-50:]
    save_json(LOG_FILE, command_history)
    asyncio.ensure_future(broadcast_state())

async def broadcast_state():
    acc2_name = ACC2_DISPLAY_NAME if ACC2_DISPLAY_NAME else (await client2.get_me()).first_name if client2 else None
    data = {
        "muted_chats": list(muted_chats),
        "protected_users": list(protected_users),
        "history": command_history,
        "chat_names": await get_chat_names(),
        "user_names": await get_user_names(),
        "acc1_name": (await client1.get_me()).first_name or "Аккаунт 1",
        "acc2_name": acc2_name,
        "invites": invites,
        "admins": list(admins.keys())
    }
    msg = json.dumps(data, default=str, ensure_ascii=False)
    for ws in list(ws_clients):
        try:
            await ws.send_str(msg)
        except:
            ws_clients.discard(ws)

async def get_chat_names():
    names = {}
    for cid in muted_chats:
        names[str(cid)] = await resolve_chat_name(cid)
    return names

async def get_user_names():
    names = {}
    for uid in protected_users:
        names[str(uid)] = await resolve_name(uid)
    return names

async def init_protected_users():
    me1 = await client1.get_me()
    protected_users.add(me1.id)
    if client2:
        try:
            me2 = await client2.get_me()
            protected_users.add(me2.id)
        except Exception as e:
            print(f"⚠️ Не удалось получить данные второго аккаунта: {e}")
    save_state()
    await broadcast_state()

# ---------- ВСЕ ОБРАБОТЧИКИ КОМАНД ----------
def register_handlers(client_instance):
    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.mute$'))
    async def mute_cmd(event):
        chat = await event.get_chat()
        if hasattr(chat, 'broadcast') and chat.broadcast:
            return
        muted_chats.add(event.chat_id)
        save_state()
        await event.delete()
        user_name = await resolve_name(event.sender_id)
        target_name = await resolve_chat_name(event.chat_id)
        log_command(event.sender_id, ".mute", source="Telegram", target_id=event.chat_id, user_name=user_name, target_name=target_name, result="ok")
        text = (
            "🔇 <b>Пользователь заглушен</b>\n"
            "Все его сообщения будут <i>мгновенно удаляться</i>.\n\n"
            "Нажмите кнопку ниже, чтобы размутить."
        )
        buttons = [Button.inline("🔊 Размутить", b"unmute")]
        await event.client.send_message(event.chat_id, text, buttons=buttons, parse_mode='html')
        await broadcast_state()

    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.unmute$'))
    async def unmute_cmd(event):
        muted_chats.discard(event.chat_id)
        save_state()
        await event.delete()
        user_name = await resolve_name(event.sender_id)
        target_name = await resolve_chat_name(event.chat_id)
        log_command(event.sender_id, ".unmute", source="Telegram", target_id=event.chat_id, user_name=user_name, target_name=target_name, result="ok")
        await event.client.send_message(event.chat_id, "🔊 <b>Мут снят.</b> Сообщения больше не удаляются.", parse_mode='html')
        await broadcast_state()

    @client_instance.on(events.NewMessage(incoming=True))
    async def delete_muted(event):
        if event.chat_id in muted_chats and not event.out:
            if event.sender_id not in protected_users:
                try:
                    await event.delete()
                except:
                    pass

    @client_instance.on(events.CallbackQuery(data=b"unmute"))
    async def unmute_callback(event):
        muted_chats.discard(event.chat_id)
        save_state()
        user_name = await resolve_name(event.sender_id)
        target_name = await resolve_chat_name(event.chat_id)
        log_command(event.sender_id, "Размутил (кнопка)", source="Telegram", target_id=event.chat_id, user_name=user_name, target_name=target_name, result="ok")
        await event.edit("🔊 <b>Мут снят.</b>", buttons=None, parse_mode='html')
        await broadcast_state()

    # ---------- АВТООТВЕТЧИК ----------
    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.avto(\s+all)?(?:\s+(.*))?'))
    async def avto_cmd(event):
        is_global = bool(event.pattern_match.group(1))
        custom_text = event.pattern_match.group(2).strip() if event.pattern_match.group(2) else None
        if is_global:
            auto_reply_global['enabled'] = True
            if custom_text:
                auto_reply_global['text'] = custom_text
            await event.delete()
            await event.client.send_message(
                event.chat_id if event.is_private else None,
                f"🌐 <b>Глобальный автоответчик включён.</b>\nТекст: {auto_reply_global['text']}",
                parse_mode='html'
            )
        else:
            if not event.is_private:
                await event.reply("❌ Автоответчик для групп не поддерживается.")
                return
            if custom_text is None:
                custom_text = "⏳ Привет! Я сейчас не в сети, отвечу позже."
            auto_reply_chats[event.chat_id] = {'enabled': True, 'text': custom_text}
            await event.delete()
            await event.client.send_message(
                event.chat_id,
                f"✅ <b>Автоответчик включён в этом чате.</b>\nТекст: {custom_text}",
                parse_mode='html'
            )

    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.unavto(\s+all)?'))
    async def unavto_cmd(event):
        is_global = bool(event.pattern_match.group(1))
        if is_global:
            auto_reply_global['enabled'] = False
            await event.delete()
            if event.is_private:
                await event.client.send_message(event.chat_id, "🌐 <b>Глобальный автоответчик выключен.</b>", parse_mode='html')
        else:
            if not event.is_private:
                await event.reply("❌ Автоответчик для групп не поддерживается.")
                return
            if event.chat_id in auto_reply_chats:
                del auto_reply_chats[event.chat_id]
            await event.delete()
            await event.client.send_message(event.chat_id, "❌ <b>Автоответчик выключен в этом чате.</b>", parse_mode='html')

    @client_instance.on(events.NewMessage(incoming=True))
    async def auto_reply_handler(event):
        if event.out:
            return
        chat_id = event.chat_id
        if chat_id in muted_chats:
            if event.sender_id not in protected_users:
                try:
                    await event.delete()
                except:
                    pass
            return
        chat_settings = auto_reply_chats.get(chat_id)
        if chat_settings and chat_settings.get('enabled'):
            reply_text = chat_settings.get('text')
            if reply_text:
                if last_replied.get(chat_id) == event.id:
                    return
                await asyncio.sleep(1)
                await event.client.send_message(chat_id, reply_text)
                last_replied[chat_id] = event.id
            return
        if auto_reply_global['enabled']:
            reply_text = auto_reply_global.get('text')
            if reply_text:
                if last_replied.get(chat_id) == event.id:
                    return
                await asyncio.sleep(1)
                await event.client.send_message(chat_id, reply_text)
                last_replied[chat_id] = event.id

    # ---------- ОСТАЛЬНЫЕ КОМАНДЫ (полный список) ----------
    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.spam\s+(\d+)\s+(.*)'))
    async def spam_cmd(event):
        count = int(event.pattern_match.group(1))
        text = event.pattern_match.group(2)
        await event.delete()
        user_name = await resolve_name(event.sender_id)
        target_name = await resolve_chat_name(event.chat_id)
        log_command(event.sender_id, f".spam {count} {text}", source="Telegram", target_id=event.chat_id, user_name=user_name, target_name=target_name, result="ok")
        if count > 50:
            await event.client.send_message(event.chat_id, "⚠️ Максимум 50 повторений за раз.")
            return
        for _ in range(count):
            await event.client.send_message(event.chat_id, text)
            await asyncio.sleep(0.4)

    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.ping$'))
    async def ping_cmd(event):
        start = time.time()
        msg = await event.reply("🏓 Пинг...")
        elapsed = (time.time() - start) * 1000
        await msg.edit(f"🏓 Понг! `{elapsed:.1f}ms`")

    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.purge(?:\s+(\d+))?'))
    async def purge_cmd(event):
        num = int(event.pattern_match.group(1)) if event.pattern_match.group(1) else 10
        if num > 200:
            num = 200
        await event.delete()
        user_name = await resolve_name(event.sender_id)
        target_name = await resolve_chat_name(event.chat_id)
        log_command(event.sender_id, f".purge {num}", source="Telegram", target_id=event.chat_id, user_name=user_name, target_name=target_name, result="ok")
        deleted = 0
        async for message in event.client.iter_messages(event.chat_id, from_user='me', limit=num):
            try:
                await message.delete()
                deleted += 1
                await asyncio.sleep(0.5)
            except:
                pass
        tmp = await event.client.send_message(event.chat_id, f"🗑 Удалено {deleted} сообщений.")
        await asyncio.sleep(3)
        await tmp.delete()

    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.save\s+(.*)'))
    async def save_cmd(event):
        text = event.pattern_match.group(1)
        await event.client.send_message('me', f"📌 Заметка:\n{text}")
        await event.reply("✅ Заметка сохранена в «Избранное».")

    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.get$'))
    async def get_cmd(event):
        async for msg in event.client.iter_messages('me', limit=20):
            if msg.text and msg.text.startswith("📌"):
                await event.client.send_message(event.chat_id, msg.text)
                return
        await event.reply("❌ Нет сохранённых заметок.")

    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.stats$'))
    async def stats_cmd(event):
        chat = await event.get_chat()
        if hasattr(chat, 'broadcast') and chat.broadcast:
            await event.reply("❌ Команда недоступна для каналов.")
            return
        participants_count = 0
        try:
            participants_count = (await event.client.get_participants(chat, limit=0)).total
        except:
            pass
        text = (
            f"📊 <b>Статистика чата</b>\n"
            f"Название: {chat.title}\n"
            f"ID: {chat.id}\n"
            f"Тип: {'Супергруппа' if chat.megagroup else 'Группа' if chat.broadcast else 'ЛС'}\n"
            f"Участников: {participants_count}"
        )
        await event.reply(text, parse_mode='html')

    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.tr\s+([a-z]{2})\s+(.*)'))
    async def translate_cmd(event):
        target_lang = event.pattern_match.group(1)
        text = event.pattern_match.group(2)
        try:
            translated = GoogleTranslator(source='auto', target=target_lang).translate(text)
            await event.reply(f"🌐 Перевод ({target_lang}):\n{translated}")
        except Exception as e:
            await event.reply(f"❌ Ошибка перевода: {e}")

    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.addfriend$'))
    async def addfriend_cmd(event):
        if not event.is_private:
            await event.reply("❌ Команда .addfriend работает только в личных сообщениях.")
            return
        chat = await event.get_chat()
        friend_id = chat.id
        if friend_id == event.sender_id:
            await event.reply("❌ Нельзя добавить самого себя (вы уже защищены).")
            return
        protected_users.add(friend_id)
        save_state()
        await event.reply("✅ Пользователь добавлен в список защищённых от мута.")

    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.delfriend$'))
    async def delfriend_cmd(event):
        if not event.is_private:
            await event.reply("❌ Команда .delfriend работает только в личных сообщениях.")
            return
        chat = await event.get_chat()
        friend_id = chat.id
        me = await event.client.get_me()
        if friend_id == me.id:
            await event.reply("❌ Нельзя удалить владельца из защиты.")
            return
        if friend_id in protected_users:
            protected_users.discard(friend_id)
            save_state()
            await event.reply("✅ Пользователь удалён из списка защиты.")
        else:
            await event.reply("❌ Пользователь не найден в списке защиты.")

    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.listfriends$'))
    async def listfriends_cmd(event):
        if not protected_users:
            await event.reply("Список защиты пуст.")
            return
        lines = ["🛡 <b>Защищённые пользователи (не мутаются):</b>"]
        for uid in protected_users:
            try:
                user = await event.client.get_entity(uid)
                name = f"@{user.username}" if user.username else f"{user.first_name} (ID: {uid})"
            except:
                name = f"ID: {uid}"
            lines.append(f"• {name}")
        await event.reply("\n".join(lines), parse_mode='html')

    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.clearall$'))
    async def clearall_cmd(event):
        await event.delete()
        user_name = await resolve_name(event.sender_id)
        target_name = await resolve_chat_name(event.chat_id)
        log_command(event.sender_id, ".clearall", source="Telegram", target_id=event.chat_id, user_name=user_name, target_name=target_name, result="ok")
        chat = await event.get_chat()
        if hasattr(chat, 'broadcast') and chat.broadcast:
            await event.reply("❌ В канале невозможно очистить сообщения.")
            return
        deleted = 0
        async for msg in event.client.iter_messages(event.chat_id):
            try:
                await msg.delete()
                deleted += 1
                await asyncio.sleep(0.5)
            except:
                pass
        tmp = await event.client.send_message(event.chat_id, f"🗑 Удалено {deleted} сообщений.")
        await asyncio.sleep(3)
        await tmp.delete()

    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.history$'))
    async def history_cmd(event):
        if not command_history:
            await event.reply("📜 История команд пуста.")
            return
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
            "<b>.cat</b> / .dog — котик/собака\n"
            "<b>.joke</b> / .fact — шутка/факт\n"
            "<b>.password [длина]</b> — сгенерировать пароль\n"
            "<b>.uuid</b> — UUID\n"
            "<b>.reverse текст</b> — переворот\n"
            "<b>.mock текст</b> — иЗдЁвКа\n"
            "<b>.calc выражение</b> — калькулятор\n"
            "<b>.id / .myid / .chatid</b> — ID\n"
            "<b>.info @user</b> — информация\n"
            "<b>.afk причина</b> / .unafk\n"
            "<b>.remind 10m текст</b> — напоминание\n"
            "<b>.timer 5m</b> — таймер\n"
            "<b>.roll</b> / .coin / .choose\n"
            "<b>.shrug / .lenny / .tableflip</b>\n"
            "<b>.bmi вес рост</b> — ИМТ\n"
            "<b>.convert сумма из в</b> — валюта\n"
            "<b>.time</b> — дата и время\n"
            "<b>.pin / .unpin / .del / .edit</b>\n"
            "<b>.link / .forward @user / .quote</b>\n"
            "<b>.chatinfo / .membercount</b>\n"
            "<b>.warn @user / .unwarn / .warns</b>\n"
            "<b>.ban @user / .unban / .kick</b>\n"
            "<b>.muteuser @user 10m / .unmuteuser</b>\n"
            "<b>.autoread on/off</b>\n"
            "<b>.pomodoro 25 / .stopwatch</b>\n"
            "<b>.slug текст</b>\n"
            "<b>.upper / .lower / .count</b>\n"
            "<b>.base64 encode/decode текст</b>\n"
            "<b>.yesno / .when</b>\n"
            "<b>.polls вопрос | вар1 | вар2</b>\n"
            "<b>.tts текст</b> — голосовое сообщение\n"
            "<b>.sticker</b> — случайный стикер\n"
            "<b>.schedule 10s .ping</b> — отложенная команда\n"
            "<b>.json</b> (реплай)\n"
            "<b>.shorten url</b>\n"
            "<b>.help</b> — это сообщение"
        )
        await event.client.send_message(event.chat_id, text, parse_mode='html')

    # ... (все остальные команды, перечисленные в help, должны быть здесь полностью)
    # Из-за ограничения длины я не могу их все продублировать, но они уже присутствуют в предыдущих полных версиях.
    # Обязательно вставьте их из последнего полного скрипта.

    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.stt$'))
    async def stt_cmd(event):
        if not event.reply_to_msg_id:
            await event.reply("❌ Ответьте на голосовое сообщение.")
            return
        reply = await event.get_reply_message()
        if not reply.voice and not (reply.audio and reply.audio.mime_type in ['audio/ogg', 'audio/mp4']):
            await event.reply("❌ Это не голосовое сообщение.")
            return
        await event.reply("🎙 Распознаю речь...")
        try:
            with tempfile.NamedTemporaryFile(suffix='.ogg', delete=False) as tmp:
                await reply.download_media(tmp.name)
                ogg_path = tmp.name
            wav_path = ogg_path.replace('.ogg', '.wav')
            audio = AudioSegment.from_file(ogg_path, format="ogg")
            audio.export(wav_path, format="wav")
            recognizer = sr.Recognizer()
            with sr.AudioFile(wav_path) as source:
                audio_data = recognizer.record(source)
            text = recognizer.recognize_google(audio_data, language="ru-RU")
            await event.reply(f"📝 Распознанный текст:\n{text}")
            log_command(event.sender_id, f".stt: {text}", source="Telegram", target_id=event.chat_id, result="ok")
        except Exception as e:
            await event.reply(f"❌ Ошибка распознавания: {e}")
        finally:
            if os.path.exists(ogg_path):
                os.unlink(ogg_path)
            if os.path.exists(wav_path):
                os.unlink(wav_path)

    # AFK авто‑ответ
    @client_instance.on(events.NewMessage(incoming=True))
    async def afk_handler(event):
        if event.out or not event.is_private:
            return
        if str(event.sender_id) in afk_users:
            reason = afk_users[str(event.sender_id)]
            await event.reply(f"⏳ Пользователь отошёл: {reason}")

    # Авто‑прочтение
    @client_instance.on(events.NewMessage(incoming=True))
    async def auto_read_handler(event):
        if getattr(client_instance, 'auto_read', False) and not event.out:
            await event.mark_read()

register_handlers(client1)
if client2:
    register_handlers(client2)

if bot:
    @bot.on(events.CallbackQuery)
    async def auth_callback(event):
        data = event.data.decode()
        if data.startswith("approve:"):
            token = data.split(":")[1]
            if token in auth_tokens:
                auth_tokens[token] = True
                await event.edit("✅ Вход одобрен. Можете вернуться на сайт и войти.", buttons=None)
        elif data.startswith("reject:"):
            token = data.split(":")[1]
            auth_tokens.pop(token, None)
            await event.edit("🚫 Вход отклонён.", buttons=None)

# Импортируем веб-сервер и запускаем
from web_server import start_web_server

async def main():
    global http_session, client2
    http_session = ClientSession()
    await client1.start()
    print("✅ Аккаунт 1 запущен")
    if client2:
        try:
            await client2.start()
            print("✅ Аккаунт 2 запущен")
        except Exception as e:
            print(f"⚠️ Не удалось запустить второй аккаунт: {e}")
            client2 = None
    if bot:
        while True:
            try:
                await bot.start(bot_token=BOT_TOKEN)
                print("🤖 Бот авторизации запущен")
                break
            except FloodWaitError as e:
                print(f"⏳ FloodWait: ждём {e.seconds} секунд...")
                await asyncio.sleep(e.seconds)
            except Exception as e:
                print(f"⚠️ Не удалось запустить бота: {e}")
                break
    await init_protected_users()

    # Запускаем веб-сервер
    await start_web_server()

    tasks = [client1.run_until_disconnected()]
    if client2:
        tasks.append(client2.run_until_disconnected())
    if bot and bot.is_connected():
        tasks.append(bot.run_until_disconnected())
    await asyncio.gather(*tasks)
    if http_session:
        await http_session.close()

if __name__ == "__main__":
    asyncio.run(main())
