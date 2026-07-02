import os
import asyncio
import time
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from deep_translator import GoogleTranslator
from aiohttp import web

# ========== КОНФИГ ИЗ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ ==========
API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
SESSION_STRING_1 = os.environ["SESSION_STRING"]
SESSION_STRING_2 = os.environ.get("SESSION_STRING_FRIEND")
PORT = int(os.environ.get("PORT", 10000))

# Глобальные клиенты
client1 = TelegramClient(StringSession(SESSION_STRING_1), API_ID, API_HASH)
client2 = None
if SESSION_STRING_2:
    try:
        client2 = TelegramClient(StringSession(SESSION_STRING_2), API_ID, API_HASH)
    except Exception as e:
        print(f"⚠️ Ошибка создания второго клиента: {e}. Бот продолжит работу с одним аккаунтом.")
        client2 = None

# ========== ОБЩИЕ ДАННЫЕ ==========
muted_chats = set()
auto_reply_chats = {}
auto_reply_global = {'enabled': False, 'text': '⏳ Привет! Я сейчас не в сети, отвечу позже.'}
last_replied = {}
protected_users = set()

async def init_protected_users():
    me1 = await client1.get_me()
    protected_users.add(me1.id)
    print(f"🛡 Владелец 1: {me1.id}")
    if client2:
        try:
            me2 = await client2.get_me()
            protected_users.add(me2.id)
            print(f"🛡 Владелец 2: {me2.id}")
        except Exception as e:
            print(f"⚠️ Не удалось получить данные второго аккаунта: {e}")

# ========== ОБРАБОТЧИКИ (без изменений) ==========
def register_handlers(client_instance):
    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.mute$'))
    async def mute_cmd(event):
        chat = await event.get_chat()
        if hasattr(chat, 'broadcast') and chat.broadcast:
            return
        muted_chats.add(event.chat_id)
        await event.delete()
        text = (
            "🔇 <b>Пользователь заглушен</b>\n"
            "Все его сообщения будут <i>мгновенно удаляться</i>.\n\n"
            "Нажмите кнопку ниже, чтобы размутить."
        )
        buttons = [Button.inline("🔊 Размутить", b"unmute")]
        await event.client.send_message(event.chat_id, text, buttons=buttons, parse_mode='html')

    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.unmute$'))
    async def unmute_cmd(event):
        chat = await event.get_chat()
        if hasattr(chat, 'broadcast') and chat.broadcast:
            return
        muted_chats.discard(event.chat_id)
        await event.delete()
        await event.client.send_message(event.chat_id, "🔊 <b>Мут снят.</b> Сообщения больше не удаляются.", parse_mode='html')

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
        chat_id = event.chat_id
        muted_chats.discard(chat_id)
        await event.edit(
            "🔊 <b>Мут снят.</b> Сообщения больше не удаляются.",
            buttons=None,
            parse_mode='html'
        )

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

    # ---------- ДРУЗЬЯ ----------
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

    # ---------- .help ----------
    @client_instance.on(events.NewMessage(outgoing=True, pattern=r'^\.help$'))
    async def help_cmd(event):
        await event.delete()
        text = (
            "📖 <b>Список команд юзербота:</b>\n\n"
            "<b>.mute</b> — заглушить чат (удалять входящие, кроме защищённых)\n"
            "<b>.unmute</b> — снять мут\n"
            "<b>.avto</b> — включить автоответчик в этом чате (только ЛС)\n"
            "<b>.avto Текст</b> — автоответчик со своим текстом\n"
            "<b>.avto all</b> — глобальный автоответчик\n"
            "<b>.avto all Текст</b> — глобальный со своим текстом\n"
            "<b>.unavto</b> — выключить автоответчик\n"
            "<b>.unavto all</b> — выключить глобальный\n"
            "<b>.spam N текст</b> — спам текстом N раз (до 50)\n"
            "<b>.ping</b> — проверить пинг\n"
            "<b>.purge [N]</b> — удалить свои последние N сообщений\n"
            "<b>.save текст</b> — заметка в Избранное\n"
            "<b>.get</b> — последняя заметка\n"
            "<b>.stats</b> — статистика чата\n"
            "<b>.tr код текст</b> — перевод\n"
            "<b>.addfriend</b> (в ЛС) — добавить собеседника в защиту от мута\n"
            "<b>.delfriend</b> (в ЛС) — удалить из защиты\n"
            "<b>.listfriends</b> — список защищённых\n"
            "<b>.help</b> — это сообщение\n\n"
            "<i>Владельцы бота всегда защищены. При .mute сообщения от защищённых не удаляются.</i>"
        )
        await event.client.send_message(event.chat_id, text, parse_mode='html')

# Регистрируем обработчики на клиентах
register_handlers(client1)
if client2:
    register_handlers(client2)

# ========== HTTP-СЕРВЕР ==========
async def handle_health(request):
    return web.Response(text="OK", status=200)

async def run_http_server():
    app = web.Application()
    app.router.add_get('/', handle_health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    print(f"HTTP сервер запущен на порту {PORT}")
    await site.start()
    while True:
        await asyncio.sleep(3600)

# ========== ЗАПУСК ==========
async def main():
    global client2   # <-- вот это исправляет UnboundLocalError
    await client1.start()
    print("✅ Аккаунт 1 запущен")
    if client2:
        try:
            await client2.start()
            print("✅ Аккаунт 2 запущен")
        except Exception as e:
            print(f"⚠️ Не удалось запустить второй аккаунт: {e}")
            client2 = None

    await init_protected_users()

    tasks = [client1.run_until_disconnected(), run_http_server()]
    if client2:
        tasks.append(client2.run_until_disconnected())
    await asyncio.gather(*tasks)

if __name__ == '__main__':
    asyncio.run(main())
