#!/opt/homebrew/bin/python3
"""build_app.py - builds /Applications/Agents.app around agents_app.py, in Oracle.app's pattern.

    /opt/homebrew/bin/python3 build_app.py

Writes only: /Applications/Agents.app (Info.plist, the two-line sh launcher, Agents.icns) and the
icon's PNG frames under ~/Library/Caches/com.masondean.agents/Agents.iconset. The launcher execs
/opt/homebrew/bin/python3 (the lab's Python with PyObjC; /usr/local/bin/python3 has none) on
agents_app.py where it lives, so edits to the app need no rebuild. Startup errors go to
~/Library/Caches/com.masondean.agents/app.log, because `open` shows none.

10 Sep 2026 (the window with SPEC sections 1 to 5 and 7 to 10): the launcher adds
-ApplePersistenceIgnoreState YES (see LAUNCHER). The previous version is
archive/build_app_v4_2026-09-10.py.
"""

import os
import subprocess
import sys

from AppKit import (
    NSBitmapImageRep, NSGraphicsContext, NSColor, NSBezierPath, NSGradient, NSAffineTransform,
    NSDeviceRGBColorSpace, NSBitmapImageFileTypePNG, NSMakeRect,
)

HERE = os.path.dirname(os.path.abspath(__file__))
APP = "/Applications/Agents.app"
CACHE = os.path.expanduser("~/Library/Caches/com.masondean.agents")
ICONSET = os.path.join(CACHE, "Agents.iconset")
PYTHON = "/opt/homebrew/bin/python3"
SCRIPT = os.path.join(HERE, "agents_app.py")

INFO = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>              <string>Agents</string>
    <key>CFBundleDisplayName</key>       <string>Agents</string>
    <key>CFBundleIdentifier</key>        <string>com.masondean.agents</string>
    <key>CFBundleVersion</key>           <string>1.0</string>
    <key>CFBundleShortVersionString</key><string>1.0</string>
    <key>CFBundleExecutable</key>        <string>agents</string>
    <key>CFBundlePackageType</key>       <string>APPL</string>
    <key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
    <key>CFBundleIconFile</key>          <string>Agents</string>
    <key>LSMinimumSystemVersion</key>    <string>11.0</string>
    <key>NSHighResolutionCapable</key>   <true/>
</dict>
</plist>
"""

# -ApplePersistenceIgnoreState YES: after any crash, AppKit would otherwise open a modal "reopen its
# windows?" alert for Python (seen 10 Sep in a test process: the window froze until it was answered).
# The app keeps no restorable state (setRestorable_(False)), so nothing is lost by ignoring it.
LAUNCHER = f"""#!/bin/sh
mkdir -p "$HOME/Library/Caches/com.masondean.agents"
exec "{PYTHON}" "{SCRIPT}" "$@" -ApplePersistenceIgnoreState YES 2>>"$HOME/Library/Caches/com.masondean.agents/app.log"
"""


def rgb(h, a=1.0):
    return NSColor.colorWithSRGBRed_green_blue_alpha_(int(h[0:2], 16) / 255.0, int(h[2:4], 16) / 255.0,
                                                      int(h[4:6], 16) / 255.0, a)


def bar(x, y, w, h, color):
    color.setFill()
    NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(NSMakeRect(x, y, w, h), h / 2.0, h / 2.0).fill()


def draw_icon():
    """1024-point canvas, drawn in the app's own palette: a near-black tile holding a small table
    (one row selected in lighter grey, an orange count), a thin divider, and the waiting list
    below it (one yellow row, one grey)."""
    tile = NSMakeRect(100, 100, 824, 824)
    path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(tile, 185, 185)
    NSGradient.alloc().initWithStartingColor_endingColor_(rgb("262626"), rgb("121212")).drawInBezierPath_angle_(path, -90)
    rgb("3a3a3a").setStroke()
    path.setLineWidth_(6)
    path.stroke()

    left, right = 190, 834
    # column header strip
    bar(left, 770, 90, 18, rgb("8e8e8e"))
    bar(left + 150, 770, 120, 18, rgb("8e8e8e"))
    bar(right - 70, 770, 70, 18, rgb("f39c2b"))
    rgb("3a3a3a").setFill()
    NSBezierPath.fillRect_(NSMakeRect(left - 20, 738, right - left + 40, 5))
    # four table rows, the second selected
    ys = [680, 610, 540, 470]
    for i, y in enumerate(ys):
        if i == 1:
            rgb("3a3a3a").setFill()
            NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                NSMakeRect(left - 20, y - 22, right - left + 40, 62), 12, 12).fill()
        bar(left, y, 110, 20, rgb("dedede"))
        bar(left + 150, y, 330 - 40 * (i % 2), 20, rgb("8a8a8a"))
        bar(right - 50, y, 50, 20, rgb("c6c6c6") if i != 2 else rgb("6a6a6a"))
    # divider
    rgb("4a4a4a").setFill()
    NSBezierPath.fillRect_(NSMakeRect(left - 20, 405, right - left + 40, 5))
    # waiting list: one yellow, one grey
    bar(left, 330, 560, 24, rgb("e9cf4f"))
    bar(left, 292, 380, 24, rgb("e9cf4f"))
    bar(left, 200, 520, 24, rgb("bdbdbd"))
    bar(left, 162, 300, 24, rgb("bdbdbd", 0.8))


def png(px, path):
    rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, px, px, 8, 4, True, False, NSDeviceRGBColorSpace, 0, 0)
    ctx = NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.setCurrentContext_(ctx)
    t = NSAffineTransform.transform()
    t.scaleBy_(px / 1024.0)
    t.concat()
    draw_icon()
    ctx.flushGraphics()
    NSGraphicsContext.restoreGraphicsState()
    data = rep.representationUsingType_properties_(NSBitmapImageFileTypePNG, {})
    data.writeToFile_atomically_(path, True)


def main():
    os.makedirs(ICONSET, exist_ok=True)
    for pt in (16, 32, 128, 256, 512):
        png(pt, os.path.join(ICONSET, f"icon_{pt}x{pt}.png"))
        png(pt * 2, os.path.join(ICONSET, f"icon_{pt}x{pt}@2x.png"))
    res = os.path.join(APP, "Contents", "Resources")
    macos = os.path.join(APP, "Contents", "MacOS")
    os.makedirs(res, exist_ok=True)
    os.makedirs(macos, exist_ok=True)
    subprocess.run(["/usr/bin/iconutil", "-c", "icns", "-o", os.path.join(res, "Agents.icns"), ICONSET], check=True)
    with open(os.path.join(APP, "Contents", "Info.plist"), "w") as f:
        f.write(INFO)
    exe = os.path.join(macos, "agents")
    with open(exe, "w") as f:
        f.write(LAUNCHER)
    os.chmod(exe, 0o755)
    os.utime(APP, None)                                # nudge Finder and the Dock to reread the icon
    subprocess.run(["/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister",
                    "-f", APP], check=False)
    print(f"built {APP}")
    for root, _, files in os.walk(APP):
        for n in sorted(files):
            p = os.path.join(root, n)
            print(f"  {os.path.getsize(p):>8}  {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
