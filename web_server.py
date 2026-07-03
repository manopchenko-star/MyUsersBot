import asyncio, json, base64, uuid, time, os
from datetime import datetime
from aiohttp import web, WSMsgType
from telethon import Button

# Импортируем глобальные переменные и функции из bot.py
from bot import (
    client1, client2, bot, http_session,
    muted_chats, protected_users, command_history, auth_tokens, ws_clients,
    invites, admins, ADMIN_USER, ADMIN_PASS, GUEST_KEY, PORT, ACC2_DISPLAY_NAME,
    save_state, save_invites, save_admins, broadcast_state,
    resolve_name, resolve_chat_name, log_command,
    get_chat_names, get_user_names, hash_password,
    auto_reply_chats, auto_reply_global
)

HTML_LOGIN = f"""<html><head><meta charset="utf-8"><title>Вход</title>
<style>
body {{ font-family: 'Segoe UI', sans-serif; background: #1a1a2e; color: #e0e0e0; display: flex; justify-content: center; align-items: center; height: 100vh; }}
form {{ background: #16213e; padding: 2rem; border-radius: 12px; box-shadow: 0 0 20px rgba(0,0,0,0.5); }}
input {{ display: block; width: 100%; margin-bottom: 1rem; padding: 0.5rem; border: none; border-radius: 6px; }}
button {{ background: #0f3460; color: white; border: none; padding: 0.7rem 1.5rem; border-radius: 6px; cursor: pointer; margin-right: 10px; }}
button:hover {{ background: #e94560; }}
.bot-login {{ background: #16213e; padding: 2rem; border-radius: 12px; margin-top: 20px; text-align: center; }}
</style></head><body>
<div>
<form action="/auth/login" method="post">
<h2>Вход по паролю</h2>
Логин: <input type="text" name="username" value="{ADMIN_USER}"><br>
Пароль: <input type="password" name="password"><br>
<button type="submit">Войти с паролем</button>
</form>
<div class="bot-login">
<button onclick="loginViaBot()">Войти через Telegram бота</button>
</div>
</div>
<script>
async function loginViaBot() {{
    const resp = await fetch('/auth/request_bot');
    const data = await resp.json();
    if (data.token) {{
        document.cookie = "auth_token=" + data.token + "; path=/";
        alert("Запрос отправлен в Telegram. Нажмите 'Принять' в сообщении бота, затем обновите страницу.");
        const interval = setInterval(async () => {{
            const check = await fetch('/auth/check_token?token=' + data.token);
            const status = await check.json();
            if (status.approved) {{
                clearInterval(interval);
                window.location.href = '/dashboard';
            }}
        }}, 3000);
    }} else {{
        alert("Ошибка: " + data.error);
    }}
}}
</script>
</body></html>"""

