#!/opt/homebrew/bin/python3
"""agents_app.py - Agents.app: one native Mac window that shows what every Claude conversation is doing,
and lets Mason answer them from it.

THE CONTRACT is lab-common/monitor/SPEC.md; every feature below traces to his words in its section 0.
This file is the window (SPEC sections 1 to 5 and 7 to 10). Data comes from monitor_data.py (the
engine, loaded once and kept for the life of the app), every action goes through monitor_actions.py,
and formatting through richtext.py. The previous version of this file is archive/agents_app_v4_2026-09-10.py.

    python3 agents_app.py            the app (bundled as /Applications/Agents.app by build_app.py)
    python3 agents_app.py --check    planted controls on a hidden window with planted data and fake
                                     actions (no cmux, no model, no ledger); exit status 1 if any fails

WHAT IS ON SCREEN, TOP TO BOTTOM
  Alarm banner    red, one line per open alarm (monitor_data.alarms()): "ALARM from <lane>: <why>", when,
                  who answered. Hidden when none are open. A click opens the alarm's full text in the
                  hover panel. When the alarm list cannot be read, the banner says so.
  cmux banner     SPEC section 11. cmux admits only processes started inside cmux, so Agents runs from
                  cmux's right sidebar (the Agents Dock control, cmux_dock_control.json). Opened any
                  other way (the macOS Dock, Finder), one "cmux ping" at launch (monitor_actions.
                  probe_cmux) or the first refused cmux call detects it ONCE; the retrying stops, his
                  words still land in the ledger and wait in the outbox, and one plain banner says:
                  "Open Agents from cmux's right sidebar (the Agents control) so replies and renames can
                  reach your agents." Nothing about cmux's security setting changes.
  Sort bar        "Sort" and a small menu with the eight orders of SPEC section 1 (also in the menu bar).
  The table       Conversation | Description | Time spent | Running now | Tasks run, plus two optional
                  columns hidden by default ("Waiting on you", "Total wait"), shown or hidden from the
                  header's right-click menu or the View menu. Columns resize by dragging and can be
                  dragged into another order; widths, order and which are shown are remembered.
                  Click a header to sort by it, click again to reverse; a small arrow marks it.
                  Conversation: the cmux sidebar title. Double-click it to rename (Return renames the
                  real sidebar through monitor_actions.rename, Escape cancels, an empty name is refused);
                  the row's right-click menu has Rename and Clear name.
                  Description: the latest message's Headline (50) or Summary (200) (View menu, default
                  Headline), rendered with its formatting (richtext.inline_attributed). A line over its
                  limit shows its first words and a small "over 50" or "over 200" tag, never a silent cut.
                  Rows whose headline starts "Waiting on you:" carry the orange accent bar at the left.
                  Hovering the cell 0.35 s opens the hover panel: an NSPopover holding a WKWebView with
                  JavaScript off and a navigation delegate that refuses every navigation except the one
                  page this app loads (richtext.to_html, which carries its own CSP); 560 pt wide, as tall
                  as the message up to 70 percent of the screen, scrolling beyond. It stays open while
                  the pointer is over it; it closes when the pointer leaves or on Escape.
                  Time spent: "13 h 34 m 07 s" in tabular digits, ticking every second while the
                  conversation's transcript is mid-turn (row "ticking", monitor_data.live_seconds),
                  frozen otherwise, so a shown second is never taken back.
                  Running now, Tasks run: "?" when unknown, never 0. Total wait ticks too.
                  Waiting on you: counted from the waiting list's own items for that row's lane (or, with
                  no lane, its session), never a number a lane typed (count_rows); "?" when it cannot
                  be known; the number in the red accent when the engine flags that lane's count as not
                  matching the list. The "most decisions" sort and Total wait read the same count.
  Storage strip   monitor_data.storage()["text"], coloured normal, orange (30 to 40 GiB) or red (under
                  the 30 GiB floor), with the trend when there is one. Hover shows each running run and the
                  Time Machine state.
  Waiting list    header "<total> waiting on you. <n> need more than a decision."; then every item of
                  queue.py's manifest (monitor_data.waiting()), yellow when the bucket is not decision.
                  Related items sit under a group header (monitor_actions.group(), once per manifest sha,
                  on a background thread) naming the topic and the agents, with one button, "Work it out
                  together". Each item shows its lane, what it needs, how long it has waited (ticking;
                  "at least" when only first seen is known), a dim "may be settled" tag with the reason,
                  what is waiting to deliver (with Cancel), and a reply field: Return sends, Shift-Return
                  adds a line. Return first runs monitor_actions.check_resolved(); RESOLVED slides down the
                  already-resolved card; OPEN delivers through monitor_actions.reply(). On the card
                  (SPEC section 11) Return presses the FOCUSED pill, Send anyway focused first; Tab and
                  Shift-Tab (or the arrows) move the focus; Escape is Don't send, E is Edit. Don't send
                  never discards: his text stays in the reply field, editable, and is kept in the cache as
                  an unsent draft (drafts.json), which a later window puts back in that item's field.
                  Command-click, Shift-click or the checkbox select several;
                  with two or more selected, one "Reply to N items" field docks above the list.
                  At the foot of the list, collapsed and dim, never counted: "Asked of you without saying
                  why (N)", queue.py's WAITING ON lines that give no "because" (fence 50), each with its
                  lane, so the lane can be told to justify it or drop it. A click on it opens or closes it.
  Message bar     "Message the coordinator": monitor_actions.message_coordinator(); the text stays in
                  the field until delivery is confirmed; a held message shows "waiting to deliver" and Cancel.
  Footer          "Updated 10:31:05 PM", results of renames, and in test mode a TEST MODE line.

LIVE: conversations, storage and alarms every 5 s; the waiting list every 30 s (and a few seconds after
a reply is sent); the outbox pumped every 5 s; ticking every second. Engine calls happen on background
threads; the window only changes on the main thread. The list is updated by inserting and removing only
the rows that changed, so his scroll position, his selection, a reply half typed and the field he is
typing in all survive every refresh (drafts are also kept per item id).

TEST MODE (environment, tests only)
    AGENTS_TEST_WORKSPACE=<uuid>  every send and every rename goes to that scratch cmux window, never
                                  another: monitor_actions refuses any other target for sends, and this
                                  file redirects renames and Clear name to it (rename_target()). The
                                  footer shows a TEST MODE line and the app never activates itself.
                                  It fails CLOSED (SPEC section 11): the variable present at all, even
                                  empty, is test mode (test prefs, grouping from cache only, a test drafts
                                  file), and with no window id in it every send and rename is refused.
    AGENTS_TEST_LEDGER=<file>     where his words go in test mode (never the real ANSWERS ledger)
    AGENTS_TEST_ALARMS=<file>     an alarm ledger read instead of lab-common/ALARMS.jsonl
    AGENTS_GROUPING=on|cache-only whether grouping may call the model; cache-only (the default in test
                                  mode) reads a cached, successful grouping and never calls
    AGENTS_PREFS=<file>           the layout file (default window.json; window-test.json in test mode)
    AGENTS_DRIVE=<folder>         runs drive(): the screenshot script, then quits

WRITES: drafts.json (his unsent drafts; drafts-test-<8>.json in test mode) and the prefs file in
~/Library/Caches/com.masondean.agents/ (window frame, divider, column widths,
order and visibility, sort, view; merged into the file by atomic replace, so the keys the older app
writes survive); the engine writes its own cache files there. Through monitor_actions: the day's ANSWERS
ledger (his words, verbatim) and cmux (renames, delivered replies). NSTableView's autosaveName is not
used, because this process runs under Homebrew Python's bundle id and AppKit would write Python's
preferences file.

No em dash character in anything shown: every displayed string goes through clean().
"""

import datetime
import difflib
import importlib.util
import json
import math
import os
import queue as queue_mod
import re
import subprocess
import sys
import threading
import time
import traceback

import objc
from Foundation import (
    NSObject, NSMakeRect, NSMakeSize, NSMakePoint, NSMakeRange, NSIndexSet, NSMutableIndexSet, NSBundle,
    NSNotificationCenter, NSTimer, NSRunLoop, NSRunLoopCommonModes, NSProcessInfo, NSPointInRect, NSDate,
)
from AppKit import (
    NSApplication, NSApp, NSApplicationActivationPolicyRegular, NSAppearance, NSAppearanceNameDarkAqua,
    NSWindow, NSWindowStyleMaskTitled, NSWindowStyleMaskClosable, NSWindowStyleMaskMiniaturizable,
    NSWindowStyleMaskResizable, NSBackingStoreBuffered, NSView, NSColor, NSFont, NSFontWeightMedium,
    NSFontWeightRegular, NSFontWeightSemibold, NSFontWeightBold, NSMenu, NSMenuItem,
    NSEventModifierFlagCommand, NSEventModifierFlagOption, NSEventModifierFlagShift, NSScrollView,
    NSTableView, NSTableColumn, NSTableHeaderView, NSTableHeaderCell, NSTableRowView, NSSplitView,
    NSRectFill, NSAttributedString, NSMutableAttributedString, NSMutableParagraphStyle, NSFontAttributeName,
    NSForegroundColorAttributeName, NSParagraphStyleAttributeName, NSKernAttributeName,
    NSLineBreakByTruncatingTail, NSLineBreakByWordWrapping, NSTextAlignmentLeft, NSTextAlignmentRight,
    NSTextAlignmentCenter, NSStringDrawingUsesLineFragmentOrigin, NSStringDrawingUsesFontLeading,
    NSStringDrawingTruncatesLastVisibleLine, NSTableColumnUserResizingMask, NSTableColumnAutoresizingMask,
    NSTableViewUniformColumnAutoresizingStyle, NSTableViewGridNone, NSScrollerStyleOverlay,
    NSFocusRingTypeNone, NSLayoutManager, NSAnimationContext, NSImage, NSBezierPath, NSTextField,
    NSButton, NSPopUpButton, NSTrackingArea, NSTrackingMouseMoved, NSTrackingMouseEnteredAndExited,
    NSTrackingActiveAlways, NSTrackingInVisibleRect, NSPopover, NSViewController, NSEvent, NSScreen,
    NSWorkspace, NSViewLayerContentsRedrawDuringViewResize, NSTableViewSelectionHighlightStyleRegular,
    NSTableViewColumnDidResizeNotification, NSTableViewColumnDidMoveNotification, NSBitmapImageRep,
    NSGraphicsContext, NSUnderlineStyleAttributeName, NSUnderlineStyleSingle, NSCursor,
)
from PyObjCTools import AppHelper
import WebKit

try:
    from AppKit import NSTableViewStylePlain
except ImportError:
    NSTableViewStylePlain = 4
try:
    from Quartz import CAMediaTimingFunction, kCAMediaTimingFunctionEaseOut
except ImportError:                                     # the slide still runs, with AppKit's default curve
    CAMediaTimingFunction, kCAMediaTimingFunctionEaseOut = None, None

NSButtonTypeSwitch = 3
NSPopoverBehaviorApplicationDefined = 0
NSPopoverBehaviorTransient = 1
NSMaxYEdge = 3
NSEventMaskKeyDown = 1 << 10
NSTableViewAnimationEffectNone = 0
KEY_RETURN, KEY_ENTER, KEY_ESCAPE, KEY_TAB, KEY_SPACE, KEY_LEFT, KEY_RIGHT = 36, 76, 53, 48, 49, 123, 124

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.expanduser("~/Library/Caches/com.masondean.agents")
ICON_PATH = "/Applications/Agents.app/Contents/Resources/Agents.icns"
LOG_PATH = os.path.join(CACHE, "app.log")
LOG_MAX = 1024 * 1024
LOG_KEEP = 256 * 1024

TEST_VAR = "AGENTS_TEST_WORKSPACE"


def test_mode_from(env):
    """(test mode, scratch window id or None). Test mode is the variable being PRESENT, even empty or
    spaces (SPEC section 11: fail closed); an empty one names no window, so nothing is sent or renamed."""
    if TEST_VAR not in env:
        return False, None
    return True, (env.get(TEST_VAR) or "").strip() or None


TEST_MODE, TEST_WS = test_mode_from(os.environ)
PREFS_PATH = os.environ.get("AGENTS_PREFS") or os.path.join(CACHE, "window-test.json" if TEST_MODE else "window.json")
ALARM_LEDGER = (os.environ.get("AGENTS_TEST_ALARMS") or "").strip() or None
GROUPING = (os.environ.get("AGENTS_GROUPING") or ("cache-only" if TEST_MODE else "on")).strip()
DRAFTS_PATH = os.path.join(CACHE, ("drafts-test-" + re.sub(r"[^0-9A-Za-z]", "", TEST_WS or "none")[:8].lower() + ".json")
                           if TEST_MODE else "drafts.json")
CMUX_BANNER = ("Open Agents from cmux's right sidebar (the Agents control) so replies and renames can reach "
               "your agents.")
DRIVE_DIR = (os.environ.get("AGENTS_DRIVE") or "").strip() or None

CONV_EVERY = 5.0          # table, storage, alarms
WAIT_EVERY = 30.0         # waiting list
PUMP_EVERY = 5.0          # outbox retries
HOVER_DELAY = 0.35
CLOSE_GRACE = 0.3
CARD_SECONDS = 0.18
GROUP_RETRY = 600.0

ENGINE = None             # monitor_data, loaded once
ACT = None                # monitor_actions
RT = None                 # richtext


def load_modules():
    """ONE engine module object for the life of the app (it holds the transcript cache in memory).
    monitor_actions imports "monitor_data" and gets this same object from sys.modules."""
    global ENGINE, ACT, RT
    if ENGINE is None:
        spec = importlib.util.spec_from_file_location("monitor_data", os.path.join(HERE, "monitor_data.py"))
        mod = importlib.util.module_from_spec(spec)
        sys.modules["monitor_data"] = mod
        spec.loader.exec_module(mod)
        ENGINE = mod
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    import monitor_actions
    import richtext
    ACT, RT = monitor_actions, richtext


def clean(s):
    """Every displayed string passes through here: never an em dash on screen."""
    s = "" if s is None else str(s)
    if ENGINE is not None and hasattr(ENGINE, "no_em_dash"):
        s = ENGINE.no_em_dash(s)
    return s.replace("\u2014", ", ")


def one_line(s):
    return re.sub(r"\s+", " ", clean(s)).strip()


def first_chars(s, n):
    s = one_line(s)
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"


def local_clock(t=None):
    return datetime.datetime.fromtimestamp(t if t is not None else time.time()).strftime("%-I:%M:%S %p")


def short_clock(t=None):
    return datetime.datetime.fromtimestamp(t if t is not None else time.time()).strftime("%-I:%M %p")


def age_words(seconds):
    """How long ago, in plain words: "less than a minute", "4 min", "2 h 5 min", "3 d 4 h"."""
    s = max(0, int(seconds or 0))
    if s < 60:
        return "less than a minute"
    if s < 3600:
        return f"{s // 60} min"
    if s < 86400:
        return f"{s // 3600} h {(s % 3600) // 60} min"
    return f"{s // 86400} d {(s % 86400) // 3600} h"


def just_now(seconds):
    s = max(0, int(seconds or 0))
    return "just now" if s < 60 else f"{age_words(s)} ago"


# ---------------------------------------------------------------------------------------------
# Look: after Native Instruments Maschine's browser (near-black panels, light grey text, small
# uppercase letter-spaced headers, thin separators, lighter grey selection, one orange accent).
# ---------------------------------------------------------------------------------------------

def rgb(hexstr, a=1.0):
    h = hexstr.lstrip("#")
    return NSColor.colorWithSRGBRed_green_blue_alpha_(
        int(h[0:2], 16) / 255.0, int(h[2:4], 16) / 255.0, int(h[4:6], 16) / 255.0, a)


BG = rgb("141414")
PANEL = rgb("1c1c1c")
HEAD_BG = rgb("1c1c1c")
SEP = rgb("262626")
SEP_STRONG = rgb("303030")
SELECT = rgb("333336")
TEXT = rgb("c6c6c6")
TEXT_BRIGHT = rgb("dedede")
DIM = rgb("7a7a7a")
DIMMER = rgb("5e5e5e")
HEAD_TEXT = rgb("8e8e8e")
ORANGE = rgb("f39c2b")
YELLOW = rgb("e9cf4f")
DECISION = rgb("bdbdbd")
RED = rgb("e5484d")
RED_BG = rgb("7a1f1f")
RED_TEXT = rgb("ffe3e3")
NOTICE_BG = rgb("3a2d12")
NOTICE_TEXT = rgb("ffd79a")
GREEN = rgb("3fb950")
GROUP_BG = rgb("202023")
FIELD_BG = rgb("121212")
FIELD_BORDER = rgb("343434")
CARD_BG = rgb("26262a")
CARD_BORDER = rgb("ffffff", 0.13)
PILL_BG = rgb("ffffff", 0.06)
PILL_BORDER = rgb("ffffff", 0.16)
TAG_BORDER = rgb("ffffff", 0.14)
HOVER_WASH = rgb("ffffff", 0.03)
MEMBER_LINE = rgb("ffffff", 0.22)

FONT = NSFont.systemFontOfSize_(12.5)
FONT_TITLE = NSFont.systemFontOfSize_weight_(12.5, NSFontWeightMedium)
FONT_NUM = NSFont.monospacedDigitSystemFontOfSize_weight_(12.5, NSFontWeightRegular)
FONT_HEAD = NSFont.systemFontOfSize_weight_(10.0, NSFontWeightSemibold)
FONT_ITEM = NSFont.systemFontOfSize_(12.5)
FONT_META = NSFont.monospacedDigitSystemFontOfSize_weight_(10.5, NSFontWeightRegular)
FONT_TAG = NSFont.systemFontOfSize_weight_(9.5, NSFontWeightMedium)
FONT_HEADER_LINE = NSFont.systemFontOfSize_weight_(12.0, NSFontWeightMedium)
FONT_HEADER_NUM = NSFont.monospacedDigitSystemFontOfSize_weight_(12.0, NSFontWeightSemibold)
FONT_FOOT = NSFont.monospacedDigitSystemFontOfSize_weight_(10.5, NSFontWeightRegular)
FONT_GROUP = NSFont.systemFontOfSize_weight_(12.0, NSFontWeightSemibold)
FONT_SMALL = NSFont.systemFontOfSize_(11.0)
FONT_CARD_TITLE = NSFont.systemFontOfSize_weight_(13.0, NSFontWeightSemibold)
FONT_CARD = NSFont.systemFontOfSize_(12.5)
FONT_PILL = NSFont.systemFontOfSize_weight_(12.0, NSFontWeightMedium)
FONT_KEY = NSFont.systemFontOfSize_(10.5)
FONT_ALARM = NSFont.systemFontOfSize_weight_(12.0, NSFontWeightSemibold)
FONT_ALARM_META = NSFont.systemFontOfSize_(11.0)
FONT_STORAGE = NSFont.monospacedDigitSystemFontOfSize_weight_(11.0, NSFontWeightRegular)

CONV_ROW_H = 24.0
HEAD_H = 26.0
PAD_X = 10.0
SORTBAR_H = 28.0
ALARM_LINE_H = 24.0
ALARM_MAX_LINES = 3
NOTICE_H = 26.0
UNJUST_HEAD_H = 30.0
STORAGE_H = 24.0
LIST_HEAD_H = 30.0
FOOT_H = 22.0
MSG_PAD = 8.0

# a waiting item row
IL = 34.0                 # text left (the checkbox sits in front of it)
IR = 14.0
I_PAD_T = 8.0
I_GAP = 3.0
I_FIELD_GAP = 6.0
I_PAD_B = 9.0
FIELD_MIN_H = 24.0
FIELD_MAX_LINES = 6
CARD_MARGIN = 8.0         # room for the card's shadow inside its clipping slot
CARD_MAX_W = 640.0        # the card stays compact however wide the window is
GROUP_PAD = 9.0

DRAW_OPTS = NSStringDrawingUsesLineFragmentOrigin | NSStringDrawingUsesFontLeading

_LH = {}


def line_height(font):
    key = (str(font.fontName()), float(font.pointSize()))
    if key not in _LH:
        _LH[key] = math.ceil(NSLayoutManager.alloc().init().defaultLineHeightForFont_(font))
    return _LH[key]


def para(align=NSTextAlignmentLeft, wrap=False):
    p = NSMutableParagraphStyle.alloc().init()
    p.setAlignment_(align)
    p.setLineBreakMode_(NSLineBreakByWordWrapping if wrap else NSLineBreakByTruncatingTail)
    return p


P_LEFT = para()
P_RIGHT = para(NSTextAlignmentRight)
P_CENTER = para(NSTextAlignmentCenter)
P_WRAP = para(wrap=True)


def attr(text, font, color, style=P_LEFT, kern=None, underline=False):
    d = {NSFontAttributeName: font, NSForegroundColorAttributeName: color, NSParagraphStyleAttributeName: style}
    if kern is not None:
        d[NSKernAttributeName] = kern
    if underline:
        d[NSUnderlineStyleAttributeName] = NSUnderlineStyleSingle
    return NSAttributedString.alloc().initWithString_attributes_(clean(text), d)


def text_height(a, width):
    return math.ceil(a.boundingRectWithSize_options_(NSMakeSize(max(width, 20.0), 1.0e7), DRAW_OPTS).size.height)


def text_width(a):
    return math.ceil(a.size().width)


def draw_line(a, x, y, w):
    """One line of attributed text, truncated with a tail, top at y (flipped views)."""
    if a is None or a.length() == 0 or w <= 4:
        return
    f = a.attribute_atIndex_effectiveRange_(NSFontAttributeName, 0, None)[0]
    a.drawWithRect_options_(NSMakeRect(x, y, w, line_height(f)), DRAW_OPTS | NSStringDrawingTruncatesLastVisibleLine)


def draw_tag(text, x, y, max_w, color=DIM, border=TAG_BORDER, font=FONT_TAG):
    """A small rounded tag, left edge at x, vertically centred on a line whose top is y. Returns its width."""
    a = attr(text, font, color)
    lh = line_height(font)
    w = min(text_width(a) + 10, max_w)
    if w < 24:
        return 0
    h = lh + 2
    r = NSMakeRect(x, y, w, h)
    path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(NSMakeRect(x + 0.5, y + 0.5, w - 1, h - 1), 4, 4)
    border.setStroke()
    path.setLineWidth_(1.0)
    path.stroke()
    draw_line(a, x + 5, y + 1, w - 10)
    return w


_REPORTED = {}


def report_exception(where):
    """An error inside a method AppKit calls is written to app.log once (again only when its text
    changes) and the method returns a safe value: the window never crashes on one bad row."""
    et, ev, _ = sys.exc_info()
    key = f"{type(ev).__name__}: {ev}"
    if _REPORTED.get(where) == key:
        return
    _REPORTED[where] = key
    sys.stderr.write(f"{local_clock()} error in {where}, the window carries on:\n")
    traceback.print_exc()
    sys.stderr.flush()


def safely(fn, *a):
    """For work queued onto the main thread (AppHelper.callAfter): errors are reported, never raised."""
    try:
        return fn(*a)
    except Exception:
        report_exception(getattr(fn, "__name__", "a queued call"))


def trim_log(path=None, limit=LOG_MAX, keep=LOG_KEEP):
    path = path or LOG_PATH
    try:
        size = os.path.getsize(path)
        if size <= limit:
            return size
        with open(path, "r+b") as f:
            f.seek(-keep, 2)
            f.readline()
            tail = f.read()
            f.seek(0)
            f.write(b"(app.log cut to its last part at " + local_clock().encode() + b")\n" + tail)
            f.truncate()
        return os.path.getsize(path)
    except OSError:
        return None


# ---------------------------------------------------------------------------------------------
# Remembered layout: one JSON file in the cache folder, merged (never replaced wholesale), so the keys
# the older app writes there ("frame", "split_top") and the keys this one adds live side by side.
# ---------------------------------------------------------------------------------------------

def read_prefs(path=None):
    try:
        with open(path or PREFS_PATH) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def write_prefs(update, path=None):
    """Merges update into the file; writes only when something changed; atomic. Returns True if written."""
    p = path or PREFS_PATH
    old = read_prefs(p)
    new = dict(old)
    new.update(update)
    if new == old:
        return False
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = f"{p}.{os.getpid()}.tmp"
        with open(tmp, "w") as f:
            json.dump(new, f, indent=1)
        os.replace(tmp, p)
        return True
    except OSError:
        traceback.print_exc()
        return False


def read_drafts(path=None):
    """His unsent drafts (SPEC section 11): {"items": {id: {"text", "t", "about"}}, "dock": {...}}."""
    try:
        with open(path or DRAFTS_PATH) as f:
            d = json.load(f)
        if isinstance(d, dict):
            d.setdefault("items", {})
            return d
    except (OSError, ValueError):
        pass
    return {"items": {}}


def write_drafts(d, path=None):
    p = path or DRAFTS_PATH
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = f"{p}.{os.getpid()}.tmp"
        with open(tmp, "w") as f:
            json.dump(d, f, indent=1)
        os.replace(tmp, p)
        return True
    except OSError:
        traceback.print_exc()
        return False


def cmux_banner_text(reason):
    """SPEC section 11's one plain banner while cmux refuses this process, else None."""
    return CMUX_BANNER if reason else None


def unjust_rows(unjust, open_):
    """The collapsed section at the list's foot (SPEC section 11): its header row, and while it is open,
    one row per ask without a reason. Never selectable, never counted."""
    if not unjust:
        return []
    return [("u", "head")] + ([("u", u["key"]) for u in unjust] if open_ else [])


def row_kind(k):
    return {"g": "group", "u": "unjust"}.get(k, "item")


# ---------------------------------------------------------------------------------------------
# The table's columns and its sorting (SPEC section 1)
# ---------------------------------------------------------------------------------------------

L, R = NSTextAlignmentLeft, NSTextAlignmentRight
COLUMNS = [
    # identifier, title, default width, minimum width, alignment, optional (hidden by default)
    ("title", "Conversation", 190.0, 96.0, L, False),
    ("desc", "Description", 430.0, 150.0, L, False),
    ("time", "Time spent", 122.0, 110.0, R, False),
    ("running", "Running now", 112.0, 110.0, R, False),
    ("tasks", "Tasks run", 94.0, 92.0, R, False),
    ("waiting", "Waiting on you", 128.0, 124.0, R, True),
    ("totalwait", "Total wait", 104.0, 96.0, R, True),
]
COL_BY_ID = {c[0]: c for c in COLUMNS}
OPTIONAL_COLUMNS = [c[0] for c in COLUMNS if c[5]]

SORTS = [
    ("sidebar", "Sidebar order"),
    ("time", "Time spent"),
    ("running", "Running now"),
    ("tasks", "Tasks run"),
    ("decisions", "Most decisions waiting on you"),
    ("wait", "Longest combined wait"),
    ("recent", "Most recently active"),
    ("alpha", "Alphabetical"),
]
SORT_TITLES = dict(SORTS)
# Clicking a header sorts by its column. Description sorts by when its message was written.
COL_SORT = {"title": "alpha", "desc": "recent", "time": "time", "running": "running", "tasks": "tasks",
            "waiting": "decisions", "totalwait": "wait"}
SORT_COL = {v: k for k, v in COL_SORT.items()}


def conv_key(row):
    return row.get("tty") or row.get("session_id") or row.get("title")


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def live_seconds(row, now):
    if ENGINE is not None and hasattr(ENGINE, "live_seconds"):
        return ENGINE.live_seconds(row, now)
    return int(row.get("seconds_working") or 0)


def total_wait_live(row, now):
    """The row's combined waiting time, ticking: every item of his adds one second a second."""
    tw = _num(row.get("total_wait_seconds"))
    if tw is None:
        return None
    n = _num(row.get("decisions_waiting")) or 0
    as_of = _num(row.get("waits_as_of"))
    return tw + (n * max(0.0, now - as_of) if as_of else 0)


def time_known(row):
    return bool(row.get("time_text")) or _num(row.get("seconds_working")) not in (None, 0)


def sort_value(row, key, now):
    """The value a row sorts by, or None when unknown (unknowns always go last)."""
    if key == "time":
        return live_seconds(row, now) if time_known(row) else None
    if key == "running":
        return _num(row.get("running_now"))
    if key == "tasks":
        return _num(row.get("tasks_run"))
    if key == "decisions":
        n = _num(row.get("decisions_waiting"))
        wo = 1 if row.get("waiting_on_you") else 0
        if n is None and not wo:
            return None
        return (wo, n if n is not None else -1)
    if key == "wait":
        return total_wait_live(row, now)
    if key == "recent":
        return _num(row.get("last_entry_ts")) or _num(row.get("full_text_ts"))
    if key == "alpha":
        return one_line(row.get("title") or row.get("tty") or "").casefold()
    return None


def sort_rows(rows, key, reverse=False, now=None):
    """rows arrive in cmux sidebar order. Numbers sort largest first, names A to Z; reverse flips that;
    ties keep sidebar order; unknown values always last."""
    now = time.time() if now is None else now
    rows = list(rows)
    if key not in SORT_TITLES or key == "sidebar":
        return rows[::-1] if reverse else rows
    known = [r for r in rows if sort_value(r, key, now) is not None]
    unknown = [r for r in rows if sort_value(r, key, now) is None]
    natural_desc = key != "alpha"
    known.sort(key=lambda r: sort_value(r, key, now), reverse=(natural_desc != bool(reverse)))
    return known + unknown


def sort_arrow(key, reverse):
    """'down' when the largest (or Z) is on top, 'up' when the smallest (or A) is; None for sidebar order."""
    if key == "sidebar" or key not in SORT_TITLES:
        return None
    natural = "up" if key == "alpha" else "down"
    return natural if not reverse else ("down" if natural == "up" else "up")


def time_cell_text(row, now):
    return ENGINE.clock_text(live_seconds(row, now)) if time_known(row) else "?"


# ---------------------------------------------------------------------------------------------
# REDESIGN-PLAN.md Phase 0 (SPEC section 0 item 17): true counts, his words kept, checks capped
# ---------------------------------------------------------------------------------------------

CHECK_AT_ONCE = 2        # already-resolved checks at one time when he answers several items (each may start Claude)
# The engine's flag that a lane's own count does not match the waiting list (monitor_data, Phase 0 item 1),
# read under any of these names, on a row or on the waiting() result, so the window works before and after
# the engine carries it.
MISMATCH_ROW_KEYS = ("waiting_mismatch", "count_mismatch", "counts_mismatch", "mismatch")
# "mismatch_lanes" is the key the engine publishes (a list of lane names; the reasons sit in w["lanes"]); the
# others are the names the first pass guessed before the engine carried it (second pass, 15 Sep).
MISMATCH_LIST_KEYS = ("mismatch_lanes", "waiting_mismatches", "count_mismatches", "counts_mismatches", "mismatches",
                      "lane_mismatches")
NOTE_FACTS = ("not been read", "no live owner")   # what the app's own two row notes state; the engine's may say it first


def _flag_reason(v):
    """(flagged, reason) for one flag value: True, a reason string, a nonzero number, or a dict (its
    reason, note or why; "mismatch": False or "ok": True in it means not flagged)."""
    if isinstance(v, dict):
        if v.get("mismatch") is False or v.get("ok") is True:
            return False, ""
        return bool(v), one_line(clean(v.get("reason") or v.get("note") or v.get("why") or ""))
    if isinstance(v, str):
        return bool(v.strip()), one_line(clean(v))
    if isinstance(v, bool):
        return v, ""
    return (isinstance(v, (int, float)) and v != 0), ""


def _lane_reason(w, lane):
    """The engine's own explanation for a lane it flags (monitor_data.lane_report, w["lanes"][lane]): the
    count from the list beside each number the lane typed, e.g. "0 on the list, but status headline says 2"."""
    lanes = w.get("lanes") if isinstance(w, dict) else None
    v = lanes.get(lane) if isinstance(lanes, dict) else None
    if not isinstance(v, dict):
        return ""
    n = _num(v.get("items"))
    typed = [t for t in (v.get("typed") or []) if isinstance(t, dict) and _num(t.get("said")) is not None]
    if n is None or not typed:
        return one_line(v.get("note") or v.get("reason") or "")
    parts = [f'{one_line(t.get("where") or "its words")} says {t["said"]}' for t in typed if t["said"] != n]
    return f"{n} on the list, but " + ", ".join(parts) if parts else ""


def list_mismatches(w):
    """{("lane", name casefolded) or ("session", id): reason} from a mismatch report on a waiting() result:
    the engine's mismatch_lanes (a list of lane names, each reason read from w["lanes"]), or a dict
    lane -> flag, or a list of dicts with "lane" and/or "session_id"."""
    out = {}
    if not isinstance(w, dict):
        return out
    for key in MISMATCH_LIST_KEYS:
        v = w.get(key)
        if isinstance(v, dict):
            for name, val in v.items():
                ok, why = _flag_reason(val)
                if ok and str(name or "").strip():
                    out[("lane", str(name).strip().casefold())] = why or _lane_reason(w, str(name).strip())
        elif isinstance(v, (list, tuple)):
            for e in v:
                if isinstance(e, str) and e.strip():
                    out[("lane", e.strip().casefold())] = _lane_reason(w, e.strip())
                elif isinstance(e, dict):
                    ok, why = _flag_reason(e)
                    if not ok:
                        continue
                    if str(e.get("lane") or "").strip():
                        out[("lane", str(e["lane"]).strip().casefold())] = why or _lane_reason(w, str(e["lane"]).strip())
                    if e.get("session_id"):
                        out[("session", str(e["session_id"]))] = why
    return out


def note_adds(engine_note, app_note):
    """Whether the app's row note says anything the engine's does not. The app's two notes each state one
    of NOTE_FACTS; when the engine's note already states that fact, the app's adds nothing."""
    e, a = one_line(engine_note).casefold(), one_line(app_note).casefold()
    facts = [f for f in NOTE_FACTS if f in a]
    return any(f not in e for f in facts) if facts else bool(a) and a not in e


def count_rows(rows, items, list_read, mismatches=None, as_of=None):
    """Copies of the rows whose "Waiting on you" number is counted from the waiting list's own items, never a
    number a lane typed (Phase 0 item 1), so the cell, the "most decisions" sort and Total wait all read the
    count the list shows:
      the row's lane is known: the items whose owner lane is that lane;
      no lane: the items whose owner session is the row's session; when none is, and some item has no live
        owner (it could be this conversation's), the number is not known: None, shown "?", never a false 0;
      the list has not been read yet: None.
    waiting_engine keeps the engine's own number. waiting_note keeps the engine's own explanation of the row
    (waiting_note_engine) and appends the app's (waiting_note_app) only when it adds a fact (second pass,
    15 Sep: the first pass overwrote it on 14 of 16 rows). waiting_red, waiting_red_why: the engine flags
    that lane's count as not matching, on the row itself or in the waiting() result by lane or session."""
    items = [i for i in (items or []) if isinstance(i, dict)]
    mismatches = mismatches or {}
    out = []
    for r in rows or []:
        r = dict(r)
        lane = r.get("lane").strip() if isinstance(r.get("lane"), str) else ""
        sid = r.get("session_id")
        mine, note = None, ""
        if not list_read:
            note = "the waiting list has not been read yet"
        elif lane:
            mine = [i for i in items if str(item_owner(i)).casefold() == lane.casefold()]
        else:
            owned = [i for i in items if sid and i.get("owner_session") == sid]
            if owned or all(i.get("owner_session") for i in items):
                mine = owned
            else:
                free = sum(1 for i in items if not i.get("owner_session"))
                note = (f"this conversation is not matched to a lane, and {free} "
                        f"{'item on the list has' if free == 1 else 'items on the list have'} no live owner")
        r["waiting_engine"] = r.get("decisions_waiting")
        if mine is None:
            r.update(decisions_waiting=None, total_wait_seconds=None, waits_as_of=None)
        else:
            r.update(decisions_waiting=len(mine),
                     total_wait_seconds=sum(int(_num(i.get("waited_seconds")) or 0) for i in mine), waits_as_of=as_of)
        eng = one_line(r.get("waiting_note") or "")
        r["waiting_note_engine"], r["waiting_note_app"] = eng, note
        if not eng:
            r["waiting_note"] = note
        elif note and note_adds(eng, note):
            r["waiting_note"] = f"{eng}; {note}"
        else:
            r["waiting_note"] = eng
        red, why = False, ""
        for key in MISMATCH_ROW_KEYS:
            if key in r:
                red, why = _flag_reason(r.get(key))
                if red:
                    break
        if not red:
            for k in ((("lane", lane.casefold()),) if lane else ()) + ((("session", str(sid)),) if sid else ()):
                if k in mismatches:
                    red, why = True, mismatches[k]
                    break
        r["waiting_red"], r["waiting_red_why"] = bool(red), (why if red else "")
        out.append(r)
    return out


