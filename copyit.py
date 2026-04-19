#!/usr/bin/env python3
"""
CopyIt: Select any area on screen, instantly copy the text.
Shortcut: Option+Shift+C
"""

import sys
import os
import threading
import subprocess
import tempfile
import time

import Quartz
import Quartz.CoreGraphics as CG
from AppKit import (
    NSApplication, NSApp, NSWindow, NSView, NSColor, NSCursor,
    NSScreen, NSBezierPath, NSEvent, NSStatusBar, NSMenu, NSMenuItem,
    NSImage, NSMakeRect, NSObject, NSRunLoop, NSDate,
    NSApplicationActivationPolicyAccessory,
    NSWindowStyleMaskBorderless, NSBackingStoreBuffered,
    NSFloatingWindowLevel, NSEventMaskKeyDown, NSEventMaskFlagsChanged,
)
from Foundation import NSTimer, NSThread
import objc

try:
    import pytesseract
    from PIL import Image
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False
    print("Warning: pytesseract or PIL not available")


#Screen capture

def capture_region(x, y, w, h):
    """Capture a region of the screen and return a PIL Image."""
    region = CG.CGRectMake(x, y, w, h)
    image = CG.CGWindowListCreateImage(
        region,
        CG.kCGWindowListOptionOnScreenOnly,
        CG.kCGNullWindowID,
        CG.kCGWindowImageDefault
    )
    if image is None:
        return None

    width = CG.CGImageGetWidth(image)
    height = CG.CGImageGetHeight(image)
    bpr = CG.CGImageGetBytesPerRow(image)

    data_provider = CG.CGImageGetDataProvider(image)
    raw_data = CG.CGDataProviderCopyData(data_provider)
    raw_bytes = bytes(raw_data)

    from PIL import Image as PILImage
    img = PILImage.frombytes("RGBA", (width, height), raw_bytes, "raw", "BGRA")
    return img.convert("RGB")


def ocr_image(pil_image):
    """Run OCR on a PIL image and return extracted text."""
    text = pytesseract.image_to_string(pil_image, config="--psm 6")
    return text.strip()


#Selection overlay window