HTML_DASHBOARD = """<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Userbot Panel</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
  <style>
    body { background: #0d1117; color: #c9d1d9; font-family: 'Segoe UI', sans-serif; }
    .navbar { background: #161b22; border-bottom: 1px solid #30363d; }
    .nav-tabs .nav-link { color: #8b949e; border: none; }
    .nav-tabs .nav-link.active { background: #1c2128; color: #e94560; border-bottom: 2px solid #e94560; }
    .tab-content { background: #1c2128; padding: 20px; border-radius: 0 0 12px 12px; }
    .card-stat { background: #161b22; border: 1px solid #30363d; border-radius: 8px; }
    .card-stat .icon { font-size: 2rem; }
    .btn-custom { background: #e94560; color: white; border: none; }
    .btn-custom:hover { background: #c93750; }
    .list-group-item { background: #161b22; border-color: #30363d; color: #c9d1d9; }
    .table { color: #c9d1d9; }
    .table thead th { border-color: #30363d; }
    .table tbody td { border-color: #30363d; }
    .badge-ok { background: #238636; }
    .badge-error { background: #da3633; }
    .notification { position: fixed; top: 20px; right: 20px; z-index: 999; }
  </style>
</head>
<body>
  <nav class="navbar navbar-expand-lg">
    <div class="container-fluid">
      <a class="navbar-brand text-white" href="#"><i class="fas fa-robot me-2"></i>Userbot Panel</a>
      <div class="d-flex align-items-center">
        <span class="navbar-text me-3"><i class="fas fa-user-circle me-1"></i>{user}</span>
        <span class="navbar-text me-3">Акк1: <span id="acc1Name">—</span></span>
        <span class="navbar-text me-3">Акк2: <span id="acc2Name">—</span></span>
        <a href="/logout" class="btn btn-outline-light btn-sm"><i class="fas fa-sign-out-alt"></i></a>
      </div>
    </div>
  </nav>
  <div class="container-fluid mt-3">
    <div id="notification" class="notification alert d-none"></div>
    <div id="statsCards" class="row mb-3"></div>
    <ul class="nav nav-tabs" role="tablist">
      <li class="nav-item"><button class="nav-link active" data-bs-toggle="tab" data-bs-target="#muted"><i class="fas fa-microphone-slash me-1"></i>Чаты в муте</button></li>
      <li class="nav-item"><button class="nav-link" data-bs-toggle="tab" data-bs-target="#protected"><i class="fas fa-shield-alt me-1"></i>Защищённые</button></li>
      <li class="nav-item"><button class="nav-link" data-bs-toggle="tab" data-bs-target="#commands"><i class="fas fa-terminal me-1"></i>Команды</button></li>
      <li class="nav-item"><button class="nav-link" data-bs-toggle="tab" data-bs-target="#history"><i class="fas fa-history me-1"></i>История</button></li>
      <li class="nav-item"><button class="nav-link" data-bs-toggle="tab" data-bs-target="#admins"><i class="fas fa-users-cog me-1"></i>Администраторы</button></li>
      <li class="nav-item"><button class="nav-link" data-bs-toggle="tab" data-bs-target="#invites"><i class="fas fa-link me-1"></i>Приглашения</button></li>
    </ul>
    <div class="tab-content">
      <div class="tab-pane fade show active" id="muted"><h5>Чаты в муте</h5><div id="mutedList" class="list-group"></div></div>
      <div class="tab-pane fade" id="protected"><h5>Защищённые</h5><div id="protectedList" class="list-group"></div></div>
      <div class="tab-pane fade" id="commands">
        <h5>Выполнить команду</h5>
        <form action="/send_cmd" method="post" class="row g-3">
          <div class="col-md-4"><label>Аккаунт</label><select name="account" id="accountSelect" class="form-select"></select></div>
          <div class="col-md-4"><label>Чат</label><input type="text" name="target" class="form-control" placeholder="@user или ID"></div>
          <div class="col-md-4"><label>Команда</label>
            <select name="command" id="cmdSelect" class="form-select" onchange="updateArgsPlaceholder()">
              <option value=".mute">.mute</option><option value=".unmute">.unmute</option>
              <option value=".spam">.spam</option><option value=".ping">.ping</option>
              <option value=".purge">.purge</option><option value=".clearall">.clearall</option>
              <option value=".stats">.stats</option><option value=".tr">.tr</option>
              <option value=".avto">.avto</option><option value=".help">.help</option>
            </select>
          </div>
          <div class="col-md-8"><label>Аргументы</label><input type="text" name="args" id="argsInput" class="form-control" placeholder="например, 3 Привет"></div>
          <div class="col-md-4"><button type="submit" class="btn btn-custom mt-4">Отправить</button></div>
        </form>
      </div>
      <div class="tab-pane fade" id="history">
        <h5>История</h5>
        <div class="mb-2">
          <label>Фильтр по аккаунту:</label>
          <select id="accountFilter" class="form-select w-auto d-inline" onchange="renderHistory()">
            <option value="all">Все</option><option value="acc1">Акк1</option><option value="acc2">Акк2</option>
          </select>
          <button class="btn btn-sm btn-custom ms-2" onclick="toggleAllHistory()">Показать все</button>
        </div>
        <div class="table-responsive">
          <table class="table table-dark table-striped">
            <thead><tr><th>Время</th><th>Источник</th><th>Пользователь</th><th>Команда</th><th>Цель</th><th>Рез.</th></tr></thead>
            <tbody id="historyBody"></tbody>
          </table>
        </div>
      </div>
      <div class="tab-pane fade" id="admins">
        <h5>Управление администраторами</h5>
        <form action="/add_admin" method="post" class="row g-3 mb-4">
          <div class="col-md-3"><input type="text" name="username" class="form-control" placeholder="Логин" required></div>
          <div class="col-md-3"><input type="password" name="password" class="form-control" placeholder="Пароль" required></div>
          <div class="col-md-3"><select name="role" class="form-select"><option value="admin">Админ</option><option value="readonly">Чтение</option></select></div>
          <div class="col-md-3"><button type="submit" class="btn btn-custom">Добавить</button></div>
        </form>
        <div id="adminsList" class="list-group"></div>
      </div>
      <div class="tab-pane fade" id="invites">
        <h5>Приглашения</h5>
        <form action="/create_invite" method="post" class="row g-3 mb-4">
          <div class="col-auto"><select name="role" class="form-select"><option value="readonly">Только чтение</option><option value="admin">Администратор</option></select></div>
          <div class="col-auto"><button type="submit" class="btn btn-custom">Создать</button></div>
        </form>
        <div id="invitesList" class="list-group"></div>
      </div>
    </div>
  </div>
  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
  <script>
    let ws;
    let fullHistory = [];
    let acc1Name = "Аккаунт 1", acc2Name = "Аккаунт 2";
    let showAllHistory = false;
    const MAX_VISIBLE = 20;

    function showNotification(text, isError = false) {
      const notif = document.getElementById('notification');
      notif.textContent = text;
      notif.className = 'notification alert ' + (isError ? 'alert-danger' : 'alert-success');
      notif.classList.remove('d-none');
      setTimeout(() => notif.classList.add('d-none'), 5000);
    }

    window.addEventListener('load', () => {
      const params = new URLSearchParams(location.search);
      if (params.has('msg')) {
        showNotification(params.get('msg'), false);
        window.history.replaceState({}, document.title, location.pathname);
      } else if (params.has('error')) {
        showNotification(params.get('error'), true);
        window.history.replaceState({}, document.title, location.pathname);
      }
      connectWS();
    });

    function connectWS() {
      ws = new WebSocket('wss://' + location.host + '/ws');
      ws.onmessage = function(event) {
        const data = JSON.parse(event.data);
        updateUI(data);
      };
      ws.onclose = function() { setTimeout(connectWS, 3000); };
    }

    function updateUI(data) {
      document.getElementById('acc1Name').textContent = data.acc1_name || 'Аккаунт 1';
      document.getElementById('acc2Name').textContent = data.acc2_name || 'не подключён';
      acc1Name = data.acc1_name || 'Аккаунт 1';
      acc2Name = data.acc2_name;

      let sel = document.getElementById('accountSelect');
      sel.innerHTML = '';
      sel.add(new Option(acc1Name, '1'));
      if (acc2Name) sel.add(new Option(acc2Name, '2'));

      let filter = document.getElementById('accountFilter');
      filter.options[0].text = 'Все';
      filter.options[1].text = acc1Name;
      if (acc2Name) filter.options[2].text = acc2Name;

      fullHistory = data.history || [];
      renderHistory();

      let mutedHtml = '';
      for (let id in data.chat_names) {
        mutedHtml += `<a class="list-group-item list-group-item-dark d-flex justify-content-between">${data.chat_names[id]} <button class="btn btn-sm btn-custom" onclick="unmuteChat(${id})">Размутить</button></a>`;
      }
      document.getElementById('mutedList').innerHTML = mutedHtml || 'Нет чатов в муте';

      let protectedHtml = '';
      for (let id in data.user_names) {
        protectedHtml += `<span class="list-group-item list-group-item-dark">${data.user_names[id]}</span>`;
      }
      document.getElementById('protectedList').innerHTML = protectedHtml || 'Нет защищённых';

      let adminsHtml = '';
      if (data.admins) {
        data.admins.forEach(user => {
          adminsHtml += `<div class="list-group-item list-group-item-dark d-flex justify-content-between">${user} <a href="/delete_admin?user=${user}" class="btn btn-sm btn-danger">Удалить</a></div>`;
        });
      }
      document.getElementById('adminsList').innerHTML = adminsHtml || 'Нет дополнительных администраторов';

      let invitesHtml = '';
      for (let key in data.invites) {
        const inv = data.invites[key];
        const role = inv.role === 'admin' ? 'Админ' : 'Чтение';
        invitesHtml += `<div class="list-group-item list-group-item-dark d-flex justify-content-between">Ключ: ${key} (${role}) <a href="/delete_invite?key=${key}" class="btn btn-sm btn-danger">Удалить</a></div>`;
      }
      document.getElementById('invitesList').innerHTML = invitesHtml || 'Нет приглашений';
    }

    function unmuteChat(chatId) {
      fetch('/unmute?chat_id=' + chatId + '&account=' + document.querySelector('select[name="account"]').value)
        .then(() => { location.reload(); });
    }

    function renderHistory() {
      const filter = document.getElementById('accountFilter').value;
      let filtered = fullHistory;
      if (filter === 'acc1') filtered = fullHistory.filter(e => e.user_name === acc1Name);
      else if (filter === 'acc2') filtered = fullHistory.filter(e => e.user_name === acc2Name);
      if (!showAllHistory) filtered = filtered.slice(-MAX_VISIBLE);
      let html = '';
      filtered.forEach(e => {
        html += `<tr>
          <td>${e.time.substr(11,8)}</td>
          <td>${e.source}</td>
          <td>${e.user_name}</td>
          <td>${e.command}</td>
          <td>${e.target_name || ''}</td>
          <td><span class="badge ${e.result === 'ok' ? 'badge-ok' : 'badge-error'}">${e.result || ''}</span></td>
        </tr>`;
      });
      document.getElementById('historyBody').innerHTML = html || '<tr><td colspan="6">Нет записей</td></tr>';
    }

    function toggleAllHistory() {
      showAllHistory = !showAllHistory;
      document.querySelector('#history button').textContent = showAllHistory ? 'Показать последние 20' : 'Показать все';
      renderHistory();
    }

    function updateArgsPlaceholder() {
      const cmd = document.getElementById('cmdSelect').value;
      const inp = document.getElementById('argsInput');
      switch(cmd) {
        case '.spam': inp.placeholder = 'число текст'; break;
        case '.purge': inp.placeholder = 'число (по умолч. 10)'; break;
        case '.tr': inp.placeholder = 'код_языка текст'; break;
        case '.avto': inp.placeholder = 'текст или all текст'; break;
        default: inp.placeholder = ''; break;
      }
    }

    updateArgsPlaceholder();
  </script>
</body>
</html>"""

