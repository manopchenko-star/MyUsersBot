import os, asyncio, json, time, base64, uuid
from pathlib import Path
from datetime import datetime
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from deep_translator import GoogleTranslator
from aiohttp import web, WSMsgType

# ---------- КОНФИГ ИЗ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ ----------
API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
SESSION_STRING_1 = os.environ["SESSION_STRING"]
SESSION_STRING_2 = os.environ.get("SESSION_STRING_FRIEND")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
GUEST_KEY = os.environ.get("GUEST_KEY", "friend123")
PORT = int(os.environ.get("PORT", 10000))
ADMIN_USER = "admin"
ADMIN_PASS = os.environ.get("ADMIN_PASSWORD", "Anopchenko2011")
DATA_FILE = Path("userbot_data.json")
LOG_FILE = Path("command_history.json")

# Глобальные клиенты
client1 = TelegramClient(StringSession(SESSION_STRING_1), API_ID, API_HASH)
client2 = None
if SESSION_STRING_2:
    try:
        client2 = TelegramClient(StringSession(SESSION_STRING_2), API_ID, API_HASH)
    except Exception as e:
        print(f"⚠️ Ошибка второго клиента: {e}")
        client2 = None

# Бот для авторизации (файловая сессия)
bot = None
if BOT_TOKEN:
    bot = TelegramClient("auth_bot_session", API_ID, API_HASH)

# ========== ОБЩИЕ ДАННЫЕ ==========
muted_chats = set()
auto_reply_chats = {}
auto_reply_global = {'enabled': False, 'text': '⏳ Привет! Я сейчас не в сети, отвечу позже.'}
last_replied = {}
protected_users = set()
command_history = []
auth_tokens = {}
ws_clients = set()

def save_state():
    data = {
        "muted_chats": list(muted_chats),
        "protected_users": list(protected_users),
    }
    DATA_FILE.write_text(json.dumps(data), encoding="utf-8")

def load_state():
    global muted_chats, protected_users
    if DATA_FILE.exists():
        try:
            data = json.loads(DATA_FILE.read_text())
            muted_chats = set(data.get("muted_chats", []))
            protected_users = set(data.get("protected_users", []))
        except:
            pass

def log_command(user, command, source="Telegram"):
    global command_history
    entry = {"time": datetime.now().isoformat(), "user": user, "command": command, "source": source}
    command_history.append(entry)
    if len(command_history) > 50:
        command_history = command_history[-50:]
    LOG_FILE.write_text(json.dumps(command_history), encoding="utf-8")
    asyncio.ensure_future(broadcast_state())

async def broadcast_state():
    data = {
        "muted_chats": list(muted_chats),
        "protected_users": list(protected_users),
        "history": command_history[-10:],
        "chat_names": await get_chat_names(),
        "user_names": await get_user_names(),
    }
    msg = json.dumps(data, default=str)
    for ws in list(ws_clients):
        try:
            await ws.send_str(msg)
        except:
            ws_clients.discard(ws)

async def get_chat_names():
    names = {}
    for cid in muted_chats:
        try:
            chat = await client1.get_entity(cid)
            name = chat.title if hasattr(chat, 'title') else f"{chat.first_name} {chat.last_name or ''}".strip()
            names[str(cid)] = name
        except:
            names[str(cid)] = str(cid)
    return names

async def get_user_names():
    names = {}
    for uid in protected_users:
        try:
            user = await client1.get_entity(uid)
            name = f"@{user.username}" if user.username else f"{user.first_name} (ID: {uid})"
            names[str(uid)] = name
        except:
            names[str(uid)] = f"ID: {uid}"
    return names

def load_history():
    global command_history
    if LOG_FILE.exists():
        try:
            command_history = json.loads(LOG_FILE.read_text())
        except:
            pass

load_state()
load_history()

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