def _sentence(s):
    s = one_line(s).rstrip(".")
    return s + "." if s else ""


def waiting_tip(n, red, why, note):
    """The Waiting on you cell's tooltip: what the cell shows, then why. A "?" never claims a number was
    counted (second pass, 15 Sep); a red count gives the engine's reason, and the engine's own row note when
    the flag came with none; a plain count with a note (an unmatched row reading 0) explains it; a plain
    count with nothing to say has no tooltip."""
    why, note = one_line(why or ""), one_line(note or "")
    flag = "The engine flags this lane's own count as not matching the waiting list"
    if n is None:
        tip = "Not known, shown as ?: " + _sentence(note or "the waiting list has not been read yet")
        return tip + (f" {flag}{': ' + why if why else ''}." if red else "")
    tip = f"Shown {n}, counted from the waiting list's items."
    if red:
        reason = why or note
        tip += f" {flag}{': ' + reason if reason else ''}."
        if why and note and note.casefold() not in why.casefold():
            tip += " " + _sentence(note)
        return tip
    return tip + " " + _sentence(note) if note else None


def reply_handoff(result):
    """(handed off, ledger warning) for one reply result. Handed off: delivered or held (the outbox owns his
    words) AND his words reached the ANSWERS ledger. Only then do his words leave the field; a failed,
    refused or unanswered send, or a ledger that could not be written, keeps them (Phase 0 item 3)."""
    r = result if isinstance(result, dict) else {}
    warn = one_line(clean(r.get("ledger_error") or ""))
    return (r.get("state") in ("delivered", "held") and not warn), warn


def check_items(check, items, limit=CHECK_AT_ONCE):
    """check(item) for every item, at most `limit` at a time from one queue (each check may start a Claude
    process), the results in the items' order whatever order they finish in. A check that raises reads as open."""
    items = list(items or [])
    out = [None] * len(items)
    if not items:
        return out
    q = queue_mod.Queue()
    for k in range(len(items)):
        q.put(k)

    def work():
        while True:
            try:
                k = q.get_nowait()
            except queue_mod.Empty:
                return
            try:
                out[k] = check(items[k])
            except Exception:
                out[k] = (False, "the check failed, treated as open", "the app")
    ts = [threading.Thread(target=work, name="agents-check", daemon=True)
          for _ in range(max(1, min(int(limit or 1), len(items))))]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    return out


# ---------------------------------------------------------------------------------------------
# The waiting list: order, groups, waiting time (SPEC section 2)
# ---------------------------------------------------------------------------------------------

def needs_more_count(counts):
    return sum(int(v or 0) for k, v in (counts or {}).items() if k != "decision")


def header_text(w):
    if not w.get("ok"):
        return clean(w.get("message") or "The waiting list could not be read.")
    n = needs_more_count(w.get("counts"))
    verb = "needs" if n == 1 else "need"
    return f"{w.get('total')} waiting on you. {n} {verb} more than a decision."


def item_owner(it):
    return it.get("owner_lane") or it.get("lane") or ""


def group_key(g):
    return "g:" + ",".join(g.get("members") or [])


def valid_groups(groups, items):
    """Groups kept against the current items: members that still exist, each item in one group only,
    at least two members from at least two different owners."""
    by_id = {i.get("id"): i for i in items if i.get("id")}
    used, out = set(), []
    for g in groups or []:
        if not isinstance(g, dict):
            continue
        members = [m for m in (g.get("members") or []) if m in by_id and m not in used]
        if len(members) < 2 or len({item_owner(by_id[m]) for m in members}) < 2:
            continue
        used.update(members)
        order = {i.get("id"): k for k, i in enumerate(items)}
        g = dict(g, members=sorted(members, key=lambda m: order[m]))
        out.append(g)
    return out


def build_display(items, groups):
    """[("g", group key) | ("i", item id)] in manifest order; a group sits where its first member
    would, with its members under it."""
    member_of = {}
    for gi, g in enumerate(groups):
        for m in g.get("members") or []:
            member_of.setdefault(m, gi)
    out, emitted = [], set()
    for it in items:
        iid = it.get("id")
        gi = member_of.get(iid)
        if gi is None:
            out.append(("i", iid))
            continue
        if gi in emitted:
            continue
        emitted.add(gi)
        out.append(("g", group_key(groups[gi])))
        for m in groups[gi]["members"]:
            out.append(("i", m))
    return out


def item_wait_seconds(it, now, as_of=None):
    ws = _num(it.get("waiting_since"))
    if ws is not None:
        return max(0.0, now - ws)
    w = _num(it.get("waited_seconds"))
    if w is None:
        return None
    return w + (max(0.0, now - as_of) if as_of else 0.0)


def item_wait_text(it, now, as_of=None):
    s = item_wait_seconds(it, now, as_of)
    if s is None:
        return ""
    return ("waiting at least " if it.get("wait_at_least") else "waiting ") + ENGINE.wait_text(s)


# ---------------------------------------------------------------------------------------------
# The card's motion (SPEC section 4): one function, both branches, so --check can drive each
# ---------------------------------------------------------------------------------------------

def reduce_motion():
    try:
        return bool(NSWorkspace.sharedWorkspace().accessibilityDisplayShouldReduceMotion())
    except Exception:
        return False


def card_motion(reduce):
    """(seconds, slides): 0.18 s ease-out slide normally; with Reduce Motion no motion at all."""
    return (0.0, False) if reduce else (CARD_SECONDS, True)


# ---------------------------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------------------------

