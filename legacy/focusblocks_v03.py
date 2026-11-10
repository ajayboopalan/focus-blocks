"""
focusblocks.py - automatic focus-block tracker for Windows (prototype v0.3)

  pythonw focusblocks.py           floating pill + tracker (no console)
  python  focusblocks.py           same, with console log (for testing)
  python  focusblocks.py --nogui   tracker only
  python  focusblocks.py --test    test mode: 1-min blocks, 30-s breaks, separate data,
                                   plus a Test menu to jump to any moment
  python  focusblocks.py report    build heatmap.html and open it

Install:  pip install pyvda winotify opencv-python psutil pillow
Settings: %USERPROFILE%\\.focusblocks\\config.json (created on first run).
          Edit it, then right-click the pill -> Reload settings.
"""
import ctypes
import datetime as dt
import json
import math
import os
import queue
import sqlite3
import sys
import threading
import time
import webbrowser
from pathlib import Path

DATA_DIR = Path.home() / ".focusblocks"
DB_PATH = DATA_DIR / "focus.db"
CONFIG_PATH = DATA_DIR / "config.json"
POS_PATH = DATA_DIR / "pill.json"
SNAP_DIR = DATA_DIR / "snaps"
CONFIG_VERSION = 2

DEFAULT_CONFIG = {
    "block_minutes": 25,
    "break_minutes": 5,
    "daily_goal": 9,
    "break_mode": "notify",        # "notify" or "overlay" (full screen, skippable)
    "pause_resume": "manual",      # "manual" or "auto" (resumes when you're back on work)
    "work_desktops": ["Work"],     # virtual desktop names
    "work_apps": [],               # process names, e.g. "Code.exe", "ms-teams.exe"
    "tag_hotkey": "ctrl+alt+w",    # tag/untag the focused window (any tab in it counts)
    "count_meetings": True,        # mic or camera in use counts as work
    "camera_fallback": True,       # webcam face check when idle mid-block
    "idle_seconds": 60,            # no input this long on a work source -> camera check
    "camera_recheck_seconds": 120,
    "abandon_minutes": 15,
    "nudge_minutes": 3,
    "lunch_nudge_seconds": 60,     # work activity during lunch before "back at your desk?"
    "lunch_snooze_minutes": 10,
}
TEST_MODE = False
TEST_OVERRIDES = {                 # starting values for the separate test config
    "block_minutes": 1, "break_minutes": 0.5, "idle_seconds": 15, "camera_recheck_seconds": 20,
    "abandon_minutes": 2, "nudge_minutes": 0.5, "lunch_nudge_seconds": 10, "lunch_snooze_minutes": 1,
}


def use_test_data() -> None:
    """Point every file at ~/.focusblocks-test so tests never touch real stats."""
    global TEST_MODE, DATA_DIR, DB_PATH, CONFIG_PATH, POS_PATH, SNAP_DIR
    real_config = CONFIG_PATH
    TEST_MODE = True
    DATA_DIR = Path.home() / ".focusblocks-test"
    DB_PATH, CONFIG_PATH = DATA_DIR / "focus.db", DATA_DIR / "config.json"
    POS_PATH, SNAP_DIR = DATA_DIR / "pill.json", DATA_DIR / "snaps"
    if not CONFIG_PATH.exists():
        DATA_DIR.mkdir(exist_ok=True)
        cfg = dict(DEFAULT_CONFIG, **TEST_OVERRIDES, config_version=CONFIG_VERSION)
        try:   # reuse your real work sources so tests behave like your day
            real = json.loads(real_config.read_text(encoding="utf-8"))
            for key in ("work_desktops", "work_apps", "break_mode", "pause_resume", "daily_goal"):
                if key in real:
                    cfg[key] = real[key]
        except Exception:
            pass
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def load_config() -> dict:
    DATA_DIR.mkdir(exist_ok=True)
    cfg = dict(DEFAULT_CONFIG, config_version=CONFIG_VERSION)
    try:
        cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    except FileNotFoundError:
        pass
    except Exception as e:
        notify("Settings not loaded", f"config.json has an error ({e}). Using defaults.")
        return cfg                     # don't overwrite a file the user is editing
    if cfg.get("config_version", 1) < 2:   # v0.3: camera check after 60 s instead of 120 s
        cfg["idle_seconds"] = 60
    cfg["config_version"] = CONFIG_VERSION
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")  # adds new keys
    return cfg


# ---------------- Windows signals ----------------
class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def idle_seconds() -> float:
    lii = _LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(lii)
    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii))
    k32 = ctypes.windll.kernel32
    k32.GetTickCount.restype = ctypes.c_uint
    return ((k32.GetTickCount() - lii.dwTime) & 0xFFFFFFFF) / 1000


_com = threading.local()


def com_init() -> None:
    """pyvda talks to Windows through COM, which every thread must initialise once."""
    if not getattr(_com, "done", False):
        try:
            ctypes.windll.ole32.CoInitialize(None)
        except Exception:
            pass
        _com.done = True


def exe_of_pid(pid: int) -> str:
    try:
        import psutil
        return psutil.Process(pid).name()
    except Exception:
        return ""


def window_pid(hwnd) -> int:
    pid = ctypes.c_ulong()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def window_title(hwnd) -> str:
    u = ctypes.windll.user32
    n = u.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    u.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def foreground():
    """(hwnd, pid, exe, title) of the focused top-level window, or None."""
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    if not hwnd:
        return None
    pid = window_pid(hwnd)
    return hwnd, pid, exe_of_pid(pid), window_title(hwnd)


def window_alive(hwnd) -> bool:
    return bool(ctypes.windll.user32.IsWindow(hwnd))


def _desk_label(d) -> str:
    return (d.name or "").strip() or f"Desktop {d.number}"


def current_desktop():
    """Name of the current virtual desktop ("Desktop 2" if unnamed); None if pyvda isn't available."""
    try:
        com_init()
        from pyvda import VirtualDesktop
        return _desk_label(VirtualDesktop.current())
    except Exception:
        return None


def list_desktops():
    """[{name, number, apps: [exe, ...], current}] for every virtual desktop."""
    try:
        com_init()
        from pyvda import VirtualDesktop, get_virtual_desktops, get_apps_by_z_order
        cur = VirtualDesktop.current().number
        apps = {}
        try:
            for view in get_apps_by_z_order(current_desktop=False):
                try:
                    exe = exe_of_pid(window_pid(view.hwnd))
                    lst = apps.setdefault(view.desktop.number, [])
                    if exe and exe not in lst:
                        lst.append(exe)
                except Exception:
                    pass
        except Exception:
            pass
        return [dict(name=_desk_label(d), number=d.number, apps=apps.get(d.number, []),
                     current=d.number == cur) for d in get_virtual_desktops()]
    except Exception:
        return []


def running_apps():
    """{exe: a window title} for apps with visible windows right now."""
    from ctypes import wintypes
    u, found, me = ctypes.windll.user32, {}, os.getpid()

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if u.IsWindowVisible(hwnd) and u.GetWindowTextLengthW(hwnd) > 0:
            pid = window_pid(hwnd)
            if pid != me:
                exe = exe_of_pid(pid)
                if exe and exe not in found:
                    found[exe] = window_title(hwnd)
        return True

    try:
        u.EnumWindows(cb, 0)
    except Exception:
        pass
    for skip in ("TextInputHost.exe", "SystemSettings.exe", "ShellExperienceHost.exe"):
        found.pop(skip, None)
    return found


def snap_path(desktop: str) -> Path:
    slug = "".join(ch if ch.isalnum() else "_" for ch in desktop.lower()) or "desktop"
    return SNAP_DIR / f"{slug}.png"


def snapshot_desktop(desktop: str) -> bool:
    """Save a small screenshot of what's on screen as this desktop's preview. Local only."""
    try:
        from PIL import ImageGrab, ImageOps
        SNAP_DIR.mkdir(parents=True, exist_ok=True)
        img = ImageOps.fit(ImageGrab.grab(), (480, 300))
        img.save(snap_path(desktop))
        return True
    except Exception:
        return False


def animations_enabled() -> bool:
    """Respects Windows Settings > Accessibility > Visual effects > Animation effects."""
    try:
        val = ctypes.c_int(1)
        ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(val), 0)
        return bool(val.value)
    except Exception:
        return True


def pin_everywhere(win) -> None:
    """Show a Tk window on every virtual desktop."""
    try:
        com_init()
        from pyvda import AppView
        AppView(hwnd=int(win.wm_frame(), 16)).pin()
    except Exception:
        pass


def device_in_use(kind: str) -> bool:
    """True if any app is using the 'webcam' or 'microphone' right now.
    Reads Windows' privacy registry (no device access, so it never disturbs a meeting)."""
    import winreg
    base = rf"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\{kind}"

    def scan(path: str) -> bool:
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, path)
        except OSError:
            return False
        with key:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(key, i)
                except OSError:
                    return False
                i += 1
                sub_path = rf"{path}\{sub}"
                if sub == "NonPackaged":  # desktop apps live one level deeper
                    if scan(sub_path):
                        return True
                    continue
                try:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub_path) as k:
                        stop, _ = winreg.QueryValueEx(k, "LastUsedTimeStop")
                        if stop == 0:  # started and not yet stopped = in use
                            return True
                except OSError:
                    pass

    try:
        return scan(base)
    except Exception:
        return False


_cascade = None


def face_seen() -> bool:
    """Open the webcam for ~1 second, look for a face, release it."""
    global _cascade
    try:
        import cv2
    except ImportError:
        return False
    if _cascade is None:
        _cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    try:
        if not cap.isOpened():
            return False
        for _ in range(10):  # first frames are dark while exposure settles
            ok, frame = cap.read()
            if not ok:
                continue
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            if len(_cascade.detectMultiScale(gray, 1.1, 5, minSize=(60, 60))):
                return True
        return False
    finally:
        cap.release()


