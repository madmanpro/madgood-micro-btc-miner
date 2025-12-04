import os
import re
import sys
import time
import threading
import subprocess
import tkinter as tk
from tkinter import ttk

import requests
from PIL import Image, ImageTk

# ---------------- CONFIG ----------------

APP_VERSION = "0.3.2"

GIF_NAME = os.path.join("assets", "BTC Miner App.gif")   # Animated logo in assets/

# Choose the right miner binary per OS
if sys.platform.startswith("win"):
    # Windows
    CPUMINER_NAME = os.path.join("miner", "windows", "cpuminer.exe")
elif sys.platform == "darwin":
    # macOS
    CPUMINER_NAME = os.path.join("miner", "mac", "cpuminer")
else:
    # Linux (what you're running now)
    CPUMINER_NAME = os.path.join("miner", "linux", "cpuminer")

README_FILENAME = "README.txt"

POOL_HOST = "solo.ckpool.org"
POOL_PORT = 3333

# Donation address (for future dev / support)
DONATION_ADDRESS = "bc1qkjdpk5awqwswx7rl4nclh90x8gntm93g3y4mnc"


# ---------------- PATH HELPERS ----------------

def resource_path(relative_path: str) -> str:
    """
    Resolve path whether running from source or as a PyInstaller binary.
    """
    if hasattr(sys, "_MEIPASS"):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, relative_path)


LOGO_PATH = resource_path(GIF_NAME)
CPUMINER_PATH = resource_path(CPUMINER_NAME)
README_PATH = resource_path(README_FILENAME)


# ---------------- GLOBAL STATE ----------------

wallet_address = ""
mining = False
connected_to_pool = False

current_hashrate = 0.0  # H/s
total_hashes = 0.0

btc_price_usd = 0.0
block_height = 0

hash_integrate_last = None

power_mode = "high"  # "high" | "medium" | "low"
mining_start_time = None

ckpool_user_id = ""
current_job_id = ""
block_attempts = 0
blocks_found = 0


# ---------------- PARSERS & HELPERS ----------------

def parse_hashrate_from_line(line: str) -> float:
    """
    Extract hashrate from cpuminer log output.

    Handles:
      - Periodic report lines: "Hash rate ... (13.16Mh/s)"
      - TTF lines: "TTF @ 80.00 h/s" or "TTF @ 13.79 Mh/s"
      - Generic "123.45 kH/s", "12.3 MH/s", etc.

    Returns hashrate in H/s.
    """
    def to_hps(val: float, unit: str) -> float:
        unit = unit.strip()
        mult = 1.0
        if unit in ("k", "K"):
            mult = 1e3
        elif unit in ("m", "M"):
            mult = 1e6
        elif unit in ("g", "G"):
            mult = 1e9
        return val * mult

    lower = line.lower()

    # Periodic report style: "Hash rate ... (13.16Mh/s)"
    m = re.search(r"\(([\d.]+)\s*([kKmMgG])h/s\)", line)
    if m:
        val = float(m.group(1))
        unit = m.group(2)
        return to_hps(val, unit)

    # TTF lines: "TTF @ 80.00 h/s" or "TTF @ 13.79 Mh/s"
    if "ttf" in lower:
        m = re.search(r"TTF @\s*([\d.]+)\s*([kKmMgG]?)[hH]/s", line)
        if m:
            val = float(m.group(1))
            unit = m.group(2)
            return to_hps(val, unit)

    # Generic "xxx H/s" somewhere in the line (not TTF)
    if "h/s" in lower and "ttf" not in lower:
        m = re.search(r"([\d.]+)\s*([kKmMgG]?)[hH]/s", line)
        if m:
            val = float(m.group(1))
            unit = m.group(2)
            return to_hps(val, unit)

    return 0.0


def parse_block_height_from_line(line: str):
    m = re.search(r"Block\s+(\d+)", line)
    return int(m.group(1)) if m else None


def parse_extranonce_from_line(line: str):
    m = re.search(r"stratum extranonce1\s+0x([0-9a-fA-F]+)", line, re.IGNORECASE)
    return m.group(1) if m else None


