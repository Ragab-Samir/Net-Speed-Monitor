"""
Net Speed Monitor
- سرعة الداونلود والابلود بوحدة KB/s
- إجمالي الاستهلاك اليومي والشهري (يُحفظ بين مرات التشغيل)
- أيقونة في شريط المهام (System Tray)

المتطلبات:  pip install psutil pystray pillow
"""

import datetime
import json
import os
import queue
import sys
import time
import tkinter as tk

import psutil
import pystray
from PIL import Image, ImageDraw

APP_NAME = "NetSpeedMonitor"
DATA_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_NAME)
DATA_FILE = os.path.join(DATA_DIR, "usage.json")

BG = "#1e1e2e"
BORDER = "#45475a"
FG_LABEL = "#cbd5e1"
FG_MUTED = "#8b93a7"
FG_DOWN = "#4ade80"
FG_UP = "#60a5fa"
FG_TOTAL = "#fbbf24"

_mutex_handle = None  # يمنع فتح أكثر من نسخة


# ---------------------------------------------------------------- icon
def draw_icon(size=64):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=size // 5, fill=(30, 30, 46, 255))
    s = size
    w, h = 0.12 * s, 0.30 * s  # عرض الساق وعرض الرأس

    cx = 0.31 * s  # سهم النزول (Download)
    top, mid, bot = 0.18 * s, 0.50 * s, 0.82 * s
    d.polygon([(cx - w / 2, top), (cx + w / 2, top), (cx + w / 2, mid), (cx + h / 2, mid),
               (cx, bot), (cx - h / 2, mid), (cx - w / 2, mid)], fill=(74, 222, 128, 255))

    cx = 0.69 * s  # سهم الرفع (Upload)
    d.polygon([(cx, top), (cx + h / 2, mid), (cx + w / 2, mid), (cx + w / 2, bot),
               (cx - w / 2, bot), (cx - w / 2, mid), (cx - h / 2, mid)], fill=(96, 165, 250, 255))
    return img


def make_icon():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.ico")
    sizes = [16, 24, 32, 48, 64, 128, 256]
    draw_icon(256).save(path, format="ICO", sizes=[(n, n) for n in sizes])
    print("Created", path)


# ---------------------------------------------------------------- helpers
def fmt_bytes(n):
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:,.0f} {unit}" if unit == "B" else f"{n:,.2f} {unit}"
        n /= 1024
    return f"{n:,.2f} GB"


def startup_command():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --minimized'
    return f'"{sys.executable}" "{os.path.abspath(__file__)}" --minimized'


def startup_enabled():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Run") as k:
            winreg.QueryValueEx(k, APP_NAME)
            return True
    except Exception:
        return False


def set_startup(enable):
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Run",
                            0, winreg.KEY_SET_VALUE) as k:
            if enable:
                winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, startup_command())
            else:
                try:
                    winreg.DeleteValue(k, APP_NAME)
                except FileNotFoundError:
                    pass
    except Exception:
        pass


def single_instance():
    global _mutex_handle
    try:
        import ctypes
        _mutex_handle = ctypes.windll.kernel32.CreateMutexW(None, False, "NetSpeedMonitorMutex")
        if ctypes.windll.kernel32.GetLastError() == 183:  # ALREADY_EXISTS
            return False
    except Exception:
        pass
    return True


def enable_dpi_awareness():
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


# ---------------------------------------------------------------- storage
class UsageStore:
    """يحفظ الاستهلاك اليومي: {"2026-11-20": {"down": bytes, "up": bytes}}"""

    def __init__(self):
        self.days = {}
        self.pos = [60, 60]
        self.load()

    def load(self):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.days = data.get("days", {})
            self.pos = data.get("pos", self.pos)
        except Exception:
            pass

    def save(self):
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            keep = sorted(self.days)[-400:]  # احتفظ بآخر ~13 شهر
            payload = {"days": {k: self.days[k] for k in keep}, "pos": self.pos}
            tmp = DATA_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f)
            os.replace(tmp, DATA_FILE)
        except Exception:
            pass

    def add(self, day, down, up):
        rec = self.days.setdefault(day, {"down": 0, "up": 0})
        rec["down"] += down
        rec["up"] += up

    def total(self, prefix):
        down = sum(v["down"] for k, v in self.days.items() if k.startswith(prefix))
        up = sum(v["up"] for k, v in self.days.items() if k.startswith(prefix))
        return down, up


