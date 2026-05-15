#!/usr/bin/env python3
"""
PyMessenger — Сервер v3 (аккаунты через email)
pip install websockets
python server.py

Перед запуском задай переменные окружения:
  MAIL_FROM  — твой gmail адрес (например bot@gmail.com)
  MAIL_PASS  — пароль приложения Google (16 символов без пробелов)

На Render задаётся в разделе Environment.
"""

import asyncio, json, time, os, sqlite3, hashlib, random, smtplib
from email.mime.text import MIMEText
import websockets
from websockets.server import WebSocketServerProtocol

PORT      = int(os.environ.get("PORT", 8765))
DB        = "accounts.db"
MAIL_FROM = os.environ.get("MAIL_FROM", "")
MAIL_PASS = os.environ.get("MAIL_PASS", "")
CODE_TTL  = 300   # код живёт 5 минут

# ── БД ────────────────────────────────────────────────────────────────────────
def init_db():
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS accounts (
        email    TEXT PRIMARY KEY,
        name     TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        created  INTEGER NOT NULL
    )""")
    con.commit(); con.close()

def hash_pw(pw): return hashlib.sha256(pw.encode()).hexdigest()

def db_register(email, name, pw):
    try:
        con = sqlite3.connect(DB)
        con.execute("INSERT INTO accounts VALUES (?,?,?,?)",
                    (email.lower(), name, hash_pw(pw), int(time.time())))
        con.commit(); return True, "ok"
    except sqlite3.IntegrityError as e:
        if "email" in str(e): return False, "Эта почта уже зарегистрирована!"
        return False, "Этот ник уже занят!"
    finally:
        try: con.close()
        except: pass

def db_login(email, pw):
    con = sqlite3.connect(DB)
    row = con.execute("SELECT name, password FROM accounts WHERE email=?",
                      (email.lower(),)).fetchone()
    con.close()
    if not row: return False, None, "Аккаунт с такой почтой не найден!"
    if row[1] != hash_pw(pw): return False, None, "Неверный пароль!"
    return True, row[0], "ok"

def db_email_exists(email):
    con = sqlite3.connect(DB)
    row = con.execute("SELECT 1 FROM accounts WHERE email=?",
                      (email.lower(),)).fetchone()
    con.close()
    return row is not None

def db_name_exists(name):
    con = sqlite3.connect(DB)
    row = con.execute("SELECT 1 FROM accounts WHERE name=?",
                      (name,)).fetchone()
    con.close()
    return row is not None

# ── EMAIL ─────────────────────────────────────────────────────────────────────
def send_code(to_email, code):
    if not MAIL_FROM or not MAIL_PASS:
        # режим разработки — просто печатаем код
        print(f"[DEV] Код для {to_email}: {code}")
        return True, "ok"
    try:
        msg = MIMEText(
            f"Твой код подтверждения PyMessenger: {code}\n\n"
            f"Код действителен 5 минут.\n"
            f"Если ты не регистрировался — просто игнорируй это письмо.",
            "plain", "utf-8"
        )
        msg["Subject"] = f"Код подтверждения: {code}"
        msg["From"]    = MAIL_FROM
        msg["To"]      = to_email
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as s:
            s.ehlo()
            s.starttls()
            s.ehlo()
            s.login(MAIL_FROM, MAIL_PASS)
            s.sendmail(MAIL_FROM, to_email, msg.as_string())
        return True, "ok"
    except Exception as e:
        print(f"[EMAIL ERROR] {e}")
        return False, f"Не удалось отправить письмо: {e}"

# ── СЕРВЕР ────────────────────────────────────────────────────────────────────
clients  = {}   # ws -> {"name": str}
# Временные коды: email -> {"code": str, "expires": int, "action": "register"|"login"}
pending  = {}

async def send(ws, obj):
    try: await ws.send(json.dumps(obj, ensure_ascii=False))
    except: pass

async def broadcast(obj, exclude=None):
    for ws in list(clients):
        if ws is not exclude: await send(ws, obj)

async def broadcast_users():
    names = [v["name"] for v in clients.values()]
    await broadcast({"type": "user_list", "users": names})

def find_ws(name):
    for ws, info in clients.items():
        if info["name"] == name: return ws
    return None

async def handler(ws: WebSocketServerProtocol):
    authed = False
    name   = ""
    try:
        async for raw in ws:
            try: msg = json.loads(raw)
            except: continue
            t = msg.get("type")

            # ══ AUTH FLOW ════════════════════════════════════════════════════

            # 1. Пользователь вводит email → отправляем код
            if t == "auth_email":
                email  = msg.get("email","").strip().lower()
                action = msg.get("action","register")  # "register" или "login"

                if action == "login" and not db_email_exists(email):
                    await send(ws, {"type":"auth_error",
                                    "text":"Аккаунт с такой почтой не найден!"})
                    continue
                if action == "register" and db_email_exists(email):
                    await send(ws, {"type":"auth_error",
                                    "text":"Эта почта уже зарегистрирована! Войди."})
                    continue

                code = str(random.randint(100000, 999999))
                pending[email] = {"code": code,
                                   "expires": int(time.time()) + CODE_TTL,
                                   "action": action}
                ok, err = send_code(email, code)
                if ok:
                    await send(ws, {"type":"auth_code_sent", "email": email})
                else:
                    await send(ws, {"type":"auth_error", "text": err})

            # 2. Пользователь вводит код
            elif t == "auth_verify":
                email = msg.get("email","").strip().lower()
                code  = msg.get("code","").strip()
                p     = pending.get(email)
                if not p:
                    await send(ws, {"type":"auth_error",
                                    "text":"Сначала запроси код!"}); continue
                if int(time.time()) > p["expires"]:
                    pending.pop(email, None)
                    await send(ws, {"type":"auth_error",
                                    "text":"Код устарел! Запроси новый."}); continue
                if p["code"] != code:
                    await send(ws, {"type":"auth_error",
                                    "text":"Неверный код!"}); continue
                # код верный
                pending[email]["verified"] = True
                if p["action"] == "register":
                    await send(ws, {"type":"auth_need_profile", "email": email})
                else:
                    # логин — спросим пароль
                    await send(ws, {"type":"auth_need_password", "email": email})

            # 3a. Регистрация — пользователь вводит ник + пароль
            elif t == "auth_register":
                email    = msg.get("email","").strip().lower()
                username = msg.get("name","").strip()
                pw       = msg.get("password","")
                p        = pending.get(email)
                if not p or not p.get("verified"):
                    await send(ws, {"type":"auth_error",
                                    "text":"Сначала подтверди email!"}); continue
                if len(username) < 2:
                    await send(ws, {"type":"auth_error",
                                    "text":"Ник минимум 2 символа!"}); continue
                if len(pw) < 6:
                    await send(ws, {"type":"auth_error",
                                    "text":"Пароль минимум 6 символов!"}); continue
                if db_name_exists(username):
                    await send(ws, {"type":"auth_error",
                                    "text":"Этот ник уже занят!"}); continue
                ok, err = db_register(email, username, pw)
                if ok:
                    pending.pop(email, None)
                    name = username; authed = True
                    clients[ws] = {"name": name}
                    await send(ws, {"type":"auth_ok", "name": name})
                    await broadcast({"type":"system",
                                     "text":f"🟢 {name} вошёл в чат"}, exclude=ws)
                    await broadcast_users()
                else:
                    await send(ws, {"type":"auth_error", "text": err})

            # 3b. Вход — пользователь вводит пароль
            elif t == "auth_login":
                email = msg.get("email","").strip().lower()
                pw    = msg.get("password","")
                p     = pending.get(email)
                if not p or not p.get("verified"):
                    await send(ws, {"type":"auth_error",
                                    "text":"Сначала подтверди email!"}); continue
                ok, uname, err = db_login(email, pw)
                if ok:
                    pending.pop(email, None)
                    name = uname; authed = True
                    clients[ws] = {"name": name}
                    await send(ws, {"type":"auth_ok", "name": name})
                    await broadcast({"type":"system",
                                     "text":f"🟢 {name} вошёл в чат"}, exclude=ws)
                    await broadcast_users()
                else:
                    await send(ws, {"type":"auth_error", "text": err})

            # ══ CHAT (только авторизованным) ═════════════════════════════════
            elif not authed:
                await send(ws, {"type":"auth_error", "text":"Сначала войди!"})

            elif t == "message":
                text = msg.get("text","").strip()
                if text:
                    await broadcast({"type":"message", "name":name,
                                     "text":text, "time":time.strftime("%H:%M")})

            elif t == "private":
                to, text = msg.get("to"), msg.get("text","").strip()
                tw = find_ws(to); ts = time.strftime("%H:%M")
                if tw and text:
                    await send(tw,  {"type":"private",      "from":name,"text":text,"time":ts})
                    await send(ws,  {"type":"private_sent", "to":to,   "text":text,"time":ts})

            elif t == "file":
                to = msg.get("to")
                payload = {**msg, "from":name, "time":time.strftime("%H:%M")}
                if to:
                    tw = find_ws(to)
                    if tw:
                        await send(tw, payload)
                        await send(ws, {**payload, "type":"file_sent","to":to})
                else:
                    await broadcast(payload, exclude=ws)

            elif t in ("call_request","call_response","call_end"):
                to = msg.get("to"); tw = find_ws(to)
                if tw: await send(tw, {**msg,"from":name})

    except websockets.ConnectionClosed:
        pass
    finally:
        if authed:
            clients.pop(ws, None)
            await broadcast({"type":"system","text":f"🔴 {name} покинул чат"})
            await broadcast_users()
        print(f"[-] {name or 'unknown'} отключился")

async def main():
    init_db()
    print(f"✅ Сервер запущен на порту {PORT}")
    if not MAIL_FROM:
        print("⚠️  MAIL_FROM не задан — коды будут печататься в консоль (режим разработки)")
    async with websockets.serve(handler, "0.0.0.0", PORT, max_size=50*1024*1024):
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
