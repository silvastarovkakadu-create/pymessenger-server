#!/usr/bin/env python3
"""
PyMessenger — Сервер (аккаунты в PostgreSQL — не теряются при перезапуске)

Зависимости:
    pip install websockets psycopg2-binary

Переменные окружения на Render:
    DATABASE_URL — выдаётся автоматически если подключить PostgreSQL на Render
"""

import asyncio, json, time, os, hashlib
import websockets
from websockets.server import WebSocketServerProtocol

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    DB_OK = True
except:
    DB_OK = False

PORT        = int(os.environ.get("PORT", 8765))
DATABASE_URL = os.environ.get("DATABASE_URL", "")
ADMIN       = "ваирт настаяши"
badges      = {}  # name -> badge emoji
banned      = set()  # banned names

# ── БД ────────────────────────────────────────────────────────────────────────
def get_conn():
    return psycopg2.connect(DATABASE_URL, sslmode="require")

def init_db():
    if not DB_OK or not DATABASE_URL:
        print("⚠️  DATABASE_URL не задан — аккаунты не сохраняются!")
        return
    try:
        con = get_conn()
        con.cursor().execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                name     TEXT PRIMARY KEY,
                password TEXT NOT NULL,
                created  BIGINT NOT NULL
            )
        """)
        con.commit(); con.close()
        print("✅ База данных подключена")
    except Exception as e:
        print(f"❌ Ошибка БД: {e}")

def hash_pw(pw): return hashlib.sha256(pw.encode()).hexdigest()

def db_register(name, pw):
    if not DB_OK or not DATABASE_URL:
        return True, "ok"  # без БД просто пускаем
    try:
        con = get_conn()
        cur = con.cursor()
        cur.execute("INSERT INTO accounts VALUES (%s,%s,%s)",
                    (name, hash_pw(pw), int(time.time())))
        con.commit(); con.close()
        return True, "ok"
    except Exception as e:
        try: con.close()
        except: pass
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            return False, "Этот ник уже занят!"
        return False, f"Ошибка: {e}"

def db_login(name, pw):
    if not DB_OK or not DATABASE_URL:
        return True, "ok"  # без БД просто пускаем
    try:
        con = get_conn()
        cur = con.cursor()
        cur.execute("SELECT password FROM accounts WHERE name=%s", (name,))
        row = cur.fetchone(); con.close()
        if not row: return False, "Пользователь не найден!"
        if row[0] != hash_pw(pw): return False, "Неверный пароль!"
        return True, "ok"
    except Exception as e:
        return False, f"Ошибка: {e}"

# ── СЕРВЕР ────────────────────────────────────────────────────────────────────
clients = {}

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

            if t == "register":
                uname = msg.get("name","").strip()[:24]
                pw    = msg.get("password","")
                if uname in banned:
                    await send(ws, {"type":"auth_error","text":"⛔ Ты заблокирован!"}); continue
                if len(uname) < 2:
                    await send(ws, {"type":"auth_error","text":"Ник минимум 2 символа!"}); continue
                if len(pw) < 6:
                    await send(ws, {"type":"auth_error","text":"Пароль минимум 6 символов!"}); continue
                ok, err = db_register(uname, pw)
                if ok:
                    name = uname; authed = True
                    clients[ws] = {"name": name}
                    await send(ws, {"type":"auth_ok","name":name})
                    await broadcast({"type":"system","text":f"🟢 {name} вошёл в чат"}, exclude=ws)
                    await broadcast_users()
                    await send(ws, {"type":"all_badges","badges":badges})
                    is_admin = (name == ADMIN)
                    await send(ws, {"type":"admin_status","is_admin":is_admin})
                else:
                    await send(ws, {"type":"auth_error","text":err})

            elif t == "login":
                uname = msg.get("name","").strip()
                pw    = msg.get("password","")
                if uname in banned:
                    await send(ws, {"type":"auth_error","text":"⛔ Ты заблокирован!"}); continue
                if len(uname) < 2:
                    await send(ws, {"type":"auth_error","text":"Введи ник!"}); continue
                ok, err = db_login(uname, pw)
                if ok:
                    name = uname; authed = True
                    clients[ws] = {"name": name}
                    await send(ws, {"type":"auth_ok","name":name})
                    await broadcast({"type":"system","text":f"🟢 {name} вошёл в чат"}, exclude=ws)
                    await broadcast_users()
                    await send(ws, {"type":"all_badges","badges":badges})
                    is_admin = (name == ADMIN)
                    await send(ws, {"type":"admin_status","is_admin":is_admin})
                else:
                    await send(ws, {"type":"auth_error","text":err})

            elif not authed:
                await send(ws, {"type":"auth_error","text":"Сначала войди!"})

            elif t == "message":
                text = msg.get("text","").strip()
                if text:
                    await broadcast({"type":"message","name":name,
                                     "text":text,"time":time.strftime("%H:%M")})

            elif t == "private":
                to, text = msg.get("to"), msg.get("text","").strip()
                tw = find_ws(to); ts = time.strftime("%H:%M")
                if tw and text:
                    await send(tw,  {"type":"private","from":name,"text":text,"time":ts})
                    await send(ws,  {"type":"private_sent","to":to,"text":text,"time":ts})

            elif t == "file":
                to = msg.get("to")
                payload = {**msg,"from":name,"time":time.strftime("%H:%M")}
                if to:
                    tw = find_ws(to)
                    if tw:
                        await send(tw, payload)
                        await send(ws, {**payload,"type":"file_sent","to":to})
                else:
                    await broadcast(payload, exclude=ws)

            elif t in ("call_request","call_response","call_end"):
                to = msg.get("to"); tw = find_ws(to)
                if tw: await send(tw, {**msg,"from":name})

            elif t == "ban":
                if name == ADMIN:
                    target = msg.get("target","")
                    if target and target != ADMIN:
                        banned.add(target)
                        # kick if online
                        tw = find_ws(target)
                        if tw:
                            await send(tw, {"type":"kicked","text":"⛔ Ты заблокирован администратором!"})
                            try: await tw.close()
                            except: pass
                        await broadcast({"type":"system","text":f"⛔ {target} заблокирован"})
                        await broadcast_users()
                else:
                    await send(ws, {"type":"system","text":"⛔ Нет прав!"})

            elif t == "unban":
                if name == ADMIN:
                    target = msg.get("target","")
                    banned.discard(target)
                    await send(ws, {"type":"system","text":f"✅ {target} разблокирован"})
                else:
                    await send(ws, {"type":"system","text":"⛔ Нет прав!"})

            elif t == "set_badge":
                if name == ADMIN:
                    target = msg.get("target","")
                    badge  = msg.get("badge","")
                    if badge:
                        badges[target] = badge
                    else:
                        badges.pop(target, None)
                    # broadcast badge update to all
                    await broadcast({"type":"badge_update",
                                     "target": target,
                                     "badge": badge})
                else:
                    await send(ws, {"type":"system","text":"⛔ Нет прав!"})

            elif t == "get_badges":
                await send(ws, {"type":"all_badges","badges": badges})

    except websockets.ConnectionClosed:
        pass
    finally:
        if authed:
            clients.pop(ws, None)
            await broadcast({"type":"system","text":f"🔴 {name} покинул чат"})
            await broadcast_users()

async def main():
    print(f"DB URL: {DATABASE_URL[:40] if DATABASE_URL else 'ПУСТО'}")
    print(f"DB_OK: {DB_OK}")
    init_db()
    print(f"✅ Сервер запущен на порту {PORT}")
    async with websockets.serve(handler, "0.0.0.0", PORT, max_size=50*1024*1024):
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