# ---------------- notifications ----------------
def notify(title: str, msg: str) -> None:
    print(f"{dt.datetime.now():%H:%M:%S} [{title}] {msg}")
    try:
        from winotify import Notification, audio
        n = Notification(app_id="Focus Blocks", title=title, msg=msg or " ", duration="short")
        n.set_audio(audio.Default, loop=False)
        n.show()
    except Exception:
        pass


# ---------------- storage ----------------
def open_db() -> sqlite3.Connection:
    DATA_DIR.mkdir(exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.execute("""CREATE TABLE IF NOT EXISTS blocks(
        id INTEGER PRIMARY KEY, day TEXT, started TEXT, ended TEXT,
        minutes REAL, completed INTEGER)""")
    con.execute("""CREATE TABLE IF NOT EXISTS events(
        id INTEGER PRIMARY KEY, day TEXT, at TEXT, kind TEXT, minutes REAL)""")
    return con


def log_block(con, started: dt.datetime, minutes: float, completed: bool) -> None:
    con.execute(
        "INSERT INTO blocks(day, started, ended, minutes, completed) VALUES (?,?,?,?,?)",
        (started.date().isoformat(), started.isoformat(timespec="seconds"),
         dt.datetime.now().isoformat(timespec="seconds"), round(minutes, 1), int(completed)))
    con.commit()


def log_event(con, kind: str, minutes: float = 0.0) -> None:
    """kind: pause | skip_break | reset | lunch"""
    now = dt.datetime.now()
    con.execute("INSERT INTO events(day, at, kind, minutes) VALUES (?,?,?,?)",
                (now.date().isoformat(), now.isoformat(timespec="seconds"), kind, round(minutes, 1)))
    con.commit()


# ---------------- engine ----------------
class Engine:
    """State machine on a background thread. The UI reads its attributes and
    sends commands through send(); it never touches the engine's state directly."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.q = queue.Queue()
        self.mode = "WORK"            # WORK | BREAK | WAIT | PAUSED | LUNCH
        self.status, self.detail = "idle", "Starting..."
        self.worked = 0.0             # seconds counted in the current block
        self.away = 0.0
        self.block_start = None
        self.break_end = 0.0
        self.overlay = False          # show the full-screen break overlay
        self.last_nudge = 0.0
        self.cam_at, self.cam_result = 0.0, False
        self.paused_from, self.pause_at, self.pause_left = "WORK", 0.0, False
        self.lunch_at = 0.0
        self.done = self.partial = 0
        self.day = None
        self.goal_sent_for = None
        self.held_since = None        # when the current block got auto-paused
        self.lunch_active = 0.0       # seconds of work activity seen during lunch
        self.lunch_nudge = False      # "back at your desk?" prompt is showing
        self.lunch_snooze_until = 0.0
        self.last_snap, self.snap_desk, self.desk_changed_at = {}, None, 0.0
        self.fg = None                # last focused window that isn't ours
        self.tags = {}                # hwnd -> title of windows tagged as work
        self.con = None

    def send(self, *cmd) -> None:
        self.q.put(cmd)

    # ----- main loop -----
    def run(self) -> None:
        self.con = open_db()
        self.refresh_counts()
        notify("Focus Blocks", f"Tracking started - {self.done}/{self.cfg['daily_goal']} blocks today.")
        last = next_tick = time.time()
        while True:
            try:
                cmd = self.q.get(timeout=max(0.0, next_tick - time.time()))
                try:
                    self.handle(*cmd)
                except Exception as e:
                    print("command failed:", cmd, e)
                continue
            except queue.Empty:
                pass
            now = time.time()
            tick = min(now - last, 5.0)       # cap after sleep/hibernate
            last, next_tick = now, now + 1.0
            try:
                self.step(now, tick)
            except Exception as e:
                print("step failed:", e)

    def refresh_counts(self) -> None:
        today = dt.date.today().isoformat()
        self.day = today
        self.done, self.partial = (int(x or 0) for x in self.con.execute(
            "SELECT SUM(completed=1), SUM(completed=0) FROM blocks WHERE day=?", (today,)).fetchone())

    def reset_block(self) -> None:
        self.worked, self.away, self.block_start, self.held_since = 0.0, 0.0, None, None

    # ----- what counts as work -----
    def update_foreground(self) -> None:
        fg = foreground()
        if fg and fg[1] != os.getpid():
            self.fg = fg
        for h in [h for h in self.tags if not window_alive(h)]:
            del self.tags[h]

    def work_source(self):
        """Why the current window counts as work, or None."""
        desktops = [d.lower() for d in self.cfg["work_desktops"]]
        apps = [a.lower() for a in self.cfg["work_apps"]]
        if not desktops and not apps and not self.tags:
            return "any window"
        if self.fg:
            hwnd, _, exe, _ = self.fg
            if hwnd in self.tags:
                return "a tagged window"
            if exe and exe.lower() in apps:
                return exe[:-4] if exe.lower().endswith(".exe") else exe
        if desktops:
            d = current_desktop()
            if d is None:
                return "any window (desktop check unavailable)"
            if d.lower() in desktops:
                return f"the {d} desktop"
        return None

    def is_working(self, allow_camera: bool = True) -> bool:
        cfg = self.cfg
        if cfg["count_meetings"] and (device_in_use("microphone") or device_in_use("webcam")):
            self.status, self.detail = "meeting", "Mic or camera in use, counting"
            return True
        source = self.work_source()
        if not source:
            name = (self.fg[2] if self.fg else "") or "This window"
            if name.lower().endswith(".exe"):
                name = name[:-4]
            if self.block_start is None:
                self.status, self.detail = "idle", f"{name} isn't a work source. Open one to start."
            else:
                self.status, self.detail = "auto_paused", f"{name} isn't a work source. Resumes on a work window."
            return False
        if idle_seconds() < cfg["idle_seconds"]:
            self.cam_result, self.cam_at = True, 0.0
            self.status, self.detail = "working", f"Counting {source}"
            return True
        if self.block_start is None:
            self.status, self.detail = "idle", "Starts when you use a work window"
            return False
        if not (allow_camera and cfg["camera_fallback"]):
            self.status, self.detail = "auto_paused", "No activity. Resumes when you're back."
            return False
        if self.cam_at and not self.cam_result:
            self.status = "auto_paused"          # keeps the "no one on camera" detail
            return False
        now = time.time()
        if now - self.cam_at >= cfg["camera_recheck_seconds"]:
            self.status, self.detail = "checking", "No input for a minute. Webcam on for a second."
            self.cam_at = now
            self.cam_result = face_seen()
            if not self.cam_result:              # you left: remove the idle grace period
                self.worked = max(0.0, self.worked - cfg["idle_seconds"])
                self.detail = f"No one on camera at {dt.datetime.now():%H:%M}. Resumes when you're back."
        if self.cam_result:
            self.status, self.detail = "reading", "No typing, but you're here"
        else:
            self.status = "auto_paused"
        return self.cam_result

    def maybe_snapshot(self, now: float) -> None:
        """Keep a fresh preview of each desktop for the settings picker."""
        if self.mode in ("LUNCH", "BREAK"):
            return
        desk = current_desktop()
        if not desk:
            return
        if desk != self.snap_desk:
            self.snap_desk, self.desk_changed_at = desk, now
            return
        if now - self.desk_changed_at < 3 or idle_seconds() > 30:
            return
        if now - self.last_snap.get(desk, 0) >= 300 and snapshot_desktop(desk):
            self.last_snap[desk] = now

    # ----- one tick -----
    def step(self, now: float, tick: float) -> None:
        cfg = self.cfg
        if self.day != dt.date.today().isoformat():
            self.refresh_counts()
        self.update_foreground()
        self.maybe_snapshot(now)

        if self.mode == "LUNCH":
            self.status = "lunch"
            if self.work_source() and idle_seconds() < 10:
                self.lunch_active += tick
            elif idle_seconds() > 30:
                self.lunch_active = 0.0
            if not self.lunch_nudge and self.lunch_active >= cfg["lunch_nudge_seconds"] and now >= self.lunch_snooze_until:
                self.lunch_nudge = True
                notify("Back at your desk?", "Hover the pill to end lunch.")
            self.detail = "Looks like you're back" if self.lunch_nudge else "Tracking off until you end lunch"
            return

        if self.mode == "PAUSED":
            if cfg["pause_resume"] == "auto":
                working = self.is_working(allow_camera=False)
                if not working:
                    self.pause_left = True
                elif self.pause_left:
                    self.resume(now)
                    notify("Resumed", "You're back on work.")
                    return
                self.detail = "Resumes when you're back on work"
            else:
                self.detail = "Click Resume to continue"
            self.status = "paused"
            return

        if self.mode == "BREAK":
            self.status, self.detail = "break", "Stand up, look away, stretch"
            if now >= self.break_end:
                self.mode, self.last_nudge, self.overlay = "WAIT", now, False
                self.status = "wait"
                notify("Back to work", "Break's over - open a work window.")
            return

        working = self.is_working()

        if self.mode == "WAIT":
            if not working:
                self.status, self.detail = "wait", "Next block starts on a work window"
                if now - self.last_nudge >= cfg["nudge_minutes"] * 60:
                    self.last_nudge = now
                    notify("Still on break?", "Your next block starts when you're back.")
                return
            self.mode = "WORK"

        if working:
            if self.block_start is None:
                self.block_start = dt.datetime.now()
            self.worked += tick
            self.away, self.held_since = 0.0, None
        elif self.block_start is not None:
            self.held_since = self.held_since or now
            self.away += tick
            if self.away >= cfg["abandon_minutes"] * 60:
                if self.worked >= 60:
                    log_block(self.con, self.block_start, self.worked / 60, False)
                self.reset_block()
                self.refresh_counts()

        if self.worked >= cfg["block_minutes"] * 60:
            self.complete_block(now)

    def complete_block(self, now: float) -> None:
        cfg = self.cfg
        in_meeting = self.status == "meeting"
        log_block(self.con, self.block_start, self.worked / 60, True)
        self.reset_block()
        self.refresh_counts()
        self.mode, self.break_end = "BREAK", now + cfg["break_minutes"] * 60
        self.status, self.detail = "break", "Stand up, look away, stretch"
        # never cover the screen during a meeting
        self.overlay = cfg["break_mode"] == "overlay" and not in_meeting
        n, goal = self.done, cfg["daily_goal"]
        today = dt.date.today()
        if n >= goal and self.goal_sent_for != today:
            self.goal_sent_for = today
            notify("Daily goal hit", f"{n} blocks done today. Take your break.")
        elif not self.overlay:
            notify(f"Take a {cfg['break_minutes']:g}-min break", f"Block {n} of {goal} done.")

    # ----- commands from the UI / hotkey -----
    def resume(self, now: float) -> None:
        if self.mode != "PAUSED":
            return
        log_event(self.con, "pause", (now - self.pause_at) / 60)
        if self.paused_from == "BREAK":
            self.break_end += now - self.pause_at      # keep the remaining break
        self.mode = self.paused_from
        self.cam_at = 0.0

    def handle(self, cmd: str, *args) -> None:
        now = time.time()
        if cmd == "toggle_pause":
            if self.mode == "PAUSED":
                self.resume(now)
            elif self.mode != "LUNCH":
                self.paused_from, self.pause_at, self.pause_left = self.mode, now, False
                self.mode, self.status = "PAUSED", "paused"
                self.detail = ("Resumes when you're back on work"
                               if self.cfg["pause_resume"] == "auto" else "Click Resume to continue")
        elif cmd == "skip_break":
            if self.mode in ("BREAK", "WAIT"):
                left = max(0.0, self.break_end - now) / 60 if self.mode == "BREAK" else 0.0
                log_event(self.con, "skip_break", left)
                self.mode, self.overlay, self.status = "WORK", False, "idle"
                self.detail = "Starts when you use a work window"
        elif cmd == "reset":
            if self.worked > 0 and self.mode in ("WORK", "PAUSED"):
                log_event(self.con, "reset", self.worked / 60)
                self.reset_block()
        elif cmd == "lunch":
            if self.mode == "LUNCH":
                log_event(self.con, "lunch", (now - self.lunch_at) / 60)
                self.mode, self.status, self.cam_at = "WORK", "idle", 0.0
                self.lunch_nudge = False
                self.detail = "Starts when you use a work window"
                notify("Lunch over", f"{self.done} of {self.cfg['daily_goal']} blocks so far.")
            else:
                self.lunch_at, self.mode, self.overlay, self.away = now, "LUNCH", False, 0.0
                self.lunch_active, self.lunch_nudge, self.held_since = 0.0, False, None
                self.status, self.detail = "lunch", "Tracking off until you end lunch"
        elif cmd == "lunch_snooze":
            self.lunch_nudge, self.lunch_active = False, 0.0
            self.lunch_snooze_until = now + self.cfg["lunch_snooze_minutes"] * 60
        elif cmd == "tag_toggle":
            hwnd, title = args
            if hwnd in self.tags:
                del self.tags[hwnd]
                notify("Window untagged", title[:80])
            else:
                self.tags[hwnd] = title
                notify("Window tagged as work", title[:80])
        elif cmd == "untag_all":
            self.tags.clear()
        elif cmd == "test_finish_block":           # jump to the end of the current block
            if self.mode == "WORK":
                self.block_start = self.block_start or dt.datetime.now()
                self.worked = self.cfg["block_minutes"] * 60
        elif cmd == "test_end_break":
            if self.mode == "BREAK":
                self.break_end = now
        elif cmd == "test_lunch_nudge":
            if self.mode == "LUNCH":
                self.lunch_active, self.lunch_snooze_until = self.cfg["lunch_nudge_seconds"], 0.0
        elif cmd == "test_camera":                 # force a camera check on the next tick
            self.cam_at = 0.0
            self.cam_result = True
        elif cmd == "reload":
            self.cfg.update(load_config())
            notify("Settings reloaded", "")


# ---------------- global hotkey ----------------
def parse_hotkey(spec: str):
    mods, vk = 0, 0
    for part in spec.lower().replace(" ", "").split("+"):
        if part in ("ctrl", "control"):
            mods |= 0x2
        elif part == "alt":
            mods |= 0x1
        elif part == "shift":
            mods |= 0x4
        elif part == "win":
            mods |= 0x8
        elif len(part) == 1 and part.isalnum():
            vk = ord(part.upper())
        elif part.startswith("f") and part[1:].isdigit():
            vk = 0x6F + int(part[1:])
    return mods, vk


def hotkey_loop(engine: Engine) -> None:
    from ctypes import wintypes
    spec = engine.cfg["tag_hotkey"]
    mods, vk = parse_hotkey(spec)
    u = ctypes.windll.user32
    if not vk or not u.RegisterHotKey(None, 1, mods | 0x4000, vk):   # 0x4000 = no repeat
        notify("Hotkey unavailable", f"{spec} is taken. Change tag_hotkey in settings.")
        return
    msg = wintypes.MSG()
    while u.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
        if msg.message == 0x0312:                                     # WM_HOTKEY
            fg = foreground()
            if fg and fg[1] != os.getpid():
                engine.send("tag_toggle", fg[0], fg[3] or fg[2])


# ---------------- look ----------------
INK, TEXT, MUTED, SUB = "#16191e", "#f2f1ee", "#a3abb5", "#c4cad1"
TRACK, LINE, BTN, BTN_HOT, BTN_OFF, OFF_TEXT = "#2e343d", "#2a2f37", "#262b33", "#323843", "#1d2127", "#6b737d"
KEY = "#010203"                       # painted transparent: gives the pill rounded corners
COL = {"focus": "#7cc79a", "camera": "#e9b25a", "paused": "#8e99a6", "meeting": "#a897f0",
       "break": "#6db3ee", "wait": "#f07a62", "lunch": "#e89a62"}
STATUS = {  # engine status -> (label, colour key)
    "working": ("Focusing", "focus"), "reading": ("Focusing", "focus"),
    "meeting": ("In a meeting", "meeting"), "checking": ("Checking on camera", "camera"),
    "auto_paused": ("Paused automatically", "paused"), "paused": ("Paused", "paused"),
    "idle": ("Ready", "paused"), "break": ("Break", "break"), "wait": ("Back to work", "wait"),
    "lunch": ("Lunch", "lunch"),
}
# settings window (light)
W_BG, W_NAV, W_LINE, W_INK, W_SUB, W_FAINT = "#fbfbfc", "#f1f2f4", "#e1e4e8", "#1c2027", "#4b535e", "#6b737d"
W_GREEN, W_CHECK_OFF, W_SEL_ROW = "#2f7a52", "#b8bec6", "#f2f8f4"
BADGES = ["#2f6fd0", "#5b5fc7", "#3a6fd8", "#1f6fbf", "#1d8a4a", "#b98a1c", "#a8467a", "#4a7d8c"]


def mmss(sec: float) -> str:
    sec = max(0, int(sec))
    return f"{sec // 60}:{sec % 60:02d}"


def hmm(sec: float) -> str:
    m = max(0, int(sec)) // 60
    return f"{m // 60}:{m % 60:02d}"


def mix(a: str, b: str, t: float) -> str:
    a, b = [int(a[i:i + 2], 16) for i in (1, 3, 5)], [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def hop_offset(t: float) -> float:
    """Two soft hops, then rest, every 4.2 s (in px, negative = up)."""
    p = (t % 4.2) / 4.2
    if p < 0.2:
        return -9 * math.sin(math.pi * p / 0.2)
    if p < 0.34:
        return -4 * math.sin(math.pi * (p - 0.2) / 0.14)
    return 0.0


class Kit:
    """Fonts and drawing helpers shared by the pill, overlay and settings window."""

    def __init__(self, root):
        from tkinter import font as tkfont
        self.S = S = root.winfo_fpixels("1i") / 96
        fams = set(tkfont.families(root))

        def pick(*names):
            return next((n for n in names if n in fams), names[-1])

        self.num = pick("Bahnschrift", "Segoe UI")
        self.num_sb = pick("Bahnschrift SemiBold", self.num)
        self.num_light = pick("Bahnschrift Light", self.num)
        self.ui = pick("Segoe UI Variable Text", "Segoe UI")
        self.ui_sb = pick("Segoe UI Variable Text Semibold", "Segoe UI Semibold", self.ui)
        cache = {}

        def F(fam, px, bold=False):
            key = (fam, px, bold)
            if key not in cache:
                cache[key] = tkfont.Font(root, family=fam, size=-max(1, round(px * S)),
                                         weight="bold" if bold else "normal")
            return cache[key]

        self.F = F

    def num_bold(self, px):
        return self.F(self.num_sb, px, self.num_sb == self.num)

    def ui_bold(self, px):
        return self.F(self.ui_sb, px, self.ui_sb == self.ui)

    _n = 0

    @classmethod
    def rrect(cls, cv, x1, y1, x2, y2, r, fill="", outline="", width=1):
        """Rounded rectangle with true circular corners (r = half the height gives a pill).
        Built from ovals and rectangles, so the ends are real semicircles.
        Returns a tag covering all its parts (usable with tag_lower / delete)."""
        cls._n += 1
        tag = f"rr{cls._n}"
        r = max(0.0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
        if fill and outline:
            cls._solid(cv, x1, y1, x2, y2, r, outline, tag)
            cls._solid(cv, x1 + width, y1 + width, x2 - width, y2 - width, max(0.0, r - width), fill, tag)
        elif fill:
            cls._solid(cv, x1, y1, x2, y2, r, fill, tag)
        elif outline:
            cls._ring(cv, x1, y1, x2, y2, r, outline, width, tag)
        return tag

    @staticmethod
    def _solid(cv, x1, y1, x2, y2, r, color, tag):
        if r < 1:
            cv.create_rectangle(x1, y1, x2, y2, fill=color, outline="", tags=tag)
            return
        d = 2 * r
        for ox, oy in ((x1, y1), (x2 - d, y1), (x1, y2 - d), (x2 - d, y2 - d)):
            cv.create_oval(ox, oy, ox + d, oy + d, fill=color, outline="", tags=tag)
        cv.create_rectangle(x1 + r, y1, x2 - r, y2, fill=color, outline="", tags=tag)
        cv.create_rectangle(x1, y1 + r, x2, y2 - r, fill=color, outline="", tags=tag)

    @staticmethod
    def _ring(cv, x1, y1, x2, y2, r, color, width, tag):
        d = 2 * r
        for bx, by, start in ((x1, y1, 90), (x2 - d, y1, 0), (x2 - d, y2 - d, 270), (x1, y2 - d, 180)):
            cv.create_arc(bx, by, bx + d, by + d, start=start, extent=90, style="arc",
                          outline=color, width=width, tags=tag)
        for a in ((x1 + r, y1, x2 - r, y1), (x2, y1 + r, x2, y2 - r),
                  (x1 + r, y2, x2 - r, y2), (x1, y1 + r, x1, y2 - r)):
            cv.create_line(*a, fill=color, width=width, tags=tag)

    @staticmethod
    def fit(text, font, width):
        if font.measure(text) <= width:
            return text
        while text and font.measure(text + "...") > width:
            text = text[:-1]
        return text + "..."

    @staticmethod
    def ring(cv, cx, cy, r, width, frac, color):
        cv.create_oval(cx - r, cy - r, cx + r, cy + r, outline=TRACK, width=width)
        if frac >= 0.999:
            cv.create_oval(cx - r, cy - r, cx + r, cy + r, outline=color, width=width)
        elif frac > 0.005:
            cv.create_arc(cx - r, cy - r, cx + r, cy + r, start=90, extent=-360 * frac,
                          style="arc", outline=color, width=width)

    @staticmethod
    def hit(buttons, x, y):
        for b in reversed(buttons):
            if b["x1"] <= x <= b["x2"] and b["y1"] <= y <= b["y2"]:
                return b
        return None

    def button(self, cv, store, x, y, w, h, label, action, enabled=True, kind="normal",
               hot=None, font=None, radius=9, **extra):
        """kinds: normal | primary (light) | accent (lunch) | dark (settings save) | outline | icon"""
        S = self.S
        is_hot = enabled and hot is not None and hot.get("id") == (label, action)
        fills = {"normal": (BTN, BTN_HOT, TEXT), "primary": ("#e9eaec", "#ffffff", INK),
                 "accent": (COL["lunch"], "#f0ab7a", "#1d140d"), "dark": (W_INK, "#343a44", "#ffffff"),
                 "outline": ("#ffffff", "#f3f4f6", W_INK), "icon": (BTN, BTN_HOT, TEXT)}
        base, hov, fg = fills[kind]
        fill = hov if is_hot else base
        if not enabled:
            fill, fg = BTN_OFF, OFF_TEXT
        self.rrect(cv, x, y, x + w, y + h, radius * S, fill=fill,
                   outline=W_LINE if kind == "outline" else "", width=1)
        if kind == "icon":
            for dx in (-6, 0, 6):
                cv.create_oval(x + w / 2 + (dx - 1.8) * S, y + h / 2 - 1.8 * S,
                               x + w / 2 + (dx + 1.8) * S, y + h / 2 + 1.8 * S, fill=SUB, outline="")
        else:
            bold = kind in ("primary", "accent", "dark")
            f = font or (self.ui_bold(12.5) if bold else self.F(self.ui, 12.5))
            cv.create_text(x + w / 2, y + h / 2, text=label, font=f, fill=fg)
        b = dict(x1=x, y1=y, x2=x + w, y2=y + h, action=action, enabled=enabled, id=(label, action))
        b.update(extra)
        store.append(b)
        return b


# ---------------- floating pill ----------------
class Pill:
    M = 9                     # transparent margin around the pill, room for the lunch glow

    def __init__(self, engine: Engine):
        import tkinter as tk
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)     # crisp text on high-DPI screens
        except Exception:
            pass
        self.tk, self.e = tk, engine
        self.root = root = tk.Tk()
        root.title("Focus Blocks")
        self.k = Kit(root)
        self.S = S = self.k.S
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.configure(bg=KEY)
        try:
            root.attributes("-transparentcolor", KEY)
        except tk.TclError:
            pass
        self.cv = tk.Canvas(root, bg=KEY, highlightthickness=0, bd=0)
        self.cv.pack(fill="both", expand=True)
        try:
            self.right, self.top = json.loads(POS_PATH.read_text())
        except Exception:
            self.right, self.top = root.winfo_screenwidth() - int(16 * S), int(16 * S)
        self.expanded, self.leave_at, self.menu_open = False, None, False
        self.buttons, self.hot, self.geom = [], None, ""
        self.press, self.dragging = None, False
        self.ov, self.ov_cv, self.ov_buttons, self.ov_hot = None, None, [], None
        self.settings = None
        self.anim = animations_enabled()

        cv = self.cv
        cv.bind("<ButtonPress-1>", self.on_press)
        cv.bind("<B1-Motion>", self.on_drag)
        cv.bind("<ButtonRelease-1>", self.on_release)
        cv.bind("<Motion>", lambda ev: setattr(self, "hot", self.k.hit(self.buttons, ev.x, ev.y)))
        cv.bind("<Button-3>", lambda ev: self.show_menu(ev.x_root, ev.y_root))
        self.menu = tk.Menu(root, tearoff=0)
        root.after(300, lambda: pin_everywhere(root))
        root.after(60_000, self.refresh_anim_setting)
        self.loop()

    def refresh_anim_setting(self):
        self.anim = animations_enabled()
        self.root.after(60_000, self.refresh_anim_setting)

    def place(self, w, h):
        geom = f"{int(w)}x{int(h)}+{int(self.right - w)}+{int(self.top)}"
        if geom != self.geom:
            self.root.geometry(geom)
            self.geom = geom

    # ----- what to show -----
    def view(self):
        e, cfg, now = self.e, self.e.cfg, time.time()
        goal, blk, brk = cfg["daily_goal"], cfg["block_minutes"] * 60, cfg["break_minutes"] * 60
        current = e.done + 1
        label, ck = STATUS.get(e.status, (e.status, "paused"))
        v = dict(label=label, color=COL[ck], clock_color=TEXT, paused_icon=False,
                 count=f"{e.done}/{goal}", ring_text=f"{current}/{goal}")
        mode = e.paused_from if e.mode == "PAUSED" else e.mode
        if mode == "BREAK":
            left = e.break_end - (e.pause_at if e.mode == "PAUSED" else now)
            v.update(clock=mmss(left), sub=f"of a {cfg['break_minutes']:g}-min break", frac=left / brk,
                     ring_text=f"{e.done}/{goal}")
        elif e.mode == "LUNCH":
            v.update(clock=hmm(now - e.lunch_at), sub="on lunch, tracking off", frac=e.worked / blk)
        elif mode == "WAIT":
            v.update(clock="Ready", sub=f"block {current} starts on a work window", frac=1.0)
        else:
            v.update(clock=mmss(blk - e.worked), frac=e.worked / blk)
            if e.status == "auto_paused" and e.held_since:
                v.update(clock_color=COL["paused"], paused_icon=True,
                         sub=f"held for {int((now - e.held_since) // 60)} min")
            elif e.block_start is None:
                v["sub"] = f"block {current} starts on a work window"
            else:
                v["sub"] = f"left in block {current}"
        if e.mode == "PAUSED":
            v.update(label="Paused", color=COL["paused"], clock_color=COL["paused"], paused_icon=True,
                     sub="resumes on a work window" if cfg["pause_resume"] == "auto" else "paused by you")
        v["frac"] = max(0.0, min(1.0, v["frac"]))
        return v

    # ----- loop -----
    def loop(self):
        try:
            self.update_hover()
            self.render()
            self.sync_overlay()
        except Exception as ex:
            print("ui error:", ex)
        fast = self.anim and self.e.mode == "LUNCH" and self.e.lunch_nudge
        self.root.after(50 if fast else 200, self.loop)

    def update_hover(self):
        if self.dragging or self.menu_open:
            return
        px, py = self.root.winfo_pointerxy()
        M = self.M * self.S
        x, y = self.root.winfo_rootx() + M, self.root.winfo_rooty() + M
        w, h = self.root.winfo_width() - 2 * M, self.root.winfo_height() - 2 * M
        if x <= px < x + w and y <= py < y + h:
            self.expanded, self.leave_at = True, None
        elif self.expanded:
            self.leave_at = self.leave_at or time.time()
            if time.time() - self.leave_at > 0.6:
                self.expanded, self.hot = False, None

    def render(self):
        self.cv.delete("all")
        self.buttons = []
        e = self.e
        if not self.expanded:
            self.draw_collapsed()
        elif e.mode == "LUNCH" and e.lunch_nudge:
            self.draw_nudge()
        else:
            self.draw_panel()

    def draw_collapsed(self):
        cv, k, S, e = self.cv, self.k, self.S, self.e
        v = self.view()
        M = self.M * S
        pw, ph = 148 * S, 38 * S
        self.place(pw + 2 * M, ph + 2 * M)
        nudging = e.mode == "LUNCH" and e.lunch_nudge
        t = time.time()
        if nudging and self.anim:                                   # soft breathing glow
            p = (1 - math.cos(2 * math.pi * t / 4.2)) / 2
            g = (2 + 5 * p) * S
            k.rrect(cv, M - g, M - g, M + pw + g, M + ph + g, ph / 2 + g,
                    fill=mix(INK, COL["lunch"], 0.2 + 0.4 * p))
        k.rrect(cv, M, M, M + pw, M + ph, ph / 2, fill=INK)
        k.ring(cv, M + 21 * S, M + ph / 2, 8 * S, 2.6 * S, v["frac"], v["color"])
        clock_font = k.num_bold(18) if v["clock"] != "Ready" else k.ui_bold(14)
        cv.create_text(M + 40 * S, M + ph / 2, text=v["clock"], anchor="w", font=clock_font,
                       fill=v["clock_color"])
        if nudging:
            dy = hop_offset(t) * S if self.anim else 0
            cx, cy, r = M + pw - 18 * S, M + ph / 2 + dy, 4.5 * S
            cv.create_oval(cx - r, cy - r, cx + r, cy + r, fill=COL["lunch"], outline="")
        else:
            cv.create_text(M + pw - 14 * S, M + ph / 2, text="TEST" if TEST_MODE else v["count"], anchor="e",
                           font=k.ui_bold(11) if TEST_MODE else k.F(k.num, 14),
                           fill=COL["camera"] if TEST_MODE else MUTED)

    def draw_panel(self):
        cv, k, S, e, cfg = self.cv, self.k, self.S, self.e, self.e.cfg
        v = self.view()
        M, pad, pw = self.M * S, 18 * S, 330 * S
        x0, y0, inner = M, M, 330 * S - 36 * S
        # header: ring + status, big clock, sub line
        top = y0 + pad
        cx, cy = x0 + pad + 26 * S, top + 35 * S
        k.ring(cv, cx, cy, 22 * S, 4 * S, v["frac"], v["color"])
        if v["paused_icon"]:
            for dx in (-6, 2):
                k.rrect(cv, cx + dx * S, cy - 7 * S, cx + (dx + 4) * S, cy + 7 * S, 1.5 * S, fill=SUB)
        else:
            cv.create_text(cx, cy, text=v["ring_text"], font=k.num_bold(15), fill=TEXT)
        tx = x0 + pad + 66 * S
        cv.create_text(tx, top, text=v["label"], anchor="nw", font=k.ui_bold(13), fill=v["color"])
        big = k.F(k.num, 32) if v["clock"] != "Ready" else k.ui_bold(26)
        cv.create_text(tx, top + 17 * S, text=v["clock"], anchor="nw", font=big, fill=v["clock_color"])
        cv.create_text(tx, top + 55 * S, text=k.fit(v["sub"], k.F(k.ui, 12), pw - 66 * S - 2 * pad),
                       anchor="nw", font=k.F(k.ui, 12), fill=MUTED)
        y = top + 84 * S
        d = cv.create_text(x0 + pad, y, text=e.detail, anchor="nw", width=inner,
                           font=k.F(k.ui, 12.5), fill=SUB)
        y = cv.bbox(d)[3] + 14 * S
        # today
        cv.create_line(x0 + pad, y, x0 + pw - pad, y, fill=LINE)
        y += 14 * S
        goal = max(1, cfg["daily_goal"])
        gap = 6 * S
        seg = min(22 * S, (inner - gap * (goal - 1)) / goal)
        for i in range(goal):
            if i < e.done:
                c = COL["focus"]
            elif i == e.done and e.mode in ("WORK", "PAUSED") and e.worked > 0:
                c = mix(TRACK, COL["focus"], 0.3)
            else:
                c = TRACK
            sx = x0 + pad + i * (seg + gap)
            k.rrect(cv, sx, y, sx + seg, y + 8 * S, 4 * S, fill=c)
        y += 20 * S
        sx = x0 + pad
        for n, word in ((e.done, "done"), (e.partial, "partial"), (max(0, goal - e.done), "breaks left")):
            f_n, f_w = k.ui_bold(12), k.F(k.ui, 12)
            cv.create_text(sx, y, text=str(n), anchor="nw", font=f_n, fill=TEXT)
            sx += f_n.measure(str(n)) + 4 * S
            cv.create_text(sx, y, text=word, anchor="nw", font=f_w, fill=MUTED)
            sx += f_w.measure(word) + 18 * S
        y += 30 * S
        # buttons
        paused = e.mode == "PAUSED"
        specs = [("Resume" if paused else "Pause", "toggle_pause", e.mode != "LUNCH", "primary" if paused else "normal", 1.0),
                 ("Skip break", "skip_break", e.mode in ("BREAK", "WAIT"), "normal", 1.3),
                 ("Reset", "reset", e.worked > 0 and e.mode in ("WORK", "PAUSED"), "normal", 1.0),
                 ("End lunch" if e.mode == "LUNCH" else "Lunch", "lunch", True,
                  "accent" if e.mode == "LUNCH" else "normal", 1.0)]
        bh, icon_w = 34 * S, 34 * S
        unit = (inner - icon_w - gap * len(specs)) / sum(s[4] for s in specs)
        bx = x0 + pad
        for label, action, enabled, kind, wgt in specs:
            k.button(cv, self.buttons, bx, y, unit * wgt, bh, label, action, enabled, kind, self.hot)
            bx += unit * wgt + gap
        k.button(cv, self.buttons, bx, y, icon_w, bh, "more", "menu", True, "icon", self.hot)
        y += bh + pad
        bg = k.rrect(cv, x0, y0, x0 + pw, y, 16 * S, fill=INK)
        cv.tag_lower(bg)
        self.place(pw + 2 * M, y + M)

    def draw_nudge(self):
        cv, k, S, e = self.cv, self.k, self.S, self.e
        M, pad, pw = self.M * S, 18 * S, 300 * S
        x0, y0, inner = M, M, pw - 36 * S
        y = y0 + pad
        dy = hop_offset(time.time()) * 0.6 * S if self.anim else 0
        r = 5 * S
        cv.create_oval(x0 + pad, y + 5 * S - r + dy, x0 + pad + 2 * r, y + 5 * S + r + dy,
                       fill=COL["lunch"], outline="")
        cv.create_text(x0 + pad + 2 * r + 12 * S, y + 5 * S, text="Back at your desk?", anchor="w",
                       font=k.ui_bold(15), fill=TEXT)
        y += 26 * S
        src = (e.fg[2][:-4] if e.fg and e.fg[2].lower().endswith(".exe") else (e.fg[2] if e.fg else "")) or "a work window"
        msg = f"You've been on {src} for a minute. Lunch has run {int((time.time() - e.lunch_at) // 60)} min."
        d = cv.create_text(x0 + pad, y, text=msg, anchor="nw", width=inner, font=k.F(k.ui, 13), fill=SUB)
        y = cv.bbox(d)[3] + 14 * S
        bw = (inner - 8 * S) / 2
        k.button(cv, self.buttons, x0 + pad, y, bw, 36 * S, "End lunch", "lunch", True, "accent", self.hot,
                 font=k.ui_bold(13))
        k.button(cv, self.buttons, x0 + pad + bw + 8 * S, y, bw, 36 * S, "Not yet", "lunch_snooze", True,
                 "normal", self.hot, font=k.F(k.ui, 13))
        y += 36 * S + 12 * S
        cv.create_text(x0 + pad, y, text="Not yet asks again in 10 min.", anchor="nw",
                       font=k.F(k.ui, 11.5), fill=MUTED)
        y += 16 * S + pad
        bg = k.rrect(cv, x0, y0, x0 + pw, y, 16 * S, fill=INK)
        cv.tag_lower(bg)
        self.place(pw + 2 * M, y + M)

    # ----- mouse -----
    def on_press(self, ev):
        self.press = (ev.x_root, ev.y_root, self.right, self.top)
        self.dragging = False

    def on_drag(self, ev):
        if not self.press:
            return
        x0, y0, r0, t0 = self.press
        if abs(ev.x_root - x0) + abs(ev.y_root - y0) > 4 * self.S:
            self.dragging = True
        if self.dragging:
            self.right, self.top = r0 + ev.x_root - x0, t0 + ev.y_root - y0
            self.geom = ""
            self.render()

    def on_release(self, ev):
        if self.dragging:
            self.dragging = False
            try:
                POS_PATH.write_text(json.dumps([int(self.right), int(self.top)]))
            except Exception:
                pass
        else:
            b = self.k.hit(self.buttons, ev.x, ev.y)
            if b and b["enabled"]:
                if b["action"] == "menu":
                    self.show_menu(ev.x_root, ev.y_root)
                else:
                    self.e.send(b["action"])
        self.press = None

    def show_menu(self, x, y):
        m, e = self.menu, self.e
        m.delete(0, "end")
        m.add_command(label="Settings...", command=self.open_settings)
        fg = e.fg
        if fg:
            title = fg[3] or fg[2] or "window"
            short = title if len(title) <= 40 else title[:39] + "..."
            verb = "Untag" if fg[0] in e.tags else "Tag as work"
            m.add_command(label=f"{verb}: {short}", command=lambda: e.send("tag_toggle", fg[0], title))
        m.add_separator()
        m.add_command(label="Open heatmap", command=lambda: threading.Thread(target=report, daemon=True).start())
        m.add_command(label="Open settings file", command=lambda: os.startfile(CONFIG_PATH))
        m.add_command(label="Reload settings", command=lambda: e.send("reload"))
        if TEST_MODE:
            tm = self.tk.Menu(m, tearoff=0)
            tm.add_command(label="Finish block now", command=lambda: e.send("test_finish_block"))
            tm.add_command(label="End break now", command=lambda: e.send("test_end_break"))
            tm.add_command(label="Trigger lunch nudge (while on lunch)", command=lambda: e.send("test_lunch_nudge"))
            tm.add_command(label="Camera check now (stay idle)", command=lambda: e.send("test_camera"))
            tm.add_command(label="Clear test data and quit", command=self.clear_test_data)
            m.add_cascade(label="Test", menu=tm)
        m.add_separator()
        m.add_command(label="Quit", command=self.root.destroy)
        self.menu_open = True
        try:
            m.tk_popup(int(x), int(y))
        finally:
            m.grab_release()
            self.menu_open = False

    def clear_test_data(self):
        import shutil
        self.root.destroy()
        if TEST_MODE:
            shutil.rmtree(DATA_DIR, ignore_errors=True)

    def open_settings(self):
        if self.settings and self.settings.alive:
            self.settings.top.lift()
            self.settings.top.focus_force()
        else:
            self.settings = Settings(self)

    # ----- full-screen break overlay -----
    def sync_overlay(self):
        e, tk = self.e, self.tk
        want = e.mode == "BREAK" and e.overlay
        if want and self.ov is None:
            ov = self.ov = tk.Toplevel(self.root)
            ov.overrideredirect(True)
            ov.attributes("-topmost", True)
            try:
                ov.attributes("-alpha", 0.95)
            except tk.TclError:
                pass
            ov.geometry(f"{self.root.winfo_screenwidth()}x{self.root.winfo_screenheight()}+0+0")
            self.ov_cv = tk.Canvas(ov, bg=INK, highlightthickness=0, bd=0)
            self.ov_cv.pack(fill="both", expand=True)
            self.ov_cv.bind("<ButtonRelease-1>", self.on_overlay_click)
            self.ov_cv.bind("<Motion>", lambda ev: setattr(self, "ov_hot", self.k.hit(self.ov_buttons, ev.x, ev.y)))
            ov.after(200, lambda: pin_everywhere(ov))
            self.root.lift()
        elif not want and self.ov is not None:
            self.ov.destroy()
            self.ov = None
        if self.ov is not None:
            self.draw_overlay()

    def draw_overlay(self):
        cv, k, S, e = self.ov_cv, self.k, self.S, self.e
        W, H = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        cx, cy = W / 2, H / 2
        cv.delete("all")
        self.ov_buttons = []
        brk = e.cfg["break_minutes"] * 60
        left = e.break_end - time.time()
        k.ring(cv, cx, cy - 30 * S, 150 * S, 6 * S, max(0.0, min(1.0, left / brk)), COL["break"])
        cv.create_text(cx, cy - 92 * S, text="Break", font=k.ui_bold(22), fill=COL["break"])
        cv.create_text(cx, cy - 30 * S, text=mmss(left), font=k.F(k.num_light, 96), fill=TEXT)
        cv.create_text(cx, cy + 36 * S, text=f"Block {e.done} of {e.cfg['daily_goal']} done",
                       font=k.F(k.ui, 15), fill=MUTED)
        cv.create_text(cx, cy + 160 * S, text="Stand up, look away from the screen, stretch.",
                       font=k.F(k.ui, 17), fill=SUB)
        f = k.F(k.ui, 15)
        bw, bh, g = 150 * S, 44 * S, 12 * S
        x = cx - bw - g / 2
        for label, action in (("Skip break", "skip_break"), ("Start lunch", "lunch")):
            k.button(cv, self.ov_buttons, x, cy + 200 * S, bw, bh, label, action, True, "normal",
                     self.ov_hot, font=f, radius=11)
            x += bw + g

    def on_overlay_click(self, ev):
        b = self.k.hit(self.ov_buttons, ev.x, ev.y)
        if b:
            self.e.send(b["action"])


# ---------------- settings window ----------------
class Settings:
    W, H, NAV = 1000, 700, 210
    PAGES = (("sources", "Work sources"), ("blocks", "Blocks and breaks"), ("camera", "Camera check"),
             ("lunch", "Lunch and pause"), ("heatmap", "Heatmap"))

    def __init__(self, pill: Pill):
        tk = pill.tk
        self.p, self.e, self.k, self.S = pill, pill.e, pill.k, pill.S
        S = self.S
        self.top = top = tk.Toplevel(pill.root)
        top.title("Focus Blocks settings")
        top.geometry(f"{int(self.W * S)}x{int(self.H * S)}")
        top.resizable(False, False)
        top.configure(bg=W_BG)
        top.protocol("WM_DELETE_WINDOW", self.close)
        self.cv = tk.Canvas(top, bg=W_BG, highlightthickness=0, bd=0)
        self.cv.pack(fill="both", expand=True)
        self.alive, self.page, self.tab = True, "sources", "desktops"
        self.buttons, self.hot, self.scroll, self.content_h = [], None, 0.0, 0.0
        cfg = self.e.cfg
        self.sel_desks = {d.lower() for d in cfg["work_desktops"]}
        self.sel_apps = {a.lower() for a in cfg["work_apps"]}
        cw = (self.W - self.NAV - 64) * S
        self.card_w = (cw - 2 * 18 * S) / 3
        self.thumb = (int(self.card_w - 20 * S), int((self.card_w - 20 * S) * 10 / 16))
        self.load()
        self.cv.bind("<ButtonRelease-1>", self.on_click)
        self.cv.bind("<Motion>", self.on_motion)
        self.cv.bind("<MouseWheel>", self.on_wheel)
        self.render()

    def load(self):
        self.desktops = list_desktops()
        have = {d["name"].lower() for d in self.desktops}
        for n in self.e.cfg["work_desktops"]:
            if n.lower() not in have:
                self.desktops.append(dict(name=n, number=None, apps=[], current=False, missing=True))
        running = running_apps()
        self.apps = [dict(exe=x, title=t, running=True) for x, t in sorted(running.items(), key=lambda i: i[0].lower())]
        have = {a["exe"].lower() for a in self.apps}
        self.apps += [dict(exe=a, title="", running=False) for a in self.e.cfg["work_apps"] if a.lower() not in have]
        self.images = {}
        try:
            from PIL import Image, ImageOps, ImageTk
            for d in self.desktops:
                p = snap_path(d["name"])
                if p.exists():
                    img = ImageOps.fit(Image.open(p), self.thumb)
                    self.images[d["name"]] = ImageTk.PhotoImage(img, master=self.top)
                    d["snap"] = dt.datetime.fromtimestamp(p.stat().st_mtime)
        except Exception as ex:
            print("previews unavailable:", ex)

    def close(self):
        self.alive = False
        self.top.destroy()

    def save(self):
        cfg = load_config()
        cfg["work_desktops"] = [d["name"] for d in self.desktops if d["name"].lower() in self.sel_desks]
        cfg["work_apps"] = [a["exe"] for a in self.apps if a["exe"].lower() in self.sel_apps]
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        self.e.send("reload")
        self.close()

    # ----- events -----
    def visible(self, b, x, y):
        """Content buttons scroll under the header/footer; only the visible part is clickable."""
        in_content = x > self.NAV * self.S and 150 * self.S <= y <= (self.H - 68) * self.S
        return b.get("content", False) == in_content

    def on_motion(self, ev):
        b = self.k.hit([b for b in self.buttons if self.visible(b, ev.x, ev.y)], ev.x, ev.y)
        if (b and b["id"]) != (self.hot and self.hot["id"]):
            self.hot = b
            self.render()

    def on_wheel(self, ev):
        view = (self.H - 68 - 150) * self.S
        self.scroll = max(0.0, min(self.scroll - ev.delta / 120 * 50 * self.S, max(0.0, self.content_h - view)))
        self.render()

    def on_click(self, ev):
        b = self.k.hit([b for b in self.buttons if self.visible(b, ev.x, ev.y)], ev.x, ev.y)
        if not b or not b["enabled"]:
            return
        a = b["action"]
        if a == "page":
            if b["page"] == "heatmap":
                threading.Thread(target=report, daemon=True).start()
            else:
                self.page, self.scroll = b["page"], 0.0
        elif a == "tab":
            self.tab, self.scroll = b["tab"], 0.0
        elif a == "desk":
            self.sel_desks ^= {b["key"]}
        elif a == "app":
            self.sel_apps ^= {b["key"]}
        elif a == "untag":
            self.e.send("tag_toggle", b["key"], self.e.tags.get(b["key"], ""))
            self.top.after(300, self.render)
        elif a == "open_file":
            os.startfile(CONFIG_PATH)
        elif a == "cancel":
            self.close()
            return
        elif a == "save":
            self.save()
            return
        self.render()

    # ----- drawing -----
    def checkbox(self, cv, x, y, on):
        S, k = self.S, self.k
        if on:
            k.rrect(cv, x, y, x + 22 * S, y + 22 * S, 6 * S, fill=W_GREEN)
            cv.create_line(x + 6 * S, y + 11.5 * S, x + 9.5 * S, y + 15 * S, x + 16.5 * S, y + 7.5 * S,
                           fill="#ffffff", width=2.6 * S, capstyle="round", joinstyle="round")
        else:
            k.rrect(cv, x, y, x + 22 * S, y + 22 * S, 6 * S, fill="#ffffff", outline=W_CHECK_OFF, width=1.5 * S)

    def render(self):
        if not self.alive:
            return
        cv, k, S = self.cv, self.k, self.S
        cv.delete("all")
        self.buttons = []
        W, H, NAV = self.W * S, self.H * S, self.NAV * S
        x0, cw = NAV + 32 * S, W - NAV - 64 * S
        head_h, foot_y = 150 * S, H - 68 * S
        start = head_h + 22 * S
        y = start - self.scroll
        if self.page == "sources":
            y = {"desktops": self.draw_desktops, "apps": self.draw_apps, "windows": self.draw_windows}[self.tab](x0, y, cw)
        self.content_h = y + self.scroll - start + 22 * S

        # header (covers scrolled content)
        cv.create_rectangle(NAV, 0, W, head_h, fill=W_BG, outline="")
        if self.page == "sources":
            cv.create_text(x0, 30 * S, text="What counts as work", anchor="nw", font=k.ui_bold(22), fill=W_INK)
            cv.create_text(x0, 64 * S, text="Pick any mix. Time counts while one of these is in front of you.",
                           anchor="nw", font=k.F(k.ui, 13.5), fill=W_SUB)
            counts = {"desktops": len(self.sel_desks & {d["name"].lower() for d in self.desktops}),
                      "apps": len(self.sel_apps & {a["exe"].lower() for a in self.apps}),
                      "windows": len(self.e.tags)}
            tabs = (("desktops", "Desktops"), ("apps", "Apps"), ("windows", "Windows"))
            f_on, f_off, f_n = k.ui_bold(13), k.F(k.ui, 13), k.F(k.num, 13)
            widths = [f_on.measure(lbl) + f_n.measure(str(counts[t])) + 34 * S for t, lbl in tabs]
            ty = 100 * S
            k.rrect(cv, x0, ty, x0 + sum(widths) + 8 * S + 4 * S * (len(tabs) - 1), ty + 40 * S, 10 * S, fill="#eceef1")
            tx = x0 + 4 * S
            for (t, lbl), w in zip(tabs, widths):
                on = self.tab == t
                if on:
                    k.rrect(cv, tx, ty + 4 * S, tx + w, ty + 36 * S, 7 * S, fill="#ffffff", outline="#e3e6ea")
                f = f_on if on else f_off
                cv.create_text(tx + 14 * S, ty + 20 * S, text=lbl, anchor="w", font=f, fill=W_INK if on else "#3b434d")
                cv.create_text(tx + 14 * S + f.measure(lbl) + 6 * S, ty + 20 * S, text=str(counts[t]), anchor="w",
                               font=f_n, fill="#5d6670")
                self.buttons.append(dict(x1=tx, y1=ty + 4 * S, x2=tx + w, y2=ty + 36 * S, action="tab", tab=t,
                                         enabled=True, id=("tab", t)))
                tx += w + 4 * S
        else:
            title = dict(self.PAGES)[self.page]
            cv.create_text(x0, 30 * S, text=title, anchor="nw", font=k.ui_bold(22), fill=W_INK)
            cfg = self.e.cfg
            lines = {"blocks": [f"Block length: {cfg['block_minutes']} min", f"Break length: {cfg['break_minutes']} min",
                                f"Daily goal: {cfg['daily_goal']} blocks", f"Break style: {cfg['break_mode']}"],
                     "camera": [f"Camera check after {cfg['idle_seconds']} s without input",
                                f"Camera fallback: {'on' if cfg['camera_fallback'] else 'off'}",
                                f"Meetings count as work: {'yes' if cfg['count_meetings'] else 'no'}"],
                     "lunch": [f"Pause resumes: {cfg['pause_resume']}",
                               f"Unfinished block resets after {cfg['abandon_minutes']} min away"]}.get(self.page, [])
            yy = 74 * S
            for ln in lines:
                cv.create_text(x0, yy, text=ln, anchor="nw", font=k.F(k.ui, 13.5), fill=W_INK)
                yy += 26 * S
            cv.create_text(x0, yy + 14 * S, text="These live in the settings file for now; this page is next.",
                           anchor="nw", font=k.F(k.ui, 13), fill=W_SUB)
            fb = k.F(k.ui, 13)
            k.button(cv, self.buttons, x0, yy + 46 * S, fb.measure("Open settings file") + 36 * S, 36 * S,
                     "Open settings file", "open_file", True, "outline", self.hot, font=fb)

        # footer
        cv.create_rectangle(NAV, foot_y, W, H, fill=W_BG, outline="")
        cv.create_line(NAV, foot_y, W, foot_y, fill=W_LINE)
        nd = len(self.sel_desks & {d["name"].lower() for d in self.desktops})
        na = len(self.sel_apps & {a["exe"].lower() for a in self.apps})
        nt = len(self.e.tags)

        def pl(n, w):
            return f"{n} {w}{'' if n == 1 else 's'}"

        summary = ("Counting any window (nothing picked)" if nd + na + nt == 0 else
                   f"Counting {pl(nd, 'desktop')}, {pl(na, 'app')} and {pl(nt, 'tagged window')}")
        cv.create_text(x0, foot_y + 34 * S, text=summary, anchor="w", font=k.F(k.ui, 13), fill="#3b434d")
        fb, fbb = k.F(k.ui, 13), k.ui_bold(13)
        sw, cw_ = fbb.measure("Save") + 40 * S, fb.measure("Cancel") + 36 * S
        k.button(cv, self.buttons, W - 32 * S - sw, foot_y + 16 * S, sw, 36 * S, "Save", "save", True, "dark",
                 self.hot, font=fbb)
        k.button(cv, self.buttons, W - 32 * S - sw - 10 * S - cw_, foot_y + 16 * S, cw_, 36 * S, "Cancel", "cancel",
                 True, "outline", self.hot, font=fb)

        # nav
        cv.create_rectangle(0, 0, NAV, H, fill=W_NAV, outline="")
        cv.create_line(NAV, 0, NAV, H, fill=W_LINE)
        rcx, rcy = 22 * S + 10 * S, 34 * S
        cv.create_oval(rcx - 8 * S, rcy - 8 * S, rcx + 8 * S, rcy + 8 * S, outline="#d5d9de", width=2.6 * S)
        cv.create_arc(rcx - 8 * S, rcy - 8 * S, rcx + 8 * S, rcy + 8 * S, start=90, extent=-216, style="arc",
                      outline=W_GREEN, width=2.6 * S)
        cv.create_text(rcx + 18 * S, rcy, text="Focus Blocks", anchor="w", font=k.ui_bold(14), fill=W_INK)
        ny = 70 * S
        for key, label in self.PAGES:
            on = self.page == key
            hot = self.hot and self.hot["id"] == ("page", key)
            if on or hot:
                k.rrect(cv, 12 * S, ny, NAV - 12 * S, ny + 36 * S, 8 * S, fill="#e2e5e9" if on else "#e8eaed")
            cv.create_text(24 * S, ny + 18 * S, text=label, anchor="w",
                           font=k.ui_bold(13.5) if on else k.F(k.ui, 13.5), fill=W_INK if on else "#3b434d")
            self.buttons.append(dict(x1=12 * S, y1=ny, x2=NAV - 12 * S, y2=ny + 36 * S, action="page", page=key,
                                     enabled=True, id=("page", key)))
            ny += 38 * S

    def draw_desktops(self, x0, y, cw):
        cv, k, S = self.cv, self.k, self.S
        if not self.desktops:
            cv.create_text(x0, y, text="Couldn't read your virtual desktops. Is pyvda installed?", anchor="nw",
                           font=k.F(k.ui, 13.5), fill=W_SUB)
            return y + 30 * S
        tw, th = self.thumb
        card_w, card_h, gap = self.card_w, th + 92 * S, 18 * S
        f_name, f_sub, f_small = k.ui_bold(14), k.F(k.ui, 12), k.F(k.ui, 11.5)
        today = dt.date.today()
        for i, d in enumerate(self.desktops):
            col, row = i % 3, i // 3
            cx, cy = x0 + col * (card_w + gap), y + row * (card_h + gap)
            key = d["name"].lower()
            on = key in self.sel_desks
            hot = self.hot and self.hot["id"] == ("desk", key)
            k.rrect(cv, cx, cy, cx + card_w, cy + card_h, 12 * S, fill="#ffffff",
                    outline=W_GREEN if on else ("#c9ced4" if hot else W_LINE), width=2 * S)
            ix, iy = cx + 10 * S, cy + 10 * S
            if d["name"] in self.images:
                cv.create_image(ix, iy, image=self.images[d["name"]], anchor="nw")
            else:
                k.rrect(cv, ix, iy, ix + tw, iy + th, 8 * S, fill="#2c3540")
                cv.create_text(ix + tw / 2, iy + th / 2, text="Visit this desktop once\nto see a preview",
                               justify="center", font=f_sub, fill="#c4cad1")
            ty = iy + th + 12 * S
            cv.create_text(cx + 12 * S, ty, text=k.fit(d["name"], f_name, card_w - 60 * S), anchor="nw",
                           font=f_name, fill=W_INK)
            apps = ", ".join(a[:-4] if a.lower().endswith(".exe") else a for a in d["apps"][:4]) or "No windows"
            cv.create_text(cx + 12 * S, ty + 22 * S, text=k.fit(apps, f_sub, card_w - 24 * S), anchor="nw",
                           font=f_sub, fill="#5d6670")
            if d.get("missing"):
                seen = "Not found. Renamed or removed?"
            elif d["current"]:
                seen = "You are here"
            elif d.get("snap"):
                sd = d["snap"]
                seen = (f"Snapshot {sd:%H:%M}" if sd.date() == today else
                        "Snapshot yesterday" if sd.date() == today - dt.timedelta(days=1) else f"Snapshot {sd:%b %d}")
            else:
                seen = "No snapshot yet"
            cv.create_text(cx + 12 * S, ty + 42 * S, text=seen, anchor="nw", font=f_small, fill=W_FAINT)
            self.checkbox(cv, cx + card_w - 34 * S, ty, on)
            self.buttons.append(dict(x1=cx, y1=cy, x2=cx + card_w, y2=cy + card_h, action="desk", key=key,
                                     enabled=True, content=True, id=("desk", key)))
        rows = (len(self.desktops) + 2) // 3
        y += rows * (card_h + gap)
        cv.create_text(x0, y, anchor="nw", width=cw, font=k.F(k.ui, 12.5), fill="#5d6670",
                       text="Previews are snapshots from the last time you used each desktop, saved only on this PC. "
                            "Rename desktops in Task View (Win + Tab).")
        return y + 40 * S

    def draw_apps(self, x0, y, cw):
        cv, k, S = self.cv, self.k, self.S
        cv.create_text(x0, y, text="Apps with windows open now. Pick one and every window of it counts.",
                       anchor="nw", font=k.F(k.ui, 13), fill=W_SUB)
        y += 30 * S
        top = y
        f_name, f_sub = k.ui_bold(13.5), k.F(k.ui, 12)
        rh = 56 * S
        for a in self.apps:
            key = a["exe"].lower()
            on = key in self.sel_apps
            hot = self.hot and self.hot["id"] == ("app", key)
            cv.create_rectangle(x0 + 1, y, x0 + cw - 1, y + rh, fill=W_SEL_ROW if on else ("#f7f8f9" if hot else "#ffffff"),
                                outline="")
            cv.create_line(x0, y + rh, x0 + cw, y + rh, fill="#eceef1")
            name = a["exe"][:-4] if key.endswith(".exe") else a["exe"]
            color = BADGES[sum(map(ord, key)) % len(BADGES)]
            k.rrect(cv, x0 + 16 * S, y + 13 * S, x0 + 46 * S, y + 43 * S, 8 * S, fill=color)
            cv.create_text(x0 + 31 * S, y + 28 * S, text=name[:1].upper(), font=k.ui_bold(13), fill="#ffffff")
            cv.create_text(x0 + 60 * S, y + 10 * S, text=name, anchor="nw", font=f_name, fill=W_INK)
            sub = f"{a['exe']}   {a['title']}" if a["running"] else f"{a['exe']}   not running"
            cv.create_text(x0 + 60 * S, y + 30 * S, text=k.fit(sub, f_sub, cw - 120 * S), anchor="nw",
                           font=f_sub, fill="#5d6670")
            self.checkbox(cv, x0 + cw - 38 * S, y + 17 * S, on)
            self.buttons.append(dict(x1=x0, y1=y, x2=x0 + cw, y2=y + rh, action="app", key=key, enabled=True,
                                     content=True, id=("app", key)))
            y += rh
        k.rrect(cv, x0, top, x0 + cw, y, 10 * S, fill="", outline=W_LINE)
        return y + 20 * S

    def draw_windows(self, x0, y, cw):
        cv, k, S = self.cv, self.k, self.S
        hotkey = self.e.cfg["tag_hotkey"].replace("+", " + ").title()
        cv.create_text(x0, y, anchor="nw", width=cw, font=k.F(k.ui, 13), fill=W_SUB,
                       text=f"Tagged windows count with every tab inside them. Press {hotkey} on any window to tag or untag it.")
        y += 40 * S
        if not self.e.tags:
            cv.create_text(x0, y, text="No tagged windows yet.", anchor="nw", font=k.F(k.ui, 13.5), fill=W_INK)
            return y + 30 * S
        f_name, f_sub, fb = k.ui_bold(13.5), k.F(k.ui, 12), k.F(k.ui, 12.5)
        for hwnd, title in list(self.e.tags.items()):
            k.rrect(cv, x0, y, x0 + cw, y + 60 * S, 10 * S, fill="#ffffff", outline=W_LINE)
            cv.create_text(x0 + 16 * S, y + 12 * S, text=k.fit(title, f_name, cw - 140 * S), anchor="nw",
                           font=f_name, fill=W_INK)
            cv.create_text(x0 + 16 * S, y + 33 * S, text="Clears when the window closes.", anchor="nw",
                           font=f_sub, fill="#5d6670")
            bw = fb.measure("Untag") + 28 * S
            k.button(cv, self.buttons, x0 + cw - 16 * S - bw, y + 14 * S, bw, 32 * S, "Untag", "untag", True,
                     "outline", self.hot, font=fb, radius=8, key=hwnd, content=True)
            y += 70 * S
        return y + 10 * S


# ---------------- heatmap report ----------------
def report() -> None:
    cfg = load_config()
    DAILY_GOAL, WORK_MIN = cfg["daily_goal"], cfg["block_minutes"]
    con = open_db()
    rows = con.execute("SELECT day, SUM(completed), SUM(minutes) FROM blocks GROUP BY day").fetchall()
    data = {d: (int(c or 0), float(m or 0)) for d, c, m in rows}
    today = dt.date.today()
    start = today - dt.timedelta(days=364)
    start -= dt.timedelta(days=(start.weekday() + 1) % 7)   # align to Sunday

    def level(c):
        if c == 0:
            return 0
        if c >= DAILY_GOAL:
            return 4
        return 1 + min(2, (c * 3) // DAILY_GOAL)

    cells, months, d, col = [], [], start, 0
    last_month = None
    while d <= today:
        if d.weekday() == 6:  # Sunday starts a new column
            if d.month != last_month and d.day <= 7:
                months.append(f'<span style="grid-column:{col + 1}">{d:%b}</span>')
            last_month = d.month
            col += 1
        c, m = data.get(d.isoformat(), (0, 0))
        tip = f"{d:%a %b %d}: {c} block{'s' if c != 1 else ''}, {m:.0f} min focused"
        cells.append(f'<div class="c l{level(c)}" style="grid-column:{col};grid-row:{(d.weekday() + 1) % 7 + 1}" title="{tip}"></div>')
        d += dt.timedelta(days=1)

    # streaks (days that met the goal)
    streak = 0
    d = today if data.get(today.isoformat(), (0,))[0] >= DAILY_GOAL else today - dt.timedelta(days=1)
    while data.get(d.isoformat(), (0,))[0] >= DAILY_GOAL:
        streak += 1
        d -= dt.timedelta(days=1)
    best = run_len = 0
    d = start
    while d <= today:
        run_len = run_len + 1 if data.get(d.isoformat(), (0,))[0] >= DAILY_GOAL else 0
        best = max(best, run_len)
        d += dt.timedelta(days=1)
    total = sum(c for c, _ in data.values())
    t = data.get(today.isoformat(), (0, 0))[0]

    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Focus blocks</title>
<style>
:root {{ --bg:#fbfaf9; --ink:#1d2229; --muted:#6b7480; --l0:#ebe8e5; --l1:#f6c7bd; --l2:#ec8f7c; --l3:#d8573f; --l4:#a8301c; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#16191d; --ink:#e9ecef; --muted:#8c96a1; --l0:#262b31; --l1:#5a2a22; --l2:#8a3a2b; --l3:#c4523b; --l4:#f07a5f; }} }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:16px/1.5 "Segoe UI Variable","Segoe UI",system-ui,sans-serif; }}
main {{ max-width:1000px; margin:48px auto; padding:0 24px; }}
h1 {{ font-size:28px; font-weight:600; margin:0 0 4px; }}
p.sub {{ color:var(--muted); margin:0 0 32px; }}
.wrap {{ overflow-x:auto; padding-bottom:8px; }}
.months, .grid {{ display:grid; grid-auto-flow:column; grid-auto-columns:14px; gap:3px; }}
.months {{ font-size:12px; color:var(--muted); height:18px; }}
.months span {{ white-space:nowrap; }}
.grid {{ grid-template-rows:repeat(7,14px); }}
.c {{ border-radius:3px; }}
.l0 {{ background:var(--l0); }} .l1 {{ background:var(--l1); }} .l2 {{ background:var(--l2); }}
.l3 {{ background:var(--l3); }} .l4 {{ background:var(--l4); }}
.stats {{ display:flex; flex-wrap:wrap; gap:40px; margin-top:32px; }}
.stats b {{ display:block; font-size:32px; font-weight:600; line-height:1.1; }}
.stats span {{ color:var(--muted); font-size:14px; }}
.legend {{ display:flex; align-items:center; gap:4px; font-size:12px; color:var(--muted); margin-top:12px; }}
.legend .c {{ width:12px; height:12px; }}
</style></head><body><main>
<h1>Focus blocks</h1>
<p class="sub">{WORK_MIN}-minute blocks over the last year. Daily goal: {DAILY_GOAL}.</p>
<div class="wrap"><div class="months">{''.join(months)}</div><div class="grid">{''.join(cells)}</div></div>
<div class="legend">Less <div class="c l0"></div><div class="c l1"></div><div class="c l2"></div><div class="c l3"></div><div class="c l4"></div> Goal met</div>
<div class="stats">
<div><b>{t}/{DAILY_GOAL}</b><span>today</span></div>
<div><b>{streak}</b><span>day streak</span></div>
<div><b>{best}</b><span>best streak</span></div>
<div><b>{total}</b><span>blocks total</span></div>
</div></main></body></html>"""
    out = DATA_DIR / "heatmap.html"
    out.write_text(html, encoding="utf-8")
    print(f"Wrote {out}")
    webbrowser.open(out.as_uri())


def main() -> None:
    args = sys.argv[1:]
    if "--test" in args:
        use_test_data()
        args.remove("--test")
    arg = args[0] if args else ""
    if arg == "report":
        report()
        return
    engine = Engine(load_config())
    threading.Thread(target=engine.run, daemon=True).start()
    if not TEST_MODE:   # leave the hotkey to the real copy if both are running
        threading.Thread(target=hotkey_loop, args=(engine,), daemon=True).start()
    else:
        notify("Focus Blocks test mode", "1-min blocks, 30-s breaks, separate data. Right-click > Test.")
    if arg == "--nogui":
        while True:
            time.sleep(3600)
    Pill(engine).root.mainloop()


if __name__ == "__main__":
    main()