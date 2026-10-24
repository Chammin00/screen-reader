# 🎧 Kindle Voice Narrator & AI Study Companion

An assistive screen reader and voice narrator designed specifically for **Kindle for PC**, **Kindle Cloud Reader** (`read.amazon.com`), and any on-screen ebook reader.

---

## ✨ Features

- 🤝 **1-Click Window Link & Permissions Handshake**:
  - **`👆 Click Window to Link` / `🤝 Link Kindle Window`**: Simply click once anywhere on your Kindle window or browser.
  - Automatically identifies the Kindle window, locks onto the book reading area (trimming window chrome/toolbars), and authorizes background focus and page-turn keystrokes.
  - **Dynamic Tracking**: You can move or resize your Kindle window freely — the narrator tracks it dynamically.
- 🔦 **Interactive Follow-Along Highlighter & Teleprompter**:
  - **Follow-Along Spotlight Bar**: Displays the active sentence in large, high-visibility text with real-time sentence counter (`[Sentence 2 of 12]`).
  - **Live In-Transcript Highlighter**: Highlights the currently spoken sentence in vibrant gold with automatic scrolling.
  - **Click-to-Jump**: Double-click any sentence in the transcript to jump speech directly to that point.
- ✂️ **Smart Hyphen & Linebreak Unwrapping**:
  - Automatically repairs words broken across linebreaks (`extraor-\n dinary` -> `extraordinary`, `read-\n ing` -> `reading`, `con-\n tinuation` -> `continuation`).
- 🌍 **Afro-European Woman Voice Presets**:
  - **Afro-European / Nigerian English Woman (`en-NG-EzinneNeural`)** *(Default — Warm, Expressive, Rich)*
  - **Afro-European Multilingual Woman (`fr-FR-VivienneMultilingualNeural`)** *(Speaks English with a Parisian/European cadence)*
  - **South African English Woman (`en-ZA-LeahNeural`)**
  - **Kenyan English Woman (`en-KE-AsiliaNeural`)**
  - **British European Woman (`en-GB-SoniaNeural` / `en-GB-LibbyNeural`)**
- ⚡ **Dynamic Reading Speed Control**:
  - Live slider from `0.5x` (slow) to `2.25x` (fast).
- 📖 **Automatic & Manual Page Turning**:
  - Automatically sends page-turn keystrokes when the page finishes and continues narrating seamlessly.
- 📝 **Intelligent Note & Summary Generation**:
  - Instant executive summaries, key takeaways, character/entity mentions, and memorable quotes with 1-click Markdown export.

---

## 🚀 Quick Start

### 1. Launch the Application
Double-click `run.bat` or run in PowerShell:
```powershell
.\run.ps1
```
Or with `uv`:
```bash
uv run --with customtkinter --with pillow --with edge-tts --with pygame --with pyautogui --with winocr --with pynput --with requests python main.py
```

---

## 📖 How to Use with Kindle

1. Open **Kindle for PC** or open [read.amazon.com](https://read.amazon.com) in your browser.
2. Open the book to the page you want to read.
3. In **Kindle Voice Narrator**:
   - Click **`🎯 Select Area`** and drag a rectangle over the text area of your Kindle page.
   - Choose your preferred **Voice Profile** (Default: *Afro-European / Nigerian English Woman*).
   - Adjust the **Reading Speed** slider to your comfort level (e.g. `1.15x` or `1.25x`).
   - Leave **`Auto Page Turn`** toggled **ON** for hands-free continuous audiobook-style listening.
4. Click **`▶ Read Page`**.
5. When you want notes on what you just read, switch to the **`📝 Notes & Summary`** tab and click **`Notes for Current Page`** or **`Notes for Entire Session`**!