# ========== ОБРАБОТЧИКИ TELEGRAM ==========
def register_handlers(client_instance):
    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.mute$'))
    async def mute_cmd(event):
        chat = await event.get_chat()
        if hasattr(chat, 'broadcast') and chat.broadcast:
            return
        muted_chats.add(event.chat_id)
        save_state()
        await event.delete()
        log_command(event.sender_id, ".mute", source="Telegram")
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
        log_command(event.sender_id, ".unmute", source="Telegram")
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
        log_command(event.sender_id, "Размутил (кнопка)", source="Telegram")
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
        if not event.is_private or event.out:
            return
        chat_id = event.chat_id
        if last_replied.get(chat_id) == event.id:
            return
        reply_text = None
        if chat_id in auto_reply_chats and auto_reply_chats[chat_id]['enabled']:
            reply_text = auto_reply_chats[chat_id]['text']
        elif auto_reply_global['enabled']:
            reply_text = auto_reply_global['text']
        if reply_text:
            await asyncio.sleep(1)
            await event.client.send_message(chat_id, reply_text)
            last_replied[chat_id] = event.id

    # ---------- .spam ----------
    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.spam\s+(\d+)\s+(.*)'))
    async def spam_cmd(event):
        count = int(event.pattern_match.group(1))
        text = event.pattern_match.group(2)
        await event.delete()
        log_command(event.sender_id, f".spam {count} {text}", source="Telegram")
        if count > 50:
            await event.client.send_message(event.chat_id, "⚠️ Максимум 50 повторений за раз.")
            return
        for _ in range(count):
            await event.client.send_message(event.chat_id, text)
            await asyncio.sleep(0.4)

    # ---------- .ping ----------
    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.ping$'))
    async def ping_cmd(event):
        start = time.time()
        msg = await event.reply("🏓 Пинг...")
        elapsed = (time.time() - start) * 1000
        await msg.edit(f"🏓 Понг! `{elapsed:.1f}ms`")

    # ---------- .purge ----------
    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.purge(?:\s+(\d+))?'))
    async def purge_cmd(event):
        num = int(event.pattern_match.group(1)) if event.pattern_match.group(1) else 10
        if num > 200:
            num = 200
        await event.delete()
        log_command(event.sender_id, f".purge {num}", source="Telegram")
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

    # ---------- .save / .get ----------
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

    # ---------- .stats ----------
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

    # ---------- .tr ----------
    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.tr\s+([a-z]{2})\s+(.*)'))
    async def translate_cmd(event):
        target_lang = event.pattern_match.group(1)
        text = event.pattern_match.group(2)
        try:
            translated = GoogleTranslator(source='auto', target=target_lang).translate(text)
            await event.reply(f"🌐 Перевод ({target_lang}):\n{translated}")
        except Exception as e:
            await event.reply(f"❌ Ошибка перевода: {e}")

    # ---------- ДРУЗЬЯ (защита от мута) ----------
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

    # ---------- .clearall ----------
    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.clearall$'))
    async def clearall_cmd(event):
        await event.delete()
        log_command(event.sender_id, ".clearall", source="Telegram")
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

    # ---------- .history ----------
    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.history$'))
    async def history_cmd(event):
        if not command_history:
            await event.reply("📜 История команд пуста.")
            return
        text = "📜 <b>Последние команды</b>:\n"
        for entry in command_history[-10:]:
            text += f"• {entry['time'][:19]} — {entry['source']} {entry['user']}: {entry['command']}\n"
        await event.reply(text, parse_mode='html')

    # ---------- .help ----------
    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.help$'))
    async def help_cmd(event):
        await event.delete()
        text = (
            "📖 <b>Список команд юзербота:</b>\n\n"
            "<b>.mute</b> — заглушить чат\n"
            "<b>.unmute</b> — снять мут\n"
            "<b>.clearall</b> — удалить все сообщения в чате\n"
            "<b>.avto</b> / .avto all / .unavto — автоответчик\n"
            "<b>.spam N текст</b> — повторить текст N раз\n"
            "<b>.ping</b> — проверить пинг\n"
            "<b>.purge [N]</b> — удалить свои последние N сообщений\n"
            "<b>.save текст</b> / .get — заметки\n"
            "<b>.stats</b> — статистика чата\n"
            "<b>.tr код текст</b> — перевод\n"
            "<b>.addfriend</b> / .delfriend / .listfriends\n"
            "<b>.history</b> — история последних команд\n"
            "<b>.help</b> — это сообщение"
        )
        await event.client.send_message(event.chat_id, text, parse_mode='html')

