"""
Verification Test Suite for Kindle Screen Reader Fixes:
1. Single page turn (no skipping multiple pages).
2. Debounce cooldown timer.
3. Zero skipped content lines:
   - Line 0 (first line on page) never dropped.
   - Percentage sentences (e.g. '90% of attacks...') never dropped.
   - Bullet points and questions never dropped.
   - Technical lines near the bottom (AES-256, Port 443, Figure 1) never dropped.
4. Auto-link to Kindle and bookmark recovery on app reopening.
"""

import unittest
import time
from unittest.mock import MagicMock, patch
from ocr_engine import OCREngine, StyleClassifier, WindowInfo
from page_turner import PageTurner
from bookmark_manager import BookmarkManager


class TestPageTurnerSingleAction(unittest.TestCase):
    def setUp(self):
        self.turner = PageTurner(turn_delay=0.01)
        self.turner.min_turn_interval = 0.5  # 500ms debounce
        self.turner.target_hwnd = 12345
        self.turner.click_target_region = (100, 100, 800, 600)

    @patch("page_turner.pyautogui.click")
    @patch("page_turner.pyautogui.press")
    @patch("page_turner.user32.PostMessageW")
    @patch("page_turner.user32.IsWindow", return_value=True)
    def test_turn_next_page_single_action(self, mock_is_window, mock_post, mock_press, mock_click):
        """Verify that turn_next_page executes only ONE turn action, not multiple."""
        res = self.turner.turn_next_page()
        self.assertTrue(res)

        # Priority 1 is margin click when bounds exist
        self.assertEqual(mock_click.call_count, 1)
        # Keystrokes must NOT be pressed when click succeeded!
        mock_press.assert_not_called()
        mock_post.assert_not_called()

    @patch("page_turner.pyautogui.click")
    @patch("page_turner.pyautogui.press")
    @patch("page_turner.user32.PostMessageW")
    @patch("page_turner.user32.IsWindow", return_value=True)
    def test_turn_next_page_debounce(self, mock_is_window, mock_post, mock_press, mock_click):
        """Verify that rapid successive calls within min_turn_interval are debounced."""
        # First call: should fire
        self.turner.turn_next_page()
        self.assertEqual(mock_click.call_count, 1)

        # Second call immediately after: should be debounced
        self.turner.turn_next_page()
        self.assertEqual(mock_click.call_count, 1)  # Still 1, did not fire again!

        # Wait past cooldown
        time.sleep(0.55)
        self.turner.turn_next_page()
        self.assertEqual(mock_click.call_count, 2)  # Fired second time after cooldown

    @patch("page_turner.pyautogui.click")
    @patch("page_turner.pyautogui.press")
    @patch("page_turner.user32.PostMessageW")
    @patch("page_turner.user32.IsWindow", return_value=False)
    def test_turn_next_page_keystroke_fallback(self, mock_is_window, mock_post, mock_press, mock_click):
        """When no reading bounds exist, single keystroke fallback must be used."""
        self.turner.click_target_region = None
        self.turner.target_hwnd = None

        with patch.object(self.turner, "get_reading_bounds", return_value=None):
            self.turner.turn_next_page()
            self.assertEqual(mock_press.call_count, 1)
            mock_click.assert_not_called()


