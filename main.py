# -*- coding: utf-8 -*-
"""
鼠标助手 - 定时模拟鼠标点击 / 上下滚动
纯标准库实现（ctypes + tkinter），无第三方依赖。
适用于 Windows 10 / 11。
"""

import ctypes
import os
import queue
import sys
import threading
import time
import tkinter as tk
from ctypes import wintypes

APP_NAME = "鼠标助手"
APP_VERSION = "1.1.0"

# ---------------------------------------------------------------- Win32 ----

user32 = ctypes.WinDLL("user32", use_last_error=True)

ULONG_PTR = ctypes.c_size_t

INPUT_MOUSE = 0
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
WHEEL_DELTA = 120

VK_F9 = 0x78
WM_HOTKEY = 0x0312
HOTKEY_ID = 0xA11

# ---- 全局快捷键：修饰键与虚拟键表 ----
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

# 动作键（内部标识）
ACT_TOGGLE_CLICK = "toggle_click"
ACT_TOGGLE_SCROLL = "toggle_scroll"
ACT_PICK = "pick"
ACT_START = "start"
ACT_STOP = "stop"

ACTION_LABELS = {
    ACT_TOGGLE_CLICK: "规则一开关",
    ACT_TOGGLE_SCROLL: "规则二开关",
    ACT_PICK: "取当前坐标",
    ACT_START: "开始",
    ACT_STOP: "停止",
}

DEFAULT_HOTKEYS = {
    ACT_TOGGLE_CLICK: "F6",
    ACT_TOGGLE_SCROLL: "F7",
    ACT_PICK: "F8",
    ACT_START: "F9",
    ACT_STOP: "F10",
}

# 虚拟键码
VK_CODES = {}
for _i in range(1, 25):
    VK_CODES["F%d" % _i] = 0x6F + _i  # F1=0x70
for _c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
    VK_CODES[_c] = ord(_c)
for _c in "0123456789":
    VK_CODES[_c] = ord(_c)
VK_CODES.update({
    "SPACE": 0x20, "TAB": 0x09, "ENTER": 0x0D, "ESC": 0x1B,
    "BACKSPACE": 0x08, "INSERT": 0x2D, "DELETE": 0x2E,
    "HOME": 0x24, "END": 0x23, "PAGEUP": 0x21, "PAGEDOWN": 0x22,
    "LEFT": 0x25, "UP": 0x26, "RIGHT": 0x27, "DOWN": 0x28,
    "`": 0xC0, "-": 0xBD, "=": 0xBB, "[": 0xDB, "]": 0xDD,
    "\\": 0xDC, ";": 0xBA, "'": 0xDE, ",": 0xBC, ".": 0xBE, "/": 0xBF,
})

# 显示名（中文界面用）
KEY_DISPLAY = {"PAGEUP": "PgUp", "PAGEDOWN": "PgDn", "BACKSPACE": "退格",
               "ENTER": "回车", "ESC": "Esc", "SPACE": "空格",
               "INSERT": "Ins", "DELETE": "Del", "HOME": "Home", "END": "End",
               "LEFT": "←", "UP": "↑", "RIGHT": "→", "DOWN": "↓"}


def parse_hotkey(text):
    """把 'Ctrl+Alt+F6' 解析为 (modifiers, vk)。失败返回 (None, None)。"""
    if not text:
        return None, None
    mods = 0
    key = None
    for part in str(text).replace(" ", "").split("+"):
        if not part:
            continue
        up = part.upper()
        if up in ("CTRL", "CONTROL"):
            mods |= MOD_CONTROL
        elif up == "ALT":
            mods |= MOD_ALT
        elif up == "SHIFT":
            mods |= MOD_SHIFT
        elif up in ("WIN", "WINDOWS", "META"):
            mods |= MOD_WIN
        else:
            if key is not None:
                return None, None
            key = up
    if key is None or key not in VK_CODES:
        return None, None
    return mods, VK_CODES[key]


def hotkey_display(text):
    """规范显示名：ctrl+alt+f6 -> Ctrl+Alt+F6"""
    if not text:
        return ""
    out = []
    for part in str(text).replace(" ", "").split("+"):
        if not part:
            continue
        up = part.upper()
        if up in ("CTRL", "CONTROL"):
            out.append("Ctrl")
        elif up == "ALT":
            out.append("Alt")
        elif up == "SHIFT":
            out.append("Shift")
        elif up in ("WIN", "WINDOWS", "META"):
            out.append("Win")
        else:
            out.append(KEY_DISPLAY.get(up, up if len(up) > 1 else up))
    return "+".join(out)


def hotkey_is_safe(text):
    """判断是否与常见软件快捷键冲突（返回 (ok, 提示)）。"""
    mods, vk = parse_hotkey(text)
    if mods is None:
        return False, "格式无法识别"
    disp = hotkey_display(text)
    # 单字母 / 单数字 无修饰键，几乎必然抢占输入
    if mods == 0 and vk is not None and (
            (0x30 <= vk <= 0x39) or (0x41 <= vk <= 0x5A)):
        return False, "单独字母/数字会抢占正常输入"
    # 系统保留组合
    reserved = {
        (MOD_CONTROL | MOD_ALT, 0x2E): "Ctrl+Alt+Del 为系统保留",
        (MOD_ALT, 0x73): "Alt+F4 为系统保留",
        (MOD_ALT, 0x09): "Alt+Tab 为系统保留",
        (MOD_WIN, ord("L")): "Win+L 为系统保留",
        (MOD_WIN, ord("D")): "Win+D 为系统保留",
        (MOD_WIN, ord("E")): "Win+E 为系统保留",
        (MOD_WIN, ord("R")): "Win+R 为系统保留",
        (MOD_WIN, ord("S")): "Win+S 为系统保留",
        (MOD_WIN, ord("Q")): "Win+Q 为系统保留",
        (MOD_WIN, VK_CODES["TAB"]): "Win+Tab 为系统保留",
        (MOD_CONTROL, 0x1B): "Ctrl+Esc 为系统保留",
    }
    if (mods, vk) in reserved:
        return False, reserved[(mods, vk)]
    return True, disp


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


try:
    user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
    user32.SendInput.restype = wintypes.UINT
    user32.GetCursorPos.argtypes = (ctypes.POINTER(POINT),)
    user32.GetCursorPos.restype = wintypes.BOOL
    user32.SetCursorPos.argtypes = (ctypes.c_int, ctypes.c_int)
    user32.SetCursorPos.restype = wintypes.BOOL
    # 消息循环相关：64 位下必须显式声明，否则指针被当 32 位截断
    user32.RegisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int,
                                      wintypes.UINT, wintypes.UINT)
    user32.RegisterHotKey.restype = wintypes.BOOL
    user32.UnregisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int)
    user32.UnregisterHotKey.restype = wintypes.BOOL
    user32.GetMessageW.argtypes = (ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                   wintypes.UINT, wintypes.UINT)
    user32.GetMessageW.restype = ctypes.c_int
    user32.PeekMessageW.argtypes = (ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                    wintypes.UINT, wintypes.UINT, wintypes.UINT)
    user32.PeekMessageW.restype = wintypes.BOOL
except Exception:
    pass


def _send_mouse(flags, data=0):
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.u.mi = MOUSEINPUT(0, 0, data, flags, 0, 0)
    try:
        if user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT)) == 1:
            return True
    except Exception:
        pass
    try:
        user32.mouse_event(flags, 0, 0, data, 0)
        return True
    except Exception:
        return False