# Регистрируем обработчики
register_handlers(client1)
if client2:
    register_handlers(client2)

# ---------- БОТ АВТОРИЗАЦИИ ----------
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

# ---------- HTTP СЕРВЕР ----------
async def check_auth(request):
    auth = request.headers.get("Authorization")
    if auth and auth.startswith("Basic "):
        credentials = base64.b64decode(auth[6:]).decode()
        user, pwd = credentials.split(":", 1)
        if user == ADMIN_USER and pwd == ADMIN_PASS:
            return
    token = request.cookies.get("auth_token")
    if token and auth_tokens.get(token) == True:
        return
    raise web.HTTPUnauthorized(headers={"WWW-Authenticate": "Basic realm=\"Userbot Panel\""})

async def dashboard(request):
    await check_auth(request)
    return web.Response(text=HTML_DASHBOARD, content_type="text/html")

async def guest_view(request):
    key = request.query.get("key", "")
    if key != GUEST_KEY:
        return web.Response(text="Неверный ключ доступа", status=403)
    return web.Response(text=HTML_GUEST, content_type="text/html")

async def login_page(request):
    return web.Response(text=HTML_LOGIN, content_type="text/html")

async def auth_login(request):
    data = await request.post()
    username = data.get("username", "")
    password = data.get("password", "")
    if username == ADMIN_USER and password == ADMIN_PASS:
        resp = web.HTTPFound("/dashboard")
        resp.set_cookie("auth_token", "password_ok")
        return resp
    return web.HTTPFound("/login?error=1")

async def request_bot_auth(request):
    if not bot:
        return web.json_response({"error": "Бот не настроен"})
    token = str(uuid.uuid4())
    auth_tokens[token] = "pending"
    me1 = await client1.get_me()
    try:
        await bot.send_message(
            me1.id,
            f"🔐 <b>Запрос на вход</b>\nКто-то пытается войти в панель управления. Разрешить?",
            buttons=[
                [Button.inline("✅ Принять", f"approve:{token}")],
                [Button.inline("❌ Отклонить", f"reject:{token}")]
            ],
            parse_mode='html'
        )
        return web.json_response({"token": token})
    except Exception as e:
        auth_tokens.pop(token, None)
        return web.json_response({"error": str(e)})

async def check_token(request):
    token = request.query.get("token")
    if token and token in auth_tokens:
        approved = auth_tokens[token] == True
        return web.json_response({"approved": approved})
    return web.json_response({"approved": False})

async def unmute_handler(request):
    await check_auth(request)
    chat_id = int(request.query["chat_id"])
    muted_chats.discard(chat_id)
    save_state()
    account = request.query.get("account", "1")
    log_command(account, f"Размутил чат {chat_id}", source="Web")
    await broadcast_state()
    raise web.HTTPFound("/dashboard")

async def remove_protected(request):
    await check_auth(request)
    user_id = int(request.query["user_id"])
    me1 = await client1.get_me()
    me2_id = (await client2.get_me()).id if client2 else None
    if user_id != me1.id and user_id != me2_id:
        protected_users.discard(user_id)
        save_state()
        log_command("admin", f"Удалил из защиты {user_id}", source="Web")
        await broadcast_state()
    raise web.HTTPFound("/dashboard")

async def send_cmd(request):
    await check_auth(request)
    data = await request.post()
    cmd = data.get("cmd", "").strip()
    account = data.get("account", "1")
    if not cmd:
        raise web.HTTPFound("/dashboard")
    if account == "2" and client2:
        await client2.send_message("me", cmd)
        log_command("Аккаунт2", cmd, source="Web")
    else:
        await client1.send_message("me", cmd)
        log_command("Аккаунт1", cmd, source="Web")
    raise web.HTTPFound("/dashboard")

async def handle_health(request):
    return web.Response(text="OK")

