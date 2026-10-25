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
            for w in gw.getAllWindows():
                title = w.title.lower()
                if any(k in title for k in ["kindle", "cloud reader", "read.amazon", "amazon.com"]):
                    if w.width > 200 and w.height > 200:
                        self.target_hwnd = getattr(w, '_hWnd', None)
                        self.target_window_title = w.title
                        self.click_target_region = (w.left, w.top, w.width, w.height)
                        break

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

    def focus_kindle_window(self) -> bool:
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

        # 3. Fallback: click reading region to focus
        bounds = self.get_reading_bounds()
        if bounds:
            rx, ry, rw, rh = bounds
            pyautogui.click(rx + rw // 2, ry + rh // 2)
            time.sleep(0.05)
            return True

        return False

    def turn_next_page(self) -> bool:
        """Sends a Next Page command to the Kindle window/region using multiple redundant methods."""
        try:
            self._ensure_target_resolved()
            self.focus_kindle_window()

            # Method A: Win32 PostMessage directly to the target window (works even in background)
            if self.target_hwnd and user32.IsWindow(self.target_hwnd):
                user32.PostMessageW(self.target_hwnd, WM_KEYDOWN, VK_RIGHT, 0)
                user32.PostMessageW(self.target_hwnd, WM_KEYUP, VK_RIGHT, 0)
                user32.PostMessageW(self.target_hwnd, WM_KEYDOWN, VK_NEXT, 0)
                user32.PostMessageW(self.target_hwnd, WM_KEYUP, VK_NEXT, 0)

            # Method B: Physical mouse click on the right margin of the Kindle book
            # In Kindle, clicking the right 8-10% of the book area ALWAYS turns to next page
            bounds = self.get_reading_bounds()
            if bounds:
                bx, by, bw, bh = bounds
                click_x = bx + int(bw * 0.92)
                click_y = by + int(bh * 0.50)

                # Save current mouse position so the user's cursor isn't permanently moved
                pt = wintypes.POINT()
                user32.GetCursorPos(ctypes.byref(pt))
                orig_x, orig_y = pt.x, pt.y

                pyautogui.click(click_x, click_y)
                time.sleep(0.03)
                user32.SetCursorPos(orig_x, orig_y)

            # Method C: Press keyboard Right arrow & PageDown
            pyautogui.press(self.key_next)
            pyautogui.press("pagedown")

            time.sleep(self.turn_delay)
            return True
        except Exception as e:
            print(f"[PageTurner Next Error] {e}")
            return False

    def turn_prev_page(self) -> bool:
        """Sends a Previous Page command to the Kindle window/region using multiple redundant methods."""
        try:
            self._ensure_target_resolved()
            self.focus_kindle_window()

            # Method A: Win32 PostMessage directly to target window
            if self.target_hwnd and user32.IsWindow(self.target_hwnd):
                user32.PostMessageW(self.target_hwnd, WM_KEYDOWN, VK_LEFT, 0)
                user32.PostMessageW(self.target_hwnd, WM_KEYUP, VK_LEFT, 0)
                user32.PostMessageW(self.target_hwnd, WM_KEYDOWN, VK_PRIOR, 0)
                user32.PostMessageW(self.target_hwnd, WM_KEYUP, VK_PRIOR, 0)

            # Method B: Physical mouse click on left margin
            bounds = self.get_reading_bounds()
            if bounds:
                bx, by, bw, bh = bounds
                click_x = bx + int(bw * 0.08)
                click_y = by + int(bh * 0.50)

                pt = wintypes.POINT()
                user32.GetCursorPos(ctypes.byref(pt))
                orig_x, orig_y = pt.x, pt.y

                pyautogui.click(click_x, click_y)
                time.sleep(0.03)
                user32.SetCursorPos(orig_x, orig_y)

            # Method C: Press keyboard Left arrow & PageUp
            pyautogui.press(self.key_prev)
            pyautogui.press("pageup")

            time.sleep(self.turn_delay)
            return True
        except Exception as e:
            print(f"[PageTurner Prev Error] {e}")
            return False
