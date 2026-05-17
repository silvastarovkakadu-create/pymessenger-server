#!/usr/bin/env python3
"""
BobeGram🫘 — Клиент v4 (единое окно, красивый UI)
pip install websockets pyaudio
python client.py
"""

import tkinter as tk
from tkinter import filedialog, messagebox
import asyncio, threading, json, time, os, base64, struct, socket, math

try:
    import pyaudio
    AUDIO_OK = True
except:
    AUDIO_OK = False

try:
    import websockets
except:
    pass

SERVER_HOST = "pymessenger-server.onrender.com"
SERVER_PORT = 443
USE_SSL     = True

CHUNK, RATE, CHANNELS = 1024, 16000, 1

# ── палитра ───────────────────────────────────────────────────────────────────
BG       = "#0a0f1e"
BG2      = "#0d1425"
PANEL    = "#111827"
PANEL2   = "#1a2235"
BORDER   = "#1e2d45"
ACCENT   = "#3b82f6"
ACCENT2  = "#2563eb"
ACCENT3  = "#60a5fa"
GLOW     = "#1d4ed8"
GREEN    = "#10b981"
RED      = "#ef4444"
YELLOW   = "#f59e0b"
TEXT     = "#e2e8f0"
TEXT2    = "#94a3b8"
MUTED    = "#475569"
ME_BG    = "#1e3a5f"
TH_BG    = "#131f35"
WHITE    = "#ffffff"

F  = ("Helvetica", 10)
FB = ("Helvetica", 10, "bold")
FS = ("Helvetica", 9)
FT = ("Helvetica", 14, "bold")
FM = ("Helvetica", 11)
FL = ("Helvetica", 12)
FX = ("Helvetica", 18, "bold")


# ══ NETWORK ══════════════════════════════════════════════════════════════════
class WSClient:
    def __init__(self):
        self.ws=None; self.name=""; self.connected=False
        self.on_msg=None
        self._loop=asyncio.new_event_loop()
        threading.Thread(target=self._loop.run_forever, daemon=True).start()

    def connect(self, host, port, use_ssl):
        proto = "wss" if use_ssl else "ws"
        url   = f"{proto}://{host}" + ("" if use_ssl else f":{port}")
        fut   = asyncio.run_coroutine_threadsafe(self._connect(url), self._loop)
        fut.result(timeout=10)

    async def _connect(self, url):
        ssl = True if url.startswith("wss") else None
        self.ws = await websockets.connect(url, ssl=ssl, max_size=50*1024*1024)
        self.connected = True
        asyncio.ensure_future(self._recv())

    async def _recv(self):
        try:
            async for raw in self.ws:
                if self.on_msg: self.on_msg(json.loads(raw))
        except: pass
        self.connected = False
        if self.on_msg: self.on_msg({"type":"system","text":"⚠️ Соединение прервано"})

    def send(self, obj):
        asyncio.run_coroutine_threadsafe(self._send(obj), self._loop)

    async def _send(self, obj):
        if self.ws: await self.ws.send(json.dumps(obj, ensure_ascii=False))

    def disconnect(self):
        self.connected = False
        if self.ws: asyncio.run_coroutine_threadsafe(self.ws.close(), self._loop)


class VoiceCall:
    def __init__(self):
        self.active=False
        self._pa=self._sin=self._sout=None
        self._peer=self._srv=None
        self.mic_index=None; self.spk_index=None

    def host(self, on_ready):
        def _r():
            self._srv=socket.socket()
            self._srv.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
            self._srv.bind(("0.0.0.0",55100)); self._srv.listen(1)
            self._srv.settimeout(20)
            try:
                conn,_=self._srv.accept()
                self._peer=conn; self._start(); on_ready(True)
            except: on_ready(False)
        threading.Thread(target=_r, daemon=True).start()

    def join(self, ip, on_ready):
        def _r():
            try:
                s=socket.socket(); s.settimeout(10)
                s.connect((ip,55100)); s.settimeout(None)
                self._peer=s; self._start(); on_ready(True)
            except: on_ready(False)
        threading.Thread(target=_r, daemon=True).start()

    def _start(self):
        if not AUDIO_OK: return
        self.active=True
        self._pa=pyaudio.PyAudio()
        ki=dict(input_device_index=self.mic_index) if self.mic_index is not None else {}
        ko=dict(output_device_index=self.spk_index) if self.spk_index is not None else {}
        self._sin=self._pa.open(format=8,channels=CHANNELS,rate=RATE,input=True,frames_per_buffer=CHUNK,**ki)
        self._sout=self._pa.open(format=8,channels=CHANNELS,rate=RATE,output=True,frames_per_buffer=CHUNK,**ko)
        threading.Thread(target=self._tx, daemon=True).start()
        threading.Thread(target=self._rx, daemon=True).start()

    def _tx(self):
        while self.active:
            try:
                d=self._sin.read(CHUNK,exception_on_overflow=False)
                self._peer.sendall(struct.pack("!I",len(d))+d)
            except: break

    def _rx(self):
        while self.active:
            try:
                h=self._ra(4)
                if not h: break
                d=self._ra(struct.unpack("!I",h)[0])
                if d: self._sout.write(d)
            except: break

    def _ra(self, n):
        buf=b""
        while len(buf)<n:
            c=self._peer.recv(n-len(buf))
            if not c: return None
            buf+=c
        return buf

    def stop(self):
        self.active=False
        for s in [self._peer,self._srv]:
            if s:
                try: s.close()
                except: pass
        for st in [self._sin,self._sout]:
            if st:
                try: st.stop_stream(); st.close()
                except: pass
        if self._pa:
            try: self._pa.terminate()
            except: pass
        self._pa=self._sin=self._sout=self._peer=self._srv=None