def parse_job_from_line(line: str):
    m = re.search(r"Job\s+([0-9a-fA-F]+)", line)
    return m.group(1) if m else None


def get_threads_for_power() -> int:
    """
    Map power_mode -> number of CPU threads.
    High   = all cores
    Medium = half the cores (rounded up)
    Low    = 1 core
    """
    cores = os.cpu_count() or 1
    if power_mode == "high":
        return max(1, cores)
    elif power_mode == "medium":
        return max(1, (cores + 1) // 2)
    else:
        return 1  # low


def load_readme_text() -> str:
    if os.path.exists(README_PATH):
        try:
            with open(README_PATH, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        except Exception:
            pass
    return (
        "MADGood Micro Miner\n"
        "(No README.txt found next to the app yet.)"
    )


def network_status_loop(ui_update_callback):
    """
    Periodically fetch BTC price + tip block height.
    """
    global btc_price_usd, block_height

    while True:
        try:
            # Block height
            r_block = requests.get(
                "https://blockstream.info/api/blocks/tip/height", timeout=5
            )
            if r_block.ok:
                block_height = int(r_block.text.strip())

            # BTC price
            r_price = requests.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": "bitcoin", "vs_currencies": "usd"},
                timeout=5,
            )
            if r_price.ok:
                data = r_price.json()
                btc_price_usd = float(data["bitcoin"]["usd"])
        except Exception:
            pass

        ui_update_callback()
        time.sleep(600)  # 10 minutes


# ---------------- MAIN APP ----------------

class MadGoodMinerApp:
    def __init__(self, root):
        self.root = root
        root.title("MADGood Micro BTC Miner")

        self.miner_proc = None
        self.log_lines = []
        self.log_lock = threading.Lock()

        # GIF & logos
        self.logo_label = None
        self.logo_frames = []
        self.logo_frame_index = 0

        self.big_logo_label = None
        self.big_logo_frames = []
        self.big_logo_frame_index = 0

        # Block alert flashing
        self.block_flash_active = False
        self.block_flash_on = False

        # Compact mode
        self.compact_win = None
        self.compact_geometry = None
        self.comp_logo_label = None
        self.comp_uptime_label = None
        self.comp_hashrate_label = None
        self.comp_attempts_label = None
        self.comp_conn_light = None
        self.comp_mining_light = None
        self.comp_status_label = None

        # Layout root
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)

        # Notebook tabs (Miner, Info, GIF)
        self.notebook = ttk.Notebook(root)
        self.notebook.grid(row=0, column=0, sticky="nsew")

        self.miner_frame = ttk.Frame(self.notebook)
        self.info_frame = ttk.Frame(self.notebook)
        self.gif_frame = ttk.Frame(self.notebook)

        self.notebook.add(self.miner_frame, text="Miner")
        self.notebook.add(self.info_frame, text="Info")
        self.notebook.add(self.gif_frame, text="GIF")

        self.build_miner_tab()
        self.build_info_tab()
        self.build_gif_tab()

        # Network info thread
        net_thread = threading.Thread(
            target=network_status_loop,
            args=(self.thread_safe_update,),
            daemon=True,
        )
        net_thread.start()

    # ---------- Miner Tab ----------

    def build_miner_tab(self):
        # Left padding buffer
        main = ttk.Frame(self.miner_frame, padding=(25, 20, 20, 20))
        main.grid(row=0, column=0, sticky="nsew")

        for i in range(3):
            main.columnconfigure(i, weight=1)
        for r in range(0, 17):
            main.rowconfigure(r, weight=0)
        main.rowconfigure(16, weight=1)

        # Title at very top-left
        title = ttk.Label(
            main,
            text="MADGood Micro BTC Miner",
            font=("Helvetica", 18, "bold"),
        )
        title.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 5))

        # Block attempts / found small counter (italic)
        self.block_counter_var = tk.StringVar(value="Attempts: 0 / Found: 0")
        block_counter_label = ttk.Label(
            main,
            textvariable=self.block_counter_var,
            font=("Helvetica", 8, "italic"),
        )
        block_counter_label.grid(row=1, column=0, sticky="w")

        # Small logo on top-right
        self.logo_label = ttk.Label(main, text="[logo]")
        self.logo_label.grid(row=0, column=2, rowspan=2,
                             sticky="ne", padx=(10, 0), pady=(0, 10))
        self.setup_small_logo_animation()

        # Block alert label (flashing red on block found)
        self.block_alert_var = tk.StringVar(value="")
        self.block_alert_label = ttk.Label(
            main,
            textvariable=self.block_alert_var,
            font=("Helvetica", 12, "bold"),
            foreground="red",
        )
        self.block_alert_label.grid(row=2, column=2, sticky="ne", padx=(10, 0))

        # Subtitle under title
        subtitle = ttk.Label(
            main,
            text="GUI for cpuminer-opt (CKPool solo)",
            font=("Helvetica", 10),
        )
        subtitle.grid(row=2, column=0, columnspan=2, sticky="w", pady=(0, 10))

        # Status
        self.status_var = tk.StringVar(value="Idle")
        status_label = ttk.Label(main, textvariable=self.status_var, foreground="gray")
        status_label.grid(row=3, column=0, columnspan=3, sticky="w", pady=(0, 5))

        # Lights
        lights_frame = ttk.Frame(main)
        lights_frame.grid(row=4, column=0, columnspan=3, sticky="w", pady=(0, 10))

        self.conn_light = tk.Label(lights_frame, text="●", font=("Helvetica", 14))
        self.conn_label = ttk.Label(lights_frame, text="Pool Connectivity")

        self.mining_light = tk.Label(lights_frame, text="●", font=("Helvetica", 14))
        self.mining_label = ttk.Label(lights_frame, text="Mining Status")

        self.conn_light.grid(row=0, column=0, padx=(0, 5))
        self.conn_label.grid(row=0, column=1, padx=(0, 20))
        self.mining_light.grid(row=0, column=2, padx=(0, 5))
        self.mining_label.grid(row=0, column=3)

        # Wallet
        ttk.Label(main, text="Wallet Address:").grid(row=5, column=0, sticky="w")
        self.wallet_var = tk.StringVar(value=wallet_address)
        self.wallet_entry = ttk.Entry(main, textvariable=self.wallet_var, width=52)
        self.wallet_entry.grid(row=5, column=1, columnspan=2,
                               sticky="we", pady=(0, 5))

        # BTC info
        ttk.Label(main, text="BTC Price (USD):").grid(
            row=6, column=0, sticky="w", pady=(8, 0)
        )
        self.price_var = tk.StringVar(value="$0.00")
        ttk.Label(main, textvariable=self.price_var).grid(
            row=6, column=1, sticky="w", pady=(8, 0)
        )

        ttk.Label(main, text="Block Height:").grid(row=7, column=0, sticky="w")
        self.block_var = tk.StringVar(value="0")
        ttk.Label(main, textvariable=self.block_var).grid(row=7, column=1, sticky="w")

        # Mining stats
        ttk.Label(main, text="Current Hashrate:").grid(
            row=8, column=0, sticky="w", pady=(8, 0)
        )
        self.hashrate_var = tk.StringVar(value="0 H/s")
        ttk.Label(main, textvariable=self.hashrate_var).grid(
            row=8, column=1, sticky="w", pady=(8, 0)
        )

        ttk.Label(main, text="Total Hash Attempts:").grid(row=9, column=0, sticky="w")
        self.total_hashes_var = tk.StringVar(value="0")
        ttk.Label(main, textvariable=self.total_hashes_var).grid(
            row=9, column=1, sticky="w"
        )

        ttk.Label(main, text="Uptime:").grid(row=10, column=0, sticky="w")
        self.uptime_var = tk.StringVar(value="0s")
        ttk.Label(main, textvariable=self.uptime_var).grid(row=10, column=1, sticky="w")

        ttk.Label(main, text="CKPool User ID:").grid(row=11, column=0, sticky="w")
        self.user_id_var = tk.StringVar(value="-")
        ttk.Label(main, textvariable=self.user_id_var).grid(
            row=11, column=1, sticky="w"
        )

        ttk.Label(main, text="Current Job ID:").grid(row=12, column=0, sticky="w")
        self.job_id_var = tk.StringVar(value="-")
        ttk.Label(main, textvariable=self.job_id_var).grid(
            row=12, column=1, sticky="w"
        )

        # Mining power
        power_frame = ttk.LabelFrame(main, text="Mining Power")
        power_frame.grid(row=13, column=0, columnspan=3, sticky="ew", pady=(12, 0))

        self.power_mode_var = tk.StringVar(value="high")

        rb_high = ttk.Radiobutton(
            power_frame,
            text="High (all cores)",
            value="high",
            variable=self.power_mode_var,
            command=self.change_power_mode,
        )
        rb_med = ttk.Radiobutton(
            power_frame,
            text="Medium (~½ cores)",
            value="medium",
            variable=self.power_mode_var,
            command=self.change_power_mode,
        )
        rb_low = ttk.Radiobutton(
            power_frame,
            text="Low (1 core)",
            value="low",
            variable=self.power_mode_var,
            command=self.change_power_mode,
        )

        rb_high.grid(row=0, column=0, padx=5, pady=5, sticky="w")
        rb_med.grid(row=0, column=1, padx=5, pady=5, sticky="w")
        rb_low.grid(row=0, column=2, padx=5, pady=5, sticky="w")

        # Controls
        controls_frame = ttk.Frame(main)
        controls_frame.grid(row=14, column=0, columnspan=3, sticky="ew", pady=(14, 0))

        self.start_btn = ttk.Button(
            controls_frame, text="Start Mining", command=self.start_mining
        )
        self.stop_btn = ttk.Button(
            controls_frame, text="Stop Mining", state="disabled", command=self.stop_mining
        )
        self.compact_btn = ttk.Button(
            controls_frame, text="Compact Mode", command=self.open_compact_mode
        )

        self.start_btn.grid(row=0, column=0, padx=(0, 5), sticky="ew")
        self.stop_btn.grid(row=0, column=1, padx=(5, 5), sticky="ew")
        self.compact_btn.grid(row=0, column=2, padx=(5, 0), sticky="ew")

        for i in range(3):
            controls_frame.columnconfigure(i, weight=1)

        # Log output
        ttk.Label(main, text="Miner Log:").grid(
            row=15, column=0, sticky="w", pady=(10, 0)
        )
        self.log_text = tk.Text(
            main, height=8, width=70, state="disabled", wrap="word"
        )
        self.log_text.grid(
            row=16, column=0, columnspan=3, sticky="nsew", pady=(2, 0)
        )

        # Kick off periodic UI refresh
        self.schedule_ui_refresh()

    # ---------- Logos & GIF ----------

    def setup_small_logo_animation(self):
        if not LOGO_PATH or not os.path.exists(LOGO_PATH):
            self.logo_label.config(text="[logo]")
            return

        frames = []
        try:
            img = Image.open(LOGO_PATH)
            i = 0
            while True:
                img.seek(i)
                frame = img.copy().resize((80, 80))
                frames.append(ImageTk.PhotoImage(frame))
                i += 1
        except EOFError:
            pass
        except Exception:
            frames = []

        if not frames:
            self.logo_label.config(text="[logo]")
            return

        self.logo_frames = frames
        self.logo_frame_index = 0
        self.logo_label.config(image=self.logo_frames[0])
        self.animate_small_logo()

    def animate_small_logo(self):
        if not self.logo_frames:
            return
        self.logo_frame_index = (self.logo_frame_index + 1) % len(self.logo_frames)
        self.logo_label.config(image=self.logo_frames[self.logo_frame_index])
        self.root.after(120, self.animate_small_logo)

    def build_gif_tab(self):
        frame = self.gif_frame
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        self.big_logo_label = ttk.Label(frame, text="[GIF]")
        # Center the GIF in the tab
        self.big_logo_label.grid(row=0, column=0, padx=10, pady=10, sticky="")
        self.setup_big_logo_animation()

    def setup_big_logo_animation(self):
        if not LOGO_PATH or not os.path.exists(LOGO_PATH):
            self.big_logo_label.config(text="[GIF]")
            return

        frames = []
        try:
            img = Image.open(LOGO_PATH)
            i = 0
            while True:
                img.seek(i)
                frame = img.copy()
                frames.append(ImageTk.PhotoImage(frame))
                i += 1
        except EOFError:
            pass
        except Exception:
            frames = []

        if not frames:
            self.big_logo_label.config(text="[GIF]")
            return

        self.big_logo_frames = frames
        self.big_logo_frame_index = 0
        self.big_logo_label.config(image=self.big_logo_frames[0])
        self.animate_big_logo()

    def animate_big_logo(self):
        if not self.big_logo_frames:
            return
        self.big_logo_frame_index = (self.big_logo_frame_index + 1) % len(
            self.big_logo_frames
        )
        self.big_logo_label.config(image=self.big_logo_frames[self.big_logo_frame_index])
        self.root.after(120, self.animate_big_logo)

    # ---------- Info Tab ----------

    def build_info_tab(self):
        frame = self.info_frame
        for i in range(2):
            frame.columnconfigure(i, weight=1)
        frame.rowconfigure(4, weight=1)

        title = ttk.Label(
            frame,
            text="MADGood Micro BTC Miner",
            font=("Helvetica", 16, "bold"),
        )
        title.grid(row=0, column=0, columnspan=2, sticky="w", pady=(10, 5), padx=10)

        version_label = ttk.Label(
            frame,
            text=f"Version: {APP_VERSION}",
            font=("Helvetica", 10),
        )
        version_label.grid(row=1, column=0, columnspan=2, sticky="w", padx=10)

        backend_label = ttk.Label(
            frame,
            text=f"Backend: cpuminer-opt\nPool: {POOL_HOST}:{POOL_PORT}",
            font=("Helvetica", 10),
            justify="left",
        )
        backend_label.grid(row=2, column=0, columnspan=2,
                           sticky="w", padx=10, pady=(5, 5))

        donation_label = ttk.Label(
            frame,
            text=f"Donation BTC Address:\n{DONATION_ADDRESS}",
            font=("Helvetica", 10, "italic"),
            justify="left",
        )
        donation_label.grid(row=3, column=0, columnspan=2,
                            sticky="w", padx=10, pady=(0, 10))

        ttk.Label(frame, text="Readme:").grid(row=4, column=0,
                                              sticky="nw", padx=10)

        self.readme_text = tk.Text(frame, height=15, width=70, wrap="word")
        self.readme_text.grid(
            row=4, column=0, columnspan=2, sticky="nsew", padx=10, pady=(0, 10)
        )
        self.readme_text.insert("1.0", load_readme_text())
        self.readme_text.config(state="disabled")

    # ---------- Mining Power ----------

    def change_power_mode(self):
        global power_mode
        power_mode = self.power_mode_var.get()
        self.status_var.set(
            f"Mining power set to: {power_mode.capitalize()} "
            f"({get_threads_for_power()} threads)"
        )

    # ---------- Alerts ----------

    def ding(self):
        try:
            self.root.bell()
        except Exception:
            pass

    def on_share_accepted_alert(self):
        self.ding()
        if "BLOCK FOUND" not in self.status_var.get():
            self.status_var.set("Share accepted by pool.")

    def on_block_found_alert(self):
        """
        Called when a block is reported as found in the log.
        Plays a sound and shows a flashing red banner.
        """
        self.ding()
        self.block_alert_var.set("BLOCK FOUND!")
        if not self.block_flash_active:
            self.block_flash_active = True
            self.flash_block_alert()

    def flash_block_alert(self):
        if not self.block_flash_active:
            self.block_alert_var.set("")
            return
        self.block_flash_on = not self.block_flash_on
        color = "red" if self.block_flash_on else "gray"
        self.block_alert_label.config(foreground=color)
        self.root.after(500, self.flash_block_alert)

    # ---------- Mining Control ----------

    def start_mining(self):
        global mining, wallet_address, hash_integrate_last, mining_start_time, current_job_id

        if mining:
            return

        if not os.path.exists(CPUMINER_PATH):
            self.status_var.set("ERROR: cpuminer not found in the miner/ folder.")
            return

        wallet_address = self.wallet_var.get().strip()
        if not wallet_address:
            self.status_var.set("ERROR: Wallet address is empty. Enter a BTC address first.")
            return

        threads = get_threads_for_power()
        cmd = [
            CPUMINER_PATH,
            "-a", "sha256d",
            "-o", f"stratum+tcp://{POOL_HOST}:{POOL_PORT}",
            "-u", wallet_address,
            "-p", "x",
            "-t", str(threads),
        ]

        try:
            self.miner_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except Exception as e:
            self.status_var.set(f"ERROR starting cpuminer: {e}")
            self.miner_proc = None
            return

        mining = True
        mining_start_time = time.time()
        hash_integrate_last = time.time()
        current_job_id = ""
        self.block_flash_active = False
        self.block_alert_var.set("")

        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.wallet_entry.config(state="disabled")
        self.status_var.set(f"cpuminer running on {threads} threads...")

        t = threading.Thread(
            target=self.miner_output_loop,
            args=(self.miner_proc,),
            daemon=True,
        )
        t.start()

    def stop_mining(self):
        global mining, mining_start_time, connected_to_pool, current_hashrate

        mining = False
        mining_start_time = None
        connected_to_pool = False
        current_hashrate = 0.0

        self.block_flash_active = False
        self.block_alert_var.set("")

        if self.miner_proc is not None:
            try:
                self.miner_proc.terminate()
                try:
                    self.miner_proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.miner_proc.kill()
            except Exception:
                pass
            self.miner_proc = None

        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.wallet_entry.config(state="normal")
        self.status_var.set("Stopped.")

    # ---------- Miner Output & Parsing ----------

    def miner_output_loop(self, proc):
        global current_hashrate, total_hashes, connected_to_pool
        global ckpool_user_id, mining, block_height, block_attempts, blocks_found, current_job_id

        for raw_line in proc.stdout:
            if raw_line is None:
                break

            line = raw_line.strip()
            if not line:
                continue

            lower = line.lower()

            # Save log
            with self.log_lock:
                self.log_lines.append(line)
                if len(self.log_lines) > 200:
                    self.log_lines = self.log_lines[-200:]

            # Connection status
            if "stratum connect" in lower:
                connected_to_pool = False
                self.status_var.set("Connecting to CKPool...")

            if (
                "stratum connection established" in lower
                or "new stratum diff" in lower
                or "new work" in lower
            ):
                connected_to_pool = True
                self.status_var.set("Connected to CKPool, mining...")

            if (
                "stratum authentication failed" in lower
                or "stratum connection failed" in lower
            ):
                connected_to_pool = False
                mining = False
                self.status_var.set("CKPool connection failed. Miner stopped.")
                try:
                    proc.terminate()
                except Exception:
                    pass
                self.thread_safe_update()
                break

            # Extranonce (used as pseudo user-id)
            if "stratum extranonce1" in lower:
                ex = parse_extranonce_from_line(line)
                if ex:
                    ckpool_user_id = ex

            # Job / block attempts
            if " job " in lower or "job " in line:
                jid = parse_job_from_line(line)
                if jid:
                    current_job_id = jid
                    block_attempts += 1

            # Block found
            if "block found" in lower or "yay!!!" in lower:
                blocks_found += 1
                self.status_var.set("BLOCK FOUND! Check CKPool / wallet.")
                self.root.after(0, self.on_block_found_alert)

            # Share accepted
            if "accepted" in lower and "block" not in lower and "yay" not in lower:
                self.root.after(0, self.on_share_accepted_alert)

            # Hashrate
            hr = parse_hashrate_from_line(line)
            if hr > 0:
                current_hashrate = hr

            # Block height from miner output (optional)
            bh = parse_block_height_from_line(line)
            if bh is not None and bh > 0:
                block_height = bh

            self.thread_safe_update()

        # Process ended
        proc.wait()
        if self.miner_proc is proc:
            self.miner_proc = None

        mining = False
        connected_to_pool = False
        current_hashrate = 0.0
        self.thread_safe_update()
        self.root.after(0, self.on_miner_exit)

    def on_miner_exit(self):
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.wallet_entry.config(state="normal")
        self.block_flash_active = False
        self.block_alert_var.set("")
        if not self.status_var.get().lower().startswith("error"):
            self.status_var.set("Miner exited.")

    # ---------- UI Refresh ----------

    def thread_safe_update(self):
        self.root.after(0, self.refresh_ui)

    def schedule_ui_refresh(self):
        self.refresh_ui()
        self.root.after(1000, self.schedule_ui_refresh)

    def refresh_ui(self):
        global total_hashes, hash_integrate_last, current_hashrate
        global mining_start_time, ckpool_user_id, block_attempts, blocks_found, current_job_id

        # Integrate hashrate over time into total_hashes
        now = time.time()
        if hash_integrate_last is not None:
            dt = now - hash_integrate_last
            if dt > 0 and current_hashrate > 0:
                total_hashes += current_hashrate * dt
        hash_integrate_last = now

        # Main lights
        self.conn_light.config(fg="green" if connected_to_pool else "red")
        self.mining_light.config(fg="green" if mining else "red")

        # Hashrate + totals
        self.hashrate_var.set(f"{current_hashrate:,.2f} H/s")
        self.total_hashes_var.set(f"{int(total_hashes):,}")

        # BTC price
        if btc_price_usd > 0:
            self.price_var.set(f"${btc_price_usd:,.2f}")
        else:
            self.price_var.set("…")

        # Block height
        self.block_var.set(str(block_height))

        # Uptime
        if mining_start_time is not None and mining:
            seconds = int(time.time() - mining_start_time)
            h, rem = divmod(seconds, 3600)
            m, s = divmod(rem, 60)
            if h > 0:
                self.uptime_var.set(f"{h}h {m}m {s}s")
            elif m > 0:
                self.uptime_var.set(f"{m}m {s}s")
            else:
                self.uptime_var.set(f"{s}s")
        else:
            self.uptime_var.set("0s")

        # Extras
        self.user_id_var.set(ckpool_user_id if ckpool_user_id else "-")
        self.job_id_var.set(current_job_id if current_job_id else "-")
        self.block_counter_var.set(f"Attempts: {block_attempts} / Found: {blocks_found}")

        # Log text
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", tk.END)
        with self.log_lock:
            tail = self.log_lines[-100:]
        if tail:
            self.log_text.insert(tk.END, "\n".join(tail))
        self.log_text.see(tk.END)
        self.log_text.config(state="disabled")

        # --- Compact UI update (if active) ---

        if self.compact_win is not None and self.compact_win.winfo_exists():
            if self.comp_uptime_label is not None:
                self.comp_uptime_label.config(text=f"Uptime: {self.uptime_var.get()}")
            if self.comp_hashrate_label is not None:
                self.comp_hashrate_label.config(text=f"Hashrate: {self.hashrate_var.get()}")
            if self.comp_attempts_label is not None:
                self.comp_attempts_label.config(
                    text=f"Attempts: {block_attempts} / Found: {blocks_found}"
                )
            if self.comp_conn_light is not None:
                self.comp_conn_light.config(fg="green" if connected_to_pool else "red")
            if self.comp_mining_light is not None:
                self.comp_mining_light.config(fg="green" if mining else "gray")
            if self.comp_status_label is not None:
                self.comp_status_label.config(text=f"Status: {self.status_var.get()}")

    # ---------- Compact Mode (with position memory) ----------

    def open_compact_mode(self):
        """
        Hide full window and open a small compact status window.

        Layout:
          [LOGO]   Uptime: XX
                   Hashrate: XX H/s
                   *Attempts / Found*

          [ Signals ]
          Connected  ●
          Mining     ●

          ------------------------------------------
          [ shaded status bar with full status text ]
                       [ Expand ]
        """
        if self.compact_win is not None and self.compact_win.winfo_exists():
            return  # already open

        # Hide full window
        self.root.withdraw()

        self.compact_win = tk.Toplevel(self.root)
        self.compact_win.title("MADGood Compact Miner")

        # Remember / restore position
        if self.compact_geometry:
            self.compact_win.geometry(self.compact_geometry)
        else:
            self.compact_win.geometry("450x165+100+100")

        self.compact_win.resizable(False, False)
        self.compact_win.protocol("WM_DELETE_WINDOW", self.close_compact_mode)

        bg = "#d9d9d9"
        self.compact_win.configure(bg=bg)

        # Main content row
        main = tk.Frame(self.compact_win, bg=bg, padx=10, pady=8)
        main.grid(row=0, column=0, sticky="nsew")
        self.compact_win.columnconfigure(0, weight=1)
        self.compact_win.rowconfigure(0, weight=1)

        # --- Logo on the left ------------------------------------------------
        if self.logo_frames:
            self.comp_logo_label = tk.Label(main, image=self.logo_frames[0], bg=bg)
        else:
            self.comp_logo_label = tk.Label(main, text="[logo]", bg=bg)
        self.comp_logo_label.grid(row=0, column=0, rowspan=3, sticky="w")

        # --- Uptime + Hashrate + attempts in the middle ---------------------
        metrics_frame = tk.Frame(main, bg=bg)
        metrics_frame.grid(row=0, column=1, rowspan=3, sticky="w", padx=(14, 18))

        self.comp_uptime_label = tk.Label(
            metrics_frame,
            text=f"Uptime: {self.uptime_var.get()}",
            bg=bg,
            font=("Helvetica", 10, "bold"),
        )
        self.comp_uptime_label.pack(anchor="w")

        self.comp_hashrate_label = tk.Label(
            metrics_frame,
            text=f"Hashrate: {self.hashrate_var.get()}",
            bg=bg,
            font=("Helvetica", 10),
        )
        self.comp_hashrate_label.pack(anchor="w")

        self.comp_attempts_label = tk.Label(
            metrics_frame,
            text=f"Attempts: {block_attempts} / Found: {blocks_found}",
            bg=bg,
            font=("Helvetica", 9, "italic"),
        )
        self.comp_attempts_label.pack(anchor="w")

        # --- Signals box on the right (lights + labels) ---------------------
        signals_frame = tk.LabelFrame(
            main,
            text="Signals",
            bg=bg,
            padx=8,
            pady=6,
            font=("Helvetica", 9, "bold"),
            labelanchor="n",
        )
        signals_frame.grid(row=0, column=2, rowspan=3, sticky="ne", padx=(18, 0))

        # Connected row
        conn_row = tk.Frame(signals_frame, bg=bg)
        conn_row.pack(anchor="w", fill="x", pady=2)
        tk.Label(conn_row, text="Connected", bg=bg, font=("Helvetica", 9)).pack(
            side="right"
        )
        self.comp_conn_light = tk.Label(
            conn_row, text="●", font=("Helvetica", 11), bg=bg
        )
        self.comp_conn_light.pack(side="left")

        # Mining row
        mine_row = tk.Frame(signals_frame, bg=bg)
        mine_row.pack(anchor="w", fill="x", pady=2)
        tk.Label(mine_row, text="Mining", bg=bg, font=("Helvetica", 9)).pack(
            side="right"
        )
        self.comp_mining_light = tk.Label(
            mine_row, text="●", font=("Helvetica", 11), bg=bg
        )
        self.comp_mining_light.pack(side="left")

        # --- Shaded status bar along the bottom -----------------------------
        self.comp_status_label = tk.Label(
            self.compact_win,
            text=f"Status: {self.status_var.get()}",
            anchor="w",
            bg="#ececec",
            fg="#333333",
            relief="sunken",
            padx=6,
            pady=2,
            font=("Helvetica", 9),
        )
        self.comp_status_label.grid(row=1, column=0, sticky="ew", padx=10, pady=(4, 0))

        # --- Expand button centered under everything ------------------------
        expand_btn = ttk.Button(
            self.compact_win, text="Expand", command=self.close_compact_mode
        )
        expand_btn.grid(row=2, column=0, pady=(6, 8))

    def close_compact_mode(self):
        """
        Close compact window, remember its position, and restore full UI.
        """
        if self.compact_win is not None and self.compact_win.winfo_exists():
            self.compact_geometry = self.compact_win.geometry()
            self.compact_win.destroy()
        self.compact_win = None
        self.root.deiconify()


# ---------------- ENTRY POINT ----------------

def main():
    root = tk.Tk()
    app = MadGoodMinerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

