#!/usr/bin/env python3
"""
PyMessenger — Сервер
Деплой на Render.com (бесплатно):
  1. Залей server.py + requirements.txt на GitHub (в один репозиторий)
  2. Зайди на render.com → New → Web Service → выбери репо
  3. Build Command:  pip install -r requirements.txt
     Start Command:  python server.py
  4. После деплоя скопируй URL (xxxx.onrender.com) в client.py → SERVER_HOST
"""

import asyncio, json, time, os
import websockets
from websockets.server import WebSocketServerProtocol

PORT = int(os.environ.get("PORT", 8765))

clients: dict = {}   # ws -> {"name": str}

async def send(ws, obj):
    try: await ws.send(json.dumps(obj, ensure_ascii=False))
    except: pass

async def broadcast(obj, exclude=None):
    for ws in list(clients):
        if ws is not exclude:
            await send(ws, obj)

async def broadcast_users():
    names = [v["name"] for v in clients.values()]
    await broadcast({"type": "user_list", "users": names})

def find_ws(name):
    for ws, info in clients.items():
        if info["name"] == name:
            return ws
    return None

async def handler(ws: WebSocketServerProtocol):
    name = f"User_{id(ws) % 9999}"
    clients[ws] = {"name": name}
    try:
        async for raw in ws:
            try: msg = json.loads(raw)
            except: continue
            t = msg.get("type")

            if t == "join":
                name = msg.get("name", name).strip()[:24] or name
                clients[ws]["name"] = name
                await send(ws, {"type": "system", "text": f"Добро пожаловать, {name}! 👋"})
                await broadcast({"type": "system", "text": f"🟢 {name} вошёл в чат"}, exclude=ws)
                await broadcast_users()

            elif t == "message":
                text = msg.get("text", "").strip()
                if text:
                    await broadcast({"type": "message", "name": name,
                                     "text": text, "time": time.strftime("%H:%M")})

            elif t == "private":
                to, text = msg.get("to"), msg.get("text", "").strip()
                tw = find_ws(to)
                ts = time.strftime("%H:%M")
                if tw and text:
                    await send(tw,  {"type": "private",      "from": name, "text": text, "time": ts})
                    await send(ws,  {"type": "private_sent", "to":   to,   "text": text, "time": ts})

            elif t == "file":
                to = msg.get("to")
                payload = {**msg, "from": name, "time": time.strftime("%H:%M")}
                if to:
                    tw = find_ws(to)
                    if tw:
                        await send(tw, payload)
                        await send(ws, {**payload, "type": "file_sent", "to": to})
                else:
                    await broadcast(payload, exclude=ws)

            elif t in ("call_request", "call_response", "call_end"):
                to = msg.get("to")
                tw = find_ws(to)
                if tw: await send(tw, {**msg, "from": name})

    except websockets.ConnectionClosed:
        pass
    finally:
        clients.pop(ws, None)
        await broadcast({"type": "system", "text": f"🔴 {name} покинул чат"})
        await broadcast_users()
        print(f"[-] {name} отключился")

async def main():
    print(f"✅ Сервер запущен на порту {PORT}")
    async with websockets.serve(handler, "0.0.0.0", PORT, max_size=50*1024*1024):
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
