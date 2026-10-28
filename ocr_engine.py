import ctypes
from ctypes import wintypes
import re
import typing
import winocr
from PIL import Image, ImageGrab
import pyautogui
try:
    import pygetwindow as gw
except ImportError:
    gw = None

user32 = ctypes.windll.user32


class StyleClassifier:
    """
    Classifies text lines into semantic document and dialogue styles:
    - QUESTION: Questions, prompts, Q:, Question 1:, numbered question stems.
    - ANSWER: Answers, explanations, A:, Ans:, Solution:.
    - OPTION: Multiple choice options like (A), (B), A), 1), etc.
    - HEADING: Chapter titles, Section headers, major subheadings.
    - QUOTE: Direct dialogue, quoted speech ("...", '...', —).
    - BODY: Regular narrative or descriptive body text.
    """
    QUESTION_PATTERNS = [
        r'^\s*(?:Q\s*[\.:]|Question\s*\d*[\.:]|Prob(?:lem)?\s*\d*[\.:]|Exercise\s*\d*[\.:]|Item\s*\d*[\.:])',
        r'^\s*\d+[\.\)]\s+(?:What|Which|Who|Where|When|Why|How|Is|Are|Do|Does|Did|Can|Could|Would|Should|If|Explain|Describe|Find|Calculate|Identify|Define)\b',
        r'\?\s*["\'\”\’\)\s]*$',
    ]
    ANSWER_PATTERNS = [
        r'^\s*(?:A\s*[\.:]|Ans(?:wer)?\s*\d*[\.:]|Solution[\.:]|Explanation[\.:]|Key[\.:]|Result[\.:])',
        r'^\s*(?:Correct\s+Answer|The\s+answer\s+is)\b',
    ]
    OPTION_PATTERNS = [
        r'^\s*(?:Option\s+)?(?:\([A-Ea-e1-5]\)|[A-Ea-e1-5]\s*[\.\:\)]|\[[A-Ea-e1-5]\])\s*',
    ]
    HEADING_PATTERNS = [
        r'^\s*(?:CHAPTER|PART|SECTION|UNIT|LESSON|MODULE|BOOK|ACT|SCENE)\s+[\dIVXLCDM]+',
        r'^\s*(?:TABLE OF CONTENTS|PREFACE|INTRODUCTION|EPILOGUE|PROLOGUE|APPENDIX|INDEX|SUMMARY|GLOSSARY|REVIEW QUESTIONS)',
    ]
    QUOTE_PATTERNS = [
        r'^\s*["“\'‘«—].*["”\'’»—]\s*$',
        r'^\s*[A-Z][a-zA-Z\s]{1,15}\s*:\s*["“]?',
        r'["“][^"”]{3,}["”]',
    ]

    @classmethod
    def classify(cls, text: str, line_h: float = 20.0, median_h: float = 20.0) -> str:
        s = text.strip()
        if not s:
            return "BODY"
        for p in cls.QUESTION_PATTERNS:
            if re.search(p, s, re.IGNORECASE):
                return "QUESTION"
        for p in cls.ANSWER_PATTERNS:
            if re.search(p, s, re.IGNORECASE):
                return "ANSWER"
        for p in cls.OPTION_PATTERNS:
            if re.search(p, s, re.IGNORECASE):
                return "OPTION"
        for p in cls.HEADING_PATTERNS:
            if re.search(p, s, re.IGNORECASE):
                return "HEADING"
        if s.isupper() and len(s) < 50 and len(s) > 3:
            return "HEADING"
        if line_h >= median_h * 1.35 and len(s) < 50:
            return "HEADING"
        for p in cls.QUOTE_PATTERNS:
            if re.search(p, s):
                return "QUOTE"
        return "BODY"


class WindowInfo:
    """Lightweight window object adapter compatible with pygetwindow interfaces."""
    def __init__(self, hwnd: int, title: str, left: int, top: int, width: int, height: int):
        self._hWnd = hwnd
        self.hwnd = hwnd
        self.title = title
        self.left = left
        self.top = top
        self.width = width
        self.height = height

    def activate(self):
        try:
            SW_RESTORE = 9
            if user32.IsIconic(self._hWnd):
                user32.ShowWindow(self._hWnd, SW_RESTORE)
            user32.keybd_event(0x12, 0, 0, 0)
            user32.SetForegroundWindow(self._hWnd)
            user32.keybd_event(0x12, 0, 2, 0)
            user32.BringWindowToTop(self._hWnd)
        except Exception:
            pass


