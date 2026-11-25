#!/usr/bin/env python3
"""
OLED Control Center - GUI zur Ansteuerung eines SSD1306 0.96" OLED (128x64, I2C)
am Raspberry Pi 5.

Benötigt auf dem Pi:
    sudo apt install -y python3-tk python3-pil python3-pil.imagetk i2c-tools
    source ~/oled-env/bin/activate      # die venv von vorhin
    pip install luma.oled psutil

Start:
    python3 oled_gui.py
"""

import importlib.util
import math
import os
import random
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps, ImageTk

try:
    import numpy as np
except ImportError:  # nur für schöneres Dithering, nicht zwingend
    np = None

WIDTH = 128
HEIGHT = 64
SCALE = 6  # Zoom-Faktor der virtuellen Anzeige im Fenster
APP_DIR = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------------------
# Hardware-Anbindung (luma.oled). Falls nicht vorhanden/kein Display
# angeschlossen, läuft die App trotzdem rein virtuell weiter.
# ---------------------------------------------------------------------------
class OledDevice:
    def __init__(self, port=1, address=0x3C, width=WIDTH, height=HEIGHT):
        self.width = width
        self.height = height
        self.device = None
        self.connected = False
        self.last_error = ""
        self._pending = None
        self._evt = threading.Event()
        self._thread = None
        self.connect(port, address)

    def push_async(self, image):
        """Schickt das neueste Bild im Hintergrund ans Display, damit die GUI
        (z.B. bei Tetris) nicht auf den langsamen I2C-Bus warten muss."""
        if not self.connected:
            return
        self._pending = image.copy()
        self._evt.set()
        if self._thread is None:
            self._thread = threading.Thread(target=self._worker, daemon=True)
            self._thread.start()

    def _worker(self):
        while True:
            self._evt.wait()
            self._evt.clear()
            img = self._pending
            if img is not None:
                self.push(img)

    def connect(self, port, address):
        try:
            from luma.core.interface.serial import i2c
            from luma.oled.device import ssd1306
            serial = i2c(port=port, address=address)
            self.device = ssd1306(serial, width=self.width, height=self.height)
            self.connected = True
            self.last_error = ""
        except Exception as e:
            self.device = None
            self.connected = False
            self.last_error = str(e)

    def push(self, image):
        if not self.connected or self.device is None:
            return
        try:
            self.device.display(image.convert("1"))
        except Exception as e:
            self.connected = False
            self.last_error = str(e)


# ---------------------------------------------------------------------------
# Systeminfos (CPU-Temperatur, Auslastung, RAM)
# ---------------------------------------------------------------------------
def get_cpu_temp():
    try:
        out = os.popen("vcgencmd measure_temp").read()
        return float(out.split("=")[1].split("'")[0])
    except Exception:
        try:
            with open("/sys/class/thermal/thermal_zone0/temp") as f:
                return int(f.read().strip()) / 1000.0
        except Exception:
            return None


def get_cpu_load():
    try:
        return os.getloadavg()[0]
    except Exception:
        return None


def get_mem_percent():
    try:
        import psutil
        return psutil.virtual_memory().percent
    except Exception:
        return None


def get_cpu_percent():
    try:
        import psutil
        return psutil.cpu_percent(interval=None)
    except Exception:
        return None


def get_mem_info():
    """Gibt (genutzt_GB, gesamt_GB, prozent) zurück."""
    try:
        import psutil
        m = psutil.virtual_memory()
        return m.used / 1024 ** 3, m.total / 1024 ** 3, m.percent
    except Exception:
        return None


def get_disk_percent():
    try:
        import shutil
        u = shutil.disk_usage("/")
        return u.used / u.total * 100
    except Exception:
        return None


def get_ip():
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "keine IP"


def get_uptime():
    try:
        with open("/proc/uptime") as f:
            secs = int(float(f.read().split()[0]))
        d, r = divmod(secs, 86400)
        h, r = divmod(r, 3600)
        m = r // 60
        return f"{d}d {h}h" if d else f"{h}h {m}m"
    except Exception:
        return "n/a"


# ---------------------------------------------------------------------------
# Hauptanwendung
# ---------------------------------------------------------------------------
TETROMINOS = {
    "I": [[1, 1, 1, 1]],
    "O": [[1, 1], [1, 1]],
    "T": [[0, 1, 0], [1, 1, 1]],
    "S": [[0, 1, 1], [1, 1, 0]],
    "Z": [[1, 1, 0], [0, 1, 1]],
    "J": [[1, 0, 0], [1, 1, 1]],
    "L": [[0, 0, 1], [1, 1, 1]],
}


class TetrisGame:
    """Reine Spiellogik (10x20 Spielfeld), unabhängig von GUI und Display."""

    COLS = 10
    ROWS = 20

    def __init__(self):
        self.reset()

    def reset(self):
        self.board = [[0] * self.COLS for _ in range(self.ROWS)]
        self.score = 0
        self.lines = 0
        self.level = 1
        self.game_over = False
        self.paused = False
        self.bag = []
        self.next_shape = self._from_bag()
        self._spawn()

    def _from_bag(self):
        if not self.bag:
            self.bag = list(TETROMINOS.values())
            random.shuffle(self.bag)
        return [row[:] for row in self.bag.pop()]

    def _spawn(self):
        self.shape = self.next_shape
        self.next_shape = self._from_bag()
        self.x = (self.COLS - len(self.shape[0])) // 2
        self.y = 0
        if self._collides(self.shape, self.x, self.y):
            self.game_over = True

    def _collides(self, shape, x, y):
        for r, row in enumerate(shape):
            for c, v in enumerate(row):
                if not v:
                    continue
                bx, by = x + c, y + r
                if bx < 0 or bx >= self.COLS or by >= self.ROWS:
                    return True
                if by >= 0 and self.board[by][bx]:
                    return True
        return False

    def _active(self):
        return not self.game_over and not self.paused

    def move(self, dx):
        if self._active() and not self._collides(self.shape, self.x + dx, self.y):
            self.x += dx

    def rotate(self):
        if not self._active():
            return
        rot = [list(r) for r in zip(*self.shape[::-1])]
        for kick in (0, -1, 1, -2, 2):  # einfache Wall-Kicks
            if not self._collides(rot, self.x + kick, self.y):
                self.shape = rot
                self.x += kick
                return

    def step(self):
        """Ein Feld nach unten; True wenn bewegt, sonst wird festgesetzt."""
        if not self._active():
            return False
        if not self._collides(self.shape, self.x, self.y + 1):
            self.y += 1
            return True
        self._lock()
        return False

    def soft_drop(self):
        if self.step():
            self.score += 1

    def hard_drop(self):
        if not self._active():
            return
        n = 0
        while not self._collides(self.shape, self.x, self.y + 1):
            self.y += 1
            n += 1
        self.score += 2 * n
        self._lock()

    def _lock(self):
        for r, row in enumerate(self.shape):
            for c, v in enumerate(row):
                if v and 0 <= self.y + r < self.ROWS:
                    self.board[self.y + r][self.x + c] = 1
        full = sum(1 for row in self.board if all(row))
        if full:
            self.board = [row for row in self.board if not all(row)]
            self.board = [[0] * self.COLS for _ in range(full)] + self.board
            self.score += [0, 100, 300, 500, 800][full] * self.level
            self.lines += full
            self.level = self.lines // 10 + 1
        self._spawn()

    def toggle_pause(self):
        if not self.game_over:
            self.paused = not self.paused

    def interval(self):
        return max(80, 500 - (self.level - 1) * 40)