class FlippedView(NSView):
    """A plain container; layout_fn(view) lays its children out whenever its size changes."""

    def initWithFrame_(self, frame):
        self = objc.super(FlippedView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.layout_fn = None
        self.fill = None
        return self

    def isFlipped(self):
        return True

    def resizeSubviewsWithOldSize_(self, old):
        try:
            return self._resizeSubviewsWithOldSize_impl(old)
        except Exception:
            report_exception("resizeSubviewsWithOldSize_")
            return None

    @objc.python_method
    def _resizeSubviewsWithOldSize_impl(self, old):
        if self.layout_fn is not None:
            self.layout_fn(self)

    def drawRect_(self, rect):
        try:
            return self._drawRect_impl(rect)
        except Exception:
            report_exception("drawRect_")
            return None

    @objc.python_method
    def _drawRect_impl(self, rect):
        # bounds, never the dirty rect: since macOS 14 views do not clip to their bounds and the rect
        # AppKit passes can cover the whole window (measured 10 Sep: the message bar painted over it)
        if self.fill is not None:
            self.fill.setFill()
            NSRectFill(self.bounds())


class LineCell(NSView):
    """One line of text, vertically centred, truncated with a tail."""

    def initWithFrame_(self, frame):
        self = objc.super(LineCell, self).initWithFrame_(frame)
        if self is None:
            return None
        self.text_attr = None
        self.fill = None
        self.inset = PAD_X
        self.line_top = None
        self.setLayerContentsRedrawPolicy_(NSViewLayerContentsRedrawDuringViewResize)
        return self

    def isFlipped(self):
        return True

    @objc.python_method
    def show(self, a, tip=None):
        same = (self.text_attr is not None and a is not None and self.text_attr.isEqualToAttributedString_(a))
        self.text_attr = a
        self.setToolTip_(tip if tip else None)
        if not same:
            self.setNeedsDisplay_(True)

    @objc.python_method
    def plain(self):
        return "" if self.text_attr is None else str(self.text_attr.string())

    def drawRect_(self, rect):
        try:
            return self._drawRect_impl(rect)
        except Exception:
            report_exception("drawRect_")
            return None

    @objc.python_method
    def _drawRect_impl(self, rect):
        b = self.bounds()
        if self.fill is not None:
            self.fill.setFill()
            NSRectFill(b)
        if self.line_top is not None:
            self.line_top.setFill()
            NSRectFill(NSMakeRect(0, 0, b.size.width, 1))
        if self.text_attr is None or self.text_attr.length() == 0:
            return
        lh = line_height(self.text_attr.attribute_atIndex_effectiveRange_(NSFontAttributeName, 0, None)[0])
        draw_line(self.text_attr, self.inset, math.floor((b.size.height - lh) / 2.0), b.size.width - 2 * self.inset)


class DescCell(NSView):
    """The Description cell: the formatted line, and when it breaks its limit a small tag at the right
    ("over 50" / "over 200") so the rule breaker is visible; the line itself shows its first words."""

    def initWithFrame_(self, frame):
        self = objc.super(DescCell, self).initWithFrame_(frame)
        if self is None:
            return None
        self.text_attr = None
        self.tag = None
        self.setLayerContentsRedrawPolicy_(NSViewLayerContentsRedrawDuringViewResize)
        return self

    def isFlipped(self):
        return True

    @objc.python_method
    def show(self, a, tag, tip=None):
        self.text_attr, self.tag = a, tag
        self.setToolTip_(tip if tip else None)
        self.setNeedsDisplay_(True)

    @objc.python_method
    def plain(self):
        return ("" if self.text_attr is None else str(self.text_attr.string())) + (f" [{self.tag}]" if self.tag else "")

    def drawRect_(self, rect):
        try:
            return self._drawRect_impl(rect)
        except Exception:
            report_exception("drawRect_")
            return None

    @objc.python_method
    def _drawRect_impl(self, rect):
        b = self.bounds()
        right = b.size.width - PAD_X
        if self.tag:
            ta = attr(self.tag, FONT_TAG, ORANGE)
            tw = text_width(ta) + 10
            th = line_height(FONT_TAG) + 2
            x = right - tw
            y = math.floor((b.size.height - th) / 2.0)
            path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(NSMakeRect(x + 0.5, y + 0.5, tw - 1, th - 1), 4, 4)
            rgb("f39c2b", 0.55).setStroke()
            path.setLineWidth_(1.0)
            path.stroke()
            draw_line(ta, x + 5, y + 1, tw - 10)
            right = x - 8
        if self.text_attr is None or self.text_attr.length() == 0:
            return
        f = self.text_attr.attribute_atIndex_effectiveRange_(NSFontAttributeName, 0, None)[0]
        lh = line_height(f)
        draw_line(self.text_attr, PAD_X, math.floor((b.size.height - lh) / 2.0), right - PAD_X)


class RowView(NSTableRowView):
    """Near-black row, one thin separator at its foot, lighter grey when selected. A conversation that
    is waiting on him carries the orange accent bar at its left edge; a group header has its own tint."""

    def initWithFrame_(self, frame):
        self = objc.super(RowView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.accent = False
        self.kind = "row"
        self.member = False            # an item under a group header
        self.member_more = False       # and the next row is in the same group
        return self

    def drawBackgroundInRect_(self, rect):
        (GROUP_BG if self.kind == "group" else PANEL).setFill()
        NSRectFill(self.bounds())
        self._extras()

    def drawSelectionInRect_(self, rect):
        if self.kind == "group":
            GROUP_BG.setFill()
        else:
            SELECT.setFill()
        NSRectFill(self.bounds())
        self._extras()

    def drawSeparatorInRect_(self, rect):
        pass

    @objc.python_method
    def _extras(self):
        b = self.bounds()
        y = b.size.height - 1 if self.isFlipped() else 0
        SEP.setFill()
        NSRectFill(NSMakeRect(0, y, b.size.width, 1))
        if self.accent:
            ORANGE.setFill()
            NSRectFill(NSMakeRect(0, 0, 3, b.size.height))
        if self.member or self.kind == "group":
            MEMBER_LINE.setFill()
            top = GROUP_PAD if self.kind == "group" else 0
            NSRectFill(NSMakeRect(4, top, 2, b.size.height - top - (0 if self.member_more else 6)))


def draw_header_label(title, frame, align, arrow=None):
    right = align == NSTextAlignmentRight
    a = attr(str(title).upper(), FONT_HEAD, HEAD_TEXT, P_RIGHT if right else P_LEFT, kern=1.1)
    lh = line_height(FONT_HEAD)
    y = frame.origin.y + math.floor((frame.size.height - lh) / 2.0)
    x0, w = frame.origin.x + PAD_X, frame.size.width - 2 * PAD_X
    if arrow:
        # a small solid triangle; it sits after a left label and before a right one
        aw = 7.0
        if right:
            ax = frame.origin.x + frame.size.width - PAD_X - aw
            w -= aw + 5
        else:
            lw = min(text_width(a), w - aw - 5)
            ax = x0 + lw + 5
        cy = frame.origin.y + frame.size.height / 2.0
        p = NSBezierPath.bezierPath()
        if arrow == "up":
            p.moveToPoint_((ax, cy + 2.5)); p.lineToPoint_((ax + aw, cy + 2.5)); p.lineToPoint_((ax + aw / 2.0, cy - 2.5))
        else:
            p.moveToPoint_((ax, cy - 2.5)); p.lineToPoint_((ax + aw, cy - 2.5)); p.lineToPoint_((ax + aw / 2.0, cy + 2.5))
        p.closePath()
        ORANGE.setFill()
        p.fill()
    a.drawWithRect_options_(NSMakeRect(x0, y, w, lh), DRAW_OPTS | NSStringDrawingTruncatesLastVisibleLine)


class HeaderCell(NSTableHeaderCell):
    """Used by AppKit while a column is dragged; the header view draws everything else itself."""

    def drawWithFrame_inView_(self, frame, view):
        HEAD_BG.setFill()
        NSRectFill(frame)
        draw_header_label(self.stringValue(), frame, self.alignment())

    def drawInteriorWithFrame_inView_(self, frame, view):
        self.drawWithFrame_inView_(frame, view)


class HeaderView(NSTableHeaderView):
    """Small uppercase letter-spaced labels on near-black, a thin divider between columns (where the
    drag to resize is), and the sort arrow on the sorted column."""

    def initWithFrame_(self, frame):
        self = objc.super(HeaderView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.arrow_col = None
        self.arrow = None
        return self

    def drawRect_(self, rect):
        try:
            return self._drawRect_impl(rect)
        except Exception:
            report_exception("drawRect_")
            return None

    @objc.python_method
    def _drawRect_impl(self, rect):
        b = self.bounds()
        HEAD_BG.setFill()
        NSRectFill(b)
        tv = self.tableView()
        if tv is not None:
            for i, col in enumerate(tv.tableColumns()):
                if col.isHidden():
                    continue
                r = self.headerRectOfColumn_(i)
                arrow = self.arrow if str(col.identifier()) == self.arrow_col else None
                draw_header_label(col.headerCell().stringValue(), r, col.headerCell().alignment(), arrow)
                SEP.setFill()
                NSRectFill(NSMakeRect(r.origin.x + r.size.width - 1, r.origin.y + 6, 1, r.size.height - 12))
        SEP_STRONG.setFill()
        y = b.size.height - 1 if self.isFlipped() else 0
        NSRectFill(NSMakeRect(0, y, b.size.width, 1))


class Split(NSSplitView):
    def dividerThickness(self):
        return 5.0

    def drawDividerInRect_(self, rect):
        BG.setFill()
        NSRectFill(rect)
        SEP_STRONG.setFill()
        NSRectFill(NSMakeRect(rect.origin.x, rect.origin.y + 2, rect.size.width, 1))


class TrackingOwner(NSObject):
    """Receives the pointer's moves over one view and hands them to the controller with the view's name."""

    def initWithSource_controller_view_(self, src, ctl, view):
        self = objc.super(TrackingOwner, self).init()
        if self is None:
            return None
        self.src, self.ctl, self.view = src, ctl, view
        return self

    @objc.python_method
    def _point(self, event):
        return self.view.convertPoint_fromView_(event.locationInWindow(), None)

    def mouseMoved_(self, event):
        try:
            return self._mouseMoved_impl(event)
        except Exception:
            report_exception("mouseMoved_")
            return None

    @objc.python_method
    def _mouseMoved_impl(self, event):
        self.ctl.hover_move(self.src, self._point(event))

    def mouseEntered_(self, event):
        try:
            return self._mouseEntered_impl(event)
        except Exception:
            report_exception("mouseEntered_")
            return None

    @objc.python_method
    def _mouseEntered_impl(self, event):
        self.ctl.hover_move(self.src, self._point(event))

    def mouseExited_(self, event):
        try:
            return self._mouseExited_impl(event)
        except Exception:
            report_exception("mouseExited_")
            return None

    @objc.python_method
    def _mouseExited_impl(self, event):
        self.ctl.hover_exit(self.src)


def add_tracking(view, owner):
    opts = NSTrackingMouseMoved | NSTrackingMouseEnteredAndExited | NSTrackingActiveAlways | NSTrackingInVisibleRect
    ta = NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(NSMakeRect(0, 0, 0, 0), opts, owner, None)
    view.addTrackingArea_(ta)
    return ta


class ReplyField(NSTextField):
    """A text field where Return sends and Shift-Return adds a line (the controller is its delegate)."""

    def initWithFrame_(self, frame):
        self = objc.super(ReplyField, self).initWithFrame_(frame)
        if self is None:
            return None
        self.role = "item"
        self.iid = None
        self.setBezeled_(False)
        self.setBordered_(False)
        self.setDrawsBackground_(False)
        self.setFocusRingType_(NSFocusRingTypeNone)
        self.setFont_(FONT_ITEM)
        self.setTextColor_(TEXT_BRIGHT)
        self.setUsesSingleLineMode_(False)
        self.cell().setWraps_(True)
        self.cell().setScrollable_(False)
        self.cell().setLineBreakMode_(NSLineBreakByWordWrapping)
        self.setEditable_(True)
        self.setSelectable_(True)
        return self

    @objc.python_method
    def set_placeholder(self, text):
        self.setPlaceholderAttributedString_(attr(text, FONT_ITEM, DIMMER))


class FieldBox(NSView):
    """The rounded dark box a ReplyField sits in."""

    def initWithFrame_(self, frame):
        self = objc.super(FieldBox, self).initWithFrame_(frame)
        if self is None:
            return None
        self.field = ReplyField.alloc().initWithFrame_(NSMakeRect(7, 4, max(10, frame.size.width - 14), 16))
        self.addSubview_(self.field)
        return self

    def isFlipped(self):
        return True

    def resizeSubviewsWithOldSize_(self, old):
        try:
            return self._resizeSubviewsWithOldSize_impl(old)
        except Exception:
            report_exception("resizeSubviewsWithOldSize_")
            return None

    @objc.python_method
    def _resizeSubviewsWithOldSize_impl(self, old):
        b = self.bounds()
        self.field.setFrame_(NSMakeRect(7, 4, max(10.0, b.size.width - 14), max(14.0, b.size.height - 8)))

    def drawRect_(self, rect):
        try:
            return self._drawRect_impl(rect)
        except Exception:
            report_exception("drawRect_")
            return None

    @objc.python_method
    def _drawRect_impl(self, rect):
        b = self.bounds()
        p = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(NSMakeRect(0.5, 0.5, b.size.width - 1, b.size.height - 1), 6, 6)
        FIELD_BG.setFill()
        p.fill()
        editing = self.window() is not None and self.field.currentEditor() is not None \
            and self.window().firstResponder() == self.field.currentEditor()
        (rgb("5a5a5a") if editing else FIELD_BORDER).setStroke()
        p.setLineWidth_(1.0)
        p.stroke()


def shift_held(ev):
    """True when Shift is down for the key that asked for a new line. The key event being handled
    says so; with no key event at hand (a menu, a script), the keyboard's state right now does."""
    try:
        if ev is not None and int(ev.type()) in (10, 11):
            return bool(ev.modifierFlags() & NSEventModifierFlagShift)
        return bool(NSEvent.modifierFlags() & NSEventModifierFlagShift)
    except Exception:
        return False


def field_height(text, width, font=FONT_ITEM, max_lines=FIELD_MAX_LINES):
    lh = line_height(font)
    if not text:
        return FIELD_MIN_H
    h = text_height(attr(text + ("​" if text.endswith("\n") else ""), font, TEXT, P_WRAP), width - 14 - 4)
    return max(FIELD_MIN_H, min(h, lh * max_lines) + 8)


class CheckButton(NSButton):
    def initWithFrame_(self, frame):
        self = objc.super(CheckButton, self).initWithFrame_(frame)
        if self is None:
            return None
        self.iid = None
        self.setButtonType_(NSButtonTypeSwitch)
        self.setTitle_("")
        self.setFocusRingType_(NSFocusRingTypeNone)
        return self


class LinkButton(NSButton):
    """A small borderless word (Cancel) that acts on one outbox entry."""

    def initWithFrame_(self, frame):
        self = objc.super(LinkButton, self).initWithFrame_(frame)
        if self is None:
            return None
        self.entry_id = None
        self.role = None
        self.setBordered_(False)
        self.setFocusRingType_(NSFocusRingTypeNone)
        self.setAttributedTitle_(attr("Cancel", FONT_SMALL, ORANGE, underline=True))
        return self

    def resetCursorRects(self):
        self.addCursorRect_cursor_(self.bounds(), NSCursor.pointingHandCursor())


STATUS_COLORS = {"info": DIM, "ok": rgb("8fbf8f"), "held": YELLOW, "error": RED}


class ItemView(NSView):
    """One waiting item: checkbox, its full text (yellow when it needs more than a decision), a meta line
    (lane, what it needs, how long it has waited, a "may be settled" tag), a status line (checking,
    sent, waiting to deliver with Cancel, not sent), then its reply field, or the already-resolved card
    sliding down over that field."""

    def initWithFrame_(self, frame):
        self = objc.super(ItemView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.ctl = None
        self.iid = None
        self.geom = None
        self.card_shown_for = None
        self.check = CheckButton.alloc().initWithFrame_(NSMakeRect(10, I_PAD_T - 1, 18, 18))
        self.addSubview_(self.check)
        self.box = FieldBox.alloc().initWithFrame_(NSMakeRect(IL, 40, 200, FIELD_MIN_H))
        self.box.field.set_placeholder("Reply  (Return sends, Shift-Return adds a line)")
        self.addSubview_(self.box)
        self.cancel = LinkButton.alloc().initWithFrame_(NSMakeRect(0, 0, 50, 16))
        self.cancel.setHidden_(True)
        self.addSubview_(self.cancel)
        self.slot = FlippedView.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 10))
        self.slot.setWantsLayer_(True)
        self.slot.layer().setMasksToBounds_(True)
        self.slot.setHidden_(True)
        self.card = CardView.alloc().initWithFrame_(NSMakeRect(CARD_MARGIN, CARD_MARGIN, 100, 60))
        self.slot.addSubview_(self.card)
        self.addSubview_(self.slot)
        self.setLayerContentsRedrawPolicy_(NSViewLayerContentsRedrawDuringViewResize)
        return self

    def isFlipped(self):
        return True

    def setFrameSize_(self, size):
        try:
            return self._setFrameSize_impl(size)
        except Exception:
            report_exception("setFrameSize_")
            return None

    @objc.python_method
    def _setFrameSize_impl(self, size):
        objc.super(ItemView, self).setFrameSize_(size)
        if self.ctl is not None and self.iid is not None:
            self.layout_now()

    @objc.python_method
    def show(self, ctl, iid):
        """(Re)binds this view to one item. The field's text is set only when it differs from the draft,
        so a field he is typing in is never disturbed."""
        if self.iid != iid and self.box.field.currentEditor() is not None and self.window() is not None:
            self.window().makeFirstResponder_(None)
        self.ctl, self.iid = ctl, iid
        f = self.box.field
        f.iid, f.role = iid, "item"
        f.setDelegate_(ctl)
        self.check.iid = iid
        self.check.setTarget_(ctl)
        self.check.setAction_("itemCheck:")
        self.cancel.setTarget_(ctl)
        self.cancel.setAction_("cancelOutbox:")
        self.card.target = ("item", iid)
        self.card.ctl = ctl
        self.layout_now()
        self.setNeedsDisplay_(True)

    @objc.python_method
    def layout_now(self):
        ctl, iid = self.ctl, self.iid
        if ctl is None or iid not in ctl.item_by_id:
            return
        width = self.bounds().size.width
        g = ctl.item_geom(iid, width)
        self.geom = g
        st = ctl.state(iid)
        f = self.box.field
        draft = st.draft or ""
        if f.currentEditor() is None and str(f.stringValue()) != draft:
            f.setStringValue_(draft)
        f.setEditable_(st.phase not in ("checking", "sending"))
        self.check.setState_(1 if ctl.is_selected_item(iid) else 0)
        self.check.setFrame_(NSMakeRect(10, I_PAD_T - 1, 18, 18))
        st_line = g["status"]
        if st_line and st_line[2]:
            cw = 46.0
            sx = IL + min(g["status_w"] + 8, max(0.0, g["w"] - cw))
            self.cancel.setFrame_(NSMakeRect(sx, g["status_y"] - 1, cw, line_height(FONT_SMALL) + 2))
            self.cancel.entry_id = st_line[2]
            self.cancel.role = "item"
            self.cancel.setHidden_(False)
        else:
            self.cancel.setHidden_(True)
        if g["card"]:
            self.box.setHidden_(True)
            sx = IL - CARD_MARGIN
            slot = NSMakeRect(sx, g["slot_y"], g["card_w"] + 2 * CARD_MARGIN, g["slot_h"])
            self.slot.setFrame_(slot)
            self.card.card = st.card
            final = NSMakeRect(CARD_MARGIN, CARD_MARGIN, g["card_w"], g["card_h"])
            if self.slot.isHidden() or self.card_shown_for != (iid, st.card.get("t")):
                self.slot.setHidden_(False)
                self.card_shown_for = (iid, st.card.get("t"))
                ctl.slide_card_in(self.card, final)
            else:
                self.card.setFrame_(final)
            self.card.setNeedsDisplay_(True)
        else:
            self.slot.setHidden_(True)
            self.card_shown_for = None
            self.box.setHidden_(False)
            self.box.setFrame_(NSMakeRect(IL, g["field_y"], g["w"], g["field_h"]))
            self.box.setNeedsDisplay_(True)

    @objc.python_method
    def meta_rect(self):
        g = self.geom
        if not g:
            return self.bounds()
        return NSMakeRect(0, g["meta_y"] - 1, self.bounds().size.width, line_height(FONT_META) + 4)

    def drawRect_(self, rect):
        try:
            return self._drawRect_impl(rect)
        except Exception:
            report_exception("drawRect_")
            return None

    @objc.python_method
    def _drawRect_impl(self, rect):
        ctl, g = self.ctl, self.geom
        if ctl is None or g is None or self.iid not in ctl.item_by_id:
            return
        it = ctl.item_by_id[self.iid]
        g["text_attr"].drawWithRect_options_(NSMakeRect(IL, I_PAD_T, g["w"], g["text_h"]), DRAW_OPTS)
        # meta line: lane, needs, waiting time, then the "may be settled" tag
        meta = attr(ctl.item_meta_text(it), FONT_META, DIM)
        mw = min(text_width(meta), g["w"])
        draw_line(meta, IL, g["meta_y"], g["w"])
        if it.get("may_be_settled"):
            reason = one_line(it.get("settled_reason") or "")
            tag = "may be settled" + (f": {reason}" if reason else "")
            draw_tag(tag, IL + mw + 10, g["meta_y"] - 1, g["w"] - mw - 10)
        st_line = g["status"]
        if st_line:
            draw_line(attr(st_line[0], FONT_SMALL, STATUS_COLORS.get(st_line[1], DIM)), IL, g["status_y"], g["w"])


class GroupButton(NSButton):
    def initWithFrame_(self, frame):
        self = objc.super(GroupButton, self).initWithFrame_(frame)
        if self is None:
            return None
        self.gkey = None
        return self


class GroupView(NSView):
    """A group header: the topic, the agents in it, and one button, "Work it out together"."""

    def initWithFrame_(self, frame):
        self = objc.super(GroupView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.ctl = None
        self.gkey = None
        self.button = GroupButton.alloc().initWithFrame_(NSMakeRect(0, 0, 170, 24))
        self.button.setTitle_("Work it out together")
        self.button.setBezelStyle_(1)
        self.button.setControlSize_(1)
        self.button.setFont_(NSFont.systemFontOfSize_weight_(11.5, NSFontWeightMedium))
        self.button.setFocusRingType_(NSFocusRingTypeNone)
        self.addSubview_(self.button)
        return self

    def isFlipped(self):
        return True

    def setFrameSize_(self, size):
        try:
            return self._setFrameSize_impl(size)
        except Exception:
            report_exception("setFrameSize_")
            return None

    @objc.python_method
    def _setFrameSize_impl(self, size):
        objc.super(GroupView, self).setFrameSize_(size)
        self.place()

    @objc.python_method
    def show(self, ctl, gkey):
        self.ctl, self.gkey = ctl, gkey
        self.button.setTarget_(ctl)
        self.button.setAction_("workTogether:")
        self.button.gkey = gkey
        self.place()
        self.setNeedsDisplay_(True)

    @objc.python_method
    def place(self):
        b = self.bounds()
        self.button.sizeToFit()
        bw = self.button.frame().size.width + 6
        self.button.setFrame_(NSMakeRect(b.size.width - IR - bw, GROUP_PAD - 2, bw, 24))
        busy = self.ctl is not None and self.ctl.group_busy(self.gkey)
        self.button.setEnabled_(not busy)

    def drawRect_(self, rect):
        try:
            return self._drawRect_impl(rect)
        except Exception:
            report_exception("drawRect_")
            return None

    @objc.python_method
    def _drawRect_impl(self, rect):
        ctl = self.ctl
        if ctl is None:
            return
        g = ctl.group_by_key.get(self.gkey)
        if g is None:
            return
        b = self.bounds()
        w = b.size.width - IL - IR - self.button.frame().size.width - 12
        n = len(g.get("members") or [])
        top = attr(f"{one_line(g.get('topic') or 'Related items')}", FONT_GROUP, TEXT_BRIGHT)
        draw_line(top, IL, GROUP_PAD, w)
        agents = ", ".join(one_line(a.get("label") or a.get("lane") or "") for a in g.get("agents") or [])
        lead = one_line(g.get("lead_label") or g.get("lead_lane") or "")
        sub = f"{n} related items from {agents}." + (f" Lead: {lead} ({one_line(g.get('lead_by') or '')})." if lead else "")
        draw_line(attr(sub, FONT_SMALL, DIM), IL, GROUP_PAD + line_height(FONT_GROUP) + 2, w)
        status = ctl.group_status.get(self.gkey)
        if status:
            draw_line(attr(status[0], FONT_SMALL, STATUS_COLORS.get(status[1], DIM)), IL,
                      GROUP_PAD + line_height(FONT_GROUP) + 2 + line_height(FONT_SMALL) + 2, b.size.width - IL - IR)



class UnjustView(NSView):
    """SPEC section 11: the foot of the waiting list. The header row, "Asked of you without saying why
    (N)", dim, with a disclosure mark; a click opens or closes the section. Each row under it: the lane
    and the line, dim, wrapped. Never selectable, never counted."""

    def initWithFrame_(self, frame):
        self = objc.super(UnjustView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.ctl = None
        self.key = None
        return self

    def isFlipped(self):
        return True

    @objc.python_method
    def show(self, ctl, key):
        self.ctl, self.key = ctl, key
        self.setToolTip_("Lines that say WAITING ON you but give no reason ('because'). Not counted above. "
                         "Tell the lane to justify each one or drop it." if key == "head" else None)
        self.setNeedsDisplay_(True)

    @objc.python_method
    def plain(self):
        a = unjust_attr(self.ctl, self.key) if self.ctl is not None else None
        return "" if a is None else str(a.string())

    def drawRect_(self, rect):
        try:
            return self._drawRect_impl(rect)
        except Exception:
            report_exception("drawRect_")
            return None

    @objc.python_method
    def _drawRect_impl(self, rect):
        if self.ctl is None:
            return
        a = unjust_attr(self.ctl, self.key)
        if a is None:
            return
        b = self.bounds()
        if self.key == "head":
            draw_line(a, IL - 16, (UNJUST_HEAD_H - line_height(FONT_SMALL)) / 2.0, b.size.width - IL - IR + 16)
        else:
            a.drawWithRect_options_(NSMakeRect(IL, I_PAD_T - 2, max(80.0, b.size.width - IL - IR), b.size.height), DRAW_OPTS)

    def mouseDown_(self, event):
        try:
            if self.ctl is not None and self.key == "head":
                self.ctl.toggle_unjust()
        except Exception:
            report_exception("mouseDown_")

    def resetCursorRects(self):
        if self.key == "head":
            self.addCursorRect_cursor_(self.bounds(), NSCursor.pointingHandCursor())


def unjust_attr(ctl, key):
    """The text of one row of the section: the header, or one ask with its lane."""
    if key == "head":
        n = len(ctl.unjust)
        mark = "\u25be" if ctl.unjust_open else "\u25b8"
        s = NSMutableAttributedString.alloc().init()
        s.appendAttributedString_(attr(f"{mark}  Asked of you without saying why ({n})", FONT_HEADER_LINE, DIM))
        s.appendAttributedString_(attr("     not counted; each lane should give its reason or drop it", FONT_SMALL, DIMMER))
        return s
    u = ctl.unjust_by_key.get(key)
    if u is None:
        return None
    k = ("unjust", key, u.get("text"))
    a = ctl.text_cache.get(k)
    if a is None:
        s = NSMutableAttributedString.alloc().init()
        s.appendAttributedString_(attr(f"Lane: {one_line(u.get('lane') or 'unknown')}     ", FONT_META, DIMMER, P_WRAP))
        s.appendAttributedString_(attr(clean(u.get("text") or ""), FONT_SMALL, DIM, P_WRAP))
        ctl.text_cache[k] = a = s
    return a


def unjust_height(ctl, key, width):
    if key == "head":
        return UNJUST_HEAD_H
    a = unjust_attr(ctl, key)
    if a is None:
        return 24.0
    return float(math.ceil(I_PAD_T - 2 + text_height(a, max(80.0, width - IL - IR)) + I_PAD_B - 2))


def group_height(ctl, gkey):
    h = GROUP_PAD + line_height(FONT_GROUP) + 2 + line_height(FONT_SMALL) + GROUP_PAD
    if ctl.group_status.get(gkey):
        h += line_height(FONT_SMALL) + 2
    return float(max(h, 24 + 2 * GROUP_PAD))


# ---------------------------------------------------------------------------------------------
# The already-resolved card (SPEC section 4)
# ---------------------------------------------------------------------------------------------

PILLS = [("send", "Send anyway", ""), ("dont", "Don't send", "Esc"), ("edit", "Edit", "E")]
RETURN_HINT = "Return"          # drawn on the FOCUSED pill (SPEC section 11: Return presses the focused pill)


def card_key_action(code, ch, shift, cmd, focus):
    """What a key does on the card (SPEC sections 4 and 11): Return, Enter and Space press the FOCUSED
    pill (Send anyway is focused first); Escape is Don't send; E is Edit; Tab, Shift-Tab and the arrows
    move the focus. ("act", pill key), ("focus", index), or None when it is not the card's key."""
    if code in (KEY_RETURN, KEY_ENTER, KEY_SPACE):
        return ("act", PILLS[focus % len(PILLS)][0])
    if code == KEY_ESCAPE:
        return ("act", "dont")
    if (ch or "").lower() == "e" and not cmd:
        return ("act", "edit")
    if code in (KEY_TAB, KEY_RIGHT, KEY_LEFT):
        back = code == KEY_LEFT or (code == KEY_TAB and shift)
        return ("focus", (focus + (-1 if back else 1)) % len(PILLS))
    return None


def pill_hint(i, focused):
    """The key shown on pill i: "Return" on the focused one, else its own key (none for Send anyway)."""
    return RETURN_HINT if i == focused else PILLS[i][2]
CARD_PAD = 14.0
PILL_H = 26.0
GLYPH = 15.0


def card_checker_text(card, now):
    by = card.get("by") or []
    names = " and ".join(one_line(b) for b in by) if by else "the checker"
    return f"checked by {names} {just_now(now - (card.get('t') or now))}"


def card_layout(card, width, now=None):
    """Every rectangle and string of the card, for measuring and for drawing (the same function)."""
    now = time.time() if now is None else now
    rows = card.get("rows") or []
    inner = max(60.0, width - 2 * CARD_PAD)
    out = {"lines": []}
    y = CARD_PAD
    title = attr("Already resolved", FONT_CARD_TITLE, TEXT_BRIGHT)
    tw = text_width(title)
    x_text = CARD_PAD + GLYPH + 8
    lh_t = line_height(FONT_CARD_TITLE)
    out["glyph"] = NSMakeRect(CARD_PAD, y + (lh_t - GLYPH) / 2.0, GLYPH, GLYPH)
    out["title"] = (title, NSMakeRect(x_text, y, tw + 2, lh_t))
    if len(rows) == 1:
        reason = attr(one_line(rows[0][1]), FONT_CARD, TEXT, P_WRAP)
        rx = x_text + tw + 10
        rw = CARD_PAD + inner - rx
        if rw < 140:                                      # too narrow: the reason goes under the title
            y += lh_t + 2
            rx, rw = x_text, CARD_PAD + inner - x_text
        rh = text_height(reason, rw)
        out["reason"] = (reason, NSMakeRect(rx, y + (1 if rh <= lh_t else 0), rw, rh))
        y += max(lh_t, rh) + 4
    else:
        extra = attr(f"{len(rows)} of {card.get('of') or len(rows)} items", FONT_CARD, DIM)
        out["reason"] = (extra, NSMakeRect(x_text + tw + 10, y + 1, inner - tw - 10 - GLYPH - 8, lh_t))
        y += lh_t + 6
        for iid, reason, about in rows:
            s = NSMutableAttributedString.alloc().init()
            s.appendAttributedString_(attr(first_chars(about, 70) + ":  ", FONT_SMALL, DIM))
            s.appendAttributedString_(attr(one_line(reason), FONT_SMALL, TEXT))
            lh = line_height(FONT_SMALL)
            out["lines"].append((s, NSMakeRect(x_text, y, CARD_PAD + inner - x_text, lh)))
            y += lh + 3
        y += 1
    checked = attr(card_checker_text(card, now), FONT_SMALL, DIM)
    out["checked"] = (checked, NSMakeRect(x_text, y, CARD_PAD + inner - x_text, line_height(FONT_SMALL)))
    y += line_height(FONT_SMALL) + 12
    x = x_text
    out["pills"] = []
    for key, label, hint in PILLS:
        la = attr(label, FONT_PILL, TEXT_BRIGHT)
        hw = max(text_width(attr(hint, FONT_KEY, DIM)), text_width(attr(RETURN_HINT, FONT_KEY, DIM)))
        pw = 14 + text_width(la) + 7 + hw + 14                 # room for "Return" on whichever pill is focused
        out["pills"].append((key, label, hint, NSMakeRect(x, y, pw, PILL_H)))
        x += pw + 8
    if len(rows) > 1 and card.get("note"):
        na = attr(card["note"], FONT_SMALL, DIM)
        out["note"] = (na, NSMakeRect(x + 4, y + (PILL_H - line_height(FONT_SMALL)) / 2.0,
                                      max(0.0, CARD_PAD + inner - x - 4), line_height(FONT_SMALL)))
    y += PILL_H + CARD_PAD
    out["height"] = math.ceil(y)
    return out


class CardView(NSView):
    """A rounded dark card, one hairline border, a soft shadow, a small green check, "Already resolved"
    and the reason, "checked by <checker> just now", and three pills. Return (or Space) presses the
    FOCUSED pill, Send anyway focused first; Tab, Shift-Tab and the arrows move the focus; Escape does
    not send; E edits (card_key_action). The focused pill carries the orange accent and the "Return"
    hint. No sounds."""

    def initWithFrame_(self, frame):
        self = objc.super(CardView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.card = None
        self.ctl = None
        self.target = None
        self.focus = 0
        self.lay = None
        self.setWantsLayer_(True)
        lay = self.layer()
        lay.setShadowOpacity_(0.5)
        lay.setShadowRadius_(7.0)
        lay.setShadowOffset_((0, -2))
        lay.setMasksToBounds_(False)
        return self

    def isFlipped(self):
        return True

    def acceptsFirstResponder(self):
        return True

    def becomeFirstResponder(self):
        self.setNeedsDisplay_(True)
        return True

    def resignFirstResponder(self):
        self.setNeedsDisplay_(True)
        return True

    def drawRect_(self, rect):
        try:
            return self._drawRect_impl(rect)
        except Exception:
            report_exception("drawRect_")
            return None

    @objc.python_method
    def _drawRect_impl(self, rect):
        if not self.card:
            return
        b = self.bounds()
        hair = 1.0 / (self.window().backingScaleFactor() if self.window() is not None else 2.0)
        path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            NSMakeRect(hair / 2, hair / 2, b.size.width - hair, b.size.height - hair), 10, 10)
        CARD_BG.setFill()
        path.fill()
        CARD_BORDER.setStroke()
        path.setLineWidth_(hair)
        path.stroke()
        lay = card_layout(self.card, b.size.width)
        self.lay = lay
        g = lay["glyph"]
        circle = NSBezierPath.bezierPathWithOvalInRect_(g)
        GREEN.setFill()
        circle.fill()
        tick = NSBezierPath.bezierPath()
        tick.moveToPoint_((g.origin.x + g.size.width * 0.27, g.origin.y + g.size.height * 0.53))
        tick.lineToPoint_((g.origin.x + g.size.width * 0.44, g.origin.y + g.size.height * 0.70))
        tick.lineToPoint_((g.origin.x + g.size.width * 0.74, g.origin.y + g.size.height * 0.33))
        tick.setLineWidth_(1.8)
        tick.setLineCapStyle_(1)
        tick.setLineJoinStyle_(1)
        rgb("0d1a10").setStroke()
        tick.stroke()
        for key in ("title", "reason", "checked", "note"):
            if key in lay:
                a, r = lay[key]
                a.drawWithRect_options_(r, DRAW_OPTS | NSStringDrawingTruncatesLastVisibleLine)
        for a, r in lay["lines"]:
            a.drawWithRect_options_(r, DRAW_OPTS | NSStringDrawingTruncatesLastVisibleLine)
        focused_view = self.window() is not None and self.window().firstResponder() == self
        for i, (key, label, hint, r) in enumerate(lay["pills"]):
            focused = focused_view and i == self.focus
            p = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                NSMakeRect(r.origin.x + 0.5, r.origin.y + 0.5, r.size.width - 1, r.size.height - 1), PILL_H / 2, PILL_H / 2)
            PILL_BG.setFill()
            p.fill()
            (ORANGE if focused else PILL_BORDER).setStroke()
            p.setLineWidth_(1.5 if focused else 1.0)
            p.stroke()
            la = attr(label, FONT_PILL, ORANGE if focused else TEXT_BRIGHT)
            ha = attr(pill_hint(i, self.focus if focused_view else -1), FONT_KEY, DIM)
            lw = text_width(la)
            lh = line_height(FONT_PILL)
            la.drawWithRect_options_(NSMakeRect(r.origin.x + 14, r.origin.y + (PILL_H - lh) / 2.0, lw + 2, lh), DRAW_OPTS)
            hh = line_height(FONT_KEY)
            ha.drawWithRect_options_(NSMakeRect(r.origin.x + 14 + lw + 7, r.origin.y + (PILL_H - hh) / 2.0 + 0.5,
                                                text_width(ha) + 2, hh), DRAW_OPTS)

    def mouseDown_(self, event):
        try:
            return self._mouseDown_impl(event)
        except Exception:
            report_exception("mouseDown_")
            return None

    @objc.python_method
    def _mouseDown_impl(self, event):
        p = self.convertPoint_fromView_(event.locationInWindow(), None)
        lay = self.lay or (card_layout(self.card, self.bounds().size.width) if self.card else None)
        if lay is None:
            return
        for i, (key, label, hint, r) in enumerate(lay["pills"]):
            if NSPointInRect(p, r):
                self.focus = i
                self.setNeedsDisplay_(True)
                self.act(key)
                return
        if self.window() is not None:
            self.window().makeFirstResponder_(self)

    @objc.python_method
    def act(self, key):
        if self.ctl is not None and self.target is not None:
            self.ctl.card_action(self.target, key)

    def keyDown_(self, event):
        try:
            return self._keyDown_impl(event)
        except Exception:
            report_exception("keyDown_")
            return None

    @objc.python_method
    def _keyDown_impl(self, event):
        code = event.keyCode()
        ch = str(event.charactersIgnoringModifiers() or "")
        flags = event.modifierFlags()
        what = card_key_action(code, ch, bool(flags & NSEventModifierFlagShift),
                               bool(flags & NSEventModifierFlagCommand), self.focus)
        if what is None:
            objc.super(CardView, self).keyDown_(event)
        elif what[0] == "act":
            self.act(what[1])
        else:
            self.focus = what[1]
            self.setNeedsDisplay_(True)

    def cancelOperation_(self, sender):
        self.act("dont")


# ---------------------------------------------------------------------------------------------
# The alarm banner (SPEC section 5) and the storage strip (SPEC section 10)
# ---------------------------------------------------------------------------------------------

class AlarmBanner(NSView):
    def initWithFrame_(self, frame):
        self = objc.super(AlarmBanner, self).initWithFrame_(frame)
        if self is None:
            return None
        self.ctl = None
        self.lines = []            # [(attributed, alarm dict or None)]
        return self

    def isFlipped(self):
        return True

    def drawRect_(self, rect):
        try:
            return self._drawRect_impl(rect)
        except Exception:
            report_exception("drawRect_")
            return None

    @objc.python_method
    def _drawRect_impl(self, rect):
        b = self.bounds()
        RED_BG.setFill()
        NSRectFill(b)
        rgb("000000", 0.35).setFill()
        NSRectFill(NSMakeRect(0, b.size.height - 1, b.size.width, 1))
        for i, (a, _) in enumerate(self.lines):
            lh = line_height(FONT_ALARM)
            draw_line(a, 12, i * ALARM_LINE_H + (ALARM_LINE_H - lh) / 2.0, b.size.width - 24)

    def mouseDown_(self, event):
        try:
            return self._mouseDown_impl(event)
        except Exception:
            report_exception("mouseDown_")
            return None

    @objc.python_method
    def _mouseDown_impl(self, event):
        p = self.convertPoint_fromView_(event.locationInWindow(), None)
        i = int(p.y // ALARM_LINE_H)
        if self.ctl is not None and 0 <= i < len(self.lines):
            self.ctl.alarm_clicked(i, NSMakeRect(0, i * ALARM_LINE_H, self.bounds().size.width, ALARM_LINE_H))

    def resetCursorRects(self):
        self.addCursorRect_cursor_(self.bounds(), NSCursor.pointingHandCursor())


class HoverContent(NSView):
    """The hover panel's content: the web view, and a tracking area so leaving the panel closes it."""

    def initWithFrame_(self, frame):
        self = objc.super(HoverContent, self).initWithFrame_(frame)
        if self is None:
            return None
        self.ctl = None
        opts = NSTrackingMouseEnteredAndExited | NSTrackingActiveAlways | NSTrackingInVisibleRect
        self.addTrackingArea_(NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(NSMakeRect(0, 0, 0, 0), opts, self, None))
        return self

    def isFlipped(self):
        return True

    def mouseEntered_(self, event):
        try:
            return self._mouseEntered_impl(event)
        except Exception:
            report_exception("mouseEntered_")
            return None

    @objc.python_method
    def _mouseEntered_impl(self, event):
        if self.ctl is not None:
            self.ctl.hover_panel_entered()

    def mouseExited_(self, event):
        try:
            return self._mouseExited_impl(event)
        except Exception:
            report_exception("mouseExited_")
            return None

    @objc.python_method
    def _mouseExited_impl(self, event):
        if self.ctl is not None:
            self.ctl.hover_panel_exited()


# ---------------------------------------------------------------------------------------------
# The hover panel (SPEC section 3): NSPopover + WKWebView, JavaScript off, every navigation refused
# ---------------------------------------------------------------------------------------------

HOVER_W = 560.0
HOVER_MAX_FRACTION = 0.70
MEASURE_JS = "Math.ceil(document.body.getBoundingClientRect().height)"


class HoverNav(NSObject):
    """The web view's navigation delegate. It allows exactly one navigation: the page this app loads
    with loadHTMLString (about:blank, type other), armed just before each load. Every other navigation
    (a link click, a redirect, a form) is refused, so nothing in an agent's message can take the panel
    anywhere. Measured 10 Sep: a second load was refused and the URL stayed about:blank."""

    def init(self):
        self = objc.super(HoverNav, self).init()
        if self is None:
            return None
        self.allow_once = False
        self.panel = None
        self.refused = 0
        return self

    def webView_decidePolicyForNavigationAction_decisionHandler_(self, wv, action, handler):
        url = action.request().URL()
        s = str(url.absoluteString()) if url is not None else ""
        ok = self.allow_once and action.navigationType() == WebKit.WKNavigationTypeOther and s in ("about:blank", "")
        if ok:
            self.allow_once = False
        else:
            self.refused += 1
        handler(WebKit.WKNavigationActionPolicyAllow if ok else WebKit.WKNavigationActionPolicyCancel)

    def webView_didFinishNavigation_(self, wv, nav):
        try:
            return self._webView_didFinishNavigation_impl(wv, nav)
        except Exception:
            report_exception("webView_didFinishNavigation_")
            return None

    @objc.python_method
    def _webView_didFinishNavigation_impl(self, wv, nav):
        if self.panel is not None:
            self.panel.loaded()


class HoverPanel(NSObject):
    """One popover and one web view, reused for every hover (the conversation's whole message, the
    storage details, an alarm's full text)."""

    def initWithController_(self, ctl):
        self = objc.super(HoverPanel, self).init()
        if self is None:
            return None
        self.ctl = ctl
        cfg = WebKit.WKWebViewConfiguration.alloc().init()
        cfg.defaultWebpagePreferences().setAllowsContentJavaScript_(False)
        cfg.preferences().setJavaScriptCanOpenWindowsAutomatically_(False)
        # in memory only: WebKit writes no cache or cookies under Python's bundle id
        cfg.setWebsiteDataStore_(WebKit.WKWebsiteDataStore.nonPersistentDataStore())
        self.web = WebKit.WKWebView.alloc().initWithFrame_configuration_(NSMakeRect(0, 0, HOVER_W, 120), cfg)
        self.web.setAutoresizingMask_(2 | 16)
        try:
            self.web.setValue_forKey_(False, "drawsBackground")
        except Exception:
            pass
        self.nav = HoverNav.alloc().init()
        self.nav.panel = self
        self.web.setNavigationDelegate_(self.nav)
        self.content = HoverContent.alloc().initWithFrame_(NSMakeRect(0, 0, HOVER_W, 120))
        self.content.ctl = ctl
        self.content.addSubview_(self.web)
        self.vc = NSViewController.alloc().init()
        self.vc.setView_(self.content)
        self.pop = NSPopover.alloc().init()
        self.pop.setContentViewController_(self.vc)
        self.pop.setBehavior_(NSPopoverBehaviorApplicationDefined)
        self.pop.setAnimates_(False)
        self.pop.setAppearance_(NSAppearance.appearanceNamed_(NSAppearanceNameDarkAqua))
        self.pop.setDelegate_(self)
        self.want = None           # (key, view, rect, sticky) waiting for its page to load
        self.shown_key = None
        self.sticky = False
        self.anchor = None         # (view, rect) of what is shown
        self.last_height = None
        self.last_html = None
        return self

    @objc.python_method
    def show(self, key, html, view, rect, sticky=False):
        if self.shown_key == key and self.pop.isShown():
            return
        self.want = (key, view, rect, sticky)
        self.last_html = html
        self.nav.allow_once = True
        self.web.loadHTMLString_baseURL_(html, None)

    @objc.python_method
    def loaded(self):
        if self.want is None:
            return
        want = self.want

        def got(result, error):
            h = None
            try:
                h = float(result) if result is not None and error is None else None
            except (TypeError, ValueError):
                h = None
            self.present(want, h)
        try:
            self.web.evaluateJavaScript_inFrame_inContentWorld_completionHandler_(
                MEASURE_JS, None, WebKit.WKContentWorld.defaultClientWorld(), got)
        except Exception:
            self.present(want, None)

    @objc.python_method
    def max_height(self, view):
        scr = (view.window().screen() if view is not None and view.window() is not None else None) or NSScreen.mainScreen()
        return math.floor(scr.visibleFrame().size.height * HOVER_MAX_FRACTION)

    @objc.python_method
    def present(self, want, h):
        if self.want is not want:
            return                                          # a newer hover replaced this one
        key, view, rect, sticky = want
        if view is None or view.window() is None:
            return
        hmax = self.max_height(view)
        height = min(max(60.0, (h or hmax) + 2), hmax)     # unmeasured: the cap, and the page scrolls
        self.last_height = height
        self.pop.setContentSize_(NSMakeSize(HOVER_W, height))
        self.pop.setBehavior_(NSPopoverBehaviorTransient if sticky else NSPopoverBehaviorApplicationDefined)
        self.pop.showRelativeToRect_ofView_preferredEdge_(rect, view, NSMaxYEdge)
        self.shown_key, self.sticky, self.anchor = key, sticky, (view, rect)
        self.want = None

    @objc.python_method
    def close(self):
        self.want = None
        if self.pop.isShown():
            self.pop.close()
        self.shown_key = None
        self.anchor = None

    @objc.python_method
    def is_shown(self):
        return bool(self.pop.isShown())

    @objc.python_method
    def window(self):
        return self.content.window()

    def popoverDidClose_(self, note):
        try:
            return self._popoverDidClose_impl(note)
        except Exception:
            report_exception("popoverDidClose_")
            return None

    @objc.python_method
    def _popoverDidClose_impl(self, note):
        self.shown_key = None
        self.anchor = None


# ---------------------------------------------------------------------------------------------
# Tables with the two behaviours AppKit does not give by default
# ---------------------------------------------------------------------------------------------

class ListTable(NSTableView):
    """The waiting list: a click in a reply field edits it at once (not only on an already selected
    row), and Select All selects items only, never group headers."""

    def validateProposedFirstResponder_forEvent_(self, responder, event):
        if isinstance(responder, (ReplyField, CardView)):
            return True
        return objc.super(ListTable, self).validateProposedFirstResponder_forEvent_(responder, event)

    def selectAll_(self, sender):
        d = self.delegate()
        if d is not None and hasattr(d, "item_rows"):
            idx = NSMutableIndexSet.indexSet()
            for r in d.item_rows():
                idx.addIndex_(r)
            self.selectRowIndexes_byExtendingSelection_(idx, False)
        else:
            objc.super(ListTable, self).selectAll_(sender)


class ConvTable(NSTableView):
    def validateProposedFirstResponder_forEvent_(self, responder, event):
        if isinstance(responder, ReplyField):
            return True
        return objc.super(ConvTable, self).validateProposedFirstResponder_forEvent_(responder, event)


class IState(object):
    """What the window holds for one waiting item, by id, across refreshes."""
    __slots__ = ("draft", "phase", "card", "status", "status_t", "restored")

    def __init__(self):
        self.draft = ""          # his half-typed reply
        self.phase = None        # None | "checking" | "card" | "sending"
        self.card = None         # {"rows": [(id, reason, about)], "by": [checker], "text": his words, "t", "of"}
        self.status = None       # (text, kind)
        self.status_t = 0.0
        self.restored = False    # a saved draft was put back once


class Controller(NSObject):

    def init(self):
        self = objc.super(Controller, self).init()
        if self is None:
            return None
        self.raw_rows, self.rows = [], []
        self.items, self.item_by_id = [], {}
        self.display, self.index = [], {}
        self.groups, self.group_by_key, self.group_status, self.groups_busy = [], {}, {}, set()
        self.member_group = {}
        self.groups_raw, self.groups_sha = [], None
        self.group_running, self.group_done, self.group_retry_at = None, set(), {}
        self.istates = {}
        self.outbox_by_item, self.outbox_entries = {}, []
        self.msg = {"phase": None, "outbox_id": None, "status": None, "status_t": 0.0, "text": ""}
        self.dock = {"phase": None, "card": None, "status": None, "status_t": 0.0, "draft": "", "iids": []}
        self.wmeta = {"ok": None, "sha": None, "as_of": None, "when": None, "err": None}
        self.wmismatch = {}                # the engine's lane count mismatch flags (list_mismatches)
        self.store = None
        self.unjust, self.unjust_by_key, self.unjust_open = [], {}, False
        self.cmux_reason = None
        self.saved_drafts = None           # read lazily (drafts.json), SPEC section 11
        self.alarm_list, self.alarm_err = [], None
        self.title_override = {}
        self.renaming = None
        self.hover_target, self.hover_token = None, 0
        self.fake_pointer = None
        self.reduce_override = None
        self.last_card_motion = None
        self.text_cache = {}
        self.flash_msg, self.flash_until = None, 0.0
        self.prefs_dirty = False
        self.remember = True
        self.sync_bg = False
        self.act = None
        self.top_pref = None
        self.wake = threading.Event()
        self.wake_outbox = threading.Event()
        self.next_wait_at = 0.0
        self.window = None
        self.logged = {}
        self.last_update = None
        p = read_prefs().get("v5") or {}
        self.sort_key = p.get("sort") if p.get("sort") in SORT_TITLES else "sidebar"
        self.sort_reverse = bool(p.get("reverse"))
        self.view_mode = p.get("view") if p.get("view") in ("headline", "summary") else "headline"
        return self

    # ---- small helpers -----------------------------------------------------------------------

    @objc.python_method
    def actions(self):
        return self.act if self.act is not None else ACT

    @objc.python_method
    def bg(self, fn, then=None, fallback=None):
        """fn off the main thread; then(result) back on it. In --check both run at once, in order."""
        def run():
            try:
                res = fn()
            except Exception:
                traceback.print_exc()
                res = fallback
            return res
        if self.sync_bg:
            res = run()
            if then is not None:
                then(res)
            return

        def thread():
            res = run()
            if then is not None:
                AppHelper.callAfter(safely, then, res)
        threading.Thread(target=thread, daemon=True).start()

    @objc.python_method
    def state(self, iid):
        st = self.istates.get(iid)
        if st is None:
            st = self.istates[iid] = IState()
        return st

    @objc.python_method
    def flash(self, text, seconds=10.0):
        self.flash_msg, self.flash_until = clean(text), time.time() + seconds
        self.show_footer()

    # ---- building the window ---------------------------------------------------------------------

    @objc.python_method
    def build_window(self, remember=True):
        self.remember = remember
        dark = NSAppearance.appearanceNamed_(NSAppearanceNameDarkAqua)
        style = (NSWindowStyleMaskTitled | NSWindowStyleMaskClosable |
                 NSWindowStyleMaskMiniaturizable | NSWindowStyleMaskResizable)
        win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, 1240, 860), style, NSBackingStoreBuffered, False)
        win.setTitle_("Agents" + ("  (TEST MODE)" if TEST_MODE else ""))
        win.setAppearance_(dark)
        win.setBackgroundColor_(BG)
        win.setTitlebarAppearsTransparent_(True)
        win.setReleasedWhenClosed_(False)
        win.setRestorable_(False)
        win.setMinSize_(NSMakeSize(640, 460))
        win.setAcceptsMouseMovedEvents_(True)
        win.center()
        self.window = win

        root = FlippedView.alloc().initWithFrame_(NSMakeRect(0, 0, 1240, 860))
        root.fill = BG
        win.setContentView_(root)
        self.root = root

        # alarm banner
        self.banner = AlarmBanner.alloc().initWithFrame_(NSMakeRect(0, 0, 100, 0))
        self.banner.ctl = self
        self.banner.setHidden_(True)
        root.addSubview_(self.banner)
        # the one plain banner of SPEC section 11 (cmux refuses a process started outside cmux)
        self.notice = LineCell.alloc().initWithFrame_(NSMakeRect(0, 0, 100, NOTICE_H))
        self.notice.fill = NOTICE_BG
        self.notice.inset = 12.0
        self.notice.setHidden_(True)
        root.addSubview_(self.notice)

        # sort bar: "Sort" and its menu, above the table
        self.sortbar = FlippedView.alloc().initWithFrame_(NSMakeRect(0, 0, 100, SORTBAR_H))
        self.sortbar.fill = BG
        lab = NSTextField.labelWithString_("Sort")
        lab.setFont_(FONT_SMALL)
        lab.setTextColor_(DIM)
        lab.setFrame_(NSMakeRect(12, 6, 30, 16))
        self.sortbar.addSubview_(lab)
        pop = NSPopUpButton.alloc().initWithFrame_pullsDown_(NSMakeRect(40, 2, 250, 24), False)
        pop.setControlSize_(1)
        pop.setFont_(FONT_SMALL)
        for key, title in SORTS:
            pop.addItemWithTitle_(title)
        pop.setTarget_(self)
        pop.setAction_("sortPopup:")
        self.sortbar.addSubview_(pop)
        self.sort_popup = pop
        self.hint = LineCell.alloc().initWithFrame_(NSMakeRect(300, 0, 400, SORTBAR_H))
        self.hint.inset = 0
        self.sortbar.addSubview_(self.hint)
        root.addSubview_(self.sortbar)

        split = Split.alloc().initWithFrame_(NSMakeRect(0, SORTBAR_H, 1240, 600))
        split.setVertical_(False)
        split.setDelegate_(self)
        root.addSubview_(split)
        self.split = split

        # top: the conversation table
        top_h = HEAD_H + 16 * CONV_ROW_H + 4
        cscroll = self.make_scroll(NSMakeRect(0, 0, 1240, top_h))
        ctable = ConvTable.alloc().initWithFrame_(NSMakeRect(0, 0, 1240, top_h))
        self.style_table(ctable)
        ctable.setHeaderView_(HeaderView.alloc().initWithFrame_(NSMakeRect(0, 0, 1240, HEAD_H)))
        ctable.setColumnAutoresizingStyle_(NSTableViewUniformColumnAutoresizingStyle)
        ctable.setAllowsColumnReordering_(True)
        ctable.setAllowsColumnResizing_(True)
        ctable.setRowHeight_(CONV_ROW_H)
        ctable.setAllowsMultipleSelection_(False)
        self.ctable = ctable
        self.add_columns()
        ctable.setDataSource_(self)
        ctable.setDelegate_(self)
        ctable.setTarget_(self)
        ctable.setDoubleAction_("tableDoubleClick:")
        cscroll.setDocumentView_(ctable)
        cscroll.setHasHorizontalScroller_(True)
        self.cscroll = cscroll
        # right-click a row: Rename, Clear name. Right-click the header: the two optional columns
        rm = NSMenu.alloc().initWithTitle_("Row")
        rm.setAutoenablesItems_(False)
        it = rm.addItemWithTitle_action_keyEquivalent_("Rename", "renameMenu:", "")
        it.setTarget_(self)
        it = rm.addItemWithTitle_action_keyEquivalent_("Clear name", "clearNameMenu:", "")
        it.setTarget_(self)
        rm.setDelegate_(self)
        ctable.setMenu_(rm)
        self.row_menu = rm
        hm = NSMenu.alloc().initWithTitle_("Columns")
        for ident in OPTIONAL_COLUMNS:
            it = hm.addItemWithTitle_action_keyEquivalent_(COL_BY_ID[ident][1], "toggleColumn:", "")
            it.setTarget_(self)
            it.setRepresentedObject_(ident)
        ctable.headerView().setMenu_(hm)
        self.header_menu = hm
        # the one plain line shown when there are no rows at all
        empty = LineCell.alloc().initWithFrame_(NSMakeRect(0, HEAD_H + 8, 1240, CONV_ROW_H))
        empty.show(attr(getattr(ENGINE, "EMPTY_TABLE", "No Claude conversations are running."), FONT, DIM))
        empty.setHidden_(True)
        cscroll.addSubview_(empty)
        self.empty_line = empty
        self.table_owner = TrackingOwner.alloc().initWithSource_controller_view_("table", self, ctable)
        add_tracking(ctable, self.table_owner)

        # bottom: storage strip, list header, the docked multi-reply, the waiting list
        bottom = FlippedView.alloc().initWithFrame_(NSMakeRect(0, 0, 1240, 400))
        bottom.fill = BG
        bottom.layout_fn = lambda v: self.layout_bottom()
        self.bottom = bottom
        self.storage_strip = LineCell.alloc().initWithFrame_(NSMakeRect(0, 0, 1240, STORAGE_H))
        self.storage_strip.fill = BG
        self.storage_strip.inset = 12.0
        self.storage_strip.show(attr("Reading the disk", FONT_STORAGE, DIM))
        bottom.addSubview_(self.storage_strip)
        self.storage_owner = TrackingOwner.alloc().initWithSource_controller_view_("storage", self, self.storage_strip)
        add_tracking(self.storage_strip, self.storage_owner)
        head = LineCell.alloc().initWithFrame_(NSMakeRect(0, STORAGE_H, 1240, LIST_HEAD_H))
        head.fill = BG
        head.line_top = SEP
        head.inset = 12.0
        head.show(attr("Reading the waiting list", FONT_HEADER_LINE, DIM))
        bottom.addSubview_(head)
        self.list_head = head
        dockv = FlippedView.alloc().initWithFrame_(NSMakeRect(0, 0, 1240, 0))
        dockv.fill = rgb("18181a")
        dockv.layout_fn = lambda v: self.layout_dock()
        self.dock_box = FieldBox.alloc().initWithFrame_(NSMakeRect(12, 8, 600, FIELD_MIN_H))
        self.dock_box.field.role = "dock"
        self.dock_box.field.setDelegate_(self)
        dockv.addSubview_(self.dock_box)
        self.dock_label = LineCell.alloc().initWithFrame_(NSMakeRect(12, 8, 140, FIELD_MIN_H))
        self.dock_label.inset = 0
        dockv.addSubview_(self.dock_label)
        self.dock_slot = FlippedView.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 10))
        self.dock_slot.setWantsLayer_(True)
        self.dock_slot.layer().setMasksToBounds_(True)
        self.dock_slot.setHidden_(True)
        self.dock_card = CardView.alloc().initWithFrame_(NSMakeRect(CARD_MARGIN, CARD_MARGIN, 100, 60))
        self.dock_card.ctl = self
        self.dock_card.target = ("dock",)
        self.dock_slot.addSubview_(self.dock_card)
        dockv.addSubview_(self.dock_slot)
        self.dock_status = LineCell.alloc().initWithFrame_(NSMakeRect(12, 0, 600, 16))
        self.dock_status.inset = 0
        dockv.addSubview_(self.dock_status)
        dockv.setHidden_(True)
        bottom.addSubview_(dockv)
        self.dockv = dockv
        wscroll = self.make_scroll(NSMakeRect(0, 0, 1240, 300))
        wtable = ListTable.alloc().initWithFrame_(NSMakeRect(0, 0, 1240, 300))
        self.style_table(wtable)
        wtable.setHeaderView_(None)
        wtable.setAllowsMultipleSelection_(True)
        wtable.setColumnAutoresizingStyle_(NSTableViewUniformColumnAutoresizingStyle)
        col = NSTableColumn.alloc().initWithIdentifier_("item")
        col.setWidth_(1200)
        col.setResizingMask_(NSTableColumnAutoresizingMask)
        wtable.addTableColumn_(col)
        wtable.setDataSource_(self)
        wtable.setDelegate_(self)
        wscroll.setDocumentView_(wtable)
        bottom.addSubview_(wscroll)
        self.wscroll, self.wtable = wscroll, wtable
        self.list_width = None
        wtable.setPostsFrameChangedNotifications_(True)
        NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            self, "listFrameChanged:", "NSViewFrameDidChangeNotification", wtable)

        split.addSubview_(cscroll)
        split.addSubview_(bottom)
        split.setHoldingPriority_forSubviewAtIndex_(260.0, 0)
        split.setHoldingPriority_forSubviewAtIndex_(250.0, 1)

        # message bar and footer
        mb = FlippedView.alloc().initWithFrame_(NSMakeRect(0, 0, 1240, 44))
        mb.fill = rgb("18181a")
        mb.layout_fn = lambda v: self.layout_msg()
        self.msg_box = FieldBox.alloc().initWithFrame_(NSMakeRect(12, MSG_PAD, 600, FIELD_MIN_H + 4))
        self.msg_box.field.role = "msg"
        self.msg_box.field.set_placeholder("Message the coordinator")
        self.msg_box.field.setDelegate_(self)
        mb.addSubview_(self.msg_box)
        self.msg_status = LineCell.alloc().initWithFrame_(NSMakeRect(12, 0, 600, 16))
        self.msg_status.inset = 0
        mb.addSubview_(self.msg_status)
        self.msg_cancel = LinkButton.alloc().initWithFrame_(NSMakeRect(0, 0, 46, 16))
        self.msg_cancel.role = "msg"
        self.msg_cancel.setTarget_(self)
        self.msg_cancel.setAction_("cancelOutbox:")
        self.msg_cancel.setHidden_(True)
        mb.addSubview_(self.msg_cancel)
        root.addSubview_(mb)
        self.msgbar = mb
        foot = LineCell.alloc().initWithFrame_(NSMakeRect(0, 0, 1240, FOOT_H))
        foot.fill = BG
        foot.line_top = SEP_STRONG
        foot.inset = 12.0
        foot.show(attr("Reading the conversations", FONT_FOOT, DIM))
        root.addSubview_(foot)
        self.foot = foot
        root.layout_fn = lambda v: self.layout_root()

        self.hover = HoverPanel.alloc().initWithController_(self)
        self.install_escape()

        saved = read_prefs() if remember else {}
        if isinstance(saved.get("frame"), str):
            win.setFrameFromString_(saved["frame"])
        self.layout_root()
        top = saved.get("split_top")
        self.top_pref = float(top) if isinstance(top, (int, float)) and top > 60 else top_h
        self.resize_split(split)
        win.setDelegate_(self)
        for n in (NSTableViewColumnDidResizeNotification, NSTableViewColumnDidMoveNotification):
            NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(self, "columnsChanged:", n, ctable)
        self.ctable.sizeToFit()                          # Description takes the width the others leave
        self.update_sort_ui()
        self.show_footer()
        self.show_msg_status()
        self.layout_dock()
        self.prefs_dirty = False
        t = NSTimer.timerWithTimeInterval_target_selector_userInfo_repeats_(1.0, self, "tick:", None, True)
        NSRunLoop.currentRunLoop().addTimer_forMode_(t, NSRunLoopCommonModes)
        self.timer = t
        return win

    @objc.python_method
    def make_scroll(self, frame):
        scroll = NSScrollView.alloc().initWithFrame_(frame)
        scroll.setHasVerticalScroller_(True)
        scroll.setHasHorizontalScroller_(False)
        scroll.setAutohidesScrollers_(True)
        scroll.setScrollerStyle_(NSScrollerStyleOverlay)
        scroll.setBorderType_(0)
        scroll.setDrawsBackground_(True)
        scroll.setBackgroundColor_(PANEL)
        return scroll

    @objc.python_method
    def style_table(self, table):
        table.setStyle_(NSTableViewStylePlain)
        table.setBackgroundColor_(PANEL)
        table.setGridStyleMask_(NSTableViewGridNone)
        table.setUsesAlternatingRowBackgroundColors_(False)
        table.setFocusRingType_(NSFocusRingTypeNone)
        table.setSelectionHighlightStyle_(NSTableViewSelectionHighlightStyleRegular)
        table.setAllowsColumnSelection_(False)
        table.setAllowsEmptySelection_(True)
        table.setIntercellSpacing_(NSMakeSize(0, 0))
        table.setCornerView_(None)

    @objc.python_method
    def add_columns(self):
        """Columns in the remembered order, at the remembered widths, the optional two hidden unless he
        showed them. Only Description absorbs the window's width changes."""
        p = (read_prefs() if self.remember else {}).get("v5") or {}
        order = [c for c in (p.get("order") or []) if c in COL_BY_ID]
        order += [c[0] for c in COLUMNS if c[0] not in order]
        widths = p.get("columns") or {}
        hidden = p.get("hidden")
        hidden = set(hidden) if isinstance(hidden, list) else set(OPTIONAL_COLUMNS)
        for ident in order:
            _, title, width, min_w, align, optional = COL_BY_ID[ident]
            col = NSTableColumn.alloc().initWithIdentifier_(ident)
            hc = HeaderCell.alloc().initTextCell_(title)
            hc.setAlignment_(align)
            col.setHeaderCell_(hc)
            col.setTitle_(title)
            col.setMinWidth_(min_w)
            col.setMaxWidth_(4000.0)
            w = widths.get(ident)
            col.setWidth_(max(min_w, float(w)) if isinstance(w, (int, float)) else width)
            mask = NSTableColumnUserResizingMask | (NSTableColumnAutoresizingMask if ident == "desc" else 0)
            col.setResizingMask_(mask)
            col.setHidden_(ident in hidden and optional)
            self.ctable.addTableColumn_(col)

    # ---- layout ----------------------------------------------------------------------------------

    @objc.python_method
    def banner_height(self):
        n = len(self.banner.lines)
        return n * ALARM_LINE_H

    @objc.python_method
    def msg_geom(self, width):
        text = str(self.msg_box.field.stringValue())
        fh = field_height(text, width - 24, max_lines=4) + 4
        h = MSG_PAD + fh + MSG_PAD
        status = self.msg_status_text()
        if status:
            h += line_height(FONT_SMALL) + 2
        return {"field_h": fh, "h": h, "status": status}

    @objc.python_method
    def layout_root(self):
        b = self.root.bounds()
        W, H = b.size.width, b.size.height
        y = 0.0
        bh = self.banner_height()
        self.banner.setFrame_(NSMakeRect(0, 0, W, bh))
        self.banner.setHidden_(bh == 0)
        y += bh
        nh = NOTICE_H if self.cmux_reason else 0.0
        self.notice.setFrame_(NSMakeRect(0, y, W, nh))
        self.notice.setHidden_(nh == 0)
        y += nh
        self.sortbar.setFrame_(NSMakeRect(0, y, W, SORTBAR_H))
        self.hint.setFrame_(NSMakeRect(300, 0, max(10.0, W - 312), SORTBAR_H))
        y += SORTBAR_H
        mg = self.msg_geom(W)
        mh = mg["h"]
        self.split.setFrame_(NSMakeRect(0, y, W, max(80.0, H - y - mh - FOOT_H)))
        self.msgbar.setFrame_(NSMakeRect(0, H - FOOT_H - mh, W, mh))
        self.foot.setFrame_(NSMakeRect(0, H - FOOT_H, W, FOOT_H))
        self.layout_msg()
        self.place_empty_line()

    @objc.python_method
    def layout_msg(self):
        b = self.msgbar.bounds()
        W = b.size.width
        mg = self.msg_geom(W)
        self.msg_box.setFrame_(NSMakeRect(12, MSG_PAD, W - 24, mg["field_h"]))
        st = mg["status"]
        if st:
            y = MSG_PAD + mg["field_h"] + 2
            a = attr(st[0], FONT_SMALL, STATUS_COLORS.get(st[1], DIM))
            sw = min(text_width(a), W - 24 - 56)
            self.msg_status.setFrame_(NSMakeRect(14, y, sw + 4, line_height(FONT_SMALL) + 2))
            self.msg_status.show(a)
            self.msg_status.setHidden_(False)
            if st[2]:
                self.msg_cancel.setFrame_(NSMakeRect(14 + sw + 10, y, 46, line_height(FONT_SMALL) + 2))
                self.msg_cancel.entry_id = st[2]
                self.msg_cancel.setHidden_(False)
            else:
                self.msg_cancel.setHidden_(True)
        else:
            self.msg_status.setHidden_(True)
            self.msg_cancel.setHidden_(True)

    @objc.python_method
    def dock_visible(self):
        d = self.dock
        return len(self.selected_item_ids()) >= 2 or d["card"] is not None or d["phase"] is not None \
            or (d["status"] is not None and time.time() - d["status_t"] < 30)

    @objc.python_method
    def dock_geom(self, width):
        d = self.dock
        w = width - 24
        g = {"w": w, "y0": 8.0}
        y = 8.0
        if d["card"] is not None:
            g["card_w"] = min(w, CARD_MAX_W + 120)
            ch = card_layout(d["card"], g["card_w"])["height"]
            g.update(card_h=ch, slot_y=y - CARD_MARGIN + 2, slot_h=ch + 2 * CARD_MARGIN)
            y += ch + 4
        else:
            g["field_h"] = field_height(d["draft"], w - 130, max_lines=4)
            g["field_y"] = y
            y += g["field_h"]
        st = self.dock_status_text()
        if st:
            g["status_y"] = y + 3
            y += 3 + line_height(FONT_SMALL)
        g["status"] = st
        g["h"] = y + 8
        return g

    @objc.python_method
    def layout_bottom(self):
        b = self.bottom.bounds()
        W, H = b.size.width, b.size.height
        self.storage_strip.setFrame_(NSMakeRect(0, 0, W, STORAGE_H))
        self.list_head.setFrame_(NSMakeRect(0, STORAGE_H, W, LIST_HEAD_H))
        y = STORAGE_H + LIST_HEAD_H
        dh = self.dock_geom(W)["h"] if self.dock_visible() else 0.0
        if dh and H < STORAGE_H + LIST_HEAD_H + dh + 60.0 and not getattr(self, "_resizing", False):
            self._resizing = True                        # the dock needs room: the table gives it up
            try:
                self.resize_split(self.split)
            finally:
                self._resizing = False
            b = self.bottom.bounds()
            W, H = b.size.width, b.size.height
        self.dockv.setHidden_(dh == 0)
        self.dockv.setFrame_(NSMakeRect(0, y, W, dh))
        self.wscroll.setFrame_(NSMakeRect(0, y + dh, W, max(20.0, H - y - dh)))
        if dh:
            self.layout_dock()

    @objc.python_method
    def layout_dock(self):
        W = self.dockv.bounds().size.width
        if W <= 0:
            return
        g = self.dock_geom(W)
        n = len(self.dock["iids"]) if self.dock["phase"] or self.dock["card"] else len(self.selected_item_ids())
        if self.dock["card"] is not None:
            self.dock_box.setHidden_(True)
            self.dock_label.setHidden_(True)
            self.dock_slot.setFrame_(NSMakeRect(12 - CARD_MARGIN, g["slot_y"], g["card_w"] + 2 * CARD_MARGIN, g["slot_h"]))
            final = NSMakeRect(CARD_MARGIN, CARD_MARGIN, g["card_w"], g["card_h"])
            self.dock_card.card = self.dock["card"]
            if self.dock_slot.isHidden():
                self.dock_slot.setHidden_(False)
                self.slide_card_in(self.dock_card, final)
            else:
                self.dock_card.setFrame_(final)
            self.dock_card.setNeedsDisplay_(True)
        else:
            self.dock_slot.setHidden_(True)
            self.dock_label.setHidden_(False)
            self.dock_box.setHidden_(False)
            self.dock_label.setFrame_(NSMakeRect(14, g["field_y"], 118, FIELD_MIN_H))
            self.dock_label.show(attr(f"Reply to {n} items", FONT_HEADER_LINE, ORANGE))
            self.dock_box.setFrame_(NSMakeRect(12 + 124, g["field_y"], g["w"] - 124, g["field_h"]))
            self.dock_box.field.set_placeholder(f"One reply to all {n}  (Return checks each, then sends)")
            f = self.dock_box.field
            if f.currentEditor() is None and str(f.stringValue()) != self.dock["draft"]:
                f.setStringValue_(self.dock["draft"])
            f.setEditable_(self.dock["phase"] is None)
        st = g["status"]
        if st:
            self.dock_status.setFrame_(NSMakeRect(14, g["status_y"], g["w"], line_height(FONT_SMALL) + 2))
            self.dock_status.show(attr(st[0], FONT_SMALL, STATUS_COLORS.get(st[1], DIM)))
            self.dock_status.setHidden_(False)
        else:
            self.dock_status.setHidden_(True)

    @objc.python_method
    def relayout_dock(self):
        self.layout_bottom()

    @objc.python_method
    def place_empty_line(self):
        hv = self.ctable.headerView()
        head = hv.frame().size.height if hv is not None else HEAD_H
        self.empty_line.setFrame_(NSMakeRect(0, head + 8, self.cscroll.frame().size.width, CONV_ROW_H))

    def splitView_constrainMinCoordinate_ofSubviewAt_(self, sv, proposed, idx):
        return max(proposed, HEAD_H + 2 * CONV_ROW_H)

    def splitView_constrainMaxCoordinate_ofSubviewAt_(self, sv, proposed, idx):
        return min(proposed, sv.bounds().size.height - 140.0)

    def splitViewDidResizeSubviews_(self, note):
        try:
            return self._splitViewDidResizeSubviews_impl(note)
        except Exception:
            report_exception("splitViewDidResizeSubviews_")
            return None

    @objc.python_method
    def _splitViewDidResizeSubviews_impl(self, note):
        info = note.userInfo()
        if info is not None and info.get("NSSplitViewDividerIndex") is not None and not getattr(self, "_resizing", False):
            subs = self.split.subviews()            # he dragged the divider: that is his table height
            if subs:
                self.top_pref = float(subs[0].frame().size.height)
        self.prefs_dirty = True
        self.place_empty_line()

    def splitView_resizeSubviewsWithOldSize_(self, sv, old):
        try:
            self.resize_split(sv)
        except Exception:
            report_exception("splitView_resizeSubviewsWithOldSize_")
            sv.adjustSubviews()

    @objc.python_method
    def split_top_for(self, avail):
        """The table's height for this much room: his chosen height, unless the list would get less than
        240 pt (or 45 percent of a small window); never below the header and two rows; and less still
        when an open card or the docked reply needs the room."""
        min_top = HEAD_H + 2 * CONV_ROW_H
        pref = self.top_pref or (HEAD_H + 16 * CONV_ROW_H + 4)
        t = min(pref, max(min_top, avail - max(240.0, avail * 0.45)))
        need = self.bottom_need()
        if need:
            t = min(t, avail - need)
        return max(min_top, min(t, avail - 60.0))

    @objc.python_method
    def resize_split(self, sv):
        subs = sv.subviews()
        if len(subs) < 2:
            return
        b = sv.bounds()
        d = sv.dividerThickness()
        avail = max(0.0, b.size.height - d)
        t = self.split_top_for(avail)
        subs[0].setFrame_(NSMakeRect(0, 0, b.size.width, t))
        subs[1].setFrame_(NSMakeRect(0, t + d, b.size.width, max(0.0, avail - t)))

    @objc.python_method
    def bottom_need(self):
        """Room the bottom must have now: the docked reply or its card, above at least 60 pt of list."""
        if not self.dock_visible():
            return 0.0
        return STORAGE_H + LIST_HEAD_H + self.dock_geom(self.bottom.bounds().size.width or 600)["h"] + 60.0

    # ---- the conversation table -----------------------------------------------------------------

    def numberOfRowsInTableView_(self, tv):
        try:
            return self._numberOfRowsInTableView_impl(tv)
        except Exception:
            report_exception("numberOfRowsInTableView_")
            return 0

    @objc.python_method
    def _numberOfRowsInTableView_impl(self, tv):
        return len(self.rows) if tv == self.ctable else len(self.display)

    def tableView_rowViewForRow_(self, tv, row):
        try:
            return self._tableView_rowViewForRow_impl(tv, row)
        except Exception:
            report_exception("tableView_rowViewForRow_")
            return None

    @objc.python_method
    def _tableView_rowViewForRow_impl(self, tv, row):
        rv = tv.makeViewWithIdentifier_owner_("row", self)
        if rv is None:
            rv = RowView.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 10))
            rv.setIdentifier_("row")
        if tv == self.ctable:
            rv.kind = "conv"
            rv.accent = bool(0 <= row < len(self.rows) and self.rows[row].get("waiting_on_you"))
        else:
            rv.kind = row_kind(self.display[row][0]) if 0 <= row < len(self.display) else "item"
            rv.accent = False
            rv.member, rv.member_more = self.group_membership(row)
        rv.setNeedsDisplay_(True)
        return rv

    def tableView_heightOfRow_(self, tv, row):
        try:
            return self._tableView_heightOfRow_impl(tv, row)
        except Exception:
            report_exception("tableView_heightOfRow_")
            return float(CONV_ROW_H)

    @objc.python_method
    def _tableView_heightOfRow_impl(self, tv, row):
        if tv == self.ctable:
            return CONV_ROW_H
        if not 0 <= row < len(self.display):
            return CONV_ROW_H
        kind, key = self.display[row]
        if kind == "g":
            return group_height(self, key)
        if kind == "u":
            return unjust_height(self, key, self.list_col_width())
        return float(self.item_geom(key, self.list_col_width())["height"])

    def tableView_viewForTableColumn_row_(self, tv, col, row):
        try:
            return self._tableView_viewForTableColumn_row_impl(tv, col, row)
        except Exception:
            report_exception("tableView_viewForTableColumn_row_")
            return None

    @objc.python_method
    def _tableView_viewForTableColumn_row_impl(self, tv, col, row):
        if tv == self.wtable:
            if not 0 <= row < len(self.display):
                return None
            kind, key = self.display[row]
            if kind == "g":
                v = tv.makeViewWithIdentifier_owner_("group", self)
                if v is None:
                    v = GroupView.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 10))
                    v.setIdentifier_("group")
                v.show(self, key)
                return v
            if kind == "u":
                v = tv.makeViewWithIdentifier_owner_("unjust", self)
                if v is None:
                    v = UnjustView.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 10))
                    v.setIdentifier_("unjust")
                v.show(self, key)
                return v
            v = tv.makeViewWithIdentifier_owner_("item", self)
            if v is None:
                v = ItemView.alloc().initWithFrame_(NSMakeRect(0, 0, self.list_col_width(), 40))
                v.setIdentifier_("item")
            v.show(self, key)
            return v
        ident = str(col.identifier())
        cls = DescCell if ident == "desc" else LineCell
        v = tv.makeViewWithIdentifier_owner_(ident, self)
        if v is None:
            v = cls.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 10))
            v.setIdentifier_(ident)
        if 0 <= row < len(self.rows):
            self.fill_cell(v, self.rows[row], ident, time.time())
        return v

    @objc.python_method
    def row_title(self, r, now=None):
        now = time.time() if now is None else now
        t = one_line(r.get("title") or r.get("tty") or "")
        ov = self.title_override.get(conv_key(r))
        if ov:
            if ov[0] == t or now > ov[1]:
                self.title_override.pop(conv_key(r), None)
            else:
                return ov[0]
        return t

    @objc.python_method
    def desc_content(self, r):
        """(attributed line, tag or None, tooltip or None) for the Description cell."""
        note = one_line(r.get("note") or "")
        f = r.get(self.view_mode)
        if not (isinstance(f, dict) and (f.get("text") or "").strip()):
            f = r.get("headline") if self.view_mode == "summary" else None
        if isinstance(f, dict) and (f.get("text") or "").strip():
            text = clean(f["text"])
            key = ("desc", text)
            a = self.text_cache.get(key)
            if a is None:
                try:
                    a = RT.inline_attributed(text, font_size=12.5, colors={"text": TEXT})
                except Exception:
                    a = attr(RT.visible_text(text) if RT else text, FONT, TEXT)
                if len(self.text_cache) > 2000:
                    self.text_cache.clear()
                self.text_cache[key] = a
            tag = f"over {f.get('limit')}" if f.get("over") else None
            return a, tag, (note or None)
        d = clean(r.get("description") or "")
        if d:
            return attr(d, FONT, TEXT), None, (note or None)
        return attr(note, FONT, DIM), None, (note or None)

    @objc.python_method
    def fill_cell(self, v, r, ident, now):
        note = one_line(r.get("note") or "")
        if ident == "title":
            v.show(attr(self.row_title(r, now), FONT_TITLE, TEXT_BRIGHT), "Double-click to rename")
        elif ident == "desc":
            a, tag, tip = self.desc_content(r)
            v.show(a, tag, tip)
        elif ident == "time":
            t = time_cell_text(r, now)
            v.show(attr(t, FONT_NUM, DIM if t == "?" else (TEXT_BRIGHT if r.get("working") else TEXT), P_RIGHT),
                   None if t != "?" else (note or None))
        elif ident in ("running", "tasks"):
            n = r.get("running_now" if ident == "running" else "tasks_run")
            if n is None:
                v.show(attr("?", FONT_NUM, DIM, P_RIGHT), note or None)
            else:
                color = DIM if n == 0 else (TEXT_BRIGHT if ident == "running" else TEXT)
                v.show(attr(str(n), FONT_NUM, color, P_RIGHT))
        elif ident == "waiting":
            n = r.get("decisions_waiting")                 # counted from the list's items (count_rows)
            red = bool(r.get("waiting_red"))
            tip = waiting_tip(n, red, r.get("waiting_red_why"), r.get("waiting_note"))   # what is shown, and why
            if n is None:
                v.show(attr("?", FONT_NUM, RED if red else DIM, P_RIGHT), tip)
            else:
                v.show(attr(str(n), FONT_NUM, RED if red else (DIM if n == 0 else TEXT), P_RIGHT), tip)
        elif ident == "totalwait":
            s = total_wait_live(r, now)
            if s is None:
                v.show(attr("?", FONT_NUM, DIM, P_RIGHT), "Not known yet: the waiting list has not been read.")
            else:
                v.show(attr(ENGINE.wait_text(s) if s > 0 else "none", FONT_NUM, DIM if s <= 0 else TEXT, P_RIGHT))

    @objc.python_method
    def apply_rows(self):
        """Sorted rows onto the table: changed rows redrawn in place; a new order reloads, keeping the
        selection by conversation. While a name is being edited the order is held still."""
        new = sort_rows(self.counted_rows(self.raw_rows), self.sort_key, self.sort_reverse)
        old = self.rows
        new_keys, old_keys = [conv_key(r) for r in new], [conv_key(r) for r in old]
        if self.renaming is not None and new_keys != old_keys:
            if sorted(map(str, new_keys)) == sorted(map(str, old_keys)):
                by = {conv_key(r): r for r in new}
                new = [by[k] for k in old_keys]
                new_keys = old_keys
            else:
                return
        sel = self.ctable.selectedRow()
        sel_key = old_keys[sel] if 0 <= sel < len(old_keys) else None
        self.rows = new
        if new_keys == old_keys:
            changed = [i for i, (a, b) in enumerate(zip(new, old)) if a != b]
            if changed:
                idx = NSMutableIndexSet.indexSet()
                for i in changed:
                    idx.addIndex_(i)
                self.ctable.reloadDataForRowIndexes_columnIndexes_(
                    idx, NSIndexSet.indexSetWithIndexesInRange_((0, len(self.ctable.tableColumns()))))
                for i in changed:
                    rv = self.ctable.rowViewAtRow_makeIfNecessary_(i, False)
                    if rv is not None:
                        rv.accent = bool(new[i].get("waiting_on_you"))
                        rv.setNeedsDisplay_(True)
        else:
            self.ctable.reloadData()
            if sel_key is not None and sel_key in new_keys:
                self.ctable.selectRowIndexes_byExtendingSelection_(NSIndexSet.indexSetWithIndex_(new_keys.index(sel_key)), False)
            else:
                self.ctable.deselectAll_(None)
        self.empty_line.setHidden_(bool(self.rows))

    @objc.python_method
    def counted_rows(self, rows):
        """The rows with their Waiting on you count taken from the list this window shows (count_rows)."""
        return count_rows(rows, self.items, bool(self.wmeta.get("ok")), self.wmismatch, self.wmeta.get("as_of"))

    @objc.python_method
    def apply_top(self, rows, err, store, alarms, alarm_err, when):
        self.apply_alarms(alarms, alarm_err)
        if store is not None:
            self.apply_storage(store)
        if err:
            self.last_update = ("error", when, err)
            if not self.rows:
                self.empty_line.show(attr(f"The conversations could not be read: {err}", FONT, DIM))
                self.empty_line.setHidden_(False)
            self.show_footer()
            return
        self.raw_rows = rows or []
        if not self.raw_rows:
            self.empty_line.show(attr(getattr(ENGINE, "EMPTY_TABLE", "No Claude conversations are running."), FONT, DIM))
        self.apply_rows()
        self.last_update = ("ok", when, None)
        self.show_footer()
        if self.prefs_dirty:
            self.save_prefs()

    @objc.python_method
    def visible_rows(self, tv):
        r = tv.rowsInRect_(tv.visibleRect())
        loc, n = (r.location, r.length) if hasattr(r, "location") else (r[0], r[1])
        return range(max(0, loc), max(0, loc) + max(0, n))

    # ---- sorting ------------------------------------------------------------------------------

    def tableView_didClickTableColumn_(self, tv, col):
        try:
            return self._tableView_didClickTableColumn_impl(tv, col)
        except Exception:
            report_exception("tableView_didClickTableColumn_")
            return None

    @objc.python_method
    def _tableView_didClickTableColumn_impl(self, tv, col):
        if tv != self.ctable:
            return
        key = COL_SORT.get(str(col.identifier()))
        if key is None:
            return
        if key == self.sort_key:
            self.set_sort(key, not self.sort_reverse)
        else:
            self.set_sort(key, False)

    @objc.python_method
    def set_sort(self, key, reverse=False):
        self.sort_key, self.sort_reverse = key, bool(reverse)
        self.prefs_dirty = True
        self.apply_rows()
        self.update_sort_ui()
        self.save_prefs()

    @objc.python_method
    def update_sort_ui(self):
        keys = [k for k, _ in SORTS]
        self.sort_popup.selectItemAtIndex_(keys.index(self.sort_key))
        hv = self.ctable.headerView()
        hv.arrow_col = SORT_COL.get(self.sort_key)
        hv.arrow = sort_arrow(self.sort_key, self.sort_reverse)
        hv.setNeedsDisplay_(True)
        hint = "Double-click a name to rename it.  Right-click the header for more columns."
        if TEST_MODE:
            hint = (f"TEST MODE: every send and rename goes to the scratch window {TEST_WS[:8]}, nowhere else." if TEST_WS
                    else "TEST MODE with no scratch window named: every send and rename is refused.")
        self.hint.show(attr(hint, FONT_SMALL, ORANGE if TEST_MODE else DIMMER))

    def sortPopup_(self, sender):
        try:
            return self._sortPopup_impl(sender)
        except Exception:
            report_exception("sortPopup_")
            return None

    @objc.python_method
    def _sortPopup_impl(self, sender):
        key = SORTS[int(sender.indexOfSelectedItem())][0]
        self.set_sort(key, False)

    def sortMenu_(self, sender):
        try:
            return self._sortMenu_impl(sender)
        except Exception:
            report_exception("sortMenu_")
            return None

    @objc.python_method
    def _sortMenu_impl(self, sender):
        self.set_sort(SORTS[int(sender.tag())][0], False)

    def reverseSort_(self, sender):
        try:
            return self._reverseSort_impl(sender)
        except Exception:
            report_exception("reverseSort_")
            return None

    @objc.python_method
    def _reverseSort_impl(self, sender):
        self.set_sort(self.sort_key, not self.sort_reverse)

    def viewMode_(self, sender):
        try:
            return self._viewMode_impl(sender)
        except Exception:
            report_exception("viewMode_")
            return None

    @objc.python_method
    def _viewMode_impl(self, sender):
        mode = "headline" if int(sender.tag()) == 0 else "summary"
        if mode != self.view_mode:
            self.view_mode = mode
            self.prefs_dirty = True
            self.ctable.reloadData()
            self.save_prefs()

    def toggleColumn_(self, sender):
        try:
            return self._toggleColumn_impl(sender)
        except Exception:
            report_exception("toggleColumn_")
            return None

    @objc.python_method
    def _toggleColumn_impl(self, sender):
        ident = str(sender.representedObject())
        col = self.ctable.tableColumnWithIdentifier_(ident)
        if col is not None:
            col.setHidden_(not col.isHidden())
            self.prefs_dirty = True
            self.save_prefs()
            self.ctable.headerView().setNeedsDisplay_(True)

    def columnsChanged_(self, note):
        try:
            return self._columnsChanged_impl(note)
        except Exception:
            report_exception("columnsChanged_")
            return None

    @objc.python_method
    def _columnsChanged_impl(self, note):
        self.prefs_dirty = True

    def validateMenuItem_(self, item):
        try:
            return self._validateMenuItem_impl(item)
        except Exception:
            report_exception("validateMenuItem_")
            return True

    @objc.python_method
    def _validateMenuItem_impl(self, item):
        a = item.action()
        a = a if isinstance(a, str) else (a.decode() if isinstance(a, bytes) else str(a))
        if a == "sortMenu:":
            item.setState_(1 if SORTS[int(item.tag())][0] == self.sort_key else 0)
        elif a == "reverseSort:":
            item.setState_(1 if self.sort_reverse else 0)
        elif a == "viewMode:":
            item.setState_(1 if (int(item.tag()) == 0) == (self.view_mode == "headline") else 0)
        elif a == "toggleColumn:":
            col = self.ctable.tableColumnWithIdentifier_(str(item.representedObject()))
            item.setState_(1 if col is not None and not col.isHidden() else 0)
        return True

    # ---- remembering the layout --------------------------------------------------------------------

    @objc.python_method
    def layout_prefs(self):
        cols = self.ctable.tableColumns()
        return {"columns": {str(c.identifier()): round(float(c.width()), 1) for c in cols},
                "order": [str(c.identifier()) for c in cols],
                "hidden": [str(c.identifier()) for c in cols if c.isHidden()],
                "sort": self.sort_key, "reverse": self.sort_reverse, "view": self.view_mode}

    @objc.python_method
    def save_prefs(self):
        self.prefs_dirty = False
        if not self.remember or self.window is None:
            return
        d = {"v5": self.layout_prefs(), "frame": str(self.window.stringWithSavedFrame())}
        if self.top_pref:
            d["split_top"] = float(self.top_pref)
        write_prefs(d)

    def windowDidMove_(self, note):
        self.prefs_dirty = True

    def windowDidResize_(self, note):
        self.prefs_dirty = True

    def windowWillClose_(self, note):
        self.save_prefs()

    # ---- the footer ------------------------------------------------------------------------------

    @objc.python_method
    def show_footer(self):
        parts = []
        lu = self.last_update
        if lu is None:
            parts.append("Reading the conversations")
        elif lu[0] == "ok":
            parts.append(f"Updated {lu[1]}")
        else:
            parts.append(f"Could not update at {lu[1]}: {lu[2]}")
        if self.flash_msg and time.time() < self.flash_until:
            parts.append(self.flash_msg)
        if TEST_MODE:
            parts.append(f"TEST MODE (scratch window {TEST_WS[:8]})" if TEST_WS else "TEST MODE (no scratch window: nothing is sent)")
        self.foot.show(attr("     ".join(parts), FONT_FOOT, DIM))

    # ---- alarms and storage ------------------------------------------------------------------------

    @objc.python_method
    def apply_alarms(self, alarms, err):
        old_h = self.banner_height()
        lines = []
        if err:
            lines.append((attr(f"The alarm list could not be read: {err}", FONT_ALARM, RED_TEXT), None))
        for al in (alarms or [])[:ALARM_MAX_LINES if len(alarms or []) <= ALARM_MAX_LINES else ALARM_MAX_LINES - 1]:
            s = NSMutableAttributedString.alloc().init()
            s.appendAttributedString_(attr(f"ALARM from {one_line(al.get('from') or '?')}: ", FONT_ALARM, rgb("ffffff")))
            s.appendAttributedString_(attr(one_line(al.get("why") or ""), FONT_ALARM, RED_TEXT))
            acks = [one_line(a) for a in al.get("acks") or []]
            who = ("answered by " + ", ".join(acks)) if acks else "no one has answered yet"
            s.appendAttributedString_(attr(f"     {one_line(al.get('when') or '')}, {who}", FONT_ALARM_META, rgb("ffc9c9")))
            lines.append((s, al))
        extra = len(alarms or []) - (ALARM_MAX_LINES - 1)
        if len(alarms or []) > ALARM_MAX_LINES:
            lines.append((attr(f"and {extra} more open alarms (python3 lab-common/monitor/alarm.py list)", FONT_ALARM, RED_TEXT), None))
        self.alarm_list, self.alarm_err = list(alarms or []), err
        self.banner.lines = lines
        self.banner.setNeedsDisplay_(True)
        self.banner.window() and self.banner.window().invalidateCursorRectsForView_(self.banner)
        if self.banner_height() != old_h:
            self.layout_root()

    @objc.python_method
    def alarm_clicked(self, i, rect):
        if not 0 <= i < len(self.banner.lines):
            return
        al = self.banner.lines[i][1]
        if al is None:
            if self.alarm_err:
                md = f"### The alarm list could not be read\n\n{self.alarm_err}"
            else:
                md = "### Open alarms\n\n" + "\n".join(
                    f"- **{one_line(a.get('from'))}**, {one_line(a.get('when'))}: {one_line(a.get('why'))}" for a in self.alarm_list)
            key = ("alarm", "all")
        else:
            acks = [one_line(a) for a in al.get("acks") or []]
            md = (f"### ALARM from {one_line(al.get('from'))}\n\n"
                  f"**Raised** {one_line(al.get('when'))}.  **Answered by:** {', '.join(acks) if acks else 'no one yet'}."
                  + ("  ==Open for more than a day.==" if al.get("stale") else "") + "\n\n"
                  + clean(al.get("why") or "") + f"\n\n---\n\nAlarm `{one_line(al.get('id'))}`. "
                  "An agent answers it with `python3 lab-common/monitor/alarm.py ack <id> --from <name>`.")
            key = ("alarm", al.get("id"))
        self.hover.show(key, RT.to_html(md, None, "An alarm raised by an agent for all the others"), self.banner, rect, sticky=True)

    @objc.python_method
    def apply_storage(self, s):
        self.store = s
        text = clean(s.get("text") or s.get("message") or "Disk: could not be read")
        level = s.get("level")
        color = {"orange": ORANGE, "red": RED, "unknown": DIM}.get(level, TEXT)
        trend = one_line(s.get("trend_text") or "")
        a = NSMutableAttributedString.alloc().init()
        a.appendAttributedString_(attr(text, FONT_STORAGE, color))
        if trend:
            a.appendAttributedString_(attr(f"  |  {trend}", FONT_STORAGE, DIM))
        if level == "red":
            a.appendAttributedString_(attr("  |  under the floor", FONT_STORAGE, RED))
        self.storage_strip.show(a)

    @objc.python_method
    def storage_markdown(self):
        s = self.store or {}
        if not s.get("ok"):
            return f"### Disk\n\nThe disk could not be read: {clean(s.get('message') or 'no reading yet')}."
        out = [f"### Disk: {s.get('free_gib', 0):.1f} GiB free",
               f"Floor **{s.get('floor_gib', 30):.0f} GiB**. Colour: {'normal' if s.get('level') == 'normal' else s.get('level')}."
               f" Volume {clean(s.get('volume') or '')}."]
        if s.get("no_running_work_declares_disk"):
            out.append("**No running work declares disk.**")
        elif s.get("after_running_gib") is not None:
            out.append(f"**After running work: about {s['after_running_gib']:.1f} GiB**, an estimate: free now minus what "
                       f"each running run declared and has not used yet ({s.get('declared_remaining_gib') or 0:.1f} GiB).")
        if s.get("trend_text"):
            out.append(f"Trend: {clean(s['trend_text'])} (least squares over the last hour, {s.get('trend_samples')} samples).")
        elif s.get("trend_note"):
            out.append(f"Trend: {clean(s['trend_note'])}.")
        runs = s.get("runs") or []
        if runs:
            out.append("")
            out.append("| Run | Lane | Declares | Used so far | Hours left |")
            out.append("|---|---|---|---|---|")
            for r in runs:
                used = r.get("used_gib")
                hl = r.get("hours_left")
                hours = "?" if hl is None else (f"{hl:.1f} h" if hl >= 0 else f"past its hours by {-hl:.1f} h")
                name = clean(r.get("name") or "?").replace("|", "/")
                if not r.get("pid_alive", True):
                    name += " (its process is gone)"
                out.append(f"| {name} | {clean(r.get('lane') or '?')} | {r.get('declared_gib') or 0:.1f} GiB | "
                           f"{'no reading' if used is None else f'{used:.2f} GiB'} | {hours} |")
            notes = [clean(r.get("reading") or "") for r in runs if r.get("reading")]
            if notes:
                out.append("")
                out += [f"- {clean(r.get('name'))}: {clean(r.get('reading'))}" for r in runs if r.get("reading")]
        elif s.get("runs_note"):
            out.append(clean(s["runs_note"]))
        tm = s.get("time_machine") or {}
        out.append("")
        if tm.get("running") is True:
            pct = f", {tm['percent']:.0f} percent" if isinstance(tm.get("percent"), (int, float)) else ""
            out.append(f"**Time Machine:** running, phase {clean(tm.get('phase') or 'unknown')}{pct}.")
        elif tm.get("running") is False:
            out.append("**Time Machine:** not running.")
        else:
            out.append(f"**Time Machine:** could not be read{': ' + clean(tm.get('note')) if tm.get('note') else ''}.")
        return "\n\n".join(x for x in out if x is not None).replace("\n\n|", "\n|").replace("|\n\n|", "|\n|")

    # ---- hover ---------------------------------------------------------------------------------------

    @objc.python_method
    def pointer_screen(self):
        return self.fake_pointer if self.fake_pointer is not None else NSEvent.mouseLocation()

    @objc.python_method
    def hover_target_at(self, src, p):
        if src == "table":
            row, col = self.ctable.rowAtPoint_(p), self.ctable.columnAtPoint_(p)
            if 0 <= row < len(self.rows) and col >= 0 and str(self.ctable.tableColumns()[col].identifier()) == "desc":
                return ("conv", conv_key(self.rows[row]))
            return None
        if src == "storage":
            return ("storage",)
        return None

    @objc.python_method
    def hover_move(self, src, p):
        """The pointer moved over the table or the storage strip. The same target for 0.35 s opens
        the hover panel; a different one restarts the wait."""
        target = self.hover_target_at(src, p)
        if target == self.hover_target:
            return
        self.hover_target = target
        self.hover_token += 1
        if target is None:
            self.schedule_close()
            return
        tok = self.hover_token
        AppHelper.callLater(HOVER_DELAY, safely, self.hover_fire, tok)

    @objc.python_method
    def hover_exit(self, src):
        self.hover_target = None
        self.hover_token += 1
        self.schedule_close()

    @objc.python_method
    def hover_fire(self, tok):
        if tok != self.hover_token or self.hover_target is None:
            return
        self.open_hover(self.hover_target)

    @objc.python_method
    def open_hover(self, target):
        if target[0] == "conv":
            r = next((x for x in self.rows if conv_key(x) == target[1]), None)
            if r is None:
                return
            i = self.rows.index(r)
            ci = self.ctable.columnWithIdentifier_("desc")
            rect = self.ctable.frameOfCellAtColumn_row_(ci, i)
            name = self.row_title(r)
            text = r.get("full_text") or r.get("description") or r.get("note") or "(no message yet)"
            ts = r.get("full_text_ts")
            if r.get("text_source") == "lane status" or not isinstance(ts, (int, float)):
                title, meta = "Lane status", f"{name}, from its lane status file"
            else:
                title, meta = "Latest message", f"{name}, written {age_words(time.time() - ts)} ago"
            if r.get("full_text_cut"):
                meta += " (the message is longer than 100,000 characters; the rest is cut)"
            html = RT.to_html(clean(text), title, clean(meta))
            self.hover.show(target, html, self.ctable, rect)
        elif target[0] == "storage":
            asof = (self.store or {}).get("as_of")
            meta = f"as of {local_clock(asof)}" if isinstance(asof, (int, float)) else None
            self.hover.show(("storage", asof), RT.to_html(self.storage_markdown(), None, meta),
                            self.storage_strip, self.storage_strip.bounds())

    @objc.python_method
    def schedule_close(self):
        AppHelper.callLater(CLOSE_GRACE, safely, self.close_check)

    @objc.python_method
    def hover_panel_entered(self):
        pass

    @objc.python_method
    def hover_panel_exited(self):
        self.schedule_close()

    @objc.python_method
    def close_check(self):
        """Close the hover panel unless the pointer is over it, or over what it belongs to."""
        hp = self.hover
        if not hp.is_shown() or hp.sticky:
            return
        p = self.pointer_screen()
        w = hp.window()
        if w is not None and NSPointInRect(p, w.frame()):
            return
        if hp.anchor is not None:
            view, rect = hp.anchor
            if view.window() is not None:
                sr = view.window().convertRectToScreen_(view.convertRect_toView_(rect, None))
                if NSPointInRect(p, sr):
                    return
        hp.close()
        self.hover_target = None

    @objc.python_method
    def install_escape(self):
        """Escape, least destructive first: an open hover panel closes. Otherwise the key goes on to
        whoever has it (the card: Don't send; the rename field: cancel)."""
        def handler(event):
            try:
                if event.keyCode() == KEY_ESCAPE and self.hover.is_shown():
                    self.hover.close()
                    self.hover_target = None
                    return None
            except Exception:
                report_exception("the Escape key")
            return event
        self.esc_handler = handler
        self.esc_monitor = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(NSEventMaskKeyDown, handler)

    # ---- the waiting list: data ------------------------------------------------------------------------

    @objc.python_method
    def list_col_width(self):
        cols = self.wtable.tableColumns()
        return float(cols[0].width()) if cols else 600.0

    @objc.python_method
    def item_text_attr(self, it):
        key = ("item", it.get("id"), it.get("text"), bool(it.get("yellow")))
        a = self.text_cache.get(key)
        if a is None:
            a = attr(it.get("text") or "", FONT_ITEM, YELLOW if it.get("yellow") else DECISION, P_WRAP)
            self.text_cache[key] = a
        return a

    @objc.python_method
    def item_meta_text(self, it, now=None):
        now = time.time() if now is None else now
        parts = [f"Lane: {one_line(it.get('lane') or 'unknown')}", f"Needs: {one_line(it.get('needs') or 'unknown')}"]
        owner = it.get("owner_lane")
        if owner and owner != it.get("lane"):
            parts.append(f"answered by the {one_line(owner)}")
        wt = item_wait_text(it, now, self.wmeta.get("as_of"))
        if wt:
            parts.append(wt)
        return "     ".join(parts)

    @objc.python_method
    def item_status(self, iid):
        """(text, kind, cancellable outbox id or None) under an item, or None."""
        st = self.state(iid)
        if st.phase == "checking":
            return ("Checking whether this is already resolved", "info", None)
        if st.phase == "sending":
            return ("Sending", "info", None)
        e = self.outbox_by_item.get(iid)
        if e is not None:
            reason = one_line(e.get("reason") or "")
            to = one_line(e.get("label") or e.get("lane") or "its agent")
            if e.get("state") == "failed":
                return (f"Not delivered to the {to} window: {reason or 'check that window'}", "error", e.get("id"))
            if e.get("state") == "typed":
                return (f"Typed into the {to} window, pressing Enter: {reason}", "held", None)
            return (f"Waiting to deliver to the {to} window: {reason or 'trying again every 5 s'}", "held", e.get("id"))
        if st.status:
            return (st.status[0], st.status[1], None)
        return None

    @objc.python_method
    def item_geom(self, iid, width):
        """The ONE layout of an item row, used for its height and for placing and drawing its parts."""
        it = self.item_by_id.get(iid) or {"text": ""}
        st = self.state(iid)
        w = max(80.0, width - IL - IR)
        ta = self.item_text_attr(it)
        th = text_height(ta, w)
        y = I_PAD_T + th + I_GAP
        g = {"w": w, "text_attr": ta, "text_h": th, "meta_y": y}
        y += line_height(FONT_META)
        status = self.item_status(iid)
        g["status"] = status
        if status:
            y += I_GAP
            g["status_y"] = y
            g["status_w"] = text_width(attr(status[0], FONT_SMALL, DIM))
            y += line_height(FONT_SMALL)
        y += I_FIELD_GAP
        if st.phase == "card" and st.card is not None:
            g["card_w"] = min(w, CARD_MAX_W)
            ch = card_layout(st.card, g["card_w"])["height"]
            g.update(card=True, card_h=ch, slot_y=y - CARD_MARGIN + 2, slot_h=ch + 2 * CARD_MARGIN)
            y += ch + 4
        else:
            g["card"] = False
            g["field_y"] = y
            g["field_h"] = field_height(st.draft, w)
            y += g["field_h"]
        y += I_PAD_B
        g["height"] = math.ceil(y)
        return g

    @objc.python_method
    def group_membership(self, row):
        """(this item row sits under a group header, the next row does too, same group)."""
        if not 0 <= row < len(self.display) or self.display[row][0] != "i":
            return False, False
        gi = self.member_group.get(self.display[row][1])
        if gi is None:
            return False, False
        nxt = self.display[row + 1] if row + 1 < len(self.display) else None
        return True, bool(nxt and nxt[0] == "i" and self.member_group.get(nxt[1]) == gi)

    @objc.python_method
    def rebuild_index(self):
        self.index = {k: i for i, k in enumerate(self.display)}

    @objc.python_method
    def item_rows(self):
        return [i for i, (k, _) in enumerate(self.display) if k == "i"]

    @objc.python_method
    def selected_item_ids(self):
        out = []
        idx = self.wtable.selectedRowIndexes()
        i = idx.firstIndex()
        while i != 0x7fffffffffffffff and i is not None and i >= 0 and i < len(self.display):
            k, key = self.display[i]
            if k == "i":
                out.append(key)
            i = idx.indexGreaterThanIndex_(i)
        return out

    @objc.python_method
    def is_selected_item(self, iid):
        r = self.index.get(("i", iid))
        return r is not None and bool(self.wtable.isRowSelected_(r))

    def tableView_selectionIndexesForProposedSelection_(self, tv, proposed):
        try:
            return self._tableView_selectionIndexesForProposedSelection_impl(tv, proposed)
        except Exception:
            report_exception("tableView_selectionIndexesForProposedSelection_")
            return proposed

    @objc.python_method
    def _tableView_selectionIndexesForProposedSelection_impl(self, tv, proposed):
        if tv != self.wtable:
            return proposed
        out = NSMutableIndexSet.indexSet()
        i = proposed.firstIndex()
        while i != 0x7fffffffffffffff and i is not None and 0 <= i < len(self.display):
            if self.display[i][0] == "i":
                out.addIndex_(i)
            i = proposed.indexGreaterThanIndex_(i)
        return out

    def tableViewSelectionDidChange_(self, note):
        try:
            return self._tableViewSelectionDidChange_impl(note)
        except Exception:
            report_exception("tableViewSelectionDidChange_")
            return None

    @objc.python_method
    def _tableViewSelectionDidChange_impl(self, note):
        if note.object() != self.wtable:
            return
        for r in self.visible_rows(self.wtable):
            if r < len(self.display) and self.display[r][0] == "i":
                v = self.wtable.viewAtColumn_row_makeIfNecessary_(0, r, False)
                if v is not None:
                    v.check.setState_(1 if self.wtable.isRowSelected_(r) else 0)
        self.layout_bottom()

    def itemCheck_(self, sender):
        try:
            return self._itemCheck_impl(sender)
        except Exception:
            report_exception("itemCheck_")
            return None

    @objc.python_method
    def _itemCheck_impl(self, sender):
        r = self.index.get(("i", sender.iid))
        if r is None:
            return
        if self.wtable.isRowSelected_(r):
            self.wtable.deselectRow_(r)
        else:
            self.wtable.selectRowIndexes_byExtendingSelection_(NSIndexSet.indexSetWithIndex_(r), True)
        sender.setState_(1 if self.wtable.isRowSelected_(r) else 0)

    @objc.python_method
    def apply_waiting(self, w, err, when):
        if err or not (w or {}).get("ok"):
            msg = err or clean((w or {}).get("message") or "the list could not be read")
            self.wmeta.update(err=msg)
            if self.items:
                self.list_head.show(attr(f"The waiting list could not be read at {when}: {msg}. "
                                         f"Showing the list from {self.wmeta.get('when') or 'earlier'}.", FONT_HEADER_LINE, TEXT))
            else:
                self.list_head.show(attr(f"The waiting list could not be read: {msg}.", FONT_HEADER_LINE, TEXT))
            return
        self.wmeta.update(ok=True, err=None, sha=w.get("sha"), as_of=w.get("as_of") or time.time(), when=when)
        self.wmismatch = list_mismatches(w)
        self.list_head.show(self.header_attr(w))
        items = [i for i in (w.get("items") or []) if isinstance(i, dict) and i.get("id")]
        old_by_id = self.item_by_id
        self.items = items
        self.item_by_id = {i["id"]: i for i in items}
        changed = {i["id"] for i in items if i["id"] in old_by_id and old_by_id[i["id"]] != i}
        sha = w.get("sha")
        un = [u for u in (w.get("unjustified") or []) if isinstance(u, dict) and u.get("key")]
        if [u.get("key") for u in un] != [u.get("key") for u in self.unjust]:
            changed_head = True
        else:
            changed_head = False
        self.unjust, self.unjust_by_key = un, {u["key"]: u for u in un}
        self.restore_drafts(items)
        self.maybe_group(items, sha)
        self.set_groups(self.current_groups(items))
        self.set_display(self.full_display(), changed)
        if changed_head:
            self.refresh_unjust()
        if self.raw_rows:
            self.apply_rows()          # each row's Waiting on you count comes from these items (count_rows)

    @objc.python_method
    def header_attr(self, w):
        n = needs_more_count(w.get("counts"))
        verb = "needs" if n == 1 else "need"
        s = NSMutableAttributedString.alloc().init()
        for piece, is_num in ((str(w.get("total")), True), (" waiting on you. ", False), (str(n), True),
                              (f" {verb} more than a decision.", False)):
            s.appendAttributedString_(attr(piece, FONT_HEADER_NUM if is_num else FONT_HEADER_LINE, ORANGE if is_num else TEXT))
        ms = w.get("may_be_settled_count")
        if isinstance(ms, int) and ms:
            s.appendAttributedString_(attr(f"     {ms} may be settled already", FONT_SMALL, DIM))
        return s

    @objc.python_method
    def set_groups(self, groups):
        self.groups = groups
        self.group_by_key = {group_key(g): g for g in groups}
        self.member_group = {m: group_key(g) for g in groups for m in g.get("members") or []}

    @objc.python_method
    def current_groups(self, items):
        """The groups for these items: the current sha's when known, else the last ones, kept against
        the items that are still here (so groups never blink out while a new grouping runs)."""
        raw = self.groups_raw
        if not raw:
            return []
        enrich = getattr(self.actions(), "_enrich", None)
        try:
            gs = enrich(raw, items) if callable(enrich) else raw
        except Exception:
            gs = raw
        return valid_groups(gs, items)

    @objc.python_method
    def read_group_cache(self, sha):
        """A cached, successful grouping for this sha: [{"topic", "members"}], or None. In cache-only
        mode with nothing for this sha, the newest successful grouping of any sha (kept against the
        current items later)."""
        paths = []
        try:
            paths.append(self.actions()._group_cache_path(sha))
        except Exception:
            pass
        if GROUPING == "cache-only":
            try:
                others = [os.path.join(CACHE, n) for n in os.listdir(CACHE) if n.startswith("groups-") and n.endswith(".json")]
                paths += sorted(others, key=lambda p: os.path.getmtime(p), reverse=True)
            except OSError:
                pass
        for p in paths:
            try:
                with open(p) as f:
                    d = json.load(f)
            except (OSError, ValueError):
                continue
            if isinstance(d, dict) and isinstance(d.get("groups"), list) and not d.get("failed"):
                return [{"topic": g.get("topic"), "members": list(g.get("members") or [])} for g in d["groups"] if isinstance(g, dict)]
        return None

    @objc.python_method
    def maybe_group(self, items, sha):
        if not sha or sha in self.group_done:
            return
        if GROUPING == "cache-only":
            raw = self.read_group_cache(sha)
            self.group_done.add(sha)
            if raw is not None:
                self.groups_raw, self.groups_sha = raw, sha
            return
        if self.group_running is not None or time.time() < self.group_retry_at.get(sha, 0):
            return
        self.group_running = sha
        act = self.actions()
        self.bg(lambda: act.group(items, sha), lambda g: self.after_group(sha, g), fallback=[])

    @objc.python_method
    def after_group(self, sha, groups):
        self.group_running = None
        raw = self.read_group_cache(sha)
        if raw is None:                                 # a failure: group() itself retries after 10 min
            self.group_retry_at[sha] = time.time() + GROUP_RETRY
        else:
            self.group_done.add(sha)
            self.groups_raw, self.groups_sha = raw, sha
            if sha == self.wmeta.get("sha"):
                self.set_groups(self.current_groups(self.items))
                self.set_display(self.full_display(), set())
        if self.wmeta.get("sha") and self.wmeta["sha"] != sha:
            self.maybe_group(self.items, self.wmeta["sha"])

    @objc.python_method
    def group_busy(self, gkey):
        return gkey in self.groups_busy

    # ---- asks without a reason (SPEC section 11) ------------------------------------------------

    @objc.python_method
    def full_display(self):
        return build_display(self.items, self.groups) + unjust_rows(self.unjust, self.unjust_open)

    @objc.python_method
    def toggle_unjust(self):
        self.unjust_open = not self.unjust_open
        self.set_display(self.full_display(), set())
        self.refresh_unjust()

    @objc.python_method
    def refresh_unjust(self):
        rows = [i for i, (k, _) in enumerate(self.display) if k == "u"]
        if rows:
            self.refresh_rows(rows)
            for r in rows:
                v = self.wtable.viewAtColumn_row_makeIfNecessary_(0, r, False)
                if v is not None:
                    v.setNeedsDisplay_(True)
                    if v.window() is not None:
                        v.window().invalidateCursorRectsForView_(v)

    # ---- the cmux banner (SPEC section 11) --------------------------------------------------------

    @objc.python_method
    def update_cmux_banner(self):
        fn = getattr(self.actions(), "cmux_denied", None)
        try:
            reason = fn() if callable(fn) else None
        except Exception:
            reason = None
        text = cmux_banner_text(reason)
        if text == self.cmux_reason:
            return
        self.cmux_reason = text
        if text:
            self.notice.show(attr(text, FONT_ALARM, NOTICE_TEXT), "Agents was opened outside cmux, and cmux admits only "
                             "processes started inside it. Your words are kept in the ANSWERS ledger and wait in the "
                             "outbox; an Agents opened from cmux delivers them.")
        self.layout_root()

    @objc.python_method
    def probe_worker(self):
        fn = getattr(ACT, "probe_cmux", None)
        try:
            if callable(fn):
                fn()
        except Exception:
            self.log_error("cmux probe", traceback.format_exc(limit=1))
        AppHelper.callAfter(safely, self.update_cmux_banner)

    # ---- unsent drafts (SPEC section 11: "Don't send" never discards) -----------------------------

    @objc.python_method
    def drafts(self):
        if self.saved_drafts is None:
            self.saved_drafts = read_drafts()
        return self.saved_drafts

    @objc.python_method
    def save_draft(self, target, text, extra=None):
        d = self.drafts()
        rec = {"text": text, "t": time.time()}
        if target[0] == "dock":
            d["dock"] = dict(rec, iids=list(extra or []))
        else:
            d.setdefault("items", {})[target[1]] = dict(rec, about=first_chars(one_line(extra or ""), 120))
        write_drafts(d)

    @objc.python_method
    def drop_draft(self, target):
        d = self.drafts()
        if target[0] == "dock":
            gone = d.pop("dock", None) is not None
        else:
            gone = d.get("items", {}).pop(target[1], None) is not None
        if gone:
            write_drafts(d)

    @objc.python_method
    def edit_draft(self, target, text):
        """A saved draft follows his edits in the field; an emptied field drops it."""
        d = self.drafts()
        rec = d.get("dock") if target[0] == "dock" else d.get("items", {}).get(target[1])
        if rec is None or rec.get("text") == text:
            return
        if not text.strip():
            self.drop_draft(target)
        else:
            rec.update(text=text, t=time.time())
            write_drafts(d)

    @objc.python_method
    def restore_drafts(self, items):
        """A draft saved by an earlier window goes back into its item's empty field, once."""
        saved = self.drafts().get("items") or {}
        for it in items:
            rec = saved.get(it["id"])
            if isinstance(rec, dict) and rec.get("text"):
                st = self.state(it["id"])
                if not st.draft and st.phase is None and not getattr(st, "restored", False):
                    st.draft = rec["text"]
                    st.restored = True
        dock = self.drafts().get("dock")
        if isinstance(dock, dict) and dock.get("text") and not self.dock["draft"] and self.dock["phase"] is None:
            self.dock["draft"] = dock["text"]

    # ---- the waiting list: keeping his place ----------------------------------------------------

    @objc.python_method
    def list_anchor(self):
        tv = self.wtable
        clip = self.wscroll.contentView()
        top = clip.bounds().origin.y
        if not self.display:
            return None
        r = tv.rowAtPoint_(NSMakePoint(2, top + 1))
        if r < 0:
            return None
        keys = [(self.display[i], tv.rectOfRow_(i).origin.y - top) for i in range(r, min(len(self.display), r + 25))]
        return {"top": top, "keys": keys}

    @objc.python_method
    def restore_anchor(self, a):
        clip = self.wscroll.contentView()
        if a is None or a["top"] <= 0.5:
            clip.scrollToPoint_(NSMakePoint(0, 0))
            self.wscroll.reflectScrolledClipView_(clip)
            return
        for key, off in a["keys"]:
            r = self.index.get(key)
            if r is None:
                continue
            y = self.wtable.rectOfRow_(r).origin.y - off
            doc_h = self.wtable.frame().size.height
            y = max(0.0, min(y, max(0.0, doc_h - clip.bounds().size.height)))
            if abs(y - clip.bounds().origin.y) > 0.5:
                clip.scrollToPoint_(NSMakePoint(0, y))
                self.wscroll.reflectScrolledClipView_(clip)
            return

    @objc.python_method
    def set_display(self, new, changed_ids):
        """Only the rows that changed are inserted, removed or redrawn, never a full reload once the
        list is showing: views of untouched rows (and the field he is typing in) stay as they are."""
        tv = self.wtable
        old = self.display
        first = not old
        anchor = None if first else self.list_anchor()
        sel = self.selected_item_ids()
        if new != old:
            ops = difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes()
            self.display = list(new)
            self.rebuild_index()
            NSAnimationContext.beginGrouping()
            NSAnimationContext.currentContext().setDuration_(0.0)
            if first:
                tv.reloadData()
            else:
                tv.beginUpdates()
                for tag, i1, i2, j1, j2 in reversed(ops):
                    if tag == "equal":
                        continue
                    if i2 > i1:
                        tv.removeRowsAtIndexes_withAnimation_(NSIndexSet.indexSetWithIndexesInRange_((i1, i2 - i1)),
                                                              NSTableViewAnimationEffectNone)
                    if j2 > j1:
                        tv.insertRowsAtIndexes_withAnimation_(NSIndexSet.indexSetWithIndexesInRange_((i1, j2 - j1)),
                                                              NSTableViewAnimationEffectNone)
                tv.endUpdates()
            NSAnimationContext.endGrouping()
            want = NSMutableIndexSet.indexSet()
            for iid in sel:
                r = self.index.get(("i", iid))
                if r is not None:
                    want.addIndex_(r)
            if not want.isEqualToIndexSet_(tv.selectedRowIndexes()):
                tv.selectRowIndexes_byExtendingSelection_(want, False)
        rows = [self.index[("i", i)] for i in changed_ids if ("i", i) in self.index]
        rows += [i for i, (k, _) in enumerate(self.display) if k == "g" or (k, _) == ("u", "head")]
        self.refresh_rows(rows)
        if not first:
            self.restore_anchor(anchor)
        for r in self.visible_rows(tv):
            rv = tv.rowViewAtRow_makeIfNecessary_(r, False)
            if rv is not None and r < len(self.display):
                m = self.group_membership(r)
                kind = row_kind(self.display[r][0])
                if (rv.member, rv.member_more, rv.kind) != (m[0], m[1], kind):
                    rv.member, rv.member_more, rv.kind = m[0], m[1], kind
                    rv.setNeedsDisplay_(True)
        self.layout_bottom()

    @objc.python_method
    def refresh_rows(self, rows, remeasure=True):
        tv = self.wtable
        idx = NSMutableIndexSet.indexSet()
        for r in rows:
            if not 0 <= r < len(self.display):
                continue
            idx.addIndex_(r)
            v = tv.viewAtColumn_row_makeIfNecessary_(0, r, False)
            if v is not None:
                v.show(self, self.display[r][1])
        if remeasure and idx.count():
            NSAnimationContext.beginGrouping()
            NSAnimationContext.currentContext().setDuration_(0.0)
            tv.noteHeightOfRowsWithIndexesChanged_(idx)
            NSAnimationContext.endGrouping()
            for r in rows:
                v = tv.viewAtColumn_row_makeIfNecessary_(0, r, False) if 0 <= r < len(self.display) else None
                if v is not None and hasattr(v, "layout_now"):
                    v.layout_now()

    @objc.python_method
    def refresh_item(self, iid):
        r = self.index.get(("i", iid))
        if r is not None:
            self.refresh_rows([r])

    def listFrameChanged_(self, note):
        try:
            return self._listFrameChanged_impl(note)
        except Exception:
            report_exception("listFrameChanged_")
            return None

    @objc.python_method
    def _listFrameChanged_impl(self, note):
        w = self.list_col_width()
        if w == self.list_width:
            return
        self.list_width = w
        n = len(self.display)
        if n:
            NSAnimationContext.beginGrouping()
            NSAnimationContext.currentContext().setDuration_(0.0)
            self.wtable.noteHeightOfRowsWithIndexesChanged_(NSIndexSet.indexSetWithIndexesInRange_((0, n)))
            NSAnimationContext.endGrouping()

    # ---- text fields: Return sends, Shift-Return adds a line -----------------------------------------

    def control_textView_doCommandBySelector_(self, control, textview, sel):
        try:
            return self._control_textView_doCommandBySelector_impl(control, textview, sel)
        except Exception:
            report_exception("control_textView_doCommandBySelector_")
            return False

    @objc.python_method
    def _control_textView_doCommandBySelector_impl(self, control, textview, sel):
        name = sel if isinstance(sel, str) else (sel.decode() if isinstance(sel, bytes) else str(sel))
        role = getattr(control, "role", None)
        if role == "rename":
            if name in ("insertNewline:", "insertNewlineIgnoringFieldEditor:"):
                self.commit_rename()
                return True
            if name == "cancelOperation:":
                self.cancel_rename()
                return True
            return False
        if name == "insertNewline:":
            if shift_held(NSApp.currentEvent()):
                textview.insertNewlineIgnoringFieldEditor_(None)
                return True
            text = str(control.stringValue())
            if role == "item":
                self.submit_item(control.iid, text)
            elif role == "dock":
                self.submit_dock(text)
            elif role == "msg":
                self.submit_msg(text)
            return True
        return False

    def controlTextDidChange_(self, note):
        try:
            return self._controlTextDidChange_impl(note)
        except Exception:
            report_exception("controlTextDidChange_")
            return None

    @objc.python_method
    def _controlTextDidChange_impl(self, note):
        f = note.object()
        role = getattr(f, "role", None)
        text = str(f.stringValue())
        if role == "item":
            st = self.state(f.iid)
            w = self.list_col_width()
            before = field_height(st.draft, max(80.0, w - IL - IR))
            st.draft = text
            self.edit_draft(("item", f.iid), text)
            if field_height(text, max(80.0, w - IL - IR)) != before:
                self.refresh_item(f.iid)
        elif role == "dock":
            before = self.dock_geom(self.dockv.bounds().size.width)["h"]
            self.dock["draft"] = text
            self.edit_draft(("dock",), text)
            if self.dock_geom(self.dockv.bounds().size.width)["h"] != before:
                self.layout_bottom()
        elif role == "msg":
            self.msg["text"] = text
            self.layout_root()

    def controlTextDidBeginEditing_(self, note):
        try:
            return self._controlTextDidBeginEditing_impl(note)
        except Exception:
            report_exception("controlTextDidBeginEditing_")
            return None

    @objc.python_method
    def _controlTextDidBeginEditing_impl(self, note):
        sv = note.object().superview()
        if sv is not None:
            sv.setNeedsDisplay_(True)

    def controlTextDidEndEditing_(self, note):
        try:
            return self._controlTextDidEndEditing_impl(note)
        except Exception:
            report_exception("controlTextDidEndEditing_")
            return None

    @objc.python_method
    def _controlTextDidEndEditing_impl(self, note):
        f = note.object()
        sv = f.superview()
        if sv is not None:
            sv.setNeedsDisplay_(True)
        if getattr(f, "role", None) == "rename" and self.renaming is not None and self.renaming.get("field") is f:
            # clicking away cancels; checked a moment later, so a restart of editing does not
            AppHelper.callLater(0.05, safely, self.rename_focus_check, f)

    @objc.python_method
    def rename_focus_check(self, f):
        rn = self.renaming
        if rn is not None and rn.get("field") is f and f.currentEditor() is None:
            self.cancel_rename()

    # ---- replying to one item (SPEC section 2: check, card or deliver) --------------------------------

    @objc.python_method
    def submit_item(self, iid, text):
        if iid not in self.item_by_id or not (text or "").strip():
            return
        st = self.state(iid)
        if st.phase in ("checking", "sending", "card"):
            return
        # his words stay in the draft and the field (not editable meanwhile) until a confirmed hand-off (after_send)
        st.phase, st.draft, st.status = "checking", text, None
        self.release_field_for(iid)
        self.refresh_item(iid)
        item = dict(self.item_by_id[iid])
        act = self.actions()
        self.bg(lambda: act.check_resolved(item), lambda res: self.after_check([iid], text, [res], docked=False),
                fallback=(False, "the check failed, treated as open", "the app"))

    @objc.python_method
    def release_field_for(self, iid):
        """Ends editing in the item's field. Its text stays: his words leave the field only after a
        confirmed hand-off (after_send, reply_handoff)."""
        r = self.index.get(("i", iid))
        v = self.wtable.viewAtColumn_row_makeIfNecessary_(0, r, False) if r is not None else None
        if v is not None and v.box.field.currentEditor() is not None:
            self.window.makeFirstResponder_(None)

    @objc.python_method
    def after_check(self, iids, text, results, docked):
        resolved, open_ids = [], []
        for iid, res in zip(iids, results):
            ok, reason, by = (res if isinstance(res, (tuple, list)) and len(res) == 3
                              else (False, "the check failed, treated as open", "the app"))
            if ok:
                it = self.item_by_id.get(iid) or {}
                resolved.append((iid, reason or "its records show it settled", by, it.get("text") or ""))
            else:
                open_ids.append(iid)
        if docked:
            self.dock["phase"] = None
            if open_ids:
                self.send_reply(open_ids, text, docked=True, note_resolved=len(resolved))
            if resolved:
                self.dock["card"] = {"rows": [(i, r, a) for i, r, _, a in resolved],
                                     "by": sorted({b for _, _, b, _ in resolved}), "text": text, "t": time.time(),
                                     "of": len(iids), "iids": [i for i, _, _, _ in resolved],
                                     "note": (f"for these {len(resolved)} only; the other {len(open_ids)} went at once"
                                              if open_ids else f"for these {len(resolved)}")}
                self.layout_bottom()
                self.focus_card(self.dock_card)
            elif not open_ids:
                self.layout_bottom()
            return
        iid = iids[0]
        st = self.state(iid)
        if resolved:
            _, reason, by, about = resolved[0]
            st.phase = "card"
            st.card = {"rows": [(iid, reason, about)], "by": [by], "text": text, "t": time.time(), "of": 1}
            st.status = None
            self.refresh_item(iid)
            self.scroll_card_visible(iid)
            r = self.index.get(("i", iid))
            v = self.wtable.viewAtColumn_row_makeIfNecessary_(0, r, False) if r is not None else None
            if v is not None:
                self.focus_card(v.card)
        else:
            self.send_reply([iid], text, docked=False)

    @objc.python_method
    def focus_card(self, card):
        if card is not None and card.window() is not None:
            card.focus = 0
            card.window().makeFirstResponder_(card)
            card.setNeedsDisplay_(True)

    @objc.python_method
    def scroll_card_visible(self, iid):
        """The whole card, pills included, inside the list's visible area (a tall item's text may
        scroll off the top; the card never sits half out of view)."""
        r = self.index.get(("i", iid))
        if r is None:
            return
        rect = self.wtable.rectOfRow_(r)
        g = self.item_geom(iid, self.list_col_width())
        if g.get("card"):
            y = rect.origin.y + g["slot_y"]
            self.wtable.scrollRectToVisible_(NSMakeRect(0, y, rect.size.width, g["slot_h"] + 6))

    @objc.python_method
    def scroll_item_visible(self, iid):
        r = self.index.get(("i", iid))
        if r is not None:
            self.wtable.scrollRowToVisible_(r)

    @objc.python_method
    def send_reply(self, iids, text, docked, note_resolved=0):
        items = [dict(self.item_by_id[i]) for i in iids if i in self.item_by_id]
        if not items:
            return
        for i in iids:
            st = self.state(i)
            st.phase, st.status = "sending", None
            self.refresh_item(i)
        if docked:
            self.dock["phase"] = "sending"
            self.dock["iids"] = list(iids)
            self.layout_bottom()
        act = self.actions()
        self.bg(lambda: act.reply(items, text), lambda res: self.after_send(iids, text, res, docked),
                fallback=[{"state": "refused", "reason": "the reply could not start", "items": iids, "label": ""}])

    @objc.python_method
    def after_send(self, iids, text, results, docked):
        now = time.time()
        seen = set()
        summary = []
        warns = []
        where = "the reply box above the list" if docked else "the field"
        for r in results or []:
            r = r if isinstance(r, dict) else {}
            label = one_line(r.get("label") or r.get("lane") or "agent's")
            note = one_line(r.get("note") or "")
            state = r.get("state")
            reason = one_line(r.get("reason") or "")
            handed, warn = reply_handoff(r)
            if warn and warn not in warns:
                warns.append(warn)
            for iid in r.get("items") or []:
                seen.add(iid)
                st = self.state(iid)
                st.phase = None
                st.status_t = now
                if state == "delivered":
                    st.status = (f"Sent to the {label} window at {short_clock(now)}" + (f" ({note})" if note else "")
                                 + (" (TEST MODE: typed into the scratch window)" if TEST_WS else ""), "ok")
                elif state == "held":
                    st.status = (f"Waiting to deliver to the {label} window: {reason}", "held")
                elif state == "failed":
                    st.status = (f"Not delivered to the {label} window: {reason}", "error")
                else:
                    st.status = (f"Not sent: {reason}", "error")
                if warn:                                # shown on the item, in the error colour, never ignored
                    st.status = (f"{st.status[0].rstrip('. ')}. Warning: {warn}. Your words stay in {where}.", "error")
                if handed:
                    self.drop_draft(("item", iid))     # his words are in the ledger and the outbox now
                    if not docked:
                        st.draft = ""                   # a confirmed hand-off: only now do they leave the field
                elif not docked and not st.draft:
                    st.draft = text                     # his words stay in the field, never lost
            summary.append((state, label, len(r.get("items") or [])))
        lost = [iid for iid in iids if iid not in seen]
        for iid in lost:
            st = self.state(iid)
            st.phase = None
            st.status = ("Not sent: no answer from the delivery", "error")
            if not docked and not st.draft:
                st.draft = text
        for iid in iids:
            self.refresh_item(iid)
        if docked:
            self.dock["phase"] = None
            delivered = [s for s in summary if s[0] == "delivered"]
            held = [s for s in summary if s[0] == "held"]
            bad = [s for s in summary if s[0] not in ("delivered", "held")]
            words = []
            if delivered:
                words.append(f"sent to {', '.join(l for _, l, _ in delivered)}")
            if held:
                words.append(f"waiting to deliver to {', '.join(l for _, l, _ in held)}")
            if bad:
                words.append(f"not sent to {', '.join(l for _, l, _ in bad)}")
            line = ("One reply, " + "; ".join(words) + f", at {short_clock(now)}.") if words else "Nothing was sent."
            if warns:
                line += " Warning: " + "; ".join(warns) + ". Your words stay in the field."
            self.dock["status"] = (line, "error" if (bad or warns or lost or not words) else ("held" if held else "ok"))
            self.dock["status_t"] = now
            if bad or warns or lost or not words:
                if not self.dock["draft"]:
                    self.dock["draft"] = text           # not all handed off: his words stay in the field
            elif self.dock["card"] is None:
                self.dock["draft"] = ""
                self.drop_draft(("dock",))
                f = self.dock_box.field
                if f.currentEditor() is None:
                    f.setStringValue_("")
            self.layout_bottom()
        self.update_cmux_banner()
        self.wake_outbox.set()
        self.next_wait_at = time.monotonic() + 4.0
        self.wake.set()

    # ---- the card's three buttons ---------------------------------------------------------------------

    @objc.python_method
    def card_action(self, target, key):
        if target[0] == "dock":
            card = self.dock["card"]
            if card is None:
                return
            self.dock["card"] = None
            ids = list(card.get("iids") or [r[0] for r in card["rows"]])
            if key == "send":
                self.send_reply(ids, card["text"], docked=True)
            elif key == "edit":
                self.dock["draft"] = card["text"]
                self.dock["status"] = None
                self.layout_bottom()
                self.edit_field(self.dock_box.field, card["text"])
            else:
                self.dock["draft"] = card["text"]              # never discarded (SPEC section 11)
                self.save_draft(("dock",), card["text"], ids)
                self.dock["status"] = (f"Not sent to the {len(ids)} already resolved. Your words stay in the field, "
                                       "saved as an unsent draft.", "info")
                self.dock["status_t"] = time.time()
                self.layout_bottom()
                f = self.dock_box.field
                if f.currentEditor() is None:
                    f.setStringValue_(card["text"])
            return
        iid = target[1]
        st = self.state(iid)
        card = st.card
        if card is None:
            return
        st.card, st.phase = None, None
        if key == "send":
            self.send_reply([iid], card["text"], docked=False)
        elif key == "edit":
            st.draft = card["text"]
            st.status = None
            self.refresh_item(iid)
            r = self.index.get(("i", iid))
            v = self.wtable.viewAtColumn_row_makeIfNecessary_(0, r, True) if r is not None else None
            if v is not None:
                self.edit_field(v.box.field, card["text"])
        else:
            st.draft = card["text"]                            # never discarded (SPEC section 11)
            it = self.item_by_id.get(iid) or {}
            self.save_draft(("item", iid), card["text"], it.get("text") or "")
            st.status = ("Not sent: it was already resolved. Your words stay in the field, saved as an unsent draft.", "info")
            st.status_t = time.time()
            self.refresh_item(iid)
            if self.window is not None:
                self.window.makeFirstResponder_(self.wtable)

    @objc.python_method
    def edit_field(self, field, text):
        """His text back in the field, the cursor at the end."""
        field.setEditable_(True)
        field.setStringValue_(text)
        if field.window() is not None:
            field.window().makeFirstResponder_(field)
            ed = field.currentEditor()
            if ed is not None:
                ed.setSelectedRange_(NSMakeRange(len(text), 0))

    @objc.python_method
    def slide_card_in(self, card, final):
        """0.18 s ease-out slide down into place, no bounce; with Reduce Motion it is simply there."""
        secs, slides = card_motion(reduce_motion() if self.reduce_override is None else self.reduce_override)
        self.last_card_motion = (secs, slides)
        if not slides:
            card.setFrame_(final)
            return
        card.setFrame_(NSMakeRect(final.origin.x, -final.size.height - CARD_MARGIN, final.size.width, final.size.height))

        def changes(ctx):
            ctx.setDuration_(secs)
            if CAMediaTimingFunction is not None:
                ctx.setTimingFunction_(CAMediaTimingFunction.functionWithName_(kCAMediaTimingFunctionEaseOut))
            card.animator().setFrame_(final)
        NSAnimationContext.runAnimationGroup_completionHandler_(changes, None)

    # ---- several items at once (SPEC section 9) --------------------------------------------------------

    @objc.python_method
    def dock_status_text(self):
        d = self.dock
        if d["phase"] == "checking":
            return (f"Checking whether each of the {len(d['iids'])} is already resolved", "info")
        if d["phase"] == "sending":
            return ("Sending", "info")
        if d["status"] is not None and time.time() - d["status_t"] < 30:
            return d["status"]
        return None

    @objc.python_method
    def submit_dock(self, text):
        ids = self.selected_item_ids()
        if len(ids) < 2 or not (text or "").strip() or self.dock["phase"] is not None or self.dock["card"] is not None:
            return
        # his words stay in the draft and the field (not editable meanwhile) until a confirmed hand-off (after_send)
        self.dock.update(phase="checking", iids=list(ids), draft=text, status=None)
        f = self.dock_box.field
        if f.currentEditor() is not None:
            self.window.makeFirstResponder_(None)
        self.layout_bottom()
        items = [dict(self.item_by_id[i]) for i in ids]
        act = self.actions()
        # one queue, at most CHECK_AT_ONCE checks (Claude processes) at a time, results back in the items' order
        self.bg(lambda: check_items(act.check_resolved, items), lambda res: self.after_check(ids, text, res, docked=True),
                fallback=[(False, "the check failed, treated as open", "the app")] * len(ids))

    # ---- the message bar (SPEC section 8) --------------------------------------------------------------

    @objc.python_method
    def msg_status_text(self):
        m = self.msg
        if m["phase"] == "sending":
            return ("Sending to the coordinator", "info", None)
        if m["phase"] == "held":
            e = next((x for x in self.outbox_entries if x.get("id") == m["outbox_id"]), None)
            reason = one_line((e or {}).get("reason") or (m["status"] or ("", ""))[0])
            cancel = m["outbox_id"] if (e or {}).get("state") in ("waiting", "failed", None) else None
            return (f"Waiting to deliver to the coordinator: {reason or 'trying again every 5 s'}", "held", cancel)
        if m["status"] is not None and time.time() - m["status_t"] < 20:
            return (m["status"][0], m["status"][1], None)
        return None

    @objc.python_method
    def show_msg_status(self):
        self.layout_root()

    @objc.python_method
    def submit_msg(self, text):
        if not (text or "").strip() or self.msg["phase"] is not None:
            return
        self.msg.update(phase="sending", status=None, text=text)
        self.msg_box.field.setEditable_(False)
        self.show_msg_status()
        act = self.actions()
        self.bg(lambda: act.message_coordinator(text), lambda res: self.after_msg(text, res),
                fallback={"state": "refused", "reason": "the message could not start", "outbox_id": None})

    @objc.python_method
    def after_msg(self, text, res):
        res = res or {}
        state = res.get("state")
        now = time.time()
        f = self.msg_box.field
        if state == "delivered":
            self.msg.update(phase=None, outbox_id=None, status=(f"Sent to the coordinator at {short_clock(now)}"
                            + (" (TEST MODE: typed into the scratch window)" if TEST_WS else ""), "ok"), status_t=now)
            if str(f.stringValue()) == text:
                f.setStringValue_("")
            f.setEditable_(True)
        elif state == "held":
            self.msg.update(phase="held", outbox_id=res.get("outbox_id"), status=(one_line(res.get("reason") or ""), "held"), status_t=now)
        else:
            self.msg.update(phase=None, outbox_id=None, status_t=now,
                            status=((f"Not delivered: {one_line(res.get('reason'))}. Check the coordinator's window."
                                     if state == "failed" else f"Not sent: {one_line(res.get('reason'))}"), "error"))
            f.setEditable_(True)
        if res.get("ledger_error"):
            self.flash(res["ledger_error"], 30)
        self.show_msg_status()
        self.update_cmux_banner()
        self.wake_outbox.set()

    # ---- the outbox: waiting to deliver, Cancel ---------------------------------------------------------

    @objc.python_method
    def apply_outbox(self, entries, changes):
        entries = [e for e in (entries or []) if isinstance(e, dict)]
        self.outbox_entries = entries
        old = self.outbox_by_item
        by_item = {}
        for e in entries:
            if e.get("kind") in ("reply", "together"):
                for iid in e.get("items") or []:
                    by_item[iid] = e
        self.outbox_by_item = by_item
        now = time.time()
        touched = set(old) | set(by_item)
        changed_items = set()
        for ch in changes or []:
            if ch.get("state") == "delivered":
                if ch.get("kind") == "reply":
                    for iid in ch.get("items") or []:
                        st = self.state(iid)
                        st.status, st.status_t = (f"Delivered at {short_clock(now)} after waiting", "ok"), now
                        touched.add(iid)
                        changed_items.add(iid)
                if ch.get("id") and ch.get("id") == self.msg.get("outbox_id"):
                    f = self.msg_box.field
                    if str(f.stringValue()) == self.msg.get("text"):
                        f.setStringValue_("")
                    f.setEditable_(True)
                    self.msg.update(phase=None, outbox_id=None, status=(f"Sent to the coordinator at {short_clock(now)}", "ok"), status_t=now)
                for gk in list(self.group_status):
                    if self.group_status[gk][2:3] == (ch.get("id"),):
                        self.group_status[gk] = (f"Delivered to the lead agent at {short_clock(now)}", "ok", None)
            elif ch.get("state") in ("failed", "cancelled", "error") and ch.get("id") == self.msg.get("outbox_id"):
                self.msg_box.field.setEditable_(True)
                self.msg.update(phase=None, outbox_id=None, status=(f"Not delivered: {one_line(ch.get('reason'))}", "error"), status_t=now)
        if self.msg.get("phase") == "held" and self.msg.get("outbox_id") and \
                not any(e.get("id") == self.msg["outbox_id"] for e in entries):
            # no longer waiting and no change seen: it was delivered or cancelled elsewhere
            self.msg_box.field.setEditable_(True)
            self.msg.update(phase=None, outbox_id=None, status=("It is no longer waiting to deliver.", "info"), status_t=now)
        def sig(e):
            return None if e is None else (e.get("id"), e.get("state"), e.get("reason"))
        rows = [self.index[("i", i)] for i in touched
                if ("i", i) in self.index and (sig(old.get(i)) != sig(by_item.get(i)) or i in changed_items)]
        if rows:
            self.refresh_rows(sorted(set(rows)))
        self.show_msg_status()
        self.update_cmux_banner()

    def cancelOutbox_(self, sender):
        try:
            return self._cancelOutbox_impl(sender)
        except Exception:
            report_exception("cancelOutbox_")
            return None

    @objc.python_method
    def _cancelOutbox_impl(self, sender):
        eid = getattr(sender, "entry_id", None)
        if not eid:
            return
        act = self.actions()
        self.bg(lambda: act.cancel(eid), lambda res: self.after_cancel(eid, sender.role, res),
                fallback={"ok": False, "message": "cancel could not run"})

    @objc.python_method
    def after_cancel(self, eid, role, res):
        res = res or {}
        now = time.time()
        if role == "msg":
            if res.get("ok"):
                self.msg_box.field.setEditable_(True)
                self.msg.update(phase=None, outbox_id=None, status_t=now,
                                status=("Cancelled, not sent. Your words stay in the field (and in the ANSWERS ledger).", "info"))
            else:
                self.msg.update(status=(one_line(res.get("message")), "error"), status_t=now)
        else:
            for iid, e in list(self.outbox_by_item.items()):
                if e.get("id") == eid:
                    st = self.state(iid)
                    st.status = (("Cancelled, not sent." if res.get("ok") else one_line(res.get("message"))),
                                 "info" if res.get("ok") else "error")
                    st.status_t = now
                    if res.get("ok"):
                        self.outbox_by_item.pop(iid, None)
                    self.refresh_item(iid)
        self.show_msg_status()
        self.wake_outbox.set()

    # ---- the group button: "Work it out together" ------------------------------------------------------

    def workTogether_(self, sender):
        try:
            return self._workTogether_impl(sender)
        except Exception:
            report_exception("workTogether_")
            return None

    @objc.python_method
    def _workTogether_impl(self, sender):
        gkey = getattr(sender, "gkey", None)
        g = self.group_by_key.get(gkey)
        if g is None or gkey in self.groups_busy:
            return
        self.groups_busy.add(gkey)
        lead = one_line(g.get("lead_label") or g.get("lead_lane") or "lead agent")
        self.group_status[gkey] = (f"Sending to the lead agent, {lead}", "info", None)
        self.refresh_group(gkey)
        act = self.actions()
        self.bg(lambda: act.work_together(g), lambda res: self.after_together(gkey, lead, res),
                fallback={"state": "refused", "reason": "it could not start"})

    @objc.python_method
    def after_together(self, gkey, lead, res):
        self.groups_busy.discard(gkey)
        res = res or {}
        state, reason = res.get("state"), one_line(res.get("reason") or "")
        now = short_clock()
        if state == "delivered":
            self.group_status[gkey] = (f"Sent to {lead} at {now}. It will confer with the others and bring you one question, "
                                       f"or close what does not need you.", "ok", None)
        elif state == "held":
            self.group_status[gkey] = (f"Waiting to deliver to {lead}: {reason}", "held", res.get("outbox_id"))
        else:
            self.group_status[gkey] = (f"Not sent: {reason}", "error", None)
        self.refresh_group(gkey)
        self.update_cmux_banner()
        self.wake_outbox.set()

    @objc.python_method
    def refresh_group(self, gkey):
        r = self.index.get(("g", gkey))
        if r is not None:
            self.refresh_rows([r])

    # ---- renaming (SPEC section 1) ---------------------------------------------------------------------

    def tableDoubleClick_(self, sender):
        try:
            return self._tableDoubleClick_impl(sender)
        except Exception:
            report_exception("tableDoubleClick_")
            return None

    @objc.python_method
    def _tableDoubleClick_impl(self, sender):
        row, col = self.ctable.clickedRow(), self.ctable.clickedColumn()
        if row < 0 or col < 0:
            return
        if str(self.ctable.tableColumns()[col].identifier()) == "title":
            self.begin_rename(row)

    def menuNeedsUpdate_(self, menu):
        try:
            return self._menuNeedsUpdate_impl(menu)
        except Exception:
            report_exception("menuNeedsUpdate_")
            return None

    @objc.python_method
    def _menuNeedsUpdate_impl(self, menu):
        if menu is self.row_menu:
            ok = 0 <= self.ctable.clickedRow() < len(self.rows)
            for it in menu.itemArray():
                it.setEnabled_(ok)

    def renameMenu_(self, sender):
        try:
            return self._renameMenu_impl(sender)
        except Exception:
            report_exception("renameMenu_")
            return None

    @objc.python_method
    def _renameMenu_impl(self, sender):
        row = self.ctable.clickedRow()
        if 0 <= row < len(self.rows):
            self.begin_rename(row)

    def clearNameMenu_(self, sender):
        try:
            return self._clearNameMenu_impl(sender)
        except Exception:
            report_exception("clearNameMenu_")
            return None

    @objc.python_method
    def _clearNameMenu_impl(self, sender):
        self.clear_name_row(self.ctable.clickedRow())

    @objc.python_method
    def clear_name_row(self, row):
        """The row menu's Clear name (split out so --check can drive it without a real right-click)."""
        if 0 <= row < len(self.rows):
            r = self.rows[row]
            self.title_override.pop(conv_key(r), None)
            self.do_rename(r, None)

    @objc.python_method
    def begin_rename(self, row):
        self.cancel_rename()
        r = self.rows[row]
        ci = self.ctable.columnWithIdentifier_("title")
        if ci < 0:
            return
        fr = self.ctable.frameOfCellAtColumn_row_(ci, row)
        ed = ReplyField.alloc().initWithFrame_(NSMakeRect(fr.origin.x + 4, fr.origin.y + 2, fr.size.width - 8, fr.size.height - 4))
        ed.role = "rename"
        ed.setUsesSingleLineMode_(True)
        ed.cell().setWraps_(False)
        ed.cell().setScrollable_(True)
        ed.setDrawsBackground_(True)
        ed.setBackgroundColor_(FIELD_BG)
        ed.setWantsLayer_(True)
        ed.layer().setBorderWidth_(1.0)
        ed.layer().setBorderColor_(ORANGE.CGColor())
        ed.layer().setCornerRadius_(3.0)
        ed.setFont_(FONT_TITLE)
        ed.setStringValue_(self.row_title(r))
        ed.setDelegate_(self)
        self.ctable.addSubview_(ed)
        self.renaming = {"key": conv_key(r), "field": ed, "row": r}
        if self.window is not None:
            self.window.makeFirstResponder_(ed)
            fe = ed.currentEditor()                         # selectText_ would end and restart editing
            if fe is not None:
                fe.selectAll_(None)

    @objc.python_method
    def cancel_rename(self):
        rn = self.renaming
        if rn is None:
            return
        self.renaming = None
        rn["field"].setDelegate_(None)
        rn["field"].removeFromSuperview()
        if self.window is not None and self.window.firstResponder() is None:
            self.window.makeFirstResponder_(self.ctable)
        self.apply_rows()

    @objc.python_method
    def commit_rename(self):
        rn = self.renaming
        if rn is None:
            return
        title = one_line(rn["field"].stringValue())
        if not title:
            self.flash("An empty name was not sent. Type a name, or use Clear name in the row's right-click menu.", 12)
            return
        row = rn["row"]
        self.cancel_rename()
        if not TEST_MODE:
            self.title_override[conv_key(row)] = (title, time.time() + 60)
            self.apply_rows()
            self.ctable.reloadData()
        self.do_rename(row, title)

    @objc.python_method
    def rename_target(self, row):
        """THE ONE PLACE a rename's or Clear name's cmux window is chosen: (workspace id, why not).
        In test mode it is always the scratch window, whatever row was clicked; with no scratch window
        named (the variable present but empty), nothing (SPEC section 11: fail closed)."""
        if TEST_MODE:
            return (TEST_WS, "") if TEST_WS else (None, "test mode names no scratch window, so nothing is renamed")
        tty = row.get("tty")
        try:
            for ws in ENGINE.cmux_workspaces():
                for p in ws.get("panels") or []:
                    if isinstance(p, dict) and tty and p.get("ttyName") == tty and ws.get("workspaceId"):
                        return str(ws["workspaceId"]), ""
        except Exception as ex:
            return None, f"the cmux windows could not be read ({type(ex).__name__})"
        sid = row.get("session_id")
        try:
            w = self.actions().windows().get(sid) if sid else None
            if w and w.get("workspace"):
                return str(w["workspace"]), ""
        except Exception:
            pass
        return None, "its cmux window was not found"

    @objc.python_method
    def do_rename(self, row, title):
        ws, why = self.rename_target(row)
        name = self.row_title(row)
        if not ws:
            self.title_override.pop(conv_key(row), None)
            self.flash(f"Not renamed: {why}.", 12)
            self.ctable.reloadData()
            return
        act = self.actions()
        fn = (lambda: act.rename(ws, title)) if title is not None else (lambda: act.clear_name(ws))
        self.bg(fn, lambda res: self.after_rename(row, name, title, res),
                fallback={"ok": False, "message": "the rename could not run"})

    @objc.python_method
    def after_rename(self, row, name, title, res):
        res = res or {}
        where = " (TEST MODE: the scratch window, not this conversation)" if TEST_MODE else ""
        if res.get("ok"):
            self.flash(clean(res.get("message") or "Renamed.") + where, 12)
        else:
            self.title_override.pop(conv_key(row), None)
            self.flash(f"{name}: " + clean(res.get("message") or "not renamed") + where, 15)
        self.ctable.reloadData()
        self.update_cmux_banner()

    # ---- the ticking second -------------------------------------------------------------------------

    def tick_(self, timer):
        try:
            return self._tick_impl(timer)
        except Exception:
            report_exception("tick_")
            return None

    @objc.python_method
    def _tick_impl(self, timer):
        now = time.time()
        # Time spent and Total wait: redraw text, never re-measure
        cols = {str(c.identifier()): i for i, c in enumerate(self.ctable.tableColumns())}
        for r in self.visible_rows(self.ctable):
            if r >= len(self.rows):
                break
            row = self.rows[r]
            for ident in ("time", "totalwait"):
                ci = cols.get(ident)
                if ci is None or self.ctable.tableColumns()[ci].isHidden():
                    continue
                if ident == "time" and not row.get("ticking"):
                    continue
                v = self.ctable.viewAtColumn_row_makeIfNecessary_(ci, r, False)
                if v is not None:
                    self.fill_cell(v, row, ident, now)
        # waiting times in the list: only each visible item's meta line is redrawn
        for r in self.visible_rows(self.wtable):
            if r < len(self.display) and self.display[r][0] == "i":
                v = self.wtable.viewAtColumn_row_makeIfNecessary_(0, r, False)
                if v is not None and v.geom is not None:
                    v.setNeedsDisplayInRect_(v.meta_rect())
                    if self.state(self.display[r][1]).phase == "card":
                        v.card.setNeedsDisplay_(True)
        if self.dock["card"] is not None:
            self.dock_card.setNeedsDisplay_(True)
        if self.hover.is_shown():
            self.close_check()
        if self.flash_msg and now >= self.flash_until:
            self.flash_msg = None
            self.show_footer()
        if (self.msg["status"] is not None and self.msg["phase"] is None and now - self.msg["status_t"] >= 20
                and not self.msgbar.isHidden() and not self.msg_status.isHidden()):
            self.show_msg_status()
        if self.dock["status"] is not None and self.dock["phase"] is None and now - self.dock["status_t"] >= 30:
            self.dock["status"] = None
            self.layout_bottom()

    # ---- background threads ------------------------------------------------------------------------

    @objc.python_method
    def log_error(self, kind, err):
        if err is None:
            self.logged.pop(kind, None)
            return False
        if self.logged.get(kind) == err:
            return False
        self.logged[kind] = err
        sys.stderr.write(f"{local_clock()} {kind} refresh failed; not repeated while it stays the same:\n")
        traceback.print_exc()
        sys.stderr.flush()
        return True

    @objc.python_method
    def start_worker(self):
        threading.Thread(target=self.probe_worker, name="agents-cmux-probe", daemon=True).start()
        threading.Thread(target=self.worker, name="agents-refresh", daemon=True).start()
        threading.Thread(target=self.outbox_worker, name="agents-outbox", daemon=True).start()

    @objc.python_method
    def worker(self):
        next_conv = next_trim = 0.0
        self.next_wait_at = 0.0
        w_last = None
        while True:
            now = time.monotonic()
            if now >= next_trim:
                next_trim = now + 60.0
                trim_log()
            if now >= self.next_wait_at:
                self.next_wait_at = now + WAIT_EVERY
                w, err = None, None
                try:
                    w = ENGINE.waiting()
                except Exception as ex:
                    err = f"{type(ex).__name__}: {ex}"
                    self.log_error("waiting", err)
                else:
                    self.log_error("waiting", None)
                    if w.get("ok"):
                        w_last = w
                AppHelper.callAfter(safely, self.apply_waiting, w, err, local_clock())
                next_conv = 0.0
            if now >= next_conv:
                next_conv = time.monotonic() + CONV_EVERY
                rows = err = store = alarms = alarm_err = None
                try:
                    rows = ENGINE.conversations(w_last)
                except Exception as ex:
                    err = f"{type(ex).__name__}: {ex}"
                    self.log_error("conversations", err)
                else:
                    self.log_error("conversations", None)
                try:
                    store = ENGINE.storage()
                except Exception as ex:
                    store = {"ok": False, "message": f"{type(ex).__name__}: {ex}", "level": "unknown",
                             "text": f"Disk: could not be read ({type(ex).__name__})"}
                try:
                    alarms = ENGINE.alarms(ALARM_LEDGER)
                except Exception as ex:
                    alarm_err = f"{type(ex).__name__}: {ex}"
                AppHelper.callAfter(safely, self.apply_top, rows, err, store, alarms, alarm_err, local_clock())
            wait = max(0.05, min(next_conv, self.next_wait_at) - time.monotonic())
            self.wake.wait(wait)
            self.wake.clear()

    @objc.python_method
    def outbox_worker(self):
        while True:
            try:
                entries = ACT.outbox()
                changes = []
                if any(e.get("state") in ("waiting", "typed") for e in entries):
                    changes = ACT.pump()
                    entries = ACT.outbox()
                AppHelper.callAfter(safely, self.apply_outbox, entries, changes)
            except Exception:
                self.log_error("outbox", traceback.format_exc(limit=1))
            self.wake_outbox.wait(PUMP_EVERY)
            self.wake_outbox.clear()

    # ---- application delegate --------------------------------------------------------------------------

    def applicationDidFinishLaunching_(self, note):
        try:
            return self._applicationDidFinishLaunching_impl(note)
        except Exception:
            report_exception("applicationDidFinishLaunching_")
            return None

    @objc.python_method
    def _applicationDidFinishLaunching_impl(self, note):
        self.build_window()
        if TEST_MODE or DRIVE_DIR:
            self.window.orderFrontRegardless()          # never takes keyboard focus from his windows
        else:
            self.window.makeKeyAndOrderFront_(None)
            NSApp.activateIgnoringOtherApps_(True)
        self.start_worker()
        if DRIVE_DIR:
            threading.Thread(target=drive, args=(self, DRIVE_DIR), name="agents-drive", daemon=True).start()

    def applicationShouldTerminateAfterLastWindowClosed_(self, app):
        return True

    def applicationWillTerminate_(self, note):
        self.save_prefs()