# WebSocket для админов
async def websocket_handler(request):
    token = request.cookies.get("auth_token")
    if not token or (token != "password_ok" and auth_tokens.get(token) != True):
        return web.Response(status=401)
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    ws_clients.add(ws)
    await ws.send_str(json.dumps({
        "muted_chats": list(muted_chats),
        "protected_users": list(protected_users),
        "history": command_history[-10:],
        "chat_names": await get_chat_names(),
        "user_names": await get_user_names(),
    }, default=str))
    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                pass
            elif msg.type == WSMsgType.ERROR:
                print(f"WebSocket error: {ws.exception()}")
    finally:
        ws_clients.discard(ws)
    return ws

# WebSocket для гостей (одноразовое состояние)
async def guest_ws_handler(request):
    key = request.query.get("key", "")
    if key != GUEST_KEY:
        return web.Response(status=403)
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    await ws.send_str(json.dumps({
        "muted_chats": list(muted_chats),
        "protected_users": list(protected_users),
        "history": command_history[-10:],
        "chat_names": await get_chat_names(),
        "user_names": await get_user_names(),
    }, default=str))
    await ws.close()
    return ws

# HTML ШАБЛОНЫ
HTML_LOGIN = """
<html><head><meta charset="utf-8"><title>Вход</title>
<style>
body { font-family: 'Segoe UI', sans-serif; background: #1a1a2e; color: #e0e0e0; display: flex; justify-content: center; align-items: center; height: 100vh; }
form { background: #16213e; padding: 2rem; border-radius: 12px; box-shadow: 0 0 20px rgba(0,0,0,0.5); }
input { display: block; width: 100%; margin-bottom: 1rem; padding: 0.5rem; border: none; border-radius: 6px; }
button { background: #0f3460; color: white; border: none; padding: 0.7rem 1.5rem; border-radius: 6px; cursor: pointer; }
button:hover { background: #e94560; }
</style></head><body>
<form action="/auth/login" method="post">
<h2>Вход</h2>
Логин: <input type="text" name="username" value="admin"><br>
Пароль: <input type="password" name="password"><br>
<button type="submit">Войти с паролем</button>
</form>
</body></html>"""

HTML_DASHBOARD = """
<html><head><meta charset="utf-8"><title>Userbot Panel</title>
<style>
body { font-family: 'Segoe UI', sans-serif; background: #1a1a2e; color: #e0e0e0; margin: 0; padding: 20px; }
.tabs { display: flex; gap: 10px; margin-bottom: 20px; }
.tab { background: #16213e; padding: 10px 20px; border-radius: 8px; cursor: pointer; }
.tab.active { background: #e94560; }
.content { background: #0f3460; padding: 20px; border-radius: 12px; }
button { background: #e94560; color: white; border: none; padding: 5px 15px; border-radius: 6px; cursor: pointer; }
button:hover { opacity: 0.8; }
select, input { padding: 5px; border-radius: 4px; border: none; }
ul { list-style: none; padding: 0; }
li { margin: 8px 0; }
</style>
</head><body>
<h1>Userbot Panel</h1>
<div class="tabs">
  <div class="tab active" onclick="showTab('muted')">Чаты в муте</div>
  <div class="tab" onclick="showTab('protected')">Защищённые</div>
  <div class="tab" onclick="showTab('commands')">Команды</div>
  <div class="tab" onclick="showTab('history')">История</div>
</div>
<div id="muted" class="content">
  <h2>Чаты в муте</h2>
  <ul id="mutedList"></ul>
</div>
<div id="protected" class="content" style="display:none">
  <h2>Защищённые пользователи</h2>
  <ul id="protectedList"></ul>
</div>
<div id="commands" class="content" style="display:none">
  <h2>Выполнить команду</h2>
  <form action="/send_cmd" method="post">
    <select name="account">
      <option value="1">Аккаунт 1</option>
      <option value="2">Аккаунт 2</option>
    </select>
    <input type="text" name="cmd" placeholder=".ping или .spam 3 Привет" style="width:300px">
    <button type="submit">Отправить</button>
  </form>
</div>
<div id="history" class="content" style="display:none">
  <h2>Последние действия</h2>
  <pre id="historyLog"></pre>
</div>

<script>
let ws;
function connectWS() {
  ws = new WebSocket('wss://' + location.host + '/ws');
  ws.onmessage = function(event) {
    const data = JSON.parse(event.data);
    updateUI(data);
  };
  ws.onclose = function() { setTimeout(connectWS, 3000); };
}
function updateUI(data) {
  let mutedHtml = '';
  for (let id in data.chat_names) {
    mutedHtml += `<li>${data.chat_names[id]} <button onclick="unmuteChat(${id})">Размутить</button></li>`;
  }
  document.getElementById('mutedList').innerHTML = mutedHtml || '<li>Пусто</li>';

  let protectedHtml = '';
  for (let id in data.user_names) {
    protectedHtml += `<li>${data.user_names[id]}</li>`;
  }
  document.getElementById('protectedList').innerHTML = protectedHtml || '<li>Пусто</li>';

  let hist = '';
  data.history.forEach(e => {
    hist += `[${e.time.substr(11,8)}] ${e.source} ${e.user}: ${e.command}\n`;
  });
  document.getElementById('historyLog').textContent = hist || 'Нет записей';
}
function unmuteChat(chatId) {
  fetch('/unmute?chat_id=' + chatId + '&account=' + document.querySelector('select[name="account"]').value)
    .then(() => {});
}
function showTab(tab) {
  document.querySelectorAll('.content').forEach(el => el.style.display = 'none');
  document.getElementById(tab).style.display = 'block';
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  event.target.classList.add('active');
}
connectWS();
</script>
</body></html>"""

