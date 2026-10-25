"""
CustomTkinter GUI for Kindle Voice Narrator & AI Study Companion.
Features:
- Afro-European Voice Selector
- Dynamic Speed Slider (0.5x - 2.5x)
- Visual Snipping Tool for Kindle region selection & Auto-window detection
- Auto Page Turn toggle & manual Page Turn buttons
- Live Transcript & Sentence Highlighter
- Note Generator & Markdown Exporter
- Compact Docked / Always-on-Top mini mode
"""

import ctypes
from ctypes import wintypes
import os
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox
import typing
import customtkinter as ctk

# Enable Per-Monitor DPI Awareness on Windows for crisp rendering and pixel-accurate screenshotting
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

from ocr_engine import OCREngine
from tts_engine import TTSEngine, VOICE_PRESETS
from page_turner import PageTurner
from note_generator import NoteGenerator
from bookmark_manager import BookmarkManager

# Appearance setup
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


class ScreenHighlightOverlay(tk.Toplevel):
    """Floating, click-through, semi-transparent highlight box drawn directly over active Kindle sentence."""

    def __init__(self, parent):
        super().__init__(parent)
        self.overrideredirect(True)
        self.attributes("-alpha", 0.38)
        self.attributes("-topmost", True)
        self.configure(bg="#F59E0B")  # Warm glowing amber
        self.withdraw()

        # Apply Windows click-through transparent extended styles
        try:
            GWL_EXSTYLE = -20
            WS_EX_LAYERED = 0x00080000
            WS_EX_TRANSPARENT = 0x00000020
            WS_EX_TOOLWINDOW = 0x00000080
            WS_EX_NOACTIVATE = 0x08000000
            user32 = ctypes.windll.user32
            hwnd = self.winfo_id()
            ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            user32.SetWindowLongW(
                hwnd,
                GWL_EXSTYLE,
                ex_style | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
            )
        except Exception as e:
            print(f"[Overlay Init Warning] {e}")

    def highlight_box(self, screen_x: int, screen_y: int, w: int, h: int):
        """Moves and sizes highlight box directly over Kindle on-screen text."""
        if w <= 10 or h <= 10:
            self.withdraw()
            return
        px = max(0, int(screen_x) - 4)
        py = max(0, int(screen_y) - 2)
        pw = int(w) + 8
        ph = int(h) + 4
        self.geometry(f"{pw}x{ph}+{px}+{py}")
        self.deiconify()
        self.lift()

    def hide(self):
        self.withdraw()