# ---------------------------------------------------------------------------------------------
# Menus and identity (SPEC section 7)
# ---------------------------------------------------------------------------------------------

def build_menu(app, ctl):
    bar = NSMenu.alloc().init()

    def submenu(title):
        item = NSMenuItem.alloc().init()
        bar.addItem_(item)
        m = NSMenu.alloc().initWithTitle_(title)
        item.setSubmenu_(m)
        return m

    def add(m, title, action, key="", target=None, mods=None, tag=None, obj=None):
        it = m.addItemWithTitle_action_keyEquivalent_(title, action, key)
        if target is not None:
            it.setTarget_(target)
        if mods is not None:
            it.setKeyEquivalentModifierMask_(mods)
        if tag is not None:
            it.setTag_(tag)
        if obj is not None:
            it.setRepresentedObject_(obj)
        return it

    m = submenu("Agents")
    add(m, "About Agents", "orderFrontStandardAboutPanel:")
    m.addItem_(NSMenuItem.separatorItem())
    add(m, "Hide Agents", "hide:", "h")
    add(m, "Hide Others", "hideOtherApplications:", "h", mods=NSEventModifierFlagCommand | NSEventModifierFlagOption)
    add(m, "Show All", "unhideAllApplications:")
    m.addItem_(NSMenuItem.separatorItem())
    add(m, "Quit Agents", "terminate:", "q")

    m = submenu("Edit")
    add(m, "Undo", "undo:", "z")
    add(m, "Redo", "redo:", "z", mods=NSEventModifierFlagCommand | NSEventModifierFlagShift)
    m.addItem_(NSMenuItem.separatorItem())
    add(m, "Cut", "cut:", "x")
    add(m, "Copy", "copy:", "c")
    add(m, "Paste", "paste:", "v")
    add(m, "Select All", "selectAll:", "a")

    m = submenu("View")
    add(m, "Headline (50)", "viewMode:", "1", target=ctl, tag=0)
    add(m, "Summary (200)", "viewMode:", "2", target=ctl, tag=1)
    m.addItem_(NSMenuItem.separatorItem())
    for ident in OPTIONAL_COLUMNS:
        add(m, f"{COL_BY_ID[ident][1]} column", "toggleColumn:", target=ctl, obj=ident)

    m = submenu("Sort")
    for i, (key, title) in enumerate(SORTS):
        add(m, title, "sortMenu:", target=ctl, tag=i)
    m.addItem_(NSMenuItem.separatorItem())
    add(m, "Reverse order", "reverseSort:", target=ctl)

    m = submenu("Window")
    add(m, "Minimize", "performMiniaturize:", "m")
    add(m, "Close", "performClose:", "w")
    app.setWindowsMenu_(m)
    app.setMainMenu_(bar)


