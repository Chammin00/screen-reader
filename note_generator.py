"""
Smart Note and Summary Generator for Kindle Narrator.
Extracts structured study notes, chapter summaries, key takeaways, vocabulary,
and memorable quotes from read text both offline (heuristic NLP) and via optional AI APIs.
"""

import collections
import datetime
import json
import os
import re
import typing
import requests


class NoteGenerator:
    def __init__(self):
        self.session_pages: typing.List[typing.Dict[str, typing.Any]] = []
        self.api_provider: str = "none"  # "none", "gemini", "openai", "ollama"
        self.api_key: str = ""
        self.api_model: str = "gemini-1.5-flash"
        self.ollama_endpoint: str = "http://localhost:11434/api/generate"

    def add_page_text(self, page_text: str, page_number: typing.Optional[int] = None):
        """Add page text to the accumulated reading session."""
        if not page_text or not page_text.strip():
            return
        self.session_pages.append({
            "page_num": page_number or (len(self.session_pages) + 1),
            "timestamp": datetime.datetime.now().strftime("%H:%M:%S"),
            "text": page_text.strip()
        })

    def clear_session(self):
        """Clear all session pages."""
        self.session_pages.clear()

    def get_full_session_text(self) -> str:
        """Combines all pages read in this session into a single text."""
        return "\n\n".join(f"[Page {p['page_num']}]\n{p['text']}" for p in self.session_pages)

    def generate_local_notes(self, text: str, title: str = "Kindle Reading Session") -> str:
        """
        Extracts structured notes locally without external API calls:
        - Executive Summary (Sentence scoring & ranking)
        - Key Takeaways (Top informational points)
        - Key Concepts / Entities & Mentions
        - Notable Quotes
        """
        if not text or len(text.strip()) < 30:
            return "Not enough text captured to generate notes. Please read a page first."

        lines = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if s.strip()]
        if not lines:
            return text

        # Frequency scoring for sentence importance
        words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
        stopwords = {
            "the", "and", "that", "have", "for", "not", "with", "you", "this", "but",
            "his", "from", "they", "say", "her", "she", "will", "one", "all", "would",
            "there", "their", "what", "out", "about", "who", "get", "which", "when",
            "make", "can", "like", "time", "just", "him", "know", "take", "people",
            "into", "year", "your", "good", "some", "could", "them", "see", "other",
            "than", "then", "now", "look", "only", "come", "its", "over", "think",
            "also", "back", "after", "use", "two", "how", "our", "work", "first",
            "well", "way", "even", "new", "want", "because", "any", "these", "give",
            "day", "most", "us", "are", "was", "were", "been", "had", "has", "did"
        }
        filtered_words = [w for w in words if w not in stopwords]
        word_freq = collections.Counter(filtered_words)

        # Score sentences
        sentence_scores = []
        for s in lines:
            s_words = re.findall(r'\b[a-zA-Z]{3,}\b', s.lower())
            if len(s_words) < 4:
                continue
            score = sum(word_freq.get(w, 0) for w in s_words) / (len(s_words) ** 0.5)
            sentence_scores.append((score, s))

        sentence_scores.sort(key=lambda x: x[0], reverse=True)
        top_sentences = [s for _, s in sentence_scores[:min(5, len(sentence_scores))]]

        # Key entities / Capitalized terms (Proper nouns / Concepts)
        proper_nouns = re.findall(r'\b[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})*\b', text)
        clean_entities = [e for e in proper_nouns if e.lower() not in stopwords and len(e) > 3]
        entity_freq = collections.Counter(clean_entities)
        top_entities = [e for e, count in entity_freq.most_common(6)]

        # Quotes or high impact sentences
        quotes = re.findall(r'["“][^"”]{10,200}["”]', text)

        # Build Markdown Document
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        doc = []
        doc.append(f"# 📖 {title} - Notes & Summary")
        doc.append(f"*Generated on {now_str}*\n")
        doc.append("---")

        doc.append("## 📌 Executive Summary")
        if top_sentences:
            doc.append(f"> {top_sentences[0]}")
            if len(top_sentences) > 1:
                doc.append(f"\n{top_sentences[1]}")
        else:
            doc.append(text[:200] + "...")

        doc.append("\n## 💡 Key Takeaways & Highlights")
        for s in top_sentences[1:4]:
            doc.append(f"- {s}")

        if top_entities:
            doc.append("\n## 🏷️ Key Concepts & Entities")
            for ent in top_entities:
                doc.append(f"- **{ent}**")

        if quotes:
            doc.append("\n## 💬 Notable Quotes")
            for q in quotes[:3]:
                doc.append(f"> {q}")

        doc.append("\n## 📝 Raw Captured Text")
        doc.append("```text")
        doc.append(text[:1000] + ("..." if len(text) > 1000 else ""))
        doc.append("```")

        return "\n".join(doc)

    def generate_ai_notes(self, text: str, prompt_style: str = "summary") -> str:
        """Generate enhanced notes using user's AI API key (Gemini, OpenAI, or Ollama)."""
        if not text:
            return "No text provided."

        prompt_instructions = {
            "summary": "Create a clear, structured summary with key takeaways and major themes.",
            "study": "Create comprehensive study notes with definitions, bullet points, and flashcard-style Q&As.",
            "characters": "Analyze key characters, motivations, relationships, and major plot developments.",
            "quotes": "Extract and analyze the most significant quotes and their thematic importance."
        }
        instruction = prompt_instructions.get(prompt_style, prompt_instructions["summary"])

        system_prompt = (
            f"You are an expert reading assistant and literary scholar. {instruction}\n"
            f"Format your response cleanly in GitHub-flavored Markdown with headers, bullet points, and callouts.\n\n"
            f"Book Content:\n{text}"
        )

        try:
            if self.api_provider == "gemini" and self.api_key:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.api_model}:generateContent?key={self.api_key}"
                payload = {
                    "contents": [{"parts": [{"text": system_prompt}]}]
                }
                res = requests.post(url, json=payload, timeout=25)
                data = res.json()
                return data["candidates"][0]["content"]["parts"][0]["text"]

            elif self.api_provider == "openai" and self.api_key:
                url = "https://api.openai.com/v1/chat/completions"
                headers = {"Authorization": f"Bearer {self.api_key}"}
                payload = {
                    "model": self.api_model or "gpt-4o-mini",
                    "messages": [{"role": "user", "content": system_prompt}]
                }
                res = requests.post(url, headers=headers, json=payload, timeout=25)
                data = res.json()
                return data["choices"][0]["message"]["content"]

            elif self.api_provider == "ollama":
                url = self.ollama_endpoint
                payload = {
                    "model": self.api_model or "llama3",
                    "prompt": system_prompt,
                    "stream": False
                }
                res = requests.post(url, json=payload, timeout=30)
                data = res.json()
                return data.get("response", "No response from Ollama")

            else:
                # Fallback to smart local notes
                return self.generate_local_notes(text)

        except Exception as e:
            print(f"[AI Note Gen Error] {e}")
            return f"{self.generate_local_notes(text)}\n\n*(AI API Note: {e}. Defaulted to local analysis.)*"

    def export_notes(self, file_path: str, content: str) -> bool:
        """Save notes to file (.md or .txt)."""
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
            return True
        except Exception as e:
            print(f"[Export Error] {e}")
            return False