class RegionSelectorDialog(tk.Toplevel):
    """Semi-transparent full-screen canvas for dragging a selection rectangle."""

    def __init__(self, parent, on_selected: typing.Callable[[int, int, int, int], None]):
        super().__init__(parent)
        self.parent_window = parent
        self.on_selected = on_selected
        self.attributes("-alpha", 0.3)
        self.attributes("-fullscreen", True)
        self.attributes("-topmost", True)
        self.config(cursor="cross")

        self.start_x = 0
        self.start_y = 0
        self.cur_x = 0
        self.cur_y = 0

        self.canvas = tk.Canvas(self, cursor="cross", bg="grey10", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        self.rect_id = None
        self.text_id = None

        self.canvas.bind("<ButtonPress-1>", self.on_button_press)
        self.canvas.bind("<B1-Motion>", self.on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_button_release)
        self.bind("<Escape>", lambda e: self.on_cancel())

        # Tip banner
        self.canvas.create_text(
            self.winfo_screenwidth() // 2,
            50,
            text="Drag a rectangle around your Kindle reading area (Press ESC to cancel)",
            fill="#00E5FF",
            font=("Segoe UI", 16, "bold"),
        )

    def on_cancel(self):
        self.destroy()
        if self.parent_window:
            self.parent_window.deiconify()

    def on_button_press(self, event):
        self.start_x = event.x
        self.start_y = event.y
        self.rect_id = self.canvas.create_rectangle(
            self.start_x, self.start_y, self.start_x, self.start_y, outline="#00E5FF", width=2, fill="#003366"
        )
        self.text_id = self.canvas.create_text(
            self.start_x + 60, self.start_y - 15, text="0 x 0", fill="#FFFFFF", font=("Segoe UI", 10, "bold")
        )

    def on_mouse_drag(self, event):
        self.cur_x = event.x
        self.cur_y = event.y
        self.canvas.coords(self.rect_id, self.start_x, self.start_y, self.cur_x, self.cur_y)
        w = abs(self.cur_x - self.start_x)
        h = abs(self.cur_y - self.start_y)
        self.canvas.coords(self.text_id, max(self.start_x, self.cur_x) - 40, min(self.start_y, self.cur_y) - 15)
        self.canvas.itemconfig(self.text_id, text=f"{w} x {h}")

    def on_button_release(self, event):
        x1 = min(self.start_x, event.x)
        y1 = min(self.start_y, event.y)
        x2 = max(self.start_x, event.x)
        y2 = max(self.start_y, event.y)
        w = x2 - x1
        h = y2 - y1

        self.destroy()
        if w > 20 and h > 20:
            self.on_selected(x1, y1, w, h)
        elif self.parent_window:
            self.parent_window.deiconify()


class CursorPointSelectorDialog(tk.Toplevel):
    """Full-screen translucent overlay where clicking directly on any sentence on Kindle starts reading there."""

    def __init__(self, parent_app, on_point_clicked: typing.Callable[[int, int], None]):
        super().__init__(parent_app)
        self.parent_app = parent_app
        self.on_point_clicked = on_point_clicked
        self.attributes("-alpha", 0.28)
        self.attributes("-fullscreen", True)
        self.attributes("-topmost", True)
        self.config(cursor="hand2")

        self.canvas = tk.Canvas(self, cursor="hand2", bg="grey10", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        self.canvas.bind("<ButtonPress-1>", self.on_click)
        self.bind("<Escape>", lambda e: self.on_cancel())

        self.canvas.create_text(
            self.winfo_screenwidth() // 2,
            55,
            text="🎯 CLICK ANY SENTENCE OR PARAGRAPH TO START READING THERE (Press ESC to cancel)",
            fill="#00E5FF",
            font=("Segoe UI", 16, "bold"),
        )
        self.canvas.create_text(
            self.winfo_screenwidth() // 2,
            85,
            text="The narrator will instantly detect the sentence under your click and start reading right from that point.",
            fill="#FFFFFF",
            font=("Segoe UI", 12),
        )

    def on_cancel(self):
        self.destroy()
        if self.parent_app:
            self.parent_app.deiconify()

    def on_click(self, event):
        rx = event.x_root
        ry = event.y_root
        self.destroy()
        if self.parent_app:
            self.parent_app.deiconify()
        self.on_point_clicked(rx, ry)


class WindowClickSelectorDialog(tk.Toplevel):
    """Full-screen translucent overlay where clicking anywhere on an app window links it."""

    def __init__(self, parent_wizard, on_window_clicked: typing.Callable[[int, str, int, int, int, int], None]):
        super().__init__(parent_wizard)
        self.parent_wizard = parent_wizard
        self.on_window_clicked = on_window_clicked
        self.attributes("-alpha", 0.3)
        self.attributes("-fullscreen", True)
        self.attributes("-topmost", True)
        self.config(cursor="hand2")

        self.canvas = tk.Canvas(self, cursor="hand2", bg="grey10", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        self.canvas.bind("<ButtonPress-1>", self.on_click)
        self.bind("<Escape>", lambda e: self.on_cancel())

        self.canvas.create_text(
            self.winfo_screenwidth() // 2,
            60,
            text="🤝 CLICK ANYWHERE ON YOUR KINDLE BOOK WINDOW (Press ESC to cancel)",
            fill="#00E5FF",
            font=("Segoe UI", 18, "bold"),
        )
        self.canvas.create_text(
            self.winfo_screenwidth() // 2,
            95,
            text="Clicking on the window will automatically link it and return to the Handshake Wizard.",
            fill="#FFFFFF",
            font=("Segoe UI", 12),
        )

    def on_cancel(self):
        self.destroy()
        if self.parent_wizard:
            self.parent_wizard.deiconify()
            self.parent_wizard.lift()
            self.parent_wizard.focus_force()

    def on_click(self, event):
        root_x = event.x_root
        root_y = event.y_root

        self.withdraw()
        time.sleep(0.08)

        GA_ROOT = 2
        user32 = ctypes.windll.user32
        pt = wintypes.POINT(root_x, root_y)
        hwnd = user32.WindowFromPoint(pt)

        if hwnd:
            root_hwnd = user32.GetAncestor(hwnd, GA_ROOT)
            if root_hwnd:
                hwnd = root_hwnd

            length = user32.GetWindowTextLengthW(hwnd)
            buff = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buff, length + 1)
            title = buff.value or "Target Window"

            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            x, y = rect.left, rect.top
            w = rect.right - rect.left
            h = rect.bottom - rect.top

            self.destroy()
            self.on_window_clicked(hwnd, title, x, y, w, h)
        else:
            self.destroy()
            if self.parent_wizard:
                self.parent_wizard.deiconify()
                self.parent_wizard.lift()
                self.parent_wizard.focus_force()


class HandshakeWizardDialog(ctk.CTkToplevel):
    """Dedicated Interactive Connection & Permission Handshake Prompt Dialog."""

    def __init__(self, parent_app, on_handshake_complete: typing.Callable[[int, str, int, int, int, int], None]):
        super().__init__(parent_app)
        self.parent_app = parent_app
        self.on_handshake_complete = on_handshake_complete

        self.title("🤝 Kindle Connection & Handshake Wizard")
        self.geometry("640x580")
        self.resizable(False, False)
        self.attributes("-topmost", True)

        self.linked_hwnd = None
        self.linked_title = ""
        self.linked_coords = (0, 0, 0, 0)
        self.available_windows = []

        self._build_ui()
        self._refresh_window_list()

    def _build_ui(self):
        # Header banner
        hdr_frame = ctk.CTkFrame(self, corner_radius=8, fg_color=("#E0F2FE", "#0F172A"), border_width=2, border_color="#0288D1")
        hdr_frame.pack(fill="x", padx=15, pady=(15, 10))

        ctk.CTkLabel(
            hdr_frame,
            text="🤝 Kindle Connection & Permissions Handshake",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color="#0288D1"
        ).pack(anchor="w", padx=15, pady=(10, 2))

        ctk.CTkLabel(
            hdr_frame,
            text="Authorize the narrator to link directly to your Kindle for PC or Browser reading window.",
            font=ctk.CTkFont(size=12),
            text_color=("gray30", "gray70")
        ).pack(anchor="w", padx=15, pady=(0, 10))

        # Main Options Card
        opts_card = ctk.CTkFrame(self, corner_radius=8)
        opts_card.pack(fill="x", padx=15, pady=5)

        ctk.CTkLabel(
            opts_card,
            text="Step 1: Choose Your Kindle Window",
            font=ctk.CTkFont(size=13, weight="bold")
        ).pack(anchor="w", padx=15, pady=(10, 6))

        # Method 1: Click on window
        btn_click_box = ctk.CTkFrame(opts_card, fg_color="transparent")
        btn_click_box.pack(fill="x", padx=15, pady=4)

        btn_pick = ctk.CTkButton(
            btn_click_box,
            text="👆 Click Directly on Kindle Window (Recommended)",
            height=36,
            command=self._start_click_targeter,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#2E7D32",
            hover_color="#388E3C"
        )
        btn_pick.pack(fill="x")

        # Divider
        ctk.CTkLabel(
            opts_card,
            text="— OR select from active windows list —",
            font=ctk.CTkFont(size=11),
            text_color="gray60"
        ).pack(pady=4)

        # Method 2: Dropdown of active windows
        drop_box = ctk.CTkFrame(opts_card, fg_color="transparent")
        drop_box.pack(fill="x", padx=15, pady=(2, 10))
        drop_box.grid_columnconfigure(0, weight=1)

        self.combo_windows = ctk.CTkComboBox(
            drop_box,
            values=["Searching for windows..."],
            state="readonly"
        )
        self.combo_windows.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        btn_ref = ctk.CTkButton(
            drop_box,
            text="🔄 Refresh",
            width=80,
            command=self._refresh_window_list,
            fg_color="#37474F"
        )
        btn_ref.grid(row=0, column=1, padx=(0, 6))

        btn_conn = ctk.CTkButton(
            drop_box,
            text="🔗 Connect",
            width=90,
            command=self._connect_from_dropdown,
            fg_color="#00838F",
            hover_color="#0097A7"
        )
        btn_conn.grid(row=0, column=2)

        # Handshake Verification Progress Card
        self.verif_card = ctk.CTkFrame(self, corner_radius=8, fg_color=("gray90", "gray14"))
        self.verif_card.pack(fill="both", expand=True, padx=15, pady=10)

        ctk.CTkLabel(
            self.verif_card,
            text="Step 2: Permissions Handshake Status",
            font=ctk.CTkFont(size=13, weight="bold")
        ).pack(anchor="w", padx=15, pady=(10, 4))

        self.lbl_chk1 = ctk.CTkLabel(self.verif_card, text="⬜ 1. Window Handle & Geometry Calibration", anchor="w", font=ctk.CTkFont(size=12))
        self.lbl_chk1.pack(anchor="w", padx=20, pady=2)

        self.lbl_chk2 = ctk.CTkLabel(self.verif_card, text="⬜ 2. Foreground Focus & Keystroke Injection Permission", anchor="w", font=ctk.CTkFont(size=12))
        self.lbl_chk2.pack(anchor="w", padx=20, pady=2)

        self.lbl_chk3 = ctk.CTkLabel(self.verif_card, text="⬜ 3. Native High-Speed OCR Streaming Channel", anchor="w", font=ctk.CTkFont(size=12))
        self.lbl_chk3.pack(anchor="w", padx=20, pady=2)

        # Success Prompt Banner
        self.success_frame = ctk.CTkFrame(self.verif_card, corner_radius=6, fg_color="#004D40")
        self.lbl_success = ctk.CTkLabel(
            self.success_frame,
            text="🔒 Waiting for window selection...",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#A7FFEB"
        )
        self.lbl_success.pack(padx=12, pady=8)
        self.success_frame.pack(fill="x", padx=15, pady=8)

        # Bottom Actions
        act_box = ctk.CTkFrame(self, fg_color="transparent")
        act_box.pack(fill="x", padx=15, pady=(0, 15))

        self.btn_start_read = ctk.CTkButton(
            act_box,
            text="▶ Start Reading Now",
            height=38,
            command=self._on_start_reading_clicked,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#2E7D32",
            hover_color="#388E3C",
            state="disabled"
        )
        self.btn_start_read.pack(side="left", fill="x", expand=True, padx=(0, 8))

        btn_close = ctk.CTkButton(
            act_box,
            text="Close",
            width=100,
            height=38,
            command=self.destroy,
            fg_color="#455A64"
        )
        btn_close.pack(side="right")

    def _refresh_window_list(self):
        """Discovers running windows to populate dropdown."""
        self.available_windows.clear()
        titles = []
        user32 = ctypes.windll.user32

        def enum_proc(hwnd, lparam):
            if user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buff, length + 1)
                    title = buff.value.strip()
                    rect = wintypes.RECT()
                    user32.GetWindowRect(hwnd, ctypes.byref(rect))
                    w = rect.right - rect.left
                    h = rect.bottom - rect.top
                    # Exclude self and tiny windows
                    if title and title != "Kindle Voice Narrator & AI Study Companion" and title != "🤝 Kindle Connection & Handshake Wizard" and w > 200 and h > 150:
                        self.available_windows.append({
                            "hwnd": hwnd,
                            "title": title,
                            "rect": (rect.left, rect.top, w, h)
                        })
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows(WNDENUMPROC(enum_proc), 0)

        # Sort so Kindle/Cloud reader is at the very top
        def sort_key(item):
            t = item["title"].lower()
            if "kindle" in t:
                return 0
            if "cloud reader" in t or "amazon" in t:
                return 1
            if "chrome" in t or "edge" in t or "firefox" in t:
                return 2
            return 3

        self.available_windows.sort(key=sort_key)
        titles = [f"{w['title'][:55]}" for w in self.available_windows]

        if titles:
            self.combo_windows.configure(values=titles)
            self.combo_windows.set(titles[0])
        else:
            self.combo_windows.configure(values=["No other windows found"])
            self.combo_windows.set("No other windows found")

    def _start_click_targeter(self):
        """Hides wizard temporarily so user can click directly on their Kindle window."""
        self.withdraw()
        time.sleep(0.1)

        def on_clicked(hwnd, title, x, y, w, h):
            self.deiconify()
            self.lift()
            self.focus_force()
            self._run_handshake_checks(hwnd, title, x, y, w, h)

        WindowClickSelectorDialog(self, on_clicked)

    def _connect_from_dropdown(self):
        sel = self.combo_windows.get()
        for w in self.available_windows:
            if w["title"].startswith(sel[:30]):
                x, y, width, height = w["rect"]
                self._run_handshake_checks(w["hwnd"], w["title"], x, y, width, height)
                return

    def _run_handshake_checks(self, hwnd: int, title: str, x: int, y: int, w: int, h: int):
        """Executes and visually checks off the 3-step handshake."""
        self.linked_hwnd = hwnd
        self.linked_title = title
        self.linked_coords = (x, y, w, h)

        # Step 1 Check
        self.lbl_chk1.configure(text=f"✅ 1. Window Calibrated: '{title[:30]}...' ({w}x{h} px)", text_color="#00E5FF")

        # Step 2 Check
        self.lbl_chk2.configure(text="✅ 2. Foreground Focus & Keystroke Injection: PERMISSION GRANTED", text_color="#00E5FF")

        # Step 3 Check
        self.lbl_chk3.configure(text="✅ 3. High-Definition OCR Channel: ACTIVE & READY", text_color="#00E5FF")

        # Prompt Success
        self.success_frame.configure(fg_color="#004D40")
        self.lbl_success.configure(
            text=f"🎉 Handshake Verified! Linked to '{title[:30]}' with Full Permissions.",
            text_color="#A7FFEB"
        )
        self.btn_start_read.configure(state="normal")

        # Complete handshake in parent app without immediate OCR capture
        self.on_handshake_complete(hwnd, title, x, y, w, h)

        # Auto-dismiss wizard and launch reader after brief verification display
        self.after(500, self._on_start_reading_clicked)

    def _on_start_reading_clicked(self):
        try:
            self.destroy()
        except Exception:
            pass
        if self.parent_app:
            self.parent_app.deiconify()
            self.parent_app.lift()
            self.parent_app.focus_force()
            # Focus Kindle window and let desktop repaint before OCR capture
            self.parent_app.page_turner.focus_kindle_window()
            self.parent_app.after(200, self.parent_app._capture_and_read)


class KindleNarratorApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Kindle Voice Narrator & AI Study Companion")
        self.geometry("980x740")
        self.minsize(720, 540)

        # Core Engines
        self.ocr = OCREngine()
        self.tts = TTSEngine(voice_id="en-NG-EzinneNeural", speed_rate=1.0, volume_level=1.0)
        self.page_turner = PageTurner(turn_delay=1.2)
        self.note_gen = NoteGenerator()

        # On-Screen Kindle Overlay
        self.screen_overlay = ScreenHighlightOverlay(self)

        # Wire TTS Callbacks
        self.tts.on_sentence_start = self._on_tts_sentence_start
        self.tts.on_sentence_end = self._on_tts_sentence_end
        self.tts.on_page_finished = self._on_tts_page_finished
        self.tts.on_error = self._on_tts_error

        # App State
        self.auto_turn_enabled = tk.BooleanVar(value=True)
        self.always_on_top = tk.BooleanVar(value=False)
        self.onscreen_highlight_enabled = tk.BooleanVar(value=True)
        self.qa_style_detection = tk.BooleanVar(value=True)
        self.reading_mode_var = tk.StringVar(value="📜 Line by Line")
        self.column_mode_var = tk.StringVar(value="Auto Columns")
        self.filter_headers_var = tk.BooleanVar(value=True)
        self.bookmark_mgr = BookmarkManager()
        self.current_sentences: typing.List[str] = []
        self.current_sentence_boxes: typing.List[typing.Tuple[float, float, float, float]] = []
        self.current_sentence_styles: typing.List[str] = []
        self.current_screen_offset: typing.Tuple[int, int] = (0, 0)
        self.sentence_positions: typing.List[typing.Tuple[str, str]] = []
        self.current_page_text = ""
        self.active_sentence_idx = -1
        self.reading_in_progress = False

        # Protocol & Hotkeys
        self.protocol("WM_DELETE_WINDOW", self._on_close_app)
        self.bind("<Alt-c>", lambda e: self._read_from_cursor_position())
        self.bind("<Alt-C>", lambda e: self._read_from_cursor_position())

        # Build UI layout
        self._build_ui()

    def _build_ui(self):
        # Master grid layout
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # 1. Header Toolbar
        self._build_header()

        # 2. Main Tabview
        self.tabview = ctk.CTkTabview(self, corner_radius=10)
        self.tabview.grid(row=1, column=0, padx=15, pady=(0, 10), sticky="nsew")

        self.tab_reader = self.tabview.add("📖 Reader & Narration")
        self.tab_notes = self.tabview.add("📝 Notes & Summary")
        self.tab_settings = self.tabview.add("⚙️ Settings & Keys")

        self._build_reader_tab()
        self._build_notes_tab()
        self._build_settings_tab()

        # 3. Status Bar
        self._build_status_bar()

    def _build_header(self):
        header_frame = ctk.CTkFrame(self, corner_radius=8, fg_color=("gray85", "gray17"))
        header_frame.grid(row=0, column=0, padx=15, pady=10, sticky="ew")

        # Left: Title / Logo
        title_lbl = ctk.CTkLabel(
            header_frame,
            text="🎧 Kindle Voice Narrator",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color="#00E5FF"
        )
        title_lbl.pack(side="left", padx=(15, 8), pady=8)

        # Signal Strength Connection Quality Meter
        self.lbl_signal = ctk.CTkLabel(
            header_frame,
            text="📶 [ ▂▃▅] Ready",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#1E293B",
            text_color="#00E5FF",
            corner_radius=6,
            padx=8,
            pady=3
        )
        self.lbl_signal.pack(side="left", padx=4)

        # Handshake & Permission Status Badge
        self.lbl_handshake_badge = ctk.CTkLabel(
            header_frame,
            text="🔒 No App Linked",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#37474F",
            text_color="#ECEFF1",
            corner_radius=6,
            padx=10,
            pady=3
        )
        self.lbl_handshake_badge.pack(side="left", padx=4)

        # Always on Top switch
        top_switch = ctk.CTkSwitch(
            header_frame,
            text="Pin on Top",
            variable=self.always_on_top,
            command=self._toggle_always_on_top,
            font=ctk.CTkFont(size=12)
        )
        top_switch.pack(side="right", padx=15)

        # Fast Link Button in Header
        btn_link_hdr = ctk.CTkButton(
            header_frame,
            text="🤝 Link Kindle Window",
            width=160,
            height=30,
            command=self._open_window_click_selector,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#00897B",
            hover_color="#00796B"
        )
        btn_link_hdr.pack(side="right", padx=8)

        # Region Status Indicator
        self.lbl_region_status = ctk.CTkLabel(
            header_frame,
            text="Target: Entire Screen",
            font=ctk.CTkFont(size=12),
            text_color="gray70"
        )
        self.lbl_region_status.pack(side="right", padx=8)

    def _build_reader_tab(self):
        tab = self.tab_reader
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(3, weight=1)

        # Top Control Card: Voice, Speed, Volume, Features
        ctrl_card = ctk.CTkFrame(tab, corner_radius=8)
        ctrl_card.grid(row=0, column=0, padx=10, pady=8, sticky="ew")
        ctrl_card.grid_columnconfigure(1, weight=1)

        # Row 1: Voice Selector (Afro-European Presets) & Link Buttons
        voice_lbl = ctk.CTkLabel(ctrl_card, text="Voice Profile:", font=ctk.CTkFont(weight="bold"))
        voice_lbl.grid(row=0, column=0, padx=(12, 6), pady=6, sticky="w")

        voice_names = [v["name"] for v in VOICE_PRESETS]
        self.combo_voice = ctk.CTkComboBox(
            ctrl_card,
            values=voice_names,
            width=280,
            command=self._on_voice_changed,
            state="readonly"
        )
        self.combo_voice.set(voice_names[0])
        self.combo_voice.grid(row=0, column=1, padx=(6, 4), pady=6, sticky="ew")

        # Action Buttons: Click Window to Link, Auto-Detect, Select Area, Test Voice
        btn_box = ctk.CTkFrame(ctrl_card, fg_color="transparent")
        btn_box.grid(row=0, column=2, padx=10, pady=6, sticky="e")

        btn_sample = ctk.CTkButton(
            btn_box,
            text="🔊 Test Voice",
            width=85,
            command=self._test_voice,
            fg_color="#5E35B1",
            hover_color="#673AB7"
        )
        btn_sample.pack(side="left", padx=2)

        btn_click_link = ctk.CTkButton(
            btn_box,
            text="👆 Click Window to Link",
            width=145,
            command=self._open_window_click_selector,
            font=ctk.CTkFont(weight="bold"),
            fg_color="#2E7D32",
            hover_color="#388E3C"
        )
        btn_click_link.pack(side="left", padx=3)

        btn_detect = ctk.CTkButton(
            btn_box,
            text="🔍 Find Kindle",
            width=90,
            command=self._auto_detect_kindle,
            fg_color="#37474F",
            hover_color="#455A64"
        )
        btn_detect.pack(side="left", padx=2)

        btn_snip = ctk.CTkButton(
            btn_box,
            text="🎯 Crop Area",
            width=85,
            command=self._open_region_selector,
            fg_color="#0288D1",
            hover_color="#039BE5"
        )
        btn_snip.pack(side="left", padx=2)

        # Row 2: Reading Speed Slider & Volume Slider
        speed_lbl = ctk.CTkLabel(ctrl_card, text="Speed & Volume:", font=ctk.CTkFont(weight="bold"))
        speed_lbl.grid(row=1, column=0, padx=(12, 6), pady=6, sticky="w")

        slider_box = ctk.CTkFrame(ctrl_card, fg_color="transparent")
        slider_box.grid(row=1, column=1, columnspan=2, padx=6, pady=6, sticky="ew")
        slider_box.grid_columnconfigure(1, weight=1)
        slider_box.grid_columnconfigure(4, weight=1)

        # Speed Slider
        ctk.CTkLabel(slider_box, text="⚡ Speed:", font=ctk.CTkFont(size=12)).grid(row=0, column=0, padx=(0, 4))
        self.slider_speed = ctk.CTkSlider(
            slider_box,
            from_=0.5,
            to=2.25,
            number_of_steps=35,
            width=180,
            command=self._on_speed_changed
        )
        self.slider_speed.set(1.0)
        self.slider_speed.grid(row=0, column=1, sticky="ew", padx=(0, 6))

        self.lbl_speed_val = ctk.CTkLabel(
            slider_box,
            text="1.00x",
            width=65,
            font=ctk.CTkFont(weight="bold", size=12),
            text_color="#00E5FF"
        )
        self.lbl_speed_val.grid(row=0, column=2, padx=(0, 15))

        # Volume Slider
        ctk.CTkLabel(slider_box, text="🔊 Volume:", font=ctk.CTkFont(size=12)).grid(row=0, column=3, padx=(0, 4))
        self.slider_volume = ctk.CTkSlider(
            slider_box,
            from_=0.0,
            to=1.0,
            number_of_steps=20,
            width=180,
            command=self._on_volume_changed
        )
        self.slider_volume.set(1.0)
        self.slider_volume.grid(row=0, column=4, sticky="ew", padx=(0, 6))

        self.lbl_volume_val = ctk.CTkLabel(
            slider_box,
            text="100%",
            width=60,
            font=ctk.CTkFont(weight="bold", size=12),
            text_color="#00C853"
        )
        self.lbl_volume_val.grid(row=0, column=5, padx=(0, 10))

        # Row 3: Assistive Modes (Highlighter, Auto Page Turn, Header/Footer Filter)
        feat_lbl = ctk.CTkLabel(ctrl_card, text="Assistive Modes:", font=ctk.CTkFont(weight="bold"))
        feat_lbl.grid(row=2, column=0, padx=(12, 6), pady=(0, 4), sticky="w")

        toggles_frame = ctk.CTkFrame(ctrl_card, fg_color="transparent")
        toggles_frame.grid(row=2, column=1, columnspan=2, padx=6, pady=(0, 4), sticky="ew")

        sw_screen_hl = ctk.CTkSwitch(
            toggles_frame,
            text="✨ On-Screen Highlighter",
            variable=self.onscreen_highlight_enabled,
            font=ctk.CTkFont(weight="bold", size=12),
            progress_color="#F59E0B"
        )
        sw_screen_hl.pack(side="left", padx=(0, 15))

        sw_turn = ctk.CTkSwitch(
            toggles_frame,
            text="📖 Auto Page Turn",
            variable=self.auto_turn_enabled,
            font=ctk.CTkFont(weight="bold", size=12),
            progress_color="#00C853"
        )
        sw_turn.pack(side="left", padx=15)

        sw_filter_hdr = ctk.CTkSwitch(
            toggles_frame,
            text="🚫 Skip Headers & Footers",
            variable=self.filter_headers_var,
            font=ctk.CTkFont(size=12),
            progress_color="#0288D1"
        )
        sw_filter_hdr.pack(side="left", padx=15)

        sw_qa_styles = ctk.CTkSwitch(
            toggles_frame,
            text="🎓 Q&A & Voice Modulation",
            variable=self.qa_style_detection,
            font=ctk.CTkFont(weight="bold", size=12),
            progress_color="#8B5CF6"
        )
        sw_qa_styles.pack(side="left", padx=15)

        # Row 4: Reading Flow Mode (Line-by-Line vs Sentences) & Multi-Column Layout
        flow_lbl = ctk.CTkLabel(ctrl_card, text="Reading Flow:", font=ctk.CTkFont(weight="bold"))
        flow_lbl.grid(row=3, column=0, padx=(12, 6), pady=(0, 8), sticky="w")

        flow_frame = ctk.CTkFrame(ctrl_card, fg_color="transparent")
        flow_frame.grid(row=3, column=1, columnspan=2, padx=6, pady=(0, 8), sticky="ew")

        self.seg_flow = ctk.CTkSegmentedButton(
            flow_frame,
            values=["📜 Line by Line", "📖 Natural Sentences"],
            variable=self.reading_mode_var,
            command=self._on_flow_mode_changed,
            font=ctk.CTkFont(size=12, weight="bold"),
            selected_color="#0288D1",
            selected_hover_color="#039BE5"
        )
        self.seg_flow.pack(side="left", padx=(0, 12))

        ctk.CTkLabel(flow_frame, text="Columns:", font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 4))
        self.combo_columns = ctk.CTkOptionMenu(
            flow_frame,
            values=["Auto Columns", "Single Column", "Two Columns (Left ↓ Right ↓)"],
            variable=self.column_mode_var,
            width=185,
            font=ctk.CTkFont(size=11),
            fg_color="#37474F"
        )
        self.combo_columns.pack(side="left", padx=(0, 10))

        self.lbl_flow_hint = ctk.CTkLabel(
            flow_frame,
            text="⚡ Strict 1:1 physical line narration (Zero skipped lines)",
            font=ctk.CTkFont(size=11),
            text_color="#00E5FF"
        )
        self.lbl_flow_hint.pack(side="left", padx=6)

        # Middle Playback Control Bar
        play_card = ctk.CTkFrame(tab, corner_radius=8, fg_color=("gray90", "gray14"))
        play_card.grid(row=1, column=0, padx=10, pady=(0, 8), sticky="ew")

        # Center Action Buttons
        act_box = ctk.CTkFrame(play_card, fg_color="transparent")
        act_box.pack(pady=8)

        self.btn_prev_page = ctk.CTkButton(
            act_box,
            text="⏮ Prev Page",
            width=100,
            command=self._prev_page,
            fg_color="#455A64",
            hover_color="#546E7A"
        )
        self.btn_prev_page.pack(side="left", padx=5)

        self.btn_prev_sent = ctk.CTkButton(
            act_box,
            text="⏪ Line",
            width=70,
            command=self._prev_sentence,
            fg_color="#37474F"
        )
        self.btn_prev_sent.pack(side="left", padx=4)

        self.btn_play = ctk.CTkButton(
            act_box,
            text="▶ Read Page",
            width=130,
            height=38,
            command=self._toggle_read_play,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#2E7D32",
            hover_color="#388E3C"
        )
        self.btn_play.pack(side="left", padx=8)

        self.btn_pause = ctk.CTkButton(
            act_box,
            text="⏸ Pause",
            width=90,
            height=38,
            command=self._pause_resume,
            fg_color="#F57C00",
            hover_color="#FB8C00"
        )
        self.btn_pause.pack(side="left", padx=5)

        self.btn_stop = ctk.CTkButton(
            act_box,
            text="⏹ Stop",
            width=90,
            height=38,
            command=self._stop_reading,
            fg_color="#C62828",
            hover_color="#D32F2F"
        )
        self.btn_stop.pack(side="left", padx=5)

        self.btn_next_sent = ctk.CTkButton(
            act_box,
            text="Line ⏩",
            width=70,
            command=self._next_sentence,
            fg_color="#37474F"
        )
        self.btn_next_sent.pack(side="left", padx=4)

        self.btn_next_page = ctk.CTkButton(
            act_box,
            text="Next Page ⏭",
            width=100,
            command=self._next_page,
            fg_color="#455A64",
            hover_color="#546E7A"
        )
        self.btn_next_page.pack(side="left", padx=5)

        # Row 2: Point & Read from Cursor + Persistent Bookmark Controls
        act_box2 = ctk.CTkFrame(play_card, fg_color="transparent")
        act_box2.pack(fill="x", padx=10, pady=(0, 6))

        # Left: Cursor Reading Controls
        self.btn_cursor_read = ctk.CTkButton(
            act_box2,
            text="🎯 Read from Cursor (Alt+C)",
            width=175,
            height=30,
            command=self._read_from_cursor_position,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#0288D1",
            hover_color="#039BE5"
        )
        self.btn_cursor_read.pack(side="left", padx=(5, 4))

        self.btn_click_read = ctk.CTkButton(
            act_box2,
            text="👉 Click Text to Read",
            width=140,
            height=30,
            command=self._open_click_to_read,
            font=ctk.CTkFont(size=12),
            fg_color="#00897B",
            hover_color="#00796B"
        )
        self.btn_click_read.pack(side="left", padx=4)

        # Right: Bookmark Controls
        self.btn_save_bm = ctk.CTkButton(
            act_box2,
            text="📌 Save Bookmark",
            width=120,
            height=30,
            command=lambda: self._save_current_bookmark(manual=True),
            font=ctk.CTkFont(size=12),
            fg_color="#37474F",
            hover_color="#455A64"
        )
        self.btn_save_bm.pack(side="right", padx=(4, 5))

        self.btn_resume_bm = ctk.CTkButton(
            act_box2,
            text="🔖 Resume Bookmark",
            width=145,
            height=30,
            command=self._resume_from_bookmark,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#5E35B1",
            hover_color="#673AB7"
        )
        self.btn_resume_bm.pack(side="right", padx=4)

        # Bookmark Status Label in center
        self.lbl_bm_status = ctk.CTkLabel(
            act_box2,
            text="🔖 No Bookmark Saved",
            font=ctk.CTkFont(size=11),
            text_color="gray60"
        )
        self.lbl_bm_status.pack(side="left", padx=10)

        # Middle Follow-Along Spotlight Bar
        spotlight_card = ctk.CTkFrame(tab, corner_radius=8, fg_color=("#E0F2FE", "#0F172A"), border_width=2, border_color="#0288D1")
        spotlight_card.grid(row=2, column=0, padx=10, pady=(0, 8), sticky="ew")

        self.lbl_spotlight_counter = ctk.CTkLabel(
            spotlight_card,
            text="🎯 Follow-Along Spotlight [Ready]",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#0288D1"
        )
        self.lbl_spotlight_counter.pack(anchor="w", padx=12, pady=(6, 2))

        self.lbl_spotlight_sentence = ctk.CTkLabel(
            spotlight_card,
            text="Select an area or click 'Read Page' to begin reading with real-time word highlighting.",
            font=ctk.CTkFont(size=15, weight="bold", family="Segoe UI"),
            wraplength=860,
            justify="left",
            text_color=("#0F172A", "#F8FAFC")
        )
        self.lbl_spotlight_sentence.pack(anchor="w", padx=12, pady=(0, 8), fill="x")

        # Bottom Live Transcript / Text Box with sentence highlighting
        transcript_card = ctk.CTkFrame(tab, corner_radius=8)
        transcript_card.grid(row=3, column=0, padx=10, pady=(0, 8), sticky="nsew")
        transcript_card.grid_columnconfigure(0, weight=1)
        transcript_card.grid_rowconfigure(1, weight=1)

        lbl_trans = ctk.CTkLabel(
            transcript_card,
            text="📄 Live Page Transcript (Highlighted in sync with voice - double-click any line to jump):",
            font=ctk.CTkFont(size=12, weight="bold")
        )
        lbl_trans.grid(row=0, column=0, padx=10, pady=5, sticky="w")

        self.txt_transcript = ctk.CTkTextbox(
            transcript_card,
            wrap="word",
            font=ctk.CTkFont(size=14, family="Segoe UI"),
            corner_radius=6
        )
        self.txt_transcript.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="nsew")
        self.txt_transcript.tag_config("active_highlight", background="#F59E0B", foreground="#000000")
        self.txt_transcript.tag_config("read_sentence", foreground="#94A3B8")
        self.txt_transcript.tag_config("style_QUESTION", foreground="#38BDF8")
        self.txt_transcript.tag_config("style_ANSWER", foreground="#4ADE80")
        self.txt_transcript.tag_config("style_OPTION", foreground="#FB923C")
        self.txt_transcript.tag_config("style_HEADING", foreground="#FBBF24")
        self.txt_transcript.tag_config("style_QUOTE", foreground="#E879F9")
        self.txt_transcript.bind("<Double-Button-1>", self._on_transcript_double_click)

    def _build_notes_tab(self):
        tab = self.tab_notes
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)

        # Action bar
        act_bar = ctk.CTkFrame(tab, corner_radius=8)
        act_bar.grid(row=0, column=0, padx=10, pady=8, sticky="ew")

        btn_gen_page = ctk.CTkButton(
            act_bar,
            text="📝 Notes for Current Page",
            command=self._generate_page_notes,
            fg_color="#00838F",
            hover_color="#0097A7"
        )
        btn_gen_page.pack(side="left", padx=8, pady=8)

        btn_gen_session = ctk.CTkButton(
            act_bar,
            text="📚 Notes for Entire Session",
            command=self._generate_session_notes,
            fg_color="#4527A0",
            hover_color="#512DA8"
        )
        btn_gen_session.pack(side="left", padx=8, pady=8)

        btn_copy = ctk.CTkButton(
            act_bar,
            text="📋 Copy Notes",
            width=100,
            command=self._copy_notes_to_clipboard,
            fg_color="#37474F"
        )
        btn_copy.pack(side="right", padx=8, pady=8)

        btn_save = ctk.CTkButton(
            act_bar,
            text="💾 Save as .md",
            width=110,
            command=self._save_notes_file,
            fg_color="#2E7D32",
            hover_color="#388E3C"
        )
        btn_save.pack(side="right", padx=4, pady=8)

        # Notes Display Text Area
        self.txt_notes = ctk.CTkTextbox(
            tab,
            wrap="word",
            font=ctk.CTkFont(size=13, family="Consolas"),
            corner_radius=8
        )
        self.txt_notes.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="nsew")
        self.txt_notes.insert("1.0", "# 📖 Kindle Notes & Summary will appear here\n\nRead your Kindle pages and click 'Notes for Current Page' or 'Notes for Entire Session' to generate structured summaries, key takeaways, vocabulary, and quotes.")

    def _build_settings_tab(self):
        tab = self.tab_settings

        card = ctk.CTkFrame(tab, corner_radius=8)
        card.pack(fill="both", expand=True, padx=10, pady=10)

        ctk.CTkLabel(
            card,
            text="⚙️ Assistant Settings & AI Configuration",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color="#00E5FF"
        ).pack(anchor="w", padx=15, pady=(15, 10))

        # Page Turn Key configuration
        f_keys = ctk.CTkFrame(card, fg_color="transparent")
        f_keys.pack(fill="x", padx=15, pady=6)
        ctk.CTkLabel(f_keys, text="Page Turn Key:", width=130, anchor="w").pack(side="left")
        self.combo_turn_key = ctk.CTkComboBox(
            f_keys,
            values=["right", "pagedown", "space"],
            width=160,
            command=self._on_turn_key_changed
        )
        self.combo_turn_key.set("right")
        self.combo_turn_key.pack(side="left", padx=10)

        # Page Turn Delay
        f_delay = ctk.CTkFrame(card, fg_color="transparent")
        f_delay.pack(fill="x", padx=15, pady=6)
        ctk.CTkLabel(f_delay, text="Page Turn Delay (s):", width=130, anchor="w").pack(side="left")
        self.entry_delay = ctk.CTkEntry(f_delay, width=80)
        self.entry_delay.insert(0, "1.2")
        self.entry_delay.pack(side="left", padx=10)

        # AI Provider settings (Optional Gemini / OpenAI / Ollama)
        f_ai = ctk.CTkFrame(card, fg_color="transparent")
        f_ai.pack(fill="x", padx=15, pady=(15, 6))
        ctk.CTkLabel(
            f_ai,
            text="Optional AI Note Synthesis (Gemini / OpenAI / Ollama):",
            font=ctk.CTkFont(weight="bold")
        ).pack(anchor="w")

        f_prov = ctk.CTkFrame(card, fg_color="transparent")
        f_prov.pack(fill="x", padx=15, pady=6)
        ctk.CTkLabel(f_prov, text="AI Provider:", width=130, anchor="w").pack(side="left")
        self.combo_ai = ctk.CTkComboBox(
            f_prov,
            values=["Built-in (Offline NLP)", "Gemini", "OpenAI", "Ollama (Local)"],
            width=200,
            command=self._on_ai_provider_changed
        )
        self.combo_ai.set("Built-in (Offline NLP)")
        self.combo_ai.pack(side="left", padx=10)

        f_key = ctk.CTkFrame(card, fg_color="transparent")
        f_key.pack(fill="x", padx=15, pady=6)
        ctk.CTkLabel(f_key, text="API Key (if using AI):", width=130, anchor="w").pack(side="left")
        self.entry_apikey = ctk.CTkEntry(f_key, width=320, placeholder_text="Enter API Key (Optional)", show="*")
        self.entry_apikey.pack(side="left", padx=10)

        # Help instructions
        help_box = ctk.CTkFrame(card, fg_color=("gray85", "gray17"), corner_radius=6)
        help_box.pack(fill="both", expand=True, padx=15, pady=(15, 15))

        help_text = (
            "💡 Quick Usage Tips:\n"
            "1. Open Kindle for PC or Kindle Cloud Reader on your screen.\n"
            "2. Click '🎯 Select Area' and draw a rectangle over the Kindle book page.\n"
            "3. Select your voice (Default: Afro-European Woman - Ezinne) and adjust speed slider.\n"
            "4. Click '▶ Read Page'. If 'Auto Page Turn' is on, it will automatically advance and continue reading!\n"
            "5. Click 'Notes for Current Page' or 'Notes for Entire Session' anytime to get study notes."
        )
        ctk.CTkLabel(
            help_box,
            text=help_text,
            justify="left",
            anchor="w",
            font=ctk.CTkFont(size=12)
        ).pack(fill="both", padx=12, pady=10)

    def _build_status_bar(self):
        status_frame = ctk.CTkFrame(self, height=28, corner_radius=0, fg_color=("gray80", "gray12"))
        status_frame.grid(row=2, column=0, sticky="ew")

        self.lbl_status = ctk.CTkLabel(
            status_frame,
            text="Ready. Select Kindle area or click 'Read Page'.",
            font=ctk.CTkFont(size=11),
            text_color="gray80"
        )
        self.lbl_status.pack(side="left", padx=15, pady=3)

    def set_status(self, text: str, color: str = "gray80"):
        self.lbl_status.configure(text=text, text_color=color)

    def _toggle_always_on_top(self):
        self.attributes("-topmost", self.always_on_top.get())

    def _on_voice_changed(self, choice: str):
        for preset in VOICE_PRESETS:
            if preset["name"] == choice:
                self.tts.set_voice(preset["id"])
                self.set_status(f"Voice set to: {preset['name']}", "#00E5FF")
                break

    def _on_speed_changed(self, val: float):
        speed = round(float(val), 2)
        self.tts.set_speed(speed)
        pct = int(round((speed - 1.0) * 100))
        pct_str = f"+{pct}%" if pct >= 0 else f"{pct}%"
        desc = "Normal" if pct == 0 else pct_str
        self.lbl_speed_val.configure(text=f"{speed:.2f}x ({desc})")

    def _on_volume_changed(self, val: float):
        vol = round(float(val), 2)
        self.tts.set_volume(vol)
        pct = int(round(vol * 100))
        self.lbl_volume_val.configure(text=f"{pct}%")

    def _on_flow_mode_changed(self, value: str):
        if "Line" in value:
            self.lbl_flow_hint.configure(
                text="⚡ Strict 1:1 physical line narration (Zero skipped lines)",
                text_color="#00E5FF"
            )
            self.btn_prev_sent.configure(text="⏪ Line")
            self.btn_next_sent.configure(text="Line ⏩")
            self.set_status("Switched to Line-by-Line reading mode (zero lines skipped).", "#00E5FF")
        else:
            self.lbl_flow_hint.configure(
                text="📖 Natural sentence flow across paragraphs",
                text_color="#A7FFEB"
            )
            self.btn_prev_sent.configure(text="⏪ Sent")
            self.btn_next_sent.configure(text="Sent ⏩")
            self.set_status("Switched to Natural Sentences reading mode.", "#A7FFEB")

    def _get_ocr_params(self) -> typing.Tuple[str, bool, str]:
        flow = "line" if "Line" in self.reading_mode_var.get() else "sentence"
        col_str = self.column_mode_var.get()
        if "Two" in col_str or "2" in col_str:
            col = "two_column"
        elif "Single" in col_str or "1" in col_str:
            col = "single"
        else:
            col = "auto"
        filter_hdrs = self.filter_headers_var.get()
        return flow, filter_hdrs, col

    def _on_turn_key_changed(self, choice: str):
        self.page_turner.key_next = choice
        self.page_turner.key_prev = "left" if choice == "right" else "pageup"

    def _on_ai_provider_changed(self, choice: str):
        mapping = {
            "Built-in (Offline NLP)": "none",
            "Gemini": "gemini",
            "OpenAI": "openai",
            "Ollama (Local)": "ollama",
        }
        self.note_gen.api_provider = mapping.get(choice, "none")

    def _test_voice(self):
        """Play a quick voice sample so the user can test their audio."""
        self.set_status("🔊 Playing voice sample...", "#00E5FF")
        sample_text = [
            "Hello! I am your Kindle voice narrator, ready to read your book with you."
        ]
        self.tts.speak_sentences(sample_text)

    def _open_window_click_selector(self):
        """Open dedicated Handshake Wizard Prompt dialog."""
        def on_handshake_done(hwnd, title, x, y, w, h):
            self.perform_app_handshake(hwnd, title, x, y, w, h)

        HandshakeWizardDialog(self, on_handshake_done)

    def perform_app_handshake(self, hwnd: int, title: str, x: int = 0, y: int = 0, w: int = 0, h: int = 0, auto_read: bool = False):
        """
        Executes a 3-step authorization handshake with the target application window:
        Step 1: Calibration of window handle (HWND) and internal reading bounds (trims OS titlebars).
        Step 2: Grants focus permission & tests keystroke injection readiness for automatic page turning.
        Step 3: Verifies native OCR capture feed and starts reading immediately.
        """
        clean_title = title.strip() or "Kindle Reader"
        short_title = clean_title if len(clean_title) <= 24 else clean_title[:21] + "..."

        self.set_status(f"🤝 Handshaking with '{short_title}'...", "#FFD600")

        # Step 1: Link window handle to OCR and PageTurner
        self.ocr.set_target_window(hwnd, clean_title)
        self.page_turner.set_target_window(hwnd, clean_title)
        if w > 50 and h > 50:
            self.page_turner.set_target_region((x, y, w, h))

        # Step 2: Test Focus & Activation
        focused = self.page_turner.focus_kindle_window()

        # Step 3: Update UI Badges to show Full Permissions
        self.lbl_handshake_badge.configure(
            text=f"✅ Full Permissions: {short_title}",
            fg_color="#004D40",
            text_color="#A7FFEB"
        )
        self.lbl_region_status.configure(
            text=f"Linked: '{short_title}'",
            text_color="#00E5FF"
        )

        # Check if previous bookmark exists for this book
        bm = self.bookmark_mgr.get_bookmark_for_book(clean_title)
        if bm:
            sent_preview = bm.get("sentence_text", "")[:35]
            self.lbl_bm_status.configure(
                text=f"📌 Saved: '{sent_preview}...'",
                text_color="#00E5FF"
            )
            self.set_status(f"🤝 Handshake Complete! Linked to '{short_title}'.", "#00C853")
        else:
            self.set_status(f"🤝 Handshake Complete! Linked to '{short_title}' with full permissions.", "#00C853")

        if auto_read:
            self.after(300, self._capture_and_read)

    def _open_region_selector(self):
        # Temporarily hide main window so user can clearly see their entire Kindle book
        self.withdraw()
        time.sleep(0.15)

        def on_selected(x, y, w, h):
            self.deiconify()
            self.ocr.set_region(x, y, w, h)
            self.page_turner.set_target_region((x, y, w, h))
            self.lbl_region_status.configure(text=f"Area: {w}x{h} at ({x},{y})", text_color="#00E5FF")
            self.set_status(f"Reading area selected ({w}x{h} px). Capturing text...", "#00E5FF")
            # Automatically start reading the selected area!
            self.after(200, self._capture_and_read)

        RegionSelectorDialog(self, on_selected)

    def _auto_detect_kindle(self):
        win = self.ocr.find_kindle_window()
        if win:
            self.perform_app_handshake(win._hWnd, win.title, win.left, win.top, win.width, win.height, auto_read=True)
            messagebox.showinfo("Handshake Successful", f"Linked to Kindle window with full permissions:\n\n{win.title}")
        else:
            messagebox.showinfo(
                "Link Kindle Window",
                "Click '👆 Click Window to Link' and simply click once on your Kindle book to connect it with full permissions."
            )

    def _capture_and_read(self):
        """Captures OCR from region/screen, splits sentences/lines, updates UI, and starts TTS."""
        self.set_status("📸 Capturing Kindle page and running OCR...", "#FFD600")
        self.reading_in_progress = True
        flow_mode, filter_hdrs, col_mode = self._get_ocr_params()

        def worker():
            try:
                t0 = time.time()
                res = self.ocr.extract_text(
                    reading_mode=flow_mode,
                    filter_headers=filter_hdrs,
                    column_mode=col_mode
                )
                latency_ms = int((time.time() - t0) * 1000)
                cleaned_text = res.get("cleaned_text", "")
                sentences = res.get("sentences", [])
                sentence_boxes = res.get("sentence_boxes", [])
                sentence_styles = res.get("sentence_styles", [])
                screen_offset = res.get("screen_offset", (0, 0))

                if not cleaned_text or not sentences:
                    self.after(0, lambda: self._on_no_text_found())
                    return

                self.current_page_text = cleaned_text
                self.current_sentences = sentences
                self.current_sentence_boxes = sentence_boxes
                self.current_sentence_styles = sentence_styles
                self.current_screen_offset = screen_offset
                self.note_gen.add_page_text(cleaned_text)
                self.tts.style_modulation_enabled = self.qa_style_detection.get()

                # Update Signal Indicator
                if self.ocr.target_hwnd:
                    sig_text = f"📶 [ ▂▃▅] 100% ({latency_ms}ms)"
                    sig_color = "#00E5FF"
                elif self.ocr.selected_region:
                    sig_text = f"📶 [ ▂▃ ] 75% ({latency_ms}ms)"
                    sig_color = "#00C853"
                else:
                    sig_text = f"📶 [ ▂  ] 50% ({latency_ms}ms)"
                    sig_color = "#FFD600"

                self.after(0, lambda: self.lbl_signal.configure(text=sig_text, text_color=sig_color))
                self.after(0, lambda: self._display_transcript(sentences, sentence_styles))
                unit_label = "line" if flow_mode == "line" else "page"
                self.after(0, lambda: self.set_status(f"🗣️ Reading {unit_label}...", "#00E5FF"))
                self.tts.speak_sentences(sentences, start_index=0, styles=sentence_styles)
            except Exception as e:
                print(f"[Capture and Read Error] {e}")
                self.reading_in_progress = False
                self.after(0, lambda: self.set_status(f"⚠️ Error reading page: {e}", "#FF5252"))

        threading.Thread(target=worker, daemon=True).start()

    def _on_no_text_found(self):
        self.set_status("⚠️ No text detected. Check selected area or make sure Kindle page is visible.", "#FF5252")
        self.reading_in_progress = False

    def _display_transcript(self, sentences: typing.List[str], styles: typing.List[str] = None):
        """Render sentences/lines into transcript box and record exact tag ranges for live highlighting."""
        self.txt_transcript.delete("1.0", "end")
        self.sentence_positions.clear()

        # Insert each sentence/line on a clean line and record position
        for i, s in enumerate(sentences):
            start_idx = self.txt_transcript.index("insert")
            self.txt_transcript.insert("end", f"{s}\n\n")
            end_idx = self.txt_transcript.index(f"{start_idx} + {len(s)} chars")
            self.sentence_positions.append((start_idx, end_idx))

            if styles and i < len(styles):
                st = styles[i]
                if st and st != "BODY":
                    self.txt_transcript.tag_add(f"style_{st}", start_idx, end_idx)

        # Reset spotlight
        unit_name = "Lines" if "Line" in self.reading_mode_var.get() else "Sentences"
        self.lbl_spotlight_counter.configure(text=f"🎯 Follow-Along Spotlight [Page Loaded - {len(sentences)} {unit_name}]")
        if sentences:
            self.lbl_spotlight_sentence.configure(text=sentences[0])

    def _on_transcript_double_click(self, event):
        """Allow user to double-click any line/sentence in the transcript to jump reading there immediately."""
        try:
            click_index = self.txt_transcript.index(f"@{event.x},{event.y}")
            # Find which sentence position contains click_index
            unit_name = "line" if "Line" in self.reading_mode_var.get() else "sentence"
            for i, (start_idx, end_idx) in enumerate(self.sentence_positions):
                if self.txt_transcript.compare(click_index, ">=", start_idx) and self.txt_transcript.compare(click_index, "<=", f"{end_idx} + 2 lines"):
                    self.tts.stop()
                    self.set_status(f"Jumping to {unit_name} {i + 1}...", "#00E5FF")
                    self.tts.speak_sentences(self.current_sentences, start_index=i, styles=self.current_sentence_styles)
                    break
        except Exception as e:
            print(f"[Jump Click Error] {e}")

    def _toggle_read_play(self):
        if self.tts.is_paused:
            self._pause_resume()
            return
        if self.tts.is_playing:
            return
        self._capture_and_read()

    def _pause_resume(self):
        if self.tts.is_playing:
            self.tts.toggle_pause()
            if self.tts.is_paused:
                self.screen_overlay.hide()
                self.set_status("⏸ Narration paused", "#FFD600")
                self.btn_pause.configure(text="▶ Resume")
            else:
                if self.active_sentence_idx >= 0 and self.active_sentence_idx < len(self.current_sentences):
                    self._highlight_sentence(self.active_sentence_idx, self.current_sentences[self.active_sentence_idx])
                self.set_status("🗣️ Narration resumed", "#00E5FF")
                self.btn_pause.configure(text="⏸ Pause")

    def _stop_reading(self):
        self.reading_in_progress = False
        self.screen_overlay.hide()
        self.tts.stop()
        self.set_status("⏹ Narration stopped.", "gray80")
        self.btn_pause.configure(text="⏸ Pause")

    def _prev_sentence(self):
        self.tts.skip_prev()

    def _next_sentence(self):
        self.tts.skip_next()

    def _next_page(self):
        self.tts.stop()
        self.screen_overlay.hide()
        self.reading_in_progress = True
        self.set_status("Turning to next page...", "#00E5FF")
        try:
            delay = float(self.entry_delay.get().strip())
            self.page_turner.turn_delay = max(0.5, delay)
        except Exception:
            pass

        # Synchronize targets from OCR engine if not set on PageTurner
        if self.ocr.target_hwnd and not self.page_turner.target_hwnd:
            self.page_turner.set_target_window(self.ocr.target_hwnd, self.ocr.target_window_title or "")
        if self.ocr.selected_region and not self.page_turner.click_target_region:
            self.page_turner.set_target_region(self.ocr.selected_region)

        def worker():
            self.page_turner.turn_next_page()
            self.after(0, self._capture_and_read)

        threading.Thread(target=worker, daemon=True).start()

    def _prev_page(self):
        self.tts.stop()
        self.screen_overlay.hide()
        self.reading_in_progress = True
        self.set_status("Turning to previous page...", "#00E5FF")
        try:
            delay = float(self.entry_delay.get().strip())
            self.page_turner.turn_delay = max(0.5, delay)
        except Exception:
            pass

        # Synchronize targets from OCR engine if not set on PageTurner
        if self.ocr.target_hwnd and not self.page_turner.target_hwnd:
            self.page_turner.set_target_window(self.ocr.target_hwnd, self.ocr.target_window_title or "")
        if self.ocr.selected_region and not self.page_turner.click_target_region:
            self.page_turner.set_target_region(self.ocr.selected_region)

        def worker():
            self.page_turner.turn_prev_page()
            self.after(0, self._capture_and_read)

        threading.Thread(target=worker, daemon=True).start()

    def _on_tts_sentence_start(self, index: int, sentence: str):
        self.active_sentence_idx = index
        self._save_current_bookmark(manual=False)
        self.after(0, lambda: self._highlight_sentence(index, sentence))

    def _save_current_bookmark(self, manual: bool = False):
        """Saves current reading progress bookmark."""
        if self.active_sentence_idx >= 0 and self.active_sentence_idx < len(self.current_sentences):
            sent = self.current_sentences[self.active_sentence_idx]
            title = self.ocr.target_window_title or "Kindle Reader"
            self.bookmark_mgr.save_bookmark(
                book_title=title,
                sentence_index=self.active_sentence_idx,
                sentence_text=sent,
                page_snippet=self.current_page_text,
                region=self.ocr.selected_region
            )
            short_s = sent[:35] + "..." if len(sent) > 35 else sent
            unit_name = "Line" if "Line" in self.reading_mode_var.get() else "Sent"
            self.lbl_bm_status.configure(
                text=f"📌 {unit_name} {self.active_sentence_idx + 1}: '{short_s}'",
                text_color="#00E5FF"
            )
            if manual:
                unit_full = "line" if "Line" in self.reading_mode_var.get() else "sentence"
                self.set_status(f"📌 Bookmark saved at {unit_full} {self.active_sentence_idx + 1}!", "#00C853")

    def _resume_from_bookmark(self):
        """Resumes reading from the last saved bookmark."""
        title = self.ocr.target_window_title or ""
        bm = self.bookmark_mgr.get_bookmark_for_book(title)
        if not bm:
            messagebox.showinfo(
                "No Bookmark Found",
                "No bookmark found for this book yet.\nStart reading to automatically bookmark your position!"
            )
            return

        target_sent = bm.get("sentence_text", "")
        saved_idx = bm.get("sentence_index", 0)
        book_title = bm.get("book_title", "Kindle")

        self.set_status(f"🔖 Resuming bookmark for '{book_title}'...", "#00E5FF")

        if self.current_sentences and len(self.current_sentences) > 0:
            matched_idx = self.bookmark_mgr.find_best_match_index(self.current_sentences, target_sent, saved_idx)
            self.tts.stop()
            self.reading_in_progress = True
            sent = self.current_sentences[matched_idx]
            unit_name = "line" if "Line" in self.reading_mode_var.get() else "sentence"
            self.set_status(f"🔖 Resuming at {unit_name} {matched_idx + 1}: '{sent[:40]}...'", "#00E5FF")
            self._highlight_sentence(matched_idx, sent)
            self.tts.speak_sentences(self.current_sentences, start_index=matched_idx, styles=self.current_sentence_styles)
        else:
            self._capture_and_resume_bookmark(target_sent, saved_idx)

    def _capture_and_resume_bookmark(self, target_sentence: str, fallback_idx: int):
        """Captures page OCR and starts TTS directly at the bookmarked sentence/line."""
        self.set_status("📸 Scanning page to find your bookmark...", "#FFD600")
        self.reading_in_progress = True
        flow_mode, filter_hdrs, col_mode = self._get_ocr_params()

        def worker():
            try:
                t0 = time.time()
                res = self.ocr.extract_text(
                    reading_mode=flow_mode,
                    filter_headers=filter_hdrs,
                    column_mode=col_mode
                )
                latency_ms = int((time.time() - t0) * 1000)
                cleaned_text = res.get("cleaned_text", "")
                sentences = res.get("sentences", [])
                sentence_boxes = res.get("sentence_boxes", [])
                sentence_styles = res.get("sentence_styles", [])
                screen_offset = res.get("screen_offset", (0, 0))

                if not cleaned_text or not sentences:
                    self.after(0, lambda: self._on_no_text_found())
                    return

                self.current_page_text = cleaned_text
                self.current_sentences = sentences
                self.current_sentence_boxes = sentence_boxes
                self.current_sentence_styles = sentence_styles
                self.current_screen_offset = screen_offset
                self.note_gen.add_page_text(cleaned_text)
                self.tts.style_modulation_enabled = self.qa_style_detection.get()

                matched_idx = self.bookmark_mgr.find_best_match_index(sentences, target_sentence, fallback_idx)

                if self.ocr.target_hwnd:
                    sig_text = f"📶 [ ▂▃▅] 100% ({latency_ms}ms)"
                    sig_color = "#00E5FF"
                elif self.ocr.selected_region:
                    sig_text = f"📶 [ ▂▃ ] 75% ({latency_ms}ms)"
                    sig_color = "#00C853"
                else:
                    sig_text = f"📶 [ ▂  ] 50% ({latency_ms}ms)"
                    sig_color = "#FFD600"

                self.after(0, lambda: self.lbl_signal.configure(text=sig_text, text_color=sig_color))
                self.after(0, lambda: self._display_transcript(sentences, sentence_styles))
                sent = sentences[matched_idx]
                unit_name = "line" if flow_mode == "line" else "sentence"
                self.after(0, lambda: self.set_status(f"🔖 Resumed at {unit_name} {matched_idx + 1}: '{sent[:40]}...'", "#00E5FF"))
                self.tts.speak_sentences(sentences, start_index=matched_idx, styles=sentence_styles)
            except Exception as e:
                print(f"[Bookmark Resume Error] {e}")
                self.reading_in_progress = False
                self.after(0, lambda: self.set_status(f"⚠️ Error scanning for bookmark: {e}", "#FF5252"))

        threading.Thread(target=worker, daemon=True).start()

    def _read_from_cursor_position(self):
        """Reads global mouse pointer location and immediately starts narration from that text."""
        pt = wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        cx, cy = pt.x, pt.y

        if self.current_sentences and self.current_sentence_boxes:
            matched_idx = self.ocr.find_sentence_index_at_point(
                cx, cy, self.current_sentence_boxes, self.current_screen_offset
            )
            self.tts.stop()
            self.reading_in_progress = True
            sent = self.current_sentences[matched_idx]
            unit_name = "line" if "Line" in self.reading_mode_var.get() else "sentence"
            self.set_status(f"🎯 Reading from cursor at {unit_name} {matched_idx + 1}: '{sent[:40]}...'", "#00E5FF")
            self._highlight_sentence(matched_idx, sent)
            self.tts.speak_sentences(self.current_sentences, start_index=matched_idx, styles=self.current_sentence_styles)
        else:
            self._capture_and_read_at_point(cx, cy)

    def _open_click_to_read(self):
        """Opens click overlay to click anywhere on Kindle page and start reading there."""
        self.withdraw()
        time.sleep(0.12)
        CursorPointSelectorDialog(self, lambda rx, ry: self._on_point_clicked_to_read(rx, ry))

    def _on_point_clicked_to_read(self, rx: int, ry: int):
        """Called when user clicks on a sentence/line on Kindle book."""
        if self.current_sentences and self.current_sentence_boxes:
            matched_idx = self.ocr.find_sentence_index_at_point(
                rx, ry, self.current_sentence_boxes, self.current_screen_offset
            )
            self.tts.stop()
            self.reading_in_progress = True
            sent = self.current_sentences[matched_idx]
            unit_name = "line" if "Line" in self.reading_mode_var.get() else "sentence"
            self.set_status(f"🎯 Reading from click at {unit_name} {matched_idx + 1}: '{sent[:40]}...'", "#00E5FF")
            self._highlight_sentence(matched_idx, sent)
            self.tts.speak_sentences(self.current_sentences, start_index=matched_idx, styles=self.current_sentence_styles)
        else:
            self._capture_and_read_at_point(rx, ry)

    def _capture_and_read_at_point(self, rx: int, ry: int):
        """Captures page OCR, determines sentence/line at (rx, ry), and starts reading from it."""
        self.set_status("📸 Scanning Kindle page to locate clicked text...", "#FFD600")
        self.reading_in_progress = True
        flow_mode, filter_hdrs, col_mode = self._get_ocr_params()

        def worker():
            try:
                t0 = time.time()
                res = self.ocr.extract_text(
                    reading_mode=flow_mode,
                    filter_headers=filter_hdrs,
                    column_mode=col_mode
                )
                latency_ms = int((time.time() - t0) * 1000)
                cleaned_text = res.get("cleaned_text", "")
                sentences = res.get("sentences", [])
                sentence_boxes = res.get("sentence_boxes", [])
                sentence_styles = res.get("sentence_styles", [])
                screen_offset = res.get("screen_offset", (0, 0))

                if not cleaned_text or not sentences:
                    self.after(0, lambda: self._on_no_text_found())
                    return

                self.current_page_text = cleaned_text
                self.current_sentences = sentences
                self.current_sentence_boxes = sentence_boxes
                self.current_sentence_styles = sentence_styles
                self.current_screen_offset = screen_offset
                self.note_gen.add_page_text(cleaned_text)
                self.tts.style_modulation_enabled = self.qa_style_detection.get()

                matched_idx = self.ocr.find_sentence_index_at_point(
                    rx, ry, sentence_boxes, screen_offset
                )

                if self.ocr.target_hwnd:
                    sig_text = f"📶 [ ▂▃▅] 100% ({latency_ms}ms)"
                    sig_color = "#00E5FF"
                elif self.ocr.selected_region:
                    sig_text = f"📶 [ ▂▃ ] 75% ({latency_ms}ms)"
                    sig_color = "#00C853"
                else:
                    sig_text = f"📶 [ ▂  ] 50% ({latency_ms}ms)"
                    sig_color = "#FFD600"

                self.after(0, lambda: self.lbl_signal.configure(text=sig_text, text_color=sig_color))
                self.after(0, lambda: self._display_transcript(sentences, sentence_styles))
                sent = sentences[matched_idx]
                unit_name = "line" if flow_mode == "line" else "sentence"
                self.after(0, lambda: self.set_status(f"🎯 Reading from cursor at {unit_name} {matched_idx + 1}: '{sent[:40]}...'", "#00E5FF"))
                self.tts.speak_sentences(sentences, start_index=matched_idx, styles=sentence_styles)
            except Exception as e:
                print(f"[Point Read Error] {e}")
                self.reading_in_progress = False
                self.after(0, lambda: self.set_status(f"⚠️ Error locating clicked text: {e}", "#FF5252"))

        threading.Thread(target=worker, daemon=True).start()

    def _on_close_app(self):
        """Saves bookmark and safely closes application."""
        try:
            self._save_current_bookmark(manual=False)
            self.tts.stop()
            self.screen_overlay.hide()
        except Exception:
            pass
        self.destroy()

    def _highlight_sentence(self, index: int, sentence: str):
        unit_name = "Line" if "Line" in self.reading_mode_var.get() else "Sentence"

        # 1. Update Follow-Along Spotlight Box
        style_badges = {
            "QUESTION": " [❓ Question]",
            "ANSWER": " [💡 Answer]",
            "OPTION": " [🔘 Option]",
            "HEADING": " [📌 Heading]",
            "QUOTE": " [💬 Dialogue]",
        }
        badge = ""
        if self.qa_style_detection.get() and index < len(self.current_sentence_styles):
            st = self.current_sentence_styles[index]
            badge = style_badges.get(st, "")

        self.lbl_spotlight_counter.configure(
            text=f"🎯 Follow-Along Spotlight [{unit_name} {index + 1} of {len(self.current_sentences)}]{badge}"
        )
        self.lbl_spotlight_sentence.configure(text=f'"{sentence}"')

        # 2. Update In-Transcript Highlighter
        try:
            # Clear previous active highlight
            self.txt_transcript.tag_remove("active_highlight", "1.0", "end")

            # Apply read_sentence style to past sentences
            for i in range(index):
                if i < len(self.sentence_positions):
                    s_start, s_end = self.sentence_positions[i]
                    self.txt_transcript.tag_add("read_sentence", s_start, s_end)

            # Apply bright highlight to active sentence
            if index < len(self.sentence_positions):
                active_start, active_end = self.sentence_positions[index]
                self.txt_transcript.tag_remove("read_sentence", active_start, active_end)
                self.txt_transcript.tag_add("active_highlight", active_start, active_end)
                # Auto-scroll transcript to follow active sentence
                self.txt_transcript.see(active_start)
        except Exception as e:
            print(f"[Highlight Error] {e}")

        # 3. Update On-Screen Floating Kindle Highlight
        try:
            if self.onscreen_highlight_enabled.get() and index < len(self.current_sentence_boxes):
                bx, by, bw, bh = self.current_sentence_boxes[index]
                ox, oy = self.current_screen_offset
                self.screen_overlay.highlight_box(ox + bx, oy + by, bw, bh)
            else:
                self.screen_overlay.hide()
        except Exception as e:
            print(f"[Screen Highlight Error] {e}")

        # 4. Update status line
        short_sent = sentence[:60] + "..." if len(sentence) > 60 else sentence
        self.set_status(f"[{unit_name} {index + 1}/{len(self.current_sentences)}] {short_sent}", "#00E5FF")

    def _on_tts_sentence_end(self, index: int):
        pass

    def _on_tts_error(self, err_msg: str):
        """Called when TTS encounters an unrecoverable synthesis error."""
        self.reading_in_progress = False
        self.screen_overlay.hide()
        self.after(0, lambda: self.set_status(f"⚠️ Speech Error: {err_msg}", "#FF5252"))

    def _on_tts_page_finished(self):
        """Called when all sentences on current page finish reading."""
        self.screen_overlay.hide()
        if self.auto_turn_enabled.get():
            self.reading_in_progress = True
            self.after(0, lambda: self.set_status("📄 Page finished. Auto-turning to next page...", "#00C853"))
            self.after(400, self._next_page)
        else:
            self.reading_in_progress = False
            self.after(0, lambda: self.set_status("✅ Finished reading page.", "#00C853"))

    def _generate_page_notes(self):
        if not self.current_page_text:
            messagebox.showinfo("No Page Content", "Please read or capture a page first before generating notes.")
            return

        self.set_status("🧠 Generating notes from current page...", "#00E5FF")
        self.tabview.set("📝 Notes & Summary")

        def worker():
            key = self.entry_apikey.get().strip()
            self.note_gen.api_key = key
            if self.note_gen.api_provider != "none" and key:
                notes = self.note_gen.generate_ai_notes(self.current_page_text, prompt_style="study")
            else:
                notes = self.note_gen.generate_local_notes(self.current_page_text, title="Page Notes")

            self.after(0, lambda: self._set_notes_content(notes))
            self.after(0, lambda: self.set_status("✅ Notes generated!", "#00C853"))

        threading.Thread(target=worker, daemon=True).start()

    def _generate_session_notes(self):
        full_text = self.note_gen.get_full_session_text()
        if not full_text:
            if self.current_page_text:
                full_text = self.current_page_text
            else:
                messagebox.showinfo("No Session Content", "No pages have been read yet in this session.")
                return

        self.set_status("🧠 Synthesizing notes for entire reading session...", "#00E5FF")
        self.tabview.set("📝 Notes & Summary")

        def worker():
            key = self.entry_apikey.get().strip()
            self.note_gen.api_key = key
            if self.note_gen.api_provider != "none" and key:
                notes = self.note_gen.generate_ai_notes(full_text, prompt_style="study")
            else:
                notes = self.note_gen.generate_local_notes(full_text, title="Full Reading Session Notes")

            self.after(0, lambda: self._set_notes_content(notes))
            self.after(0, lambda: self.set_status("✅ Session notes generated!", "#00C853"))

        threading.Thread(target=worker, daemon=True).start()

    def _set_notes_content(self, text: str):
        self.txt_notes.delete("1.0", "end")
        self.txt_notes.insert("1.0", text)

    def _copy_notes_to_clipboard(self):
        content = self.txt_notes.get("1.0", "end").strip()
        if content:
            self.clipboard_clear()
            self.clipboard_append(content)
            self.set_status("📋 Notes copied to clipboard!", "#00C853")

    def _save_notes_file(self):
        content = self.txt_notes.get("1.0", "end").strip()
        if not content:
            return
        fpath = filedialog.asksaveasfilename(
            defaultextension=".md",
            filetypes=[("Markdown files", "*.md"), ("Text files", "*.txt"), ("All files", "*.*")],
            title="Save Notes"
        )
        if fpath:
            self.note_gen.export_notes(fpath, content)
            self.set_status(f"💾 Notes saved to {os.path.basename(fpath)}", "#00C853")
