"""
Main Entry Point for Kindle Voice Narrator & AI Study Companion.
Initializes the application, global hotkeys, and GUI.
"""

import sys
import threading
from ui import KindleNarratorApp


def main():
    print("=" * 60)
    print("  🎧 Kindle Voice Narrator & AI Study Companion")
    print("  - Afro-European Voice Presets (Ezinne / Vivienne / Leah)")
    print("  - Dynamic Reading Speed Slider")
    print("  - Continuous Auto Page Turn")
    print("  - Intelligent Note & Summary Generator")
    print("=" * 60)

    app = KindleNarratorApp()
    app.mainloop()


if __name__ == "__main__":
    main()