def cursor_pos():
    p = POINT()
    try:
        user32.GetCursorPos(ctypes.byref(p))
        return p.x, p.y
    except Exception:
        return 0, 0


def set_cursor_pos(x, y):
    try:
        user32.SetCursorPos(int(x), int(y))
        return True
    except Exception:
        return False


def enable_dpi_awareness():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
        return
    except Exception:
        pass
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass


def system_dpi():
    try:
        return int(user32.GetDpiForSystem())
    except Exception:
        try:
            return int(ctypes.windll.gdi32.GetDeviceCaps(
                ctypes.windll.user32.GetDC(0), 88))
        except Exception:
            return 96


# ---------------------------------------------------------------- 动作 ----

def do_click(button="left", times=1, x=None, y=None):
    """在指定位置（x/y 为 None 时用当前位置）点击，动作完成后回位。"""
    ox, oy = cursor_pos()
    moved = False
    if x is not None and y is not None:
        if abs(ox - x) > 1 or abs(oy - y) > 1:
            set_cursor_pos(x, y)
            moved = True
            time.sleep(0.05)

    if button == "right":
        down, up = MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP
    elif button == "middle":
        down, up = MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP
    else:
        down, up = MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP

    for i in range(max(1, times)):
        _send_mouse(down)
        time.sleep(0.04)
        _send_mouse(up)
        if i + 1 < times:
            time.sleep(0.08)

    if moved:
        time.sleep(0.06)
        set_cursor_pos(ox, oy)


def do_scroll(up_notches=1, down_notches=1, x=None, y=None):
    ox, oy = cursor_pos()
    moved = False
    if x is not None and y is not None:
        if abs(ox - x) > 1 or abs(oy - y) > 1:
            set_cursor_pos(x, y)
            moved = True
            time.sleep(0.05)

    for _ in range(max(0, up_notches)):
        _send_mouse(MOUSEEVENTF_WHEEL, WHEEL_DELTA)
        time.sleep(0.04)
    if up_notches and down_notches:
        time.sleep(0.12)
    for _ in range(max(0, down_notches)):
        _send_mouse(MOUSEEVENTF_WHEEL, -WHEEL_DELTA)
        time.sleep(0.04)

    if moved:
        time.sleep(0.06)
        set_cursor_pos(ox, oy)


# ---------------------------------------------------------------- 引擎 ----

class Engine(threading.Thread):
    def __init__(self, cfg, shared, logq):
        super().__init__(daemon=True)
        self.cfg = cfg
        self.shared = shared
        self.logq = logq
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def _log(self, msg, level="info"):
        self.logq.put(("log", msg, level))

    def _resolve_target(self):
        """返回锁定坐标；未锁定时返回 (None, None) 表示使用光标当前位置。
        注意：不能命名为 _target，threading.Thread.__init__ 会写入实例属性 _target
        并把方法遮盖掉。"""
        if self.cfg["pos"] == "lock" and self.shared.get("lock_pos"):
            return self.shared["lock_pos"]
        return None, None

    def _inside_own_window(self, x, y):
        rect = self.shared.get("rect")
        if not rect:
            return False
        l, t, r, b = rect
        return l <= x <= r and t <= y <= b

    def _tick(self):
        cfg = self.cfg
        # 实时开关：快捷键可在运行中切换规则
        flags = self.shared.get("flags") or {}
        click_on = flags.get("click", cfg["click_on"])
        scroll_on = flags.get("scroll", cfg["scroll_on"])
        if not click_on and not scroll_on:
            self._log("两条规则均已关闭，本轮跳过", "warn")
            return

        lx, ly = self._resolve_target()
        locked = lx is not None

        if locked:
            tx, ty = lx, ly
            where = "坐标 %d, %d" % (lx, ly)
        else:
            tx, ty = cursor_pos()
            where = "鼠标位置 %d, %d" % (tx, ty)
            if self._inside_own_window(tx, ty):
                self._log("跳过本轮：鼠标停在程序窗口上，请移开", "warn")
                return

        if click_on:
            do_click(cfg["button"], cfg["times"], lx, ly)
            nm = {"left": "左键", "right": "右键", "middle": "中键"}[cfg["button"]]
            self._log("点击 · %s · %s" % (nm, where))

        if scroll_on and not self._stop.is_set():
            time.sleep(0.05)
            do_scroll(cfg["up"], cfg["down"], lx, ly)
            self._log("滚动 · 上%d / 下%d 格 · %s" % (cfg["up"], cfg["down"], where))

        self.shared["runs"] = self.shared.get("runs", 0) + 1

    def run(self):
        interval = max(1.0, float(self.cfg["interval"]))
        nxt = time.monotonic() + (0.05 if self.cfg["immediate"] else interval)
        self.shared["next_tick"] = nxt
        while not self._stop.is_set():
            wait = nxt - time.monotonic()
            if wait > 0 and self._stop.wait(wait):
                break
            if self._stop.is_set():
                break
            try:
                self._tick()
            except Exception as exc:  # noqa: BLE001
                self._log("执行出错：%s" % exc, "err")
            nxt += interval
            if nxt < time.monotonic() - interval:
                nxt = time.monotonic() + interval
            self.shared["next_tick"] = nxt
        self.shared["next_tick"] = None
        self.logq.put(("stopped", "", ""))


# ---------------------------------------------------------------- 配色 ----

BG = "#f4f5f7"
CARD = "#ffffff"
LINE = "#e6e8ec"
LINE_S = "#eceef1"
TEXT = "#171a1f"
SUB = "#7a828f"
ACCENT = "#2f6bff"
ACCENT_D = "#1f56e0"
OK = "#12a150"
ERR = "#d92d20"
WARN = "#b45309"
CHIP_BG = "#f2f3f6"
CHIP_HV = "#e8eaee"

FONT = "Microsoft YaHei UI"


# ---------------------------------------------------------------- 自绘控件 ----

class Toggle(tk.Canvas):
    """开关：44x24 药丸形。"""

    def __init__(self, parent, var, command=None, bg=CARD, scale=1.0):
        self.scale = scale
        self.w = int(round(40 * scale))
        self.h = int(round(22 * scale))
        super().__init__(parent, width=self.w, height=self.h, bg=bg,
                         highlightthickness=0, bd=0, cursor="hand2")
        self.var = var
        self.command = command
        self.locked = False
        self._draw()
        self.bind("<Button-1>", self._click)

    def _draw(self):
        self.delete("all")
        on = bool(self.var.get())
        track = ACCENT if on else "#d3d7de"
        r = self.h / 2
        self.create_oval(0, 0, self.h, self.h, fill=track, outline="")
        self.create_oval(self.w - self.h, 0, self.w, self.h, fill=track, outline="")
        self.create_rectangle(r, 0, self.w - r, self.h, fill=track, outline="")
        pad = max(2, int(round(3 * self.scale)))
        kr = r - pad
        cy = self.h / 2
        cx = (self.w - r) if on else r
        self.create_oval(cx - kr, cy - kr, cx + kr, cy + kr, fill="#ffffff", outline="")

    def _click(self, _e=None):
        if self.locked:
            return
        self.var.set(not self.var.get())
        self._draw()
        if self.command:
            self.command()

    def refresh(self):
        self._draw()

    def set_enabled(self, en):
        self.locked = not en
        self.configure(cursor="hand2" if en else "arrow")


