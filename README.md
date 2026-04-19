# CopyIt ⌨️

> Copy text from anywhere on your screen — even when the app won't let you.

---

## The problem

Some apps just won't let you select text. PDFs with copy protection. Text baked into images. YouTube thumbnails. Error messages from other apps. Websites that disable right-click.

Your only option was to take a screenshot, open it, squint, and retype it manually.

**CopyIt fixes that.**

---

## How it works

Press **Option+Shift+C**. Drag over anything on your screen. Text is copied to your clipboard instantly.

That's it. No windows, no popups, no saving files. Just select and paste.

Works on:
- Images and photos with text in them
- Copy-protected PDFs
- Video frames and thumbnails
- Websites that block text selection
- Error messages from other apps
- Anything you can see but can't select

---

## Requirements

- macOS Sequoia or later
- Python 3.x
- Homebrew

---

## Installation

**1. Clone the repo**
```bash
git clone https://github.com/yourusername/copyit.git
cd copyit
```

**2. Install system dependencies**
```bash
brew install python tesseract
```

**3. Set up Python environment**
```bash
python3 -m venv venv
source venv/bin/activate
pip install pillow pytesseract pyobjc-framework-Quartz pyobjc-framework-Cocoa
```

**4. Run**
```bash
python3 copyit.py
```

A ⌨️ icon appears in your menu bar. You're ready.

---

## Permissions

First time you run it, grant these in **System Settings → Privacy & Security:**

| Permission | Why |
|---|---|
| Screen Recording | To capture the selected area |
| Accessibility | To detect the keyboard shortcut system-wide |

Click **+** in each list → navigate to **Applications → Utilities → Terminal** → toggle on.

---

## Usage

| | |
|---|---|
| **Option+Shift+C** | Activate from anywhere |
| **Drag** | Select the area with text |
| **Cmd+V** | Paste the copied text anywhere |

A notification shows a preview of what was copied.

---

## Run on startup

So you never have to think about it:

1. Open **Automator** → New Document → **Application**
2. Add **Run Shell Script** and paste:
```bash
cd ~/path/to/copyit && source venv/bin/activate && python3 copyit.py
```
3. Save it somewhere (e.g. Desktop)
4. **System Settings → General → Login Items → +** → add the saved app

Now it starts automatically every time your Mac boots.

---

## Stack

- [PyObjC](https://pyobjc.readthedocs.io/) — Python bindings for macOS
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) — text recognition engine
- [Pillow](https://python-pillow.org/) — image processing
- [pytesseract](https://github.com/madmaze/pytesseract) — Python wrapper for Tesseract

100% local. Nothing leaves your machine.

---

## License

MIT