class TestOCREngineZeroSkippedLines(unittest.TestCase):
    def setUp(self):
        self.ocr = OCREngine()
        self.ocr.target_window_title = "CompTIA Security+ SY0-701 Study Guide - Kindle for PC"

    def test_page_number_detection_strictness(self):
        """Verify only genuine page numbers are matched, never content sentences."""
        # Valid page numbers:
        self.assertTrue(self.ocr.is_page_number_text("142"))
        self.assertTrue(self.ocr.is_page_number_text("Page 142"))
        self.assertTrue(self.ocr.is_page_number_text("page 142 of 500"))
        self.assertTrue(self.ocr.is_page_number_text("- 42 -"))
        self.assertTrue(self.ocr.is_page_number_text("15%"))
        self.assertTrue(self.ocr.is_page_number_text("loc 1245"))
        self.assertTrue(self.ocr.is_page_number_text("14 mins left in book"))

        # Must NOT match legitimate content:
        self.assertFalse(self.ocr.is_page_number_text("90% of attacks start with phishing emails."))
        self.assertFalse(self.ocr.is_page_number_text("100% compliance is required across all departments."))
        self.assertFalse(self.ocr.is_page_number_text("• User provisioning: Automating the process of creating accounts"))
        self.assertFalse(self.ocr.is_page_number_text("AES-256 provides strong encryption for data at rest."))
        self.assertFalse(self.ocr.is_page_number_text("Port 443 is used for secure HTTPS traffic."))
        self.assertFalse(self.ocr.is_page_number_text("What is the primary purpose of multi-factor authentication?"))

    def test_running_header_never_drops_first_line(self):
        """Verify line 0 of a page is NEVER dropped just because it is short or the first line."""
        img_h = 1000.0
        all_lines = [
            {"text": "Authentication methods", "x": 100, "y": 80, "w": 200, "h": 22, "bottom": 102},
            {"text": "Users must verify their identity using multiple factors.", "x": 100, "y": 140, "w": 500, "h": 22, "bottom": 162}
        ]

        # Line 0 is a heading or topic sentence: must NOT be dropped!
        is_header = self.ocr.is_running_header_or_title(all_lines[0], 0, all_lines, img_h)
        self.assertFalse(is_header)

    def test_running_header_never_drops_bullets_or_questions(self):
        """Verify bullet points and questions in top area are preserved."""
        img_h = 1000.0
        all_lines = [
            {"text": "• User provisioning: Automating accounts", "x": 100, "y": 50, "w": 300, "h": 22, "bottom": 72},
            {"text": "What is the role of an IdP?", "x": 100, "y": 80, "w": 250, "h": 22, "bottom": 102},
            {"text": "1. Verify user identity against Active Directory.", "x": 100, "y": 110, "w": 350, "h": 22, "bottom": 132}
        ]

        for idx, line in enumerate(all_lines):
            self.assertFalse(self.ocr.is_running_header_or_title(line, idx, all_lines, img_h))

    def test_running_header_filters_actual_window_title(self):
        """Verify actual running title at the very top is properly identified."""
        img_h = 1000.0
        title_line = {"text": "CompTIA Security+ SY0-701 Study Guide", "x": 200, "y": 30, "w": 400, "h": 20, "bottom": 50}
        all_lines = [title_line]
        self.assertTrue(self.ocr.is_running_header_or_title(title_line, 0, all_lines, img_h))

    def test_bottom_margin_preserves_technical_acronyms(self):
        """Verify lines in bottom area with numbers (AES-256, Figure 1) are preserved."""
        img_w, img_h = 800, 1000
        # Simulated lines near bottom
        simulated_lines = [
            {"text": "Figure 3-2: TLS 1.3 Handshake Architecture", "x": 100, "y": 910, "w": 300, "h": 20, "right": 400, "bottom": 930},
            {"text": "AES-256 ensures maximum cipher strength.", "x": 100, "y": 940, "w": 320, "h": 20, "right": 420, "bottom": 960},
            {"text": "142", "x": 380, "y": 970, "w": 40, "h": 18, "right": 420, "bottom": 988}  # Page number
        ]

        # Test filtering logic directly
        kept = []
        for pl in simulated_lines:
            # Check bottom margin check from extract_text
            if pl["bottom"] > (img_h * 0.90):
                if self.ocr.is_page_number_text(pl["text"]):
                    continue
            kept.append(pl["text"])

        self.assertIn("Figure 3-2: TLS 1.3 Handshake Architecture", kept)
        self.assertIn("AES-256 ensures maximum cipher strength.", kept)
        self.assertNotIn("142", kept)


class TestAppReopenAndBookmark(unittest.TestCase):
    def test_bookmark_matching_and_recovery(self):
        """Verify bookmark manager recovers CompTIA Security+ study guide position."""
        bm_mgr = BookmarkManager()
        # Retrieve latest bookmark
        latest = bm_mgr.get_bookmark_for_book("")
        self.assertIsNotNone(latest)
        self.assertIn("book_title", latest)

        # Verify fuzzy sentence match
        sentences = [
            "CompTIA Security+ Get Certified Get Ahead Study Guide.",
            "managing various security-related tasks.",
            "As you prepare for the Security+ exam, you should be familiar with the use cases.",
            "This helps maintain a standardized, secure environment while reducing the administrative overhead.",
            "Next topic covers access controls."
        ]
        target = "This helps maintain a standardized, secure environment while reducing the"
        idx = bm_mgr.find_best_match_index(sentences, target, saved_index=3)
        self.assertEqual(idx, 3)


if __name__ == "__main__":
    unittest.main()