class Chip(tk.Label):
    """单选胶囊按钮。"""

    def __init__(self, parent, text, value, group, scale=1.0, bg=CARD):
        self.scale = scale
        self.value = value
        self.group = group
        pad_x = int(round(11 * scale))
        pad_y = int(round(4 * scale))
        super().__init__(parent, text=text, bg=CHIP_BG, fg=TEXT,
                         font=(FONT, 9), padx=pad_x, pady=pad_y,
                         cursor="hand2", bd=0)
        self.bind("<Button-1>", self._click)
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        group.register(self)

    def _click(self, _e=None):
        if self.group.locked:
            return
        self.group.var.set(self.value)
        self.group.refresh()
        if self.group.command:
            self.group.command()

    def _enter(self, _e=None):
        if not self.group.locked and self.group.var.get() != self.value:
            self.configure(bg=CHIP_HV)

    def _leave(self, _e=None):
        self._paint()

    def _paint(self):
        if self.group.var.get() == self.value:
            self.configure(bg=ACCENT, fg="#ffffff")
        else:
            self.configure(bg=CHIP_BG, fg=TEXT)


class ChipGroup:
    def __init__(self, var, command=None):
        self.var = var
        self.members = []
        self.command = command
        self.locked = False

    def register(self, chip):
        self.members.append(chip)
        chip._paint()

    def refresh(self):
        for c in self.members:
            c._paint()

    def set_enabled(self, en):
        self.locked = not en
        for c in self.members:
            c.configure(cursor="hand2" if en else "arrow")
            if en:
                c._paint()
            else:
                c.configure(bg=CHIP_BG, fg="#b6bac2")


class HotkeyManager:
    """全局快捷键注册与消息循环。

    关键约束：RegisterHotKey(None, ...) 把热键绑定到**调用它的线程**，
    WM_HOTKEY 只会投递到那个线程的消息队列。因此注册/注销必须和
    GetMessageW 在同一个线程里执行，否则永远收不到消息。
    """

    BASE_ID = 0x5000

    def __init__(self, on_fire, on_error=None):
        self.on_fire = on_fire
        self.on_error = on_error
        self.registered = {}            # action -> (id, mods, vk, text)
        self._next_id = self.BASE_ID
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._thread = None
        self._req_q = queue.Queue()
        self._res_q = queue.Queue()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self._ready.wait(3.0)

    def _loop(self):
        # 在消息循环线程内建立消息队列
        msg = wintypes.MSG()
        try:
            user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)
        except Exception:
            pass
        self._ready.set()

        while True:
            # 先处理待办的注册/注销请求（在同一个线程内执行）
            try:
                while True:
                    req = self._req_q.get_nowait()
                    kind = req[0]
                    if kind == "exit":
                        self._res_q.put(("exit", None))
                        return
                    elif kind == "register":
                        mapping = req[1]
                        self._res_q.put(("register", self._do_register(mapping)))
                    elif kind == "unregister":
                        self._do_unregister_all()
                        self._res_q.put(("unregister", True))
            except queue.Empty:
                pass

            # 处理窗口消息（含 WM_HOTKEY）
            try:
                r = user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1)  # PM_REMOVE
            except Exception:
                return
            if r:
                if msg.message == WM_HOTKEY:
                    with self._lock:
                        action = None
                        for act, info in self.registered.items():
                            if info[0] == msg.wParam:
                                action = act
                                break
                    if action:
                        try:
                            self.on_fire(action)
                        except Exception:
                            pass
            else:
                time.sleep(0.012)

    def _do_register(self, mapping):
        with self._lock:
            self._unregister_locked()
            result = {}
            seen = {}
            for act, text in mapping.items():
                if not text:
                    result[act] = (False, "未设置")
                    continue
                mods, vk = parse_hotkey(text)
                if mods is None:
                    result[act] = (False, "格式错误")
                    continue
                key = (mods, vk)
                if key in seen:
                    result[act] = (False, "与「%s」重复" %
                                   ACTION_LABELS.get(seen[key], seen[key]))
                    continue
                seen[key] = act

            for act, text in mapping.items():
                if act in result:
                    continue
                mods, vk = parse_hotkey(text)
                hid = self._next_id
                self._next_id += 1
                try:
                    ok = bool(user32.RegisterHotKey(
                        None, hid, mods | MOD_NOREPEAT, vk))
                except Exception:
                    ok = False
                if ok:
                    self.registered[act] = (hid, mods, vk, text)
                    result[act] = (True, hotkey_display(text))
                else:
                    result[act] = (False, "已被其他程序占用")
            return result

    def _unregister_locked(self):
        for act, info in list(self.registered.items()):
            try:
                user32.UnregisterHotKey(None, info[0])
            except Exception:
                pass
        self.registered.clear()

    def _do_unregister_all(self):
        with self._lock:
            self._unregister_locked()

    def register_all(self, mapping):
        """mapping: action -> 'Ctrl+Alt+F6'。返回 {action: (ok, msg)}"""
        self.start()
        try:
            self._req_q.put(("register", dict(mapping)))
            kind, result = self._res_q.get(timeout=5.0)
            return result or {}
        except Exception:
            return {a: (False, "注册超时") for a in mapping}

    def unregister_all(self):
        if not (self._thread and self._thread.is_alive()):
            return
        try:
            self._req_q.put(("unregister", None))
            self._res_q.get(timeout=3.0)
        except Exception:
            pass