HTML_GUEST = """<html><head><meta charset="utf-8"><title>Гостевой просмотр</title>
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
  for (let id in data.chat_names) { html += '<li>' + data.chat_names[id] + '</li>'; }
  html += '</ul><h3>Защищённые:</h3><ul>';
  for (let id in data.user_names) { html += '<li>' + data.user_names[id] + '</li>'; }
  html += '</ul><h3>История:</h3><table border="1" cellpadding="4"><tr><th>Время</th><th>Источник</th><th>Пользователь</th><th>Команда</th><th>Цель</th></tr>';
  data.history.forEach(e => {
    html += `<tr><td>${e.time.substr(11,8)}</td><td>${e.source}</td><td>${e.user_name}</td><td>${e.command}</td><td>${e.target_name||''}</td></tr>`;
  });
  html += '</table>';
  document.getElementById('content').innerHTML = html;
};
</script>
</body></html>"""

# ----- ОБРАБОТЧИКИ ВЕБ-СЕРВЕРА -----
async def check_auth(request):
    auth = request.headers.get("Authorization")
    if auth and auth.startswith("Basic "):
        credentials = base64.b64decode(auth[6:]).decode()
        user, pwd = credentials.split(":", 1)
        if user in admins and admins[user]["password"] == hash_password(pwd):
            return user
    token = request.cookies.get("auth_token")
    if token and auth_tokens.get(token) == True:
        return "admin"
    invite_token = request.cookies.get("invite_token")
    if invite_token and invite_token in invites:
        return invites[invite_token].get("role", "readonly")
    raise web.HTTPUnauthorized(headers={"WWW-Authenticate": "Basic realm=\"Userbot Panel\""})

