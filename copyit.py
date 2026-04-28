#!/usr/bin/env python3
"""
CopyIt - Select any area on screen, instantly copy the text.
Uses Apple Vision OCR for high accuracy.
Shortcut: Option+Shift+C
"""

import sys
import threading
import subprocess

import Quartz.CoreGraphics as CG
from AppKit import (
    NSApplication, NSApp, NSWindow, NSView, NSColor, NSCursor,
    NSScreen, NSBezierPath, NSEvent, NSStatusBar, NSMenu, NSMenuItem,
    NSMakeRect, NSObject,
    NSApplicationActivationPolicyAccessory,
    NSWindowStyleMaskBorderless, NSBackingStoreBuffered,
    NSFloatingWindowLevel, NSEventMaskKeyDown,
)
import objc
import Vision
from Foundation import NSData


#Screen capture

def capture_region_as_cgimage(x, y, w, h):
    region = CG.CGRectMake(x, y, w, h)
    image = CG.CGWindowListCreateImage(
        region,
        CG.kCGWindowListOptionOnScreenOnly,
        CG.kCGNullWindowID,
        CG.kCGWindowImageDefault
    )
    return image


def ocr_cgimage(cg_image):
    """Use Apple Vision to OCR a CGImage. Returns extracted text preserving spatial layout."""
    observations = []
    done = threading.Event()

    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(
        cg_image, {}
    )

    def completion(request, error):
        if error:
            done.set()
            return
        for obs in request.results():
            bbox = obs.boundingBox()  # normalized CGRect: origin bottom-left, y increases upward
            observations.append({
                'text': obs.text(),
                'x': bbox.origin.x,
                'y': bbox.origin.y,
                'w': bbox.size.width,
                'h': bbox.size.height,
            })
        done.set()

    request = Vision.VNRecognizeTextRequest.alloc().initWithCompletionHandler_(completion)
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    request.setUsesLanguageCorrection_(True)

    handler.performRequests_error_([request], None)
    done.wait(timeout=10)

    if not observations:
        return ""

    return reconstruct_layout(observations)


def reconstruct_layout(observations):
    """Reconstruct text layout from Vision observations using bounding box positions."""
    # Sort top-to-bottom (Vision y=0 is bottom, so descending y = top of image first)
    observations.sort(key=lambda o: (-o['y'], o['x']))

    # Group observations into lines by clustering similar vertical positions
    lines = []
    used = set()

    for i, obs in enumerate(observations):
        if i in used:
            continue
        used.add(i)
        line = [obs]
        obs_mid_y = obs['y'] + obs['h'] / 2

        for j, other in enumerate(observations):
            if j in used:
                continue
            other_mid_y = other['y'] + other['h'] / 2
            # Same line if vertical centers are within half the average height
            threshold = (obs['h'] + other['h']) / 2 * 0.5
            if abs(obs_mid_y - other_mid_y) <= threshold:
                line.append(other)
                used.add(j)

        line.sort(key=lambda o: o['x'])
        lines.append(line)

    # Detect blank lines between sections by checking y-gaps
    result = []
    prev_line_bottom_y = None  # bottom edge of previous line (in Vision coords, higher = higher on screen)

    for line in lines:
        line_top_y = max(obs['y'] + obs['h'] for obs in line)
        avg_height = sum(obs['h'] for obs in line) / len(line)

        if prev_line_bottom_y is not None:
            gap = prev_line_bottom_y - line_top_y
            if gap > avg_height * 1.2:
                result.append('')  # blank line between sections

        if len(line) == 1:
            result.append(line[0]['text'])
        else:
            # Tab-separate items on the same line to preserve column alignment
            result.append('\t'.join(obs['text'] for obs in line))

        prev_line_bottom_y = min(obs['y'] for obs in line)

    return '\n'.join(result).strip()


#Selection overlay

class SelectionView(NSView):

    def initWithFrame_(self, frame):
        self = objc.super(SelectionView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.startPoint = None
        self.currentPoint = None
        self.isDragging = False
        return self

    def drawRect_(self, rect):
        NSColor.colorWithCalibratedRed_green_blue_alpha_(0, 0, 0, 0.4).set()
        NSBezierPath.fillRect_(rect)

        if self.startPoint and self.currentPoint and self.isDragging:
            selRect = self._selectionRect()
            NSColor.clearColor().set()
            NSBezierPath.fillRect_(selRect)
            NSColor.colorWithCalibratedRed_green_blue_alpha_(0.38, 0.70, 1.0, 1.0).set()
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
        if event.keyCode() == 53:
            self.window().cancelSelection()

    def acceptsFirstResponder(self):
        return True


class OverlayWindow(NSWindow):

    def initForScreen_(self, screen):
        frame = screen.frame()
        self = objc.super(OverlayWindow, self).initWithContentRect_styleMask_backing_defer_(
            frame, NSWindowStyleMaskBorderless, NSBackingStoreBuffered, False
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
        if rect.size.width < 5 or rect.size.height < 5:
            self.cancelSelection()
            return

        screen_frame = self._screen.frame()
        screen_height = screen_frame.size.height
        ox = screen_frame.origin.x
        oy = screen_frame.origin.y

        x = int(ox + rect.origin.x)
        y = int(screen_height - (rect.origin.y + rect.size.height) + oy)
        w = int(rect.size.width)
        h = int(rect.size.height)

        self.orderOut_(None)
        NSCursor.arrowCursor().set()

        def do_ocr():
            try:
                cg_image = capture_region_as_cgimage(x, y, w, h)
                if cg_image:
                    text = ocr_cgimage(cg_image)
                    if text:
                        copy_to_clipboard(text)
                        notify("CopyIt ✓", f"Copied: {text[:60]}{'…' if len(text) > 60 else ''}")
                    else:
                        notify("CopyIt", "No text found — try selecting more area")
            except Exception as e:
                notify("CopyIt Error", str(e))
            finally:
                if self._callback:
                    self.performSelectorOnMainThread_withObject_waitUntilDone_(
                        "invokeCallback", None, False
                    )

        threading.Thread(target=do_ocr, daemon=True).start()

    def invokeCallback(self):
        if self._callback:
            self._callback()

    def cancelSelection(self):
        self.orderOut_(None)
        NSCursor.arrowCursor().set()
        if self._callback:
            self._callback()


# Clipboard & notifications

def copy_to_clipboard(text):
    from AppKit import NSPasteboard, NSStringPboardType
    pb = NSPasteboard.generalPasteboard()
    pb.clearContents()
    pb.setString_forType_(text, NSStringPboardType)


def notify(title, message):
    message = message.replace('"', "'")
    script = f'display notification "{message}" with title "{title}"'
    subprocess.run(["osascript", "-e", script], capture_output=True)


#App delegate 

class AppDelegate(NSObject):

    def applicationDidFinishLaunching_(self, notification):
        NSApp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

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


# Entry Point

if __name__ == "__main__":
    app = NSApplication.sharedApplication()
    delegate = AppDelegate.alloc().init()
    app.setDelegate_(delegate)
    app.run()