HTML_GUEST = """
<html><head><meta charset="utf-8"><title>Гостевой просмотр</title>
<style>body { font-family: 'Segoe UI', sans-serif; background: #1a1a2e; color: #e0e0e0; padding: 20px; }
ul { list-style: none; } li { margin: 5px 0; }</style>
</head><body>
<h1>Состояние бота (только просмотр)</h1>
<div id="content"></div>
<script>
let ws = new WebSocket('wss://' + location.host + '/guest-ws?key=' + (new URL(location)).searchParams.get('key'));
ws.onmessage = function(event) {
  const data = JSON.parse(event.data);
  let html = '<h3>Чаты в муте:</h3><ul>';
  for (let id in data.chat_names) {
    html += '<li>' + data.chat_names[id] + '</li>';
  }
  html += '</ul><h3>Защищённые:</h3><ul>';
  for (let id in data.user_names) {
    html += '<li>' + data.user_names[id] + '</li>';
  }
  html += '</ul><h3>История:</h3><pre>';
  data.history.forEach(e => {
    html += `[${e.time.substr(11,8)}] ${e.source} ${e.user}: ${e.command}\n`;
  });
  html += '</pre>';
  document.getElementById('content').innerHTML = html;
};
</script>
</body></html>"""

app = web.Application()
app.router.add_get("/", handle_health)
app.router.add_get("/login", login_page)
app.router.add_post("/auth/login", auth_login)
app.router.add_get("/auth/request_bot", request_bot_auth)
app.router.add_get("/auth/check_token", check_token)
app.router.add_get("/dashboard", dashboard)
app.router.add_get("/guest", guest_view)
app.router.add_get("/unmute", unmute_handler)
app.router.add_get("/remove_protected", remove_protected)
app.router.add_post("/send_cmd", send_cmd)
app.router.add_get("/ws", websocket_handler)
app.router.add_get("/guest-ws", guest_ws_handler)

async def run_http():
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"🔐 Панель управления: http://.../dashboard")
    while True:
        await asyncio.sleep(3600)

# ========== ЗАПУСК ==========
async def main():
    global client2
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
        await bot.start(bot_token=BOT_TOKEN)
        print("🤖 Бот авторизации запущен")
    await init_protected_users()

    tasks = [client1.run_until_disconnected(), run_http()]
    if client2:
        tasks.append(client2.run_until_disconnected())
    if bot:
        tasks.append(bot.run_until_disconnected())
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
