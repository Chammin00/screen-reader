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

    def focus_kindle_window(self) -> bool:
        """Attempts to activate and bring the Kindle window to focus."""
        # 1. Direct HWND Activation (fastest and most reliable)
        if self.target_hwnd and user32.IsWindow(self.target_hwnd):
            try:
                SW_RESTORE = 9
                if user32.IsIconic(self.target_hwnd):
                    user32.ShowWindow(self.target_hwnd, SW_RESTORE)
                user32.SetForegroundWindow(self.target_hwnd)
                user32.BringWindowToTop(self.target_hwnd)
                time.sleep(0.08)
                return True
            except Exception:
                pass

        if not gw:
            return False

        # 2. If a specific title was assigned
        if self.target_window_title:
            windows = gw.getWindowsWithTitle(self.target_window_title)
            if windows:
                try:
                    win = windows[0]
                    if win.isMinimized:
                        win.restore()
                    win.activate()
                    time.sleep(0.1)
                    return True
                except Exception:
                    pass

        # 3. Search for any Kindle or Cloud reader window
        for w in gw.getAllWindows():
            title = w.title.lower()
            if "kindle" in title or "cloud reader" in title or "amazon" in title:
                try:
                    if w.isMinimized:
                        w.restore()
                    win.activate()
                    time.sleep(0.1)
                    return True
                except Exception:
                    pass
                    pass

        # Fallback: click inside reading region to focus
        if self.click_target_region:
            rx, ry, rw, rh = self.click_target_region
            pyautogui.click(rx + rw // 2, ry + rh // 2)
            time.sleep(0.05)
            return True

        return False

    def turn_next_page(self) -> bool:
        """Sends a Next Page command to the Kindle window/region."""
        try:
            self.focus_kindle_window()
            pyautogui.press(self.key_next)
            time.sleep(self.turn_delay)
            return True
        except Exception as e:
            print(f"[PageTurner Next Error] {e}")
            # Fallback: click right margin of reading region
            if self.click_target_region:
                rx, ry, rw, rh = self.click_target_region
                pyautogui.click(rx + int(rw * 0.9), ry + rh // 2)
                time.sleep(self.turn_delay)
                return True
            return False

    def turn_prev_page(self) -> bool:
        """Sends a Previous Page command to the Kindle window/region."""
        try:
            self.focus_kindle_window()
            pyautogui.press(self.key_prev)
            time.sleep(self.turn_delay)
            return True
        except Exception as e:
            print(f"[PageTurner Prev Error] {e}")
            # Fallback: click left margin of reading region
            if self.click_target_region:
                rx, ry, rw, rh = self.click_target_region
                pyautogui.click(rx + int(rw * 0.1), ry + rh // 2)
                time.sleep(self.turn_delay)
                return True
            return False