async def dashboard(request):
    user = await check_auth(request)
    is_admin = (user == "admin" or (user in admins and admins[user]["role"] == "admin"))
    return web.Response(text=HTML_DASHBOARD.format(user=user, is_admin=is_admin), content_type="text/html")

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
    if username in admins and admins[username]["password"] == hash_password(password):
        resp = web.HTTPFound("/dashboard")
        resp.set_cookie("auth_token", "password_ok")
        return resp
    return web.HTTPFound("/login?error=1")

async def logout(request):
    resp = web.HTTPFound("/login")
    resp.del_cookie("auth_token")
    resp.del_cookie("invite_token")
    return resp

async def request_bot_auth(request):
    if not bot:
        return web.json_response({"error": "Бот не настроен"})
    token = str(uuid.uuid4())
    auth_tokens[token] = "pending"
    me1 = await client1.get_me()
    try:
        await bot.send_message(
            me1.id,
            "🔐 <b>Запрос на вход</b>\nКто-то пытается войти в панель управления. Разрешить?",
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
        return web.json_response({"approved": auth_tokens[token] == True})
    return web.json_response({"approved": False})

async def add_admin(request):
    user = await check_auth(request)
    if user != "admin" and (user not in admins or admins[user]["role"] != "admin"):
        raise web.HTTPFound("/dashboard?error=Только+главный+админ")
    data = await request.post()
    new_user = data.get("username", "").strip()
    new_pass = data.get("password", "").strip()
    role = data.get("role", "readonly")
    if not new_user or not new_pass:
        raise web.HTTPFound("/dashboard?error=Логин+и+пароль+обязательны")
    admins[new_user] = {"password": hash_password(new_pass), "role": role}
    save_admins()
    await broadcast_state()
    raise web.HTTPFound("/dashboard?msg=Пользователь+добавлен")

async def delete_admin(request):
    user = await check_auth(request)
    if user != "admin" and (user not in admins or admins[user]["role"] != "admin"):
        raise web.HTTPFound("/dashboard?error=Только+главный+админ")
    del_user = request.query.get("user", "")
    if del_user == ADMIN_USER:
        raise web.HTTPFound("/dashboard?error=Нельзя+удалить+главного+админа")
    if del_user in admins:
        del admins[del_user]
        save_admins()
        await broadcast_state()
    raise web.HTTPFound("/dashboard?msg=Пользователь+удалён")

async def create_invite(request):
    user = await check_auth(request)
    if user != "admin" and (user not in admins or admins[user]["role"] != "admin"):
        raise web.HTTPFound("/dashboard?error=Только+админ")
    data = await request.post()
    role = data.get("role", "readonly")
    key = str(uuid.uuid4())[:8]
    invites[key] = {"role": role, "created": datetime.now().isoformat()}
    save_invites()
    await broadcast_state()
    raise web.HTTPFound("/dashboard?msg=Инвайт+создан")

async def delete_invite(request):
    user = await check_auth(request)
    if user != "admin" and (user not in admins or admins[user]["role"] != "admin"):
        raise web.HTTPFound("/dashboard?error=Только+админ")
    key = request.query.get("key", "")
    if key in invites:
        del invites[key]
        save_invites()
        await broadcast_state()
    raise web.HTTPFound("/dashboard?msg=Инвайт+удалён")

async def unmute_handler(request):
    user = await check_auth(request)
    if user == "readonly":
        raise web.HTTPFound("/dashboard?error=Недостаточно+прав")
    chat_id = int(request.query["chat_id"])
    muted_chats.discard(chat_id)
    save_state()
    account = request.query.get("account", "1")
    if account == "2" and client2:
        client = client2
        acc_name = (await client2.get_me()).first_name or "Аккаунт2"
    else:
        client = client1
        acc_name = (await client1.get_me()).first_name or "Аккаунт1"
    target_name = await resolve_chat_name(chat_id)
    log_command(0, f"Размутил чат {chat_id}", source="Web", target_id=chat_id, user_name=acc_name, target_name=target_name, result="ok")
    try:
        await client.send_message(chat_id, "🔊 Администратор размутил этот чат! Берегитесь, он может снова замутить 😈")
    except:
        pass
    await broadcast_state()
    raise web.HTTPFound("/dashboard?msg=Чат+размучен")

async def remove_protected(request):
    user = await check_auth(request)
    if user == "readonly":
        raise web.HTTPFound("/dashboard?error=Недостаточно+прав")
    user_id = int(request.query["user_id"])
    me1 = await client1.get_me()
    me2_id = (await client2.get_me()).id if client2 else None
    if user_id != me1.id and user_id != me2_id:
        protected_users.discard(user_id)
        save_state()
        user_name = await resolve_name(me1.id)
        target_name = await resolve_name(user_id)
        log_command(me1.id, f"Удалил из защиты {user_id}", source="Web", target_id=user_id, user_name=user_name, target_name=target_name, result="ok")
        await broadcast_state()
        raise web.HTTPFound("/dashboard?msg=Пользователь+удалён+из+защиты")
    raise web.HTTPFound("/dashboard?error=Нельзя+удалить+владельца")

async def send_cmd(request):
    user = await check_auth(request)
    if user == "readonly":
        raise web.HTTPFound("/dashboard?error=Недостаточно+прав")
    data = await request.post()
    account = data.get("account", "1")
    target = data.get("target", "").strip()
    command = data.get("command", "").strip()
    args = data.get("args", "").strip()
    if not command:
        raise web.HTTPFound("/dashboard?error=Команда+не+выбрана")
    client = client2 if (account == "2" and client2) else client1
    acc_name = (await client.get_me()).first_name or ("Аккаунт2" if account == "2" else "Аккаунт1")
    target_entity = target if target else 'me'
    target_name = target_entity
    if target_entity == 'me':
        target_name = "Избранное"
    else:
        try:
            chat = await client.get_entity(target_entity)
            target_name = chat.title if hasattr(chat, 'title') else (chat.first_name or target_entity)
        except:
            target_name = target_entity

    result_msg = None
    try:
        if command == ".mute":
            chat = await client.get_entity(target_entity)
            if hasattr(chat, 'broadcast') and chat.broadcast:
                result_msg = "Ошибка: каналы нельзя мутить"
            else:
                muted_chats.add(chat.id)
                save_state()
                await broadcast_state()
                log_command(0, ".mute", source="Web", target_id=chat.id, user_name=acc_name, target_name=target_name, result="ok")
                result_msg = f"Чат {target_name} заглушен"
        elif command == ".unmute":
            chat = await client.get_entity(target_entity)
            muted_chats.discard(chat.id)
            save_state()
            await broadcast_state()
            log_command(0, ".unmute", source="Web", target_id=chat.id, user_name=acc_name, target_name=target_name, result="ok")
            try:
                await client.send_message(target_entity, "🔊 Администратор размутил этот чат! Берегитесь, он может снова замутить 😈")
            except:
                pass
            result_msg = f"Чат {target_name} размучен"
        elif command == ".spam":
            parts = args.split(maxsplit=1)
            if len(parts) == 2:
                count = int(parts[0])
                text = parts[1]
                if count > 50:
                    result_msg = "Ошибка: максимум 50 повторений"
                else:
                    for _ in range(count):
                        await client.send_message(target_entity, text)
                        await asyncio.sleep(0.4)
                    log_command(0, f".spam {count} {text}", source="Web", user_name=acc_name, target_name=target_name, result="ok")
                    result_msg = f"Спам отправлен в {target_name}"
            else:
                result_msg = "Ошибка: укажите число и текст (пример: 3 Привет)"
        elif command == ".ping":
            start = time.time()
            msg = await client.send_message(target_entity, "🏓 Пинг...")
            elapsed = (time.time() - start) * 1000
            await msg.edit(f"🏓 Понг! `{elapsed:.1f}ms`")
            log_command(0, ".ping", source="Web", user_name=acc_name, target_name=target_name, result="ok")
            result_msg = f"Пинг: {elapsed:.1f}ms"
        elif command == ".purge":
            num = int(args) if args else 10
            if num > 200:
                num = 200
            deleted = 0
            async for message in client.iter_messages(target_entity, from_user='me', limit=num):
                try:
                    await message.delete()
                    deleted += 1
                    await asyncio.sleep(0.5)
                except:
                    pass
            tmp = await client.send_message(target_entity, f"🗑 Удалено {deleted} сообщений.")
            await asyncio.sleep(3)
            await tmp.delete()
            log_command(0, f".purge {num}", source="Web", user_name=acc_name, target_name=target_name, result="ok")
            result_msg = f"Удалено {deleted} сообщений в {target_name}"
        elif command == ".clearall":
            deleted = 0
            async for msg in client.iter_messages(target_entity):
                try:
                    await msg.delete()
                    deleted += 1
                    await asyncio.sleep(0.5)
                except:
                    pass
            tmp = await client.send_message(target_entity, f"🗑 Удалено {deleted} сообщений.")
            await asyncio.sleep(3)
            await tmp.delete()
            log_command(0, ".clearall", source="Web", user_name=acc_name, target_name=target_name, result="ok")
            result_msg = f"Удалено {deleted} сообщений в {target_name}"
        elif command == ".stats":
            chat = await client.get_entity(target_entity)
            if hasattr(chat, 'broadcast') and chat.broadcast:
                result_msg = "Ошибка: канал"
            else:
                participants_count = 0
                try:
                    participants_count = (await client.get_participants(chat, limit=0)).total
                except:
                    pass
                text = (
                    f"📊 <b>Статистика чата</b>\n"
                    f"Название: {chat.title}\n"
                    f"ID: {chat.id}\n"
                    f"Участников: {participants_count}"
                )
                await client.send_message(target_entity, text, parse_mode='html')
                log_command(0, ".stats", source="Web", user_name=acc_name, target_name=target_name, result="ok")
                result_msg = f"Статистика отправлена в {target_name}"
        elif command == ".tr":
            parts = args.split(maxsplit=1)
            if len(parts) == 2:
                target_lang, text = parts
                translated = GoogleTranslator(source='auto', target=target_lang).translate(text)
                await client.send_message(target_entity, f"🌐 Перевод ({target_lang}):\n{translated}")
                log_command(0, f".tr {target_lang} {text}", source="Web", user_name=acc_name, target_name=target_name, result="ok")
                result_msg = f"Перевод отправлен в {target_name}"
            else:
                result_msg = "Ошибка: укажите код языка и текст"
        elif command == ".avto":
            if args.startswith("all "):
                auto_reply_global['enabled'] = True
                custom_text = args[4:]
                if custom_text:
                    auto_reply_global['text'] = custom_text
                await client.send_message(target_entity, f"🌐 Глобальный автоответчик включён. Текст: {auto_reply_global['text']}")
                result_msg = "Глобальный автоответчик включён"
            else:
                if target_entity == 'me':
                    result_msg = "Ошибка: автоответчик только в личных сообщениях"
                else:
                    custom_text = args if args else "⏳ Привет! Я сейчас не в сети, отвечу позже."
                    auto_reply_chats[target_entity] = {'enabled': True, 'text': custom_text}
                    await client.send_message(target_entity, f"✅ Автоответчик включён. Текст: {custom_text}")
                    result_msg = f"Автоответчик включён в {target_name}"
            log_command(0, ".avto", source="Web", user_name=acc_name, target_name=target_name, result="ok")
        elif command == ".help":
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
                "<b>.help</b> — это сообщение"
            )
            await client.send_message(target_entity, text, parse_mode='html')
            result_msg = "Справка отправлена"
        else:
            result_msg = "Неизвестная команда"
    except Exception as e:
        log_command(0, f"ОШИБКА: {command} -> {e}", source="Web", user_name=acc_name, target_name=target_name, result=f"error: {e}")
        result_msg = f"Ошибка: {str(e)}"

    if result_msg:
        redirect_url = f"/dashboard?msg={result_msg.replace(' ', '+')}"
    else:
        redirect_url = "/dashboard"
    raise web.HTTPFound(redirect_url)