# ---------------------------------------------------------------------------
# Doom
# ---------------------------------------------------------------------------
# Tastatur -> logische Doom-Aktionen
DOOM_KEYS = {
    "Up": "fwd", "Down": "back", "Left": "left", "Right": "right",
    "Control_L": "fire", "Control_R": "fire", "f": "fire", "F": "fire",
    "space": "use", "e": "use", "E": "use",
    "Shift_L": "run", "Shift_R": "run",
    "a": "strafel", "A": "strafel", "d": "strafer", "D": "strafer",
    **{str(i): f"w{i}" for i in range(1, 8)},
}

WAD_NAMES = ["doom.wad", "doom1.wad", "doom2.wad", "freedoom2.wad", "freedoom1.wad"]

_GAMMA_LUT = [int(255 * (i / 255) ** 0.6) for i in range(256)]
_BAYER4 = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]


def find_wad(app_dir):
    """Sucht eine Doom-WAD (egal ob groß/klein geschrieben) in ein paar Ordnern."""
    dirs = [app_dir, os.path.expanduser("~"), "/usr/share/games/doom", "/usr/share/doom"]
    found = {}
    for d in dirs:
        try:
            for name in os.listdir(d):
                found.setdefault((d, name.lower()), os.path.join(d, name))
        except OSError:
            pass
    for wanted in WAD_NAMES:
        for d in dirs:
            path = found.get((d, wanted))
            if path and os.path.isfile(path):
                return path
    return None


