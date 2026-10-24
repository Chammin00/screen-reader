"""
Bookmark Manager for Kindle Voice Narrator.
Persists reading bookmarks to a local JSON file (bookmarks.json) and provides
smart matching to resume reading at the exact sentence after disconnection or app restart.
"""

import json
import os
import time
import typing
from difflib import SequenceMatcher


class BookmarkManager:
    def __init__(self, storage_path: typing.Optional[str] = None):
        if storage_path is None:
            # Save in current working directory
            self.storage_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bookmarks.json")
        else:
            self.storage_path = storage_path

        self.bookmarks: typing.Dict[str, typing.Any] = {}
        self.load_bookmarks()

    def load_bookmarks(self) -> typing.Dict[str, typing.Any]:
        """Loads bookmarks from local JSON file."""
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    self.bookmarks = json.load(f)
            except Exception as e:
                print(f"[BookmarkManager Load Error] {e}")
                self.bookmarks = {}
        else:
            self.bookmarks = {}
        return self.bookmarks

    def save_bookmark(
        self,
        book_title: str,
        sentence_index: int,
        sentence_text: str,
        page_snippet: str = "",
        region: typing.Optional[typing.Tuple[int, int, int, int]] = None
    ) -> typing.Dict[str, typing.Any]:
        """
        Saves or updates a bookmark for a given book/window title and the latest overall bookmark.
        """
        clean_title = (book_title or "Default").strip()
        data = {
            "book_title": clean_title,
            "sentence_index": int(sentence_index),
            "sentence_text": sentence_text.strip(),
            "page_snippet": (page_snippet[:300] if page_snippet else "").strip(),
            "region": list(region) if region else None,
            "timestamp": time.time(),
            "time_str": time.strftime("%Y-%m-%d %H:%M:%S")
        }

        # Store by specific title and as latest
        self.bookmarks[clean_title] = data
        self.bookmarks["_LATEST_"] = data

        self._flush_to_disk()
        return data

    def get_latest_bookmark(self) -> typing.Optional[typing.Dict[str, typing.Any]]:
        """Returns the most recent bookmark saved across any book."""
        return self.bookmarks.get("_LATEST_")

    def get_bookmark_for_book(self, book_title: str) -> typing.Optional[typing.Dict[str, typing.Any]]:
        """Returns bookmark specific to a book or window title."""
        clean_title = (book_title or "Default").strip()
        if clean_title in self.bookmarks:
            return self.bookmarks[clean_title]
        # Partial title match
        for k, v in self.bookmarks.items():
            if k != "_LATEST_" and (k.lower() in clean_title.lower() or clean_title.lower() in k.lower()):
                return v
        return self.get_latest_bookmark()

    def find_best_match_index(
        self,
        sentences: typing.List[str],
        target_sentence: str,
        saved_index: int = 0
    ) -> int:
        """
        Finds the index of the sentence on the page that best matches the target sentence.
        Returns 0 if no good match is found.
        """
        if not sentences or not target_sentence:
            return 0

        target_clean = target_sentence.strip().lower()

        # 1. Exact match
        for i, s in enumerate(sentences):
            if s.strip().lower() == target_clean:
                return i

        # 2. Substring or prefix match
        target_prefix = target_clean[:30]
        for i, s in enumerate(sentences):
            s_lower = s.strip().lower()
            if target_prefix in s_lower or (len(s_lower) > 15 and s_lower[:30] in target_clean):
                return i

        # 3. Fuzzy similarity matching
        best_idx = -1
        best_score = 0.0

        for i, s in enumerate(sentences):
            score = SequenceMatcher(None, target_clean, s.strip().lower()).ratio()
            if score > best_score:
                best_score = score
                best_idx = i

        if best_score >= 0.55:
            return best_idx

        # 4. Fallback to saved_index if valid
        if 0 <= saved_index < len(sentences):
            return saved_index

        return 0

    def _flush_to_disk(self):
        try:
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(self.bookmarks, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[BookmarkManager Save Error] {e}")