async def handle_health(request):
    return web.Response(text="OK")

async def websocket_handler(request):
    token = request.cookies.get("auth_token")
    invite_token = request.cookies.get("invite_token")
    if not token and not invite_token:
        return web.Response(status=401)
    if token and token != "password_ok" and auth_tokens.get(token) != True:
        return web.Response(status=401)
    if invite_token and invite_token not in invites:
        return web.Response(status=401)
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    ws_clients.add(ws)
    acc2_name = ACC2_DISPLAY_NAME if ACC2_DISPLAY_NAME else (await client2.get_me()).first_name if client2 else None
    initial = {
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
    await ws.send_str(json.dumps(initial, default=str, ensure_ascii=False))
    try:
        async for msg in ws:
            pass
    finally:
        ws_clients.discard(ws)
    return ws

async def guest_ws_handler(request):
    key = request.query.get("key", "")
    if key != GUEST_KEY:
        return web.Response(status=403)
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    await ws.send_str(json.dumps({
        "muted_chats": list(muted_chats),
        "protected_users": list(protected_users),
        "history": command_history,
        "chat_names": await get_chat_names(),
        "user_names": await get_user_names(),
    }, default=str, ensure_ascii=False))
    await ws.close()
    return ws

app = web.Application()
app.router.add_get("/", handle_health)
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
app.router.add_post("/create_invite", create_invite)
app.router.add_get("/delete_invite", delete_invite)
app.router.add_get("/ws", websocket_handler)
app.router.add_get("/guest-ws", guest_ws_handler)

async def start_web_server():
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"🔐 Панель управления: http://.../dashboard")
    while True:
        await asyncio.sleep(3600)