class SelectionView(NSView):
    """Transparent view that draws the selection rectangle."""

    def initWithFrame_(self, frame):
        self = objc.super(SelectionView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.startPoint = None
        self.currentPoint = None
        self.isDragging = False
        return self

    def drawRect_(self, rect):
        # Dark overlay
        NSColor.colorWithCalibratedRed_green_blue_alpha_(0, 0, 0, 0.35).set()
        NSBezierPath.fillRect_(rect)

        if self.startPoint and self.currentPoint and self.isDragging:
            selRect = self._selectionRect()

            # Clear the selected area (punch through overlay)
            NSColor.clearColor().set()
            NSBezierPath.fillRect_(selRect)

            # Blue border
            NSColor.colorWithCalibratedRed_green_blue_alpha_(
                0.38, 0.70, 1.0, 1.0
            ).set()
            path = NSBezierPath.bezierPathWithRect_(selRect)
            path.setLineWidth_(2.0)
            path.stroke()

    def _selectionRect(self):
        if not self.startPoint or not self.currentPoint:
            return NSMakeRect(0, 0, 0, 0)
        x = min(self.startPoint.x, self.currentPoint.x)
        y = min(self.startPoint.y, self.currentPoint.y)
        w = abs(self.currentPoint.x - self.startPoint.x)
        h = abs(self.currentPoint.y - self.startPoint.y)
        return NSMakeRect(x, y, w, h)

    def mouseDown_(self, event):
        self.startPoint = event.locationInWindow()
        self.isDragging = True
        self.setNeedsDisplay_(True)

    def mouseDragged_(self, event):
        self.currentPoint = event.locationInWindow()
        self.setNeedsDisplay_(True)

    def mouseUp_(self, event):
        self.currentPoint = event.locationInWindow()
        self.isDragging = False
        self.window().finishSelection_(self._selectionRect())

    def keyDown_(self, event):
        if event.keyCode() == 53:  # Escape
            self.window().cancelSelection()

    def acceptsFirstResponder(self):
        return True


class OverlayWindow(NSWindow):
    """Full-screen transparent window for selection."""

    def initForScreen_(self, screen):
        frame = screen.frame()
        self = objc.super(OverlayWindow, self).initWithContentRect_styleMask_backing_defer_(
            frame,
            NSWindowStyleMaskBorderless,
            NSBackingStoreBuffered,
            False
        )
        if self is None:
            return None

        self.setLevel_(NSFloatingWindowLevel + 1)
        self.setOpaque_(False)
        self.setBackgroundColor_(NSColor.clearColor())
        self.setIgnoresMouseEvents_(False)
        self.setAcceptsMouseMovedEvents_(True)

        self._screen = screen
        self._callback = None

        view = SelectionView.alloc().initWithFrame_(frame)
        self.setContentView_(view)
        return self

    def setCallback_(self, callback):
        self._callback = callback

    def canBecomeKeyWindow(self):
        return True

    def finishSelection_(self, rect):
        """Called when user releases mouse — perform OCR."""
        if rect.size.width < 5 or rect.size.height < 5:
            self.cancelSelection()
            return

        # Convert AppKit coords (bottom-left origin) to screen coords (top-left)
        screen_frame = self._screen.frame()
        screen_height = screen_frame.size.height

        # Account for menu bar / screen origin
        ox = screen_frame.origin.x
        oy = screen_frame.origin.y

        x = int(ox + rect.origin.x)
        # Flip Y: AppKit is bottom-left origin, CG is top-left
        y = int(screen_height - (rect.origin.y + rect.size.height) + oy)
        w = int(rect.size.width)
        h = int(rect.size.height)

        self.orderOut_(None)
        NSCursor.arrowCursor().set()

        # Run OCR in background thread so UI stays responsive
        def do_ocr():
            try:
                img = capture_region(x, y, w, h)
                if img:
                    text = ocr_image(img)
                    if text:
                        copy_to_clipboard(text)
                        notify("CopyIt ✓", f"Copied: {text[:60]}{'…' if len(text)>60 else ''}")
                    else:
                        notify("CopyIt", "No text found in selection")
            except Exception as e:
                notify("CopyIt", f"Error: {e}")
            finally:
                if self._callback:
                    self._callback()

        t = threading.Thread(target=do_ocr, daemon=True)
        t.start()

    def cancelSelection(self):
        self.orderOut_(None)
        NSCursor.arrowCursor().set()
        if self._callback:
            self._callback()


#Clipboard & notifications

def copy_to_clipboard(text):
    from AppKit import NSPasteboard, NSStringPboardType
    pb = NSPasteboard.generalPasteboard()
    pb.clearContents()
    pb.setString_forType_(text, NSStringPboardType)


def notify(title, message):
    """Show a macOS notification."""
    script = f'display notification "{message}" with title "{title}"'
    subprocess.run(["osascript", "-e", script], capture_output=True)


#App delegate & status bar

class AppDelegate(NSObject):

    def applicationDidFinishLaunching_(self, notification):
        NSApp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

        # Status bar icon
        self._statusItem = NSStatusBar.systemStatusBar().statusItemWithLength_(-1)
        self._statusItem.button().setTitle_("⌨️")
        self._statusItem.button().setToolTip_("CopyIt — Option+Shift+C to capture")

        menu = NSMenu.alloc().init()
        captureItem = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Capture Text  (⌥⇧C)", "startCapture:", ""
        )
        captureItem.setTarget_(self)
        menu.addItem_(captureItem)
        menu.addItem_(NSMenuItem.separatorItem())
        quitItem = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Quit CopyIt", "quitApp:", ""
        )
        quitItem.setTarget_(self)
        menu.addItem_(quitItem)
        self._statusItem.setMenu_(menu)

        # Global keyboard shortcut monitor (Option+Shift+C)
        mask = NSEventMaskKeyDown

        def handleKey(event):
            flags = event.modifierFlags()
            optionHeld = bool(flags & 0x080000)
            shiftHeld  = bool(flags & 0x020000)
            chars = event.charactersIgnoringModifiers()
            if optionHeld and shiftHeld and chars and chars.lower() == "c":
                self.startCapture_(None)

        self._monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
            mask, handleKey
        )

        self._overlayWindows = []
        notify("CopyIt", "Running! Press Option+Shift+C to capture text.")

    def startCapture_(self, sender):
        # Close any existing overlays
        for w in self._overlayWindows:
            try:
                w.orderOut_(None)
            except Exception:
                pass
        self._overlayWindows = []

        NSApp.activateIgnoringOtherApps_(True)
        NSCursor.crosshairCursor().push()

        for screen in NSScreen.screens():
            win = OverlayWindow.alloc().initForScreen_(screen)
            win.setCallback_(self._captureFinished)
            self._overlayWindows.append(win)
            win.makeKeyAndOrderFront_(None)

        # Make sure key events work
        if self._overlayWindows:
            self._overlayWindows[0].makeKeyWindow()

    def _captureFinished(self):
        for w in self._overlayWindows:
            try:
                w.orderOut_(None)
            except Exception:
                pass
        self._overlayWindows = []

    def quitApp_(self, sender):
        NSApp.terminate_(None)


#Entry point

if __name__ == "__main__":
    if not OCR_AVAILABLE:
        print("Error: Please install pillow and pytesseract first:")
        print("  pip install pillow pytesseract")
        sys.exit(1)

    app = NSApplication.sharedApplication()
    delegate = AppDelegate.alloc().init()
    app.setDelegate_(delegate)
    app.run()