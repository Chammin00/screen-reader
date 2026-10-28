import ctypes
from ctypes import wintypes
import time
import typing
import pyautogui
try:
    import pygetwindow as gw
except ImportError:
    gw = None

user32 = ctypes.windll.user32

# Disable pyautogui fail-safe pauses for snappy interaction
pyautogui.PAUSE = 0.05

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
VK_LEFT = 0x25
VK_RIGHT = 0x27
VK_PRIOR = 0x21  # Page Up
VK_NEXT = 0x22   # Page Down
VK_SPACE = 0x20


class PageTurner:
    def __init__(self, key_next: str = "right", key_prev: str = "left", turn_delay: float = 1.0):
        self.key_next = key_next
        self.key_prev = key_prev
        self.turn_delay = turn_delay  # Wait seconds after turning page for animation to settle
        self.target_window_title: typing.Optional[str] = None
        self.target_hwnd: typing.Optional[int] = None
        self.click_target_region: typing.Optional[typing.Tuple[int, int, int, int]] = None

        self.last_turn_timestamp: float = 0.0
        self.min_turn_interval: float = 1.0  # Minimum seconds between page turns to prevent double-firing

    def set_target_window(self, hwnd: int, title: str = ""):
        """Set direct window handle for page-turn keystrokes."""
        self.target_hwnd = hwnd
        self.target_window_title = title

    def set_target_region(self, region: typing.Optional[typing.Tuple[int, int, int, int]]):
        """Set region bounds (x, y, w, h) for directional click fallbacks."""
        self.click_target_region = region

    def _ensure_target_resolved(self):
        """Auto-discovers Kindle window and region if not explicitly linked by user."""
        if (self.target_hwnd and user32.IsWindow(self.target_hwnd)) or self.click_target_region:
            return

        if gw:
            try:
                for w in gw.getAllWindows():
                    title = w.title.lower()
                    if any(k in title for k in ["kindle", "cloud reader", "read.amazon", "amazon.com"]):
                        if w.width > 200 and w.height > 200:
                            self.target_hwnd = getattr(w, '_hWnd', None)
                            self.target_window_title = w.title
                            self.click_target_region = (w.left, w.top, w.width, w.height)
                            return
            except Exception:
                pass

        # Win32 EnumWindows fallback
        try:
            found_info = []
            def _enum_proc(hwnd, lParam):
                if user32.IsWindowVisible(hwnd):
                    length = user32.GetWindowTextLengthW(hwnd)
                    if length > 0:
                        buff = ctypes.create_unicode_buffer(length + 1)
                        user32.GetWindowTextW(hwnd, buff, length + 1)
                        t = buff.value
                        t_lower = t.lower()
                        if any(k in t_lower for k in ["kindle", "cloud reader", "read.amazon"]):
                            rect = wintypes.RECT()
                            user32.GetWindowRect(hwnd, ctypes.byref(rect))
                            rw = rect.right - rect.left
                            rh = rect.bottom - rect.top
                            if rw > 200 and rh > 200:
                                found_info.append((hwnd, t, rect.left, rect.top, rw, rh))
                return True

            ENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
            user32.EnumWindows(ENUMPROC(_enum_proc), 0)
            if found_info:
                h, t, rx, ry, rw, rh = found_info[0]
                self.target_hwnd = h
                self.target_window_title = t
                self.click_target_region = (rx, ry, rw, rh)
        except Exception:
            pass

    def get_reading_bounds(self) -> typing.Optional[typing.Tuple[int, int, int, int]]:
        """Returns (x, y, w, h) for the target page."""
        if self.click_target_region:
            return self.click_target_region

        if self.target_hwnd and user32.IsWindow(self.target_hwnd):
            rect = wintypes.RECT()
            user32.GetWindowRect(self.target_hwnd, ctypes.byref(rect))
            x, y = rect.left, rect.top
            w = rect.right - rect.left
            h = rect.bottom - rect.top
            if w > 100 and h > 100:
                return (x, y, w, h)

        if gw and self.target_window_title:
            windows = gw.getWindowsWithTitle(self.target_window_title)
            if windows and windows[0].width > 100:
                win = windows[0]
                return (win.left, win.top, win.width, win.height)

        return None

    def focus_kindle_window(self, allow_click_fallback: bool = False) -> bool:
        """Attempts to activate and bring the Kindle window to focus using Windows API."""
        self._ensure_target_resolved()

        # 1. Direct HWND Activation with Windows LockSetForegroundWindow bypass
        if self.target_hwnd and user32.IsWindow(self.target_hwnd):
            try:
                SW_RESTORE = 9
                if user32.IsIconic(self.target_hwnd):
                    user32.ShowWindow(self.target_hwnd, SW_RESTORE)

                # Simulate ALT key tap to bypass Windows LockSetForegroundWindow restrictions
                user32.keybd_event(0x12, 0, 0, 0)  # ALT down
                user32.SetForegroundWindow(self.target_hwnd)
                user32.keybd_event(0x12, 0, 2, 0)  # ALT up
                user32.BringWindowToTop(self.target_hwnd)
                time.sleep(0.06)
                return True
            except Exception as e:
                print(f"[Focus HWND Warning] {e}")

        # 2. If pygetwindow is available
        if gw:
            if self.target_window_title:
                windows = gw.getWindowsWithTitle(self.target_window_title)
                if windows:
                    try:
                        win = windows[0]
                        if win.isMinimized:
                            win.restore()
                        win.activate()
                        time.sleep(0.08)
                        return True
                    except Exception:
                        pass

            for w in gw.getAllWindows():
                title = w.title.lower()
                if any(k in title for k in ["kindle", "cloud reader", "amazon.com", "read.amazon"]):
                    try:
                        if w.isMinimized:
                            w.restore()
                        w.activate()
                        time.sleep(0.08)
                        return True
                    except Exception:
                        pass

        # 3. Optional fallback: click reading region to focus (disabled during page turns to avoid toggling toolbars)
        if allow_click_fallback:
            bounds = self.get_reading_bounds()
            if bounds:
                rx, ry, rw, rh = bounds
                pyautogui.click(rx + rw // 2, ry + rh // 2)
                time.sleep(0.05)
                return True

        return False

    def turn_next_page(self) -> bool:
        """
        Sends a single, decisive Next Page command.
        Uses a priority fallback chain (Click margin OR single Keystroke),
        guaranteeing exactly ONE page turn per call.
        """
        now = time.time()
        if (now - self.last_turn_timestamp) < self.min_turn_interval:
            # Debounce rapid triggers
            return True
        self.last_turn_timestamp = now

        try:
            self._ensure_target_resolved()
            self.focus_kindle_window()

            turned = False
            # Priority 1: Physical mouse click on the right margin of Kindle book
            # In Kindle, clicking the right 6-8% of the book area reliably turns exactly 1 page
            bounds = self.get_reading_bounds()
            if bounds:
                bx, by, bw, bh = bounds
                click_x = bx + int(bw * 0.94)
                click_y = by + int(bh * 0.50)

                # Save current mouse position so the user's cursor is restored
                pt = wintypes.POINT()
                user32.GetCursorPos(ctypes.byref(pt))
                orig_x, orig_y = pt.x, pt.y

                pyautogui.click(click_x, click_y)
                time.sleep(0.04)
                user32.SetCursorPos(orig_x, orig_y)
                turned = True

            # Priority 2: Keystroke fallback (only if click was not performed)
            if not turned:
                if self.target_hwnd and user32.IsWindow(self.target_hwnd):
                    user32.PostMessageW(self.target_hwnd, WM_KEYDOWN, VK_RIGHT, 0)
                    user32.PostMessageW(self.target_hwnd, WM_KEYUP, VK_RIGHT, 0)
                else:
                    pyautogui.press(self.key_next)

            time.sleep(self.turn_delay)
            return True
        except Exception as e:
            print(f"[PageTurner Next Error] {e}")
            return False

    def turn_prev_page(self) -> bool:
        """
        Sends a single, decisive Previous Page command.
        Uses a priority fallback chain (Click margin OR single Keystroke),
        guaranteeing exactly ONE page turn per call.
        """
        now = time.time()
        if (now - self.last_turn_timestamp) < self.min_turn_interval:
            return True
        self.last_turn_timestamp = now

        try:
            self._ensure_target_resolved()
            self.focus_kindle_window()

            turned = False
            # Priority 1: Physical mouse click on left margin of Kindle book
            bounds = self.get_reading_bounds()
            if bounds:
                bx, by, bw, bh = bounds
                click_x = bx + int(bw * 0.06)
                click_y = by + int(bh * 0.50)

                pt = wintypes.POINT()
                user32.GetCursorPos(ctypes.byref(pt))
                orig_x, orig_y = pt.x, pt.y

                pyautogui.click(click_x, click_y)
                time.sleep(0.04)
                user32.SetCursorPos(orig_x, orig_y)
                turned = True

            # Priority 2: Keystroke fallback (only if click was not performed)
            if not turned:
                if self.target_hwnd and user32.IsWindow(self.target_hwnd):
                    user32.PostMessageW(self.target_hwnd, WM_KEYDOWN, VK_LEFT, 0)
                    user32.PostMessageW(self.target_hwnd, WM_KEYUP, VK_LEFT, 0)
                else:
                    pyautogui.press(self.key_prev)

            time.sleep(self.turn_delay)
            return True
        except Exception as e:
            print(f"[PageTurner Prev Error] {e}")
            return False
