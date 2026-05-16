#!/usr/bin/env python3
"""
PyMessenger — Сервер (аккаунты: ник + пароль)
pip install websockets
python server.py
"""

import asyncio, json, time, os, sqlite3, hashlib
import websockets
from websockets.server import WebSocketServerProtocol

PORT     = int(os.environ.get("PORT", 8765))
DB       = "accounts.db"
CODE_TTL = 300

def init_db():
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS accounts (
        name     TEXT PRIMARY KEY,
        password TEXT NOT NULL,
        created  INTEGER NOT NULL
    )""")
    con.commit(); con.close()

def hash_pw(pw): return hashlib.sha256(pw.encode()).hexdigest()

def db_register(name, pw):
    try:
        con = sqlite3.connect(DB)
        con.execute("INSERT INTO accounts VALUES (?,?,?)",
                    (name, hash_pw(pw), int(time.time())))
        con.commit(); return True, "ok"
    except sqlite3.IntegrityError:
        return False, "Этот ник уже занят!"
    finally:
        try: con.close()
        except: pass

def db_login(name, pw):
    con = sqlite3.connect(DB)
    row = con.execute("SELECT password FROM accounts WHERE name=?",
                      (name,)).fetchone()
    con.close()
    if not row: return False, "Пользователь не найден!"
    if row[0] != hash_pw(pw): return False, "Неверный пароль!"
    return True, "ok"

# ── сервер ────────────────────────────────────────────────────────────────────
clients = {}  # ws -> {"name": str}

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
                else:
                    await send(ws, {"type":"auth_error","text":err})

            elif t == "login":
                uname = msg.get("name","").strip()
                pw    = msg.get("password","")
                ok, err = db_login(uname, pw)
                if ok:
                    name = uname; authed = True
                    clients[ws] = {"name": name}
                    await send(ws, {"type":"auth_ok","name":name})
                    await broadcast({"type":"system","text":f"🟢 {name} вошёл в чат"}, exclude=ws)
                    await broadcast_users()
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

    except websockets.ConnectionClosed:
        pass
    finally:
        if authed:
            clients.pop(ws, None)
            await broadcast({"type":"system","text":f"🔴 {name} покинул чат"})
            await broadcast_users()

async def main():
    init_db()
    print(f"✅ Сервер запущен на порту {PORT}")
    async with websockets.serve(handler, "0.0.0.0", PORT, max_size=50*1024*1024):
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