# ══ MAIN APP ══════════════════════════════════════════════════════════════════
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("BobeGram🫘")
        self.geometry("1000x680")
        self.minsize(800,560)
        self.configure(bg=BG)
        self.protocol("WM_DELETE_WINDOW", self._quit)

        self.ws        = WSClient()
        self.voice     = VoiceCall()
        self.in_call   = False
        self.call_peer = None
        self.my_ip     = self._get_ip()

        self.history   = {"general": []}
        self.unread    = {}
        self.users     = []
        self.active    = "general"
        self._dm_btns  = {}

        self.mic_devices = [("По умолчанию", None)]
        self.spk_devices = [("По умолчанию", None)]
        self.mic_var     = tk.StringVar(value="По умолчанию")
        self.spk_var     = tk.StringVar(value="По умолчанию")
        self._load_audio()
        self.badges   = {}   # name -> badge emoji
        self.is_admin = False

        # текущая панель: "auth", "chat", "settings"
        self._panel = None

        self._build_shell()
        self.after(200, self._show_auth)

    def _load_audio(self):
        if not AUDIO_OK: return
        try:
            pa = pyaudio.PyAudio()
            for i in range(pa.get_device_count()):
                info = pa.get_device_info_by_index(i)
                try:
                    raw = info["name"]
                    name = raw
                    for enc in ['utf-8', 'cp1251', 'latin-1']:
                        try:
                            name = raw.encode('latin-1').decode(enc)
                            if name.isprintable(): break
                        except: pass
                    # keep only printable, shorten
                    name = ''.join(c for c in name if c.isprintable())
                    if len(name) > 45: name = name[:43] + "…"
                    if not name: name = f"Device {i}"
                except: name = f"Device {i}"
                if info["maxInputChannels"]>0: self.mic_devices.append((name,i))
                if info["maxOutputChannels"]>0: self.spk_devices.append((name,i))
            pa.terminate()
        except: pass

    # ── SHELL (постоянные элементы) ───────────────────────────────────────────
    def _build_shell(self):
        # фон с градиентом через canvas
        self._bg_canvas = tk.Canvas(self, highlightthickness=0, bg=BG)
        self._bg_canvas.place(x=0, y=0, relwidth=1, relheight=1)
        self._bg_canvas.bind("<Configure>", self._draw_bg)

        # основной контейнер поверх фона
        self._main = tk.Frame(self, bg=BG, bd=0)
        self._main.place(x=0, y=0, relwidth=1, relheight=1)

    def _draw_bg(self, e=None):
        import random as _rnd
        c = self._bg_canvas
        w = c.winfo_width(); h = c.winfo_height()
        if w < 2 or h < 2: return
        c.delete("all")
        # gradient background
        steps = 60
        for i in range(steps):
            ratio = i / steps
            r = int(0x0a + (0x06-0x0a)*ratio)
            g = int(0x0f + (0x0a-0x0f)*ratio)
            b = int(0x1e + (0x2a-0x1e)*ratio)
            color = f"#{r:02x}{g:02x}{b:02x}"
            y0 = int(h * i / steps)
            y1 = int(h * (i+1) / steps) + 1
            c.create_rectangle(0, y0, w, y1, fill=color, outline="")
        # glow orbs
        for ox,oy,sz,alpha in [(w*0.15,h*0.2,280,"#0d2a5a"),(w*0.85,h*0.75,220,"#0a1f44"),(w*0.6,h*0.15,160,"#091833")]:
            c.create_oval(ox-sz,oy-sz,ox+sz,oy+sz, fill=alpha, outline="")
        # stars
        _rnd.seed(42)
        for _ in range(120):
            sx = _rnd.randint(0, w)
            sy = _rnd.randint(0, h)
            ss = _rnd.choice([1,1,1,2])
            brightness = _rnd.randint(60,180)
            sc = f"#{brightness:02x}{brightness:02x}{brightness+30:02x}"
            c.create_oval(sx,sy,sx+ss,sy+ss, fill=sc, outline="")
        # grid lines subtle
        for gx in range(0, w, 80):
            c.create_line(gx,0,gx,h, fill="#0f1e35", width=1)
        for gy in range(0, h, 80):
            c.create_line(0,gy,w,gy, fill="#0f1e35", width=1)

    # ── ПАНЕЛИ ────────────────────────────────────────────────────────────────
    def _clear_main(self):
        for w in self._main.winfo_children():
            w.destroy()

    # ════════════════════════════════════════════════════════════════════════
    #  AUTH PANEL
    # ════════════════════════════════════════════════════════════════════════
    def _show_auth(self):
        self._panel = "auth"
        self._clear_main()

        # центрированная карточка
        outer = tk.Frame(self._main, bg=BG)
        outer.place(relx=0.5, rely=0.5, anchor="center")

        card = tk.Frame(outer, bg=PANEL, bd=0,
                        highlightthickness=1,
                        highlightbackground=BORDER)
        card.pack(ipadx=40, ipady=36)

        # логотип
        tk.Label(card, text="✈", font=("Helvetica",36),
                 fg=ACCENT3, bg=PANEL).pack(pady=(0,4))
        tk.Label(card, text="BobeGram🫘", font=("Helvetica",22,"bold"),
                 fg=WHITE, bg=PANEL).pack()
        tk.Label(card, text="Мессенджер для своих", font=FS,
                 fg=MUTED, bg=PANEL).pack(pady=(2,24))

        # вкладки
        tab_frame = tk.Frame(card, bg=PANEL2,
                             highlightthickness=1, highlightbackground=BORDER)
        tab_frame.pack(fill=tk.X, padx=0, pady=(0,20))
        self._auth_mode = tk.StringVar(value="register")
        self._tab_reg = self._tab(tab_frame,"Регистрация","register")
        self._tab_log = self._tab(tab_frame,"Войти","login")
        self._tab_reg.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._tab_log.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._upd_tabs()

        # поля
        tk.Label(card, text="Ник", font=FS, fg=TEXT2, bg=PANEL,
                 anchor="w").pack(fill=tk.X)
        self._auth_name = tk.StringVar()
        self._auth_entry(card, self._auth_name, "Придумай ник")

        tk.Label(card, text="Пароль", font=FS, fg=TEXT2, bg=PANEL,
                 anchor="w").pack(fill=tk.X, pady=(10,0))
        self._auth_pw = tk.StringVar()
        pe = self._auth_entry(card, self._auth_pw, "Минимум 6 символов", show="●")
        pe.bind("<Return>", lambda _: self._auth_submit())

        self._auth_err = tk.Label(card, text="", font=FS,
                                   fg=RED, bg=PANEL, wraplength=280)
        self._auth_err.pack(pady=(8,0))

        # кнопка
        self._auth_btn_text = tk.StringVar(value="Зарегистрироваться")
        btn = tk.Button(card, textvariable=self._auth_btn_text,
                        font=FB, bg=ACCENT, fg=WHITE,
                        relief=tk.FLAT, cursor="hand2",
                        activebackground=ACCENT2,
                        command=self._auth_submit)
        btn.pack(fill=tk.X, pady=(16,0), ipady=10)
        self._glow_btn(btn)

        # попытка подключения к серверу
        self.after(100, self._try_connect)

    def _tab(self, parent, text, mode):
        btn = tk.Button(parent, text=text, font=FB,
                        relief=tk.FLAT, cursor="hand2",
                        pady=8, bd=0,
                        command=lambda m=mode: self._set_auth_mode(m))
        return btn

    def _set_auth_mode(self, mode):
        self._auth_mode.set(mode)
        self._upd_tabs()
        self._auth_btn_text.set("Зарегистрироваться" if mode=="register" else "Войти")

    def _upd_tabs(self):
        mode = self._auth_mode.get()
        if hasattr(self, "_tab_reg"):
            self._tab_reg.config(
                bg=ACCENT if mode=="register" else PANEL2,
                fg=WHITE)
            self._tab_log.config(
                bg=ACCENT if mode=="login" else PANEL2,
                fg=WHITE if mode=="login" else MUTED)

    def _auth_entry(self, parent, var, ph, show=None):
        f = tk.Frame(parent, bg=PANEL2,
                     highlightthickness=1, highlightbackground=BORDER)
        f.pack(fill=tk.X, pady=(4,0))
        e = tk.Entry(f, textvariable=var, font=FL,
                     bg=PANEL2, fg=TEXT,
                     insertbackground=ACCENT3,
                     relief=tk.FLAT, bd=8, show=show or "")
        e.pack(fill=tk.X)
        f.bind("<FocusIn>", lambda _: f.config(highlightbackground=ACCENT))
        e.bind("<FocusIn>",  lambda _: f.config(highlightbackground=ACCENT))
        e.bind("<FocusOut>", lambda _: f.config(highlightbackground=BORDER))
        return e

    def _glow_btn(self, btn):
        btn.bind("<Enter>", lambda _: btn.config(bg=ACCENT2))
        btn.bind("<Leave>", lambda _: btn.config(bg=ACCENT))

    def _try_connect(self):
        try:
            self.ws.connect(SERVER_HOST, SERVER_PORT, USE_SSL)
        except Exception as ex:
            if hasattr(self, "_auth_err"):
                self._auth_err.config(
                    text=f"⚠️ Нет связи с сервером\n{ex}", fg=YELLOW)

    def _auth_submit(self):
        name = self._auth_name.get().strip()
        pw   = self._auth_pw.get()
        if len(name)<2:
            self._auth_err.config(text="Ник минимум 2 символа!", fg=RED); return
        if len(pw)<6:
            self._auth_err.config(text="Пароль минимум 6 символов!", fg=RED); return
        self._auth_err.config(text="Подключаюсь…", fg=YELLOW)
        self.update()
        if not self.ws.connected:
            try: self.ws.connect(SERVER_HOST, SERVER_PORT, USE_SSL)
            except Exception as ex:
                self._auth_err.config(text=f"Ошибка: {ex}", fg=RED); return
        self.ws.on_msg = self._on_auth_msg
        mode = self._auth_mode.get()
        self.ws.send({"type": mode, "name": name, "password": pw})

    def _on_auth_msg(self, msg):
        self.after(0, self._dispatch_auth, msg)

    def _dispatch_auth(self, msg):
        t = msg.get("type")
        if t == "auth_ok":
            self.ws.name = msg.get("name","")
            self.ws.on_msg = self._on_msg
            self._show_chat()
        elif t == "auth_error":
            if hasattr(self, "_auth_err"):
                self._auth_err.config(text=msg.get("text","Ошибка"), fg=RED)

    # ════════════════════════════════════════════════════════════════════════
    #  CHAT PANEL
    # ════════════════════════════════════════════════════════════════════════
    def _show_chat(self):
        self._panel = "chat"
        self._clear_main()

        # sidebar
        self.sidebar = tk.Frame(self._main, bg=PANEL,
                                width=260,
                                highlightthickness=1,
                                highlightbackground=BORDER)
        self.sidebar.pack(side=tk.LEFT, fill=tk.Y)
        self.sidebar.pack_propagate(False)

        # sidebar header
        shdr = tk.Frame(self.sidebar, bg=PANEL2, pady=12)
        shdr.pack(fill=tk.X)

        av_frame = tk.Frame(shdr, bg=PANEL2)
        av_frame.pack(padx=14, anchor="w")
        self.my_av = tk.Label(av_frame,
                              text=self.ws.name[0].upper() if self.ws.name else "?",
                              font=("Helvetica",11,"bold"),
                              fg=WHITE, bg=ACCENT,
                              width=3, pady=6)
        self.my_av.pack(side=tk.LEFT)
        nc = tk.Frame(av_frame, bg=PANEL2)
        nc.pack(side=tk.LEFT, padx=8)
        self.my_name_lbl = tk.Label(nc, text=self.ws.name,
                                     font=FB, fg=WHITE, bg=PANEL2, anchor="w")
        self.my_name_lbl.pack(anchor="w")
        self.my_st = tk.Label(nc, text="● онлайн",
                               font=FS, fg=GREEN, bg=PANEL2, anchor="w")
        self.my_st.pack(anchor="w")

        # nav buttons
        nav = tk.Frame(self.sidebar, bg=PANEL2)
        nav.pack(fill=tk.X)
        self._nav_chat_btn = self._nav_btn(nav, "💬  Чаты", lambda: None, active=True)
        self._nav_chat_btn.pack(fill=tk.X)
        self._nav_set_btn  = self._nav_btn(nav, "⚙  Настройки", self._show_settings)
        self._nav_set_btn.pack(fill=tk.X)

        tk.Frame(self.sidebar, bg=BORDER, height=1).pack(fill=tk.X)

        # search
        sf = tk.Frame(self.sidebar, bg=PANEL, pady=8)
        sf.pack(fill=tk.X, padx=10)
        sw = tk.Frame(sf, bg=PANEL2,
                      highlightthickness=1, highlightbackground=BORDER)
        sw.pack(fill=tk.X)
        tk.Label(sw, text="🔍", font=FS, bg=PANEL2, fg=MUTED
                 ).pack(side=tk.LEFT, padx=(8,0))
        self.search_var = tk.StringVar()
        self.search_var.trace("w", self._filter)
        se = tk.Entry(sw, textvariable=self.search_var, font=F,
                      bg=PANEL2, fg=TEXT, insertbackground=ACCENT3,
                      relief=tk.FLAT, bd=4)
        se.pack(fill=tk.X, expand=True)
        se.insert(0,"Поиск"); se.config(fg=MUTED)
        se.bind("<FocusIn>",  lambda e: (se.delete(0,tk.END), se.config(fg=TEXT)) if se.get()=="Поиск" else None)
        se.bind("<FocusOut>", lambda e: (se.insert(0,"Поиск"), se.config(fg=MUTED)) if not se.get() else None)

        # chat list
        lf = tk.Frame(self.sidebar, bg=PANEL)
        lf.pack(fill=tk.BOTH, expand=True)
        self.lc = tk.Canvas(lf, bg=PANEL, highlightthickness=0)
        self.li = tk.Frame(self.lc, bg=PANEL)
        self.lc.create_window((0,0), window=self.li, anchor="nw")
        self.lc.pack(fill=tk.BOTH, expand=True)
        self.li.bind("<Configure>", lambda e: self.lc.configure(
            scrollregion=self.lc.bbox("all")))

        self.gen_btn = self._crow(self.li, "general", "Общий чат", "Добро пожаловать!")
        self.gen_btn.pack(fill=tk.X)

        # Restore DM buttons from history
        old_dm = list(self._dm_btns.keys())
        self._dm_btns = {}
        for uname in old_dm:
            btn = self._crow(self.li, uname, uname, "Личные сообщения")
            btn.pack(fill=tk.X)
            self._dm_btns[uname] = btn
            # restore last message preview
            msgs = self.history.get(uname, [])
            if msgs:
                last = msgs[-1]
                text = last.get("text","") or last.get("filename","файл")
                sender = last.get("name") or last.get("from","")
                btn._sub.config(text=f"{sender}: {text}"[:35])
                btn._time.config(text=last.get("time",""))
            n = self.unread.get(uname, 0)
            if n: btn._badge.config(text=str(n))

        # ── RIGHT AREA ──
        self.right = tk.Frame(self._main, bg=BG2)
        self.right.pack(fill=tk.BOTH, expand=True)

        # topbar
        self.topbar = tk.Frame(self.right, bg=PANEL,
                               highlightthickness=1,
                               highlightbackground=BORDER)
        self.topbar.pack(fill=tk.X)

        self.peer_av_lbl = tk.Label(self.topbar, text="💬",
                                     font=("Helvetica",13,"bold"),
                                     fg=WHITE, bg=ACCENT,
                                     width=3, pady=10)
        self.peer_av_lbl.pack(side=tk.LEFT, padx=(14,10), pady=8)

        tc = tk.Frame(self.topbar, bg=PANEL)
        tc.pack(side=tk.LEFT, fill=tk.Y, pady=10)
        self.chat_title = tk.Label(tc, text="Общий чат",
                                    font=FB, fg=WHITE, bg=PANEL, anchor="w")
        self.chat_title.pack(anchor="w")
        self.chat_sub = tk.Label(tc, text="",
                                  font=FS, fg=TEXT2, bg=PANEL, anchor="w")
        self.chat_sub.pack(anchor="w")

        # call controls
        self.call_bar = tk.Frame(self.topbar, bg=PANEL)
        self.call_btn = self._icon_btn(self.call_bar, "📞", GREEN, self._call)
        self.call_btn.pack(side=tk.LEFT, padx=4)
        self.hangup_btn = self._icon_btn(self.call_bar, "📵", RED, self._hangup,
                                          state=tk.DISABLED)
        self.hangup_btn.pack(side=tk.LEFT, padx=4)
        self.call_status = tk.Label(self.call_bar, text="",
                                     font=FS, fg=YELLOW, bg=PANEL)
        self.call_status.pack(side=tk.LEFT, padx=4)

        tk.Frame(self.right, bg=BORDER, height=1).pack(fill=tk.X)

        # messages
        mw = tk.Frame(self.right, bg=BG2)
        mw.pack(fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(mw, bg=BG2, highlightthickness=0)
        sb = tk.Scrollbar(mw, orient=tk.VERTICAL, command=self.canvas.yview,
                          bg=PANEL2, troughcolor=BG2, width=4,
                          relief=tk.FLAT, bd=0)
        self.inner = tk.Frame(self.canvas, bg=BG2)
        self._win  = self.canvas.create_window((0,0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.inner.bind("<Configure>", lambda e:
            self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e:
            self.canvas.itemconfig(self._win, width=e.width))
        self.canvas.bind_all("<MouseWheel>", lambda e:
            self.canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        # input bar
        iw = tk.Frame(self.right, bg=PANEL,
                      highlightthickness=1, highlightbackground=BORDER,
                      pady=10)
        iw.pack(fill=tk.X, side=tk.BOTTOM)

        self._attach_btn = self._icon_btn(iw, "📎", MUTED, self._attach, size=13)
        self._attach_btn.pack(side=tk.LEFT, padx=(14,6))

        entry_wrap = tk.Frame(iw, bg=PANEL2,
                              highlightthickness=1, highlightbackground=BORDER)
        entry_wrap.pack(side=tk.LEFT, fill=tk.X, expand=True, pady=2)
        self.entry = tk.Text(entry_wrap, height=2, font=FM,
                             bg=PANEL2, fg=TEXT,
                             insertbackground=ACCENT3,
                             relief=tk.FLAT, wrap=tk.WORD,
                             padx=10, pady=8)
        self.entry.pack(fill=tk.BOTH, expand=True)
        entry_wrap.bind("<FocusIn>",  lambda _: entry_wrap.config(highlightbackground=ACCENT))
        self.entry.bind("<FocusIn>",  lambda _: entry_wrap.config(highlightbackground=ACCENT))
        self.entry.bind("<FocusOut>", lambda _: entry_wrap.config(highlightbackground=BORDER))

        self._ph = False
        self.entry.config(fg=TEXT)
        self.entry.bind("<Return>", self._on_enter)

        send_btn = tk.Button(iw, text="  ➤  ",
                             font=("Helvetica",12,"bold"),
                             bg=ACCENT, fg=WHITE, relief=tk.FLAT,
                             cursor="hand2", pady=10,
                             activebackground=ACCENT2,
                             command=self._send_text)
        send_btn.pack(side=tk.RIGHT, padx=(6,14), fill=tk.Y)
        self._glow_btn(send_btn)

        # открыть общий чат
        self._open("general")

    def _nav_btn(self, parent, text, cmd, active=False):
        btn = tk.Button(parent, text=text, font=F,
                        bg=ACCENT if active else PANEL2,
                        fg=WHITE if active else TEXT2,
                        relief=tk.FLAT, cursor="hand2",
                        anchor="w", padx=14, pady=8,
                        activebackground=ACCENT2,
                        command=cmd)
        btn.bind("<Enter>", lambda _: btn.config(bg=ACCENT2 if btn.cget("bg")!=ACCENT else ACCENT))
        btn.bind("<Leave>", lambda _: btn.config(bg=ACCENT if active else PANEL2))
        return btn

    def _icon_btn(self, parent, text, color, cmd, size=14, state=tk.NORMAL):
        btn = tk.Button(parent, text=text, font=("Helvetica",size),
                        bg=PANEL, fg=color, relief=tk.FLAT,
                        cursor="hand2", state=state,
                        activebackground=PANEL2, command=cmd)
        btn.bind("<Enter>", lambda _: btn.config(bg=PANEL2))
        btn.bind("<Leave>", lambda _: btn.config(bg=PANEL))
        return btn

    # ════════════════════════════════════════════════════════════════════════
    #  SETTINGS PANEL (встроен в то же окно)
    # ════════════════════════════════════════════════════════════════════════
    def _show_settings(self):
        self._panel = "settings"
        self._clear_main()

        # sidebar (такой же)
        sb = tk.Frame(self._main, bg=PANEL, width=260,
                      highlightthickness=1, highlightbackground=BORDER)
        sb.pack(side=tk.LEFT, fill=tk.Y)
        sb.pack_propagate(False)

        shdr = tk.Frame(sb, bg=PANEL2, pady=12); shdr.pack(fill=tk.X)
        av = tk.Label(shdr, text=self.ws.name[0].upper() if self.ws.name else "?",
                      font=("Helvetica",11,"bold"), fg=WHITE, bg=ACCENT,
                      width=3, pady=6)
        av.pack(side=tk.LEFT, padx=(14,8))
        nc = tk.Frame(shdr, bg=PANEL2); nc.pack(side=tk.LEFT)
        tk.Label(nc, text=self.ws.name, font=FB, fg=WHITE, bg=PANEL2).pack(anchor="w")
        tk.Label(nc, text="● онлайн", font=FS, fg=GREEN, bg=PANEL2).pack(anchor="w")

        nav = tk.Frame(sb, bg=PANEL2); nav.pack(fill=tk.X)
        self._nav_btn(nav, "💬  Чаты", self._show_chat).pack(fill=tk.X)
        self._nav_btn(nav, "⚙  Настройки", lambda: None, active=True).pack(fill=tk.X)

        tk.Frame(sb, bg=BORDER, height=1).pack(fill=tk.X)
        tk.Label(sb, text="Настройки", font=FT, fg=TEXT2,
                 bg=PANEL, pady=16, padx=14, anchor="w").pack(fill=tk.X)

        # ── правая часть — настройки ──
        right = tk.Frame(self._main, bg=BG2)
        right.pack(fill=tk.BOTH, expand=True)

        # scrollable content
        sc_wrap = tk.Frame(right, bg=BG2)
        sc_wrap.pack(fill=tk.BOTH, expand=True)
        sc = tk.Canvas(sc_wrap, bg=BG2, highlightthickness=0)
        sc_sb = tk.Scrollbar(sc_wrap, orient=tk.VERTICAL, command=sc.yview,
                             bg=PANEL2, troughcolor=BG2, width=4, relief=tk.FLAT)
        sc_sb.pack(side=tk.RIGHT, fill=tk.Y)
        sc.pack(fill=tk.BOTH, expand=True, padx=40, pady=30)
        sc.configure(yscrollcommand=sc_sb.set)
        content = tk.Frame(sc, bg=BG2)
        sc_win = sc.create_window((0,0), window=content, anchor="nw")
        content.bind("<Configure>", lambda e: sc.configure(
            scrollregion=sc.bbox("all")))
        sc.bind("<Configure>", lambda e: sc.itemconfig(sc_win, width=e.width-80))
        sc.bind_all("<MouseWheel>", lambda e: sc.yview_scroll(int(-1*(e.delta/120)),"units"))

        # ── секция профиля ──
        self._s_section(content, "👤  Профиль")
        prof = tk.Frame(content, bg=PANEL,
                        highlightthickness=1, highlightbackground=BORDER)
        prof.pack(fill=tk.X, pady=(0,20))
        av2 = tk.Label(prof, text=self.ws.name[0].upper() if self.ws.name else "?",
                       font=("Helvetica",20,"bold"), fg=WHITE, bg=ACCENT,
                       width=4, pady=14)
        av2.pack(side=tk.LEFT, padx=16, pady=16)
        pi = tk.Frame(prof, bg=PANEL); pi.pack(side=tk.LEFT, pady=16)
        tk.Label(pi, text=self.ws.name, font=FT, fg=WHITE, bg=PANEL).pack(anchor="w")
        tk.Label(pi, text="BobeGram🫘 аккаунт", font=FS, fg=MUTED, bg=PANEL).pack(anchor="w")

        # ── секция аудио ──
        self._s_section(content, "🎙  Аудио устройства")

        if not AUDIO_OK:
            warn = tk.Frame(content, bg=PANEL,
                            highlightthickness=1, highlightbackground=BORDER)
            warn.pack(fill=tk.X, pady=(0,20))
            tk.Label(warn, text="⚠  pyaudio не установлен",
                     font=FB, fg=YELLOW, bg=PANEL,
                     pady=14, padx=16, anchor="w").pack(fill=tk.X)
            tk.Label(warn, text="Установи: pip install pyaudio",
                     font=FS, fg=MUTED, bg=PANEL,
                     padx=16, anchor="w").pack(fill=tk.X, pady=(0,14))
        else:
            for label, var, devs, icon in [
                ("Микрофон", self.mic_var, self.mic_devices, "🎤"),
                ("Динамики / Наушники", self.spk_var, self.spk_devices, "🔊")
            ]:
                fr = tk.Frame(content, bg=PANEL,
                              highlightthickness=1, highlightbackground=BORDER)
                fr.pack(fill=tk.X, pady=(0,12))
                hdr = tk.Frame(fr, bg=PANEL); hdr.pack(fill=tk.X, padx=16, pady=(14,4))
                tk.Label(hdr, text=f"{icon}  {label}", font=FB,
                         fg=TEXT, bg=PANEL).pack(side=tk.LEFT)
                names = [d[0] for d in devs]
                om = tk.OptionMenu(fr, var, *names)
                om.config(bg=PANEL2, fg=TEXT, font=FS, relief=tk.FLAT,
                          highlightthickness=0, activebackground=BORDER,
                          bd=0, pady=8)
                om["menu"].config(bg=PANEL2, fg=TEXT,
                                  activebackground=ACCENT,
                                  activeforeground=WHITE, font=FS)
                om.pack(fill=tk.X, padx=16, pady=(0,14))

        # ── секция сервера ──
        self._s_section(content, "🌐  Сервер")
        srv_frame = tk.Frame(content, bg=PANEL,
                             highlightthickness=1, highlightbackground=BORDER)
        srv_frame.pack(fill=tk.X, pady=(0,20))
        tk.Label(srv_frame,
                 text=f"Адрес:  {SERVER_HOST}:{SERVER_PORT}",
                 font=("Courier",10), fg=ACCENT3, bg=PANEL,
                 pady=14, padx=16, anchor="w").pack(fill=tk.X)
        dot_color = GREEN if self.ws.connected else RED
        dot_text  = "● Подключён" if self.ws.connected else "● Не подключён"
        tk.Label(srv_frame, text=dot_text, font=FS,
                 fg=dot_color, bg=PANEL,
                 padx=16, anchor="w").pack(fill=tk.X, pady=(0,14))

        # ── ADMIN PANEL ──
        if self.is_admin:
            self._s_section(content, "👑  Администратор")
            adm = tk.Frame(content, bg=PANEL,
                           highlightthickness=1, highlightbackground=BORDER)
            adm.pack(fill=tk.X, pady=(0,20))

            tk.Label(adm, text="Выдать значок пользователю",
                     font=FB, fg=TEXT, bg=PANEL,
                     pady=10, padx=16, anchor="w").pack(fill=tk.X)

            # target user
            tk.Label(adm, text="Ник:", font=FS, fg=TEXT2, bg=PANEL,
                     padx=16, anchor="w").pack(fill=tk.X)
            target_var = tk.StringVar()
            te = tk.Entry(adm, textvariable=target_var, font=FL,
                          bg=PANEL2, fg=TEXT, insertbackground=ACCENT3,
                          relief=tk.FLAT, bd=6,
                          highlightthickness=1, highlightbackground=BORDER)
            te.pack(fill=tk.X, padx=16, pady=(2,10))

            # badge choice
            tk.Label(adm, text="Значок:", font=FS, fg=TEXT2, bg=PANEL,
                     padx=16, anchor="w").pack(fill=tk.X)

            BADGES = ["✅","⭐","👑","💎","🔥","🎖️","🫘","⚡","🌟","❌ Убрать"]
            badge_var = tk.StringVar(value="✅")

            badges_frame = tk.Frame(adm, bg=PANEL)
            badges_frame.pack(fill=tk.X, padx=16, pady=(4,10))

            for b in BADGES:
                tk.Radiobutton(badges_frame, text=b,
                               variable=badge_var, value=b,
                               font=("Helvetica",12),
                               fg=TEXT, bg=PANEL,
                               selectcolor=PANEL2,
                               activebackground=PANEL,
                               activeforeground=TEXT).pack(side=tk.LEFT, padx=4)

            def give_badge():
                target = target_var.get().strip()
                badge  = badge_var.get()
                if not target: return
                if badge == "❌ Убрать": badge = ""
                self.ws.send({"type":"set_badge","target":target,"badge":badge})

            tk.Button(adm, text="✅ Выдать значок",
                      font=FB, bg=ACCENT, fg=WHITE,
                      relief=tk.FLAT, cursor="hand2",
                      activebackground=ACCENT2,
                      command=give_badge).pack(padx=16, pady=(0,14),
                                               ipadx=16, ipady=6, anchor="w")

            # ── BAN PANEL ──
            ban_fr = tk.Frame(content, bg=PANEL,
                              highlightthickness=1, highlightbackground=BORDER)
            ban_fr.pack(fill=tk.X, pady=(0,20))

            tk.Label(ban_fr, text="🔨  Управление пользователями",
                     font=FB, fg=TEXT, bg=PANEL,
                     pady=10, padx=16, anchor="w").pack(fill=tk.X)

            tk.Label(ban_fr, text="Ник пользователя:", font=FS,
                     fg=TEXT2, bg=PANEL, padx=16, anchor="w").pack(fill=tk.X)
            ban_target = tk.StringVar()
            tk.Entry(ban_fr, textvariable=ban_target, font=FL,
                     bg=PANEL2, fg=TEXT, insertbackground=ACCENT3,
                     relief=tk.FLAT, bd=6,
                     highlightthickness=1,
                     highlightbackground=BORDER).pack(fill=tk.X, padx=16, pady=(2,10))

            btn_row = tk.Frame(ban_fr, bg=PANEL)
            btn_row.pack(fill=tk.X, padx=16, pady=(0,14))

            def do_ban():
                t = ban_target.get().strip()
                if not t: return
                if messagebox.askyesno("Бан", f"Заблокировать {t}?"):
                    self.ws.send({"type":"ban","target":t})

            def do_unban():
                t = ban_target.get().strip()
                if not t: return
                self.ws.send({"type":"unban","target":t})

            tk.Button(btn_row, text="⛔ Заблокировать",
                      font=FB, bg=RED, fg=WHITE,
                      relief=tk.FLAT, cursor="hand2",
                      activebackground="#c0392b",
                      command=do_ban).pack(side=tk.LEFT, ipadx=12, ipady=6, padx=(0,8))
            tk.Button(btn_row, text="✅ Разблокировать",
                      font=FB, bg=GREEN, fg=WHITE,
                      relief=tk.FLAT, cursor="hand2",
                      activebackground="#0d9668",
                      command=do_unban).pack(side=tk.LEFT, ipadx=12, ipady=6)

        # кнопка сохранить
        def save():
            self.voice.mic_index = next((d[1] for d in self.mic_devices
                                          if d[0]==self.mic_var.get()), None)
            self.voice.spk_index = next((d[1] for d in self.spk_devices
                                          if d[0]==self.spk_var.get()), None)
            self._show_chat()

        save_btn = tk.Button(content, text="Сохранить и вернуться",
                             font=FB, bg=ACCENT, fg=WHITE,
                             relief=tk.FLAT, cursor="hand2",
                             activebackground=ACCENT2,
                             command=save)
        save_btn.pack(pady=8, ipadx=24, ipady=10)
        self._glow_btn(save_btn)

    def _s_section(self, parent, title):
        tk.Label(parent, text=title, font=("Helvetica",11,"bold"),
                 fg=TEXT2, bg=BG2, anchor="w"
                 ).pack(fill=tk.X, pady=(0,8))

    # ── chat row widget ───────────────────────────────────────────────────────
    def _crow(self, parent, cid, name, subtitle):
        f = tk.Frame(parent, bg=PANEL, cursor="hand2"); f._id = cid

        av = tk.Label(f,
                      text="💬" if cid=="general" else name[0].upper(),
                      font=("Helvetica",10,"bold"),
                      fg=WHITE, bg=ACCENT, width=3, pady=8)
        av.pack(side=tk.LEFT, padx=(10,10), pady=6)

        mid = tk.Frame(f, bg=PANEL); mid.pack(side=tk.LEFT, fill=tk.X, expand=True, pady=8)
        tr  = tk.Frame(mid, bg=PANEL); tr.pack(fill=tk.X)
        nl  = tk.Label(tr, text=name, font=FB, fg=TEXT, bg=PANEL, anchor="w")
        nl.pack(side=tk.LEFT)
        tl  = tk.Label(tr, text="", font=("Helvetica",8), fg=MUTED, bg=PANEL)
        tl.pack(side=tk.RIGHT, padx=8)
        br  = tk.Frame(mid, bg=PANEL); br.pack(fill=tk.X)
        sl  = tk.Label(br, text=subtitle, font=FS, fg=MUTED, bg=PANEL, anchor="w")
        sl.pack(side=tk.LEFT, fill=tk.X, expand=True)
        badge = tk.Label(br, text="", font=("Helvetica",8,"bold"),
                         fg=WHITE, bg=ACCENT, width=2, padx=4)
        badge.pack(side=tk.RIGHT, padx=8)

        tk.Frame(f, bg=BORDER, height=1).pack(fill=tk.X, side=tk.BOTTOM)

        f._av=av; f._name=nl; f._sub=sl; f._time=tl; f._badge=badge

        def _hl(on):
            bg = ACCENT if self.active==cid else (PANEL2 if on else PANEL)
            for w in [f,av,mid,tr,br,nl,sl,tl,badge]:
                try: w.config(bg=bg)
                except: pass
        f.bind("<Enter>",    lambda e: _hl(True))
        f.bind("<Leave>",    lambda e: _hl(False))
        f.bind("<Button-1>", lambda e: self._open(cid))
        for w in [av,mid,tr,br,nl,sl,tl]:
            w.bind("<Enter>",    lambda e: _hl(True))
            w.bind("<Leave>",    lambda e: _hl(False))
            w.bind("<Button-1>", lambda e: self._open(cid))
        f._hl = _hl
        return f

    # ── messages ──────────────────────────────────────────────────────────────
    def _on_msg(self, msg): self.after(0, self._dispatch, msg)

    def _dispatch(self, msg):
        t = msg.get("type")
        if t=="message":
            self._store("general",msg)
            if self.active=="general": self._bubble(msg)
            else: self._unread("general",msg)
        elif t=="private":
            cid=msg["from"]; self._edm(cid); self._store(cid,msg)
            if self.active==cid: self._bubble(msg)
            else: self._unread(cid,msg)
        elif t=="private_sent":
            cid=msg["to"]; self._edm(cid); self._store(cid,msg)
            if self.active==cid: self._bubble(msg)
        elif t in("file","file_sent"):
            cid="general" if t=="file" else msg["to"]
            self._store(cid,msg)
            if self.active==cid: self._fbubble(msg)
            else: self._unread(cid,msg)
        elif t=="system":
            self._store("general",msg)
            if self._panel=="chat" and self.active=="general": self._sys(msg["text"])
        elif t=="user_list": self._upd_users(msg["users"])
        elif t=="all_badges":
            self.badges = msg.get("badges",{})
            self._refresh_badges_ui()
        elif t=="badge_update":
            target = msg.get("target","")
            badge  = msg.get("badge","")
            if badge: self.badges[target] = badge
            else: self.badges.pop(target,None)
            self._refresh_badges_ui()
        elif t=="admin_status":
            self.is_admin = msg.get("is_admin",False)
        elif t=="kicked":
            messagebox.showerror("Заблокирован", msg.get("text","⛔ Ты заблокирован!"))
            self.ws.disconnect()
            self._show_auth()
        elif t=="call_request": self._inc_call(msg["from"],msg.get("ip",""))
        elif t=="call_response": self._call_resp(msg)
        elif t=="call_end": self._remote_hangup()

    def _store(self, cid, msg): self.history.setdefault(cid,[]).append(msg)

    def _unread(self, cid, msg):
        self.unread[cid] = self.unread.get(cid,0)+1
        btn = self._dm_btns.get(cid) or (self.gen_btn if cid=="general" else None)
        if btn and hasattr(btn,"_badge"):
            btn._badge.config(text=str(self.unread[cid]))
            text = msg.get("text","") or msg.get("filename","файл")
            sender = msg.get("name") or msg.get("from","")
            btn._sub.config(text=f"{sender}: {text}"[:35])
            btn._time.config(text=msg.get("time",""))

    def _edm(self, name):
        if name in self._dm_btns: return
        btn = self._crow(self.li, name, name, "Личные сообщения")
        btn.pack(fill=tk.X)
        self._dm_btns[name] = btn
        self.history.setdefault(name,[])

    def _refresh_badges_ui(self):
        """Update badge display in chat list"""
        # update general btn subtitle if needed
        for name, btn in self._dm_btns.items():
            if hasattr(btn,"_name"):
                badge = self.badges.get(name,"")
                btn._name.config(text=f"{name} {badge}".strip())

    def _upd_users(self, users):
        others = [u for u in users if u!=self.ws.name]
        self.users = others
        if hasattr(self,"chat_sub"):
            self.chat_sub.config(text=f"{len(users)} участников онлайн")
        for u in others: self._edm(u)
        if hasattr(self,"call_bar"):
            if self.active!="general" and self.active in others:
                self.call_bar.pack(side=tk.RIGHT, padx=8)
            else:
                self.call_bar.pack_forget()

    def _filter(self, *_):
        q = self.search_var.get().lower()
        if q=="поиск": return
        for name,btn in self._dm_btns.items():
            if q in name.lower(): btn.pack(fill=tk.X)
            else: btn.pack_forget()

    def _open(self, cid):
        self.active = cid
        self.unread.pop(cid, None)
        btn = self._dm_btns.get(cid) or (self.gen_btn if cid=="general" else None)
        if btn and hasattr(btn,"_badge"): btn._badge.config(text="")

        # highlight
        if hasattr(self,"gen_btn"): self.gen_btn._hl(False)
        for b in self._dm_btns.values():
            if hasattr(b,"_hl"): b._hl(False)
        tgt = self.gen_btn if cid=="general" else self._dm_btns.get(cid)
        if tgt:
            for w in list(tgt.winfo_children())+[tgt]:
                try: w.config(bg=ACCENT)
                except: pass

        if hasattr(self,"chat_title"):
            self.chat_title.config(text="Общий чат" if cid=="general" else cid)
        if hasattr(self,"peer_av_lbl"):
            self.peer_av_lbl.config(text="💬" if cid=="general" else cid[0].upper())
        if hasattr(self,"call_bar"):
            if cid!="general" and cid in self.users:
                self.call_bar.pack(side=tk.RIGHT, padx=8)
            else:
                self.call_bar.pack_forget()

        if not hasattr(self,"inner"): return
        for w in self.inner.winfo_children(): w.destroy()
        for m in self.history.get(cid,[]):
            t = m.get("type")
            if t in("message","private","private_sent"): self._bubble(m,scroll=False)
            elif t in("file","file_sent"):               self._fbubble(m,scroll=False)
            elif t=="system":                            self._sys(m["text"],scroll=False)
        self.after(80, self._sb)

    def _bubble(self, msg, scroll=True):
        t    = msg.get("type")
        mine = (t=="private_sent" or
                (t=="message" and msg.get("name")==self.ws.name))
        name = self.ws.name if mine else (msg.get("name") or msg.get("from","?"))
        text = msg.get("text",""); ts = msg.get("time","")
        color = ME_BG if mine else TH_BG
        side  = tk.RIGHT if mine else tk.LEFT

        row = tk.Frame(self.inner, bg=BG2)
        row.pack(fill=tk.X, padx=16, pady=3,
                 anchor="e" if mine else "w")

        if not mine:
            av = tk.Label(row,
                          text=name[0].upper(),
                          font=("Helvetica",9,"bold"),
                          fg=WHITE, bg=ACCENT,
                          width=3, pady=6)
            av.pack(side=tk.LEFT, anchor="n", padx=(0,8))

        bub = tk.Frame(row, bg=color,
                       highlightthickness=1,
                       highlightbackground=BORDER,
                       padx=12, pady=8)
        bub.pack(side=side)

        if not mine:
            badge = self.badges.get(name,"")
            tk.Label(bub, text=f"{name} {badge}".strip(),
                     font=("Helvetica",9,"bold"),
                     fg=ACCENT3, bg=color).pack(anchor="w")

        tk.Label(bub, text=text, font=FM, fg=TEXT, bg=color,
                 wraplength=460, justify=tk.LEFT).pack(anchor="w")
        tk.Label(bub, text=ts, font=("Helvetica",7),
                 fg=MUTED, bg=color).pack(anchor="e")

        if scroll: self.after(40, self._sb)

    def _fbubble(self, msg, scroll=True):
        mine     = msg.get("type")=="file_sent" or msg.get("from")==self.ws.name
        sender   = self.ws.name if mine else msg.get("from","?")
        filename = msg.get("filename","файл")
        size     = msg.get("size",0)
        data_b64 = msg.get("data","")
        ts       = msg.get("time","")
        color    = ME_BG if mine else TH_BG
        side     = tk.RIGHT if mine else tk.LEFT

        row = tk.Frame(self.inner, bg=BG2)
        row.pack(fill=tk.X, padx=16, pady=3, anchor="e" if mine else "w")

        if not mine:
            tk.Label(row, text=sender[0].upper(),
                     font=("Helvetica",9,"bold"),
                     fg=WHITE, bg=ACCENT,
                     width=3, pady=6).pack(side=tk.LEFT, anchor="n", padx=(0,8))

        bub = tk.Frame(row, bg=color,
                       highlightthickness=1, highlightbackground=BORDER,
                       padx=12, pady=8)
        bub.pack(side=side)
        if not mine:
            tk.Label(bub, text=sender, font=("Helvetica",9,"bold"),
                     fg=ACCENT3, bg=color).pack(anchor="w")
        r = tk.Frame(bub, bg=color); r.pack(anchor="w")
        tk.Label(r, text="📄", font=("Helvetica",20), bg=color).pack(side=tk.LEFT)
        inf = tk.Frame(r, bg=color); inf.pack(side=tk.LEFT, padx=8)
        tk.Label(inf, text=filename, font=FB, fg=TEXT, bg=color).pack(anchor="w")
        tk.Label(inf, text=f"{size/1024:.1f} KB", font=FS, fg=MUTED, bg=color).pack(anchor="w")
        if data_b64:
            def save(d=data_b64, fn=filename):
                path = filedialog.asksaveasfilename(initialfile=fn)
                if path:
                    with open(path,"wb") as f: f.write(base64.b64decode(d))
            save_btn = tk.Button(bub, text="⬇  Сохранить", font=FS,
                                 bg=ACCENT, fg=WHITE, relief=tk.FLAT,
                                 cursor="hand2", activebackground=ACCENT2,
                                 command=save)
            save_btn.pack(anchor="w", pady=(6,0))
        tk.Label(bub, text=ts, font=("Helvetica",7), fg=MUTED, bg=color).pack(anchor="e")
        if scroll: self.after(40, self._sb)

    def _sys(self, text, scroll=True):
        f = tk.Frame(self.inner, bg=BG2)
        f.pack(fill=tk.X, pady=4)
        tk.Label(f, text=text, font=("Helvetica",9,"italic"),
                 fg=MUTED, bg=BG2).pack()
        if scroll: self.after(40, self._sb)

    def _sb(self):
        if hasattr(self,"canvas"):
            self.canvas.update_idletasks()
            self.canvas.yview_moveto(1.0)

    # ── input ─────────────────────────────────────────────────────────────────
    def _ph_clear(self, _):
        pass

    def _ph_restore(self, _):
        pass

    def _on_enter(self, e):
        if not (e.state & 0x1): self._send_text(); return "break"

    def _send_text(self):
        if not self.ws.connected: return
        text = self.entry.get("1.0", tk.END).strip()
        if not text: return
        if self.active=="general":
            self.ws.send({"type":"message","text":text})
        else:
            self.ws.send({"type":"private","to":self.active,"text":text})
        self.entry.delete("1.0", tk.END)

    def _attach(self):
        if not self.ws.connected: return
        path = filedialog.askopenfilename()
        if not path: return
        size = os.path.getsize(path)
        if size > 20*1024*1024:
            messagebox.showwarning("Слишком большой","Максимум 20 МБ"); return
        with open(path,"rb") as f: data = base64.b64encode(f.read()).decode()
        to = None if self.active=="general" else self.active
        self.ws.send({"type":"file","to":to,
                      "filename":os.path.basename(path),"data":data,"size":size})

    # ── voice ─────────────────────────────────────────────────────────────────
    def _call(self):
        if not AUDIO_OK:
            messagebox.showinfo("Нет аудио","pip install pyaudio"); return
        if self.active=="general": return
        self.call_peer = self.active
        self.ws.send({"type":"call_request","to":self.call_peer,"ip":self.my_ip})
        self.call_status.config(text=f"Звоним {self.call_peer}…")
        self.voice.host(lambda ok: self.after(0,
            self._call_ok if ok else lambda: self._sys("⚠️ Ошибка звонка")))

    def _inc_call(self, caller, ip):
        if not AUDIO_OK:
            self.ws.send({"type":"call_response","to":caller,"accepted":False}); return
        ans = messagebox.askyesno("Входящий звонок",f"📞 {caller} звонит!\nПринять?")
        self.ws.send({"type":"call_response","to":caller,"accepted":ans})
        if ans:
            self.call_peer = caller
            self.voice.join(ip, lambda ok: self.after(0,
                self._call_ok if ok else lambda: self._sys("⚠️ Ошибка")))

    def _call_resp(self, msg):
        if msg.get("accepted"): self._sys(f"✅ {self.call_peer} принял звонок")
        else:
            self._sys(f"❌ {self.call_peer} отклонил")
            self.voice.stop(); self.call_peer = None
            if hasattr(self,"call_status"): self.call_status.config(text="")

    def _call_ok(self):
        self.in_call = True
        if hasattr(self,"call_status"): self.call_status.config(text=f"🎙 {self.call_peer}")
        if hasattr(self,"hangup_btn"): self.hangup_btn.config(state=tk.NORMAL)
        if hasattr(self,"call_btn"):   self.call_btn.config(state=tk.DISABLED)
        self._sys(f"🎙 Звонок с {self.call_peer} начался")

    def _hangup(self):
        if self.call_peer: self.ws.send({"type":"call_end","to":self.call_peer})
        self._end_call()

    def _remote_hangup(self):
        self._sys(f"📵 {self.call_peer} завершил звонок")
        self._end_call()

    def _end_call(self):
        self.voice.stop(); self.voice = VoiceCall()
        self.voice.mic_index = next((d[1] for d in self.mic_devices
                                      if d[0]==self.mic_var.get()), None)
        self.voice.spk_index = next((d[1] for d in self.spk_devices
                                      if d[0]==self.spk_var.get()), None)
        self.in_call = False; self.call_peer = None
        if hasattr(self,"call_status"): self.call_status.config(text="")
        if hasattr(self,"hangup_btn"): self.hangup_btn.config(state=tk.DISABLED)
        if hasattr(self,"call_btn"):   self.call_btn.config(state=tk.NORMAL)

    @staticmethod
    def _get_ip():
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8",80)); ip = s.getsockname()[0]; s.close(); return ip
        except: return "127.0.0.1"

    def _quit(self):
        if self.in_call: self.voice.stop()
        self.ws.disconnect(); self.destroy()


if __name__ == "__main__":
    App().mainloop()