class OCREngine:
    def __init__(self, language: str = "en"):
        self.language = language
        self.selected_region: typing.Optional[typing.Tuple[int, int, int, int]] = None  # (x, y, w, h)
        self.target_window_title: typing.Optional[str] = None
        self.target_hwnd: typing.Optional[int] = None

    def set_target_window(self, hwnd: int, title: str = ""):
        """Link a specific application window handle (HWND) for direct reading."""
        self.target_hwnd = hwnd
        self.target_window_title = title
        self.selected_region = None

    def set_region(self, x: int, y: int, width: int, height: int):
        """Set a specific screen bounding box (x, y, width, height) to capture."""
        if width > 10 and height > 10:
            self.selected_region = (int(x), int(y), int(width), int(height))
            self.target_hwnd = None

    def clear_region(self):
        """Clear custom region and window targeting."""
        self.selected_region = None
        self.target_hwnd = None

    def get_window_reading_rect(self, hwnd: int) -> typing.Optional[typing.Tuple[int, int, int, int]]:
        """Calculates inner reading rectangle of window, trimming chrome/titlebars."""
        if not hwnd or not user32.IsWindow(hwnd):
            return None
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        x, y = rect.left, rect.top
        w = rect.right - rect.left
        h = rect.bottom - rect.top
        if w > 200 and h > 200:
            # Safely trim window borders (approx 12px sides, 42px top header, 30px footer)
            return (x + 12, y + 42, max(50, w - 24), max(50, h - 75))
        return (x, y, max(10, w), max(10, h))

    def find_kindle_window(self) -> typing.Optional[typing.Any]:
        """Find Kindle desktop app or Kindle browser tab window using pygetwindow and Win32 EnumWindows."""
        target_keywords = ["kindle", "cloud reader", "read.amazon", "amazon.com", "security+", "sy0-701"]

        # 1. Try pygetwindow
        if gw:
            try:
                for w in gw.getAllWindows():
                    t_lower = w.title.lower()
                    if any(k in t_lower for k in target_keywords):
                        if w.width > 200 and w.height > 200:
                            return w
            except Exception:
                pass

        # 2. Direct Win32 EnumWindows fallback
        try:
            found = []
            def _enum_proc(hwnd, lParam):
                if user32.IsWindowVisible(hwnd):
                    length = user32.GetWindowTextLengthW(hwnd)
                    if length > 0:
                        buff = ctypes.create_unicode_buffer(length + 1)
                        user32.GetWindowTextW(hwnd, buff, length + 1)
                        t = buff.value
                        t_lower = t.lower()
                        if any(k in t_lower for k in target_keywords):
                            rect = wintypes.RECT()
                            user32.GetWindowRect(hwnd, ctypes.byref(rect))
                            rw = rect.right - rect.left
                            rh = rect.bottom - rect.top
                            if rw > 200 and rh > 200:
                                found.append(WindowInfo(hwnd, t, rect.left, rect.top, rw, rh))
                return True

            ENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
            user32.EnumWindows(ENUMPROC(_enum_proc), 0)
            if found:
                return found[0]
        except Exception:
            pass

        return None

    def _capture_gdi(self, x: int, y: int, w: int, h: int) -> Image.Image:
        """High-reliability Win32 GDI BitBlt screen capture fallback."""
        w = max(10, int(w))
        h = max(10, int(h))
        x = int(x)
        y = int(y)
        hdc_screen = user32.GetDC(0)
        hdc_mem = ctypes.windll.gdi32.CreateCompatibleDC(hdc_screen)
        hbm = ctypes.windll.gdi32.CreateCompatibleBitmap(hdc_screen, w, h)
        old_bm = ctypes.windll.gdi32.SelectObject(hdc_mem, hbm)
        
        # SRCCOPY = 0x00CC0020
        ctypes.windll.gdi32.BitBlt(hdc_mem, 0, 0, w, h, hdc_screen, x, y, 0x00CC0020)
        
        import struct
        bmi = bytearray(44)
        bmi[:40] = struct.pack('<IIIHHIIIIII', 40, w, h, 1, 32, 0, w * h * 4, 0, 0, 0, 0)
        buf = bytearray(w * h * 4)
        c_buf = (ctypes.c_char * len(buf)).from_buffer(buf)
        ctypes.windll.gdi32.GetDIBits(hdc_mem, hbm, 0, h, c_buf, (ctypes.c_char * 40).from_buffer(bmi), 0)
        
        ctypes.windll.gdi32.SelectObject(hdc_mem, old_bm)
        ctypes.windll.gdi32.DeleteObject(hbm)
        ctypes.windll.gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(0, hdc_screen)
        
        img = Image.frombuffer('RGBA', (w, h), bytes(buf), 'raw', 'BGRA', 0, 1)
        return img.transpose(Image.FLIP_TOP_BOTTOM).convert('RGB')

    def capture_screen_with_offset(self) -> typing.Tuple[Image.Image, typing.Tuple[int, int]]:
        """Capture image and return (Image, (screen_x, screen_y))."""
        if self.target_hwnd and user32.IsWindow(self.target_hwnd):
            wrect = self.get_window_reading_rect(self.target_hwnd)
            if wrect:
                x, y, w, h = wrect
                bbox = (x, y, x + w, y + h)
                try:
                    return ImageGrab.grab(bbox=bbox), (x, y)
                except Exception:
                    return self._capture_gdi(x, y, w, h), (x, y)

        if self.selected_region:
            x, y, w, h = self.selected_region
            bbox = (x, y, x + w, y + h)
            try:
                return ImageGrab.grab(bbox=bbox), (x, y)
            except Exception:
                return self._capture_gdi(x, y, w, h), (x, y)

        if self.target_window_title and gw:
            windows = gw.getWindowsWithTitle(self.target_window_title)
            if windows and windows[0].width > 50 and windows[0].height > 50:
                win = windows[0]
                bbox = (win.left, win.top, win.left + win.width, win.top + win.height)
                try:
                    return ImageGrab.grab(bbox=bbox), (win.left, win.top)
                except Exception:
                    return self._capture_gdi(win.left, win.top, win.width, win.height), (win.left, win.top)

        # Fallback to full screen
        try:
            return ImageGrab.grab(), (0, 0)
        except Exception:
            sw = user32.GetSystemMetrics(0)
            sh = user32.GetSystemMetrics(1)
            return self._capture_gdi(0, 0, sw, sh), (0, 0)

    def capture_screen(self) -> Image.Image:
        """Capture image of the linked window, selected region, or entire screen."""
        img, _ = self.capture_screen_with_offset()
        return img

    @staticmethod
    def is_page_number_text(text: str) -> bool:
        """Determines if a text string is a page number, location, progress indicator, or reading time."""
        s = text.strip()
        if not s:
            return False

        # Legitimate content sentences are NEVER page numbers
        if len(s.split()) > 5:
            return False

        # Protect bullet points, list items, questions, and common content with words
        if s.startswith(("•", "-", "*", "·", "–", "—")) and any(c.isalpha() for c in s):
            return False
        if s.endswith("?"):
            return False

        patterns = [
            # Standalone digits, with optional punctuation/brackets/dashes: e.g. '142', '- 142 -', '[142]', '(142)', '• 142 •', '142.'
            r"^[\(\[\-\—\–\~•·\|\<\>]?\s*\d{1,5}\s*[\)\]\-\—\–\~•·\|\<\>\.]?$",
            # Page prefixes: 'Page 142', 'page 142 of 300', 'Page 142 / 300', 'p. 142', 'pp. 142-143', 'pg 142'
            r"^(?:page|pg|p|p\.|pp\.)\s*[\.:]?\s*\d{1,5}(?:\s*(?:of|/|\||•|-|–|—)\s*\d{1,5})?$",
            # Page fractions: '142 of 300', '142 / 300', '142 | 300'
            r"^\d{1,5}\s*(?:of|/|\|)\s*\d{1,5}$",
            # Roman numerals: 'iv', 'xii', 'xvi', '- iv -'
            r"^[\(\[\-\—\–\~•·]?\s*[ivxlcdmIVXLCDM]{1,8}\s*[\)\]\-\—\–\~•·\.]?$",
            # Kindle location, percentage, and time remaining (strictly standalone):
            r"^loc(?:ation)?\s*[\.:]?\s*\d+$",
            r"^\d{1,3}\s*%$",
            r"^\d+\s+mins?\s+left(?:\s+in\s+book)?$",
            r"^\d+\s+hours?\s+left(?:\s+in\s+book)?$",
            r"^kindle(?:\s+for\s+pc)?$",
            r"^amazon(?:\s+kindle)?$",
            r"^cloud\s+reader$",
        ]
        return any(re.match(pat, s, re.IGNORECASE) for pat in patterns)

    def is_running_header_or_title(
        self,
        pl: typing.Dict[str, typing.Any],
        idx: int,
        all_lines: typing.List[typing.Dict[str, typing.Any]],
        img_h: float
    ) -> bool:
        """Identifies running book/chapter titles, author headers, and page numbers at the top of the screen."""
        text = pl["text"].strip()
        if not text:
            return False

        # NEVER filter out legitimate questions, prompts, bullets, or numbered list items
        if text.endswith("?") or re.match(r"^\s*(?:Q\s*[\.:]|Question\s*\d*[\.:]|Prob(?:lem)?\s*\d*[\.:]|Exercise\s*\d*[\.:]|Item\s*\d*[\.:])", text, re.IGNORECASE):
            return False
        if text.startswith(("•", "*", "·", "–", "—")) or re.match(r"^\s*\d{1,3}[\.\)]\s+", text):
            return False

        # Any page number text in top 15% is a running header
        if pl["y"] < (img_h * 0.15) and self.is_page_number_text(text):
            return True

        # Page number combined with title in top margin (e.g. '42 | The Art of War' or 'Chapter 3 - 42')
        if pl["y"] < (img_h * 0.12):
            combo_pattern = r"^\s*(?:\d{1,5}\s*[-–—|•·\~]\s*.+|.+\s*[-–—|•·\~]\s*\d{1,5})\s*$"
            if re.match(combo_pattern, text) and len(text) <= 50:
                return True

        # Check top 10% of the screen ONLY
        if pl["y"] < (img_h * 0.10):
            # Known window title match
            if self.target_window_title:
                clean_win = re.sub(r"[^a-zA-Z0-9\s]", "", self.target_window_title.lower())
                clean_line = re.sub(r"[^a-zA-Z0-9\s]", "", text.lower())
                if clean_line and len(clean_line) >= 6 and clean_line in clean_win:
                    return True

            # Explicit Chapter/Part marker in the extreme top margin (short header)
            if re.match(r"^\s*(?:CHAPTER|PART|SECTION|UNIT|LESSON|BOOK|ACT)\s+[\dIVXLCDM]+.*$", text, re.IGNORECASE):
                if len(text.split()) <= 6:
                    return True

        return False

    def clean_text(self, raw_text: str) -> str:
        """
        Cleans extracted OCR text by:
        - Removing common Kindle headers/footers (page numbers, loc, battery, percentage)
        - Fixing broken hyphenated line wraps (e.g. 'extraor-\n dinary' -> 'extraordinary')
        - Preserving full sentences without dropping words or abbreviations.
        """
        if not raw_text:
            return ""

        lines = raw_text.splitlines()
        cleaned_lines = []

        for line in lines:
            trimmed = line.strip()
            if not trimmed:
                continue

            if self.is_page_number_text(trimmed):
                continue

            cleaned_lines.append(trimmed)

        if not cleaned_lines:
            return ""

        text = "\n".join(cleaned_lines)

        # 1. Fix hyphenation at line breaks or spaces (e.g., 'deter-\n mined' -> 'determined', 'traf-\n fic' -> 'traffic')
        hyphen_pattern = r"([a-zA-Z]+)\s*[\-\u2010\u2011\u2012\u2013\u00ad\u00ac~]\s*(?:\r?\n|\s+)\s*([a-zA-Z]+)"
        text = re.sub(hyphen_pattern, r"\1\2", text)

        # 2. Fix OCR punctuation glitches (e.g. 'traffic,.' -> 'traffic,' or 'traffic.')
        # If comma-period is followed by lowercase, it was originally a comma
        text = re.sub(r'[,;]\s*[.](?=\s+[a-z])', ',', text)
        text = re.sub(r'[,;]\s*[.]', '.', text)
        text = re.sub(r'[.]\s*[,;](?=\s+[a-z])', ',', text)
        text = re.sub(r'[.]\s*[,;]', '.', text)
        text = re.sub(r',\s*,+', ',', text)
        text = re.sub(r'(?<!\.)\.\.(?!\.)', '.', text)

        # Clean dashes after commas or semicolons (e.g. 'traffic, -' -> 'traffic,')
        text = re.sub(r'([,;:!?])\s*[-–—]+', r'\1', text)
        text = re.sub(r'[-–—]+\s*([,;:!?])', r'\1', text)

        # Remove spaces before punctuation (e.g. 'traffic ,' -> 'traffic,')
        text = re.sub(r'\s+([,.!?;:])', r'\1', text)

        # 3. Join soft line breaks within paragraphs
        # If line does not end with sentence-ending punctuation (.!?), join with space
        text = re.sub(r"(?<![.!?])\s*\r?\n\s*", " ", text)
        # Even if line ends with period/exclamation/question, if next line starts with lowercase, join it
        text = re.sub(r"([.!?])\s*\r?\n\s*(?=[a-z])", r"\1 ", text)

        # Normalize whitespace
        text = re.sub(r"[ \t]+", " ", text).strip()
        return text

    def split_into_sentences(self, text: str) -> typing.List[str]:
        """Splits cleaned text into distinct sentences without splitting on abbreviations or dropping words."""
        if not text:
            return []

        abbrs = [
            "Mr.", "Mrs.", "Ms.", "Dr.", "Prof.", "Sr.", "Jr.", "vs.",
            "etc.", "e.g.", "i.e.", "St.", "Jan.", "Feb.", "Mar.",
            "Apr.", "Aug.", "Sept.", "Oct.", "Nov.", "Dec.",
            "Vol.", "p.m.", "a.m.", "U.S.", "U.K."
        ]

        temp_text = text
        for i, ab in enumerate(abbrs):
            temp_text = temp_text.replace(ab, f"ABBRX{i}X")

        raw_sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z0-9\"\'“‘\(\[])', temp_text)

        sentences = []
        for s in raw_sentences:
            s_clean = re.sub(r"\s+", " ", s).strip()
            # Clean punctuation at ends or inside
            s_clean = re.sub(r'[,;]\s*[.](?=\s+[a-z])', ',', s_clean)
            s_clean = re.sub(r'[,;]\s*[.]', '.', s_clean)
            if s_clean:
                for i, ab in enumerate(abbrs):
                    s_clean = s_clean.replace(f"ABBRX{i}X", ab)
                sentences.append(s_clean)

        return sentences

    def clean_single_line(self, text: str) -> str:
        """
        Cleans a single OCR line:
        - Normalizes whitespace
        - Fixes OCR punctuation glitches (e.g. 'traffic,.' -> 'traffic,')
        - Fixes dashes and symbols
        """
        if not text:
            return ""
        s = text.strip()

        # Fix OCR punctuation glitches (e.g. 'traffic,.' -> 'traffic,' or 'traffic.')
        s = re.sub(r'[,;]\s*[.](?=\s+[a-z])', ',', s)
        s = re.sub(r'[,;]\s*[.]', '.', s)
        s = re.sub(r'[.]\s*[,;](?=\s+[a-z])', ',', s)
        s = re.sub(r'[.]\s*[,;]', '.', s)
        s = re.sub(r',\s*,+', ',', s)
        s = re.sub(r'(?<!\.)\.\.(?!\.)', '.', s)

        # Clean dashes after/before commas or semicolons
        s = re.sub(r'([,;:!?])\s*[-–—]+', r'\1', s)
        s = re.sub(r'[-–—]+\s*([,;:!?])', r'\1', s)

        # Remove spaces before punctuation
        s = re.sub(r'\s+([,.!?;:])', r'\1', s)

        # Remove trailing dangling hyphens so TTS doesn't say "dash" or pause unnaturally
        s = re.sub(r'([a-zA-Z]{2,})[-\u2010\u2011\u2012\u2013\u00ad~]\s*$', r'\1', s)

        # Normalize whitespace
        s = re.sub(r'\s+', ' ', s).strip()
        return s

    def _sort_and_merge_lines(
        self,
        lines: typing.List[typing.Dict[str, typing.Any]]
    ) -> typing.List[typing.Dict[str, typing.Any]]:
        """
        Sorts lines top-to-bottom and horizontally merges fragmented words on the same baseline.
        """
        if not lines:
            return []

        # Sort primarily by vertical y, secondary by horizontal x
        sorted_raw = sorted(lines, key=lambda item: (item["y"], item["x"]))

        merged: typing.List[typing.Dict[str, typing.Any]] = []
        for l in sorted_raw:
            if not merged:
                merged.append(dict(l))
                continue
            prev = merged[-1]

            # Check vertical overlap between prev and l
            v_overlap = min(prev["bottom"], l["bottom"]) - max(prev["y"], l["y"])
            min_h = min(prev["h"], l["h"])

            # If they share the same baseline row and l is to the right of prev (or slightly overlapping)
            if min_h > 0 and (v_overlap / min_h) >= 0.45 and (l["x"] >= prev["x"] - 10):
                # Merge into a single continuous physical line
                prev["text"] = f"{prev['text']} {l['text']}".strip()
                prev["x"] = min(prev["x"], l["x"])
                prev["y"] = min(prev["y"], l["y"])
                prev["right"] = max(prev["right"], l["right"])
                prev["bottom"] = max(prev["bottom"], l["bottom"])
                prev["w"] = prev["right"] - prev["x"]
                prev["h"] = prev["bottom"] - prev["y"]
            else:
                merged.append(dict(l))

        return merged

    def _map_sentences_to_boxes(
        self,
        sentences: typing.List[str],
        ordered_lines: typing.List[typing.Dict[str, typing.Any]],
        img_w: float
    ) -> typing.List[typing.Tuple[float, float, float, float]]:
        """Maps full sentences across physical lines so multi-line sentences get accurate bounding boxes."""
        if not sentences:
            return []
        if not ordered_lines:
            return [(0, 0, img_w, 30) for _ in sentences]

        total_lines = len(ordered_lines)
        sentence_boxes: typing.List[typing.Tuple[float, float, float, float]] = []
        cur_line_idx = 0

        for s in sentences:
            s_words = [w.lower().strip(".,!?:;\"'()[]") for w in s.split() if w.strip(".,!?:;\"'()[]")]
            first_words = s_words[:3] if len(s_words) >= 3 else s_words

            # Find starting line matching first words
            start_line = cur_line_idx
            found_start = False
            for test_idx in range(cur_line_idx, min(cur_line_idx + 4, total_lines)):
                line_lower = ordered_lines[test_idx]["text"].lower()
                if any(w in line_lower for w in first_words):
                    start_line = test_idx
                    found_start = True
                    break

            if not found_start:
                start_line = min(cur_line_idx, total_lines - 1)

            # Estimate how many lines this sentence spans
            approx_line_count = max(1, round(len(s) / 65))
            end_line = min(total_lines - 1, start_line + approx_line_count - 1)

            # Gather all physical lines belonging to this sentence
            matched_lines = ordered_lines[start_line : end_line + 1]
            if matched_lines:
                bx = min(l["x"] for l in matched_lines)
                by = min(l["y"] for l in matched_lines)
                bright = max(l["right"] for l in matched_lines)
                bbottom = max(l["bottom"] for l in matched_lines)
                bw = max(20.0, bright - bx)
                bh = max(24.0, bbottom - by)
                sentence_boxes.append((float(bx), float(by), float(bw), float(bh)))
            else:
                sentence_boxes.append((0, 0, img_w, 30))

            cur_line_idx = min(total_lines - 1, end_line + 1)

        return sentence_boxes

    def _detect_and_order_columns(
        self,
        lines: typing.List[typing.Dict[str, typing.Any]],
        img_w: float,
        img_h: float,
        column_mode: str = "auto"
    ) -> typing.List[typing.Dict[str, typing.Any]]:
        """
        Uses Recursive XY-Cut and dynamic vertical gutter detection to segment multi-column documents.
        Identifies full-width banners/headers and reads Left Column completely down before Right Column.
        """
        if not lines:
            return []
        if len(lines) <= 2 or column_mode == "single":
            return self._sort_and_merge_lines(lines)

        min_x = min(l["x"] for l in lines)
        max_right = max(l["right"] for l in lines)
        content_w = max_right - min_x

        if content_w < 120:
            return self._sort_and_merge_lines(lines)

        # 1. Separate cross-column banners (full-width section headers, chapter titles)
        def is_cross_column(l: typing.Dict[str, typing.Any]) -> bool:
            w_ratio = l["w"] / max(1.0, content_w)
            spans_left = l["x"] < (min_x + content_w * 0.38)
            spans_right = l["right"] > (max_right - content_w * 0.38)
            return w_ratio > 0.58 and spans_left and spans_right

        cross_lines = [l for l in lines if is_cross_column(l)]
        body_lines = [l for l in lines if not is_cross_column(l)]

        if not body_lines:
            return self._sort_and_merge_lines(lines)

        # 2. Dynamic Gutter Detection across the central 22% to 78% of the text width
        search_min = min_x + content_w * 0.22
        search_max = max_right - content_w * 0.22

        best_split_x = (min_x + max_right) / 2.0
        min_crossings = 999999

        # Search for minimum line crossing / whitespace gutter
        for x in range(int(search_min), int(search_max), 3):
            crossings = sum(1 for l in body_lines if l["x"] < (x - 8) and l["right"] > (x + 8))
            if crossings < min_crossings:
                min_crossings = crossings
                best_split_x = float(x)
            elif crossings == min_crossings:
                best_split_x = (best_split_x + float(x)) / 2.0

        # Partition body lines into left column and right column using best_split_x
        left_col = [l for l in body_lines if (l["x"] + l["right"]) / 2.0 < best_split_x]
        right_col = [l for l in body_lines if (l["x"] + l["right"]) / 2.0 >= best_split_x]

        # 3. Determine if two-column ordering should be applied
        apply_two_col = False
        if column_mode == "two_column":
            apply_two_col = True
        elif column_mode == "single":
            apply_two_col = False
        else:  # "auto"
            # Require at least 2 lines on each side and low crossings at gutter
            if len(left_col) >= 2 and len(right_col) >= 2:
                if min_crossings == 0 or (len(left_col) + len(right_col)) >= len(body_lines) * 0.75:
                    apply_two_col = True

        if not apply_two_col:
            return self._sort_and_merge_lines(lines)

        # 4. Band Ordering: Top Headers -> Left Column (Down) -> Mid Banners -> Right Column (Down) -> Bottom Footers
        col_top = min(
            min((l["y"] for l in left_col), default=0),
            min((l["y"] for l in right_col), default=0)
        )
        col_bottom = max(
            max((l["bottom"] for l in left_col), default=img_h),
            max((l["bottom"] for l in right_col), default=img_h)
        )

        top_headers = [l for l in cross_lines if l["bottom"] <= (col_top + 15)]
        bottom_footers = [l for l in cross_lines if l["y"] >= (col_bottom - 15)]
        mid_cross = [l for l in cross_lines if l not in top_headers and l not in bottom_footers]

        sorted_top = self._sort_and_merge_lines(top_headers)
        sorted_left = self._sort_and_merge_lines(left_col)
        sorted_right = self._sort_and_merge_lines(right_col)
        sorted_bottom = self._sort_and_merge_lines(bottom_footers)
        sorted_mid = self._sort_and_merge_lines(mid_cross)

        return sorted_top + sorted_left + sorted_mid + sorted_right + sorted_bottom

    def extract_text(
        self,
        image: typing.Optional[Image.Image] = None,
        reading_mode: str = "line",
        filter_headers: bool = True,
        column_mode: str = "auto"
    ) -> typing.Dict[str, typing.Any]:
        """
        Captures screen/region, performs OCR, detects columns,
        and extracts text in either strict 'line' (Line-by-Line) or 'sentence' mode.
        """
        screen_offset = (0, 0)
        if image is None:
            image, screen_offset = self.capture_screen_with_offset()

        img_w, img_h = image.size

        try:
            res = winocr.recognize_pil_sync(image, self.language)
            raw_text = res.get("text", "")
            ocr_lines = res.get("lines", [])
        except Exception as e:
            raw_text = ""
            ocr_lines = []
            print(f"[OCR Error] {e}")

        # 1. Parse lines with their geometric bounding boxes
        parsed_lines = []
        for line in ocr_lines:
            words = line.get("words", [])
            if not words:
                continue
            x = min(w["bounding_rect"]["x"] for w in words)
            y = min(w["bounding_rect"]["y"] for w in words)
            right = max(w["bounding_rect"]["x"] + w["bounding_rect"]["width"] for w in words)
            bottom = max(w["bounding_rect"]["y"] + w["bounding_rect"]["height"] for w in words)
            line_text = line.get("text", "").strip()

            if line_text:
                parsed_lines.append({
                    "text": line_text,
                    "x": x,
                    "y": y,
                    "w": right - x,
                    "h": bottom - y,
                    "right": right,
                    "bottom": bottom
                })

        # Sort raw parsed lines by vertical position to evaluate gaps
        parsed_lines.sort(key=lambda item: item["y"])

        # 2. Filtering noise, running headers, and running footers
        ui_noise_phrases = [
            "handshake", "permissions", "voice narrator", "kindle voice", "speed & volume",
            "voice profile", "follow-along spotlight", "live page transcript", "notes & summary",
            "settings & keys", "test voice", "click window to link", "step 1", "step 2", "step 3",
            "full permissions", "window calibrated", "high-definition ocr", "connection & permissions",
            "resume bookmark", "save bookmark", "read from cursor", "click text to read",
            "pin on top", "crop area", "find kindle", "prev page", "next page", "read page",
            "no app linked", "target window", "drag a rectangle", "reading area selected"
        ]

        filtered_lines = []

        for idx, pl in enumerate(parsed_lines):
            lower_text = pl["text"].lower()

            # Ignore any text belonging to narrator app UI or connection handshake
            if any(phrase in lower_text for phrase in ui_noise_phrases):
                continue

            if filter_headers:
                # 1. Skip any page number anywhere on the page (top, bottom, or inline)
                if self.is_page_number_text(pl["text"]):
                    continue

                # 2. Skip running titles, book names, and author headers at the top of the screen
                if self.is_running_header_or_title(pl, idx, parsed_lines, img_h):
                    continue

                # 3. Skip footer / progress noise in the bottom margin (bottom 10% of page)
                if pl["bottom"] > (img_h * 0.90):
                    if self.is_page_number_text(pl["text"]):
                        continue
                    if re.match(r"^\s*(?:page\s+\d+|\d+\s*%\s*|loc(?:ation)?\s*[\.:]?\s*\d+|\d+\s+mins?\s+left|\d+\s+hours?\s+left)\s*$", pl["text"], re.IGNORECASE):
                        continue

            filtered_lines.append(pl)

        # 3. Column Layout & Sorting (Recursive XY-Cut & Dynamic Gutter Detection)
        ordered_lines = self._detect_and_order_columns(filtered_lines, img_w, img_h, column_mode)

        # Calculate median font height for style classification
        median_h = 22.0
        if ordered_lines:
            sorted_h = sorted(l["h"] for l in ordered_lines)
            median_h = float(sorted_h[len(sorted_h) // 2])

        # 4. Reading Mode Processing
        if reading_mode == "line":
            # Strict Line-by-Line Reading:
            # 1:1 mapping between physical lines on screen, spoken items, and highlight bounding boxes.
            # Fix dangling hyphenation between adjacent lines so speech flow is completely natural.
            for i in range(len(ordered_lines) - 1):
                cur_text = ordered_lines[i]["text"]
                m_dash = re.search(r'([a-zA-Z]{2,})[-\u2010\u2011\u2012\u2013\u00ad~]\s*$', cur_text)
                if m_dash:
                    prefix = m_dash.group(1)
                    next_text = ordered_lines[i + 1]["text"]
                    m_next = re.match(r'^\s*([a-zA-Z]{2,})\b', next_text)
                    if m_next:
                        suffix = m_next.group(1)
                        full_word = prefix + suffix
                        ordered_lines[i]["text"] = cur_text[:m_dash.start(1)] + full_word
                        rest = next_text[m_next.end():].lstrip()
                        ordered_lines[i + 1]["text"] = rest

            lines_to_read = []
            line_boxes = []
            sentence_styles = []
            for l in ordered_lines:
                clean_l = self.clean_single_line(l["text"])
                if clean_l and len(clean_l) > 1:
                    lines_to_read.append(clean_l)
                    line_boxes.append((float(l["x"]), float(l["y"]), float(l["w"]), float(l["h"])))
                    style = StyleClassifier.classify(clean_l, l["h"], median_h)
                    sentence_styles.append(style)

            cleaned_text = "\n".join(lines_to_read)
            return {
                "raw_text": raw_text,
                "cleaned_text": cleaned_text,
                "sentences": lines_to_read,
                "sentence_boxes": line_boxes,
                "sentence_styles": sentence_styles,
                "screen_offset": screen_offset,
                "image": image,
                "reading_mode": "line",
            }
        else:
            # Natural Sentence Mode
            raw_combined = "\n".join(l["text"] for l in ordered_lines)
            cleaned_text = self.clean_text(raw_combined)
            sentences = self.split_into_sentences(cleaned_text)
            sentence_boxes = self._map_sentences_to_boxes(sentences, ordered_lines, img_w)
            sentence_styles = [StyleClassifier.classify(s, 22.0, median_h) for s in sentences]

            return {
                "raw_text": raw_text,
                "cleaned_text": cleaned_text,
                "sentences": sentences,
                "sentence_boxes": sentence_boxes,
                "sentence_styles": sentence_styles,
                "screen_offset": screen_offset,
                "image": image,
                "reading_mode": "sentence",
            }

    def find_sentence_index_at_point(
        self,
        screen_x: int,
        screen_y: int,
        sentence_boxes: typing.List[typing.Tuple[float, float, float, float]],
        screen_offset: typing.Tuple[int, int]
    ) -> int:
        """
        Given global screen coordinates (screen_x, screen_y) of mouse pointer,
        finds the index of the sentence whose bounding box contains or is closest to that point.
        """
        if not sentence_boxes:
            return 0

        ox, oy = screen_offset
        rel_x = screen_x - ox
        rel_y = screen_y - oy

        # 1. Check direct containment (with generous horizontal padding)
        for i, (bx, by, bw, bh) in enumerate(sentence_boxes):
            if (by - 6) <= rel_y <= (by + bh + 8):
                if (bx - 20) <= rel_x <= (bx + bw + 20):
                    return i

        # 2. Check closest proximity (vertical distance weighted higher)
        best_idx = 0
        min_dist = float("inf")
        for i, (bx, by, bw, bh) in enumerate(sentence_boxes):
            cy = by + (bh / 2.0)
            cx = bx + (bw / 2.0)
            dist = ((rel_y - cy) ** 2) * 4.0 + ((rel_x - cx) ** 2)
            if dist < min_dist:
                min_dist = dist
                best_idx = i

        return best_idx