def make_app():
    """The process runs as Homebrew's Python.app. Its name, the menu title, the Dock tile's label and
    icon are set to Agents here, before AppKit reads them."""
    try:
        NSProcessInfo.processInfo().setProcessName_("Agents")
    except Exception:
        pass
    try:
        info = NSBundle.mainBundle().infoDictionary()
        if info is not None:
            info["CFBundleName"] = "Agents"
            info["CFBundleDisplayName"] = "Agents"
    except Exception:
        pass
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
    app.setAppearance_(NSAppearance.appearanceNamed_(NSAppearanceNameDarkAqua))
    if os.path.exists(ICON_PATH):
        img = NSImage.alloc().initWithContentsOfFile_(ICON_PATH)
        if img is not None:
            app.setApplicationIconImage_(img)
    return app


# ---------------------------------------------------------------------------------------------
# drive(): the screenshot script (AGENTS_DRIVE=<folder>). Every step calls the function a real
# interaction calls: the hover step calls hover_move (what the pointer's tracking area calls), a reply
# step calls submit_item (what Return calls), the card is answered through its own keyDown_.
# ---------------------------------------------------------------------------------------------

def on_main(fn, *a, timeout=60):
    box, ev = {}, threading.Event()

    def run():
        try:
            box["v"] = fn(*a)
        except Exception as ex:
            box["e"] = f"{type(ex).__name__}: {ex}"
            traceback.print_exc()
        ev.set()
    AppHelper.callAfter(run)
    ev.wait(timeout)
    if "e" in box:
        raise RuntimeError(box["e"])
    return box.get("v")


