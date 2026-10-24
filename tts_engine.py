"""
Neural TTS and Playback Engine for Kindle Narrator.
Provides high-fidelity voice narration with Afro-European Woman presets,
speed/pitch adjustment, live sentence synchronization, and playback control.
"""

import asyncio
import io
import os
import re
import tempfile
import threading
import time
import typing
import edge_tts
import edge_tts.communicate
import edge_tts.constants
import pygame

try:
    import pyttsx3
except ImportError:
    pyttsx3 = None

# Update WSS_URL to use the current Microsoft Edge online endpoint (api.msedgeservices.com)
# Since October 2026, the legacy speech.platform.bing.com returns 403 Forbidden.
EDGE_TTS_ACTIVE_WSS_URL = (
    "wss://api.msedgeservices.com/tts/cognitiveservices/websocket/v1"
    f"?Ocp-Apim-Subscription-Key={edge_tts.constants.TRUSTED_CLIENT_TOKEN}"
)
edge_tts.constants.WSS_URL = EDGE_TTS_ACTIVE_WSS_URL
edge_tts.communicate.WSS_URL = EDGE_TTS_ACTIVE_WSS_URL

# Curated voice presets focusing on Afro-European woman voices & popular options
VOICE_PRESETS = [
    {
        "id": "en-NG-EzinneNeural",
        "name": "Afro-European / Nigerian English Woman (Ezinne - Warm & Expressive)",
        "gender": "Female",
        "region": "Afro-European"
    },
    {
        "id": "fr-FR-VivienneMultilingualNeural",
        "name": "Afro-European Multilingual Woman (Vivienne - European Accent)",
        "gender": "Female",
        "region": "Afro-European"
    },
    {
        "id": "en-ZA-LeahNeural",
        "name": "South African English Woman (Leah - Clear & Engaging)",
        "gender": "Female",
        "region": "African"
    },
    {
        "id": "en-KE-AsiliaNeural",
        "name": "Kenyan English Woman (Asilia - Natural & Smooth)",
        "gender": "Female",
        "region": "African"
    },
    {
        "id": "en-GB-SoniaNeural",
        "name": "British European Woman (Sonia - Sophisticated)",
        "gender": "Female",
        "region": "European"
    },
    {
        "id": "en-GB-LibbyNeural",
        "name": "British European Woman (Libby - Storyteller)",
        "gender": "Female",
        "region": "European"
    },
    {
        "id": "en-US-JennyNeural",
        "name": "American English Woman (Jenny - Friendly)",
        "gender": "Female",
        "region": "US"
    },
]


# Natural speech prosody profiles for structured document reading (Q&A, dialogue, headings)
STYLE_PROSODY = {
    "QUESTION": {"pitch": "+5Hz", "rate_factor": 1.0, "pause_ms": 400},
    "ANSWER": {"pitch": "-2Hz", "rate_factor": 0.96, "pause_ms": 350},
    "OPTION": {"pitch": "+2Hz", "rate_factor": 1.0, "pause_ms": 220},
    "HEADING": {"pitch": "+2Hz", "rate_factor": 0.92, "pause_ms": 450},
    "QUOTE": {"pitch": "+3Hz", "rate_factor": 1.0, "pause_ms": 200},
    "BODY": {"pitch": "+0Hz", "rate_factor": 1.0, "pause_ms": 80},
}


