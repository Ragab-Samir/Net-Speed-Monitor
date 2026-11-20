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


def fmt_speed(kb):
    """أقل من 1024 KB/s يظهر بالكيلوبايت، وأكبر يظهر بالميجابايت."""
    if kb >= 1024:
        return f"{kb / 1024:,.2f} MB/s"
    return f"{kb:,.1f} KB/s"


def virtual_screen(root):
    """حدود سطح المكتب كله (تشمل الشاشات المتعددة)."""
    try:
        import ctypes
        u = ctypes.windll.user32
        return u.GetSystemMetrics(76), u.GetSystemMetrics(77), \
            u.GetSystemMetrics(78), u.GetSystemMetrics(79)
    except Exception:
        return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()


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
        self.scale = 1.0
        self.load()

    def load(self):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.days = data.get("days", {})
            self.pos = data.get("pos", self.pos)
            self.scale = float(data.get("scale", 1.0))
        except Exception:
            pass

    def save(self):
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            keep = sorted(self.days)[-400:]  # احتفظ بآخر ~13 شهر
            payload = {"days": {k: self.days[k] for k in keep}, "pos": self.pos, "scale": self.scale}
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
SCALES = {"Small": 1.0, "Medium": 1.35, "Large": 1.8}


class App:
    def __init__(self, start_hidden=False):
        self.store = UsageStore()
        self.cmds = queue.Queue()
        self.on_top = True
        self.visible = not start_hidden
        self.ticks = 0
        self.scale = self.store.scale if self.store.scale in SCALES.values() else 1.0
        self.frame = None

        self.root = tk.Tk()
        self.root.title("Net Speed Monitor")
        self.root.configure(bg=BG)
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.94)

        vx, vy, vw, vh = virtual_screen(self.root)
        x = min(max(int(self.store.pos[0]), vx), vx + vw - 80)
        y = min(max(int(self.store.pos[1]), vy), vy + vh - 60)
        self.root.geometry(f"+{x}+{y}")

        self.v = {k: tk.StringVar(value="-") for k in ("down", "up", "totals")}

        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="Hide to tray", command=self.hide)
        size_menu = tk.Menu(self.menu, tearoff=0)
        self.size_var = tk.StringVar(value=self.size_name())
        for name in SCALES:
            size_menu.add_radiobutton(label=name, value=name, variable=self.size_var,
                                      command=lambda n=name: self.set_scale(n))
        self.menu.add_cascade(label="Size", menu=size_menu)
        self.top_var = tk.BooleanVar(value=True)
        self.menu.add_checkbutton(label="Always on top", variable=self.top_var,
                                  command=self.toggle_top)
        self.menu.add_separator()
        self.menu.add_command(label="Exit", command=self.quit)

        self.build_ui()

        c = psutil.net_io_counters()
        self.last_recv, self.last_sent, self.last_time = c.bytes_recv, c.bytes_sent, time.time()

        self.icon = None
        self.setup_tray()

        if start_hidden:
            self.root.withdraw()

        self.root.after(1000, self.tick)
        self.root.after(150, self.poll)

    # ---- UI (لوحة صغيرة: سطر للتحميل، سطر للرفع، وسطر صغير للإجماليات)
    def size_name(self):
        for n, v in SCALES.items():
            if abs(v - self.scale) < 0.01:
                return n
        return "Small"

    def build_ui(self):
        if self.frame is not None:
            self.frame.destroy()
        s = self.scale
        f_arrow = ("Segoe UI", int(round(10 * s)), "bold")
        f_speed = ("Consolas", int(round(10 * s)), "bold")
        f_small = ("Consolas", max(7, int(round(8 * s))))

        f = tk.Frame(self.root, bg=BG, padx=int(8 * s), pady=int(3 * s),
                     highlightbackground=BORDER, highlightthickness=1)
        f.pack()
        self.frame = f

        for r, (arrow, key, color) in enumerate((("\u2193", "down", FG_DOWN),
                                                 ("\u2191", "up", FG_UP))):
            tk.Label(f, text=arrow, bg=BG, fg=color, font=f_arrow
                     ).grid(row=r, column=0, sticky="w")
            tk.Label(f, textvariable=self.v[key], bg=BG, fg=color, font=f_speed,
                     anchor="e", width=12).grid(row=r, column=1, sticky="e")

        tk.Label(f, textvariable=self.v["totals"], bg=BG, fg=FG_MUTED, font=f_small
                 ).grid(row=2, column=0, columnspan=2, sticky="ew")

        self.bind_all(f)
        self.bind_all(self.root)

    def bind_all(self, w):
        w.bind("<ButtonPress-1>", self.start_move)
        w.bind("<B1-Motion>", self.do_move)
        w.bind("<ButtonRelease-1>", self.end_move)
        w.bind("<Button-3>", lambda e: self.menu.tk_popup(e.x_root, e.y_root))
        for c in w.winfo_children():
            self.bind_all(c)

    # ---- السحب: اسحب اللوحة من أي مكان فيها
    def start_move(self, e):
        self._ox = e.x_root - self.root.winfo_x()
        self._oy = e.y_root - self.root.winfo_y()

    def do_move(self, e):
        self.root.geometry(f"+{e.x_root - self._ox}+{e.y_root - self._oy}")

    def end_move(self, e):
        self.store.pos = [self.root.winfo_x(), self.root.winfo_y()]
        self.store.save()

    # ---- options
    def set_scale(self, name):
        self.scale = SCALES[name]
        self.store.scale = self.scale
        self.size_var.set(name)
        self.build_ui()
        self.store.save()

    def toggle_top(self):
        self.on_top = not self.on_top
        self.top_var.set(self.on_top)
        self.root.attributes("-topmost", self.on_top)

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
        def size_item(name):
            return pystray.MenuItem(
                name, lambda i, it, n=name: self.cmds.put("size:" + n),
                checked=lambda it, n=name: self.size_name() == n, radio=True)

        menu = pystray.Menu(
            pystray.MenuItem("Show / Hide", lambda i, it: self.cmds.put("toggle"), default=True),
            pystray.MenuItem("Size", pystray.Menu(*[size_item(n) for n in SCALES])),
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
                    self.toggle_top()
                elif cmd == "startup":
                    set_startup(not startup_enabled())
                elif cmd.startswith("size:"):
                    self.set_scale(cmd.split(":", 1)[1])
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
        td, tu = self.store.total(today)
        md, mu = self.store.total(today[:7])

        self.v["down"].set(fmt_speed(down_kb))
        self.v["up"].set(fmt_speed(up_kb))
        self.v["totals"].set(f"Today {fmt_bytes(td + tu)}  |  Month {fmt_bytes(md + mu)}")

        try:
            self.icon.title = (f"\u2193 {fmt_speed(down_kb)}   \u2191 {fmt_speed(up_kb)}\n"
                               f"Today: {fmt_bytes(td)} \u2193  {fmt_bytes(tu)} \u2191\n"
                               f"Month: {fmt_bytes(md)} \u2193  {fmt_bytes(mu)} \u2191")
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