def my_windows():
    import Quartz
    infos = Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID)
    out = []
    for w in infos or []:
        b = w.get("kCGWindowBounds") or {}
        if w.get("kCGWindowOwnerPID") == os.getpid() and b.get("Width", 0) > 8 and b.get("Height", 0) > 8:
            out.append((int(w["kCGWindowNumber"]), {k: float(b[k]) for k in ("X", "Y", "Width", "Height")}))
    return out                                          # front to back


def shoot(path):
    """The front-most window of this process, captured by its window id, occluded or not, never
    raising it. Measured 10 Sep: screencapture -l on an open popover's window returns the main window
    with the popover in place (its window group), so one capture shows both."""
    wins = my_windows()
    if wins:
        subprocess.run(["/usr/sbin/screencapture", "-x", "-o", "-l", str(wins[0][0]), path], check=False,
                       capture_output=True, timeout=20)
        if os.path.exists(path) and os.path.getsize(path) > 0:
            return True
    # 11 Sep 06:38: with the display asleep or the screen locked, screencapture writes nothing (a full
    # capture was all black), so every screenshot of the live test was missing. Then the window draws
    # its own views into a bitmap instead: the whole content, exactly as laid out, without the title bar
    # and without a popover (a popover is its own window). The result says which it was.
    return "rendered" if on_main(_render_window, path) else False


def _render_window(path):
    from AppKit import NSBitmapImageFileTypePNG
    wins = [w for w in NSApp.windows() if w.isVisible() and w.contentView() is not None]
    if not wins:
        return False
    w = max(wins, key=lambda x: x.frame().size.width * x.frame().size.height)
    cv = w.contentView()
    cv.layoutSubtreeIfNeeded()
    rep = cv.bitmapImageRepForCachingDisplayInRect_(cv.bounds())
    if rep is None:
        return False
    cv.cacheDisplayInRect_toBitmapImageRep_(cv.bounds(), rep)
    # A scroll view's document is left blank (white) by that render (measured 11 Sep: the conversation
    # table drew only when rendered on its own), so each scroll view's visible part is drawn again, from
    # its own render, in its place.
    from AppKit import NSGraphicsContext, NSCompositingOperationSourceOver, NSZeroRect
    ctx = NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.setCurrentContext_(ctx)
    try:
        todo = list(cv.subviews())
        while todo:
            v = todo.pop()
            if v.isHidden():
                continue
            if isinstance(v, NSScrollView) and v.documentView() is not None:
                clip, doc = v.contentView(), v.documentView()
                vis = clip.documentVisibleRect()
                part = doc.bitmapImageRepForCachingDisplayInRect_(vis)
                if part is not None:
                    doc.cacheDisplayInRect_toBitmapImageRep_(vis, part)
                    dest = clip.convertRect_toView_(clip.bounds(), cv)
                    if cv.isFlipped():
                        dest.origin.y = cv.bounds().size.height - dest.origin.y - dest.size.height
                    part.drawInRect_fromRect_operation_fraction_respectFlipped_hints_(
                        dest, NSZeroRect, NSCompositingOperationSourceOver, 1.0, True, None)
                continue
            todo.extend(v.subviews())
    finally:
        NSGraphicsContext.restoreGraphicsState()
    data = rep.representationUsingType_properties_(NSBitmapImageFileTypePNG, {})
    return bool(data is not None and data.writeToFile_atomically_(path, True))


def wait_until(pred, timeout=30.0, step=0.25):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if on_main(pred):
                return True
        except Exception:
            pass
        time.sleep(step)
    return False


def drive(ctl, out_dir):
    """Steps from AGENTS_DRIVE_STEPS (comma separated), default the six screenshots of the work order.
    Writes <step>.png files and drive.json (what each step saw) into out_dir, then quits."""
    os.makedirs(out_dir, exist_ok=True)
    steps = [s.strip() for s in (os.environ.get("AGENTS_DRIVE_STEPS") or
                                 "window,hover,group,storage,card,small").split(",") if s.strip()]
    log = {"steps": {}, "started": local_clock()}

    def note(step, **kw):
        log["steps"].setdefault(step, {}).update(kw)
        with open(os.path.join(out_dir, "drive.json"), "w") as f:
            json.dump(log, f, indent=1, default=str)

    wait_until(lambda: bool(ctl.rows) and bool(ctl.display), timeout=40)
    time.sleep(1.5)
    item_env = (os.environ.get("AGENTS_DRIVE_ITEM") or "").strip()

    def screen_point(view, rect):
        r = view.window().convertRectToScreen_(view.convertRect_toView_(rect, None))
        return NSMakePoint(r.origin.x + r.size.width / 2, r.origin.y + r.size.height / 2)

    def scroll_list_to(key):
        r = ctl.index.get(key)
        if r is None:
            return False
        rect = ctl.wtable.rectOfRow_(r)
        clip = ctl.wscroll.contentView()
        clip.scrollToPoint_(NSMakePoint(0, max(0.0, rect.origin.y - 8)))
        ctl.wscroll.reflectScrolledClipView_(clip)
        return True

    for step in steps:
        try:
            if step == "window":
                def flags():
                    out = []
                    for r in ctl.visible_rows(ctl.wtable):
                        rv = ctl.wtable.rowViewAtRow_makeIfNecessary_(r, False)
                        if rv is not None and r < len(ctl.display):
                            out.append((r, ctl.display[r][0], rv.kind, rv.member, rv.member_more))
                    return out
                note(step, row_flags=on_main(flags))
                note(step, png=shoot(os.path.join(out_dir, "window.png")), rows=len(ctl.rows), items=len(ctl.items),
                     groups=len(ctl.groups), footer=on_main(lambda: ctl.foot.plain()))
            elif step == "hover":
                def start():
                    ci = ctl.ctable.columnWithIdentifier_("desc")
                    rect = ctl.ctable.frameOfCellAtColumn_row_(ci, 0)
                    ctl.fake_pointer = screen_point(ctl.ctable, rect)
                    ctl.hover_move("table", NSMakePoint(rect.origin.x + 30, rect.origin.y + rect.size.height / 2))
                    return ctl.rows[0].get("title")
                title = on_main(start)
                opened = wait_until(lambda: ctl.hover.is_shown(), timeout=8)
                time.sleep(0.8)
                info = on_main(lambda: {"shown": ctl.hover.is_shown(), "height": ctl.hover.last_height,
                                        "refused": ctl.hover.nav.refused, "key": str(ctl.hover.shown_key)})
                note(step, title=title, opened=opened, png=shoot(os.path.join(out_dir, "hover.png")), **info)
                # a navigation attempted inside the panel (what a link click would start) is refused
                from Foundation import NSURL, NSURLRequest
                on_main(lambda: ctl.hover.web.loadRequest_(NSURLRequest.requestWithURL_(NSURL.URLWithString_("https://example.com/"))))
                time.sleep(1.5)
                note(step, after_navigation=on_main(lambda: {"refused": ctl.hover.nav.refused,
                                                             "url": str(ctl.hover.web.URL().absoluteString()) if ctl.hover.web.URL() else None,
                                                             "still_shown": ctl.hover.is_shown()}))
                # the pointer leaves: the panel closes by itself within the grace time
                on_main(lambda: setattr(ctl, "fake_pointer", NSMakePoint(5, 5)) or ctl.hover_exit("table"))
                closed = wait_until(lambda: not ctl.hover.is_shown(), timeout=4)
                note(step, closed_after_leaving=closed)
                on_main(lambda: setattr(ctl, "fake_pointer", None))
            elif step == "group":
                gk = on_main(lambda: next((k for k in ctl.display if k[0] == "g"), None))
                if gk is None:
                    note(step, error="no group in the list")
                    continue
                on_main(scroll_list_to, gk)
                time.sleep(0.6)
                g = on_main(lambda: ctl.group_by_key.get(gk[1]))
                note(step, topic=(g or {}).get("topic"), members=len((g or {}).get("members") or []),
                     png=shoot(os.path.join(out_dir, "group.png")))
            elif step == "storage":
                def start_s():
                    b = ctl.storage_strip.bounds()
                    ctl.fake_pointer = screen_point(ctl.storage_strip, b)
                    ctl.hover_move("storage", NSMakePoint(40, 10))
                on_main(start_s)
                opened = wait_until(lambda: ctl.hover.is_shown(), timeout=8)
                time.sleep(0.8)
                note(step, opened=opened, strip=on_main(lambda: ctl.storage_strip.plain()),
                     png=shoot(os.path.join(out_dir, "storage-hover.png")))
                on_main(lambda: (setattr(ctl, "fake_pointer", None), ctl.hover.close()))
            elif step == "card":
                iid = item_env or on_main(lambda: ctl.items[0]["id"])
                on_main(scroll_list_to, ("i", iid))
                time.sleep(0.4)
                text = "Test reply from the Agents app build: please go ahead as you proposed."

                def type_and_return():
                    ctl.state(iid).draft = text
                    ctl.refresh_item(iid)
                    ctl.submit_item(iid, text)          # what Return in that field calls
                on_main(type_and_return)
                got = wait_until(lambda: ctl.state(iid).phase == "card" or ctl.state(iid).phase is None, timeout=30)
                time.sleep(0.9)
                st = on_main(lambda: {"phase": ctl.state(iid).phase, "card": ctl.state(iid).card,
                                      "status": ctl.state(iid).status, "motion": ctl.last_card_motion})
                note(step, item=iid, settled=got, png=shoot(os.path.join(out_dir, "card.png")), **st)
                if st["phase"] == "card":
                    def press_e():
                        r = ctl.index.get(("i", iid))
                        v = ctl.wtable.viewAtColumn_row_makeIfNecessary_(0, r, True)
                        ev = NSEvent.keyEventWithType_location_modifierFlags_timestamp_windowNumber_context_characters_charactersIgnoringModifiers_isARepeat_keyCode_(
                            10, NSMakePoint(0, 0), 0, 0, ctl.window.windowNumber(), None, "e", "e", False, 14)
                        v.card.keyDown_(ev)
                        f = ctl.wtable.viewAtColumn_row_makeIfNecessary_(0, ctl.index[("i", iid)], True).box.field
                        ed = f.currentEditor()
                        return {"field": str(f.stringValue()), "editing": ed is not None,
                                "cursor": tuple(ed.selectedRange()) if ed is not None else None,
                                "phase": ctl.state(iid).phase}
                    note(step, after_E=on_main(press_e))
                    time.sleep(0.5)
                    note(step, png_after_edit=shoot(os.path.join(out_dir, "card-after-edit.png")))
                    def clear():
                        ctl.window.makeFirstResponder_(None)
                        ctl.state(iid).draft = ""
                        ctl.refresh_item(iid)
                    on_main(clear)
            elif step == "deliver":
                iid = (os.environ.get("AGENTS_DRIVE_OPEN_ITEM") or "").strip()
                on_main(scroll_list_to, ("i", iid))
                text = "Agents app build test (open path): no action needed."
                on_main(lambda: ctl.submit_item(iid, text))
                wait_until(lambda: ctl.state(iid).phase is None or ctl.state(iid).phase == "card", timeout=40)
                on_main(scroll_list_to, ("i", iid))
                time.sleep(0.6)
                note(step, item=iid, status=on_main(lambda: ctl.state(iid).status), phase=on_main(lambda: ctl.state(iid).phase),
                     png=shoot(os.path.join(out_dir, "deliver.png")))
            elif step == "multi":
                ids = [x for x in (os.environ.get("AGENTS_DRIVE_MULTI") or "").split(",") if x]

                def select():
                    idx = NSMutableIndexSet.indexSet()
                    for i in ids:
                        r = ctl.index.get(("i", i))
                        if r is not None:
                            idx.addIndex_(r)
                    ctl.wtable.selectRowIndexes_byExtendingSelection_(idx, False)
                    ctl.tableViewSelectionDidChange_(type("N", (), {"object": lambda self: ctl.wtable})())
                    return ctl.selected_item_ids()
                sel = on_main(select)
                time.sleep(0.5)
                note(step, selected=sel, png_selected=shoot(os.path.join(out_dir, "multi-selected.png")))
                on_main(lambda: ctl.submit_dock("Agents app build test (several at once): no action needed."))
                wait_until(lambda: ctl.dock["phase"] is None, timeout=45)
                time.sleep(0.9)
                note(step, dock_card=on_main(lambda: ctl.dock["card"]), dock_status=on_main(lambda: ctl.dock["status"]),
                     statuses=on_main(lambda: {i: ctl.state(i).status for i in ids}),
                     png=shoot(os.path.join(out_dir, "multi-card.png")))
            elif step == "held":
                # An item reply held by the guard, on screen: the seeded (answered) item brings the card
                # from the free checks (no model call), Send anyway goes to a window showing a permission
                # question, so it waits to deliver with Cancel; then Cancel.
                iid = item_env or on_main(lambda: ctl.items[0]["id"])
                on_main(scroll_list_to, ("i", iid))
                text = "Agents app build test (held path): no action needed."
                on_main(lambda: ctl.submit_item(iid, text))
                wait_until(lambda: ctl.state(iid).phase == "card" or ctl.state(iid).phase is None, timeout=30)
                on_main(lambda: ctl.card_action(("i", iid), "send"))
                wait_until(lambda: ctl.outbox_by_item.get(iid) is not None, timeout=20)
                on_main(scroll_list_to, ("i", iid))
                time.sleep(0.8)

                def held_view():
                    r = ctl.index.get(("i", iid))
                    v = ctl.wtable.viewAtColumn_row_makeIfNecessary_(0, r, True) if r is not None else None
                    g = ctl.item_geom(iid, v.bounds().size.width) if v is not None else {}
                    return {"status_line": list((g or {}).get("status") or [])[:3],
                            "cancel_shown": bool(v is not None and not v.cancel.isHidden()),
                            "entry": dict(ctl.outbox_by_item.get(iid) or {})}
                info = on_main(held_view)
                note(step, item=iid, png=shoot(os.path.join(out_dir, "held.png")), **info)

                def press_cancel():
                    r = ctl.index.get(("i", iid))
                    v = ctl.wtable.viewAtColumn_row_makeIfNecessary_(0, r, True)
                    ctl.cancelOutbox_(v.cancel)              # what a click on Cancel calls
                on_main(press_cancel)
                wait_until(lambda: ctl.outbox_by_item.get(iid) is None, timeout=15)
                time.sleep(0.5)
                note(step, after_cancel=on_main(lambda: ctl.state(iid).status),
                     png_after_cancel=shoot(os.path.join(out_dir, "held-cancelled.png")))
            elif step in ("msg", "msgheld"):
                on_main(lambda: ctl.msg_box.field.setStringValue_("Agents app build test: message bar, no action needed."))
                on_main(lambda: ctl.submit_msg(str(ctl.msg_box.field.stringValue())))
                wait_until(lambda: ctl.msg["phase"] != "sending", timeout=20)
                time.sleep(0.4)
                note(step, msg=on_main(lambda: dict(ctl.msg)), field=on_main(lambda: str(ctl.msg_box.field.stringValue())),
                     png=shoot(os.path.join(out_dir, f"{step}.png")))
                if on_main(lambda: ctl.msg["phase"]) == "held":
                    on_main(lambda: ctl.cancelOutbox_(ctl.msg_cancel))
                    wait_until(lambda: ctl.msg["phase"] is None, timeout=10)
                    note(step, after_cancel=on_main(lambda: dict(ctl.msg)),
                         field_after_cancel=on_main(lambda: str(ctl.msg_box.field.stringValue())),
                         png_after_cancel=shoot(os.path.join(out_dir, f"{step}-cancelled.png")))
            elif step == "rename":
                name = os.environ.get("AGENTS_DRIVE_RENAME") or "Agents test renamed by the app"

                def start_r():
                    ctl.begin_rename(0)
                    f = ctl.renaming["field"]
                    f.setStringValue_(name)
                    return ctl.row_title(ctl.rows[0])
                title = on_main(start_r)
                time.sleep(0.3)
                png = shoot(os.path.join(out_dir, "rename-editing.png"))
                on_main(lambda: ctl.control_textView_doCommandBySelector_(ctl.renaming["field"], None, "insertNewline:"))
                time.sleep(2.5)
                note(step, row_title=title, png=png, footer=on_main(lambda: ctl.foot.plain()))
                # Escape cancels: a second edit, cancelled, sends nothing
                on_main(lambda: ctl.begin_rename(0))
                on_main(lambda: ctl.control_textView_doCommandBySelector_(ctl.renaming["field"], None, "cancelOperation:"))
                note(step, escape_cancelled=on_main(lambda: ctl.renaming is None))
            elif step == "alarm":
                wait_until(lambda: bool(ctl.banner.lines), timeout=12)
                note(step, lines=on_main(lambda: [str(a.string()) for a, _ in ctl.banner.lines]))
                on_main(lambda: ctl.alarm_clicked(0, NSMakeRect(0, 0, ctl.banner.bounds().size.width, ALARM_LINE_H)))
                wait_until(lambda: ctl.hover.is_shown(), timeout=8)
                time.sleep(0.8)
                note(step, png=shoot(os.path.join(out_dir, "alarm.png")))
                on_main(lambda: ctl.hover.close())
            elif step == "small":
                on_main(lambda: ctl.window.setContentSize_(NSMakeSize(700, 500)))
                time.sleep(1.2)
                fr = on_main(lambda: tuple(ctl.window.contentView().frame().size))
                note(step, size=fr, png=shoot(os.path.join(out_dir, "700x500.png")))
            elif step == "dump":
                def dump():
                    lines = []

                    def walk(v, d):
                        f = v.frame()
                        lines.append("  " * d + f"{type(v).__name__} ({f.origin.x:.0f},{f.origin.y:.0f},{f.size.width:.0f},"
                                     f"{f.size.height:.0f}) hidden={v.isHidden()} alpha={v.alphaValue():.2f} layer={v.wantsLayer()}")
                        if d < 3:
                            for sv in v.subviews():
                                walk(sv, d + 1)
                    cv = ctl.window.contentView()
                    walk(cv, 0)
                    rep = cv.bitmapImageRepForCachingDisplayInRect_(cv.bounds())
                    cv.cacheDisplayInRect_toBitmapImageRep_(cv.bounds(), rep)
                    from AppKit import NSBitmapImageFileTypePNG
                    rep.representationUsingType_properties_(NSBitmapImageFileTypePNG, {}).writeToFile_atomically_(
                        os.path.join(out_dir, "dump-cache.png"), True)
                    return lines, [(b, str(w)) for w, b in my_windows()]
                lines, wins = on_main(dump)
                note(step, views=lines, windows=wins)
            elif step.startswith("mode:"):
                mf = os.environ.get("AGENTS_DRIVE_MODEFILE")
                if mf:
                    with open(mf, "w") as f:
                        f.write(step[5:])
                    time.sleep(0.8)
                note(step, mode=step[5:])
            elif step == "together":
                gk = on_main(lambda: next((k for k in ctl.display if k[0] == "g"), None))
                on_main(scroll_list_to, gk)
                time.sleep(0.3)

                def press():
                    r = ctl.index.get(gk)
                    v = ctl.wtable.viewAtColumn_row_makeIfNecessary_(0, r, True)
                    ctl.workTogether_(v.button)              # what the button's click calls
                    return ctl.group_by_key[gk[1]].get("topic")
                topic = on_main(press)
                wait_until(lambda: gk[1] not in ctl.groups_busy, timeout=20)
                time.sleep(0.5)
                note(step, topic=topic, status=on_main(lambda: ctl.group_status.get(gk[1])),
                     png=shoot(os.path.join(out_dir, "together.png")))
            elif step.startswith("sleep"):
                time.sleep(float(step[5:] or 2))
        except Exception as ex:
            note(step, error=f"{type(ex).__name__}: {ex}", trace=traceback.format_exc(limit=3))
    note("done", at=local_clock())
    time.sleep(0.5)
    AppHelper.callAfter(NSApp.terminate_, None)