class HotkeyRecorder(tk.Toplevel):
    """录制一个快捷键：按下组合即捕获。"""

    def __init__(self, parent, action, current, on_ok, scale=1.0):
        super().__init__(parent)
        self.parent = parent
        self.action = action
        self.on_ok = on_ok
        self.scale = scale
        self.captured = None
        self.transient(parent)
        self.title("设置快捷键")
        self.configure(bg=CARD)
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._cancel)

        pad = int(round(16 * scale))
        wrap = tk.Frame(self, bg=CARD)
        wrap.pack(fill="both", expand=True, padx=pad, pady=pad)

        tk.Label(wrap, text="为「%s」设置快捷键" % ACTION_LABELS.get(action, action),
                 bg=CARD, fg=TEXT, font=(FONT, 11, "bold")).pack(anchor="w")
        tk.Label(wrap, text="直接按下你想要的组合键，例如 Ctrl+Alt+F6",
                 bg=CARD, fg=SUB, font=(FONT, 8)).pack(anchor="w", pady=(int(round(4 * scale)), 0))

        self.box = tk.Label(wrap, text="请按下快捷键…", bg="#f7f8fa", fg="#9aa1ab",
                            font=(FONT, 13, "bold"), height=2,
                            highlightthickness=1, highlightbackground=LINE)
        self.box.pack(fill="x", pady=(int(round(12 * scale)), int(round(10 * scale))))

        self.hint = tk.Label(wrap, text="建议用 F 键或带 Ctrl/Alt 的组合，避免冲突",
                             bg=CARD, fg=SUB, font=(FONT, 8))
        self.hint.pack(anchor="w")

        bar = tk.Frame(wrap, bg=CARD)
        bar.pack(fill="x", pady=(int(round(14 * scale)), 0))
        self.btn_ok = tk.Label(bar, text="确定", bg=ACCENT, fg="#ffffff",
                               font=(FONT, 9, "bold"), padx=int(round(20 * scale)),
                               pady=int(round(6 * scale)), cursor="hand2")
        self.btn_ok.pack(side="left")
        self.btn_ok.bind("<Button-1>", lambda e: self._ok())
        btn_c = tk.Label(bar, text="取消", bg="#f2f3f6", fg=TEXT,
                         font=(FONT, 9), padx=int(round(16 * scale)),
                         pady=int(round(6 * scale)), cursor="hand2")
        btn_c.pack(side="left", padx=(int(round(8 * scale)), 0))
        btn_c.bind("<Button-1>", lambda e: self._cancel())

        self.bind("<KeyPress>", self._on_key)
        self.bind("<Escape>", lambda e: self._cancel())

        self.update_idletasks()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        w, h = self.winfo_width(), self.winfo_height()
        self.geometry("+%d+%d" % (px + (pw - w) // 2, py + (ph - h) // 2))
        self.after(120, self._grab)

    def _grab(self):
        try:
            self.focus_force()
            self.grab_set()
        except Exception:
            pass

    def _on_key(self, e):
        ks = e.keysym
        mods = []
        if e.state & 0x0004:
            mods.append("CTRL")
        if e.state & 0x0001:
            mods.append("SHIFT")
        if e.state & 0x20000 or e.state & 0x0008:
            mods.append("ALT")

        # 忽略单独的修饰键
        if ks in ("Control_L", "Control_R", "Shift_L", "Shift_R",
                  "Alt_L", "Alt_R", "Win_L", "Win_R", "Super_L", "Super_R"):
            return "break"

        key = None
        if ks.startswith("F") and ks[1:].isdigit():
            key = ks
        elif len(ks) == 1:
            key = ks.upper()
        elif ks in ("space", "Tab", "Return", "BackSpace", "Insert", "Delete",
                    "Home", "End", "Prior", "Next", "Left", "Up", "Right", "Down"):
            key = {"space": "SPACE", "Tab": "TAB", "Return": "ENTER",
                   "BackSpace": "BACKSPACE", "Insert": "INSERT", "Delete": "DELETE",
                   "Home": "HOME", "End": "END", "Prior": "PAGEUP",
                   "Next": "PAGEDOWN", "Left": "LEFT", "Up": "UP",
                   "Right": "RIGHT", "Down": "DOWN"}[ks]

        if key is None or key not in VK_CODES:
            self.hint.configure(text="这个键不支持，换一个", fg=ERR)
            return "break"

        text = "+".join(mods + [key]) if mods else key
        ok, info = hotkey_is_safe(text)
        self.captured = text
        self.box.configure(text=hotkey_display(text),
                           fg=TEXT if ok else ERR,
                           bg="#f7f8fa" if ok else "#fdf2f2")
        if ok:
            self.hint.configure(text="按下确定保存，或继续按其他组合", fg=SUB)
        else:
            self.hint.configure(text=info, fg=ERR)
        return "break"

    def _ok(self):
        if not self.captured:
            self.hint.configure(text="还没按键，请先按一个组合键", fg=ERR)
            return
        ok, info = hotkey_is_safe(self.captured)
        if not ok:
            self.hint.configure(text=info, fg=ERR)
            return
        cb = self.on_ok
        text = self.captured
        self._close()
        cb(text)

    def _cancel(self):
        self._close()

    def _close(self):
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()


class HotkeyTag(tk.Label):
    """页面上显示的快捷键括号标记，点击可修改。"""

    def __init__(self, parent, action, app, scale=1.0, bg=CARD):
        self.action = action
        self.app = app
        super().__init__(parent, bg=bg, fg=SUB, font=(FONT, 8),
                         cursor="hand2", bd=0)
        self.bind("<Button-1>", lambda e: app.edit_hotkey(action))
        self.bind("<Enter>", lambda e: self.configure(fg=ACCENT))
        self.bind("<Leave>", lambda e: self.configure(fg=self._fg()))
        self.refresh()

    def _fg(self):
        if self.app.hotkey_state.get(self.action, True):
            return SUB
        return WARN

    def refresh(self):
        text = self.app.hotkeys.get(self.action, "")
        disp = hotkey_display(text) if text else "未设置"
        if not self.app.hotkey_state.get(self.action, True):
            disp += " ⚠"
        self.configure(text="(%s)" % disp, fg=self._fg())


class Stepper(tk.Frame):
    """[-] 数字 [+] 组合，可键盘输入。"""

    def __init__(self, parent, var, lo, hi, width=3, scale=1.0, bg=CARD, command=None):
        self.scale = scale
        self.var = var
        self.lo = lo
        self.hi = hi
        self.command = command
        h = int(round(26 * scale))
        super().__init__(parent, bg="#f2f3f6", highlightthickness=1,
                         highlightbackground=LINE, highlightcolor=LINE)
        f = (FONT, 9)

        self.btn_m = tk.Label(self, text="−", bg="#f2f3f6", fg="#5b6270", font=(FONT, 11),
                              width=2, cursor="hand2")
        self.btn_m.pack(side="left", fill="y")

        self.entry = tk.Entry(self, textvariable=var, width=width, justify="center",
                              bg="#f2f3f6", fg=TEXT, font=f, bd=0,
                              highlightthickness=0, insertbackground=ACCENT)
        self.entry.pack(side="left", fill="both", expand=True, ipady=int(round(3 * scale)))

        self.btn_p = tk.Label(self, text="+", bg="#f2f3f6", fg="#5b6270", font=(FONT, 11),
                              width=2, cursor="hand2")
        self.btn_p.pack(side="left", fill="y")

        for b in (self.btn_m, self.btn_p):
            b.bind("<Enter>", lambda e, w=b: w.configure(bg="#e8eaee"))
            b.bind("<Leave>", lambda e, w=b: w.configure(bg="#f2f3f6"))
        self.btn_m.bind("<Button-1>", lambda e: self._step(-1))
        self.btn_p.bind("<Button-1>", lambda e: self._step(1))
        self.entry.bind("<FocusOut>", lambda e: self._normalize())
        self.entry.bind("<Return>", lambda e: self._normalize())

    def _step(self, d):
        try:
            v = int(str(self.var.get()).strip())
        except Exception:
            v = self.lo
        v = max(self.lo, min(self.hi, v + d))
        self.var.set(str(v))
        if self.command:
            self.command()

    def _normalize(self):
        try:
            v = int(str(self.var.get()).strip())
        except Exception:
            v = self.lo
        self.var.set(str(max(self.lo, min(self.hi, v))))

    def set_enabled(self, en):
        st = "normal" if en else "disabled"
        for w in (self.btn_m, self.btn_p):
            w.configure(cursor="hand2" if en else "arrow",
                        fg="#5b6270" if en else "#c2c6cd")
        self.entry.configure(state=st,
                             disabledbackground="#f2f3f6",
                             disabledforeground="#b6bac2")


class FlatButton(tk.Label):
    """扁平按钮，三种外观：primary / ghost / danger。"""

    def __init__(self, parent, text, command, kind="ghost", scale=1.0, bg=BG, width=None):
        self.kind = kind
        self.enabled = True
        self.scale = scale
        pads = {"primary": (26, 8), "ghost": (18, 8), "danger": (18, 8)}[kind]
        px_ = int(round(pads[0] * scale))
        py_ = int(round(pads[1] * scale))
        colors = {
            "primary": (ACCENT, "#ffffff", ACCENT_D, "#a9bdf5"),
            "ghost": ("#ffffff", TEXT, "#f3f4f7", "#f7f8fa"),
            "danger": ("#fdeeee", ERR, "#fbdcdc", "#f8f2f2"),
        }
        self.bg_n, self.fg_n, self.bg_h, self.bg_d = colors[kind]
        bold = "bold" if kind in ("primary", "danger") else "normal"
        kw = {}
        if width:
            kw["width"] = width
        super().__init__(parent, text=text, bg=self.bg_n, fg=self.fg_n,
                         font=(FONT, 10, bold), padx=px_, pady=py_,
                         cursor="hand2", bd=0,
                         highlightthickness=0 if kind != "ghost" else 1,
                         highlightbackground=LINE, highlightcolor=LINE, **kw)
        self.command = command
        self.bind("<Button-1>", self._click)
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)

    def _click(self, _e=None):
        if self.enabled and self.command:
            self.command()

    def _enter(self, _e=None):
        if self.enabled:
            self.configure(bg=self.bg_h)

    def _leave(self, _e=None):
        if self.enabled:
            self.configure(bg=self.bg_n)

    def set_enabled(self, en):
        self.enabled = en
        if en:
            self.configure(bg=self.bg_n, fg=self.fg_n, cursor="hand2")
        else:
            self.configure(bg=self.bg_d, fg="#ffffff" if self.kind == "primary" else "#b6bac2",
                           cursor="arrow")


class ThinScroll(tk.Canvas):
    """日志用的细滚动条。"""

    def __init__(self, parent, target, scale=1.0, bg=CARD):
        self.sw = max(6, int(round(6 * scale)))
        super().__init__(parent, width=self.sw, height=1, bg=bg,
                         highlightthickness=0, bd=0)
        self.target = target
        self.scale = scale
        self.first, self.last = 0.0, 1.0
        self._drag = False
        self._grab_off = 0
        self._thumb = self.create_rectangle(0, 0, 0, 0, fill="#d6dade", outline="")
        self.bind("<Configure>", lambda e: self._redraw())
        self.tag_bind(self._thumb, "<ButtonPress-1>", self._press_thumb)
        self.bind("<ButtonPress-1>", self._press_page)
        self.bind("<B1-Motion>", self._motion)
        self.bind("<ButtonRelease-1>", lambda e: setattr(self, "_drag", False))

    def _set(self, first, last):
        self.first, self.last = float(first), float(last)
        self._redraw()

    def _span(self):
        return max(0.02, self.last - self.first)

    def _redraw(self):
        h = self.winfo_height() or 1
        y1 = int(self.first * h)
        y2 = int(self.last * h)
        if y2 - y1 < int(round(20 * self.scale)):
            y2 = y1 + int(round(20 * self.scale))
        y2 = min(h, y2)
        if self._span() >= 0.999:
            self.itemconfigure(self._thumb, state="hidden")
        else:
            self.itemconfigure(self._thumb, state="normal")
            self.coords(self._thumb, 1, y1, self.sw - 1, y2)

    def _thumb_bounds(self):
        c = self.coords(self._thumb)
        return (c[1], c[3]) if c else (0, 0)

    def _press_thumb(self, e):
        top, _ = self._thumb_bounds()
        self._drag = True
        self._grab_off = e.y - top
        return "break"

    def _press_page(self, e):
        top, bot = self._thumb_bounds()
        if top <= e.y <= bot:
            return "break"
        h = self.winfo_height() or 1
        span = self._span()
        frac = max(0.0, min(1.0 - span, e.y / h - span / 2))
        self.target.yview_moveto(frac)
        self._set(*self.target.yview())

    def _motion(self, e):
        if not self._drag:
            return
        h = self.winfo_height() or 1
        span = self._span()
        frac = (e.y - self._grab_off) / h
        frac = max(0.0, min(1.0 - span, frac))
        self.target.yview_moveto(frac)
        self._set(*self.target.yview())


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("%s v%s" % (APP_NAME, APP_VERSION))
        self.root.configure(bg=BG)

        self.scale = max(1.0, system_dpi() / 96.0)
        try:
            self.root.tk.call("tk", "scaling", system_dpi() / 72.0)
        except Exception:
            pass

        self.logq = queue.Queue()
        self.engine = None
        self.running = False
        self._building = True
        self.shared = {"rect": None, "lock_pos": None, "next_tick": None,
                       "runs": 0, "flags": {"click": True, "scroll": True}}
        self.lock_pos = None

        # 快捷键配置（持久化到 ini）
        self.hotkeys = dict(DEFAULT_HOTKEYS)
        self.hotkey_state = {a: True for a in DEFAULT_HOTKEYS}
        self._load_hotkeys()

        self.var_click = tk.BooleanVar(value=True)
        self.var_button = tk.StringVar(value="left")
        self.var_pos = tk.StringVar(value="follow")
        self.var_scroll = tk.BooleanVar(value=True)
        self.var_up = tk.StringVar(value="1")
        self.var_down = tk.StringVar(value="1")
        self.var_min = tk.StringVar(value="5")
        self.var_sec = tk.StringVar(value="0")
        self.var_immediate = tk.BooleanVar(value=False)

        self._build()
        self.hk = HotkeyManager(self._on_hotkey)
        self._apply_hotkeys(quiet=True)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(200, self._pump)
        self._set_running(False)
        self._center()
        self._append("就绪。设置好规则后点「开始」。", "info")

    # -- 工具 --
    def px(self, n):
        return int(round(n * self.scale))

    def _center(self):
        self.root.update_idletasks()
        w, h = self.root.winfo_width(), self.root.winfo_height()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.geometry("+%d+%d" % ((sw - w) // 2, max(24, (sh - h) // 3)))

    def card(self, parent):
        return tk.Frame(parent, bg=CARD, highlightthickness=1,
                        highlightbackground=LINE, highlightcolor=LINE)

    def label(self, parent, text, size=9, bold=False, color=TEXT, bg=CARD, **kw):
        return tk.Label(parent, text=text, bg=bg, fg=color,
                        font=(FONT, size, "bold" if bold else "normal"), **kw)

    # -- 构建 --
    def _build(self):
        root = self.root
        pad = self.px(16)
        outer = tk.Frame(root, bg=BG)
        outer.pack(fill="both", expand=True, padx=pad, pady=pad)

        # ===== 顶部 =====
        head = tk.Frame(outer, bg=BG)
        head.pack(fill="x", pady=(0, self.px(12)))
        hl = tk.Frame(head, bg=BG)
        hl.pack(side="left", anchor="w")
        self.label(hl, APP_NAME, size=14, bold=True, bg=BG).pack(anchor="w")
        self.label(hl, "定时模拟鼠标点击与上下滚动", size=8, color=SUB, bg=BG).pack(
            anchor="w", pady=(self.px(2), 0))

        hr = tk.Frame(head, bg=BG)
        hr.pack(side="right", anchor="e")
        self.dot = tk.Canvas(hr, width=self.px(8), height=self.px(8), bg=BG,
                             highlightthickness=0, bd=0)
        self.dot.pack(side="left", padx=(0, self.px(6)))
        self._dot = self.dot.create_oval(0, 0, self.px(8), self.px(8), fill="#c4c9d1", outline="")
        self.lbl_state = self.label(hr, "未运行", size=9, bold=True, color=SUB, bg=BG)
        self.lbl_state.pack(side="left")
        self.lbl_next = self.label(hr, "", size=8, color=SUB, bg=BG)
        self.lbl_next.pack(side="left", padx=(self.px(8), 0))

        # ===== 规则一 =====
        c1 = self.card(outer)
        c1.pack(fill="x")
        b1 = tk.Frame(c1, bg=CARD)
        b1.pack(fill="x", padx=self.px(16), pady=self.px(13))

        r1 = tk.Frame(b1, bg=CARD)
        r1.pack(fill="x")
        self.label(r1, "规则一　定时点击鼠标", size=10, bold=True).pack(side="left")
        self.tag_c1 = HotkeyTag(r1, ACT_TOGGLE_CLICK, self, self.scale)
        self.tag_c1.pack(side="left", padx=(self.px(5), 0))
        self.tg_click = Toggle(r1, self.var_click, self._sync, scale=self.scale)
        self.tg_click.pack(side="right", padx=(0, self.px(1)))
        self.lbl_c1 = self.label(r1, "按间隔循环", size=8, color=SUB)
        self.lbl_c1.pack(side="right", padx=(0, self.px(9)))

        # 按键 / 位置
        g1 = tk.Frame(b1, bg=CARD)
        g1.pack(fill="x", pady=(self.px(11), 0))
        self.label(g1, "按键", size=8, color=SUB).pack(side="left", padx=(0, self.px(9)))
        self.chips_btn = ChipGroup(self.var_button, self._sync)
        for txt, val in (("左键", "left"), ("右键", "right"), ("中键", "middle")):
            Chip(g1, txt, val, self.chips_btn, self.scale).pack(side="left", padx=(0, self.px(5)))

        g1b = tk.Frame(b1, bg=CARD)
        g1b.pack(fill="x", pady=(self.px(8), 0))
        self.label(g1b, "位置", size=8, color=SUB).pack(side="left", padx=(0, self.px(9)))
        self.chips_pos = ChipGroup(self.var_pos, self._sync)
        for txt, val in (("跟随鼠标", "follow"), ("锁定坐标", "lock")):
            Chip(g1b, txt, val, self.chips_pos, self.scale).pack(side="left", padx=(0, self.px(5)))
        self.btn_pick = FlatButton(g1b, "取当前坐标", self._take_pos, "ghost",
                                   self.scale, width=8)
        self.btn_pick.pack(side="left", padx=(self.px(6), 0))
        self.tag_pick = HotkeyTag(g1b, ACT_PICK, self, self.scale)
        self.tag_pick.pack(side="left", padx=(self.px(4), 0))
        self.lbl_lock = self.label(g1b, "", size=8, color=ACCENT)
        self.lbl_lock.pack(side="left", padx=(self.px(8), 0))

        # ===== 规则二 =====
        c2 = self.card(outer)
        c2.pack(fill="x", pady=(self.px(10), 0))
        b2 = tk.Frame(c2, bg=CARD)
        b2.pack(fill="x", padx=self.px(16), pady=self.px(13))

        r2 = tk.Frame(b2, bg=CARD)
        r2.pack(fill="x")
        self.label(r2, "规则二　定时上下滚动", size=10, bold=True).pack(side="left")
        self.tag_c2 = HotkeyTag(r2, ACT_TOGGLE_SCROLL, self, self.scale)
        self.tag_c2.pack(side="left", padx=(self.px(5), 0))
        self.tg_scroll = Toggle(r2, self.var_scroll, self._sync, scale=self.scale)
        self.tg_scroll.pack(side="right", padx=(0, self.px(1)))
        self.lbl_c2 = self.label(r2, "按间隔循环", size=8, color=SUB)
        self.lbl_c2.pack(side="right", padx=(0, self.px(9)))

        g2 = tk.Frame(b2, bg=CARD)
        g2.pack(fill="x", pady=(self.px(11), 0))
        self.label(g2, "向上", size=8, color=SUB).pack(side="left", padx=(0, self.px(7)))
        self.st_up = Stepper(g2, self.var_up, 0, 30, 2, self.scale)
        self.st_up.pack(side="left")
        self.label(g2, "格", size=8, color=SUB).pack(side="left", padx=(self.px(5), self.px(12)))
        self.label(g2, "向下", size=8, color=SUB).pack(side="left", padx=(0, self.px(7)))
        self.st_down = Stepper(g2, self.var_down, 0, 30, 2, self.scale)
        self.st_down.pack(side="left")
        self.label(g2, "格", size=8, color=SUB).pack(side="left", padx=(self.px(5), 0))

        # ===== 节拍 =====
        c3 = self.card(outer)
        c3.pack(fill="x", pady=(self.px(10), 0))
        b3 = tk.Frame(c3, bg=CARD)
        b3.pack(fill="x", padx=self.px(16), pady=self.px(13))

        r3 = tk.Frame(b3, bg=CARD)
        r3.pack(fill="x")
        self.label(r3, "执行间隔", size=10, bold=True).pack(side="left")
        self.label(r3, "每条规则各自按此节奏触发", size=8, color=SUB).pack(
            side="left", padx=(self.px(10), 0))

        r3b = tk.Frame(b3, bg=CARD)
        r3b.pack(fill="x", pady=(self.px(11), 0))
        self.st_min = Stepper(r3b, self.var_min, 0, 1440, 3, self.scale)
        self.st_min.pack(side="left")
        self.label(r3b, "分", size=8, color=SUB).pack(side="left", padx=(self.px(5), self.px(10)))
        self.st_sec = Stepper(r3b, self.var_sec, 0, 59, 2, self.scale)
        self.st_sec.pack(side="left")
        self.label(r3b, "秒", size=8, color=SUB).pack(side="left", padx=(self.px(5), 0))

        imm = tk.Frame(r3b, bg=CARD)
        imm.pack(side="right")
        self.label(imm, "启动后先执行一次", size=8, color=SUB).pack(side="left", padx=(0, self.px(7)))
        self.tg_imm = Toggle(imm, self.var_immediate, None, scale=self.scale)
        self.tg_imm.pack(side="left")

        # ===== 操作栏 =====
        bar = tk.Frame(outer, bg=BG)
        bar.pack(fill="x", pady=(self.px(14), 0))
        self.btn_start = FlatButton(bar, "开 始", self.start, "primary", self.scale, bg=BG)
        self.btn_start.pack(side="left")
        self.bar_start_tag = HotkeyTag(bar, ACT_START, self, self.scale, bg=BG)
        self.bar_start_tag.pack(side="left", padx=(self.px(4), self.px(10)))

        self.btn_stop = FlatButton(bar, "停 止", self.stop, "danger", self.scale, bg=BG)
        self.btn_stop.pack(side="left")
        self.bar_stop_tag = HotkeyTag(bar, ACT_STOP, self, self.scale, bg=BG)
        self.bar_stop_tag.pack(side="left", padx=(self.px(4), self.px(10)))

        self.btn_test = FlatButton(bar, "测试一次", self.test_once, "ghost", self.scale, bg=BG)
        self.btn_test.pack(side="left")

        self.lbl_hk_hint = self.label(bar, "点括号可改键", size=8, color=SUB, bg=BG)
        self.lbl_hk_hint.pack(side="right")

        # ===== 日志 =====
        c4 = self.card(outer)
        c4.pack(fill="both", expand=True, pady=(self.px(14), 0))
        b4 = tk.Frame(c4, bg=CARD)
        b4.pack(fill="both", expand=True, padx=self.px(14), pady=self.px(11))

        lh = tk.Frame(b4, bg=CARD)
        lh.pack(fill="x")
        self.label(lh, "运行记录", size=8, bold=True, color=SUB).pack(side="left")
        self.lbl_runs = self.label(lh, "已执行 0 次", size=8, color=SUB)
        self.lbl_runs.pack(side="right")

        wrap = tk.Frame(b4, bg="#fbfcfd", highlightthickness=1,
                        highlightbackground=LINE_S, highlightcolor=LINE_S)
        wrap.pack(fill="both", expand=True, pady=(self.px(8), 0))

        self.log = tk.Text(wrap, height=4, bg="#fbfcfd", fg="#3a4049", bd=0,
                           highlightthickness=0, font=(FONT, 8), wrap="word",
                           padx=self.px(9), pady=self.px(6), insertwidth=0,
                           cursor="arrow", state="disabled", spacing1=1, spacing3=2)
        sb = ThinScroll(wrap, self.log, self.scale, bg="#fbfcfd")
        self.log.configure(yscrollcommand=sb._set)
        self.log.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y", padx=(0, self.px(3)), pady=self.px(3))

        self._sync()
        self.root.minsize(self.px(520), self.px(560))
        self.root.resizable(False, True)
        self._building = False

    # -- 交互 --
    def _sync(self):
        if getattr(self, "_building", True):
            return
        c1 = bool(self.var_click.get())
        c2 = bool(self.var_scroll.get())
        run = bool(self.running)
        self.lbl_c1.configure(text="按间隔循环" if c1 else "已关闭")
        self.lbl_c2.configure(text="按间隔循环" if c2 else "已关闭")
        self.lbl_c1.configure(fg=SUB if c1 else "#b6bac2")
        self.lbl_c2.configure(fg=SUB if c2 else "#b6bac2")
        lock = self.var_pos.get() == "lock"
        if not lock and self.lbl_lock.cget("text"):
            self.lbl_lock.configure(text="")

        editable = not run
        self.chips_btn.set_enabled(editable and c1)
        self.chips_pos.set_enabled(editable and c1)
        self.st_up.set_enabled(editable and c2)
        self.st_down.set_enabled(editable and c2)
        self.st_min.set_enabled(editable)
        self.st_sec.set_enabled(editable)
        self.btn_pick.set_enabled(c1)
        # 运行中仍可用快捷键/开关切换规则，只是不改动其它参数
        self.tg_click.set_enabled(True)
        self.tg_scroll.set_enabled(True)
        self.tg_imm.set_enabled(editable)
        # 引擎读取的实时开关
        self.shared["flags"]["click"] = c1
        self.shared["flags"]["scroll"] = c2

    def _take_pos(self, from_hotkey=False):
        x, y = cursor_pos()
        if self._in_own_window(x, y):
            self._toast("鼠标在程序窗口上，请移到目标处再取坐标")
            return
        self.lock_pos = (x, y)
        self.shared["lock_pos"] = (x, y)
        self.lbl_lock.configure(text="已锁定 %d, %d" % (x, y))
        self._append("已锁定坐标 %d, %d%s" % (x, y, "（快捷键）" if from_hotkey else ""), "ok")
        # 取坐标后自动切到锁定模式
        if self.var_pos.get() != "lock":
            self.var_pos.set("lock")
            self.chips_pos.refresh()
            self._sync()

    def _in_own_window(self, x, y):
        rect = self.shared.get("rect")
        if not rect:
            return False
        l, t, r, b = rect
        return l <= x <= r and t <= y <= b

    def _toast(self, msg):
        self._append(msg, "warn")

    def _append(self, msg, level="info"):
        color = {"info": "#3a4049", "warn": WARN, "err": ERR, "ok": OK}.get(level, "#3a4049")
        self.log.configure(state="normal")
        self.log.insert("end", "%s  " % time.strftime("%H:%M:%S"), ("ts",))
        self.log.insert("end", msg + "\n", (level,))
        self.log.tag_configure("ts", foreground="#a8aeb8")
        for lv, c in (("info", "#3a4049"), ("warn", WARN), ("err", ERR), ("ok", OK)):
            self.log.tag_configure(lv, foreground=c)
        self.log.see("end")
        try:
            if int(self.log.index("end-1c").split(".")[0]) > 250:
                self.log.delete("1.0", "60.0")
        except Exception:
            pass
        self.log.configure(state="disabled")

    def _read_int(self, var, default, lo, hi):
        try:
            v = int(str(var.get()).strip())
        except Exception:
            return default
        return max(lo, min(hi, v))

    def _collect(self):
        if not (self.var_click.get() or self.var_scroll.get()):
            self._toast("请至少开启一条规则")
            return None

        pos = "lock" if self.var_pos.get() == "lock" else "follow"
        if pos == "lock" and not self.lock_pos:
            x, y = cursor_pos()
            if self._in_own_window(x, y):
                self._toast("请先把鼠标移到目标处再点「开始」")
                return None
            self.lock_pos = (x, y)
            self.shared["lock_pos"] = (x, y)
            self.lbl_lock.configure(text="已锁定 %d, %d" % (x, y))

        minutes = self._read_int(self.var_min, 5, 0, 1440)
        seconds = self._read_int(self.var_sec, 0, 0, 59)
        interval = minutes * 60 + seconds
        if interval < 1:
            self._toast("执行间隔至少 1 秒")
            return None

        up = self._read_int(self.var_up, 1, 0, 30)
        down = self._read_int(self.var_down, 1, 0, 30)
        if self.var_scroll.get() and up == 0 and down == 0:
            self._toast("滚动格数不能同时为 0")
            return None

        self.var_min.set(str(minutes))
        self.var_sec.set(str(seconds))

        return {
            "click_on": bool(self.var_click.get()),
            "button": self.var_button.get(),
            "times": 1,
            "scroll_on": bool(self.var_scroll.get()),
            "up": up,
            "down": down,
            "pos": pos,
            "interval": interval,
            "immediate": bool(self.var_immediate.get()),
        }

    def start(self):
        if self.engine and self.engine.is_alive():
            return
        cfg = self._collect()
        if not cfg:
            return

        self.shared["runs"] = 0
        self.shared["lock_pos"] = self.lock_pos
        self.shared["flags"]["click"] = bool(self.var_click.get())
        self.shared["flags"]["scroll"] = bool(self.var_scroll.get())
        self.engine = Engine(cfg, self.shared, self.logq)
        self.engine.start()
        self._set_running(True)

        acts = []
        if cfg["click_on"]:
            nm = {"left": "左键", "right": "右键", "middle": "中键"}[cfg["button"]]
            acts.append("%s点击" % nm)
        if cfg["scroll_on"]:
            acts.append("上%d下%d滚动" % (cfg["up"], cfg["down"]))
        self._append("已启动 · %s · 每 %s一次（可用快捷键实时开关规则）"
                     % (" + ".join(acts), self._fmt_iv(cfg["interval"])), "ok")

    def stop(self, quiet=False):
        running = self.engine and self.engine.is_alive()
        if running:
            self.engine.stop()
            self.engine = None
        self._set_running(False)
        if running and not quiet:
            self._append("已停止", "warn")

    def test_once(self):
        cfg = self._collect()
        if not cfg:
            return
        if cfg["pos"] == "lock":
            lx, ly = self.lock_pos
            tx, ty = lx, ly
        else:
            lx = ly = None
            tx, ty = cursor_pos()
            if self._in_own_window(tx, ty):
                self._toast("鼠标正停在程序窗口上，请移开后再测试")
                return
        try:
            if cfg["click_on"]:
                do_click(cfg["button"], 1, lx, ly)
            if cfg["scroll_on"]:
                time.sleep(0.12)
                do_scroll(cfg["up"], cfg["down"], lx, ly)
            self._append("测试执行完成 · 目标 %d, %d" % (tx, ty), "ok")
        except Exception as exc:  # noqa: BLE001
            self._append("测试失败：%s" % exc, "err")

    def _fmt_iv(self, sec):
        m, s = divmod(int(sec), 60)
        if m and s:
            return "%d分%d秒" % (m, s)
        return ("%d分钟" % m) if m else ("%d秒" % s)

    def _set_running(self, on):
        self.running = bool(on)
        if on:
            self.dot.itemconfigure(self._dot, fill=OK)
            self.lbl_state.configure(text="运行中", fg=OK)
            self.btn_start.set_enabled(False)
            self.btn_stop.set_enabled(True)
            self.btn_test.set_enabled(False)
            self.btn_pick.set_enabled(True)
        else:
            self.dot.itemconfigure(self._dot, fill="#c4c9d1")
            self.lbl_state.configure(text="未运行", fg=SUB)
            self.lbl_next.configure(text="")
            self.btn_start.set_enabled(True)
            self.btn_stop.set_enabled(False)
            self.btn_test.set_enabled(True)
        self._sync()

    # -- 主循环 --
    def _pump(self):
        try:
            while True:
                item = self.logq.get_nowait()
                kind = item[0]
                if kind == "log":
                    self._append(item[1], item[2])
                elif kind == "stopped":
                    if self.lbl_state.cget("text") == "运行中":
                        self._set_running(False)
        except queue.Empty:
            pass

        try:
            if self.root.state() != "iconic":
                x, y = self.root.winfo_rootx(), self.root.winfo_rooty()
                self.shared["rect"] = (x, y, x + self.root.winfo_width(),
                                       y + self.root.winfo_height())
            else:
                self.shared["rect"] = None
        except Exception:
            self.shared["rect"] = None

        nxt = self.shared.get("next_tick")
        if nxt and self.engine and self.engine.is_alive():
            left = int(max(0, nxt - time.monotonic())) + 1
            self.lbl_next.configure(text="下次 %d 秒后" % left if left < 60
                                    else "下次 %d 分 %d 秒后" % (left // 60, left % 60))
            self.lbl_runs.configure(text="已执行 %d 次" % self.shared.get("runs", 0))
        self.root.after(200, self._pump)

    # -- 快捷键 --
    def _config_path(self):
        try:
            base = os.path.dirname(os.path.abspath(sys.argv[0]))
        except Exception:
            base = os.getcwd()
        return os.path.join(base, "hotkeys.ini")

    def _load_hotkeys(self):
        path = self._config_path()
        try:
            if not os.path.exists(path):
                return
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip()
                    if k in self.hotkeys and v:
                        self.hotkeys[k] = v
        except Exception:
            pass

    def _save_hotkeys(self):
        path = self._config_path()
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("# 鼠标助手 快捷键配置\n")
                f.write("# 格式：动作=组合键，例：toggle_click=F6 / start=Ctrl+Alt+S\n")
                for act in (ACT_TOGGLE_CLICK, ACT_TOGGLE_SCROLL,
                            ACT_PICK, ACT_START, ACT_STOP):
                    f.write("%s=%s\n" % (act, self.hotkeys.get(act, "")))
        except Exception as exc:  # noqa: BLE001
            self._append("快捷键保存失败（不影响本次使用）：%s" % exc, "warn")

    def _apply_hotkeys(self, quiet=False):
        """按当前配置注册全部快捷键，并把结果显示到页面括号上。"""
        result = self.hk.register_all(self.hotkeys)
        problems = []
        for act, (ok, info) in result.items():
            self.hotkey_state[act] = ok
            if not ok:
                problems.append("%s %s" % (ACTION_LABELS.get(act, act), info))
        self._refresh_hotkey_tags()
        if problems and not quiet:
            self._append("快捷键注册失败：" + "；".join(problems), "warn")
        elif not quiet:
            self._append("快捷键已生效：" + "  ".join(
                "%s %s" % (ACTION_LABELS.get(a, a), hotkey_display(self.hotkeys.get(a, "")))
                for a in DEFAULT_HOTKEYS), "info")
        return result

    def _refresh_hotkey_tags(self):
        for w in (getattr(self, "tag_c1", None), getattr(self, "tag_c2", None),
                  getattr(self, "tag_pick", None), getattr(self, "bar_start_tag", None),
                  getattr(self, "bar_stop_tag", None)):
            if w is not None:
                try:
                    w.refresh()
                except Exception:
                    pass

    def edit_hotkey(self, action):
        """打开录制对话框修改某个动作的快捷键。"""
        HotkeyRecorder(self.root, action, self.hotkeys.get(action, ""),
                       lambda text: self._on_hotkey_set(action, text),
                       self.scale)

    def _on_hotkey_set(self, action, text):
        disp = hotkey_display(text)
        # 与其他动作查重
        for act, val in self.hotkeys.items():
            if act != action and val and hotkey_display(val).upper() == disp.upper():
                self._append("「%s」已被「%s」占用，未修改" %
                             (disp, ACTION_LABELS.get(act, act)), "err")
                return
        self.hotkeys[action] = text
        self._save_hotkeys()
        res = self._apply_hotkeys(quiet=True)
        ok, info = res.get(action, (False, ""))
        if ok:
            self._append("「%s」快捷键已改为 %s" % (ACTION_LABELS.get(action, action), disp), "ok")
        else:
            self._append("「%s」设为 %s 失败：%s" %
                         (ACTION_LABELS.get(action, action), disp, info), "err")
        self._refresh_hotkey_tags()

    def _on_hotkey(self, action):
        """工作线程收到热键，转到主线程执行。"""
        try:
            self.root.after(0, lambda: self._hotkey_action(action))
        except Exception:
            pass

    def _hotkey_action(self, action):
        if action == ACT_TOGGLE_CLICK:
            v = not self.var_click.get()
            self.var_click.set(v)
            self.shared["flags"]["click"] = v
            self.tg_click.refresh()
            self._sync()
            self._append("快捷键：规则一已%s" % ("开启" if v else "关闭"), "warn" if not v else "ok")
        elif action == ACT_TOGGLE_SCROLL:
            v = not self.var_scroll.get()
            self.var_scroll.set(v)
            self.shared["flags"]["scroll"] = v
            self.tg_scroll.refresh()
            self._sync()
            self._append("快捷键：规则二已%s" % ("开启" if v else "关闭"), "warn" if not v else "ok")
        elif action == ACT_PICK:
            self._take_pos(from_hotkey=True)
        elif action == ACT_START:
            if not self.running:
                self.start()
            else:
                self._append("已在运行中", "warn")
        elif action == ACT_STOP:
            if self.running:
                self.stop()
            else:
                self._append("当前未运行", "warn")

    def _on_close(self):
        if self.engine and self.engine.is_alive():
            self.engine.stop()
            time.sleep(0.05)
        try:
            self.hk.unregister_all()
        except Exception:
            pass
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    enable_dpi_awareness()
    App().run()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        import os
        try:
            base = os.path.dirname(os.path.abspath(sys.argv[0]))
            path = os.path.join(base, "error.log")
            with open(path, "w", encoding="utf-8") as f:
                f.write("Python: %s\n" % sys.version)
                f.write("Frozen: %s\n" % getattr(sys, "frozen", False))
                f.write("MeiPath: %s\n" % getattr(sys, "_MEIPASS", "n/a"))
                f.write(traceback.format_exc())
        except Exception:
            pass
        raise