def to_1bit(img_l):
    """Graustufenbild (128x64) -> 1-Bit-Bild mit geordnetem Dithering."""
    img_l = ImageOps.autocontrast(img_l, cutoff=1).point(_GAMMA_LUT)
    if np is None:
        return img_l.convert("1")  # Floyd-Steinberg
    a = np.asarray(img_l, dtype=np.uint8)
    h, w = a.shape
    thr = np.tile(np.array(_BAYER4, dtype=np.float32), (h // 4 + 1, w // 4 + 1))[:h, :w]
    thr = (thr + 0.5) * (255 / 16)
    bits = (a > thr).astype(np.uint8) * 255
    return Image.fromarray(bits).convert("1")


def draw_banner(draw, font, title, subtitle):
    draw.rectangle((10, 16, WIDTH - 11, 47), fill=0, outline=255)
    for text, y in ((title, 20), (subtitle, 34)):
        tw = draw.textlength(text, font=font)
        draw.text(((WIDTH - tw) / 2, y), text, font=font, fill=255)


class ViZDoomBackend:
    """Das echte Doom: ViZDoom-Engine, Bild wird auf 128x64 Pixel (1 Bit) verkleinert."""

    BUTTONS = [
        ("fwd", "MOVE_FORWARD"), ("back", "MOVE_BACKWARD"),
        ("left", "TURN_LEFT"), ("right", "TURN_RIGHT"),
        ("strafel", "MOVE_LEFT"), ("strafer", "MOVE_RIGHT"),
        ("fire", "ATTACK"), ("use", "USE"), ("run", "SPEED"),
    ] + [(f"w{i}", f"SELECT_WEAPON{i}") for i in range(1, 8)]

    def __init__(self, font, app_dir):
        import vizdoom as vzd  # ImportError, wenn nicht installiert

        self.font = font
        self.finished = False
        self._last = Image.new("1", (WIDTH, HEIGHT), 0)
        g = vzd.DoomGame()

        self.wad = find_wad(app_dir)
        if self.wad:
            g.set_doom_game_path(self.wad)
            g.set_doom_map("MAP01" if "2" in os.path.basename(self.wad) else "E1M1")

        res = getattr(vzd.ScreenResolution, "RES_320X200", None) or vzd.ScreenResolution.RES_320X240
        g.set_screen_resolution(res)
        g.set_screen_format(vzd.ScreenFormat.GRAY8)
        g.set_window_visible(False)
        g.set_sound_enabled(False)
        g.set_console_enabled(False)
        g.set_render_hud(False)
        g.set_render_crosshair(True)
        g.set_render_weapon(True)
        g.set_mode(vzd.Mode.PLAYER)
        g.set_episode_timeout(0)

        self.names = []
        for logical, bname in self.BUTTONS:
            button = getattr(vzd.Button, bname, None)
            if button is not None:
                g.add_available_button(button)
                self.names.append(logical)
        try:
            g.add_available_game_variable(vzd.GameVariable.HEALTH)
            g.add_available_game_variable(vzd.GameVariable.SELECTED_WEAPON_AMMO)
        except Exception:
            pass

        g.init()
        self.game = g

    def _overlay_end(self):
        img = self._last.copy()
        draw_banner(ImageDraw.Draw(img), self.font, "ENDE", "Leertaste = neu")
        return img

    def step(self, keys):
        g = self.game
        if g.is_episode_finished():
            self.finished = True
            if "use" in keys:
                g.new_episode()
                self.finished = False
            return self._overlay_end()

        g.make_action([1 if n in keys else 0 for n in self.names], 1)
        state = g.get_state()
        if state is None:
            return self._overlay_end()

        buf = np.squeeze(np.asarray(state.screen_buffer))
        img = Image.fromarray(np.ascontiguousarray(buf, dtype=np.uint8))
        w, h = img.size
        crop_h = w // 2  # 2:1 wie das Display
        if crop_h < h:
            top = (h - crop_h) // 2
            img = img.crop((0, top, w, top + crop_h))
        img = img.resize((WIDTH, HEIGHT), Image.BOX)
        out = to_1bit(img)

        vars_ = state.game_variables
        if vars_ is not None and len(vars_) >= 2:
            d = ImageDraw.Draw(out)
            text = f"HP{int(vars_[0])} A{int(vars_[1])}"
            tw = d.textlength(text, font=self.font)
            d.rectangle((0, 0, tw + 2, 9), fill=0)
            d.text((1, -1), text, font=self.font, fill=255)
        self._last = out
        return out

    def close(self):
        try:
            self.game.close()
        except Exception:
            pass


class MiniDoom:
    """Kleiner Doom-Klon (Raycaster) - läuft ohne Zusatzinstallation."""

    FOV = math.radians(66)
    MAP = [
        "################",
        "#..............#",
        "#.####..####...#",
        "#.#..........#.#",
        "#.#..######..#.#",
        "#....#....#....#",
        "#.#..#.##.#..#.#",
        "#.#....##....#.#",
        "#.#..#....#..#.#",
        "#.#..######..#.#",
        "#.#..........#.#",
        "#.####..####...#",
        "#..............#",
        "#.###......###.#",
        "#..............#",
        "################",
    ]

    def __init__(self, font=None):
        self.font = font or ImageFont.load_default()
        self.bg = self._make_background()
        self.sprite, self.mask = self._make_imp()
        self.restart()

    # -- Aufbau ------------------------------------------------------------
    def _make_background(self):
        img = Image.new("1", (WIDTH, HEIGHT), 0)
        d = ImageDraw.Draw(img)
        half = HEIGHT // 2
        for y in range(half + 1, HEIGHT):  # Boden: nach unten dichtere Punkte
            k = max(2, 9 - (y - half) // 4)
            for x in range((y * 3) % k, WIDTH, k):
                d.point((x, y), fill=1)
        return img

    def _make_imp(self):
        sw, sh = 24, 32

        def shapes(d):
            d.ellipse((7, 1, 16, 10), fill=1)
            d.polygon([(7, 4), (5, 0), (9, 2)], fill=1)
            d.polygon([(16, 4), (18, 0), (14, 2)], fill=1)
            d.rectangle((5, 11, 18, 22), fill=1)
            d.rectangle((1, 12, 4, 21), fill=1)
            d.rectangle((19, 12, 22, 21), fill=1)
            d.rectangle((6, 23, 10, 31), fill=1)
            d.rectangle((13, 23, 17, 31), fill=1)

        spr = Image.new("1", (sw, sh), 0)
        shapes(ImageDraw.Draw(spr))
        d = ImageDraw.Draw(spr)
        d.rectangle((9, 5, 10, 6), fill=0)
        d.rectangle((13, 5, 14, 6), fill=0)
        for y in (14, 17, 20):
            d.line((8, y, 15, y), fill=0)
        sil = Image.new("1", (sw, sh), 0)
        shapes(ImageDraw.Draw(sil))
        mask = sil.convert("L").filter(ImageFilter.MaxFilter(3)).convert("1")
        return spr, mask

    def restart(self):
        self.px, self.py, self.pa = 1.5, 1.5, 0.0  # Blick nach Osten, Gang ist frei
        self.hp, self.ammo = 100, 60
        self.cool = self.flash = self.hurt = 0
        self.bob = 0.0
        self.kills = 0
        self.dead = self.won = False
        spots = [
            (x + 0.5, y + 0.5)
            for y, row in enumerate(self.MAP)
            for x, ch in enumerate(row)
            if ch == "." and math.hypot(x - 1.5, y - 1.5) > 5
        ]
        self.monsters = [
            {"x": x, "y": y, "hp": 3, "cool": 20, "pain": 0}
            for x, y in random.sample(spots, 6)
        ]

    @property
    def finished(self):
        return self.dead or self.won

    # -- Physik / Logik ----------------------------------------------------
    def _blocked(self, x, y, r=0.22):
        for ox in (-r, r):
            for oy in (-r, r):
                if self.MAP[int(y + oy)][int(x + ox)] == "#":
                    return True
        return False

    @staticmethod
    def _norm(a):
        return (a + math.pi) % (2 * math.pi) - math.pi

    def _cast(self, ang):
        """DDA-Strahl: (Distanz, Seite, Zelle, Position entlang der Wand)."""
        dx, dy = math.cos(ang), math.sin(ang)
        dx = dx if abs(dx) > 1e-9 else 1e-9
        dy = dy if abs(dy) > 1e-9 else 1e-9
        mx, my = int(self.px), int(self.py)
        ddx, ddy = abs(1 / dx), abs(1 / dy)
        if dx < 0:
            stepx, sdx = -1, (self.px - mx) * ddx
        else:
            stepx, sdx = 1, (mx + 1 - self.px) * ddx
        if dy < 0:
            stepy, sdy = -1, (self.py - my) * ddy
        else:
            stepy, sdy = 1, (my + 1 - self.py) * ddy
        side = 0
        for _ in range(64):
            if sdx < sdy:
                sdx += ddx
                mx += stepx
                side = 0
            else:
                sdy += ddy
                my += stepy
                side = 1
            if self.MAP[my][mx] == "#":
                break
        dist = (sdx - ddx) if side == 0 else (sdy - ddy)
        hit = (self.py + dist * dy) if side == 0 else (self.px + dist * dx)
        return dist, side, (mx, my), hit - math.floor(hit)

    def _los(self, m):
        ang = math.atan2(m["y"] - self.py, m["x"] - self.px)
        return self._cast(ang)[0] >= math.hypot(m["x"] - self.px, m["y"] - self.py)

    def _shoot(self):
        wall = self._cast(self.pa)[0]
        best = None
        for m in self.monsters:
            dx, dy = m["x"] - self.px, m["y"] - self.py
            d = math.hypot(dx, dy)
            if d >= wall or d < 0.2:
                continue
            if abs(self._norm(math.atan2(dy, dx) - self.pa)) < math.atan2(0.3, d):
                if best is None or d < best[0]:
                    best = (d, m)
        if best:
            m = best[1]
            m["hp"] -= 1
            m["pain"] = 3
            if m["hp"] <= 0:
                self.monsters.remove(m)
                self.kills += 1
                if not self.monsters:
                    self.won = True

    def _update(self, keys):
        run = 1.6 if "run" in keys else 1.0
        if "left" in keys:
            self.pa -= 0.065 * run
        if "right" in keys:
            self.pa += 0.065 * run
        sp = 0.07 * run
        c, s = math.cos(self.pa), math.sin(self.pa)
        dx = dy = 0.0
        if "fwd" in keys:
            dx += c * sp
            dy += s * sp
        if "back" in keys:
            dx -= c * sp
            dy -= s * sp
        if "strafel" in keys:
            dx += s * sp
            dy -= c * sp
        if "strafer" in keys:
            dx -= s * sp
            dy += c * sp
        if dx or dy:
            self.bob += 0.3
            if not self._blocked(self.px + dx, self.py):
                self.px += dx
            if not self._blocked(self.px, self.py + dy):
                self.py += dy

        self.cool = max(0, self.cool - 1)
        self.flash = max(0, self.flash - 1)
        self.hurt = max(0, self.hurt - 1)
        if "fire" in keys and self.cool == 0 and self.ammo > 0:
            self.ammo -= 1
            self.cool = 9
            self.flash = 3
            self._shoot()

        for m in self.monsters:
            m["pain"] = max(0, m["pain"] - 1)
            dx, dy = self.px - m["x"], self.py - m["y"]
            d = math.hypot(dx, dy)
            if d > 9 or not self._los(m):
                continue
            if d > 0.9:
                nx, ny = m["x"] + dx / d * 0.025, m["y"] + dy / d * 0.025
                if not self._blocked(nx, m["y"], 0.25):
                    m["x"] = nx
                if not self._blocked(m["x"], ny, 0.25):
                    m["y"] = ny
            else:
                m["cool"] -= 1
                if m["cool"] <= 0:
                    m["cool"] = 35
                    self.hp -= 7
                    self.hurt = 3
        if self.hp <= 0:
            self.hp = 0
            self.dead = True

    def step(self, keys):
        if self.finished:
            if "use" in keys:
                self.restart()
        else:
            self._update(keys)
        return self._render()

    # -- Darstellung -------------------------------------------------------
    def _render(self):
        img = self.bg.copy()
        d = ImageDraw.Draw(img)
        zbuf = [99.0] * WIDTH
        prev = None
        for col in range(WIDTH):
            ang = self.pa + (col / WIDTH - 0.5) * self.FOV
            dist, side, cell, wx = self._cast(ang)
            perp = max(0.05, dist * math.cos(ang - self.pa))
            zbuf[col] = perp
            h = int(HEIGHT / perp)
            top = (HEIGHT - h) // 2
            t0, b0 = max(top, 0), min(top + h, HEIGHT) - 1
            key = (cell, side)
            if t0 <= b0:
                if key != prev or (wx * 4) % 1 < 0.06:
                    d.line((col, t0, col, b0), fill=0)  # Kante / Fuge
                else:
                    d.line((col, t0, col, b0), fill=255)
                    lvl = min(3, int(perp / 2.2) + side)
                    if lvl == 1:
                        d.point([(col, y) for y in range(t0, b0 + 1) if (col + y) % 4 == 0], fill=0)
                    elif lvl == 2:
                        d.point([(col, y) for y in range(t0, b0 + 1) if (col + y) % 2 == 0], fill=0)
                    elif lvl == 3:
                        d.point([(col, y) for y in range(t0, b0 + 1) if (col + y) % 4], fill=0)
            prev = key

        # Gegner als Sprites (von hinten nach vorn)
        sprites = []
        for m in self.monsters:
            dx, dy = m["x"] - self.px, m["y"] - self.py
            ang = self._norm(math.atan2(dy, dx) - self.pa)
            if abs(ang) < self.FOV / 2 + 0.4:
                sprites.append((math.hypot(dx, dy), ang, m))
        sprites.sort(key=lambda s: -s[0])
        for dist, ang, m in sprites:
            perp = dist * math.cos(ang)
            if perp < 0.2:
                continue
            sh = max(2, int(HEIGHT * 0.85 / perp))
            sw = max(2, int(sh * 0.75))
            bottom = (HEIGHT + int(HEIGHT / perp)) // 2
            top = bottom - sh
            left = int((ang / self.FOV + 0.5) * WIDTH) - sw // 2
            spr = self.sprite.resize((sw, sh), Image.NEAREST)
            msk = self.mask.resize((sw, sh), Image.NEAREST)
            if m["pain"]:
                spr = ImageChops.invert(spr)
            for i in range(sw):
                x = left + i
                if 0 <= x < WIDTH and perp < zbuf[x]:
                    img.paste(spr.crop((i, 0, i + 1, sh)), (x, top), msk.crop((i, 0, i + 1, sh)))

        # Waffe + Fadenkreuz
        d = ImageDraw.Draw(img)
        gx = WIDTH // 2 - 3 + int(math.sin(self.bob) * 2)
        gy = HEIGHT - 15 + abs(int(math.cos(self.bob)))
        d.rectangle((gx - 1, gy - 1, gx + 7, HEIGHT), fill=0)
        d.rectangle((gx + 2, gy, gx + 4, gy + 6), fill=255)
        d.rectangle((gx, gy + 6, gx + 6, HEIGHT), fill=255)
        d.line((gx + 3, gy + 9, gx + 3, HEIGHT), fill=0)
        if self.flash:
            d.polygon(
                [(gx + 3, gy - 9), (gx + 5, gy - 3), (gx + 10, gy - 2), (gx + 5, gy),
                 (gx + 3, gy + 1), (gx + 1, gy), (gx - 4, gy - 2), (gx + 1, gy - 3)],
                fill=255,
            )
        cx, cy = WIDTH // 2, HEIGHT // 2
        d.point([(cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)], fill=255)
        d.point((cx, cy), fill=0)

        # Anzeige oben links
        text = f"HP{self.hp} A{self.ammo} K{self.kills}"
        tw = d.textlength(text, font=self.font)
        d.rectangle((0, 0, tw + 2, 9), fill=0)
        d.text((1, -1), text, font=self.font, fill=255)

        if self.hurt == 3:
            img = ImageChops.invert(img)
        if self.dead:
            draw_banner(ImageDraw.Draw(img), self.font, "YOU DIED", "Leertaste = neu")
        elif self.won:
            draw_banner(ImageDraw.Draw(img), self.font, "ALLE TOT!", "Leertaste = neu")
        return img

    def close(self):
        pass


class OledApp:
    def __init__(self, root):
        self.root = root
        self.root.title("OLED Control Center - Raspberry Pi 4/5")
        self.root.resizable(False, False)
        # Fenster-Symbol aus dem Installationsordner laden. Beim direkten Start
        # ohne mitgelieferte Icon-Datei läuft die Anwendung unverändert weiter.
        self._window_icon = None
        try:
            icon_path = os.path.join(APP_DIR, "oled-control-center.png")
            if os.path.isfile(icon_path):
                self._window_icon = ImageTk.PhotoImage(Image.open(icon_path))
                self.root.iconphoto(True, self._window_icon)
        except Exception:
            pass

        self.image = Image.new("1", (WIDTH, HEIGHT), 0)
        self.draw = ImageDraw.Draw(self.image)
        try:
            self.font = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14
            )
            self.font_small = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 11
            )
        except Exception:
            self.font = ImageFont.load_default()
            self.font_small = ImageFont.load_default()
        self.font_sys = self._load_font(9)

        self.oled = OledDevice()
        self._doom = None  # laufendes Doom-Backend
        self._doom_job = None
        self._doom_held = set()  # aktuell gedrückte Doom-Aktionen
        self._doom_rel = {}  # verzögertes Loslassen (Tastenwiederholung glätten)
        self.running_mode = None  # None | "text" | "system"
        self.live_push = tk.BooleanVar(value=True)
        self.draw_color = 1  # 1 = an (weiss), 0 = aus (schwarz) beim Zeichnen

        self._build_connection_bar()
        self._build_notebook()
        self._update_status_label()
        self.render()

    # ------------------------------------------------------------------
    # Verbindungsleiste oben
    # ------------------------------------------------------------------
    def _build_connection_bar(self):
        bar = ttk.Frame(self.root, padding=6)
        bar.pack(fill="x")

        ttk.Label(bar, text="I2C-Port:").pack(side="left")
        self.port_entry = ttk.Entry(bar, width=4)
        self.port_entry.insert(0, "1")
        self.port_entry.pack(side="left", padx=(2, 10))

        ttk.Label(bar, text="Adresse:").pack(side="left")
        self.addr_entry = ttk.Entry(bar, width=6)
        self.addr_entry.insert(0, "0x3C")
        self.addr_entry.pack(side="left", padx=(2, 10))

        ttk.Button(bar, text="Verbinden", command=self.reconnect).pack(side="left")

        self.status_label = ttk.Label(bar, text="", width=40)
        self.status_label.pack(side="left", padx=10)

        ttk.Checkbutton(
            bar, text="Live auf Display", variable=self.live_push
        ).pack(side="right")

    def reconnect(self):
        try:
            port = int(self.port_entry.get())
            addr = int(self.addr_entry.get(), 16)
        except ValueError:
            messagebox.showerror("Fehler", "Port muss eine Zahl, Adresse z.B. 0x3C sein.")
            return
        self.oled.connect(port, addr)
        self._update_status_label()
        if self.live_push.get():
            self.oled.push(self.image)

    def _update_status_label(self):
        if self.oled.connected:
            self.status_label.config(
                text="Verbunden mit echtem Display", foreground="green"
            )
        else:
            msg = "Nur virtuell (kein Display gefunden)"
            self.status_label.config(text=msg, foreground="red")

    # ------------------------------------------------------------------
    # Tabs
    # ------------------------------------------------------------------
    def _build_notebook(self):
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(padx=8, pady=8)
        self.notebook.bind("<<NotebookTabChanged>>", lambda e: self.stop_modes())

        # virtuelle Anzeige wird in jedem Tab oben eingebettet
        self.display_frame = ttk.Frame(self.root)
        self.canvas = tk.Canvas(
            self.display_frame,
            width=WIDTH * SCALE,
            height=HEIGHT * SCALE,
            bg="black",
            highlightthickness=1,
            highlightbackground="gray",
        )
        self.canvas.pack()
        self.display_frame.pack(pady=(0, 8))

        self._build_pixel_tab()
        self._build_text_tab()
        self._build_system_tab()
        self._build_code_tab()
        self._build_tetris_tab()
        self._build_doom_tab()

    # -- Pixel-Editor -----------------------------------------------------
    def _build_pixel_tab(self):
        tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(tab, text="Pixel-Editor")

        info = ttk.Label(
            tab,
            text="Linksklick/ziehen = Pixel an, Rechtsklick/ziehen = Pixel aus",
        )
        info.pack(anchor="w")

        btns = ttk.Frame(tab)
        btns.pack(fill="x", pady=6)
        ttk.Button(btns, text="Löschen", command=self.clear_image).pack(side="left")
        ttk.Button(btns, text="Invertieren", command=self.invert_image).pack(
            side="left", padx=6
        )
        ttk.Button(
            btns, text="Auf Display übertragen", command=self.push_now
        ).pack(side="left")

        self.canvas.bind("<Button-1>", lambda e: self._paint(e, 1))
        self.canvas.bind("<B1-Motion>", lambda e: self._paint(e, 1))
        self.canvas.bind("<Button-3>", lambda e: self._paint(e, 0))
        self.canvas.bind("<B3-Motion>", lambda e: self._paint(e, 0))

    def _paint(self, event, value):
        if self.running_mode == "tetris":
            return
        x = event.x // SCALE
        y = event.y // SCALE
        if 0 <= x < WIDTH and 0 <= y < HEIGHT:
            self.image.putpixel((x, y), 255 if value else 0)
            self.render()
            if self.live_push.get():
                self.oled.push(self.image)

    def clear_image(self):
        self.stop_modes()
        self.draw.rectangle((0, 0, WIDTH, HEIGHT), fill=0)
        self.render()
        if self.live_push.get():
            self.oled.push(self.image)

    def invert_image(self):
        self.stop_modes()
        self.image = Image.eval(self.image, lambda p: 255 - p)
        self.draw = ImageDraw.Draw(self.image)
        self.render()
        if self.live_push.get():
            self.oled.push(self.image)

    def push_now(self):
        self.oled.push(self.image)
        self._update_status_label()

    # -- Text-Modus ---------------------------------------------------------
    def _build_text_tab(self):
        tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(tab, text="Text")

        ttk.Label(tab, text="Text:").pack(anchor="w")
        self.text_entry = ttk.Entry(tab, width=40)
        self.text_entry.insert(0, "Hallo Pi 5!")
        self.text_entry.pack(fill="x", pady=(0, 6))

        speed_frame = ttk.Frame(tab)
        speed_frame.pack(fill="x")
        ttk.Label(speed_frame, text="Geschwindigkeit:").pack(side="left")
        self.speed_scale = ttk.Scale(speed_frame, from_=1, to=20, orient="horizontal")
        self.speed_scale.set(5)
        self.speed_scale.pack(side="left", fill="x", expand=True, padx=6)

        size_frame = ttk.Frame(tab)
        size_frame.pack(fill="x")
        ttk.Label(size_frame, text="Schriftgröße:      ").pack(side="left")
        self.size_scale = ttk.Scale(size_frame, from_=8, to=56, orient="horizontal")
        self.size_scale.set(40)
        self.size_scale.pack(side="left", fill="x", expand=True, padx=6)

        btns = ttk.Frame(tab)
        btns.pack(fill="x", pady=6)
        ttk.Button(btns, text="Start Scrollen", command=self.start_text_scroll).pack(
            side="left"
        )
        ttk.Button(btns, text="Stop", command=self.stop_modes).pack(side="left", padx=6)

    def start_text_scroll(self):
        self.stop_modes()
        text = self.text_entry.get() or " "
        font = self._load_font(int(self.size_scale.get()))
        bbox = self.draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        self._scroll_text_img = Image.new("1", (text_w + WIDTH * 2, HEIGHT), 0)
        d = ImageDraw.Draw(self._scroll_text_img)
        d.text((WIDTH - bbox[0], (HEIGHT - (bbox[3] - bbox[1])) // 2 - bbox[1]), text, font=font, fill=255)
        self._scroll_offset = 0
        self._scroll_text_w = text_w
        self.running_mode = "text"
        self._text_tick()

    def _text_tick(self):
        if self.running_mode != "text":
            return
        frame = self._scroll_text_img.crop(
            (self._scroll_offset, 0, self._scroll_offset + WIDTH, HEIGHT)
        )
        self.image = frame
        self.draw = ImageDraw.Draw(self.image)
        self.render()
        if self.live_push.get():
            self.oled.push(self.image)

        self._scroll_offset += 2
        if self._scroll_offset > self._scroll_text_w + WIDTH:
            self._scroll_offset = 0

        delay = int(110 - self.speed_scale.get() * 5)
        self.root.after(max(delay, 10), self._text_tick)

    # -- System-Modus ----------------------------------------------------
    def _build_system_tab(self):
        tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(tab, text="System")

        ttk.Label(
            tab, text="Zeigt CPU-Temperatur, Auslastung und RAM laufend an."
        ).pack(anchor="w")

        btns = ttk.Frame(tab)
        btns.pack(fill="x", pady=6)
        ttk.Button(btns, text="Start", command=self.start_system_mode).pack(side="left")
        ttk.Button(btns, text="Stop", command=self.stop_modes).pack(side="left", padx=6)

    def _load_font(self, size):
        try:
            return ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size
            )
        except Exception:
            return ImageFont.load_default()

    def _bar(self, x0, y0, x1, y1, pct):
        pct = max(0, min(100, pct))
        self.draw.rectangle((x0, y0, x1, y1), outline=255, fill=0)
        w = int((x1 - x0 - 2) * pct / 100)
        if w > 0:
            self.draw.rectangle((x0 + 1, y0 + 1, x0 + w, y1 - 1), fill=255)

    def start_system_mode(self):
        self.stop_modes()
        get_cpu_percent()  # erster Aufruf initialisiert die Messung
        self.running_mode = "system"
        self._system_tick()

    def _system_tick(self):
        if self.running_mode != "system":
            return
        temp = get_cpu_temp()
        cpu = get_cpu_percent()
        mem = get_mem_info()
        disk = get_disk_percent()
        load = get_cpu_load()
        font = self.font_sys

        # (Text, Prozentwert für den Balken)
        rows = [
            (f"Temp {temp:.1f}C" if temp is not None else "Temp n/a",
             temp / 85 * 100 if temp is not None else None),
            (f"CPU {cpu:.1f}%" if cpu is not None else "CPU n/a", cpu),
            (f"RAM {mem[0]:.1f}/{mem[1]:.1f}G" if mem else "RAM n/a",
             mem[2] if mem else None),
            (f"Disk {disk:.0f}%" if disk is not None else "Disk n/a", disk),
            (f"Last {load:.2f}" if load is not None else "Last n/a",
             load / 4 * 100 if load is not None else None),  # Pi 5 = 4 Kerne
        ]

        self.draw.rectangle((0, 0, WIDTH, HEIGHT), fill=0)
        row_h = 10
        for i, (label, pct) in enumerate(rows):
            y = i * row_h
            self.draw.text((0, y), label, font=font, fill=255)
            if pct is not None:
                self._bar(76, y + 2, WIDTH - 1, y + 8, pct)

        self.draw.line((0, 51, WIDTH, 51), fill=255)
        self.draw.text((0, 53), f"{get_ip()}  {get_uptime()}", font=font, fill=255)

        self.render()
        if self.live_push.get():
            self.oled.push(self.image)

        self.root.after(1000, self._system_tick)

    # -- Code-Modus --------------------------------------------------------
    def _build_code_tab(self):
        tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(tab, text="Code")

        ttk.Label(
            tab,
            text="Eigener Python-Code. Verfügbar: draw, image, Image, ImageDraw,"
            " ImageFont, width, height",
        ).pack(anchor="w")

        self.code_box = scrolledtext.ScrolledText(tab, width=56, height=12)
        self.code_box.pack(pady=6)
        self.code_box.insert(
            "1.0",
            'draw.rectangle((0, 0, width, height), fill=0)\n'
            'draw.ellipse((10, 10, 54, 54), outline=255)\n'
            'draw.text((60, 20), "Hi!", fill=255)\n',
        )

        ttk.Button(tab, text="Ausführen", command=self.run_code).pack(anchor="w")
        self.code_status = ttk.Label(tab, text="")
        self.code_status.pack(anchor="w", pady=(4, 0))

    def run_code(self):
        self.stop_modes()
        code = self.code_box.get("1.0", "end")
        namespace = {
            "draw": self.draw,
            "image": self.image,
            "Image": Image,
            "ImageDraw": ImageDraw,
            "ImageFont": ImageFont,
            "width": WIDTH,
            "height": HEIGHT,
        }
        try:
            exec(code, namespace)
            self.code_status.config(text="OK", foreground="green")
        except Exception as e:
            self.code_status.config(text=f"Fehler: {e}", foreground="red")

        self.render()
        if self.live_push.get():
            self.oled.push(self.image)

    # ------------------------------------------------------------------
    # -- Tetris ------------------------------------------------------------
    def _build_tetris_tab(self):
        tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(tab, text="Tetris")

        self.tetris = TetrisGame()
        self._tetris_job = None

        ttk.Label(
            tab,
            justify="left",
            text="Pfeil links/rechts = bewegen    Pfeil hoch = drehen\n"
            "Pfeil runter = schneller fallen    Leertaste = sofort fallen\n"
            "P = Pause    (Tasten wirken, wenn das Display-Bild den Fokus hat -\n"
            "nach dem Start passiert das automatisch, sonst einmal draufklicken)",
        ).pack(anchor="w")

        btns = ttk.Frame(tab)
        btns.pack(fill="x", pady=6)
        ttk.Button(btns, text="Neues Spiel", command=self.start_tetris).pack(side="left")
        ttk.Button(btns, text="Stop", command=self.stop_modes).pack(side="left", padx=6)

        def space_action():
            if self.tetris.game_over:
                self.start_tetris()
            else:
                self.tetris.hard_drop()

        keys = {
            "<Left>": lambda: self.tetris.move(-1),
            "<Right>": lambda: self.tetris.move(1),
            "<Up>": self.tetris.rotate,
            "<Down>": self.tetris.soft_drop,
            "<space>": space_action,
            "<Return>": space_action,
            "<p>": self.tetris.toggle_pause,
            "<P>": self.tetris.toggle_pause,
        }
        # Tastaturereignisse laufen über _on_key_press (gemeinsam mit Doom)
        self._tetris_keys = {k[1:-1]: a for k, a in keys.items()}
        # Klick auf das Bild gibt ihm den Tastaturfokus
        self.canvas.bind("<Button-1>", lambda e: self.canvas.focus_set(), add="+")

    def _tetris_key(self, action):
        if self.running_mode == "tetris":
            action()
            if self.running_mode == "tetris":
                self._tetris_draw()
        return "break"

    def start_tetris(self):
        self.stop_modes()
        self.tetris.reset()
        self.running_mode = "tetris"
        self.canvas.focus_set()
        self._tetris_draw()
        self._tetris_job = self.root.after(self.tetris.interval(), self._tetris_tick)

    def _tetris_tick(self):
        self._tetris_job = None
        if self.running_mode != "tetris":
            return
        g = self.tetris
        if g._active():
            g.step()
            self._tetris_draw()
        self._tetris_job = self.root.after(g.interval(), self._tetris_tick)

    def _tetris_draw(self):
        g = self.tetris
        self.image = Image.new("1", (WIDTH, HEIGHT), 0)
        d = self.draw = ImageDraw.Draw(self.image)
        font = self.font_sys
        CELL, BX, BY = 3, 2, 1  # 3 px pro Feld -> 30x60 px Spielfeld

        def cell(px, py):
            d.rectangle((px, py, px + 1, py + 1), fill=255)  # 2x2 + 1px Lücke

        # Rahmen und festgesetzte Steine
        d.rectangle((BX - 1, BY - 1, BX + g.COLS * CELL, BY + g.ROWS * CELL), outline=255)
        for r, row in enumerate(g.board):
            for c, v in enumerate(row):
                if v:
                    cell(BX + c * CELL, BY + r * CELL)
        # fallender Stein
        for r, row in enumerate(g.shape):
            for c, v in enumerate(row):
                if v and g.y + r >= 0:
                    cell(BX + (g.x + c) * CELL, BY + (g.y + r) * CELL)

        # Info-Bereich rechts
        d.text((38, 0), "TETRIS", font=font, fill=255)
        d.text((38, 12), f"Punkte {g.score}", font=font, fill=255)
        d.text((38, 22), f"Linien {g.lines}", font=font, fill=255)
        d.text((38, 32), f"Level {g.level}", font=font, fill=255)
        if g.game_over:
            d.text((38, 44), "GAME OVER", font=font, fill=255)
            d.text((38, 54), "Leertaste=neu", font=font, fill=255)
        elif g.paused:
            d.text((38, 46), "PAUSE", font=font, fill=255)
        else:
            d.text((38, 46), "Next", font=font, fill=255)
            for r, row in enumerate(g.next_shape):
                for c, v in enumerate(row):
                    if v:
                        cell(80 + c * CELL, 46 + r * CELL)

        self.render()
        if self.live_push.get():
            self.oled.push_async(self.image)

    # -- Doom --------------------------------------------------------------
    def _build_doom_tab(self):
        tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(tab, text="Doom")

        engines = ["Echtes Doom (ViZDoom)", "Mini-Doom (Raycaster)"]
        has_vizdoom = importlib.util.find_spec("vizdoom") is not None
        self.doom_engine = tk.StringVar(value=engines[0] if has_vizdoom else engines[1])

        row = ttk.Frame(tab)
        row.pack(fill="x")
        ttk.Label(row, text="Engine:").pack(side="left")
        ttk.Combobox(
            row, textvariable=self.doom_engine, values=engines, state="readonly", width=24
        ).pack(side="left", padx=6)
        ttk.Button(row, text="Start", command=self.start_doom).pack(side="left")
        ttk.Button(row, text="Stop", command=self.stop_modes).pack(side="left", padx=6)

        self.doom_status = ttk.Label(tab, text="")
        self.doom_status.pack(anchor="w", pady=(4, 0))
        ttk.Label(
            tab,
            justify="left",
            text="Pfeile = laufen/drehen    Strg oder F = schießen    Leertaste/E = benutzen\n"
            "Shift = rennen    A/D = seitwärts    1-7 = Waffe (nur echtes Doom)\n"
            "Nach dem Tod: Leertaste = neu starten",
        ).pack(anchor="w", pady=(4, 0))

        self.canvas.bind("<KeyPress>", self._on_key_press)
        self.canvas.bind("<KeyRelease>", self._on_key_release)

    def _on_key_press(self, event):
        if self.running_mode == "tetris":
            action = self._tetris_keys.get(event.keysym)
            if action:
                self._tetris_key(action)
            return "break"
        if self.running_mode == "doom":
            name = DOOM_KEYS.get(event.keysym)
            if name:
                job = self._doom_rel.pop(name, None)
                if job:
                    self.root.after_cancel(job)
                self._doom_held.add(name)
            return "break"

    def _on_key_release(self, event):
        if self.running_mode != "doom":
            return
        name = DOOM_KEYS.get(event.keysym)
        if name:
            # Tastenwiederholung unter X11 sendet Release+Press direkt nacheinander:
            # deshalb erst nach kurzer Pause wirklich loslassen.
            job = self._doom_rel.pop(name, None)
            if job:
                self.root.after_cancel(job)
            self._doom_rel[name] = self.root.after(45, lambda n=name: self._doom_drop(n))
        return "break"

    def _doom_drop(self, name):
        self._doom_held.discard(name)
        self._doom_rel.pop(name, None)

    def start_doom(self):
        self.stop_modes()
        self.doom_status.config(text="Doom wird geladen ...", foreground="black")
        self.root.update_idletasks()

        backend = None
        if self.doom_engine.get().startswith("Echtes"):
            try:
                backend = ViZDoomBackend(self.font_sys, APP_DIR)
                wad = os.path.basename(backend.wad) if backend.wad else "mitgelieferte WAD"
                self.doom_status.config(text=f"Echtes Doom läuft ({wad})", foreground="green")
            except ImportError:
                messagebox.showinfo(
                    "ViZDoom fehlt",
                    "Für echtes Doom wird ViZDoom benötigt. Installation im Terminal:\n\n"
                    "source ~/oled-env/bin/activate\npip install vizdoom\n\n"
                    "Ich starte stattdessen Mini-Doom.",
                )
            except Exception as e:
                messagebox.showerror(
                    "ViZDoom konnte nicht starten",
                    f"{e}\n\nTipp: Lege eine WAD-Datei (z.B. doom1.wad oder freedoom2.wad) in den "
                    "Programmordner oder installiere sie mit 'sudo apt install freedoom'.\n\n"
                    "Ich starte stattdessen Mini-Doom.",
                )
        if backend is None:
            backend = MiniDoom(self.font_sys)
            self.doom_status.config(text="Mini-Doom läuft", foreground="green")

        self._doom = backend
        self._doom_held = set()
        self.running_mode = "doom"
        self.canvas.focus_set()
        self._doom_job = self.root.after(1, self._doom_tick)

    def _doom_tick(self):
        self._doom_job = None
        if self.running_mode != "doom" or self._doom is None:
            return
        t0 = time.perf_counter()
        try:
            frame = self._doom.step(self._doom_held)
        except Exception as e:
            self.stop_modes()
            self.doom_status.config(text=f"Fehler: {e}", foreground="red")
            return
        self.image = frame
        self.draw = ImageDraw.Draw(frame)
        self.render()
        if self.live_push.get():
            self.oled.push_async(self.image)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        self._doom_job = self.root.after(max(1, int(1000 / 35 - elapsed_ms)), self._doom_tick)

    # ------------------------------------------------------------------
    def stop_modes(self):
        self.running_mode = None
        if getattr(self, "_tetris_job", None) is not None:
            self.root.after_cancel(self._tetris_job)
            self._tetris_job = None
        if self._doom_job is not None:
            self.root.after_cancel(self._doom_job)
            self._doom_job = None
        if self._doom is not None:
            self._doom.close()
            self._doom = None
        for job in self._doom_rel.values():
            self.root.after_cancel(job)
        self._doom_rel.clear()
        self._doom_held.clear()

    def render(self):
        big = self.image.convert("L").resize(
            (WIDTH * SCALE, HEIGHT * SCALE), Image.NEAREST
        )
        # weisse Pixel bleiben weiss, schwarze werden dunkelblau (OLED-Look)
        rgb = ImageOps.colorize(big, black=(10, 10, 20), white=(255, 255, 255))
        self._tk_img = ImageTk.PhotoImage(rgb)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self._tk_img)


if __name__ == "__main__":
    root = tk.Tk()
    app = OledApp(root)
    root.mainloop()