def main(argv):
    load_modules()
    if "--check" in argv:
        return run_check()
    trim_log()
    app = make_app()
    ctl = Controller.alloc().init()
    app.setDelegate_(ctl)
    build_menu(app, ctl)
    main.ctl = ctl                                    # keep the delegate alive
    AppHelper.runEventLoop(installInterrupt=False)
    return 0


def run_check():
    """Planted controls on a hidden window: planted rows and items, fake actions (no cmux, no model,
    no ledger), a prefs file in a temporary folder. Each control drives the function a click, a key or
    a refresh would call, and can fail."""
    global PREFS_PATH, TEST_WS, TEST_MODE, DRAFTS_PATH
    import tempfile
    tmp = tempfile.mkdtemp(prefix="agents-check-")
    PREFS_PATH = os.path.join(tmp, "prefs.json")
    DRAFTS_PATH = os.path.join(tmp, "drafts.json")
    NSApplication.sharedApplication()
    results = []

    def check(name, ok, detail=""):
        results.append(bool(ok))
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"   ({detail})" if detail else ""))

    now = time.time()

    def headline(text, limit=50, over=False):
        return {"text": text, "visible": text, "visible_len": len(text), "limit": limit, "complete": True,
                "over": over, "ok": not over, "code": False}

    rows = [
        # lanes: the Waiting on you count is counted from the list's items by lane (count_rows); WORKFLOW's 3 are
        # i1 (a stack item, the coordinator's) and i19, i20; Clip's 1 is i2; EQ has no lane and stays unknown.
        {"title": "WORKFLOW", "lane": "coordinator", "tty": "ttys001", "session_id": "s1", "working": True, "ticking": True, "seconds_working": 1000,
         "time_text": "16 m", "last_entry_ts": now - 10, "running_now": 1, "tasks_run": 5,
         "headline": headline("Waiting on you: pick **one**."), "summary": headline("The **plan** is ready.", 200),
         "waiting_on_you": True, "decisions_waiting": 3, "total_wait_seconds": 600, "waits_as_of": now,
         "full_text": "Waiting on you: pick one.\n\n- a\n- b", "full_text_ts": now - 90, "text_source": "transcript", "note": ""},
        {"title": "Clip", "lane": "clip", "tty": "ttys002", "session_id": "s2", "working": False, "ticking": False, "seconds_working": 5000,
         "time_text": "1 h 23 m", "last_entry_ts": now - 100, "running_now": 0, "tasks_run": 10,
         "headline": headline("A very long first line \u2014 with an em dash, that runs past fifty visible characters.", over=True),
         "summary": headline("x" * 230, 200, over=True), "waiting_on_you": False, "decisions_waiting": 1,
         "total_wait_seconds": 100, "waits_as_of": now, "full_text": "Long.", "full_text_ts": None,
         "text_source": "lane status", "note": ""},
        {"title": "EQ", "lane": None, "tty": "ttys003", "session_id": "s3", "working": None, "ticking": None, "seconds_working": 0, "time_text": "",
         "last_entry_ts": None, "running_now": None, "tasks_run": None, "headline": None, "summary": None,
         "description": "", "waiting_on_you": False, "decisions_waiting": None, "total_wait_seconds": None,
         "waits_as_of": None, "note": "no transcript could be read"},
        {"title": "Beta", "lane": "beta", "tty": "ttys004", "session_id": "s4", "working": False, "ticking": False, "seconds_working": 200,
         "time_text": "3 m", "last_entry_ts": now - 5000, "running_now": 0, "tasks_run": 2,
         "headline": headline("Done."), "summary": headline("Done.", 200), "waiting_on_you": False,
         "decisions_waiting": 0, "total_wait_seconds": 0, "waits_as_of": now, "full_text": "Done.",
         "full_text_ts": now - 5000, "text_source": "transcript", "note": ""},
    ]

    def item(i, lane, owner, yellow=False, text=None, since=None):
        return {"id": f"i{i}", "lane": lane, "owner_lane": owner, "bucket": "ear" if yellow else "decision",
                "needs": "listen" if yellow else "decide", "yellow": yellow,
                "text": text or f"Item {i}: a question from the {lane} lane that needs him. " * 2,
                "waiting_since": since if since is not None else now - 3600 * i, "waited_seconds": 3600 * i,
                "wait_at_least": False, "may_be_settled": i == 2, "settled_reason": "you wrote to EQ 19:26" if i == 2 else ""}

    items = [item(1, "stack", "coordinator"), item(2, "clip", "clip", True), item(3, "eq", "eq"),
             item(4, "eq", "eq", True), item(5, "sampler", "sampler"), item(6, "midi", "midi"),
             item(7, "level", "level"), item(8, "midi", "midi")]
    items += [item(k, "comp", "coordinator" if k >= 19 else "comp") for k in range(9, 21)]   # enough below, so the list can keep its place
    unjust = [{"key": "u000000001", "lane": "eq", "field": "next", "text": "WAITING ON MASON: say go \u2014 now"},
              {"key": "u000000002", "lane": "clip", "field": "blocked", "text": "WAITING ON MASON: pick the knob"},
              {"key": "u000000003", "lane": "sampler", "field": "next", "text": "WAITING ON MASON: " + "a long line " * 30}]
    wfull = {"ok": True, "total": 8, "counts": {"decision": 6, "ear": 2}, "sha": "planted", "items": items,
             "as_of": now, "may_be_settled_count": 1, "unjustified": unjust, "unjustified_total": 3}

    class Fake:
        def __init__(self):
            self.calls = []
            self.denied = None
            self.resolved = {"i3": "answered in chat \u2014 on 9 Sep"}
            self.msg_result = {"state": "held", "reason": "the window shows a permission question",
                               "outbox_id": "ob1", "ledger_error": ""}
            self.reply_state, self.reply_ledger_error = "delivered", ""     # controls 25 and 26
            self.on_check, self.delay = None, 0.0                           # controls 25 and 27
            self.active = self.peak = 0
            self.lock = threading.Lock()

        def check_resolved(self, it):
            with self.lock:
                self.active += 1
                self.peak = max(self.peak, self.active)
            try:
                self.calls.append(("check", it["id"]))
                if self.on_check is not None:
                    self.on_check(it)
                if self.delay:
                    time.sleep(self.delay)
                if it["id"] in self.resolved:
                    return True, self.resolved[it["id"]], "Claude Haiku 4.5"
                return False, "", "Claude Haiku 4.5"
            finally:
                with self.lock:
                    self.active -= 1

        def reply(self, its, text):
            self.calls.append(("reply", [i["id"] for i in its], text))
            return [{"state": self.reply_state, "reason": "delivered" if self.reply_state == "delivered" else "planted failure",
                     "items": [i["id"] for i in its], "label": "Clip", "lane": "clip", "note": "", "outbox_id": "x",
                     "ledger_error": self.reply_ledger_error}]

        def message_coordinator(self, text):
            self.calls.append(("msg", text))
            return dict(self.msg_result)

        def rename(self, ws, title):
            self.calls.append(("rename", ws, title))
            return {"ok": True, "message": f"Renamed to {title}."}

        def clear_name(self, ws):
            self.calls.append(("clear", ws))
            return {"ok": True, "message": "cleared"}

        def work_together(self, g):
            self.calls.append(("together", g.get("topic")))
            return {"state": "delivered", "reason": "delivered"}

        def cancel(self, oid):
            self.calls.append(("cancel", oid))
            return {"ok": True, "message": "Cancelled."}

        def windows(self):
            return {}

        def cmux_denied(self):
            return self.denied

        def _group_cache_path(self, sha):
            return os.path.join(tmp, f"groups-{sha}.json")

        def _enrich(self, groups, its):
            by = {i["id"]: i for i in its}
            out = []
            for g in groups:
                m = [x for x in g["members"] if x in by]
                out.append({"topic": g["topic"], "members": m, "items": [by[x] for x in m], "lead_lane": by[m[0]]["owner_lane"],
                            "lead_label": by[m[0]]["owner_lane"], "lead_by": "waiting longest",
                            "agents": [{"lane": by[x]["owner_lane"], "label": by[x]["owner_lane"]} for x in m]})
            return out

    fake = Fake()
    ctl = Controller.alloc().init()
    ctl.act, ctl.sync_bg = fake, True
    win = ctl.build_window(remember=True)
    win.setContentSize_(NSMakeSize(1240, 860))
    ctl.groups_raw = [{"topic": "Planted \u2014 topic", "members": ["i2", "i4"]}]
    ctl.group_done.add("planted")
    ctl.apply_top(rows, None, {"ok": True, "text": "Disk  78.1 GiB free  |  floor 30", "level": "normal"}, [], None, "10:00:00 PM")
    ctl.apply_waiting(wfull, None, "10:00:00 PM")
    win.contentView().layoutSubtreeIfNeeded()
    shown = []

    def cell(row_i, ident):
        ci = ctl.ctable.columnWithIdentifier_(ident)
        v = ctl.tableView_viewForTableColumn_row_(ctl.ctable, ctl.ctable.tableColumns()[ci], row_i)
        shown.append(v.plain())
        return v

    # 1 to 3: the Description cell, its tags, the accent
    d0, d1 = cell(0, "desc"), cell(1, "desc")
    check("Headline is the default and renders the formatting (bold markers gone)",
          ctl.view_mode == "headline" and d0.plain() == "Waiting on you: pick one." and d0.tag is None, d0.plain())
    check("a headline over its limit shows its first words and an 'over 50' tag, never a silent cut",
          d1.tag == "over 50" and d1.plain().startswith("A very long first line"), d1.plain())
    it_sum = NSMenuItem.alloc().init()
    it_sum.setTag_(1)
    ctl.viewMode_(it_sum)
    d1s = cell(1, "desc")
    check("View menu Summary (200) switches the column and tags an over-200 line", ctl.view_mode == "summary" and d1s.tag == "over 200", d1s.tag)
    it_sum.setTag_(0)
    ctl.viewMode_(it_sum)
    rv0, rv1 = ctl.tableView_rowViewForRow_(ctl.ctable, 0), ctl.tableView_rowViewForRow_(ctl.ctable, 1)
    check("a row whose headline starts 'Waiting on you:' carries the orange accent, others do not", rv0.accent and not rv1.accent)
    t3, r3 = cell(2, "time"), cell(2, "running")
    check("unknown numbers show '?', never 0", t3.plain() == "?" and r3.plain() == "?", f"{t3.plain()} {r3.plain()}")

    # 4: sorting, every option, arrows, header click reverses
    expect = {"sidebar": ["WORKFLOW", "Clip", "EQ", "Beta"], "time": ["Clip", "WORKFLOW", "Beta", "EQ"],
              "running": ["WORKFLOW", "Clip", "Beta", "EQ"], "tasks": ["Clip", "WORKFLOW", "Beta", "EQ"],
              "decisions": ["WORKFLOW", "Clip", "Beta", "EQ"], "wait": ["WORKFLOW", "Clip", "Beta", "EQ"],
              "recent": ["WORKFLOW", "Clip", "Beta", "EQ"], "alpha": ["Beta", "Clip", "EQ", "WORKFLOW"]}
    bad = []
    for key, _ in SORTS:
        ctl.set_sort(key, False)
        got = [r["title"] for r in ctl.rows]
        hv = ctl.ctable.headerView()
        arrow_ok = (hv.arrow is None) if key == "sidebar" else (hv.arrow in ("up", "down") and hv.arrow_col in COL_BY_ID)
        if got != expect[key] or not arrow_ok or ctl.sort_popup.titleOfSelectedItem() != SORT_TITLES[key]:
            bad.append((key, got, hv.arrow_col, hv.arrow))
    check("each of the 8 sort orders gives its order, unknowns last; the arrow marks a column (none for sidebar)", not bad, str(bad))
    ctl.set_sort("sidebar", False)
    tcol = ctl.ctable.tableColumnWithIdentifier_("time")
    ctl.tableView_didClickTableColumn_(ctl.ctable, tcol)
    first = ([r["title"] for r in ctl.rows], ctl.sort_reverse, ctl.ctable.headerView().arrow)
    ctl.tableView_didClickTableColumn_(ctl.ctable, tcol)
    second = ([r["title"] for r in ctl.rows], ctl.sort_reverse, ctl.ctable.headerView().arrow)
    check("a header click sorts by that column, a second click reverses it and flips the arrow",
          first == (["Clip", "WORKFLOW", "Beta", "EQ"], False, "down") and second == (["Beta", "WORKFLOW", "Clip", "EQ"], True, "up"),
          f"{first} then {second}")
    check("the sort choice is remembered", (read_prefs().get("v5") or {}).get("sort") == "time" and (read_prefs().get("v5") or {}).get("reverse") is True)
    ctl.set_sort("sidebar", False)

    # 5: ticking
    a0, a1 = time_cell_text(rows[0], now), time_cell_text(rows[0], now + 1)
    b0, b1 = time_cell_text(rows[1], now), time_cell_text(rows[1], now + 1)
    check("Time spent ticks one second a second while working and is frozen while waiting",
          a0 != a1 and a1.endswith(f"{(int(live_seconds(rows[0], now + 1)) % 60):02d} s") and b0 == b1, f"{a0} -> {a1}; {b0} -> {b1}")
    busy_after_end = dict(rows[0], working=True, ticking=False)
    c0, c1 = time_cell_text(busy_after_end, now), time_cell_text(busy_after_end, now + 1)
    check("Time spent is frozen while the registry says busy after a turn ended (that gap is never counted, "
          "so ticking there would be taken back)", c0 == c1, f"{c0} -> {c1}")
    check("Total wait ticks by the number of his items each second",
          round(total_wait_live(rows[0], now + 1) - total_wait_live(rows[0], now)) == 3)

    # 6: the optional columns, the header menu, remembered widths
    hidden = [str(c.identifier()) for c in ctl.ctable.tableColumns() if c.isHidden()]
    menu_titles = [str(i.title()) for i in ctl.header_menu.itemArray()]
    check("the two optional columns are hidden by default and are exactly the header menu's items",
          sorted(hidden) == sorted(OPTIONAL_COLUMNS) and menu_titles == ["Waiting on you", "Total wait"], f"{hidden} {menu_titles}")
    mi = ctl.header_menu.itemArray()[0]
    ctl.toggleColumn_(mi)
    ctl.ctable.tableColumnWithIdentifier_("title").setWidth_(251.0)
    ctl.ctable.moveColumn_toColumn_(ctl.ctable.columnWithIdentifier_("tasks"), 0)
    ctl.save_prefs()
    c2 = Controller.alloc().init()
    c2.act, c2.sync_bg = fake, True
    c2.build_window(remember=True)
    w2 = c2.ctable.tableColumnWithIdentifier_("title").width()
    order2 = [str(c.identifier()) for c in c2.ctable.tableColumns()]
    check("column width, order and a shown optional column are restored in a new window",
          abs(w2 - 251.0) < 0.6 and order2[0] == "tasks" and not c2.ctable.tableColumnWithIdentifier_("waiting").isHidden(),
          f"width {w2:.1f}, order {order2[:3]}")
    c2.window.setDelegate_(None)
    cw = cell(0, "waiting")
    check("the Waiting on you column shows the row's count", cw.plain() == "3", cw.plain())

    # 7: the waiting list
    head = str(ctl.list_head.plain())
    check("list header: '<total> waiting on you. <n> need more than a decision.'", head.startswith("8 waiting on you. 2 need more than a decision."), head)
    disp = ctl.display
    gi = disp.index(("g", "g:i2,i4"))
    check("a group header sits where its first member would, its members under it",
          disp[:4] == [("i", "i1"), ("g", "g:i2,i4"), ("i", "i2"), ("i", "i4")] and gi == 1, str(disp[:5]))
    col = ctl.item_text_attr(items[1]).attribute_atIndex_effectiveRange_(NSForegroundColorAttributeName, 0, None)[0]
    check("yellow text when the item needs more than a decision", col == YELLOW)
    meta = ctl.item_meta_text(items[0], now)
    check("each item shows its waiting time", "waiting 1 h 0 m" in meta, meta)
    ctl.wtable.selectAll_(None)
    sel = ctl.selected_item_ids()
    check("Select All selects items only, never a group header", len(sel) == len(items) and ctl.wtable.numberOfSelectedRows() == len(items), f"{len(sel)} of {len(items)}")
    prop = NSMutableIndexSet.indexSet()
    prop.addIndex_(0); prop.addIndex_(1); prop.addIndex_(2)
    out = ctl.tableView_selectionIndexesForProposedSelection_(ctl.wtable, prop)
    check("a click proposing a group header selects only the items", out.count() == 2 and not out.containsIndex_(1))
    ctl.wtable.deselectAll_(None)

    # 8: a manifest change removes rows above a half typed reply: draft, focus and place survive
    r6 = ctl.index[("i", "i6")]
    clip = ctl.wscroll.contentView()
    target_y = ctl.wtable.rectOfRow_(r6).origin.y - 40
    clip.scrollToPoint_(NSMakePoint(0, target_y))
    ctl.wscroll.reflectScrolledClipView_(clip)
    v6 = ctl.wtable.viewAtColumn_row_makeIfNecessary_(0, r6, True)
    f6 = v6.box.field
    win.makeFirstResponder_(f6)
    f6.setStringValue_("half typed")
    ctl.controlTextDidChange_(type("N", (), {"object": lambda self: f6})())
    off_before = ctl.wtable.rectOfRow_(ctl.index[("i", "i6")]).origin.y - clip.bounds().origin.y
    w_less = dict(wfull, items=[i for i in items if i["id"] not in ("i1", "i3")], sha="planted2", total=6)
    ctl.group_done.add("planted2")
    ctl.apply_waiting(w_less, None, "10:00:30 PM")
    off_after = ctl.wtable.rectOfRow_(ctl.index[("i", "i6")]).origin.y - clip.bounds().origin.y
    v6b = ctl.wtable.viewAtColumn_row_makeIfNecessary_(0, ctl.index[("i", "i6")], False)
    check("rows removed above a half typed reply: same field, still being typed in, draft kept, place kept",
          v6b is v6 and f6.currentEditor() is not None and ctl.state("i6").draft == "half typed" and abs(off_after - off_before) < 1.0,
          f"offset {off_before:.1f} -> {off_after:.1f}, editing {f6.currentEditor() is not None}, draft {ctl.state('i6').draft!r}")
    # 8b: real key events through the field editor: Shift-Return makes a new line, Return sends
    def real_key(field, mods):
        ev = NSEvent.keyEventWithType_location_modifierFlags_timestamp_windowNumber_context_characters_charactersIgnoringModifiers_isARepeat_keyCode_(
            10, NSMakePoint(0, 0), mods, 0, win.windowNumber(), None, "\r", "\r", False, KEY_RETURN)
        NSApp.postEvent_atStart_(ev, True)
        got = NSApp.nextEventMatchingMask_untilDate_inMode_dequeue_(0xFFFFFFFFFFFFFFFF, NSDate.dateWithTimeIntervalSinceNow_(0.5),
                                                                    "kCFRunLoopDefaultMode", True)
        if field.currentEditor() is not None:
            field.currentEditor().keyDown_(got)
        return got
    fake.calls.clear()
    r6 = ctl.index[("i", "i6")]
    row_h1 = ctl.wtable.rectOfRow_(r6).size.height
    f6.setStringValue_("")
    ctl.state("i6").draft = ""
    win.makeFirstResponder_(f6)
    f6.currentEditor().insertText_("line one")
    ctl.controlTextDidChange_(type("N", (), {"object": lambda self: f6})())
    got = real_key(f6, NSEventModifierFlagShift)
    if f6.currentEditor() is not None:
        f6.currentEditor().insertText_("line two")
    ctl.controlTextDidChange_(type("N", (), {"object": lambda self: f6})())
    row_h2 = ctl.wtable.rectOfRow_(ctl.index[("i", "i6")]).size.height
    check("a real Shift-Return in a reply field: a new line in his words, nothing sent, the row grows",
          str(f6.stringValue()) == "line one\nline two" and not fake.calls and row_h2 > row_h1
          and NSApp.currentEvent() is got,
          f"{str(f6.stringValue())!r} calls {fake.calls} row {row_h1:.0f} -> {row_h2:.0f}")
    real_key(f6, 0)
    check("a real Return in the same field: sends both lines, once",
          [c for c in fake.calls if c[0] == "reply"] == [("reply", ["i6"], "line one\nline two")], str(fake.calls))
    win.makeFirstResponder_(None)
    ctl.state("i6").draft = ""
    ctl.state("i6").status = None
    ctl.apply_waiting(wfull, None, "10:01:00 PM")

    # 9: one reply: OPEN delivers; RESOLVED shows the card; Escape, E and Return on the card
    fake.calls.clear()
    ctl.submit_item("i1", "hello")
    check("Return on an OPEN item: checked, then delivered once with his words",
          fake.calls == [("check", "i1"), ("reply", ["i1"], "hello")] and ctl.state("i1").status[0].startswith("Sent to"),
          str(fake.calls))
    fake.calls.clear()
    ctl.submit_item("i3", "hi")
    st3 = ctl.state("i3")
    check("Return on a RESOLVED item: the card, nothing sent; its reason at most 50 characters, no em dash",
          st3.phase == "card" and not [c for c in fake.calls if c[0] == "reply"] and "\u2014" not in one_line(st3.card["rows"][0][1]),
          str(st3.card["rows"][0][:2]))
    v3 = ctl.wtable.viewAtColumn_row_makeIfNecessary_(0, ctl.index[("i", "i3")], True)
    lay = card_layout(st3.card, 600)
    shown += [str(lay["title"][0].string()), str(lay["reason"][0].string()), str(lay["checked"][0].string())]
    check("the card reads 'Already resolved', the reason, 'checked by Claude Haiku 4.5 just now', three pills",
          str(lay["title"][0].string()) == "Already resolved" and str(lay["checked"][0].string()) == "checked by Claude Haiku 4.5 just now"
          and [p[1] for p in lay["pills"]] == ["Send anyway", "Don't send", "Edit"], str(lay["checked"][0].string()))

    def key(card, ch, code):
        ev = NSEvent.keyEventWithType_location_modifierFlags_timestamp_windowNumber_context_characters_charactersIgnoringModifiers_isARepeat_keyCode_(
            10, NSMakePoint(0, 0), 0, 0, win.windowNumber(), None, ch, ch, False, code)
        card.keyDown_(ev)
    key(v3.card, "\x1b", KEY_ESCAPE)
    check("Escape on the card: Don't send", st3.phase is None and st3.status[0].startswith("Not sent") and not [c for c in fake.calls if c[0] == "reply"])
    ctl.submit_item("i3", "hi")
    v3 = ctl.wtable.viewAtColumn_row_makeIfNecessary_(0, ctl.index[("i", "i3")], True)
    key(v3.card, "e", 14)
    fe = v3.box.field.currentEditor()
    check("E on the card: his text back in the field, the cursor at the end",
          st3.phase is None and str(v3.box.field.stringValue()) == "hi" and fe is not None and tuple(fe.selectedRange()) == (2, 0),
          f"{str(v3.box.field.stringValue())!r} {tuple(fe.selectedRange()) if fe is not None else None}")
    win.makeFirstResponder_(None)
    st3.draft = ""
    ctl.submit_item("i3", "hi again")
    v3 = ctl.wtable.viewAtColumn_row_makeIfNecessary_(0, ctl.index[("i", "i3")], True)
    key(v3.card, "\r", KEY_RETURN)
    check("Return on the card: Send anyway, once", fake.calls[-1] == ("reply", ["i3"], "hi again"), str(fake.calls[-1]))

    # 10: Reduce Motion, both branches
    ctl.reduce_override = True
    ctl.submit_item("i3", "motion")
    m_reduced = ctl.last_card_motion
    ctl.card_action(("item", "i3"), "dont")
    ctl.reduce_override = False
    ctl.submit_item("i3", "motion")
    m_normal = ctl.last_card_motion
    ctl.card_action(("item", "i3"), "dont")
    ctl.reduce_override = None
    check("the card slides 0.18 s normally and does not move at all with Reduce Motion",
          m_reduced == (0.0, False) and m_normal == (0.18, True), f"{m_reduced} {m_normal}")

    # 11: several at once
    fake.calls.clear()
    idx = NSMutableIndexSet.indexSet()
    for i in ("i1", "i3", "i4"):
        idx.addIndex_(ctl.index[("i", i)])
    ctl.wtable.selectRowIndexes_byExtendingSelection_(idx, False)
    ctl.layout_bottom()
    dock_shown = not ctl.dockv.isHidden() and "Reply to 3 items" in ctl.dock_label.plain()
    ctl.submit_dock("one answer")
    replies = [c for c in fake.calls if c[0] == "reply"]
    check("three selected: 'Reply to 3 items' docks; the open two go at once in one call; ONE card lists the resolved one",
          dock_shown and replies == [("reply", ["i1", "i4"], "one answer")] and [r[0] for r in ctl.dock["card"]["rows"]] == ["i3"],
          f"{replies} {ctl.dock['card'] and [r[0] for r in ctl.dock['card']['rows']]}")
    ctl.card_action(("dock",), "send")
    check("Send anyway on that card sends to the resolved one only", fake.calls[-1] == ("reply", ["i3"], "one answer"), str(fake.calls[-1]))
    ctl.wtable.deselectAll_(None)

    # 11b: an item held in the outbox shows "waiting to deliver" and Cancel; the checkbox selects
    fake.calls.clear()
    ctl.apply_outbox([{"id": "e1", "kind": "reply", "items": ["i5"], "state": "waiting", "label": "Sampler",
                       "reason": "the window shows a menu"}], [])
    s5 = ctl.item_status("i5")
    v5 = ctl.wtable.viewAtColumn_row_makeIfNecessary_(0, ctl.index[("i", "i5")], True)
    v5.layout_now()
    cancel_shown = not v5.cancel.isHidden() and v5.cancel.entry_id == "e1"
    ctl.cancelOutbox_(v5.cancel)
    check("an item held by the guard shows 'waiting to deliver' with the reason and Cancel; Cancel cancels it",
          s5 is not None and s5[0].startswith("Waiting to deliver to the Sampler window: the window shows a menu") and s5[2] == "e1"
          and cancel_shown and fake.calls == [("cancel", "e1")] and ctl.state("i5").status[0].startswith("Cancelled"),
          f"{s5} {fake.calls}")
    ctl.apply_outbox([], [])
    v7 = ctl.wtable.viewAtColumn_row_makeIfNecessary_(0, ctl.index[("i", "i7")], True)
    v8 = ctl.wtable.viewAtColumn_row_makeIfNecessary_(0, ctl.index[("i", "i8")], True)
    ctl.itemCheck_(v7.check)
    ctl.itemCheck_(v8.check)
    two = ctl.selected_item_ids()
    ctl.layout_bottom()
    docked = not ctl.dockv.isHidden() and "Reply to 2 items" in ctl.dock_label.plain()
    ctl.itemCheck_(v7.check)
    check("the checkbox on each item adds it to the selection and takes it out again; two checked dock 'Reply to 2 items'",
          sorted(two) == ["i7", "i8"] and docked and ctl.selected_item_ids() == ["i8"], f"{two} then {ctl.selected_item_ids()}")
    ctl.wtable.deselectAll_(None)
    ctl.layout_bottom()

    # 12: renaming: test mode redirects, an empty name is refused, Escape cancels
    TEST_WS, TEST_MODE = "11111111-2222-4333-8444-555555555555", True
    try:
        tgt = [ctl.rename_target(r)[0] for r in rows]
        check("in test mode every row's rename goes to the scratch window", set(tgt) == {TEST_WS}, str(set(tgt)))
        fake.calls.clear()
        ctl.begin_rename(0)
        ctl.renaming["field"].setStringValue_("   ")
        ctl.control_textView_doCommandBySelector_(ctl.renaming["field"], None, "insertNewline:")
        refused = ctl.renaming is not None and not fake.calls
        ctl.control_textView_doCommandBySelector_(ctl.renaming["field"], None, "cancelOperation:")
        check("an empty name is refused (nothing sent) and Escape cancels the edit", refused and ctl.renaming is None and not fake.calls)
        ctl.begin_rename(0)
        ctl.renaming["field"].setStringValue_("New name")
        ctl.control_textView_doCommandBySelector_(ctl.renaming["field"], None, "insertNewline:")
        check("Return renames through monitor_actions.rename", fake.calls == [("rename", TEST_WS, "New name")], str(fake.calls))
        fake.calls.clear()
        ctl.clear_name_row(1)
        check("Clear name in the row menu runs monitor_actions.clear_name on the scratch window in test mode",
              fake.calls == [("clear", TEST_WS)], str(fake.calls))
    finally:
        TEST_WS, TEST_MODE = None, False

    # 13: the message bar keeps his text until delivery is confirmed
    fake.calls.clear()
    ctl.msg_box.field.setStringValue_("to the coordinator")
    ctl.submit_msg("to the coordinator")
    held = str(ctl.msg_box.field.stringValue()) == "to the coordinator" and not ctl.msg_box.field.isEditable() \
        and ctl.msg_status_text()[0].startswith("Waiting to deliver")
    ctl.apply_outbox([], [{"id": "ob1", "state": "delivered", "kind": "coordinator", "items": []}])
    check("message bar: held keeps the text (and shows waiting to deliver); delivered clears it",
          held and str(ctl.msg_box.field.stringValue()) == "" and ctl.msg_box.field.isEditable(), str(ctl.msg["status"]))

    # 14: the group button
    fake.calls.clear()
    btn = GroupButton.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 10))
    btn.gkey = "g:i2,i4"
    ctl.workTogether_(btn)
    check("Work it out together sends one request and says so on the header",
          fake.calls == [("together", "Planted \u2014 topic")] and ctl.group_status["g:i2,i4"][1] == "ok")

    # 15: hover content
    got = []

    class FakeHover:
        def show(self, key, html, view, rect, sticky=False):
            got.append((key, html))
        def is_shown(self):
            return False
    real_hover = ctl.hover
    ctl.hover = FakeHover()
    ctl.open_hover(("conv", "ttys001"))
    ctl.open_hover(("conv", "ttys002"))

    class ShownHover(FakeHover):
        closed = 0
        def is_shown(self):
            return True
        def close(self):
            ShownHover.closed += 1
    esc = NSEvent.keyEventWithType_location_modifierFlags_timestamp_windowNumber_context_characters_charactersIgnoringModifiers_isARepeat_keyCode_(
        10, NSMakePoint(0, 0), 0, 0, win.windowNumber(), None, "\x1b", "\x1b", False, KEY_ESCAPE)
    ctl.hover = ShownHover()
    eaten = ctl.esc_handler(esc)
    ctl.hover = FakeHover()
    passed = ctl.esc_handler(esc)
    ctl.hover = real_hover
    check("Escape closes an open hover panel first (the key goes no further); with none open it passes on to the card or field",
          eaten is None and ShownHover.closed == 1 and passed is esc)
    h1, h2 = got[0][1], got[1][1]
    check("hover: the whole message, meta '<conversation>, written <age> ago', CSP with no scripts",
          "WORKFLOW, written 1 min ago" in h1 and "script-src &#x27;none&#x27;" in h1 and "<script" not in h1 and "<li>" in h1,
          h1[h1.find("Content-Security"):h1.find("Content-Security") + 90])
    check("hover of a row whose text came from its lane status says so", "Clip, from its lane status file" in h2)

    # 16: storage strip and its hover text
    store = {"ok": True, "free_gib": 35.2, "floor_gib": 30.0, "level": "orange", "after_running_gib": 33.0,
             "declared_remaining_gib": 2.2, "volume": "/System/Volumes/Data", "no_running_work_declares_disk": False,
             "text": "Disk  35.2 GiB free  |  floor 30  |  after running work  about 33.0 GiB, an estimate",
             "trend_text": "falling 0.3 GiB an hour", "trend_samples": 12,
             "runs": [{"name": "bench sweep", "lane": "clip", "pid_alive": True, "declared_gib": 3.0, "used_gib": 0.8,
                       "hours_left": 1.5, "reading": ""}],
             "time_machine": {"running": True, "phase": "Copying", "percent": 45.0}}
    ctl.apply_storage(store)
    md_s = ctl.storage_markdown()
    col = ctl.storage_strip.text_attr.attribute_atIndex_effectiveRange_(NSForegroundColorAttributeName, 0, None)[0]
    check("storage strip in the orange accent from 30 to 40 GiB, with the trend",
          col == ORANGE and "falling 0.3 GiB an hour" in ctl.storage_strip.plain(), ctl.storage_strip.plain())
    check("storage hover lists each running run (name, lane, declared GiB, hours left) and Time Machine",
          "| bench sweep | clip | 3.0 GiB | 0.80 GiB | 1.5 h |" in md_s and "running, phase Copying, 45 percent" in md_s
          and "an estimate" in md_s)

    # 17: alarms
    ctl.apply_alarms([{"id": "a1", "from": "clip", "why": "the disk is filling \u2014 help", "when": "Thu 10 Sep 9:00 PM",
                       "acks": ["eq"], "stale": False}], None)
    line = str(ctl.banner.lines[0][0].string())
    check("an open alarm shows as the banner: 'ALARM from <lane>: <why>', when, who answered",
          line.startswith("ALARM from clip: the disk is filling") and "answered by eq" in line and ctl.banner_height() > 0
          and "\u2014" not in line, line)
    got.clear()
    ctl.hover = FakeHover()
    ctl.alarm_clicked(0, NSMakeRect(0, 0, 10, 10))
    ctl.hover = real_hover
    ah = got[0][1] if got else ""
    check("a click on the alarm banner opens its full text in the hover panel: why, when, who answered",
          bool(got) and got[0][0][0] == "alarm" and "the disk is filling" in ah and "Thu 10 Sep 9:00 PM" in ah
          and "eq" in ah and "Answered by" in ah and "\u2014" not in ah, ah[ah.find("ALARM"):ah.find("ALARM") + 120])
    ctl.apply_alarms([], "ImportError: planted")
    check("an alarm list that cannot be read says so, never an empty banner", "could not be read" in str(ctl.banner.lines[0][0].string()))
    ctl.apply_alarms([], None)
    check("no open alarm: no banner", ctl.banner_height() == 0 and ctl.banner.isHidden())

    # 18: a first refresh that fails
    c4 = Controller.alloc().init()
    c4.act, c4.sync_bg = fake, True
    c4.build_window(remember=False)
    c4.apply_top(None, "RuntimeError: planted", None, [], None, "10:00:00 PM")
    check("a first refresh that fails says so in the table, never a blank table",
          not c4.empty_line.isHidden() and "could not be read: RuntimeError: planted" in c4.empty_line.plain())
    c4.window.setDelegate_(None)

    # 19: the Edit menu (Command-C, Command-V in every field) and the sort and view menus
    app = NSApplication.sharedApplication()
    build_menu(app, ctl)
    titles = [str(i.title()) for i in app.mainMenu().itemArray() if i.submenu() is not None]
    edit = [str(i.title()) for i in app.mainMenu().itemArray()[1].submenu().itemArray()]
    check("menu bar: Agents, Edit (Cut, Copy, Paste, Select All), View, Sort, Window",
          [str(i.submenu().title()) for i in app.mainMenu().itemArray()] == ["Agents", "Edit", "View", "Sort", "Window"]
          and {"Cut", "Copy", "Paste", "Select All"} <= set(edit))

    # 21: SPEC section 11, the card. Return presses the FOCUSED pill (Send anyway first), Tab and Shift-Tab
    # move the focus, and Don't send keeps his words in the field and in the cache as an unsent draft.
    # Sabotage: the old keys (Return always sends) planted back must make it fail.
    def card_run(words):
        fake.calls.clear()
        st = ctl.state("i3")
        st.draft, st.status = "", None
        ctl.submit_item("i3", words)
        v = ctl.wtable.viewAtColumn_row_makeIfNecessary_(0, ctl.index[("i", "i3")], True)
        f0 = v.card.focus
        key(v.card, "\t", KEY_TAB)
        f1 = v.card.focus
        key(v.card, "\r", KEY_RETURN)
        v.layout_now()
        return {"f0": f0, "f1": f1, "phase": st.phase, "draft": st.draft, "field": str(v.box.field.stringValue()),
                "editable": bool(v.box.field.isEditable()), "sent": [c for c in fake.calls if c[0] == "reply"],
                "saved": (read_drafts().get("items") or {}).get("i3", {}).get("text"),
                "status": (st.status or ("",))[0]}
    r21 = card_run("keep these words")
    ok21 = (r21["f0"] == 0 and r21["f1"] == 1 and r21["phase"] is None and r21["draft"] == "keep these words"
            and r21["field"] == "keep these words" and r21["editable"] and not r21["sent"] and r21["saved"] == "keep these words"
            and "unsent draft" in r21["status"])
    c5 = Controller.alloc().init()
    c5.act, c5.sync_bg = fake, True
    c5.build_window(remember=False)
    c5.group_done.add("planted")
    c5.apply_waiting(wfull, None, "10:02:00 PM")
    restored = c5.state("i3").draft
    c5.window.setDelegate_(None)
    win.makeFirstResponder_(None)
    ctl.state("i3").draft = ""
    ctl.submit_item("i3", "focus walk")
    v3 = ctl.wtable.viewAtColumn_row_makeIfNecessary_(0, ctl.index[("i", "i3")], True)
    walk = [v3.card.focus]
    for ch_, code_, shift_ in (("\t", KEY_TAB, False), ("\t", KEY_TAB, False), ("\t", KEY_TAB, False),
                               ("\t", KEY_TAB, True)):
        ev = NSEvent.keyEventWithType_location_modifierFlags_timestamp_windowNumber_context_characters_charactersIgnoringModifiers_isARepeat_keyCode_(
            10, NSMakePoint(0, 0), NSEventModifierFlagShift if shift_ else 0, 0, win.windowNumber(), None, ch_, ch_, False, code_)
        v3.card.keyDown_(ev)
        walk.append(v3.card.focus)
    key(v3.card, "\r", KEY_RETURN)                  # the walk ends on Edit: Return edits
    fe = v3.box.field.currentEditor()
    edit_ok = ctl.state("i3").phase is None and str(v3.box.field.stringValue()) == "focus walk" and fe is not None \
        and not [c for c in fake.calls if c[0] == "reply" and c[2] == "focus walk"]
    hints = [pill_hint(i, 1) for i in range(3)]
    win.makeFirstResponder_(None)
    ctl.state("i3").draft = ""
    real_keys = card_key_action

    def old_keys(code, ch, shift, cmd, focus):
        return ("act", "send") if code in (KEY_RETURN, KEY_ENTER) else real_keys(code, ch, shift, cmd, focus)
    globals()["card_key_action"] = old_keys
    try:
        sab21 = card_run("sabotaged words")
    finally:
        globals()["card_key_action"] = real_keys
    ctl.state("i3").draft, ctl.state("i3").status = "", None
    check("the card: Return presses the FOCUSED pill (Send anyway first); Tab, Tab, Tab wraps and Shift-Tab goes back; "
          "Don't send keeps his words in the field, editable, and saved as an unsent draft that a new window puts back; "
          "the Return hint sits on the focused pill; sabotage (Return always sends) makes it fail",
          ok21 and restored == "keep these words" and walk == [0, 1, 2, 0, 2] and edit_ok and hints == ["", "Return", "E"]
          and bool(sab21["sent"]),
          f"focus {r21['f0']} then {r21['f1']}, field {r21['field']!r}, saved {r21['saved']!r}, restored {restored!r}, "
          f"walk {walk}, edit {edit_ok}, hints {hints}, sabotaged Return sent {sab21['sent']}")

    # 22: SPEC section 11, the cmux banner. Hidden while cmux admits the app; the one plain banner, SPEC's words,
    # pushing the window down, once cmux refuses; a held reply shows the same reason. Sabotage: no banner text.
    def banner_run():
        fake.denied = None
        ctl.update_cmux_banner()
        h0, ya = ctl.notice.isHidden(), ctl.sortbar.frame().origin.y
        fake.denied = "cmux refused"
        ctl.update_cmux_banner()
        sh = (not ctl.notice.isHidden()) and ctl.notice.plain() == ("Open Agents from cmux's right sidebar (the Agents "
                                                                     "control) so replies and renames can reach your agents.")
        yb = ctl.sortbar.frame().origin.y
        return h0, sh, ya, yb
    hid0, shown22, y0, y1 = banner_run()
    ctl.apply_outbox([{"id": "e9", "kind": "reply", "items": ["i5"], "state": "waiting", "label": "Sampler",
                       "reason": CMUX_BANNER}], [])
    held22 = (ctl.item_status("i5") or ("",))[0]
    shown += [ctl.notice.plain(), held22]
    ctl.apply_outbox([], [])
    real_banner = cmux_banner_text
    globals()["cmux_banner_text"] = lambda reason: None
    try:
        sab22 = not banner_run()[1]
    finally:
        globals()["cmux_banner_text"] = real_banner
    fake.denied = None
    ctl.update_cmux_banner()
    check("cmux refuses the app: one plain banner with SPEC's words, the window below moves down for it, a held reply "
          "says why; hidden while cmux admits it; sabotage (no banner text) makes it fail",
          hid0 and shown22 and abs(y1 - y0 - NOTICE_H) < 0.5 and held22.endswith("so replies and renames can reach your agents.")
          and sab22 and ctl.notice.isHidden(),
          f"hidden before {hid0}, shown {shown22}, sort bar {y0:.0f} -> {y1:.0f}, held line {held22[:60]!r}, sabotaged hidden {sab22}")

    # 23: SPEC section 11, asks without a reason: a collapsed, dim, uncounted section at the foot of the list,
    # each with its lane; a click opens and closes it; never selectable. Sabotage: no rows for the section.
    tail0 = [k for k in ctl.display if k[0] == "u"]
    hv = ctl.tableView_viewForTableColumn_row_(ctl.wtable, ctl.wtable.tableColumns()[0], ctl.index[("u", "head")])
    head23 = hv.plain()
    last_is_head = ctl.display[-1] == ("u", "head")
    hv.mouseDown_(None)                             # what a click on the header calls
    tail1 = [k for k in ctl.display if k[0] == "u"]
    lines23 = [ctl.tableView_viewForTableColumn_row_(ctl.wtable, ctl.wtable.tableColumns()[0], ctl.index[k]).plain()
               for k in tail1[1:]]
    hts = [ctl.tableView_heightOfRow_(ctl.wtable, ctl.index[k]) for k in tail1]
    ctl.wtable.selectAll_(None)
    sel23 = ctl.selected_item_ids()
    nsel = ctl.wtable.numberOfSelectedRows()
    ctl.wtable.deselectAll_(None)
    open_head = ctl.tableView_viewForTableColumn_row_(ctl.wtable, ctl.wtable.tableColumns()[0], ctl.index[("u", "head")]).plain()
    shown += [head23] + lines23
    hv.mouseDown_(None)
    tail2 = [k for k in ctl.display if k[0] == "u"]
    list_head23 = str(ctl.list_head.plain())
    real_rows = unjust_rows
    globals()["unjust_rows"] = lambda u, o: []
    try:
        ctl.set_display(ctl.full_display(), set())
        sab23 = [k for k in ctl.display if k[0] == "u"]
    finally:
        globals()["unjust_rows"] = real_rows
        ctl.set_display(ctl.full_display(), set())
    check("asks without a reason: collapsed at the foot of the list, 'Asked of you without saying why (3)', dim; a click opens "
          "it, each with its lane; never selected, never in the header's count; sabotage (no section rows) makes it fail",
          tail0 == [("u", "head")] and last_is_head and head23.startswith("\u25b8  Asked of you without saying why (3)")
          and tail1 == [("u", "head"), ("u", "u000000001"), ("u", "u000000002"), ("u", "u000000003")]
          and lines23[0].startswith("Lane: eq") and "\u2014" not in lines23[0] and lines23[1].startswith("Lane: clip")
          and all(h > 0 for h in hts) and hts[3] > hts[2] and len(sel23) == nsel == len(items)
          and open_head.startswith("\u25be") and tail2 == [("u", "head")] and list_head23.startswith("8 waiting on you.")
          and sab23 == [],
          f"collapsed {tail0}, open {len(tail1) - 1} rows, first {lines23[0][:40]!r}, heights {[int(h) for h in hts]}, "
          f"Select All {nsel} of {len(items)} items, header {list_head23[:40]!r}, sabotaged rows {sab23}")
    hv_col = None

    # 24: SPEC section 11, test mode fails closed: the variable present at all, even empty, is test mode; with no
    # scratch window named, a rename goes nowhere. Sabotage: the old rule (a value must be present) makes it fail.
    def modes(fn):
        return {k: fn(e) for k, e in (("absent", {}), ("empty", {TEST_VAR: ""}), ("spaces", {TEST_VAR: "   "}),
                                      ("id", {TEST_VAR: " ABC "}))}
    want24 = {"absent": (False, None), "empty": (True, None), "spaces": (True, None), "id": (True, "ABC")}
    got24 = modes(test_mode_from)
    sab24 = modes(lambda env: (bool((env.get(TEST_VAR) or "").strip()), (env.get(TEST_VAR) or "").strip() or None))
    TEST_WS, TEST_MODE = None, True
    try:
        fake.calls.clear()
        tgt24 = ctl.rename_target(rows[0])
        ctl.begin_rename(0)
        ctl.renaming["field"].setStringValue_("Should go nowhere")
        ctl.control_textView_doCommandBySelector_(ctl.renaming["field"], None, "insertNewline:")
        calls24 = list(fake.calls)
        foot24 = ctl.foot.plain()
        ctl.update_sort_ui()
        hint24 = ctl.hint.plain()
    finally:
        TEST_WS, TEST_MODE = None, False
        ctl.update_sort_ui()
        ctl.show_footer()
    check("test mode fails closed: AGENTS_TEST_WORKSPACE present but empty or spaces is test mode; a rename then goes "
          "nowhere and says why; sabotage (the old rule) makes it fail",
          got24 == want24 and sab24 != want24 and tgt24[0] is None and not calls24 and "Not renamed" in foot24
          and "every send and rename is refused" in hint24,
          f"{got24}; rename target {tgt24}; calls {calls24}; footer {foot24[-70:]!r}")

    # 25 to 28: REDESIGN-PLAN.md Phase 0 (SPEC section 0 item 17). Each is a planted case the old code fails; where
    # the old behaviour sits in one function it is planted back as sabotage and the control must then fail.
    win.makeFirstResponder_(None)
    ctl.wtable.deselectAll_(None)
    ctl.apply_waiting(wfull, None, "10:03:00 PM")
    ctl.layout_bottom()

    def p0_note(field):
        return type("N", (), {"object": lambda self: field})()

    def p0_field(iid):
        return ctl.wtable.viewAtColumn_row_makeIfNecessary_(0, ctl.index[("i", iid)], True).box.field

    def p0_select(ids_):
        ix = NSMutableIndexSet.indexSet()
        for i_ in ids_:
            ix.addIndex_(ctl.index[("i", i_)])
        ctl.wtable.selectRowIndexes_byExtendingSelection_(ix, False)
        ctl.layout_bottom()

    def p0_reset(ids_=()):
        for i_ in ids_:
            s_ = ctl.state(i_)
            s_.draft, s_.status, s_.phase, s_.card = "", None, None, None
            ctl.drop_draft(("item", i_))
            ctl.refresh_item(i_)
        ctl.dock.update(phase=None, card=None, status=None, draft="", iids=[])
        ctl.drop_draft(("dock",))
        ctl.dock_box.field.setStringValue_("")
        ctl.wtable.deselectAll_(None)
        ctl.layout_bottom()
        fake.reply_state, fake.reply_ledger_error, fake.on_check, fake.delay = "delivered", "", None, 0.0

    # 25: fix 1 (submit_item, submit_dock). His words stay in the draft and the field while the already-resolved
    # check runs (the old code cleared both first) and after a send that fails; only a confirmed hand-off clears them.
    p0_reset(["i6", "i7", "i8"])
    fake.calls.clear()
    during25 = []
    fake.on_check = lambda it: during25.append((ctl.state(it["id"]).draft, str(p0_field(it["id"]).stringValue())))
    f25 = p0_field("i6")
    f25.setStringValue_("my words")
    ctl.controlTextDidChange_(p0_note(f25))
    fake.reply_state = "failed"
    ctl.submit_item("i6", "my words")
    failed25 = (ctl.state("i6").draft, str(p0_field("i6").stringValue()), (ctl.state("i6").status or ("", ""))[1])
    fake.reply_state = "delivered"
    ctl.submit_item("i6", "my words")
    sent25 = (ctl.state("i6").draft, str(p0_field("i6").stringValue()), (ctl.state("i6").status or ("", ""))[1])
    p0_reset(["i6"])
    dock_during25 = []
    fake.on_check = lambda it: dock_during25.append(ctl.dock["draft"])     # a worker thread: plain Python state only
    p0_select(["i7", "i8"])
    ctl.dock_box.field.setStringValue_("both of you")
    ctl.controlTextDidChange_(p0_note(ctl.dock_box.field))
    fake.reply_state = "refused"
    ctl.submit_dock("both of you")
    ctl.layout_bottom()
    dock_failed25 = (ctl.dock["draft"], str(ctl.dock_box.field.stringValue()), (ctl.dock_status_text() or ("", ""))[1])
    fake.reply_state = "delivered"
    ctl.submit_dock("both of you")
    ctl.layout_bottom()
    dock_sent25 = (ctl.dock["draft"], str(ctl.dock_box.field.stringValue()))
    replies25 = [c for c in fake.calls if c[0] == "reply"]
    p0_reset(["i6", "i7", "i8"])
    check("fix 1: his words stay in the draft and the field while the resolved check runs and after a failed or refused "
          "send, for one item and for several at once; a confirmed hand-off clears them",
          during25 == [("my words", "my words"), ("my words", "my words")] and failed25 == ("my words", "my words", "error")
          and sent25 == ("", "", "ok") and dock_during25 == ["both of you"] * 4
          and dock_failed25 == ("both of you", "both of you", "error") and dock_sent25 == ("", "") and len(replies25) == 4,
          f"during {during25}, failed {failed25}, sent {sent25}, dock during {dock_during25}, dock failed {dock_failed25}, "
          f"dock sent {dock_sent25}, {len(replies25)} replies")

    # 26: fix 2 (after_send). A reply whose result carries ledger_error: a warning on that item (and the dock) in the
    # error colour, and his words kept. Sabotage: the old after_send, which ignored ledger_error.
    ledger26 = "his words could not be written to the ANSWERS ledger (planted: No space left on device)"

    def run26():
        p0_reset(["i6", "i7", "i8"])
        fake.reply_ledger_error = ledger26
        f_ = p0_field("i6")
        f_.setStringValue_("record me")
        ctl.controlTextDidChange_(p0_note(f_))
        ctl.submit_item("i6", "record me")
        s_item = ctl.item_status("i6") or ("", "", None)
        kept_item = (ctl.state("i6").draft, str(p0_field("i6").stringValue()))
        p0_select(["i7", "i8"])
        fake.reply_ledger_error = ledger26
        ctl.dock_box.field.setStringValue_("record both")
        ctl.controlTextDidChange_(p0_note(ctl.dock_box.field))
        ctl.submit_dock("record both")
        ctl.layout_bottom()
        s_dock = ctl.dock_status_text() or ("", "")
        kept_dock = (ctl.dock["draft"], str(ctl.dock_box.field.stringValue()))
        s7 = ctl.item_status("i7") or ("", "", None)
        out_ = {"item": s_item[:2], "kept_item": kept_item, "dock": tuple(s_dock[:2]), "kept_dock": kept_dock, "i7": s7[:2]}
        p0_reset(["i6", "i7", "i8"])
        return out_

    def ok26(r_):
        return (r_["item"][1] == "error" and r_["item"][0].startswith("Sent to the Clip window") and ledger26 in r_["item"][0]
                and "Your words stay in the field." in r_["item"][0] and r_["kept_item"] == ("record me", "record me")
                and r_["dock"][1] == "error" and ledger26 in r_["dock"][0] and r_["kept_dock"] == ("record both", "record both")
                and r_["i7"][1] == "error" and ledger26 in r_["i7"][0] and STATUS_COLORS["error"] == RED)
    r26 = run26()
    shown += [r26["item"][0], r26["dock"][0], r26["i7"][0]]
    real_handoff = reply_handoff
    globals()["reply_handoff"] = lambda res: ((res or {}).get("state") in ("delivered", "held"), "")
    try:
        sab26 = run26()
    finally:
        globals()["reply_handoff"] = real_handoff
    check("fix 2: a ledger_error on a reply result shows a warning on that item and the dock in the red error colour and "
          "keeps his words; sabotage (ledger_error ignored) makes it fail",
          ok26(r26) and not ok26(sab26), f"item {r26['item']}, kept {r26['kept_item']}, dock {r26['dock'][1]}, "
          f"sabotaged item {sab26['item']}, sabotaged kept {sab26['kept_item']}")

    # 27: fix 3 (submit_dock). Six items at once: at most CHECK_AT_ONCE checks run at one time from one queue, every
    # item checked once, results paired with their own item. Sabotage: the old one thread per item.
    ids27 = ["i1", "i3", "i4", "i5", "i6", "i7"]

    def run27():
        p0_reset(ids27)
        fake.calls.clear()
        fake.peak, fake.delay = 0, 0.06
        p0_select(ids27)
        ctl.submit_dock("six at once")
        out_ = {"peak": fake.peak, "checks": sorted(c[1] for c in fake.calls if c[0] == "check"),
                "replies": [c for c in fake.calls if c[0] == "reply"],
                "card": [(r_[0], r_[1]) for r_ in (ctl.dock["card"] or {}).get("rows", [])]}
        p0_reset(ids27)
        return out_
    r27 = run27()
    scrambled = check_items(lambda k: (time.sleep(0.004 * (8 - k)), ("r", k))[1], list(range(8)))
    raised = check_items(lambda k: 1 / 0, [1])

    def old_check_all(check_, items_, limit=None):
        out_ = [None] * len(items_)

        def one(k):
            out_[k] = check_(items_[k])
        ts_ = [threading.Thread(target=one, args=(k,), daemon=True) for k in range(len(items_))]
        for t_ in ts_:
            t_.start()
        for t_ in ts_:
            t_.join()
        return out_
    real_check_items = check_items
    globals()["check_items"] = old_check_all
    try:
        sab27 = run27()
    finally:
        globals()["check_items"] = real_check_items
    check("fix 3: answering 6 at once runs at most 2 checks at a time from one queue, each item once, each result "
          "paired with its own item (finishing order scrambled); sabotage (one thread per item) makes it fail",
          CHECK_AT_ONCE == 2 and 1 <= r27["peak"] <= CHECK_AT_ONCE and r27["checks"] == sorted(ids27)
          and r27["replies"] == [("reply", ["i1", "i4", "i5", "i6", "i7"], "six at once")]
          and r27["card"] == [("i3", fake.resolved["i3"])] and scrambled == [("r", k) for k in range(8)]
          and raised == [(False, "the check failed, treated as open", "the app")] and sab27["peak"] > CHECK_AT_ONCE,
          f"peak {r27['peak']}, checks {len(r27['checks'])}, replies {r27['replies']}, card {r27['card']}, "
          f"sabotaged peak {sab27['peak']}")

    # 28: fix 4 (the Waiting on you cell). The count comes from the list's items for that lane, not the number the
    # row carries; "?" when it cannot be known; red on the engine's mismatch flag; it follows a new list without a
    # new table refresh; the sort reads the same count. Sabotage: the rows' own numbers (the old cell).
    def p28_item(k, owner, session="", waited=600):
        return {"id": f"p{k}", "lane": owner, "owner_lane": owner, "owner_session": session, "bucket": "decision",
                "needs": "decide", "yellow": False, "text": f"Planted ask {k} for {owner}.", "waiting_since": now - waited,
                "waited_seconds": waited, "wait_at_least": False, "may_be_settled": False, "settled_reason": ""}
    items28 = ([p28_item(k, "level", waited=1000 * k) for k in range(1, 5)]
               + [p28_item(5, "clip", "s12"), p28_item(6, "coordinator"), p28_item(7, "coordinator")])

    def p28_row(title, tty, sid, lane, typed, **kw):
        return dict(rows[3], title=title, tty=tty, session_id=sid, lane=lane, decisions_waiting=typed, total_wait_seconds=0,
                    waits_as_of=now, waiting_on_you=False, **kw)
    rows28 = [p28_row("Leveller", "ttys010", "s10", "level", 0),
              p28_row("Clip helper", "ttys012", "s12", None, 0, waiting_mismatch={"reason": "planted row flag"}),
              p28_row("Unmatched", "ttys013", "s13", None, 0),
              p28_row("Beta lane", "ttys014", "s14", "beta", 0)]
    w28 = {"ok": True, "total": 7, "counts": {"decision": 7}, "sha": "p28", "items": items28, "as_of": now,
           "unjustified": [], "unjustified_total": 0, "waiting_mismatches": {"level": "its status file says 0, the list shows 4"}}
    names28 = ["Leveller", "Clip helper", "Unmatched", "Beta lane"]

    def run28():
        c6 = Controller.alloc().init()
        c6.act, c6.sync_bg = fake, True
        c6.build_window(remember=False)
        c6.group_done.update({"p28", "p28b"})
        c6.apply_top(rows28, None, None, [], None, "10:05:00 PM")

        def cell6(title):
            col_ = c6.ctable.tableColumns()[c6.ctable.columnWithIdentifier_("waiting")]
            return c6.tableView_viewForTableColumn_row_(c6.ctable, col_, [r_["title"] for r_ in c6.rows].index(title))

        def red6(title):
            v_ = cell6(title)
            return v_.text_attr.attribute_atIndex_effectiveRange_(NSForegroundColorAttributeName, 0, None)[0] == RED
        out_ = {"before": cell6("Leveller").plain()}
        c6.apply_waiting(w28, None, "10:05:01 PM")
        out_["got"] = [cell6(t).plain() for t in names28]
        out_["red"] = [red6(t) for t in names28]
        out_["tip_unknown"] = str(cell6("Unmatched").toolTip() or "")
        out_["tip_red"] = str(cell6("Leveller").toolTip() or "")
        out_["total"] = next(r_ for r_ in c6.rows if r_["title"] == "Leveller").get("total_wait_seconds")
        c6.sort_key = "decisions"
        c6.apply_rows()
        out_["order"] = [r_["title"] for r_ in c6.rows]
        c6.sort_key = "sidebar"
        c6.apply_rows()
        c6.apply_waiting(dict(w28, sha="p28b", total=5, items=[i_ for i_ in items28 if i_["id"] not in ("p1", "p2")]),
                         None, "10:05:31 PM")
        out_["fewer"] = cell6("Leveller").plain()
        c6.window.setDelegate_(None)
        return out_

    def ok28(r_):
        return (r_["before"] == "?" and r_["got"] == ["4", "1", "?", "0"] and r_["red"] == [True, True, False, False]
                and "no live owner" in r_["tip_unknown"] and "the list shows 4" in r_["tip_red"] and r_["total"] == 10000
                and r_["order"] == ["Leveller", "Clip helper", "Beta lane", "Unmatched"] and r_["fewer"] == "2")
    r28 = run28()
    shown += r28["got"] + [r28["tip_unknown"], r28["tip_red"]]
    real_count_rows = count_rows
    globals()["count_rows"] = lambda rows_, *a, **k: [dict(r_) for r_ in (rows_ or [])]
    try:
        sab28 = run28()
    finally:
        globals()["count_rows"] = real_count_rows
    check("fix 4: Waiting on you is counted from the list's items for the lane (4, not the row's 0), by session when "
          "there is no lane, '?' when unknowable, red on the engine's mismatch flag, follows a new list, sorts by the "
          "same count; sabotage (the row's own number) makes it fail",
          ok28(r28) and not ok28(sab28),
          f"before {r28['before']!r}, cells {r28['got']}, red {r28['red']}, total {r28['total']}, order {r28['order']}, "
          f"after fewer {r28['fewer']!r}; sabotaged cells {sab28['got']}")

    # 29: the second pass's loose ends B and C (15 Sep). The engine's per-row note survives count_rows and reaches
    # the tooltip; the app's own note is appended only when it adds a fact; the engine's mismatch_lanes key turns
    # the lane's row red with the engine's reason; a "?" cell's tooltip says what is shown and why, never that a
    # number was counted. Sabotage: the old count_rows (note overwritten), the old key list (mismatch_lanes unread),
    # the old tooltip (a "?" told it was counted).
    eng_ghost = ("its session is in no roster.json row, so no item of the list can reach this row, and 2 items on "
                 "the list have no live owner, so its count is not known")
    rows29 = [p28_row("Leveller", "ttys010", "s10", "level", 0, waiting_mismatch=True,
                      waiting_note="4 on the list, but its headline says 5"),
              p28_row("Ghost", "ttys013", "s13", None, 0, waiting_mismatch=False, waiting_note=eng_ghost),
              p28_row("Fresh", "ttys015", "s15", None, 0, waiting_mismatch=False, waiting_note=""),
              p28_row("Beta lane", "ttys014", "s14", "beta", 0, waiting_mismatch=False, waiting_note="")]
    w29 = {"ok": True, "total": 7, "counts": {"decision": 7}, "sha": "p29", "items": items28, "as_of": now,
           "unjustified": [], "unjustified_total": 0, "mismatch_lanes": ["beta"],
           "lanes": {"beta": {"items": 0, "typed": [{"where": "status headline", "said": 2, "words": "two asks"}],
                              "mismatch": True},
                     "level": {"items": 4, "typed": [], "mismatch": False}}}
    names29 = ["Leveller", "Ghost", "Fresh", "Beta lane"]

    def run29():
        c9 = Controller.alloc().init()
        c9.act, c9.sync_bg = fake, True
        c9.build_window(remember=False)
        c9.group_done.add("p29")
        c9.apply_top(rows29, None, None, [], None, "10:06:00 PM")
        c9.apply_waiting(w29, None, "10:06:01 PM")

        def cell9(title):
            col_ = c9.ctable.tableColumns()[c9.ctable.columnWithIdentifier_("waiting")]
            return c9.tableView_viewForTableColumn_row_(c9.ctable, col_, [r_["title"] for r_ in c9.rows].index(title))

        def red9(title):
            v_ = cell9(title)
            return v_.text_attr.attribute_atIndex_effectiveRange_(NSForegroundColorAttributeName, 0, None)[0] == RED
        out_ = {"cells": [cell9(t).plain() for t in names29], "red": [red9(t) for t in names29],
                "tips": {t: str(cell9(t).toolTip() or "") for t in names29},
                "notes": {r_["title"]: r_.get("waiting_note") or "" for r_ in c9.rows}}
        c9.window.setDelegate_(None)
        return out_

    def ok29(r_):
        t_ = r_["tips"]
        return (r_["cells"] == ["4", "?", "?", "0"] and r_["red"] == [True, False, False, True]
                and r_["notes"]["Leveller"] == "4 on the list, but its headline says 5"            # kept, not overwritten
                and r_["notes"]["Ghost"] == eng_ghost                                              # the app's adds nothing
                and r_["notes"]["Fresh"].startswith("this conversation is not matched to a lane")  # the app's, alone
                and "its headline says 5" in t_["Leveller"]                                        # the engine's reason on the red
                and "status headline says 2" in t_["Beta lane"] and "0 on the list" in t_["Beta lane"]
                and all(t_[n].startswith("Not known, shown as ?") for n in ("Ghost", "Fresh"))
                and not any("counted from the list" in t_[n] for n in ("Ghost", "Fresh"))
                and t_["Ghost"].count("no live owner") == 1 and "no roster.json row" in t_["Ghost"])
    r29 = run29()
    shown += r29["cells"] + list(r29["tips"].values()) + list(r29["notes"].values())
    sab29 = {}
    real_cr29 = count_rows

    def old_count_rows(rows_, *a, **k):                       # sabotage 1: the first pass, the app's note overwrites the engine's
        out_ = real_cr29(rows_, *a, **k)
        for r_ in out_:
            r_["waiting_note"] = r_["waiting_note_app"]
        return out_
    globals()["count_rows"] = old_count_rows
    try:
        sab29["note overwritten"] = run29()
    finally:
        globals()["count_rows"] = real_cr29
    real_keys29 = MISMATCH_LIST_KEYS
    globals()["MISMATCH_LIST_KEYS"] = tuple(k for k in real_keys29 if k != "mismatch_lanes")   # sabotage 2: the engine's key unread
    try:
        sab29["mismatch_lanes unread"] = run29()
    finally:
        globals()["MISMATCH_LIST_KEYS"] = real_keys29
    real_tip29 = waiting_tip
    globals()["waiting_tip"] = lambda n, red, why, note: (                                    # sabotage 3: the first pass's tooltip
        "The engine flags this lane's own count as not matching the waiting list. The number shown is counted from the list."
        if red else (one_line(note or "") or "Not known yet: the waiting list has not been read."))
    try:
        sab29["the old ? tooltip"] = run29()
    finally:
        globals()["waiting_tip"] = real_tip29
    failed29 = [k for k, s in sab29.items() if not ok29(s)]
    check("fix 5: the engine's row note is kept and reaches the tooltip, the app's note is added only when it adds a fact, "
          "the engine's mismatch_lanes key turns the lane red with the engine's reason, and a ? cell says what is shown "
          "and why; sabotage (note overwritten; mismatch_lanes unread; the old ? tooltip) makes it fail",
          ok29(r29) and len(failed29) == 3,
          f"cells {r29['cells']}, red {r29['red']}, Leveller tip {r29['tips']['Leveller']!r}, Ghost tip {r29['tips']['Ghost']!r}, "
          f"Beta tip {r29['tips']['Beta lane']!r}, Fresh note {r29['notes']['Fresh']!r}; sabotaged {failed29} fail")

    # 20: no em dash anywhere shown
    shown += [ctl.foot.plain(), ctl.list_head.plain(), ctl.storage_strip.plain()]
    shown += [ctl.item_meta_text(i, now) for i in items]
    shown += [st.status[0] for st in ctl.istates.values() if st.status]
    shown += [one_line(g.get("topic")) for g in ctl.groups]
    em = [x for x in shown if "\u2014" in x]
    check("no em dash in anything shown (planted em dashes in a headline, a reason, a topic, an alarm)", not em,
          f"{len(shown)} strings, {len(em)} with an em dash")
    src = open(os.path.abspath(__file__), encoding="utf-8").read()
    check("no em dash character in this file", "\u2014" not in src)
    win.setDelegate_(None)
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{sum(results)} of {len(results)} controls pass")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