# ---------------------------------------------------------------- app
class App:
    def __init__(self, start_hidden=False):
        self.store = UsageStore()
        self.cmds = queue.Queue()
        self.on_top = True
        self.visible = not start_hidden
        self.ticks = 0

        self.root = tk.Tk()
        self.root.title("Net Speed Monitor")
        self.root.configure(bg=BG)
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.94)

        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        x = min(max(int(self.store.pos[0]), 0), sw - 120)
        y = min(max(int(self.store.pos[1]), 0), sh - 120)
        self.root.geometry(f"+{x}+{y}")

        self.v = {k: tk.StringVar(value="-") for k in
                  ("down", "up", "today", "today_s", "month", "month_s")}
        self.build_ui()

        c = psutil.net_io_counters()
        self.last_recv, self.last_sent, self.last_time = c.bytes_recv, c.bytes_sent, time.time()

        self.icon = None
        self.setup_tray()

        if start_hidden:
            self.root.withdraw()

        self.root.after(1000, self.tick)
        self.root.after(150, self.poll)

    # ---- UI
    def build_ui(self):
        f = tk.Frame(self.root, bg=BG, padx=14, pady=8,
                     highlightbackground=BORDER, highlightthickness=1)
        f.pack()

        tk.Label(f, text="Net Speed Monitor", bg=BG, fg=FG_MUTED,
                 font=("Segoe UI", 8)).grid(row=0, column=0, sticky="w")
        self.hide_btn = tk.Label(f, text="\u2013", bg=BG, fg=FG_MUTED,
                                 font=("Segoe UI", 11, "bold"), cursor="hand2")
        self.hide_btn.grid(row=0, column=1, sticky="e")
        self.hide_btn.bind("<Button-1>", lambda e: self.hide())

        self.row(f, 1, "\u2193 Download", "down", FG_DOWN, 14)
        self.row(f, 2, "\u2191 Upload", "up", FG_UP, 14)

        tk.Frame(f, bg=BORDER, height=1).grid(row=3, column=0, columnspan=2, sticky="ew", pady=6)

        self.row(f, 4, "Today", "today", FG_TOTAL, 12)
        tk.Label(f, textvariable=self.v["today_s"], bg=BG, fg=FG_MUTED,
                 font=("Consolas", 9), anchor="e").grid(row=5, column=0, columnspan=2, sticky="e")
        self.row(f, 6, "This month", "month", FG_TOTAL, 12)
        tk.Label(f, textvariable=self.v["month_s"], bg=BG, fg=FG_MUTED,
                 font=("Consolas", 9), anchor="e").grid(row=7, column=0, columnspan=2, sticky="e")

        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="Hide to tray", command=self.hide)
        self.menu.add_command(label="Exit", command=self.quit)

        def bind_all(w):
            if w is not self.hide_btn:
                w.bind("<ButtonPress-1>", self.start_move)
                w.bind("<B1-Motion>", self.do_move)
                w.bind("<ButtonRelease-1>", self.end_move)
            w.bind("<Button-3>", lambda e: self.menu.tk_popup(e.x_root, e.y_root))
            for c in w.winfo_children():
                bind_all(c)
        bind_all(self.root)

    def row(self, parent, r, label, key, color, size):
        tk.Label(parent, text=label, bg=BG, fg=FG_LABEL, font=("Segoe UI", 10),
                 anchor="w").grid(row=r, column=0, sticky="w", pady=1)
        tk.Label(parent, textvariable=self.v[key], bg=BG, fg=color,
                 font=("Consolas", size, "bold"), anchor="e", width=13
                 ).grid(row=r, column=1, sticky="e", pady=1)

    def start_move(self, e):
        self._mx, self._my = e.x_root, e.y_root

    def do_move(self, e):
        dx, dy = e.x_root - self._mx, e.y_root - self._my
        self._mx, self._my = e.x_root, e.y_root
        self.root.geometry(f"+{self.root.winfo_x() + dx}+{self.root.winfo_y() + dy}")

    def end_move(self, e):
        self.store.pos = [self.root.winfo_x(), self.root.winfo_y()]
        self.store.save()

    # ---- show / hide
    def hide(self):
        self.root.withdraw()
        self.visible = False

    def show(self):
        self.root.deiconify()
        self.root.attributes("-topmost", self.on_top)
        self.visible = True

    def toggle(self):
        self.hide() if self.visible else self.show()

    def quit(self):
        self.store.pos = [self.root.winfo_x(), self.root.winfo_y()]
        self.store.save()
        try:
            if self.icon:
                self.icon.stop()
        except Exception:
            pass
        self.root.destroy()

    # ---- tray (callbacks تعمل في Thread آخر، فنمرر الأوامر عبر queue)
    def setup_tray(self):
        menu = pystray.Menu(
            pystray.MenuItem("Show / Hide", lambda i, it: self.cmds.put("toggle"), default=True),
            pystray.MenuItem("Always on top", lambda i, it: self.cmds.put("top"),
                             checked=lambda it: self.on_top),
            pystray.MenuItem("Start with Windows", lambda i, it: self.cmds.put("startup"),
                             checked=lambda it: startup_enabled()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", lambda i, it: self.cmds.put("quit")),
        )
        self.icon = pystray.Icon(APP_NAME, draw_icon(64), "Net Speed Monitor", menu)
        self.icon.run_detached()

    def poll(self):
        try:
            while True:
                cmd = self.cmds.get_nowait()
                if cmd == "toggle":
                    self.toggle()
                elif cmd == "top":
                    self.on_top = not self.on_top
                    self.root.attributes("-topmost", self.on_top)
                elif cmd == "startup":
                    set_startup(not startup_enabled())
                elif cmd == "quit":
                    self.quit()
                    return
        except queue.Empty:
            pass
        self.root.after(150, self.poll)

    # ---- main loop
    def tick(self):
        c = psutil.net_io_counters()
        now = time.time()
        dt = max(now - self.last_time, 1e-6)

        d_recv = c.bytes_recv - self.last_recv
        d_sent = c.bytes_sent - self.last_sent
        if d_recv < 0:  # العدّاد اتصفّر (إعادة تشغيل/تعطيل كارت)
            d_recv = c.bytes_recv
        if d_sent < 0:
            d_sent = c.bytes_sent
        self.last_recv, self.last_sent, self.last_time = c.bytes_recv, c.bytes_sent, now

        today = datetime.date.today().isoformat()
        self.store.add(today, d_recv, d_sent)

        down_kb = d_recv / 1024 / dt
        up_kb = d_sent / 1024 / dt
        self.v["down"].set(f"{down_kb:,.1f} KB/s")
        self.v["up"].set(f"{up_kb:,.1f} KB/s")

        td, tu = self.store.total(today)
        md, mu = self.store.total(today[:7])
        self.v["today"].set(fmt_bytes(td + tu))
        self.v["today_s"].set(f"\u2193 {fmt_bytes(td)}  \u2191 {fmt_bytes(tu)}")
        self.v["month"].set(fmt_bytes(md + mu))
        self.v["month_s"].set(f"\u2193 {fmt_bytes(md)}  \u2191 {fmt_bytes(mu)}")

        try:
            self.icon.title = f"\u2193 {down_kb:,.1f} KB/s   \u2191 {up_kb:,.1f} KB/s"
        except Exception:
            pass

        self.ticks += 1
        if self.ticks % 10 == 0:
            self.store.save()
        self.root.after(1000, self.tick)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    if "--make-icon" in sys.argv:
        make_icon()
        sys.exit(0)
    if not single_instance():
        sys.exit(0)
    enable_dpi_awareness()
    App(start_hidden="--minimized" in sys.argv).run()