class TTSEngine:
    def __init__(self, voice_id: str = "en-NG-EzinneNeural", speed_rate: float = 1.0, volume_level: float = 1.0):
        self.voice_id = voice_id
        self.speed_rate = speed_rate  # Multiplier: 1.0 = normal, 1.25 = +25%, 0.8 = -20%
        self.volume_level = volume_level  # 0.0 to 1.0
        self.pitch = "+0Hz"
        self.volume = "+0%"

        # State flags
        self.is_playing = False
        self.is_paused = False
        self.stop_requested = False
        self.current_sentence_index = 0
        self.sentences: typing.List[str] = []
        self.styles: typing.List[str] = []
        self.style_profiles = STYLE_PROSODY
        self.style_modulation_enabled: bool = True

        # Audio temp cache directory
        self.temp_dir = tempfile.mkdtemp(prefix="kindle_narrator_")

        # Prefetch background pipeline to eliminate pauses between sentences
        self._cached_audio: typing.Dict[int, str] = {}
        self._prefetch_lock = threading.Lock()
        self._prefetch_event = threading.Event()
        self._prefetch_thread: typing.Optional[threading.Thread] = None

        # Callbacks
        self.on_sentence_start: typing.Optional[typing.Callable[[int, str], None]] = None
        self.on_sentence_end: typing.Optional[typing.Callable[[int], None]] = None
        self.on_page_finished: typing.Optional[typing.Callable[[], None]] = None
        self.on_error: typing.Optional[typing.Callable[[str], None]] = None

        # Lock & Thread
        self._thread: typing.Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # Offline fallback TTS engine
        self._offline_lock = threading.Lock()

        # Initialize pygame mixer
        self._init_mixer()

    def _init_mixer(self):
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=1024)
        except Exception as e:
            print(f"[Mixer Init Warning] {e}")

    def format_rate_string(self, multiplier: float) -> str:
        """Converts float multiplier (e.g. 1.25 -> '+25%', 0.8 -> '-20%') for edge-tts."""
        pct = int(round((multiplier - 1.0) * 100))
        if pct >= 0:
            return f"+{pct}%"
        else:
            return f"{pct}%"

    def set_speed(self, multiplier: float):
        """Update speed rate dynamically."""
        self.speed_rate = max(0.5, min(3.0, float(multiplier)))

    def set_volume(self, level: float):
        """Update audio playback volume (0.0 to 1.0) dynamically."""
        self.volume_level = max(0.0, min(1.0, float(level)))
        try:
            if pygame.mixer.get_init():
                pygame.mixer.music.set_volume(self.volume_level)
        except Exception:
            pass

    def set_voice(self, voice_id: str):
        """Update voice model."""
        self.voice_id = voice_id

    def sanitize_for_tts(self, text: str) -> str:
        """Cleans internal newlines, double punctuation, and OCR glitches for fluent speech."""
        if not text:
            return ""
        # 1. Collapse all internal line breaks and whitespace to a single space
        s = re.sub(r"[\r\n]+", " ", text)
        s = re.sub(r"\s+", " ", s).strip()

        # 2. Fix conflicting and double punctuation (e.g. 'traffic,.' -> 'traffic.')
        s = re.sub(r'[,;]\s*[.](?=\s+[a-z])', ',', s)
        s = re.sub(r'[,;]\s*[.]', '.', s)
        s = re.sub(r'[.]\s*[,;](?=\s+[a-z])', ',', s)
        s = re.sub(r'[.]\s*[,;]', '.', s)
        s = re.sub(r',\s*,+', ',', s)
        s = re.sub(r'(?<!\.)\.\.(?!\.)', '.', s)

        # 3. Clean dashes after commas or semicolons
        s = re.sub(r'([,;:!?])\s*[-–—]+', r'\1', s)
        s = re.sub(r'[-–—]+\s*([,;:!?])', r'\1', s)

        # 4. Remove space before punctuation
        s = re.sub(r'\s+([,.!?;:])', r'\1', s)
        return s

    async def _synthesize_text_to_file(self, text: str, output_path: str, style: str = "BODY"):
        """Synthesize a sentence to an audio file using Edge-TTS with writing style prosody."""
        clean_text = self.sanitize_for_tts(text)
        if not clean_text:
            clean_text = " "

        pitch_val = self.pitch
        rate_val = self.format_rate_string(self.speed_rate)

        if self.style_modulation_enabled:
            if style == "QUESTION":
                # Inquisitive upward prompt pitch
                pitch_val = "+5Hz"
            elif style == "ANSWER":
                # Grounded explanatory pitch and slightly measured cadence
                pitch_val = "-2Hz"
                rate_val = self.format_rate_string(max(0.5, self.speed_rate * 0.96))
            elif style == "OPTION":
                # Crisp option articulation
                pitch_val = "+2Hz"
            elif style == "HEADING":
                # Prominent, dignified tone
                pitch_val = "+2Hz"
                rate_val = self.format_rate_string(max(0.5, self.speed_rate * 0.92))
            elif style == "QUOTE":
                # Expressive dialogue pitch
                pitch_val = "+3Hz"

        communicate = edge_tts.Communicate(
            text=clean_text,
            voice=self.voice_id,
            rate=rate_val,
            pitch=pitch_val,
            volume=self.volume
        )
        await communicate.save(output_path)

    def _synthesize_offline_fallback(self, text: str, output_path: str) -> bool:
        """Fallback to local Windows SAPI / pyttsx3 speech synthesis if online synthesis fails."""
        if pyttsx3 is None:
            return False
        with self._offline_lock:
            try:
                engine = pyttsx3.init()
                # Adjust speaking rate (normal is ~200 wpm)
                base_rate = 200
                engine.setProperty('rate', int(base_rate * self.speed_rate))
                # Choose female voice if available
                voices = engine.getProperty('voices')
                for v in voices:
                    if 'zira' in v.name.lower() or 'female' in v.name.lower():
                        engine.setProperty('voice', v.id)
                        break
                wav_path = output_path
                if not wav_path.lower().endswith(".wav"):
                    wav_path = output_path + ".wav"
                engine.save_to_file(text, wav_path)
                engine.runAndWait()
                if os.path.exists(wav_path) and os.path.getsize(wav_path) > 0:
                    if wav_path != output_path:
                        try:
                            if os.path.exists(output_path):
                                os.remove(output_path)
                            os.rename(wav_path, output_path)
                        except Exception:
                            return False
                    return True
            except Exception as e:
                print(f"[Offline TTS Fallback Error] {e}")
        return False

    def synthesize_sentence(self, text: str, output_path: str, style: str = "BODY"):
        """Synchronous wrapper for Edge-TTS synthesis with offline fallback."""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self._synthesize_text_to_file(text, output_path, style=style))
            finally:
                loop.close()
        except Exception as e:
            print(f"[Edge-TTS Synthesis Warning] {e}. Attempting offline fallback...")
            success = self._synthesize_offline_fallback(text, output_path)
            if not success:
                raise e

    def speak_sentences(
        self,
        sentences: typing.List[str],
        start_index: int = 0,
        styles: typing.Optional[typing.List[str]] = None
    ):
        """Starts background prefetch and playback threads for seamless zero-lag narration."""
        self.stop()

        with self._lock:
            self.sentences = [self.sanitize_for_tts(s) for s in sentences if s and s.strip()]
            self.styles = list(styles) if styles else ["BODY"] * len(self.sentences)
            self.current_sentence_index = start_index
            self.stop_requested = False
            self.is_paused = False
            self.is_playing = True

        with self._prefetch_lock:
            self._cached_audio.clear()
            self._prefetch_event.clear()

        # Start prefetcher and playback workers
        self._prefetch_thread = threading.Thread(target=self._prefetch_worker, daemon=True)
        self._prefetch_thread.start()

        self._thread = threading.Thread(target=self._playback_worker, daemon=True)
        self._thread.start()

    def _get_audio_for_sentence(self, idx: int, sentence: str) -> typing.Optional[str]:
        """Ensures audio for a sentence is synthesized and returns its path safely."""
        with self._prefetch_lock:
            cached = self._cached_audio.get(idx)
            if cached and os.path.exists(cached):
                return cached

        style = self.styles[idx] if (self.styles and idx < len(self.styles)) else "BODY"
        audio_file = os.path.join(self.temp_dir, f"sentence_{idx}_{int(self.speed_rate*100)}_{style.lower()}.mp3")
        try:
            if not os.path.exists(audio_file):
                self.synthesize_sentence(sentence, audio_file, style=style)
            with self._prefetch_lock:
                self._cached_audio[idx] = audio_file
            return audio_file
        except Exception as e:
            print(f"[TTS Synthesis Error] Sentence {idx}: {e}")
            return None

    def _prefetch_worker(self):
        """Background thread that pre-synthesizes upcoming sentences into cache."""
        PREFETCH_AHEAD = 3
        while self.is_playing and not self.stop_requested:
            with self._lock:
                curr_idx = self.current_sentence_index
                total = len(self.sentences)
                sentences_snapshot = list(self.sentences)

            # Find unbuffered upcoming sentences within lookahead window
            needed = []
            for i in range(curr_idx + 1, min(curr_idx + 1 + PREFETCH_AHEAD, total)):
                with self._prefetch_lock:
                    if i not in self._cached_audio:
                        needed.append((i, sentences_snapshot[i]))

            if not needed:
                self._prefetch_event.wait(timeout=0.2)
                self._prefetch_event.clear()
                continue

            target_idx, target_sent = needed[0]
            if self.stop_requested or not self.is_playing:
                break

            self._get_audio_for_sentence(target_idx, target_sent)
            time.sleep(0.02)

    def _playback_worker(self):
        """Plays audio sequentially from prefetch cache with near-zero latency between sentences."""
        if not self.sentences:
            self.is_playing = False
            return

        total_sentences = len(self.sentences)
        idx = self.current_sentence_index
        sentences_played_count = 0
        consecutive_errors = 0

        while idx < total_sentences:
            if self.stop_requested:
                break

            sentence = self.sentences[idx]
            self.current_sentence_index = idx

            # Signal prefetcher to fetch subsequent sentences
            self._prefetch_event.set()

            # Retrieve prefetched audio (or synthesize immediately if not cached yet)
            audio_file = self._get_audio_for_sentence(idx, sentence)

            if self.stop_requested:
                break

            if not audio_file or not os.path.exists(audio_file):
                consecutive_errors += 1
                if consecutive_errors >= 3 and sentences_played_count == 0:
                    print("[Playback Error] Multiple audio synthesis failures. Halting to avoid false page turn.")
                    if self.on_error:
                        try:
                            self.on_error("Unable to synthesize audio. Check network connection.")
                        except Exception:
                            pass
                    break
                idx += 1
                continue

            consecutive_errors = 0

            # Fire sentence start callback
            if self.on_sentence_start:
                try:
                    self.on_sentence_start(idx, sentence)
                except Exception as e:
                    print(f"[Callback Error] {e}")

            # Play audio file via pygame mixer
            try:
                self._init_mixer()
                pygame.mixer.music.load(audio_file)
                pygame.mixer.music.play()

                while pygame.mixer.music.get_busy() or self.is_paused:
                    if self.stop_requested:
                        pygame.mixer.music.stop()
                        break

                    if self.is_paused:
                        pygame.mixer.music.pause()
                        while self.is_paused and not self.stop_requested:
                            time.sleep(0.05)
                        if not self.stop_requested:
                            pygame.mixer.music.unpause()

                    time.sleep(0.02)

                try:
                    pygame.mixer.music.unload()
                except Exception:
                    pass

                sentences_played_count += 1

            except Exception as e:
                print(f"[Playback Error] {e}")

            if self.stop_requested:
                break

            # Style-aware intelligent pauses (Q&A pacing, choice gaps, heading pauses)
            if self.style_modulation_enabled and self.styles and idx < len(self.styles):
                curr_style = self.styles[idx]
                next_style = self.styles[idx + 1] if (idx + 1) < len(self.styles) else "BODY"
                if curr_style == "QUESTION":
                    time.sleep(0.40)
                elif curr_style == "OPTION" and next_style == "OPTION":
                    time.sleep(0.22)
                elif next_style == "ANSWER":
                    time.sleep(0.35)
                elif curr_style == "HEADING":
                    time.sleep(0.30)
                else:
                    time.sleep(0.06)
            else:
                time.sleep(0.06)

            # Fire sentence end callback
            if self.on_sentence_end:
                try:
                    self.on_sentence_end(idx)
                except Exception as e:
                    print(f"[Callback Error] {e}")

            # Evict older cached audio from disk
            old_idx = idx - 2
            if old_idx >= 0:
                with self._prefetch_lock:
                    old_path = self._cached_audio.pop(old_idx, None)
                    if old_path and os.path.exists(old_path):
                        try:
                            os.remove(old_path)
                        except Exception:
                            pass

            idx += 1

        with self._lock:
            self.is_playing = False

        # Fire page finished callback ONLY if sentences were actually played
        if not self.stop_requested and idx >= total_sentences and sentences_played_count > 0:
            if self.on_page_finished:
                try:
                    self.on_page_finished()
                except Exception as e:
                    print(f"[Page Finished Callback Error] {e}")

    def pause(self):
        """Pause playback."""
        self.is_paused = True

    def resume(self):
        """Resume playback."""
        self.is_paused = False

    def toggle_pause(self):
        """Toggle between pause and resume."""
        if self.is_paused:
            self.resume()
        else:
            self.pause()

    def stop(self):
        """Stop playback immediately and cancel prefetcher."""
        self.stop_requested = True
        self.is_paused = False
        self._prefetch_event.set()
        try:
            if pygame.mixer.get_init():
                pygame.mixer.music.stop()
        except Exception:
            pass

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.6)
        if self._prefetch_thread and self._prefetch_thread.is_alive():
            self._prefetch_thread.join(timeout=0.6)

        with self._prefetch_lock:
            self._cached_audio.clear()

        self.is_playing = False

    def skip_next(self):
        """Skip to next sentence."""
        if self.is_playing and self.current_sentence_index + 1 < len(self.sentences):
            next_idx = self.current_sentence_index + 1
            sentences_copy = list(self.sentences)
            self.stop()
            self.speak_sentences(sentences_copy, start_index=next_idx)

    def skip_prev(self):
        """Skip to previous sentence."""
        if self.is_playing and self.current_sentence_index > 0:
            prev_idx = max(0, self.current_sentence_index - 1)
            sentences_copy = list(self.sentences)
            self.stop()
            self.speak_sentences(sentences_copy, start_index=prev_idx)

    @staticmethod
    def get_voice_presets() -> typing.List[typing.Dict[str, str]]:
        """Return curated list of voice presets with Afro-European focus."""
        return VOICE_PRESETS
