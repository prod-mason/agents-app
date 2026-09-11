#!/opt/homebrew/bin/python3
"""richtext_snapshot: render an HTML file offscreen in a WKWebView and save a PNG.

    python3 richtext_snapshot.py page.html out.png [width_px]

Test helper for richtext.to_html: it shows exactly what the hover panel's
WKWebView would draw. It runs as an accessory process (no Dock icon), puts the
web view in a borderless window far off screen, waits for the page to finish
loading, sizes the window to the page, then calls takeSnapshotWithConfiguration.
Nothing here touches the running Agents.app.
"""
import sys
import time

import objc
from AppKit import (NSApplication, NSApplicationActivationPolicyAccessory, NSWindow,
                    NSWindowStyleMaskBorderless, NSBackingStoreBuffered, NSBitmapImageRep,
                    NSPNGFileType)
from Foundation import NSObject, NSRunLoop, NSDate, NSMakeRect
from WebKit import WKWebView, WKWebViewConfiguration, WKSnapshotConfiguration


class _Nav(NSObject):
    def init(self):
        self = objc.super(_Nav, self).init()
        self.done = False
        self.failed = None
        return self

    def webView_didFinishNavigation_(self, wv, nav):
        self.done = True

    def webView_didFailNavigation_withError_(self, wv, nav, err):
        self.failed = str(err)

    def webView_didFailProvisionalNavigation_withError_(self, wv, nav, err):
        self.failed = str(err)


def _spin(pred, timeout):
    end = time.time() + timeout
    while not pred() and time.time() < end:
        NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.05))
    return pred()


def snapshot(html_text, out_png, width=700, height=900, timeout=20.0):
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(-20000, -20000, width, height), NSWindowStyleMaskBorderless, NSBackingStoreBuffered, False)
    wv = WKWebView.alloc().initWithFrame_configuration_(NSMakeRect(0, 0, width, height),
                                                        WKWebViewConfiguration.alloc().init())
    nav = _Nav.alloc().init()
    wv.setNavigationDelegate_(nav)
    win.setContentView_(wv)
    win.orderFrontRegardless()
    wv.loadHTMLString_baseURL_(html_text, None)
    if not _spin(lambda: nav.done or nav.failed, timeout) or nav.failed:
        raise RuntimeError("page did not load: %s" % (nav.failed or "timeout"))

    # Page height, measured by the host (native evaluateJavaScript is not page script).
    box = {}
    wv.evaluateJavaScript_completionHandler_(
        "Math.ceil(document.querySelector('main').getBoundingClientRect().bottom)", lambda v, e: box.update(h=v, e=e))
    _spin(lambda: "h" in box, 5)
    h = box.get("h")
    if isinstance(h, (int, float)) and h > 0:
        height = int(min(max(h, 120), 6000))
        win.setContentSize_((width, height))
        wv.setFrame_(NSMakeRect(0, 0, width, height))
        _spin(lambda: False, 0.4)

    shot = {}
    cfg = WKSnapshotConfiguration.alloc().init()
    wv.takeSnapshotWithConfiguration_completionHandler_(cfg, lambda img, err: shot.update(img=img, err=err))
    if not _spin(lambda: "img" in shot, timeout) or shot.get("img") is None:
        raise RuntimeError("snapshot failed: %s" % shot.get("err"))
    img = shot["img"]
    rep = NSBitmapImageRep.imageRepWithData_(img.TIFFRepresentation())
    data = rep.representationUsingType_properties_(NSPNGFileType, {})
    if not data.writeToFile_atomically_(out_png, True):
        raise RuntimeError("could not write %s" % out_png)
    win.orderOut_(None)
    return out_png, (rep.pixelsWide(), rep.pixelsHigh()), box.get("h")


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    with open(argv[0], encoding="utf-8") as fh:
        text = fh.read()
    width = int(argv[2]) if len(argv) > 2 else 700
    path, px, h = snapshot(text, argv[1], width=width)
    print("%s %dx%d px (page height %s css px)" % (path, px[0], px[1], h))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
